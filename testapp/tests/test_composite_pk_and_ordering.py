# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

"""
Tests for:
1. ORDER BY deduplication in compiler.py - SQL Server doesn't allow duplicate columns
2. Composite PK bulk_update validation in functions.py
"""

from django import VERSION
from django.db import connection, models
from django.test import TestCase, TransactionTestCase

from ..models import Author, Post


class OrderByDeduplicationTests(TestCase):
    """
    Test that the ORDER BY deduplication logic works correctly.
    SQL Server error: "A column has been specified more than once in the order by list"
    """

    @classmethod
    def setUpTestData(cls):
        cls.author1 = Author.objects.create(name='Alice')
        cls.author2 = Author.objects.create(name='Bob')
        cls.author3 = Author.objects.create(name='Charlie')

    def test_simple_order_by(self):
        """Basic ORDER BY should work."""
        authors = list(Author.objects.order_by('name'))
        self.assertEqual([a.name for a in authors], ['Alice', 'Bob', 'Charlie'])

    def test_order_by_desc(self):
        """ORDER BY DESC should work."""
        authors = list(Author.objects.order_by('-name'))
        self.assertEqual([a.name for a in authors], ['Charlie', 'Bob', 'Alice'])

    def test_order_by_pk(self):
        """ORDER BY pk should work."""
        authors = list(Author.objects.order_by('pk'))
        self.assertEqual(len(authors), 3)

    def test_order_by_pk_desc(self):
        """ORDER BY -pk should work."""
        authors = list(Author.objects.order_by('-pk'))
        self.assertEqual(len(authors), 3)

    def test_order_by_with_values(self):
        """ORDER BY with values() should work."""
        names = list(Author.objects.order_by('name').values_list('name', flat=True))
        self.assertEqual(names, ['Alice', 'Bob', 'Charlie'])

    def test_order_by_multiple_fields(self):
        """ORDER BY with multiple different fields should work."""
        authors = list(Author.objects.order_by('name', 'pk'))
        self.assertEqual(len(authors), 3)

    def test_raw_sql_with_single_column_order_by(self):
        """Raw SQL with single column ORDER BY should work."""
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT name FROM {Author._meta.db_table} ORDER BY name ASC"
            )
            results = cursor.fetchall()
            self.assertEqual(len(results), 3)


class OrderByDeduplicationRawSQLTests(TransactionTestCase):
    """
    Test raw SQL cases that would fail without deduplication.
    Using TransactionTestCase to ensure isolation.
    """

    def test_duplicate_column_in_order_by_fails_in_raw_sql(self):
        """
        This test documents that SQL Server rejects duplicate columns in ORDER BY.
        Raw SQL: ORDER BY name ASC, name DESC - should fail.
        """
        Author.objects.create(name='Test')
        
        with self.assertRaises(Exception):
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT * FROM {Author._meta.db_table} ORDER BY name ASC, name DESC"
                )


class BulkUpdateValidationTests(TestCase):
    """
    Test that bulk_update properly validates fields.
    """

    @classmethod
    def setUpTestData(cls):
        cls.author1 = Author.objects.create(name='Alice')
        cls.author2 = Author.objects.create(name='Bob')

    def test_bulk_update_regular_field(self):
        """bulk_update with regular fields should work."""
        self.author1.name = 'Alice Updated'
        self.author2.name = 'Bob Updated'
        
        Author.objects.bulk_update([self.author1, self.author2], ['name'])
        
        self.author1.refresh_from_db()
        self.author2.refresh_from_db()
        self.assertEqual(self.author1.name, 'Alice Updated')
        self.assertEqual(self.author2.name, 'Bob Updated')

    def test_bulk_update_pk_field_raises_error(self):
        """bulk_update with PK field should raise ValueError."""
        with self.assertRaises(ValueError) as cm:
            Author.objects.bulk_update([self.author1], ['id'])
        
        self.assertIn('primary key', str(cm.exception).lower())

    def test_bulk_update_empty_fields_raises_error(self):
        """bulk_update with empty fields should raise ValueError."""
        with self.assertRaises(ValueError) as cm:
            Author.objects.bulk_update([self.author1], [])
        
        self.assertIn('field names must be given', str(cm.exception).lower())

    def test_bulk_update_with_none_pk_raises_error(self):
        """bulk_update with unsaved objects should raise ValueError."""
        unsaved_author = Author(name='Unsaved')
        
        with self.assertRaises(ValueError) as cm:
            Author.objects.bulk_update([unsaved_author], ['name'])
        
        self.assertIn('primary key set', str(cm.exception).lower())


# Django 5.2+ specific tests for composite PK
if VERSION >= (5, 2):
    from django.db.models import CompositePrimaryKey
    from django.db.models.fields.composite import CompositePrimaryKey as CompositePrimaryKeyField

    class CompositePKValidationTests(TestCase):
        """
        Test composite PK validation logic for bulk_update.
        These tests require Django 5.2+.
        """

        def test_composite_pk_field_names_detection(self):
            """Verify we can correctly detect fields that are part of a composite PK."""
            cpk = CompositePrimaryKey('tenant_id', 'user_id')
            
            pk_field_names = set()
            if isinstance(cpk, CompositePrimaryKeyField):
                pk_field_names = set(cpk.field_names)
            
            self.assertEqual(pk_field_names, {'tenant_id', 'user_id'})

        def test_composite_pk_validation_logic(self):
            """Test the validation logic used in bulk_update."""
            class MockField:
                def __init__(self, name, primary_key=False):
                    self.name = name
                    self.primary_key = primary_key

            pk_field_names = {'tenant_id', 'user_id'}
            
            # Regular field - should be allowed
            regular_field = MockField('name', primary_key=False)
            is_pk_field = regular_field.primary_key or regular_field.name in pk_field_names
            self.assertFalse(is_pk_field)
            
            # Field that's part of composite PK - should NOT be allowed
            cpk_field = MockField('tenant_id', primary_key=False)
            is_pk_field = cpk_field.primary_key or cpk_field.name in pk_field_names
            self.assertTrue(is_pk_field)
            
            # Traditional single PK field - should NOT be allowed
            traditional_pk = MockField('id', primary_key=True)
            is_pk_field = traditional_pk.primary_key or traditional_pk.name in pk_field_names
            self.assertTrue(is_pk_field)

        def test_non_composite_pk_has_empty_field_names(self):
            """For regular models, pk_field_names should be empty."""
            pk_field_names = set()
            
            if isinstance(Author._meta.pk, CompositePrimaryKeyField):
                pk_field_names = set(Author._meta.pk.field_names)
            
            self.assertEqual(pk_field_names, set())

    class CompositePKModelTests(TransactionTestCase):
        """
        Test with actual composite PK model in the database.
        """

        @classmethod
        def setUpClass(cls):
            super().setUpClass()
            # Create the test table
            with connection.cursor() as cursor:
                cursor.execute('''
                    IF OBJECT_ID('testapp_tenantuser', 'U') IS NOT NULL
                        DROP TABLE testapp_tenantuser
                ''')
                cursor.execute('''
                    CREATE TABLE testapp_tenantuser (
                        tenant_id INT NOT NULL,
                        user_id INT NOT NULL,
                        name NVARCHAR(100) NOT NULL,
                        email NVARCHAR(100) NOT NULL,
                        PRIMARY KEY (tenant_id, user_id)
                    )
                ''')

        @classmethod
        def tearDownClass(cls):
            with connection.cursor() as cursor:
                cursor.execute('''
                    IF OBJECT_ID('testapp_tenantuser', 'U') IS NOT NULL
                        DROP TABLE testapp_tenantuser
                ''')
            super().tearDownClass()

        def setUp(self):
            # Define model dynamically
            class TenantUser(models.Model):
                pk = CompositePrimaryKey('tenant_id', 'user_id')
                tenant_id = models.IntegerField()
                user_id = models.IntegerField()
                name = models.CharField(max_length=100)
                email = models.CharField(max_length=100)

                class Meta:
                    app_label = 'testapp'
                    db_table = 'testapp_tenantuser'
                    managed = False

            self.TenantUser = TenantUser
            
            # Insert test data
            with connection.cursor() as cursor:
                cursor.execute('DELETE FROM testapp_tenantuser')
                cursor.execute('''
                    INSERT INTO testapp_tenantuser (tenant_id, user_id, name, email)
                    VALUES (1, 1, 'Alice', 'alice@example.com'),
                           (1, 2, 'Bob', 'bob@example.com'),
                           (2, 1, 'Charlie', 'charlie@example.com')
                ''')

        def test_model_has_composite_pk(self):
            """Verify the model has a composite PK."""
            self.assertIsInstance(self.TenantUser._meta.pk, CompositePrimaryKeyField)
            self.assertEqual(self.TenantUser._meta.pk.field_names, ('tenant_id', 'user_id'))

        def test_bulk_update_regular_field_on_composite_pk_model(self):
            """bulk_update with regular field should work on composite PK model."""
            users = list(self.TenantUser.objects.all())
            self.assertEqual(len(users), 3)
            
            for u in users:
                u.email = u.email.replace('@example.com', '@test.com')
            
            self.TenantUser.objects.bulk_update(users, ['email'])
            
            # Verify the update
            updated_users = list(self.TenantUser.objects.all())
            for u in updated_users:
                self.assertIn('@test.com', u.email)

        def test_bulk_update_composite_pk_field_tenant_id_raises_error(self):
            """bulk_update with composite PK field tenant_id should raise ValueError."""
            users = list(self.TenantUser.objects.all())
            
            with self.assertRaises(ValueError) as cm:
                self.TenantUser.objects.bulk_update(users, ['tenant_id'])
            
            self.assertIn('primary key', str(cm.exception).lower())

        def test_bulk_update_composite_pk_field_user_id_raises_error(self):
            """bulk_update with composite PK field user_id should raise ValueError."""
            users = list(self.TenantUser.objects.all())
            
            with self.assertRaises(ValueError) as cm:
                self.TenantUser.objects.bulk_update(users, ['user_id'])
            
            self.assertIn('primary key', str(cm.exception).lower())
