import django.db.utils
from django import VERSION
from django.db import connections, connection, models
from django.db.models.functions import Now
from django.test import TransactionTestCase, TestCase, skipUnlessDBFeature
from django.utils import timezone

from ..models import Author, BinaryData

class TestTableWithTrigger(TransactionTestCase):
    def test_insert_into_table_with_trigger(self):
        connection = connections['default']
        with connection.schema_editor() as cursor:
            cursor.execute("""
                CREATE TRIGGER TestTrigger
                ON [testapp_author]
                FOR INSERT
                AS
                INSERT INTO [testapp_editor]([name]) VALUES ('Bar')
            """)

        try:
            # Change can_return_rows_from_bulk_insert to be the same as when
            # has_trigger = True
            old_return_rows_flag = connection.features_class.can_return_rows_from_bulk_insert
            connection.features_class.can_return_rows_from_bulk_insert = False
            Author.objects.create(name='Foo')
        except django.db.utils.ProgrammingError as e:
            self.fail('Check for regression of issue #130. Insert with trigger failed with exception: %s' % e)
        finally:
            with connection.schema_editor() as cursor:
                cursor.execute("DROP TRIGGER TestTrigger")
            connection.features_class.can_return_rows_from_bulk_insert = old_return_rows_flag

class TestBinaryfieldGroupby(TestCase):
    def test_varbinary(self):
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT binary FROM {BinaryData._meta.db_table} WHERE binary = %s GROUP BY binary", [bytes("ABC", 'utf-8')])


@skipUnlessDBFeature("supports_expression_defaults")
class DbDefaultBulkCreateRegressionTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        if VERSION < (6, 0):
            cls.skipTest("db_default bulk insert alignment is Django 6.0+ specific")

        class DbDefaultBulkInsertModel(models.Model):
            name = models.CharField(max_length=100)
            created_at = models.DateTimeField(db_default=Now())

            class Meta:
                app_label = "testapp"
                db_table = "testapp_dbdefault_bulk_insert"
                managed = False

        cls.DbDefaultBulkInsertModel = DbDefaultBulkInsertModel

        with connection.cursor() as cursor:
            cursor.execute(
                """
                IF OBJECT_ID('testapp_dbdefault_bulk_insert', 'U') IS NOT NULL
                    DROP TABLE testapp_dbdefault_bulk_insert
                """
            )
            cursor.execute(
                """
                CREATE TABLE testapp_dbdefault_bulk_insert (
                    id INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
                    name NVARCHAR(100) NOT NULL,
                    created_at DATETIME2 NOT NULL DEFAULT SYSDATETIME()
                )
                """
            )

    @classmethod
    def tearDownClass(cls):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                IF OBJECT_ID('testapp_dbdefault_bulk_insert', 'U') IS NOT NULL
                    DROP TABLE testapp_dbdefault_bulk_insert
                """
            )
        super().tearDownClass()

    def test_db_default_field_excluded_and_included(self):
        model = self.DbDefaultBulkInsertModel
        created_at_quoted_name = connection.ops.quote_name("created_at")

        with self.assertNumQueries(1) as ctx:
            model.objects.bulk_create([model(name="foo"), model(name="bar")])

        self.assertEqual(
            ctx[0]["sql"].count(created_at_quoted_name),
            1 if connection.features.can_return_rows_from_bulk_insert else 0,
        )

        with self.assertNumQueries(1) as ctx:
            model.objects.bulk_create(
                [
                    model(name="baz", created_at=timezone.now()),
                    model(name="qux"),
                ]
            )

        self.assertEqual(
            ctx[0]["sql"].count(created_at_quoted_name),
            2 if connection.features.can_return_rows_from_bulk_insert else 1,
        )
