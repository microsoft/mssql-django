# Django Backend for Microsoft SQL

mssql-django is the official Microsoft‑supported Django database backend for SQL Server, Azure SQL and SQL Database in Microsoft Fabric. 

It provides a reliable, enterprise‑grade database connectivity option for the Django web framework, enabling Python developers to build and run production‑ready applications on Microsoft’s data platform.

This project is the continuation and evolution of earlier community efforts, and it builds on the strong foundation established by django-mssql-backend and its predecessors. mssql-django focuses on long‑term stability, performance, security, and compatibility with both Django and SQL Server.

## Supportability

| Component | Supported Versions |
|---|---|
| Django | 3.2, 4.0, 4.1, 4.2, 5.0, 5.1, 5.2, 6.0, 6.1 |
| Python | 3.8 – 3.14 (Django 6.0 and 6.1 require 3.12+) |
| SQL Server | 2016, 2017, 2019, 2022, 2025 |
| Azure SQL | Database, Managed Instance, SQL Database in Microsoft Fabric |
| ODBC Driver | Microsoft ODBC Driver 17 or 18 for SQL Server |
| FreeTDS | Supported via FreeTDS ODBC driver |

## Quick Start

1. Install mssql-django (pulls in Django, pyodbc, and pytz automatically):

       pip install mssql-django

2. Configure your `settings.py`:

```python
DATABASES = {
    'default': {
        'ENGINE': 'mssql',
        'NAME': 'mydb',
        'USER': 'user@myserver',
        'PASSWORD': 'password',
        'HOST': 'myserver.database.windows.net',
        'PORT': '',
        'OPTIONS': {
            'driver': 'ODBC Driver 18 for SQL Server',
        },
    },
}

# set this to False if you want to turn off pyodbc's connection pooling
DATABASE_CONNECTION_POOLING = False
```

## Configuration Reference

### Standard Django Settings

| Setting | Type | Description |
|---|---|---|
| `ENGINE` | String | Must be `"mssql"` |
| `NAME` | String | Database name. Required. |
| `HOST` | String | SQL Server instance in `"server\instance"` format |
| `PORT` | String | Server instance port. Empty string means default port. |
| `USER` | String | Database user name. If not given, MS Integrated Security is used. |
| `PASSWORD` | String | Database user password |
| `TOKEN` | String | Access token for Azure AD auth (e.g. via `azure.identity`) |
| `AUTOCOMMIT` | Boolean | Set to `False` to disable Django's transaction management |
| `Trusted_Connection` | String | Default `"yes"`. Set to `"no"` if required. |

### TEST Settings

| Setting | Type | Description |
|---|---|---|
| `NAME` | String | Test database name. Default: `"test_" + NAME` |
| `COLLATION` | String | Collation for test database. Default: instance default. |
| `DEPENDENCIES` | String | Creation-order dependencies of the database |
| `MIRROR` | String | Alias of database to mirror during testing |

### OPTIONS

| Option | Type | Default | Description |
|---|---|---|---|
| `python_driver` | String | Unset | **Unreleased (planned 2.0).** Set to `"mssql_python"` to opt in to mssql-python. Omit it to use pyodbc. See [Selecting the database driver](#selecting-the-database-driver). |
| `driver` | String | `"ODBC Driver 18 for SQL Server"` | ODBC driver to use (pyodbc path). Auto-falls back to Driver 17 if 18 is not installed. |
| `isolation_level` | String | `None` | [Transaction isolation level](https://docs.microsoft.com/en-us/sql/t-sql/statements/set-transaction-isolation-level-transact-sql): `READ UNCOMMITTED`, `READ COMMITTED`, `REPEATABLE READ`, `SNAPSHOT`, or `SERIALIZABLE` |
| `dsn` | String | Unset | Named DSN, can be used instead of `HOST` (pyodbc only) |
| `host_is_server` | Boolean | `False` | Set to `True` to use `HOST`/`PORT` directly with FreeTDS instead of a `freetds.conf` dataserver name (pyodbc only). [Details](https://www.freetds.org/userguide/dsnless.html) |
| `unicode_results` | Boolean | `False` | Activate pyodbc's unicode\_results feature |
| `extra_params` | String | Unset | Additional connection parameters (`"param=value;param=value"`), passed unchanged to the selected driver. See [Azure AD Authentication](https://github.com/microsoft/mssql-django/wiki/Azure-AD-Authentication) and the [opt-in restrictions](#selecting-the-database-driver). |
| `collation` | String | `None` | Collation for text field lookups (e.g. `"Chinese_PRC_CI_AS"`) |
| `connection_timeout` | Integer | `0` | Connection timeout in seconds (`0` = disabled) |
| `connection_retries` | Integer | `5` | Number of connection retry attempts |
| `connection_retry_backoff_time` | Integer | `5` | Back-off time in seconds between retries |
| `query_timeout` | Integer | `0` | Query timeout in seconds (`0` = disabled) |
| `setencoding` / `setdecoding` | List | Unset | Forwarded to the selected connection's encoding / decoding methods. See the pyodbc [encoding](https://github.com/mkleehammer/pyodbc/wiki/Connection#setencoding) / [decoding](https://github.com/mkleehammer/pyodbc/wiki/Connection#setdecoding) reference. |
| `return_rows_bulk_insert` | Boolean | `False` | Allow returning rows from bulk insert. Must be `False` if tables have triggers. |

#### Disabling MARS

On the pyodbc path, the backend enables Multiple Active Result Sets (MARS) by
default with Microsoft ODBC drivers on Windows. To connect to an endpoint that does not support MARS,
such as Microsoft Fabric Warehouse, set `MARS_Connection=no` in that database
alias's `extra_params`:

```python
'OPTIONS': {
    'driver': 'ODBC Driver 18 for SQL Server',
    'extra_params': 'Authentication=ActiveDirectoryServicePrincipal;MARS_Connection=no',
},
```

Keep your existing `HOST`, `NAME`, `USER` (client ID), and `PASSWORD` (client
secret) settings. For other authentication methods, keep the corresponding
authentication settings and append `MARS_Connection=no` to `extra_params`.
An explicit MARS setting is honored case-insensitively, without adding a
conflicting default. With MARS disabled, ORM iteration buffers results before
yielding them so nested queries can use the same connection; this can use more
memory for large querysets. This connection setting does not imply full
Warehouse support for Django migrations or other SQL Server features.

### Selecting the database driver

> **Unreleased (planned 2.0).** This option and the installation extra require
> the backend and packaging changes in [#596](https://github.com/microsoft/mssql-django/pull/596)
> and [#599](https://github.com/microsoft/mssql-django/pull/599).
> Published mssql-django 1.x does not support them.

mssql-django continues to install and use **pyodbc** by default. The opt-in
[mssql-python](https://github.com/microsoft/mssql-python) path requires
Python 3.10 or newer and **mssql-python >=1.15.0**. Once mssql-django 2.0 is
released, install the optional driver with:

```bash
python -m pip install "mssql-django[mssql-python]>=2.0"
```

For development, use `python -m pip install ".[mssql-python]"` from a checkout
containing both changes linked above. Installing mssql-python alone does not
add this backend option to mssql-django 1.x.

Select the driver per database alias without changing `ENGINE`:

```python
DATABASES = {
    'default': {
        'ENGINE': 'mssql',
        'NAME': 'mydb',
        'USER': 'user',
        'PASSWORD': 'password',
        'HOST': 'myserver.database.windows.net',
        'PORT': '',
        'OPTIONS': {
            'python_driver': 'mssql_python',
        },
    },
}
```

- **Default and rollback.** Omit `python_driver` or set it to `"pyodbc"` to
  use pyodbc. Different aliases can use different drivers. Keep pyodbc
  installed and retain its runtime prerequisites, even when opting in.
- **Native dependencies.** pip installs the `mssql-python-odbc` companion
  package automatically. By default, the opt-in connection loads its native driver from
  that package, not from a separately installed ODBC Driver 17 or 18.
  Follow mssql-python's [platform prerequisites](https://github.com/microsoft/mssql-python#installation),
  including OpenSSL on macOS and the required Linux libraries.
- **Encryption.** Use a trusted server certificate. For local development
  with a self-signed certificate, `TrustServerCertificate=yes` in `extra_params`
  bypasses certificate validation; do not use it as a production default.
- **Driver-specific options.** On the opt-in path, `driver`, `dsn`,
  `host_is_server`, and `unicode_results` are ignored. Supply `HOST` and
  optionally `PORT`; they become `SERVER=host,port`. Driver 17 fallback is
  available only on the pyodbc path.
- **Connection keywords.** `extra_params` is passed unchanged, not filtered.
  On the opt-in path, explicit keywords in `extra_params` replace matching
  backend-generated keywords rather than creating duplicates.
  mssql-python 1.15.0 rejects `DRIVER`, `DSN`, `SERVERNAME`, and
  `MARS_Connection`. Do not copy those keywords from a pyodbc connection
  string. For endpoints requiring the [MARS opt-out](#disabling-mars), keep
  using pyodbc.
- **Result iteration.** The opt-in path does not enable MARS. The backend
  buffers query results before yielding from `QuerySet.iterator()` so nested
  queries can run on the same connection. Large result sets therefore require
  memory for the complete result, even when a small `chunk_size` is requested.
- **Authentication.** Use only authentication modes supported by
  [mssql-python on your platform](https://github.com/microsoft/mssql-python/wiki/Microsoft-Entra-ID-support).
  The backend forwards `Authentication` through `extra_params` and packs
  `TOKEN` as an access-token connection attribute. When supplying `TOKEN`,
  omit `USER`, `PASSWORD`, and `Authentication`; the application must manage
  token acquisition and renewal.

### Backend-Specific Settings

| Setting | Type | Default | Description |
|---|---|---|---|
| `DATABASE_CONNECTION_POOLING` | Boolean | `True` | Set to `False` before opening connections to disable driver pooling. Applies to pyodbc and the unreleased mssql-python opt-in path. |

## Known Limitations

The following limitations apply when using SQL Server with Django:

- Altering a model field from or to AutoField at migration
- Floating point arithmetic in some annotate functions
- Annotate/exists function in `order_by`
- Righthand power and arithmetic with datetimes
- Timezones and timedeltas not fully supported
- Rename field/model with foreign key constraint
- Database level constraints and filtered indexes
- Date extract function
- Bulk insert with triggers and returning rows

### Version-Specific Notes

| Version | Notes |
|---|---|
| Django 5.1 | Minor limitations with composite primary key inspection via `inspectdb` |
| Django 5.2 | Tuple lookups require Django 5.2.4+ for full support. Some JSONField bulk/CASE WHEN update edge cases. See [test exclusions](https://github.com/microsoft/mssql-django/blob/dev/testapp/settings.py) for details. |
| Django 6.0 | Requires Python 3.12+. All 5.2 limitations apply. Backend handles all 6.0 API changes transparently. |
| Django 6.1 | Requires Python 3.12+. All 6.0 limitations apply. Two 6.1 additions are unavailable: database-level referential actions (`DB_CASCADE`, `DB_SET_NULL`, `DB_SET_DEFAULT`) are not supported because SQL Server disallows multiple cascade paths to the same table, so using one raises a Django system check (`fields.E324`) that points you to the standard Django-level `on_delete`; and bitwise aggregates (`BitAnd`, `BitOr`, `BitXor`) are not implemented by this backend and raise `NotSupportedError`. See [test exclusions](https://github.com/microsoft/mssql-django/blob/dev/testapp/settings.py) for details. |

JSONField lookups have additional limitations — see the [JSONField wiki page](https://github.com/microsoft/mssql-django/wiki/JSONField).

## Helpful Links

| Resource | Link |
|---|---|
| Wiki & Guides | [mssql-django Wiki](https://github.com/microsoft/mssql-django/wiki) |
| Contributing | [Contributing Guide](https://github.com/microsoft/mssql-django/blob/dev/CONTRIBUTING.md) |
| Code of Conduct | [Microsoft Open Source Code of Conduct](https://github.com/microsoft/mssql-django/blob/dev/CODE_OF_CONDUCT.md) |

## Still have questions?

Check the [FAQ](https://github.com/microsoft/mssql-django/wiki/Frequently-Asked-Questions) or [open an issue](https://github.com/microsoft/mssql-django/issues/new) on GitHub.

## Contributing

We welcome contributions and suggestions! See [CONTRIBUTING.md](https://github.com/microsoft/mssql-django/blob/dev/CONTRIBUTING.md) for details.

All contributors are listed on GitHub: [Contributor Insights](https://github.com/microsoft/mssql-django/graphs/contributors)

Most contributions require a Contributor License Agreement (CLA). For details, visit https://cla.opensource.microsoft.com. A CLA bot will guide you when you submit a pull request.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).

## Security

For security reporting instructions please refer to [`SECURITY.md`](https://github.com/microsoft/mssql-django/blob/dev/SECURITY.md).

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft
trademarks or logos is subject to and must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.
