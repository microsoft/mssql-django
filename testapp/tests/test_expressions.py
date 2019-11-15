from django.db.models.expressions import Exists, OuterRef, Subquery
from django.test import TestCase

from ..models import Comment, Post


class TestSubquery(TestCase):
    def setUp(self):
        self.post = Post.objects.create(title="foo")

    def test_with_count(self):
        newest = Comment.objects.filter(post=OuterRef('pk')).order_by('-created_at')
        Post.objects.annotate(
            post_exists=Subquery(newest.values('text')[:1])
        ).filter(post_exists=True).count()


class TestExists(TestCase):
    def setUp(self):
        self.post = Post.objects.create(title="foo")

    def test_with_count(self):
        Post.objects.annotate(
            post_exists=Exists(Post.objects.all())
        ).filter(post_exists=True).count()
