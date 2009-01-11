"""
Sorting by related model fields, excerpts from Django queries regression tests.
"""

from django.db import models

class Tag(models.Model):
    name = models.CharField(max_length=10)
    parent = models.ForeignKey('self', blank=True, null=True,
            related_name='children')

    class Meta:
        ordering = ['name']

    def __unicode__(self):
        return self.name

class Note(models.Model):
    note = models.CharField(max_length=100)
    misc = models.CharField(max_length=10)

    class Meta:
        ordering = ['note']

    def __unicode__(self):
        return self.note

class ExtraInfo(models.Model):
    info = models.CharField(max_length=100)
    note = models.ForeignKey(Note)

    class Meta:
        ordering = ['info']

    def __unicode__(self):
        return self.info

class Item(models.Model):
    name = models.CharField(max_length=10)
    tags = models.ManyToManyField(Tag, blank=True, null=True)
    note = models.ForeignKey(Note)

    class Meta:
        ordering = ['-note', 'name']

    def __unicode__(self):
        return self.name

__test__ = {'API_TESTS':"""
>>> t1 = Tag.objects.create(name='t1')
>>> t2 = Tag.objects.create(name='t2', parent=t1)
>>> t3 = Tag.objects.create(name='t3', parent=t1)
>>> t4 = Tag.objects.create(name='t4', parent=t3)
>>> t5 = Tag.objects.create(name='t5', parent=t3)

>>> n1 = Note.objects.create(note='n1', misc='foo')
>>> n2 = Note.objects.create(note='n2', misc='bar')
>>> n3 = Note.objects.create(note='n3', misc='foo')

Create these out of order so that sorting by 'id' will be different to sorting
by 'info'. Helps detect some problems later.
>>> e2 = ExtraInfo.objects.create(info='e2', note=n2)
>>> e1 = ExtraInfo.objects.create(info='e1', note=n1)

>>> i1 = Item.objects.create(name='one', note=n3)
>>> i1.tags = [t1, t2]
>>> i2 = Item.objects.create(name='two', note=n2)
>>> i2.tags = [t1, t3]
>>> i3 = Item.objects.create(name='three', note=n3)
>>> i4 = Item.objects.create(name='four', note=n3)
>>> i4.tags = [t4]

Bug #2076
# Ordering on related tables should be possible, even if the table is not
# otherwise involved.
>>> Item.objects.order_by('note__note', 'name')
[<Item: two>, <Item: four>, <Item: one>, <Item: three>]

Bug #7181 -- ordering by related tables should accomodate nullable fields (this
test is a little tricky, since NULL ordering is database dependent. Instead, we
just count the number of results).
>>> len(Tag.objects.order_by('parent__name'))
5

Bug #7791 -- there were "issues" when ordering and distinct-ing on fields
related via ForeignKeys.
>>> len(Note.objects.order_by('extrainfo__info').distinct())
3
"""}
