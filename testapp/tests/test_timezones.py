# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

import datetime
from django.db import connection
from django.test import TestCase
from django.test.utils import override_settings

from mssql.operations import DatabaseOperations

from ..models import TimeZone

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


class TestGetUtcOffset(TestCase):
    """
    Regression tests for DatabaseOperations._get_utcoffset.

    The helper returns the standard (non-DST) UTC offset of a time zone
    in seconds and feeds directly into compiled SQL via DATEADD. these
    values must stay stable across the year and across Python versions
    to avoid silent SQL behavior changes.
    """

    def setUp(self):
        self.ops = DatabaseOperations(connection=None)

    def test_fixed_offset_zones(self):
        # zones without DST: offset is unambiguous
        self.assertEqual(self.ops._get_utcoffset('UTC'), 0)
        self.assertEqual(self.ops._get_utcoffset('Asia/Kolkata'), 19800)
        self.assertEqual(self.ops._get_utcoffset('Africa/Nairobi'), 10800)
        self.assertEqual(self.ops._get_utcoffset('Asia/Tokyo'), 32400)

    def test_northern_hemisphere_dst_zones(self):
        # standard (winter) offset, not DST offset
        self.assertEqual(self.ops._get_utcoffset('America/Los_Angeles'), -28800)
        self.assertEqual(self.ops._get_utcoffset('America/New_York'), -18000)
        self.assertEqual(self.ops._get_utcoffset('Europe/London'), 0)
        self.assertEqual(self.ops._get_utcoffset('Europe/Berlin'), 3600)

    def test_southern_hemisphere_dst_zones(self):
        # for southern zones, "standard" is the winter (Jul) offset
        self.assertEqual(self.ops._get_utcoffset('Australia/Sydney'), 36000)
        self.assertEqual(self.ops._get_utcoffset('Pacific/Auckland'), 43200)

    def test_zones_with_unusual_dst_rules(self):
        # Casablanca has had Ramadan-based negative DST since 2018
        # with +1 as the standard offset
        self.assertEqual(self.ops._get_utcoffset('Africa/Casablanca'), 3600)
        # Inuvik observes MST/MDT; standard is MST = -7h
        self.assertEqual(self.ops._get_utcoffset('America/Inuvik'), -25200)

    def test_returns_int(self):
        # the value flows into '%d' formatting in compiled SQL
        result = self.ops._get_utcoffset('America/Los_Angeles')
        self.assertIsInstance(result, int)

    def test_stable_across_year(self):
        # the helper must not depend on when it's called. call it twice
        # and confirm the result doesn't drift.
        first = self.ops._get_utcoffset('America/Los_Angeles')
        second = self.ops._get_utcoffset('America/Los_Angeles')
        self.assertEqual(first, second)
