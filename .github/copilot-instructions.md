# GitHub Copilot Instructions for mssql-django

## Project Overview

mssql-django is a Django database backend for Microsoft SQL Server. It enables Django applications to use SQL Server as their database by translating Django's database abstraction layer to SQL Server's T-SQL dialect.

## Repository Structure

```
mssql/                  # Core backend implementation
├── base.py            # Database connection and cursor handling
├── compiler.py        # SQL query compilation (most complex file)
├── features.py        # SQL Server capability flags
├── operations.py      # SQL Server-specific operations
├── schema.py          # Schema modification operations
├── introspection.py   # Database introspection
├── creation.py        # Test database creation/destruction
├── functions.py       # SQL function overrides
└── client.py          # Command-line client support

testapp/               # Unit tests for the backend
├── tests/             # 61 unit tests
├── settings.py        # Test configuration with EXCLUDED_TESTS
└── models.py          # Test models

django/                # Django source (submodule for full test suite)
└── tests/             # Django's test suite
```

## Key Technical Context

### SQL Server Limitations
When working on this codebase, be aware of these SQL Server limitations that require workarounds:

1. **No tuple/row comparisons**: `WHERE (a, b) IN ((1, 2), (3, 4))` is not supported
2. **ORDER BY uniqueness**: Same column cannot appear twice in ORDER BY clause
3. **No LIMIT/OFFSET natively**: Requires `TOP` or `OFFSET...FETCH` emulation
4. **No boolean type**: Uses `BIT` (0/1) instead
5. **String concatenation**: Uses `+` instead of `||`
6. **RAND() in ORDER BY**: Doesn't randomize; must use `NEWID()`
7. **Identifier quoting**: Uses `[brackets]` instead of `"quotes"`

### Critical Files

**mssql/compiler.py** - The most complex file. Handles:
- SQL query generation with SQL Server syntax
- OFFSET/LIMIT pagination emulation  
- ORDER BY deduplication for composite primary keys
- ROW_NUMBER() window function for offset queries

**testapp/settings.py** - Contains `EXCLUDED_TESTS` list for Django tests that cannot pass due to SQL Server limitations (not bugs).

**mssql/features.py** - Declares what SQL Server supports/doesn't support. Check here first when a test fails to see if it's a known limitation.

## Coding Patterns

### SQL Generation
When modifying SQL generation in compiler.py:
```python
# Always handle both qualified and unqualified column references
col_ref = '[table].[column]'  # qualified
col_ref = '[column]'          # unqualified

# Handle multi-column ORDER BY from composite PKs
# Django 5.2+ can emit: "[t].[a] DESC, [t].[b] DESC" as single item
parts = [p.strip() for p in o_sql.split(',')]
```

### Test Exclusions
When a test fails due to SQL Server limitations (not bugs), add to `EXCLUDED_TESTS` in testapp/settings.py:
```python
EXCLUDED_TESTS = [
    'app.test_module.TestClass.test_method',  # Brief reason
]
```

### Database Connections
```python
# Test database configuration
DATABASES = {
    "default": {
        "ENGINE": "mssql",
        "OPTIONS": {"driver": "ODBC Driver 17 for SQL Server"},
    }
}
```

## Testing

### Run mssql-django unit tests (61 tests)
```bash
python manage.py test testapp.tests
```

### Run specific Django test module
```bash
cd django && python tests/runtests.py --settings=testapp.settings <module>
```

### Common test modules for validation
- `composite_pk` - Composite primary key support (Django 5.2+)
- `ordering` - ORDER BY functionality
- `queries` - General query tests
- `aggregation` - Aggregate functions

## Version Compatibility

- **Django**: 3.2, 4.0, 4.1, 4.2, 5.0, 5.1, 5.2
- **Python**: 3.8+
- **SQL Server**: 2017, 2019, 2022
- **ODBC Driver**: 17 or 18 for SQL Server

## Common Issues

### "Column specified more than once in ORDER BY"
SQL Server error 169. Check for duplicate columns in ORDER BY, especially with composite primary keys. Fix in `compiler.py` ORDER BY deduplication logic.

### "Tuple lookups not supported"
Add test to `EXCLUDED_TESTS` - this is a SQL Server limitation, not a bug.

### Tests hanging on database creation
The test database may already exist. Answer "yes" to drop it, or use:
```bash
echo "yes" | python tests/runtests.py --settings=testapp.settings <module>
```

## Pull Request Guidelines

1. Run affected Django test modules, not just unit tests
2. Check if failures are bugs or SQL Server limitations
3. Add appropriate test exclusions with comments explaining why
4. Keep compiler.py changes focused - it's complex and sensitive
