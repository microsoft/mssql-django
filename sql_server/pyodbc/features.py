from django.db.backends.base.features import BaseDatabaseFeatures
from django.utils.functional import cached_property


class DatabaseFeatures(BaseDatabaseFeatures):
    has_native_uuid_field = False
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
    supports_ignore_conflicts = False
    supports_index_on_text_field = False
    supports_paramstyle_pyformat = False
    supports_regex_backreferencing = False
    supports_sequence_reset = False
    supports_subqueries_in_group_by = False
    supports_tablespaces = True
    supports_temporal_subtraction = True
    supports_timezones = False
    supports_transactions = True
    uses_savepoints = True

    @cached_property
    def has_bulk_insert(self):
        return self.connection.sql_server_version > 2005

    @cached_property
    def supports_nullable_unique_constraints(self):
        return self.connection.sql_server_version > 2005

    @cached_property
    def supports_partially_nullable_unique_constraints(self):
        return self.connection.sql_server_version > 2005

    @cached_property
    def supports_partial_indexes(self):
        return self.connection.sql_server_version > 2005

    @cached_property
    def supports_functions_in_partial_indexes(self):
        return self.connection.sql_server_version > 2005
