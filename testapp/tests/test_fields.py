# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from django.test import TestCase

from ..models import UUIDModel, Customer_name, Customer_address


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
