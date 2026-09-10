# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from django.db import DatabaseError
import pyodbc as Database

from collections import namedtuple

from django import VERSION
from django.db.backends.base.introspection import BaseDatabaseIntrospection
from django.db.backends.base.introspection import FieldInfo as BaseFieldInfo
from django.db.backends.base.introspection import TableInfo as BaseTableInfo
from django.db.models.indexes import Index
from django.db.models import DO_NOTHING
from django.conf import settings

from mssql.parser import parse_multipart_identifier, build_multipart_name

SQL_AUTOFIELD = -777555
SQL_BIGAUTOFIELD = -777444
SQL_SMALLAUTOFIELD = -777333
SQL_TIMESTAMP_WITH_TIMEZONE = -155

FieldInfo = namedtuple("FieldInfo", BaseFieldInfo._fields + ("comment",))
TableInfo = namedtuple("TableInfo", BaseTableInfo._fields + ("comment",))

def get_schema_name():
    if hasattr(settings, 'SCHEMA_TO_INSPECT'):
        return getattr(settings, 'SCHEMA_TO_INSPECT')
    return None

def get_table_name_with_schema(table_name):
    # This takes into account that doing
    # db_table = '[schema].[table_name]'
    # is supported
    
    _, _, schema_name, table_name = parse_multipart_identifier(table_name)

    if schema_name is not None:
        return f"'{schema_name}'", table_name

    return getattr(settings, 'SCHEMA_TO_INSPECT', 'SCHEMA_NAME()'), table_name


class DatabaseIntrospection(BaseDatabaseIntrospection):
    # Map type codes to Django Field types.
    data_types_reverse = {
        SQL_AUTOFIELD: 'AutoField',
        SQL_BIGAUTOFIELD: 'BigAutoField',
        SQL_SMALLAUTOFIELD: 'SmallAutoField',
        Database.SQL_BIGINT: 'BigIntegerField',
        # Database.SQL_BINARY:            ,
        Database.SQL_BIT: 'BooleanField',
        Database.SQL_CHAR: 'CharField',
        Database.SQL_DECIMAL: 'DecimalField',
        Database.SQL_DOUBLE: 'FloatField',
        Database.SQL_FLOAT: 'FloatField',
        Database.SQL_GUID: 'TextField',
        Database.SQL_INTEGER: 'IntegerField',
        Database.SQL_LONGVARBINARY: 'BinaryField',
        # Database.SQL_LONGVARCHAR:       ,
        Database.SQL_NUMERIC: 'DecimalField',
        Database.SQL_REAL: 'FloatField',
        Database.SQL_SMALLINT: 'SmallIntegerField',
        Database.SQL_SS_TIME2: 'TimeField',
        Database.SQL_TINYINT: 'SmallIntegerField',
        Database.SQL_TYPE_DATE: 'DateField',
        Database.SQL_TYPE_TIME: 'TimeField',
        Database.SQL_TYPE_TIMESTAMP: 'DateTimeField',
        SQL_TIMESTAMP_WITH_TIMEZONE: 'DateTimeField',
        Database.SQL_VARBINARY: 'BinaryField',
        Database.SQL_VARCHAR: 'TextField',
        Database.SQL_WCHAR: 'CharField',
        Database.SQL_WLONGVARCHAR: 'TextField',
        Database.SQL_WVARCHAR: 'TextField',
    }

    ignored_tables = []

    def get_field_type(self, data_type, description):
        field_type = super().get_field_type(data_type, description)
        # the max nvarchar length is described as 0 or 2**30-1
        # (it depends on the driver)
        size = description.internal_size
        if field_type == 'CharField':
            if size == 0 or size >= 2**30 - 1:
                field_type = "TextField"
        elif field_type == 'TextField':
            if size > 0 and size < 2**30 - 1:
                field_type = 'CharField'
        return field_type

    def get_table_list(self, cursor):
        """
        Returns a list of table and view names in the current database.
        """
        if VERSION >= (4, 2) and self.connection.features.supports_comments:
            sql = """SELECT
                        TABLE_SCHEMA,
                        TABLE_NAME,
                        TABLE_TYPE,
                        CAST(ep.value AS VARCHAR) AS COMMENT
                    FROM INFORMATION_SCHEMA.TABLES i
                    LEFT JOIN sys.tables t ON t.name = i.TABLE_NAME
                    LEFT JOIN sys.extended_properties ep ON t.object_id = ep.major_id
                    AND ((ep.name = 'MS_DESCRIPTION' AND ep.minor_id = 0) OR ep.value IS NULL)
                    """
        else:
            sql = 'SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES'

        schema = get_schema_name()
        if schema:
            sql += f" WHERE TABLE_SCHEMA = {schema}"

        cursor.execute(sql)
        types = {'BASE TABLE': 't', 'VIEW': 'v'}
        rows = cursor.fetchall()

        def create_table_name(schema, table_name):
            # Why do we do this?
            # We only use the table name (ie `[table_1]` or `table_1`)
            # if the schema is `dbo` because this package defaults to 
            # dbo for its schema. Therefore django models without a
            # specified schema (eg `django_migrations`) will fall in 
            # `dbo`. However django expects the found table name 
            # to be `django_migrations` NOT `dbo.django_migrations`
            # For the same reason, `build_multipart_name` only adds
            # braces when brace escaping is used
            if schema == 'dbo':
                return build_multipart_name(table_name)
            return build_multipart_name(schema, table_name)

        if VERSION >= (4, 2) and self.connection.features.supports_comments:
            return [TableInfo(create_table_name(row[0], row[1]), types.get(row[2]), row[3])
                    for row in rows
                    if row[1] not in self.ignored_tables]
        else:
            return [BaseTableInfo(create_table_name(row[0], row[1]), types.get(row[2]))
                    for row in rows
                    if row[1] not in self.ignored_tables]

    def identifier_converter(self, name):
        """
        Apply a conversion to the identifier for the purposes of comparison.

        The default identifier converter is for case sensitive comparison.
        """
        prefix = '[dbo].['
        suffix = ']'
        if name is not None and name.startswith(prefix) and name.endswith(suffix):
            name = name[len(prefix):-len(suffix)]
        return name

    def _is_auto_field(self, cursor, table_name, column_name):
        """
        Checks whether column is Identity
        """
        # COLUMNPROPERTY: http://msdn2.microsoft.com/en-us/library/ms174968.aspx

        # from django.db import connection
        # cursor.execute("SELECT COLUMNPROPERTY(OBJECT_ID(%s), %s, 'IsIdentity')",
        #                 (connection.ops.quote_name(table_name), column_name))
        cursor.execute("SELECT COLUMNPROPERTY(OBJECT_ID(%s), %s, 'IsIdentity')",
                       (self.connection.ops.quote_name(table_name), column_name))
        return cursor.fetchall()[0][0]

    def get_table_description(self, cursor, table_name, identity_check=True):
        """Returns a description of the table, with DB-API cursor.description interface.

        The 'auto_check' parameter has been added to the function argspec.
        If set to True, the function will check each of the table's fields for the
        IDENTITY property (the IDENTITY property is the MSSQL equivalent to an AutoField).

        When an integer field is found with an IDENTITY property, it is given a custom field number
        of SQL_AUTOFIELD, which maps to the 'AutoField' value in the DATA_TYPES_REVERSE dict.

        When a bigint field is found with an IDENTITY property, it is given a custom field number
        of SQL_BIGAUTOFIELD, which maps to the 'BigAutoField' value in the DATA_TYPES_REVERSE dict.
        """

        # map pyodbc's cursor.columns to db-api cursor description
        schema_name, table_name = get_table_name_with_schema(table_name=table_name)
        columns = [[c[3], c[4], c[6], c[6], c[6], c[8], c[10], c[12]] for c in cursor.columns(table=table_name, schema=schema_name[1:-1])]

        if not columns:
            raise DatabaseError(f"Table {table_name} does not exist.")

        items = []
        for column in columns:
            if VERSION >= (3, 2):
                if self.connection.sql_server_version >= 2019:
                    sql = """SELECT collation_name
                            FROM sys.columns c
                            inner join sys.tables t on c.object_id = t.object_id
                            WHERE t.name = '%s' and c.name = '%s'
                            """ % (table_name, column[0])
                    cursor.execute(sql)
                    collation_name = cursor.fetchone()
                    column.append(collation_name[0] if collation_name else '')
                else:
                    column.append('')
            if VERSION >= (4, 2) and self.connection.features.supports_comments:
                sql = """select CAST(ep.value AS VARCHAR) AS COMMENT
                        FROM sys.columns c
                        INNER JOIN sys.tables t ON c.object_id = t.object_id
                        INNER JOIN sys.extended_properties ep ON c.object_id=ep.major_id AND ep.minor_id = c.column_id
                        WHERE t.name = '%s' AND c.name = '%s' AND ep.name = 'MS_Description'
                        """ % (table_name, column[0])
                cursor.execute(sql)
                comment = cursor.fetchone()
                column.append(comment[0] if comment else '')
            if identity_check and self._is_auto_field(cursor, table_name, column[0]):
                if column[1] == Database.SQL_BIGINT:
                    column[1] = SQL_BIGAUTOFIELD
                elif column[1] == Database.SQL_SMALLINT:
                    column[1] = SQL_SMALLAUTOFIELD
                else:
                    column[1] = SQL_AUTOFIELD
            if column[1] == Database.SQL_WVARCHAR and column[3] < 4000:
                column[1] = Database.SQL_WCHAR
            # Remove surrounding parentheses for default values
            if column[7]:
                default_value = column[7]
                start = 0
                end = -1
                for _ in range(2):
                    if default_value[start] == '(' and default_value[end] == ')':
                        start += 1
                        end -= 1
                column[7] = default_value[start:end + 1]
            if VERSION >= (4, 2) and self.connection.features.supports_comments:
                items.append(FieldInfo(*column))
            else:
                items.append(BaseFieldInfo(*column))
        return items

    def get_sequences(self, cursor, table_name, table_fields=()):
        schema_name, table_name = get_table_name_with_schema(table_name=table_name)

        cursor.execute(f"""
            SELECT c.name FROM sys.columns c
            INNER JOIN sys.tables t ON c.object_id = t.object_id
            WHERE t.schema_id = SCHEMA_ID({schema_name}) AND t.name = %s AND c.is_identity = 1""",
                       [table_name])
        # SQL Server allows only one identity column per table
        # https://docs.microsoft.com/en-us/sql/t-sql/statements/create-table-transact-sql-identity-property
        row = cursor.fetchone()
        return [{'table': table_name, 'column': row[0]}] if row else []

    def get_relations(self, cursor, table_name):
        """
        Returns a dictionary of {field_name: (field_name_other_table, other_table)}
        representing all relationships to the given table. On Django 6.1+ the value
        is a 3-tuple that also carries the introspected on-delete rule.
        """
        schema_name, table_name = get_table_name_with_schema(table_name=table_name)

        # CONSTRAINT_COLUMN_USAGE: http://msdn2.microsoft.com/en-us/library/ms174431.aspx
        # CONSTRAINT_TABLE_USAGE:  http://msdn2.microsoft.com/en-us/library/ms179883.aspx
        # REFERENTIAL_CONSTRAINTS: http://msdn2.microsoft.com/en-us/library/ms179987.aspx
        # TABLE_CONSTRAINTS:       http://msdn2.microsoft.com/en-us/library/ms181757.aspx
        sql = f"""
SELECT e.COLUMN_NAME AS column_name,
  c.TABLE_NAME AS referenced_table_name,
  d.COLUMN_NAME AS referenced_column_name,
  b.DELETE_RULE AS delete_rule
FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS AS a
INNER JOIN INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS AS b
  ON a.CONSTRAINT_NAME = b.CONSTRAINT_NAME AND a.TABLE_SCHEMA = b.CONSTRAINT_SCHEMA
INNER JOIN INFORMATION_SCHEMA.CONSTRAINT_TABLE_USAGE AS c
  ON b.UNIQUE_CONSTRAINT_NAME = c.CONSTRAINT_NAME AND b.CONSTRAINT_SCHEMA = c.CONSTRAINT_SCHEMA
INNER JOIN INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE AS d
  ON c.CONSTRAINT_NAME = d.CONSTRAINT_NAME AND c.CONSTRAINT_SCHEMA = d.CONSTRAINT_SCHEMA
INNER JOIN INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE AS e
  ON a.CONSTRAINT_NAME = e.CONSTRAINT_NAME AND a.TABLE_SCHEMA = e.TABLE_SCHEMA
WHERE a.TABLE_SCHEMA = {schema_name} AND a.TABLE_NAME = %s AND a.CONSTRAINT_TYPE = 'FOREIGN KEY'"""
        cursor.execute(sql, (table_name,))
        rows = cursor.fetchall()
        if VERSION >= (6, 1):
            # Django 6.1 expects (ref_column, ref_table, db_on_delete). Django creates
            # SQL Server FKs with NO ACTION (on_delete is emulated in the ORM), which
            # on_delete_types maps to DO_NOTHING.
            return dict(
                [item[0], (item[2], item[1], self.on_delete_types.get(item[3], DO_NOTHING))]
                for item in rows
            )
        return dict([[item[0], (item[2], item[1])] for item in rows])

    def get_key_columns(self, cursor, table_name):
        """
        Returns a list of (column_name, referenced_table_name, referenced_column_name) for all
        key columns in given table.
        """
        key_columns = []
        schema_name, table_name = get_table_name_with_schema(table_name=table_name)

        cursor.execute(f"""
            SELECT c.name AS column_name, rt.name AS referenced_table_name, rc.name AS referenced_column_name
            FROM sys.foreign_key_columns fk
            INNER JOIN sys.tables t ON t.object_id = fk.parent_object_id
            INNER JOIN sys.columns c ON c.object_id = t.object_id AND c.column_id = fk.parent_column_id
            INNER JOIN sys.tables rt ON rt.object_id = fk.referenced_object_id
            INNER JOIN sys.columns rc ON rc.object_id = rt.object_id AND rc.column_id = fk.referenced_column_id
            WHERE t.schema_id = SCHEMA_ID({schema_name}) AND t.name = %s""", [table_name])
        key_columns.extend([tuple(row) for row in cursor.fetchall()])
        return key_columns

    def get_constraints(self, cursor, table_name):
        """
        Retrieves any constraints or keys (unique, pk, fk, check, index)
        across one or more columns.

        Returns a dict mapping constraint names to their attributes,
        where attributes is a dict with keys:
         * columns: List of columns this covers
         * primary_key: True if primary key, False otherwise
         * unique: True if this is a unique constraint, False otherwise
         * foreign_key: (table, column) of target, or None
         * check: True if check constraint, False otherwise
         * index: True if index, False otherwise.
         * orders: The order (ASC/DESC) defined for the columns of indexes
         * type: The type of the index (btree, hash, etc.)
        """
        constraints = {}

        schema_name, table_name = get_table_name_with_schema(table_name=table_name)

        # Loop over the key table, collecting things as constraints
        # This will get PKs, FKs, and uniques, but not CHECK
        cursor.execute(f"""
            SELECT
                kc.constraint_name,
                kc.column_name,
                tc.constraint_type,
                fk.referenced_table_name,
                fk.referenced_column_name
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS kc
            INNER JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS AS tc ON
                kc.table_schema = tc.table_schema AND
                kc.table_name = tc.table_name AND
                kc.constraint_name = tc.constraint_name
            LEFT OUTER JOIN (
                SELECT
                    ps.name AS table_schema,
                    pt.name AS table_name,
                    pc.name AS column_name,
                    rt.name AS referenced_table_name,
                    rc.name AS referenced_column_name
                FROM
                    sys.foreign_key_columns fkc
                INNER JOIN sys.tables pt ON
                    fkc.parent_object_id = pt.object_id
                INNER JOIN sys.schemas ps ON
                    pt.schema_id = ps.schema_id
                INNER JOIN sys.columns pc ON
                    fkc.parent_object_id = pc.object_id AND
                    fkc.parent_column_id = pc.column_id
                INNER JOIN sys.tables rt ON
                    fkc.referenced_object_id = rt.object_id
                INNER JOIN sys.schemas rs ON
                    rt.schema_id = rs.schema_id
                INNER JOIN sys.columns rc ON
                    fkc.referenced_object_id = rc.object_id AND
                    fkc.referenced_column_id = rc.column_id
            ) fk ON
                kc.table_schema = fk.table_schema AND
                kc.table_name = fk.table_name AND
                kc.column_name = fk.column_name
            WHERE
                kc.table_schema = {schema_name} AND
                kc.table_name = %s
            ORDER BY
                kc.constraint_name ASC,
                kc.ordinal_position ASC
        """, [table_name])

        for constraint, column, kind, ref_table, ref_column in cursor.fetchall():
            # If we're the first column, make the record
            if constraint not in constraints:
                constraints[constraint] = {
                    "columns": [],
                    "primary_key": kind.lower() == "primary key",
                    # In the sys.indexes table, primary key indexes have is_unique_constraint as false,
                    # but is_unique as true.
                    "unique": kind.lower() in ["primary key", "unique"],
                    "unique_constraint": kind.lower() == "unique",
                    "foreign_key": (ref_table, ref_column) if kind.lower() == "foreign key" else None,
                    "check": False,
                    # Potentially misleading: primary key and unique constraints still have indexes attached to them.
                    # Should probably be updated with the additional info from the sys.indexes table we fetch later on.
                    "index": False,
                    "default": False,
                }
            # Record the details
            constraints[constraint]['columns'].append(column)
        # Now get CHECK constraint columns
        cursor.execute(f"""
            SELECT kc.constraint_name, kc.column_name
            FROM INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE AS kc
            JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS AS c ON
                kc.table_schema = c.table_schema AND
                kc.table_name = c.table_name AND
                kc.constraint_name = c.constraint_name
            WHERE
                c.constraint_type = 'CHECK' AND
                kc.table_schema = {schema_name} AND
                kc.table_name = %s
        """, [table_name])
        for constraint, column in cursor.fetchall():
            # If we're the first column, make the record
            if constraint not in constraints:
                constraints[constraint] = {
                    "columns": [],
                    "primary_key": False,
                    "unique": False,
                    "unique_constraint": False,
                    "foreign_key": None,
                    "check": True,
                    "index": False,
                    "default": False,
                }
            # Record the details
            constraints[constraint]['columns'].append(column)
        # Now get DEFAULT constraint columns
        cursor.execute("""
            SELECT
                [name],
                COL_NAME([parent_object_id], [parent_column_id])
            FROM
                [sys].[default_constraints]
            WHERE
                OBJECT_NAME([parent_object_id]) = %s
        """, [table_name])
        for constraint, column in cursor.fetchall():
            # If we're the first column, make the record
            if constraint not in constraints:
                constraints[constraint] = {
                    "columns": [],
                    "primary_key": False,
                    "unique": False,
                    "unique_constraint": False,
                    "foreign_key": None,
                    "check": False,
                    "index": False,
                    "default": True,
                }
            # Record the details
            constraints[constraint]['columns'].append(column)
        # Now get indexes
        cursor.execute(f"""
            SELECT
                i.name AS index_name,
                i.is_unique,
                i.is_unique_constraint,
                i.is_primary_key,
                i.type,
                i.type_desc,
                ic.is_descending_key,
                c.name AS column_name
            FROM
                sys.tables AS t
            INNER JOIN sys.schemas AS s ON
                t.schema_id = s.schema_id
            INNER JOIN sys.indexes AS i ON
                t.object_id = i.object_id
            INNER JOIN sys.index_columns AS ic ON
                i.object_id = ic.object_id AND
                i.index_id = ic.index_id
            INNER JOIN sys.columns AS c ON
                ic.object_id = c.object_id AND
                ic.column_id = c.column_id
            WHERE
                t.schema_id = SCHEMA_ID({schema_name}) AND
                t.name = %s
            ORDER BY
                i.index_id ASC,
                ic.index_column_id ASC
        """, [table_name])
        indexes = {}
        for index, unique, unique_constraint, primary, type_, desc, order, column in cursor.fetchall():
            if index not in indexes:
                indexes[index] = {
                    "columns": [],
                    "primary_key": primary,
                    "unique": unique,
                    "unique_constraint": unique_constraint,
                    "foreign_key": None,
                    "check": False,
                    "default": False,
                    "index": True,
                    "orders": [],
                    "type": Index.suffix if type_ in (1, 2) else desc.lower(),
                }
            indexes[index]["columns"].append(column)
            indexes[index]["orders"].append("DESC" if order == 1 else "ASC")
        for index, constraint in indexes.items():
            if index not in constraints:
                constraints[index] = constraint
        return constraints

    def get_primary_key_column(self, cursor, table_name):
        cursor.execute("SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = N'%s'" % table_name)
        row = cursor.fetchone()
        if row is None:
            raise ValueError("Table %s does not exist" % table_name)
        return super().get_primary_key_column(cursor, table_name)
