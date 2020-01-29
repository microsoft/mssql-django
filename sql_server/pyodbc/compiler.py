import types
from itertools import chain

import django
from django.db.models.aggregates import Avg, Count, StdDev, Variance
from django.db.models.expressions import Ref, Subquery, Value
from django.db.models.functions import (
    Chr, ConcatPair, Greatest, Least, Length, LPad, Repeat, RPad, StrIndex, Substr, Trim
)
from django.db.models.sql import compiler
from django.db.transaction import TransactionManagementError
from django.db.utils import NotSupportedError


def _as_sql_agv(self, compiler, connection):
    return self.as_sql(compiler, connection, template='%(function)s(CONVERT(float, %(field)s))')


def _as_sql_chr(self, compiler, connection):
    return self.as_sql(compiler, connection, function='NCHAR')


def _as_sql_concatpair(self, compiler, connection):
    if connection.sql_server_version < 2012:
        node = self.coalesce()
        return node.as_sql(compiler, connection, arg_joiner=' + ', template='%(expressions)s')
    else:
        return self.as_sql(compiler, connection)


def _as_sql_count(self, compiler, connection):
    return self.as_sql(compiler, connection, function='COUNT_BIG')


def _as_sql_greatest(self, compiler, connection):
    # SQL Server does not provide GREATEST function,
    # so we emulate it with a table value constructor
    # https://msdn.microsoft.com/en-us/library/dd776382.aspx
    template = '(SELECT MAX(value) FROM (VALUES (%(expressions)s)) AS _%(function)s(value))'
    return self.as_sql(compiler, connection, arg_joiner='), (', template=template)


def _as_sql_least(self, compiler, connection):
    # SQL Server does not provide LEAST function,
    # so we emulate it with a table value constructor
    # https://msdn.microsoft.com/en-us/library/dd776382.aspx
    template = '(SELECT MIN(value) FROM (VALUES (%(expressions)s)) AS _%(function)s(value))'
    return self.as_sql(compiler, connection, arg_joiner='), (', template=template)


def _as_sql_length(self, compiler, connection):
    return self.as_sql(compiler, connection, function='LEN')


def _as_sql_lpad(self, compiler, connection):
    i = iter(self.get_source_expressions())
    expression, expression_arg = compiler.compile(next(i))
    length, length_arg = compiler.compile(next(i))
    fill_text, fill_text_arg = compiler.compile(next(i))
    params = []
    params.extend(fill_text_arg)
    params.extend(length_arg)
    params.extend(length_arg)
    params.extend(expression_arg)
    params.extend(length_arg)
    params.extend(expression_arg)
    params.extend(expression_arg)
    template = ('LEFT(REPLICATE(%(fill_text)s, %(length)s), CASE WHEN %(length)s > LEN(%(expression)s) '
                'THEN %(length)s - LEN(%(expression)s) ELSE 0 END) + %(expression)s')
    return template % {'expression': expression, 'length': length, 'fill_text': fill_text}, params


def _as_sql_repeat(self, compiler, connection):
    return self.as_sql(compiler, connection, function='REPLICATE')


def _as_sql_rpad(self, compiler, connection):
    i = iter(self.get_source_expressions())
    expression, expression_arg = compiler.compile(next(i))
    length, length_arg = compiler.compile(next(i))
    fill_text, fill_text_arg = compiler.compile(next(i))
    params = []
    params.extend(expression_arg)
    params.extend(fill_text_arg)
    params.extend(length_arg)
    params.extend(length_arg)
    template = 'LEFT(%(expression)s + REPLICATE(%(fill_text)s, %(length)s), %(length)s)'
    return template % {'expression': expression, 'length': length, 'fill_text': fill_text}, params


def _as_sql_stddev(self, compiler, connection):
    function = 'STDEV'
    if self.function == 'STDDEV_POP':
        function = '%sP' % function
    return self.as_sql(compiler, connection, function=function)


def _as_sql_strindex(self, compiler, connection):
    self.source_expressions.reverse()
    sql = self.as_sql(compiler, connection, function='CHARINDEX')
    self.source_expressions.reverse()
    return sql


def _as_sql_substr(self, compiler, connection):
    if len(self.get_source_expressions()) < 3:
        self.get_source_expressions().append(Value(2**31 - 1))
    return self.as_sql(compiler, connection)


def _as_sql_trim(self, compiler, connection):
    return self.as_sql(compiler, connection, template='LTRIM(RTRIM(%(expressions)s))')


def _as_sql_variance(self, compiler, connection):
    function = 'VAR'
    if self.function == 'VAR_POP':
        function = '%sP' % function
    return self.as_sql(compiler, connection, function=function)


def _cursor_iter(cursor, sentinel, col_count, itersize):
    """
    Yields blocks of rows from a cursor and ensures the cursor is closed when
    done.
    """
    if not hasattr(cursor.db, 'supports_mars') or cursor.db.supports_mars:
        # same as the original Django implementation
        try:
            for rows in iter((lambda: cursor.fetchmany(itersize)), sentinel):
                yield rows if col_count is None else [r[:col_count] for r in rows]
        finally:
            cursor.close()
    else:
        # retrieve all chunks from the cursor and close it before yielding
        # so that we can open an another cursor over an iteration
        # (for drivers such as FreeTDS)
        chunks = []
        try:
            for rows in iter((lambda: cursor.fetchmany(itersize)), sentinel):
                chunks.append(rows if col_count is None else [r[:col_count] for r in rows])
        finally:
            cursor.close()
        for rows in chunks:
            yield rows


compiler.cursor_iter = _cursor_iter


class SQLCompiler(compiler.SQLCompiler):

    def as_sql(self, with_limits=True, with_col_aliases=False):
        """
        Create the SQL for this query. Return the SQL string and list of
        parameters.

        If 'with_limits' is False, any limit/offset information is not included
        in the query.
        """
        refcounts_before = self.query.alias_refcount.copy()
        try:
            extra_select, order_by, group_by = self.pre_sql_setup()
            for_update_part = None
            # Is a LIMIT/OFFSET clause needed?
            with_limit_offset = with_limits and (self.query.high_mark is not None or self.query.low_mark)
            combinator = self.query.combinator
            features = self.connection.features

            # The do_offset flag indicates whether we need to construct
            # the SQL needed to use limit/offset w/SQL Server.
            high_mark = self.query.high_mark
            low_mark = self.query.low_mark
            do_limit = with_limits and high_mark is not None
            do_offset = with_limits and low_mark != 0
            # SQL Server 2012 or newer supports OFFSET/FETCH clause
            supports_offset_clause = self.connection.sql_server_version >= 2012
            do_offset_emulation = do_offset and not supports_offset_clause

            if combinator:
                if not getattr(features, 'supports_select_{}'.format(combinator)):
                    raise NotSupportedError('{} is not supported on this database backend.'.format(combinator))
                result, params = self.get_combinator_sql(combinator, self.query.combinator_all)
            else:
                distinct_fields, distinct_params = self.get_distinct()
                # This must come after 'select', 'ordering', and 'distinct' -- see
                # docstring of get_from_clause() for details.
                from_, f_params = self.get_from_clause()
                where, w_params = self.compile(self.where) if self.where is not None else ("", [])
                having, h_params = self.compile(self.having) if self.having is not None else ("", [])
                params = []
                result = ['SELECT']

                if self.query.distinct:
                    distinct_result, distinct_params = self.connection.ops.distinct_sql(
                        distinct_fields,
                        distinct_params,
                    )
                    result += distinct_result
                    params += distinct_params

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
                                    o_sql, _ = src.as_sql(self, self.connection)
                                    odir = 'DESC' if expr.descending else 'ASC'
                                    o_sql = '%s %s' % (o_sql, odir)
                                ordering.append(o_sql)
                                params.extend(o_params)
                            offsetting_order_by = ', '.join(ordering)
                            order_by = []
                        out_cols.append('ROW_NUMBER() OVER (ORDER BY %s) AS [rn]' % offsetting_order_by)
                    elif not order_by:
                        order_by.append(((None, ('%s ASC' % offsetting_order_by, [], None))))

                if self.query.select_for_update and self.connection.features.has_select_for_update:
                    if self.connection.get_autocommit():
                        raise TransactionManagementError('select_for_update cannot be used outside of a transaction.')

                    if with_limit_offset and not self.connection.features.supports_select_for_update_with_limit:
                        raise NotSupportedError(
                            'LIMIT/OFFSET is not supported with '
                            'select_for_update on this database backend.'
                        )
                    nowait = self.query.select_for_update_nowait
                    skip_locked = self.query.select_for_update_skip_locked
                    of = self.query.select_for_update_of
                    # If it's a NOWAIT/SKIP LOCKED/OF query but the backend
                    # doesn't support it, raise NotSupportedError to prevent a
                    # possible deadlock.
                    if nowait and not self.connection.features.has_select_for_update_nowait:
                        raise NotSupportedError('NOWAIT is not supported on this database backend.')
                    elif skip_locked and not self.connection.features.has_select_for_update_skip_locked:
                        raise NotSupportedError('SKIP LOCKED is not supported on this database backend.')
                    elif of and not self.connection.features.has_select_for_update_of:
                        raise NotSupportedError('FOR UPDATE OF is not supported on this database backend.')
                    for_update_part = self.connection.ops.for_update_sql(
                        nowait=nowait,
                        skip_locked=skip_locked,
                        of=self.get_select_for_update_of_arguments(),
                    )

                if for_update_part and self.connection.features.for_update_after_from:
                    from_.insert(1, for_update_part)

                result += [', '.join(out_cols), 'FROM', *from_]
                params.extend(f_params)

                if where:
                    result.append('WHERE %s' % where)
                    params.extend(w_params)

                grouping = []
                for g_sql, g_params in group_by:
                    grouping.append(g_sql)
                    params.extend(g_params)
                if grouping:
                    if distinct_fields:
                        raise NotImplementedError('annotate() + distinct(fields) is not implemented.')
                    order_by = order_by or self.connection.ops.force_no_ordering()
                    result.append('GROUP BY %s' % ', '.join(grouping))

                if having:
                    result.append('HAVING %s' % having)
                    params.extend(h_params)

            if self.query.explain_query:
                result.insert(0, self.connection.ops.explain_query_prefix(
                    self.query.explain_format,
                    **self.query.explain_options
                ))

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
                        result.append('BETWEEN %d AND %d' % (low_mark + 1, high_mark))
                    else:
                        result.append('>= %d' % (low_mark + 1))
                    if not self.query.subquery:
                        result.append('ORDER BY X.rn')
                else:
                    result.append(self.connection.ops.limit_offset_sql(self.query.low_mark, self.query.high_mark))

            if self.query.subquery and extra_select:
                # If the query is used as a subquery, the extra selects would
                # result in more columns than the left-hand side expression is
                # expecting. This can happen when a subquery uses a combination
                # of order_by() and distinct(), forcing the ordering expressions
                # to be selected as well. Wrap the query in another subquery
                # to exclude extraneous selects.
                sub_selects = []
                sub_params = []
                for index, (select, _, alias) in enumerate(self.select, start=1):
                    if not alias and with_col_aliases:
                        alias = 'col%d' % index
                    if alias:
                        sub_selects.append("%s.%s" % (
                            self.connection.ops.quote_name('subquery'),
                            self.connection.ops.quote_name(alias),
                        ))
                    else:
                        select_clone = select.relabeled_clone({select.alias: 'subquery'})
                        subselect, subparams = select_clone.as_sql(self, self.connection)
                        sub_selects.append(subselect)
                        sub_params.extend(subparams)
                return 'SELECT %s FROM (%s) subquery' % (
                    ', '.join(sub_selects),
                    ' '.join(result),
                ), tuple(sub_params + params)

            return ' '.join(result), tuple(params)
        finally:
            # Finally do cleanup - get rid of the joins we created above.
            self.query.reset_refcounts(refcounts_before)

    def compile(self, node, *args, **kwargs):
        node = self._as_microsoft(node)
        return super().compile(node, *args, **kwargs)

    def collapse_group_by(self, expressions, having):
        expressions = super().collapse_group_by(expressions, having)
        return [e for e in expressions if not isinstance(e, Subquery)]

    def _as_microsoft(self, node):
        as_microsoft = None
        if isinstance(node, Avg):
            as_microsoft = _as_sql_agv
        elif isinstance(node, Chr):
            as_microsoft = _as_sql_chr
        elif isinstance(node, ConcatPair):
            as_microsoft = _as_sql_concatpair
        elif isinstance(node, Count):
            as_microsoft = _as_sql_count
        elif isinstance(node, Greatest):
            as_microsoft = _as_sql_greatest
        elif isinstance(node, Least):
            as_microsoft = _as_sql_least
        elif isinstance(node, Length):
            as_microsoft = _as_sql_length
        elif isinstance(node, RPad):
            as_microsoft = _as_sql_rpad
        elif isinstance(node, LPad):
            as_microsoft = _as_sql_lpad
        elif isinstance(node, Repeat):
            as_microsoft = _as_sql_repeat
        elif isinstance(node, StdDev):
            as_microsoft = _as_sql_stddev
        elif isinstance(node, StrIndex):
            as_microsoft = _as_sql_strindex
        elif isinstance(node, Substr):
            as_microsoft = _as_sql_substr
        elif isinstance(node, Trim):
            as_microsoft = _as_sql_trim
        elif isinstance(node, Variance):
            as_microsoft = _as_sql_variance
        if as_microsoft:
            node = node.copy()
            node.as_microsoft = types.MethodType(as_microsoft, node)
        return node


class SQLInsertCompiler(compiler.SQLInsertCompiler, SQLCompiler):
    def get_returned_fields(self):
        if django.VERSION >= (3, 0, 0):
            return self.returning_fields
        return self.return_id

    def fix_auto(self, sql, opts, fields, qn):
        if opts.auto_field is not None:
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

    def as_sql(self):
        # We don't need quote_name_unless_alias() here, since these are all
        # going to be column names (so we can avoid the extra overhead).
        qn = self.connection.ops.quote_name
        opts = self.query.get_meta()
        result = ['INSERT INTO %s' % qn(opts.db_table)]
        fields = self.query.fields or [opts.pk]

        if self.query.fields:
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
        can_bulk = (not self.get_returned_fields() and self.connection.features.has_bulk_insert) and self.query.fields

        placeholder_rows, param_rows = self.assemble_as_sql(fields, value_rows)

        if self.get_returned_fields() and self.connection.features.can_return_id_from_insert:
            result.insert(0, 'SET NOCOUNT ON')
            result.append((values_format + ';') % ', '.join(placeholder_rows[0]))
            params = [param_rows[0]]
            result.append('SELECT CAST(SCOPE_IDENTITY() AS bigint)')
            sql = [(" ".join(result), tuple(chain.from_iterable(params)))]
        else:
            if can_bulk:
                result.append(self.connection.ops.bulk_insert_sql(fields, placeholder_rows))
                sql = [(" ".join(result), tuple(p for ps in param_rows for p in ps))]
            else:
                sql = [
                    (" ".join(result + [values_format % ", ".join(p)]), vals)
                    for p, vals in zip(placeholder_rows, param_rows)
                ]

        if self.query.fields:
            sql = self.fix_auto(sql, opts, fields, qn)

        return sql


class SQLDeleteCompiler(compiler.SQLDeleteCompiler, SQLCompiler):
    def as_sql(self):
        sql, params = super().as_sql()
        if sql:
            sql = '; '.join(['SET NOCOUNT OFF', sql])
        return sql, params


class SQLUpdateCompiler(compiler.SQLUpdateCompiler, SQLCompiler):
    def as_sql(self):
        sql, params = super().as_sql()
        if sql:
            sql = '; '.join(['SET NOCOUNT OFF', sql])
        return sql, params


class SQLAggregateCompiler(compiler.SQLAggregateCompiler, SQLCompiler):
    pass
