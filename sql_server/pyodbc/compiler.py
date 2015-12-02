from django.db.models.expressions import Ref, Value
from django.db.models.sql import compiler
from django.db.transaction import TransactionManagementError
from django.db.utils import DatabaseError
from django.utils import six


class SQLCompiler(compiler.SQLCompiler):

    def as_sql(self, with_limits=True, with_col_aliases=False, subquery=False):
        """
        Creates the SQL for this query. Returns the SQL string and list of
        parameters.

        If 'with_limits' is False, any limit/offset information is not included
        in the query.
        """
        if with_limits and self.query.low_mark == self.query.high_mark:
            return '', ()
        self.subquery = subquery
        refcounts_before = self.query.alias_refcount.copy()
        try:
            extra_select, order_by, group_by = self.pre_sql_setup()
            if with_limits and self.query.low_mark == self.query.high_mark:
                return '', ()

            # The do_offset flag indicates whether we need to construct
            # the SQL needed to use limit/offset w/SQL Server.
            high_mark = self.query.high_mark
            low_mark = self.query.low_mark
            do_limit = with_limits and high_mark is not None
            do_offset = with_limits and low_mark != 0
            # SQL Server 2012 or newer supports OFFSET/FETCH clause
            supports_offset_clause = self.connection.sql_server_version >= 2012
            do_offset_emulation = do_offset and not supports_offset_clause

            distinct_fields = self.get_distinct()

            # This must come after 'select', 'ordering', and 'distinct' -- see
            # docstring of get_from_clause() for details.
            from_, f_params = self.get_from_clause()

            where, w_params = self.compile(self.where) if self.where is not None else ("", [])
            having, h_params = self.compile(self.having) if self.having is not None else ("", [])
            params = []
            result = ['SELECT']

            if self.query.distinct:
                result.append(self.connection.ops.distinct_sql(distinct_fields))

            # SQL Server requires the keword for limitting at the begenning
            if do_limit and not do_offset:
                result.append('TOP %d' % high_mark)

            out_cols = []
            col_idx = 1
            for _, (s_sql, s_params), alias in self.select + extra_select:
                if alias:
                    s_sql = '%s AS %s' % (s_sql, self.connection.ops.quote_name(alias))
                elif with_col_aliases or do_offset_emulation:
                    s_sql = '%s AS %s' % (s_sql, 'Col%d' % col_idx)
                    col_idx += 1
                params.extend(s_params)
                out_cols.append(s_sql)

            # SQL Server requires an order-by clause for offsetting
            if do_offset:
                meta = self.query.get_meta()
                qn = self.quote_name_unless_alias
                offsetting_order_by = '%s.%s' % (qn(meta.db_table), qn(meta.pk.db_column or meta.pk.column))
                if do_offset_emulation:
                    if order_by:
                        ordering = []
                        for expr, (o_sql, o_params, _) in order_by:
                            # value_expression in OVER clause cannot refer to
                            # expressions or aliases in the select list. See:
                            # http://msdn.microsoft.com/en-us/library/ms189461.aspx
                            src = next(iter(expr.get_source_expressions()))
                            if isinstance(src, Ref):
                                src = next(iter(src.get_source_expressions()))
                                o_sql, _  = src.as_sql(self, self.connection)
                                odir = 'DESC' if expr.descending else 'ASC'
                                o_sql = '%s %s' % (o_sql, odir)
                            ordering.append(o_sql)
                            params.extend(o_params)
                        offsetting_order_by = ', '.join(ordering)
                        order_by = []
                    out_cols.append('ROW_NUMBER() OVER (ORDER BY %s) AS [rn]' % offsetting_order_by)
                elif not order_by:
                    order_by.append(((None, ('%s ASC' % offsetting_order_by, [], None))))

            result.append(', '.join(out_cols))

            result.append('FROM')
            result.extend(from_)
            params.extend(f_params)

            if self.query.select_for_update and self.connection.features.has_select_for_update:
                if self.connection.get_autocommit():
                    raise TransactionManagementError(
                        "select_for_update cannot be used outside of a transaction."
                    )

                # If we've been asked for a NOWAIT query but the backend does
                # not support it, raise a DatabaseError otherwise we could get
                # an unexpected deadlock.
                nowait = self.query.select_for_update_nowait
                if nowait and not self.connection.features.has_select_for_update_nowait:
                    raise DatabaseError('NOWAIT is not supported on this database backend.')
                result.append(self.connection.ops.for_update_sql(nowait=nowait))

            if where:
                result.append('WHERE %s' % where)
                params.extend(w_params)

            grouping = []
            for g_sql, g_params in group_by:
                grouping.append(g_sql)
                params.extend(g_params)
            if grouping:
                if distinct_fields:
                    raise NotImplementedError(
                        "annotate() + distinct(fields) is not implemented.")
                if not order_by:
                    order_by = self.connection.ops.force_no_ordering()
                result.append('GROUP BY %s' % ', '.join(grouping))

            if having:
                result.append('HAVING %s' % having)
                params.extend(h_params)

            if order_by:
                ordering = []
                for _, (o_sql, o_params, _) in order_by:
                    ordering.append(o_sql)
                    params.extend(o_params)
                result.append('ORDER BY %s' % ', '.join(ordering))

            # SQL Server requires the backend-specific emulation (2008 or earlier)
            # or an offset clause (2012 or newer) for offsetting
            if do_offset:
                if do_offset_emulation:
                    # Construct the final SQL clause, using the initial select SQL
                    # obtained above.
                    result = ['SELECT * FROM (%s) AS X WHERE X.rn' % ' '.join(result)]
                    # Place WHERE condition on `rn` for the desired range.
                    if do_limit:
                        result.append('BETWEEN %d AND %d' % (low_mark+1, high_mark))
                    else:
                        result.append('>= %d' % (low_mark+1))
                    if not subquery:
                        result.append('ORDER BY X.rn')
                else:
                    result.append('OFFSET %d ROWS' % low_mark)
                    if do_limit:
                        result.append('FETCH FIRST %d ROWS ONLY' % (high_mark - low_mark))

            return ' '.join(result), tuple(params)
        finally:
            # Finally do cleanup - get rid of the joins we created above.
            self.query.reset_refcounts(refcounts_before)

    def compile(self, node, select_format=False):
        node = self._as_microsoft(node)
        return super(SQLCompiler, self).compile(node, select_format)

    def _as_microsoft(self, node):
        if hasattr(node, 'function'):
            if node.function == 'AVG':
                node.template = '%(function)s(CONVERT(float, %(field)s))'
            elif node.function == 'CONCAT':
                if self.connection.sql_server_version < 2012:
                    node.arg_joiner = ' + '
                    node.template = '%(expressions)s'
                    node = node.coalesce()
            # SQL Server does not provide GREATEST/LEAST functions,
            # so we emulate them with table value constructors
            # https://msdn.microsoft.com/en-us/library/dd776382.aspx
            elif node.function == 'GREATEST':
                node.arg_joiner = '), ('
                node.template = '(SELECT MAX(value) FROM (VALUES (%(expressions)s)) AS _%(function)s(value))'
            elif node.function == 'LEAST':
                node.arg_joiner = '), ('
                node.template = '(SELECT MIN(value) FROM (VALUES (%(expressions)s)) AS _%(function)s(value))'
            elif node.function == 'LENGTH':
                node.function = 'LEN'
            elif node.function == 'STDDEV_SAMP':
                node.function = 'STDEV'
            elif node.function == 'STDDEV_POP':
                node.function = 'STDEVP'
            elif node.function == 'SUBSTRING':
                if len(node.get_source_expressions()) < 3:
                    node.get_source_expressions().append(Value(2**31-1))
            elif node.function == 'VAR_SAMP':
                node.function = 'VAR'
            elif node.function == 'VAR_POP':
                node.function = 'VARP'
        return node


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
            result.append('(%s)' % ', '.join(qn(f.column) for f in fields))
            values_format = 'VALUES (%s)'
            value_rows = [
                [self.prepare_value(field, self.pre_save_val(field, obj)) for field in fields]
                for obj in self.query.objs
            ]
        else:
            values_format = '%s VALUES'
            # An empty object.
            value_rows = [[self.connection.ops.pk_default_value()] for _ in self.query.objs]
            fields = [None]

        # Currently the backends just accept values when generating bulk
        # queries and generate their own placeholders. Doing that isn't
        # necessary and it should be possible to use placeholders and
        # expressions in bulk inserts too.
        can_bulk = (not self.return_id and self.connection.features.has_bulk_insert) and has_fields

        placeholder_rows, param_rows = self.assemble_as_sql(fields, value_rows)

        if self.return_id and self.connection.features.can_return_id_from_insert:
            result.insert(0, 'SET NOCOUNT ON')
            result.append((values_format + ';') % ', '.join(placeholder_rows[0]))
            result.append('SELECT CAST(SCOPE_IDENTITY() AS BIGINT)')
            return [(" ".join(result), tuple(param_rows[0]))]

        if can_bulk:
            result.append(self.connection.ops.bulk_insert_sql(fields, placeholder_rows))
            sql = [(" ".join(result), tuple(p for ps in param_rows for p in ps))]
        else:
            sql = [
                (" ".join(result + [values_format % ", ".join(p)]), vals)
                for p, vals in zip(placeholder_rows, param_rows)
            ]

        if has_fields:
            if opts.has_auto_field:
                # db_column is None if not explicitly specified by model field
                auto_field_column = opts.auto_field.db_column or opts.auto_field.column
                columns = [f.column for f in fields]
                if auto_field_column in columns:
                    id_insert_sql = []
                    table = qn(opts.db_table)
                    sql_format = 'SET IDENTITY_INSERT %s ON; %s; SET IDENTITY_INSERT %s OFF'
                    for q, p in sql:
                        id_insert_sql.append((sql_format % (table, q, table), p))
                    sql = id_insert_sql

        return sql


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
