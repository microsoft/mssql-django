# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from django import VERSION
from django.db.models import BooleanField
from django.db.models.functions import Cast
from django.db.models.functions.math import ATan2, Log, Ln, Mod, Round
from django.db.models.expressions import Case, Exists, OrderBy, When
from django.db.models.lookups import Lookup

DJANGO3 = VERSION[0] >= 3


class TryCast(Cast):
    function = 'TRY_CAST'


def sqlserver_atan2(self, compiler, connection, **extra_context):
    return self.as_sql(compiler, connection, function='ATN2', **extra_context)


def sqlserver_log(self, compiler, connection, **extra_context):
    clone = self.copy()
    clone.set_source_expressions(self.get_source_expressions()[::-1])
    return clone.as_sql(compiler, connection, **extra_context)


def sqlserver_ln(self, compiler, connection, **extra_context):
    return self.as_sql(compiler, connection, function='LOG', **extra_context)


def sqlserver_mod(self, compiler, connection):
    # MSSQL doesn't have keyword MOD
    expr = self.get_source_expressions()
    number_a = compiler.compile(expr[0])
    number_b = compiler.compile(expr[1])
    return self.as_sql(
        compiler, connection,
        function="",
        template='(ABS({a}) - FLOOR(ABS({a}) / ABS({b})) * ABS({b})) * SIGN({a}) * SIGN({b})'.format(
            a=number_a[0], b=number_b[0]),
        arg_joiner=""
    )


def sqlserver_round(self, compiler, connection, **extra_context):
    return self.as_sql(compiler, connection, template='%(function)s(%(expressions)s, 0)', **extra_context)


def sqlserver_exists(self, compiler, connection, template=None, **extra_context):
    # MS SQL doesn't allow EXISTS() in the SELECT list, so wrap it with a
    # CASE WHEN expression. Change the template since the When expression
    # requires a left hand side (column) to compare against.
    sql, params = self.as_sql(compiler, connection, template, **extra_context)
    sql = 'CASE WHEN {} THEN 1 ELSE 0 END'.format(sql)
    return sql, params


def sqlserver_lookup(self, compiler, connection):
    # MSSQL doesn't allow EXISTS() to be compared to another expression
    # unless it's wrapped in a CASE WHEN.
    wrapped = False
    exprs = []
    for expr in (self.lhs, self.rhs):
        if isinstance(expr, Exists):
            expr = Case(When(expr, then=True), default=False, output_field=BooleanField())
            wrapped = True
        exprs.append(expr)
    lookup = type(self)(*exprs) if wrapped else self
    return lookup.as_sql(compiler, connection)


def sqlserver_orderby(self, compiler, connection):
    # MSSQL doesn't allow ORDER BY EXISTS() unless it's wrapped in
    # a CASE WHEN.

    template = None
    if self.nulls_last:
        template = 'CASE WHEN %(expression)s IS NULL THEN 1 ELSE 0 END, %(expression)s %(ordering)s'
    if self.nulls_first:
        template = 'CASE WHEN %(expression)s IS NULL THEN 0 ELSE 1 END, %(expression)s %(ordering)s'

    if isinstance(self.expression, Exists):
        copy = self.copy()
        copy.expression = Case(
            When(self.expression, then=True),
            default=False,
            output_field=BooleanField(),
        )
        return copy.as_sql(compiler, connection, template=template)
    return self.as_sql(compiler, connection, template=template)


ATan2.as_microsoft = sqlserver_atan2
Log.as_microsoft = sqlserver_log
Ln.as_microsoft = sqlserver_ln
Mod.as_microsoft = sqlserver_mod
Round.as_microsoft = sqlserver_round

if DJANGO3:
    Lookup.as_microsoft = sqlserver_lookup
else:
    Exists.as_microsoft = sqlserver_exists

OrderBy.as_microsoft = sqlserver_orderby
