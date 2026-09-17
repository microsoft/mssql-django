import io
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from testapp import check_driver
from testapp.runners import ExcludedTestSuiteRunner


class DriverCheckTests(SimpleTestCase):
    def run_check(self, expected, actual, getinfo_error=None,
                  native_driver="libmsodbcsql-18.6.so.2.1", provider=None,
                  expected_native="msodbcsql18"):
        wrappers = {}
        for alias in ("default", "other"):
            wrapper = mock.Mock()
            wrapper.Database = SimpleNamespace(
                __name__=actual, __version__="1.15.0", version="5.3.0",
                SQL_DRIVER_NAME=6, SQL_DRIVER_VER=7,
                get_native_provider_info=mock.Mock(return_value=provider or {
                    "id": "msodbcsql18",
                    "package": "mssql_python_odbc",
                    "version": "18.6.2.1",
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
        env = {"MSSQL_PYTHON_DRIVER": expected}
        if expected_native:
            env["MSSQL_EXPECTED_NATIVE_DRIVER"] = expected_native
        with mock.patch.object(check_driver, "connections", wrappers), \
                mock.patch.object(check_driver.django, "setup"), \
                mock.patch.dict("os.environ", env, clear=True), \
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
                    version = "1.15.0" if actual == "mssql_python" else "5.3.0"
                    self.assertIn(
                        "%s: %s %s; native driver: "
                        "libmsodbcsql-18.6.so.2.1 18.6" %
                        (alias, actual, version),
                        output,
                    )
                    wrapper.get_new_connection.assert_called_once_with({
                        "NAME": "master", "OPTIONS": {"python_driver": configured},
                    })
                    self.assertEqual(
                        wrapper.get_new_connection.return_value.getinfo.call_args_list,
                        [mock.call(6), mock.call(7)],
                    )
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
                RuntimeError,
                "expected native driver msodbcsql18, connected with libtdsodbc.so"):
            self.run_check("pyodbc", "pyodbc", native_driver="libtdsodbc.so")
        self.wrappers["default"].get_new_connection.return_value.close.assert_called_once()

    def test_wrong_mssql_python_provider_fails_and_closes_connection(self):
        provider = {
            "id": "mssql-odbc",
            "package": "mssql_python_rs",
            "version": "1.0.0",
            "driver_path": "/driver/libmssql-odbc.so",
        }
        with self.assertRaisesRegex(
                RuntimeError, "unexpected mssql-python native provider"):
            self.run_check("mssql_python", "mssql_python", provider=provider)
        self.wrappers["default"].get_new_connection.return_value.close.assert_called_once()

    def test_odbc_driver_18_names_are_normalized(self):
        for driver_name in (
                "MSODBCSQL18.DLL",
                "libmsodbcsql.18.dylib",
                "libmsodbcsql.18.so",
                "libmsodbcsql-18.6.so.2.1"):
            with self.subTest(driver_name=driver_name):
                self.assertEqual(
                    check_driver._native_driver_id(driver_name), "msodbcsql18")

    def test_native_check_is_limited_to_configured_ci_jobs(self):
        output = self.run_check(
            "pyodbc", "pyodbc", native_driver="libtdsodbc.so",
            expected_native=None)
        self.assertIn("native driver: libtdsodbc.so", output)

    def test_xml_runner_preserves_requested_verbosity(self):
        suite = mock.Mock()
        with mock.patch("builtins.open", mock.mock_open()) as output, \
                mock.patch("testapp.runners.xmlrunner.XMLTestRunner") as runner:
            result = ExcludedTestSuiteRunner(verbosity=2).run_suite(suite)
        runner.assert_called_once_with(
            output=output.return_value, verbosity=2, descriptions=False,
        )
        runner.return_value.run.assert_called_once_with(suite)
        self.assertIs(result, runner.return_value.run.return_value)
