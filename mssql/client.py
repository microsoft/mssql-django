from django.db.backends import BaseDatabaseClient
from django.conf import settings
import os
import sys

class DatabaseClient(BaseDatabaseClient):
    def runshell(self):
        if os.name=='nt':
            db = settings.DATABASE_OPTIONS.get('db', settings.DATABASE_NAME)
            user = settings.DATABASE_OPTIONS.get('user', settings.DATABASE_USER)
            password = settings.DATABASE_OPTIONS.get('passwd', settings.DATABASE_PASSWORD)
            server = settings.DATABASE_OPTIONS.get('host', settings.DATABASE_HOST)
            port = settings.DATABASE_OPTIONS.get('port', settings.DATABASE_PORT)
            defaults_file = settings.DATABASE_OPTIONS.get('read_default_file')

            args = ['osql']
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
            user = settings.DATABASE_OPTIONS.get('user', settings.DATABASE_USER)
            password = settings.DATABASE_OPTIONS.get('passwd', settings.DATABASE_PASSWORD)
            args = ['isql -v %s %s %s' %(dsn, user, password)]

        import subprocess
        try:
            retcode = subprocess.call(args, shell=True)
            if retcode:
                print >>sys.stderr, "error level:", retcode
                sys.exit(retcode)
        except KeyboardInterrupt:
            pass
        except OSError, e:
            print >>sys.stderr, "Execution failed:", e

