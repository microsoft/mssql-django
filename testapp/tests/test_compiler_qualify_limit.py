# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

"""Regression coverage for qualify queries with sliced results."""

from django.db.models import F, Window
from django.db.models.functions import RowNumber
from django.test import TestCase

from testapp.models import Author


class QualifyLimitCompilerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Author.objects.bulk_create([Author(name="name%02d" % i) for i in range(6)])

    def _qualify_queryset(self):
        return Author.objects.annotate(
            row_number=Window(expression=RowNumber(), partition_by=[F("name")])
        ).filter(row_number=1)

    def test_offset_zero_slice_limits_unordered_query(self):
        rows = list(self._qualify_queryset()[:2])

        self.assertEqual(len(rows), 2)

    def test_offset_zero_slice_preserves_ordering(self):
        rows = list(self._qualify_queryset().order_by("name")[:2])

        self.assertEqual([author.name for author in rows], ["name00", "name01"])

    def test_offset_nonzero_slice_still_limits_query(self):
        rows = list(self._qualify_queryset().order_by("name")[1:3])

        self.assertEqual([author.name for author in rows], ["name01", "name02"])

    def test_unsliced_qualify_query_returns_all_rows(self):
        rows = list(self._qualify_queryset())

        self.assertEqual(len(rows), 6)
