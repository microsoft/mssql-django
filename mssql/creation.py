# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

import binascii
import os

from django.db.utils import InterfaceError
from django.db.backends.base.creation import BaseDatabaseCreation
from django import VERSION as django_version


class DatabaseCreation(BaseDatabaseCreation):

    def cursor(self):
        if django_version >= (3, 1):
            return self.connection._nodb_cursor()

        return self.connection._nodb_connection.cursor()

    def _create_test_db(self, verbosity, autoclobber, keepdb=False):
        """
        Internal implementation - create the test db tables.
        """

        # Try to create the test DB, but if we fail due to 28000 (Login failed for user),
        #   it's probably because the user doesn't have permission to [dbo].[master],
        #   so we can proceed if we're keeping the DB anyway.
        # https://github.com/microsoft/mssql-django/issues/61
        try:
            test_database_name = super()._create_test_db(verbosity, autoclobber, keepdb)
            
            # Create required schemas for Django tests (only for 5.2+)
            if django_version >= (5, 2):
                self._create_test_schemas(test_database_name, verbosity)

            return test_database_name
        except InterfaceError as err:
            if err.args[0] == '28000' and keepdb:
                self.log('Received error %s, proceeding because keepdb=True' % (
                    err.args[1],
                ))
            else:
                raise err

    def _create_test_schemas(self, test_database_name, verbosity):
        """
        Create required schemas in test database for Django tests.
        """
        schemas_to_create = ['inspectdb_special', 'inspectdb_pascal']
        
        # Use a cursor connected to the test database
        test_settings = self.connection.settings_dict.copy()
        test_settings['NAME'] = test_database_name
        test_connection = self.connection.__class__(test_settings)
        
        try:
            with test_connection.cursor() as cursor:
                for schema in schemas_to_create:
                    try:
                        quoted_schema = self.connection.ops.quote_name(schema)
                        cursor.execute(f"CREATE SCHEMA {quoted_schema}")
                        if verbosity >= 2:
                            self.log(f'Created schema {schema} in test database {test_database_name}')
                    except Exception as e:
                        # Schema might already exist, which is fine
                        if verbosity >= 2:
                            self.log(f'Schema {schema} creation failed (might already exist): {e}')
        finally:
            test_connection.close()

    def _destroy_test_db(self, test_database_name, verbosity):
        """
        Internal implementation - remove the test db tables.
        """
        # Remove the test database to clean up after
        # ourselves. Connect to the previous database (not the test database)
        # to do so, because it's not allowed to delete a database while being
        # connected to it.
        with self.cursor() as cursor:
            to_azure_sql_db = self.connection.to_azure_sql_db
            if not to_azure_sql_db:
                cursor.execute("ALTER DATABASE %s SET SINGLE_USER WITH ROLLBACK IMMEDIATE"
                               % self.connection.ops.quote_name(test_database_name))
            cursor.execute("DROP DATABASE %s"
                           % self.connection.ops.quote_name(test_database_name))

    def _clone_test_db(self, suffix, verbosity, keepdb=False):
        """
        Clone the already-created test database so Django can run tests with
        the --parallel flag (one clone per worker process).

        SQL Server has no CREATE DATABASE ... TEMPLATE, so the clone is made
        with a server-side BACKUP of the source test database followed by a
        RESTORE ... WITH MOVE into a new database. This copies both schema and
        data, matching what Django expects from a cloned test database.

        The source is identical for every clone, so it is backed up once and
        that single backup is restored for each worker.
        """
        if self.connection.to_azure_sql_db:
            raise NotImplementedError(
                "Cloning test databases is not supported on Azure SQL Database, "
                "which does not allow BACKUP/RESTORE to disk. Run tests without "
                "the --parallel flag."
            )

        source_database_name = self.connection.settings_dict['NAME']
        target_database_name = self.get_test_db_clone_settings(suffix)['NAME']
        quote_name = self.connection.ops.quote_name

        with self.cursor() as cursor:
            if keepdb and self._database_exists(cursor, target_database_name):
                return target_database_name
            self._drop_database_if_exists(cursor, target_database_name)

            backup_path, logical_files = self._backup_source_once(
                cursor, source_database_name)

            # A RESTORE onto the same instance must relocate every logical file
            # to a new physical path. Put each clone file in the same directory
            # as its source file, which is guaranteed to exist and be writable
            # by the server (no dependency on SERVERPROPERTY default paths).
            move_clauses = []
            for logical_name, file_type, physical_name in logical_files:
                extension = {0: '.mdf', 1: '.ldf'}.get(file_type, '.ndf')
                directory = self._directory_of(physical_name)
                target_physical = '%s%s_%s%s' % (
                    directory, target_database_name, logical_name, extension)
                move_clauses.append('MOVE %s TO %s' % (
                    self._quote_literal(logical_name),
                    self._quote_literal(target_physical),
                ))

            cursor.execute(
                "RESTORE DATABASE %s FROM DISK = %s WITH %s, RECOVERY, REPLACE" % (
                    quote_name(target_database_name),
                    self._quote_literal(backup_path),
                    ', '.join(move_clauses),
                )
            )
            self._drain(cursor)

        return target_database_name

    def _backup_source_once(self, cursor, source_database_name):
        """Back up the source test database a single time and cache the result.

        Returns (backup_path, logical_files) where logical_files is a list of
        (logical_name, file_type, physical_name) tuples. All clones of the same
        source restore from this one backup instead of re-dumping it per worker.
        """
        cache = getattr(self, '_clone_backup_cache', None)
        if cache and cache[0] == source_database_name:
            return cache[1], cache[2]

        cursor.execute(
            "SELECT name, type, physical_name FROM sys.master_files "
            "WHERE database_id = DB_ID(%s)",
            [source_database_name],
        )
        logical_files = cursor.fetchall()

        # Write the backup next to a source data file (a directory the server
        # can definitely write to).
        data_file = next(
            (pn for _, ftype, pn in logical_files if ftype == 0),
            logical_files[0][2],
        )
        backup_path = '%s%s_clone_source.bak' % (
            self._directory_of(data_file), source_database_name)
        cursor.execute(
            "BACKUP DATABASE %s TO DISK = %s WITH INIT, COPY_ONLY" % (
                self.connection.ops.quote_name(source_database_name),
                self._quote_literal(backup_path),
            )
        )
        self._drain(cursor)
        self._clone_backup_cache = (source_database_name, backup_path, logical_files)
        return backup_path, logical_files

    @staticmethod
    def _quote_literal(value):
        """Quote a string as a T-SQL literal (BACKUP/RESTORE reject parameters)."""
        return "N'%s'" % value.replace("'", "''")

    @staticmethod
    def _directory_of(physical_name):
        """Return the directory portion (with trailing separator) of a SQL
        Server physical file path, handling both Windows and POSIX separators."""
        separator = '\\' if '\\' in physical_name else '/'
        return physical_name.rsplit(separator, 1)[0] + separator

    @staticmethod
    def _drain(cursor):
        """Consume the informational result sets BACKUP/RESTORE emit.

        Without this the connection is still finishing the restore when the next
        statement runs, which raises 'database is in the middle of a restore'.
        """
        while cursor.nextset():
            pass

    def _database_exists(self, cursor, database_name):
        cursor.execute(
            "SELECT 1 FROM sys.databases WHERE name = %s", [database_name])
        return cursor.fetchone() is not None

    def _drop_database_if_exists(self, cursor, database_name):
        if not self._database_exists(cursor, database_name):
            return
        quoted = self.connection.ops.quote_name(database_name)
        if not self.connection.to_azure_sql_db:
            cursor.execute(
                "ALTER DATABASE %s SET SINGLE_USER WITH ROLLBACK IMMEDIATE" % quoted)
        cursor.execute("DROP DATABASE %s" % quoted)

    def sql_table_creation_suffix(self):
        suffix = []
        collation = self.connection.settings_dict['TEST'].get('COLLATION', None)
        if collation:
            suffix.append('COLLATE %s' % collation)
        return ' '.join(suffix)

    # The following code to add regex support in SQLServer is taken from django-mssql
    # see https://bitbucket.org/Manfre/django-mssql
    def enable_clr(self):
        """ Enables clr for server if not already enabled
        This function will not fail if current user doesn't have
        permissions to enable clr, and clr is already enabled
        """
        with self.cursor() as cursor:
            # check whether clr is enabled
            cursor.execute('''
            SELECT value FROM sys.configurations
            WHERE name = 'clr enabled'
            ''')
            res = None
            try:
                res = cursor.fetchone()
            except Exception:
                pass

            if not res or not res[0]:
                # if not enabled enable clr
                cursor.execute("sp_configure 'clr enabled', 1")
                cursor.execute("RECONFIGURE")

                cursor.execute("sp_configure 'show advanced options', 1")
                cursor.execute("RECONFIGURE")

                cursor.execute("sp_configure 'clr strict security', 0")
                cursor.execute("RECONFIGURE")

    def install_regex_clr(self, database_name):
        sql = '''
USE {database_name};
-- Drop and recreate the function if it already exists
IF OBJECT_ID('REGEXP_LIKE') IS NOT NULL
DROP FUNCTION [dbo].[REGEXP_LIKE]
IF EXISTS(select * from sys.assemblies where name like 'regex_clr')
DROP ASSEMBLY regex_clr
;
CREATE ASSEMBLY regex_clr
FROM 0x{assembly_hex}
WITH PERMISSION_SET = SAFE;
create function [dbo].[REGEXP_LIKE]
(
@input nvarchar(max),
@pattern nvarchar(max),
@caseSensitive int
)
RETURNS INT  AS
EXTERNAL NAME regex_clr.UserDefinedFunctions.REGEXP_LIKE
        '''.format(
            database_name=self.connection.ops.quote_name(database_name),
            assembly_hex=self.get_regex_clr_assembly_hex(),
        ).split(';')

        self.enable_clr()

        with self.cursor() as cursor:
            for s in sql:
                cursor.execute(s)

    def get_regex_clr_assembly_hex(self):
        with open(os.path.join(os.path.dirname(__file__), 'regex_clr.dll'), 'rb') as f:
            return binascii.hexlify(f.read()).decode('ascii')
