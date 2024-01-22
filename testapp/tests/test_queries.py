import django.db.utils
from django.db import connections
from django.test import TransactionTestCase

from ..models import Author

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
            connection.features_class.can_return_rows_from_bulk_insert = False
            Author.objects.create(name='Foo')
        except django.db.utils.ProgrammingError as e:
            self.fail('Check for regression of issue #130. Insert with trigger failed with exception: %s' % e)
        finally:
            with connection.schema_editor() as cursor:
                cursor.execute("DROP TRIGGER TestTrigger")
            # connection.features_class.can_return_rows_from_bulk_insert = True