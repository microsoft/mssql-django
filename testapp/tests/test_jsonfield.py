# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from unittest import skipUnless

from django import VERSION
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
