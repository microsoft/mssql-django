"""Check the actual DB-API and native driver used by each SQL Server test alias."""
import os
import sys

import django
from django.db import connections

def _expected_dbapi(configured, uses_mssql_python):
    value = (configured or '').strip()
    if not value or value.lower() == 'pyodbc':
        return 'pyodbc'
    if uses_mssql_python({'OPTIONS': {'python_driver': value}}):
        return 'mssql_python'
    return value


def _native_driver_id(driver_name):
    name = os.path.basename(str(driver_name)).lower()
    if (name == 'msodbcsql18.dll' or
            name in ('libmsodbcsql.18.dylib', 'libmsodbcsql.18.so') or
            name.startswith('libmsodbcsql-18.') and '.so' in name):
        return 'msodbcsql18'
    return name


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "testapp.settings")
    django.setup()
    from mssql.base import DatabaseWrapper

    expected = _expected_dbapi(
        os.environ.get("MSSQL_PYTHON_DRIVER", "pyodbc"),
        DatabaseWrapper._uses_mssql_python)
    expected_native = os.environ.get("MSSQL_EXPECTED_NATIVE_DRIVER")
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
            native_version = connection.getinfo(
                wrapper.Database.SQL_DRIVER_VER)
            native_id = _native_driver_id(native_driver)
            if expected_native and native_id != expected_native:
                raise RuntimeError(
                    "%s: expected native driver %s, connected with %s" %
                    (alias, expected_native, native_driver)
                )
            if actual == "mssql_python" and expected_native:
                provider = wrapper.Database.get_native_provider_info()
                if (provider["id"] != expected_native or
                        provider["version"].split('.')[0] !=
                        str(native_version).split('.')[0]):
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
                    native_version,
                ),
                flush=True,
            )
        finally:
            connection.close()


if __name__ == "__main__":
    main()
