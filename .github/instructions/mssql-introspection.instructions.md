---
applyTo: "mssql/introspection.py"
---
# Review guidance: introspection.py

`introspection.py` maps SQL Server type codes to Django fields and introspects tables,
columns, and relations. It is one of only two driver-coupled files (with `base.py`) — its
type map depends on driver-exported constants.

## Django-version return shapes

- **Introspection return shapes change across Django minors — write version-aware tests.**
  For example, `get_relations()` / foreign-key introspection gained a wider tuple on newer
  Django. A change here must be tested against each supported Django version's expected
  shape, using `django.VERSION` conditionals in one test rather than assuming a single
  shape. See #556/#558.

## Driver type constants

- **Audit every `Database.SQL_*` type constant the map uses.** Driver builds differ in
  which constants they export (e.g. `SQL_SS_TIME2` is not exported by every driver), so a
  new type mapping should confirm the constant exists on all supported drivers, or provide
  a fallback, rather than referencing it unconditionally.

## Schema qualification

- Introspection should behave correctly for tables in **non-default schemas**, not just
  `dbo`. Test table/column/relation introspection with a schema-qualified `db_table`.
