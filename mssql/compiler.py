# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

import types
from functools import partial
from itertools import chain

import django
from django.db.models.aggregates import Avg, Count, StdDev, Variance
from django.db.models import AutoField
if django.VERSION >= (6, 0):
    from django.db.models.aggregates import StringAgg
from django.db.models.expressions import Col, OuterRef, Ref, Subquery, Value, Window
from django.db.models.expressions import ResolvedOuterRef
from django.db.models.functions import (
    Chr, ConcatPair, Greatest, Least, Length, LPad, Random, Repeat, RPad, StrIndex, Substr, Trim
)
from django.db.models.sql import compiler
from django.db.transaction import TransactionManagementError
from django.db.utils import NotSupportedError
if django.VERSION >= (3, 1):
    from django.db.models.fields.json import KeyTransform as json_KeyTransform
    # compile_json_path was moved to connection.ops in Django 6.0
    if django.VERSION < (6, 0):
        from django.db.models.fields.json import compile_json_path
    else:
        compile_json_path = None
if django.VERSION >= (4, 2):
    from django.core.exceptions import EmptyResultSet, FullResultSet
# ColPairs was introduced in Django 5.2 for composite primary key support.
# When an OrderBy wraps a ColPairs, Django's OrderBy.as_sql() joins all
# columns into a single comma-separated SQL string. We expand these at
# the expression level in get_order_by() so each ORDER BY item is always
# a single column expression.
if django.VERSION >= (5, 2):
    from django.db.models.expressions import ColPairs
else:
    ColPairs = None

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

def _as_sql_json_keytransform(self, compiler, connection):
    lhs, params, key_transforms = self.preprocess_lhs(compiler, connection)
    # Always prefer backend compilation when available so SQL Server-specific
    # escaping rules are applied consistently across Django versions.
    if hasattr(connection.ops, 'compile_json_path'):
        json_path = connection.ops.compile_json_path(key_transforms)
    else:
        json_path = compile_json_path(key_transforms)
    json_path = json_path.replace("'", "''")
    return (
        "COALESCE(JSON_QUERY(%s, '%s'), JSON_VALUE(%s, '%s'))" %
        ((lhs, json_path) * 2)
    ), tuple(params) * 2

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
    params.extend(length_arg)
    template = ('LEFT(LEFT(REPLICATE(%(fill_text)s, %(length)s), CASE WHEN %(length)s > LEN(%(expression)s) '
                'THEN %(length)s - LEN(%(expression)s) ELSE 0 END) + %(expression)s, %(length)s)')
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


def _as_sql_stringagg(self, compiler, connection):
    if self.order_by and _contains_outerref(self.order_by, compiler.query):
        node = self.copy()
        node.order_by = None
        return node.as_sql(compiler, connection)

    template = None
    if self.order_by:
        template = '%(function)s(%(distinct)s%(expressions)s) WITHIN GROUP (%(order_by)s)%(filter)s'
    return self.as_sql(compiler, connection, template=template)


def _contains_outerref(expression, query=None):
    if expression is None:
        return False
    if isinstance(expression, (OuterRef, ResolvedOuterRef)):
        return True
    if isinstance(expression, Col) and query is not None:
        query_aliases = set(query.alias_map) if getattr(query, 'alias_map', None) else set()
        if expression.alias not in query_aliases:
            return True

    source_expressions = getattr(expression, 'get_source_expressions', None)
    if source_expressions is None:
        return False

    return any(_contains_outerref(expr, query) for expr in expression.get_source_expressions() if expr is not None)


def _as_sql_window(self, compiler, connection, template=None):
    # Get the expressions supported by the backend
    connection.ops.check_expression_support(self)
    # Raise an error if window expressions are not supported.
    if not connection.features.supports_over_clause:
        raise NotSupportedError("This backend does not support window expressions.")
    # Compile the source expression for the window function.
    expr_sql, params = compiler.compile(self.source_expression)
    # Initialize window SQL parts and parameters.
    window_sql, window_params = [], ()
    # Handle PARTITION BY clause if present.
    if self.partition_by is not None:
        # Compile the PARTITION BY clause.
        sql_expr, sql_params = self.partition_by.as_sql(
            compiler=compiler,
            connection=connection,
            template="PARTITION BY %(expressions)s",
        )
        window_sql.append(sql_expr)
        window_params += tuple(sql_params)

    # Handle ORDER BY clause if present.
    if self.order_by is not None:
        # Compile the ORDER BY clause.
        order_sql, order_params = compiler.compile(self.order_by)
        # Handles cases where order_by compiles to empty
        if not order_sql.strip():
            order_sql = "ORDER BY (SELECT NULL)"
            order_params = ()
        window_sql.append(order_sql)
        window_params += tuple(order_params)
    else:
        # Default to ORDER BY (SELECT NULL) if no order_by is specified.
        window_sql.append('ORDER BY (SELECT NULL)')

    # Handle frame specification if present.
    if self.frame:
        # Compile the frame clause.
        frame_sql, frame_params = compiler.compile(self.frame)
        window_sql.append(frame_sql)
        window_params += tuple(frame_params)

    # Use provided template or default to self.template.
    template = template or self.template
    # Return the formatted SQL and combined parameters.
    return (
        template % {"expression": expr_sql, "window": " ".join(window_sql).strip()},
        (*params, *window_params),
    )

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

    def _resolve_order_by_source_expression(self, expression, dereference_ref=True):
        if expression is None:
            return None
        source_expressions = expression.get_source_expressions()
        if not source_expressions:
            return None
        source = source_expressions[0]
        if dereference_ref and isinstance(source, Ref):
            ref_source_expressions = source.get_source_expressions()
            if ref_source_expressions:
                source = ref_source_expressions[0]
        return source

    def _is_constant_order_by_expression(self, expression):
        if django.VERSION >= (4, 2):
            unresolved = self._resolve_order_by_source_expression(expression, dereference_ref=False)
            if isinstance(unresolved, Ref):
                return False
        source = self._resolve_order_by_source_expression(expression)
        return source is not None and self._is_constant_expression(source)

    def get_order_by(self):
        """
        Expand ColPairs-based OrderBy expressions into individual per-column
        OrderBy entries before SQL compilation.

        Django 5.2+ composite PKs produce OrderBy(ColPairs(...)) which
        compiles to a single comma-separated SQL string. SQL Server doesn't
        allow duplicate columns in ORDER BY (error 169), and expanding at
        the expression level lets us deduplicate individual columns cleanly
        without parsing SQL strings.
        """
        result = super().get_order_by()
        if ColPairs is None:
            return result
        expanded = []
        for resolved, (sql, params, is_ref) in result:
            if isinstance(getattr(resolved, 'expression', None), ColPairs):
                for col in resolved.expression.get_cols():
                    order = resolved.copy()
                    order.set_source_expressions([col])
                    col_sql, col_params = self.compile(order)
                    expanded.append((order, (col_sql, col_params, is_ref)))
            else:
                expanded.append((resolved, (sql, params, is_ref)))
        return expanded

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
            elif django.VERSION >= (4, 2) and self.qualify:
                result, params = self.get_qualify_sql()
                order_by = None
            else:
                distinct_fields, distinct_params = self.get_distinct()
                # This must come after 'select', 'ordering', and 'distinct' -- see
                # docstring of get_from_clause() for details.
                from_, f_params = self.get_from_clause()
                if django.VERSION >= (4, 2):
                    try:
                        where, w_params = self.compile(self.where) if self.where is not None else ("", [])
                    except EmptyResultSet:
                        if self.elide_empty:
                            raise
                        # Use a predicate that's always False.
                        where, w_params = "0 = 1", []
                    except FullResultSet:
                        where, w_params = "", []
                    try:
                        having, h_params = self.compile(self.having) if self.having is not None else ("", [])
                    except FullResultSet:
                        having, h_params = "", []
                else:
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
                            seen_full = set()  # Full column refs (qualified or unqualified)
                            seen_unqualified = set()  # Just column names from unqualified refs
                            for expr, (o_sql, o_params, _) in order_by:
                                if self._is_constant_order_by_expression(expr):
                                    continue
                                # value_expression in OVER clause cannot refer to
                                # expressions or aliases in the select list. See:
                                # http://msdn.microsoft.com/en-us/library/ms189461.aspx
                                src = self._resolve_order_by_source_expression(expr, dereference_ref=False)
                                if isinstance(src, Ref):
                                    src = self._resolve_order_by_source_expression(expr)
                                    o_sql, _ = src.as_sql(self, self.connection)
                                    odir = 'DESC' if expr.descending else 'ASC'
                                    o_sql = '%s %s' % (o_sql, odir)
                                # SQL Server doesn't allow duplicate columns in ORDER BY.
                                # ColPairs are already expanded in get_order_by(), so each
                                # o_sql is a single column/expression.
                                # Handle the case where [col] and [table].[col] refer to
                                # the same column.
                                col_ref = o_sql.rsplit(' ', 1)[0] if o_sql.rstrip().endswith(('ASC', 'DESC')) else o_sql
                                col_ref_upper = col_ref.upper()
                                # Only treat as a qualified column ref if it looks like
                                # [table].[col], not a function call containing dots.
                                is_qualified = '.' in col_ref and '(' not in col_ref
                                col_name = col_ref.rsplit('.', 1)[-1].upper() if is_qualified else col_ref_upper
                                if col_ref_upper in seen_full:
                                    continue
                                if is_qualified and col_name in seen_unqualified:
                                    continue
                                seen_full.add(col_ref_upper)
                                if not is_qualified:
                                    seen_unqualified.add(col_name)
                                ordering.append(o_sql)
                                params.extend(o_params)
                            if ordering:
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

                result += [', '.join(out_cols)]
                if from_:
                    result += ['FROM', *from_]
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
                    if self.query.default_ordering and not self.query.order_by:
                        order_by = self.connection.ops.force_no_ordering()
                    else:
                        order_by = order_by or self.connection.ops.force_no_ordering()
                    result.append('GROUP BY %s' % ', '.join(grouping))

                if having:
                    result.append('HAVING %s' % having)
                    params.extend(h_params)

            explain = self.query.explain_info if django.VERSION >= (4, 0) else self.query.explain_query
            if explain:
                result.insert(0, self.connection.ops.explain_query_prefix(
                    self.query.explain_format,
                    **self.query.explain_options
                ))

            if order_by:
                ordering = []
                seen_full = set()  # Full column refs (qualified or unqualified)
                seen_unqualified = set()  # Just column names from unqualified refs
                for expr, (o_sql, o_params, _) in order_by:
                    json_key_transform_ordering = False
                    uses_ref_alias = False
                    # Build one or more ORDER BY items for this expression,
                    # then run all of them through the shared de-duplication
                    # logic below.
                    normalized_order_items = None
                    if self._is_constant_order_by_expression(expr):
                        continue
                    if expr:
                        unresolved_src = self._resolve_order_by_source_expression(
                            expr,
                            dereference_ref=False,
                        )
                        uses_ref_alias = isinstance(unresolved_src, Ref)
                        src = self._resolve_order_by_source_expression(expr)
                        if isinstance(src, Random):
                            # ORDER BY RAND() doesn't return rows in random order
                            # replace it with NEWID()
                            o_sql = o_sql.replace('RAND()', 'NEWID()')
                        elif isinstance(src, json_KeyTransform) and not uses_ref_alias:
                            json_key_transform_ordering = True
                    if json_key_transform_ordering:
                        direction = 'DESC' if getattr(expr, 'descending', False) else 'ASC'
                        stripped_o_sql = o_sql.strip()
                        if stripped_o_sql.upper().endswith(' DESC'):
                            base_o_sql = stripped_o_sql[:-5]
                        elif stripped_o_sql.upper().endswith(' ASC'):
                            base_o_sql = stripped_o_sql[:-4]
                        else:
                            base_o_sql = stripped_o_sql
                        if base_o_sql.isdigit():
                            json_key_transform_ordering = False
                        else:
                            # For JSON numeric ordering, use a numeric-first
                            # key and then a textual fallback key. Both keys
                            # must still go through the standard dedupe path.
                            normalized_order_items = [
                                ('TRY_CONVERT(float, %s) %s' % (base_o_sql, direction), o_params),
                                ('%s %s' % (base_o_sql, direction), o_params),
                            ]
                    if normalized_order_items is None:
                        # Default path: keep original ORDER BY SQL as-is.
                        normalized_order_items = [(o_sql, o_params)]
                    # SQL Server doesn't allow the same column to appear twice
                    # in ORDER BY. ColPairs are already expanded in
                    # get_order_by(), so each o_sql is a single expression.
                    # Handle the case where [col] and [table].[col] refer to
                    # the same column.
                    for normalized_sql, normalized_params in normalized_order_items:
                        # Normalize sort direction suffix so dedupe compares
                        # on the expression body, not ASC/DESC text noise.
                        col_ref = (
                            normalized_sql.rsplit(' ', 1)[0]
                            if normalized_sql.rstrip().endswith(('ASC', 'DESC'))
                            else normalized_sql
                        )
                        col_ref_upper = col_ref.upper()
                        is_qualified = '.' in col_ref and '(' not in col_ref
                        col_name = col_ref.rsplit('.', 1)[-1].upper() if is_qualified else col_ref_upper
                        if col_ref_upper in seen_full:
                            continue
                        if is_qualified and col_name in seen_unqualified:
                            continue
                        seen_full.add(col_ref_upper)
                        if not is_qualified:
                            seen_unqualified.add(col_name)
                        ordering.append(normalized_sql)
                        params.extend(normalized_params)
                if ordering:
                    result.append('ORDER BY %s' % ', '.join(ordering))
                else:
                    order_by = []
                    if do_offset and supports_offset_clause:
                        meta = self.query.get_meta()
                        qn = self.quote_name_unless_alias
                        result.append(
                            'ORDER BY %s.%s ASC' % (
                                qn(meta.db_table),
                                qn(meta.pk.db_column or meta.pk.column),
                            )
                        )

                # For subqueres with an ORDER BY clause, SQL Server also
                # requires a TOP or OFFSET clause which is not generated for
                # Django 2.x.  See https://github.com/microsoft/mssql-django/issues/12
                # Add OFFSET for all Django versions.
                # https://github.com/microsoft/mssql-django/issues/109
                if ordering and not (do_offset or do_limit) and supports_offset_clause:
                    result.append("OFFSET 0 ROWS")

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
        # SQL server does not allow subqueries or constant expressions in the group by
        # For constants: Each GROUP BY expression must contain at least one column that is not an outer reference.
        # For subqueries: Cannot use an aggregate or a subquery in an expression used for the group by list of a GROUP BY clause.
        return self._filter_subquery_and_constant_expressions(expressions)

    def _is_constant_expression(self, expression):
        if expression is None:
            return False
        if isinstance(expression, Value):
            return True
        if not hasattr(expression, 'get_source_expressions'):
            return False
        sub_exprs = expression.get_source_expressions()
        if not sub_exprs:
            return False
        for each in sub_exprs:
            if each is None:
                return False
            if not self._is_constant_expression(each):
                return False
        return True



    def _filter_subquery_and_constant_expressions(self, expressions):
        ret = []
        for expression in expressions:
            if self._is_subquery(expression):
                continue
            if self._is_constant_expression(expression):
                continue
            if not self._has_nested_subquery(expression):
                ret.append(expression)
        return ret

    def _has_nested_subquery(self, expression):
        if self._is_subquery(expression):
            return True
        for sub_expr in expression.get_source_expressions():
            if self._has_nested_subquery(sub_expr):
                return True
        return False

    def _is_subquery(self, expression):
        return isinstance(expression, Subquery)

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
        elif django.VERSION >= (6, 0) and isinstance(node, StringAgg):
            as_microsoft = _as_sql_stringagg
        if django.VERSION >= (3, 1):
            if isinstance(node, json_KeyTransform):
                as_microsoft = _as_sql_json_keytransform
        if django.VERSION >= (4, 1):
            if isinstance(node, Window):
                as_microsoft = _as_sql_window
        if as_microsoft:
            node = node.copy()
            node.as_microsoft = types.MethodType(as_microsoft, node)
        return node


class SQLInsertCompiler(compiler.SQLInsertCompiler, SQLCompiler):
    def get_returned_fields(self):
        if django.VERSION >= (3, 0, 0):
            return self.returning_fields
        return self.return_id

    def can_return_columns_from_insert(self):
        if django.VERSION >= (3, 0, 0):
            return self.connection.features.can_return_columns_from_insert
        return self.connection.features.can_return_id_from_insert

    def can_return_rows_from_bulk_insert(self):
        if django.VERSION >= (3, 0, 0):
            return self.connection.features.can_return_rows_from_bulk_insert
        return self.connection.features.can_return_ids_from_bulk_insert

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

    def bulk_insert_default_values_sql(self, table):
        seed_rows_number = 8
        cross_join_power = 4  # 8^4 = 4096 > maximum allowed batch size for the backend = 1000

        def generate_seed_rows(n):
            return " UNION ALL ".join("SELECT 1 AS x" for _ in range(n))

        def cross_join(p):
            return ", ".join("SEED_ROWS AS _%s" % i for i in range(p))

        return """
        WITH SEED_ROWS AS (%s)
            MERGE INTO %s
            USING (
                SELECT TOP %s * FROM (SELECT 1 as x FROM %s) FAKE_ROWS
            ) FAKE_DATA
            ON 1 = 0
            WHEN NOT MATCHED THEN
            INSERT DEFAULT VALUES
        """ % (generate_seed_rows(seed_rows_number),
               table,
               len(self.query.objs),
               cross_join(cross_join_power))

    def as_sql(self):
        # We don't need quote_name_unless_alias() here, since these are all
        # going to be column names (so we can avoid the extra overhead).
        qn = self.connection.ops.quote_name
        opts = self.query.get_meta()
        result = ['INSERT INTO %s' % qn(opts.db_table)]

        if self.query.fields:
            fields = list(self.query.fields)
            supports_default_keyword_in_bulk_insert = (
                self.connection.features.supports_default_keyword_in_bulk_insert
            )
            result.append('(%s)' % ', '.join(qn(f.column) for f in fields))
            values_format = 'VALUES (%s)'

            if django.VERSION < (6, 0):
                value_rows = [
                    [self.prepare_value(field, self.pre_save_val(field, obj)) for field in fields]
                    for obj in self.query.objs
                ]
            else:
                from django.db.models.expressions import DatabaseDefault

                value_cols = []
                for field in list(fields):
                    field_prepare = partial(self.prepare_value, field)
                    field_pre_save = partial(self.pre_save_val, field)
                    field_values = [
                        field_prepare(field_pre_save(obj)) for obj in self.query.objs
                    ]

                    if not field.has_db_default():
                        value_cols.append(field_values)
                        continue

                    if len(fields) > 1 and all(
                        isinstance(value, DatabaseDefault) for value in field_values
                    ):
                        fields.remove(field)
                        continue

                    if supports_default_keyword_in_bulk_insert:
                        value_cols.append(field_values)
                        continue

                    prepared_db_default = field_prepare(field.db_default)
                    field_values = [
                        prepared_db_default
                        if isinstance(value, DatabaseDefault)
                        else value
                        for value in field_values
                    ]
                    value_cols.append(field_values)
                value_rows = list(zip(*value_cols))
                result[-1] = '(%s)' % ', '.join(qn(f.column) for f in fields)
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

        if self.get_returned_fields() and self.can_return_columns_from_insert():
            if self.can_return_rows_from_bulk_insert():
                if not(self.query.fields):
                    # There isn't really a single statement to bulk multiple DEFAULT VALUES insertions,
                    # so we have to use a workaround:
                    # https://dba.stackexchange.com/questions/254771/insert-multiple-rows-into-a-table-with-only-an-identity-column
                    result = [self.bulk_insert_default_values_sql(qn(opts.db_table))]
                    r_sql, self.returning_params = self.connection.ops.return_insert_columns(self.get_returned_fields())
                    if r_sql:
                        result.append(r_sql)
                    sql = " ".join(result) + ";"
                    return [(sql, None)]
                # Regular bulk insert
                params = []
                r_sql, self.returning_params = self.connection.ops.return_insert_columns(self.get_returned_fields())
                if r_sql:
                    result.append(r_sql)
                    params += [self.returning_params]
                params += param_rows
                result.append(self.connection.ops.bulk_insert_sql(fields, placeholder_rows))
            else:
                returned_fields = self.get_returned_fields()
                use_scope_identity = (
                    len(returned_fields) == 1 and isinstance(returned_fields[0], AutoField)
                )

                if use_scope_identity:
                    result.insert(0, 'SET NOCOUNT ON')
                    if not self.query.fields:
                        result.append('DEFAULT VALUES;')
                        params = []
                    else:
                        result.append((values_format + ';') % ', '.join(placeholder_rows[0]))
                        params = [param_rows[0]]
                    result.append('SELECT CAST(SCOPE_IDENTITY() AS bigint)')
                else:
                    params = []
                    table_name = qn(opts.db_table)
                    tmp_table_name = '#django_returning_insert'
                    returned_columns = ', '.join(qn(field.column) for field in returned_fields)
                    select_into_columns = []
                    for field in returned_fields:
                        column_sql = qn(field.column)
                        if isinstance(field, AutoField):
                            select_into_columns.append(f'CAST({column_sql} AS bigint) AS {column_sql}')
                        else:
                            select_into_columns.append(column_sql)

                    r_sql, self.returning_params = self.connection.ops.return_insert_columns(returned_fields)
                    if r_sql and self.returning_params:
                        params.append(self.returning_params)

                    insert_sql = result[:]
                    if r_sql:
                        insert_sql.append(f'{r_sql} INTO {tmp_table_name}')
                    if not self.query.fields:
                        insert_sql.append('DEFAULT VALUES')
                    else:
                        insert_sql.append(values_format % ', '.join(placeholder_rows[0]))
                        params.append(param_rows[0])

                    sql_batch = '; '.join([
                        'SET NOCOUNT ON',
                        f"IF OBJECT_ID('tempdb..{tmp_table_name}') IS NOT NULL DROP TABLE {tmp_table_name}",
                        f"SELECT TOP 0 {', '.join(select_into_columns)} INTO {tmp_table_name} FROM {table_name}",
                        ' '.join(insert_sql),
                        f'SELECT {returned_columns} FROM {tmp_table_name}',
                        f'DROP TABLE {tmp_table_name}',
                    ])
                    sql = [(sql_batch, tuple(chain.from_iterable(params)))]
                    if self.query.fields:
                        sql = self.fix_auto(sql, opts, fields, qn)
                    return sql
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
