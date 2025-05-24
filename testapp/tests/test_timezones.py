# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

import datetime
from django.db import connection
from django.test import TestCase
from django.test.utils import override_settings
from mssql.operations import DatabaseOperations
from ..models import TimeZone
import unittest
import sys
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
#Testing related to _get_utcoffset method
class DummyConnection:
    timezone_name = 'UTC'
@unittest.skipUnless(sys.version_info >= (3, 9), "zoneinfo requires Python 3.9+")
class TestGetUTCOffset(TestCase):
    def setUp(self):
        self.ops = DatabaseOperations(DummyConnection())

    def test_get_utcoffset_utc(self):
        offset = self.ops._get_utcoffset('UTC')
        self.assertEqual(offset, 0)  # UTC offset should be 0 for UTC timezone

    def test_get_utcoffset_ist(self):
        offset = self.ops._get_utcoffset('Asia/Kolkata')
        # IST is usually UTC+5:30 → 19800 seconds
        self.assertEqual(offset, 19800)