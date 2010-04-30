from django.db.models.sql import compiler
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


class SQLCompiler(compiler.SQLCompiler):
    
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
        elif field and field.get_internal_type() == 'TimeField' or (isinstance(value, datetime) and value.year == 1900 and value.month == value.day == 1):
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
        index_start = len(self.query.extra_select.keys())
        values = [self.convert_values(v, None) for v in row[:index_start]]
        for value, field in map(None, row[index_start:], fields):
            values.append(self.convert_values(value, field))
        return tuple(values)

    def modify_query(self, strategy, ordering, out_cols):
        """
        Helper method, called from _as_sql()

        Sets the value of the self._ord and self.default_reverse_ordering
        attributes.
        Can modify the values of the out_cols list argument and the
        self.query.ordering_aliases attribute.
        """
        self.default_reverse_ordering = False
        self._ord = []
        cnt = 0
        extra_select_aliases = [k.strip('[]') for k in self.query.extra_select.keys()]
        for ord_spec_item in ordering:
            if ord_spec_item.endswith(' ASC') or ord_spec_item.endswith(' DESC'):
                parts = ord_spec_item.split()
                col, odir = ' '.join(parts[:-1]), parts[-1]
                if col not in self.query.ordering_aliases and col.strip('[]') not in extra_select_aliases:
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
                        self.query.ordering_aliases.append('%s AS [%s]' % (col, alias))
                    else:
                        self._ord.append((col, odir))
                else:
                    self._ord.append((col, odir))

        if strategy == USE_ROW_NUMBER and not self._ord and 'RAND()' in ordering:
            self._ord.append(('RAND()',''))
        if strategy == USE_TOP_HMARK and not self._ord:
            # XXX:
            #meta = self.get_meta()
            meta = self.query.model._meta
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
                meta = self.query.get_meta()
                qn = self.quote_name_unless_alias
                # Special case: pk not in out_cols, use random ordering. 
                #
                if '%s.%s' % (qn(meta.db_table), qn(meta.pk.db_column or meta.pk.column)) not in self.get_columns():
                    ordering = ['RAND()']
                    # XXX: Maybe use group_by field for ordering?
                    #if self.group_by:
                        #ordering = ['%s.%s ASC' % (qn(self.group_by[0][0]),qn(self.group_by[0][1]))]
                else:
                    ordering = ['%s.%s ASC' % (qn(meta.db_table), qn(meta.pk.db_column or meta.pk.column))]

        if strategy in (USE_TOP_HMARK, USE_ROW_NUMBER):
            self.modify_query(strategy, ordering, out_cols)

        if strategy == USE_ROW_NUMBER:
            ord = ', '.join(['%s %s' % pair for pair in self._ord])
            self.query.ordering_aliases.append('(ROW_NUMBER() OVER (ORDER BY %s)) AS [rn]' % ord)

        # This must come after 'select' and 'ordering' -- see docstring of
        # get_from_clause() for details.
        from_, f_params = self.get_from_clause()

        qn = self.quote_name_unless_alias
        where, w_params = self.query.where.as_sql(qn, self.connection)
        having, h_params = self.query.having.as_sql(qn, self.connection)
        params = []
        for val in self.query.extra_select.itervalues():
            params.extend(val[1])

        result = ['SELECT']
        if self.query.distinct:
            result.append('DISTINCT')

        if strategy == USE_TOP_LMARK:
            # XXX:
            #meta = self.get_meta()
            meta = self.query.model._meta
            result.append('TOP %s %s' % (self.query.low_mark, self.quote_name_unless_alias(meta.pk.db_column or meta.pk.column)))
        else:
            if strategy == USE_TOP_HMARK and self.query.high_mark is not None:
                result.append('TOP %s' % self.query.high_mark)
            result.append(', '.join(out_cols + self.query.ordering_aliases))

        result.append('FROM')
        result.extend(from_)
        params.extend(f_params)

        if where:
            result.append('WHERE %s' % where)
            params.extend(w_params)

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
        do_offset = with_limits and (self.query.high_mark is not None or self.query.low_mark != 0)

        # If no offsets, just return the result of the base class
        # `as_sql`.
        if not do_offset:
            return super(SQLCompiler, self).as_sql(with_limits=False,
                                                      with_col_aliases=with_col_aliases)
        # Shortcut for the corner case when high_mark value is 0:
        if self.query.high_mark == 0:
            return "", ()

        self.pre_sql_setup()
        # XXX:
        #meta = self.get_meta()
        meta = self.query.model._meta
        qn = self.quote_name_unless_alias
        fallback_ordering = '%s.%s' % (qn(meta.db_table), qn(meta.pk.db_column or meta.pk.column))

        # SQL Server 2000, offset+limit case
        if self.connection.ops._get_sql_server_ver(self.connection) < 2005 and self.query.high_mark is not None:
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
                'limit': self.query.high_mark - self.query.low_mark,
                'orig_sql': orig_sql,
                'ord': ord,
                'rev_ord': rev_ord,
                # XXX:
                'table': qn(meta.db_table),
            }
            return sql, params

        # SQL Server 2005
        if self.connection.ops._get_sql_server_ver(self.connection) >= 2005:
            sql, params = self._as_sql(USE_ROW_NUMBER)
            
            # Construct the final SQL clause, using the initial select SQL
            # obtained above.
            result = ['SELECT * FROM (%s) AS X' % sql]

            # Place WHERE condition on `rn` for the desired range.
            if self.query.high_mark is None:
                self.query.high_mark = 9223372036854775807
            result.append('WHERE X.rn BETWEEN %d AND %d' % (self.query.low_mark+1, self.query.high_mark))

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


class SQLInsertCompiler(compiler.SQLInsertCompiler, SQLCompiler):
    def as_sql(self):
        sql, params = super(SQLInsertCompiler, self).as_sql()
        meta = self.query.get_meta()
        quoted_table = self.connection.ops.quote_name(meta.db_table)
        if meta.pk.attname in self.query.columns and meta.pk.__class__.__name__ == "AutoField":
            if len(self.query.columns) == 1 and not params:
                sql = "INSERT INTO %s DEFAULT VALUES" % quoted_table
            else:
                sql = "SET IDENTITY_INSERT %s ON;\n%s;\nSET IDENTITY_INSERT %s OFF" % \
                    (quoted_table, sql, quoted_table)

        return sql, params


class SQLDeleteCompiler(compiler.SQLDeleteCompiler, SQLCompiler):
    pass

class SQLUpdateCompiler(compiler.SQLUpdateCompiler, SQLCompiler):
    pass

class SQLAggregateCompiler(compiler.SQLAggregateCompiler, SQLCompiler):
    pass

class SQLDateCompiler(compiler.SQLDateCompiler, SQLCompiler):
    pass
