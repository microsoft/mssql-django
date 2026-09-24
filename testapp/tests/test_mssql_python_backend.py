# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

import datetime
import uuid
from contextlib import ExitStack, closing
from types import SimpleNamespace
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings

from mssql import base
from mssql.compiler import _cursor_iter
from testapp.models import UUIDModel


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
        connection = self.wrapper.get_new_connection(self.params)
        self.assertIs(connection, self.driver.connect.return_value)
        self.assertIs(self.wrapper.Database, self.driver)
        args, kwargs = self.driver.connect.call_args
        self.assertEqual(kwargs, {"timeout": 7, "native_uuid": False})
        for keyword in ("DRIVER=", "DSN=", "SERVERNAME=", "MARS_Connection="):
            self.assertNotIn(keyword, args[0])
        self.assertIn("SERVER=example.test", args[0])
        self.assertEqual(connection.timeout, 9)
        connection.add_output_converter.assert_not_called()
        self.pyodbc_connect.assert_not_called()

    def test_empty_host_uses_localhost(self):
        self.params["HOST"] = ""

        self.wrapper.get_new_connection(self.params)

        self.assertIn("SERVER=localhost", self.driver.connect.call_args.args[0])
        self.pyodbc_connect.assert_not_called()

    def test_empty_host_preserves_pyodbc_connection_string(self):
        self.params["HOST"] = ""
        self.params["OPTIONS"]["python_driver"] = "pyodbc"

        self.wrapper.get_new_connection(self.params)

        self.assertIn("SERVER=;", self.pyodbc_connect.call_args.args[0])
        self.loader.assert_not_called()

    def test_explicit_extra_params_replace_generated_keywords(self):
        generated = {
            "SERVER": "example.test",
            "UID": "testuser",
            "PWD": "testpass",
            "DATABASE": "testdb",
        }
        for key in generated:
            with self.subTest(key=key):
                extra = " %s = {override;value}}suffix}" % key.lower()
                self.params["OPTIONS"]["extra_params"] = extra
                self.wrapper.get_new_connection(self.params)
                expected = {k: v for k, v in generated.items() if k != key}
                self.assertEqual(
                    self.driver.connect.call_args.args[0],
                    base.encode_connection_string(expected) + ";" + extra,
                )
        self.pyodbc_connect.assert_not_called()

    def test_explicit_trusted_connection_replaces_default(self):
        self.params.update(USER="", PASSWORD="")
        for value in ("yes", "no"):
            with self.subTest(value=value):
                extra = " trusted_connection = {%s}" % value
                self.params["OPTIONS"]["extra_params"] = extra
                self.wrapper.get_new_connection(self.params)
                self.assertEqual(
                    self.driver.connect.call_args.args[0],
                    "SERVER=example.test;DATABASE=testdb;" + extra,
                )

    def test_explicit_server_aliases_replace_generated_server(self):
        for alias in ("Address", "Addr"):
            with self.subTest(alias=alias):
                extra = alias + "=override.example.test"
                self.params["OPTIONS"]["extra_params"] = extra
                self.wrapper.get_new_connection(self.params)
                connstr = self.driver.connect.call_args.args[0]
                self.assertNotIn("SERVER=example.test", connstr)
                self.assertTrue(connstr.endswith(";" + extra))

    def test_braced_keyword_text_does_not_override_generated_server(self):
        extra = "ApplicationIntent={ReadOnly;SERVER=not-a-server}"
        self.params["OPTIONS"]["extra_params"] = extra
        self.wrapper.get_new_connection(self.params)
        connstr = self.driver.connect.call_args.args[0]
        self.assertTrue(connstr.startswith("SERVER=example.test;"))
        self.assertTrue(connstr.endswith(";" + extra))

    def test_invalid_user_extras_are_preserved_for_driver_validation(self):
        for extra in ("SERVER=first;server=second", "SERVER=", "UnknownKeyword=value"):
            with self.subTest(extra=extra):
                self.params["OPTIONS"]["extra_params"] = extra
                self.wrapper.get_new_connection(self.params)
                self.assertTrue(self.driver.connect.call_args.args[0].endswith(";" + extra))

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

    def test_mssql_python_communication_failure_clears_connection(self):
        stale = mock.Mock()
        error = RuntimeError(
            "Driver Error: Communication link failure; "
            "DDBC Error: [Microsoft]TCP Provider: Error code 0x2746"
        )
        error.driver_error = "Communication link failure"
        self.wrapper._use_python_driver = True
        self.wrapper.connection = stale
        self.wrapper.connection_recovery_interval_msec = 0
        self.wrapper.close = mock.Mock()

        self.wrapper._on_error(error)

        self.wrapper.close.assert_called_once_with()
        self.assertIsNone(self.wrapper.connection)


class TestMssqlPythonConnectionState(SimpleTestCase):
    def test_mars_capabilities_follow_driver_on_reinitialization(self):
        wrapper = base.DatabaseWrapper({"OPTIONS": {}}, alias="optin_mars")
        wrapper.connection = mock.MagicMock()
        wrapper.get_system_datetime = datetime.datetime(2026, 1, 1)
        for use_python_driver, native_driver, expected in (
            (False, "MSODBCSQL18.DLL", True),
            (True, "MSODBCSQL18.DLL", False),
            (False, "MSODBCSQL18.DLL", True),
            (True, "libmsodbcsql.18.dylib", False),
            (False, "MSODBCSQL18.DLL", True),
            (False, "libtdsodbc.so", False),
        ):
            with self.subTest(python_driver=use_python_driver, native_driver=native_driver):
                wrapper._use_python_driver = use_python_driver
                wrapper.connection.getinfo.return_value = native_driver
                wrapper.init_connection_state()
                self.assertEqual(wrapper.supports_mars, expected)
                self.assertEqual(wrapper.features.can_use_chunked_reads, expected)
                if use_python_driver:
                    self.assertTrue(wrapper._is_microsoft_driver)
                    cursor = wrapper.create_cursor()
                    cursor.cursor.fetchone.side_effect = [(1,), (2,)]
                    self.assertEqual(cursor.fetchone(), (1,))
                    self.assertEqual(cursor.fetchone(), (2,))
                    cursor.cursor.nextset.assert_not_called()


class TestMssqlPythonIteration(TestCase):
    def test_native_uniqueidentifier_converts_to_uuid(self):
        value = uuid.UUID("01234567-89ab-cdef-0123-456789abcdef")
        rows = UUIDModel.objects.raw(
            "SELECT CAST(%s AS uniqueidentifier) AS id", [str(value)]
        )
        self.assertEqual(list(rows)[0].pk, value)

    def test_non_mars_iteration_allows_nested_query(self):
        wrapper = connection.copy(alias="non_mars_iteration")
        self.addCleanup(wrapper.close)
        options = wrapper.settings_dict["OPTIONS"]
        if not wrapper._uses_mssql_python(wrapper.settings_dict):
            options["extra_params"] = "MARS_Connection=no;" + (options.get("extra_params") or "")
        payload = "x" * 1024
        # Exceed native result buffering so the first chunk leaves unread rows.
        with wrapper.cursor() as cursor:
            cursor.execute("""
                WITH d(n) AS (SELECT n FROM
                    (VALUES (0),(1),(2),(3),(4),(5),(6),(7),(8),(9)) x(n))
                SELECT TOP (2000)
                    ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS n,
                    CAST(REPLICATE(N'x', 1024) AS nvarchar(1024))
                FROM d a CROSS JOIN d b CROSS JOIN d c CROSS JOIN d e
                ORDER BY n
            """)
            with closing(_cursor_iter(cursor, [], None, 2)) as chunks:
                self.assertEqual(next(chunks), [(1, payload), (2, payload)])
                with wrapper.cursor() as nested:
                    nested.execute("SELECT 42")
                    self.assertEqual(nested.fetchone(), (42,))
                self.assertEqual(
                    [row for chunk in chunks for row in chunk],
                    [(i, payload) for i in range(3, 2001)],
                )
