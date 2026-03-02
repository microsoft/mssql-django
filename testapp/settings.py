# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.
import os
from pathlib import Path

from django import VERSION

BASE_DIR = Path(__file__).resolve().parent.parent

DATABASES = {
    "default": {
        "ENGINE": "mssql",
        "NAME": os.environ.get("MSSQL_DB_NAME", "default"),
        "USER": os.environ.get("MSSQL_USER", "sa"),
        "PASSWORD": os.environ.get("MSSQL_PASSWORD", "MyPassword42"),
        "HOST": os.environ.get("MSSQL_HOST", "localhost"),
        "PORT": os.environ.get("MSSQL_PORT", "1433"),
        "OPTIONS": {"driver": os.environ.get("MSSQL_DRIVER", "ODBC Driver 17 for SQL Server"), "return_rows_bulk_insert": True},
    },
    'other': {
        "ENGINE": "mssql",
        "NAME": os.environ.get("MSSQL_DB_NAME_OTHER", "other"),
        "USER": os.environ.get("MSSQL_USER", "sa"),
        "PASSWORD": os.environ.get("MSSQL_PASSWORD", "MyPassword42"),
        "HOST": os.environ.get("MSSQL_HOST", "localhost"),
        "PORT": os.environ.get("MSSQL_PORT", "1433"),
        "OPTIONS": {"driver": os.environ.get("MSSQL_DRIVER", "ODBC Driver 17 for SQL Server"), "return_rows_bulk_insert": True},
    },
}

# Django 3.0 and below unit test doesn't handle more than 2 databases in DATABASES correctly
if VERSION >= (3, 1):
    DATABASES['sqlite'] = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(BASE_DIR / "db.sqlitetest"),
    }


# Set to `True` locally if you want SQL queries logged to django_sql.log
DEBUG = False

# Logging
LOG_DIR = os.path.join(os.path.dirname(__file__), '..', 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': True,
    'formatters': {
        'myformatter': {
            'format': '%(asctime)s P%(process)05dT%(thread)05d [%(levelname)s] %(name)s: %(message)s',
        },
    },
    'handlers': {
        'db_output': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(LOG_DIR, 'django_sql.log'),
            'formatter': 'myformatter',
        },
        'default': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(LOG_DIR, 'default.log'),
            'formatter': 'myformatter',
        }
    },
    'loggers': {
        '': {
            'handlers': ['default'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'django.db': {
            'handlers': ['db_output'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}

INSTALLED_APPS = (
    'django.contrib.contenttypes',
    'django.contrib.staticfiles',
    'django.contrib.auth',
    'mssql',
    'testapp',
)

SECRET_KEY = "django_tests_secret_key"

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
]

# Set DEFAULT_AUTO_FIELD to suppress W042 warnings in Django's test suite.
# Our testapp models that need AutoField (Question, Choice) have explicit
# id = models.AutoField(primary_key=True) to match their existing migrations.
if VERSION >= (6, 0):
    DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
else:
    DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

ENABLE_REGEX_TESTS = False
USE_TZ = False

TEST_RUNNER = "testapp.runners.ExcludedTestSuiteRunner"

# Test exclusions for features not supported by SQL Server or requiring special handling
# Community contributions welcome to implement these features incrementally
EXCLUDED_TESTS = [
    'aggregation_regress.tests.AggregationTests.test_annotation_with_value',
    'aggregation.tests.AggregateTestCase.test_distinct_on_aggregate',
    'annotations.tests.NonAggregateAnnotationTestCase.test_annotate_exists',
    'custom_lookups.tests.BilateralTransformTests.test_transform_order_by',
    'expressions.tests.BasicExpressionsTests.test_filtering_on_annotate_that_uses_q',
    'expressions.tests.BasicExpressionsTests.test_order_by_exists',
    'expressions.tests.ExpressionOperatorTests.test_righthand_power',
    'expressions.tests.FTimeDeltaTests.test_datetime_subtraction_microseconds',
    'expressions.tests.FTimeDeltaTests.test_duration_with_datetime_microseconds',
    'expressions.tests.IterableLookupInnerExpressionsTests.test_expressions_in_lookups_join_choice',
    'expressions_case.tests.CaseExpressionTests.test_annotate_with_in_clause',
    'expressions_window.tests.WindowFunctionTests.test_nth_returns_null',
    'expressions_window.tests.WindowFunctionTests.test_nthvalue',
    'expressions_window.tests.WindowFunctionTests.test_range_n_preceding_and_following',
    'field_deconstruction.tests.FieldDeconstructionTests.test_binary_field',
    'ordering.tests.OrderingTests.test_orders_nulls_first_on_filtered_subquery',
    'get_or_create.tests.UpdateOrCreateTransactionTests.test_creation_in_transaction',
    'indexes.tests.PartialIndexTests.test_multiple_conditions',
    'migrations.test_executor.ExecutorTests.test_alter_id_type_with_fk',
    'migrations.test_operations.OperationTests.test_add_constraint_percent_escaping',
    'migrations.test_operations.OperationTests.test_alter_field_pk',
    'migrations.test_operations.OperationTests.test_alter_field_reloads_state_on_fk_with_to_field_target_changes',
    'schema.tests.SchemaTests.test_alter_auto_field_to_char_field',
    'schema.tests.SchemaTests.test_alter_auto_field_to_integer_field',
    'schema.tests.SchemaTests.test_alter_implicit_id_to_explicit',
    'schema.tests.SchemaTests.test_alter_int_pk_to_autofield_pk',
    'schema.tests.SchemaTests.test_alter_int_pk_to_bigautofield_pk',
    'schema.tests.SchemaTests.test_alter_pk_with_self_referential_field',
    'schema.tests.SchemaTests.test_remove_field_check_does_not_remove_meta_constraints',
    'schema.tests.SchemaTests.test_remove_field_unique_does_not_remove_meta_constraints',
    'schema.tests.SchemaTests.test_text_field_with_db_index',
    'schema.tests.SchemaTests.test_unique_together_with_fk',
    'schema.tests.SchemaTests.test_unique_together_with_fk_with_existing_index',
    'aggregation.tests.AggregateTestCase.test_count_star',
    'aggregation_regress.tests.AggregationTests.test_values_list_annotation_args_ordering',
    'expressions.tests.FTimeDeltaTests.test_invalid_operator',
    'fixtures_regress.tests.TestFixtures.test_loaddata_raises_error_when_fixture_has_invalid_foreign_key',
    'invalid_models_tests.test_ordinary_fields.TextFieldTests.test_max_length_warning',
    'model_indexes.tests.IndexesTests.test_db_tablespace',
    'ordering.tests.OrderingTests.test_deprecated_values_annotate',
    'queries.test_qs_combinators.QuerySetSetOperationTests.test_limits',
    'backends.tests.BackendTestCase.test_unicode_password',
    'migrations.test_commands.MigrateTests.test_migrate_syncdb_app_label',
    'migrations.test_commands.MigrateTests.test_migrate_syncdb_deferred_sql_executed_with_schemaeditor',
    'migrations.test_operations.OperationTests.test_alter_field_pk_fk',
    'schema.tests.SchemaTests.test_add_foreign_key_quoted_db_table',
    'schema.tests.SchemaTests.test_unique_and_reverse_m2m',
    'schema.tests.SchemaTests.test_unique_no_unnecessary_fk_drops',
    'select_for_update.tests.SelectForUpdateTests.test_for_update_after_from',
    'db_functions.datetime.test_extract_trunc.DateFunctionTests.test_extract_year_exact_lookup',
    'db_functions.datetime.test_extract_trunc.DateFunctionTests.test_extract_year_greaterthan_lookup',
    'db_functions.datetime.test_extract_trunc.DateFunctionTests.test_extract_year_lessthan_lookup',
    'db_functions.datetime.test_extract_trunc.DateFunctionWithTimeZoneTests.test_extract_year_exact_lookup',
    'db_functions.datetime.test_extract_trunc.DateFunctionWithTimeZoneTests.test_extract_year_greaterthan_lookup',
    'db_functions.datetime.test_extract_trunc.DateFunctionWithTimeZoneTests.test_extract_year_lessthan_lookup',
    'db_functions.datetime.test_extract_trunc.DateFunctionWithTimeZoneTests.test_trunc_ambiguous_and_invalid_times',
    'delete.tests.DeletionTests.test_only_referenced_fields_selected',
    'queries.test_db_returning.ReturningValuesTests.test_insert_returning',
    'queries.test_db_returning.ReturningValuesTests.test_insert_returning_non_integer',
    'backends.tests.BackendTestCase.test_queries',
    'schema.tests.SchemaTests.test_inline_fk',
    'aggregation.tests.AggregateTestCase.test_aggregation_subquery_annotation_exists',
    'aggregation.tests.AggregateTestCase.test_aggregation_subquery_annotation_values_collision',
    'db_functions.datetime.test_extract_trunc.DateFunctionWithTimeZoneTests.test_extract_func_with_timezone',
    'expressions.tests.FTimeDeltaTests.test_date_subquery_subtraction',
    'expressions.tests.FTimeDeltaTests.test_datetime_subquery_subtraction',
    'expressions.tests.FTimeDeltaTests.test_time_subquery_subtraction',
    'migrations.test_operations.OperationTests.test_alter_field_reloads_state_on_fk_with_to_field_target_type_change',
    'schema.tests.SchemaTests.test_alter_smallint_pk_to_smallautofield_pk',
    'db_functions.datetime.test_extract_trunc.DateFunctionTests.test_extract_func',
    'db_functions.datetime.test_extract_trunc.DateFunctionTests.test_extract_iso_weekday_func',
    'db_functions.datetime.test_extract_trunc.DateFunctionWithTimeZoneTests.test_extract_func',
    'db_functions.datetime.test_extract_trunc.DateFunctionWithTimeZoneTests.test_extract_iso_weekday_func',
    'datetimes.tests.DateTimesTests.test_datetimes_ambiguous_and_invalid_times',
    'inspectdb.tests.InspectDBTestCase.test_number_field_types',
    'inspectdb.tests.InspectDBTestCase.test_json_field',
    'ordering.tests.OrderingTests.test_default_ordering_by_f_expression',
    'ordering.tests.OrderingTests.test_order_by_nulls_first',
    'ordering.tests.OrderingTests.test_order_by_nulls_last',
    'queries.test_qs_combinators.QuerySetSetOperationTests.test_ordering_by_f_expression_and_alias',
    'queries.test_db_returning.ReturningValuesTests.test_insert_returning_multiple',
    'dbshell.tests.DbshellCommandTestCase.test_command_missing',
    'schema.tests.SchemaTests.test_char_field_pk_to_auto_field',
    'datetimes.tests.DateTimesTests.test_21432',

    # JSONFields
    'model_fields.test_jsonfield.TestQuerying.test_key_quoted_string',
    'model_fields.test_jsonfield.TestQuerying.test_isnull_key',
    'model_fields.test_jsonfield.TestQuerying.test_none_key',
    'model_fields.test_jsonfield.TestQuerying.test_none_key_and_exact_lookup',
    'model_fields.test_jsonfield.TestQuerying.test_key_escape',
    'model_fields.test_jsonfield.TestQuerying.test_ordering_by_transform',
    'expressions_window.tests.WindowFunctionTests.test_key_transform',

    # Django 3.2
    'db_functions.datetime.test_extract_trunc.DateFunctionWithTimeZoneTests.test_trunc_func_with_timezone',
    'db_functions.datetime.test_extract_trunc.DateFunctionWithTimeZoneTests.test_trunc_timezone_applied_before_truncation',
    'expressions.tests.ExistsTests.test_optimizations',
    'expressions.tests.FTimeDeltaTests.test_delta_add',
    'expressions.tests.FTimeDeltaTests.test_delta_subtract',
    'expressions.tests.FTimeDeltaTests.test_delta_update',
    'expressions.tests.FTimeDeltaTests.test_exclude',
    'expressions.tests.FTimeDeltaTests.test_mixed_comparisons1',
    'expressions.tests.FTimeDeltaTests.test_negative_timedelta_update',
    'inspectdb.tests.InspectDBTestCase.test_field_types',
    'lookup.tests.LookupTests.test_in_ignore_none',
    'lookup.tests.LookupTests.test_in_ignore_none_with_unhashable_items',
    'queries.test_qs_combinators.QuerySetSetOperationTests.test_exists_union',
    'schema.tests.SchemaTests.test_ci_cs_db_collation',
    'select_for_update.tests.SelectForUpdateTests.test_unsuported_no_key_raises_error',

    # Django 4.0
    'aggregation.tests.AggregateTestCase.test_aggregation_default_using_date_from_database',
    'aggregation.tests.AggregateTestCase.test_aggregation_default_using_datetime_from_database',
    'aggregation.tests.AggregateTestCase.test_aggregation_default_using_time_from_database',
    'expressions.tests.FTimeDeltaTests.test_durationfield_multiply_divide',
    'lookup.tests.LookupQueryingTests.test_alias',
    'lookup.tests.LookupQueryingTests.test_filter_exists_lhs',
    'lookup.tests.LookupQueryingTests.test_filter_lookup_lhs',
    'lookup.tests.LookupQueryingTests.test_filter_subquery_lhs',
    'lookup.tests.LookupQueryingTests.test_filter_wrapped_lookup_lhs',
    'lookup.tests.LookupQueryingTests.test_lookup_in_order_by',
    'lookup.tests.LookupTests.test_lookup_rhs',
    'order_with_respect_to.tests.OrderWithRespectToBaseTests.test_previous_and_next_in_order',
    'ordering.tests.OrderingTests.test_default_ordering_does_not_affect_group_by',
    'queries.test_explain.ExplainUnsupportedTests.test_message',
    'aggregation.tests.AggregateTestCase.test_coalesced_empty_result_set',
    'aggregation.tests.AggregateTestCase.test_empty_result_optimization',
    'queries.tests.Queries6Tests.test_col_alias_quoted',
    'backends.tests.BackendTestCase.test_queries_logger',
    'migrations.test_operations.OperationTests.test_alter_field_pk_mti_fk',
    'migrations.test_operations.OperationTests.test_run_sql_add_missing_semicolon_on_collect_sql',
    'migrations.test_operations.OperationTests.test_alter_field_pk_mti_and_fk_to_base',

    # Hashing
    # UTF-8 support was added in SQL Server 2019
    'db_functions.text.test_md5.MD5Tests.test_basic',
    'db_functions.text.test_md5.MD5Tests.test_transform',
    'db_functions.text.test_sha1.SHA1Tests.test_basic',
    'db_functions.text.test_sha1.SHA1Tests.test_transform',
    'db_functions.text.test_sha256.SHA256Tests.test_basic',
    'db_functions.text.test_sha256.SHA256Tests.test_transform',
    'db_functions.text.test_sha512.SHA512Tests.test_basic',
    'db_functions.text.test_sha512.SHA512Tests.test_transform',
    # SQL Server doesn't support SHA224 or SHA387
    'db_functions.text.test_sha224.SHA224Tests.test_basic',
    'db_functions.text.test_sha224.SHA224Tests.test_transform',
    'db_functions.text.test_sha384.SHA384Tests.test_basic',
    'db_functions.text.test_sha384.SHA384Tests.test_transform',

    # Timezone
    'timezones.tests.NewDatabaseTests.test_cursor_explicit_time_zone',
    # Skipped next tests because pyodbc drops timezone https://github.com/mkleehammer/pyodbc/issues/810
    'timezones.tests.LegacyDatabaseTests.test_cursor_execute_accepts_naive_datetime',
    'timezones.tests.LegacyDatabaseTests.test_cursor_execute_returns_naive_datetime',
    'timezones.tests.NewDatabaseTests.test_cursor_execute_accepts_naive_datetime',
    'timezones.tests.NewDatabaseTests.test_cursor_execute_returns_naive_datetime',
    'timezones.tests.NewDatabaseTests.test_cursor_execute_accepts_aware_datetime',
    'timezones.tests.NewDatabaseTests.test_cursor_execute_returns_aware_datetime',

    # Django 4.1
    'aggregation.test_filter_argument.FilteredAggregateTests.test_filtered_aggregate_on_exists',
    'aggregation.tests.AggregateTestCase.test_aggregation_exists_multivalued_outeref',
    'annotations.tests.NonAggregateAnnotationTestCase.test_full_expression_annotation_with_aggregation',
    'db_functions.datetime.test_extract_trunc.DateFunctionWithTimeZoneTests.test_extract_lookup_name_sql_injection',
    'db_functions.datetime.test_extract_trunc.DateFunctionTests.test_extract_lookup_name_sql_injection',
    'schema.tests.SchemaTests.test_autofield_to_o2o',
    'prefetch_related.tests.PrefetchRelatedTests.test_m2m_prefetching_iterator_with_chunks',
    'migrations.test_operations.OperationTests.test_create_model_with_boolean_expression_in_check_constraint',
    'queries.test_qs_combinators.QuerySetSetOperationTests.test_union_in_subquery_related_outerref',
    # These tests pass on SQL Server 2022 or newer
    'model_fields.test_jsonfield.TestQuerying.test_has_key_list',
    'model_fields.test_jsonfield.TestQuerying.test_has_key_null_value',
    'model_fields.test_jsonfield.TestQuerying.test_lookups_with_key_transform',
    'model_fields.test_jsonfield.TestQuerying.test_ordering_grouping_by_count',
    'model_fields.test_jsonfield.TestQuerying.test_has_key_number',

    # Django 4.2
    'get_or_create.tests.UpdateOrCreateTests.test_update_only_defaults_and_pre_save_fields_when_local_fields',
    'aggregation.test_filter_argument.FilteredAggregateTests.test_filtered_aggregate_empty_condition',
    'aggregation.test_filter_argument.FilteredAggregateTests.test_filtered_aggregate_ref_multiple_subquery_annotation',
    'aggregation.test_filter_argument.FilteredAggregateTests.test_filtered_aggregate_ref_subquery_annotation',
    'aggregation.tests.AggregateAnnotationPruningTests.test_referenced_group_by_annotation_kept',
    'aggregation.tests.AggregateAnnotationPruningTests.test_referenced_window_requires_wrapping',
    'aggregation.tests.AggregateTestCase.test_group_by_nested_expression_with_params',
    'expressions.tests.BasicExpressionsTests.test_aggregate_subquery_annotation',
    'queries.test_qs_combinators.QuerySetSetOperationTests.test_union_order_with_null_first_last',
    'queries.test_qs_combinators.QuerySetSetOperationTests.test_union_with_select_related_and_order',
    'expressions_window.tests.WindowFunctionTests.test_limited_filter',
    'schema.tests.SchemaTests.test_remove_ignored_unique_constraint_not_create_fk_index',

]

# Django 5.0 specific exclusions - these tests fail due to SQL Server limitations
if VERSION >= (5, 0):
    EXCLUDED_TESTS.extend([
        # Generated field 5.0.6 tests
        'migrations.test_operations.OperationTests.test_invalid_generated_field_changes_on_rename_virtual',
        'migrations.test_operations.OperationTests.test_invalid_generated_field_changes_on_rename_stored',
    ])

# Django 5.1 specific exclusions - these tests fail due to SQL Server limitations
if VERSION >= (5, 1):
    EXCLUDED_TESTS.extend([
        # Composite primary key tests - not supported in SQL Server
        'inspectdb.tests.InspectDBTransactionalTests.test_composite_primary_key',
        
        # Backend and schema test failures that appear in Django 5.1
        # TODO: Fix SQL Server specific backend behavior 
        'backends.base.test_base.ExecuteWrapperTests.test_wrapper_debug',
        'indexes.tests.SchemaIndexesTests.test_alter_field_unique_false_removes_deferred_sql',
    ])

# Django 6.0 specific exclusions
if VERSION >= (6, 0):
    EXCLUDED_TESTS.extend([
        # JSONField - UUID serialization and negative array index handling needed
        'model_fields.test_jsonfield.TestQuerying.test_deep_negative_lookup_array',
        'model_fields.test_jsonfield.TestQuerying.test_deep_negative_lookup_mixed',
        'model_fields.test_jsonfield.TestQuerying.test_deep_values',
        'model_fields.test_jsonfield.TestQuerying.test_expression_wrapper_key_transform',
        'model_fields.test_jsonfield.TestQuerying.test_has_any_keys',
        'model_fields.test_jsonfield.TestQuerying.test_has_key',
        'model_fields.test_jsonfield.TestQuerying.test_has_keys',
        'model_fields.test_jsonfield.TestQuerying.test_icontains',
        'model_fields.test_jsonfield.TestQuerying.test_join_key_transform_annotation_expression',
        'model_fields.test_jsonfield.TestQuerying.test_key_contains',
        'model_fields.test_jsonfield.TestQuerying.test_key_endswith',
        'model_fields.test_jsonfield.TestQuerying.test_key_icontains',
        'model_fields.test_jsonfield.TestQuerying.test_key_iendswith',
        'model_fields.test_jsonfield.TestQuerying.test_key_iexact',
        'model_fields.test_jsonfield.TestQuerying.test_key_in',
        'model_fields.test_jsonfield.TestQuerying.test_key_istartswith',
        'model_fields.test_jsonfield.TestQuerying.test_key_startswith',
        'model_fields.test_jsonfield.TestQuerying.test_key_transform',
        'model_fields.test_jsonfield.TestQuerying.test_key_transform_annotation_expression',
        'model_fields.test_jsonfield.TestQuerying.test_key_transform_raw_expression',
        'model_fields.test_jsonfield.TestQuerying.test_lookup_exclude',
        'model_fields.test_jsonfield.TestQuerying.test_lookup_exclude_nonexistent_key',
        'model_fields.test_jsonfield.TestQuerying.test_nested_key_transform_annotation_expression',
        'model_fields.test_jsonfield.TestQuerying.test_nested_key_transform_on_subquery',
        'model_fields.test_jsonfield.TestQuerying.test_nested_key_transform_raw_expression',
        'model_fields.test_jsonfield.TestQuerying.test_none_key_exclude',
        'model_fields.test_jsonfield.TestQuerying.test_order_grouping_custom_decoder',
        'model_fields.test_jsonfield.TestQuerying.test_ordering_by_transform',
        'model_fields.test_jsonfield.TestQuerying.test_shallow_list_lookup',
        'model_fields.test_jsonfield.TestQuerying.test_shallow_list_negative_lookup',
        'model_fields.test_jsonfield.TestQuerying.test_shallow_lookup_obj_target',
        
        # SQL Server limitations (permanent exclusions)
        # STRING_AGG with DISTINCT - SQL Server syntax differs
        'aggregation.tests.AggregateTestCase.test_distinct_on_stringagg',
        # REGEXP_LIKE function not available in SQL Server
        'expressions.tests.BasicExpressionsTests.test_lookups_subquery',
        
        # JSON path escaping test - bracket notation difference
        'model_fields.test_jsonfield.TestQuerying.test_key_sql_injection_escape',
        # Migration tests with schema differences
        'migrations.test_commands.MakeMigrationsTests.test_makemigrations_check_no_changes',
        'migrations.test_commands.MakeMigrationsTests.test_makemigrations_model_rename_interactive',
        'migrations.test_commands.MakeMigrationsTests.test_makemigrations_no_changes',
        'schema.tests.SchemaTests.test_remove_constraints_capital_letters',
        # Query count differences due to SQL Server parameter limits
        'lookup.tests.LookupTests.test_in_bulk_lots_of_ids',
        'foreign_object.tests.ForeignObjectModelValidationTests.test_validate_constraints_success_case_single_query',
        # Bulk create output column count
        'bulk_create.tests.BulkCreateTests.test_db_default_field_excluded',
        # DEFAULT_AUTO_FIELD behavior - testapp models use explicit AutoField
        'model_options.test_default_pk.TestDefaultPK.test_default_value_of_default_auto_field_setting',
        # Introspection returns IntegerField for AutoField-generated columns
        'introspection.tests.IntrospectionTests.test_get_table_description_types',
        # Schema tests expect BigIntegerField (from BigAutoField) but get IntegerField
        'schema.tests.SchemaTests.test_alter_fk',
        'schema.tests.SchemaTests.test_alter_fk_to_o2o',
        'schema.tests.SchemaTests.test_alter_o2o_to_fk',
        'schema.tests.SchemaTests.test_m2m',
        'schema.tests.SchemaTests.test_m2m_create',
        'schema.tests.SchemaTests.test_m2m_create_custom',
        'schema.tests.SchemaTests.test_m2m_create_inherited',
        'schema.tests.SchemaTests.test_m2m_create_through',
        'schema.tests.SchemaTests.test_m2m_create_through_custom',
        'schema.tests.SchemaTests.test_m2m_create_through_inherited',
        'schema.tests.SchemaTests.test_m2m_custom',
        'schema.tests.SchemaTests.test_m2m_inherited',
    ])

# Django 5.2 specific exclusions
# These are good candidates for community contributions - see GitHub issues
if VERSION >= (5, 2):
    EXCLUDED_TESTS.extend([
        # SQL Server parameter splitting uses temp tables, resulting in different query count
        'composite_pk.tests.CompositePKTests.test_in_bulk_batching',
        
        # inspectdb tests that expect specific table structures in inspectdb_special/pascal schemas
        'inspectdb.tests.InspectDBTestCase.test_custom_normalize_table_name',
        'inspectdb.tests.InspectDBTestCase.test_special_column_name_introspection', 
        'inspectdb.tests.InspectDBTestCase.test_table_name_introspection',
        
        # JSONField bulk update with null handling
        # TODO: Fix bulk update SQL generation for JSONField null values
        'queries.test_bulk_update.BulkUpdateTests.test_json_field_sql_null',
        
        # Migration and composite primary key issues  
        # TODO: Implement composite primary key support
        'migrations.test_operations.OperationTests.test_composite_pk_operations',
        'migrations.test_operations.OperationTests.test_generated_field_changes_output_field',
        
        # Backend and schema test failures
        # TODO: Fix SQL Server specific backend behavior 
        # 'backends.base.test_base.ExecuteWrapperTests.test_wrapper_debug',  # Removed duplicate; now only in Django 5.2+ block
        'indexes.tests.SchemaIndexesTests.test_alter_field_unique_false_removes_deferred_sql',
        
        # Aggregation with filtered references  
        # TODO: Fix complex aggregation queries with outer references
        'aggregation.test_filter_argument.FilteredAggregateTests.test_filtered_aggregrate_ref_in_subquery_annotation',
        
        # JSONField test failures
        # TODO: Fix JSONField update with CASE WHEN handling
        'expressions.tests.BasicExpressionsTests.test_update_jsonfield_case_when_key_is_null',
        
    ])

if VERSION >= (5, 2) and VERSION < (5, 2, 4):
    EXCLUDED_TESTS.extend([
        # Composite PK tuple subquery fallback fix landed in Django 5.2.4.
        'composite_pk.test_filter.CompositePKFilterTests.test_explicit_subquery',
        'composite_pk.test_filter.CompositePKFilterTests.test_outer_ref_pk_filter_on_pk_exact',
        'composite_pk.test_filter.CompositePKFilterTests.test_outer_ref_pk_filter_on_pk_comparison',

        # Tuple lookup tests kept excluded for Django <5.2.4.
        'foreign_object.test_tuple_lookups.TupleLookupsTests.test_exact',
        'foreign_object.test_tuple_lookups.TupleLookupsTests.test_gt',
        'foreign_object.test_tuple_lookups.TupleLookupsTests.test_gte',
        'foreign_object.test_tuple_lookups.TupleLookupsTests.test_in',
        'foreign_object.test_tuple_lookups.TupleLookupsTests.test_lt',
        'foreign_object.test_tuple_lookups.TupleLookupsTests.test_lte',
        'foreign_object.test_tuple_lookups.TupleLookupsTests.test_tuple_in_subquery',
        'foreign_object.test_agnostic_order_trimjoin.TestLookupQuery.test_deep_mixed_backward',

        # Multi-column foreign key tuple-lookup tests kept excluded for Django <5.2.4.
        'foreign_object.tests.MultiColumnFKTests.test_double_nested_query',
        'foreign_object.tests.MultiColumnFKTests.test_forward_in_lookup_filters_correctly',
        'foreign_object.tests.MultiColumnFKTests.test_prefetch_foreignobject_forward',
        'foreign_object.tests.MultiColumnFKTests.test_prefetch_foreignobject_hidden_forward',
        'foreign_object.tests.MultiColumnFKTests.test_prefetch_foreignobject_reverse',
        'foreign_object.tests.MultiColumnFKTests.test_prefetch_related_m2m_forward_works',
        'foreign_object.tests.MultiColumnFKTests.test_prefetch_related_m2m_reverse_works',
        'foreign_object.tests.MultiColumnFKTests.test_reverse_query_returns_correct_result',
    ])

REGEX_TESTS = [
    'lookup.tests.LookupTests.test_regex',
    'lookup.tests.LookupTests.test_regex_backreferencing',
    'lookup.tests.LookupTests.test_regex_non_ascii',
    'lookup.tests.LookupTests.test_regex_non_string',
    'lookup.tests.LookupTests.test_regex_null',
    'model_fields.test_jsonfield.TestQuerying.test_key_iregex',
    'model_fields.test_jsonfield.TestQuerying.test_key_regex',
]
