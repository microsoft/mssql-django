# Running Django's Full Test Suite Against SQL Server

This guide covers running Django's comprehensive test suite (~6000+ tests) against SQL Server using mssql-django. This is what CI runs and takes 30-45 minutes.

## Prerequisites

### 1. SQL Server Database (Required)

```bash
# Start SQL Server 2022 in Docker
docker run -e "ACCEPT_EULA=Y" -e "MSSQL_SA_PASSWORD=MyPassword42" \
  -p 1433:1433 --name sqlserver -d mcr.microsoft.com/mssql/server:2022-latest

# Wait for SQL Server to fully initialize
sleep 25

# Verify it's running
docker logs sqlserver 2>&1 | tail -3
# Should show: "Recovery is complete" and "tempdb database has X data file(s)"
```

### 2. ODBC Driver (Required)

```bash
# Ubuntu 24.04 - Install ODBC Driver 18
curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | sudo gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg
echo "deb [arch=amd64,arm64,armhf signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/ubuntu/24.04/prod noble main" | sudo tee /etc/apt/sources.list.d/mssql-release.list
sudo apt-get update
sudo ACCEPT_EULA=Y apt-get install -y msodbcsql18 unixodbc-dev
```

### 3. System Dependencies (Required for Django test dependencies)

```bash
# libmemcached is needed for pylibmc (Django test dependency)
sudo apt-get install -y libmemcached-dev
```

### 4. Python Dependencies

```bash
# Install mssql-django in development mode
pip install -e .

# Install coverage (used by test.sh)
pip install coverage
```

### 5. Update Settings for ODBC Driver 18

If using ODBC Driver 18 (Ubuntu 24.04), update `testapp/settings.py`:

```python
DATABASES = {
    "default": {
        "ENGINE": "mssql",
        "NAME": "default",
        "USER": "sa",
        "PASSWORD": "MyPassword42",
        "HOST": "localhost",
        "PORT": "1433",
        "OPTIONS": {
            "driver": "ODBC Driver 18 for SQL Server",
            "return_rows_bulk_insert": True,
            "extra_params": "TrustServerCertificate=yes"
        },
    },
    'other': {
        "ENGINE": "mssql",
        "NAME": "other",
        "USER": "sa",
        "PASSWORD": "MyPassword42",
        "HOST": "localhost",
        "PORT": "1433",
        "OPTIONS": {
            "driver": "ODBC Driver 18 for SQL Server",
            "return_rows_bulk_insert": True,
            "extra_params": "TrustServerCertificate=yes"
        },
    },
}
```

### 6. Django Repository

The `test.sh` script expects a pre-existing Django clone in the `django/` directory. It uses `git fetch`, not `git clone`:

```bash
cd /workspaces/mssql-django
git clone --depth=1 https://github.com/django/django.git django
```

## Running the Full Test Suite

### Using test.sh (Recommended)

```bash
cd /workspaces/mssql-django
bash test.sh 2>&1 | tee test_output.log
```

This will:
1. Fetch tags and checkout the Django version matching your installed Django
2. Install Django's test requirements
3. Run ~100+ test modules against SQL Server
4. Generate coverage report

**Expected runtime:** 30-45 minutes

### Manual Execution

```bash
cd /workspaces/mssql-django/django

# Fetch Django tags and checkout matching version
DJANGO_VERSION="$(python -m django --version)"
git fetch --depth=1 origin +refs/tags/*:refs/tags/*
git checkout $DJANGO_VERSION

# Install Django test requirements
pip install -r tests/requirements/py3.txt

# Run tests
coverage run tests/runtests.py --settings=testapp.settings --noinput \
    aggregation \
    annotations \
    basic \
    composite_pk \
    queries \
    # ... add more test modules as needed
```

### Run Specific Test Modules

```bash
cd /workspaces/mssql-django/django
python tests/runtests.py --settings=testapp.settings --noinput composite_pk
```

### Run Specific Test

```bash
cd /workspaces/mssql-django/django
python tests/runtests.py --settings=testapp.settings --noinput \
    composite_pk.test_filter.CompositePKFilterTests.test_explicit_subquery
```

## Understanding Test Output

Test result symbols:
- `.` = passed
- `x` = expected failure (test is known to fail on SQL Server)
- `s` = skipped (test excluded in settings.py)
- `E` = error
- `F` = failure

## Test Exclusions

Tests that are known to fail on SQL Server are excluded in `testapp/settings.py`:

```python
EXCLUDED_TESTS = [
    # Tuple lookups - SQL Server doesn't support (col1, col2) IN syntax
    'composite_pk.test_filter.CompositePKFilterTests.test_explicit_subquery',
    'foreign_object.test_tuple_lookups.TupleLookupsTests.test_exact',
    # ... many more
]
```

## Expected Results

From CI (Django 5.2, Python 3.13):
- **Total tests:** ~6200
- **Passed:** ~5400+
- **Skipped:** ~500+
- **Expected failures:** ~200+
- **Errors:** 0 (if code is working correctly)

## Cleanup

```bash
# Stop SQL Server
docker stop sqlserver && docker rm sqlserver

# Restore settings.py
git checkout testapp/settings.py

# Remove Django clone (optional)
rm -rf django/
```

## Troubleshooting

### "coverage: command not found"

```bash
pip install coverage
```

### "pylibmc build failed"

```bash
sudo apt-get install -y libmemcached-dev
```

### Tests hang or timeout

Check SQL Server is running:
```bash
docker ps | grep sqlserver
docker logs sqlserver | tail -10
```

### "An expression of non-boolean type specified in a context where a condition is expected"

This is the tuple lookup limitation. The test should be in `EXCLUDED_TESTS` in settings.py.

### "A column has been specified more than once in the order by list"

This is the ORDER BY duplicate column issue. If you see this, the deduplication fix in `mssql/compiler.py` may need adjustment.

## CI Configuration

The CI uses `tox` with matrix testing. See:
- `azure-pipelines.yml` - CI configuration
- `tox.ini` - Test matrix (Python versions × Django versions)
- `test.sh` - Test script that CI runs

## Test Modules Covered

The full list of Django test modules run by `test.sh`:

- aggregation, aggregation_regress
- annotations, backends, basic
- bulk_create, composite_pk, constraints
- custom_columns, custom_lookups, custom_managers
- custom_methods, custom_pk, datatypes
- dates, datetimes, db_functions
- defer, delete, expressions
- fixtures, foreign_object, get_or_create
- indexes, inspectdb, introspection
- lookup, m2m_*, many_to_one, many_to_many
- migrations, migrations2, model_fields
- ordering, pagination, prefetch_related
- queries, raw_query, schema
- select_for_update, select_related
- serializers, timezones, transactions
- update, update_only_fields
- ... and more (see test.sh for complete list)
