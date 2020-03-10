import uuid

from django.db import models
from django.utils import timezone


class Author(models.Model):
    name = models.CharField(max_length=100)


class Editor(models.Model):
    name = models.CharField(max_length=100)


class Post(models.Model):
    title = models.CharField('title', max_length=255)
    author = models.ForeignKey(Author, models.CASCADE)
    # Optional secondary author
    alt_editor = models.ForeignKey(Editor, models.SET_NULL, blank=True, null=True)

    class Meta:
        unique_together = (
            ('author', 'title', 'alt_editor'),
        )

    def __str__(self):
        return self.title


class Comment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE)
    text = models.TextField('text')
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.text


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    def __str__(self):
        return self.pk


class TestUniqueNullableModel(models.Model):
    # This field started off as unique=True *and* null=True so it is implemented with a filtered unique index
    # Then it is made non-nullable by a subsequent migration, to check this is correctly handled (the index
    # should be dropped, then a normal unique constraint should be added, now that the column is not nullable)
    test_field = models.CharField(max_length=100, unique=True)
