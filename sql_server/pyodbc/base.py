"""
MS SQL Server database backend for Django.
"""
import datetime
import logging
import os
import re
import sys

from django.core.exceptions import ImproperlyConfigured

try:
    import pyodbc as Database
except ImportError as e:
    raise ImproperlyConfigured("Error loading pyodbc module: %s" % e)

pyodbc_ver = tuple(map(int, Database.version.split('.')[:2]))
if pyodbc_ver < (3, 0):
    raise ImproperlyConfigured("pyodbc 3.0 or newer is required; you have %s" % Database.version)

from django.conf import settings
from django.db.backends import *
from django.utils.encoding import smart_str
from django.utils.functional import cached_property
from django.utils.six import binary_type, text_type
from django.utils.timezone import utc
from django import VERSION as DjangoVersion
if DjangoVersion[:2] == (1,6):
    _DJANGO_VERSION = 16
else:
    raise ImproperlyConfigured("Django %d.%d is not supported." % DjangoVersion[:2])

if hasattr(settings, 'DATABASE_CONNECTION_POOLING'):
    if not settings.DATABASE_CONNECTION_POOLING:
        Database.pooling = False

from sql_server.pyodbc.operations import DatabaseOperations
from sql_server.pyodbc.client import DatabaseClient
from sql_server.pyodbc.creation import DatabaseCreation
from sql_server.pyodbc.introspection import DatabaseIntrospection

logger = logging.getLogger('django.db.backends')

EDITION_AZURE_SQL_DB = 5


class DatabaseFeatures(BaseDatabaseFeatures):
    allow_sliced_subqueries = False
    can_return_id_from_insert = True
    can_use_chunked_reads = False
    has_bulk_insert = True
    has_real_datatype = True
    has_select_for_update = True
    has_select_for_update_nowait = True
    has_zoneinfo_database = False
    ignores_nulls_in_unique_constraints = False
    needs_datetime_string_cast = False
    supports_1000_query_parameters = False
    supports_paramstyle_pyformat = 'pyformat' in Database.paramstyle
    supports_regex_backreferencing = False
    supports_sequence_reset = False
    supports_subqueries_in_group_by = False
    supports_tablespaces = True
    supports_timezones = False
    supports_transactions = True
    uses_savepoints = True

class DatabaseWrapper(BaseDatabaseWrapper):
    _DJANGO_VERSION = _DJANGO_VERSION
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
    }
    _codes_for_networkerror = (
        '08S01',
        '08S02',
    )
    _sql_server_versions = {
        9: 2005,
        10: 2008,
        11: 2012,
        12: 2014,
    }

    Database = Database

    def __init__(self, *args, **kwargs):
        super(DatabaseWrapper, self).__init__(*args, **kwargs)

        opts = self.settings_dict["OPTIONS"]

        # capability for multiple result sets or cursors
        self.supports_mars = opts.get('MARS_Connection', False)
        self.open_cursor = None

        # Some drivers need unicode encoded as UTF8. If this is left as
        # None, it will be determined based on the driver, namely it'll be
        # False if the driver is a windows driver and True otherwise.
        #
        # However, recent versions of FreeTDS and pyodbc (0.91 and 3.0.6 as
        # of writing) are perfectly okay being fed unicode, which is why
        # this option is configurable.
        self.driver_needs_utf8 = opts.get('driver_needs_utf8', False)

        # data type compatibility to databases created by old django-pyodbc
        self.use_legacy_datetime = opts.get('use_legacy_datetime', False)

        # interval to wait for recovery from network error
        interval = opts.get('connection_recovery_interval_msec', 0.0)
        self.connection_recovery_interval_msec = float(interval) / 1000

        # make lookup operators to be collation-sensitive if needed
        collation = opts.get('collation', None)
        if collation:
            self.operators = dict(self.__class__.operators)
            ops = {}
            for op in self.operators:
                sql = self.operators[op]
                if sql.startswith('LIKE '):
                    ops[op] = '%s COLLATE %s' % (sql, collation)
            self.operators.update(ops)

        self.features = DatabaseFeatures(self)
        self.ops = DatabaseOperations(self)
        self.client = DatabaseClient(self)
        self.creation = DatabaseCreation(self)
        self.introspection = DatabaseIntrospection(self)
        self.validation = BaseDatabaseValidation(self)

    def close(self):
        self.validate_thread_sharing()
        if self.connection is None:
            return
        if self.open_cursor:
            try:
                self.open_cursor.close()
            except:
                pass

        try:
            self.connection.close()
        except Database.Error:
            # In some cases (database restart, network connection lost etc...)
            # the connection to the database is lost without giving Django a
            # notification. If we don't set self.connection to None, the error
            # will occur a every request.
            logger.warning('pyodbc error while closing the connection.',
                           exc_info=sys.exc_info())
            raise
        finally:
            self.connection = None
            self.open_cursor = None
            self.set_clean()

    def create_cursor(self):
        return CursorWrapper(self._create_cursor(), self)

    def get_connection_params(self):
        settings_dict = self.settings_dict
        if not settings_dict['NAME']:
            from django.core.exceptions import ImproperlyConfigured
            raise ImproperlyConfigured(
                "settings.DATABASES is improperly configured. "
                "Please supply the NAME value.")
        return settings_dict

    def get_new_connection(self, conn_params):
        database = conn_params['NAME']
        host = conn_params.get('HOST', 'localhost')
        user = conn_params.get('USER', None)
        password = conn_params.get('PASSWORD', None)
        port = conn_params.get('PORT', None)

        default_driver = 'SQL Server' if os.name == 'nt' else 'FreeTDS'
        options = conn_params.get('OPTIONS', {})
        driver = options.get('driver', default_driver)
        dsn = options.get('dsn', None)

        # Microsoft driver names assumed here are:
        # * SQL Server
        # * SQL Native Client
        # * SQL Server Native Client 10.0/11.0
        # * ODBC Driver 11 for SQL Server
        ms_drivers = re.compile('.*SQL (Server$|(Server )?Native Client)')

        cstr_parts = []
        if dsn:
            cstr_parts.append('DSN=%s' % dsn)
        else:
            # Only append DRIVER if DATABASE_ODBC_DSN hasn't been set
            cstr_parts.append('DRIVER={%s}' % driver)
            if ms_drivers.match(driver) or driver == 'FreeTDS' and \
                options.get('host_is_server', False):
                if port:
                    host += ';PORT=%s' % port
                cstr_parts.append('SERVER=%s' % host)
            else:
                cstr_parts.append('SERVERNAME=%s' % host)

        if user:
            cstr_parts.append('UID=%s;PWD=%s' % (user, password))
        else:
            if ms_drivers.match(driver):
                cstr_parts.append('Trusted_Connection=yes')
            else:
                cstr_parts.append('Integrated Security=SSPI')

        cstr_parts.append('DATABASE=%s' % database)

        if self.supports_mars:
            cstr_parts.append('MARS_Connection=yes')
                
        if options.get('extra_params', None):
            cstr_parts.append(options['extra_params'])

        connstr = ';'.join(cstr_parts)
        unicode_results = options.get('unicode_results', False)

        conn = Database.connect(connstr, unicode_results=unicode_results)

        drv_name = conn.getinfo(Database.SQL_DRIVER_NAME).upper()

        driver_is_freetds = drv_name.startswith('LIBTDSODBC')
        if driver_is_freetds:
            self.use_legacy_datetime = True
            self.supports_mars = False

        ms_drv_names = re.compile('^(LIB)?(SQLN?CLI|MSODBCSQL)')

        if drv_name == 'SQLSRV32.DLL' or ms_drv_names.match(drv_name):
            self.driver_needs_utf8 = False

        # http://msdn.microsoft.com/en-us/library/ms131686.aspx
        if self.supports_mars and ms_drv_names.match(drv_name):
            # How to to activate it: Add 'MARS_Connection': True
            # to the OPTIONS dictionary setting
            self.features.can_use_chunked_reads = True

        # FreeTDS can't execute some sql queries like CREATE DATABASE etc.
        # in multi-statement, so we need to commit the above SQL sentence(s)
        # to avoid this
        if driver_is_freetds and not conn_params['AUTOCOMMIT']:
            conn.commit()

        return conn

    def init_connection_state(self):
        if self.sql_server_version < 2008:
            self.use_legacy_datetime = True
            self.features.has_bulk_insert = False

        if self.use_legacy_datetime:
            self.creation.use_legacy_datetime()
            self.features.supports_microsecond_precision = False

        settings_dict = self.settings_dict
        cursor = self._create_cursor()

        # Set date format for the connection. Also, make sure Sunday is
        # considered the first day of the week (to be consistent with the
        # Django convention for the 'week_day' Django lookup) if the user
        # hasn't told us otherwise
        options = settings_dict.get('OPTIONS', {})
        datefirst = options.get('datefirst', 7)
        cursor.execute('SET DATEFORMAT ymd; SET DATEFIRST %s' % datefirst)

    def is_usable(self):
        try:
            # use a pyodbc cursor directly, bypassing Django's utilities.
            self._create_cursor().execute("SELECT 1")
        except Database.Error:
            return False
        else:
            return True

    @cached_property
    def sql_server_version(self):
        with self.temporary_connection():
            # use a pyodbc cursor directly, bypassing Django's utilities.
            cursor = self._create_cursor()
            cursor.execute("SELECT CAST(SERVERPROPERTY('ProductVersion') AS varchar)")
            ver = cursor.fetchone()[0]
            ver = int(ver.split('.')[0])
            if not ver in self._sql_server_versions:
                raise NotImplementedError('SQL Server v%d is not supported.' % ver)
            return self._sql_server_versions[ver]

    @cached_property
    def to_azure_sql_db(self):
        with self.temporary_connection():
            # use a pyodbc cursor directly, bypassing Django's utilities.
            cursor = self._create_cursor()
            cursor.execute("SELECT CAST(SERVERPROPERTY('EngineEdition') AS integer)")
            return cursor.fetchone()[0] == EDITION_AZURE_SQL_DB

    def _create_cursor(self):
        if self.supports_mars:
            cursor = self.connection.cursor()
        else:
            if not self.open_cursor:
                self.open_cursor = self.connection.cursor()
            cursor = self.open_cursor
        return cursor

    def _cursor_closed(self, cursor):
        if not self.supports_mars:
            self.open_cursor = None

    def _execute_foreach(self, sql, table_names=None):
        cursor = self.cursor()
        if not table_names:
            table_names = self.introspection.get_table_list(cursor)
        for table_name in table_names:
            cursor.execute(sql % self.ops.quote_name(table_name))

    def _on_error(self, e):
        if e.args[0] in self._codes_for_networkerror:
            try:
                # close the stale connection
                self.close()
                # wait a moment for recovery from network error
                import time
                time.sleep(self.connection_recovery_interval_msec)
            except:
                pass
            self.connection = None

    def _savepoint(self, sid):
        cursor = self.cursor()
        cursor.execute('SELECT @@TRANCOUNT')
        trancount = cursor.fetchone()[0]
        if trancount == 0:
            cursor.execute(self.ops.start_transaction_sql())
        cursor.execute(self.ops.savepoint_create_sql(sid))

    def _savepoint_commit(self, sid):
        # SQL Server has no support for partial commit in a transaction
        pass

    def _set_autocommit(self, autocommit):
        if autocommit:
            self.connection.commit()
        else:
            self.connection.rollback()
        self.connection.autocommit = autocommit

    def check_constraints(self, table_names=None):
        self._execute_foreach('ALTER TABLE %s WITH CHECK CHECK CONSTRAINT ALL',
                              table_names)

    def disable_constraint_checking(self):
        # Windows Azure SQL Database doesn't support sp_msforeachtable
        #cursor.execute('EXEC sp_msforeachtable "ALTER TABLE ? NOCHECK CONSTRAINT ALL"')
        self._execute_foreach('ALTER TABLE %s NOCHECK CONSTRAINT ALL')
        return True

    def enable_constraint_checking(self):
        # Windows Azure SQL Database doesn't support sp_msforeachtable
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

    def close(self):
        self.cursor.close()
        self.connection._cursor_closed(self)

    def format_sql(self, sql, n_params=0):
        if self.driver_needs_utf8 and isinstance(sql, text_type):
            # FreeTDS (and other ODBC drivers?) doesn't support Unicode
            # yet, so we need to encode the SQL clause itself in utf-8
            sql = smart_str(sql, 'utf-8')

        # pyodbc uses '?' instead of '%s' as parameter placeholder.
        if n_params > 0:
            sql = sql % tuple('?' * n_params)

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
        params = self.format_params(params)
        sql = self.format_sql(sql, len(params))
        self.last_params = params
        try:
            return self.cursor.execute(sql, params)
        except Database.Error as e:
            self.connection._on_error(e)
            raise

    def executemany(self, sql, params_list=()):
        if not params_list:
            return None
        raw_pll = params_list
        params_list = [self.format_params(p) for p in raw_pll]
        sql = self.format_sql(sql, len(params_list[0]))
        try:
            return self.cursor.executemany(sql, params_list)
        except Database.Error as e:
            self.connection._on_error(e)
            raise

    def format_rows(self, rows):
        return list(map(self.format_row, rows))

    def format_row(self, row):
        """
        Decode data coming from the database if needed and convert rows to tuples
        (pyodbc Rows are not sliceable).
        """
        if not (settings.USE_TZ or self.driver_needs_utf8):
            return row

        for i in range(len(row)):
            f = row[i]
            if isinstance(f, datetime.datetime):
                if settings.USE_TZ:
                    row[i] = f.replace(tzinfo=utc)
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
