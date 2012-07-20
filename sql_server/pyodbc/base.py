"""
MS SQL Server database backend for Django.
"""

try:
    import pyodbc as Database
except ImportError, e:
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured("Error loading pyodbc module: %s" % e)

import re
m = re.match(r'(\d+)\.(\d+)\.(\d+)(?:-beta(\d+))?', Database.version)
vlist = list(m.groups())
if vlist[3] is None: vlist[3] = '9999'
pyodbc_ver = tuple(map(int, vlist))
if pyodbc_ver < (2, 0, 38, 9999):
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured("pyodbc 2.0.38 or newer is required; you have %s" % Database.version)

from django.db.backends import BaseDatabaseWrapper, BaseDatabaseFeatures, BaseDatabaseValidation
from django.db.backends.signals import connection_created
from django.conf import settings
from django import VERSION as DjangoVersion
if DjangoVersion[:2] == (1,4):
    # Django version 1.4 adds a backwards incompatible change to
    # DatabaseOperations
    _DJANGO_VERSION = 14
elif DjangoVersion[:2] == (1,2) :
    from django import get_version
    version_str = get_version()
    if 'SVN' in version_str and int(version_str.split('SVN-')[-1]) < 11952: # django trunk revision 11952 Added multiple database support.
        _DJANGO_VERSION = 11
    else:
        _DJANGO_VERSION = 12
elif DjangoVersion[:2] == (1,1):
    _DJANGO_VERSION = 11
elif DjangoVersion[:2] == (1,0):
    _DJANGO_VERSION = 10
elif DjangoVersion[0] == 1:
    _DJANGO_VERSION = 13
else:
    _DJANGO_VERSION = 9
    
from sql_server.pyodbc.operations import DatabaseOperations
from sql_server.pyodbc.client import DatabaseClient
from sql_server.pyodbc.creation import DatabaseCreation
from sql_server.pyodbc.introspection import DatabaseIntrospection
import os
import warnings

warnings.filterwarnings('error', 'The DATABASE_ODBC.+ is deprecated', DeprecationWarning, __name__, 0)

collation = 'Latin1_General_CI_AS'
if hasattr(settings, 'DATABASE_COLLATION'):
    warnings.warn(
        "The DATABASE_COLLATION setting is going to be deprecated, use DATABASE_OPTIONS['collation'] instead.",
        DeprecationWarning
    )
    collation = settings.DATABASE_COLLATION
elif hasattr(settings, 'DATABASE_OPTIONS') and 'collation' in settings.DATABASE_OPTIONS:
    collation = settings.DATABASE_OPTIONS['collation']

deprecated = (
    ('DATABASE_ODBC_DRIVER', 'driver'),
    ('DATABASE_ODBC_DSN', 'dsn'),
    ('DATABASE_ODBC_EXTRA_PARAMS', 'extra_params'),
)
for old, new in deprecated:
    if hasattr(settings, old):
        warnings.warn(
            "The %s setting is deprecated, use DATABASE_OPTIONS['%s'] instead." % (old, new),
            DeprecationWarning
        )

DatabaseError = Database.DatabaseError
IntegrityError = Database.IntegrityError

class DatabaseFeatures(BaseDatabaseFeatures):
    uses_custom_query_class = True
    can_use_chunked_reads = False
    can_return_id_from_insert = True
    #uses_savepoints = True


class DatabaseWrapper(BaseDatabaseWrapper):
    _DJANGO_VERSION = _DJANGO_VERSION

    drv_name = None
    driver_needs_utf8 = None
    MARS_Connection = False
    unicode_results = False
    datefirst = 7

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
        'exact': '= %s',
        'iexact': "= UPPER(%s)",
        'contains': "LIKE %s ESCAPE '\\' COLLATE " + collation,
        'icontains': "LIKE UPPER(%s) ESCAPE '\\' COLLATE "+ collation,
        'gt': '> %s',
        'gte': '>= %s',
        'lt': '< %s',
        'lte': '<= %s',
        'startswith': "LIKE %s ESCAPE '\\' COLLATE " + collation,
        'endswith': "LIKE %s ESCAPE '\\' COLLATE " + collation,
        'istartswith': "LIKE UPPER(%s) ESCAPE '\\' COLLATE " + collation,
        'iendswith': "LIKE UPPER(%s) ESCAPE '\\' COLLATE " + collation,

        # TODO: remove, keep native T-SQL LIKE wildcards support
        # or use a "compatibility layer" and replace '*' with '%'
        # and '.' with '_'
        'regex': 'LIKE %s COLLATE ' + collation,
        'iregex': 'LIKE %s COLLATE ' + collation,

        # TODO: freetext, full-text contains...
    }

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

        if _DJANGO_VERSION >= 13:
            self.features = DatabaseFeatures(self)
        else:
            self.features = DatabaseFeatures()

        self.ops = DatabaseOperations(self)
        self.client = DatabaseClient(self)
        self.creation = DatabaseCreation(self)
        self.introspection = DatabaseIntrospection(self)
        if _DJANGO_VERSION >= 12:
            self.validation = BaseDatabaseValidation(self)
        else:
            self.validation = BaseDatabaseValidation()

        self.connection = None

    def _cursor(self):
        new_conn = False
        settings_dict = self.settings_dict
        db_str, user_str, passwd_str, port_str = None, None, "", None
        if _DJANGO_VERSION >= 12:
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
        else:
            options = settings_dict['DATABASE_OPTIONS']
            if settings_dict['DATABASE_NAME']:
                db_str = settings_dict['DATABASE_NAME']
            if settings_dict['DATABASE_HOST']:
                host_str = settings_dict['DATABASE_HOST']
            else:
                host_str = 'localhost'
            if settings_dict['DATABASE_USER']:
                user_str = settings_dict['DATABASE_USER']
            if settings_dict['DATABASE_PASSWORD']:
                passwd_str = settings_dict['DATABASE_PASSWORD']
            if settings_dict['DATABASE_PORT']:
                port_str = settings_dict['DATABASE_PORT']
        if self.connection is None:
            new_conn = True
            if not db_str:
                from django.core.exceptions import ImproperlyConfigured
                raise ImproperlyConfigured('You need to specify NAME in your Django settings file.')

            cstr_parts = []
            if 'driver' in options:
                driver = options['driver']
            else:
                if os.name == 'nt':
                    driver = 'SQL Server'
                else:
                    driver = 'FreeTDS'

            if 'dsn' in options:
                cstr_parts.append('DSN=%s' % options['dsn'])
            else:
                # Only append DRIVER if DATABASE_ODBC_DSN hasn't been set
                cstr_parts.append('DRIVER={%s}' % driver)
                
                if os.name == 'nt' or driver == 'FreeTDS' and \
                        options.get('host_is_server', False):
                    if port_str:
                        host_str += ';PORT=%s' % port_str
                    cstr_parts.append('SERVER=%s' % host_str)
                else:
                    cstr_parts.append('SERVERNAME=%s' % host_str)

            if user_str:
                cstr_parts.append('UID=%s;PWD=%s' % (user_str, passwd_str))
            else:
                if driver in ('SQL Server', 'SQL Native Client'):
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
            connection_created.send(sender=self.__class__)

        cursor = self.connection.cursor()
        if new_conn:
            # Set date format for the connection. Also, make sure Sunday is
            # considered the first day of the week (to be consistent with the
            # Django convention for the 'week_day' Django lookup) if the user
            # hasn't told us otherwise
            cursor.execute("SET DATEFORMAT ymd; SET DATEFIRST %s" % self.datefirst)
            if self.ops.sql_server_ver < 2005:
                self.creation.data_types['TextField'] = 'ntext'
                self.features.can_return_id_from_insert = False

            self.drv_name = self.connection.getinfo(Database.SQL_DRIVER_NAME).upper()

            if self.driver_needs_utf8 is None:
                self.driver_needs_utf8 = False
                if self.drv_name in ('SQLSRV32.DLL', 'SQLNCLI.DLL', 'SQLNCLI10.DLL'):
                    self.driver_needs_utf8 = False

            # http://msdn.microsoft.com/en-us/library/ms131686.aspx
            if self.ops.sql_server_ver >= 2005 and self.drv_name in ('SQLNCLI.DLL', 'SQLNCLI10.DLL') and self.MARS_Connection:
                # How to to activate it: Add 'MARS_Connection': True
                # to the DATABASE_OPTIONS dictionary setting
                self.features.can_use_chunked_reads = True

            # FreeTDS can't execute some sql queries like CREATE DATABASE etc.
            # in multi-statement, so we need to commit the above SQL sentence(s)
            # to avoid this
            if self.drv_name.startswith('LIBTDSODBC') and not self.connection.autocommit:
                self.connection.commit()

        return CursorWrapper(cursor, self.driver_needs_utf8)


class CursorWrapper(object):
    """
    A wrapper around the pyodbc's cursor that takes in account a) some pyodbc
    DB-API 2.0 implementation and b) some common ODBC driver particularities.
    """
    def __init__(self, cursor, driver_needs_utf8):
        self.cursor = cursor
        self.driver_needs_utf8 = driver_needs_utf8
        self.last_sql = ''
        self.last_params = ()

    def format_sql(self, sql, n_params=None):
        if self.driver_needs_utf8 and isinstance(sql, unicode):
            # FreeTDS (and other ODBC drivers?) doesn't support Unicode
            # yet, so we need to encode the SQL clause itself in utf-8
            sql = sql.encode('utf-8')

        # pyodbc uses '?' instead of '%s' as parameter placeholder.
        if n_params is not None:
            sql = sql % tuple('?' * n_params)
        else:
            if '%s' in sql:
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

    def format_rows(self, rows):
        return map(self.format_row, rows)

    def format_row(self, row):
        """
        Decode data coming from the database if needed and convert rows to tuples
        (pyodbc Rows are not sliceable).
        """

        if not self.driver_needs_utf8:
            return tuple(row)

        # FreeTDS (and other ODBC drivers?) doesn't support Unicode
        # yet, so we need to decode utf-8 data coming from the DB
        out = []
        for f in row:
            if isinstance(f, str):
                out.append(f.decode('utf-8'))
            else:
                out.append(f)

        return tuple(out)

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is not None:
            return self.format_row(row)
        return []

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
