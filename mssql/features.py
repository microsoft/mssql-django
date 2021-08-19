# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from django.db.backends.base.features import BaseDatabaseFeatures
from django.utils.functional import cached_property


class DatabaseFeatures(BaseDatabaseFeatures):
    allow_sliced_subqueries_with_in = False
    can_introspect_autofield = True
    can_introspect_json_field = False
    can_introspect_small_integer_field = True
    can_return_columns_from_insert = True
    can_return_id_from_insert = True
    can_rollback_ddl = True
    can_use_chunked_reads = False
    for_update_after_from = True
    greatest_least_ignores_nulls = True
    has_json_object_function = False
    has_json_operators = False
    has_native_json_field = False
    has_native_uuid_field = False
    has_real_datatype = True
    has_select_for_update = True
    has_select_for_update_nowait = True
    has_select_for_update_skip_locked = True
    ignores_quoted_identifier_case = True
    ignores_table_name_case = True
    order_by_nulls_first = True
    requires_literal_defaults = True
    requires_sqlparse_for_splitting = False
    supports_boolean_expr_in_select_clause = False
    supports_covering_indexes = True
    supports_deferrable_unique_constraints = False
    supports_expression_indexes = False
    supports_ignore_conflicts = False
    supports_index_on_text_field = False
    supports_json_field_contains = False
    supports_order_by_nulls_modifier = False
    supports_over_clause = True
    supports_paramstyle_pyformat = False
    supports_primitives_in_json_field = False
    supports_regex_backreferencing = True
    supports_sequence_reset = False
    supports_subqueries_in_group_by = False
    supports_tablespaces = True
    supports_temporal_subtraction = True
    supports_timezones = False
    supports_transactions = True
    uses_savepoints = True
    has_bulk_insert = True
    supports_nullable_unique_constraints = True
    supports_partially_nullable_unique_constraints = True
    supports_partial_indexes = True
    supports_functions_in_partial_indexes = True

    @cached_property
    def has_zoneinfo_database(self):
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT TOP 1 1 FROM sys.time_zone_info")
            return cursor.fetchone() is not None

    @cached_property
    def supports_json_field(self):
        return self.connection.sql_server_version >= 2016 or self.connection.to_azure_sql_db
