import uuid

from django.db import models
from django.utils import timezone


class Post(models.Model):
    title = models.CharField('title', max_length=255)

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
