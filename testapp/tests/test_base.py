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
    EDITION_AZURE_SQL_DB,
    EDITION_AZURE_SQL_MANAGED_INSTANCE,
    EDITION_AZURE_SQL_FABRIC,
)


class TestEncodeValue(SimpleTestCase):
    """Tests for the encode_value function."""

    def test_simple_value(self):
        """Simple values without special characters should pass through unchanged."""
        self.assertEqual(encode_value("simple"), "simple")
        self.assertEqual(encode_value("MyPassword123"), "MyPassword123")

    def test_value_with_semicolon(self):
        """Values containing semicolons should be wrapped in curly braces."""
        self.assertEqual(encode_value("pass;word"), "{pass;word}")
        self.assertEqual(encode_value("a;b;c"), "{a;b;c}")

    def test_value_starting_with_curly_brace(self):
        """Values starting with { should be wrapped and escaped."""
        # '{value}' -> the } is escaped to }}, then wrapped: {{value}}}
        self.assertEqual(encode_value("{value}"), "{{value}}}")
        self.assertEqual(encode_value("  {spaced}"), "{  {spaced}}}")

    def test_value_with_right_curly_brace(self):
        """Right curly braces should be escaped when wrapping is needed."""
        self.assertEqual(encode_value("pass}word;"), "{pass}}word;}")

    def test_empty_string(self):
        """Empty string should pass through unchanged."""
        self.assertEqual(encode_value(""), "")


class TestEncodeConnectionString(SimpleTestCase):
    """Tests for the encode_connection_string function."""

    def test_simple_connection_string(self):
        """Test basic connection string encoding."""
        fields = {"DRIVER": "ODBC Driver 18 for SQL Server", "SERVER": "localhost"}
        result = encode_connection_string(fields)
        self.assertIn("DRIVER=ODBC Driver 18 for SQL Server", result)
        self.assertIn("SERVER=localhost", result)

    def test_connection_string_with_special_chars(self):
        """Test connection string with values containing special characters."""
        fields = {"PASSWORD": "pass;word"}
        result = encode_connection_string(fields)
        self.assertEqual(result, "PASSWORD={pass;word}")

    def test_empty_fields(self):
        """Test with empty fields dictionary."""
        result = encode_connection_string({})
        self.assertEqual(result, "")

    def test_multiple_fields(self):
        """Test with multiple fields."""
        fields = {
            "DRIVER": "ODBC Driver 18 for SQL Server",
            "SERVER": "localhost",
            "DATABASE": "testdb",
            "UID": "testuser",
        }
        result = encode_connection_string(fields)
        # All keys should be present
        for key in fields:
            self.assertIn(f"{key}=", result)


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
        self.assertEqual(payload[0], ord("A"))
        self.assertEqual(payload[1], 0)
        # 'B' should be followed by null byte
        self.assertEqual(payload[2], ord("B"))
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

    def test_datetime_conversion_utc(self):
        """Test conversion of binary datetime offset with UTC (zero offset)."""
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
        self.assertIsNotNone(result.tzinfo)
        self.assertEqual(result.utcoffset(), datetime.timedelta(0))

    def test_datetime_positive_offset(self):
        """Test conversion with a positive timezone offset (+05:30 IST)."""
        dto_bytes = struct.pack("<6hI2h", 2024, 1, 10, 9, 0, 0, 0, 5, 30)
        result = handle_datetimeoffset(dto_bytes)

        self.assertEqual(result.year, 2024)
        self.assertEqual(result.hour, 9)
        self.assertIsNotNone(result.tzinfo)
        self.assertEqual(result.utcoffset(), datetime.timedelta(hours=5, minutes=30))

    def test_datetime_negative_offset(self):
        """Test conversion with a negative timezone offset (-05:00 EST)."""
        dto_bytes = struct.pack("<6hI2h", 2024, 12, 25, 18, 0, 0, 0, -5, 0)
        result = handle_datetimeoffset(dto_bytes)

        self.assertEqual(result.year, 2024)
        self.assertEqual(result.hour, 18)
        self.assertIsNotNone(result.tzinfo)
        self.assertEqual(result.utcoffset(), datetime.timedelta(hours=-5))

    def test_datetime_negative_half_hour_offset(self):
        """Test conversion with a negative half-hour offset (-09:30 Marquesas)."""
        dto_bytes = struct.pack("<6hI2h", 2024, 7, 1, 12, 0, 0, 0, -9, -30)
        result = handle_datetimeoffset(dto_bytes)

        self.assertEqual(result.hour, 12)
        self.assertIsNotNone(result.tzinfo)
        expected = datetime.timedelta(hours=-9, minutes=-30)
        self.assertEqual(result.utcoffset(), expected)

    def test_datetime_positive_three_quarter_offset(self):
        """Test conversion with +05:45 (Nepal) offset."""
        dto_bytes = struct.pack("<6hI2h", 2024, 3, 15, 10, 30, 0, 0, 5, 45)
        result = handle_datetimeoffset(dto_bytes)

        self.assertEqual(result.hour, 10)
        self.assertIsNotNone(result.tzinfo)
        self.assertEqual(result.utcoffset(), datetime.timedelta(hours=5, minutes=45))

    def test_datetime_edge_case_midnight_utc(self):
        """Test with edge case: midnight on Jan 1, 2000 at UTC."""
        dto_bytes = struct.pack("<6hI2h", 2000, 1, 1, 0, 0, 0, 0, 0, 0)
        result = handle_datetimeoffset(dto_bytes)

        self.assertEqual(result.year, 2000)
        self.assertEqual(result.month, 1)
        self.assertEqual(result.day, 1)
        self.assertEqual(result.hour, 0)
        self.assertEqual(result.minute, 0)
        self.assertEqual(result.second, 0)
        self.assertEqual(result.microsecond, 0)
        self.assertEqual(result.utcoffset(), datetime.timedelta(0))


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
            "NAME": "testdb",
            "HOST": "localhost",
            "USER": "testuser",
            "PASSWORD": "testpass",
            "OPTIONS": {},
        }
        driver = "ODBC Driver 18 for SQL Server"
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertIn("DRIVER=ODBC Driver 18 for SQL Server", result)
        self.assertIn("SERVER=localhost", result)
        self.assertIn("DATABASE=testdb", result)
        self.assertIn("UID=testuser", result)
        self.assertIn("PWD=testpass", result)

    def test_connection_string_with_port(self):
        """Test connection string with port number."""
        conn_params = {
            "NAME": "testdb",
            "HOST": "localhost",
            "PORT": 1433,
            "USER": "testuser",
            "PASSWORD": "testpass",
            "OPTIONS": {},
        }
        driver = "ODBC Driver 18 for SQL Server"
        result = self.wrapper._build_connection_string(conn_params, driver)

        # Microsoft drivers use comma for port
        self.assertIn("SERVER=localhost,1433", result)

    def test_connection_string_with_dsn(self):
        """Test connection string with DSN."""
        conn_params = {
            "NAME": "testdb",
            "HOST": "localhost",
            "OPTIONS": {"dsn": "MyDSN"},
        }
        driver = "ODBC Driver 18 for SQL Server"
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertIn("DSN=MyDSN", result)
        # DRIVER should not be present when using DSN
        self.assertNotIn("DRIVER=", result)

    def test_connection_string_trusted_connection(self):
        """Test connection string with trusted connection (no user/password)."""
        conn_params = {
            "NAME": "testdb",
            "HOST": "localhost",
            "OPTIONS": {},
        }
        driver = "ODBC Driver 18 for SQL Server"
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertIn("Trusted_Connection=yes", result)
        self.assertNotIn("UID=", result)
        self.assertNotIn("PWD=", result)

    def test_connection_string_with_extra_params(self):
        """Test connection string with extra parameters."""
        conn_params = {
            "NAME": "testdb",
            "HOST": "localhost",
            "USER": "testuser",
            "PASSWORD": "testpass",
            "OPTIONS": {"extra_params": "Encrypt=yes;TrustServerCertificate=yes"},
        }
        driver = "ODBC Driver 18 for SQL Server"
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertIn("Encrypt=yes", result)
        self.assertIn("TrustServerCertificate=yes", result)

    def test_connection_string_freetds(self):
        """Test connection string building for FreeTDS driver."""
        conn_params = {
            "NAME": "testdb",
            "HOST": "myserver",
            "PORT": 1433,
            "OPTIONS": {
                "host_is_server": True,
            },
        }
        driver = "FreeTDS"
        result = self.wrapper._build_connection_string(conn_params, driver)

        # FreeTDS uses PORT separately when host_is_server is True
        self.assertIn("SERVER=myserver", result)
        self.assertIn("PORT=1433", result)
        self.assertIn("Integrated Security=SSPI", result)

    def test_connection_string_active_directory_interactive(self):
        """Test that PASSWORD is not included with ActiveDirectoryInteractive auth."""
        conn_params = {
            "NAME": "testdb",
            "HOST": "localhost",
            "USER": "user@domain.com",
            "PASSWORD": "ignored",
            "OPTIONS": {"extra_params": "Authentication=ActiveDirectoryInteractive"},
        }
        driver = "ODBC Driver 18 for SQL Server"
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertIn("UID=user@domain.com", result)
        self.assertNotIn("PWD=", result)


    def test_connection_string_active_directory_integrated_no_trusted_connection(self):
        """Test that Trusted_Connection is not injected with ActiveDirectoryIntegrated.

        Regression test for #529: Authentication=ActiveDirectoryIntegrated
        without USER or TOKEN must not get Trusted_Connection=yes appended,
        as the ODBC driver rejects that combination (FA001).
        """
        conn_params = {
            "NAME": "testdb",
            "HOST": "server.database.windows.net",
            "OPTIONS": {"extra_params": "Authentication=ActiveDirectoryIntegrated"},
        }
        driver = "ODBC Driver 18 for SQL Server"
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertNotIn("Trusted_Connection=", result)
        self.assertNotIn("Integrated Security=", result)
        self.assertIn("Authentication=ActiveDirectoryIntegrated", result)

    def test_connection_string_active_directory_msi_no_trusted_connection(self):
        """Test that Trusted_Connection is not injected with ActiveDirectoryMsi."""
        conn_params = {
            "NAME": "testdb",
            "HOST": "server.database.windows.net",
            "OPTIONS": {"extra_params": "Authentication=ActiveDirectoryMsi"},
        }
        driver = "ODBC Driver 18 for SQL Server"
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertNotIn("Trusted_Connection=", result)
        self.assertNotIn("Integrated Security=", result)

    def test_connection_string_active_directory_default_no_trusted_connection(self):
        """Test that Trusted_Connection is not injected with ActiveDirectoryDefault."""
        conn_params = {
            "NAME": "testdb",
            "HOST": "server.database.windows.net",
            "OPTIONS": {"extra_params": "Authentication=ActiveDirectoryDefault"},
        }
        driver = "ODBC Driver 18 for SQL Server"
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertNotIn("Trusted_Connection=", result)
        self.assertNotIn("Integrated Security=", result)

    def test_connection_string_sql_password_auth_keeps_pwd(self):
        """Test that PWD is still included with Authentication=SqlPassword."""
        conn_params = {
            "NAME": "testdb",
            "HOST": "server.database.windows.net",
            "USER": "sqluser",
            "PASSWORD": "secret",
            "OPTIONS": {"extra_params": "Authentication=SqlPassword"},
        }
        driver = "ODBC Driver 18 for SQL Server"
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertIn("UID=sqluser", result)
        self.assertIn("PWD=secret", result)
        self.assertNotIn("Trusted_Connection=", result)

    def test_connection_string_active_directory_password_keeps_pwd(self):
        """Test that PWD is still included with Authentication=ActiveDirectoryPassword."""
        conn_params = {
            "NAME": "testdb",
            "HOST": "server.database.windows.net",
            "USER": "user@domain.com",
            "PASSWORD": "secret",
            "OPTIONS": {"extra_params": "Authentication=ActiveDirectoryPassword"},
        }
        driver = "ODBC Driver 18 for SQL Server"
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertIn("UID=user@domain.com", result)
        self.assertIn("PWD=secret", result)

    def test_connection_string_auth_keyword_case_insensitive(self):
        """Test that Authentication= is detected case-insensitively."""
        conn_params = {
            "NAME": "testdb",
            "HOST": "server.database.windows.net",
            "OPTIONS": {"extra_params": "authentication=ActiveDirectoryIntegrated"},
        }
        driver = "ODBC Driver 18 for SQL Server"
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertNotIn("Trusted_Connection=", result)
        self.assertNotIn("Integrated Security=", result)

    def test_connection_string_auth_with_other_extra_params(self):
        """Test Authentication= detection alongside other extra_params."""
        conn_params = {
            "NAME": "testdb",
            "HOST": "server.database.windows.net",
            "OPTIONS": {
                "extra_params": "Encrypt=yes;Authentication=ActiveDirectoryIntegrated;TrustServerCertificate=yes",
            },
        }
        driver = "ODBC Driver 18 for SQL Server"
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertNotIn("Trusted_Connection=", result)
        self.assertIn("Encrypt=yes", result)

    def test_connection_string_freetds_auth_no_sspi(self):
        """Test that FreeTDS also skips Integrated Security=SSPI when Authentication= is present."""
        conn_params = {
            "NAME": "testdb",
            "HOST": "myserver",
            "OPTIONS": {
                "host_is_server": True,
                "extra_params": "Authentication=ActiveDirectoryIntegrated",
            },
        }
        driver = "FreeTDS"
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertNotIn("Integrated Security=", result)
        self.assertNotIn("Trusted_Connection=", result)

    def test_get_authentication_mode_returns_none_for_empty(self):
        """Test that _get_authentication_mode returns None for empty extra_params."""
        self.assertIsNone(DatabaseWrapper._get_authentication_mode(''))

    def test_get_authentication_mode_parses_value(self):
        """Test that _get_authentication_mode extracts and normalizes the auth mode."""
        result = DatabaseWrapper._get_authentication_mode(
            'Encrypt=yes;Authentication=ActiveDirectoryIntegrated;Foo=bar'
        )
        self.assertEqual(result, 'activedirectoryintegrated')

    def test_get_authentication_mode_case_insensitive(self):
        """Test that _get_authentication_mode is case-insensitive on the keyword."""
        result = DatabaseWrapper._get_authentication_mode(
            'authentication=SqlPassword'
        )
        self.assertEqual(result, 'sqlpassword')

    def test_get_authentication_mode_ignores_braced_values(self):
        """Test that Authentication= inside a braced value is not detected."""
        result = DatabaseWrapper._get_authentication_mode(
            'Application Name={foo;Authentication=SqlPassword};Encrypt=yes'
        )
        self.assertIsNone(result)

    def test_get_authentication_mode_none_extra_params(self):
        """Test that _get_authentication_mode handles None gracefully."""
        self.assertIsNone(DatabaseWrapper._get_authentication_mode(None))

    def test_get_authentication_mode_braced_auth_value(self):
        """Test that braced Authentication value is correctly unbraced and stripped."""
        result = DatabaseWrapper._get_authentication_mode(
            'Authentication={ActiveDirectoryIntegrated}'
        )
        self.assertEqual(result, 'activedirectoryintegrated')

    def test_get_authentication_mode_braced_auth_value_with_whitespace(self):
        """Test that whitespace inside braced Authentication value is stripped."""
        result = DatabaseWrapper._get_authentication_mode(
            'Authentication={ ActiveDirectoryIntegrated }'
        )
        self.assertEqual(result, 'activedirectoryintegrated')

    def test_get_authentication_mode_empty_auth_value(self):
        """Test that Authentication= with empty value returns empty string, not None."""
        result = DatabaseWrapper._get_authentication_mode(
            'Authentication=;Server=localhost'
        )
        self.assertEqual(result, '')

    def test_parse_extra_params_simple(self):
        """Test basic key=value parsing."""
        result = DatabaseWrapper._parse_extra_params(
            'Encrypt=yes;TrustServerCertificate=yes'
        )
        self.assertEqual(result, {'encrypt': 'yes', 'trustservercertificate': 'yes'})

    def test_parse_extra_params_braced_value_with_semicolon(self):
        """Test that semicolons inside braced values are not treated as delimiters."""
        result = DatabaseWrapper._parse_extra_params(
            'Application Name={my;app};Encrypt=yes'
        )
        self.assertEqual(result['application name'], 'my;app')
        self.assertEqual(result['encrypt'], 'yes')

    def test_parse_extra_params_escaped_closing_brace(self):
        """Test that }} inside a braced value is unescaped to }."""
        result = DatabaseWrapper._parse_extra_params(
            'PWD={p}}w}'
        )
        self.assertEqual(result['pwd'], 'p}w')

    def test_parse_extra_params_open_brace_in_braced_value(self):
        """Test that { inside a braced value is kept as-is per MS-ODBCSTR spec."""
        result = DatabaseWrapper._parse_extra_params(
            'App={foo{bar}'
        )
        self.assertEqual(result['app'], 'foo{bar')

    def test_parse_extra_params_equals_in_braced_value(self):
        """Test that = inside a braced value does not split key/value."""
        result = DatabaseWrapper._parse_extra_params(
            'App={key=val};Encrypt=yes'
        )
        self.assertEqual(result['app'], 'key=val')

    def test_parse_extra_params_empty_string(self):
        """Test that empty string returns empty dict."""
        self.assertEqual(DatabaseWrapper._parse_extra_params(''), {})

    def test_parse_extra_params_none(self):
        """Test that None returns empty dict."""
        self.assertEqual(DatabaseWrapper._parse_extra_params(None), {})

    def test_parse_extra_params_trailing_semicolons(self):
        """Test that trailing semicolons are handled gracefully."""
        result = DatabaseWrapper._parse_extra_params(
            'Encrypt=yes;;;'
        )
        self.assertEqual(result, {'encrypt': 'yes'})

    def test_parse_extra_params_whitespace_around_equals(self):
        """Test that whitespace around key and value is stripped."""
        result = DatabaseWrapper._parse_extra_params(
            '  Authentication = ActiveDirectoryIntegrated '
        )
        self.assertEqual(result['authentication'], 'ActiveDirectoryIntegrated')

    def test_parse_extra_params_unclosed_brace_skipped(self):
        """Test that unclosed braced value is silently consumed without crashing."""
        result = DatabaseWrapper._parse_extra_params(
            'App={unclosed;Authentication=SqlPassword'
        )
        # unclosed brace consumes to end of string; Authentication is inside it
        self.assertNotIn('authentication', result)

    def test_parse_extra_params_first_key_wins(self):
        """Test that first occurrence of a key wins (setdefault semantics)."""
        result = DatabaseWrapper._parse_extra_params(
            'Encrypt=yes;Encrypt=no'
        )
        self.assertEqual(result['encrypt'], 'yes')

    def test_connection_string_active_directory_interactive_no_user(self):
        """Test ActiveDirectoryInteractive without USER skips Trusted_Connection."""
        conn_params = {
            "NAME": "testdb",
            "HOST": "server.database.windows.net",
            "OPTIONS": {"extra_params": "Authentication=ActiveDirectoryInteractive"},
        }
        driver = "ODBC Driver 18 for SQL Server"
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertNotIn("Trusted_Connection=", result)
        self.assertNotIn("Integrated Security=", result)

    def test_connection_string_active_directory_service_principal_keeps_pwd(self):
        """Test that PWD is still included with Authentication=ActiveDirectoryServicePrincipal."""
        conn_params = {
            "NAME": "testdb",
            "HOST": "server.database.windows.net",
            "USER": "app-id",
            "PASSWORD": "client-secret",
            "OPTIONS": {"extra_params": "Authentication=ActiveDirectoryServicePrincipal"},
        }
        driver = "ODBC Driver 18 for SQL Server"
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertIn("UID=app-id", result)
        self.assertIn("PWD=client-secret", result)

    def test_connection_string_extra_params_none(self):
        """Test that extra_params=None does not crash."""
        conn_params = {
            "NAME": "testdb",
            "HOST": "localhost",
            "OPTIONS": {"extra_params": None},
        }
        driver = "ODBC Driver 18 for SQL Server"
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertIn("Trusted_Connection=yes", result)

    def test_extra_params_appended_verbatim(self):
        """Test that extra_params is glued onto the connection string verbatim.

        Regression test for #427: the reporter suspected extra_params was not
        being applied. It is appended to the end of the connection string as-is
        (no parsing, no re-encoding), so whatever the settings writer puts there
        reaches the ODBC driver unchanged.
        """
        extra = "Encrypt=no;TrustServerCertificate=yes"
        conn_params = {
            "NAME": "testdb",
            "HOST": "localhost",
            "USER": "testuser",
            "PASSWORD": "testpass",
            "OPTIONS": {"extra_params": extra},
        }
        driver = "ODBC Driver 18 for SQL Server"
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertTrue(result.endswith(";" + extra))

    def test_extra_params_keyword_with_space_preserved(self):
        """Test that an ODBC keyword containing a space survives verbatim.

        Regression test for #427: a follow-up report claimed a space in an
        extra_params keyword (e.g. ``Connection Timeout``) broke the connection.
        extra_params is appended verbatim, so spaced keywords are passed through
        to the driver unchanged and are not mangled or split.
        """
        conn_params = {
            "NAME": "testdb",
            "HOST": "localhost",
            "USER": "testuser",
            "PASSWORD": "testpass",
            "OPTIONS": {"extra_params": "Encrypt=no;Connection Timeout=30"},
        }
        driver = "ODBC Driver 18 for SQL Server"
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertIn("Connection Timeout=30", result)

    def test_spaced_keyword_alongside_authentication_skips_sspi(self):
        """Test the realistic #427 scenario: spaced keyword next to Authentication.

        Combines the two threads from #427: a spaced keyword
        (``Connection Timeout``) alongside an explicit ``Authentication=`` mode.
        The spaced keyword must be preserved verbatim, and the FA001 fix from
        #529 must still hold (no Trusted_Connection / Integrated Security
        injected when Authentication= is present and there is no USER).
        """
        conn_params = {
            "NAME": "testdb",
            "HOST": "server.database.windows.net",
            "OPTIONS": {
                "extra_params": "Connection Timeout=30;Authentication=ActiveDirectoryIntegrated",
            },
        }
        driver = "ODBC Driver 18 for SQL Server"
        result = self.wrapper._build_connection_string(conn_params, driver)

        self.assertIn("Connection Timeout=30", result)
        self.assertIn("Authentication=ActiveDirectoryIntegrated", result)
        self.assertNotIn("Trusted_Connection=", result)
        self.assertNotIn("Integrated Security=", result)

    def test_parse_extra_params_spaced_key_with_authentication(self):
        """Test that auth-mode detection is robust to a spaced sibling keyword.

        Regression test for #427: a spaced keyword such as ``Connection Timeout``
        must not confuse the tokenizer that drives the #529 FA001 fix. The
        Authentication mode is still detected, and the spaced key keeps its
        interior space.
        """
        parsed = DatabaseWrapper._parse_extra_params(
            "Connection Timeout=30;Authentication=ActiveDirectoryIntegrated"
        )
        self.assertEqual(parsed["connection timeout"], "30")
        self.assertEqual(parsed["authentication"], "ActiveDirectoryIntegrated")
        self.assertEqual(
            DatabaseWrapper._get_authentication_mode(
                "Connection Timeout=30;Authentication=ActiveDirectoryIntegrated"
            ),
            "activedirectoryintegrated",
        )


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
        self.assertEqual(self.wrapper._as_sql_type(str, ""), "NVARCHAR")
        self.assertEqual(self.wrapper._as_sql_type(str, "short"), "NVARCHAR(5)")
        self.assertEqual(self.wrapper._as_sql_type(str, "x" * 5000), "NVARCHAR(max)")

    def test_integer_types(self):
        """Test SQL type detection for integers."""
        self.assertEqual(self.wrapper._as_sql_type(int, 100), "INT")
        self.assertEqual(self.wrapper._as_sql_type(int, -100), "INT")
        # Values exceeding INT range should be BIGINT
        self.assertEqual(self.wrapper._as_sql_type(int, 0x7FFFFFFF + 1), "BIGINT")
        self.assertEqual(self.wrapper._as_sql_type(int, -0x7FFFFFFF - 1), "BIGINT")

    def test_float_type(self):
        """Test SQL type detection for floats."""
        self.assertEqual(self.wrapper._as_sql_type(float, 3.14), "DOUBLE PRECISION")

    def test_bool_type(self):
        """Test SQL type detection for booleans."""
        self.assertEqual(self.wrapper._as_sql_type(bool, True), "BIT")
        self.assertEqual(self.wrapper._as_sql_type(bool, False), "BIT")

    def test_decimal_type(self):
        """Test SQL type detection for Decimal."""
        self.assertEqual(
            self.wrapper._as_sql_type(Decimal, Decimal("123.45")), "NUMERIC"
        )

    def test_datetime_types(self):
        """Test SQL type detection for datetime types."""
        self.assertEqual(
            self.wrapper._as_sql_type(datetime.datetime, datetime.datetime.now()),
            "DATETIME2",
        )
        self.assertEqual(
            self.wrapper._as_sql_type(datetime.date, datetime.date.today()), "DATE"
        )
        self.assertEqual(
            self.wrapper._as_sql_type(datetime.time, datetime.time(12, 30)), "TIME"
        )

    def test_uuid_type(self):
        """Test SQL type detection for UUID."""
        self.assertEqual(
            self.wrapper._as_sql_type(
                UUID, UUID("12345678-1234-5678-1234-567812345678")
            ),
            "uniqueidentifier",
        )

    def test_bytes_type(self):
        """Test SQL type detection for bytes."""
        self.assertEqual(self.wrapper._as_sql_type(bytes, b"binary_data"), "VARBINARY")

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
        result = self.wrapper.format_sql(sql, ["param1", "param2"])
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
        result = self.wrapper.format_params(["hello", "world"])
        self.assertEqual(result, ("hello", "world"))

    def test_format_params_bytes(self):
        """Test formatting bytes parameters."""
        result = self.wrapper.format_params([b"binary"])
        self.assertEqual(result, (b"binary",))

    def test_format_params_bool(self):
        """Test formatting boolean parameters (converted to 1/0)."""
        result = self.wrapper.format_params([True, False])
        self.assertEqual(result, (1, 0))

    def test_format_params_mixed(self):
        """Test formatting mixed parameter types."""
        result = self.wrapper.format_params([True, "text", 123, None])
        self.assertEqual(result, (1, "text", 123, None))

    def test_format_params_with_driver_charset(self):
        """Test formatting with driver charset encoding."""
        from mssql.base import CursorWrapper

        mock_cursor = mock.MagicMock()
        mock_connection = mock.MagicMock()
        mock_connection.driver_charset = "utf-8"
        wrapper = CursorWrapper(mock_cursor, mock_connection)

        result = wrapper.format_params(["unicode: \u00e9"])
        # String should be encoded
        self.assertEqual(result[0], "unicode: é")


class TestEditionDetection(SimpleTestCase):
    """Tests for EngineEdition detection including Fabric support."""

    def _make_wrapper(self, alias):
        """Create a bare DatabaseWrapper without calling __init__."""
        wrapper = object.__new__(DatabaseWrapper)
        wrapper.alias = alias
        return wrapper

    def _mock_server_properties(self, wrapper, engine_edition, product_version="12.0.2000.8"):
        """Mock temporary_connection to return EngineEdition and ProductVersion."""
        mock_cursor = mock.MagicMock()
        mock_cursor.fetchone.return_value = (product_version, engine_edition)
        mock_ctx = mock.MagicMock()
        mock_ctx.__enter__ = mock.MagicMock(return_value=mock_cursor)
        mock_ctx.__exit__ = mock.MagicMock(return_value=False)
        wrapper.temporary_connection = mock.MagicMock(return_value=mock_ctx)

    def _clear_caches(self, wrapper):
        """Clear both class-level and instance-level caches."""
        # Clear class-level caches
        DatabaseWrapper._known_azures.pop(wrapper.alias, None)
        DatabaseWrapper._known_versions.pop(wrapper.alias, None)
        # Clear instance-level cached_property values
        wrapper.__dict__.pop("to_azure_sql_db", None)
        wrapper.__dict__.pop("sql_server_version", None)

    def test_fabric_detected_as_azure(self):
        """Fabric SQL Database (EngineEdition=12) should be recognized as Azure."""
        wrapper = self._make_wrapper("test_fabric")
        self._mock_server_properties(wrapper, EDITION_AZURE_SQL_FABRIC)
        self.assertTrue(wrapper.to_azure_sql_db)
        self._clear_caches(wrapper)

    def test_azure_sql_db_detected(self):
        """Azure SQL DB (EngineEdition=5) should be recognized."""
        wrapper = self._make_wrapper("test_azure_db")
        self._mock_server_properties(wrapper, EDITION_AZURE_SQL_DB)
        self.assertTrue(wrapper.to_azure_sql_db)
        self._clear_caches(wrapper)

    def test_azure_managed_instance_detected(self):
        """Azure SQL Managed Instance (EngineEdition=8) should be recognized."""
        wrapper = self._make_wrapper("test_azure_mi")
        self._mock_server_properties(wrapper, EDITION_AZURE_SQL_MANAGED_INSTANCE)
        self.assertTrue(wrapper.to_azure_sql_db)
        self._clear_caches(wrapper)

    def test_on_prem_not_detected_as_azure(self):
        """On-premises editions (2=Standard, 3=Enterprise) should not be Azure."""
        for edition in (1, 2, 3, 4):
            wrapper = self._make_wrapper(f"test_onprem_{edition}")
            self._mock_server_properties(wrapper, edition, "16.0.4135.4")
            self.assertFalse(wrapper.to_azure_sql_db)
            self._clear_caches(wrapper)

    def test_unrecognized_edition_not_detected_as_azure(self):
        """Unrecognized editions (e.g. 6=Synapse dedicated, 9=SQL Edge) should not be Azure."""
        for edition in (6, 9, 11):
            wrapper = self._make_wrapper(f"test_unknown_{edition}")
            self._mock_server_properties(wrapper, edition, "16.0.4135.4")
            self.assertFalse(wrapper.to_azure_sql_db)
            self._clear_caches(wrapper)

    def test_single_query_populates_both_caches(self):
        """Accessing to_azure_sql_db should also populate sql_server_version cache."""
        wrapper = self._make_wrapper("test_single_query")
        self._mock_server_properties(wrapper, EDITION_AZURE_SQL_FABRIC)
        # Access to_azure_sql_db first
        self.assertTrue(wrapper.to_azure_sql_db)
        # sql_server_version should already be cached (no extra query)
        latest = max(DatabaseWrapper._sql_server_versions.values())
        self.assertEqual(wrapper.sql_server_version, latest)
        # temporary_connection should have been called only once
        self.assertEqual(wrapper.temporary_connection.call_count, 1)
        self._clear_caches(wrapper)


class TestSqlServerVersionDetection(SimpleTestCase):
    """Tests for sql_server_version with cloud engines."""

    def _make_wrapper(self, alias):
        wrapper = object.__new__(DatabaseWrapper)
        wrapper.alias = alias
        return wrapper

    def _mock_server_properties(self, wrapper, engine_edition, product_version="12.0.2000.8"):
        """Mock temporary_connection to return EngineEdition and ProductVersion."""
        mock_cursor = mock.MagicMock()
        mock_cursor.fetchone.return_value = (product_version, engine_edition)
        mock_ctx = mock.MagicMock()
        mock_ctx.__enter__ = mock.MagicMock(return_value=mock_cursor)
        mock_ctx.__exit__ = mock.MagicMock(return_value=False)
        wrapper.temporary_connection = mock.MagicMock(return_value=mock_ctx)

    def _clear_caches(self, wrapper):
        DatabaseWrapper._known_azures.pop(wrapper.alias, None)
        DatabaseWrapper._known_versions.pop(wrapper.alias, None)
        wrapper.__dict__.pop("to_azure_sql_db", None)
        wrapper.__dict__.pop("sql_server_version", None)

    def test_fabric_gets_latest_version(self):
        """Fabric should get the latest supported version, not 2014."""
        wrapper = self._make_wrapper("test_fabric_ver")
        self._mock_server_properties(wrapper, EDITION_AZURE_SQL_FABRIC)
        latest = max(DatabaseWrapper._sql_server_versions.values())
        self.assertEqual(wrapper.sql_server_version, latest)
        self._clear_caches(wrapper)

    def test_azure_sql_db_preserves_product_version(self):
        """Azure SQL DB should use ProductVersion lookup, not latest version.

        Azure SQL DB reports ProductVersion 12.0.2000.8 which maps to 2014.
        Feature checks use 'or to_azure_sql_db' as a fallback, so changing
        this would risk breaking existing Azure SQL DB connections.
        """
        wrapper = self._make_wrapper("test_azure_ver")
        self._mock_server_properties(wrapper, EDITION_AZURE_SQL_DB)
        self.assertEqual(wrapper.sql_server_version, 2014)
        self._clear_caches(wrapper)

    def test_azure_managed_instance_preserves_product_version(self):
        """Azure SQL MI should use ProductVersion lookup, not latest version."""
        wrapper = self._make_wrapper("test_azure_mi_ver")
        self._mock_server_properties(wrapper, EDITION_AZURE_SQL_MANAGED_INSTANCE)
        self.assertEqual(wrapper.sql_server_version, 2014)
        self._clear_caches(wrapper)

    def test_on_prem_sql2022_version(self):
        """On-premises SQL Server 2022 (ProductVersion 16.x) should return 2022."""
        wrapper = self._make_wrapper("test_onprem_2022")
        self._mock_server_properties(wrapper, 3, "16.0.4135.4")
        self.assertEqual(wrapper.sql_server_version, 2022)
        self._clear_caches(wrapper)

    def test_on_prem_unsupported_version_raises(self):
        """Unsupported on-premises version should raise NotSupportedError."""
        from django.db import NotSupportedError

        wrapper = self._make_wrapper("test_onprem_bad")
        self._mock_server_properties(wrapper, 3, "99.0.0.0")

        with self.assertRaises(NotSupportedError):
            _ = wrapper.sql_server_version
        self._clear_caches(wrapper)


class TestDatabaseWrapperSubclass(SimpleTestCase):
    """Regression test for #531: subclassing DatabaseWrapper must not crash."""

    def test_subclass_server_properties_no_keyerror(self):
        """Accessing sql_server_version on a subclass should not raise KeyError."""

        class SubWrapper(DatabaseWrapper):
            pass

        wrapper = object.__new__(SubWrapper)
        wrapper.alias = "test_subclass"

        mock_cursor = mock.MagicMock()
        mock_cursor.fetchone.return_value = ("16.0.4135.4", 3)
        mock_ctx = mock.MagicMock()
        mock_ctx.__enter__ = mock.MagicMock(return_value=mock_cursor)
        mock_ctx.__exit__ = mock.MagicMock(return_value=False)
        wrapper.temporary_connection = mock.MagicMock(return_value=mock_ctx)

        self.assertEqual(wrapper.sql_server_version, 2022)
        self.assertFalse(wrapper.to_azure_sql_db)
        self.assertEqual(wrapper.temporary_connection.call_count, 1)

        DatabaseWrapper._known_versions.pop("test_subclass", None)
        DatabaseWrapper._known_azures.pop("test_subclass", None)
