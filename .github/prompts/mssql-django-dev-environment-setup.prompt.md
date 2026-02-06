# mssql-django Development Environment Setup

This guide covers setting up a development environment for mssql-django, a Django database backend for Microsoft SQL Server.

## Quick Start

```bash
# 1. Install mssql-django in development mode
pip install -e ".[test]"

# 2. Start SQL Server (Docker)
docker run -e "ACCEPT_EULA=Y" -e "MSSQL_SA_PASSWORD=MyPassword42" \
  -p 1433:1433 --name sqlserver -d mcr.microsoft.com/mssql/server:2022-latest

# 3. Run mssql-django tests
python manage.py test --noinput
```

## Test Options

| Test Type | Tests | Time | Guide |
|-----------|-------|------|-------|
| mssql-django unit tests | ~61 | ~22s | [run-mssql-django-tests.prompt.md](run-mssql-django-tests.prompt.md) |
| Django full test suite | ~6200 | ~45min | [run-django-test-suite.prompt.md](run-django-test-suite.prompt.md) |

## Project Structure

```
mssql-django/
├── mssql/                    # Main backend code
│   ├── base.py              # DatabaseWrapper, connection management
│   ├── compiler.py          # Query compiler, SQL generation
│   ├── schema.py            # Schema editor, migrations
│   ├── operations.py        # Database operations, SQL functions
│   ├── features.py          # Backend feature flags
│   ├── introspection.py     # Database introspection
│   └── creation.py          # Test database creation
├── testapp/                  # Test application
│   ├── settings.py          # Django settings, test exclusions
│   ├── runners.py           # Custom test runner
│   ├── models.py            # Test models
│   └── tests/               # mssql-django unit tests
├── django/                   # Django source (cloned for full test suite)
├── test.sh                   # Script to run Django's full test suite
├── tox.ini                   # Test matrix configuration
└── azure-pipelines.yml       # CI configuration
```

## Requirements

### System Requirements

- Python 3.10+ (3.12+ recommended)
- SQL Server 2016+ or Azure SQL Database
- ODBC Driver 17 or 18 for SQL Server

### Python Dependencies

```bash
# Development install with test dependencies
pip install -e ".[test]"

# Core dependencies (installed automatically)
# - Django >= 3.2
# - pyodbc >= 3.0
# - pytz
```

## Configuration

### Database Settings (`testapp/settings.py`)

```python
DATABASES = {
    "default": {
        "ENGINE": "mssql",
        "NAME": "default",           # Database name
        "USER": "sa",                # SQL Server user
        "PASSWORD": "MyPassword42",  # Password
        "HOST": "localhost",         # Server host
        "PORT": "1433",              # Port
        "OPTIONS": {
            "driver": "ODBC Driver 18 for SQL Server",
            "return_rows_bulk_insert": True,
            "extra_params": "TrustServerCertificate=yes"  # For self-signed certs
        },
    },
}
```

### Test Exclusions

Tests known to fail due to SQL Server limitations are excluded in `testapp/settings.py`:

```python
EXCLUDED_TESTS = [
    # Tuple lookups - SQL Server doesn't support (col1, col2) IN syntax
    'foreign_object.test_tuple_lookups.TupleLookupsTests.test_exact',
    # ... see settings.py for full list
]
```

## Common Commands

```bash
# Install in development mode
pip install -e ".[test]"

# Run mssql-django tests only
python manage.py test --noinput

# Run Django's full test suite
bash test.sh

# Run specific Django test module
cd django && python tests/runtests.py --settings=testapp.settings composite_pk

# Check Python syntax
python -m py_compile mssql/compiler.py

# View generated SQL
python -c "
from myapp.models import MyModel
print(MyModel.objects.filter(...).query)
"
```

## SQL Server Limitations

Key limitations that affect the backend implementation:

| Limitation | Description | Workaround |
|------------|-------------|------------|
| No LIMIT clause | Must use TOP or OFFSET-FETCH | compiler.py handles this |
| OFFSET requires ORDER BY | Can't paginate without sorting | compiler.py adds default ORDER BY |
| No tuple IN | `(a, b) IN (...)` not supported | Tests excluded |
| No native boolean | Uses BIT type | Automatic conversion |
| Identifier quoting | Must use `[]` not `""` | operations.py quote_name() |
| ORDER BY duplicates | Same column can't appear twice | compiler.py deduplicates |

## Debugging

### Enable SQL Logging

In `testapp/settings.py`:
```python
DEBUG = True  # Enables SQL logging to logs/django_sql.log
```

### View Generated SQL

```python
from django.db import connection
qs = MyModel.objects.filter(...)
print(qs.query)  # Shows SQL without parameters
print(connection.queries)  # Shows executed queries with timing
```

## CI/CD

- **CI Platform:** Azure DevOps
- **Config:** `azure-pipelines.yml`
- **Test Matrix:** `tox.ini` (Python 3.10-3.13 × Django 4.2-5.2)
- **SQL Server:** Windows hosted agents with SQL Server 2019

## Contributing

1. Create a feature branch
2. Make changes to `mssql/` files
3. Add tests to `testapp/tests/` if needed
4. Run `python manage.py test` to verify
5. For SQL changes, run `bash test.sh` for full validation
6. Submit PR against `dev` branch
