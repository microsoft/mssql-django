# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from django.db import connection
from django.test import TestCase


class SqlTableCreationSuffixTests(TestCase):
    """Cover DatabaseCreation.sql_table_creation_suffix.

    The suffix is derived from the TEST['COLLATION'] setting. The regular test
    run leaves COLLATION unset, so the COLLATE branch was never exercised.
    """

    def setUp(self):
        self.original = connection.settings_dict.get('TEST', {}).get('COLLATION', None)

    def tearDown(self):
        connection.settings_dict.setdefault('TEST', {})['COLLATION'] = self.original

    def test_no_collation_returns_empty_suffix(self):
        connection.settings_dict.setdefault('TEST', {})['COLLATION'] = None
        self.assertEqual(connection.creation.sql_table_creation_suffix(), '')

    def test_collation_is_included_in_suffix(self):
        connection.settings_dict.setdefault('TEST', {})['COLLATION'] = 'Latin1_General_CI_AS'
        self.assertEqual(
            connection.creation.sql_table_creation_suffix(),
            'COLLATE Latin1_General_CI_AS',
        )
