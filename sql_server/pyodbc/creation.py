from django.db.backends.creation import BaseDatabaseCreation

class DatabaseCreation(BaseDatabaseCreation):
    data_types = {
        'AutoField':         'int IDENTITY (1, 1)',
        'BooleanField':      'bit',
        'CharField':         'nvarchar(%(max_length)s)',
        'CommaSeparatedIntegerField': 'nvarchar(%(max_length)s)',
        'DateField':         'datetime',
        'DateTimeField':     'datetime',
        'DecimalField':      'numeric(%(max_digits)s, %(decimal_places)s)',
        'FileField':         'nvarchar(%(max_length)s)',
        'FilePathField':     'nvarchar(%(max_length)s)',
        'FloatField':        'double precision',
        'IntegerField':      'int',
        'IPAddressField':    'nvarchar(15)',
        'ManyToManyField':   None,
        'NullBooleanField':  'bit',
        'OneToOneField':     'int',
        'PositiveIntegerField': 'int CHECK ([%(column)s] >= 0)',
        'PositiveSmallIntegerField': 'smallint CHECK ([%(column)s] >= 0)',
        'SlugField':         'nvarchar(%(max_length)s)',
        'SmallIntegerField': 'smallint',
        'TextField':         'nvarchar(max)',
        'TimeField':         'datetime',
    }

    def _destroy_test_db(self, test_database_name, verbosity):
        cursor = self.connection.cursor()
        if not self.connection.connection.autocommit:
            self.connection.connection.commit()
        self.connection.connection.autocommit = True
        cursor.execute("ALTER DATABASE %s SET SINGLE_USER WITH ROLLBACK IMMEDIATE " % self.connection.ops.quote_name(test_database_name))
        cursor.execute("DROP DATABASE %s" %self.connection.ops.quote_name(test_database_name))
        self.connection.close()



