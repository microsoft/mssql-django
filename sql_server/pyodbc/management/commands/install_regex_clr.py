# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

# Add regex support in SQLServer
# Code taken from django-mssql (see https://bitbucket.org/Manfre/django-mssql)

from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Installs the regex_clr.dll assembly with the database"

    requires_model_validation = False

    args = 'database_name'

    def add_arguments(self, parser):
        parser.add_argument('database_name')

    def handle(self, *args, **options):
        database_name = options['database_name']
        if not database_name:
            self.print_help('manage.py', 'install_regex_clr')
            return

        connection.creation.install_regex_clr(database_name)
        print('Installed regex_clr to database %s' % database_name)
