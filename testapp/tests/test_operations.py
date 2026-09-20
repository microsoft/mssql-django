# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

"""
Tests for mssql/operations.py — DatabaseOperations helpers.
"""

from unittest import mock

from django.test import SimpleTestCase

from mssql.operations import DatabaseOperations


def _ops():
    """Return a DatabaseOperations instance with a mocked timezone."""
    return DatabaseOperations(mock.MagicMock(timezone_name="UTC"))


class TestQuoteName(SimpleTestCase):
    """Regression tests for quote_name bracket escaping (issue #607)."""

    def test_simple_name(self):
        """An unadorned name is wrapped in brackets."""
        self.assertEqual(_ops().quote_name("col"), "[col]")

    def test_empty_string(self):
        """Empty string passes through unchanged."""
        self.assertEqual(_ops().quote_name(""), "")

    def test_none(self):
        """None passes through unchanged."""
        self.assertIsNone(_ops().quote_name(None))

    def test_already_quoted(self):
        """An already bracket-quoted name is returned as-is."""
        self.assertEqual(_ops().quote_name("[col]"), "[col]")

    def test_name_with_closing_bracket(self):
        """#607: A name containing ] must escape it as ]]."""
        self.assertEqual(_ops().quote_name("a]b"), "[a]]b]")

    def test_name_with_multiple_closing_brackets(self):
        """All ] characters are doubled."""
        self.assertEqual(_ops().quote_name("a]]b"), "[a]]]]b]")

    def test_name_starting_with_bracket(self):
        """A name that starts with ] but isn't already quoted."""
        self.assertEqual(_ops().quote_name("]col"), "[]]col]")

    def test_name_ending_with_bracket(self):
        """A name that ends with ] but isn't already quoted."""
        self.assertEqual(_ops().quote_name("col]"), "[col]]]")

    def test_already_quoted_with_inner_bracket(self):
        """Already-quoted name with inner ] is returned as-is (quoted once)."""
        self.assertEqual(_ops().quote_name("[a]b]"), "[a]b]")

    def test_dot_in_name(self):
        """Dots are treated as literal characters, not schema separators."""
        self.assertEqual(_ops().quote_name("schema.table"), "[schema.table]")
