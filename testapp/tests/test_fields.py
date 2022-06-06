# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from django.test import TestCase

from ..models import UUIDModel


class TestUUIDField(TestCase):
    def test_create(self):
        UUIDModel.objects.create()
