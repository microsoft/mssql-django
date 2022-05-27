# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.
import logging

import django.db.utils
from django.db import connections, migrations, models
from django.db.migrations.state import ProjectState
from django.db.utils import IntegrityError
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature

from mssql.base import DatabaseWrapper
from . import get_constraint_names_where
from ..models import (
    Author,
    Editor,
    M2MOtherModel,
    Post,
    TestUniqueNullableModel,
    TestNullableUniqueTogetherModel,
    TestRenameManyToManyFieldModel,
)

logger = logging.getLogger('mssql.tests')


@skipUnlessDBFeature('supports_nullable_unique_constraints')
class TestNullableUniqueColumn(TestCase):
    def test_type_change(self):
        # Issue https://github.com/ESSolutions/django-mssql-backend/issues/45 (case 1)
        # After field `x` has had its type changed, the filtered UNIQUE INDEX which is
        # implementing the nullable unique constraint should still be correctly in place
        # i.e. allowing multiple NULLs but still enforcing uniqueness of non-NULLs

        # Allowed (NULL != NULL)
        TestUniqueNullableModel.objects.create(x=None, test_field='randomness')
        TestUniqueNullableModel.objects.create(x=None, test_field='doesntmatter')

        # Disallowed
        TestUniqueNullableModel.objects.create(x="foo", test_field='irrelevant')
        with self.assertRaises(IntegrityError):
            TestUniqueNullableModel.objects.create(x="foo", test_field='nonsense')

    def test_rename(self):
        # Rename of a column which is both nullable & unique. Test that
        # the constraint-enforcing unique index survived this migration
        # Related to both:
        # Issue https://github.com/microsoft/mssql-django/issues/67
        # Issue https://github.com/microsoft/mssql-django/issues/14

        # Allowed (NULL != NULL)
        TestUniqueNullableModel.objects.create(y_renamed=None, test_field='something')
        TestUniqueNullableModel.objects.create(y_renamed=None, test_field='anything')

        # Disallowed
        TestUniqueNullableModel.objects.create(y_renamed=42, test_field='nonimportant')
        with self.assertRaises(IntegrityError):
            TestUniqueNullableModel.objects.create(y_renamed=42, test_field='whocares')


@skipUnlessDBFeature('supports_partially_nullable_unique_constraints')
class TestPartiallyNullableUniqueTogether(TestCase):
    def test_partially_nullable(self):
        # Check basic behaviour of `unique_together` where at least 1 of the columns is nullable

        # It should be possible to have 2 rows both with NULL `alt_editor`
        author = Author.objects.create(name="author")
        Post.objects.create(title="foo", author=author)
        Post.objects.create(title="foo", author=author)

        # But `unique_together` is still enforced for non-NULL values
        editor = Editor.objects.create(name="editor")
        Post.objects.create(title="foo", author=author, alt_editor=editor)
        with self.assertRaises(IntegrityError):
            Post.objects.create(title="foo", author=author, alt_editor=editor)

    def test_after_type_change(self):
        # Issue https://github.com/ESSolutions/django-mssql-backend/issues/45 (case 2)
        # After one of the fields in the `unique_together` has had its type changed
        # in a migration, the constraint should still be correctly enforced

        # Multiple rows with a=NULL are considered different
        TestNullableUniqueTogetherModel.objects.create(a=None, b='bbb', c='ccc')
        TestNullableUniqueTogetherModel.objects.create(a=None, b='bbb', c='ccc')

        # Uniqueness still enforced for non-NULL values
        TestNullableUniqueTogetherModel.objects.create(a='aaa', b='bbb', c='ccc')
        with self.assertRaises(IntegrityError):
            TestNullableUniqueTogetherModel.objects.create(a='aaa', b='bbb', c='ccc')


class TestHandleOldStyleUniqueTogether(TransactionTestCase):
    """
    Regression test for https://github.com/microsoft/mssql-django/issues/137

    Start with a unique_together which was created by an older version of this backend code, which implemented
    it with a table CONSTRAINT instead of a filtered UNIQUE INDEX like the current code does.
    e.g. django-mssql-backend < v2.6.0 or (before that) all versions of django-pyodbc-azure

    Then alter the type of a column (e.g. max_length of CharField) which is part of that unique_together and
    check that the (old-style) CONSTRAINT is dropped before (& a new-style UNIQUE INDEX created afterwards).
    """
    def test_drop_old_unique_together_constraint(self):
        class TestMigrationA(migrations.Migration):
            initial = True

            operations = [
                migrations.CreateModel(
                    name='TestHandleOldStyleUniqueTogether',
                    fields=[
                        ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('foo', models.CharField(max_length=50)),
                        ('bar', models.CharField(max_length=50)),
                    ],
                ),
                # Create the unique_together so that Django knows it exists, however we will deliberately drop
                # it (filtered unique INDEX) below & manually replace with the old implementation (CONSTRAINT)
                migrations.AlterUniqueTogether(
                    name='testhandleoldstyleuniquetogether',
                    unique_together={('foo', 'bar')}
                ),
            ]

        class TestMigrationB(migrations.Migration):
            operations = [
                # Alter the type of the field to trigger the _alter_field code which drops/recreats indexes/constraints
                migrations.AlterField(
                    model_name='testhandleoldstyleuniquetogether',
                    name='foo',
                    field=models.CharField(max_length=99),
                )
            ]

        migration_a = TestMigrationA(name='test_drop_old_unique_together_constraint_a', app_label='testapp')
        migration_b = TestMigrationB(name='test_drop_old_unique_together_constraint_b', app_label='testapp')

        connection = connections['default']

        # Setup
        with connection.schema_editor(atomic=True) as editor:
            project_state = migration_a.apply(ProjectState(), editor)

        # Manually replace the unique_together-enforcing INDEX with the old implementation using a CONSTRAINT instead
        # to simulate the state of a database which had been migrated using an older version of this backend
        table_name = 'testapp_testhandleoldstyleuniquetogether'
        unique_index_names = get_constraint_names_where(table_name=table_name, index=True, unique=True)
        assert len(unique_index_names) == 1
        unique_together_name = unique_index_names[0]
        logger.debug('Replacing UNIQUE INDEX %s with a CONSTRAINT of the same name', unique_together_name)
        with connection.schema_editor(atomic=True) as editor:
            # Out with the new
            editor.execute('DROP INDEX [%s] ON [%s]' % (unique_together_name, table_name))
            # In with the old, so that we end up in the state that an old database might be in
            editor.execute('ALTER TABLE [%s] ADD CONSTRAINT [%s] UNIQUE ([foo], [bar])' % (table_name, unique_together_name))

        # Test by running AlterField
        with connection.schema_editor(atomic=True) as editor:
            # If this doesn't explode then all is well. Without the bugfix, the CONSTRAINT wasn't dropped before,
            # so then re-instating the unique_together using an INDEX of the same name (after altering the field)
            # would fail due to the presence of a CONSTRAINT (really still an index under the hood) with that name.
            try:
                migration_b.apply(project_state, editor)
            except django.db.utils.DatabaseError as e:
                logger.exception('Failed to AlterField:')
                self.fail('Check for regression of issue #137, AlterField failed with exception: %s' % e)


class TestRenameManyToManyField(TestCase):
    def test_uniqueness_still_enforced_afterwards(self):
        # Issue https://github.com/microsoft/mssql-django/issues/86
        # Prep
        thing1 = TestRenameManyToManyFieldModel.objects.create()
        other1 = M2MOtherModel.objects.create(name='1')
        other2 = M2MOtherModel.objects.create(name='2')
        thing1.others_renamed.set([other1, other2])
        # Check that the unique_together on the through table is still enforced
        # (created by create_many_to_many_intermediary_model)
        ThroughModel = TestRenameManyToManyFieldModel.others_renamed.through
        with self.assertRaises(IntegrityError, msg='Through model fails to enforce uniqueness after m2m rename'):
            # This should fail due to the unique_together because (thing1, other1) is already in the through table
            ThroughModel.objects.create(testrenamemanytomanyfieldmodel=thing1, m2mothermodel=other1)


class TestUniqueConstraints(TransactionTestCase):
    def test_unsupportable_unique_constraint(self):
        # Only execute tests when running against SQL Server
        connection = connections['default']
        if isinstance(connection, DatabaseWrapper):

            class TestMigration(migrations.Migration):
                initial = True

                operations = [
                    migrations.CreateModel(
                        name='TestUnsupportableUniqueConstraint',
                        fields=[
                            (
                                'id',
                                models.AutoField(
                                    auto_created=True,
                                    primary_key=True,
                                    serialize=False,
                                    verbose_name='ID',
                                ),
                            ),
                            ('_type', models.CharField(max_length=50)),
                            ('status', models.CharField(max_length=50)),
                        ],
                    ),
                    migrations.AddConstraint(
                        model_name='testunsupportableuniqueconstraint',
                        constraint=models.UniqueConstraint(
                            condition=models.Q(
                                ('status', 'in_progress'),
                                ('status', 'needs_changes'),
                                _connector='OR',
                            ),
                            fields=('_type',),
                            name='or_constraint',
                        ),
                    ),
                ]

            migration = TestMigration(name='test_unsupportable_unique_constraint', app_label='testapp')

            with connection.schema_editor(atomic=True) as editor:
                with self.assertRaisesRegex(
                    NotImplementedError, "does not support OR conditions"
                ):
                    return migration.apply(ProjectState(), editor)
