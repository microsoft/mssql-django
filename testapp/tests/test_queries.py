import django.db.utils
from django.db import connections, connection
from django.test import TransactionTestCase, TestCase

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
                INSERT INTO [test_schema].[editor]([name]) VALUES ('Bar')
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
