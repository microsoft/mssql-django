"""
MS SQL Server database backend for Django.
"""
import datetime
import os
import re
import sys

from django.core.exceptions import ImproperlyConfigured

try:
    import pyodbc as Database
except ImportError:
    e = sys.exc_info()[1]
    raise ImproperlyConfigured("Error loading pyodbc module: %s" % e)

pyodbc_ver = tuple(map(int, Database.version.split('.')[:2]))
if pyodbc_ver < (2, 1):
    raise ImproperlyConfigured("pyodbc 2.1 or newer is required; you have %s" % Database.version)

from django.db import utils
from django.db.backends import BaseDatabaseWrapper, BaseDatabaseFeatures, BaseDatabaseValidation
from django.db.backends.signals import connection_created
from django.conf import settings
from django.utils.encoding import smart_str
from django import VERSION as DjangoVersion
if DjangoVersion[:2] == (1,5):
    _DJANGO_VERSION = 15
elif DjangoVersion[:2] == (1,4):
    _DJANGO_VERSION = 14
elif DjangoVersion[:2] == (1,3):
    _DJANGO_VERSION = 13
elif DjangoVersion[:2] == (1,2):
    _DJANGO_VERSION = 12
else:
    raise ImproperlyConfigured("Django %d.%d is not supported." % DjangoVersion[:2])

if hasattr(settings, 'DATABASE_CONNECTION_POOLING'):
    if not settings.DATABASE_CONNECTION_POOLING:
        Database.pooling = False

from sql_server.pyodbc.operations import DatabaseOperations
from sql_server.pyodbc.client import DatabaseClient
from sql_server.pyodbc.compat import binary_type, text_type, timezone
from sql_server.pyodbc.creation import DatabaseCreation
from sql_server.pyodbc.introspection import DatabaseIntrospection

DatabaseError = Database.Error
IntegrityError = Database.IntegrityError

class DatabaseFeatures(BaseDatabaseFeatures):
    allow_sliced_subqueries = False
    can_return_id_from_insert = True
    can_use_chunked_reads = False
    has_bulk_insert = True
    has_select_for_update = _DJANGO_VERSION >= 14
    has_select_for_update_nowait = _DJANGO_VERSION >= 14
    ignores_nulls_in_unique_constraints = False
    supports_1000_query_parameters = False
    supports_microsecond_precision = True
    supports_mixed_date_datetime_comparisons = False
    supports_regex_backreferencing = False
    supports_sequence_reset = False
    supports_subqueries_in_group_by = False
    supports_timezones = False
    supports_transactions = True
    #uses_savepoints = True

    def _supports_transactions(self):
        # keep it compatible with Django 1.3 and 1.4
        return self.supports_transactions

class DatabaseWrapper(BaseDatabaseWrapper):
    _DJANGO_VERSION = _DJANGO_VERSION

    drv_name = None
    driver_needs_utf8 = None
    MARS_Connection = False
    unicode_results = False
    datefirst = 7
    use_legacy_datetime = False
    connection_recovery_interval_msec = 0.0

    # Collations:       http://msdn2.microsoft.com/en-us/library/ms184391.aspx
    #                   http://msdn2.microsoft.com/en-us/library/ms179886.aspx
    # T-SQL LIKE:       http://msdn2.microsoft.com/en-us/library/ms179859.aspx
    # Full-Text search: http://msdn2.microsoft.com/en-us/library/ms142571.aspx
    #   CONTAINS:       http://msdn2.microsoft.com/en-us/library/ms187787.aspx
    #   FREETEXT:       http://msdn2.microsoft.com/en-us/library/ms176078.aspx

    vendor = 'microsoft'
    operators = {
        # Since '=' is used not only for string comparision there is no way
        # to make it case (in)sensitive. 
        'exact': '= %s',
        'iexact': "= UPPER(%s)",
        'contains': "LIKE %s ESCAPE '\\'",
        'icontains': "LIKE UPPER(%s) ESCAPE '\\'",
        'gt': '> %s',
        'gte': '>= %s',
        'lt': '< %s',
        'lte': '<= %s',
        'startswith': "LIKE %s ESCAPE '\\'",
        'endswith': "LIKE %s ESCAPE '\\'",
        'istartswith': "LIKE UPPER(%s) ESCAPE '\\'",
        'iendswith': "LIKE UPPER(%s) ESCAPE '\\'",

        # TODO: remove, keep native T-SQL LIKE wildcards support
        # or use a "compatibility layer" and replace '*' with '%'
        # and '.' with '_'
        #'regex': 'LIKE %s',
        #'iregex': 'LIKE %s',

        # TODO: freetext, full-text contains...
    }

    codes_for_stale_connection = (
        '08S01',
        '08S02',
    )

    def __init__(self, *args, **kwargs):
        super(DatabaseWrapper, self).__init__(*args, **kwargs)

        options = self.settings_dict.get('OPTIONS', None)

        if options:
            self.MARS_Connection = options.get('MARS_Connection', False)
            self.datefirst = options.get('datefirst', 7)
            self.unicode_results = options.get('unicode_results', False)
            
            # Some drivers need unicode encoded as UTF8. If this is left as
            # None, it will be determined based on the driver, namely it'll be
            # False if the driver is a windows driver and True otherwise.
            #
            # However, recent versions of FreeTDS and pyodbc (0.91 and 3.0.6 as
            # of writing) are perfectly okay being fed unicode, which is why
            # this option is configurable.
            self.driver_needs_utf8 = options.get('driver_needs_utf8', None)

            # data type compatibility to databases created by old django-pyodbc
            self.use_legacy_datetime = options.get('use_legacy_datetime', False)

            # interval to wait for recovery from network error
            interval = options.get('connection_recovery_interval_msec', 0.0)
            self.connection_recovery_interval_msec = float(interval) / 1000

            # make lookup operators to be collation-sensitive if needed
            self.collation = options.get('collation', None)
            if self.collation:
                self.operators = dict(self.__class__.operators)
                ops = {}
                for op in self.operators:
                    sql = self.operators[op]
                    if sql.startswith('LIKE '):
                        ops[op] = '%s COLLATE %s' % (sql, self.collation)
                self.operators.update(ops)

        self.test_create = self.settings_dict.get('TEST_CREATE', True)

        if _DJANGO_VERSION >= 13:
            self.features = DatabaseFeatures(self)
        else:
            self.features = DatabaseFeatures()

        self.ops = DatabaseOperations(self)
        self.client = DatabaseClient(self)
        self.creation = DatabaseCreation(self)
        self.introspection = DatabaseIntrospection(self)
        self.validation = BaseDatabaseValidation(self)

        self.connection = None

    def _cursor(self):
        new_conn = False
        settings_dict = self.settings_dict
        db_str, user_str, passwd_str, port_str = None, None, "", None

        options = settings_dict['OPTIONS']
        if settings_dict['NAME']:
            db_str = settings_dict['NAME']
        if settings_dict['HOST']:
            host_str = settings_dict['HOST']
        else:
            host_str = 'localhost'
        if settings_dict['USER']:
            user_str = settings_dict['USER']
        if settings_dict['PASSWORD']:
            passwd_str = settings_dict['PASSWORD']
        if settings_dict['PORT']:
            port_str = settings_dict['PORT']

        if self.connection is None:
            new_conn = True
            if not db_str:
                raise ImproperlyConfigured('You need to specify NAME in your Django settings file.')

            cstr_parts = []
            if 'driver' in options:
                driver = options['driver']
            else:
                if os.name == 'nt':
                    driver = 'SQL Server'
                else:
                    driver = 'FreeTDS'

            # Microsoft driver names assumed here are:
            # * SQL Server
            # * SQL Native Client
            # * SQL Server Native Client 10.0/11.0
            # * ODBC Driver 11 for SQL Server
            ms_drivers = re.compile('.*SQL (Server$|(Server )?Native Client)')
            if 'dsn' in options:
                cstr_parts.append('DSN=%s' % options['dsn'])
            else:
                # Only append DRIVER if DATABASE_ODBC_DSN hasn't been set
                cstr_parts.append('DRIVER={%s}' % driver)
                
                if ms_drivers.match(driver) or driver == 'FreeTDS' and \
                        options.get('host_is_server', False):
                    if port_str:
                        host_str += ';PORT=%s' % port_str
                    cstr_parts.append('SERVER=%s' % host_str)
                else:
                    cstr_parts.append('SERVERNAME=%s' % host_str)

            if user_str:
                cstr_parts.append('UID=%s;PWD=%s' % (user_str, passwd_str))
            else:
                if ms_drivers.match(driver):
                    cstr_parts.append('Trusted_Connection=yes')
                else:
                    cstr_parts.append('Integrated Security=SSPI')

            cstr_parts.append('DATABASE=%s' % db_str)

            if self.MARS_Connection:
                cstr_parts.append('MARS_Connection=yes')
                
            if 'extra_params' in options:
                cstr_parts.append(options['extra_params'])

            connstr = ';'.join(cstr_parts)
            autocommit = options.get('autocommit', False)
            if self.unicode_results:
                self.connection = Database.connect(connstr, \
                        autocommit=autocommit, \
                        unicode_results='True')
            else:
                self.connection = Database.connect(connstr, \
                        autocommit=autocommit)
            connection_created.send(sender=self.__class__, connection=self)

        cursor = self.connection.cursor()
        if new_conn:
            # Set date format for the connection. Also, make sure Sunday is
            # considered the first day of the week (to be consistent with the
            # Django convention for the 'week_day' Django lookup) if the user
            # hasn't told us otherwise
            cursor.execute("SET DATEFORMAT ymd; SET DATEFIRST %s" % self.datefirst)

            self.drv_name = self.connection.getinfo(Database.SQL_DRIVER_NAME).upper()

            driver_is_freetds = self.drv_name.startswith('LIBTDSODBC')
            driver_is_sqlsrv32 = self.drv_name == 'SQLSRV32.DLL'
            driver_is_snac9 = self.drv_name == "SQLNCLI.DLL"

            self.use_legacy_datetime = \
                driver_is_freetds or driver_is_sqlsrv32 or driver_is_snac9

            if self.ops.sql_server_ver < 2008:
                self.use_legacy_datetime = True
                self.features.has_bulk_insert = False

            if self.use_legacy_datetime:
                self.creation.use_legacy_datetime()
                self.features.supports_microsecond_precision = False
                self.features.supports_mixed_date_datetime_comparisons = True

            ms_drv_names = re.compile('^(LIB)?(SQLN?CLI|MSODBCSQL)')
            if self.driver_needs_utf8 is None:
                self.driver_needs_utf8 = False
                if driver_is_sqlsrv32 or ms_drv_names.match(self.drv_name):
                    self.driver_needs_utf8 = False

            # http://msdn.microsoft.com/en-us/library/ms131686.aspx
            if self.MARS_Connection and ms_drv_names.match(self.drv_name):
                # How to to activate it: Add 'MARS_Connection': True
                # to the OPTIONS dictionary setting
                self.features.can_use_chunked_reads = True

            # FreeTDS can't execute some sql queries like CREATE DATABASE etc.
            # in multi-statement, so we need to commit the above SQL sentence(s)
            # to avoid this
            if driver_is_freetds and not self.connection.autocommit:
                self.connection.commit()

        return CursorWrapper(cursor, self)

    def _execute_foreach(self, sql, table_names=None):
        cursor = self.cursor()
        if not table_names:
            table_names = self.introspection.get_table_list(cursor)
        for table_name in table_names:
            cursor.execute(sql % self.ops.quote_name(table_name))

    def _on_error(self, e):
        if e.args[0] in self.codes_for_stale_connection:
            # close the connection and try to open a new one next time
            try:
                self.close()
            except:
                pass
            self.connection = None
            # wait a moment for recovery from network error
            import time
            time.sleep(self.connection_recovery_interval_msec)

    def check_constraints(self, table_names=None):
        self._execute_foreach('ALTER TABLE %s WITH CHECK CHECK CONSTRAINT ALL', table_names)

    def disable_constraint_checking(self):
        # Azure SQL Database doesn't support sp_msforeachtable
        #cursor.execute('EXEC sp_msforeachtable "ALTER TABLE ? NOCHECK CONSTRAINT ALL"')
        self._execute_foreach('ALTER TABLE %s NOCHECK CONSTRAINT ALL')
        return True

    def enable_constraint_checking(self):
        # Azure SQL Database doesn't support sp_msforeachtable
        #cursor.execute('EXEC sp_msforeachtable "ALTER TABLE ? WITH CHECK CHECK CONSTRAINT ALL"')
        self.check_constraints()

class CursorWrapper(object):
    """
    A wrapper around the pyodbc's cursor that takes in account a) some pyodbc
    DB-API 2.0 implementation and b) some common ODBC driver particularities.
    """
    def __init__(self, cursor, connection):
        self.cursor = cursor
        self.connection = connection
        self.driver_needs_utf8 = connection.driver_needs_utf8
        self.last_sql = ''
        self.last_params = ()
        self.use_legacy_datetime = connection.use_legacy_datetime

    def format_sql(self, sql, n_params=None):
        if self.driver_needs_utf8 and isinstance(sql, text_type):
            # FreeTDS (and other ODBC drivers?) doesn't support Unicode
            # yet, so we need to encode the SQL clause itself in utf-8
            sql = smart_str(sql, 'utf-8')

        # pyodbc uses '?' instead of '%s' as parameter placeholder.
        if n_params is not None and n_params > 0:
            sql = sql % tuple('?' * n_params)
        else:
            if '%s' in sql:
                sql = sql.replace('%s', '?')
        return sql

    def format_params(self, params):
        fp = []
        for p in params:
            if isinstance(p, text_type):
                if self.driver_needs_utf8:
                    # FreeTDS (and other ODBC drivers?) doesn't support Unicode
                    # yet, so we need to encode parameters in utf-8
                    fp.append(smart_str(p, 'utf-8'))
                else:
                    fp.append(p)

            elif isinstance(p, binary_type):
                fp.append(p)

            elif isinstance(p, type(True)):
                if p:
                    fp.append(1)
                else:
                    fp.append(0)

            else:
                fp.append(p)

        return tuple(fp)

    def execute(self, sql, params=()):
        self.last_sql = sql
        sql = self.format_sql(sql, len(params))
        params = self.format_params(params)
        self.last_params = params

        try:
            return self.cursor.execute(sql, params)
        except IntegrityError:
            e = sys.exc_info()[1]
            raise utils.IntegrityError(*e.args)
        except DatabaseError:
            e = sys.exc_info()[1]
            self.connection._on_error(e)
            raise utils.DatabaseError(*e.args)

    def executemany(self, sql, params_list):
        sql = self.format_sql(sql)
        # pyodbc's cursor.executemany() doesn't support an empty param_list
        if not params_list:
            if '?' in sql:
                return
        else:
            raw_pll = params_list
            params_list = [self.format_params(p) for p in raw_pll]

        try:
            return self.cursor.executemany(sql, params_list)
        except IntegrityError:
            e = sys.exc_info()[1]
            raise utils.IntegrityError(*e.args)
        except DatabaseError:
            e = sys.exc_info()[1]
            self.connection._on_error(e)
            raise utils.DatabaseError(*e.args)

    def format_rows(self, rows):
        return list(map(self.format_row, rows))

    def format_row(self, row):
        """
        Decode data coming from the database if needed and convert rows to tuples
        (pyodbc Rows are not sliceable).
        """
        needs_utc = _DJANGO_VERSION >= 14 and settings.USE_TZ
        if not (needs_utc or self.driver_needs_utf8):
            return row

        for i in range(len(row)):
            f = row[i]
            if isinstance(f, datetime.datetime):
                if needs_utc:
                    row[i] = f.replace(tzinfo=timezone.utc)
            elif self.driver_needs_utf8:
                # FreeTDS (and other ODBC drivers?) doesn't support Unicode
                # yet, so we need to decode utf-8 data coming from the DB
                if isinstance(f, binary_type):
                    row[i] = f.decode('utf-8')

        return row

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is not None:
            row = self.format_row(row)
        return row

    def fetchmany(self, chunk):
        return self.format_rows(self.cursor.fetchmany(chunk))

    def fetchall(self):
        return self.format_rows(self.cursor.fetchall())

    def __getattr__(self, attr):
        if attr in self.__dict__:
            return self.__dict__[attr]
        return getattr(self.cursor, attr)

    def __iter__(self):
        return iter(self.cursor)
