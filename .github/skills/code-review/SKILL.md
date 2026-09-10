---
name: code-review
description: Review methodology for pull requests to the mssql-django SQL Server backend. Use when reviewing a PR that changes the Django database backend under mssql/ or its tests under testapp/. Adds whole-PR, cross-file, and cross-version review procedure on top of the path-scoped instructions in .github/instructions/.
license: See repository LICENSE.
---

# mssql-django backend review

Guidance for reviewing a change to `mssql-django`, a Django database backend that
translates Django's ORM into SQL Server T-SQL. The path-scoped files in
`.github/instructions/` carry the per-file checks; `AGENTS.md` carries project facts and
review judgment. This skill adds the parts a single-file instruction cannot see: the
**whole-PR procedure**, **cross-file interactions**, and **cross-version safety**.

Reviews are advisory. Prefer a few high-value comments to many low-value ones. Anchor every
significant finding to a concrete query or model operation that behaves differently before
vs. after the change, not to an abstract concern.

## Regression Police: executable review

For behavior-changing pull requests, act as **Regression Police**: turn plausible SQL Server
regressions into disposable, executable proofs before reporting them. Static reasoning may
identify candidates, but it is not evidence when the behavior can be exercised in `testapp`.

1. **Freeze the evidence target.** Record `git rev-parse HEAD` before testing. Publish evidence
   only for that SHA, and stop if the checkout changes during review.
2. **Mine a small suspect set.** Trace changed code through its callers and choose at most three
   high-value candidates. Prioritize silent wrong results, data loss, broken migrations, and
   cross-version failures over style or speculative edge cases.
3. **Write one minimal proof per candidate.** Add a disposable test under `testapp/tests/` using
   existing models and helpers. Exercise the real ORM and SQL Server behavior, avoid mocks for
   database behavior, and assert observable rows, schema, or errors rather than SQL text when
   possible. Do not commit the generated test.
4. **Run the identical test on head and base.** Run only the generated test on the reviewed SHA,
   then copy it unchanged to a detached worktree at `git merge-base HEAD origin/dev` and run the
   same command there. Keep the two runs sequential so they do not collide on shared test
   databases.
5. **Interpret the differential correctly.**

   | Base | Head | Verdict |
   |------|------|---------|
   | Pass | Fail | The pull request introduces a regression. |
   | Fail | Pass | The pull request fixes the exercised behavior. |
   | Fail | Fail | Pre-existing or an incomplete claimed fix; not a new regression. |
   | Pass | Pass | The candidate is disproved. |

   Setup failures, flaky outcomes, different tests, or a stale SHA are inconclusive and must
   not be reported as proof.
6. **Run the Devil's Advocate Rubber Duck.** Assume each candidate is wrong. Challenge the
   test's trigger, attribution, determinism, user impact, nearby input shapes, and use of public
   behavior. Classify it internally as `KEEP`, `HARDEN`, or `DROP`. Rerun both revisions after
   hardening and drop anything that does not survive.
7. **Apply Ponytail.** Shrink every surviving test and recommendation to the smallest case that
   still proves the behavior. Reuse existing code and point to the narrowest shared root-cause
   correction instead of proposing a new abstraction.

Publish only `KEEP` findings on changed lines. Start a newly introduced defect with
`Regression Police: Proven regression` and an incomplete claimed fix with
`Regression Police: Proven incomplete fix`. Include concrete user impact, the minimal test,
the exact command, base/head outcomes, and the smallest credible fix direction. Do not treat
pending or absent Azure DevOps runs as evidence, and do not fetch routine successful logs.

## Review procedure

1. **Restate the change and its blast radius.** What ORM behavior does this alter, and which
   callers are affected? A change to a widely-called helper (identifier quoting, JSON path
   compilation, connection-string construction, `_alter_field`) has repo-wide reach even if
   the diff is small — review it by impact, not by line count or the `FIX:`/`FEAT:` label.
2. **Run the cross-cutting checks below** for the areas the PR touches.
3. **Check the change across the whole support matrix**, not just the author's version.
4. **Check test discipline** (see Testing).
5. **Run Regression Police** for executable behavior candidates.
6. **Calibrate severity** (see Severity) and report.

## Cross-version safety (the most common real defect)

Read the current Django and Python support policy from `setup.py`, the executed matrix from
`azure-pipelines.yml`, and environment definitions from `tox.ini` before reviewing. A
change that is correct on the author's version routinely breaks another.

- **Do not use a Django API newer than the declared minimum without a version guard.**
  Accessing an attribute or symbol introduced in a later Django raises
  `AttributeError`/`ImportError` on older supported versions, *after* the SELECT compiles —
  so it passes the author's local run and fails in the field. Match the version guard already
  used by the nearest related branch.
- **Version-gated code for retired versions is dead-code-adjacent.** The tree still contains
  compatibility branches for versions below the currently declared floor; those versions
  are no longer tested or declared supported, although the compatibility code remains in
  the distributed package. A change that adds logic to or depends on a below-floor branch
  is working on an untested path — flag it as such and steer the fix onto a supported
  branch. Do not ask contributors to *fix* below-floor branches; they exist only as inert
  history.
- **New Django minor → check `features.py`.** New minors add `supports_*` flags defaulting to
  `True`; if not overridden, Django emits SQL SQL Server rejects, sometimes at test-database
  creation (which fails the whole suite before a test runs).
- **Migrating off a deprecated API → sweep every call site.** A deprecated call usually still
  works (warns now, breaks on a future major), so CI stays green even if a second call site
  was missed. Grep the whole symbol across the module, not just the path the failing test hit.
- **Review the SQL/ORM behavior, not the Python driver.** Keep review at the T-SQL / Django
  ORM level. Don't assume a specific DBAPI driver's behavior or bind a fix to one driver's
  quirk. Direct DBAPI imports and type-code handling belong in the adapter boundary
  (`base.py` and `introspection.py`); capability-based behavior such as MARS may legitimately
  appear elsewhere. Flag new direct driver coupling outside that boundary unless the PR
  explicitly justifies it.

## Cross-file interactions (single-file review misses these)

- **JSON key/path handling ↔ `operations.py` path semantics.** A change compiling a JSON key
  path or array index (`OPENJSON`, key transforms) must not bypass `compile_json_path` in
  `operations.py`, which distinguishes array indices from object keys and rejects unsupported
  negative indices with `NotSupportedError`. Comparing a raw key against `OPENJSON`'s string
  `[key]` column loses that distinction (an integer index and an object key of the same text
  collide) and skips the negative-index guard (silently returns no rows instead of raising).
- **Capability flag ↔ actual capability, for every supported config.** A `supports_*` /
  `can_*` flag must be `True` only where the operation truly works. Setting it unconditionally
  while the implementation declines some configuration (Azure SQL Database, an older SQL Server
  build, a permission-limited login) makes `connection.features` advertise a capability that
  isn't there and makes the matching flag test wrong for that config.
- **Capability detection must fail safe.** A feature-detection property that opens a
  connection or queries the server (for example against `master`) is evaluated by Django
  before test-DB creation; if it raises for a restricted login it aborts the whole run.
  Catch the connection failure and return `False` so detection degrades to "unavailable"
  rather than crashing.
- **Connection-string keyword ↔ runtime flag.** Any keyword the backend injects in `base.py`
  needs a user opt-out via `extra_params`, and the corresponding `supports_*` flag must stay
  consistent with the effective connection string (the flag is often derived from the driver
  name, so the two can silently disagree).
- **Bypassing a shared catalog/safety check.** Emitting DDL (for example `DROP INDEX`) from a
  declared/expected name instead of the catalog lookup that previously guarded it can issue
  the statement for an object that isn't present and abort the migration. Preserve the
  catalog/existence check on the shared path rather than short-circuiting it.

## Correctness traps

- **Test the executable query, not just the generated SQL string.** SQL Server rejects some
  text-valid SQL at execution — most notably `OFFSET ... FETCH` without an `ORDER BY`. A
  change that only asserts on the compiled SQL can pass while the query fails when run. Verify
  the query executes, and that pagination/qualify paths still apply the fallback ordering.
- **Do not assume the shape of Django internals.** Iterating `index.fields_orders` without
  unpacking the `(field_name, order)` tuple, or treating every `Q` leaf as a
  `(lookup, value)` pair, breaks on the shapes Django also allows (expression nodes, `F()`
  references, conditional leaves). Handle expression/node forms, not only the tuple form.
- **Type dispatch by `isinstance`, not exact identity.** `type(x) == int` / `is int` excludes
  subclasses such as `IntegerChoices` / `IntEnum`.
- **Prefer node-level fixes over compiled-SQL string surgery.** Regex/`str.format` over raw
  SQL is blind to string literals, comments, and escape sequences; solve at Django's
  expression level.

## Testing

- **Every `FIX:` / `FEAT:` should ship an owned regression test under `testapp/tests/`** in
  the same PR, asserting the exact trigger combination from the issue. Re-enabling upstream
  Django tests by removing an `EXCLUDED_TESTS` entry is welcome but is not, by itself, an owned
  regression test — flag when a fix relies solely on un-excluding upstream coverage.
- **Assert the promised behavior, not a weaker proxy.** A test whose postcondition still
  passes when the behavior is wrong (for example asserting a database merely exists to cover a
  `keepdb` no-op that could have dropped and recreated it) does not regression-test the claim.
  Assert a marker/row/state that only the correct behavior preserves.
- **Respect feature flags in tests.** A test that calls a capability-gated method regardless of
  the flag will fail on the supported configs where the capability is declined. Skip on
  connections that don't advertise it.
- **Restore shared connection state.** Tests that pin a `cached_property` (for example the
  detected SQL Server version) or mutate class dictionaries must restore both the class state
  and `connection.__dict__` entries, or later tests observe stale capability flags.
- **`testapp` runs with `USE_TZ=False`.** The timezone / `datetimeoffset` path is exercised
  only by the upstream Django suite; a timezone fix that can't be covered from `testapp` should
  say so in the PR body.
- **Version-gate tests with `django.VERSION`**, not by skipping, so a fix gated to a new minor
  still runs and asserts on current legs. When the only observable difference is a deprecation
  warning, scope a filter to that `RemovedInDjangoXWarning` and promote it to an error so the
  deprecation itself is the assertion.

## Severity

- **Silent-wrong-results outrank crashes.** A change that can return incorrect rows with no
  error is more serious than one that raises — the crash gets reported, the wrong `filter()`
  ships into business logic. Lead such findings with "silent: returns wrong rows".
- **A swallowed exception is a defect, not cleanup.** Catching an error and silently skipping
  work (losing an index during restoration) or ignoring a failure that leaks resources
  (leaving a data-bearing backup on the server) hides real problems. Surface, handle, or
  document — don't swallow.
- **A missing `NotSupportedError` is a defect:** silently returning nothing where the backend
  previously raised hides an unsupported operation from the user.

## Exclusion hygiene

- `EXCLUDED_TESTS` comments are documentation. State whether an exclusion is a permanent
  platform limitation (a wall) or an unimplemented capability (a gap) — a wrong reason there
  becomes received wisdom. `@expectedFailure` / `@skip` documents a known failure; it does not
  mean the bug is fixed.

## What NOT to flag

- The `as_microsoft` monkey-patch pattern in `functions.py` is the intended, idiomatic
  extension mechanism — don't flag it as a code smell.
- `[bracket]` identifier quoting is correct for SQL Server; don't suggest `"double quotes"`.
- Test exclusions carrying a clear, correct platform-limitation reason are fine as-is.
- Do not ask for a `testapp` test for a change that genuinely can't have one (pure infra, or a
  `USE_TZ`-only path) when the PR body already says so.
