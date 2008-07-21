DATA_TYPES = {
    'AutoField':         'int IDENTITY (1, 1)',
    'BooleanField':      'bit',
    'BooleanField':      'smallint',
    'CharField':         'nvarchar(%(max_length)s)',
    'CommaSeparatedIntegerField': 'nvarchar(%(max_length)s)',
    'DateField':         'datetime',
    'DateTimeField':     'datetime',
    'DecimalField':      'numeric(%(max_digits)s, %(decimal_places)s)',
    'FileField':         'nvarchar(254) ',
    'FilePathField':     'nvarchar(254) ',
    'FloatField':        'double precision',
    'ImageField':        'nvarchar(254)',
    'IntegerField':      'int',
    'IPAddressField':    'nvarchar(15)',
    'ManyToManyField':   None,
    'NullBooleanField':  'bit',
    'OneToOneField':     'int',
    'PhoneNumberField':  'nvarchar(20) ',
    'PositiveIntegerField': 'int CHECK ([%(column)s] >= 0)',    
    'PositiveSmallIntegerField': 'smallint CHECK ([%(column)s] >= 0)',
    'SlugField':         'nvarchar(%(max_length)s)',
    'SmallIntegerField': 'smallint',
    'TextField':         'ntext',
    'TimeField':         'datetime',
    'USStateField':      'nchar(2)',
}

def destroy_test_db(settings, connection, old_database_name, verbosity=1):
    connection.close()
    TEST_DATABASE_NAME = settings.DATABASE_NAME
    settings.DATABASE_NAME = old_database_name
    cursor = connection.cursor()
    connection.connection.autocommit = True
    cursor.execute("ALTER DATABASE %s SET SINGLE_USER WITH ROLLBACK IMMEDIATE " % connection.ops.quote_name(TEST_DATABASE_NAME))
    cursor.execute("DROP DATABASE %s" %connection.ops.quote_name(TEST_DATABASE_NAME))
    connection.close()


    