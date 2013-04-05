import re

from django.db.backends import BaseDatabaseClient

class DatabaseClient(BaseDatabaseClient):
    executable_name = 'sqlcmd'

    def runshell(self):
        settings_dict = self.connection.settings_dict
        options = settings_dict['OPTIONS']
        user = options.get('user', settings_dict['USER'])
        password = options.get('passwd', settings_dict['PASSWORD'])

        driver = options.get('driver', '')
        ms_drivers = re.compile('.*SQL (Server$|(Server )?Native Client)')
        if not ms_drivers.match(driver):
            self.executable_name = 'isql'

        if self.executable_name == 'sqlcmd':
            db = options.get('db', settings_dict['NAME'])
            server = options.get('host', settings_dict['HOST'])
            port = options.get('port', settings_dict['PORT'])
            defaults_file = options.get('read_default_file')

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
            dsn = options.get('dsn', '')
            args = ['%s -v %s %s %s' % (self.executable_name, dsn, user, password)]

        # XXX: This works only with Python >= 2.4 because subprocess was added
        # in that release
        import subprocess
        try:
            subprocess.call(args, shell=True)
        except KeyboardInterrupt:
            pass
