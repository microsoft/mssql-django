from django.db.models.sql.aggregates import *

class StdDev(Aggregate):
    is_computed = True

    def __init__(self, col, sample=False, **extra):
        super(StdDev, self).__init__(col, **extra)
        self.sql_function = sample and 'STDEV' or 'STDEVP'

class Variance(Aggregate):
    is_computed = True

    def __init__(self, col, sample=False, **extra):
        super(Variance, self).__init__(col, **extra)
        self.sql_function = sample and 'VAR' or 'VARP'

class Avg(Aggregate):
    is_computed = True
    sql_function = 'AVG'
    sql_template = '%(function)s(Convert(FLOAT, %(field)s))'
