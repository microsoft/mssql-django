from django.db.backends.base.features import BaseDatabaseFeatures


class DatabaseFeatures(BaseDatabaseFeatures):
    allow_sliced_subqueries_with_in = False
    can_introspect_autofield = True
    can_introspect_small_integer_field = True
    can_return_id_from_insert = True
    can_use_chunked_reads = False
    for_update_after_from = True
    greatest_least_ignores_nulls = True
    has_real_datatype = True
    has_select_for_update = True
    has_select_for_update_nowait = True
    has_select_for_update_skip_locked = True
    has_zoneinfo_database = False
    ignores_table_name_case = True
    ignores_quoted_identifier_case = True
    requires_literal_defaults = True
    requires_sqlparse_for_splitting = False
    supports_index_on_text_field = False
    supports_nullable_unique_constraints = True
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
