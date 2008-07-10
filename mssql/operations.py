from django.db.backends import BaseDatabaseOperations, util
from django.utils.datastructures import SortedDict
from django.db.backends.mssql import query

ORDER_ASC = "ASC"
ORDER_DESC = "DESC"

SQL_SERVER_2005_VERSION = 9

class DatabaseOperations(BaseDatabaseOperations):
    def last_insert_id(self, cursor, table_name, pk_name):
        # TODO: Check how the `last_insert_id` is being used in the upper layers
        #       in context of multithreaded access, compare with other backends
        
        # IDENT_CURRENT:  http://msdn2.microsoft.com/en-us/library/ms175098.aspx
        # SCOPE_IDENTITY: http://msdn2.microsoft.com/en-us/library/ms190315.aspx
        # @@IDENTITY:     http://msdn2.microsoft.com/en-us/library/ms187342.aspx
        
        # IDENT_CURRENT is not limited by scope and session; it is limited to
        # a specified table. IDENT_CURRENT returns the value generated for
        # a specific table in any session and any scope. 
        # SCOPE_IDENTITY and @@IDENTITY return the last identity values that
        # are generated in any table in the current session. However,
        # SCOPE_IDENTITY returns values inserted only within the current scope;
        # @@IDENTITY is not limited to a specific scope.

        table_name = self.quote_name(table_name)
        pk_name = self.quote_name(pk_name)
        #cursor.execute("SELECT %s FROM %s WHERE %s = IDENT_CURRENT(%%s)" % (pk_name, table_name, pk_name), [table_name]) 
        cursor.execute("SELECT CAST(IDENT_CURRENT(%s) as int)", [table_name]) 
        return cursor.fetchone()[0]

    def query_class(self,DefaultQueryClass):
        return query.query_class(DefaultQueryClass)
    
    def query_set_class(self, DefaultQuerySet):
        "Create a custom QuerySet class for SQL Server."
        return SqlServerQuerySet

    def date_extract_sql(self, lookup_type, field_name):
        """
        Given a lookup_type of 'year', 'month' or 'day', returns the SQL that
        extracts a value from the given date field field_name.
        """
        return "DATEPART(%s, %s)" % (lookup_type, field_name)

    def date_trunc_sql(self, lookup_type, field_name):
        """
        Given a lookup_type of 'year', 'month' or 'day', returns the SQL that
        truncates the given date field field_name to a DATE object with only
        the given specificity.
        """
        if lookup_type=='year':
            return "Convert(datetime, Convert(varchar, DATEPART(year, %s)) + '/01/01')" % field_name
        if lookup_type=='month':
            return "Convert(datetime, Convert(varchar, DATEPART(year, %s)) + '/' + Convert(varchar, DATEPART(month, %s)) + '/01')" % (field_name, field_name)
        if lookup_type=='day':
            return "Convert(datetime, Convert(varchar(12), %s))" % field_name

    def limit_offset_sql(self, limit, offset=None):
        # Limits and offset are too complicated to be handled here.
        # Look for a implementation similar to SQL Server backend
        return ""

    def quote_name(self, name):
        """
        Returns a quoted version of the given table, index or column name. Does
        not quote the given name if it's already been quoted.
        """
        if name.startswith('[') and name.endswith(']'):
            return name # Quoting once is enough.
        return '[%s]' % name

    def get_random_function_sql(self):
        """
        Returns a SQL expression that returns a random value.
        """
        return "RAND()"

    def tablespace_sql(self, tablespace, inline=False):
        """
        Returns the tablespace SQL, or None if the backend doesn't use
        tablespaces.
        """
        return "ON %s" % self.quote_name(tablespace)

    def sql_flush(self, style, tables, sequences):
        """
        Returns a list of SQL statements required to remove all data from
        the given database tables (without actually removing the tables
        themselves).

        The `style` argument is a Style object as returned by either
        color_style() or no_style() in django.core.management.color.
        """
        # Cannot use TRUNCATE on tables that are referenced by a FOREIGN KEY
        # So must use the much slower DELETE
        from django.db import connection
        cursor = connection.cursor()
        cursor.execute("SELECT TABLE_NAME, CONSTRAINT_NAME FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS")
        fks = cursor.fetchall()
        sql_list = ['ALTER TABLE %s NOCHECK CONSTRAINT %s;' % \
                (self.quote_name(fk[0]), self.quote_name(fk[1])) for fk in fks]
        sql_list.extend(['%s %s %s;' % (style.SQL_KEYWORD('DELETE'), style.SQL_KEYWORD('FROM'),
                         style.SQL_FIELD(self.quote_name(table)) ) for table in tables])
        # The reset the counters on each table.
        sql_list.extend(['%s %s (%s, %s, %s) %s %s;' % (
            style.SQL_KEYWORD('DBCC'),
            style.SQL_KEYWORD('CHECKIDENT'),
            style.SQL_FIELD(self.quote_name(seq["table"])),
            style.SQL_KEYWORD('RESEED'),
            style.SQL_FIELD('1'),
            style.SQL_KEYWORD('WITH'),
            style.SQL_KEYWORD('NO_INFOMSGS'),
            ) for seq in sequences])
        sql_list.extend(['ALTER TABLE %s CHECK CONSTRAINT %s;' % \
                (self.quote_name(fk[0]), self.quote_name(fk[1])) for fk in fks])
        return sql_list 

    def start_transaction_sql(self):
        """
        Returns the SQL statement required to start a transaction.
        """
        return "BEGIN TRANSACTION"

