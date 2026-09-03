---
applyTo: "mssql/operations.py"
---
# Review guidance: operations.py

`operations.py` handles SQL Server quoting, parameter and type handling, and datetime
adaptation. It is the highest-traffic bug surface in the backend — review changes here
against the following checks.

## Type dispatch

- **Use `isinstance`, not exact-type identity.** `type(x) == int` (or `is int`)
  silently rejects subclasses such as `IntegerChoices` / `IntEnum`, which reach the
  parameter path through raw `GROUP BY` queries and then fall through to
  `NotImplementedError`. Classify with `isinstance` (or read the enum's value). See #541.
- **Integer range boundaries.** SQL Server `INT` is `-0x80000000 .. 0x7FFFFFFF`. When
  classifying a value as `INT` vs `BIGINT`, verify the exact boundary values are not
  misclassified.

## SQL string manipulation

- **Rewriting placeholders on raw SQL is unsafe by construction.** Any `%s`→`{}`-style
  substitution is blind to string literals, comments, and escape sequences. A change to
  placeholder handling must preserve `%%`-escaped literals; require a test covering
  `GROUP BY` + an escaped `%%` literal + a real parameter in the same query. If the fix
  only widens a regex, note that it is a band-aid over an unparsed-SQL approach. See #476/#537.
- Prefer solving at Django's expression level over post-processing generated SQL.

## Datetime adaptation

- **Read and write paths must stay symmetric.** `convert_datetimefield_value` (read) and
  `adapt_datetimefield_value` (write) must agree on timezone handling. A fix that touches
  only one side creates a read/write asymmetry when a per-database `TIME_ZONE` is set
  (aware values written as UTC but read back in the connection timezone, or vice versa).
  Verify both paths, and test with `USE_TZ=True` plus an explicit non-UTC per-database
  `TIME_ZONE`. See #371.

## Identifier quoting

- Identifiers are quoted with `[brackets]` via `quote_name()`. A change that routes more
  call sites through quoting is a behavior change for every identifier — review its blast
  radius, not just the reported case.
