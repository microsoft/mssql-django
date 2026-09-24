# Changelog

All notable user-facing changes to mssql-django are documented in this file.

## [Unreleased]

### Fixed

- Allowed mssql-python connections to start without the unixODBC driver
  manager when pyodbc is not selected ([#621]).

## [2.0.0] - 2026-09-18

### Added

- Added per-connection opt-in support for mssql-python while retaining pyodbc
  as the default driver ([#596]).

### Changed

- Made mssql-python 1.15.0 or newer a required dependency while retaining
  pyodbc as the default database driver ([#599]).
- Narrowed declared support to CPython 3.10-3.14, Django 5.2-6.1,
  supported mssql-python platforms, and SQL Server 2017-2025 ([#598],
  [#605]).
- Replaced pytz with standard-library zoneinfo and tzdata, stabilizing named
  timezone offsets across the year ([#535]).
- Honored explicit `MARS_Connection` values for Microsoft Fabric Warehouse
  connections and buffered ORM iteration when MARS is disabled ([#600]).
- Allowed future SQL Server releases to use the latest capabilities known to
  the backend instead of failing version validation ([#609]).

### Fixed

- Defaulted an omitted `HOST` to `localhost` for mssql-python connections,
  matching pyodbc's local-server behavior ([#613]).
- Escaped SQL Server `[` wildcards in pattern lookups that use `F()`
  expressions ([#575]).
- Escaped single quotes in `inspectdb --schema` metadata queries ([#583]).

## [1.8.0] - 2026-08-07

### Added

- Added Django 6.1 support ([#553], [#554], [#555], [#556], [#563], [#564]).
- Added Django 6.1 foreign-key introspection support, including the database
  `ON DELETE` rule ([#556]).

### Changed

- Declared database-level referential actions and bitwise aggregates
  unsupported on Django 6.1 so they fail explicitly instead of producing
  incorrect behavior ([#553], [#554]).
- Updated query compilation for Django 6.1's identifier quoting API ([#555],
  [#563]).

## [1.7.4] - 2026-07-24

### Fixed

- Preserved escaped `%%` literals in raw and annotated `GROUP BY` queries
  ([#537]).
- Supported `IntegerChoices` parameters in raw `GROUP BY` queries ([#541]).

## [1.7.3] - 2026-06-22

### Fixed

- Fixed `KeyError` when connecting through a `DatabaseWrapper` subclass
  ([#532]).
- Stopped adding `Trusted_Connection` or SSPI when an explicit
  `Authentication=` mode is configured ([#533]).

## [1.7.2] - 2026-05-22

### Fixed

- Fixed `.explain()` compatibility with Django 4.0 and newer ([#524]).
- Preserved timezone offsets from `DATETIMEOFFSET` values and used
  `SYSDATETIMEOFFSET()` for `Now()` when `USE_TZ=True` ([#484]).

## [1.7.1] - 2026-04-24

### Added

- Added Microsoft Fabric SQL Database support for `EngineEdition=12`
  ([#518]).

### Fixed

- Fixed `AlterField` migrations for descending fields in `Meta.indexes`
  ([#519]).

## [1.7.0] - 2026-03-06

### Added

- Added Django 6.0 and Python 3.14 support ([#488], [#506], [#507], [#508],
  [#509], [#511], [#512]).
- Added SQL Server 2025 support ([#489]).
- Added Django 5.2 composite primary key support for ordering, bulk updates,
  tuple lookups, and JSON expressions ([#462], [#465], [#501], [#504]).

### Changed

- Made Microsoft ODBC Driver 18 the default, with automatic fallback to
  Driver 17 ([#493]).
- Improved quoting for identifiers and aliases containing periods ([#490]).

### Fixed

- Restored `Meta.indexes` after field alterations ([#498]).
- Fixed JSON lookup paths and ordering ([#506], [#509]).
- Fixed batching and `ORDER BY` compatibility ([#507]).
- Fixed bulk inserts and returned rows for fields with `db_default` ([#508],
  [#512]).
- Fixed ordered `StringAgg`, including `OuterRef` handling ([#511]).
- Excluded `testapp` from distributed packages ([#503]).

[Unreleased]: https://github.com/microsoft/mssql-django/compare/2.0.0...dev
[2.0.0]: https://github.com/microsoft/mssql-django/compare/1.8.0...2.0.0
[1.8.0]: https://github.com/microsoft/mssql-django/releases/tag/1.8.0
[1.7.4]: https://github.com/microsoft/mssql-django/releases/tag/1.7.4
[1.7.3]: https://github.com/microsoft/mssql-django/releases/tag/1.7.3
[1.7.2]: https://github.com/microsoft/mssql-django/releases/tag/1.7.2
[1.7.1]: https://github.com/microsoft/mssql-django/releases/tag/1.7.1
[1.7.0]: https://github.com/microsoft/mssql-django/releases/tag/1.7
[#462]: https://github.com/microsoft/mssql-django/pull/462
[#465]: https://github.com/microsoft/mssql-django/pull/465
[#484]: https://github.com/microsoft/mssql-django/pull/484
[#488]: https://github.com/microsoft/mssql-django/pull/488
[#489]: https://github.com/microsoft/mssql-django/pull/489
[#490]: https://github.com/microsoft/mssql-django/pull/490
[#493]: https://github.com/microsoft/mssql-django/pull/493
[#498]: https://github.com/microsoft/mssql-django/pull/498
[#501]: https://github.com/microsoft/mssql-django/pull/501
[#503]: https://github.com/microsoft/mssql-django/pull/503
[#504]: https://github.com/microsoft/mssql-django/pull/504
[#506]: https://github.com/microsoft/mssql-django/pull/506
[#507]: https://github.com/microsoft/mssql-django/pull/507
[#508]: https://github.com/microsoft/mssql-django/pull/508
[#509]: https://github.com/microsoft/mssql-django/pull/509
[#511]: https://github.com/microsoft/mssql-django/pull/511
[#512]: https://github.com/microsoft/mssql-django/pull/512
[#518]: https://github.com/microsoft/mssql-django/pull/518
[#519]: https://github.com/microsoft/mssql-django/pull/519
[#524]: https://github.com/microsoft/mssql-django/pull/524
[#532]: https://github.com/microsoft/mssql-django/pull/532
[#533]: https://github.com/microsoft/mssql-django/pull/533
[#535]: https://github.com/microsoft/mssql-django/pull/535
[#537]: https://github.com/microsoft/mssql-django/pull/537
[#541]: https://github.com/microsoft/mssql-django/pull/541
[#553]: https://github.com/microsoft/mssql-django/pull/553
[#554]: https://github.com/microsoft/mssql-django/pull/554
[#555]: https://github.com/microsoft/mssql-django/pull/555
[#556]: https://github.com/microsoft/mssql-django/pull/556
[#563]: https://github.com/microsoft/mssql-django/pull/563
[#564]: https://github.com/microsoft/mssql-django/pull/564
[#575]: https://github.com/microsoft/mssql-django/pull/575
[#583]: https://github.com/microsoft/mssql-django/pull/583
[#596]: https://github.com/microsoft/mssql-django/pull/596
[#598]: https://github.com/microsoft/mssql-django/pull/598
[#599]: https://github.com/microsoft/mssql-django/pull/599
[#600]: https://github.com/microsoft/mssql-django/pull/600
[#605]: https://github.com/microsoft/mssql-django/pull/605
[#609]: https://github.com/microsoft/mssql-django/pull/609
[#613]: https://github.com/microsoft/mssql-django/pull/613
[#621]: https://github.com/microsoft/mssql-django/pull/621
