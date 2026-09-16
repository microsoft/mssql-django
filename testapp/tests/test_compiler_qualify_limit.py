# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

"""Regression coverage for qualify queries with sliced results."""

from unittest import skipIf, skipUnless

import django
from django.db.models import F, Window
from django.db.models.functions import RowNumber
from django.db.utils import NotSupportedError
from django.test import TestCase

from testapp.models import Author


def qualify_queryset():
    """A queryset routed through SQLCompiler.get_qualify_sql()."""
    return Author.objects.annotate(
        row_number=Window(expression=RowNumber(), partition_by=[F("name")])
    ).filter(row_number=1)


@skipUnless(django.VERSION >= (4, 2), "Filtering against a window expression requires Django 4.2+")
class QualifyLimitCompilerTests(TestCase):
    """Slicing must survive the qualify path, which bypasses the `TOP %d` insertion."""

    @classmethod
    def setUpTestData(cls):
        Author.objects.bulk_create([Author(name="name%02d" % i) for i in range(6)])

    def test_offset_zero_slice_limits_unordered_query(self):
        rows = list(qualify_queryset()[:2])

        self.assertEqual(len(rows), 2)

    def test_offset_zero_slice_preserves_ordering(self):
        rows = list(qualify_queryset().order_by("name")[:2])

        self.assertEqual([author.name for author in rows], ["name00", "name01"])

    def test_offset_nonzero_slice_limits_unordered_query(self):
        # An unordered qualify query still needs an outer ORDER BY for its
        # OFFSET/FETCH clause to be valid SQL Server syntax. Row identity is
        # undefined without ordering, so only the row count is asserted.
        rows = list(qualify_queryset()[1:3])

        self.assertEqual(len(rows), 2)

    def test_offset_nonzero_slice_still_limits_query(self):
        rows = list(qualify_queryset().order_by("name")[1:3])

        self.assertEqual([author.name for author in rows], ["name01", "name02"])

    def test_unsliced_qualify_query_returns_all_rows(self):
        rows = list(qualify_queryset())

        self.assertEqual(len(rows), 6)


@skipIf(django.VERSION >= (4, 2), "Django 4.2+ supports filtering against a window expression")
class QualifyUnsupportedTests(TestCase):
    """Django 3.2-4.1 reject the queryset outright, so the qualify path is unreachable.

    The compiler branch this module covers is guarded on Django 4.2+ for the
    same reason (see `mssql/compiler.py`).
    """

    def test_window_filter_is_rejected(self):
        with self.assertRaises(NotSupportedError):
            qualify_queryset()
