# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

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
    # Issue #38:
    # This field started off as unique=True *and* null=True so it is implemented with a filtered unique index
    # Then it is made non-nullable by a subsequent migration, to check this is correctly handled (the index
    # should be dropped, then a normal unique constraint should be added, now that the column is not nullable)
    test_field = models.CharField(max_length=100, unique=True)

    # Issue #45 (case 1)
    # Field used for testing changing the 'type' of a field that's both unique & nullable
    x = models.CharField(max_length=11, null=True, unique=True)


class TestNullableUniqueTogetherModel(models.Model):
    class Meta:
        unique_together = (('a', 'b', 'c'),)

    # Issue #45 (case 2)
    # Fields used for testing changing the 'type of a field that is in a `unique_together`
    a = models.CharField(max_length=51, null=True)
    b = models.CharField(max_length=50)
    c = models.CharField(max_length=50)


class TestRemoveOneToOneFieldModel(models.Model):
    # Fields used for testing removing OneToOne field. Verifies that delete_unique do not try to remove indexes
    # thats already is removed.
    # b = models.OneToOneField('self', on_delete=models.SET_NULL, null=True)
    a = models.CharField(max_length=50)
