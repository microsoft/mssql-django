"""
Custom Query class for SQL Server.
Derives from: django.db.models.sql.query.Query
"""
import string

from django.db.backends import util

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

            # If we are an insert query, wrap "as_sql"
            if self.__class__.__name__ == "InsertQuery":
                self._parent_as_sql = self.as_sql
                self.as_sql = self._insert_as_sql

        def as_sql_internal(self, with_col_aliases=False, with_row_number=False, with_top_n=False):
            """
                SQL SERVER row_number() already have ordering, so this return sql don't has ordering
            """
            out_cols = self.get_columns(with_col_aliases)
            ordering = self.get_ordering()

            # This must come after 'select' and 'ordering' -- see docstring of
            # get_from_clause() for details.
            from_, f_params = self.get_from_clause()

            where, w_params = self.where.as_sql(qn=self.quote_name_unless_alias)
            params = list(self.extra_select_params)

            result = ['SELECT']
            if self.distinct:
                result.append('DISTINCT')
            if with_top_n:
                result.append('TOP ${end_rows} ')
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

            params.extend(self.extra_params)
            return ' '.join(result), tuple(params)

        def as_sql(self, with_limits=True, with_col_aliases=False):
            """
            """
            from django.db import connection
            from operations import SQL_SERVER_2005_VERSION

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

            if connection.sqlserver_version >= SQL_SERVER_2005_VERSION:
                # Getting the "ORDER BY" SQL for the ROW_NUMBER() result.
                if not self.high_mark:
                    self.high_mark = connection.ops.no_limit_value()

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
                self.extra_select['rn'] = 'ROW_NUMBER() OVER (ORDER BY %s )' % rn_orderby
                sql, params= self.as_sql_internal(with_col_aliases=True, with_row_number=True)

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
            as_temp_table = '__XXX_as_XXX__'
            if not ordering: # if don't has ordering, we make a default ordering
                ordering = '%s.%s' % (qn(opts.db_table), qn(opts.fields[0].db_column or opts.fields[0].column))
                ordering_as = '%s.%s' % (as_temp_table, qn(opts.fields[0].db_column or opts.fields[0].column))
                ordering_rev = '%s DESC' % ordering_as
            else:
                self.standard_ordering = not self.standard_ordering
                ordering_rev = self.get_ordering()
                self.standard_ordering = not self.standard_ordering
                ordering = ','.join(ordering)
                ordering_rev = ','.join(ordering_rev)
            fmt = """SELECT * FROM (SELECT TOP  %(limit)d * FROM (%(sql)s ORDER BY %(ordering)s ) as %(table)s ORDER BY %(ordering_rev)s ) AS %(table)s ORDER BY %(ordering_as)s"""
            tmpl = string.Template(sql)
            if not self.high_mark:
                raise "SQL SERVER 2000 not supper [OFFSET:] "
            else:
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
            meta = self.get_meta()
            
            quoted_table = self.connection.ops.quote_name(meta.db_table)
            # Get (sql,params) from original InsertQuery.as_sql
            sql, params = self._parent_as_sql(*args,**kwargs)
            
            if (meta.pk.attname in self.columns) and (meta.pk.__class__.__name__ == "AutoField"):
                # check if only have pk and default value
                if len(self.columns)==1 and len(params)==0:
                    sql = "INSERT INTO %s DEFAULT VALUES" % quoted_table
                else:
                    sql = "SET IDENTITY_INSERT %s ON;%s;SET IDENTITY_INSERT %s OFF" %\
                        (quoted_table, sql, quoted_table)

            return sql, params

        def set_limits(self, low=None, high=None):
            super(SqlServerQuery, self).set_limits(low, high)

            from django.db import connection
            from operations import SQL_SERVER_2005_VERSION
            if connection.sqlserver_version >= SQL_SERVER_2005_VERSION:
                # For Sqlserver 2005 and up, we use row_number() for limit/offset
                # We need to select the row number for the LIMIT/OFFSET sql.
                # A placeholder is added to extra_select now, because as_sql is
                # too late to be modifying extra_select.  However, the actual sql
                # depends on the ordering, so that is generated in as_sql.
                self.extra_select['rn'] = '1'

        def clear_limits(self):
            super(SqlServerQuery, self).clear_limits()
            if 'rn' in self.extra_select:
                del self.extra_select['rn']

    _classes[QueryClass] = SqlServerQuery
    return SqlServerQuery
