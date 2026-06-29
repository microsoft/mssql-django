
from django.test import TestCase

from mssql.parser import (
    IdentifierError, parse_multipart_identifier, build_multipart_name,
    escape_identifier, escape_string_literal,
    SERVER_INDEX, CATALOG_INDEX, SCHEMA_INDEX, TABLE_INDEX
)

class ParserTests(TestCase):

    def test_parse_one_part(self):
        server, db, schema, table = parse_multipart_identifier("Users", False)
        self.assertEqual(server, None)
        self.assertEqual(db, None)
        self.assertEqual(schema, None)
        self.assertEqual(table, 'Users')
    
    def test_parse_two_parts(self):
        parts = parse_multipart_identifier("dbo.Users", False)
        self.assertEqual(parts[SERVER_INDEX], None)
        self.assertEqual(parts[CATALOG_INDEX], None)
        self.assertEqual(parts[SCHEMA_INDEX], "dbo")
        self.assertEqual(parts[TABLE_INDEX], "Users")

    def test_parse_three_parts(self):
        parts = parse_multipart_identifier("MyDB.dbo.Users", False)
        self.assertEqual(parts[SERVER_INDEX], None)
        self.assertEqual(parts[CATALOG_INDEX], "MyDB")
        self.assertEqual(parts[SCHEMA_INDEX], "dbo")
        self.assertEqual(parts[TABLE_INDEX], "Users")

    def test_parse_four_parts(self):
        parts = parse_multipart_identifier("Server.MyDB.dbo.Users", False)
        self.assertEqual(parts[SERVER_INDEX], "Server")
        self.assertEqual(parts[CATALOG_INDEX], "MyDB")
        self.assertEqual(parts[SCHEMA_INDEX], "dbo")
        self.assertEqual(parts[TABLE_INDEX], "Users")

    def test_parse_quoted_identifier(self):
        parts = parse_multipart_identifier("[My Table]", False)
        self.assertEqual(parts[TABLE_INDEX], "My Table")

    def test_parse_escaped_brackets(self):
        parts = parse_multipart_identifier("[My]]Table]", False)
        self.assertEqual(parts[TABLE_INDEX], "My]Table")

    def test_parse_double_quotes(self):
        parts = parse_multipart_identifier("\"My Table\"", False)
        self.assertEqual(parts[TABLE_INDEX], "My Table")

    def test_parse_mixed_quotes_and_unquoted(self):
        parts = parse_multipart_identifier("[My DB].dbo.[My Table]", False)
        self.assertEqual(parts[CATALOG_INDEX], "My DB")
        self.assertEqual(parts[SCHEMA_INDEX], "dbo")
        self.assertEqual(parts[TABLE_INDEX], "My Table")

    def test_parse_whitespace_handling(self):
        parts = parse_multipart_identifier("  MyDB . dbo . Users  ", False)
        self.assertEqual(parts[CATALOG_INDEX], "MyDB")
        self.assertEqual(parts[SCHEMA_INDEX], "dbo")
        self.assertEqual(parts[TABLE_INDEX], "Users")

    def test_parse_too_many_parts(self):
        self.assertRaises(
            Exception,
            parse_multipart_identifier,
            "A.B.C.D.E", False
        )

    def test_parse_empty_not_allowed(self):
        self.assertRaises(
            IdentifierError,
            parse_multipart_identifier,
            "", False
        )

    def test_parse_empty_allowed(self):
        parse_multipart_identifier("", True)

    def test_parse_unclosed_quote(self):
        self.assertRaises(
            IdentifierError,
            parse_multipart_identifier,
            "[MyTable", False
        )

class EscapeTest(TestCase):
    
    def test_escape_identifier(self):
        self.assertEqual(escape_identifier("MyTable"), "MyTable")
        self.assertEqual(escape_identifier("MyTable", force_wrap=True), "[MyTable]")
        self.assertEqual(escape_identifier("My]Table"), "[My]]Table]")
        self.assertEqual(escape_identifier("My]]Table"), "[My]]]]Table]")
        self.assertEqual(escape_identifier(""), "")
        self.assertEqual(escape_identifier("", force_wrap=True), "[]")
    

    def test_escape_string_literal(self):
        self.assertEqual(escape_string_literal("O'Brien"), "O''Brien")
        self.assertEqual(escape_string_literal("It's"), "It''s")
        self.assertEqual(escape_string_literal("No quotes"), "No quotes")
        self.assertEqual(escape_string_literal(""), "")

class TestBuilder(TestCase):

    def test_build_multipart_name(self):
        parts = [
            None,
            "MyDB",
            "dbo",
            "Users",
        ]
        self.assertEqual(build_multipart_name(*parts), "[MyDB].[dbo].[Users]")

    def test_build_multipart_name_with_special_chars(self):
        parts = [
            None,
            "My]DB",
            "dbo",
            "My]Table",
        ]
        self.assertEqual(build_multipart_name(*parts), "[My]]DB].[dbo].[My]]Table]")

    def test_build_multipart_name_single_part(self):
        parts = [None, None, None, "Users"]
        self.assertEqual(build_multipart_name(*parts), "[Users]")

    def test_build_multipart_name_all_parts(self):
        parts = [
            "Server",
            "DB",
            "schema",
            "table",
        ]
        self.assertEqual(
            build_multipart_name(*parts),
            "[Server].[DB].[schema].[table]"
        )