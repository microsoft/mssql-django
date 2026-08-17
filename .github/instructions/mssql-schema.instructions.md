---
applyTo: "mssql/schema.py"
---
# Review guidance: schema.py

`schema.py` is the schema editor and the largest, most sensitive file in the backend. Its
`_alter_field()` drops and recreates dependent constraints (foreign keys, indexes, unique
constraints) around a column change. Keep changes here focused and well-tested.

## `_alter_field` and cascading constraints

- A change to field alteration must **recreate every constraint it drops**, in the right
  order. When reviewing, confirm the set of constraints dropped equals the set recreated —
  a missed recreation leaves the schema subtly wrong after a migration.

## Schema-qualified tables (non-default schema)

- **DDL must work for a `db_table` in a non-default schema, not just `dbo`.** A known open
  case: adding a non-nullable column (with a default) to a model whose `db_table` uses an
  explicit schema fails. Test the matrix explicitly: schema-qualified × nullable/non-nullable
  × with/without default. See #402 (reproduced by more than one reporter).

## Blast radius over label

- **A change that reroutes identifier handling is an enhancement, review it as one.** If a
  PR (even one labeled `FIX:`) routes every identifier through a new parser or changes a
  default of a widely-called helper (e.g. `quote_name()` behavior, `get_table_list()`
  defaults), the blast radius is the whole backend, with backward-compatibility and
  SemVer implications. Assess it by what it changes, not by its stated intent. See #497.

## General

- Prefer Django's schema-editor hooks over hand-built DDL strings where they exist, and
  keep DDL generation consistent with `operations.py` quoting (`[brackets]`).
