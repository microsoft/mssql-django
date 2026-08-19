---
applyTo: "testapp/**"
---
# Review guidance: testapp/

`testapp/` is the test project we own — the only place we add regression coverage for
`mssql/*.py`. `testapp/settings.py` holds `EXCLUDED_TESTS`; `testapp/models.py` holds the
test models.

## Regression tests are mandatory

- **Every `FIX:` and `FEAT:` ships a test here, in the same PR.** For a `FIX:`, the test
  must fail on `dev` without the change and pass with it, and must assert the **exact
  trigger combination** from the issue (e.g. GROUP BY + escaped `%%` + a real param), not a
  simplified proxy. A one-dimensional test that doesn't reproduce the real combo isn't
  coverage.
- **Use the real fields in `testapp/models.py`** — don't invent model fields in a test.

## The `USE_TZ` gap

- `testapp` runs with `USE_TZ=False`, so the timezone / `datetimeoffset` path (a
  `DateTimeField` becomes `datetimeoffset` only under `USE_TZ=True`) is exercised **only by
  the upstream Django suite**, never by `testapp`. A timezone fix therefore can't be
  regression-covered from `testapp` alone — say so explicitly in the PR body. That is the
  one accepted "no testapp test" exception.

## Version-aware tests

- **Gate tests by `django.VERSION`, not by skipping.** A fix gated to a new Django minor is
  inert on the legs CI runs today; a version-aware test still runs and asserts on the
  current legs and automatically starts covering the new minor once it's enabled. See #558/#559.
- **When the only observable change is a deprecation warning, make the warning the
  assertion:** scope a filter to the specific `RemovedInDjangoXWarning` and promote it to an
  error in the test. That mirrors Django's own warnings-as-errors suite and gives an
  otherwise-untestable fix real coverage.

## `EXCLUDED_TESTS` hygiene

- Exclusions are version-gated blocks (`if VERSION >= (X, Y):`). Add an exclusion only for a
  genuine SQL Server limitation, not a bug you introduced.
- **The comment is documentation.** State whether the reason is a permanent platform
  limitation or an unimplemented capability — a wrong reason there becomes received wisdom.
- **`@expectedFailure` / `@skip` (or an exclusion) means the bug is NOT fixed** — it
  documents a known failure while keeping CI green. Never read "a test exists" as "fixed".
