# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from unittest import skipUnless

from django import VERSION
from django.db import NotSupportedError, connections
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

if VERSION >= (3, 1):
    from ..models import JSONModel


def _check_jsonfield_supported_sqlite():
    # Info about JSONField support in SQLite: https://code.djangoproject.com/wiki/JSON1Extension
    import sqlite3

    try:
        conn = sqlite3.connect(':memory:')
        cursor = conn.cursor()
        cursor.execute('SELECT JSON(\'{"a": "b"}\')')
        return True
    except sqlite3.OperationalError:
        return False


class TestJSONField(TestCase):
    databases = ['default']
    # Django 3.0 and below unit test doesn't handle more than 2 databases in DATABASES correctly
    if VERSION >= (3, 1):
        databases.append('sqlite')

    json = {
        'a': 'b',
        'b': 1,
        'c': '1',
        'd': [],
        'e': [1, 2],
        'f': ['a', 'b'],
        'g': [1, 'a'],
        'h': {},
        'i': {'j': 1},
        'j': False,
        'k': True,
        'l': {
            'foo': 'bar',
            'baz': {'a': 'b', 'c': 'd'},
            'bar': ['foo', 'bar'],
            'bax': {'foo': 'bar'},
        },
    }

    @skipUnless(VERSION >= (3, 1), "JSONField not supported in Django versions < 3.1")
    @skipUnless(
        _check_jsonfield_supported_sqlite(),
        "JSONField not supported by SQLite on this platform and Python version",
    )
    def test_keytransformexact_not_overriding(self):
        # Issue https://github.com/microsoft/mssql-django/issues/82
        json_obj = JSONModel(value=self.json)
        json_obj.save()
        self.assertSequenceEqual(
            JSONModel.objects.filter(value__a='b'),
            [json_obj],
        )
        json_obj.save(using='sqlite')
        self.assertSequenceEqual(
            JSONModel.objects.using('sqlite').filter(value__a='b'),
            [json_obj],
        )

    def test_compile_json_path_special_chars(self):
        path = connections['default'].ops.compile_json_path([
            'owner',
            'role name',
            'a"b',
            "o'reilly",
        ])
        self.assertEqual(path, "$.owner.\"role name\".\"a\\\"b\".\"o'reilly\"")

    def test_compile_json_path_negative_index_not_supported(self):
        with self.assertRaises(NotSupportedError):
            connections['default'].ops.compile_json_path(['items', '-1'])

    @skipUnless(VERSION >= (3, 1), "JSONField not supported in Django versions < 3.1")
    def test_has_key_lookup_with_single_quote_key(self):
        obj = JSONModel.objects.create(value={"o'reilly": 1, "safe": True})

        self.assertSequenceEqual(
            JSONModel.objects.filter(value__has_key="o'reilly"),
            [obj],
        )

    @skipUnless(VERSION >= (3, 1), "JSONField not supported in Django versions < 3.1")
    def test_exact_complex_value_lookup(self):
        obj = JSONModel.objects.create(
            value={
                "name": "example",
                "flags": {"active": True, "count": 2},
                "items": [1, "two", {"deep": "value"}],
            }
        )

        self.assertSequenceEqual(
            JSONModel.objects.filter(
                value={
                    "name": "example",
                    "flags": {"active": True, "count": 2},
                    "items": [1, "two", {"deep": "value"}],
                }
            ),
            [obj],
        )

    @skipUnless(VERSION >= (3, 1), "JSONField not supported in Django versions < 3.1")
    def test_key_transform_exact_lookup(self):
        # Basic key-transform lookup sanity check to ensure JSON path
        # extraction remains stable for simple equality filtering.
        obj = JSONModel.objects.create(value={"message": "alpha-beta", "other": "x"})

        self.assertSequenceEqual(
            JSONModel.objects.filter(value__message="alpha-beta"),
            [obj],
        )

    @skipUnless(VERSION >= (3, 1), "JSONField not supported in Django versions < 3.1")
    def test_json_null_key_lookups(self):
        present = JSONModel.objects.create(
            value={"nullable": None, "nested": {"nullable": None}}
        )
        JSONModel.objects.create(value={"nullable": "value", "nested": {}})
        JSONModel.objects.create(value={})

        self.assertSequenceEqual(JSONModel.objects.filter(value__nullable=None), [present])
        self.assertSequenceEqual(JSONModel.objects.filter(value__nullable__iexact=None), [present])
        self.assertSequenceEqual(JSONModel.objects.filter(value__nested__nullable=None), [present])

    @skipUnless(VERSION >= (3, 1), "JSONField not supported in Django versions < 3.1")
    def test_json_null_numeric_key_uses_array_index_semantics(self):
        array_null = JSONModel.objects.create(value=[None])
        nested_array_null = JSONModel.objects.create(value={"items": [None]})
        JSONModel.objects.create(value={"0": None})
        JSONModel.objects.create(value={"items": {"0": None}})
        JSONModel.objects.create(value=["value"])

        self.assertSequenceEqual(JSONModel.objects.filter(value__0=None), [array_null])
        self.assertSequenceEqual(
            JSONModel.objects.filter(value__items__0=None),
            [nested_array_null],
        )

        with self.assertRaises(NotSupportedError):
            list(JSONModel.objects.filter(**{"value__-1": None}))

    @skipUnless(VERSION >= (3, 1), "JSONField not supported in Django versions < 3.1")
    def test_ordering_by_numeric_json_key_ascending(self):
        # Regression coverage for compiler ORDER BY rewrite:
        # JSON key transforms should sort numerically (not lexicographically)
        # when numeric-like payloads are present.
        rows = [
            JSONModel.objects.create(value={"ord": 93, "name": "bar"}),
            JSONModel.objects.create(value={"ord": 22.1, "name": "foo"}),
            JSONModel.objects.create(value={"ord": -1, "name": "baz"}),
            JSONModel.objects.create(value={"ord": 21.931902, "name": "spam"}),
            JSONModel.objects.create(value={"ord": -100291029, "name": "eggs"}),
        ]

        queryset = JSONModel.objects.filter(value__name__isnull=False).order_by("value__ord")
        self.assertSequenceEqual(queryset, [rows[4], rows[2], rows[3], rows[1], rows[0]])

    @skipUnless(VERSION >= (3, 1), "JSONField not supported in Django versions < 3.1")
    def test_ordering_by_numeric_json_key_descending(self):
        # Descending path exercises the same rewrite branch with DESC handling.
        rows = [
            JSONModel.objects.create(value={"ord": 5, "name": "a"}),
            JSONModel.objects.create(value={"ord": -2.5, "name": "b"}),
            JSONModel.objects.create(value={"ord": 11, "name": "c"}),
        ]

        queryset = JSONModel.objects.filter(value__name__isnull=False).order_by("-value__ord")
        self.assertSequenceEqual(queryset, [rows[2], rows[0], rows[1]])

    @skipUnless(VERSION >= (3, 1), "JSONField not supported in Django versions < 3.1")
    def test_ordering_by_non_numeric_json_key_fallback(self):
        # Mixed non-numeric content should still be deterministic and should not
        # fail conversion: backend falls back to text ordering as secondary key.
        rows = [
            JSONModel.objects.create(value={"ord": "b", "name": "first"}),
            JSONModel.objects.create(value={"ord": "a", "name": "second"}),
            JSONModel.objects.create(value={"ord": "c", "name": "third"}),
        ]

        queryset = JSONModel.objects.filter(value__name__isnull=False).order_by("value__ord")
        self.assertSequenceEqual(queryset, [rows[1], rows[0], rows[2]])

    @skipUnless(VERSION >= (3, 1), "JSONField not supported in Django versions < 3.1")
    def test_ordering_by_duplicate_numeric_json_key_deduplicated(self):
        # Regression for fast-path ordering rewrite + dedupe interaction.
        # Duplicate order_by entries must not produce duplicate ORDER BY
        # expressions, otherwise SQL Server can fail with error 169.
        rows = [
            JSONModel.objects.create(value={"ord": 3, "name": "c"}),
            JSONModel.objects.create(value={"ord": 1, "name": "a"}),
            JSONModel.objects.create(value={"ord": 2, "name": "b"}),
        ]

        queryset = JSONModel.objects.filter(value__name__isnull=False).order_by(
            "value__ord", "value__ord"
        )

        # Execute once and inspect SQL text generated by compiler to assert
        # de-duplication happened on transformed ORDER BY fragments.
        with CaptureQueriesContext(connections['default']) as captured:
            result = list(queryset)

        self.assertSequenceEqual(result, [rows[1], rows[2], rows[0]])

        # The numeric conversion expression should appear only once even though
        # the same order clause is requested twice.
        select_sql = captured[-1]["sql"]
        self.assertEqual(select_sql.upper().count("TRY_CONVERT(FLOAT"), 1)
