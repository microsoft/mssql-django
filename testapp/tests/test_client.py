# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from django.test import SimpleTestCase

from mssql.client import DatabaseClient


class SettingsToCmdArgsTests(SimpleTestCase):
    """Unit tests for the sqlcmd argument builder in mssql.client.

    These exercise pure argument construction, so no database connection is
    required. settings_to_cmd_args mutates the class-level executable_name, so
    each test resets it first to stay independent of run order.
    """

    def setUp(self):
        DatabaseClient.executable_name = 'sqlcmd'

    def _settings(self, **options):
        opts = {'driver': 'ODBC Driver 18 for SQL Server'}
        opts.update(options)
        return {
            'OPTIONS': opts,
            'USER': 'sa',
            'PASSWORD': 'secret',
            'NAME': 'mydb',
            'HOST': 'myserver',
            'PORT': '1433',
        }

    def test_server_and_port_are_joined(self):
        args = DatabaseClient.settings_to_cmd_args(self._settings(), [])
        self.assertEqual(args[:3], ['sqlcmd', '-S', 'myserver,1433'])

    def test_server_without_port(self):
        settings = self._settings()
        settings['PORT'] = ''
        args = DatabaseClient.settings_to_cmd_args(settings, [])
        self.assertIn('-S', args)
        self.assertEqual(args[args.index('-S') + 1], 'myserver')

    def test_user_and_password(self):
        args = DatabaseClient.settings_to_cmd_args(self._settings(), [])
        self.assertIn('-U', args)
        self.assertEqual(args[args.index('-U') + 1], 'sa')
        self.assertIn('-P', args)
        self.assertEqual(args[args.index('-P') + 1], 'secret')

    def test_trusted_connection_when_no_user(self):
        settings = self._settings()
        settings['USER'] = ''
        args = DatabaseClient.settings_to_cmd_args(settings, [])
        self.assertIn('-E', args)
        self.assertNotIn('-U', args)

    def test_database_name(self):
        args = DatabaseClient.settings_to_cmd_args(self._settings(), [])
        self.assertIn('-d', args)
        self.assertEqual(args[args.index('-d') + 1], 'mydb')

    def test_read_default_file_maps_to_input_file(self):
        args = DatabaseClient.settings_to_cmd_args(
            self._settings(read_default_file='/tmp/init.sql'), [])
        self.assertIn('-i', args)
        self.assertEqual(args[args.index('-i') + 1], '/tmp/init.sql')

    def test_options_override_top_level_settings(self):
        # OPTIONS values take precedence over the top-level settings_dict keys.
        args = DatabaseClient.settings_to_cmd_args(
            self._settings(user='optuser', host='opthost', db='optdb'), [])
        self.assertEqual(args[args.index('-U') + 1], 'optuser')
        self.assertEqual(args[args.index('-S') + 1], 'opthost,1433')
        self.assertEqual(args[args.index('-d') + 1], 'optdb')

    def test_extra_parameters_are_appended(self):
        args = DatabaseClient.settings_to_cmd_args(
            self._settings(), ['-Q', 'SELECT 1'])
        self.assertEqual(args[-2:], ['-Q', 'SELECT 1'])
