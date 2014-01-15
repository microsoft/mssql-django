from django.db.models.sql import compiler
                                            
from sql_server.pyodbc.compat import zip_longest


class SQLCompiler(compiler.SQLCompiler):

    def resolve_columns(self, row, fields=()):
        index_start = len(list(self.query.extra_select.keys()))
        values = [self.query.convert_values(v, None, connection=self.connection) for v in row[:index_start]]
        for value, field in zip_longest(row[index_start:], fields):
            if field:
                value = self.query.convert_values(value, field, connection=self.connection)
            values.append(value)
        return tuple(values)

    def as_sql(self, with_limits=True, with_col_aliases=False):
        """
        Creates the SQL for this query. Returns the SQL string and list of
        parameters.

        If 'with_limits' is False, any limit/offset information is not included
        in the query.
        """
        if with_limits and self.query.low_mark == self.query.high_mark:
            return '', ()

        self.pre_sql_setup()

        # The do_offset flag indicates whether we need to construct
        # the SQL needed to use limit/offset w/SQL Server.
        high_mark = self.query.high_mark
        low_mark = self.query.low_mark
        do_limit = with_limits and high_mark is not None
        do_offset = with_limits and low_mark != 0
        # SQL Server 2012 or newer supports OFFSET/FETCH clause
        supports_offset_clause = self.connection.ops.sql_server_ver >= 2012
        do_offset_emulation = do_offset and not supports_offset_clause

        # After executing the query, we must get rid of any joins the query
        # setup created. So, take note of alias counts before the query ran.
        # However we do not want to get rid of stuff done in pre_sql_setup(),
        # as the pre_sql_setup will modify query state in a way that forbids
        # another run of it.
        if self.connection._DJANGO_VERSION >= 14:
            self.refcounts_before = self.query.alias_refcount.copy()
        out_cols = self.get_columns(with_col_aliases or do_offset_emulation)
        ordering, ordering_group_by, offset_params = \
            self._get_ordering(out_cols, not do_offset_emulation)

        # This must come after 'select' and 'ordering' -- see docstring of
        # get_from_clause() for details.
        from_, f_params = self.get_from_clause()

        qn = self.quote_name_unless_alias

        where, w_params = self.query.where.as_sql(qn=qn, connection=self.connection)
        having, h_params = self.query.having.as_sql(qn=qn, connection=self.connection)
        params = []
        for val in self.query.extra_select.values():
            params.extend(val[1])

        result = ['SELECT']

        if self.query.distinct:
            result.append('DISTINCT')

        if do_offset:
            if not ordering:
                meta = self.query.get_meta()
                qn = self.quote_name_unless_alias
                pk = '%s.%s' % (qn(meta.db_table), qn(meta.pk.db_column or meta.pk.column))
                # Special case: pk not in out_cols, use random ordering.
                if not pk in out_cols:
                    ordering = [self.connection.ops.random_function_sql()]
                # XXX: Maybe use group_by field for ordering?
                #if self.group_by:
                    #ordering = ['%s.%s ASC' % (qn(self.group_by[0][0]),qn(self.group_by[0][1]))]
                else:
                    ordering = ['%s ASC' % pk]
            if do_offset_emulation:
                order = ', '.join(ordering)
                self.query.ordering_aliases.append('(ROW_NUMBER() OVER (ORDER BY %s)) AS [rn]' % order)
                ordering = self.connection.ops.force_no_ordering()
        elif do_limit:
            result.append('TOP %d' % high_mark)

        result.append(', '.join(out_cols + self.query.ordering_aliases))

        params.extend(offset_params)

        result.append('FROM')
        result.extend(from_)
        params.extend(f_params)

        if self.connection.features.has_select_for_update and self.query.select_for_update:
            # If we've been asked for a NOWAIT query but the backend does not support it,
            # raise a DatabaseError otherwise we could get an unexpected deadlock.
            nowait = self.query.select_for_update_nowait
            result.append(self.connection.ops.for_update_sql(nowait=nowait))

        if where:
            result.append('WHERE %s' % where)
            params.extend(w_params)

        if self.connection._DJANGO_VERSION >= 15:
            grouping, gb_params = self.get_grouping(ordering_group_by)
        else:
            grouping, gb_params = self.get_grouping()
            if grouping and ordering:
                # If the backend can't group by PK (i.e., any database
                # other than MySQL), then any fields mentioned in the
                # ordering clause needs to be in the group by clause.
                if not self.connection.features.allows_group_by_pk:
                    for col, col_params in ordering_group_by:
                        if col not in grouping:
                            grouping.append(str(col))
                            gb_params.extend(col_params)
        if grouping:
            if not ordering:
                ordering = self.connection.ops.force_no_ordering()
            result.append('GROUP BY %s' % ', '.join(grouping))
            params.extend(gb_params)

        if having:
            result.append('HAVING %s' % having)
            params.extend(h_params)

        if ordering and not with_col_aliases:
            result.append('ORDER BY %s' % ', '.join(ordering))
            if do_offset and not do_offset_emulation:
                result.append('OFFSET %d ROWS' % low_mark)
                if do_limit:
                    result.append('FETCH FIRST %d ROWS ONLY' % (high_mark - low_mark))

        if do_offset_emulation:
            # Construct the final SQL clause, using the initial select SQL
            # obtained above.
            result = ['SELECT * FROM (%s) AS X WHERE X.rn' % ' '.join(result)]
            # Place WHERE condition on `rn` for the desired range.
            if do_limit:
                result.append('BETWEEN %d AND %d' % (low_mark+1, high_mark))
            else:
                result.append('>= %d' % (low_mark+1))
            result.append('ORDER BY X.rn')

        # Finally do cleanup - get rid of the joins we created above.
        if self.connection._DJANGO_VERSION >= 14:
            self.query.reset_refcounts(self.refcounts_before)

        return ' '.join(result), tuple(params)

    def _get_ordering(self, out_cols, allow_aliases=True):
        # SQL Server doesn't support grouping by column number
        ordering, ordering_group_by = self.get_ordering()
        grouping = []
        for group_by in ordering_group_by:
            try:
                col_index = int(group_by[0]) - 1
                grouping.append((out_cols[col_index], group_by[1]))
            except ValueError:
                grouping.append(group_by)
        # value_expression in OVER clause cannot refer to
        # expressions or aliases in the select list. See:
        # http://msdn.microsoft.com/en-us/library/ms189461.aspx
        offset_params = []
        if not allow_aliases:
            keys = self.query.extra.keys()
            for i in range(len(ordering)):
                order_col, order_dir = ordering[i].split()
                order_col = order_col.strip('[]')
                if order_col in keys:
                    ex = self.query.extra[order_col]
                    ordering[i] = '%s %s' % (ex[0], order_dir)
                    offset_params.extend(ex[1])
        return ordering, grouping, offset_params

class SQLInsertCompiler(compiler.SQLInsertCompiler, SQLCompiler):

    def as_sql_legacy(self):
        # We don't need quote_name_unless_alias() here, since these are all
        # going to be column names (so we can avoid the extra overhead).
        qn = self.connection.ops.quote_name
        opts = self.query.model._meta
        returns_id = bool(self.return_id and
                          self.connection.features.can_return_id_from_insert)

        if returns_id:
            result = ['SET NOCOUNT ON']
        else:
            result = []

        result.append('INSERT INTO %s' % qn(opts.db_table))
        result.append('(%s)' % ', '.join([qn(c) for c in self.query.columns]))

        values = [self.placeholder(*v) for v in self.query.values]
        result.append('VALUES (%s)' % ', '.join(values))

        params = self.query.params
        sql = ' '.join(result)

        meta = self.query.get_meta()
        if meta.has_auto_field:
            # db_column is None if not explicitly specified by model field
            auto_field_column = meta.auto_field.db_column or meta.auto_field.column

            if auto_field_column in self.query.columns:
                quoted_table = self.connection.ops.quote_name(meta.db_table)

                if len(self.query.columns) == 1 and not params:
                    sql = ''
                    if returns_id:
                        sql = 'SET NOCOUNT ON '
                    sql += "INSERT INTO %s DEFAULT VALUES" % quoted_table
                else:
                    sql = "SET IDENTITY_INSERT %s ON;\n%s;\nSET IDENTITY_INSERT %s OFF" % \
                        (quoted_table, sql, quoted_table)

        if returns_id:
            sql += ';\nSELECT CAST(SCOPE_IDENTITY() AS BIGINT)'

        return sql, params

    def as_sql(self):
        if self.connection._DJANGO_VERSION < 14:
            return self.as_sql_legacy()

        can_return_id = self.connection.features.can_return_id_from_insert
        self.connection.features.can_return_id_from_insert = False

        items = super(SQLInsertCompiler, self).as_sql()

        self.connection.features.can_return_id_from_insert = can_return_id

        opts = self.query.model._meta
        returns_id = bool(self.return_id and
                          self.connection.features.can_return_id_from_insert)

        has_fields = bool(self.query.fields)
        if has_fields:
            fields = self.query.fields 
        else:
            fields = [opts.pk]
        columns = [f.column for f in fields]

        if returns_id:
            items = [['SET NOCOUNT ON ' + x[0], x[1]] for x in items]

        # This section deals with specifically setting the primary key,
        # or using default values if necessary
        meta = self.query.get_meta()
        if meta.has_auto_field:
            # db_column is None if not explicitly specified by model field
            auto_field_column = meta.auto_field.db_column or meta.auto_field.column

            out = []
            for sql, params in items:
                if auto_field_column in columns:
                    quoted_table = self.connection.ops.quote_name(meta.db_table)
                    if not has_fields:
                        # If there are no fields specified in the insert..
                        sql = ''
                        if returns_id:
                            sql = 'SET NOCOUNT ON '
                        sql += "INSERT INTO %s DEFAULT VALUES" % quoted_table
                    else:
                        sql = "SET IDENTITY_INSERT %s ON;\n%s;\nSET IDENTITY_INSERT %s OFF"% \
                            (quoted_table, sql, quoted_table)
                out.append([sql, params])
            items = out

        if returns_id:
            items = [[x[0] + ';\nSELECT CAST(SCOPE_IDENTITY() AS BIGINT)', x[1]] for x in items]

        return items


class SQLDeleteCompiler(compiler.SQLDeleteCompiler, SQLCompiler):
    pass

class SQLUpdateCompiler(compiler.SQLUpdateCompiler, SQLCompiler):
    def as_sql(self):
        sql, params = super(SQLUpdateCompiler, self).as_sql()
        if sql:
            sql = '; '.join(['SET NOCOUNT OFF', sql])
        return sql, params

class SQLAggregateCompiler(compiler.SQLAggregateCompiler, SQLCompiler):
    pass

class SQLDateCompiler(compiler.SQLDateCompiler, SQLCompiler):
    pass
