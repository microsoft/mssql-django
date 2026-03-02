# Django 6.0 SQL Server Support Activity Summary

Audience: Senior reviewer / manager, new to Django + SQL Server specifics

Date: 2026-03-02
Branch: bewithgaurav/finish-6.0-support
Latest pushed commit: 6ec87cb

## 1) Executive Summary

This activity focused on turning Django 6.0 exclusions into passing behavior by fixing backend-level SQL Server mismatches at the right extension points (`features`, `operations`, and compiler overrides), then proving each fix with focused test reruns before unexcluding.

The work was intentionally incremental and evidence-driven:
- Reproduce one concrete failure.
- Implement a minimal root-cause fix.
- Re-run failing and adjacent tests.
- Remove only exclusions that were verifiably green.

Outcome:
- Started this continuation with 32 Django 6.0 exclusions in testapp/settings.py.
- Ended with 4 remaining exclusions.
- Net reduction during this activity: 28 exclusions removed.

The implementation stayed within established backend patterns (especially compiler/operation hooks), avoided brittle SQL string surgery, and prioritized behavior alignment with Django semantics over test-specific workarounds.

High-level technical gains:
- JSON negative-index behavior now fails early as an explicit unsupported capability instead of failing later as malformed SQL.
- JSON transform ordering now handles numeric-like values in numeric order where expected.
- `in_bulk()` batching now reflects parameter-budget behavior for scalar ID lists.
- MSSQL bulk insert behavior now matches Django 6.0 default-pruning expectations for `db_default` fields.

## 2) What We Actually Did (Task-Oriented)

### Task A — Fix JSON negative-index handling

Problem before:
- SQL Server does not support negative JSON array indexing in paths.
- Backend was still compiling negative indices into JSON paths, causing runtime SQL errors.

Why this mattered:
- Django 6.0 introduced/relied on explicit feature signaling for JSON negative indexing.
- Without a backend capability guard, queries reached SQL Server and failed with low-level parser errors, which is the wrong failure mode for unsupported backend semantics.

Actions:
- Declared SQL Server behavior explicitly via supports_json_negative_indexing = False.
- Added guard in JSON path compilation to reject negative indices with a clear backend error.

Concrete example:
- Conceptual ORM shape: access JSON path using a negative array index (for example, “last element” semantics).
- Previous backend behavior: compiled a SQL path with `[-1]`, leading to SQL Server error 13607 (“unexpected character '-'”).
- New backend behavior: raises backend-level `NotSupportedError` before SQL emission, with SQL Server identified in the message while preserving Django’s expected wording contract.

Files:
- mssql/features.py
- mssql/operations.py

Result:
- Prevented malformed JSON path SQL errors.
- Enabled Django’s feature-gated behavior (unsupported tests skip instead of hard-fail).
- Reduced blast radius from runtime SQL exceptions to predictable capability handling.

---

### Task B — Fix JSON transform ordering semantics

Problem before:
- Ordering by JSON numeric-like values could behave lexicographically (string order), not numerically.
- Example impact: values like -1 and -100291029 could be ordered incorrectly.

Why this happened:
- JSON extraction commonly produces string-typed output in SQL paths.
- SQL Server string sort compares lexemes, so `'-1'` can sort before/after larger negative strings unexpectedly compared to numeric expectations.

Actions:
- In ORDER BY generation path for JSON KeyTransform, added numeric-aware ordering strategy for actual expressions:
  - primary sort by SQL Server numeric conversion,
  - fallback sort by original expression,
  - guarded against positional ORDER BY ordinals to avoid SQL Server 408 errors.

Concrete example:
- Input values (as JSON strings): `"2"`, `"10"`, `"-1"`, `"-100291029"`.
- Lexicographic ordering can produce sequences that do not match numeric intent.
- New SQL ordering pattern for JSON transform expressions follows a two-key strategy:
  1) `TRY_CONVERT(float, <json-expr>) <dir>`
  2) `<json-expr> <dir>`
- This keeps deterministic ordering for mixed/partially-convertible data while honoring numeric ordering where conversion succeeds.

Files:
- mssql/compiler.py

Result:
- test_ordering_by_transform moved from excluded to passing.
- Adjacent ordering/grouping tests also validated to avoid regressions.
- Composite-PK and dedup-sensitive ORDER BY logic remained intact.

---

### Task C — Fix Django 6.0 in_bulk batching query count mismatch

Problem before:
- Django 6.0 QuerySet.in_bulk() now relies on ops.bulk_batch_size().
- Existing SQL Server bulk_batch_size() logic was insert-oriented (1000-row cap), forcing unnecessary query splitting for scalar ID lists.

Why this mattered:
- The failing expectation was not data correctness but query shape/count correctness.
- Over-splitting scalar-ID lookup batches increased query count and violated test assumptions for a single-batch fetch under parameter budget.

Actions:
- Updated bulk_batch_size() to detect non-model scalar batches and size using parameter budget logic.

Concrete example:
- Scalar `IN` lookup over IDs should be bounded by SQL Server parameter limits, not by multi-row insert row caps.
- Previous behavior reused insert-style row limit and split lookups too aggressively.
- New behavior computes batch capacity for scalar-ID parameterized predicates so larger ID sets stay in one query when safe.

Files:
- mssql/operations.py

Result:
- lookup test expecting a single query is now green.
- Exclusion for test_in_bulk_lots_of_ids removed.
- Behavior now better matches Django’s `in_bulk()` intent in 6.0.

---

### Task D — Align MSSQL SQLInsertCompiler with Django 6.0 db_default behavior

Problem before:
- For bulk inserts with db_default fields (for example created_at), SQL generation included default-only columns redundantly.
- This broke new Django 6.0 expectation that redundant default-only columns are excluded where possible.

Why this mattered:
- Django 6.0 tightened bulk insert SQL shaping around `DatabaseDefault`/`db_default` semantics.
- Backend divergence here affects generated column lists and placeholder/value assembly, and surfaces as assertion mismatches in compiler-oriented tests.

Actions:
- Ported Django 6.0 field-pruning logic into MSSQL SQLInsertCompiler.as_sql().
- Preserved MSSQL return-row behavior while pruning fully defaulted columns.

Concrete example:
- Model has fields: `id`, `created_at` (`db_default`), `name`.
- If every object in a bulk insert uses DB default for `created_at`, Django 6.0 expects the column to be omitted (when legal) rather than redundantly emitted with explicit default markers.
- Updated compiler path now drops fully defaulted columns from insert field list in the matching branch.

Version-compatibility follow-up:
- CI surfaced a Django 5.1 failure (`has_db_default` not present on older field objects).
- Logic was version-gated so Django < 6.0 uses the pre-6.0 path and Django 6.0 uses default-pruning path.
- Additional import hygiene was also converted from try/except to explicit version gate for `ColPairs` (`>=5.2`).

Files:
- mssql/compiler.py

Result:
- bulk_create db_default exclusion test moved from excluded to passing.
- Adjacent db_default primary-key behavior revalidated.
- Cross-version compatibility restored after CI signal.

---

### Task E — Re-validate and remove stale exclusions in batches

Approach:
- For each candidate test or cluster:
  1) run under settings_fast (no exclusions),
  2) if green, remove from exclusions,
  3) rerun under normal settings.

Why batch this way:
- It isolates regressions quickly.
- It separates “test now passes with real backend behavior” from “still blocked by platform limitations.”
- It keeps `testapp/settings.py` as a truthful map of known incompatibilities rather than an accumulation of stale entries.

Large wins in this activity:
- Removed 12-test schema FK/M2M cluster after full validation.
- Removed multiple JSON and migration-related exclusions that now pass.

Examples of exclusion classes removed after proof:
- JSON path/transform lookups that were previously blocked by negative-index/runtime handling.
- Ordering transform cases aligned by numeric-aware JSON ordering.
- `makemigrations`-related checks that no longer fail under current compiler/schema behavior.
- Schema constraint operations (including capital-letter path) validated as stable.

Primary file:
- testapp/settings.py

---

### Task F — Fix post-push CI regressions (Django 4.0 lane)

Problem before:
- After prior push, CI reported three regressions:
  1) `expressions_window.tests.WindowFunctionTests.test_ntile`
     - crash in constant-expression recursion (`NoneType` access)
  2) `model_fields.test_jsonfield.TestQuerying.test_ordering_grouping_by_key_transform`
     - SQL Server error 207 (`Invalid column name 'key'`)
  3) `delete.tests.DeletionTests.test_large_delete_related`
     - query-count mismatch (+1 query) from over-splitting related fetch batches

Root causes and actions:
- Constant-expression recursion:
  - Added defensive handling for `None` and non-expression nodes in `_is_constant_expression()`.
  - Prevents recursive descent from dereferencing absent source expressions in specific window/order trees.
- JSON ordering alias path:
  - Numeric JSON ORDER BY rewrite is now skipped when ORDER BY source is a `Ref` alias path.
  - Avoids generating `TRY_CONVERT(...)` wrappers around alias SQL in contexts where SQL Server resolves aliases differently.
- Delete collector batching:
  - Refined `bulk_batch_size()` to use parameter-budget sizing when batch objects and lookup fields are from different models.
  - This preserves insert constraints for insert/update paths while restoring expected delete-related batch sizing.

Files:
- mssql/compiler.py
- mssql/operations.py

Validation (targeted):
- `expressions_window.tests.WindowFunctionTests.test_ntile` → PASS
- `model_fields.test_jsonfield.TestQuerying.test_ordering_grouping_by_key_transform` → PASS
- `delete.tests.DeletionTests.test_large_delete_related` → PASS
- `lookup.tests.LookupTests.test_in_bulk_lots_of_ids` → PASS (regression guard)

Result:
- CI-reported failures were resolved without broadening scope or reintroducing earlier Django 6.0 fixes.
- Follow-up patch was isolated and pushed as a separate commit for clean reviewability.

## 3) Before vs After (Behavioral)

### JSON negative index

Before:
- Compiled invalid JSON path for SQL Server when negative index used.
- Produced SQL runtime errors.

After:
- Backend explicitly reports unsupported negative indexing and aligns with Django feature gating.
- Unsupported paths no longer fail with malformed SQL.
- Failure mode moved from SQL parser error to deterministic backend capability error.

### JSON ORDER BY transform

Before:
- Numeric JSON values could be ordered as strings.

Example symptom:
- For descending/ascending order, string comparison could place `"10"` relative to `"2"` differently than numeric comparison.

After:
- Numeric-aware ordering used for JSON KeyTransform ORDER BY expressions.
- Ordering test expectations now met.
- Fallback ordering keeps stable behavior when conversion fails.

### in_bulk with large ID lists

Before:
- Unnecessary split into multiple queries due to insert-style batch cap reuse.

Example symptom:
- Query-count assertions expected one query but observed multiple batched queries.

After:
- Scalar ID batching respects parameter limits and avoids avoidable split.
- Query-shape expectations align with Django 6.0 behavior.

### bulk_create with db_default fields

Before:
- db_default columns could be redundantly present in SQL when all values were defaults.

Example symptom:
- Generated insert column set retained fully-defaulted fields where Django 6.0 expects pruning.

After:
- Redundant default-only fields are pruned, matching Django 6.0 SQLInsertCompiler behavior.
- CI-reported Django 5.1 compatibility issue was handled via explicit version-gating.

## 4) Validation Strategy and Evidence Pattern

For each fix we used:
- single-test reproduction,
- minimal patch,
- targeted reruns (failing test + adjacent tests),
- verification under normal settings before exclusion removal.

This ensured we did not rely on speculative fixes and did not broaden risk unnecessarily.

Validation detail:
- Unit-level backend suite (`testapp.tests`) was run to ensure local backend health after major edits.
- Focus modules (ordering/composite PK/migrations/schema/json-specific areas) were re-run when relevant.
- After the CI signal, a compatibility patch was validated locally and pushed as a follow-up rather than folded into unrelated logic.

Representative evidence pattern:
1) Failing test confirms issue.
2) Patch changes only backend layer responsible for SQL generation/capability.
3) Original failing test turns green.
4) Nearby tests remain green.
5) Exclusion removed only after (3) and (4).

## 5) What Is Still Excluded (and Why)

Current Django 6.0 exclusions remaining:
- ordering.tests.OrderingTests.test_order_by_case_when_constant_value
- aggregation.tests.AggregateTestCase.test_distinct_on_stringagg
- expressions.tests.BasicExpressionsTests.test_lookups_subquery
- foreign_object.tests.ForeignObjectModelValidationTests.test_validate_constraints_success_case_single_query

Reason classes:
- SQL Server ORDER BY expression semantics edge case (constant/parameterized CASE ordering).
- SQL Server STRING_AGG DISTINCT syntax limitation in this path.
- REGEXP_LIKE dependency (requires CLR function installation for regex paths).
- Query-count expectation mismatch in foreign-object constraint validation path.

Expanded rationale:
- `test_order_by_case_when_constant_value`: constant/parameterized CASE ordering semantics differ in SQL Server execution/normalization path and require a targeted semantic decision, not a quick toggle.
- `test_distinct_on_stringagg`: SQL Server `STRING_AGG` feature surface differs from backend expectation in this test path; needs a dedicated translation strategy.
- `test_lookups_subquery`: path depends on regex capability (`REGEXP_LIKE`) that is only available when CLR helper is installed; exclusion remains correct for baseline environments.
- `test_validate_constraints_success_case_single_query`: functional behavior is correct, but query-count strictness differs in this foreign-object validation path.

## 6) Risk / Scope Assessment

What we changed safely:
- Backend capability flags,
- compiler-level expression handling,
- operations-level batching/path logic,
- exclusion list entries backed by successful reruns.

What we intentionally did not force:
- Deep SQL Server semantic overrides for known hard limitations,
- broad behavior toggles that increased query counts or caused regressions.

Risk controls used:
- Kept edits localized to backend extension points (no broad refactors across unrelated modules).
- Preserved behavior for older Django versions with explicit version checks.
- Avoided changing local DB credentials/settings and avoided committing helper artifacts.

## 7) Files Touched in This Branch Delta

- mssql/compiler.py
- mssql/features.py
- mssql/functions.py
- mssql/operations.py
- testapp/settings.py

Note:
- Supporting handoff/summary docs were produced during execution, but core product behavior changes are concentrated in the backend files above and exclusion updates.

## 8) Manager-Level Outcome

This PR materially improves Django 6.0 readiness for SQL Server by converting a large set of prior exclusions into verified passing behavior, while keeping unresolved edge cases explicit and isolated. It demonstrates measurable forward progress with controlled risk.

Practical interpretation for review:
- This is not just exclusion churn; it is backend behavior convergence with Django 6.0 expectations.
- Remaining exclusions are now a small, explicit set of real platform/semantic gaps.
- The branch is in a stronger mergeable state because high-churn areas (JSON handling, ordering, batching, insert compilation) were validated incrementally with evidence.

Latest status note:
- A post-push CI follow-up commit (`6ec87cb`) addressed three cross-version regressions while preserving the branch’s Django 6.0 progress and exclusion reductions.
