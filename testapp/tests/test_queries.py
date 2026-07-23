import unittest

import django.db.utils
from django import VERSION
from django.db import connections, connection, models
from django.db.models.functions import Now
from django.test import TransactionTestCase, TestCase, skipUnlessDBFeature
from django.test.utils import override_settings
from django.utils import timezone

from ..models import Author, BinaryData, Editor


class TestTableWithTrigger(TransactionTestCase):
    def test_insert_into_table_with_trigger(self):
        connection = connections['default']
        with connection.schema_editor() as cursor:
            cursor.execute("""
                CREATE TRIGGER TestTrigger
                ON [testapp_author]
                FOR INSERT
                AS
                INSERT INTO [testapp_editor]([name]) VALUES ('Bar')
            """)

        try:
            # Change can_return_rows_from_bulk_insert to be the same as when
            # has_trigger = True
            old_return_rows_flag = connection.features_class.can_return_rows_from_bulk_insert
            connection.features_class.can_return_rows_from_bulk_insert = False
            Author.objects.create(name='Foo')
        except django.db.utils.ProgrammingError as e:
            self.fail('Check for regression of issue #130. Insert with trigger failed with exception: %s' % e)
        finally:
            with connection.schema_editor() as cursor:
                cursor.execute("DROP TRIGGER TestTrigger")
            connection.features_class.can_return_rows_from_bulk_insert = old_return_rows_flag


class TestBinaryfieldGroupby(TestCase):
    def test_varbinary(self):
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT binary FROM {BinaryData._meta.db_table} WHERE binary = %s GROUP BY binary", [bytes("ABC", 'utf-8')])


class TestIntegerChoicesGroupby(TestCase):
    # Regression test for #540: an IntegerChoices value (an int subclass) passed to a
    # raw query containing GROUP BY raised NotImplementedError because _as_sql_type used
    # an exact type check (typ == int) instead of isinstance.
    def test_integerchoices_param(self):
        class StatusChoices(models.IntegerChoices):
            NOT_STARTED = 1
            IN_PROGRESS = 2

        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT id FROM {Author._meta.db_table} WHERE id <= %s GROUP BY id",
                [StatusChoices.IN_PROGRESS],
            )
            cursor.fetchall()


@skipUnlessDBFeature("supports_expression_defaults")
class DbDefaultBulkCreateRegressionTests(TransactionTestCase):
    """Regression tests for Django 6.0 db_default bulk insert alignment.

    Django 6.0 introduced DatabaseDefault sentinel values for fields with
    db_default. Our SQLInsertCompiler.as_sql() override must correctly:
      - Exclude a db_default column from the INSERT column list when *every*
        row uses the database default (letting the server supply the value).
      - Include the column when at least one row supplies an explicit value
        (mixing explicit values with DEFAULT keyword or prepared db_default).

    These tests create a raw table with a server-side DEFAULT SYSDATETIME()
    to exercise both paths end-to-end against SQL Server.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # This feature is Django 6.0+ only; skip cleanly on older versions.
        # Note: raise unittest.SkipTest, not cls.skipTest(), because
        # skipTest() is an instance method and cannot be called from
        # setUpClass (a classmethod).
        if VERSION < (6, 0):
            raise unittest.SkipTest(
                "db_default bulk insert alignment is Django 6.0+ specific"
            )

        # Unmanaged model so Django doesn't try to create/drop the table
        # via migrations — we handle that with raw SQL below.
        class DbDefaultBulkInsertModel(models.Model):
            name = models.CharField(max_length=100)
            created_at = models.DateTimeField(db_default=Now())

            class Meta:
                app_label = "testapp"
                db_table = "testapp_dbdefault_bulk_insert"
                managed = False

        cls.DbDefaultBulkInsertModel = DbDefaultBulkInsertModel

        with connection.cursor() as cursor:
            cursor.execute(
                """
                IF OBJECT_ID('testapp_dbdefault_bulk_insert', 'U') IS NOT NULL
                    DROP TABLE testapp_dbdefault_bulk_insert
                """
            )
            cursor.execute(
                """
                CREATE TABLE testapp_dbdefault_bulk_insert (
                    id INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
                    name NVARCHAR(100) NOT NULL,
                    created_at DATETIME2 NOT NULL DEFAULT SYSDATETIME()
                )
                """
            )

    @classmethod
    def tearDownClass(cls):
        if VERSION < (6, 0):
            # Table was never created when the test was skipped.
            super().tearDownClass()
            return
        with connection.cursor() as cursor:
            cursor.execute(
                """
                IF OBJECT_ID('testapp_dbdefault_bulk_insert', 'U') IS NOT NULL
                    DROP TABLE testapp_dbdefault_bulk_insert
                """
            )
        super().tearDownClass()

    def test_db_default_field_excluded_and_included(self):
        """Verify created_at column presence in INSERT SQL for db_default.

        Case 1 — all rows use the database default:
          The column should be omitted from the INSERT column list so the
          server-side DEFAULT kicks in.  The quoted column name appears only
          in the OUTPUT INSERTED clause (if can_return_rows_from_bulk_insert)
          or not at all.

        Case 2 — at least one row supplies an explicit value:
          The column must appear in the INSERT column list (so the explicit
          value is written) *and* in OUTPUT INSERTED (if applicable).
        """
        model = self.DbDefaultBulkInsertModel
        created_at_quoted_name = connection.ops.quote_name("created_at")

        # --- Case 1: all rows rely on db_default for created_at ---
        with self.assertNumQueries(1) as ctx:
            model.objects.bulk_create([model(name="foo"), model(name="bar")])

        # created_at should NOT be in the INSERT column list.
        # It appears once only if OUTPUT INSERTED includes it.
        self.assertEqual(
            ctx[0]["sql"].count(created_at_quoted_name),
            1 if connection.features.can_return_rows_from_bulk_insert else 0,
        )

        # --- Case 2: one row overrides created_at with an explicit value ---
        with self.assertNumQueries(1) as ctx:
            model.objects.bulk_create(
                [
                    model(name="baz", created_at=timezone.now()),
                    model(name="qux"),
                ]
            )

        # created_at must be in the INSERT column list (1 occurrence)
        # plus OUTPUT INSERTED (1 more if can_return_rows_from_bulk_insert).
        self.assertEqual(
            ctx[0]["sql"].count(created_at_quoted_name),
            2 if connection.features.can_return_rows_from_bulk_insert else 1,
        )

    def test_single_insert_with_returning_fields_when_bulk_rows_unsupported(self):
        """Single-row create must still return all db_returning fields.

        Regression for a path where can_return_rows_from_bulk_insert=False
        caused SQLInsertCompiler to use SCOPE_IDENTITY() (1 column) while
        Django expected all returning fields, leading to IndexError.
        """
        model = self.DbDefaultBulkInsertModel
        old_return_rows_flag = connection.features_class.can_return_rows_from_bulk_insert
        connection.features_class.can_return_rows_from_bulk_insert = False
        try:
            with self.assertNumQueries(1) as ctx:
                obj = model.objects.create(name="single")

            self.assertIsNotNone(obj.pk)
            self.assertIsNotNone(obj.created_at)
            self.assertIn("OUTPUT INSERTED", ctx[0]["sql"])
            self.assertNotIn("SCOPE_IDENTITY", ctx[0]["sql"])
        finally:
            connection.features_class.can_return_rows_from_bulk_insert = old_return_rows_flag


class ExplainRegressionTests(TestCase):
    """Regression test for #409: explain() AttributeError on Django 4.0+.

    Django 4.0 replaced query.explain_format/explain_options with
    query.explain_info. The compiler must read the correct attributes
    so .explain() raises NotSupportedError (not AttributeError).
    """

    def test_explain_raises_not_supported(self):
        """explain() should raise NotSupportedError, not AttributeError."""
        qs = Author.objects.all()
        with self.assertRaises(django.db.utils.NotSupportedError):
            qs.explain()


class NowSQLTemplateTests(TestCase):
    """Regression tests for #371 / PR #484: Now() should emit
    SYSDATETIMEOFFSET() when USE_TZ=True, SYSDATETIME() otherwise."""

    @override_settings(USE_TZ=True)
    def test_now_uses_sysdatetimeoffset_when_use_tz(self):
        qs = Author.objects.annotate(ts=Now()).filter(name="x")
        compiler = qs.query.get_compiler(using="default")
        sql_compiled, _ = compiler.as_sql()
        self.assertIn("SYSDATETIMEOFFSET()", sql_compiled)
        self.assertNotIn("SYSDATETIME()", sql_compiled)

    @override_settings(USE_TZ=False)
    def test_now_uses_sysdatetime_when_no_tz(self):
        qs = Author.objects.annotate(ts=Now()).filter(name="x")
        compiler = qs.query.get_compiler(using="default")
        sql_compiled, _ = compiler.as_sql()
        self.assertIn("SYSDATETIME()", sql_compiled)
        self.assertNotIn("SYSDATETIMEOFFSET()", sql_compiled)
