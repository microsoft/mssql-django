try:
    import pytz
except ImportError:
    pytz = None

from django.db.backends.base.features import BaseDatabaseFeatures


class DatabaseFeatures(BaseDatabaseFeatures):
    allow_sliced_subqueries = False
    can_introspect_autofield = True
    can_introspect_small_integer_field = True
    can_return_id_from_insert = True
    can_use_chunked_reads = False
    for_update_after_from = True
    has_bulk_insert = True
    has_real_datatype = True
    has_select_for_update = True
    has_select_for_update_nowait = True
    has_zoneinfo_database = pytz is not None
    ignores_quoted_identifier_case = True
    requires_literal_defaults = True
    requires_sqlparse_for_splitting = False
    supports_1000_query_parameters = False
    supports_nullable_unique_constraints = False
    supports_paramstyle_pyformat = False
    supports_partially_nullable_unique_constraints = False
    supports_regex_backreferencing = False
    supports_sequence_reset = False
    supports_subqueries_in_group_by = False
    supports_tablespaces = True
    supports_temporal_subtraction = True
    supports_timezones = False
    supports_transactions = True
    uses_savepoints = True
