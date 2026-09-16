# AGENTS.md — mssql-django

Repository context for automated agents and code review. This file holds durable
project facts and review judgment. SQL Server limitations, the `as_microsoft`
extension pattern, and the `EXCLUDED_TESTS` mechanism are documented in
`.github/copilot-instructions.md`; this file does not repeat them.

## What this project is

`mssql-django` is a Django database backend for Microsoft SQL Server. It translates
Django's database abstraction layer into T-SQL. The backend lives entirely under
`mssql/`; `testapp/` is the test project we own.

## Project facts

- **Default branch:** `dev` (not `main`). Open pull requests against `dev`.
- **Version and support policy:** `setup.py` declares the package version and supported
  Python/Django ranges (`install_requires`, classifiers, and `python_requires` when
  present). `azure-pipelines.yml` defines the executed CI matrix, `tox.ini` defines its
  environment dependencies and commands, and `README.md` documents supported database
  platforms. Treat those files as the source of truth rather than duplicating ranges here.
- **Retired-version code:** compatibility branches below the currently declared support
  floor can remain in the distributed package, but those runtimes are no longer tested or
  declared supported. Treat changes that add logic to or depend on those branches as work
  on an untested path; steer the fix onto a supported branch instead of asking contributors
  to maintain retired versions.
- **Tests:** `python manage.py test testapp --noinput` runs the suite we own. A live
  SQL Server is required; connection settings come from environment variables read in
  `testapp/settings.py` (`MSSQL_HOST`, `MSSQL_PASSWORD`, ...). The full upstream Django
  suite is driven by `test.sh` (clones Django, runs `runtests.py` against SQL Server).

## Module map (`mssql/`)

| File | Responsibility |
|------|----------------|
| `schema.py` | Schema editor; `_alter_field` constraint drop/recreate. Largest, most sensitive file. |
| `compiler.py` | SQL query compilation: pagination (OFFSET/FETCH, TOP), ORDER BY handling. |
| `operations.py` | SQL Server operations: quoting, parameter/type handling, datetime adaptation. |
| `functions.py` | Function overrides via the `as_microsoft` pattern; parameter-limit splitting. |
| `base.py` | `DatabaseWrapper`, connection-string construction, cursor handling. |
| `features.py` | Capability flags (`supports_*`) declaring what SQL Server can and can't do. |
| `introspection.py` | Type-code → Django field mapping; table/relation introspection. |
| `creation.py` | Test-database creation and teardown. |
| `client.py` | Database shell command selection (`sqlcmd` / `isql`). |

Direct DBAPI imports and type-code coupling are concentrated in `base.py` and
`introspection.py`. Other modules may legitimately branch on backend capabilities such as
MARS or database-shell selection. Review SQL and ORM behavior independently of the Python
driver, and flag new direct DBAPI coupling outside the adapter boundary unless it is
explicitly justified.

## Commit and PR conventions

- **Title prefix (uppercase, colon):** `FEAT:`, `FIX:`, `CHORE:`, `DOCS:`, `REFACTOR:`,
  `RELEASE:`, `AI:` (AI-initiative changes).
- Reference issues in the body: `Closes #<N>` or `Issue: #<N>`.
- **Every `FIX:` and `FEAT:` ships a regression test in the same PR**, added under
  `testapp/tests/`. For a `FIX:`, the test must fail on `dev` without the change and
  pass with it, asserting the exact trigger combination from the issue. The only
  exception is a change that genuinely cannot be covered from `testapp` (e.g. a path
  exercised only under `USE_TZ=True`, which `testapp` does not run) — state that
  explicitly in the PR body.

## History rules

- No force-push (not even `--force-with-lease`) and no rebase of already-pushed
  branches. Resolve conflicts with `git merge origin/dev`, then a normal push.

## Review judgment (apply across all files)

- **Fix the root cause, not the symptom.** Solve problems at Django's structured
  expression/node level (e.g. override `get_order_by()`, use the `as_microsoft`
  pattern). Do not post-process compiled SQL strings with regex or `str.format`.
- **Fixing one input shape is not fixing the bug class.** If a change narrows a crash
  for one input, check whether the same failure mode survives on adjacent inputs. A
  narrow fix can be worth shipping, but call it out as narrow.
- **Classify a change by its blast radius, not its label.** A PR labeled `FIX:` that
  reroutes a hot-path helper (e.g. every identifier through a new parser) or changes a
  default is an enhancement with backward-compatibility implications. Review it as such.
- **Silent-wrong-results outrank crashes.** A change that can return incorrect rows with
  no error deserves more scrutiny than one that raises — the crash gets reported, the
  wrong `filter()` ships into someone's business logic.
- **Migrating off a deprecated Django API requires a whole-file sweep.** A deprecated
  call often still works (warns on the current Django, breaks on a future major), so CI
  and correctness tests stay green while a missed second call site lingers. Grep the
  full symbol across the file, not just the path the failing test walked.
- **Test-exclusion comments are documentation.** State whether an exclusion is a
  permanent platform limitation or an unimplemented capability — a wrong reason there
  becomes received wisdom for years. `@expectedFailure` / `@skip` documents a known
  failure; it does not mean the bug is fixed.
