# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from django.test import TestCase
from unittest import skipUnless
from django.db import IntegrityError
from django.utils import timezone
from ..models import UUIDModel, Customer_name, Customer_address
from django import VERSION as DJANGO_VERSION
from testapp.models import Question, Choice
#import Release class only if Django version is 5.2 or higher
if (DJANGO_VERSION >= (5, 2)):
    from testapp.models import Release
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
#testing unique_together fields in Choice model
class ChoiceDeleteTest(TestCase):
    def setUp(self):
        # Create a Question and a related Choice object
        self.question = Question.objects.create(
            question_text="What's up?",
            pub_date=timezone.now()
        )
        self.choice = Choice.objects.create(
            question=self.question,
            choice_text="Yes",
            votes=5
        )
    def test_delete_choice(self):
        # Fetch and delete using unique_together fields
        obj = Choice.objects.get(question=self.question, choice_text="Yes")
        obj.delete()
        self.assertFalse(Choice.objects.filter(question=self.question, choice_text="Yes").exists())   

@skipUnless(DJANGO_VERSION >= (5, 2), "Composite primary keys require Django 5.2+")
class CompositePrimaryKeyTestCase(TestCase):

     def setUp(self):
        # Create an initial Release object with a composite primary key (version, name)
        self.release = Release.objects.create(version=1, name='Alpha')
    # Test that an object with a composite PK can be retrieved correctly
     def test_composite_pk_create_and_retrieve(self):
        obj = Release.objects.get(version=1, name='Alpha')
        self.assertEqual(obj.version, self.release.version)
        self.assertEqual(obj.name, self.release.name)
    # Test that creating a duplicate composite PK raises an IntegrityError
     def test_prevent_duplicate(self):
        with self.assertRaises(IntegrityError):
            Release.objects.create(version=1, name='Alpha')

     def test_allow_different_combinations(self):
        # Test that different combinations of composite PK values are allowed
        Release.objects.create(version=2, name='Alpha')
        Release.objects.create(version=1, name='Beta')
        self.assertEqual(Release.objects.count(), 3)

     def test_composite_pk_deletion(self):
        ## Test that deleting by composite PK removes the correct object
        num_deleted, _ = Release.objects.filter(version=1, name='Alpha').delete()
        self.assertEqual(num_deleted, 1)
 #
        # Confirm it's deleted
        self.assertFalse(Release.objects.filter(version=1, name='Alpha').exists())
     def test_update_composite_pk(self):
        """
        Testing that updating a composite primary key raises an error,
        as Django does not support altering composite PKs.
        """
        # Create an initial object
        obj = Release.objects.create(version=3, name='Gaama')
        # Attempt to update the composite PK fields
        obj.version = 4
        obj.name = 'delta'
        with self.assertRaises(Exception):
            obj.save()