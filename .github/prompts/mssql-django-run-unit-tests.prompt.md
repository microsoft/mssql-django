# Running mssql-django Unit Tests

This guide covers running the mssql-django package's own unit tests (42 tests across 11 test files).

## Prerequisites

### 1. SQL Server Database

You need a running SQL Server instance. Options:

#### Option A: Docker (Recommended for local development)

```bash
# Start SQL Server 2022 in Docker
docker run -e "ACCEPT_EULA=Y" -e "MSSQL_SA_PASSWORD=MyPassword42" \
  -p 1433:1433 --name sqlserver -d mcr.microsoft.com/mssql/server:2022-latest

# Wait for SQL Server to start (about 20 seconds)
sleep 20

# Verify it's running
docker logs sqlserver 2>&1 | tail -5
```

#### Option B: Use existing SQL Server

Update `testapp/settings.py` with your connection details.

### 2. ODBC Driver

Install Microsoft ODBC Driver for SQL Server:

```bash
# Ubuntu 24.04
curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | sudo gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg
echo "deb [arch=amd64,arm64,armhf signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/ubuntu/24.04/prod noble main" | sudo tee /etc/apt/sources.list.d/mssql-release.list
sudo apt-get update
sudo ACCEPT_EULA=Y apt-get install -y msodbcsql18 unixodbc-dev
```

**Note:** Ubuntu 24.04 only has ODBC Driver 18 available. The default `testapp/settings.py` uses Driver 17. You may need to update:

```python
# In testapp/settings.py, change:
"OPTIONS": {"driver": "ODBC Driver 17 for SQL Server", ...}
# To:
"OPTIONS": {"driver": "ODBC Driver 18 for SQL Server", "extra_params": "TrustServerCertificate=yes", ...}
```

### 3. Python Dependencies

```bash
# Install mssql-django in development mode with test dependencies
pip install -e ".[test]"
```

The `[test]` extra installs `unittest-xml-reporting` which provides the `xmlrunner` module required by the test runner.

**Warning:** Do NOT install the old `xmlrunner` package directly - it's incompatible with Python 3.12+.

## Running Tests

### Run all mssql-django tests

```bash
python manage.py test --noinput
```

Expected output: `Ran 42 tests in ~22s - OK`

### Run specific test module

```bash
python manage.py test testapp.tests.test_base -v 2
```

### Run specific test class

```bash
python manage.py test testapp.tests.test_base.TestEncodeValue -v 2
```

### Run specific test method

```bash
python manage.py test testapp.tests.test_base.TestEncodeValue.test_simple_value -v 2
```

## Test Structure

- Tests are in `testapp/tests/`
- Test runner: `testapp/runners.py` (ExcludedTestSuiteRunner)
- Settings: `testapp/settings.py`

## Cleanup

```bash
# Stop and remove SQL Server container
docker stop sqlserver && docker rm sqlserver

# Restore settings.py if modified
git checkout testapp/settings.py
```

## Troubleshooting

### "Can't open lib 'ODBC Driver 17 for SQL Server'"

Install ODBC Driver 18 and update settings.py (see Prerequisites section).

### "Login failed for user 'sa'"

Wait longer for SQL Server to start, or check the password matches settings.py.

### ModuleNotFoundError: No module named 'xmlrunner'

```bash
pip install unittest-xml-reporting
# Or: pip install -e ".[test]"
```
