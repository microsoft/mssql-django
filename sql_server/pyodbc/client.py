from django.db.backends import BaseDatabaseClient
import os
import sys

class DatabaseClient(BaseDatabaseClient):
    if os.name=='nt':
        executable_name = 'osql'
    else:
        executable_name = 'isql'

    def runshell(self):
        settings_dict = self.connection.settings_dict
        user = settings_dict['DATABASE_OPTIONS'].get('user', settings_dict['DATABASE_USER'])
        password = settings_dict['DATABASE_OPTIONS'].get('passwd', settings_dict['DATABASE_PASSWORD'])
        if os.name=='nt':
            db = settings_dict['DATABASE_OPTIONS'].get('db', settings_dict['DATABASE_NAME'])
            server = settings_dict['DATABASE_OPTIONS'].get('host', settings_dict['DATABASE_HOST'])
            port = settings_dict['DATABASE_OPTIONS'].get('port', settings_dict['DATABASE_PORT'])
            defaults_file = settings_dict['DATABASE_OPTIONS'].get('read_default_file')

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
            dsn = settings_dict['DATABASE_OPTIONS'].get('dsn', settings_dict['DATABASE_ODBC_DSN'])
            args = ['%s -v %s %s %s' % (self.executable_name, dsn, user, password)]

        # XXX: This works only with Python >= 2.4 because subprocess was added
        # in that release
        import subprocess
        try:
            subprocess.call(args, shell=True)
        except KeyboardInterrupt:
            pass
