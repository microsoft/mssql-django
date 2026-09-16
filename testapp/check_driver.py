"""Check the actual DB-API and native driver used by each SQL Server test alias."""
import os
import sys

import django
from django.db import connections

from mssql.base import DatabaseWrapper


def _expected_dbapi(configured):
    value = (configured or '').strip()
    if not value or value.lower() == 'pyodbc':
        return 'pyodbc'
    if DatabaseWrapper._uses_mssql_python(
            {'OPTIONS': {'python_driver': value}}):
        return 'mssql_python'
    return value


def _is_odbc_driver_18(driver_name):
    name = os.path.basename(str(driver_name)).lower()
    if os.name == 'nt':
        return name == 'msodbcsql18.dll'
    if sys.platform == 'darwin':
        return name == 'libmsodbcsql.18.dylib'
    return name.startswith('libmsodbcsql-18.') and '.so' in name


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "testapp.settings")
    django.setup()
    expected = _expected_dbapi(
        os.environ.get("MSSQL_PYTHON_DRIVER", "pyodbc"))
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
            native_driver = connection.getinfo(
                wrapper.Database.SQL_DRIVER_NAME)
            if not _is_odbc_driver_18(native_driver):
                raise RuntimeError(
                    "%s: expected ODBC Driver 18, connected with %s" %
                    (alias, native_driver)
                )
            if actual == "mssql_python":
                provider = wrapper.Database.get_native_provider_info()
                provider_driver = os.path.basename(provider["driver_path"])
                if (provider["id"] != "msodbcsql18" or
                        provider["package"] != "mssql_python_odbc" or
                        provider_driver.lower() !=
                        os.path.basename(str(native_driver)).lower()):
                    raise RuntimeError(
                        "%s: unexpected mssql-python native provider %r" %
                        (alias, provider)
                    )
            version = (wrapper.Database.__version__ if actual == "mssql_python"
                       else wrapper.Database.version)
            print(
                "%s: %s %s; native driver: %s %s" % (
                    alias, actual, version,
                    native_driver,
                    connection.getinfo(wrapper.Database.SQL_DRIVER_VER),
                ),
                flush=True,
            )
        finally:
            connection.close()


if __name__ == "__main__":
    main()
