# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

import re
import subprocess

from django.db.backends.base.client import BaseDatabaseClient


class DatabaseClient(BaseDatabaseClient):
    executable_name = 'sqlcmd'

    @classmethod
    def settings_to_cmd_args(cls, settings_dict, parameters):
        options = settings_dict['OPTIONS']
        user = options.get('user', settings_dict['USER'])
        password = options.get('passwd', settings_dict['PASSWORD'])

        driver = options.get('driver', 'ODBC Driver 13 for SQL Server')
        ms_drivers = re.compile('^ODBC Driver .* for SQL Server$|^SQL Server Native Client')
        if not ms_drivers.match(driver):
            cls.executable_name = 'isql'

        if cls.executable_name == 'sqlcmd':
            db = options.get('db', settings_dict['NAME'])
            server = options.get('host', settings_dict['HOST'])
            port = options.get('port', settings_dict['PORT'])
            defaults_file = options.get('read_default_file')

            args = [cls.executable_name]
            if server:
                if port:
                    server = ','.join((server, str(port)))
                args += ["-S", server]
            if user:
                args += ["-U", user]
                if password:
                    args += ["-P", password]
            else:
                args += ["-E"]  # Try trusted connection instead
            if db:
                args += ["-d", db]
            if defaults_file:
                args += ["-i", defaults_file]
        else:
            dsn = options.get('dsn', '')
            args = ['%s -v %s %s %s' % (cls.executable_name, dsn, user, password)]

        args.extend(parameters)
        return args

    def runshell(self, parameters=[]):
        args = DatabaseClient.settings_to_cmd_args(self.connection.settings_dict, parameters)
        subprocess.run(args, check=True)
