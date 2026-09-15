# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

import datetime
import struct
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import mock

from django.db import ProgrammingError
from django.db.utils import ConnectionHandler
from django.test import SimpleTestCase

from mssql import base


class TestMssqlPythonLifecycle(SimpleTestCase):
    def setUp(self):
        # Distinct DB-API exceptions catch accidental routing through pyodbc.
        error = type("Error", (Exception,), {})
        database_error = type("DatabaseError", (error,), {})
        self.driver = SimpleNamespace(
            Error=error,
            DatabaseError=database_error,
            InterfaceError=type("InterfaceError", (error,), {}),
            **{
                name: type(name, (database_error,), {})
                for name in ("DataError", "OperationalError", "IntegrityError",
                             "InternalError", "ProgrammingError", "NotSupportedError")
            },
            connect=mock.MagicMock(),
            SQL_DRIVER_NAME=mock.sentinel.driver_name,
        )
        self.params = {
            "ENGINE": "mssql",
            "NAME": "testdb",
            "HOST": "example.test",
            "USER": "testuser",
            "PASSWORD": "testpass",
            "OPTIONS": {"python_driver": "mssql_python", "connection_retries": 0},
        }
        self.aliases = ConnectionHandler({
            "default": dict(self.params, OPTIONS={}),
            "optin_unit": self.params,
        })
        self.wrapper = self.aliases["optin_unit"]
        self.wrapper.get_system_datetime = datetime.datetime(2026, 1, 1)
        self.wrapper.sql_server_version = 2025
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch("mssql.base._load_mssql_python", return_value=self.driver))
        self.pyodbc_connect = stack.enter_context(mock.patch.object(base.Database, "connect"))
        self.sleep = stack.enter_context(mock.patch("mssql.base.time.sleep"))
        for connect in (self.driver.connect, self.pyodbc_connect):
            connect.return_value.getinfo.return_value = "MSODBCSQL18.DLL"
            cursor = connect.return_value.cursor.return_value
            cursor.__enter__.return_value = cursor
            cursor.execute.return_value = cursor
            cursor.fetchone.return_value = (0,)
        self.addCleanup(self.wrapper.close)

    def test_access_token_is_packed_and_passed_to_selected_driver(self):
        self.params.update(TOKEN="AB", USER="", PASSWORD="")
        self.wrapper.get_new_connection(self.params)
        args, kwargs = self.driver.connect.call_args
        self.assertEqual(kwargs, {
            "timeout": 0,
            "attrs_before": {1256: struct.pack("=i", 4) + b"A\x00B\x00"},
        })
        for keyword in ("UID=", "PWD=", "Trusted_Connection=", "Integrated Security=", "TOKEN="):
            self.assertNotIn(keyword, args[0])
        self.pyodbc_connect.assert_not_called()

    def test_encoding_options_reach_selected_connection(self):
        self.params["OPTIONS"].update(
            setencoding=[{"encoding": "utf-8"}],
            setdecoding=[{"sqltype": base.Database.SQL_CHAR, "encoding": "utf-8"}],
        )
        connection = self.wrapper.get_new_connection(self.params)
        connection.setencoding.assert_called_once_with(encoding="utf-8")
        connection.setdecoding.assert_called_once_with(
            sqltype=base.Database.SQL_CHAR, encoding="utf-8"
        )

    def test_connection_initialization_uses_selected_driver_constants(self):
        self.wrapper.ensure_connection()
        self.driver.connect.return_value.getinfo.assert_called_once_with(self.driver.SQL_DRIVER_NAME)
        self.assertTrue(self.wrapper._is_microsoft_driver)
        self.assertFalse(self.wrapper.supports_mars)
        self.assertFalse(self.wrapper.features.can_use_chunked_reads)

    def test_reconnection_refreshes_mars_capabilities_for_selected_driver(self):
        for driver, expected in (("pyodbc", True), ("mssql_python", False), ("pyodbc", True)):
            with self.subTest(driver=driver):
                self.wrapper.close()
                self.params["OPTIONS"]["python_driver"] = driver
                self.wrapper.ensure_connection()
                self.assertEqual(self.wrapper.supports_mars, expected)
                self.assertEqual(self.wrapper.features.can_use_chunked_reads, expected)

    def test_cursor_errors_use_selected_driver_for_execute_and_executemany(self):
        self.wrapper.ensure_connection()
        for operation, params in (("execute", [1]), ("executemany", [[1], [2]])):
            with self.subTest(operation=operation):
                error = self.driver.ProgrammingError("Invalid SQL")
                raw_cursor = self.wrapper.connection.cursor.return_value
                getattr(raw_cursor, operation).side_effect = error
                with mock.patch.object(self.wrapper, "_on_error") as on_error:
                    with self.assertRaises(ProgrammingError) as raised:
                        with self.wrapper.cursor() as cursor:
                            getattr(cursor, operation)("SELECT %s", params)
                self.assertIs(raised.exception.__cause__, error)
                on_error.assert_called_once_with(error)

    def test_is_usable_handles_only_selected_driver_errors(self):
        self.wrapper.ensure_connection()
        raw_cursor = self.wrapper.connection.cursor.return_value
        self.assertTrue(self.wrapper.is_usable())
        raw_cursor.execute.side_effect = self.driver.Error("Connection lost")
        self.assertFalse(self.wrapper.is_usable())
        raw_cursor.execute.side_effect = ValueError("Invalid argument")
        with self.assertRaises(ValueError):
            self.wrapper.is_usable()

    def test_network_error_clears_connection_and_reconnects(self):
        self.wrapper.ensure_connection()
        stale = self.wrapper.connection
        self.wrapper._on_error(self.driver.Error("Communication link failure [08S01]"))
        stale.close.assert_called_once_with()
        self.assertIsNone(self.wrapper.connection)
        fresh = mock.MagicMock()
        fresh.getinfo.return_value = "MSODBCSQL18.DLL"
        cursor = fresh.cursor.return_value
        cursor.__enter__.return_value = cursor
        cursor.execute.return_value = cursor
        cursor.fetchone.return_value = (0,)
        self.driver.connect.return_value = fresh
        self.wrapper.ensure_connection()
        self.assertIs(self.wrapper.connection, fresh)
        self.assertIs(self.wrapper.Database, self.driver)
        self.assertEqual(self.driver.connect.call_count, 2)
        self.pyodbc_connect.assert_not_called()

    def test_non_network_error_does_not_close_connection(self):
        self.wrapper.ensure_connection()
        current = self.wrapper.connection
        self.wrapper._on_error(self.driver.ProgrammingError("Invalid object name"))
        self.assertIs(self.wrapper.connection, current)
        current.close.assert_not_called()
        self.sleep.assert_not_called()

    def test_mixed_aliases_keep_exception_modules_independent(self):
        for alias in ("optin_unit", "default"):
            wrapper = self.aliases[alias]
            wrapper.get_new_connection(wrapper.get_connection_params())
        default = self.aliases["default"]
        self.assertIs(default.Database, base.Database)
        self.assertIs(self.wrapper.Database, self.driver)
        for wrapper, driver in ((default, base.Database), (self.wrapper, self.driver)):
            with self.subTest(alias=wrapper.alias):
                error = driver.ProgrammingError("Invalid SQL")
                with self.assertRaises(ProgrammingError) as raised:
                    with wrapper.wrap_database_errors:
                        raise error
                self.assertIs(raised.exception.__cause__, error)
        self.assertIs(base.DatabaseWrapper.Database, base.Database)
