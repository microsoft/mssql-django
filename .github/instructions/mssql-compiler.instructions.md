---
applyTo: "mssql/compiler.py"
---
# Review guidance: compiler.py

`compiler.py` compiles Django queries into T-SQL: pagination emulation and ORDER BY
handling are the sensitive areas. Keep changes here focused and node-level.

## Deprecated Django API migration

- **Sweep every call site in the file.** When a change moves off a deprecated Django API
  (e.g. `quote_name_unless_alias`), grep the full symbol across the module — not just the
  path the failing test exercised. The deprecated call typically still works: it warns on
  the current Django and only breaks on a future major, so CI and correctness tests stay
  green while a missed call site (such as the empty-ordering `ORDER BY pk` fallback)
  lingers. See #555/#563.
- **Make the deprecation itself the assertion.** When the query returns correct rows
  either way and the only observable change is a `RemovedInDjangoXWarning`, scope a
  warnings filter to that specific category and promote it to an error in the regression
  test. That reproduces how the upstream warnings-as-errors suite surfaces the problem and
  gives an otherwise-untestable fix real coverage. See #559.

## Pagination and ORDER BY

- SQL Server has no native `LIMIT/OFFSET`; pagination is emulated with `TOP` and
  `OFFSET ... FETCH` / `ROW_NUMBER()`. Order-dependent changes need coverage on both the
  offset and non-offset paths.
- **ORDER BY must not list the same column twice** (SQL Server error 169), which composite
  primary keys can trigger when Django emits a multi-column ordering as a single item.
  Preserve the deduplication logic and handle both qualified (`[t].[c]`) and unqualified
  (`[c]`) column references.

## General

- **Do not do string surgery on compiled SQL.** Solve at the expression/node level
  (override the relevant compiler method, use the `as_microsoft` pattern) rather than
  regex over generated SQL — the latter is blind to literals, aliases, and escaping.
