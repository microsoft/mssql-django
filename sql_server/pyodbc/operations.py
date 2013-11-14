import datetime
import time

from django.conf import settings
from django.db.backends import BaseDatabaseOperations
from django.utils import timezone
from django.utils.six import string_types


class DatabaseOperations(BaseDatabaseOperations):
    _aggregate_functions = (
        'AVG',
        'COUNT',
        'COUNT_BIG',
        'MAX',
        'MIN',
        'STDEV',
        'STDEVP',
        'SUM',
        'VAR',
        'VARP',
    )
    compiler_module = 'sql_server.pyodbc.compiler'
    def __init__(self, connection):
        super(DatabaseOperations, self).__init__(connection)

    def bulk_batch_size(self, fields, objs):
        """
        Returns the maximum allowed batch size for the backend. The fields
        are the fields going to be inserted in the batch, the objs contains
        all the objects to be inserted.
        """
        objs_len, fields_len, max_row_values = len(objs), len(fields), 1000
        if (objs_len * fields_len) <= max_row_values:
            size = objs_len
        else:
            size = max_row_values // fields_len
        return size

    def bulk_insert_sql(self, fields, num_values):
        items_sql = "(%s)" % ", ".join(["%s"] * len(fields))
        return "VALUES " + ", ".join([items_sql] * num_values)

    def check_aggregate_support(self, aggregate):
        if not aggregate.sql_function.upper() in self._aggregate_functions:
            raise NotImplementedError('SQL Server has no support for the function %s.'
                                      % aggregate.sql_function)

    def cache_key_culling_sql(self):
        """
        Returns a SQL query that retrieves the first cache key greater than the
        smallest.

        This is used by the 'db' cache backend to determine where to start
        culling.
        """
        return "SELECT cache_key FROM (SELECT cache_key, " \
               "ROW_NUMBER() OVER (ORDER BY cache_key) AS rn FROM %s" \
               ") cache WHERE rn = %%s + 1"

    def date_extract_sql(self, lookup_type, field_name):
        """
        Given a lookup_type of 'year', 'month', 'day' or 'week_day', returns
        the SQL that extracts a value from the given date field field_name.
        """
        if lookup_type == 'week_day':
            return "DATEPART(dw, %s)" % field_name
        else:
            return "DATEPART(%s, %s)" % (lookup_type, field_name)

    def date_interval_sql(self, sql, connector, timedelta):
        """
        implements the interval functionality for expressions
        """
        sign = 1
        if connector != '+':
            sign = -1
        sec = (timedelta.seconds + timedelta.days * 86400) * sign
        if sec:
            sql = 'DATEADD(SECOND, %d, CAST(%s AS DATETIME))' % (sec, sql)
        if timedelta.microseconds and self.connection.sql_server_version >= 2008:
            sql = 'DATEADD(MICROSECOND, %d, CAST(%s AS DATETIME2))' % \
                (timedelta.microseconds * sign, sql)
        return sql

    def date_trunc_sql(self, lookup_type, field_name):
        """
        Given a lookup_type of 'year', 'month' or 'day', returns the SQL that
        truncates the given date field field_name to a date object with only
        the given specificity.
        """
        if lookup_type == 'year':
            return "CONVERT(datetime, CONVERT(varchar, DATEPART(year, %s)) + '/01/01')" % field_name
        if lookup_type == 'month':
            return "CONVERT(datetime, CONVERT(varchar, DATEPART(year, %s)) + '/' + CONVERT(varchar, DATEPART(month, %s)) + '/01')" % (field_name, field_name)
        if lookup_type == 'day':
            return "CONVERT(datetime, CONVERT(varchar(12), %s, 112))" % field_name

    def datetime_extract_sql(self, lookup_type, field_name, tzname):
        if settings.USE_TZ:
            # see http://blogs.msdn.com/b/sqlprogrammability/archive/2008/03/18/using-time-zone-data-in-sql-server-2008.aspx
            raise NotImplementedError('SQL Server has no built-in support for tz database.')
        params = []
        sql = self.date_extract_sql(lookup_type, field_name)
        return sql, params

    def datetime_trunc_sql(self, lookup_type, field_name, tzname):
        if settings.USE_TZ:
            # see http://blogs.msdn.com/b/sqlprogrammability/archive/2008/03/18/using-time-zone-data-in-sql-server-2008.aspx
            raise NotImplementedError('SQL Server has no built-in support for tz database.')
        params = []
        sql = ''
        if lookup_type in ('year', 'month', 'day'):
            sql = self.date_trunc_sql(lookup_type, field_name)
        elif lookup_type == 'hour':
            sql = "CONVERT(datetime, SUBSTRING(CONVERT(varchar, %s, 20), 0, 14) + ':00:00')" % field_name
        elif lookup_type == 'minute':
            sql = "CONVERT(datetime, SUBSTRING(CONVERT(varchar, %s, 20), 0, 17) + ':00')" % field_name
        elif lookup_type == 'second':
            sql = "CONVERT(datetime, CONVERT(varchar, %s, 20))" % field_name
        return sql, params

    def for_update_sql(self, nowait=False):
        """
        Returns the FOR UPDATE SQL clause to lock rows for an update operation.
        """
        if nowait:
            return 'WITH (NOWAIT, ROWLOCK, UPDLOCK)'
        else:
            return 'WITH (ROWLOCK, UPDLOCK)'

    def fulltext_search_sql(self, field_name):
        """
        Returns the SQL WHERE clause to use in order to perform a full-text
        search of the given field_name. Note that the resulting string should
        contain a '%s' placeholder for the value being searched against.
        """
        return 'CONTAINS(%s, %%s)' % field_name

    def last_insert_id(self, cursor, table_name, pk_name):
        """
        Given a cursor object that has just performed an INSERT statement into
        a table that has an auto-incrementing ID, returns the newly created ID.

        This method also receives the table name and the name of the primary-key
        column.
        """
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
        cursor.execute("SELECT CAST(IDENT_CURRENT(%s) as bigint)", [table_name])
        return cursor.fetchone()[0]

    def lookup_cast(self, lookup_type):
        if lookup_type in ('iexact', 'icontains', 'istartswith', 'iendswith'):
            return "UPPER(%s)"
        return "%s"

    def max_name_length(self):
        return 128

    def no_limit_value(self):
        return None

    def quote_name(self, name):
        """
        Returns a quoted version of the given table, index or column name. Does
        not quote the given name if it's already been quoted.
        """
        if name.startswith('[') and name.endswith(']'):
            return name # Quoting once is enough.
        return '[%s]' % name

    def random_function_sql(self):
        """
        Returns a SQL expression that returns a random value.
        """
        return "RAND()"

    def regex_lookup(self, lookup_type):
        """
        Returns the string to use in a query when performing regular expression
        lookups (using "regex" or "iregex"). The resulting string should
        contain a '%s' placeholder for the column being searched against.

        If the feature is not supported (or part of it is not supported), a
        NotImplementedError exception can be raised.
        """
        raise NotImplementedError('SQL Server has no built-in regular expression support.')

    def last_executed_query(self, cursor, sql, params):
        """
        Returns a string of the query last executed by the given cursor, with
        placeholders replaced with actual values.

        `sql` is the raw query containing placeholders, and `params` is the
        sequence of parameters. These are used by default, but this method
        exists for database backends to provide a better implementation
        according to their own quoting schemes.
        """
        return super(DatabaseOperations, self).last_executed_query(cursor, cursor.last_sql, cursor.last_params)

    def savepoint_create_sql(self, sid):
        """
        Returns the SQL for starting a new savepoint. Only required if the
        "uses_savepoints" feature is True. The "sid" parameter is a string
        for the savepoint id.
        """
        return "SAVE TRANSACTION %s" % sid

    def savepoint_rollback_sql(self, sid):
        """
        Returns the SQL for rolling back the given savepoint.
        """
        return "ROLLBACK TRANSACTION %s" % sid

    def sql_flush(self, style, tables, sequences, allow_cascade=False):
        """
        Returns a list of SQL statements required to remove all data from
        the given database tables (without actually removing the tables
        themselves).

        The returned value also includes SQL statements required to reset DB
        sequences passed in :param sequences:.

        The `style` argument is a Style object as returned by either
        color_style() or no_style() in django.core.management.color.

        The `allow_cascade` argument determines whether truncation may cascade
        to tables with foreign keys pointing the tables being truncated.
        """
        if tables:
            # Cannot use TRUNCATE on tables that are referenced by a FOREIGN KEY
            # So must use the much slower DELETE
            from django.db import connections
            cursor = connections[self.connection.alias].cursor()
            # Try to minimize the risks of the braindeaded inconsistency in
            # DBCC CHEKIDENT(table, RESEED, n) behavior.
            seqs = []
            for seq in sequences:
                cursor.execute("SELECT COUNT(*) FROM %s" % self.quote_name(seq["table"]))
                rowcnt = cursor.fetchone()[0]
                elem = {}
                if rowcnt:
                    elem['start_id'] = 0
                else:
                    elem['start_id'] = 1
                elem.update(seq)
                seqs.append(elem)
            cursor.execute("SELECT TABLE_NAME, CONSTRAINT_NAME FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS WHERE CONSTRAINT_TYPE not in ('PRIMARY KEY','UNIQUE')")
            fks = cursor.fetchall()
            sql_list = ['ALTER TABLE %s NOCHECK CONSTRAINT %s;' % \
                    (self.quote_name(fk[0]), self.quote_name(fk[1])) for fk in fks]
            sql_list.extend(['%s %s %s;' % (style.SQL_KEYWORD('DELETE'), style.SQL_KEYWORD('FROM'),
                             style.SQL_FIELD(self.quote_name(table)) ) for table in tables])

            if self.connection.to_azure_sql_db:
                import warnings
                warnings.warn("The identity columns will never be reset " \
                              "on Windows Azure SQL Database.",
                              RuntimeWarning)
            else:
                # Then reset the counters on each table.
                sql_list.extend(['%s %s (%s, %s, %s) %s %s;' % (
                    style.SQL_KEYWORD('DBCC'),
                    style.SQL_KEYWORD('CHECKIDENT'),
                    style.SQL_FIELD(self.quote_name(seq["table"])),
                    style.SQL_KEYWORD('RESEED'),
                    style.SQL_FIELD('%d' % seq['start_id']),
                    style.SQL_KEYWORD('WITH'),
                    style.SQL_KEYWORD('NO_INFOMSGS'),
                    ) for seq in seqs])

            sql_list.extend(['ALTER TABLE %s CHECK CONSTRAINT %s;' % \
                    (self.quote_name(fk[0]), self.quote_name(fk[1])) for fk in fks])
            return sql_list
        else:
            return []

    def start_transaction_sql(self):
        """
        Returns the SQL statement required to start a transaction.
        """
        return "BEGIN TRANSACTION"

    def tablespace_sql(self, tablespace, inline=False):
        """
        Returns the SQL that will be appended to tables or rows to define
        a tablespace. Returns '' if the backend doesn't use tablespaces.
        """
        return "ON %s" % self.quote_name(tablespace)

    def prep_for_like_query(self, x):
        """Prepares a value for use in a LIKE query."""
        # http://msdn2.microsoft.com/en-us/library/ms179859.aspx
        from django.utils.encoding import force_text
        return force_text(x).replace('\\', '\\\\').replace('[', '[[]').replace('%', '[%]').replace('_', '[_]')

    def prep_for_iexact_query(self, x):
        """
        Same as prep_for_like_query(), but called for "iexact" matches, which
        need not necessarily be implemented using "LIKE" in the backend.
        """
        return x

    def value_to_db_datetime(self, value):
        """
        Transform a datetime value to an object compatible with what is expected
        by the backend driver for datetime columns.
        """
        if value is None:
            return None
        if settings.USE_TZ and timezone.is_aware(value):
            # pyodbc donesn't support datetimeoffset
            value = value.astimezone(timezone.utc)
        if not self.connection.features.supports_microsecond_precision:
            value = value.replace(microsecond=0)
        return value

    def value_to_db_time(self, value):
        """
        Transform a time value to an object compatible with what is expected
        by the backend driver for time columns.
        """
        if value is None:
            return None
        if self.connection.use_legacy_datetime:
            # SQL Server's datetime type doesn't support microseconds
            if isinstance(value, string_types):
                value = datetime.datetime(*(time.strptime(value, '%H:%M:%S')[:6]))
            else:
                value = datetime.datetime(1900, 1, 1, value.hour, value.minute, value.second)
        return value

    def year_lookup_bounds_for_date_field(self, value):
        """
        Returns a two-elements list with the lower and upper bound to be used
        with a BETWEEN operator to query a DateField value using a year
        lookup.

        `value` is an int, containing the looked-up year.
        """
        if self.connection.use_legacy_datetime:
            bounds = super(DatabaseOperations, self).year_lookup_bounds_for_datetime_field(value)
            bounds = [dt.replace(microsecond=0) for dt in bounds]
        else:
            bounds = super(DatabaseOperations, self).year_lookup_bounds_for_date_field(value)
        return bounds

    def year_lookup_bounds_for_datetime_field(self, value):
        """
        Returns a two-elements list with the lower and upper bound to be used
        with a BETWEEN operator to query a DateTimeField value using a year
        lookup.

        `value` is an int, containing the looked-up year.
        """
        bounds = super(DatabaseOperations, self).year_lookup_bounds_for_datetime_field(value)
        if settings.USE_TZ:
            # datetime values are saved as utc with no offset
            bounds = [dt.astimezone(timezone.utc) for dt in bounds]
        if not self.connection.features.supports_microsecond_precision:
            bounds = [dt.replace(microsecond=0) for dt in bounds]
        return bounds

    def convert_values(self, value, field):
        """
        Coerce the value returned by the database backend into a consistent
        type that is compatible with the field type.

        In our case, cater for the fact that SQL Server < 2008 has no
        separate Date and Time data types.
        """
        if value is None:
            return None
        if field and field.get_internal_type() == 'DateTimeField':
            return value
        elif field and field.get_internal_type() == 'DateField':
            if self.connection.use_legacy_datetime:
                if isinstance(value, datetime.datetime):
                    value = value.date() # extract date
        elif field and field.get_internal_type() == 'TimeField':
            if self.connection.use_legacy_datetime:
                if (isinstance(value, datetime.datetime) and value.year == 1900 and value.month == value.day == 1):
                    value = value.time() # extract time
        # Some cases (for example when select_related() is used) aren't
        # caught by the DateField case above and date fields arrive from
        # the DB as datetime instances.
        # Implement a workaround stealing the idea from the Oracle
        # backend. It's not perfect so the same warning applies (i.e. if a
        # query results in valid date+time values with the time part set
        # to midnight, this workaround can surprise us by converting them
        # to the datetime.date Python type).
        elif isinstance(value, datetime.datetime) and value.hour == value.minute == value.second == value.microsecond == 0:
            if self.connection.use_legacy_datetime:
                value = value.date()
        # Force floats to the correct type
        elif field and field.get_internal_type() == 'FloatField':
            value = float(value)
        return value
