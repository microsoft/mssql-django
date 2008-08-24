"""
MS SQL Server database backend for Django.

Requires pyodbc 2.0.38 or higher (http://pyodbc.sourceforge.net/)

pyodbc params:
DATABASE_NAME               - Database name. Required.
DATABASE_HOST               - SQL Server instance in "server\instance" format.
DATABASE_PORT               - SQL Server instance port.
DATABASE_USER               - Database user name. If not given then the
                              Integrated Security will be used.
DATABASE_PASSWORD           - Database user password.
DATABASE_ODBC_DSN           - A named DSN can be used instead of DATABASE_HOST.
DATABASE_ODBC_DRIVER        - ODBC Driver. Defalut is "{Sql Server}".
DATABASE_ODBC_EXTRA_PARAMS  - Additional parameters for the ODBC connection.
                              The format is "param=value;param=value".
DATABASE_COLLATE            - Collations
"""

try:
    import pyodbc as Database
except ImportError, e:
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured("Error loading pyodbc module: %s" % e)

version = tuple(map(int, Database.version.split('.')))
if version < (2, 0, 38):
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured("pyodbc 2.0.38 or newer is required; you have %s" % Database.version)

from django.db.backends import BaseDatabaseWrapper, BaseDatabaseFeatures, BaseDatabaseValidation
from django.conf import settings
from sql_server.pyodbc.operations import DatabaseOperations
from sql_server.pyodbc.client import DatabaseClient
from sql_server.pyodbc.creation import DatabaseCreation
from sql_server.pyodbc.introspection import DatabaseIntrospection
import os

if not hasattr(settings, "DATABASE_COLLATE"):
    settings.DATABASE_COLLATE = 'Latin1_General_CI_AS'

DatabaseError = Database.DatabaseError
IntegrityError = Database.IntegrityError

class DatabaseFeatures(BaseDatabaseFeatures):
    uses_custom_query_class = True
    can_use_chunked_reads = False


class DatabaseWrapper(BaseDatabaseWrapper):
    features = DatabaseFeatures()
    ops = DatabaseOperations()
    sqlserver_version = None
    driver_needs_utf8 = None
    MARS_Connection = False

    # Collations:       http://msdn2.microsoft.com/en-us/library/ms184391.aspx
    #                   http://msdn2.microsoft.com/en-us/library/ms179886.aspx
    # T-SQL LIKE:       http://msdn2.microsoft.com/en-us/library/ms179859.aspx
    # Full-Text search: http://msdn2.microsoft.com/en-us/library/ms142571.aspx
    #   CONTAINS:       http://msdn2.microsoft.com/en-us/library/ms187787.aspx
    #   FREETEXT:       http://msdn2.microsoft.com/en-us/library/ms176078.aspx

    operators = {
        # Since '=' is used not only for string comparision there is no way
        # to make it case (in)sensitive. It will simply fallback to the
        # database collation.
        'exact': '= %s ',
        'iexact': "= UPPER(%s) ",
        'contains': "LIKE %s ESCAPE '\\' COLLATE " + settings.DATABASE_COLLATE,
        'icontains': "LIKE UPPER(%s) ESCAPE '\\' COLLATE "+ settings.DATABASE_COLLATE,
        'gt': '> %s',
        'gte': '>= %s',
        'lt': '< %s',
        'lte': '<= %s',
        'startswith': "LIKE %s ESCAPE '\\' COLLATE " + settings.DATABASE_COLLATE,
        'endswith': "LIKE %s ESCAPE '\\' COLLATE " + settings.DATABASE_COLLATE,
        'istartswith': "LIKE UPPER(%s) ESCAPE '\\' COLLATE " + settings.DATABASE_COLLATE,
        'iendswith': "LIKE UPPER(%s) ESCAPE '\\' COLLATE " + settings.DATABASE_COLLATE,

        # TODO: remove, keep native T-SQL LIKE wildcards support
        # or use a "compatibility layer" and replace '*' with '%'
        # and '.' with '_'
        'regex': 'LIKE %s COLLATE ' + settings.DATABASE_COLLATE,
        'iregex': 'LIKE %s COLLATE ' + settings.DATABASE_COLLATE,

        # TODO: freetext, full-text contains...
    }

    def __init__(self, autocommit=False, **kwargs):
        super(DatabaseWrapper, self).__init__(autocommit=autocommit, **kwargs)

        if kwargs.get('MARS_Connection',False):
            self.MARS_Connection = True

        self.client = DatabaseClient()
        self.creation = DatabaseCreation(self)
        self.introspection = DatabaseIntrospection(self)
        self.validation = BaseDatabaseValidation()

        self.connection = None

    def _cursor(self, settings):
        new_conn = False
        if self.connection is None:
            new_conn = True
            if not settings.DATABASE_NAME:
                from django.core.exceptions import ImproperlyConfigured
                raise ImproperlyConfigured("You need to specify DATABASE_NAME in your Django settings file.")

            connstr = []
            if hasattr(settings, "DATABASE_ODBC_DSN"):
                connstr.append("DSN=%s" % settings.DATABASE_ODBC_DSN)
            else:
                if settings.DATABASE_HOST:
                    host_str = settings.DATABASE_HOST
                else:
                    host_str = 'localhost'
                if settings.DATABASE_PORT:
                    host_str += ',%s' % settings.DATABASE_PORT
                connstr.append("Server=%s" % host_str)

            if hasattr(settings, "DATABASE_ODBC_DRIVER"):
                odbc_driver = settings.DATABASE_ODBC_DRIVER
            else:
                if os.name == 'nt':
                    odbc_driver = "SQL Server"
                else:
                    odbc_driver = "FreeTDS"
            connstr.append("Driver={%s}" % odbc_driver)

            if settings.DATABASE_USER:
                connstr.append("Uid=%s;Pwd=%s" % (settings.DATABASE_USER, settings.DATABASE_PASSWORD))
            else:
                connstr.append("Integrated Security=SSPI")

            connstr.append("Database=%s" % settings.DATABASE_NAME)

            if self.MARS_Connection:
                connstr.append("MARS_Connection=yes")
            if hasattr(settings, "DATABASE_ODBC_EXTRA_PARAMS"):
                connstr.append(settings.DATABASE_ODBC_EXTRA_PARAMS)

            self.connection = Database.connect(';'.join(connstr), autocommit=self.options["autocommit"])

        cursor = self.connection.cursor()
        if new_conn:
            cursor.execute("SET DATEFORMAT ymd")

            if not self.sqlserver_version:
                cursor.execute("SELECT cast(SERVERPROPERTY('ProductVersion') as varchar)")
                ver_code = int(cursor.fetchone()[0].split('.')[0])
                if ver_code >= 9:
                    self.sqlserver_version = 2005
                else:
                    self.sqlserver_version = 2000

            if self.sqlserver_version < 2005:
                self.creation.data_types['TextField'] = 'ntext'

            if self.driver_needs_utf8 is None:
                self.driver_needs_utf8 = True
                drv_name = self.connection.getinfo(Database.SQL_DRIVER_NAME).upper()
                if drv_name in ('SQLSRV32.DLL','SQLNCLI.DLL'):
                    self.driver_needs_utf8 = False

                # http://msdn.microsoft.com/en-us/library/ms131686.aspx
                if self.sqlserver_version >= 2005 and drv_name == 'SQLNCLI.DLL' and self.MARS_Connection:
                    # How to to activate it: Add
                    # "{'MARS_Connection':True}" to DATABASE_OPTIONS
                    self.features.can_use_chunked_reads = True


            # FreeTDS can't execute some sql like CREATE DATABASE etc. in
            # Multi-statement, so we need to commit the above SQL sentences to
            # avoid this
            if not self.connection.autocommit:
                self.connection.commit()

        return CursorWrapper(cursor, self.driver_needs_utf8)


class CursorWrapper(object):
    """
    A wrapper around the pyodbc's cursor that takes in account some pyodbc
    DB-API 2.0 implementation and common ODBC driver particularities.
    """
    def __init__(self, cursor, driver_needs_utf8):
        self.cursor = cursor
        self.driver_needs_utf8 = driver_needs_utf8

    def format_sql(self, sql):
        # pyodbc uses '?' instead of '%s' as parameter placeholder.
        if "%s" in sql:
            sql = sql.replace('%s', '?')
        return sql

    def format_params(self, params):
        fp = []
        for p in params:
            if isinstance(p, unicode):
                if self.driver_needs_utf8:
                    # FreeTDS (and other ODBC drivers?) doesn't support Unicode
                    # yet, so we need to encode parameters in utf-8
                    fp.append(p.encode('utf-8'))
                else:
                    fp.append(p)
            elif isinstance(p, str):
                np = p.decode('utf-8') # TODO: use system encoding?
                fp.append(np.encode('utf-8'))
            elif isinstance(p, type(True)):
                if p:
                    fp.append(1)
                else:
                    fp.append(0)
            else:
                fp.append(p)
        return tuple(fp)

    def execute(self, sql, params=()):
        sql = self.format_sql(sql)
        params = self.format_params(params)
        return self.cursor.execute(sql, params)

    def executemany(self, sql, params_list):
        sql = self.format_sql(sql)
        # pyodbc's cursor.executemany() doesn't support an empty param_list
        if not params_list:
            if '?' in sql:
                return
        else:
            raw_pll = params_list
            params_list = [self.format_params(p) for p in raw_pll]
        return self.cursor.executemany(sql, params_list)

    def format_results(self, rows):
        if not self.driver_needs_utf8:
            return rows
        # FreeTDS (and other ODBC drivers?) doesn't support Unicode
        # yet, so we need to decode utf-8 data coming from the DB
        fr = []
        for row in rows:
            if isinstance(row, str):
                fr.append(row.decode('utf-8'))
            else:
                fr.append(row)
        return tuple(fr)

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is not None:
            # Convert row to tuple (pyodbc Rows are not sliceable).
            return tuple(self.format_results(row))
        return row

    def fetchmany(self, chunk):
        return [tuple(self.format_results(row)) for row in self.cursor.fetchmany(chunk)]

    def fetchall(self):
        return [tuple(self.format_results(row)) for row in self.cursor.fetchall()]

    def __getattr__(self, attr):
        if attr in self.__dict__:
            return self.__dict__[attr]
        else:
            return getattr(self.cursor, attr)
