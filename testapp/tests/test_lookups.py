# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from django.test import TestCase
from ..models import Pizza, Topping

class TestLookups(TestCase):
    def test_large_number_of_params(self):
        iterations = 3000
        for i in range(iterations):
            Pizza.objects.create(name="Pizza" + str(i))
            Topping.objects.create(name="Topping" + str(i))
        prefetch_result = Pizza.objects.prefetch_related('toppings')

        self.assertEqual(len(prefetch_result), iterations)
