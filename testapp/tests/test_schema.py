# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.
from django.test import TestCase
from django.db import connections
from django.core.management import call_command

from ..models import ParentSchema, DboSchema, UnusualSchema

class NonDefaultSchemaTests(TestCase):

    def __do_flush(self):
        call_command('flush', verbosity=0, database='default', interactive=False)

    def test_flushing_database_with_non_default_schemas(self):
        self.__do_flush()
        
    def test_insert_then_flush(self):
        base_parents = ParentSchema.objects.all().count()

        ParentSchema.objects.create(
            name='Test Person'
        )

        created_parents = ParentSchema.objects.all().count()

        self.__do_flush()

        flushed_parents = ParentSchema.objects.all().count()

        self.assertEqual(base_parents + 1, created_parents, msg="Could not create parent")
        self.assertEqual(base_parents, flushed_parents, msg="Flush was not successful in restoring state")

    def test_inspectdb(self):
        connection = connections['default']

        with connection.cursor() as cursor:
            descs = connection.introspection.get_table_description(cursor=cursor, table_name='[events].[ParentSchema]')

        self.assertEqual(len(descs), 2, msg="Unable to get both columns on table")
        self.assertEqual( [ desc.name for desc in descs ], ['id', 'name'], msg="Unable to get both columns on table")
    
    def test_insert_then_flush_default_schema(self):
        DboSchema.objects.all().delete()

        DboSchema.objects.create(
            name='Test'
        )

        num_schema = DboSchema.objects.all().count()
        self.assertEqual(num_schema, 1, msg="DboSchema model was not inserted to")

        self.__do_flush()

        num_schema = DboSchema.objects.all().count()
        self.assertEqual(num_schema, 0, msg="DboSchema model was not flushed")

    def test_unusual_schema_flush(self):
        UnusualSchema.objects.all().delete()

        UnusualSchema.objects.create(
            name='Test'
        )

        num_schema = UnusualSchema.objects.all().count()
        self.assertEqual(num_schema, 1, msg="UnusualSchema model was not inserted to")

        self.__do_flush()

        num_schema = UnusualSchema.objects.all().count()
        self.assertEqual(num_schema, 0, msg="UnusualSchema model was not flushed")

    def test_unusual_schema_correct(self):
        connection = connections['default']

        with connection.cursor() as cursor:
            descs = connection.introspection.get_table_description(cursor=cursor, table_name='[unusual]]schema].[Unusual]]Table]')

            # TODO !!
