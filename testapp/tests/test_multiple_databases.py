# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from unittest import skipUnless

from django import VERSION
from django.db import OperationalError
from django.db.backends.sqlite3.operations import DatabaseOperations
from django.test import TestCase, skipUnlessDBFeature

from ..models import BinaryData, Pizza, Topping, TestCheckConstraintWithUnicode


@skipUnless(
    VERSION >= (3, 1),
    "Django 3.0 and below doesn't support different databases in unit testing",
)
class TestMultpleDatabases(TestCase):
    databases = ['default', 'sqlite']

    def test_in_split_parameter_list_as_sql(self):
        # Issue: https://github.com/microsoft/mssql-django/issues/92

        # Mimic databases that have a limit on parameters (e.g. Oracle DB)
        old_max_in_list_size = DatabaseOperations.max_in_list_size
        DatabaseOperations.max_in_list_size = lambda self: 100

        iterations = 3000
        for _ in range(iterations):
            Pizza.objects.create()
            Topping.objects.create()
            Pizza.objects.using('sqlite').create()
            Topping.objects.using('sqlite').create()
        prefetch_result = Pizza.objects.prefetch_related('toppings')
        self.assertEqual(len(prefetch_result), iterations)

        prefetch_result_sqlite = Pizza.objects.using('sqlite').prefetch_related('toppings')
        self.assertEqual(len(prefetch_result_sqlite), iterations)

        DatabaseOperations.max_in_list_size = old_max_in_list_size

    def test_binaryfield_init(self):
        binary_data = b'\x00\x46\xFE'
        binary = BinaryData(binary=binary_data)
        binary.save()
        binary.save(using='sqlite')

        try:
            binary.full_clean()
        except ValidationError:
            self.fail()

        b1 = BinaryData.objects.filter(binary=binary_data)
        self.assertSequenceEqual(
            b1,
            [binary],
        )
        b2 = BinaryData.objects.using('sqlite').filter(binary=binary_data)
        self.assertSequenceEqual(
            b2,
            [binary],
        )

    @skipUnlessDBFeature('supports_table_check_constraints')
    @skipUnless(
        VERSION >= (3, 2),
        "Django 3.1 and below has errors from running migrations for this test",
    )
    def test_checkconstraint_get_check_sql(self):
        TestCheckConstraintWithUnicode.objects.create(name='abc')
        try:
            TestCheckConstraintWithUnicode.objects.using('sqlite').create(name='abc')
        except OperationalError:
            self.fail()

    def test_queryset_bulk_update(self):
        objs = [
            BinaryData.objects.create(binary=b'\x00') for _ in range(5)
        ]
        for obj in objs:
            obj.binary = None
        BinaryData.objects.bulk_update(objs, ["binary"])
        self.assertCountEqual(BinaryData.objects.filter(binary__isnull=True), objs)

        objs = [
            BinaryData.objects.using('sqlite').create(binary=b'\x00') for _ in range(5)
        ]
        for obj in objs:
            obj.binary = None
        BinaryData.objects.using('sqlite').bulk_update(objs, ["binary"])
        self.assertCountEqual(BinaryData.objects.using('sqlite').filter(binary__isnull=True), objs)
