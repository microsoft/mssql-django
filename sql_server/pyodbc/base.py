"""
MS SQL Server database backend for Django.
"""
import os
import re
import time

from django.core.exceptions import ImproperlyConfigured
from django import VERSION

if VERSION[:3] < (1,11,12) or VERSION[:2] >= (2,0):
    raise ImproperlyConfigured("Django %d.%d.%d is not supported." % VERSION[:3])

try:
    import pyodbc as Database
except ImportError as e:
    raise ImproperlyConfigured("Error loading pyodbc module: %s" % e)

pyodbc_ver = tuple(map(int, Database.version.split('.')[:2]))
if pyodbc_ver < (3, 0):
    raise ImproperlyConfigured("pyodbc 3.0 or newer is required; you have %s" % Database.version)

from django.conf import settings
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.backends.base.validation import BaseDatabaseValidation
from django.utils.encoding import smart_str
from django.utils.functional import cached_property
from django.utils.six import binary_type, text_type
from django.utils.timezone import utc

if hasattr(settings, 'DATABASE_CONNECTION_POOLING'):
    if not settings.DATABASE_CONNECTION_POOLING:
        Database.pooling = False

from .client import DatabaseClient
from .creation import DatabaseCreation
from .features import DatabaseFeatures
from .introspection import DatabaseIntrospection
from .operations import DatabaseOperations
from .schema import DatabaseSchemaEditor

EDITION_AZURE_SQL_DB = 5


def encode_connection_string(fields):
    """Encode dictionary of keys and values as an ODBC connection String.

    See [MS-ODBCSTR] document:
    https://msdn.microsoft.com/en-us/library/ee208909%28v=sql.105%29.aspx
    """
    # As the keys are all provided by us, don't need to encode them as we know
    # they are ok.
    return ';'.join(
        '%s=%s' % (k, encode_value(v))
        for k, v in fields.items()
    )

def encode_value(v):
    """If the value contains a semicolon, or starts with a left curly brace,
    then enclose it in curly braces and escape all right curly braces.
    """
    if ';' in v or v.strip(' ').startswith('{'):
        return '{%s}' % (v.replace('}', '}}'),)
    return v

class DatabaseWrapper(BaseDatabaseWrapper):
    vendor = 'microsoft'
    # This dictionary maps Field objects to their associated MS SQL column
    # types, as strings. Column-type strings can contain format strings; they'll
    # be interpolated against the values of Field.__dict__ before being output.
    # If a column type is set to None, it won't be included in the output.
    data_types = {
        'AutoField':         'int IDENTITY (1, 1)',
        'BigAutoField':      'bigint IDENTITY (1, 1)',
        'BigIntegerField':   'bigint',
        'BinaryField':       'varbinary(max)',
        'BooleanField':      'bit',
        'CharField':         'nvarchar(%(max_length)s)',
        'CommaSeparatedIntegerField': 'nvarchar(%(max_length)s)',
        'DateField':         'date',
        'DateTimeField':     'datetime2',
        'DecimalField':      'numeric(%(max_digits)s, %(decimal_places)s)',
        'DurationField':     'bigint',
        'FileField':         'nvarchar(%(max_length)s)',
        'FilePathField':     'nvarchar(%(max_length)s)',
        'FloatField':        'double precision',
        'IntegerField':      'int',
        'IPAddressField':    'nvarchar(15)',
        'GenericIPAddressField': 'nvarchar(39)',
        'NullBooleanField':  'bit',
        'OneToOneField':     'int',
        'PositiveIntegerField': 'int',
        'PositiveSmallIntegerField': 'smallint',
        'SlugField':         'nvarchar(%(max_length)s)',
        'SmallIntegerField': 'smallint',
        'TextField':         'nvarchar(max)',
        'TimeField':         'time',
        'UUIDField':         'char(32)',
    }
    data_type_check_constraints = {
        'PositiveIntegerField': '[%(column)s] >= 0',
        'PositiveSmallIntegerField': '[%(column)s] >= 0',
    }
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

    # The patterns below are used to generate SQL pattern lookup clauses when
    # the right-hand side of the lookup isn't a raw string (it might be an expression
    # or the result of a bilateral transformation).
    # In those cases, special characters for LIKE operators (e.g. \, *, _) should be
    # escaped on database side.
    #
    # Note: we use str.format() here for readability as '%' is used as a wildcard for
    # the LIKE operator.
    pattern_esc = r"REPLACE(REPLACE(REPLACE({}, '\', '[\]'), '%%', '[%%]'), '_', '[_]')"
    pattern_ops = {
        'contains': "LIKE '%%' + {} + '%%'",
        'icontains': "LIKE '%%' + UPPER({}) + '%%'",
        'startswith': "LIKE {} + '%%'",
        'istartswith': "LIKE UPPER({}) + '%%'",
        'endswith': "LIKE '%%' + {}",
        'iendswith': "LIKE '%%' + UPPER({})",
    }

    Database = Database
    SchemaEditorClass = DatabaseSchemaEditor
    # Classes instantiated in __init__().
    client_class = DatabaseClient
    creation_class = DatabaseCreation
    features_class = DatabaseFeatures
    introspection_class = DatabaseIntrospection
    ops_class = DatabaseOperations

    _codes_for_networkerror = (
        '08S01',
        '08S02',
    )
    _sql_server_versions = {
        9: 2005,
        10: 2008,
        11: 2012,
        12: 2014,
        13: 2016,
        14: 2017,
    }

    # https://azure.microsoft.com/en-us/documentation/articles/sql-database-develop-csharp-retry-windows/
    _transient_error_numbers = (
        '4060',
        '10928',
        '10929',
        '40197',
        '40501',
        '40613',
        '49918',
        '49919',
        '49920',
    )

    def __init__(self, *args, **kwargs):
        super(DatabaseWrapper, self).__init__(*args, **kwargs)

        opts = self.settings_dict["OPTIONS"]

        # capability for multiple result sets or cursors
        self.supports_mars = False

        # Some drivers need unicode encoded as UTF8. If this is left as
        # None, it will be determined based on the driver, namely it'll be
        # False if the driver is a windows driver and True otherwise.
        #
        # However, recent versions of FreeTDS and pyodbc (0.91 and 3.0.6 as
        # of writing) are perfectly okay being fed unicode, which is why
        # this option is configurable.
        if 'driver_needs_utf8' in opts:
            self.driver_charset = 'utf-8'
        else:
            self.driver_charset = opts.get('driver_charset', None)

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

    def create_cursor(self, name=None):
        return CursorWrapper(self.connection.cursor(), self)

    def get_connection_params(self):
        settings_dict = self.settings_dict
        if settings_dict['NAME'] == '':
            raise ImproperlyConfigured(
                "settings.DATABASES is improperly configured. "
                "Please supply the NAME value.")
        conn_params = settings_dict.copy()
        if conn_params['NAME'] is None:
            conn_params['NAME'] = 'master'
        return conn_params

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
        # * ODBC Driver 11/13 for SQL Server
        ms_drivers = re.compile('.*SQL (Server$|(Server )?Native Client)')

        # available ODBC connection string keywords:
        # (Microsoft drivers for Windows)
        # https://docs.microsoft.com/en-us/sql/relational-databases/native-client/applications/using-connection-string-keywords-with-sql-server-native-client
        # (Microsoft drivers for Linux/Mac)
        # https://docs.microsoft.com/en-us/sql/connect/odbc/linux-mac/connection-string-keywords-and-data-source-names-dsns
        # (FreeTDS)
        # http://www.freetds.org/userguide/odbcconnattr.htm
        cstr_parts = {}
        if dsn:
            cstr_parts['DSN'] = dsn
        else:
            # Only append DRIVER if DATABASE_ODBC_DSN hasn't been set
            cstr_parts['DRIVER'] = driver

            if ms_drivers.match(driver):
                if port:
                    host = ','.join((host, str(port)))
                cstr_parts['SERVER'] = host
            elif options.get('host_is_server', False):
                if port:
                    cstr_parts['PORT'] = str(port)
                cstr_parts['SERVER'] = host
            else:
                cstr_parts['SERVERNAME'] = host

        if user:
            cstr_parts['UID'] = user
            cstr_parts['PWD'] = password
        else:
            if ms_drivers.match(driver):
                cstr_parts['Trusted_Connection'] = 'yes'
            else:
                cstr_parts['Integrated Security'] = 'SSPI'

        cstr_parts['DATABASE'] = database

        if ms_drivers.match(driver) and not driver == 'SQL Server':
            self.supports_mars = True
        if self.supports_mars:
            cstr_parts['MARS_Connection'] = 'yes'

        connstr = encode_connection_string(cstr_parts)

        # extra_params are glued on the end of the string without encoding,
        # so it's up to the settings writer to make sure they're appropriate -
        # use encode_connection_string if constructing from external input.
        if options.get('extra_params', None):
            connstr += ';' + options['extra_params']

        unicode_results = options.get('unicode_results', False)
        timeout = options.get('connection_timeout', 0)
        retries = options.get('connection_retries', 5)
        backoff_time = options.get('connection_retry_backoff_time', 5)
        query_timeout = options.get('query_timeout', 0)

        conn = None
        retry_count = 0
        need_to_retry = False
        while conn is None:
            try:
                conn = Database.connect(connstr,
                                        unicode_results=unicode_results,
                                        timeout=timeout)
            except Exception as e:
                for error_number in self._transient_error_numbers:
                    if error_number in e.args[1]:
                        if error_number in e.args[1] and retry_count < retries:
                            time.sleep(backoff_time)
                            need_to_retry = True
                            retry_count = retry_count + 1
                        else:
                            need_to_retry = False
                        break
                if not need_to_retry:
                    raise

        conn.timeout = query_timeout
        return conn

    def init_connection_state(self):
        drv_name = self.connection.getinfo(Database.SQL_DRIVER_NAME).upper()
        driver_is_freetds = drv_name.startswith('LIBTDSODBC')
        driver_is_sqlsrv32 = drv_name == 'SQLSRV32.DLL'

        if driver_is_freetds:
            self.supports_mars = False
            try:
                drv_ver = self.connection.getinfo(Database.SQL_DRIVER_VER)
                ver = tuple(map(int, drv_ver.split('.')[:2]))
                if ver < (0, 95):
                    # FreeTDS can't execute some sql queries like CREATE DATABASE etc.
                    # in multi-statement, so we need to commit the above SQL sentence(s)
                    # to avoid this
                    self.connection.commit()
            except:
                # unknown driver version
                pass
        elif driver_is_sqlsrv32:
            self.supports_mars = False

        ms_drv_names = re.compile('^(LIB)?(SQLN?CLI|MSODBCSQL)')

        if driver_is_sqlsrv32 or ms_drv_names.match(drv_name):
            self.driver_charset = None

        # http://msdn.microsoft.com/en-us/library/ms131686.aspx
        if self.supports_mars and ms_drv_names.match(drv_name):
            self.features.can_use_chunked_reads = True

        if self.sql_server_version < 2008:
            self.features.has_bulk_insert = False

        settings_dict = self.settings_dict
        cursor = self.create_cursor()

        options = settings_dict.get('OPTIONS', {})
        isolation_level = options.get('isolation_level', None)
        if isolation_level:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL %s' % isolation_level)

        # Set date format for the connection. Also, make sure Sunday is
        # considered the first day of the week (to be consistent with the
        # Django convention for the 'week_day' Django lookup) if the user
        # hasn't told us otherwise
        datefirst = options.get('datefirst', 7)
        cursor.execute('SET DATEFORMAT ymd; SET DATEFIRST %s' % datefirst)

        # http://blogs.msdn.com/b/sqlnativeclient/archive/2008/02/27/microsoft-sql-server-native-client-and-microsoft-sql-server-2008-native-client.aspx
        try:
            val = cursor.execute('SELECT SYSDATETIME()').fetchone()[0]
            if isinstance(val, text_type):
                # the driver doesn't support the modern datetime types
                self.use_legacy_datetime = True
        except:
            # the server doesn't support the modern datetime types
            self.use_legacy_datetime = True
        if self.use_legacy_datetime:
            self._use_legacy_datetime()
            self.features.supports_microsecond_precision = False

    def is_usable(self):
        try:
            self.create_cursor().execute("SELECT 1")
        except Database.Error:
            return False
        else:
            return True

    def schema_editor(self, *args, **kwargs):
        "Returns a new instance of this backend's SchemaEditor"
        return DatabaseSchemaEditor(self, *args, **kwargs)

    @cached_property
    def sql_server_version(self, _known_versions={}):
        """
        Get the SQL server version

        The _known_versions default dictionary is created on the class. This is
        intentional - it allows us to cache this property's value across instances.
        Therefore, when Django creates a new database connection using the same
        alias, we won't need query the server again.
        """
        if self.alias not in _known_versions:
            with self.temporary_connection() as cursor:
                cursor.execute("SELECT CAST(SERVERPROPERTY('ProductVersion') AS varchar)")
                ver = cursor.fetchone()[0]
                ver = int(ver.split('.')[0])
                if not ver in self._sql_server_versions:
                    raise NotImplementedError('SQL Server v%d is not supported.' % ver)
                _known_versions[self.alias] = self._sql_server_versions[ver]
        return _known_versions[self.alias]

    @cached_property
    def to_azure_sql_db(self, _known_azures={}):
        """
        Whether this connection is to a Microsoft Azure database server

        The _known_azures default dictionary is created on the class. This is
        intentional - it allows us to cache this property's value across instances.
        Therefore, when Django creates a new database connection using the same
        alias, we won't need query the server again.
        """
        if self.alias not in _known_azures:
            with self.temporary_connection() as cursor:
                cursor.execute("SELECT CAST(SERVERPROPERTY('EngineEdition') AS integer)")
                _known_azures[self.alias] = cursor.fetchone()[0] == EDITION_AZURE_SQL_DB
        return _known_azures[self.alias]

    def _execute_foreach(self, sql, table_names=None):
        cursor = self.cursor()
        if table_names is None:
            table_names = self.introspection.table_names(cursor)
        for table_name in table_names:
            cursor.execute(sql % self.ops.quote_name(table_name))

    def _get_trancount(self):
        with self.connection.cursor() as cursor:
            return cursor.execute('SELECT @@TRANCOUNT').fetchone()[0]

    def _on_error(self, e):
        if e.args[0] in self._codes_for_networkerror:
            try:
                # close the stale connection
                self.close()
                # wait a moment for recovery from network error
                time.sleep(self.connection_recovery_interval_msec)
            except:
                pass
            self.connection = None

    def _savepoint(self, sid):
        with self.cursor() as cursor:
            cursor.execute('SELECT @@TRANCOUNT')
            trancount = cursor.fetchone()[0]
            if trancount == 0:
                cursor.execute(self.ops.start_transaction_sql())
            cursor.execute(self.ops.savepoint_create_sql(sid))

    def _savepoint_commit(self, sid):
        # SQL Server has no support for partial commit in a transaction
        pass

    def _savepoint_rollback(self, sid):
        with self.cursor() as cursor:
            # FreeTDS v0.95 requires TRANCOUNT that is greater than 0
            cursor.execute('SELECT @@TRANCOUNT')
            trancount = cursor.fetchone()[0]
            if trancount > 0:
                cursor.execute(self.ops.savepoint_rollback_sql(sid))

    def _set_autocommit(self, autocommit):
        with self.wrap_database_errors:
            allowed = not autocommit
            if not allowed:
                # FreeTDS v0.95 requires TRANCOUNT that is greater than 0
                allowed = self._get_trancount() > 0
            if allowed:
                self.connection.autocommit = autocommit

    def _use_legacy_datetime(self):
        for field in ('DateField', 'DateTimeField', 'TimeField'):
            self.data_types[field] = 'datetime'

    def check_constraints(self, table_names=None):
        self._execute_foreach('ALTER TABLE %s WITH CHECK CHECK CONSTRAINT ALL',
                              table_names)

    def disable_constraint_checking(self):
        # Azure SQL Database doesn't support sp_msforeachtable
        #cursor.execute('EXEC sp_msforeachtable "ALTER TABLE ? NOCHECK CONSTRAINT ALL"')
        if not self.needs_rollback:
            self._execute_foreach('ALTER TABLE %s NOCHECK CONSTRAINT ALL')
        return not self.needs_rollback

    def enable_constraint_checking(self):
        # Azure SQL Database doesn't support sp_msforeachtable
        #cursor.execute('EXEC sp_msforeachtable "ALTER TABLE ? WITH CHECK CHECK CONSTRAINT ALL"')
        if not self.needs_rollback:
            self.check_constraints()


class CursorWrapper(object):
    """
    A wrapper around the pyodbc's cursor that takes in account a) some pyodbc
    DB-API 2.0 implementation and b) some common ODBC driver particularities.
    """
    def __init__(self, cursor, connection):
        self.active = True
        self.cursor = cursor
        self.connection = connection
        self.driver_charset = connection.driver_charset
        self.last_sql = ''
        self.last_params = ()

    def close(self):
        if self.active:
            self.active = False
            self.cursor.close()

    def format_sql(self, sql, params):
        if self.driver_charset and isinstance(sql, text_type):
            # FreeTDS (and other ODBC drivers?) doesn't support Unicode
            # yet, so we need to encode the SQL clause itself in utf-8
            sql = smart_str(sql, self.driver_charset)

        # pyodbc uses '?' instead of '%s' as parameter placeholder.
        if params is not None:
            sql = sql % tuple('?' * len(params))

        return sql

    def format_params(self, params):
        fp = []
        if params is not None:
            for p in params:
                if isinstance(p, text_type):
                    if self.driver_charset:
                        # FreeTDS (and other ODBC drivers?) doesn't support Unicode
                        # yet, so we need to encode parameters in utf-8
                        fp.append(smart_str(p, self.driver_charset))
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

    def execute(self, sql, params=None):
        self.last_sql = sql
        sql = self.format_sql(sql, params)
        params = self.format_params(params)
        self.last_params = params
        try:
            return self.cursor.execute(sql, params)
        except Database.Error as e:
            self.connection._on_error(e)
            raise

    def executemany(self, sql, params_list=()):
        if not params_list:
            return None
        raw_pll = [p for p in params_list]
        sql = self.format_sql(sql, raw_pll[0])
        params_list = [self.format_params(p) for p in raw_pll]
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
        if self.driver_charset:
            for i in range(len(row)):
                f = row[i]
                # FreeTDS (and other ODBC drivers?) doesn't support Unicode
                # yet, so we need to decode utf-8 data coming from the DB
                if isinstance(f, binary_type):
                    row[i] = f.decode(self.driver_charset)
        return row

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is not None:
            row = self.format_row(row)
        # Any remaining rows in the current set must be discarded
        # before changing autocommit mode when you use FreeTDS
        self.cursor.nextset()
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
