---
applyTo: "mssql/base.py"
---
# Review guidance: base.py

`base.py` builds the `DatabaseWrapper`, the connection string, and cursor handling. It is
one of only two driver-coupled files (with `introspection.py`) — everything else in
`mssql/` is driver-agnostic. Connection-string changes have broad blast radius; review
them carefully.

## Connection-string defaults

- **Any default the backend injects into the connection string needs a user opt-out.**
  The established pattern (see #533, the `Authentication=` / `Trusted_Connection` fix) is:
  if the user set the keyword explicitly in `extra_params`, skip our injection. Apply the
  same pattern to any newly injected keyword; parse `extra_params` (case-insensitive) to
  detect it.
- **MARS defaults on for Microsoft drivers on Windows.** Honor an explicit
  `MARS_Connection` in `extra_params` without injecting a duplicate, and keep
  `supports_mars` and `can_use_chunked_reads` consistent with that setting. Disabling
  MARS must not apply the FreeTDS `fetchone()` result-discard workaround to Microsoft
  drivers. See #415.
- **`extra_params` is appended verbatim.** A keyword the backend also sets can appear
  twice; dedupe rather than emit duplicates.

## Authentication shape

- `USER` / `PASSWORD` become `UID` / `PWD`, which is **SQL Server authentication**. A
  domain `username`/`password` pair is Windows auth (NTLM), which the Microsoft ODBC
  driver does not support — passing a domain account as `USER` yields a confusing "login
  failed" for a SQL login by that name. Windows auth is process identity via
  `Trusted_Connection=yes` (added only when `USER` is empty). See #413, #428.

## Server-property probes

- Detection that runs `SERVERPROPERTY(...)` needs an **already-open connection**, so it
  cannot gate connection-string construction (which happens before connect). Don't design
  connect-time behavior around a value only available post-connect.

## Testing

- Connection-string builder tests are `SimpleTestCase` (no live DB) — fast to run and the
  right home for connstring assertions.
