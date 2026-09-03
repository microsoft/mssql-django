# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

import hashlib

from django.db import connection
from django.db.models.functions import MD5, SHA1, SHA256, SHA512
from django.test import TestCase

from ..models import Author


class HashFunctionTests(TestCase):
    """Exercise the SQL Server HASHBYTES-based hash functions.

    Django's own hashing tests are excluded on this backend, so these lines in
    mssql/functions.py were previously never run. SQL Server 2019+ (the CI
    baseline) hashes the UTF-8 collated bytes, so the results match hashlib
    over the same UTF-8 input. We assert the exact digests, not just execution.
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

    def test_md5(self):
        expected = hashlib.md5(self.text.encode()).hexdigest()
        self.assertEqual(self._annotated(MD5), expected)

    def test_sha1(self):
        expected = hashlib.sha1(self.text.encode()).hexdigest()
        self.assertEqual(self._annotated(SHA1), expected)

    def test_sha256(self):
        expected = hashlib.sha256(self.text.encode()).hexdigest()
        self.assertEqual(self._annotated(SHA256), expected)

    def test_sha512(self):
        expected = hashlib.sha512(self.text.encode()).hexdigest()
        self.assertEqual(self._annotated(SHA512), expected)
