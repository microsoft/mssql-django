import logging
from collections import namedtuple

import django.db
from django import VERSION
from django.apps import apps
from django.db import models, migrations
from django.db.migrations.migration import Migration
from django.db.migrations.state import ProjectState
from django.db.models import UniqueConstraint
from django.db.models.lookups import Exact
from django.db.utils import DEFAULT_DB_ALIAS, ConnectionHandler, ProgrammingError
from django.test import TestCase, TransactionTestCase
from unittest import expectedFailure, skipIf, skipUnless
from unittest.mock import patch

from mssql.schema import _clone_index_with_replacements, _replace_condition_field_names

from . import get_constraints
from ..models import (
    TestIndexesRetainedRenamed,
    Choice,
    Question,
)

connections = ConnectionHandler()

if (VERSION >= (3, 2)):
    from django.utils.connection import ConnectionProxy
    connection = ConnectionProxy(connections, DEFAULT_DB_ALIAS)
else:
    from django.db import DefaultConnectionProxy
    connection = DefaultConnectionProxy()

logger = logging.getLogger('mssql.tests')

# Result type for migration test helper
MigrationTestResult = namedtuple('MigrationTestResult', ['model', 'constraints', 'project_state'])


class TestIndexesRetained(TestCase):
    """
    Issue https://github.com/microsoft/mssql-django/issues/14
    Indexes dropped during a migration should be re-created afterwards
    assuming the field still has `db_index=True`
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Pre-fetch which indexes exist for the relevant test model
        # now that all the test migrations have run
        cls.constraints = get_constraints(table_name=TestIndexesRetainedRenamed._meta.db_table)
        cls.indexes = {k: v for k, v in cls.constraints.items() if v['index'] is True}

    def _assert_index_exists(self, columns):
        matching = {k: v for k, v in self.indexes.items() if set(v['columns']) == columns}
        assert len(matching) == 1, (
            "Expected 1 index for columns %s but found %d %s" % (
                columns,
                len(matching),
                ', '.join(matching.keys())
            )
        )

    def test_field_made_nullable(self):
        # case (a) of https://github.com/microsoft/mssql-django/issues/14
        self._assert_index_exists({'a'})

    def test_field_renamed(self):
        # case (b) of https://github.com/microsoft/mssql-django/issues/14
        self._assert_index_exists({'b_renamed'})

    def test_table_renamed(self):
        # case (c) of https://github.com/microsoft/mssql-django/issues/14
        self._assert_index_exists({'c'})

def _get_all_models():
    for app in apps.get_app_configs():
        app_label = app.label
        for model_name, model_class in app.models.items():
            yield model_class, model_name, app_label


class TestCorrectIndexes(TestCase):

    def test_correct_indexes_exist(self):
        """
        Check there are the correct number of indexes for each field after all migrations
        by comparing what the model says (e.g. `db_index=True` / `index_together` etc.)
        with the actual constraints found in the database.
        This acts as a general regression test for issues such as:
         - duplicate index created (e.g. https://github.com/microsoft/mssql-django/issues/77)
         - index dropped but accidentally not recreated
         - index incorrectly 'recreated' when it was never actually dropped or required at all
        Note of course that it only covers cases which exist in testapp/models.py and associated migrations
        """
        connection = django.db.connections[django.db.DEFAULT_DB_ALIAS]
        for model_cls, model_name, app_label in _get_all_models():
            logger.debug('Checking model: %s.%s', app_label, model_name)
            if not model_cls._meta.managed:
                # Models where the table is not managed by Django migrations are irrelevant
                continue
            model_constraints = get_constraints(table_name=model_cls._meta.db_table)
            # Check correct indexes are in place for all fields in model
            for field in model_cls._meta.get_fields():
                if not hasattr(field, 'column'):
                    # ignore things like reverse fields which don't have a column on this table
                    continue
                col_name = connection.introspection.identifier_converter(field.column)
                field_str = f'{app_label}.{model_name}.{field.name} ({col_name})'
                logger.debug('  > Checking field: %s', field_str)

                # Find constraints which include this column
                col_constraints = [
                    dict(name=name, **infodict) for name, infodict in model_constraints.items()
                    if col_name in infodict['columns']
                ]
                col_indexes = [c for c in col_constraints if c['index']]
                for c in col_constraints:
                    logger.debug('    > Column <%s> is involved in constraint: %s', col_name, c)

                # There should be an explicit index for each of the following cases
                expected_index_causes = []
                if field.db_index:
                    expected_index_causes.append('db_index=True')
                if VERSION < (5, 1):
                   for field_names in model_cls._meta.index_together:
                      if field.name in field_names:
                         expected_index_causes.append(f'index_together[{field_names}]')
                if field._unique and field.null:
                    # This is implemented using a (filtered) unique index (not a constraint) to get ANSI NULL behaviour
                    expected_index_causes.append('unique=True & null=True')
                for field_names in model_cls._meta.unique_together:
                    if field.name in field_names:
                        # unique_together results in an index because this backend implements it using a
                        # (filtered) unique index rather than a constraint, to get ANSI NULL behaviour
                        expected_index_causes.append(f'unique_together[{field_names}]')
                for uniq_constraint in filter(lambda c: isinstance(c, UniqueConstraint), model_cls._meta.constraints):
                    if field.name in uniq_constraint.fields and uniq_constraint.condition is not None:
                        # Meta:constraints > UniqueConstraint with condition are implemented with filtered unique index
                        expected_index_causes.append(f'UniqueConstraint (with condition) in Meta: constraints')

                # Other cases like `unique=True, null=False` or `field.primary_key` do have index-like constraints
                # but in those cases the introspection returns `"index": False` so they are not in the list of
                # explicit indexes which we are checking here (`col_indexes`)

                assert len(col_indexes) == len(expected_index_causes), \
                    'Expected %s index(es) on %s but found %s.\n' \
                    'Check for behaviour changes around index drop/recreate in methods like _alter_field.\n' \
                    'Expected due to: %s\n' \
                    'Found: %s' % (
                        len(expected_index_causes),
                        field_str,
                        len(col_indexes),
                        expected_index_causes,
                        '\n'.join(str(i) for i in col_indexes),
                    )
                logger.debug('  Found %s index(es) as expected', len(col_indexes))


class TestIndexesBeingDropped(TestCase):

    def test_unique_index_dropped(self):
        """
        Issues https://github.com/microsoft/mssql-django/issues/110
        and https://github.com/microsoft/mssql-django/issues/90
        Unique indexes not being dropped when changing non-nullable
        foreign key with unique_together to nullable causing
        dependent on column error
        """
        old_field = Choice._meta.get_field('question')
        new_field = models.ForeignKey(
            Question, null=False, on_delete=models.deletion.CASCADE
        )
        new_field.set_attributes_from_name("question")
        with connection.schema_editor() as editor:
            editor.alter_field(Choice, old_field, new_field, strict=True)

        old_field = new_field
        new_field = models.ForeignKey(
            Question, null=True, on_delete=models.deletion.CASCADE
        )
        new_field.set_attributes_from_name("question")
        try:
            with connection.schema_editor() as editor:
                editor.alter_field(Choice, old_field, new_field, strict=True)
        except ProgrammingError:
            self.fail("Unique indexes not being dropped")

class TestMetaIndexesRetained(TransactionTestCase):
    """
    Regression test for indexes defined via Meta.indexes being dropped
    and not recreated after altering one of the indexed columns.

    Tests various schema operations that trigger index drop/recreate logic to ensure
    indexes are properly restored.

    Each test runs twice:
    - With migrations in split contexts (simulates separate migration files)
    - With migrations in combined context (simulates single migration file with multiple operations)
    """

    def _run_migration_test(
        self,
        operations_a: list,
        operations_b: list,
        migration_name_prefix: str,
        model_name: str,
        use_single_migration: bool,
        operations_c=None,
    ) -> MigrationTestResult:
        """
        Helper to run migration tests with either combined or split schema_editor contexts.

        Args:
            operations_a: List of operations for initial setup (CreateModel + AddIndex)
            operations_b: List of operations for the alteration being tested
            migration_name_prefix: Prefix for migration names (e.g., 'test_mc_type')
            model_name: Name of the model being tested
            use_single_migration: If True, combine both operation lists into one Migration;
                               If False, create two separate Migrations

        Returns:
            MigrationTestResult: Named tuple containing (model, constraints, project_state)
        """
        # Use django.db.connections to get a fresh connection for TransactionTestCase
        conn = django.db.connections[django.db.DEFAULT_DB_ALIAS]
        suffix = '_combined' if use_single_migration else '_split'
        operations_c = operations_c or []

        if use_single_migration:
            # Combined: Create ONE migration with all operations combined
            # This simulates combining operations in a single migration file
            class CombinedMigration(migrations.Migration):
                initial = True
                operations = operations_a + operations_b + operations_c

            migration = CombinedMigration(name=f'{migration_name_prefix}{suffix}', app_label='testapp')

            with conn.schema_editor(atomic=True) as editor:
                project_state = migration.apply(ProjectState(), editor)
        else:
            # Split: Create TWO separate migrations, each with its own operations
            # This simulates two separate migration files where the first migration
            # is fully committed and `deferred_sql` runs before starting the second migration
            class MigrationA(migrations.Migration):
                initial = True
                operations = operations_a

            class MigrationB(migrations.Migration):
                operations = operations_b

            migration_a = MigrationA(name=f'{migration_name_prefix}{suffix}_a', app_label='testapp')
            migration_b = MigrationB(name=f'{migration_name_prefix}{suffix}_b', app_label='testapp')
            if operations_c:
                class MigrationC(migrations.Migration):
                    operations = operations_c

                migration_c = MigrationC(
                    name=f'{migration_name_prefix}{suffix}_c', app_label='testapp'
                )

            with conn.schema_editor(atomic=True) as editor:
                project_state = migration_a.apply(ProjectState(), editor)
            with conn.schema_editor(atomic=True) as editor:
                project_state = migration_b.apply(project_state, editor)
            if operations_c:
                with conn.schema_editor(atomic=True) as editor:
                    project_state = migration_c.apply(project_state, editor)

        # Get the model and constraints for assertions
        model = project_state.apps.get_model('testapp', model_name)
        constraints = get_constraints(table_name=model._meta.db_table)

        return MigrationTestResult(model, constraints, project_state)

    def _assert_index_exists(self, constraints, expected_columns, error_msg):
        """
        Assert that an index with exactly the expected columns exists.

        Args:
            constraints: Dictionary of constraints from get_constraints()
            expected_columns: Set of column names that should be in the index
            error_msg: Message to display if assertion fails
        """
        found = any(
            set(info['columns']) == expected_columns and info['index']
            for info in constraints.values()
        )
        self.assertTrue(found, error_msg)

    def _get_context_description(self, use_single_migration: bool) -> str:
        return "combined single migration" if use_single_migration else "split into 2 migrations"

    def _assert_named_index_columns(self, constraints, index_name, expected_columns, error_msg):
        self.assertIn(index_name, constraints, error_msg)
        self.assertEqual(constraints[index_name]['columns'], expected_columns, error_msg)

    def _get_index_catalog(self, model, index_name):
        with django.db.connections[django.db.DEFAULT_DB_ALIAS].cursor() as cursor:
            cursor.execute(
                """
                SELECT ic.is_included_column, c.name, i.filter_definition
                FROM sys.indexes AS i
                INNER JOIN sys.index_columns AS ic
                    ON i.object_id = ic.object_id AND i.index_id = ic.index_id
                INNER JOIN sys.columns AS c
                    ON ic.object_id = c.object_id AND ic.column_id = c.column_id
                WHERE i.object_id = OBJECT_ID(%s) AND i.name = %s
                ORDER BY ic.key_ordinal, ic.index_column_id
                """,
                [model._meta.db_table, index_name],
            )
            return cursor.fetchall()

    def test_index_from_meta_indexes_retained_after_type_change(self):
        """
        Test that indexes defined in Meta.indexes are retained when altering field type (max_length change).
        This exercises the type change code path in _alter_field.
        Runs with both split and combined migrations
        """
        for use_single_migration in [False, True]:

            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestMetaIdxType{suffix}'

                operations_a = [
                    migrations.CreateModel(
                        name=model_name,
                        fields=[
                            ('id', models.AutoField(primary_key=True)),
                            ('a', models.CharField(max_length=20)),
                            ('b', models.CharField(max_length=20)),
                        ],
                    ),
                    migrations.AddIndex(
                        model_name=model_name.lower(),
                        index=models.Index(fields=['a', 'b'], name=f'idx_type{suffix}'),
                    ),
                ]

                operations_b = [
                    migrations.AlterField(
                        model_name=model_name.lower(),
                        name='a',
                        field=models.CharField(max_length=40),
                    ),
                ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_mc_type',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'a', 'b'},
                    error_msg=(
                        f"Index on ('a', 'b') from Meta.indexes was not recreated after field type change "
                        f"({self._get_context_description(use_single_migration)}). Expected index to be restored after ALTER COLUMN operation."
                    ),
                )

    def test_index_from_meta_indexes_retained_after_nullability_change(self):
        """
        Test that indexes defined in Meta.indexes are retained when changing field nullability.
        This exercises the nullability change code path in _alter_field.
        Runs with both split and combined migrations
        """
        for use_single_migration in [False, True]:

            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestMetaIdxNull{suffix}'

                operations_a = [
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),
                                ('b', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(fields=['a', 'b'], name=f'idx_null{suffix}'),
                        ),
                    ]

                operations_b = [
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='b',
                            field=models.CharField(max_length=20, null=True),
                        ),
                    ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_mc_null',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'a', 'b'},
                    error_msg=(
                        f"Index on ('a', 'b') from Meta.indexes was not recreated after nullability change "
                        f"({self._get_context_description(use_single_migration)}). Expected index to be restored after ALTER COLUMN NULL operation."
                    ),
                )

    def test_alter_field_with_descending_index_fields(self):
        """
        Regression test for https://github.com/microsoft/mssql-django/issues/405

        When a model has Meta.indexes with descending fields (e.g. fields=['-date']),
        AlterField on any field in the model crashed with FieldDoesNotExist because
        _delete_indexes and the index restoration loop iterated over index.fields
        (which contains '-date') instead of index.fields_orders (which yields ('date', 'DESC')).
        """
        for use_single_migration in [False, True]:

            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestDescIdx{suffix}'

                operations_a = [
                    migrations.CreateModel(
                        name=model_name,
                        fields=[
                            ('id', models.AutoField(primary_key=True)),
                            ('name', models.CharField(max_length=100)),
                            ('date', models.DateTimeField()),
                            ('optional', models.TextField(default='')),
                        ],
                    ),
                    migrations.AddIndex(
                        model_name=model_name.lower(),
                        index=models.Index(fields=['-date'], name=f'idx_desc{suffix}'),
                    ),
                ]

                operations_b = [
                    migrations.AlterField(
                        model_name=model_name.lower(),
                        name='optional',
                        field=models.TextField(null=True),
                    ),
                ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_desc_idx',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'date'},
                    error_msg=(
                        f"Index on ('-date',) from Meta.indexes was not retained after AlterField "
                        f"({self._get_context_description(use_single_migration)}). "
                        f"Descending index fields should not cause FieldDoesNotExist."
                    ),
                )

    def test_db_index_retained_after_nullability_only_change(self):
        """
        Test that db_index=True indexes are retained when ONLY nullability changes.

        This tests the case where:
        - Field has db_index=True
        - Field nullability changes (null=False → null=True)
        - Field type does NOT change (same max_length)

        Runs with both split and combined migrations
        """
        for use_single_migration in [False, True]:

            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestDbIndexNullChange{suffix}'

                operations_a = [
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20, db_index=True)),  # db_index=True, null=False
                            ],
                        ),
                    ]

                operations_b = [
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='a',
                            field=models.CharField(max_length=20, db_index=True, null=True),  # Same type, different null
                        ),
                    ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_dbidx_null',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                # Verify db_index=True index was retained
                # Look for single-column index on 'a'
                db_index_indexes = [
                    info for info in result.constraints.values()
                    if info.get('index') and set(info['columns']) == {'a'}
                ]
                self.assertTrue(
                    len(db_index_indexes) > 0,
                    f"db_index=True index on 'a' was not retained after nullability-only change "
                    f"({self._get_context_description(use_single_migration)}). "
                    f"Expected index from db_index=True to be restored after changing null=False to null=True."
                )

    def test_db_index_retained_after_nullability_change_to_not_null(self):
        """
        Test that db_index=True indexes are retained when changing from null=True to null=False.

        This is the reverse direction of test_db_index_retained_after_nullability_only_change
        and exercises the four-way default alteration path in _alter_field (requires a default value).

        Runs with both split and combined migrations
        """
        for use_single_migration in [False, True]:

            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestDbIndexNotNull{suffix}'

                operations_a = [
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20, db_index=True, null=True)),  # db_index=True, null=True
                            ],
                        ),
                    ]

                operations_b = [
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='a',
                            field=models.CharField(max_length=20, db_index=True, null=False, default=''),  # null=False requires default
                        ),
                    ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_dbidx_notnull',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                # Verify db_index=True index was retained
                db_index_indexes = [
                    info for info in result.constraints.values()
                    if info.get('index') and set(info['columns']) == {'a'}
                ]
                self.assertTrue(
                    len(db_index_indexes) > 0,
                    f"db_index=True index on 'a' was not retained after nullability change from NULL to NOT NULL "
                    f"({self._get_context_description(use_single_migration)}). "
                    f"Expected index from db_index=True to be restored after four-way default alteration."
                )

    def test_index_from_meta_indexes_retained_after_field_rename(self):
        """
        Test that indexes defined in Meta.indexes are retained and updated when renaming a field.
        The index should exist on the renamed column.
        Runs with both split and combined migrations
        """
        for use_single_migration in [False, True]:

            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestMetaIdxRename{suffix}'

                operations_a = [
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),
                                ('b', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(fields=['a', 'b'], name=f'idx_rename{suffix}'),
                        ),
                    ]

                operations_b = [
                        migrations.RenameField(
                            model_name=model_name.lower(),
                            old_name='a',
                            new_name='a_renamed',
                        ),
                    ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_mc_rename',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'a_renamed', 'b'},
                    error_msg=(
                        f"Index on ('a_renamed', 'b') from Meta.indexes was not found after field rename "
                        f"({self._get_context_description(use_single_migration)}). Expected index to be updated to reflect the renamed column."
                    ),
                )

    def test_index_from_meta_indexes_retained_after_rename_and_type_change(self):
        """
        Test that indexes from Meta.indexes are retained when a field is renamed
        AND has its type changed in the same migration.

        Regression test for https://github.com/microsoft/mssql-django/issues/499

        Runs with both split and combined migrations
        """
        for use_single_migration in [False, True]:

            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestMetaIdxRenameType{suffix}'

                operations_a = [
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),
                                ('b', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(fields=['a', 'b'], name=f'idx_rename_type{suffix}'),
                        ),
                    ]

                operations_b = [
                        # Rename field 'a' to 'a_renamed'
                        migrations.RenameField(
                            model_name=model_name.lower(),
                            old_name='a',
                            new_name='a_renamed',
                        ),
                        # Also change its type (max_length 20 -> 40)
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='a_renamed',
                            field=models.CharField(max_length=40),
                        ),
                    ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_mc_rename_type',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'a_renamed', 'b'},
                    error_msg=(
                        f"Index on ('a_renamed', 'b') from Meta.indexes was not found after field rename + type change "
                        f"({self._get_context_description(use_single_migration)}). "
                        f"Expected index to be retained when both rename and type change occur."
                    ),
                )

    def test_db_index_retained_after_rename_and_type_change(self):
        """
        Test that db_index=True indexes are retained when a field's db_column is changed
        AND has its type changed in the same AlterField operation.

        Runs with both split and combined migrations
        """
        for use_single_migration in [False, True]:

            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestDbIdxRenameType{suffix}'

                operations_a = [
                    migrations.CreateModel(
                        name=model_name,
                        fields=[
                            ('id', models.AutoField(primary_key=True)),
                            ('a', models.CharField(max_length=20, db_index=True, db_column='col_a')),
                            ('b', models.CharField(max_length=20)),
                        ],
                    ),
                ]

                operations_b = [
                    # Change db_column AND type in single AlterField
                    migrations.AlterField(
                        model_name=model_name.lower(),
                        name='a',
                        field=models.CharField(max_length=40, db_index=True, db_column='col_a_renamed'),
                    ),
                ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_dbidx_rename_type',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'col_a_renamed'},
                    error_msg=(
                        f"db_index=True index on 'col_a_renamed' was not found after column rename + type change "
                        f"({self._get_context_description(use_single_migration)}). "
                        f"Expected index to be retained when both column rename and type change occur in same AlterField."
                    ),
                )

    def test_unique_retained_after_rename_and_type_change(self):
        """
        Test that unique=True constraints are retained when a field's db_column is changed
        AND has its type changed in the same AlterField operation.

        Runs with both split and combined migrations
        """
        for use_single_migration in [False, True]:

            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestUniqueRenameType{suffix}'

                operations_a = [
                    migrations.CreateModel(
                        name=model_name,
                        fields=[
                            ('id', models.AutoField(primary_key=True)),
                            ('a', models.CharField(max_length=20, unique=True, db_column='col_a')),
                            ('b', models.CharField(max_length=20)),
                        ],
                    ),
                ]

                operations_b = [
                    # Change db_column AND type in single AlterField
                    migrations.AlterField(
                        model_name=model_name.lower(),
                        name='a',
                        field=models.CharField(max_length=40, unique=True, db_column='col_a_renamed'),
                    ),
                ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_uniq_rename_type',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                # Check for unique constraint on the renamed column
                unique_constraints = [
                    info for info in result.constraints.values()
                    if info.get('unique') and set(info['columns']) == {'col_a_renamed'}
                ]
                self.assertTrue(
                    len(unique_constraints) > 0,
                    f"unique=True constraint on 'col_a_renamed' was not found after column rename + type change "
                    f"({self._get_context_description(use_single_migration)}). "
                    f"Expected unique constraint to be retained."
                )

    @expectedFailure
    @skipIf(VERSION >= (5, 1), "unique_together is deprecated in Django 5.1+")
    def test_unique_together_retained_after_rename_and_type_change(self):
        """
        Test that unique_together constraints are retained when a field's db_column is changed
        AND has its type changed in the same AlterField operation.

        Runs with both split and combined migrations
        """
        for use_single_migration in [False, True]:

            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestUniqTogetherRenameType{suffix}'

                operations_a = [
                    migrations.CreateModel(
                        name=model_name,
                        fields=[
                            ('id', models.AutoField(primary_key=True)),
                            ('a', models.CharField(max_length=20, db_column='col_a')),
                            ('b', models.CharField(max_length=20)),
                        ],
                        options={
                            'unique_together': {('a', 'b')},
                        },
                    ),
                ]

                operations_b = [
                    # Change db_column AND type in single AlterField
                    migrations.AlterField(
                        model_name=model_name.lower(),
                        name='a',
                        field=models.CharField(max_length=40, db_column='col_a_renamed'),
                    ),
                ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_uniqtog_rename_type',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                # Check for unique_together constraint on ('col_a_renamed', 'b')
                unique_constraints = [
                    info for info in result.constraints.values()
                    if info.get('unique') and set(info['columns']) == {'col_a_renamed', 'b'}
                ]
                self.assertTrue(
                    len(unique_constraints) > 0,
                    f"unique_together constraint on ('col_a_renamed', 'b') was not found after column rename + type change "
                    f"({self._get_context_description(use_single_migration)}). "
                    f"Expected unique_together to be retained."
                )

    def test_index_from_meta_indexes_retained_after_rename_and_nullability_change(self):
        """
        Test that indexes from Meta.indexes are retained when a field is renamed
        AND has its nullability changed in the same migration.

        Regression test for https://github.com/microsoft/mssql-django/issues/499

        Runs with both split and combined migrations
        """
        for use_single_migration in [False, True]:

            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestMetaIdxRenameNull{suffix}'

                operations_a = [
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),
                                ('b', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(fields=['a', 'b'], name=f'idx_rename_null{suffix}'),
                        ),
                    ]

                operations_b = [
                        # Rename field 'a' to 'a_renamed'
                        migrations.RenameField(
                            model_name=model_name.lower(),
                            old_name='a',
                            new_name='a_renamed',
                        ),
                        # Also change its nullability
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='a_renamed',
                            field=models.CharField(max_length=20, null=True),
                        ),
                    ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_mc_rename_null',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'a_renamed', 'b'},
                    error_msg=(
                        f"Index on ('a_renamed', 'b') from Meta.indexes was not found after field rename + nullability change "
                        f"({self._get_context_description(use_single_migration)}). "
                        f"Expected index to be retained when both rename and nullability change occur."
                    ),
                )

    def test_index_from_meta_indexes_retained_after_altering_both_fields(self):
        """
        Test that indexes defined in Meta.indexes are retained when altering multiple fields in the index.
        This ensures the index is properly restored even when both participating columns are altered.
        Runs with both split and combined migrations
        """
        for use_single_migration in [False, True]:

            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestMetaIdxBoth{suffix}'

                operations_a = [
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),
                                ('b', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(fields=['a', 'b'], name=f'idx_both{suffix}'),
                        ),
                    ]

                operations_b = [
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='a',
                            field=models.CharField(max_length=40),
                        ),
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='b',
                            field=models.CharField(max_length=30),
                        ),
                    ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_mc_both',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'a', 'b'},
                    error_msg=(
                        f"Index on ('a', 'b') from Meta.indexes was not recreated after altering both fields "
                        f"({self._get_context_description(use_single_migration)}). Expected index to be restored after multiple ALTER COLUMN operations."
                    ),
                )

    def test_three_column_index_retained_after_field_alteration(self):
        """
        Test that indexes with 3+ columns are retained when altering one of the fields.
        This ensures the fix works for indexes with more than 2 columns.
        Runs with both split and combined migrations
        """
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestMetaIdx3Col{suffix}'

                operations_a = [
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),
                                ('b', models.CharField(max_length=20)),
                                ('c', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(fields=['a', 'b', 'c'], name=f'idx_3col{suffix}'),
                        ),
                    ]

                operations_b = [
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='b',
                            field=models.CharField(max_length=50),
                        ),
                    ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_mc_3col',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'a', 'b', 'c'},
                    error_msg=(
                        f"Three-column index on ('a', 'b', 'c') was not recreated after field alteration "
                        f"({self._get_context_description(use_single_migration)}). Expected index to be restored after ALTER COLUMN operation on middle column."
                    ),
                )

    def test_indexes_retained_for_field_with_db_index_and_meta_indexes(self):
        """
        Test that when a field has indexes from both db_index=True and Meta.indexes, those
        indexes are both retained after altering that field.
        """
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestMetaIdxDbIdx{suffix}'

                operations_a = [
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20, db_index=True)),
                                ('b', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(fields=['a', 'b'], name=f'idx_dbidx{suffix}'),
                        ),
                    ]

                operations_b = [
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='a',
                            field=models.CharField(max_length=40, db_index=True),
                        ),
                    ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_mc_dbidx',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                # Check that _meta_indexes index was recreated
                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'a', 'b'},
                    error_msg=(
                        f"Index on ('a', 'b') from Meta.indexes was not recreated after field type change "
                        f"({self._get_context_description(use_single_migration)})."
                    ),
                )

                # Check that index from db_index=True was also recreated
                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'a'},
                    error_msg=(
                        "Index on 'a' from db_index=True was not recreated "
                        f"after field type change ({self._get_context_description(use_single_migration)})."
                    ),
                )

    def test_index_from_meta_indexes_retained_after_type_and_nullability_change(self):
        """
        Test that indexes defined in Meta.indexes are retained when BOTH type and nullability change simultaneously.
        This exercises both code paths in _alter_field (type change AND nullability change).
        The index should only be dropped once and recreated once (tests deduplication logic).
        Runs with both split and combined migrations
        """
        for use_single_migration in [False, True]:

            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestMetaIdxTypeNull{suffix}'

                operations_a = [
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),
                                ('b', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(fields=['a', 'b'], name=f'idx_typenull{suffix}'),
                        ),
                    ]

                operations_b = [
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='a',
                            field=models.CharField(max_length=40, null=True),
                        ),
                    ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_mc_typenull',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'a', 'b'},
                    error_msg=(
                        f"Index on ('a', 'b') from Meta.indexes was not recreated after simultaneous type and nullability change "
                        f"({self._get_context_description(use_single_migration)}). "
                        f"Expected index to be restored after ALTER COLUMN operation changing both max_length and nullability."
                    ),
                )

    def test_indexes_from_meta_indexes_retained_with_unique_together(self):
        """
        Test that indexes defined in Meta.indexes coexist properly with unique_together constraints.
        Tests the case where a model has overlapping columns participating in both unique_together and
        indexes defined in Meta.indexes. The index defined in Meta.indexes should be retained after field alteration.
        Runs with both split and combined migrations
        """
        for use_single_migration in [False, True]:

            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestMetaIdxUniqTogether{suffix}'

                operations_a = [
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),
                                ('b', models.CharField(max_length=20)),
                                ('c', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AlterUniqueTogether(
                            name=model_name.lower(),
                            unique_together={('a', 'b')},
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(fields=['a', 'c'], name=f'idx_uniqtog{suffix}'),
                        ),
                    ]

                operations_b = [
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='a',
                            field=models.CharField(max_length=40),
                        ),
                    ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_mc_uniqtog',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                # Check that the index (a, c) from Meta.indexes was recreated
                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'a', 'c'},
                    error_msg=(
                        f"Index on ('a', 'c') from Meta.indexes was not recreated after field alteration "
                        f"({self._get_context_description(use_single_migration)}). "
                        f"Expected index to coexist with unique_together constraint on ('a', 'b')."
                    ),
                )

                # Also verify that unique_together constraint still exists
                unique_constraints = [
                    info for info in result.constraints.values()
                    if info.get('unique') and set(info['columns']) == {'a', 'b'}
                ]
                self.assertTrue(
                    len(unique_constraints) > 0,
                    f"unique_together constraint on ('a', 'b') was lost "
                    f"({self._get_context_description(use_single_migration)})."
                )

    def test_index_from_meta_indexes_retained_after_fk_alteration(self):
        """
        Test that indexes defined in Meta.indexes containing ForeignKey fields are retained after FK alteration.
        ForeignKey handling in _alter_field is complex, and this ensures that indexes defined in Meta.indexes
        involving FK fields are properly restored.
        Runs with both split and combined migrations
        """
        for use_single_migration in [False, True]:

            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                ref_model_name = f'TestMetaIdxFKRef{suffix}'
                model_name = f'TestMetaIdxFK{suffix}'

                operations_a = [
                        migrations.CreateModel(
                            name=ref_model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('name', models.CharField(max_length=50)),
                            ],
                        ),
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('fk_field', models.ForeignKey(
                                    to=f'testapp.{ref_model_name}',
                                    on_delete=models.CASCADE,
                                )),
                                ('other_field', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(fields=['fk_field', 'other_field'], name=f'idx_fk{suffix}'),
                        ),
                    ]

                operations_b = [
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='fk_field',
                            field=models.ForeignKey(
                                to=f'testapp.{ref_model_name}',
                                on_delete=models.SET_NULL,
                                null=True,
                            ),
                        ),
                    ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_mc_fk',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'fk_field_id', 'other_field'},
                    error_msg=(
                        f"Index on ('fk_field', 'other_field') from Meta.indexes was not recreated after FK alteration "
                        f"({self._get_context_description(use_single_migration)}). "
                        f"Expected index to be restored after changing FK from CASCADE to SET_NULL with null=True."
                    ),
                )

    def test_multiple_index_from_meta_indexes_retained(self):
        """
        Test that ALL indexes defined in Meta.indexes are retained when a field participates in multiple indexes.
        A field can be part of multiple different indexes defined in Meta.indexes, and all should be restored
        after altering that field.
        Runs with both split and combined migrations
        """
        for use_single_migration in [False, True]:

            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestMetaMulti{suffix}'

                operations_a = [
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),
                                ('b', models.CharField(max_length=20)),
                                ('c', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(fields=['a', 'b'], name=f'idx_multi_ab{suffix}'),
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(fields=['a', 'c'], name=f'idx_multi_ac{suffix}'),
                        ),
                    ]

                operations_b = [
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='a',
                            field=models.CharField(max_length=40),
                        ),
                    ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_mc_multi',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                # Check that both indexes defined in Meta.indexes were recreated
                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'a', 'b'},
                    error_msg=(
                        f"Index on ('a', 'b') from Meta.indexes was not recreated after field alteration "
                        f"({self._get_context_description(use_single_migration)}). "
                        f"Expected BOTH indexes containing field 'a' to be restored."
                    ),
                )

                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'a', 'c'},
                    error_msg=(
                        f"Index on ('a', 'c') from Meta.indexes was not recreated after field alteration "
                        f"({self._get_context_description(use_single_migration)}). "
                        f"Expected BOTH indexes containing field 'a' to be restored."
                    ),
                )

    def test_index_from_meta_indexes_retained_after_nullability_change_to_not_null(self):
        """
        Test that indexes defined in Meta.indexes are retained when changing field from NULL to NOT NULL.
        This is the reverse direction of the existing nullability test and exercises the
        four-way default alteration path in _alter_field (requires a default value).
        Runs with both split and combined migrations
        """
        for use_single_migration in [False, True]:

            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestMetaIdxNotNull{suffix}'

                operations_a = [
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20, null=True)),
                                ('b', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(fields=['a', 'b'], name=f'idx_notnull{suffix}'),
                        ),
                    ]

                operations_b = [
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='a',
                            field=models.CharField(max_length=20, null=False, default=''),
                        ),
                    ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_mc_notnull',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'a', 'b'},
                    error_msg=(
                        f"Index on ('a', 'b') from Meta.indexes was not recreated after nullability change from NULL to NOT NULL "
                        f"({self._get_context_description(use_single_migration)}). "
                        f"Expected index to be restored after ALTER COLUMN operation with default value handling."
                    ),
                )

    def test_autofield_type_change_preserves_indexes(self):
        """
        Test that indexes defined in Meta.indexes are retained when changing AutoField to BigAutoField.
        This exercises the AutoField/BigAutoField restoration path in _alter_field
        which restores ALL indexes on ALL fields, not just the altered field.
        Runs with both split and combined migrations.
        """
        for use_single_migration in [False, True]:

            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestMetaIdxAutoField{suffix}'

                operations_a = [
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),
                                ('b', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(fields=['a', 'b'], name=f'idx_auto{suffix}'),
                        ),
                    ]

                operations_b = [
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='id',
                            field=models.BigAutoField(primary_key=True),
                        ),
                    ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_mc_auto',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'a', 'b'},
                    error_msg=(
                        f"Index on ('a', 'b') from Meta.indexes was not recreated after AutoField to BigAutoField change "
                        f"({self._get_context_description(use_single_migration)}). "
                        f"Expected index to be restored via AutoField/BigAutoField special restoration path."
                    ),
                )

    def test_autofield_to_bigautofield_with_other_db_index_field_split(self):
        """
        Test that changing AutoField to BigAutoField preserves db_index=True indexes
        on other fields when operations are in separate migrations.

        This test verifies the split migration case works correctly - the index is
        created and committed in the first migration before the AutoField alteration
        runs in the second migration.
        """
        model_name = 'TestAutoDbIndex_split'

        operations_a = [
            migrations.CreateModel(
                name=model_name,
                fields=[
                    ('id', models.AutoField(primary_key=True)),
                    ('name', models.CharField(max_length=100, db_index=True)),
                    ('other', models.CharField(max_length=100)),
                ],
            ),
        ]

        operations_b = [
            migrations.AlterField(
                model_name=model_name.lower(),
                name='id',
                field=models.BigAutoField(primary_key=True),
            ),
        ]

        result = self._run_migration_test(
            operations_a=operations_a,
            operations_b=operations_b,
            migration_name_prefix='test_auto_dbindex',
            model_name=model_name,
            use_single_migration=False,
        )

        # Verify db_index=True index on 'name' was retained
        self._assert_index_exists(
            result.constraints,
            expected_columns={'name'},
            error_msg=(
                "db_index=True index on 'name' was not retained after AutoField to BigAutoField change "
                "(split into 2 migrations). Expected index to be preserved."
            ),
        )

    def test_autofield_to_bigautofield_with_other_db_index_field_combined(self):
        """
        Test that changing AutoField to BigAutoField preserves db_index=True indexes
        on other fields when operations are in a single (combined) migration.

        This tests that the deduplication logic in _alter_field works correctly:
        when CreateModel queues a db_index in deferred_sql and the AutoField
        restoration code runs, it should skip creating duplicate indexes.
        """
        model_name = 'TestAutoDbIndex_combined'

        operations_a = [
            migrations.CreateModel(
                name=model_name,
                fields=[
                    ('id', models.AutoField(primary_key=True)),
                    ('name', models.CharField(max_length=100, db_index=True)),
                    ('other', models.CharField(max_length=100)),
                ],
            ),
        ]

        operations_b = [
            migrations.AlterField(
                model_name=model_name.lower(),
                name='id',
                field=models.BigAutoField(primary_key=True),
            ),
        ]

        result = self._run_migration_test(
            operations_a=operations_a,
            operations_b=operations_b,
            migration_name_prefix='test_auto_dbindex',
            model_name=model_name,
            use_single_migration=True,
        )

        # Verify db_index=True index on 'name' was retained
        self._assert_index_exists(
            result.constraints,
            expected_columns={'name'},
            error_msg=(
                "db_index=True index on 'name' was not retained after AutoField to BigAutoField change "
                "(combined into 1 migration). Expected index to be preserved."
            ),
        )

    @skipIf(VERSION >= (5, 1), "index_together is removed in Django 5.1+")
    def test_index_together_retained_after_autofield_change(self):
        """
        Test that index_together indexes are retained when changing AutoField to BigAutoField.

        This tests the index_together restoration path in _alter_field for AutoField changes.
        Since AutoField changes drop ALL indexes on the table, the restoration code must
        also restore ALL index_together indexes, not just those involving the altered field.

        Note: index_together is deprecated in Django 4.2 and removed in Django 5.1+.
        This test only runs on Django < 5.1.
        """
        for use_single_migration in [False, True]:

            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestIdxTogetherAuto{suffix}'

                # Create model with index_together using the deprecated Meta option
                # We need to use a raw SQL approach or create the model dynamically
                # since Django's migration system handles index_together
                operations_a = [
                    migrations.CreateModel(
                        name=model_name,
                        fields=[
                            ('id', models.AutoField(primary_key=True)),
                            ('a', models.CharField(max_length=20)),
                            ('b', models.CharField(max_length=20)),
                        ],
                        options={
                            'index_together': {('a', 'b')},
                        },
                    ),
                ]

                operations_b = [
                    migrations.AlterField(
                        model_name=model_name.lower(),
                        name='id',
                        field=models.BigAutoField(primary_key=True),
                    ),
                ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_idx_together_auto',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'a', 'b'},
                    error_msg=(
                        f"index_together index on ('a', 'b') was not recreated after AutoField to BigAutoField change "
                        f"({self._get_context_description(use_single_migration)}). "
                        f"Expected index to be restored via AutoField restoration path."
                    ),
                )

    def test_pk_type_change_preserves_indexes(self):
        """
        Test that indexes defined in Meta.indexes are retained when changing primary key type.
        This tests the primary key restoration path alongside the restoration of indexes from Meta.indexes.
        Runs with both split and combined migrations
        """
        for use_single_migration in [False, True]:

            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestMetaIdxPK{suffix}'

                operations_a = [
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),
                                ('b', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(fields=['id', 'a'], name=f'idx_pk{suffix}'),
                        ),
                    ]

                operations_b = [
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='id',
                            field=models.BigAutoField(primary_key=True),
                        ),
                    ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_mc_pk',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                # Verify primary key still exists
                pk_constraints = [
                    info for info in result.constraints.values()
                    if info.get('primary_key')
                ]
                self.assertTrue(
                    len(pk_constraints) > 0,
                    f"Primary key was not restored ({self._get_context_description(use_single_migration)})."
                )

                # Verify index from Meta.indexes including PK column was restored
                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'id', 'a'},
                    error_msg=(
                        f"Index on ('id', 'a') from Meta.indexes was not recreated after PK type change "
                        f"({self._get_context_description(use_single_migration)}). "
                        f"Expected index containing PK column to be restored."
                    ),
                )

    @skipIf(VERSION >= (5, 1), "index_together removed in Django 5.1")
    def test_index_together_retained_after_type_change(self):
        """
        Test that index_together indexes are retained when altering a field type.

        IMPORTANT: This test documents the known limitation that index_together is only
        restored when the field does NOT have db_index=True. If a field has both
        db_index=True AND is in index_together, only the index from db_index=True is restored
        through the standard restoration path. This is intentional behavior for the
        deprecated index_together API (removed in Django 5.1+).

        This test uses a field WITHOUT db_index=True to verify the index_together
        restoration works in that scenario.

        Runs with both split and combined migrations
        """
        for use_single_migration in [False, True]:

            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestIdxTogether{suffix}'

                operations_a = [
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),  # No db_index=True
                                ('b', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AlterIndexTogether(
                            name=model_name.lower(),
                            index_together={('a', 'b')},
                        ),
                    ]

                operations_b = [
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='a',
                            field=models.CharField(max_length=40),
                        ),
                    ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_idxtog',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                # Verify index_together index was restored
                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'a', 'b'},
                    error_msg=(
                        f"index_together index on ('a', 'b') was not recreated after type change "
                        f"({self._get_context_description(use_single_migration)}). "
                        f"Expected index_together to be restored for field without db_index=True."
                    ),
                )
    def test_stale_meta_index_not_retargeted_by_autofield_change(self):
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestStaleIndexAuto{suffix}'
                index_name = f'idx_stale_auto{suffix}'
                result = self._run_migration_test(
                    operations_a=[
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(fields=['a'], name=index_name),
                        ),
                    ],
                    operations_b=[
                        migrations.RenameField(
                            model_name=model_name.lower(), old_name='a', new_name='aa'
                        ),
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='id',
                            field=models.BigAutoField(primary_key=True),
                        ),
                    ],
                    migration_name_prefix='test_stale_index_auto',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )
                self._assert_named_index_columns(
                    result.constraints,
                    index_name,
                    ['aa'],
                    'A stale Meta.indexes field was retargeted during an AutoField change.',
                )

    def test_stale_meta_index_reconciles_reused_field_name(self):
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestReusedIndexField{suffix}'
                index_name = f'idx_reused_field{suffix}'
                result = self._run_migration_test(
                    operations_a=[
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(fields=['a'], name=index_name),
                        ),
                    ],
                    operations_b=[
                        migrations.RenameField(
                            model_name=model_name.lower(), old_name='a', new_name='aa'
                        ),
                        migrations.AddField(
                            model_name=model_name.lower(),
                            name='a',
                            field=models.CharField(max_length=20),
                        ),
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='aa',
                            field=models.CharField(max_length=40),
                        ),
                    ],
                    migration_name_prefix='test_reused_index_field',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )
                self._assert_named_index_columns(
                    result.constraints,
                    index_name,
                    ['aa'],
                    'A stale Meta.indexes field was not reconciled after its old name was reused.',
                )

    def test_removed_meta_index_not_retargeted_by_unrelated_alter(self):
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestRemovedIndex{suffix}'
                index_name = f'idx_removed{suffix}'
                result = self._run_migration_test(
                    operations_a=[
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),
                                ('b', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(fields=['a'], name=index_name),
                        ),
                    ],
                    operations_b=[
                        migrations.RemoveField(model_name=model_name.lower(), name='a'),
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='b',
                            field=models.CharField(max_length=40),
                        ),
                    ],
                    migration_name_prefix='test_removed_index',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )
                self.assertNotIn(
                    index_name,
                    result.constraints,
                    'A removed Meta.indexes definition was recreated on an unrelated field.',
                )

    def test_meta_index_restored_after_multiple_renames(self):
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestMultipleRenames{suffix}'
                index_name = f'idx_multiple_renames{suffix}'
                result = self._run_migration_test(
                    operations_a=[
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),
                                ('b', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(fields=['a', 'b'], name=index_name),
                        ),
                    ],
                    operations_b=[
                        migrations.RenameField(
                            model_name=model_name.lower(), old_name='a', new_name='aa'
                        ),
                        migrations.RenameField(
                            model_name=model_name.lower(), old_name='b', new_name='bb'
                        ),
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='aa',
                            field=models.CharField(max_length=40),
                        ),
                    ],
                    migration_name_prefix='test_multiple_renames',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )
                self._assert_named_index_columns(
                    result.constraints,
                    index_name,

                    ['aa', 'bb'],
                    'A composite Meta.indexes definition was not restored after multiple renames.',
                )
    def test_filtered_meta_index_restored_after_multiple_renames(self):
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestFilteredMultipleRenames{suffix}'
                index_name = f'idx_filtered_multiple{suffix}'
                result = self._run_migration_test(
                    operations_a=[
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),
                                ('c', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(
                                fields=['a'],
                                condition=models.Q(c__isnull=False),
                                name=index_name,
                            ),
                        ),
                        migrations.RenameField(
                            model_name=model_name.lower(), old_name='a', new_name='aa'
                        ),
                    ],
                    operations_b=[
                        migrations.RenameField(
                            model_name=model_name.lower(), old_name='c', new_name='cc'
                        ),
                    ],
                    migration_name_prefix='test_filtered_multiple_renames',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )
                self._assert_named_index_columns(
                    result.constraints,
                    index_name,
                    ['aa'],
                    'A filtered Meta.indexes key was not restored after multiple renames.',
                )
                filter_definition = self._get_index_catalog(result.model, index_name)[0][2]
                self.assertIn('[cc]', filter_definition)
                self.assertNotIn('[c]', filter_definition)

    def test_filtered_meta_index_preserves_literal_after_field_rename(self):
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestFilteredLiteral{suffix}'
                index_name = f'idx_filtered_literal{suffix}'
                result = self._run_migration_test(
                    operations_a=[
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),
                                ('b', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(
                                fields=['b'],
                                condition=models.Q(a='[a]'),
                                name=index_name,
                            ),
                        ),
                    ],
                    operations_b=[
                        migrations.RenameField(
                            model_name=model_name.lower(), old_name='a', new_name='aa'
                        ),
                    ],
                    migration_name_prefix='test_filtered_literal',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )
                filter_definition = self._get_index_catalog(result.model, index_name)[0][2]
                self.assertIn('[aa]', filter_definition)
                self.assertIn("'[a]'", filter_definition)
                self.assertNotIn("'[aa]'", filter_definition)
    @skipUnless(VERSION >= (4, 0), "Django 4.0+ ProjectState.rename_field support")
    def test_filtered_meta_index_ignores_bracketed_literal(self):
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestBracketedLiteral{suffix}'
                index_name = f'idx_bracketed_literal{suffix}'
                result = self._run_migration_test(
                    operations_a=[
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),
                                ('b', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(
                                fields=['b'],
                                condition=models.Q(a='[b]'),
                                name=index_name,
                            ),
                        ),
                    ],
                    operations_b=[
                        migrations.RenameField(
                            model_name=model_name.lower(), old_name='a', new_name='aa'
                        ),
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='b',
                            field=models.CharField(max_length=40),
                        ),
                    ],
                    migration_name_prefix='test_bracketed_literal',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )
                catalog = self._get_index_catalog(result.model, index_name)
                self._assert_named_index_columns(
                    result.constraints,
                    index_name,
                    ['b'],
                    'A filtered Meta.indexes key was not restored after an unrelated rename.',
                )
                self.assertIn('[aa]', catalog[0][2])
                self.assertIn("'[b]'", catalog[0][2])
                self.assertNotIn("'[aa]'", catalog[0][2])

    def test_deferred_filtered_meta_index_after_field_rename(self):
        """
        A filtered Meta.indexes condition remains structured until deferred SQL
        executes, so a following RenameField updates its identifier only.
        """
        migration = Migration('test_deferred_filtered_index', 'testapp')
        migration.operations = [
            migrations.CreateModel(
                name='TestDeferredFilteredIndex',
                fields=[
                    ('id', models.AutoField(primary_key=True)),
                    ('a', models.CharField(max_length=20)),
                    ('b', models.CharField(max_length=20)),
                ],
                options={
                    'indexes': [
                        models.Index(
                            fields=['b'],
                            condition=models.Q(a='[a]'),
                            name='idx_deferred_filtered',
                        ),
                    ],
                },
            ),
            migrations.RenameField(
                model_name='testdeferredfilteredindex', old_name='a', new_name='aa'
            ),
        ]
        conn = django.db.connections[django.db.DEFAULT_DB_ALIAS]
        with patch.object(conn.features, 'connection_persists_old_columns', False):
            with conn.schema_editor(collect_sql=True, atomic=False) as editor:
                migration.apply(ProjectState(), editor)
        index_sql = next(sql for sql in editor.collected_sql if 'idx_deferred_filtered' in sql)
        self.assertIn('[aa]', index_sql)
        self.assertIn("'[a]'", index_sql)

    def test_deferred_filtered_meta_index_after_field_rename_executes(self):
        index_name = 'idx_deferred_filtered_execution'
        result = self._run_migration_test(
            operations_a=[
                migrations.CreateModel(
                    name='TestDeferredFilteredIndexExecution',
                    fields=[
                        ('id', models.AutoField(primary_key=True)),
                        ('a', models.CharField(max_length=20)),
                        ('b', models.CharField(max_length=20)),
                    ],
                    options={
                        'indexes': [
                            models.Index(
                                fields=['b'],
                                condition=models.Q(a='[a]'),
                                name=index_name,
                            ),
                        ],
                    },
                ),
            ],
            operations_b=[
                migrations.RenameField(
                    model_name='testdeferredfilteredindexexecution',
                    old_name='a',
                    new_name='aa',
                ),
            ],
            migration_name_prefix='test_deferred_filtered_index_execution',
            model_name='TestDeferredFilteredIndexExecution',
            use_single_migration=True,
        )
        filter_definition = self._get_index_catalog(result.model, index_name)[0][2]
        self.assertIn('[aa]', filter_definition)
        self.assertIn("'[a]'", filter_definition)

    def test_deferred_conditional_unique_constraint_after_field_rename(self):
        index_name = 'idx_deferred_conditional_unique_rename'
        result = self._run_migration_test(
            operations_a=[
                migrations.CreateModel(
                    name='TestDeferredConditionalUniqueRename',
                    fields=[
                        ('id', models.AutoField(primary_key=True)),
                        ('a', models.CharField(max_length=20)),
                        ('b', models.CharField(max_length=20)),
                    ],
                    options={
                        'constraints': [
                            UniqueConstraint(
                                fields=['b'],
                                condition=models.Q(a='[a]'),
                                name=index_name,
                            ),
                        ],
                    },
                ),
            ],
            operations_b=[
                migrations.RenameField(
                    model_name='testdeferredconditionaluniquerename',
                    old_name='a',
                    new_name='aa',
                ),
            ],
            migration_name_prefix='test_deferred_conditional_unique_rename',
            model_name='TestDeferredConditionalUniqueRename',
            use_single_migration=True,
        )
        self._assert_named_index_columns(
            result.constraints,
            index_name,
            ['b'],
            'A deferred conditional unique constraint was not created as an index.',
        )
        filter_definition = self._get_index_catalog(result.model, index_name)[0][2]
        self.assertIn('[aa]', filter_definition)
        self.assertIn("'[a]'", filter_definition)
        self.assertNotIn("'[aa]'", filter_definition)

    def test_filtered_meta_index_condition_only_rename_before_unrelated_alter(self):
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestConditionOnlyRename{suffix}'
                index_name = f'idx_condition_only_rename{suffix}'
                result = self._run_migration_test(
                    operations_a=[
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),
                                ('b', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(
                                fields=['b'],
                                condition=models.Q(a__isnull=False),
                                name=index_name,
                            ),
                        ),
                    ],
                    operations_b=[
                        migrations.RenameField(
                            model_name=model_name.lower(), old_name='a', new_name='aa'
                        ),
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='b',
                            field=models.CharField(max_length=40),
                        ),
                    ],
                    migration_name_prefix='test_condition_only_rename',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )
                self._assert_named_index_columns(
                    result.constraints,
                    index_name,
                    ['b'],
                    'A predicate-only filtered Meta.index was not restored after a rename.',
                )
                filter_definition = self._get_index_catalog(result.model, index_name)[0][2]
                self.assertIn('[aa]', filter_definition)
                self.assertNotIn('[a]', filter_definition)

    @skipUnless(VERSION >= (4, 0), "Django 4.0+ ProjectState.rename_field support")
    def test_filtered_meta_index_retained_after_rename_and_alter(self):
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestFilteredIndex{suffix}'
                index_name = f'idx_filtered{suffix}'
                result = self._run_migration_test(
                    operations_a=[
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20, null=True)),
                                ('b', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(
                                fields=['b'],
                                condition=models.Q(a__isnull=False),
                                name=index_name,
                            ),
                        ),
                    ],
                    operations_b=[
                        migrations.RenameField(
                            model_name=model_name.lower(), old_name='a', new_name='aa'
                        ),
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='b',
                            field=models.CharField(max_length=40),
                        ),
                    ],
                    migration_name_prefix='test_filtered_index',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )
                catalog = self._get_index_catalog(result.model, index_name)
                self.assertIn('[aa]', catalog[0][2])
    @skipUnless(VERSION >= (4, 0), "Django 4.0+ ProjectState.rename_field support")
    def test_filtered_meta_index_retained_across_migration_rename(self):
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestFilteredIndexAcrossRename{suffix}'
                index_name = f'idx_filtered_across_rename{suffix}'
                result = self._run_migration_test(
                    operations_a=[
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20, null=True)),
                                ('b', models.CharField(max_length=20)),
                                ('c', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(
                                fields=['b'],
                                include=['c'],
                                condition=models.Q(a__isnull=False),
                                name=index_name,
                            ),
                        ),
                    ],
                    operations_b=[
                        migrations.RenameField(
                            model_name=model_name.lower(), old_name='a', new_name='aa'
                        ),
                    ],
                    operations_c=[
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='b',
                            field=models.CharField(max_length=40),
                        ),
                    ],
                    migration_name_prefix='test_filtered_index_across_rename',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )
                self.assertIn(index_name, result.constraints)
                catalog = self._get_index_catalog(result.model, index_name)
                self.assertEqual(
                    [column for included, column, _ in catalog if not included], ['b']
                )
                filter_definition = catalog[0][2]
                self.assertIn((True, 'c', filter_definition), catalog)
                self.assertIn('[aa]', filter_definition)

    @skipUnless(VERSION >= (4, 0), "Django 4.0+ ProjectState.rename_field support")
    def test_filtered_meta_index_survives_reconstructed_rename_state(self):
        """
        MigrationExecutor startup rebuilds applied-migration state without replaying
        DDL, unlike the existing across-migration rename test.
        """
        class MigrationA(Migration):
            initial = True
            operations = [
                migrations.CreateModel(
                    name='TestFilteredIndexReconstructed',
                    fields=[
                        ('id', models.AutoField(primary_key=True)),
                        ('a', models.CharField(max_length=20, null=True)),
                        ('b', models.CharField(max_length=20)),
                    ],
                ),
                migrations.AddIndex(
                    model_name='testfilteredindexreconstructed',
                    index=models.Index(
                        fields=['b'],
                        condition=models.Q(a__isnull=False),
                        name='idx_filtered_reconstructed',
                    ),
                ),
            ]

        class MigrationB(Migration):
            operations = [
                migrations.RenameField(
                    model_name='testfilteredindexreconstructed',
                    old_name='a',
                    new_name='aa',
                ),
            ]

        class MigrationC(Migration):
            operations = [
                migrations.AlterField(
                    model_name='testfilteredindexreconstructed',
                    name='b',
                    field=models.CharField(max_length=40),
                ),
            ]

        migration_a = MigrationA('test_filtered_index_reconstructed_a', 'testapp')
        migration_b = MigrationB('test_filtered_index_reconstructed_b', 'testapp')
        migration_c = MigrationC('test_filtered_index_reconstructed_c', 'testapp')
        conn = django.db.connections[django.db.DEFAULT_DB_ALIAS]

        with conn.schema_editor(atomic=True) as editor:
            applied_state = migration_a.apply(ProjectState(), editor)
        with conn.schema_editor(atomic=True) as editor:
            migration_b.apply(applied_state, editor)

        # Deliberately bypass Migration.apply(), as MigrationExecutor does while
        # rebuilding applied state through mutate_state().
        rebuilt_state = migration_a.mutate_state(ProjectState())
        rebuilt_state = migration_b.mutate_state(rebuilt_state)
        with conn.schema_editor(atomic=True) as editor:
            project_state = migration_c.apply(rebuilt_state, editor)

        model = project_state.apps.get_model('testapp', 'TestFilteredIndexReconstructed')
        constraints = get_constraints(table_name=model._meta.db_table)
        self._assert_named_index_columns(
            constraints,
            'idx_filtered_reconstructed',
            ['b'],
            'A reconstructed filtered Meta.index was not restored after a rename.',
        )
        catalog = self._get_index_catalog(model, 'idx_filtered_reconstructed')
        self.assertIn('[aa]', catalog[0][2])

    @skipUnless(VERSION >= (4, 0), "Django 4.0+ ProjectState.rename_field support")
    def test_filtered_meta_index_retained_after_logical_rename(self):
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestFilteredIndexLogicalRename{suffix}'
                index_name = f'idx_filtered_logical_rename{suffix}'
                result = self._run_migration_test(
                    operations_a=[
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                (
                                    'a',
                                    models.CharField(
                                        max_length=20,
                                        null=True,
                                        db_column='stable_a',
                                    ),
                                ),
                                ('b', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(
                                fields=['b'],
                                condition=models.Q(a__isnull=False),
                                name=index_name,
                            ),
                        ),
                    ],
                    operations_b=[
                        migrations.RenameField(
                            model_name=model_name.lower(), old_name='a', new_name='aa'
                        ),
                    ],
                    operations_c=[
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='b',
                            field=models.CharField(max_length=40),
                        ),
                    ],
                    migration_name_prefix='test_filtered_index_logical_rename',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )
                self._assert_named_index_columns(
                    result.constraints,
                    index_name,
                    ['b'],
                    'A logical rename did not update the filtered Meta.index reference.',
                )
                self.assertIn(
                    '[stable_a]', self._get_index_catalog(result.model, index_name)[0][2]
                )

    def test_readded_meta_index_does_not_inherit_rename_replacements(self):
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestReaddedFilteredIndex{suffix}'
                index_name = f'idx_readded_filtered{suffix}'
                result = self._run_migration_test(
                    operations_a=[
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20, null=True)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(
                                fields=['a'],
                                condition=models.Q(a__isnull=False),
                                name=index_name,
                            ),
                        ),
                    ],
                    operations_b=[
                        migrations.RenameField(
                            model_name=model_name.lower(), old_name='a', new_name='aa'
                        ),
                        migrations.AddField(
                            model_name=model_name.lower(),
                            name='a',
                            field=models.CharField(max_length=20, null=True),
                        ),
                        migrations.RemoveIndex(
                            model_name=model_name.lower(), name=index_name
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(
                                fields=['a'],
                                condition=models.Q(a__isnull=False),
                                name=index_name,
                            ),
                        ),
                    ],
                    operations_c=[
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='aa',
                            field=models.CharField(max_length=40, null=True),
                        ),
                    ],
                    migration_name_prefix='test_readded_filtered_index',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )
                self._assert_named_index_columns(
                    result.constraints,
                    index_name,
                    ['a'],
                    'A re-added Meta index inherited replacements from a removed index.',
                )
                filter_definition = self._get_index_catalog(result.model, index_name)[0][2]
                self.assertIn('[a]', filter_definition)
                self.assertNotIn('[aa]', filter_definition)

    def test_filtered_fk_meta_index_restored_after_constraint_removal(self):
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                parent_model_name = f'TestFilteredFkParent{suffix}'
                model_name = f'TestFilteredFkChild{suffix}'
                index_name = f'idx_filtered_fk{suffix}'
                parent_model = f'testapp.{parent_model_name}'
                result = self._run_migration_test(
                    operations_a=[
                        migrations.CreateModel(
                            name=parent_model_name,
                            fields=[('id', models.AutoField(primary_key=True))],
                        ),
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                (
                                    'parent',
                                    models.ForeignKey(
                                        parent_model,
                                        on_delete=models.CASCADE,
                                    ),
                                ),
                                ('flag', models.CharField(max_length=20, null=True)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(
                                fields=['parent'],
                                condition=models.Q(flag__isnull=False),
                                name=index_name,
                            ),
                        ),
                    ],
                    operations_b=[
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='parent',
                            field=models.ForeignKey(
                                parent_model,
                                db_constraint=False,
                                null=True,
                                on_delete=models.CASCADE,
                            ),
                        ),
                    ],
                    migration_name_prefix='test_filtered_fk_index',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )
                self._assert_named_index_columns(
                    result.constraints,
                    index_name,
                    ['parent_id'],
                    'A filtered FK Meta index was not restored after its constraint dropped.',
                )
                self.assertIn(
                    '[flag]', self._get_index_catalog(result.model, index_name)[0][2]
                )

    @skipUnless(VERSION >= (4, 0), "Django 4.0+ expression conditions")
    def test_filtered_meta_index_tracks_tuple_rhs_expression(self):
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestTupleRhsFilteredIndex{suffix}'
                index_name = f'idx_tuple_rhs_filtered{suffix}'
                operations_a = [
                    migrations.CreateModel(
                        name=model_name,
                        fields=[
                            ('id', models.AutoField(primary_key=True)),
                            ('a', models.CharField(max_length=20)),
                            ('b', models.CharField(max_length=20)),
                            ('c', models.CharField(max_length=20)),
                        ],
                    ),
                    migrations.AddIndex(
                        model_name=model_name.lower(),
                        index=models.Index(
                            fields=['c'],
                            condition=models.Q(a=models.F('b')),
                            name=index_name,
                        ),
                    ),
                ]
                operations_b = [
                    migrations.RenameField(
                        model_name=model_name.lower(), old_name='a', new_name='aa'
                    ),
                    migrations.RenameField(
                        model_name=model_name.lower(), old_name='b', new_name='bb'
                    ),
                ]
                operations_c = [
                    migrations.AlterField(
                        model_name=model_name.lower(),
                        name='c',
                        field=models.CharField(max_length=40),
                    ),
                ]
                conn = django.db.connections[django.db.DEFAULT_DB_ALIAS]
                with patch.object(conn.features, 'connection_persists_old_columns', False):
                    if use_single_migration:
                        class CombinedMigration(migrations.Migration):
                            initial = True
                            operations = operations_a + operations_b + operations_c

                        migration = CombinedMigration(
                            name=f'test_tuple_rhs_filtered{suffix}', app_label='testapp'
                        )
                        with conn.schema_editor(collect_sql=True, atomic=False) as editor:
                            project_state = migration.apply(ProjectState(), editor)
                            model = project_state.apps.get_model('testapp', model_name)
                            index = next(
                                index for index in model._meta.indexes
                                if index.name == index_name
                            )
                            self.assertEqual(
                                editor._get_condition_field_names(index.condition), ['aa', 'bb']
                            )
                            editor.execute(
                                _clone_index_with_replacements(index, {}).create_sql(
                                    model, editor
                                )
                            )
                    else:
                        class MigrationA(migrations.Migration):
                            initial = True
                            operations = operations_a

                        class MigrationB(migrations.Migration):
                            operations = operations_b

                        class MigrationC(migrations.Migration):
                            operations = operations_c

                        with conn.schema_editor(collect_sql=True, atomic=False) as editor_a:
                            project_state = MigrationA(
                                name=f'test_tuple_rhs_filtered{suffix}_a', app_label='testapp'
                            ).apply(ProjectState(), editor_a)
                        with conn.schema_editor(collect_sql=True, atomic=False) as editor_b:
                            project_state = MigrationB(
                                name=f'test_tuple_rhs_filtered{suffix}_b', app_label='testapp'
                            ).apply(project_state, editor_b)
                        with conn.schema_editor(collect_sql=True, atomic=False) as editor:
                            project_state = MigrationC(
                                name=f'test_tuple_rhs_filtered{suffix}_c', app_label='testapp'
                            ).apply(project_state, editor)
                            model = project_state.apps.get_model('testapp', model_name)
                            index = next(
                                index for index in model._meta.indexes
                                if index.name == index_name
                            )
                            self.assertEqual(
                                editor._get_condition_field_names(index.condition), ['aa', 'bb']
                            )
                            editor.execute(
                                _clone_index_with_replacements(index, {}).create_sql(
                                    model, editor
                                )
                            )
                index_sql = editor.collected_sql[-1]
                self.assertIn('[aa]', index_sql)
                self.assertIn('[bb]', index_sql)
                self.assertIn('[c]', index_sql)

    @skipUnless(VERSION >= (4, 0), "Django 4.0+ ProjectState.rename_field support")
    def test_expression_filtered_meta_index_retained_after_rename_and_alter(self):
        """
        Field references nested in positional lookup expressions must be updated
        when a rename precedes an alteration that recreates the filtered index.
        """
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestExpressionFilteredRename{suffix}'
                index_name = f'idx_expression_rename{suffix}'
                result = self._run_migration_test(
                    operations_a=[
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),
                                ('b', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(
                                fields=['b'],
                                condition=models.Q(Exact(models.F('a'), models.Value('value'))),
                                name=index_name,
                            ),
                        ),
                    ],
                    operations_b=[
                        migrations.RenameField(
                            model_name=model_name.lower(), old_name='a', new_name='aa'
                        ),
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='b',
                            field=models.CharField(max_length=40),
                        ),
                    ],
                    migration_name_prefix='test_expression_filtered_rename',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )
                self.assertIn('[aa]', self._get_index_catalog(result.model, index_name)[0][2])

    def test_covering_meta_index_retained_after_rename_and_alter(self):
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestCoveringIndex{suffix}'
                index_name = f'idx_covering{suffix}'
                result = self._run_migration_test(
                    operations_a=[
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),
                                ('b', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(fields=['b'], include=['a'], name=index_name),
                        ),
                    ],
                    operations_b=[
                        migrations.RenameField(
                            model_name=model_name.lower(), old_name='a', new_name='aa'
                        ),
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='aa',
                            field=models.CharField(max_length=40),
                        ),
                    ],
                    migration_name_prefix='test_covering_index',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )
                catalog = self._get_index_catalog(result.model, index_name)
                self.assertIn((False, 'b', None), catalog)
                self.assertIn((True, 'aa', None), catalog)

    @skipUnless(VERSION >= (4, 0), "Django 4.0+ expression conditions")
    def test_expression_filtered_meta_index_retained_after_alter(self):
        """
        A filtered Meta index may use a positional lookup expression instead of
        a keyword-style Q tuple. Ensure altering its key field preserves the
        index and doesn't treat the Exact expression as a subscriptable tuple.
        """
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestExpressionFilteredIndex{suffix}'
                index_name = f'idx_expression_filtered{suffix}'
                result = self._run_migration_test(
                    operations_a=[
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20)),
                                ('b', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AddIndex(
                            model_name=model_name.lower(),
                            index=models.Index(
                                fields=['b'],
                                condition=models.Q(Exact(models.F('a'), models.Value('value'))),
                                name=index_name,
                            ),
                        ),
                    ],
                    operations_b=[
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='b',
                            field=models.CharField(max_length=40),
                        ),
                    ],
                    migration_name_prefix='test_expression_filtered_index',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )
                self.assertIn('[a]', self._get_index_catalog(result.model, index_name)[0][2])

    @expectedFailure
    def test_unique_together_retained_when_field_also_has_unique_true(self):
        """
        Test that unique_together constraints are retained when a field with unique=True is altered.

        KNOWN BUG: When a field has BOTH unique=True AND participates in unique_together,
        only the single-field unique constraint is restored after field alteration.
        The unique_together constraint is NOT restored because the unique_together restoration is in an
        'else' block that only executes when the field does NOT have unique=True.

        Runs with both split and combined migrations
        """
        for use_single_migration in [False, True]:

            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestUniqueAndUniqTogether{suffix}'

                operations_a = [
                        migrations.CreateModel(
                            name=model_name,
                            fields=[
                                ('id', models.AutoField(primary_key=True)),
                                ('a', models.CharField(max_length=20, unique=True)),
                                ('b', models.CharField(max_length=20)),
                            ],
                        ),
                        migrations.AlterUniqueTogether(
                            name=model_name.lower(),
                            unique_together={('a', 'b')},
                        ),
                    ]

                operations_b = [
                        migrations.AlterField(
                            model_name=model_name.lower(),
                            name='a',
                            field=models.CharField(max_length=40, unique=True),
                        ),
                    ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_uniq_uniqtog',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                # Check that single-field unique constraint on 'a' was restored
                single_unique_constraints = [
                    info for info in result.constraints.values()
                    if info.get('unique') and set(info['columns']) == {'a'}
                ]
                self.assertTrue(
                    len(single_unique_constraints) > 0,
                    f"Single-field unique constraint on 'a' was not restored "
                    f"({self._get_context_description(use_single_migration)})."
                )

                # Check that unique_together constraint on ('a', 'b') was restored
                # THIS ASSERTION WILL FAIL due to the bug in mssql/schema.py lines 838-871
                unique_together_constraints = [
                    info for info in result.constraints.values()
                    if info.get('unique') and set(info['columns']) == {'a', 'b'}
                ]
                self.assertTrue(
                    len(unique_together_constraints) > 0,
                    f"unique_together constraint on ('a', 'b') was not restored when field 'a' has unique=True "
                    f"({self._get_context_description(use_single_migration)}). "
                    f"This is a bug in mssql/schema.py: unique_together restoration is in an 'else' block "
                    f"that only executes when the field does NOT have unique=True."
                )

    def test_plain_meta_index_retained_after_combined_rename_and_alter(self):
        """
        A single AlterField that changes both db_column (rename) and max_length
        (type) on the same field must not drop a plain (non-conditional)
        Meta.indexes entry referencing that field without recreating it.

        Unlike RenameField (which never changes type/null in the same
        operation), AlterField can combine a db_column rename with a type
        change in one call - this is the repro shape for this regression.
        """
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestPlainCombinedRename{suffix}'
                index_name = f'idx_plain_combined_rename{suffix}'

                operations_a = [
                    migrations.CreateModel(
                        name=model_name,
                        fields=[
                            ('id', models.AutoField(primary_key=True)),
                            ('a', models.CharField(max_length=20)),
                            ('b', models.CharField(max_length=20)),
                        ],
                    ),
                    migrations.AddIndex(
                        model_name=model_name.lower(),
                        index=models.Index(fields=['b'], name=index_name),
                    ),
                ]

                operations_b = [
                    migrations.AlterField(
                        model_name=model_name.lower(),
                        name='b',
                        field=models.CharField(max_length=40, db_column='bb'),
                    ),
                ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_plain_combined_rename',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                self._assert_named_index_columns(
                    result.constraints, index_name, ['bb'],
                    "A plain Meta.index was dropped and not restored after "
                    "a combined db_column rename and type change "
                    f"({self._get_context_description(use_single_migration)})."
                )

    def test_conditional_unique_constraint_removable_after_rename(self):
        """
        RenameField rewrites structured Meta.indexes state but not
        Meta.constraints (UniqueConstraint.condition/fields/include), leaving a
        stale field reference that raises FieldError when a later operation
        (e.g. RemoveConstraint) renders it.

        Uses split migrations (each operation committed in its own
        schema_editor context) so the filtered unique index physically exists
        before the rename, exercising the real rename-time DDL path rather
        than racing CreateModel's deferred index-creation SQL.
        """
        model_name = 'TestStaleConstraintRename'
        constraint_name = 'uq_stale_rename'

        operations_a = [
            migrations.CreateModel(
                name=model_name,
                fields=[
                    ('id', models.AutoField(primary_key=True)),
                    ('a', models.CharField(max_length=20)),
                    ('b', models.CharField(max_length=20)),
                ],
                options={
                    'constraints': [
                        UniqueConstraint(
                            fields=['b'],
                            condition=models.Q(a__isnull=False),
                            name=constraint_name,
                        ),
                    ],
                },
            ),
        ]
        operations_b = [
            migrations.RenameField(
                model_name=model_name.lower(), old_name='a', new_name='aa'
            ),
        ]
        operations_c = [
            migrations.RemoveConstraint(
                model_name=model_name.lower(), name=constraint_name
            ),
        ]

        result = self._run_migration_test(
            operations_a=operations_a,
            operations_b=operations_b,
            operations_c=operations_c,
            migration_name_prefix='test_stale_constraint_rename',
            model_name=model_name,
            use_single_migration=False,
        )

        self.assertNotIn(constraint_name, result.constraints)

    def test_squashed_create_model_rename_field_retains_meta_index(self):
        """
        When Django's migration optimizer folds a RenameField into a
        preceding CreateModel (e.g. via squashmigrations, or autodetector-side
        optimization within one makemigrations run), CreateModel.reduce()
        rewrites only unique_together/index_together in its absorbed options,
        never the structured Meta.indexes/.constraints - so a folded
        CreateModel keeps referencing the pre-rename field name.
        """
        from django.db.migrations.optimizer import MigrationOptimizer

        model_name = 'TestSquashedRenameIndex'
        index_name = 'idx_squashed_rename'
        operations = [
            migrations.CreateModel(
                name=model_name,
                fields=[
                    ('id', models.AutoField(primary_key=True)),
                    ('a', models.CharField(max_length=20)),
                    ('b', models.CharField(max_length=20)),
                ],
                options={
                    'indexes': [
                        models.Index(
                            fields=['b'],
                            condition=models.Q(a__isnull=False),
                            name=index_name,
                        ),
                    ],
                },
            ),
            migrations.RenameField(
                model_name=model_name.lower(), old_name='a', new_name='aa'
            ),
        ]
        optimized = MigrationOptimizer().optimize(operations, 'testapp')
        # Precondition: confirm Django's optimizer actually folds CreateModel +
        # RenameField into one CreateModel (the scenario this fix targets). If
        # this assertion ever fails, Django's optimizer behavior changed and
        # this test needs re-deriving, not weakening.
        self.assertEqual(len(optimized), 1)
        self.assertIsInstance(optimized[0], migrations.CreateModel)

        class SquashedMigration(migrations.Migration):
            initial = True
            operations = optimized

        migration = SquashedMigration(
            name='test_squashed_rename_index', app_label='testapp'
        )
        conn = django.db.connections[django.db.DEFAULT_DB_ALIAS]
        with conn.schema_editor(atomic=True) as editor:
            project_state = migration.apply(ProjectState(), editor)

        model = project_state.apps.get_model('testapp', model_name)
        constraints = get_constraints(table_name=model._meta.db_table)
        self._assert_named_index_columns(
            constraints, index_name, ['b'],
            'A Meta.index folded into CreateModel by the optimizer lost its key column.',
        )
        filter_definition = self._get_index_catalog(model, index_name)[0][2]
        self.assertIn('[aa]', filter_definition)
        self.assertNotIn('[a]', filter_definition)

    def test_condition_field_names_rewritten_for_collection_and_transformed_rhs(self):
        """
        Field references nested in a tuple/list RHS value, or reached through
        a lookup transform on an F() reference, must be rewritten on rename,
        not silently left stale (or silently dropped from the referenced
        field names used to decide which indexes are affected by a rename).
        """
        conn = django.db.connections[django.db.DEFAULT_DB_ALIAS]
        editor = conn.schema_editor(collect_sql=True, atomic=False)

        collection_condition = models.Q(a__in=(models.F('b'),))
        _replace_condition_field_names(collection_condition, {'b': 'bb'})
        self.assertEqual(
            editor._get_condition_field_names(collection_condition), ['a', 'bb']
        )

        transformed_condition = models.Q(b=models.F('a__year'))
        _replace_condition_field_names(transformed_condition, {'a': 'aa'})
        # Assert the rewritten F() object directly: _get_condition_field_names()
        # deliberately strips everything after '__', so it alone cannot tell
        # apart a correctly preserved 'aa__year' from a broken 'aa' that lost
        # the year transform entirely.
        self.assertEqual(transformed_condition.children[0][1].name, 'aa__year')
        self.assertEqual(
            editor._get_condition_field_names(transformed_condition), ['b', 'aa']
        )

    def test_filtered_meta_index_restored_with_unbound_replacement_field(self):
        """
        schema_editor.alter_field() may be called directly (as
        TestIndexesBeingDropped.test_unique_index_dropped already does
        elsewhere) with an unbound replacement field that has no .model
        attribute. The rename-restoration path must use the same meta_model
        fallback _alter_field() establishes for old_field/new_field elsewhere,
        not new_field.model directly.

        `to_model` (obtained via AlterField.state_forwards(), like a real
        migration's to_state) is passed as the `model` argument so meta_model's
        fallback has correct post-alter field metadata to restore against,
        while `new_field` itself is a manually constructed field deliberately
        left unbound (no .model), reproducing the exact caller shape that
        crashes without the fix.
        """
        model_name = 'TestUnboundRenameFilteredIndex'
        index_name = 'idx_unbound_rename_filtered'

        class SetupMigration(migrations.Migration):
            initial = True
            operations = [
                migrations.CreateModel(
                    name=model_name,
                    fields=[
                        ('id', models.AutoField(primary_key=True)),
                        ('a', models.CharField(max_length=20, null=True)),
                        ('b', models.CharField(max_length=20)),
                    ],
                ),
                migrations.AddIndex(
                    model_name=model_name.lower(),
                    index=models.Index(
                        fields=['b'],
                        condition=models.Q(a__isnull=False),
                        name=index_name,
                    ),
                ),
            ]

        migration = SetupMigration(
            name='test_unbound_rename_filtered', app_label='testapp'
        )
        conn = django.db.connections[django.db.DEFAULT_DB_ALIAS]
        with conn.schema_editor(atomic=True) as editor:
            from_state = migration.apply(ProjectState(), editor)

        to_state = from_state.clone()
        migrations.AlterField(
            model_name=model_name.lower(),
            name='a',
            field=models.CharField(max_length=20, null=True, db_column='aa'),
        ).state_forwards('testapp', to_state)

        from_model = from_state.apps.get_model('testapp', model_name)
        to_model = to_state.apps.get_model('testapp', model_name)
        old_field = from_model._meta.get_field('a')
        new_field = models.CharField(max_length=20, null=True, db_column='aa')
        new_field.set_attributes_from_name('a')
        with conn.schema_editor(atomic=True) as editor:
            editor.alter_field(to_model, old_field, new_field, strict=True)

        constraints = get_constraints(table_name=to_model._meta.db_table)
        self._assert_named_index_columns(
            constraints, index_name, ['b'],
            'A filtered Meta.index was lost when alter_field() was called '
            'directly with an unbound replacement field.',
        )
        self.assertIn(
            '[aa]', self._get_index_catalog(to_model, index_name)[0][2]
        )

    def test_meta_index_restore_skips_still_deferred_creation(self):
        """
        A Meta.indexes entry declared inline via CreateModel(options={...})
        is legitimately absent from the catalog until its deferred CREATE
        INDEX statement runs at schema_editor context exit. A combined
        db_column rename and type change on that index's field within the
        SAME migration must not have _restore_missing_meta_indexes() treat
        that still-pending index as one it needs to recreate - doing so
        collides with the original deferred CREATE INDEX once it finally
        executes.
        """
        model_name = 'TestDeferredIndexCollision'
        index_name = 'idx_deferred_index_collision'

        operations_a = [
            migrations.CreateModel(
                name=model_name,
                fields=[
                    ('id', models.AutoField(primary_key=True)),
                    ('a', models.CharField(max_length=20)),
                    ('b', models.CharField(max_length=20)),
                ],
                options={
                    'indexes': [
                        models.Index(fields=['b'], name=index_name),
                    ],
                },
            ),
            migrations.AlterField(
                model_name=model_name.lower(),
                name='b',
                field=models.CharField(max_length=40, db_column='bb'),
            ),
        ]

        result = self._run_migration_test(
            operations_a=operations_a,
            operations_b=[],
            migration_name_prefix='test_deferred_index_collision',
            model_name=model_name,
            use_single_migration=True,
        )

        self._assert_named_index_columns(
            result.constraints, index_name, ['bb'],
            'A Meta.index declared inline via CreateModel was not correctly '
            'restored after a combined rename and type change in the same '
            'migration.',
        )

    def test_pk_alias_condition_survives_unrelated_alter(self):
        """
        A Meta.index condition may reference the 'pk' query alias (e.g.
        Q(pk__gt=0)), which Options.get_field() does not recognize as a
        literal field name. Altering the type of ANY field on the model
        must not crash while resolving that index's reference names -
        _delete_indexes() inspects every existing index on the model, not
        just ones tied to the field being altered.
        """
        model_name = 'TestPkAliasCondition'
        index_name = 'idx_pk_alias_condition'

        operations_a = [
            migrations.CreateModel(
                name=model_name,
                fields=[
                    ('id', models.AutoField(primary_key=True)),
                    ('a', models.CharField(max_length=20)),
                ],
            ),
            migrations.AddIndex(
                model_name=model_name.lower(),
                index=models.Index(
                    fields=['a'], condition=models.Q(pk__gt=0), name=index_name
                ),
            ),
        ]
        operations_b = [
            migrations.AlterField(
                model_name=model_name.lower(),
                name='a',
                field=models.CharField(max_length=40),
            ),
        ]

        result = self._run_migration_test(
            operations_a=operations_a,
            operations_b=operations_b,
            migration_name_prefix='test_pk_alias_condition',
            model_name=model_name,
            use_single_migration=True,
        )

        self._assert_named_index_columns(
            result.constraints, index_name, ['a'],
            "A Meta.index filtered on the 'pk' alias was lost (or crashed) "
            "when an unrelated field's type was altered.",
        )

    def test_meta_index_retained_after_autofield_column_rename(self):
        """
        Altering an AutoField/BigAutoField field unconditionally drops every
        index on the table (SQL Server requires this before an ALTER COLUMN
        on an IDENTITY column). When that alteration also renames the
        AutoField's own db_column, the normal "column alteration cleanup"
        restoration is skipped (it only runs when the column was NOT
        renamed), so a Meta.index on an unrelated field must still be
        restored via the rename-restoration path, not silently dropped for
        good.
        """
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestAutoFieldColumnRename{suffix}'
                index_name = f'idx_autofield_column_rename{suffix}'

                operations_a = [
                    migrations.CreateModel(
                        name=model_name,
                        fields=[
                            ('id', models.AutoField(primary_key=True)),
                            ('a', models.CharField(max_length=20)),
                        ],
                    ),
                    migrations.AddIndex(
                        model_name=model_name.lower(),
                        index=models.Index(fields=['a'], name=index_name),
                    ),
                ]
                operations_b = [
                    migrations.AlterField(
                        model_name=model_name.lower(),
                        name='id',
                        field=models.AutoField(primary_key=True, db_column='new_id'),
                    ),
                ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_autofield_column_rename',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                self._assert_named_index_columns(
                    result.constraints, index_name, ['a'],
                    'A Meta.index was permanently lost after renaming an '
                    "AutoField's own db_column "
                    f"({self._get_context_description(use_single_migration)}).",
                )

    def test_db_index_retained_after_autofield_column_rename(self):
        """
        Same AutoField-own-db_column-rename scenario as
        test_meta_index_retained_after_autofield_column_rename above, but for
        a plain db_index=True column instead of a Meta.indexes entry. The
        AutoField "drop all indexes" path drops this index too, and it must
        be restored the same way the non-renamed "column alteration cleanup"
        path restores db_index=True columns for a plain (non-renamed)
        AutoField/BigAutoField change.
        """
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestDbIdxAutoFieldRename{suffix}'

                operations_a = [
                    migrations.CreateModel(
                        name=model_name,
                        fields=[
                            ('id', models.AutoField(primary_key=True)),
                            ('a', models.CharField(max_length=20, db_index=True)),
                        ],
                    ),
                ]
                operations_b = [
                    migrations.AlterField(
                        model_name=model_name.lower(),
                        name='id',
                        field=models.AutoField(primary_key=True, db_column='new_id'),
                    ),
                ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_db_idx_autofield_column_rename',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'a'},
                    error_msg=(
                        "A db_index=True column's index was permanently lost after renaming an "
                        "AutoField's own db_column "
                        f"({self._get_context_description(use_single_migration)})."
                    ),
                )

    @skipIf(VERSION >= (5, 1), "index_together is removed in Django 5.1+")
    def test_index_together_retained_after_autofield_column_rename(self):
        """
        Same AutoField-own-db_column-rename scenario as
        test_meta_index_retained_after_autofield_column_rename above, but for
        an index_together entry instead of a Meta.indexes entry.
        """
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestIdxTogetherAutoFieldRename{suffix}'

                operations_a = [
                    migrations.CreateModel(
                        name=model_name,
                        fields=[
                            ('id', models.AutoField(primary_key=True)),
                            ('a', models.CharField(max_length=20)),
                            ('b', models.CharField(max_length=20)),
                        ],
                        options={
                            'index_together': {('a', 'b')},
                        },
                    ),
                ]
                operations_b = [
                    migrations.AlterField(
                        model_name=model_name.lower(),
                        name='id',
                        field=models.AutoField(primary_key=True, db_column='new_id'),
                    ),
                ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_idx_together_autofield_column_rename',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                self._assert_index_exists(
                    result.constraints,
                    expected_columns={'a', 'b'},
                    error_msg=(
                        "An index_together index was permanently lost after renaming an "
                        "AutoField's own db_column "
                        f"({self._get_context_description(use_single_migration)})."
                    ),
                )

    def test_unique_together_retained_after_autofield_column_rename(self):
        """
        Same AutoField-own-db_column-rename scenario as
        test_meta_index_retained_after_autofield_column_rename above, but for
        a unique_together entry instead of a Meta.indexes entry. Unlike
        test_unique_together_retained_after_rename_and_type_change (a
        different, non-AutoField scenario left as a documented
        @expectedFailure), the AutoField-wholesale-drop path here is the one
        this fix restores.
        """
        for use_single_migration in [False, True]:
            with self.subTest(single_migration=use_single_migration):
                suffix = '_combined' if use_single_migration else '_split'
                model_name = f'TestUniqTogetherAutoFieldRename{suffix}'

                operations_a = [
                    migrations.CreateModel(
                        name=model_name,
                        fields=[
                            ('id', models.AutoField(primary_key=True)),
                            ('a', models.CharField(max_length=20)),
                            ('b', models.CharField(max_length=20)),
                        ],
                        options={
                            'unique_together': {('a', 'b')},
                        },
                    ),
                ]
                operations_b = [
                    migrations.AlterField(
                        model_name=model_name.lower(),
                        name='id',
                        field=models.AutoField(primary_key=True, db_column='new_id'),
                    ),
                ]

                result = self._run_migration_test(
                    operations_a=operations_a,
                    operations_b=operations_b,
                    migration_name_prefix='test_uniq_together_autofield_column_rename',
                    model_name=model_name,
                    use_single_migration=use_single_migration,
                )

                unique_constraints = [
                    info for info in result.constraints.values()
                    if info.get('unique') and set(info['columns']) == {'a', 'b'}
                ]
                self.assertTrue(
                    len(unique_constraints) > 0,
                    "unique_together constraint on ('a', 'b') was permanently lost after "
                    "renaming an AutoField's own db_column "
                    f"({self._get_context_description(use_single_migration)})."
                )

    def test_unique_constraint_retained_after_autofield_column_rename(self):
        """
        Same AutoField-own-db_column-rename scenario as
        test_meta_index_retained_after_autofield_column_rename above, but for
        a Meta.constraints UniqueConstraint unrelated to the renamed field
        instead of a Meta.indexes entry.
        """
        model_name = 'TestUniqueConstraintAutoFieldRename'
        constraint_name = 'uq_autofield_rename_unrelated'

        result = self._run_migration_test(
            operations_a=[
                migrations.CreateModel(
                    name=model_name,
                    fields=[
                        ('id', models.AutoField(primary_key=True)),
                        ('a', models.CharField(max_length=20, null=True)),
                    ],
                    options={
                        'constraints': [
                            UniqueConstraint(
                                fields=['a'],
                                condition=models.Q(a__isnull=False),
                                name=constraint_name,
                            ),
                        ],
                    },
                ),
            ],
            operations_b=[
                migrations.AlterField(
                    model_name=model_name.lower(),
                    name='id',
                    field=models.AutoField(primary_key=True, db_column='new_id'),
                ),
            ],
            migration_name_prefix='test_unique_constraint_autofield_column_rename',
            model_name=model_name,
            use_single_migration=False,
        )

        self.assertIn(
            constraint_name, result.constraints,
            "A Meta.constraints UniqueConstraint unrelated to the renamed field was "
            "permanently lost after renaming an AutoField's own db_column."
        )

    def test_covering_unique_constraint_include_semantics_retained_after_rename(self):
        """
        A covering UniqueConstraint's INCLUDE column, when renamed, must stay
        an INCLUDE column - not get silently promoted into the unique key.
        The generic "drop any unique index whose physical columns include
        the renamed column" path does not distinguish key from INCLUDE
        columns (sys.index_columns doesn't either, without an explicit
        filter), so it must not be allowed to rebuild this constraint; only
        the structured restoration (via _clone_constraint_with_replacements())
        preserves the key/include distinction.
        """
        model_name = 'TestCoveringConstraintRename'
        constraint_name = 'uq_covering_constraint_rename'

        result = self._run_migration_test(
            operations_a=[
                migrations.CreateModel(
                    name=model_name,
                    fields=[
                        ('id', models.AutoField(primary_key=True)),
                        ('a', models.CharField(max_length=20, null=True)),
                        ('b', models.CharField(max_length=20)),
                    ],
                    options={
                        'constraints': [
                            UniqueConstraint(
                                fields=['b'],
                                include=['a'],
                                condition=models.Q(a__isnull=False),
                                name=constraint_name,
                            ),
                        ],
                    },
                ),
            ],
            operations_b=[
                migrations.RenameField(
                    model_name=model_name.lower(), old_name='a', new_name='aa'
                ),
            ],
            migration_name_prefix='test_covering_constraint_rename',
            model_name=model_name,
            use_single_migration=False,
        )

        catalog = self._get_index_catalog(result.model, constraint_name)
        included_by_column = {name: is_included for is_included, name, _ in catalog}
        self.assertEqual(
            included_by_column.get('b'), False,
            "The constraint's key column 'b' should remain key-only.",
        )
        self.assertEqual(
            included_by_column.get('aa'), True,
            "The renamed INCLUDE column must stay an INCLUDE column, not be "
            "promoted into the unique key.",
        )





class TestAddAndAlterUniqueIndex(TestCase):

    def test_alter_unique_nullable_to_non_nullable(self):
        """
        Test a single migration that creates a field with unique=True and null=True and then alters
        the field to set null=False. See https://github.com/microsoft/mssql-django/issues/22
        """
        operations = [
            migrations.CreateModel(
                "TestAlterNullableInUniqueField",
                [
                    ("id", models.AutoField(primary_key=True)),
                    ("a", models.CharField(max_length=4, unique=True, null=True)),
                ]
            ),
            migrations.AlterField(
                "testalternullableinuniquefield",
                "a",
                models.CharField(max_length=4, unique=True)
            )
        ]

        project_state = ProjectState()
        new_state = project_state.clone()
        migration = Migration("name", "testapp")
        migration.operations = operations

        try:
            with connection.schema_editor(atomic=True) as editor:
                migration.apply(new_state, editor)
        except django.db.utils.ProgrammingError as e:
            self.fail('Check if can alter field from unique, nullable to unique non-nullable for issue #23, AlterField failed with exception: %s' % e)

class TestKeepIndexWithDbcomment(TestCase):
    def _find_key_with_type_idx(self, input_dict):
        for key, value in input_dict.items():
            if value.get("type") == "idx":
                return key
        return None

    @skipIf(VERSION < (4, 2), "db_comment not available before 4.2")
    def test_drop_foreignkey(self):
        app_label = "test_drop_foreignkey"
        operations = [
                migrations.CreateModel(
                    name="brand",
                    fields=[
                        ("id", models.AutoField(primary_key=True)),
                        ("name", models.CharField(max_length=100)),
                    ],
                ),
                migrations.CreateModel(
                    name="car1",
                    fields=[
                        ("id", models.AutoField(primary_key=True)),
                        (
                            "brand",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                to="test_drop_foreignkey.brand",
                                related_name="car1",
                                db_constraint=True,
                            ),
                        ),
                    ],
                ),
                migrations.CreateModel(
                    name="car2",
                    fields=[
                        ("id", models.AutoField(primary_key=True)),
                        (
                            "brand",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                to="test_drop_foreignkey.brand",
                                related_name="car2",
                                db_constraint=True,
                            ),
                        ),
                    ],
                ),
                migrations.CreateModel(
                    name="car3",
                    fields=[
                        ("id", models.AutoField(primary_key=True)),
                        (
                            "brand",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                to="test_drop_foreignkey.brand",
                                related_name="car3",
                                db_constraint=True,
                            ),
                        ),
                    ],
                ),
            ]
        migration = Migration("name", app_label)
        migration.operations = operations
        with connection.schema_editor(atomic=True) as editor:
            project_state = migration.apply(ProjectState(), editor)

        alter_fk_car1 = migrations.AlterField(
            model_name="car1",
            name="brand",
            field=models.ForeignKey(
                to="test_drop_foreignkey.brand",
                on_delete=django.db.models.deletion.CASCADE,
                db_constraint=False,
                related_name="car1",
            ),
        )
        alter_fk_car2 = migrations.AlterField(
            model_name="car2",
            name="brand",
            field=models.ForeignKey(
                to="test_drop_foreignkey.brand",
                on_delete=django.db.models.deletion.CASCADE,
                db_constraint=False,
                related_name="car2",
                db_comment=""
            ),
        )
        alter_fk_car3 = migrations.AlterField(
            model_name="car3",
            name="brand",
            field=models.ForeignKey(
                to="test_drop_foreignkey.brand",
                on_delete=django.db.models.deletion.CASCADE,
                db_constraint=False,
                related_name="car3",
                db_comment="fk_on_delete_keep_index"
            ),
        )
        new_state = project_state.clone()
        with connection.schema_editor(atomic=True) as editor:
            alter_fk_car1.state_forwards("test_drop_foreignkey", new_state)
            alter_fk_car1.database_forwards(
                "test_drop_foreignkey", editor, project_state, new_state
            )
        car_index = self._find_key_with_type_idx(
            get_constraints(
                table_name=new_state.apps.get_model(
                    "test_drop_foreignkey", "car1"
                )._meta.db_table
            )
        )
        # Test alter foreignkey without db_comment field
        # The index should be dropped (keep the old behavior)
        self.assertIsNone(car_index)

        project_state = new_state
        new_state = new_state.clone()
        with connection.schema_editor(atomic=True) as editor:
            alter_fk_car2.state_forwards("test_drop_foreignkey", new_state)
            alter_fk_car2.database_forwards(
                "test_drop_foreignkey", editor, project_state, new_state
            )
        car_index = self._find_key_with_type_idx(
            get_constraints(
                table_name=new_state.apps.get_model(
                    "test_drop_foreignkey", "car2"
                )._meta.db_table
            )
        )
        # Test alter fk with empty db_comment
        self.assertIsNone(car_index)

        project_state = new_state
        new_state = new_state.clone()
        with connection.schema_editor(atomic=True) as editor:
            alter_fk_car3.state_forwards("test_drop_foreignkey", new_state)
            alter_fk_car3.database_forwards(
                "test_drop_foreignkey", editor, project_state, new_state
            )
        car_index = self._find_key_with_type_idx(
            get_constraints(
                table_name=new_state.apps.get_model(
                    "test_drop_foreignkey", "car3"
                )._meta.db_table
            )
        )
        # Test alter fk with fk_on_delete_keep_index in db_comment
        # Index should be preserved in this case
        self.assertIsNotNone(car_index)
