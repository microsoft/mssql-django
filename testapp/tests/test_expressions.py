from unittest import skipUnless

from django import VERSION
from django.db.models import IntegerField
from django.db.models.expressions import Case, Exists, OuterRef, Subquery, Value, When
from django.test import TestCase

from ..models import Author, Comment, Post

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

    @skipUnless(DJANGO3, "Django 3 specific tests")
    def test_order_by_exists(self):
        author_without_posts = Author.objects.create(name="other author")
        authors_by_posts = Author.objects.order_by(Exists(Post.objects.filter(author=OuterRef('pk'))).desc())
        self.assertSequenceEqual(authors_by_posts, [self.author, author_without_posts])

        authors_by_posts = Author.objects.order_by(Exists(Post.objects.filter(author=OuterRef('pk'))).asc())
        self.assertSequenceEqual(authors_by_posts, [author_without_posts, self.author])
