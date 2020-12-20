# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from django.db.utils import IntegrityError
from django.test import TestCase, skipUnlessDBFeature

from ..models import (
    Author, Editor, Post,
    TestUniqueNullableModel, TestNullableUniqueTogetherModel,
)


@skipUnlessDBFeature('supports_nullable_unique_constraints')
class TestNullableUniqueColumn(TestCase):
    def test_multiple_nulls(self):
        # Issue #45 (case 1) - after field `x` has had its type changed, the filtered UNIQUE
        # INDEX which is implementing the nullable unique constraint should still be correctly
        # in place - i.e. allowing multiple NULLs but still enforcing uniqueness of non-NULLs

        # Allowed
        TestUniqueNullableModel.objects.create(x=None, test_field='randomness')
        TestUniqueNullableModel.objects.create(x=None, test_field='doesntmatter')

        # Disallowed
        TestUniqueNullableModel.objects.create(x="foo", test_field='irrelevant')
        with self.assertRaises(IntegrityError):
            TestUniqueNullableModel.objects.create(x="foo", test_field='nonsense')


@skipUnlessDBFeature('supports_partially_nullable_unique_constraints')
class TestPartiallyNullableUniqueTogether(TestCase):
    def test_partially_nullable(self):
        # Check basic behaviour of `unique_together` where at least 1 of the columns is nullable

        # It should be possible to have 2 rows both with NULL `alt_editor`
        author = Author.objects.create(name="author")
        Post.objects.create(title="foo", author=author)
        Post.objects.create(title="foo", author=author)

        # But `unique_together` is still enforced for non-NULL values
        editor = Editor.objects.create(name="editor")
        Post.objects.create(title="foo", author=author, alt_editor=editor)
        with self.assertRaises(IntegrityError):
            Post.objects.create(title="foo", author=author, alt_editor=editor)

    def test_after_type_change(self):
        # Issue #45 (case 2) - after one of the fields in the `unique_together` has had its
        # type changed in a migration, the constraint should still be correctly enforced

        # Multiple rows with a=NULL are considered different
        TestNullableUniqueTogetherModel.objects.create(a=None, b='bbb', c='ccc')
        TestNullableUniqueTogetherModel.objects.create(a=None, b='bbb', c='ccc')

        # Uniqueness still enforced for non-NULL values
        TestNullableUniqueTogetherModel.objects.create(a='aaa', b='bbb', c='ccc')
        with self.assertRaises(IntegrityError):
            TestNullableUniqueTogetherModel.objects.create(a='aaa', b='bbb', c='ccc')
