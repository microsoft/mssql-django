# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from unittest import skipUnless

from django import VERSION
from django.db.models import IntegerField, F
from django.db.models.expressions import Case, Exists, OuterRef, Subquery, Value, When
from django.test import TestCase, skipUnlessDBFeature

from django.db.models.aggregates import Count
from ..models import Author, Comment, Post, Editor

DJANGO3 = VERSION[0] >= 3


class TestSubquery(TestCase):
    def setUp(self):
        self.author = Author.objects.create(name="author")
        self.post = Post.objects.create(title="foo", author=self.author)

    def test_with_count(self):
        newest = Comment.objects.filter(post=OuterRef('pk')).order_by('-created_at')
        Post.objects.annotate(
            post_exists=Subquery(newest.values('text')[:1])
        ).filter(post_exists=True).count()


class TestExists(TestCase):
    def setUp(self):
        self.author = Author.objects.create(name="author")
        self.post = Post.objects.create(title="foo", author=self.author)

    def test_with_count(self):
        Post.objects.annotate(
            post_exists=Exists(Post.objects.all())
        ).filter(post_exists=True).count()

    @skipUnless(DJANGO3, "Django 3 specific tests")
    def test_with_case_when(self):
        author = Author.objects.annotate(
            has_post=Case(
                When(Exists(Post.objects.filter(author=OuterRef('pk')).values('pk')), then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        ).get()
        self.assertEqual(author.has_post, 1)

    def test_unnecessary_exists_group_by(self):
        author = Author.objects.annotate(
            has_post=Case(
                When(Exists(Post.objects.filter(author=OuterRef('pk')).values('pk')), then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )).annotate(
            amount=Count("post")
        ).get()
        self.assertEqual(author.amount, 1)
        self.assertEqual(author.has_post, 1)

    @skipUnless(DJANGO3, "Django 3 specific tests")
    def test_order_by_exists(self):
        author_without_posts = Author.objects.create(name="other author")
        authors_by_posts = Author.objects.order_by(Exists(Post.objects.filter(author=OuterRef('pk'))).desc())
        self.assertSequenceEqual(authors_by_posts, [self.author, author_without_posts])

        authors_by_posts = Author.objects.order_by(Exists(Post.objects.filter(author=OuterRef('pk'))).asc())
        self.assertSequenceEqual(authors_by_posts, [author_without_posts, self.author])


@skipUnless(DJANGO3, "Django 3 specific tests")
@skipUnlessDBFeature("order_by_nulls_first")
class TestOrderBy(TestCase):
    def setUp(self):
        self.author = Author.objects.create(name="author")
        self.post = Post.objects.create(title="foo", author=self.author)
        self.editor = Editor.objects.create(name="editor")
        self.post_alt = Post.objects.create(title="Post with editor", author=self.author, alt_editor=self.editor)

    def test_order_by_nulls_last(self):
        results = Post.objects.order_by(F("alt_editor").asc(nulls_last=True)).all()
        self.assertEqual(len(results), 2)
        self.assertIsNotNone(results[0].alt_editor)
        self.assertIsNone(results[1].alt_editor)

    def test_order_by_nulls_first(self):
        results = Post.objects.order_by(F("alt_editor").desc(nulls_first=True)).all()
        self.assertEqual(len(results), 2)
        self.assertIsNone(results[0].alt_editor)
        self.assertIsNotNone(results[1].alt_editor)
