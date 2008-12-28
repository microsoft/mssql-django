"""
Custom Query class for SQL Server.
Derives from: django.db.models.sql.query.Query
"""
import string

# Cache. Maps default query class to new SqlServer query class.
_classes = {}

def query_class(QueryClass):
    """
    Returns a custom django.db.models.sql.query.Query subclass that is
    appropriate for SQL Server.

    """
    global _classes
    try:
        return _classes[QueryClass]
    except KeyError:
        pass

    class SqlServerQuery(QueryClass):
        def __init__(self, *args, **kwargs):
            super(SqlServerQuery, self).__init__(*args, **kwargs)

            # If we are an insert query, monkeypatch the "as_sql" method
            from django.db.models.sql.subqueries import InsertQuery
            if isinstance(self, InsertQuery):
                self._orig_as_sql = self.as_sql
                self.as_sql = self._insert_as_sql

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

        def resolve_columns(self, row, fields=()):
            """
            Cater for the fact that SQL Server has no separate Date and Time
            data types.
            """
            from django.db.models.fields import DateField, DateTimeField, \
                TimeField, BooleanField, NullBooleanField
            values = []
            for value, field in map(None, row, fields):
                if value is not None:
                    if isinstance(field, DateTimeField):
                        # DateTimeField subclasses DateField so must be checked
                        # first.
                        pass # do nothing
                    elif isinstance(field, DateField):
                        value = value.date() # extract date
                    elif isinstance(field, TimeField):
                        value = value.time() # extract time
                    elif isinstance(field, (BooleanField, NullBooleanField)):
                        if value in (1,'t','True','1',True):
                            value = True
                        else:
                            value = False
                values.append(value)
            return values

        def as_sql_internal(self, with_col_aliases=False, with_row_number=False, with_top_n=False, rn_orderby=''):
            """
            SQL SERVER row_number() already has ordering, so this return sql doesn't have
            """
            out_cols = self.get_columns(with_col_aliases)
            ordering = self.get_ordering()

            # This must come after 'select' and 'ordering' -- see docstring of
            # get_from_clause() for details.
            from_, f_params = self.get_from_clause()

            where, w_params = self.where.as_sql(qn=self.quote_name_unless_alias)
            params = []
            for val in self.extra_select.itervalues():
                params.extend(val[1])
            result = ['SELECT']
            if self.distinct:
                result.append('DISTINCT')
            if with_top_n:
                result.append('TOP ${end_rows} ')
            else:
                self.ordering_aliases.append('(ROW_NUMBER() OVER (ORDER BY %s)) AS [rn]' % rn_orderby)
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

            if self.group_by:
                grouping = self.get_grouping()
                result.append('GROUP BY %s' % ', '.join(grouping))

            if self.having:
                having, h_params = self.get_having()
                result.append('HAVING %s' % ','.join(having))
                params.extend(h_params)

            params.extend(self.extra_params)
            return ' '.join(result), tuple(params)

        def as_sql(self, with_limits=True, with_col_aliases=False):
            """
            """
            if with_limits and self.high_mark == 0 and self.low_mark == 0:
                return "",()
            do_offset = with_limits and (self.high_mark or self.low_mark)

            # If no offsets, just return the result of the base class
            # `as_sql`.
            if not do_offset:
                return super(SqlServerQuery, self).as_sql(with_limits=False,
                                                          with_col_aliases=with_col_aliases)

            self.pre_sql_setup()
            out_cols = self.get_columns(with_col_aliases)
            ordering = self.get_ordering()

            if self.connection.sqlserver_version >= 2005:
                # Getting the "ORDER BY" SQL for the ROW_NUMBER() result.
                if not self.high_mark:
                    self.high_mark = self.connection.ops.no_limit_value()

                if ordering:
                    rn_orderby = ', '.join(ordering)
                else:
                    # ROW_NUMBER() function always requires an
                    # order-by clause.  So we need to define a default
                    # order-by, since none was provided.
                    qn = self.quote_name_unless_alias
                    opts = self.model._meta
                    rn_orderby = '%s.%s' % (qn(opts.db_table), qn(opts.fields[0].db_column or opts.fields[0].column))

                # Getting the selection SQL and the params, which has the `rn`
                # extra selection SQL.
                sql, params= self.as_sql_internal(with_col_aliases=True, with_row_number=True, rn_orderby=rn_orderby)

                # Constructing the result SQL, using the initial select SQL
                # obtained above.
                result = ['SELECT * FROM (%s) as X' % sql]

                # Place WHERE condition on `rn` for the desired range.
                result.append('WHERE X.rn BETWEEN %d AND %d' % (self.low_mark+1, self.high_mark,))

                # Returning the SQL w/params.
                return ' '.join(result), params

            # else SQL SERVER 2000 and below
            # For example: limit,offset 10,20
            # SQL as> select * from (select TOP 20 * from (select top 30 * from hello_page order by id ASC) as p order by p.id desc) as x order by id asc;
            sql, params= self.as_sql_internal(with_col_aliases=True, with_top_n=True)
            qn = self.quote_name_unless_alias
            opts = self.model._meta
            #
            # We can have model's db_table as [dbname].[dbo].[tablename] (actually dbname].[dbo].[tablename ;-) ,
            # so we need change:
            #     as [dbname].[dbo].[tablename] order by [dbname].[dbo].[tablename].[field]
            #  => as X order by [X].[field]
            #
            as_temp_table = 'X'
            if not ordering: # if don't has ordering, we make a default ordering
                ordering = '%s.%s' % (qn(opts.db_table), qn(opts.fields[0].db_column or opts.fields[0].column))
                ordering_as = '%s.%s' % (as_temp_table, qn(opts.fields[0].db_column or opts.fields[0].column))
                ordering_rev = '%s DESC' % ordering_as
            else:
                o_as = []
                o_rev = []
                for o in ordering:
                    field, order = o.split(".")[-1].split(' ')
                    o_as += ["%s.%s %s" % (as_temp_table, field, order)]
                    if order=="DESC":
                        order="ASC"
                    else:
                        order="DESC"
                    o_rev += ["%s.%s %s" % (as_temp_table, field, order)]
                ordering_as = ','.join(o_as)
                ordering_rev = ','.join(o_rev)
                ordering = ','.join(ordering)
            if not self.high_mark:
                fmt = """SELECT %(cols)s FROM %(table)s WHERE %(key)s NOT IN (%(sql)s ORDER BY %(ordering)s)"""
                # get cols and replace by key
                cols_begin = sql.find('${end_rows}')+len('${end_rows}')+1
                cols_end = sql.find(' FROM ')
                cols = sql[cols_begin:cols_end]
                sql = sql[:cols_begin]+' ${key} ' + sql[cols_end:]
                tmpl = string.Template(sql)
                sqlp = tmpl.substitute({'end_rows':self.low_mark,'key':qn(opts.pk.db_column or opts.pk.column)})
                result = fmt % {'sql':sqlp,
                                'ordering':ordering,
                                'table':qn(opts.db_table),
                                'key':qn(opts.pk.db_column or opts.pk.column),
                                'cols':cols,
                                }
            else:
                fmt = """SELECT * FROM (SELECT TOP  %(limit)d * FROM (%(sql)s ORDER BY %(ordering)s ) as %(table)s ORDER BY %(ordering_rev)s ) AS %(table)s ORDER BY %(ordering_as)s"""
                tmpl = string.Template(sql)
                sqlp = tmpl.substitute({'end_rows':self.high_mark})
                result = fmt % {'limit':self.high_mark-self.low_mark,
                            'sql':sqlp,
                            'ordering':ordering,
                            'ordering_as':ordering_as,
                            'ordering_rev':ordering_rev,
                            'table':as_temp_table,
                            }
            return result, params

        def _insert_as_sql(self, *args, **kwargs):
            """Helper method for monkeypatching Django InsertQuery's as_sql."""
            meta = self.get_meta()

            quoted_table = self.connection.ops.quote_name(meta.db_table)
            # Get (sql, params) from original InsertQuery.as_sql
            sql, params = self._orig_as_sql(*args, **kwargs)

            if meta.pk.attname in self.columns and meta.pk.__class__.__name__ == "AutoField":
                # check if only have pk and default value
                if len(self.columns) == 1 and not params:
                    sql = "INSERT INTO %s DEFAULT VALUES" % quoted_table
                else:
                    sql = "SET IDENTITY_INSERT %s ON;%s;SET IDENTITY_INSERT %s OFF" %\
                        (quoted_table, sql, quoted_table)

            return sql, params

    _classes[QueryClass] = SqlServerQuery
    return SqlServerQuery

def unpickle_query_class(QueryClass):
    """
    Utility function, called by Python's unpickling machinery, that handles
    unpickling of our custom Query subclasses.
    """
    klass = query_class(QueryClass)
    return klass.__new__(klass)
unpickle_query_class.__safe_for_unpickling__ = True
