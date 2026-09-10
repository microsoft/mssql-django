# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

"""
Regression coverage for mssql/compiler.py's qualify + limit-only slicing path.

A Window-function `.filter()` (e.g. `.annotate(...).filter(row_number=1)`) makes
Django route through SQLCompiler.get_qualify_sql(), which wraps the query in a
subquery. That branch bypasses the plain-SELECT `TOP %d` insertion entirely, so
the only place a limit could still be emitted was the `do_offset` block at the
end of `as_sql()` -- gated solely on `low_mark != 0`. A slice with offset=0
(`qs[:50]`) therefore compiled with no row limit anywhere: `do_limit` was true
but `do_offset` was false, so the qualified query returned every matching row.

These tests build the SQL text via `str(queryset.query)`, which never opens a
real connection -- it only calls SQLCompiler.as_sql(). The one piece that does
require a live connection, SQLCompiler.sql_server_version, is pre-seeded via
DatabaseWrapper's own version cache so the test can run without a database.
"""

from django.db import DEFAULT_DB_ALIAS, connections
from django.db.models import F, Window
from django.db.models.functions import RowNumber
from django.test import SimpleTestCase

from testapp.models import Author


class QualifyLimitCompilerTests(SimpleTestCase):
    """A qualify (window-function-filtered) queryset must keep its row limit.

    No database access happens here: `str(queryset.query)` only builds SQL text
    via SQLCompiler.as_sql() and never opens a cursor, so this runs as a plain
    SimpleTestCase without a `databases` declaration or a live SQL Server.
    """

    def setUp(self):
        connection = connections[DEFAULT_DB_ALIAS]
        # Avoid a live round trip: seed the same caches
        # DatabaseWrapper.sql_server_version/to_azure_sql_db populate from
        # SERVERPROPERTY(), so as_sql() can run against no database at all.
        self._known_versions = connection._known_versions.get(connection.alias)
        self._known_azures = connection._known_azures.get(connection.alias)
        connection._known_versions[connection.alias] = 2019
        connection._known_azures[connection.alias] = False
        self.addCleanup(self._restore_version_cache, connection)

    def _restore_version_cache(self, connection):
        if self._known_versions is None:
            connection._known_versions.pop(connection.alias, None)
        else:
            connection._known_versions[connection.alias] = self._known_versions
        if self._known_azures is None:
            connection._known_azures.pop(connection.alias, None)
        else:
            connection._known_azures[connection.alias] = self._known_azures

    def _qualify_queryset(self):
        return Author.objects.annotate(
            row_number=Window(expression=RowNumber(), partition_by=[F("name")])
        ).filter(row_number=1)

    def test_offset_zero_slice_emits_fetch_clause(self):
        sql = str(self._qualify_queryset()[:50].query)

        self.assertIn(") [qualify]", sql, "sanity check: query took the qualify path")
        self.assertIn("OFFSET 0 ROWS FETCH FIRST 50 ROWS ONLY", sql)

    def test_offset_nonzero_slice_still_emits_fetch_clause(self):
        # This shape already worked before the fix; guard against regressing it.
        sql = str(self._qualify_queryset()[1:50].query)

        self.assertIn(") [qualify]", sql, "sanity check: query took the qualify path")
        self.assertIn("OFFSET 1 ROWS FETCH FIRST 49 ROWS ONLY", sql)

    def test_unsliced_qualify_query_has_no_limit_clause(self):
        # No slicing at all: do_limit is false, so nothing should be emitted.
        sql = str(self._qualify_queryset().query)

        self.assertIn(") [qualify]", sql, "sanity check: query took the qualify path")
        self.assertNotIn("FETCH FIRST", sql)
        self.assertNotIn("OFFSET", sql)
