"""Check the actual DB-API and native driver used by each SQL Server test alias."""
import os
import sys

import django
from django.db import connections


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "testapp.settings")
    django.setup()
    expected = os.environ.get("MSSQL_PYTHON_DRIVER", "pyodbc")
    print("Python: %s; Django: %s" % (sys.version, django.get_version()), flush=True)
    for alias in ("default", "other"):
        wrapper = connections[alias]
        params = wrapper.get_connection_params()
        # Test databases do not exist yet. Use the same driver/options against master.
        params["NAME"] = "master"
        connection = wrapper.get_new_connection(params)
        try:
            actual = wrapper.Database.__name__
            if actual != expected:
                raise RuntimeError(
                    "%s: expected %s, connected with %s" % (alias, expected, actual)
                )
            version = (wrapper.Database.__version__ if actual == "mssql_python"
                       else wrapper.Database.version)
            print(
                "%s: %s %s; native driver: %s %s" % (
                    alias, actual, version,
                    connection.getinfo(wrapper.Database.SQL_DRIVER_NAME),
                    connection.getinfo(wrapper.Database.SQL_DRIVER_VER),
                ),
                flush=True,
            )
        finally:
            connection.close()


if __name__ == "__main__":
    main()
