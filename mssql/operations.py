# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

import datetime
import uuid
import warnings
import sys

from django.conf import settings
from django.db.backends.base.operations import BaseDatabaseOperations
from django.db.models.expressions import Exists, ExpressionWrapper, RawSQL
from django.db.models.sql.where import WhereNode
from django.utils import timezone
from django.utils.encoding import force_str
from django import VERSION as django_version
import pytz

DJANGO41 = django_version >= (4, 1)


class DatabaseOperations(BaseDatabaseOperations):
    compiler_module = 'mssql.compiler'

    cast_char_field_without_max_length = 'nvarchar(max)'

    def max_in_list_size(self):
        # The driver might add a few parameters
        # chose a reasonable number less than 2100 limit
        return 2048

    def _convert_field_to_tz(self, field_name, tzname):
        if tzname and settings.USE_TZ and self.connection.timezone_name != tzname:
            offset = self._get_utcoffset(tzname)
            field_name = 'DATEADD(second, %d, %s)' % (offset, field_name)
        return field_name

    def _convert_sql_to_tz(self, sql, params, tzname):
        if tzname and settings.USE_TZ and self.connection.timezone_name != tzname:
            offset = self._get_utcoffset(tzname)
            sql = 'DATEADD(second, %d, %s)' % (offset, sql)
        return sql, params

    def _get_utcoffset(self, tzname):
        """
        Returns UTC offset for given time zone in seconds
        """
        # SQL Server has no built-in support for tz database, see:
        # http://blogs.msdn.com/b/sqlprogrammability/archive/2008/03/18/using-time-zone-data-in-sql-server-2008.aspx
        zone = pytz.timezone(tzname)
        # no way to take DST into account at this point
        now = datetime.datetime.now()
        delta = zone.localize(now, is_dst=False).utcoffset()
        return delta.days * 86400 + delta.seconds - zone.dst(now).seconds

    def bulk_batch_size(self, fields, objs):
        """
        Returns the maximum allowed batch size for the backend. The fields
        are the fields going to be inserted in the batch, the objs contains
        all the objects to be inserted.
        """
        max_insert_rows = 1000
        fields_len = len(fields)
        if fields_len == 0:
            # Required for empty model
            # (bulk_create.tests.BulkCreateTests.test_empty_model)
            return max_insert_rows

        # MSSQL allows a query to have 2100 parameters but some parameters are
        # taken up defining `NVARCHAR` parameters to store the query text and
        # query parameters for the `sp_executesql` call. This should only take
        # up 2 parameters but I've had this error when sending 2098 parameters.
        max_query_params = 2050
        # inserts are capped at 1000 rows regardless of number of query params.
        # bulk_update CASE...WHEN...THEN statement sometimes takes 2 parameters per field
        return min(max_insert_rows, max_query_params // fields_len // 2)

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
        elif connector == '#':
            return '%s ^ %s' % tuple(sub_expressions)
        elif connector == '<<':
            return '%s * POWER(2, %s)' % tuple(sub_expressions)
        elif connector == '>>':
            return 'FLOOR(CONVERT(float, %s) / POWER(2, %s))' % tuple(sub_expressions)
        return super().combine_expression(connector, sub_expressions)

    def convert_datetimefield_value(self, value, expression, connection):
        if value is not None:
            if settings.USE_TZ and not timezone.is_aware(value):
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

    def convert_booleanfield_value(self, value, expression, connection):
        return bool(value) if value in (0, 1) else value


    if DJANGO41:
        def date_extract_sql(self, lookup_type, sql, params):
            if lookup_type == 'week_day':
                sql = "DATEPART(weekday, %s)" % sql
            elif lookup_type == 'week':
                sql = "DATEPART(iso_week, %s)" % sql
            elif lookup_type == 'iso_week_day':
                sql = "DATEPART(weekday, DATEADD(day, -1, %s))" % sql
            elif lookup_type == 'iso_year':
                sql = "YEAR(DATEADD(day, 26 - DATEPART(isoww, %s), %s))" % (sql, sql)
            else:
                sql = "DATEPART(%s, %s)" % (lookup_type, sql)
            return sql, params
    else:
        def date_extract_sql(self, lookup_type, field_name):
            if lookup_type == 'week_day':
                return "DATEPART(weekday, %s)" % field_name
            elif lookup_type == 'week':
                return "DATEPART(iso_week, %s)" % field_name
            elif lookup_type == 'iso_week_day':
                return "DATEPART(weekday, DATEADD(day, -1, %s))" % field_name
            elif lookup_type == 'iso_year':
                return "YEAR(DATEADD(day, 26 - DATEPART(isoww, %s), %s))" % (field_name, field_name)
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

    if DJANGO41:
        def date_trunc_sql(self, lookup_type, sql, params, tzname=None):
            sql, params = self._convert_sql_to_tz(sql, params, tzname)
            
            # Python formats year with leading zeroes. This preserves that format for 
            # compatibility with SQL Server's date since DATEPART drops the leading zeroes.
            CONVERT_YEAR = 'CONVERT(varchar(4), %s)' % sql
            CONVERT_QUARTER = 'CONVERT(varchar, 1+((DATEPART(quarter, %s)-1)*3))' % sql
            CONVERT_MONTH = 'CONVERT(varchar, DATEPART(month, %s))' % sql
            CONVERT_WEEK = "DATEADD(DAY, (DATEPART(weekday, %s) + 5) %%%% 7 * -1, %s)" % (sql, sql)

            if lookup_type == 'year':
                sql = "CONVERT(datetime2, %s + '/01/01')" % CONVERT_YEAR
            if lookup_type == 'quarter':
                sql = "CONVERT(datetime2, %s + '/' + %s + '/01')" % (CONVERT_YEAR, CONVERT_QUARTER)
            if lookup_type == 'month':
                sql = "CONVERT(datetime2, %s + '/' + %s + '/01')" % (CONVERT_YEAR, CONVERT_MONTH)
            if lookup_type == 'week':
                sql = "CONVERT(datetime2, CONVERT(varchar, %s, 112))" % CONVERT_WEEK
            if lookup_type == 'day':
                sql = "CONVERT(datetime2, CONVERT(varchar(12), %s, 112))" % sql
            return sql, params
    else:
        def date_trunc_sql(self, lookup_type, field_name, tzname=None):
            field_name = self._convert_field_to_tz(field_name, tzname)
            
            # Python formats year with leading zeroes. This preserves that format for 
            # compatibility with SQL Server's date since DATEPART drops the leading zeroes.
            CONVERT_YEAR = 'CONVERT(varchar(4), %s)' % field_name
            CONVERT_QUARTER = 'CONVERT(varchar, 1+((DATEPART(quarter, %s)-1)*3))' % field_name
            CONVERT_MONTH = 'CONVERT(varchar, DATEPART(month, %s))' % field_name
            CONVERT_WEEK = "DATEADD(DAY, (DATEPART(weekday, %s) + 5) %%%% 7 * -1, %s)" % (field_name, field_name)

            if lookup_type == 'year':
                return "CONVERT(datetime2, %s + '/01/01')" % CONVERT_YEAR
            if lookup_type == 'quarter':
                return "CONVERT(datetime2, %s + '/' + %s + '/01')" % (CONVERT_YEAR, CONVERT_QUARTER)
            if lookup_type == 'month':
                return "CONVERT(datetime2, %s + '/' + %s + '/01')" % (CONVERT_YEAR, CONVERT_MONTH)
            if lookup_type == 'week':
                return "CONVERT(datetime2, CONVERT(varchar, %s, 112))" % CONVERT_WEEK
            if lookup_type == 'day':
                return "CONVERT(datetime2, CONVERT(varchar(12), %s, 112))" % field_name

    if DJANGO41:
        def datetime_cast_date_sql(self, sql, params, tzname):
            sql, params = self._convert_sql_to_tz(sql, params, tzname)
            sql = 'CAST(%s AS date)' % sql
            return sql, params
    else:
        def datetime_cast_date_sql(self, field_name, tzname):
            field_name = self._convert_field_to_tz(field_name, tzname)
            sql = 'CAST(%s AS date)' % field_name
            return sql

    if DJANGO41:
        def datetime_cast_time_sql(self, sql, params, tzname):
            sql, params = self._convert_sql_to_tz(sql, params, tzname)
            sql = 'CAST(%s AS time)' % sql
            return sql, params
    else:
        def datetime_cast_time_sql(self, field_name, tzname):
            field_name = self._convert_field_to_tz(field_name, tzname)
            sql = 'CAST(%s AS time)' % field_name
            return sql

    if DJANGO41:
        def datetime_extract_sql(self, lookup_type, sql, params, tzname):
            sql, params = self._convert_sql_to_tz(sql, params, tzname)
            return self.date_extract_sql(lookup_type, sql, params)
    else:
        def datetime_extract_sql(self, lookup_type, field_name, tzname):
            field_name = self._convert_field_to_tz(field_name, tzname)
            return self.date_extract_sql(lookup_type, field_name)

    if DJANGO41:
        def datetime_trunc_sql(self, lookup_type, sql, params, tzname):
            sql, params = self._convert_sql_to_tz(sql, params, tzname)
            if lookup_type in ('year', 'quarter', 'month', 'week', 'day'):
                return self.date_trunc_sql(lookup_type, sql, params)
            elif lookup_type == 'hour':
                sql = "CONVERT(datetime2, SUBSTRING(CONVERT(varchar, %s, 20), 0, 14) + ':00:00')" % sql
            elif lookup_type == 'minute':
                sql = "CONVERT(datetime2, SUBSTRING(CONVERT(varchar, %s, 20), 0, 17) + ':00')" % sql
            elif lookup_type == 'second':
                sql = "CONVERT(datetime2, CONVERT(varchar, %s, 20))" % sql
            return sql, params
    else:
        def datetime_trunc_sql(self, lookup_type, field_name, tzname):
            field_name = self._convert_field_to_tz(field_name, tzname)
            sql = ''
            if lookup_type in ('year', 'quarter', 'month', 'week', 'day'):
                sql = self.date_trunc_sql(lookup_type, field_name)
            elif lookup_type == 'hour':
                sql = "CONVERT(datetime2, SUBSTRING(CONVERT(varchar, %s, 20), 0, 14) + ':00:00')" % field_name
            elif lookup_type == 'minute':
                sql = "CONVERT(datetime2, SUBSTRING(CONVERT(varchar, %s, 20), 0, 17) + ':00')" % field_name
            elif lookup_type == 'second':
                sql = "CONVERT(datetime2, CONVERT(varchar, %s, 20))" % field_name
            return sql

    def fetch_returned_insert_rows(self, cursor):
        """
        Given a cursor object that has just performed an INSERT...OUTPUT INSERTED
        statement into a table, return the list of returned data.
        """
        return cursor.fetchall()

    def return_insert_columns(self, fields):
        if not fields:
            return '', ()
        columns = [
            '%s.%s' % (
                'INSERTED',
                self.quote_name(field.column),
            ) for field in fields
        ]
        return 'OUTPUT %s' % ', '.join(columns), ()

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
            MICROSECOND = "DATEADD(microsecond, %s %%%%%%%% 1000000%%s, CAST(%%s AS datetime2))"
            fmt = 'DATEADD(second, %s / 1000000%%s, {})'.format(MICROSECOND)
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
        elif internal_type in ('BooleanField', 'NullBooleanField'):
            converters.append(self.convert_booleanfield_value)
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
            return name  # Quoting once is enough.
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
        match_option = {'iregex': 0, 'regex': 1}[lookup_type]
        return "dbo.REGEXP_LIKE(%%s, %%s, %s)=1" % (match_option,)

    def limit_offset_sql(self, low_mark, high_mark):
        """Return LIMIT/OFFSET SQL clause."""
        limit, offset = self._get_limit_offset_params(low_mark, high_mark)
        return '%s%s' % (
            (' OFFSET %d ROWS' % offset) if offset else '',
            (' FETCH FIRST %d ROWS ONLY' % limit) if limit else '',
        )

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

    def _build_sequences(self, sequences, cursor):
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
        return seqs

    def _sql_flush_new(self, style, tables, *, reset_sequences=False, allow_cascade=False):
        if reset_sequences:
            return [
                sequence
                for sequence in self.connection.introspection.sequence_list()
                if sequence['table'].lower() in [table.lower() for table in tables]
            ]

        return []

    def _sql_flush_old(self, style, tables, sequences, allow_cascade=False):
        return sequences

    def sql_flush(self, style, tables, *args, **kwargs):
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

        if not tables:
            return []

        if django_version >= (3, 1):
            sequences = self._sql_flush_new(style, tables, *args, **kwargs)
        else:
            sequences = self._sql_flush_old(style, tables, *args, **kwargs)

        from django.db import connections
        cursor = connections[self.connection.alias].cursor()

        seqs = self._build_sequences(sequences, cursor)

        COLUMNS = "TABLE_NAME, CONSTRAINT_NAME"
        WHERE = "CONSTRAINT_TYPE not in ('PRIMARY KEY','UNIQUE')"
        cursor.execute(
            "SELECT {} FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS WHERE {}".format(COLUMNS, WHERE))
        fks = cursor.fetchall()
        sql_list = ['ALTER TABLE %s NOCHECK CONSTRAINT %s;' %
                    (self.quote_name(fk[0]), self.quote_name(fk[1])) for fk in fks]
        sql_list.extend(['%s %s %s;' % (style.SQL_KEYWORD('DELETE'), style.SQL_KEYWORD('FROM'),
                                        style.SQL_FIELD(self.quote_name(table))) for table in tables])

        if self.connection.to_azure_sql_db and self.connection.sql_server_version < 2014:
            warnings.warn("Resetting identity columns is not supported "
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

        sql_list.extend(['ALTER TABLE %s CHECK CONSTRAINT %s;' %
                         (self.quote_name(fk[0]), self.quote_name(fk[1])) for fk in fks])
        return sql_list

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
            SECOND = "DATEDIFF(second, %(rhs)s, %(lhs)s)"
            MICROSECOND = "DATEPART(microsecond, %(lhs)s) - DATEPART(microsecond, %(rhs)s)"
            sql = "CAST({} AS bigint) * 1000000 + {}".format(SECOND, MICROSECOND)
            params = rhs_params + lhs_params * 2 + rhs_params
        return sql % {'lhs': lhs_sql, 'rhs': rhs_sql}, params

    def tablespace_sql(self, tablespace, inline=False):
        """
        Returns the SQL that will be appended to tables or rows to define
        a tablespace. Returns '' if the backend doesn't use tablespaces.
        """
        return "ON %s" % self.quote_name(tablespace)

    def prep_for_like_query(self, x):
        """Prepares a value for use in a LIKE query."""
        # http://msdn2.microsoft.com/en-us/library/ms179859.aspx
        return force_str(x).replace('\\', '\\\\').replace('[', '[[]').replace('%', '[%]').replace('_', '[_]')

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

        # Expression values are adapted by the database.
        if hasattr(value, 'resolve_expression'):
            return value

        if timezone.is_aware(value):
            if settings.USE_TZ:
                # When support for time zones is enabled, Django stores datetime information
                # in UTC in the database and uses time-zone-aware objects internally
                # source: https://docs.djangoproject.com/en/dev/topics/i18n/timezones/#overview
                value = value.astimezone(datetime.timezone.utc)
            else:
                # When USE_TZ is False, settings.TIME_ZONE is the time zone in
                # which Django will store all datetimes
                # source: https://docs.djangoproject.com/en/dev/ref/settings/#std:setting-TIME_ZONE
                value = timezone.make_naive(value, self.connection.timezone)
        return value

    if DJANGO41:
        def time_trunc_sql(self, lookup_type, sql, params, tzname=None):
            # if self.connection.sql_server_version >= 2012:
            #    fields = {
            #        'hour': 'DATEPART(hour, %s)' % field_name,
            #        'minute': 'DATEPART(minute, %s)' % field_name if lookup_type != 'hour' else '0',
            #        'second': 'DATEPART(second, %s)' % field_name if lookup_type == 'second' else '0',
            #    }
            #    sql = 'TIMEFROMPARTS(%(hour)s, %(minute)s, %(second)s, 0, 0)' % fields
            if lookup_type == 'hour':
                sql = "CONVERT(time, SUBSTRING(CONVERT(varchar, %s, 114), 0, 3) + ':00:00')" % sql
            elif lookup_type == 'minute':
                sql = "CONVERT(time, SUBSTRING(CONVERT(varchar, %s, 114), 0, 6) + ':00')" % sql
            elif lookup_type == 'second':
                sql = "CONVERT(time, SUBSTRING(CONVERT(varchar, %s, 114), 0, 9))" % sql
            return sql, params
    else:
        def time_trunc_sql(self, lookup_type, field_name, tzname=''):
            # if self.connection.sql_server_version >= 2012:
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

    def conditional_expression_supported_in_where_clause(self, expression):
        """
        Following "Moved conditional expression wrapping to the Exact lookup" in django 3.1
        https://github.com/django/django/commit/37e6c5b79bd0529a3c85b8c478e4002fd33a2a1d
        """
        if isinstance(expression, (Exists, WhereNode)):
            return True
        if isinstance(expression, ExpressionWrapper) and expression.conditional:
            return self.conditional_expression_supported_in_where_clause(expression.expression)
        if isinstance(expression, RawSQL) and expression.conditional:
            return True
        return False
