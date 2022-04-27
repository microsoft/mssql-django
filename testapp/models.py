# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

import datetime
import uuid

from django import VERSION
from django.db import models
from django.db.models import Q
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
    # Issue https://github.com/ESSolutions/django-mssql-backend/issues/38:
    # This field started off as unique=True *and* null=True so it is implemented with a filtered unique index
    # Then it is made non-nullable by a subsequent migration, to check this is correctly handled (the index
    # should be dropped, then a normal unique constraint should be added, now that the column is not nullable)
    test_field = models.CharField(max_length=100, unique=True)

    # Issue https://github.com/ESSolutions/django-mssql-backend/issues/45 (case 1)
    # Field used for testing changing the 'type' of a field that's both unique & nullable
    x = models.CharField(max_length=11, null=True, unique=True)

    # A variant of Issue https://github.com/microsoft/mssql-django/issues/14 case (b)
    # but for a unique index (not db_index)
    y_renamed = models.IntegerField(null=True, unique=True)


class TestNullableUniqueTogetherModel(models.Model):
    class Meta:
        unique_together = (('a', 'b', 'c'),)

    # Issue https://github.com/ESSolutions/django-mssql-backend/issues/45 (case 2)
    # Fields used for testing changing the type of a field that is in a `unique_together`
    a = models.CharField(max_length=51, null=True)
    b = models.CharField(max_length=50)
    c = models.CharField(max_length=50)


class TestRemoveOneToOneFieldModel(models.Model):
    # Issue https://github.com/ESSolutions/django-mssql-backend/pull/51
    # Fields used for testing removing OneToOne field. Verifies that delete_unique
    # does not try to remove indexes that have already been removed
    # b = models.OneToOneField('self', on_delete=models.SET_NULL, null=True)
    a = models.CharField(max_length=50)


class TestIndexesRetainedRenamed(models.Model):
    # Issue https://github.com/microsoft/mssql-django/issues/14
    # In all these cases the column index should still exist afterwards
    # case (a) `a` starts out not nullable, but then is changed to be nullable
    a = models.IntegerField(db_index=True, null=True)
    # case (b) column originally called `b` is renamed
    b_renamed = models.IntegerField(db_index=True)
    # case (c) this entire model is renamed - this is just a column whose index can be checked afterwards
    c = models.IntegerField(db_index=True)


class M2MOtherModel(models.Model):
    name = models.CharField(max_length=10)


class TestRenameManyToManyFieldModel(models.Model):
    # Issue https://github.com/microsoft/mssql-django/issues/86
    others_renamed = models.ManyToManyField(M2MOtherModel)


class Topping(models.Model):
    name = models.UUIDField(primary_key=True, default=uuid.uuid4)


class Pizza(models.Model):
    name = models.UUIDField(primary_key=True, default=uuid.uuid4)
    toppings = models.ManyToManyField(Topping)

    def __str__(self):
        return "%s (%s)" % (
            self.name,
            ", ".join(topping.name for topping in self.toppings.all()),
        )


class TestUnsupportableUniqueConstraint(models.Model):
    class Meta:
        managed = False
        constraints = [
            models.UniqueConstraint(
                name='or_constraint',
                fields=['_type'],
                condition=(Q(status='in_progress') | Q(status='needs_changes')),
            ),
        ]

    _type = models.CharField(max_length=50)
    status = models.CharField(max_length=50)


class TestSupportableUniqueConstraint(models.Model):
    class Meta:
        constraints = [
            models.UniqueConstraint(
                name='and_constraint',
                fields=['_type'],
                condition=(
                    Q(status='in_progress') & Q(status='needs_changes') & Q(status='published')
                ),
            ),
            models.UniqueConstraint(
                name='in_constraint',
                fields=['_type'],
                condition=(Q(status__in=['in_progress', 'needs_changes'])),
            ),
        ]

    _type = models.CharField(max_length=50)
    status = models.CharField(max_length=50)


class BinaryData(models.Model):
    binary = models.BinaryField(null=True)


if VERSION >= (3, 1):
    class JSONModel(models.Model):
        value = models.JSONField()

        class Meta:
            required_db_features = {'supports_json_field'}


if VERSION >= (3, 2):
    class TestCheckConstraintWithUnicode(models.Model):
        name = models.CharField(max_length=100)

        class Meta:
            required_db_features = {
                'supports_table_check_constraints',
            }
            constraints = [
                models.CheckConstraint(
                    check=~models.Q(name__startswith='\u00f7'),
                    name='name_does_not_starts_with_\u00f7',
                )
            ]


class Question(models.Model):
    question_text = models.CharField(max_length=200)
    pub_date = models.DateTimeField('date published')

    def __str__(self):
        return self.question_text

    def was_published_recently(self):
        return self.pub_date >= timezone.now() - datetime.timedelta(days=1)


class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, null=True)
    choice_text = models.CharField(max_length=200)
    votes = models.IntegerField(default=0)

    class Meta:
        unique_together = (('question', 'choice_text'))


class Customer_name(models.Model):
    Customer_name = models.CharField(max_length=100)
    class Meta:
        ordering = ['Customer_name']

class Customer_address(models.Model):
    Customer_name = models.ForeignKey(Customer_name, on_delete=models.CASCADE)
    Customer_address = models.CharField(max_length=100)
    class Meta:
        ordering = ['Customer_address']
