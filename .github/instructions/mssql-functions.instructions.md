---
applyTo: "mssql/functions.py"
---
# Review guidance: functions.py

`functions.py` overrides Django SQL functions for SQL Server via the `as_microsoft`
pattern, and handles the parameter-count limit.

## Extension mechanism

- **New function overrides must use the `as_microsoft` pattern** — define a
  `sqlserver_<fn>` and monkey-patch it onto the Django expression class
  (`Round.as_microsoft = sqlserver_round`). Don't special-case functions elsewhere or
  post-process compiled SQL.

## String and collation manipulation (historically fragile)

- **`CONVERT(varchar, ...)` without a length truncates to 30 characters.** Any generated
  `CONVERT`/`CAST` to a character type that carries an identifier (database name, object
  name) must specify an explicit length, or long names are silently cut. See #423.
- **Do not fabricate collations by string substitution.** Deriving a collation with
  `.replace('_CI', '_CS')` (or similar) produces invalid collation names for suffixes like
  `_CI_AI` or `_SC_UT`, and crashes when the collation is `NULL`. Guard for `NULL` and
  don't synthesize collation names from substrings. See #420.
- These live in a small, dense helper (`sqlserver_replace`); a change touching it should
  check the whole helper, since multiple reported bugs share it.

## Pattern lookups

- **Escape `[` and `]` in pattern/`LIKE` operands.** SQL Server treats `[...]` as a
  character class, so an unescaped `[J]` matches the single character `J`, not the literal
  string `[J]` — a silent-wrong-results bug (correct rows, no error). Verify escaping is
  applied when a pattern value can come from an `F()` expression or a column, not only from
  a literal. See #573.

## Parameter limit

- SQL Server caps parameters per statement (~2100). Large `IN` clauses are split via temp
  tables here — preserve that splitting when changing how multi-value lookups are compiled.
