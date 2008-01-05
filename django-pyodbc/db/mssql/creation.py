DATA_TYPES = {
    'AutoField':         'int IDENTITY (1, 1)',
    'BooleanField':      'bit',
    'CharField':         'nvarchar(%(max_length)s) %(db_collation)s',
    'CommaSeparatedIntegerField': 'nvarchar(%(max_length)s) %(db_collation)s',
    'DateField':         'datetime',
    'DateTimeField':     'datetime',
    'DecimalField':      'numeric(%(max_digits)s, %(decimal_places)s)',
    'FileField':         'nvarchar(254) %(db_collation)s',
    'FilePathField':     'nvarchar(254) %(db_collation)s',
    'FloatField':        'double precision',
    'ImageField':        'nvarchar(254) %(db_collation)s',
    'IntegerField':      'int',
    'IPAddressField':    'nvarchar(15)',
    'ManyToManyField':   None,
    'NullBooleanField':  'bit',
    'OneToOneField':     'int',
    'PhoneNumberField':  'nvarchar(20) %(db_collation)s',
    #The check must be unique in for the database. Put random so the regresion test not complain about duplicate names
    'PositiveIntegerField': 'int CONSTRAINT [CK_int_pos_%(creation_counter)s_%(column)s] CHECK ([%(column)s] > 0)',    
    'PositiveSmallIntegerField': 'smallint CONSTRAINT [CK_smallint_pos_%(creation_counter)s_%(column)s] CHECK ([%(column)s] > 0)',
    'SlugField':         'nvarchar(%(max_length)s) %(db_collation)s',
    'SmallIntegerField': 'smallint',
    'TextField':         'ntext %(db_collation)s',
    'TimeField':         'datetime',
    'USStateField':      'nchar(2) %(db_collation)s',
}

# TODO: how should this import look like? from db .. import ..
from operations import sql_server_version, SQL_SERVER_2005_VERSION
if sql_server_version() >= SQL_SERVER_2005_VERSION:
    DATA_TYPES['TextField'] = 'nvarchar(max) %(db_collation)s'
