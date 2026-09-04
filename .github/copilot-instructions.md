# GitHub Copilot Instructions for mssql-django

## Project Overview

mssql-django is a Django database backend for Microsoft SQL Server. It enables Django applications to use SQL Server as their database by translating Django's database abstraction layer to SQL Server's T-SQL dialect.

## How these instructions are organized

- **This file** is the repository-wide technical reference: SQL Server limitations, coding patterns, common errors, and testing commands.
- **`AGENTS.md`** holds project facts, contribution conventions, and cross-cutting review judgment.
- **`.github/instructions/*.instructions.md`** hold path-specific review checks, loaded automatically only when a matching file changes.

## Repository Structure

```
mssql/                  # Core backend implementation (~4400 lines)
├── schema.py          # Schema modifications, _alter_field (~1585 lines, largest file)
├── base.py            # DatabaseWrapper, connection/cursor handling (~736 lines)
├── compiler.py        # SQL query compilation, pagination, ORDER BY (~697 lines)
├── operations.py      # SQL Server-specific operations (~694 lines)
├── functions.py       # SQL function overrides via as_microsoft pattern (~673 lines)
├── features.py        # SQL Server capability flags
├── introspection.py   # Database introspection
├── creation.py        # Test database creation/destruction
├── client.py          # Command-line client support
└── management/
    └── commands/
        └── install_regex_clr.py  # CLR assembly for REGEXP_LIKE support

testapp/               # Unit tests for the backend
├── tests/             # 214 tests across 15 test files
├── settings.py        # Test configuration with EXCLUDED_TESTS
└── models.py          # Test models

django/                # NOT in repo — cloned at runtime by test.sh for full test suite
```

## Key Technical Context

### SQL Server Limitations

| Limitation | Description | Where handled |
|------------|-------------|---------------|
| No tuple/row comparisons | `WHERE (a, b) IN (...)` not supported | Tests excluded |
| ORDER BY uniqueness | Same column can't appear twice | `compiler.py` deduplication |
| No LIMIT/OFFSET natively | Requires `TOP` or `OFFSET...FETCH` | `compiler.py` emulation |
| No boolean in SELECT | `supports_boolean_expr_in_select_clause = False` | CASE WHEN wrapping |
| No subqueries in GROUP BY | `supports_subqueries_in_group_by = False` | `features.py` flag |
| String concatenation | Uses `+` instead of `\|\|` | `compiler.py` |
| RAND() in ORDER BY | Doesn't randomize | Replaced with `NEWID()` in `compiler.py` |
| Identifier quoting | Uses `[brackets]` not `"quotes"` | `operations.py` `quote_name()` |
| ~2100 parameter limit | SQL Server max parameters per query | Temp table splitting in `functions.py` |

### Critical Files

**mssql/schema.py** (~1585 lines) - The **largest** file. Its `_alter_field()` method (~647 lines) handles cascading constraint drop/recreate logic for schema migrations.

**mssql/compiler.py** (~697 lines) - Handles:
- SQL query generation with SQL Server syntax
- OFFSET/LIMIT pagination emulation  
- ORDER BY deduplication for composite primary keys
- ROW_NUMBER() window function for offset queries

**mssql/functions.py** (~673 lines) - Uses the `as_microsoft` monkey-patching pattern (see Coding Patterns below). Also handles parameter limit splitting via temp tables for large IN clauses.

**mssql/features.py** - Declares what SQL Server supports/doesn't support. Check here first when a test fails to see if it's a known limitation. On a new Django minor, diff Django's `BaseDatabaseFeatures` and override any newly added `supports_*` flags SQL Server can't honor.

**testapp/settings.py** - Contains `EXCLUDED_TESTS` list for Django tests that cannot pass due to SQL Server limitations (not bugs). Includes version-gated blocks (`if VERSION >= (X, Y):`) spanning Django 3.1 through 6.1.

## Coding Patterns

### The `as_microsoft` Pattern
The primary extension mechanism. Functions in `functions.py` define custom SQL generation and are monkey-patched onto Django expression classes:
```python
def sqlserver_round(self, compiler, connection, **extra_context):
    # Custom SQL Server ROUND implementation
    return self.as_sql(compiler, connection, template='ROUND(%(expressions)s, %(extra)s)', **extra_context)

# Monkey-patch onto Django's class
Round.as_microsoft = sqlserver_round
```

This pattern is used for: `Cast`, `Ln`, `Log`, `Mod`, `Round`, `Window`, `Now`, `MD5`, `SHA*`, `OrderBy`, `Lookup`, `Random`, and more.

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
State whether the reason is a permanent platform limitation or an unimplemented capability — the comment is documentation future maintainers rely on.

### Regex Support
`python manage.py install_regex_clr <database>` installs a CLR assembly enabling `REGEXP_LIKE` support for regex-based Django tests.

## Testing

### Run mssql-django unit tests (214 tests)
```bash
python manage.py test testapp.tests
```

### Run specific Django test module
```bash
cd django && python tests/runtests.py --settings=testapp.settings --parallel 1 <module>
```

### Common test modules for validation
- `composite_pk` - Composite primary key support (Django 5.2+)
- `ordering` - ORDER BY functionality
- `queries` - General query tests
- `aggregation` - Aggregate functions
- `schema` - Schema migration tests

## Version Compatibility

- **Django**: 3.2, 4.0, 4.1, 4.2, 5.0, 5.1, 5.2, 6.0, 6.1
- **Python**: 3.8 – 3.14
- **SQL Server**: 2017, 2019, 2022, 2025; Azure SQL DB / Managed Instance
- **ODBC Driver**: 17 or 18 for SQL Server

## Common Issues

### "Column specified more than once in ORDER BY"
SQL Server error 169. Check for duplicate columns in ORDER BY, especially with composite primary keys. Fix in `compiler.py` ORDER BY deduplication logic.

### "Tuple lookups not supported"
Add test to `EXCLUDED_TESTS` - this is a SQL Server limitation, not a bug.

### Tests hanging on database creation
The test database may already exist. Answer "yes" to drop it, or use:
```bash
echo "yes" | python tests/runtests.py --settings=testapp.settings --parallel 1 <module>
```

## Pull Request Guidelines

1. Run affected Django test modules, not just unit tests
2. Check if failures are bugs or SQL Server limitations
3. Add appropriate test exclusions with comments explaining why
4. Keep compiler.py and schema.py changes focused - they are complex and sensitive
5. When adding SQL Server function overrides, use the `as_microsoft` pattern in `functions.py`

## Development Workflow Rules

For contribution conventions (branch, commit prefixes, history rules) and cross-cutting review judgment, see `AGENTS.md`.

### Git Hygiene
- **Only commit files you intentionally changed.** Untracked files (e.g. `result.xml`, build artifacts) may exist in the workspace but not be in `.gitignore` — do not stage or commit them. Review `git diff` and `git status` before committing.
- Do not modify `testapp/settings.py` database connection settings (ODBC driver version, passwords) as part of a PR — those are local dev environment changes.

### Fix Quality
- Follow the root-cause-over-workaround and node-level-fix principles in `AGENTS.md` (Review judgment).
- Use the existing extension points: the `as_microsoft` monkey-patching pattern in `functions.py`, the `_as_microsoft()` dispatch in `compiler.py`, and compiler method overrides.

### Test Discipline
- **All tests must be green before submitting.** If a test fails due to a SQL Server limitation (not a bug you introduced), add it to `EXCLUDED_TESTS` in `testapp/settings.py` with a comment explaining why.
- If a failure is outside the scope of your PR, ask whether to fix it or exclude it — don't leave it failing silently.
- Always run the specific Django test modules affected by your change (e.g. `ordering`, `db_functions`, `composite_pk`) in addition to the unit tests (`python manage.py test testapp.tests`).

## Prompt References

Use prompt files via slash-style workspace paths:

- `/.github/prompts/mssql-django-pr-self-check-gate.prompt.md` - Gated PR self-check workflow and merge gate criteria.
- `/.github/prompts/mssql-django-dev-environment-setup.prompt.md` - Development environment setup.
- `/.github/prompts/mssql-django-run-unit-tests.prompt.md` - mssql-django unit test workflow.
- `/.github/prompts/mssql-django-run-django-test-suite.prompt.md` - Upstream Django suite workflow.
