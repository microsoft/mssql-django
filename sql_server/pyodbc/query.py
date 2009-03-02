"""
Custom Query class for MS SQL Server.
Derives from: django.db.models.sql.query.Query
"""

from datetime import datetime

REV_ODIR = {
    'ASC': 'DESC',
    'DESC': 'ASC'
}

SQL_SERVER_8_LIMIT_QUERY = \
"""SELECT *
FROM (
  SELECT TOP %(limit)s *
  FROM (
    %(orig_sql)s
    ORDER BY %(ord)s
  ) AS %(table)s
  ORDER BY %(rev_ord)s
) AS %(table)s
ORDER BY %(ord)s"""

SQL_SERVER_8_NO_LIMIT_QUERY = \
"""SELECT *
FROM %(table)s
WHERE %(key)s NOT IN (
  %(orig_sql)s
  ORDER BY %(ord)s
)"""

# Strategies for handling limit+offset emulation:
USE_ROW_NUMBER = 0 # For SQL Server >= 2005
USE_TOP_HMARK = 1 # For SQL Server 2000 when both limit and offset are provided
USE_TOP_LMARK = 2 # For SQL Server 2000 when offset but no limit is provided

# Cache. Maps default query class to new MS SQL query class.
_classes = {}

# Gets the base class for all Django queries.
# Django's subquery items (InsertQuery, DeleteQuery, etc.) will then inherit
# from this custom class.
def query_class(QueryClass):
    """
    Returns a custom django.db.models.sql.query.Query subclass that is
    appropriate for MS SQL Server.
    """
    global _classes
    try:
        return _classes[QueryClass]
    except KeyError:
        pass

    class PyOdbcSSQuery(QueryClass):
        from sql_server.pyodbc import aggregates
        aggregates_module = aggregates

        def __init__(self, *args, **kwargs):
            super(PyOdbcSSQuery, self).__init__(*args, **kwargs)
            self.default_reverse_ordering = False
            self._ord = []

            # If we are an insert query, monkeypatch the "as_sql" method
            from django.db.models.sql.subqueries import InsertQuery
            if isinstance(self, InsertQuery):
                self._orig_as_sql = self.as_sql
                self.as_sql = self._insert_as_sql

        def _insert_as_sql(self, *args, **kwargs):
            """Helper method for monkeypatching Django InsertQuery's as_sql."""
            meta = self.get_meta()
            quoted_table = self.connection.ops.quote_name(meta.db_table)
            # Get (sql, params) from original InsertQuery.as_sql
            sql, params = self._orig_as_sql(*args, **kwargs)
            if meta.pk.attname in self.columns and meta.pk.__class__.__name__ == "AutoField":
                if len(self.columns) == 1 and not params:
                    sql = "INSERT INTO %s DEFAULT VALUES" % quoted_table
                else:
                    sql = "SET IDENTITY_INSERT %s ON;\n%s;\nSET IDENTITY_INSERT %s OFF" % \
                        (quoted_table, sql, quoted_table)

            return sql, params

        def __reduce__(self):
            """
            Enable pickling for this class (normal pickling handling doesn't
            work as Python can only pickle module-level classes by default).
            """
            if hasattr(QueryClass, '__getstate__'):
                assert hasattr(QueryClass, '__setstate__')
                data = self.__getstate__()
            else:
                data = self.__dict__
            return (unpickle_query_class, (QueryClass,), data)

        def convert_values(self, value, field):
            """
            Coerce the value returned by the database backend into a consistent
            type that is compatible with the field type.

            In our case, cater for the fact that SQL Server < 2008 has no
            separate Date and Time data types.
            TODO: See how we'll handle this for SQL Server >= 2008
            """
            if value is None:
                return None
            if field and field.get_internal_type() == 'DateTimeField':
                return value
            elif field and field.get_internal_type() == 'DateField':
                value = value.date() # extract date
            elif field and field.get_internal_type() == 'TimeField':
                value = value.time() # extract time
            # Some cases (for example when select_related() is used) aren't
            # caught by the DateField case above and date fields arrive from
            # the DB as datetime instances.
            # Implement a workaround stealing the idea from the Oracle
            # backend. It's not perfect so the same warning applies (i.e. if a
            # query results in valid date+time values with the time part set
            # to midnight, this workaround can surprise us by converting them
            # to the datetime.date Python type).
            elif isinstance(value, datetime) and value.hour == value.minute == value.second == value.microsecond == 0:
                value = value.date()
            # Force floats to the correct type
            elif value is not None and field and field.get_internal_type() == 'FloatField':
                value = float(value)
            return value

        def resolve_columns(self, row, fields=()):
            values = []
            for value, field in map(None, row, fields):
                values.append(self.convert_values(value, field))
            return values

        def modify_query(self, strategy, ordering, out_cols):
            """
            Helper method, called from _as_sql()

            Sets the value of the self._ord and self.default_reverse_ordering
            attributes.
            Can modify the values of the out_cols list argument and the
            self.ordering_aliases attribute.
            """
            self.default_reverse_ordering = False
            self._ord = []
            cnt = 0
            extra_select_aliases = [k.strip('[]') for k in self.extra_select.keys()]
            for ord_spec_item in ordering:
                if ord_spec_item.endswith(' ASC') or ord_spec_item.endswith(' DESC'):
                    parts = ord_spec_item.split()
                    col, odir = ' '.join(parts[:-1]), parts[-1]
                    if col not in self.ordering_aliases and col.strip('[]') not in extra_select_aliases:
                        if col.isdigit():
                            cnt += 1
                            n = int(col)-1
                            alias = 'OrdAlias%d' % cnt
                            out_cols[n] = '%s AS [%s]' % (out_cols[n], alias)
                            self._ord.append((alias, odir))
                        elif col in out_cols:
                            if strategy == USE_TOP_HMARK:
                                cnt += 1
                                n = out_cols.index(col)
                                alias = 'OrdAlias%d' % cnt
                                out_cols[n] = '%s AS %s' % (col, alias)
                                self._ord.append((alias, odir))
                            else:
                                self._ord.append((col, odir))
                        elif strategy == USE_TOP_HMARK:
                            # Special case: '_order' column created by Django
                            # when Meta.order_with_respect_to is used
                            if col.split('.')[-1] == '[_order]' and odir == 'DESC':
                                self.default_reverse_ordering = True
                            cnt += 1
                            alias = 'OrdAlias%d' % cnt
                            self._ord.append((alias, odir))
                            self.ordering_aliases.append('%s AS [%s]' % (col, alias))
                        else:
                            self._ord.append((col, odir))
                    else:
                        self._ord.append((col, odir))

            if strategy == USE_TOP_HMARK and not self._ord:
                # XXX:
                #meta = self.get_meta()
                meta = self.model._meta
                qn = self.quote_name_unless_alias
                pk_col = '%s.%s' % (qn(meta.db_table), qn(meta.pk.db_column or meta.pk.column))
                if pk_col not in out_cols:
                    out_cols.append(pk_col)

        def _as_sql(self, strategy):
            """
            Helper method, called from as_sql()
            Similar to django/db/models/sql/query.py:Query.as_sql() but without
            the ordering and limits code.

            Returns SQL that hasn't an order-by clause.
            """
            # get_columns needs to be called before get_ordering to populate
            # _select_alias.
            out_cols = self.get_columns(True)
            ordering, ordering_group_by = self.get_ordering()
            if strategy == USE_ROW_NUMBER:
                if not ordering:
                    meta = self.get_meta()
                    qn = self.quote_name_unless_alias
                    ordering = ['%s.%s ASC' % (qn(meta.db_table), qn(meta.pk.db_column or meta.pk.column))]

            if strategy in (USE_TOP_HMARK, USE_ROW_NUMBER):
                self.modify_query(strategy, ordering, out_cols)

            if strategy == USE_ROW_NUMBER:
                ord = ', '.join(['%s %s' % pair for pair in self._ord])
                self.ordering_aliases.append('(ROW_NUMBER() OVER (ORDER BY %s)) AS [rn]' % ord)

            # This must come after 'select' and 'ordering' -- see docstring of
            # get_from_clause() for details.
            from_, f_params = self.get_from_clause()

            qn = self.quote_name_unless_alias
            where, w_params = self.where.as_sql(qn=qn)
            having, h_params = self.having.as_sql(qn=qn)
            params = []
            for val in self.extra_select.itervalues():
                params.extend(val[1])

            result = ['SELECT']
            if self.distinct:
                result.append('DISTINCT')

            if strategy == USE_TOP_LMARK:
                # XXX:
                #meta = self.get_meta()
                meta = self.model._meta
                result.append('TOP %s %s' % (self.low_mark, self.quote_name_unless_alias(meta.pk.db_column or meta.pk.column)))
            else:
                if strategy == USE_TOP_HMARK and self.high_mark is not None:
                    result.append('TOP %s' % self.high_mark)
                result.append(', '.join(out_cols + self.ordering_aliases))

            result.append('FROM')
            result.extend(from_)
            params.extend(f_params)

            if where:
                result.append('WHERE %s' % where)
                params.extend(w_params)
            if self.extra_where:
                if not where:
                    result.append('WHERE')
                else:
                    result.append('AND')
                result.append(' AND '.join(self.extra_where))

            grouping, gb_params = self.get_grouping()
            if grouping:
                if ordering:
                    # If the backend can't group by PK (i.e., any database
                    # other than MySQL), then any fields mentioned in the
                    # ordering clause needs to be in the group by clause.
                    if not self.connection.features.allows_group_by_pk:
                        for col, col_params in ordering_group_by:
                            if col not in grouping:
                                grouping.append(str(col))
                                gb_params.extend(col_params)
                else:
                    ordering = self.connection.ops.force_no_ordering()
                result.append('GROUP BY %s' % ', '.join(grouping))
                params.extend(gb_params)

            if having:
                result.append('HAVING %s' % having)
                params.extend(h_params)

            params.extend(self.extra_params)
            return ' '.join(result), tuple(params)

        def as_sql(self, with_limits=True, with_col_aliases=False):
            """
            Creates the SQL for this query. Returns the SQL string and list of
            parameters.

            If 'with_limits' is False, any limit/offset information is not included
            in the query.
            """
            # The do_offset flag indicates whether we need to construct
            # the SQL needed to use limit/offset w/SQL Server.
            do_offset = with_limits and (self.high_mark is not None or self.low_mark != 0)

            # If no offsets, just return the result of the base class
            # `as_sql`.
            if not do_offset:
                return super(PyOdbcSSQuery, self).as_sql(with_limits=False,
                                                          with_col_aliases=with_col_aliases)
            # Shortcut for the corner case when high_mark value is 0:
            if self.high_mark == 0:
                return "", ()

            self.pre_sql_setup()
            # XXX:
            #meta = self.get_meta()
            meta = self.model._meta
            qn = self.quote_name_unless_alias
            fallback_ordering = '%s.%s' % (qn(meta.db_table), qn(meta.pk.db_column or meta.pk.column))

            # SQL Server 2000, offset+limit case
            if self.connection.ops.sql_server_ver < 2005 and self.high_mark is not None:
                orig_sql, params = self._as_sql(USE_TOP_HMARK)
                if self._ord:
                    ord = ', '.join(['%s %s' % pair for pair in self._ord])
                    rev_ord = ', '.join(['%s %s' % (col, REV_ODIR[odir]) for col, odir in self._ord])
                else:
                    if not self.default_reverse_ordering:
                        ord = '%s ASC' % fallback_ordering
                        rev_ord = '%s DESC' % fallback_ordering
                    else:
                        ord = '%s DESC' % fallback_ordering
                        rev_ord = '%s ASC' % fallback_ordering
                sql = SQL_SERVER_8_LIMIT_QUERY % {
                    'limit': self.high_mark - self.low_mark,
                    'orig_sql': orig_sql,
                    'ord': ord,
                    'rev_ord': rev_ord,
                    # XXX:
                    'table': qn(meta.db_table),
                }
                return sql, params

            # SQL Server 2005
            if self.connection.ops.sql_server_ver >= 2005:
                sql, params = self._as_sql(USE_ROW_NUMBER)

                # Construct the final SQL clause, using the initial select SQL
                # obtained above.
                result = ['SELECT * FROM (%s) AS X' % sql]

                # Place WHERE condition on `rn` for the desired range.
                if self.high_mark is None:
                    self.high_mark = 9223372036854775807
                result.append('WHERE X.rn BETWEEN %d AND %d' % (self.low_mark+1, self.high_mark))

                return ' '.join(result), params

            # SQL Server 2000, offset without limit case
            # get_columns needs to be called before get_ordering to populate
            # select_alias.
            self.get_columns(with_col_aliases)
            ordering, ordering_group_by = self.get_ordering()
            if ordering:
                ord = ', '.join(ordering)
            else:
                # We need to define an ordering clause since none was provided
                ord = fallback_ordering
            orig_sql, params = self._as_sql(USE_TOP_LMARK)
            sql = SQL_SERVER_8_NO_LIMIT_QUERY % {
                'orig_sql': orig_sql,
                'ord': ord,
                'table': qn(meta.db_table),
                'key': qn(meta.pk.db_column or meta.pk.column),
            }
            return sql, params


    _classes[QueryClass] = PyOdbcSSQuery
    return PyOdbcSSQuery

def unpickle_query_class(QueryClass):
    """
    Utility function, called by Python's unpickling machinery, that handles
    unpickling of our custom Query subclasses.
    """
    klass = query_class(QueryClass)
    return klass.__new__(klass)
unpickle_query_class.__safe_for_unpickling__ = True
