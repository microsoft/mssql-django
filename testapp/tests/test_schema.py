# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.
from django.test import TestCase
from django.core.management import call_command

from ..models import ParentSchema

class NonDefaultSchemaTests(TestCase):

    def __do_flush(self):
        call_command('flush', verbosity=3, database='default', interactive=False)

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