# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

import datetime
from unittest import skipUnless

from django import VERSION
from django.db.models import CharField, IntegerField, F
from django.db.models.expressions import Case, Exists, OuterRef, Subquery, Value, When, ExpressionWrapper
from django.test import TestCase, skipUnlessDBFeature

from django.db.models.aggregates import Count, Sum

from ..models import Author, Book, Comment, Post, Editor, ModelWithNullableFieldsOfDifferentTypes


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

    def test_combined_expression_annotation_with_aggregation(self):
        book = Author.objects.annotate(
            combined=ExpressionWrapper(
                Value(2) * Value(5), output_field=IntegerField()
            ),
            null_value=ExpressionWrapper(
                Value(None), output_field=IntegerField()
            ),
            rating_count=Count("post"),
        ).first()
        self.assertEqual(book.combined, 10)
        self.assertEqual(book.null_value, None)


    @skipUnless(DJANGO3, "Django 3 specific tests")
    def test_order_by_exists(self):
        author_without_posts = Author.objects.create(name="other author")
        authors_by_posts = Author.objects.order_by(Exists(Post.objects.filter(author=OuterRef('pk'))).desc())
        self.assertSequenceEqual(authors_by_posts, [self.author, author_without_posts])

        authors_by_posts = Author.objects.order_by(Exists(Post.objects.filter(author=OuterRef('pk'))).asc())
        self.assertSequenceEqual(authors_by_posts, [author_without_posts, self.author])


class TestGroupBy(TestCase):
    def test_group_by_case(self):
        annotated_queryset = Book.objects.annotate(age=Case(
            When(id__gt=1000, then=Value("new")),
            default=Value("old"),
            output_field=CharField())).values('age').annotate(sum=Sum('id'))
        self.assertEqual(list(annotated_queryset.all()), [])

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

class TestBulkUpdate(TestCase):
     def test_bulk_update_different_column_types(self):
        data = (
            (1, 'a', datetime.datetime(year=2024, month=1, day=1)),
            (2, 'b', datetime.datetime(year=2023, month=12, day=31))
        )
        objs = ModelWithNullableFieldsOfDifferentTypes.objects.bulk_create(ModelWithNullableFieldsOfDifferentTypes(int_value=row_data[0],
                                                                                                                   name=row_data[1],
                                                                                                                   date=row_data[2]) for row_data in data)
        for obj in objs:
            obj.int_value = None
            obj.name = None
            obj.date = None
        ModelWithNullableFieldsOfDifferentTypes.objects.bulk_update(objs, ["int_value", "name", "date"])
        self.assertCountEqual(ModelWithNullableFieldsOfDifferentTypes.objects.filter(int_value__isnull=True), objs)
        self.assertCountEqual(ModelWithNullableFieldsOfDifferentTypes.objects.filter(name__isnull=True), objs)
        self.assertCountEqual(ModelWithNullableFieldsOfDifferentTypes.objects.filter(date__isnull=True), objs)
