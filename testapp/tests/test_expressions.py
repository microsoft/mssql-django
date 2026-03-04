# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

import datetime
from unittest import skipUnless

from django import VERSION
from django.db.models import CharField, IntegerField, F
from django.db.models.expressions import Case, Exists, OuterRef, Subquery, Value, When, ExpressionWrapper
from django.test import TestCase, skipUnlessDBFeature

from django.db.models.aggregates import Count, Sum

if VERSION >= (6, 0):
    from django.db.models import StringAgg

from ..models import Author, Book, Comment, Post, Editor, ModelWithNullableFieldsOfDifferentTypes, Publisher


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


class TestOrderingRegressions(TestCase):
    def setUp(self):
        Author.objects.bulk_create([
            Author(name='alice'),
            Author(name='bob'),
            Author(name='charlie'),
        ])

    def test_order_by_case_when_constant_value_executes(self):
        queryset = Author.objects.order_by(
            Case(
                When(name__isnull=False, then=Value(1)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        self.assertCountEqual(
            list(queryset.values_list('name', flat=True)),
            ['alice', 'bob', 'charlie'],
        )

    def test_order_by_case_when_constant_value_with_offset_executes(self):
        queryset = Author.objects.order_by(Value(1))[1:3]
        expected = list(Author.objects.order_by('pk').values_list('name', flat=True))[1:3]
        self.assertEqual(
            list(queryset.values_list('name', flat=True)),
            expected,
        )


class TestModuloExpressionRegressions(TestCase):
    def test_modulo_expression_with_value_parameter_executes(self):
        author = Author.objects.create(name='mod-author')
        annotated = Author.objects.filter(pk=author.pk).annotate(
            mod_value=F('pk') % Value(2)
        ).values_list('mod_value', flat=True)
        self.assertEqual(list(annotated), [author.pk % 2])

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


class TestStringAggOrderingRegression(TestCase):
    @skipUnless(VERSION >= (6, 0), "StringAgg ordering is Django 6.0+")
    def test_stringagg_honors_ordering(self):
        Author.objects.bulk_create([
            Author(name='Charlie'),
            Author(name='Alice'),
            Author(name='Bob'),
        ])
        with self.assertNumQueries(1) as ctx:
            result = Author.objects.aggregate(
                names=StringAgg('name', delimiter=Value(', '), order_by=F('name'))
            )
        self.assertEqual(result['names'], 'Alice, Bob, Charlie')
        self.assertIn('WITHIN GROUP (', ctx[0]['sql'])
        self.assertIn('ORDER BY [testapp_author].[name]', ctx[0]['sql'])

    @skipUnless(VERSION >= (6, 0), "StringAgg ordering is Django 6.0+")
    def test_stringagg_order_by_outerref_does_not_use_within_group(self):
        publisher_1 = Publisher.objects.create(name='p1')
        Book.objects.create(name='Alpha', publisher=publisher_1)

        with self.assertNumQueries(1) as ctx:
            values = list(
                Publisher.objects.filter(pk=publisher_1.pk).annotate(
                    names=Subquery(
                        Book.objects.annotate(
                            names=StringAgg(
                                'name',
                                delimiter=Value(';'),
                                order_by=OuterRef('pk'),
                            )
                        ).values('names')[:1]
                    )
                ).values_list('names', flat=True)
            )

        self.assertEqual(values, ['Alpha'])
        self.assertNotIn('WITHIN GROUP', ctx[0]['sql'])
