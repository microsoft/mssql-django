# Context Handoff (Django 6.0 focused work)

Date: 2026-03-02
Branch: `bewithgaurav/finish-6.0-support`
Repo: `microsoft/mssql-django`
Django checkout used for testing: `/workspaces/mssql-django/django` (branch `6.0.2`, local/untracked in this repo)

## 1) Current branch and commit state

Current HEAD:
- `6ec87cb` — Fix CI regressions in order-by and batch sizing

Recent branch commits (newest first):
- `6ec87cb` Fix CI regressions in order-by and batch sizing
- `6b59fa0` Version-gate ColPairs import for Django 5.2+
- `7960c95` Django 6.0: unexclude passing tests and align insert/json behaviors
- `bb351ca` Unexclude 5 more passing Django 6.0 nested JSON tests
- `15fa288` Unexclude 5 more passing Django 6.0 JSON lookup tests
- `8dfd78a` Unexclude 5 more passing Django 6.0 JSON key lookup tests
- `e753d4b` Unexclude 5 more passing Django 6.0 JSON tests
- `e62e604` Unexclude passing Django 6.0 JSON has_key tests

Remote branch:
- `origin/bewithgaurav/finish-6.0-support` is updated through `6ec87cb` (pushed)

## 2) User preferences and workflow constraints from this session

- Keep scope minimal and practical for Django 6.0 support.
- Avoid hacky regex SQL parsing for ORDER BY constant handling.
- Prefer robust targeted fixes; if a case is invasive/non-comprehensive, keep excluded.
- Keep helper files in workspace but **do not commit** them unless explicitly requested.

## 3) Local helper files restored intentionally (untracked)

These were used for fast iteration and should remain untracked unless explicitly requested:
- `testapp/settings_fast.py` (sets `EXCLUDED_TESTS = []`)
- `scripts/quick_django60_smoke.sh`

Other untracked local files/folders currently present:
- `DJANGO6_MIN_SUPPORT_ACTION_PLAN.md`
- `DJANGO6_PR_ACTIVITY_SUMMARY.md`
- `django/`
- `logs/`
- `result.xml`

## 4) Backend fixes completed in this session

### `mssql/features.py`
- Added:
  - `supports_json_negative_indexing = False`

### `mssql/operations.py`
- Added tuple/list-safe batching branch in `bulk_batch_size()` for scalar ID batches (Django 6.0 `in_bulk()` path):
  - if `objs` are scalar IDs (not model instances), use parameter-budget sizing, not insert row cap.
- Added negative JSON index guard in `compile_json_path()`:
  - raises `NotSupportedError` for negative indices with backend message.
- Added model-mismatch handling in `bulk_batch_size()` for delete collector traversal:
  - when batch objects and field models differ, uses parameter-budget sizing to avoid over-splitting delete-related select batches.

### `mssql/compiler.py`
- ORDER BY improvements for JSON key transforms:
  - numeric-aware ordering for JSON scalar values via `TRY_CONVERT(float, ...)` plus fallback sort,
  - guard to skip rewrite for positional ORDER BY ordinals (`1`, `2`, ...), preventing SQL Server 408.
- SQLInsertCompiler alignment with Django 6.0 db-default pruning behavior:
  - excludes fully defaulted db_default fields from insert columns when safe,
  - fixed `bulk_create` db_default field inclusion mismatch.
- Added CI follow-up hardening:
  - `_is_constant_expression()` now safely handles `None` and non-expression nodes in recursion.
  - JSON transform numeric ORDER BY rewrite is skipped for `Ref` alias paths to avoid invalid alias references in SQL Server.

## 5) Django 6.0 exclusions status at end of session

Current count in `testapp/settings.py` Django 6.0 block:
- **4 tests excluded**

Current excluded list (Django 6.0 block):
- `ordering.tests.OrderingTests.test_order_by_case_when_constant_value`
- `aggregation.tests.AggregateTestCase.test_distinct_on_stringagg`
- `expressions.tests.BasicExpressionsTests.test_lookups_subquery`
- `foreign_object.tests.ForeignObjectModelValidationTests.test_validate_constraints_success_case_single_query`

## 6) Exclusions removed in this session (from Django 6.0 block)

Removed after reproducing and revalidating under normal settings:
- `model_fields.test_jsonfield.TestQuerying.test_deep_negative_lookup_array`
- `model_fields.test_jsonfield.TestQuerying.test_deep_negative_lookup_mixed`
- `model_fields.test_jsonfield.TestQuerying.test_deep_values`
- `model_fields.test_jsonfield.TestQuerying.test_expression_wrapper_key_transform`
- `model_fields.test_jsonfield.TestQuerying.test_join_key_transform_annotation_expression`
- `model_fields.test_jsonfield.TestQuerying.test_shallow_list_lookup`
- `model_fields.test_jsonfield.TestQuerying.test_shallow_list_negative_lookup`
- `model_fields.test_jsonfield.TestQuerying.test_ordering_by_transform`
- `migrations.test_commands.MakeMigrationsTests.test_makemigrations_check_no_changes`
- `migrations.test_commands.MakeMigrationsTests.test_makemigrations_model_rename_interactive`
- `migrations.test_commands.MakeMigrationsTests.test_makemigrations_no_changes`
- `schema.tests.SchemaTests.test_remove_constraints_capital_letters`
- `lookup.tests.LookupTests.test_in_bulk_lots_of_ids`
- `bulk_create.tests.BulkCreateTests.test_db_default_field_excluded`
- `model_options.test_default_pk.TestDefaultPK.test_default_value_of_default_auto_field_setting`
- `introspection.tests.IntrospectionTests.test_get_table_description_types`
- `schema.tests.SchemaTests.test_alter_fk`
- `schema.tests.SchemaTests.test_alter_fk_to_o2o`
- `schema.tests.SchemaTests.test_alter_o2o_to_fk`
- `schema.tests.SchemaTests.test_m2m`
- `schema.tests.SchemaTests.test_m2m_create`
- `schema.tests.SchemaTests.test_m2m_create_custom`
- `schema.tests.SchemaTests.test_m2m_create_inherited`
- `schema.tests.SchemaTests.test_m2m_create_through`
- `schema.tests.SchemaTests.test_m2m_create_through_custom`
- `schema.tests.SchemaTests.test_m2m_create_through_inherited`
- `schema.tests.SchemaTests.test_m2m_custom`
- `schema.tests.SchemaTests.test_m2m_inherited`

## 7) Remaining blocker notes

- `ordering.tests.OrderingTests.test_order_by_case_when_constant_value`
  - still fails with SQL Server error 1008 (ORDER BY expression/position semantics with parameterized constant CASE path).
- `aggregation.tests.AggregateTestCase.test_distinct_on_stringagg`
  - still fails with SQL Server syntax error near delimiter in DISTINCT STRING_AGG shape.
- `expressions.tests.BasicExpressionsTests.test_lookups_subquery`
  - fails due to missing `dbo.REGEXP_LIKE` function in DB (CLR regex function not installed).
- `foreign_object.tests.ForeignObjectModelValidationTests.test_validate_constraints_success_case_single_query`
  - still query-count mismatch (2 expected 1); attempted feature-flag experiment worsened to 3 and was reverted.

## 8) Key test commands run in this session

Common env:
- `PYTHONPATH=/workspaces/mssql-django`
- Python: `/usr/local/bin/python`
- Django runner: `/workspaces/mssql-django/django/tests/runtests.py`

Representative commands:
- Focused failing/probe runs under fast settings:
  - `.../runtests.py --settings=testapp.settings_fast <test> --verbosity 2`
- Normal settings verification before unexclude:
  - `.../runtests.py --settings=testapp.settings <tests...> --verbosity 1`
- Local backend suite sanity:
  - `echo yes | /usr/local/bin/python manage.py test testapp.tests --verbosity 0`

## 9) Verified test status highlights

- Full local suite:
  - `manage.py test testapp.tests` → `Ran 64 tests ... OK`
- Targeted changed areas validated:
  - JSON negative indexing / JSON ordering tests passed or skipped as expected.
  - in_bulk large-ID query-count test passed after batch-size fix.
  - bulk_create db_default tests passed after SQLInsertCompiler alignment.
  - 12-test schema FK/M2M cluster passed and was unexcluded.
  - CI-reported regressions revalidated locally and passing:
    - `expressions_window.tests.WindowFunctionTests.test_ntile`
    - `model_fields.test_jsonfield.TestQuerying.test_ordering_grouping_by_key_transform`
    - `delete.tests.DeletionTests.test_large_delete_related`
    - `lookup.tests.LookupTests.test_in_bulk_lots_of_ids`

## 10) What to do first in next session

1. Decide whether to stop at current 4 exclusions or attempt one deeper fix:
   - likely only `foreign_object...single_query` is potentially fixable without DB feature install.
2. If needed, separate follow-up tasks:
   - regex CLR install path for `test_lookups_subquery` (`install_regex_clr` command),
   - deeper constant CASE ORDER BY handling for SQL Server 1008,
   - revisit DISTINCT STRING_AGG handling strategy.

## 11) Guardrails for continuation

- Keep helper files untracked unless explicitly asked.
- Keep fixes targeted and evidence-backed.
- Avoid broad global feature flips unless validated across affected modules.
- Preserve current 4 exclusions unless each is fixed with passing targeted tests.

## 12) Model note

If asked: model in use is GPT-5.3-Codex.
