import logging
from collections import namedtuple

import django.db
from django import VERSION
from django.apps import apps
from django.db import models, migrations
from django.db.migrations.migration import Migration
from django.db.migrations.state import ProjectState
from django.db.models import UniqueConstraint
from django.db.utils import DEFAULT_DB_ALIAS, ConnectionHandler, ProgrammingError
from django.test import TestCase, TransactionTestCase
from unittest import skipIf, expectedFailure

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

        if use_single_migration:
            # Combined: Create ONE migration with all operations combined
            # This simulates combining operations in a single migration file
            class CombinedMigration(migrations.Migration):
                initial = True
                operations = operations_a + operations_b

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

            with conn.schema_editor(atomic=True) as editor:
                project_state = migration_a.apply(ProjectState(), editor)
            with conn.schema_editor(atomic=True) as editor:
                project_state = migration_b.apply(project_state, editor)

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
