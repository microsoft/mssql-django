# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

import datetime
from contextlib import contextmanager

from django.db import connection
from django.test import TestCase
from django.test.utils import override_settings

from ..models import TimeZone


@contextmanager
def override_database_connection_timezone(timezone):
    original_timezone = connection.settings_dict['TIME_ZONE']
    try:
        connection.settings_dict['TIME_ZONE'] = timezone
        connection.timezone
        del connection.timezone
        connection.timezone_name
        del connection.timezone_name
        yield
    finally:
        connection.settings_dict['TIME_ZONE'] = original_timezone
        connection.timezone
        del connection.timezone
        connection.timezone_name
        del connection.timezone_name


class TestDateTimeField(TestCase):

    def test_iso_week_day(self):
        days = {
            1: TimeZone.objects.create(date=datetime.datetime(2022, 5, 16)),
            2: TimeZone.objects.create(date=datetime.datetime(2022, 5, 17)),
            3: TimeZone.objects.create(date=datetime.datetime(2022, 5, 18)),
            4: TimeZone.objects.create(date=datetime.datetime(2022, 5, 19)),
            5: TimeZone.objects.create(date=datetime.datetime(2022, 5, 20)),
            6: TimeZone.objects.create(date=datetime.datetime(2022, 5, 21)),
            7: TimeZone.objects.create(date=datetime.datetime(2022, 5, 22)),
        }
        for k, v in days.items():
            self.assertSequenceEqual(TimeZone.objects.filter(date__iso_week_day=k), [v])

    @override_settings(USE_TZ=True)
    def test_adapt_datetimefield_value_uses_database_timezone(self):
        value = datetime.datetime(2024, 1, 15, 12, tzinfo=datetime.timezone.utc)

        with override_database_connection_timezone('Europe/Berlin'):
            adapted = connection.ops.adapt_datetimefield_value(value)

        self.assertEqual(adapted, datetime.datetime(2024, 1, 15, 13))
        self.assertIsNone(adapted.tzinfo)

    @override_settings(USE_TZ=True)
    def test_datetime_sql_conversion_uses_database_timezone(self):
        with override_database_connection_timezone('Asia/Bangkok'):
            converted_field = connection.ops._convert_field_to_tz(
                '[date]', 'Africa/Nairobi'
            )
            converted_sql, params = connection.ops._convert_sql_to_tz(
                '[date]', [], 'Africa/Nairobi'
            )

        expected = 'DATEADD(second, -14400, [date])'
        self.assertEqual(converted_field, expected)
        self.assertEqual(converted_sql, expected)
        self.assertEqual(params, [])

    @override_settings(USE_TZ=True, TIME_ZONE='Africa/Nairobi')
    def test_datetime_round_trip_uses_database_timezone(self):
        value = datetime.datetime(2024, 7, 15, 20, 10, tzinfo=datetime.timezone.utc)
        database_timezone = datetime.timezone(datetime.timedelta(hours=7))

        with override_database_connection_timezone('Asia/Bangkok'):
            obj = TimeZone.objects.create(date=value)
            retrieved = TimeZone.objects.get(pk=obj.pk)
            by_exact_datetime = TimeZone.objects.get(date=value)
            by_local_date = TimeZone.objects.get(date__date=datetime.date(2024, 7, 15))

        self.assertEqual(retrieved.date, value.astimezone(database_timezone))
        self.assertEqual(by_exact_datetime, obj)
        self.assertEqual(by_local_date, obj)


class TestDateTimeToDateTimeOffsetMigration(TestCase):

    def setUp(self):
        # Want this to be a naive datetime so don't want
        # to override settings before TimeZone creation
        self.time = TimeZone.objects.create()

    def tearDown(self):
        TimeZone.objects.all().delete()

    @override_settings(USE_TZ=True)
    def test_datetime_to_datetimeoffset_utc(self):
        dt = self.time.date

        # Do manual migration from DATETIME2 to DATETIMEOFFSET
        # and local time to UTC
        with connection.schema_editor() as cursor:
            cursor.execute("""
                ALTER TABLE [testapp_timezone]
                   ALTER COLUMN [date] DATETIMEOFFSET;

                UPDATE [testapp_timezone]
                   SET [date] = TODATETIMEOFFSET([date], 0) AT TIME ZONE 'UTC'
            """)

        dto = TimeZone.objects.get(id=self.time.id).date

        try:
            self.assertEqual(dt, dto.replace(tzinfo=None))
        finally:
            # Migrate back to DATETIME2 for other unit tests
            with connection.schema_editor() as cursor:
                cursor.execute("ALTER TABLE [testapp_timezone] ALTER column [date] datetime2")

    @override_settings(USE_TZ=True, TIME_ZONE="Africa/Nairobi")
    def test_datetime_to_datetimeoffset_local_timezone(self):
        dt = self.time.date

        # Do manual migration from DATETIME2 to DATETIMEOFFSET
        # and local time to UTC
        with connection.schema_editor() as cursor:
            cursor.execute("""
                ALTER TABLE [testapp_timezone]
                   ALTER COLUMN [date] DATETIMEOFFSET;

                UPDATE [testapp_timezone]
                   SET [date] = TODATETIMEOFFSET([date], 180) AT TIME ZONE 'UTC'
            """)

        dto = TimeZone.objects.get(id=self.time.id).date

        try:
            # Africa/Nairobi (EAT) offset is +03:00
            self.assertEqual(dt - datetime.timedelta(hours=3), dto.replace(tzinfo=None))
        finally:
            # Migrate back to DATETIME2 for other unit tests
            with connection.schema_editor() as cursor:
                cursor.execute("ALTER TABLE [testapp_timezone] ALTER column [date] datetime2")

    @override_settings(USE_TZ=True, TIME_ZONE="Africa/Nairobi")
    def test_datetime_to_datetimeoffset_other_timezone(self):
        dt = self.time.date

        # Do manual migration from DATETIME2 to DATETIMEOFFSET
        # and local time to UTC
        with connection.schema_editor() as cursor:
            cursor.execute("""
                ALTER TABLE [testapp_timezone]
                   ALTER COLUMN [date] DATETIMEOFFSET;

                UPDATE [testapp_timezone]
                   SET [date] = TODATETIMEOFFSET([date], 420) AT TIME ZONE 'UTC'
            """)

        dto = TimeZone.objects.get(id=self.time.id).date

        try:
            self.assertEqual(dt - datetime.timedelta(hours=7), dto.replace(tzinfo=None))
        finally:
            # Migrate back to DATETIME2 for other unit tests
            with connection.schema_editor() as cursor:
                cursor.execute("ALTER TABLE [testapp_timezone] ALTER column [date] datetime2")
