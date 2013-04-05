from django.db.models.sql import compiler
from django.db.models.sql.constants import SINGLE, MULTI
                                            
from sql_server.pyodbc.compat import zip_longest

REV_ODIR = {
    'ASC': 'DESC',
    'DESC': 'ASC'
}

# Strategies for handling limit+offset emulation:
USE_ROW_NUMBER = 0 # For SQL Server >= 2005


class SQLCompiler(compiler.SQLCompiler):
    
    def resolve_columns(self, row, fields=()):
        index_start = len(list(self.query.extra_select.keys()))
        values = [self.query.convert_values(v, None, connection=self.connection) for v in row[:index_start]]
        for value, field in zip_longest(row[index_start:], fields):
            values.append(self.query.convert_values(value, field, connection=self.connection))
        return tuple(values)

    def modify_query(self, strategy, ordering, out_cols):
        """
        Helper method, called from _as_sql()

        Sets the value of the self._ord and self.default_reverse_ordering
        attributes.
        Can modify the values of the out_cols list argument and the
        self.query.ordering_aliases attribute.
        """
        self.default_reverse_ordering = False
        self._ord = []
        cnt = 0
        extra_select_aliases = [k.strip('[]') for k in self.query.extra_select.keys()]
        for ord_spec_item in ordering:
            if ord_spec_item.endswith(' ASC') or ord_spec_item.endswith(' DESC'):
                parts = ord_spec_item.split()
                col, odir = ' '.join(parts[:-1]), parts[-1]
                if col not in self.query.ordering_aliases and col.strip('[]') not in extra_select_aliases:
                    if col.isdigit():
                        cnt += 1
                        n = int(col)-1
                        alias = 'OrdAlias%d' % cnt
                        # ordering by aliases defined in the same query is not available ...
                        self._ord.append((out_cols[n], odir))
                        out_cols[n] = '%s AS [%s]' % (out_cols[n], alias)
                    else:
                        self._ord.append((col, odir))
                else:
                    self._ord.append((col, odir))

        if not self._ord and 'RAND()' in ordering:
            self._ord.append(('RAND()',''))

    def _as_sql(self, strategy):
        """
        Helper method, called from as_sql()
        Similar to django/db/models/sql/query.py:Query.as_sql() but without
        the ordering and limits code.

        Returns SQL that hasn't an order-by clause.
        """
        # get_columns needs to be called before get_ordering to populate
        # _select_alias.
        out_cols = self.get_columns(True)
        ordering, ordering_group_by = self.get_ordering()
        if not ordering:
            meta = self.query.get_meta()
            qn = self.quote_name_unless_alias
            # Special case: pk not in out_cols, use random ordering. 
            #
            if '%s.%s' % (qn(meta.db_table), qn(meta.pk.db_column or meta.pk.column)) not in self.get_columns():
                ordering = ['RAND()']
                # XXX: Maybe use group_by field for ordering?
                #if self.group_by:
                    #ordering = ['%s.%s ASC' % (qn(self.group_by[0][0]),qn(self.group_by[0][1]))]
            else:
                ordering = ['%s.%s ASC' % (qn(meta.db_table), qn(meta.pk.db_column or meta.pk.column))]

        self.modify_query(strategy, ordering, out_cols)

        order = ', '.join(['%s %s' % pair for pair in self._ord])
        self.query.ordering_aliases.append('(ROW_NUMBER() OVER (ORDER BY %s)) AS [rn]' % order)

        # This must come after 'select' and 'ordering' -- see docstring of
        # get_from_clause() for details.
        from_, f_params = self.get_from_clause()

        qn = self.quote_name_unless_alias
        where, w_params = self.query.where.as_sql(qn, self.connection)
        having, h_params = self.query.having.as_sql(qn, self.connection)
        params = []
        for val in self.query.extra_select.values():
            params.extend(val[1])

        result = ['SELECT']
        if self.query.distinct:
            result.append('DISTINCT')

        result.append(', '.join(out_cols + self.query.ordering_aliases))

        result.append('FROM')
        result.extend(from_)
        params.extend(f_params)

        if where:
            result.append('WHERE %s' % where)
            params.extend(w_params)

        if self.connection._DJANGO_VERSION >= 15:
            grouping, gb_params = self.get_grouping(ordering_group_by)
        else:
            grouping, gb_params = self.get_grouping()
        if grouping:
            if ordering:
                # If the backend can't group by PK (i.e., any database
                # other than MySQL), then any fields mentioned in the
                # ordering clause needs to be in the group by clause.
                if not self.connection.features.allows_group_by_pk:
                    for col, col_params in ordering_group_by:
                        if col not in grouping:
                            grouping.append(str(col))
                            gb_params.extend(col_params)
            else:
                ordering = self.connection.ops.force_no_ordering()
            result.append('GROUP BY %s' % ', '.join(grouping))
            params.extend(gb_params)

        if having:
            result.append('HAVING %s' % having)
            params.extend(h_params)

        return ' '.join(result), tuple(params)

    def as_sql(self, with_limits=True, with_col_aliases=False):
        """
        Creates the SQL for this query. Returns the SQL string and list of
        parameters.

        If 'with_limits' is False, any limit/offset information is not included
        in the query.
        """
        if with_limits and self.query.low_mark == self.query.high_mark:
            return '', ()

        # The do_offset flag indicates whether we need to construct
        # the SQL needed to use limit/offset w/SQL Server.
        do_offset = with_limits and (self.query.high_mark is not None or self.query.low_mark != 0)
        
        # no row ordering or row offsetting is assumed to be required
        # if the result type is specified as SINGLE
        if hasattr(self, 'result_type') and self.result_type == SINGLE:
            do_offset = False

        # If no offsets, just return the result of the base class
        # `as_sql`.
        if not do_offset:
            return super(SQLCompiler, self).as_sql(with_limits=False,
                                                      with_col_aliases=with_col_aliases)
        # Shortcut for the corner case when high_mark value is 0:
        if self.query.high_mark == 0:
            return "", ()

        self.pre_sql_setup()

        # SQL Server 2005 or newer
        sql, params = self._as_sql(USE_ROW_NUMBER)
        
        # Construct the final SQL clause, using the initial select SQL
        # obtained above.
        result = ['SELECT * FROM (%s) AS X' % sql]

        # Place WHERE condition on `rn` for the desired range.
        if self.query.high_mark is None:
            self.query.high_mark = 9223372036854775807
        result.append('WHERE X.rn BETWEEN %d AND %d' % (self.query.low_mark+1, self.query.high_mark))

        return ' '.join(result), params

    def get_ordering(self):
        # SQL Server doesn't support grouping by column number
        ordering, ordering_group_by = super(SQLCompiler, self).get_ordering()
        grouping = []
        for t in ordering_group_by:
            try:
                int(t[0])
            except ValueError:
                grouping.append(t)
        return ordering, grouping

    def execute_sql(self, result_type=MULTI):
        self.result_type = result_type
        return super(SQLCompiler, self).execute_sql(result_type)

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
    pass

class SQLAggregateCompiler(compiler.SQLAggregateCompiler, SQLCompiler):
    pass

class SQLDateCompiler(compiler.SQLDateCompiler, SQLCompiler):
    pass
