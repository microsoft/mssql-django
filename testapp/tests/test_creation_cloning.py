# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

import os
import subprocess
import sys

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
        # Detection is via the master-scoped engine edition, so it is accurate
        # (False on the Azure SQL family) without connecting to the application
        # database.
        self.assertEqual(
            connection.features.can_clone_databases,
            not connection.to_azure_sql_db,
        )

    @skipUnlessDBFeature('can_clone_databases')
    def test_clone_is_a_working_copy(self):
        creation = connection.creation
        suffix = 'clonetest'
        clone_name = creation.get_test_db_clone_settings(suffix)['NAME']
        quoted_clone = connection.ops.quote_name(clone_name)
        try:
            returned_name = creation._clone_test_db(suffix, verbosity=0)
            self.assertEqual(returned_name, clone_name)
            with connection._nodb_cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM sys.databases WHERE name = %s", [clone_name])
                self.assertIsNotNone(
                    cursor.fetchone(), 'clone database was not created')

                # Schema is copied: the testapp tables exist in the clone.
                cursor.execute(
                    "SELECT COUNT(*) FROM %s.sys.tables WHERE name = %%s"
                    % quoted_clone, ['testapp_author'])
                self.assertEqual(cursor.fetchone()[0], 1)

                # Data is copied too: the applied-migration rows come across.
                cursor.execute(
                    "SELECT COUNT(*) FROM %s.dbo.django_migrations" % quoted_clone)
                self.assertGreater(cursor.fetchone()[0], 0)
        finally:
            with connection._nodb_cursor() as cursor:
                creation._drop_database_if_exists(cursor, clone_name)

    @skipUnlessDBFeature('can_clone_databases')
    def test_clone_keepdb_reuses_existing(self):
        creation = connection.creation
        suffix = 'clonekeep'
        clone_name = creation.get_test_db_clone_settings(suffix)['NAME']
        quoted_clone = connection.ops.quote_name(clone_name)
        try:
            creation._clone_test_db(suffix, verbosity=0)

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
                    % quoted_clone, ['keepdb_marker'])
                self.assertEqual(
                    cursor.fetchone()[0], 1,
                    'keepdb=True should reuse the clone, not recreate it')
        finally:
            with connection._nodb_cursor() as cursor:
                creation._drop_database_if_exists(cursor, clone_name)

    @skipUnlessDBFeature('can_clone_databases')
    def test_parallel_run_end_to_end(self):
        """Drive a real two-worker run with Django's stock DiscoverRunner.

        This exercises the whole lifecycle the project's own custom runner
        cannot: setup_databases creates the test DB, clones it per worker, the
        workers connect to their clone, run, and everything is torn down. Runs
        in a subprocess with isolated database names so it does not collide with
        the outer test run's databases.
        """
        repo_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        env = dict(
            os.environ,
            MSSQL_DB_NAME='parallel_clone_smoke',
            MSSQL_DB_NAME_OTHER='parallel_clone_smoke_other',
        )
        result = subprocess.run(
            [sys.executable, 'manage.py', 'test',
             'testapp.tests.test_fields',
             '--parallel', '2', '--noinput', '--verbosity', '2',
             '--settings=testapp.settings_parallel'],
            cwd=repo_root, env=env, capture_output=True, text=True, timeout=600,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, 'parallel run failed:\n' + output)
        # Confirm cloning actually happened (not silently downgraded to serial).
        self.assertIn('Cloning test database', output)
