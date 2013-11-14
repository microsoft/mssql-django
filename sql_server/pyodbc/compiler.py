try:
    from itertools import zip_longest
except ImportError:
    from itertools import izip_longest as zip_longest

from django.db.models.sql import compiler
from django.utils import six


class SQLCompiler(compiler.SQLCompiler):

    def resolve_columns(self, row, fields=()):
        index_start = len(list(self.query.extra_select.keys()))
        values = [self.query.convert_values(v, None, self.connection) for v in row[:index_start]]
        for value, field in zip_longest(row[index_start:], fields):
            if field:
                value = self.query.convert_values(value, field, self.connection)
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
        supports_offset_clause = self.connection.sql_server_version >= 2012

        # After executing the query, we must get rid of any joins the query
        # setup created. So, take note of alias counts before the query ran.
        # However we do not want to get rid of stuff done in pre_sql_setup(),
        # as the pre_sql_setup will modify query state in a way that forbids
        # another run of it.
        self.refcounts_before = self.query.alias_refcount.copy()
        out_cols, s_params = self.get_columns(with_col_aliases)
        #ordering, o_params, ordering_group_by = self.get_ordering()
        ordering, o_params, ordering_group_by, offset_params = \
            self._get_ordering(out_cols, supports_offset_clause or not do_offset)

        distinct_fields = self.get_distinct()

        # This must come after 'select', 'ordering' and 'distinct' -- see
        # docstring of get_from_clause() for details.
        from_, f_params = self.get_from_clause()

        qn = self.quote_name_unless_alias

        where, w_params = self.query.where.as_sql(qn=qn, connection=self.connection)
        having, h_params = self.query.having.as_sql(qn=qn, connection=self.connection)
        having_group_by = self.query.having.get_cols()
        params = []
        for val in six.itervalues(self.query.extra_select):
            params.extend(val[1])

        result = ['SELECT']

        if self.query.distinct:
            result.append(self.connection.ops.distinct_sql(distinct_fields))
        params.extend(o_params)

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
            if not supports_offset_clause:
                order = ', '.join(ordering)
                self.ordering_aliases.append('(ROW_NUMBER() OVER (ORDER BY %s)) AS [rn]' % order)
                ordering = self.connection.ops.force_no_ordering()
        elif do_limit:
            result.append('TOP %d' % high_mark)

        result.append(', '.join(out_cols + self.ordering_aliases))

        params.extend(s_params)
        params.extend(self.ordering_params)
        params.extend(offset_params)

        result.append('FROM')
        result.extend(from_)
        params.extend(f_params)

        if self.query.select_for_update and self.connection.features.has_select_for_update:
            # If we've been asked for a NOWAIT query but the backend does not support it,
            # raise a DatabaseError otherwise we could get an unexpected deadlock.
            nowait = self.query.select_for_update_nowait
            result.append(self.connection.ops.for_update_sql(nowait=nowait))

        if where:
            result.append('WHERE %s' % where)
            params.extend(w_params)

        grouping, gb_params = self.get_grouping(having_group_by, ordering_group_by)
        if grouping:
            if distinct_fields:
                raise NotImplementedError(
                    "annotate() + distinct(fields) not implemented.")
            if not ordering:
                ordering = self.connection.ops.force_no_ordering()
            result.append('GROUP BY %s' % ', '.join(grouping))
            params.extend(gb_params)

        if having:
            result.append('HAVING %s' % having)
            params.extend(h_params)

        if ordering and not with_col_aliases:
            result.append('ORDER BY %s' % ', '.join(ordering))
            if do_offset and supports_offset_clause:
                result.append('OFFSET %d ROWS' % low_mark)
                if do_limit:
                    result.append('FETCH FIRST %d ROWS ONLY' % (high_mark - low_mark))

        if do_offset and not supports_offset_clause:
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
        self.query.reset_refcounts(self.refcounts_before)

        return ' '.join(result), tuple(params)

    def _get_ordering(self, out_cols, allow_aliases=True):
        ordering, o_params, ordering_group_by = self.get_ordering()
        # SQL Server doesn't support grouping by column number
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
        return ordering, o_params, grouping, offset_params

class SQLInsertCompiler(compiler.SQLInsertCompiler, SQLCompiler):

    def as_sql(self):
        # We don't need quote_name_unless_alias() here, since these are all
        # going to be column names (so we can avoid the extra overhead).
        qn = self.connection.ops.quote_name
        opts = self.query.get_meta()
        result = ['INSERT INTO %s' % qn(opts.db_table)]

        has_fields = bool(self.query.fields)

        if has_fields:
            fields = self.query.fields
            result.append('(%s)' % ', '.join([qn(f.column) for f in fields]))
            values_format = 'VALUES (%s)'
            params = values = [
                [
                    f.get_db_prep_save(getattr(obj, f.attname) if self.query.raw else f.pre_save(obj, True), connection=self.connection)
                    for f in fields
                ]
                for obj in self.query.objs
            ]
        else:
            values_format = '%s VALUES'
            values = [[self.connection.ops.pk_default_value()] for obj in self.query.objs]
            params = [[]]
            fields = [None]
        can_bulk = (not any(hasattr(field, "get_placeholder") for field in fields) and
            not self.return_id and self.connection.features.has_bulk_insert)

        if can_bulk:
            placeholders = [["%s"] * len(fields)]
        else:
            placeholders = [
                [self.placeholder(field, v) for field, v in zip(fields, val)]
                for val in values
            ]
            # Oracle Spatial needs to remove some values due to #10888
            params = self.connection.ops.modify_insert_params(placeholders, params)

        if self.return_id and self.connection.features.can_return_id_from_insert:
            result.append("OUTPUT INSERTED.%s" % qn(opts.pk.column))
            result.append(values_format % ", ".join(placeholders[0]))
            return [(" ".join(result), tuple(params[0]))]

        if can_bulk:
            result.append(self.connection.ops.bulk_insert_sql(fields, len(values)))
            sql = [(" ".join(result), tuple([v for val in values for v in val]))]
        else:
            sql = [
                (" ".join(result + [values_format % ", ".join(p)]), vals)
                for p, vals in zip(placeholders, params)
            ]

        if has_fields:
            if opts.has_auto_field:
                # db_column is None if not explicitly specified by model field
                auto_field_column = opts.auto_field.db_column or opts.auto_field.column
                columns = [f.column for f in fields]
                if auto_field_column in columns:
                    id_insert_sql = []
                    table = qn(opts.db_table)
                    sql_format = 'SET IDENTITY_INSERT %s ON;\n%s;\nSET IDENTITY_INSERT %s OFF'
                    for q, p in sql:
                        id_insert_sql.append((sql_format % (table, q, table), p))
                    sql = id_insert_sql

        return sql

class SQLDeleteCompiler(compiler.SQLDeleteCompiler, SQLCompiler):
    pass

class SQLUpdateCompiler(compiler.SQLUpdateCompiler, SQLCompiler):
    pass

class SQLAggregateCompiler(compiler.SQLAggregateCompiler, SQLCompiler):
    pass

class SQLDateCompiler(compiler.SQLDateCompiler, SQLCompiler):
    pass

class SQLDateTimeCompiler(compiler.SQLDateTimeCompiler, SQLCompiler):
    pass
