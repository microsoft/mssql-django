# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from django.db import connections, migrations, models
from django.db.migrations.state import ProjectState
from django.db.utils import IntegrityError
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature

from mssql.base import DatabaseWrapper
from ..models import (
    Author,
    Editor,
    Post,
    TestUniqueNullableModel,
    TestNullableUniqueTogetherModel,
)


@skipUnlessDBFeature('supports_nullable_unique_constraints')
class TestNullableUniqueColumn(TestCase):
    def test_multiple_nulls(self):
        # Issue https://github.com/ESSolutions/django-mssql-backend/issues/45 (case 1)
        # After field `x` has had its type changed, the filtered UNIQUE INDEX which is
        # implementing the nullable unique constraint should still be correctly in place
        # i.e. allowing multiple NULLs but still enforcing uniqueness of non-NULLs

        # Allowed
        TestUniqueNullableModel.objects.create(x=None, test_field='randomness')
        TestUniqueNullableModel.objects.create(x=None, test_field='doesntmatter')

        # Disallowed
        TestUniqueNullableModel.objects.create(x="foo", test_field='irrelevant')
        with self.assertRaises(IntegrityError):
            TestUniqueNullableModel.objects.create(x="foo", test_field='nonsense')


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

            migration = TestMigration('testapp', 'test_unsupportable_unique_constraint')

            with connection.schema_editor(atomic=True) as editor:
                with self.assertRaisesRegex(
                    NotImplementedError, "does not support OR conditions"
                ):
                    return migration.apply(ProjectState(), editor)
