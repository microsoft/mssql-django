import io
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from testapp import check_driver
from testapp.runners import ExcludedTestSuiteRunner


class DriverCheckTests(SimpleTestCase):
    def run_check(self, expected, actual, getinfo_error=None):
        wrappers = {}
        for alias in ("default", "other"):
            wrapper = mock.Mock()
            wrapper.Database = SimpleNamespace(
                __name__=actual, __version__="1.15.0", version="5.3.0",
                SQL_DRIVER_NAME=6, SQL_DRIVER_VER=7,
            )
            wrapper.get_connection_params.return_value = {
                "NAME": "application_db", "OPTIONS": {"python_driver": expected},
            }
            connection = wrapper.get_new_connection.return_value
            connection.getinfo.side_effect = (
                getinfo_error if getinfo_error else ["native-driver", "18.6"]
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
        for driver in ("pyodbc", "mssql_python"):
            with self.subTest(driver=driver):
                output = self.run_check(driver, driver)
                for alias, wrapper in self.wrappers.items():
                    self.assertIn("%s: %s" % (alias, driver), output)
                    wrapper.get_new_connection.assert_called_once_with({
                        "NAME": "master", "OPTIONS": {"python_driver": driver},
                    })
                    wrapper.get_new_connection.return_value.close.assert_called_once()

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
