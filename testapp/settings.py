# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.
import os
from pathlib import Path

from django import VERSION

BASE_DIR = Path(__file__).resolve().parent.parent

DATABASES = {
    "default": {
        "ENGINE": "mssql",
        "NAME": "default",
        "USER": "sa",
        "PASSWORD": "MyPassword42",
        "HOST": "localhost",
        "PORT": "1433",
        "OPTIONS": {"driver": "ODBC Driver 17 for SQL Server", },
    },
    'other': {
        "ENGINE": "mssql",
        "NAME": "other",
        "USER": "sa",
        "PASSWORD": "MyPassword42",
        "HOST": "localhost",
        "PORT": "1433",
        "OPTIONS": {"driver": "ODBC Driver 17 for SQL Server", },
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

DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

ENABLE_REGEX_TESTS = False
USE_TZ = False

TEST_RUNNER = "testapp.runners.ExcludedTestSuiteRunner"
EXCLUDED_TESTS = [
    'aggregation.tests.AggregateTestCase.test_expression_on_aggregation',
    'aggregation_regress.tests.AggregationTests.test_annotated_conditional_aggregate',
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
    'backends.tests.LastExecutedQueryTest.test_last_executed_query',
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
    'introspection.tests.IntrospectionTests.test_smallautofield',
    'schema.tests.SchemaTests.test_inline_fk',
    'aggregation.tests.AggregateTestCase.test_aggregation_subquery_annotation_exists',
    'aggregation.tests.AggregateTestCase.test_aggregation_subquery_annotation_values_collision',
    'db_functions.datetime.test_extract_trunc.DateFunctionWithTimeZoneTests.test_extract_func_with_timezone',
    'expressions.tests.FTimeDeltaTests.test_date_subquery_subtraction',
    'expressions.tests.FTimeDeltaTests.test_datetime_subquery_subtraction',
    'expressions.tests.FTimeDeltaTests.test_time_subquery_subtraction',
    'migrations.test_operations.OperationTests.test_alter_field_reloads_state_on_fk_with_to_field_target_type_change',
    'schema.tests.SchemaTests.test_alter_smallint_pk_to_smallautofield_pk',
    
    'annotations.tests.NonAggregateAnnotationTestCase.test_combined_expression_annotation_with_aggregation',
    'db_functions.comparison.test_cast.CastTests.test_cast_to_integer',
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
    'schema.tests.SchemaTests.test_add_auto_field',
    'prefetch_related.tests.PrefetchRelatedTests.test_m2m_prefetching_iterator_with_chunks',
    'queries.test_q.QCheckTests.test_basic',
    'queries.test_q.QCheckTests.test_boolean_expression',
    'queries.test_q.QCheckTests.test_expression',
    'constraints.tests.CheckConstraintTests.test_validate',
    'constraints.tests.CheckConstraintTests.test_validate_boolean_expressions',
    'constraints.tests.UniqueConstraintTests.test_model_validation_with_condition',
    'constraints.tests.UniqueConstraintTests.test_validate_condition',
    'constraints.tests.UniqueConstraintTests.test_validate_expression_condition',
    'migrations.test_operations.OperationTests.test_create_model_with_boolean_expression_in_check_constraint',
    'queries.test_qs_combinators.QuerySetSetOperationTests.test_union_in_subquery_related_outerref',
    # These tests pass on SQL Server 2022 or newer
    'model_fields.test_jsonfield.TestQuerying.test_has_key_list',
    'model_fields.test_jsonfield.TestQuerying.test_has_key_null_value',
    'model_fields.test_jsonfield.TestQuerying.test_lookups_with_key_transform',
    'model_fields.test_jsonfield.TestQuerying.test_ordering_grouping_by_count',
    'model_fields.test_jsonfield.TestQuerying.test_has_key_number',
]

REGEX_TESTS = [
    'lookup.tests.LookupTests.test_regex',
    'lookup.tests.LookupTests.test_regex_backreferencing',
    'lookup.tests.LookupTests.test_regex_non_ascii',
    'lookup.tests.LookupTests.test_regex_non_string',
    'lookup.tests.LookupTests.test_regex_null',
    'model_fields.test_jsonfield.TestQuerying.test_key_iregex',
    'model_fields.test_jsonfield.TestQuerying.test_key_regex',
]
