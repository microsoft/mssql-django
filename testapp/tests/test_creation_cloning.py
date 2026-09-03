# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from django.db import connection
from django.test import TransactionTestCase


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

    def test_clone_is_a_working_copy(self):
        creation = connection.creation
        suffix = 'clonetest'
        clone_name = creation.get_test_db_clone_settings(suffix)['NAME']

        creation._clone_test_db(suffix, verbosity=0)
        try:
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

    def test_clone_keepdb_reuses_existing(self):
        creation = connection.creation
        suffix = 'clonekeep'
        clone_name = creation.get_test_db_clone_settings(suffix)['NAME']

        creation._clone_test_db(suffix, verbosity=0)
        try:
            # A second clone with keepdb=True must be a no-op, not an error.
            creation._clone_test_db(suffix, verbosity=0, keepdb=True)
            with connection._nodb_cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM sys.databases WHERE name = %s", [clone_name])
                self.assertIsNotNone(cursor.fetchone())
        finally:
            with connection._nodb_cursor() as cursor:
                creation._drop_database_if_exists(cursor, clone_name)
