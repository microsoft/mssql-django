# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from unittest import skipUnless

from django import VERSION
from django.db import NotSupportedError, connections
from django.test import TestCase

if VERSION >= (3, 1):
    from ..models import JSONModel


def _check_jsonfield_supported_sqlite():
    # Info about JSONField support in SQLite: https://code.djangoproject.com/wiki/JSON1Extension
    import sqlite3

    supports_jsonfield = True
    try:
        conn = sqlite3.connect(':memory:')
        cursor = conn.cursor()
        cursor.execute('SELECT JSON(\'{"a": "b"}\')')
    except sqlite3.OperationalError:
        supports_jsonfield = False
    finally:
        return supports_jsonfield


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

    @skipUnless(VERSION >= (3, 1), "JSONField not support in Django versions < 3.1")
    @skipUnless(
        _check_jsonfield_supported_sqlite(),
        "JSONField not support by SQLite on this platform and Python version",
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

    @skipUnless(VERSION >= (3, 1), "JSONField not support in Django versions < 3.1")
    def test_has_key_lookup_with_single_quote_key(self):
        obj = JSONModel.objects.create(value={"o'reilly": 1, "safe": True})

        self.assertSequenceEqual(
            JSONModel.objects.filter(value__has_key="o'reilly"),
            [obj],
        )

    @skipUnless(VERSION >= (3, 1), "JSONField not support in Django versions < 3.1")
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

    @skipUnless(VERSION >= (3, 1), "JSONField not support in Django versions < 3.1")
    def test_key_transform_exact_lookup(self):
        obj = JSONModel.objects.create(value={"message": "alpha-beta", "other": "x"})

        self.assertSequenceEqual(
            JSONModel.objects.filter(value__message="alpha-beta"),
            [obj],
        )

