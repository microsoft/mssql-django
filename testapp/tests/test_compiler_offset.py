# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

"""
Tests for mssql/compiler.py offset handling.

Regression coverage for the OFFSET/slice ordering path. SQL Server needs an
ORDER BY to offset, and the compiler builds it by quoting the table and pk
names. Django 6.1 deprecated SQLCompiler.quote_name_unless_alias() in favour of
SQLCompiler.quote_name(); the deprecated call still works on 6.1 but raises
RemovedInDjango70Warning (and is removed entirely in Django 7.0), so under
Django's warnings-as-errors test run it broke every sliced/offset query.
"""

import warnings

from django.test import TestCase

from testapp.models import Author

try:
    from django.utils.deprecation import RemovedInDjango70Warning
except ImportError:  # older Django versions
    RemovedInDjango70Warning = None


class OffsetOrderingCompilerTests(TestCase):
    """The SQL Server offset ordering path avoids deprecated compiler APIs."""

    def test_sliced_query_does_not_use_deprecated_quote_name(self):
        Author.objects.bulk_create([Author(name="name%02d" % i) for i in range(6)])

        with warnings.catch_warnings():
            # Fail if the offset path emits the 6.1 deprecation (i.e. still calls
            # quote_name_unless_alias). Scoped to that specific category so
            # unrelated warnings don't affect the result.
            if RemovedInDjango70Warning is not None:
                warnings.filterwarnings("error", category=RemovedInDjango70Warning)
            # A sliced queryset compiles to OFFSET ... FETCH, which triggers the
            # SQL Server offset ordering path in the compiler.
            rows = list(Author.objects.order_by("name")[2:5])

        # Correctness: OFFSET 2, next 3 rows.
        self.assertEqual([a.name for a in rows], ["name02", "name03", "name04"])
