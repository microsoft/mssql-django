# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from django.test import TestCase

from ..models import UUIDModel, Customer_name, Customer_address
from django.db import connections


class TestUUIDField(TestCase):
    def test_create(self):
        UUIDModel.objects.create()


class TestOrderBy(TestCase):
    def test_order_by(self):
        # Issue 109
        # Sample: https://github.com/jwaschkau/django-mssql-issue109
        john = Customer_name.objects.create(Customer_name='John')
        Customer_address.objects.create(Customer_address='123 Main St', Customer_name=john)
        names = Customer_name.objects.select_for_update().all()
        addresses = Customer_address.objects.filter(Customer_address='123 Main St', Customer_name__in=names)
        self.assertEqual(len(addresses), 1)

    def test_random_order_by(self):
        # https://code.djangoproject.com/ticket/33531
        Customer_name.objects.bulk_create([
            Customer_name(Customer_name='Jack'),
            Customer_name(Customer_name='Jane'),
            Customer_name(Customer_name='John'),
        ])
        names = []
        # iterate 20 times to make sure we don't get the same result
        for _ in range(20):
            names.append(list(Customer_name.objects.order_by('?')))

        self.assertNotEqual(names.count(names[0]), 20)


class TestSQLVariant(TestCase):
    def test_sql_variant(self):
        connection = connections['default']
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE sqlVariantTest(targetCol sql_variant, colB INT)")
            cursor.execute("INSERT INTO sqlVariantTest values (CAST(46279.1 as decimal(8,2)), 1689)")
            cursor.execute("SELECT targetCol FROM sqlVariantTest")

            rows = cursor.fetchall()
            self.assertEqual(len(rows), 1)
