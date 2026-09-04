# mssql-django Gated PR Self-Check

Use this prompt before merging any backend/compiler/schema PR.

## Objective

Run a **merge gate** that prevents regressions from:
- contract ambiguity,
- double-escaping/double-transforms,
- fast-path branches bypassing shared safety logic,
- stale test exclusions,
- insufficient integration proof.

The output must be a clear **PASS / FAIL / BLOCKED** decision with evidence.

## Inputs

- PR branch name
- Target branch (usually `dev`)
- Changed files (`git diff --name-only <target>...HEAD`)
- Related Django test modules for changed areas

## Required Checks (in order)

### 1) Contract change declared
For every behavior-changing helper/symbol, declare one explicit contract:
- who returns raw values,
- who escapes/normalizes,
- where transformation happens,
- and whether call sites must change.

### 2) All call sites audited
Audit all consumers of changed symbols and verify:
- contract applied exactly once,
- no mixed old/new behavior,
- no hidden secondary escaping/transform.

### 3) Fast-path invariants preserved
If a fast-path exists (special-case `continue`/`return`/short-circuit), prove it does not bypass shared safety logic:
- ORDER BY dedupe,
- alias handling,
- parameter ordering,
- escaping rules,
- pagination/order requirements.

If it does bypass shared logic, fix by integrating with shared path, not by adding ad-hoc string post-processing.

### 4) Integration test proof
Provide end-to-end proof for each behavior change:
- Add local regression tests under `testapp/tests/` when applicable.
- Run upstream Django tests that exercise the same path.
- Include at least one regression that targets the **risky edge** (duplicate/equivalent path, alias path, mixed type path, etc.).

### 5) Doc/comments synced
Ensure comments and PR description match current behavior:
- remove stale “still failing” language if test now passes,
- add concise reasons for any remaining exclusions.

### 6) Exclusion hygiene (strict)
For any exclusion touched in `testapp/settings.py`:
- Verify candidate removals under **normal settings** (`testapp.settings`), not only fast profile.
- If using `settings_fast`, treat as exploratory only; confirm final decision with `testapp.settings`.
- Keep only exclusions that are proven failing due to true SQL Server limitation or out-of-scope known issue.

### 7) Version matrix evidence
Run targeted tests plus HOT guard matrix and report:
- PASS lanes,
- FAIL lanes,
- BLOCKED lanes with concrete environment reason.

## Merge Gate (must all be true)

- No unresolved contract ambiguity.
- No double-escaping / double-transform pattern in call sites.
- No fast-path branch bypassing shared invariants without explicit handling.
- Integration regression proof exists for each behavior change.
- Exclusion changes are validated under `testapp.settings`.
- Targeted tests green + HOT guard green (or BLOCKED with environment reason).
- PR description includes root cause, fix scope, and exclusions touched.

## Recommended Evidence Commands

```bash
# Diff scope
git --no-pager diff --name-status origin/dev...HEAD
git --no-pager diff --stat origin/dev...HEAD

# Local backend tests
python manage.py test testapp.tests --verbosity 2

# Targeted local module
python manage.py test testapp.tests.test_jsonfield --verbosity 2

# Upstream targeted test(s)
cd django
PYTHONPATH=/workspaces/mssql-django/django python tests/runtests.py --settings=testapp.settings --parallel 1 <module.or.test>

# HOT matrix / CI guard
# Run or verify the HOT matrix / CI guard workflow for this branch in your CI system
# and record its status (PASS / FAIL / BLOCKED) in the gate summary.
```

## Required Output Format

### Gate Summary
- Overall: PASS / FAIL / BLOCKED
- Scope: changed files + behavior areas

### Checklist Results
- Contract change declared: PASS/FAIL (+ evidence)
- Call-site audit: PASS/FAIL (+ evidence)
- Fast-path invariants: PASS/FAIL (+ evidence)
- Integration test proof: PASS/FAIL (+ tests run)
- Doc/comments sync: PASS/FAIL (+ note)
- Exclusion hygiene: PASS/FAIL (+ list kept/removed)
- Version matrix evidence: PASS/FAIL/BLOCKED (+ lanes)

### Exclusions Decision Table
For each touched exclusion:
- test id
- decision (keep/remove)
- reason
- proof command
- result

### Merge Recommendation
- Merge now / Needs fixes
- If fixes needed, list minimal required changes.

## Notes specific to mssql-django

- `testapp/runners.py` marks excluded tests as expected-failure (`x`) under normal settings. Do not treat `x` alone as proof of backend failure for exclusion decisions.
- For exclusion removal decisions, always re-run candidate tests directly under `testapp.settings` and inspect actual pass/fail outcomes.
- Prefer expression-level/compiler-level fixes over SQL string surgery.
