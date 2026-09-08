# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from django.db import connection
from django.test import SimpleTestCase

_UNSET = object()


class SqlTableCreationSuffixTests(SimpleTestCase):
    """Cover DatabaseCreation.sql_table_creation_suffix.

    The suffix is derived from the TEST['COLLATION'] setting. The regular test
    run leaves COLLATION unset, so the COLLATE branch was never exercised.
    This reads settings and builds a string only, so no database is needed.
    """

    def setUp(self):
        self.test_settings = connection.settings_dict['TEST']
        self.original = self.test_settings.get('COLLATION', _UNSET)

    def tearDown(self):
        # Restore the exact prior state, distinguishing an unset key from None.
        if self.original is _UNSET:
            self.test_settings.pop('COLLATION', None)
        else:
            self.test_settings['COLLATION'] = self.original

    def test_no_collation_returns_empty_suffix(self):
        self.test_settings['COLLATION'] = None
        self.assertEqual(connection.creation.sql_table_creation_suffix(), '')

    def test_collation_is_included_in_suffix(self):
        self.test_settings['COLLATION'] = 'Latin1_General_CI_AS'
        self.assertEqual(
            connection.creation.sql_table_creation_suffix(),
            'COLLATE Latin1_General_CI_AS',
        )
