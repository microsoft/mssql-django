from django.db.backends import BaseDatabaseIntrospection, FieldInfo
import pyodbc as Database

SQL_AUTOFIELD = -777555

class DatabaseIntrospection(BaseDatabaseIntrospection):
    # Map type codes to Django Field types.
    data_types_reverse = {
        SQL_AUTOFIELD:                  'AutoField',
        Database.SQL_BIGINT:            'BigIntegerField',
        #Database.SQL_BINARY:            ,
        Database.SQL_BIT:               'BooleanField',
        Database.SQL_CHAR:              'CharField',
        Database.SQL_DECIMAL:           'DecimalField',
        Database.SQL_DOUBLE:            'FloatField',
        Database.SQL_FLOAT:             'FloatField',
        Database.SQL_GUID:              'TextField',
        Database.SQL_INTEGER:           'IntegerField',
        Database.SQL_LONGVARBINARY:     'BinaryField',
        #Database.SQL_LONGVARCHAR:       ,
        Database.SQL_NUMERIC:           'DecimalField',
        Database.SQL_REAL:              'FloatField',
        Database.SQL_SMALLINT:          'SmallIntegerField',
        Database.SQL_TINYINT:           'SmallIntegerField',
        Database.SQL_TYPE_DATE:         'DateField',
        Database.SQL_TYPE_TIME:         'TimeField',
        Database.SQL_TYPE_TIMESTAMP:    'DateTimeField',
        Database.SQL_VARBINARY:         'BinaryField',
        Database.SQL_VARCHAR:           'TextField',
        Database.SQL_WCHAR:             'CharField',
        Database.SQL_WLONGVARCHAR:      'TextField',
        Database.SQL_WVARCHAR:          'TextField',
    }

    def get_table_list(self, cursor):
        """
        Returns a list of table names in the current database.
        """
        # TABLES: http://msdn2.microsoft.com/en-us/library/ms186224.aspx

        cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE'")
        return [row[0] for row in cursor.fetchall()]

        # Or pyodbc specific:
        #return [row[2] for row in cursor.tables(tableType='TABLE')]

    def _is_auto_field(self, cursor, table_name, column_name):
        """
        Checks whether column is Identity
        """
        # COLUMNPROPERTY: http://msdn2.microsoft.com/en-us/library/ms174968.aspx

        #from django.db import connection
        #cursor.execute("SELECT COLUMNPROPERTY(OBJECT_ID(%s), %s, 'IsIdentity')",
        #                 (connection.ops.quote_name(table_name), column_name))
        cursor.execute("SELECT COLUMNPROPERTY(OBJECT_ID(%s), %s, 'IsIdentity')",
                         (self.connection.ops.quote_name(table_name), column_name))
        return cursor.fetchall()[0][0]

    def get_table_description(self, cursor, table_name, identity_check=True):
        """Returns a description of the table, with DB-API cursor.description interface.

        The 'auto_check' parameter has been added to the function argspec.
        If set to True, the function will check each of the table's fields for the
        IDENTITY property (the IDENTITY property is the MSSQL equivalent to an AutoField).

        When a field is found with an IDENTITY property, it is given a custom field number
        of SQL_AUTOFIELD, which maps to the 'AutoField' value in the DATA_TYPES_REVERSE dict.
        """

        # map pyodbc's cursor.columns to db-api cursor description
        columns = [[c[3], c[4], None, c[6], c[6], c[8], c[10]] for c in cursor.columns(table=table_name)]
        items = []
        for column in columns:
            if identity_check and self._is_auto_field(cursor, table_name, column[0]):
                column[1] = SQL_AUTOFIELD
            if column[1] == Database.SQL_WVARCHAR and column[3] < 4000:
                column[1] = Database.SQL_WCHAR
            items.append(FieldInfo(*column))
        return items

    def _name_to_index(self, cursor, table_name):
        """
        Returns a dictionary of {field_name: field_index} for the given table.
        Indexes are 0-based.
        """
        return dict([(d[0], i) for i, d in enumerate(self.get_table_description(cursor, table_name, identity_check=False))])

    def get_relations(self, cursor, table_name):
        """
        Returns a dictionary of {field_index: (field_index_other_table, other_table)}
        representing all relationships to the given table. Indexes are 0-based.
        """
        # CONSTRAINT_COLUMN_USAGE: http://msdn2.microsoft.com/en-us/library/ms174431.aspx
        # CONSTRAINT_TABLE_USAGE:  http://msdn2.microsoft.com/en-us/library/ms179883.aspx
        # REFERENTIAL_CONSTRAINTS: http://msdn2.microsoft.com/en-us/library/ms179987.aspx
        # TABLE_CONSTRAINTS:       http://msdn2.microsoft.com/en-us/library/ms181757.aspx

        table_index = self._name_to_index(cursor, table_name)
        sql = """
SELECT e.COLUMN_NAME AS column_name,
  c.TABLE_NAME AS referenced_table_name,
  d.COLUMN_NAME AS referenced_column_name
FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS AS a
INNER JOIN INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS AS b
  ON a.CONSTRAINT_NAME = b.CONSTRAINT_NAME
INNER JOIN INFORMATION_SCHEMA.CONSTRAINT_TABLE_USAGE AS c
  ON b.UNIQUE_CONSTRAINT_NAME = c.CONSTRAINT_NAME
INNER JOIN INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE AS d
  ON c.CONSTRAINT_NAME = d.CONSTRAINT_NAME
INNER JOIN INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE AS e
  ON a.CONSTRAINT_NAME = e.CONSTRAINT_NAME
WHERE a.TABLE_NAME = %s AND a.CONSTRAINT_TYPE = 'FOREIGN KEY'"""
        cursor.execute(sql, (table_name,))
        return dict([(table_index[item[0]], (self._name_to_index(cursor, item[1])[item[2]], item[1]))
                     for item in cursor.fetchall()])

    def get_indexes(self, cursor, table_name):
        """
        Returns a dictionary of fieldname -> infodict for the given table,
        where each infodict is in the format:
            {'primary_key': boolean representing whether it's the primary key,
             'unique': boolean representing whether it's a unique index}
        """
        # CONSTRAINT_COLUMN_USAGE: http://msdn2.microsoft.com/en-us/library/ms174431.aspx
        # TABLE_CONSTRAINTS: http://msdn2.microsoft.com/en-us/library/ms181757.aspx

        pk_uk_sql = """
SELECT d.COLUMN_NAME, c.CONSTRAINT_TYPE FROM (
SELECT a.CONSTRAINT_NAME, a.CONSTRAINT_TYPE
FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS AS a
INNER JOIN INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE AS b
  ON a.CONSTRAINT_NAME = b.CONSTRAINT_NAME AND a.TABLE_NAME = b.TABLE_NAME
WHERE a.TABLE_NAME = %s AND (CONSTRAINT_TYPE = 'PRIMARY KEY' OR CONSTRAINT_TYPE = 'UNIQUE')
GROUP BY a.CONSTRAINT_TYPE, a.CONSTRAINT_NAME
HAVING(COUNT(a.CONSTRAINT_NAME)) = 1) AS c
INNER JOIN INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE AS d
  ON c.CONSTRAINT_NAME = d.CONSTRAINT_NAME"""

        field_names = [item[0] for item in self.get_table_description(cursor, table_name, identity_check=False)]
        indexes, results = {}, {}
        cursor.execute(pk_uk_sql, (table_name,))
        data = cursor.fetchall()
        if data:
            results.update(data)

        # non-unique, non-compound indexes, only in SS2005?
        ix_sql = """
SELECT DISTINCT c.name
FROM sys.columns c
INNER JOIN sys.index_columns ic
  ON ic.object_id = c.object_id AND ic.column_id = c.column_id
INNER JOIN sys.indexes ix
  ON ix.object_id = ic.object_id AND ix.index_id = ic.index_id
INNER JOIN sys.tables t
  ON t.object_id = ix.object_id
WHERE ix.object_id IN (
  SELECT ix.object_id
  FROM sys.indexes ix
  GROUP BY ix.object_id, ix.index_id
  HAVING count(1) = 1)
AND ix.is_primary_key = 0
AND ix.is_unique_constraint = 0
AND t.name = %s"""

        cursor.execute(ix_sql, (table_name,))
        for column in [r[0] for r in cursor.fetchall()]:
            if column not in results:
                results[column] = 'IX'

        for field in field_names:
            val = results.get(field, None)
            if val:
                indexes[field] = dict(primary_key=(val=='PRIMARY KEY'), unique=(val=='UNIQUE'))

        return indexes

    def get_key_columns(self, cursor, table_name):
        key_columns = []
        cursor.execute("""
            SELECT kcu.column_name, ccu.table_name AS referenced_table, ccu.column_name AS referenced_column
            FROM INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE ccu
            LEFT JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
                ON ccu.constraint_catalog = kcu.constraint_catalog
                    AND ccu.constraint_schema = kcu.constraint_schema
                    AND ccu.constraint_name = kcu.constraint_name
            LEFT JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                ON ccu.constraint_catalog = tc.constraint_catalog
                    AND ccu.constraint_schema = tc.constraint_schema
                    AND ccu.constraint_name = tc.constraint_name
            WHERE kcu.table_name = %s AND tc.constraint_type = 'FOREIGN KEY'""" , [table_name])
        key_columns.extend(cursor.fetchall())
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
        """
        constraints = {}
        # Loop over the key table, collecting things as constraints
        # This will get PKs, FKs, and uniques, but not CHECK
        cursor.execute("""
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
                kc.table_name = %s
            ORDER BY kc.ordinal_position ASC
        """, [table_name])
        for constraint, column, kind, ref_table, ref_column in cursor.fetchall():
            # If we're the first column, make the record
            if constraint not in constraints:
                constraints[constraint] = {
                    "columns": [],
                    "primary_key": kind.lower() == "primary key",
                    "unique": kind.lower() in ["primary key", "unique"],
                    "foreign_key": (ref_table, ref_column) if kind.lower() == "foreign key" else None,
                    "check": False,
                    "index": False,
                }
            # Record the details
            constraints[constraint]['columns'].append(column)
        # Now get CHECK constraint columns
        cursor.execute("""
            SELECT kc.constraint_name, kc.column_name
            FROM INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE AS kc
            JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS AS c ON
                kc.table_schema = c.table_schema AND
                kc.table_name = c.table_name AND
                kc.constraint_name = c.constraint_name
            WHERE
                c.constraint_type = 'CHECK' AND
                kc.table_name = %s
        """, [table_name])
        for constraint, column in cursor.fetchall():
            # If we're the first column, make the record
            if constraint not in constraints:
                constraints[constraint] = {
                    "columns": [],
                    "primary_key": False,
                    "unique": False,
                    "foreign_key": None,
                    "check": True,
                    "index": False,
                }
            # Record the details
            constraints[constraint]['columns'].append(column)
        # Now get indexes
        cursor.execute("""
            SELECT
                i.name AS index_name,
                i.is_unique,
                i.is_primary_key,
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
                t.name = %s
            ORDER BY
                i.index_id ASC,
                ic.index_column_id ASC
        """, [table_name])
        indexes = {}
        for index, unique, primary, column in cursor.fetchall():
            if index not in indexes:
                indexes[index] = {
                    "columns": [],
                    "primary_key": primary,
                    "unique": unique,
                    "foreign_key": None,
                    "check": False,
                    "index": True,
                }
            indexes[index]["columns"].append(column)
        for index, constraint in indexes.items():
            if index not in constraints:
                constraints[index] = constraint
        return constraints
