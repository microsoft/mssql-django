import io
import os
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from testapp import check_driver
from testapp.runners import ExcludedTestSuiteRunner


class DriverCheckTests(SimpleTestCase):
    def native_driver(self):
        if os.name == "nt":
            return "MSODBCSQL18.DLL"
        if sys.platform == "darwin":
            return "libmsodbcsql.18.dylib"
        return "libmsodbcsql-18.6.so.2.1"

    def run_check(self, expected, actual, getinfo_error=None,
                  native_driver=None, provider=None):
        wrappers = {}
        for alias in ("default", "other"):
            wrapper = mock.Mock()
            native_driver = native_driver or self.native_driver()
            wrapper.Database = SimpleNamespace(
                __name__=actual, __version__="1.15.0", version="5.3.0",
                SQL_DRIVER_NAME=6, SQL_DRIVER_VER=7,
                get_native_provider_info=mock.Mock(return_value=provider or {
                    "id": "msodbcsql18",
                    "package": "mssql_python_odbc",
                    "driver_path": "/driver/" + native_driver,
                }),
            )
            wrapper.get_connection_params.return_value = {
                "NAME": "application_db", "OPTIONS": {"python_driver": expected},
            }
            connection = wrapper.get_new_connection.return_value
            connection.getinfo.side_effect = (
                getinfo_error if getinfo_error else [native_driver, "18.6"]
            )
            wrappers[alias] = wrapper
        self.wrappers = wrappers
        with mock.patch.object(check_driver, "connections", wrappers), \
                mock.patch.object(check_driver.django, "setup"), \
                mock.patch.dict("os.environ", {"MSSQL_PYTHON_DRIVER": expected}), \
                redirect_stdout(io.StringIO()) as output:
            check_driver.main()
        return output.getvalue()

    def test_reports_both_aliases_and_closes_connections(self):
        for configured, actual in (
                ("pyodbc", "pyodbc"),
                ("", "pyodbc"),
                ("mssql_python", "mssql_python"),
                ("mssql-python", "mssql_python"),
                ("python", "mssql_python"),
                (" MSSQL_PYTHON ", "mssql_python")):
            with self.subTest(configured=configured):
                output = self.run_check(configured, actual)
                for alias, wrapper in self.wrappers.items():
                    self.assertIn("%s: %s" % (alias, actual), output)
                    wrapper.get_new_connection.assert_called_once_with({
                        "NAME": "master", "OPTIONS": {"python_driver": configured},
                    })
                    wrapper.get_new_connection.return_value.close.assert_called_once()

    def test_unknown_driver_alias_fails(self):
        with self.assertRaisesRegex(
                RuntimeError, "expected unknown, connected with pyodbc"):
            self.run_check("unknown", "pyodbc")

    def test_wrong_driver_fails_and_closes_connection(self):
        with self.assertRaisesRegex(RuntimeError, "expected mssql_python, connected with pyodbc"):
            self.run_check("mssql_python", "pyodbc")
        self.wrappers["default"].get_new_connection.return_value.close.assert_called_once()
        self.wrappers["other"].get_new_connection.assert_not_called()

    def test_diagnostic_error_propagates_and_closes_connection(self):
        error = RuntimeError("getinfo failed")
        with self.assertRaises(RuntimeError) as caught:
            self.run_check("pyodbc", "pyodbc", error)
        self.assertIs(caught.exception, error)
        self.wrappers["default"].get_new_connection.return_value.close.assert_called_once()

    def test_wrong_native_driver_fails_and_closes_connection(self):
        with self.assertRaisesRegex(
                RuntimeError, "expected ODBC Driver 18, connected with libtdsodbc.so"):
            self.run_check("pyodbc", "pyodbc", native_driver="libtdsodbc.so")
        self.wrappers["default"].get_new_connection.return_value.close.assert_called_once()

    def test_wrong_mssql_python_provider_fails_and_closes_connection(self):
        provider = {
            "id": "mssql-odbc",
            "package": "mssql_python_rs",
            "driver_path": "/driver/libmssql-odbc.so",
        }
        with self.assertRaisesRegex(
                RuntimeError, "unexpected mssql-python native provider"):
            self.run_check("mssql_python", "mssql_python", provider=provider)
        self.wrappers["default"].get_new_connection.return_value.close.assert_called_once()

    def test_odbc_driver_18_names_are_platform_specific(self):
        for os_name, platform, driver_name in (
                ("nt", "win32", "MSODBCSQL18.DLL"),
                ("posix", "darwin", "libmsodbcsql.18.dylib"),
                ("posix", "linux", "libmsodbcsql-18.6.so.2.1")):
            with self.subTest(platform=platform), \
                    mock.patch.object(check_driver.os, "name", os_name), \
                    mock.patch.object(check_driver.sys, "platform", platform):
                self.assertTrue(check_driver._is_odbc_driver_18(driver_name))

    def test_xml_runner_preserves_requested_verbosity(self):
        suite = mock.Mock()
        with mock.patch("testapp.runners.open", mock.mock_open()) as output, \
                mock.patch("testapp.runners.xmlrunner.XMLTestRunner") as runner:
            result = ExcludedTestSuiteRunner(verbosity=2).run_suite(suite)
        runner.assert_called_once_with(
            output=output.return_value, verbosity=2, descriptions=False,
        )
        runner.return_value.run.assert_called_once_with(suite)
        self.assertIs(result, runner.return_value.run.return_value)
