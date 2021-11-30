# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from django.core.management.commands.inspectdb import Command as inspectdb_Command
from django.conf import settings

class Command(inspectdb_Command):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            '--schema',
            default='dbo',
            help='Choose the database schema to inspect, default is [dbo]',
        )

    def handle(self, *args, **options):
        if options["schema"]:
            settings.SCHEMA_TO_INSPECT = options["schema"]
        return super().handle(*args, **options)
