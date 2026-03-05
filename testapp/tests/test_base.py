# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

"""
Tests for mssql/base.py utility functions and classes.
"""
import struct
import datetime
from decimal import Decimal
from uuid import UUID
from unittest import mock

from django.test import TestCase, SimpleTestCase

from mssql.base import (
    encode_connection_string,
    encode_value,
    prepare_token_for_odbc,
    handle_datetimeoffset,
    DatabaseWrapper,
)


class TestEncodeValue(SimpleTestCase):
    """Tests for the encode_value function."""

    def test_simple_value(self):
        """Simple values without special characters should pass through unchanged."""
        self.assertEqual(encode_value('simple'), 'simple')
        self.assertEqual(encode_value('MyPassword123'), 'MyPassword123')

    def test_value_with_semicolon(self):
        """Values containing semicolons should be wrapped in curly braces."""
        self.assertEqual(encode_value('pass;word'), '{pass;word}')
        self.assertEqual(encode_value('a;b;c'), '{a;b;c}')

    def test_value_starting_with_curly_brace(self):
        """Values starting with { should be wrapped and escaped."""
        # '{value}' -> the } is escaped to }}, then wrapped: {{value}}}
        self.assertEqual(encode_value('{value}'), '{{value}}}')
        self.assertEqual(encode_value('  {spaced}'), '{  {spaced}}}')

    def test_value_with_right_curly_brace(self):
        """Right curly braces should be escaped when wrapping is needed."""
        self.assertEqual(encode_value('pass}word;'), '{pass}}word;}')

    def test_empty_string(self):
        """Empty string should pass through unchanged."""
        self.assertEqual(encode_value(''), '')


class TestEncodeConnectionString(SimpleTestCase):
    """Tests for the encode_connection_string function."""

    def test_simple_connection_string(self):
        """Test basic connection string encoding."""
        fields = {'DRIVER': 'ODBC Driver 18 for SQL Server', 'SERVER': 'localhost'}
        result = encode_connection_string(fields)
        self.assertIn('DRIVER=ODBC Driver 18 for SQL Server', result)
        self.assertIn('SERVER=localhost', result)

    def test_connection_string_with_special_chars(self):
        """Test connection string with values containing special characters."""
        fields = {'PASSWORD': 'pass;word'}
        result = encode_connection_string(fields)
        self.assertEqual(result, 'PASSWORD={pass;word}')

    def test_empty_fields(self):
        """Test with empty fields dictionary."""
        result = encode_connection_string({})
        self.assertEqual(result, '')

    def test_multiple_fields(self):
        """Test with multiple fields."""
        fields = {
            'DRIVER': 'ODBC Driver 18 for SQL Server',
            'SERVER': 'localhost',
            'DATABASE': 'testdb',
            'UID': 'testuser',
        }
        result = encode_connection_string(fields)
        # All keys should be present
        for key in fields:
            self.assertIn(f'{key}=', result)


class TestPrepareTokenForOdbc(SimpleTestCase):
    """Tests for the prepare_token_for_odbc function."""

    def test_simple_token(self):
        """Test token preparation for a simple string."""
        token = "ABC"
        result = prepare_token_for_odbc(token)
        # Result should be bytes
        self.assertIsInstance(result, bytes)
        # Should start with 4-byte length header
        length = struct.unpack("=i", result[:4])[0]
        self.assertEqual(length, len(token) * 2)  # Each char becomes 2 bytes

    def test_token_content(self):
        """Test that token is properly expanded with null bytes."""
        token = "AB"
        result = prepare_token_for_odbc(token)
        # Skip the 4-byte length header
        payload = result[4:]
        # 'A' should be followed by null byte
        self.assertEqual(payload[0], ord('A'))
        self.assertEqual(payload[1], 0)
        # 'B' should be followed by null byte
        self.assertEqual(payload[2], ord('B'))
        self.assertEqual(payload[3], 0)

    def test_invalid_token_type(self):
        """Test that non-string tokens raise TypeError."""
        with self.assertRaises(TypeError) as cm:
            prepare_token_for_odbc(12345)
        self.assertIn("Invalid token format", str(cm.exception))

        with self.assertRaises(TypeError):
            prepare_token_for_odbc(b"bytes_token")

        with self.assertRaises(TypeError):
            prepare_token_for_odbc(None)

    def test_empty_token(self):
        """Test with empty string token."""
        token = ""
        result = prepare_token_for_odbc(token)
        # Should have 4-byte header with length 0
        length = struct.unpack("=i", result[:4])[0]
        self.assertEqual(length, 0)


class TestHandleDatetimeoffset(SimpleTestCase):
    """Tests for the handle_datetimeoffset function."""

    def test_datetime_conversion(self):
        """Test conversion of binary datetime offset to Python datetime."""
        # Pack a known datetime: 2023-06-15 14:30:45.123456
        # Format: year, month, day, hour, minute, second, nanoseconds (as microseconds * 1000), tz_hour, tz_min
        dto_bytes = struct.pack("<6hI2h", 2023, 6, 15, 14, 30, 45, 123456000, 0, 0)
        result = handle_datetimeoffset(dto_bytes)

        self.assertIsInstance(result, datetime.datetime)
        self.assertEqual(result.year, 2023)
        self.assertEqual(result.month, 6)
        self.assertEqual(result.day, 15)
        self.assertEqual(result.hour, 14)
        self.assertEqual(result.minute, 30)
        self.assertEqual(result.second, 45)
        self.assertEqual(result.microsecond, 123456)

    def test_datetime_edge_case(self):
        """Test with edge case values."""
        # Midnight on Jan 1, 2000
        dto_bytes = struct.pack("<6hI2h", 2000, 1, 1, 0, 0, 0, 0, 0, 0)
        result = handle_datetimeoffset(dto_bytes)

        self.assertEqual(result.year, 2000)
        self.assertEqual(result.month, 1)
        self.assertEqual(result.day, 1)
        self.assertEqual(result.hour, 0)
        self.assertEqual(result.minute, 0)
        self.assertEqual(result.second, 0)
        self.assertEqual(result.microsecond, 0)


class TestDatabaseWrapperIsDriverNotFoundError(SimpleTestCase):
    """Tests for the _is_driver_not_found_error method."""

    def setUp(self):
        # Create a mock DatabaseWrapper to test the method
        self.wrapper = object.__new__(DatabaseWrapper)

    def test_driver_not_found_libsodbc(self):
        """Test detection of 'can't open lib' error."""
        exception = Exception("Can't open lib 'ODBC Driver 18 for SQL Server'")
        self.assertTrue(self.wrapper._is_driver_not_found_error(exception))

    def test_driver_not_found_dsn(self):
        """Test detection of 'data source name not found' error."""
        exception = Exception("[IM002] Data source name not found")
        self.assertTrue(self.wrapper._is_driver_not_found_error(exception))

    def test_driver_not_found_explicit(self):
        """Test detection of 'driver not found' error."""
        exception = Exception("Driver not found: ODBC Driver 18")
        self.assertTrue(self.wrapper._is_driver_not_found_error(exception))

    def test_driver_could_not_be_loaded(self):
        """Test detection of 'specified driver could not be loaded' error."""
        exception = Exception("The specified driver could not be loaded")
        self.assertTrue(self.wrapper._is_driver_not_found_error(exception))

    def test_other_error(self):
        """Test that other errors are not detected as driver not found."""
        exception = Exception("Connection timeout expired")
        self.assertFalse(self.wrapper._is_driver_not_found_error(exception))

        exception = Exception("Login failed for user")
        self.assertFalse(self.wrapper._is_driver_not_found_error(exception))


class TestDatabaseWrapperBuildConnectionString(SimpleTestCase):
    """Tests for the _build_connection_string method."""

    def setUp(self):
        # Create a mock DatabaseWrapper
        self.wrapper = object.__new__(DatabaseWrapper)

    def test_basic_connection_string(self):
        """Test basic connection string building."""
        conn_params = {
            'NAME': 'testdb',
            'HOST': 'localhost',
            'USER': 'testuser',
            'PASSWORD': 'testpass',
            'OPTIONS': {},
        }
        driver = 'ODBC Driver 18 for SQL Server'
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertIn('DRIVER=ODBC Driver 18 for SQL Server', result)
        self.assertIn('SERVER=localhost', result)
        self.assertIn('DATABASE=testdb', result)
        self.assertIn('UID=testuser', result)
        self.assertIn('PWD=testpass', result)

    def test_connection_string_with_port(self):
        """Test connection string with port number."""
        conn_params = {
            'NAME': 'testdb',
            'HOST': 'localhost',
            'PORT': 1433,
            'USER': 'testuser',
            'PASSWORD': 'testpass',
            'OPTIONS': {},
        }
        driver = 'ODBC Driver 18 for SQL Server'
        result = self.wrapper._build_connection_string(conn_params, driver)

        # Microsoft drivers use comma for port
        self.assertIn('SERVER=localhost,1433', result)

    def test_connection_string_with_dsn(self):
        """Test connection string with DSN."""
        conn_params = {
            'NAME': 'testdb',
            'HOST': 'localhost',
            'OPTIONS': {'dsn': 'MyDSN'},
        }
        driver = 'ODBC Driver 18 for SQL Server'
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertIn('DSN=MyDSN', result)
        # DRIVER should not be present when using DSN
        self.assertNotIn('DRIVER=', result)

    def test_connection_string_trusted_connection(self):
        """Test connection string with trusted connection (no user/password)."""
        conn_params = {
            'NAME': 'testdb',
            'HOST': 'localhost',
            'OPTIONS': {},
        }
        driver = 'ODBC Driver 18 for SQL Server'
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertIn('Trusted_Connection=yes', result)
        self.assertNotIn('UID=', result)
        self.assertNotIn('PWD=', result)

    def test_connection_string_with_extra_params(self):
        """Test connection string with extra parameters."""
        conn_params = {
            'NAME': 'testdb',
            'HOST': 'localhost',
            'USER': 'testuser',
            'PASSWORD': 'testpass',
            'OPTIONS': {
                'extra_params': 'Encrypt=yes;TrustServerCertificate=yes'
            },
        }
        driver = 'ODBC Driver 18 for SQL Server'
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertIn('Encrypt=yes', result)
        self.assertIn('TrustServerCertificate=yes', result)

    def test_connection_string_freetds(self):
        """Test connection string building for FreeTDS driver."""
        conn_params = {
            'NAME': 'testdb',
            'HOST': 'myserver',
            'PORT': 1433,
            'OPTIONS': {
                'host_is_server': True,
            },
        }
        driver = 'FreeTDS'
        result = self.wrapper._build_connection_string(conn_params, driver)

        # FreeTDS uses PORT separately when host_is_server is True
        self.assertIn('SERVER=myserver', result)
        self.assertIn('PORT=1433', result)
        self.assertIn('Integrated Security=SSPI', result)

    def test_connection_string_active_directory_interactive(self):
        """Test that PASSWORD is not included with ActiveDirectoryInteractive auth."""
        conn_params = {
            'NAME': 'testdb',
            'HOST': 'localhost',
            'USER': 'user@domain.com',
            'PASSWORD': 'ignored',
            'OPTIONS': {
                'extra_params': 'Authentication=ActiveDirectoryInteractive'
            },
        }
        driver = 'ODBC Driver 18 for SQL Server'
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertIn('UID=user@domain.com', result)
        self.assertNotIn('PWD=', result)


class TestCursorWrapperAsSqlType(SimpleTestCase):
    """Tests for CursorWrapper._as_sql_type method."""

    def setUp(self):
        from mssql.base import CursorWrapper
        # Create a mock CursorWrapper
        mock_cursor = mock.MagicMock()
        mock_connection = mock.MagicMock()
        mock_connection.driver_charset = None
        self.wrapper = CursorWrapper(mock_cursor, mock_connection)

    def test_string_types(self):
        """Test SQL type detection for strings."""
        self.assertEqual(self.wrapper._as_sql_type(str, ''), 'NVARCHAR')
        self.assertEqual(self.wrapper._as_sql_type(str, 'short'), 'NVARCHAR(5)')
        self.assertEqual(self.wrapper._as_sql_type(str, 'x' * 5000), 'NVARCHAR(max)')

    def test_integer_types(self):
        """Test SQL type detection for integers."""
        self.assertEqual(self.wrapper._as_sql_type(int, 100), 'INT')
        self.assertEqual(self.wrapper._as_sql_type(int, -100), 'INT')
        # Values exceeding INT range should be BIGINT
        self.assertEqual(self.wrapper._as_sql_type(int, 0x7FFFFFFF + 1), 'BIGINT')
        self.assertEqual(self.wrapper._as_sql_type(int, -0x7FFFFFFF - 1), 'BIGINT')

    def test_float_type(self):
        """Test SQL type detection for floats."""
        self.assertEqual(self.wrapper._as_sql_type(float, 3.14), 'DOUBLE PRECISION')

    def test_bool_type(self):
        """Test SQL type detection for booleans."""
        self.assertEqual(self.wrapper._as_sql_type(bool, True), 'BIT')
        self.assertEqual(self.wrapper._as_sql_type(bool, False), 'BIT')

    def test_decimal_type(self):
        """Test SQL type detection for Decimal."""
        self.assertEqual(self.wrapper._as_sql_type(Decimal, Decimal('123.45')), 'NUMERIC')

    def test_datetime_types(self):
        """Test SQL type detection for datetime types."""
        self.assertEqual(
            self.wrapper._as_sql_type(datetime.datetime, datetime.datetime.now()),
            'DATETIME2'
        )
        self.assertEqual(
            self.wrapper._as_sql_type(datetime.date, datetime.date.today()),
            'DATE'
        )
        self.assertEqual(
            self.wrapper._as_sql_type(datetime.time, datetime.time(12, 30)),
            'TIME'
        )

    def test_uuid_type(self):
        """Test SQL type detection for UUID."""
        self.assertEqual(
            self.wrapper._as_sql_type(UUID, UUID('12345678-1234-5678-1234-567812345678')),
            'uniqueidentifier'
        )

    def test_bytes_type(self):
        """Test SQL type detection for bytes."""
        self.assertEqual(self.wrapper._as_sql_type(bytes, b'binary_data'), 'VARBINARY')

    def test_unsupported_type(self):
        """Test that unsupported types raise NotImplementedError."""
        with self.assertRaises(NotImplementedError):
            self.wrapper._as_sql_type(list, [1, 2, 3])


class TestCursorWrapperFormatSql(SimpleTestCase):
    """Tests for CursorWrapper.format_sql method."""

    def setUp(self):
        from mssql.base import CursorWrapper
        mock_cursor = mock.MagicMock()
        mock_connection = mock.MagicMock()
        mock_connection.driver_charset = None
        self.wrapper = CursorWrapper(mock_cursor, mock_connection)

    def test_format_sql_no_params(self):
        """Test SQL formatting with no parameters."""
        sql = "SELECT * FROM users"
        result = self.wrapper.format_sql(sql, None)
        self.assertEqual(result, "SELECT * FROM users")

    def test_format_sql_empty_params(self):
        """Test SQL formatting with empty params list."""
        sql = "SELECT * FROM users"
        result = self.wrapper.format_sql(sql, [])
        self.assertEqual(result, "SELECT * FROM users")

    def test_format_sql_with_params(self):
        """Test SQL formatting replaces %s with ?."""
        sql = "SELECT * FROM users WHERE id = %s AND name = %s"
        result = self.wrapper.format_sql(sql, ['param1', 'param2'])
        self.assertEqual(result, "SELECT * FROM users WHERE id = ? AND name = ?")


class TestCursorWrapperFormatParams(SimpleTestCase):
    """Tests for CursorWrapper.format_params method."""

    def setUp(self):
        from mssql.base import CursorWrapper
        mock_cursor = mock.MagicMock()
        mock_connection = mock.MagicMock()
        mock_connection.driver_charset = None
        self.wrapper = CursorWrapper(mock_cursor, mock_connection)

    def test_format_params_none(self):
        """Test formatting with None params."""
        result = self.wrapper.format_params(None)
        self.assertEqual(result, ())

    def test_format_params_string(self):
        """Test formatting string parameters."""
        result = self.wrapper.format_params(['hello', 'world'])
        self.assertEqual(result, ('hello', 'world'))

    def test_format_params_bytes(self):
        """Test formatting bytes parameters."""
        result = self.wrapper.format_params([b'binary'])
        self.assertEqual(result, (b'binary',))

    def test_format_params_bool(self):
        """Test formatting boolean parameters (converted to 1/0)."""
        result = self.wrapper.format_params([True, False])
        self.assertEqual(result, (1, 0))

    def test_format_params_mixed(self):
        """Test formatting mixed parameter types."""
        result = self.wrapper.format_params([True, 'text', 123, None])
        self.assertEqual(result, (1, 'text', 123, None))

    def test_format_params_with_driver_charset(self):
        """Test formatting with driver charset encoding."""
        from mssql.base import CursorWrapper
        mock_cursor = mock.MagicMock()
        mock_connection = mock.MagicMock()
        mock_connection.driver_charset = 'utf-8'
        wrapper = CursorWrapper(mock_cursor, mock_connection)

        result = wrapper.format_params(['unicode: \u00e9'])
        # String should be encoded
        self.assertEqual(result[0], 'unicode: é')
