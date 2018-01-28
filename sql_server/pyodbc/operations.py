import datetime
import uuid
import warnings

from django.conf import settings
from django.db.backends.base.operations import BaseDatabaseOperations
from django.utils import timezone
from django.utils.encoding import force_text

import pytz


class DatabaseOperations(BaseDatabaseOperations):
    compiler_module = 'sql_server.pyodbc.compiler'

    cast_char_field_without_max_length = 'nvarchar(max)'

    def _convert_field_to_tz(self, field_name, tzname):
        if settings.USE_TZ and not tzname == 'UTC':
            offset = self._get_utcoffset(tzname)
            field_name = 'DATEADD(second, %d, %s)' % (offset, field_name)
        return field_name

    def _get_utcoffset(self, tzname):
        """
        Returns UTC offset for given time zone in seconds
        """
        # SQL Server has no built-in support for tz database
        # see http://blogs.msdn.com/b/sqlprogrammability/archive/2008/03/18/using-time-zone-data-in-sql-server-2008.aspx
        zone = pytz.timezone(tzname)
        # no way to take DST into account at this point
        now = datetime.datetime.now()
        delta = zone.localize(now, is_dst=False).utcoffset()
        return delta.days * 86400 + delta.seconds

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

    def bulk_insert_sql(self, fields, placeholder_rows):
        placeholder_rows_sql = (", ".join(row) for row in placeholder_rows)
        values_sql = ", ".join("(%s)" % sql for sql in placeholder_rows_sql)
        return "VALUES " + values_sql

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

    def combine_duration_expression(self, connector, sub_expressions):
        lhs, rhs = sub_expressions
        sign = ' * -1' if connector == '-' else ''
        if lhs.startswith('DATEADD'):
            col, sql = rhs, lhs
        else:
            col, sql = lhs, rhs
        params = [sign for _ in range(sql.count('DATEADD'))]
        params.append(col)
        return sql % tuple(params)

    def combine_expression(self, connector, sub_expressions):
        """
        SQL Server requires special cases for some operators in query expressions
        """
        if connector == '^':
            return 'POWER(%s)' % ','.join(sub_expressions)
        elif connector == '<<':
            return '%s * (2 * %s)' % tuple(sub_expressions)
        elif connector == '>>':
            return '%s / (2 * %s)' % tuple(sub_expressions)
        return super().combine_expression(connector, sub_expressions)

    def convert_datetimefield_value(self, value, expression, connection):
        if value is not None:
            if settings.USE_TZ:
                value = timezone.make_aware(value, self.connection.timezone)
        return value

    def convert_floatfield_value(self, value, expression, connection):
        if value is not None:
            value = float(value)
        return value

    def convert_uuidfield_value(self, value, expression, connection):
        if value is not None:
            value = uuid.UUID(value)
        return value

    def date_extract_sql(self, lookup_type, field_name):
        if lookup_type == 'week_day':
            return "DATEPART(dw, %s)" % field_name
        else:
            return "DATEPART(%s, %s)" % (lookup_type, field_name)

    def date_interval_sql(self, timedelta):
        """
        implements the interval functionality for expressions
        """
        sec = timedelta.seconds + timedelta.days * 86400
        sql = 'DATEADD(second, %d%%s, CAST(%%s AS datetime2))' % sec
        if timedelta.microseconds:
            sql = 'DATEADD(microsecond, %d%%s, CAST(%s AS datetime2))' % (timedelta.microseconds, sql)
        return sql

    def date_trunc_sql(self, lookup_type, field_name):
        if lookup_type == 'year':
            return "CONVERT(datetime2, CONVERT(varchar, DATEPART(year, %s)) + '/01/01')" % field_name
        if lookup_type == 'quarter':
            return "CONVERT(datetime2, CONVERT(varchar, DATEPART(year, %s)) + '/' + CONVERT(varchar, 1+((DATEPART(quarter, %s)-1)*3)) + '/01')" % (field_name, field_name)
        if lookup_type == 'month':
            return "CONVERT(datetime2, CONVERT(varchar, DATEPART(year, %s)) + '/' + CONVERT(varchar, DATEPART(month, %s)) + '/01')" % (field_name, field_name)
        if lookup_type == 'day':
            return "CONVERT(datetime2, CONVERT(varchar(12), %s, 112))" % field_name

    def datetime_cast_date_sql(self, field_name, tzname):
        field_name = self._convert_field_to_tz(field_name, tzname)
        sql = 'CAST(%s AS date)' % field_name
        return sql

    def datetime_cast_time_sql(self, field_name, tzname):
        field_name = self._convert_field_to_tz(field_name, tzname)
        sql = 'CAST(%s AS time)' % field_name
        return sql

    def datetime_extract_sql(self, lookup_type, field_name, tzname):
        field_name = self._convert_field_to_tz(field_name, tzname)
        return self.date_extract_sql(lookup_type, field_name)

    def datetime_trunc_sql(self, lookup_type, field_name, tzname):
        field_name = self._convert_field_to_tz(field_name, tzname)
        sql = ''
        if lookup_type in ('year', 'quarter', 'month', 'day'):
            sql = self.date_trunc_sql(lookup_type, field_name)
        elif lookup_type == 'hour':
            sql = "CONVERT(datetime2, SUBSTRING(CONVERT(varchar, %s, 20), 0, 14) + ':00:00')" % field_name
        elif lookup_type == 'minute':
            sql = "CONVERT(datetime2, SUBSTRING(CONVERT(varchar, %s, 20), 0, 17) + ':00')" % field_name
        elif lookup_type == 'second':
            sql = "CONVERT(datetime2, CONVERT(varchar, %s, 20))" % field_name
        return sql

    def for_update_sql(self, nowait=False, skip_locked=False, of=()):
        if skip_locked:
            return 'WITH (ROWLOCK, UPDLOCK, READPAST)'
        elif nowait:
            return 'WITH (NOWAIT, ROWLOCK, UPDLOCK)'
        else:
            return 'WITH (ROWLOCK, UPDLOCK)'

    def format_for_duration_arithmetic(self, sql):
        if sql == '%s':
            # use DATEADD only once because Django prepares only one parameter for this 
            fmt = 'DATEADD(second, %s / 1000000%%s, CAST(%%s AS datetime2))'
            sql = '%%s'
        else:
            # use DATEADD twice to avoid arithmetic overflow for number part
            fmt = 'DATEADD(second, %s / 1000000%%s, DATEADD(microsecond, %s %%%%%%%% 1000000%%s, CAST(%%s AS datetime2)))'
            sql = (sql, sql)
        return fmt % sql

    def fulltext_search_sql(self, field_name):
        """
        Returns the SQL WHERE clause to use in order to perform a full-text
        search of the given field_name. Note that the resulting string should
        contain a '%s' placeholder for the value being searched against.
        """
        return 'CONTAINS(%s, %%s)' % field_name

    def get_db_converters(self, expression):
        converters = super().get_db_converters(expression)
        internal_type = expression.output_field.get_internal_type()
        if internal_type == 'DateTimeField':
            converters.append(self.convert_datetimefield_value)
        elif internal_type == 'FloatField':
            converters.append(self.convert_floatfield_value)
        elif internal_type == 'UUIDField':
            converters.append(self.convert_uuidfield_value)
        return converters

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
        cursor.execute("SELECT CAST(IDENT_CURRENT(%s) AS int)", [table_name])
        return cursor.fetchone()[0]

    def lookup_cast(self, lookup_type, internal_type=None):
        if lookup_type in ('iexact', 'icontains', 'istartswith', 'iendswith'):
            return "UPPER(%s)"
        return "%s"

    def max_name_length(self):
        return 128

    def no_limit_value(self):
        return None

    def prepare_sql_script(self, sql, _allow_fallback=False):
        return [sql]

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
        return super().last_executed_query(cursor, cursor.last_sql, cursor.last_params)

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

            if self.connection.to_azure_sql_db and self.connection.sql_server_version < 2014:
                warnings.warn("Resetting identity columns is not supported " \
                              "on this versios of Azure SQL Database.",
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

    def subtract_temporals(self, internal_type, lhs, rhs):
        lhs_sql, lhs_params = lhs
        rhs_sql, rhs_params = rhs
        if internal_type == 'DateField':
            sql = "CAST(DATEDIFF(day, %(rhs)s, %(lhs)s) AS bigint) * 86400 * 1000000"
            params = rhs_params + lhs_params
        else:
            sql = "CAST(DATEDIFF(second, %(rhs)s, %(lhs)s) AS bigint) * 1000000 + DATEPART(microsecond, %(lhs)s) - DATEPART(microsecond, %(rhs)s)"
            params = rhs_params + lhs_params * 2 + rhs_params
        return  sql % {'lhs':lhs_sql, 'rhs':rhs_sql}, params

    def tablespace_sql(self, tablespace, inline=False):
        """
        Returns the SQL that will be appended to tables or rows to define
        a tablespace. Returns '' if the backend doesn't use tablespaces.
        """
        return "ON %s" % self.quote_name(tablespace)

    def prep_for_like_query(self, x):
        """Prepares a value for use in a LIKE query."""
        # http://msdn2.microsoft.com/en-us/library/ms179859.aspx
        return force_text(x).replace('\\', '\\\\').replace('[', '[[]').replace('%', '[%]').replace('_', '[_]')

    def prep_for_iexact_query(self, x):
        """
        Same as prep_for_like_query(), but called for "iexact" matches, which
        need not necessarily be implemented using "LIKE" in the backend.
        """
        return x

    def adapt_datetimefield_value(self, value):
        """
        Transforms a datetime value to an object compatible with what is expected
        by the backend driver for datetime columns.
        """
        if value is None:
            return None
        if settings.USE_TZ and timezone.is_aware(value):
            # pyodbc donesn't support datetimeoffset
            value = value.astimezone(self.connection.timezone).replace(tzinfo=None)
        return value

    def time_trunc_sql(self, lookup_type, field_name):
        #if self.connection.sql_server_version >= 2012:
        #    fields = {
        #        'hour': 'DATEPART(hour, %s)' % field_name,
        #        'minute': 'DATEPART(minute, %s)' % field_name if lookup_type != 'hour' else '0',
        #        'second': 'DATEPART(second, %s)' % field_name if lookup_type == 'second' else '0',
        #    }
        #    sql = 'TIMEFROMPARTS(%(hour)s, %(minute)s, %(second)s, 0, 0)' % fields
        if lookup_type == 'hour':
            sql = "CONVERT(time, SUBSTRING(CONVERT(varchar, %s, 114), 0, 3) + ':00:00')" % field_name
        elif lookup_type == 'minute':
            sql = "CONVERT(time, SUBSTRING(CONVERT(varchar, %s, 114), 0, 6) + ':00')" % field_name
        elif lookup_type == 'second':
            sql = "CONVERT(time, SUBSTRING(CONVERT(varchar, %s, 114), 0, 9))" % field_name
        return sql
