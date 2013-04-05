from django.db.models.sql.aggregates import Aggregate

class _Aggregate(Aggregate):

    def __init__(self, lookup, **extra):
        self.lookup = lookup
        self.extra = extra

    def _default_alias(self):
        return '%s__%s' % (self.lookup, self.__class__.__name__.lower())
    default_alias = property(_default_alias)

    def add_to_query(self, query, alias, col, source, is_summary):
        super(_Aggregate, self).__init__(col, source, is_summary, **self.extra)
        query.aggregates[alias] = self

class StdDev(_Aggregate):
    name = 'StdDev'
    is_computed = True

    def __init__(self, col, sample=False, **extra):
        super(StdDev, self).__init__(col, **extra)
        self.sql_function = sample and 'STDEV' or 'STDEVP'

class Variance(_Aggregate):
    name = 'Variance'
    is_computed = True

    def __init__(self, col, sample=False, **extra):
        super(Variance, self).__init__(col, **extra)
        self.sql_function = sample and 'VAR' or 'VARP'

class Avg(_Aggregate):
    name = 'Avg'
    is_computed = True
    sql_function = 'AVG'
    sql_template = '%(function)s(Convert(FLOAT, %(field)s))'
