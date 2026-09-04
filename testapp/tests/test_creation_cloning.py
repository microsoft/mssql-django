# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from django.db import connection
from django.test import TransactionTestCase, skipUnlessDBFeature


class DatabaseCloningTests(TransactionTestCase):
    """Regression tests for parallel-test database cloning (issue #342).

    SQL Server has no CREATE DATABASE ... TEMPLATE, so mssql-django clones the
    test database with a server-side BACKUP + RESTORE WITH MOVE. These tests
    exercise that path directly (the --parallel test runner drives the same
    code) and clean up the clone they create.
    """

    available_apps = ['testapp']

    def test_feature_flag_enabled(self):
        # Cloning is available on regular SQL Server, but not on Azure SQL
        # Database (no BACKUP/RESTORE to disk).
        self.assertEqual(
            connection.features.can_clone_databases,
            not connection.to_azure_sql_db,
        )

    @skipUnlessDBFeature('can_clone_databases')
    def test_clone_is_a_working_copy(self):
        creation = connection.creation
        suffix = 'clonetest'
        clone_name = creation.get_test_db_clone_settings(suffix)['NAME']

        returned_name = creation._clone_test_db(suffix, verbosity=0)
        try:
            self.assertEqual(returned_name, clone_name)
            with connection._nodb_cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM sys.databases WHERE name = %s", [clone_name])
                self.assertIsNotNone(
                    cursor.fetchone(), 'clone database was not created')

                # The schema is copied, so the testapp tables exist in the clone.
                cursor.execute(
                    "SELECT COUNT(*) FROM %s.sys.tables WHERE name = %%s"
                    % connection.ops.quote_name(clone_name),
                    ['testapp_author'],
                )
                self.assertEqual(cursor.fetchone()[0], 1)
        finally:
            with connection._nodb_cursor() as cursor:
                creation._drop_database_if_exists(cursor, clone_name)

    @skipUnlessDBFeature('can_clone_databases')
    def test_clone_keepdb_reuses_existing(self):
        creation = connection.creation
        suffix = 'clonekeep'
        clone_name = creation.get_test_db_clone_settings(suffix)['NAME']
        quoted_clone = connection.ops.quote_name(clone_name)

        creation._clone_test_db(suffix, verbosity=0)
        try:
            # Write a marker that exists only in the clone (the source backup
            # has no such table), so a genuine keepdb no-op can be told apart
            # from a silent drop-and-restore.
            with connection._nodb_cursor() as cursor:
                cursor.execute(
                    "EXEC('USE %s; CREATE TABLE keepdb_marker (id int)')"
                    % quoted_clone)

            # A second clone with keepdb=True must reuse the existing database.
            creation._clone_test_db(suffix, verbosity=0, keepdb=True)

            with connection._nodb_cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM %s.sys.tables WHERE name = %%s"
                    % quoted_clone,
                    ['keepdb_marker'],
                )
                self.assertEqual(
                    cursor.fetchone()[0], 1,
                    'keepdb=True should reuse the clone, not recreate it')
        finally:
            with connection._nodb_cursor() as cursor:
                creation._drop_database_if_exists(cursor, clone_name)
