# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.
#
# Regression coverage for the inspectdb --schema argument handling: the value
# is wrapped as a T-SQL string literal, so any embedded single quote must be
# doubled to keep the schema name intact.

from unittest import mock

from django.conf import settings
from django.core.management.commands.inspectdb import Command as DjangoInspectDBCommand
from django.test import SimpleTestCase

from mssql.management.commands.inspectdb import Command as MSSQLInspectDBCommand

_SENTINEL = object()


class InspectDBSchemaArgTests(SimpleTestCase):
    def _resolve_schema_literal(self, schema):
        # Preserve and restore the module-level setting the command mutates.
        original = getattr(settings, "SCHEMA_TO_INSPECT", _SENTINEL)

        def _restore():
            if original is _SENTINEL:
                if hasattr(settings, "SCHEMA_TO_INSPECT"):
                    delattr(settings, "SCHEMA_TO_INSPECT")
            else:
                settings.SCHEMA_TO_INSPECT = original

        self.addCleanup(_restore)

        command = MSSQLInspectDBCommand()
        # Stub out the parent handle() so no database introspection runs; we
        # only care about the SCHEMA_TO_INSPECT value the override computes.
        with mock.patch.object(DjangoInspectDBCommand, "handle", return_value=None):
            command.handle(schema=schema)
        return settings.SCHEMA_TO_INSPECT

    def test_plain_schema_is_wrapped(self):
        self.assertEqual(self._resolve_schema_literal("dbo"), "'dbo'")

    def test_schema_with_apostrophe_is_kept_literal(self):
        # Without doubling, the literal would terminate early and the trailing
        # text would no longer be part of the schema name.
        self.assertEqual(self._resolve_schema_literal("O'Brien"), "'O''Brien'")
