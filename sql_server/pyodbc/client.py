from django.db.backends import BaseDatabaseClient
from django.conf import settings
import os
import sys

class DatabaseClient(BaseDatabaseClient):
    if os.name=='nt':
        executable_name = 'osql'
    else:
        executable_name = 'isql'

    def runshell(self):
        user = settings.DATABASE_OPTIONS.get('user', settings.DATABASE_USER)
        password = settings.DATABASE_OPTIONS.get('passwd', settings.DATABASE_PASSWORD)
        if os.name=='nt':
            db = settings.DATABASE_OPTIONS.get('db', settings.DATABASE_NAME)
            server = settings.DATABASE_OPTIONS.get('host', settings.DATABASE_HOST)
            port = settings.DATABASE_OPTIONS.get('port', settings.DATABASE_PORT)
            defaults_file = settings.DATABASE_OPTIONS.get('read_default_file')

            args = [self.executable_name]
            if server:
                args += ["-S", server]
            if user:
                args += ["-U", user]
                if password:
                    args += ["-P", password]
            else:
                args += ["-E"] # Try trusted connection instead
            if db:
                args += ["-d", db]
            if defaults_file:
                args += ["-i", defaults_file]
        else:
            dsn = settings.DATABASE_OPTIONS.get('dsn', settings.DATABASE_ODBC_DSN)
            args = ['%s -v %s %s %s' % (self.executable_name, dsn, user, password)]

        import subprocess
        try:
            subprocess.call(args, shell=True)
        except KeyboardInterrupt:
            pass
