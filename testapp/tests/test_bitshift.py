from django.test import TestCase
from django.db.models import F

from ..models import Number

class BitShiftTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.n = Number.objects.create(integer=42, float=15.5)
        cls.n1 = Number.objects.create(integer=-42, float=-15.5)

    def test_lefthand_bitwise_left_shift_operator_check(self):
        Number.objects.update(integer=F("integer").bitleftshift(3))
        self.assertEqual(Number.objects.get(pk=self.n.pk).integer, 336)
        self.assertEqual(Number.objects.get(pk=self.n1.pk).integer, -336)

    def test_lefthand_bitwise_right_shift_operator_check(self):
        Number.objects.update(integer=F("integer").bitrightshift(3))
        self.assertEqual(Number.objects.get(pk=self.n.pk).integer, 5)
        self.assertEqual(Number.objects.get(pk=self.n1.pk).integer, -6)