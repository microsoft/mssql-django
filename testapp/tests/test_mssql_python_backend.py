# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from contextlib import ExitStack
from types import SimpleNamespace
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from mssql import base


@override_settings(DATABASE_CONNECTION_POOLING=True)
class TestMssqlPythonLoading(SimpleTestCase):
    def test_missing_driver_has_direct_install_guidance(self):
        with mock.patch.dict("sys.modules", {"mssql_python": None}):
            with self.assertRaisesMessage(ImproperlyConfigured, "mssql-python>=1.15.0"):
                base._load_mssql_python()

    def test_rejects_versions_before_required_fixes(self):
        for version in ("1.0.0", "1.14.0"):
            with self.subTest(version=version):
                driver = SimpleNamespace(__version__=version)
                with mock.patch.dict("sys.modules", {"mssql_python": driver}):
                    with self.assertRaisesMessage(ImproperlyConfigured, "1.15.0 or newer"):
                        base._load_mssql_python()

    def test_accepts_released_version_without_changing_pyodbc(self):
        driver = SimpleNamespace(__version__="1.15.0", PoolingManager=mock.Mock())
        default_driver = base.DatabaseWrapper.Database
        with mock.patch.dict("sys.modules", {"mssql_python": driver}):
            self.assertIs(base._load_mssql_python(), driver)
        driver.PoolingManager.disable.assert_not_called()
        self.assertIs(base.DatabaseWrapper.Database, default_driver)

    @override_settings(DATABASE_CONNECTION_POOLING=False)
    def test_disables_pooling_for_selected_driver(self):
        driver = SimpleNamespace(__version__="1.15.0", PoolingManager=mock.Mock())
        with mock.patch.dict("sys.modules", {"mssql_python": driver}):
            base._load_mssql_python()
        driver.PoolingManager.disable.assert_called_once_with()


class TestMssqlPythonConnection(SimpleTestCase):
    def setUp(self):
        self.wrapper = object.__new__(base.DatabaseWrapper)
        self.params = {
            "NAME": "testdb",
            "HOST": "example.test",
            "USER": "testuser",
            "PASSWORD": "testpass",
            "OPTIONS": {
                "python_driver": "mssql_python",
                "connection_retries": 1,
                "connection_retry_backoff_time": 0,
            },
        }
        self.driver = SimpleNamespace(connect=mock.Mock())
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.loader = stack.enter_context(
            mock.patch("mssql.base._load_mssql_python", return_value=self.driver)
        )
        self.pyodbc_connect = stack.enter_context(mock.patch.object(base.Database, "connect"))
        self.sleep = stack.enter_context(mock.patch("mssql.base.time.sleep"))

    def test_opt_in_connect_arguments_and_converter(self):
        self.params["OPTIONS"].update(connection_timeout=7, query_timeout=9, unicode_results=True)
        with mock.patch("mssql.base.os.name", "nt"):
            connection = self.wrapper.get_new_connection(self.params)
        self.assertIs(connection, self.driver.connect.return_value)
        self.assertIs(self.wrapper.Database, self.driver)
        args, kwargs = self.driver.connect.call_args
        self.assertEqual(kwargs, {"timeout": 7})
        for keyword in ("DRIVER=", "DSN=", "SERVERNAME=", "MARS_Connection="):
            self.assertNotIn(keyword, args[0])
        self.assertIn("SERVER=example.test", args[0])
        self.assertEqual(connection.timeout, 9)
        connection.add_output_converter.assert_not_called()
        self.pyodbc_connect.assert_not_called()

    def test_default_driver_is_not_changed_by_another_wrapper(self):
        self.wrapper.get_new_connection(self.params)
        default_wrapper = object.__new__(base.DatabaseWrapper)
        default_params = dict(self.params, OPTIONS={})
        connection = default_wrapper.get_new_connection(default_params)
        self.assertIs(default_wrapper.Database, base.Database)
        self.assertIs(self.wrapper.Database, self.driver)
        self.loader.assert_called_once_with()
        self.assertIn("unicode_results", self.pyodbc_connect.call_args.kwargs)
        connection.add_output_converter.assert_called_once_with(
            base.SQL_TIMESTAMP_WITH_TIMEZONE, base.handle_datetimeoffset
        )

    def test_reconnection_can_return_to_default_driver(self):
        self.wrapper.get_new_connection(self.params)
        self.params["OPTIONS"].pop("python_driver")
        self.wrapper.get_new_connection(self.params)
        self.assertIs(self.wrapper.Database, base.Database)
        self.assertFalse(self.wrapper._use_python_driver)
        self.pyodbc_connect.assert_called_once()

    def test_permanent_error_after_transient_error_is_not_retried(self):
        for driver_name, connect in (
            ("mssql_python", self.driver.connect),
            ("pyodbc", self.pyodbc_connect),
        ):
            with self.subTest(driver=driver_name):
                self.wrapper = object.__new__(base.DatabaseWrapper)
                connect.reset_mock()
                self.params["OPTIONS"]["python_driver"] = driver_name
                transient = RuntimeError("42000", "Service unavailable (40613)")
                permanent = RuntimeError("28000", "Login failed (18456)")
                connect.side_effect = [transient, permanent, mock.Mock()]
                with self.assertRaises(RuntimeError) as raised:
                    self.wrapper.get_new_connection(self.params)
                self.assertIs(raised.exception, permanent)
                self.assertEqual(connect.call_count, 2)

    def test_retry_limit_applies_to_each_driver(self):
        for driver_name, connect in (
            ("mssql_python", self.driver.connect),
            ("pyodbc", self.pyodbc_connect),
        ):
            with self.subTest(driver=driver_name):
                self.wrapper = object.__new__(base.DatabaseWrapper)
                connect.reset_mock()
                self.params["OPTIONS"]["python_driver"] = driver_name
                error = RuntimeError("42000", "Service unavailable (40613)")
                connect.side_effect = [error, error, mock.Mock()]
                with self.assertRaises(RuntimeError):
                    self.wrapper.get_new_connection(self.params)
                self.assertEqual(connect.call_count, 2)

    def test_single_argument_error_is_preserved(self):
        self.params["OPTIONS"]["python_driver"] = "pyodbc"
        error = ValueError("invalid connection option")
        self.pyodbc_connect.side_effect = error
        with self.assertRaises(ValueError) as raised:
            self.wrapper.get_new_connection(self.params)
        self.assertIs(raised.exception, error)
        self.sleep.assert_not_called()

    def test_mssql_python_does_not_attempt_odbc_driver_fallback(self):
        error = RuntimeError("driver not found")
        self.driver.connect.side_effect = error
        with self.assertRaises(RuntimeError) as raised:
            self.wrapper.get_new_connection(self.params)
        self.assertIs(raised.exception, error)
        self.driver.connect.assert_called_once()
        self.pyodbc_connect.assert_not_called()
