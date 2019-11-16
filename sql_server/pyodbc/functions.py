from django.db.models.functions import Cast
from django.db.models.functions.math import ATan2, Log, Ln, Round


class TryCast(Cast):
    function = 'TRY_CAST'


def sqlserver_atan2(self, compiler, connection, **extra_context):
    return self.as_sql(compiler, connection, function='ATN2', **extra_context)


def sqlserver_log(self, compiler, connection, **extra_context):
    clone = self.copy()
    clone.set_source_expressions(self.get_source_expressions()[::-1])
    return clone.as_sql(compiler, connection, **extra_context)


def sqlserver_ln(self, compiler, connection, **extra_context):
    return self.as_sql(compiler, connection, function='LOG', **extra_context)


def sqlserver_round(self, compiler, connection, **extra_context):
    return self.as_sql(compiler, connection, template='%(function)s(%(expressions)s, 0)', **extra_context)


ATan2.as_microsoft = sqlserver_atan2
Log.as_microsoft = sqlserver_log
Ln.as_microsoft = sqlserver_ln
Round.as_microsoft = sqlserver_round
