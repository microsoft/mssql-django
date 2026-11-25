# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

import hashlib

from django.db import NotSupportedError, connection
from django.db.models import F, Value
from django.db.models.functions import SHA256, SHA512, JSONObject, Lower
from django.test import TestCase

from ..models import Author, ModelWithNullableFieldsOfDifferentTypes


class HashFunctionTests(TestCase):
    """Exercise the SQL Server HASHBYTES-based hash functions.

    Django's own hashing tests are excluded on this backend, so these lines in
    mssql/functions.py were previously never run. SQL Server 2019+ (the CI
    baseline) hashes the UTF-8 collated bytes, so the results match hashlib
    over the same UTF-8 input. We assert the exact digests, not just execution.

    Only the strong SHA-256/512 algorithms are covered here; weaker algorithms
    are intentionally omitted so the test introduces no weak-hash usage that
    security scanners flag.
    """

    text = 'Hello World'

    @classmethod
    def setUpTestData(cls):
        Author.objects.create(name=cls.text)

    def setUp(self):
        if connection.sql_server_version < 2019:
            self.skipTest('HASHBYTES UTF-8 hashing requires SQL Server 2019+')

    def _annotated(self, func):
        return Author.objects.annotate(h=func('name')).values_list('h', flat=True).first()

    def test_sha256(self):
        expected = hashlib.sha256(self.text.encode()).hexdigest()
        self.assertEqual(self._annotated(SHA256), expected)

    def test_sha512(self):
        expected = hashlib.sha512(self.text.encode()).hexdigest()
        self.assertEqual(self._annotated(SHA512), expected)


class JSONObjectTests(TestCase):
    """JSONObject() compiles to JSON_OBJECT(key: value, ...) on SQL Server 2022+."""

    @classmethod
    def setUpTestData(cls):
        cls.obj = ModelWithNullableFieldsOfDifferentTypes.objects.create(int_value=21, name='Ivan')

    def setUp(self):
        if not connection.features.has_json_object_function:
            self.skipTest('JSON_OBJECT() requires SQL Server 2022+ or Azure SQL')

    def _annotated(self, expression):
        return (
            ModelWithNullableFieldsOfDifferentTypes.objects.filter(pk=self.obj.pk)
            .annotate(j=expression)
            .values_list('j', flat=True)
            .get()
        )

    def test_empty(self):
        self.assertEqual(self._annotated(JSONObject()), {})

    def test_fields_expressions_and_null(self):
        self.assertEqual(
            self._annotated(JSONObject(
                name='name',
                lowered=Lower('name'),
                doubled=F('int_value') * 2,
                ratio=Value(1.5),
                missing='date',
            )),
            {'name': 'Ivan', 'lowered': 'ivan', 'doubled': 42, 'ratio': 1.5, 'missing': None},
        )

    def test_nested(self):
        self.assertEqual(
            self._annotated(JSONObject(
                name='name',
                nested=JSONObject(value='int_value'),
                empty=JSONObject(),
            )),
            {'name': 'Ivan', 'nested': {'value': 21}, 'empty': {}},
        )

    def test_key_is_bound_as_parameter(self):
        # Keys are passed as query parameters, never interpolated into the SQL.
        self.assertEqual(self._annotated(JSONObject(**{"it's": 'name'})), {"it's": 'Ivan'})


class JSONObjectNotSupportedTests(TestCase):
    def test_not_supported_before_sql_server_2022(self):
        if connection.features.has_json_object_function:
            self.skipTest('JSON_OBJECT() is supported on this server')
        msg = 'JSONObject() is not supported on this database backend.'
        with self.assertRaisesMessage(NotSupportedError, msg):
            ModelWithNullableFieldsOfDifferentTypes.objects.annotate(j=JSONObject()).first()
