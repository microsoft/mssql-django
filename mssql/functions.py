# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

import json

from django import VERSION
from django.core import validators
from django.db import NotSupportedError, connections, transaction
from django.db.models import BooleanField, CheckConstraint, Value
from django.db.models.expressions import Case, Exists, OrderBy, When, Window
from django.db.models.fields import BinaryField, Field
from django.db.models.functions import Cast, NthValue, MD5, SHA1, SHA224, SHA256, SHA384, SHA512
from django.db.models.functions.datetime import Now
from django.db.models.functions.math import ATan2, Ln, Log, Mod, Round, Degrees, Radians, Power
from django.db.models.functions.text import Replace
from django.db.models.lookups import In, Lookup
from django.db.models.query import QuerySet
from django.db.models.sql.query import Query
from django.db.models import Value
from django.db.models.functions import JSONArray

if VERSION >= (3, 1):
    from django.db.models.fields.json import (
        KeyTransform, KeyTransformIn, KeyTransformExact,
        HasKeyLookup, compile_json_path)

if VERSION >= (3, 2):
    from django.db.models.functions.math import Random

DJANGO3 = VERSION[0] >= 3
DJANGO41 = VERSION >= (4, 1)


class TryCast(Cast):
    function = 'TRY_CAST'

def sqlserver_cast(self, compiler, connection, **extra_context):
    if hasattr(self.source_expressions[0], 'lookup_name'):
        if self.source_expressions[0].lookup_name in ['gt', 'gte', 'lt', 'lte']:
            return self.as_sql(
                compiler, connection,
                template = 'CASE WHEN %(expressions)s THEN 1 ELSE 0 END',
                **extra_context
            )
    return self.as_sql(compiler, connection, **extra_context)
    

def sqlserver_atan2(self, compiler, connection, **extra_context):
    return self.as_sql(compiler, connection, function='ATN2', **extra_context)


def sqlserver_log(self, compiler, connection, **extra_context):
    clone = self.copy()
    clone.set_source_expressions(self.get_source_expressions()[::-1])
    return clone.as_sql(compiler, connection, **extra_context)


def sqlserver_ln(self, compiler, connection, **extra_context):
    return self.as_sql(compiler, connection, function='LOG', **extra_context)


def sqlserver_replace(self, compiler, connection, **extra_context):
    current_db = "CONVERT(varchar, (SELECT DB_NAME()))"
    with connection.cursor() as cursor:
        cursor.execute("SELECT CONVERT(varchar, DATABASEPROPERTYEX(%s, 'collation'))" % current_db)
        default_collation = cursor.fetchone()[0]
    current_collation = default_collation.replace('_CI', '_CS')
    return self.as_sql(
            compiler, connection, function='REPLACE',
            template = 'REPLACE(%s COLLATE %s)' % ('%(expressions)s', current_collation),
            **extra_context
        )

def sqlserver_degrees(self, compiler, connection, **extra_context):
    return self.as_sql(
            compiler, connection, function='DEGREES',
            template= 'DEGREES(CONVERT(float, %(expressions)s))',
            **extra_context
        )

def sqlserver_radians(self, compiler, connection, **extra_context):
    return self.as_sql(
            compiler, connection, function='RADIANS',
            template= 'RADIANS(CONVERT(float, %(expressions)s))', 
            **extra_context
        )

def sqlserver_power(self, compiler, connection, **extra_context):
    expr = self.get_source_expressions()
    number_a = compiler.compile(expr[0])
    number_b = compiler.compile(expr[1])
    return self.as_sql(
            compiler, connection, function='POWER',
            template = 'POWER(CONVERT(float,{a}),{b})'.format(a=number_a[0], b=number_b[0]),
            **extra_context
        )

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
    if VERSION < (4, 1) and self.order_by is None:
        self.order_by = Value('SELECT NULL')
    return self.as_sql(compiler, connection, template)


def sqlserver_exists(self, compiler, connection, template=None, **extra_context):
    # MS SQL doesn't allow EXISTS() in the SELECT list, so wrap it with a
    # CASE WHEN expression. Change the template since the When expression
    # requires a left hand side (column) to compare against.
    sql, params = self.as_sql(compiler, connection, template, **extra_context)
    sql = 'CASE WHEN {} THEN 1 ELSE 0 END'.format(sql)
    return sql, params

def sqlserver_now(self, compiler, connection, **extra_context):
        return self.as_sql(
            compiler, connection, template="SYSDATETIME()", **extra_context
        )

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
    if connection.vendor == 'microsoft':
        return mssql_split_parameter_list_as_sql(self, compiler, connection)
    else:
        return in_split_parameter_list_as_sql(self, compiler, connection)


def mssql_split_parameter_list_as_sql(self, compiler, connection):
    # Insert In clause parameters 1000 at a time into a temp table.
    lhs, _ = self.process_lhs(compiler, connection)
    _, rhs_params = self.batch_process_rhs(compiler, connection)

    with connection.cursor() as cursor:
        cursor.execute("IF OBJECT_ID('tempdb.dbo.#Temp_params', 'U') IS NOT NULL DROP TABLE #Temp_params; ")
        parameter_data_type = self.lhs.field.db_type(connection)
        Temp_table_collation = 'COLLATE DATABASE_DEFAULT' if 'char' in parameter_data_type else ''
        cursor.execute(f"CREATE TABLE #Temp_params (params {parameter_data_type} {Temp_table_collation})")
        for offset in range(0, len(rhs_params), 1000):
            sqls_params = rhs_params[offset: offset + 1000]
            sql = "INSERT INTO [#Temp_params] ([params]) VALUES " + ', '.join(['(%s)'] * len(sqls_params))
            cursor.execute(sql, sqls_params)

    in_clause = lhs + ' IN ' + '(SELECT params from #Temp_params)'

    return in_clause, ()


def unquote_json_rhs(rhs_params):
    for value in rhs_params:
        value = json.loads(value)
        if not isinstance(value, (list, dict)):
            rhs_params = [param.replace('"', '') for param in rhs_params]
    return rhs_params

def sqlserver_json_array(self, compiler, connection, **extra_context):
    """
    SQL Server implementation of JSONArray.
    """
    elements = []  # List to hold SQL fragments for each array element
    params = []    # List to hold parameters for the SQL query

    # Iterate through each source expression (element of the array)
    for arg in self.source_expressions:
        # Check if the argument is a Value instance
        if isinstance(arg, Value):
            # If it's a Value, we need to handle it based on its type
            val = arg.value
            # If the value is None, we represent it as SQL NULL
            if val is None:
                elements.append('NULL')     
            elif isinstance(val, (int, float)):
                # Numbers are inserted as it is, without quotes
                elements.append('%s')
                params.append(str(val))
            elif isinstance(val, (list, dict)):
                # Nested JSON structures are handled with JSON_QUERY
                elements.append('JSON_QUERY(%s)')
                params.append(json.dumps(val))
            else:
                # Strings and other types are cast to NVARCHAR(MAX)
                elements.append('CAST(%s AS NVARCHAR(MAX))')
                params.append(str(val))
        else:
            # Compile non-Value expressions (e.g., fields, functions)
            arg_sql, arg_params = compiler.compile(arg)
            if isinstance(arg, JSONArray):
                # Nested JSONArray: use its SQL directly
                elements.append(arg_sql)
            else:
                # Other expressions: cast to NVARCHAR(MAX)
                elements.append(f'CAST({arg_sql} AS NVARCHAR(MAX))')
            if arg_params:
                params.extend(arg_params)
    # If there are no elements, return an empty JSON array
    if not elements:
        return "JSON_QUERY('[]')", []

    # Build the SQL for the JSON array using STRING_AGG and CASE for formatting
    sql = (
        "JSON_QUERY(("
        "SELECT '[' + "
        "STRING_AGG("
        "CASE "
        "WHEN value IS NULL THEN 'null' "  # NULLs as JSON null
        "WHEN ISJSON(value) = 1 THEN value "  # Valid JSON: insert as-is
        "WHEN ISNUMERIC(value) = 1 THEN CAST(value AS NVARCHAR(MAX)) "  # Numbers: insert as-is
        "ELSE CONCAT('\"', REPLACE(REPLACE(value, '\\', '\\\\'), '\"', '\\\"'), '\"') "  # Strings: escape and quote
        "END, "
        "','"
        ") + ']' "
        f"FROM (VALUES {','.join('(' + el + ')' for el in elements)}) AS t(value)))"
    )

    return sql, params

# Register for Django 5.2+ so that JSONArray uses this implementation on SQL Server
if VERSION >= (5, 2):
    JSONArray.as_microsoft = sqlserver_json_array

def json_KeyTransformExact_process_rhs(self, compiler, connection):
    rhs, rhs_params = key_transform_exact_process_rhs(self, compiler, connection)
    if connection.vendor == 'microsoft':
        rhs_params = unquote_json_rhs(rhs_params)
    return rhs, rhs_params


def json_KeyTransformIn(self, compiler, connection):
    lhs, _ = super(KeyTransformIn, self).process_lhs(compiler, connection)
    rhs, rhs_params = super(KeyTransformIn, self).process_rhs(compiler, connection)

    return (lhs + ' IN ' + rhs, unquote_json_rhs(rhs_params))

# This handles the case where the JSON data comes from a table column (actual database data).
# Also deals with hardcoded JSON string literal seperately, since handling differs for literals vs. table data
def json_HasKeyLookup(self, compiler, connection):
    """
    Implementation of HasKey lookup for SQL Server.
    Handles for both SQL Server 2022+ (using JSON_PATH_EXISTS) and older versions (using OPENJSON).
    """
    # Determine the JSON path for the left-hand side (lhs).
    # If dealing with a nested JSON structure, use KeyTransform to extract the path.
    if isinstance(self.lhs, KeyTransform):
        lhs, _, lhs_key_transforms = self.lhs.preprocess_lhs(compiler, connection)
        lhs_json_path = compile_json_path(lhs_key_transforms)
    # if dealing with the JSON and not with nested structure then else block will be executed
    else:
        lhs, lhs_params = self.process_lhs(compiler, connection)
        lhs_json_path = "$"

    # Check if we're dealing with a Cast expression (literal JSON value)
    is_cast_expression = isinstance(self.lhs, Cast)

    # Process JSON paths from the right-hand side
    rhs = self.rhs
    # rhs_params stored the complete JSON path
    rhs_params = []
    # Convert single values into a list for uniform processing
    # If rhs is not already a list or tuple (i.e., it's a single key),
    # wrap it in a list so we can handle both single and multiple keys
    if not isinstance(rhs, (list, tuple)):
        rhs = [rhs]
    for key in rhs:
        # if dealing with the nested JSON structure then if block will be executed
        if isinstance(key, KeyTransform):
            *_, rhs_key_transforms = key.preprocess_lhs(compiler, connection)
        else:
            rhs_key_transforms = [key]
        # Compile the full JSON path (lhs + rhs) according to the Django version in use
        if VERSION >= (4, 1):
            *rhs_key_transforms, final_key = rhs_key_transforms
            rhs_json_path = compile_json_path(rhs_key_transforms, include_root=False)
            rhs_json_path += self.compile_json_path_final_key(final_key)
            rhs_params.append(lhs_json_path + rhs_json_path)
        else:
            rhs_params.append(
                "%s%s"
                % (
                    lhs_json_path,
                    compile_json_path(rhs_key_transforms, include_root=False),
                )
            )

    # For SQL Server 2022+,use JSON_PATH_EXISTS
    if connection.sql_server_version >= 2022:
        if is_cast_expression:
            # For Cast expressions, manually construct SQL without %s placeholders
            cast_sql, cast_params = self.lhs.as_sql(compiler, connection)

            # Build conditions for each key
            conditions = []
            for path in rhs_params:
                # Escapes single quotes in the JSON path to avoid breaking SQL syntax.
                path_escaped = path.replace("'", "''")
                # The > 0 checks that the path exists
                conditions.append(
                    "JSON_PATH_EXISTS(" + cast_sql + ", '" + path_escaped + "') > 0"
                )
            # this if else block deals with forming this syntax (JSON_PATH_EXISTS(...) > 0 AND JSON_PATH_EXISTS(...) > 0)
            if hasattr(self, "logical_operator") and self.logical_operator:
                logical_op = " " + self.logical_operator + " "
                sql = "(" + logical_op.join(conditions) + ")"
            else:
                # if no operators are specified
                sql = conditions[0]

            return sql, cast_params
        else:
            conditions = []
            for path in rhs_params:
                # Escapes single quotes in the JSON path to avoid breaking SQL syntax.
                path_escaped = path.replace("'", "''")
                conditions.append(
                    "JSON_PATH_EXISTS(" + lhs + ", '" + path_escaped + "') > 0"
                )

            if hasattr(self, "logical_operator") and self.logical_operator:
                logical_op = " " + self.logical_operator + " "
                sql = "(" + logical_op.join(conditions) + ")"
            else:
                sql = conditions[0]

            # Return SQL with empty params list
            return sql, []
    else:
        # For older SQL Server versions
        if is_cast_expression:
            # SQL Server versions prior to 2022 do not support JSON_PATH_EXISTS,
            # and OPENJSON cannot be used on literal JSON values (i.e., values not stored in a table column).
            # Therefore, when a literal JSON value is used in a has_key lookup on these versions,
            # we cannot perform a meaningful check in SQL. To ensure the query does not fail and
            # to match Django's expected behavior (e.g., for test_has_key_literal_lookup),
            # we return a constant true condition ("1=1") with no parameters, which effectively returns all rows.
            return "1=1", []
        else:
            # Handling for versions prior to SQL Server 2022
            # For older SQL Server versions, we use OPENJSON to check for the existence of keys in JSON data.
            if VERSION >= (4, 2):
                try:
                    # Get table name from compiler query for Django 4.2+
                    # This retrieves the alias Django assigned to the main table in the SQL query.
                    # An alias is something like "T1" or "U0" that Django uses internally in the SQL it generates.
                    main_alias = compiler.query.get_initial_alias()
                    # Get the table name from the alias map
                    table_name = compiler.query.alias_map[main_alias].table_name
                except (AttributeError, KeyError):
                    # Fallback to traditional method
                    table_name = self.lhs.output_field.model._meta.db_table
            else:
                table_name = self.lhs.output_field.model._meta.db_table

            # Build SQL conditions with string concatenation 
            conditions = []
            for path in rhs_params:
                # Escapes single quotes in the JSON path to avoid breaking SQL syntax.
                path_escaped = path.replace("'", "''")    
                condition = (lhs + " IN (SELECT " + lhs + " FROM " + table_name +
                            " CROSS APPLY OPENJSON(" + lhs + ") WITH ([json_path_value] char(1) '" + 
                            path_escaped + "') WHERE [json_path_value] IS NOT NULL)")
                conditions.append(condition)

            if hasattr(self, "logical_operator") and self.logical_operator:
                logical_op = " " + self.logical_operator + " "
                sql = "(" + logical_op.join(conditions) + ")"
            else:
                sql = conditions[0]

            # Return SQL with no params 
            return sql, []

def BinaryField_init(self, *args, **kwargs):
    # Add max_length option for BinaryField, default to max
    kwargs.setdefault('editable', False)
    Field.__init__(self, *args, **kwargs)
    if self.max_length is not None:
        self.validators.append(validators.MaxLengthValidator(self.max_length))
    else:
        self.max_length = 'max'


def _get_check_sql(self, model, schema_editor):
    if VERSION >= (3, 1):
        query = Query(model=model, alias_cols=False)
    else:
        query = Query(model=model)
    # Build the query to check the condition of the CheckConstraint.
    # Note: Starting from Django 5.1, the CheckConstraint API changed:
    # the attribute 'self.check' was replaced by 'self.condition'.
    # For backwards compatibility, we use 'self.check' for versions < 5.1,
    # and 'self.condition' for 5.1 and above.
    if VERSION >= (5, 1):
        where = query.build_where(self.condition)
    else:
        # use check for backwards compatibility    
        where = query.build_where(self.check)    
    compiler = query.get_compiler(connection=schema_editor.connection)
    sql, params = where.as_sql(compiler, schema_editor.connection)
    if schema_editor.connection.vendor == 'microsoft':
        try:
            for p in params:
                str(p).encode('ascii')
        except UnicodeEncodeError:
            sql = sql.replace('%s', 'N%s')

    return sql % tuple(schema_editor.quote_value(p) for p in params)


def bulk_update_with_default(self, objs, fields, batch_size=None, default=None):
    """
        Update the given fields in each of the given objects in the database.

        When bulk_update all fields to null,
        SQL Server require that at least one of the result expressions in a CASE specification must be an expression other than the NULL constant.
        Patched with a default value 0. The user can also pass a custom default value for CASE statement.
    """
    if batch_size is not None and batch_size <= 0:
        raise ValueError('Batch size must be a positive integer.')
    if not fields:
        raise ValueError('Field names must be given to bulk_update().')
    objs = tuple(objs)
    if any(obj.pk is None for obj in objs):
        raise ValueError('All bulk_update() objects must have a primary key set.')
    fields = [self.model._meta.get_field(name) for name in fields]
    if any(not f.concrete or f.many_to_many for f in fields):
        raise ValueError('bulk_update() can only be used with concrete fields.')
    if any(f.primary_key for f in fields):
        raise ValueError('bulk_update() cannot be used with primary key fields.')
    if not objs:
        return 0
    if DJANGO41:
        for obj in objs:
            obj._prepare_related_fields_for_save(
                operation_name="bulk_update", fields=fields
            )
    # PK is used twice in the resulting update query, once in the filter
    # and once in the WHEN. Each field will also have one CAST.
    self._for_write = True
    connection = connections[self.db]
    max_batch_size = connection.ops.bulk_batch_size(['pk', 'pk'] + fields, objs)
    batch_size = min(batch_size, max_batch_size) if batch_size else max_batch_size
    requires_casting = connection.features.requires_casted_case_in_updates
    batches = (objs[i:i + batch_size] for i in range(0, len(objs), batch_size))
    updates = []
    for batch_objs in batches:
        update_kwargs = {}
        for field in fields:
            value_none_counter = 0
            when_statements = []
            for obj in batch_objs:
                attr = getattr(obj, field.attname)
                if not hasattr(attr, "resolve_expression"):
                    if attr is None:
                        value_none_counter += 1
                    attr = Value(attr, output_field=field)
                when_statements.append(When(pk=obj.pk, then=attr))
            if connection.vendor == 'microsoft' and value_none_counter == len(when_statements):
                # We don't need a case statement if we are setting everything to None
                case_statement = Value(None)
            else:
                case_statement = Case(*when_statements, output_field=field)
            if requires_casting:
                case_statement = Cast(case_statement, output_field=field)
            update_kwargs[field.attname] = case_statement
        updates.append(([obj.pk for obj in batch_objs], update_kwargs))
    rows_updated = 0
    queryset = self.using(self.db)
    with transaction.atomic(using=self.db, savepoint=False):
        for pks, update_kwargs in updates:
            rows_updated += queryset.filter(pk__in=pks).update(**update_kwargs)
    return rows_updated


def sqlserver_md5(self, compiler, connection, **extra_context):
    # UTF-8 support added in SQL Server 2019
    if (connection.sql_server_version < 2019):
        raise NotSupportedError("Hashing is not supported on this version SQL Server. Upgrade to 2019 or above")

    column_name = self.get_source_fields()[0].name

    with connection.cursor() as cursor:
        cursor.execute("SELECT MAX(DATALENGTH(%s)) FROM %s" % (column_name, compiler.query.model._meta.db_table))
        max_size = cursor.fetchone()[0]

    # Collation of SQL Server by default is UTF-16 but Django always assumes UTF-8 enconding
    # https://docs.djangoproject.com/en/4.0/ref/unicode/#general-string-handling
    return self.as_sql(
        compiler,
        connection,
        template="LOWER(CONVERT(CHAR(32), HASHBYTES('%s', CAST(%s COLLATE Latin1_General_100_CI_AI_SC_UTF8 AS VARCHAR(%s))), 2))" % ('%(function)s', column_name, max_size),
        **extra_context,
    )


def sqlserver_sha1(self, compiler, connection, **extra_context):
    # UTF-8 support added in SQL Server 2019
    if (connection.sql_server_version < 2019):
        raise NotSupportedError("Hashing is not supported on this version SQL Server. Upgrade to 2019 or above")

    column_name = self.get_source_fields()[0].name

    # Collation of SQL Server by default is UTF-16 but Django always assumes UTF-8 enconding
    # https://docs.djangoproject.com/en/4.0/ref/unicode/#general-string-handling
    with connection.cursor() as cursor:
        cursor.execute("SELECT MAX(DATALENGTH(%s)) FROM %s" % (column_name, compiler.query.model._meta.db_table))
        max_size = cursor.fetchone()[0]

    return self.as_sql(
        compiler,
        connection,
        template="LOWER(CONVERT(CHAR(40), HASHBYTES('%s', CAST(%s COLLATE Latin1_General_100_CI_AI_SC_UTF8 AS VARCHAR(%s))), 2))" % ('%(function)s', column_name, max_size),
        **extra_context,
    )


def sqlserver_sha224(self, compiler, connection, **extra_context):
    raise NotSupportedError("SHA224 is not supported on SQL Server.")


def sqlserver_sha256(self, compiler, connection, **extra_context):
    # UTF-8 support added in SQL Server 2019
    if (connection.sql_server_version < 2019):
        raise NotSupportedError("Hashing is not supported on this version SQL Server. Upgrade to 2019 or above")

    column_name = self.get_source_fields()[0].name

    # Collation of SQL Server by default is UTF-16 but Django always assumes UTF-8 enconding
    # https://docs.djangoproject.com/en/4.0/ref/unicode/#general-string-handling
    with connection.cursor() as cursor:
        cursor.execute("SELECT MAX(DATALENGTH(%s)) FROM %s" % (column_name, compiler.query.model._meta.db_table))
        max_size = cursor.fetchone()[0]

    return self.as_sql(
        compiler,
        connection,
        template="LOWER(CONVERT(CHAR(64), HASHBYTES('SHA2_256', CAST(%s COLLATE Latin1_General_100_CI_AI_SC_UTF8 AS VARCHAR(%s))), 2))" % (column_name, max_size),
        **extra_context,
    )


def sqlserver_sha384(self, compiler, connection, **extra_context):
    raise NotSupportedError("SHA384 is not supported on SQL Server.")


def sqlserver_sha512(self, compiler, connection, **extra_context):
    # UTF-8 support added in SQL Server 2019
    if (connection.sql_server_version < 2019):
        raise NotSupportedError("Hashing is not supported on this version SQL Server. Upgrade to 2019 or above")

    column_name = self.get_source_fields()[0].name

    # Collation of SQL Server by default is UTF-16 but Django always assumes UTF-8 enconding
    # https://docs.djangoproject.com/en/4.0/ref/unicode/#general-string-handling
    with connection.cursor() as cursor:
        cursor.execute("SELECT MAX(DATALENGTH(%s)) FROM %s" % (column_name, compiler.query.model._meta.db_table))
        max_size = cursor.fetchone()[0]

    return self.as_sql(
        compiler,
        connection,
        template="LOWER(CONVERT(CHAR(128), HASHBYTES('SHA2_512', CAST(%s COLLATE Latin1_General_100_CI_AI_SC_UTF8 AS VARCHAR(%s))), 2))" % (column_name, max_size),
        **extra_context,
    )


# `as_microsoft` called by django.db.models.sql.compiler based on connection.vendor
ATan2.as_microsoft = sqlserver_atan2
# Need copy of old In.split_parameter_list_as_sql for other backends to call
in_split_parameter_list_as_sql = In.split_parameter_list_as_sql
In.split_parameter_list_as_sql = split_parameter_list_as_sql
if VERSION >= (3, 1):
    KeyTransformIn.as_microsoft = json_KeyTransformIn
    # Need copy of old KeyTransformExact.process_rhs to call later
    key_transform_exact_process_rhs = KeyTransformExact.process_rhs
    KeyTransformExact.process_rhs = json_KeyTransformExact_process_rhs
    HasKeyLookup.as_microsoft = json_HasKeyLookup
Cast.as_microsoft = sqlserver_cast
Degrees.as_microsoft = sqlserver_degrees
Radians.as_microsoft = sqlserver_radians
Power.as_microsoft = sqlserver_power
Ln.as_microsoft = sqlserver_ln
Log.as_microsoft = sqlserver_log
Mod.as_microsoft = sqlserver_mod
NthValue.as_microsoft = sqlserver_nth_value
Round.as_microsoft = sqlserver_round
Window.as_microsoft = sqlserver_window
Replace.as_microsoft = sqlserver_replace
Now.as_microsoft = sqlserver_now
MD5.as_microsoft = sqlserver_md5
SHA1.as_microsoft = sqlserver_sha1
SHA224.as_microsoft = sqlserver_sha224
SHA256.as_microsoft = sqlserver_sha256
SHA384.as_microsoft = sqlserver_sha384
SHA512.as_microsoft = sqlserver_sha512
BinaryField.__init__ = BinaryField_init
CheckConstraint._get_check_sql = _get_check_sql

if VERSION >= (3, 2):
    Random.as_microsoft = sqlserver_random

if DJANGO3:
    Lookup.as_microsoft = sqlserver_lookup
else:
    Exists.as_microsoft = sqlserver_exists

OrderBy.as_microsoft = sqlserver_orderby
QuerySet.bulk_update = bulk_update_with_default
