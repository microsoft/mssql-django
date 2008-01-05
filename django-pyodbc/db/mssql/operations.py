from django.db.backends import BaseDatabaseOperations, util
from django.utils.datastructures import SortedDict

# Version specific queries

# LIMIT and OFFSET are turned into inlcusive range
# start_row = offset + 1
# end_row = offset + limit
SQL_SERVER_9_LIMIT_QUERY = \
"""
SELECT *
FROM (
    SELECT %(distinc)s TOP %(end_row)s
        %(fields)s, ROW_NUMBER()
        OVER(
            ORDER BY  %(orderby)s
        ) AS row
    %(sql)s ORDER BY %(orderby)s
    ) AS x
    WHERE x.row BETWEEN %(start_row)s AND %(end_row)s
"""

# end_row = offset + limit -- upper range
# limit -- chunk size
SQL_SERVER_8_LIMIT_QUERY = \
"""
SELECT * FROM (
  SELECT TOP %(limit)s * FROM (
    SELECT TOP %(end_row)s %(distinc)s%(fields)s
        %(sql)s    
    ORDER BY %(orderby)s
  ) AS %(table)s
  ORDER BY %(orderby_reversed)s) AS %(table)s
ORDER BY %(orderby)s
"""

ORDER_ASC = "ASC"
ORDER_DESC = "DESC"

SQL_SERVER_2005_VERSION = 9
SQL_SERVER_VERSION = None

def sql_server_version():
    """
    Returns the major version of the SQL Server:
      2000 -> 8
      2005 -> 9
    """
    global SQL_SERVER_VERSION
    if SQL_SERVER_VERSION is not None:
        return SQL_SERVER_VERSION
    else:
        from django.db import connection
        cur = connection.cursor()
        cur.execute("SELECT cast(SERVERPROPERTY('ProductVersion') as varchar)")
        SQL_SERVER_VERSION = int(cur.fetchone()[0].split('.')[0])
        return SQL_SERVER_VERSION

class DatabaseOperations(BaseDatabaseOperations):
    def last_insert_id(self, cursor, table_name, pk_name):
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
        pk_name = self.quote_name(pk_name)
        #cursor.execute("SELECT %s FROM %s WHERE %s = IDENT_CURRENT(%%s)" % (pk_name, table_name, pk_name), [table_name]) 
        cursor.execute("SELECT CAST(IDENT_CURRENT(%s) as int)", [table_name]) 
        return cursor.fetchone()[0]

    def query_set_class(self, DefaultQuerySet):
        "Create a custom QuerySet class for SQL Server."
        from django.db import connection
        from django.db.models.query import EmptyResultSet, GET_ITERATOR_CHUNK_SIZE, quote_only_if_word

        class SqlServerQuerySet(DefaultQuerySet):

            def iterator(self):
                "Performs the SELECT database lookup of this QuerySet."

                from django.db.models.query import get_cached_row

                # self._select is a dictionary, and dictionaries' key order is
                # undefined, so we convert it to a list of tuples.
                extra_select = self._select.items()

                full_query = None

                try:
                    try:
                        select, sql, params, full_query = self._get_sql_clause(get_full_query=True)
                    except TypeError:
                        select, sql, params = self._get_sql_clause()
                except EmptyResultSet:
                    raise StopIteration
                if not full_query:
                    full_query = "SELECT %s%s\n%s" % ((self._distinct and "DISTINCT " or ""), ', '.join(select), sql)

                cursor = connection.cursor()
                cursor.execute(full_query, params)

                fill_cache = self._select_related
                fields = self.model._meta.fields
                index_end = len(fields)

                while 1:
                    rows = cursor.fetchmany(GET_ITERATOR_CHUNK_SIZE)
                    if not rows:
                        raise StopIteration
                    for row in rows:
                        row = self.resolve_columns(row, fields)
                        if fill_cache:
                            obj, index_end = get_cached_row(klass=self.model, row=row,
                                                            index_start=0, max_depth=self._max_related_depth)
                        else:
                            obj = self.model(*row[:index_end])
                        for i, k in enumerate(extra_select):
                            setattr(obj, k[0], row[index_end+i])
                        yield obj

            def _get_sql_clause(self, get_full_query=False):
                from django.db.models.query import fill_table_cache, \
                    handle_legacy_orderlist, orderfield2column

                opts = self.model._meta
                qn = connection.ops.quote_name

                # Construct the fundamental parts of the query: SELECT X FROM Y WHERE Z.
                select = ["%s.%s" % (qn(opts.db_table), qn(f.column)) for f in opts.fields]
                # TODO: quote_only_if_word?
                tables = [quote_only_if_word(t) for t in self._tables]
                joins = SortedDict()
                where = self._where[:]
                params = self._params[:]

                # Convert self._filters into SQL.
                joins2, where2, params2 = self._filters.get_sql(opts)
                joins.update(joins2)
                where.extend(where2)
                params.extend(params2)

                # Add additional tables and WHERE clauses based on select_related.
                if self._select_related:
                    fill_table_cache(opts, select, tables, where, opts.db_table, [opts.db_table])

                # Add any additional SELECTs.
                # TODO: quote_only_if_word?
                if self._select:
                    select.extend(['(%s) AS %s' % (quote_only_if_word(s[1]), qn(s[0])) for s in self._select.items()])

                # Start composing the body of the SQL statement.
                sql = [" FROM", qn(opts.db_table)]

                # Compose the join dictionary into SQL describing the joins.
                if joins:
                    sql.append(" ".join(["%s %s %s ON %s" % (join_type, table, alias, condition)
                                    for (alias, (table, join_type, condition)) in joins.items()]))

                # Compose the tables clause into SQL.
                if tables:
                    sql.append(", " + ", ".join(tables))

                # Compose the where clause into SQL.
                if where:
                    sql.append(where and "WHERE " + " AND ".join(where))

                # Copy version suitable for LIMIT
                sql2 = sql[:]

                # ORDER BY clause
                order_by = []
                if self._order_by is not None:
                    ordering_to_use = self._order_by
                else:
                    ordering_to_use = opts.ordering
                for f in handle_legacy_orderlist(ordering_to_use):
                    if f == '?': # Special case.
                        order_by.append(connection.ops.get_random_function_sql())
                    else:
                        if f.startswith('-'):
                            col_name = f[1:]
                            order = ORDER_DESC
                        else:
                            col_name = f
                            order = ORDER_ASC
                        if "." in col_name:
                            table_prefix, col_name = col_name.split('.', 1)
                            table_prefix = qn(table_prefix) + '.'
                        else:
                            # Use the database table as a column prefix if it wasn't given,
                            # and if the requested column isn't a custom SELECT.
                            if "." not in col_name and col_name not in (self._select or ()):
                                table_prefix = qn(opts.db_table) + '.'
                            else:
                                table_prefix = ''
                        order_by.append('%s%s %s' % (table_prefix, qn(orderfield2column(col_name, opts)), order))
                if order_by:
                    sql.append("ORDER BY " + ", ".join(order_by))

                # Look for column name collisions in the select elements
                # and fix them with an AS alias.  This allows us to do a
                # SELECT * later in the paging query.
                cols = [clause.split('.')[-1] for clause in select]
                for index, col in enumerate(cols):
                    if cols.count(col) > 1:
                        col = '%s%d' % (col.replace('[', '').replace(']',''), index)
                        cols[index] = qn(col)
                        select[index] = '%s AS %s' % (select[index], qn(col))

                # LIMIT and OFFSET clauses
                # To support limits and offsets, SQL Server requires some funky rewriting of an otherwise normal looking query.
                select_clause = ",".join(select)
                distinct = (self._distinct and "DISTINCT " or "")
                full_query = None

                # offset: start row (zero indexed)
                # limit: chunk size

                if self._limit is None:
                    assert self._offset is None, "'offset' is not allowed without 'limit'" # TODO: actually, why not?

                if self._limit is not None:
                    limit = int(self._limit)
                else:
                    limit = None

                if self._offset is not None and limit > 0:
                    offset = int(self._offset)
                else:
                    offset = 0

                limit_and_offset_clause = ''

                if limit is not None:
                    limit_and_offset_clause = True
                elif offset:
                    limit_and_offset_clause = True

                if limit_and_offset_clause:
                    # TOP and ROW_NUMBER in T-SQL requires an order.
                    # If order is not specified the use id column.
                    if len(order_by)==0:
                        order_by.append('%s.%s %s' % (qn(opts.db_table), qn(opts.fields[0].db_column or opts.fields[0].column), ORDER_ASC))

                    order_by_clause = ", ".join(order_by)
                    order_by_clause_reverse = ""

                    if sql_server_version() >= SQL_SERVER_2005_VERSION:
                        fmt = SQL_SERVER_9_LIMIT_QUERY
                    else:
                        # Compatibility mode for older versions
                        order_by_clause_reverse = ", ".join(self.change_order_direction(order_by))
                        fmt = SQL_SERVER_8_LIMIT_QUERY

                    full_query = fmt % {'distinc': distinct, 'fields': select_clause,
                                        'sql': " ".join(sql2), 'orderby': order_by_clause,
                                        'orderby_reversed': order_by_clause_reverse,
                                        'table': qn(opts.db_table),
                                        'limit': limit,
                                        'start_row': offset + 1, 'end_row': offset + limit}
                if get_full_query:
                    return select, " ".join(sql), params, full_query
                else:
                    return select, " ".join(sql), params

            def change_order_direction(self, order_by):
                new_order = []
                for order in order_by:
                    if order.endswith(ORDER_ASC):
                        new_order.append(order[:-len(ORDER_ASC)] + ORDER_DESC)
                    elif order.endswith(ORDER_DESC):
                        new_order.append(order[:-len(ORDER_DESC)] + ORDER_ASC)
                    else:
                        # TODO: check special case '?' -- random order
                        new_order.append(order)
                return new_order

            def resolve_columns(self, row, fields=()):
                from django.db.models.fields import DateField, DateTimeField, \
                    TimeField, DecimalField
                values = []
                for value, field in map(None, row, fields):
                    if value is not None:
                        if isinstance(field, DateTimeField):
                            pass # do nothing
                        elif isinstance(field, DateField):
                            value = value.date() # extract date
                        elif isinstance(field, TimeField):
                            value = value.time() # extract time
                    values.append(value)
                return values

        return SqlServerQuerySet

    def date_extract_sql(self, lookup_type, field_name):
        """
        Given a lookup_type of 'year', 'month' or 'day', returns the SQL that
        extracts a value from the given date field field_name.
        """
        return "DATEPART(%s, %s)" % (lookup_type, field_name)

    def date_trunc_sql(self, lookup_type, field_name):
        """
        Given a lookup_type of 'year', 'month' or 'day', returns the SQL that
        truncates the given date field field_name to a DATE object with only
        the given specificity.
        """
        if lookup_type=='year':
            return "Convert(datetime, Convert(varchar, DATEPART(year, %s)) + '/01/01')" % field_name
        if lookup_type=='month':
            return "Convert(datetime, Convert(varchar, DATEPART(year, %s)) + '/' + Convert(varchar, DATEPART(month, %s)) + '/01')" % (field_name, field_name)
        if lookup_type=='day':
            return "Convert(datetime, Convert(varchar(12), %s))" % field_name

    def limit_offset_sql(self, limit, offset=None):
        # Limits and offset are too complicated to be handled here.
        # Look for a implementation similar to SQL Server backend
        return ""

    def quote_name(self, name):
        """
        Returns a quoted version of the given table, index or column name. Does
        not quote the given name if it's already been quoted.
        """
        if name.startswith('[') and name.endswith(']'):
            return name # Quoting once is enough.
        return '[%s]' % name

    def get_random_function_sql(self):
        """
        Returns a SQL expression that returns a random value.
        """
        return "RAND()"

    def tablespace_sql(self, tablespace, inline=False):
        """
        Returns the tablespace SQL, or None if the backend doesn't use
        tablespaces.
        """
        return "ON %s" % self.quote_name(tablespace)

    def sql_flush(self, style, tables, sequences):
        """
        Returns a list of SQL statements required to remove all data from
        the given database tables (without actually removing the tables
        themselves).

        The `style` argument is a Style object as returned by either
        color_style() or no_style() in django.core.management.color.
        """
        # Cannot use TRUNCATE on tables that are referenced by a FOREIGN KEY
        # So must use the much slower DELETE
        from django.db import connection
        cursor = connection.cursor()
        cursor.execute("SELECT TABLE_NAME, CONSTRAINT_NAME FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS")
        fks = cursor.fetchall()
        sql_list = ['ALTER TABLE %s NOCHECK CONSTRAINT %s;' % \
                (self.quote_name(fk[0]), self.quote_name(fk[1])) for fk in fks]
        sql_list.extend(['%s %s %s;' % (style.SQL_KEYWORD('DELETE'), style.SQL_KEYWORD('FROM'),
                         style.SQL_FIELD(self.quote_name(table)) ) for table in tables])
        # The reset the counters on each table.
        sql_list.extend(['%s %s (%s, %s, %s) %s %s;' % (
            style.SQL_KEYWORD('DBCC'),
            style.SQL_KEYWORD('CHECKIDENT'),
            style.SQL_FIELD(self.quote_name(seq["table"])),
            style.SQL_KEYWORD('RESEED'),
            style.SQL_FIELD('1'),
            style.SQL_KEYWORD('WITH'),
            style.SQL_KEYWORD('NO_INFOMSGS'),
            ) for seq in sequences])
        sql_list.extend(['ALTER TABLE %s CHECK CONSTRAINT %s;' % \
                (self.quote_name(fk[0]), self.quote_name(fk[1])) for fk in fks])
        return sql_list 

    def start_transaction_sql(self):
        """
        Returns the SQL statement required to start a transaction.
        """
        return "BEGIN TRANSACTION"
