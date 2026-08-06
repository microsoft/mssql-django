# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

"""
Tests for mssql/introspection.py.

Regression coverage for get_relations(), whose return shape changed in
Django 6.1: relations are now (referenced_column, referenced_table,
db_on_delete) 3-tuples that carry the introspected ON DELETE rule, where
earlier versions returned (referenced_column, referenced_table) 2-tuples.
"""

from django import VERSION as django_version
from django.db import connection
from django.test import TestCase

from testapp.models import Comment


class GetRelationsTests(TestCase):
    """get_relations() returns the version-correct relation shape."""

    def test_get_relations_shape_for_foreign_key(self):
        table = Comment._meta.db_table
        fk_column = Comment._meta.get_field('post').column  # post_id
        referenced_table = Comment._meta.get_field('post').related_model._meta.db_table

        with connection.cursor() as cursor:
            relations = connection.introspection.get_relations(cursor, table)

        self.assertIn(fk_column, relations)
        relation = relations[fk_column]

        if django_version >= (6, 1):
            # Django 6.1: (referenced_column, referenced_table, db_on_delete).
            from django.db.models import DO_NOTHING
            self.assertEqual(len(relation), 3)
            ref_column, ref_table, db_on_delete = relation
            self.assertEqual(ref_table, referenced_table)
            # SQL Server FKs are created with NO ACTION (on_delete is emulated
            # in the ORM), which maps to DO_NOTHING.
            self.assertEqual(db_on_delete, DO_NOTHING)
        else:
            # Older Django: (referenced_column, referenced_table).
            self.assertEqual(len(relation), 2)
            ref_column, ref_table = relation
            self.assertEqual(ref_table, referenced_table)
