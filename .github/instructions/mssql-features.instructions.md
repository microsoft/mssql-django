---
applyTo: "mssql/features.py"
---
# Review guidance: features.py

`features.py` subclasses Django's `BaseDatabaseFeatures` and overrides the `supports_*`
flags SQL Server can't honor. One correct flag both skips the inapplicable Django tests
(`@skipUnlessDBFeature`) and makes runtime raise a clean `NotSupportedError` instead of
emitting SQL the engine rejects.

## First tool on a new Django minor

- **Diff Django's `BaseDatabaseFeatures` between the old and new minor.** New minors add
  `supports_*` flags that default to `True`; a backend that doesn't override them inherits
  `True`, so Django assumes SQL Server can do the new thing, runs the new tests, and emits
  SQL that fails. Override the new flags that SQL Server can't honor.
- Some new-flag failures surface **at test-database creation**, before any test runs — so
  a missed override can red the entire suite, not just one test. (Example: Django 6.1's
  `supports_on_delete_db_cascade` / `_db_null` / `_db_default` left `True` makes the new
  `delete` models create FK graphs SQL Server rejects with error 1785, multiple cascade
  paths.) Bitwise-aggregate flags left `True` surface as ODBC error 195.

## Correctness rules

- **Overriding a flag the base class doesn't define yet is an inert no-op** (nothing reads
  it on older Django), so a plain `= False` never needs version gating. Version-gate only
  when the *reference itself* would fail on an older Django (e.g. importing a symbol that
  doesn't exist yet). Follow the existing file: version gates guard imports, plain booleans
  are unconditional.
- **Turning a flag off declines the capability — it is not support.** If SQL Server can
  actually do the thing with different SQL, that's real (higher-value) work, separate from
  making the minor not break.

## Comment discipline

- State whether a `False` reflects a **permanent platform limitation** (a wall — e.g. the
  1785 multi-cascade-path restriction) or an **unimplemented capability** (a gap that could
  be emulated). Conflating the two turns "we haven't done it" into "it can't be done", and
  that misclassification survives for years.
