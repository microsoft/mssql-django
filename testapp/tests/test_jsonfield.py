# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from django.test import TestCase

from ..models import JSONModel


class TestJSONField(TestCase):
    databases = ['default', 'sqlite']
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
