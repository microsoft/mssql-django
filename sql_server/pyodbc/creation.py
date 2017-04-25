from django.db.backends.base.creation import BaseDatabaseCreation


class DatabaseCreation(BaseDatabaseCreation):

    def _destroy_test_db(self, test_database_name, verbosity):
        """
        Internal implementation - remove the test db tables.
        """
        # Remove the test database to clean up after
        # ourselves. Connect to the previous database (not the test database)
        # to do so, because it's not allowed to delete a database while being
        # connected to it.
        with self.connection._nodb_connection.cursor() as cursor:
            to_azure_sql_db = self.connection.to_azure_sql_db
            if not to_azure_sql_db:
                cursor.execute("ALTER DATABASE %s SET SINGLE_USER WITH ROLLBACK IMMEDIATE"
                                % self.connection.ops.quote_name(test_database_name))
            cursor.execute("DROP DATABASE %s"
                           % self.connection.ops.quote_name(test_database_name))

    def sql_table_creation_suffix(self):
        suffix = []
        collation = self.connection.settings_dict['TEST'].get('COLLATION', None)
        if collation:
            suffix.append('COLLATE %s' % collation)
        return ' '.join(suffix)
