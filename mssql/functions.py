# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json

from django import VERSION
from django.db import NotSupportedError
from django.db.models import BooleanField, Value
from django.db.models.functions import Cast, NthValue
from django.db.models.functions.math import ATan2, Log, Ln, Mod, Round
from django.db.models.expressions import Case, Exists, OrderBy, When, Window
from django.db.models.lookups import Lookup, In
from django.db.models import lookups
from django.db.models.fields import BinaryField, Field
from django.core import validators

if VERSION >= (3, 1):
    from django.db.models.fields.json import (
        KeyTransform, KeyTransformIn, KeyTransformExact,
        HasKeyLookup, compile_json_path)

if VERSION >= (3, 2):
    from django.db.models.functions.math import Random

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


def sqlserver_nth_value(self, compiler, connection, **extra_content):
    raise NotSupportedError('This backend does not support the NthValue function')


def sqlserver_round(self, compiler, connection, **extra_context):
    return self.as_sql(compiler, connection, template='%(function)s(%(expressions)s, 0)', **extra_context)

def sqlserver_random(self, compiler, connection, **extra_context):
    return self.as_sql(compiler, connection, function='RAND', **extra_context)

def sqlserver_window(self, compiler, connection, template=None):
    # MSSQL window functions require an OVER clause with ORDER BY
    if self.order_by is None:
        self.order_by = Value('SELECT NULL')
    return self.as_sql(compiler, connection, template)


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
    template = None
    if self.nulls_last:
        template = 'CASE WHEN %(expression)s IS NULL THEN 1 ELSE 0 END, %(expression)s %(ordering)s'
    if self.nulls_first:
        template = 'CASE WHEN %(expression)s IS NULL THEN 0 ELSE 1 END, %(expression)s %(ordering)s'

    copy = self.copy()

    # Prevent OrderBy.as_sql() from modifying supplied templates
    copy.nulls_first = False
    copy.nulls_last = False

    # MSSQL doesn't allow ORDER BY EXISTS() unless it's wrapped in a CASE WHEN.
    if isinstance(self.expression, Exists):
        copy.expression = Case(
            When(self.expression, then=True),
            default=False,
            output_field=BooleanField(),
        )

    return copy.as_sql(compiler, connection, template=template)


def split_parameter_list_as_sql(self, compiler, connection):
    # Insert In clause parameters 1000 at a time into a temp table.
    lhs, _ = self.process_lhs(compiler, connection)
    _, rhs_params = self.batch_process_rhs(compiler, connection)

    with connection.cursor() as cursor:
        cursor.execute("IF OBJECT_ID('tempdb.dbo.#Temp_params', 'U') IS NOT NULL DROP TABLE #Temp_params; ")
        parameter_data_type = self.lhs.field.db_type(connection)
        cursor.execute(f"CREATE TABLE #Temp_params (params {parameter_data_type})")
        for offset in range(0, len(rhs_params), 1000):
            sqls_params = rhs_params[offset: offset + 1000]
            sqls_params = ", ".join("('{}')".format(item) for item in sqls_params)
            cursor.execute("INSERT INTO #Temp_params VALUES %s" % sqls_params)

    in_clause = lhs + ' IN ' + '(SELECT params from #Temp_params)'

    return in_clause, ()

def unquote_json_rhs(rhs_params):
    for value in rhs_params:
        value = json.loads(value)
        if not isinstance(value, (list, dict)):
            rhs_params = [param.replace('"', '') for param in rhs_params]
    return rhs_params

def json_KeyTransformExact_process_rhs(self, compiler, connection):
    if isinstance(self.rhs, KeyTransform):
        return super(lookups.Exact, self).process_rhs(compiler, connection)
    rhs, rhs_params = super(KeyTransformExact, self).process_rhs(compiler, connection)

    return rhs, unquote_json_rhs(rhs_params)

def json_KeyTransformIn(self, compiler, connection):
    lhs, _ = super(KeyTransformIn, self).process_lhs(compiler, connection)
    rhs, rhs_params = super(KeyTransformIn, self).process_rhs(compiler, connection)

    return (lhs + ' IN ' + rhs, unquote_json_rhs(rhs_params))

def json_HasKeyLookup(self, compiler, connection):
    # Process JSON path from the left-hand side.
    if isinstance(self.lhs, KeyTransform):
        lhs, _, lhs_key_transforms = self.lhs.preprocess_lhs(compiler, connection)
        lhs_json_path = compile_json_path(lhs_key_transforms)
    else:
        lhs, _ = self.process_lhs(compiler, connection)
        lhs_json_path = '$'
    sql = lhs + ' IN (SELECT ' + lhs + ' FROM ' + self.lhs.output_field.model._meta.db_table + \
    ' CROSS APPLY OPENJSON(' + lhs + ') WITH ( [json_path_value] char(1) \'%s\') WHERE [json_path_value] IS NOT NULL)'
    # Process JSON path from the right-hand side.
    rhs = self.rhs
    rhs_params = []
    if not isinstance(rhs, (list, tuple)):
        rhs = [rhs]
    for key in rhs:
        if isinstance(key, KeyTransform):
            *_, rhs_key_transforms = key.preprocess_lhs(compiler, connection)
        else:
            rhs_key_transforms = [key]
        rhs_params.append('%s%s' % (
            lhs_json_path,
            compile_json_path(rhs_key_transforms, include_root=False),
        ))
    # Add condition for each key.
    if self.logical_operator:
        sql = '(%s)' % self.logical_operator.join([sql] * len(rhs_params))

    return sql % tuple(rhs_params), []

def BinaryField_init(self, *args, **kwargs):
    # Add max_length option for BinaryField, default to max
    kwargs.setdefault('editable', False)
    Field.__init__(self, *args, **kwargs)
    if self.max_length is not None:
        self.validators.append(validators.MaxLengthValidator(self.max_length))
    else:
        self.max_length = 'max'

ATan2.as_microsoft = sqlserver_atan2
In.split_parameter_list_as_sql = split_parameter_list_as_sql
if VERSION >= (3, 1):
    KeyTransformIn.as_microsoft = json_KeyTransformIn
    KeyTransformExact.process_rhs = json_KeyTransformExact_process_rhs
    HasKeyLookup.as_microsoft = json_HasKeyLookup
Ln.as_microsoft = sqlserver_ln
Log.as_microsoft = sqlserver_log
Mod.as_microsoft = sqlserver_mod
NthValue.as_microsoft = sqlserver_nth_value
Round.as_microsoft = sqlserver_round
Window.as_microsoft = sqlserver_window
BinaryField.__init__ = BinaryField_init

if VERSION >= (3, 2):
    Random.as_microsoft = sqlserver_random

if DJANGO3:
    Lookup.as_microsoft = sqlserver_lookup
else:
    Exists.as_microsoft = sqlserver_exists

OrderBy.as_microsoft = sqlserver_orderby

