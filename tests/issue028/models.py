"""
Queries that involve models with fields stored in columns with the same name.
"""

from django.db import models

class Page(models.Model):
    #id = models.AutoField(primary_key=True, db_column='pageid')
    pageid = models.AutoField(primary_key=True)
    name = models.CharField(max_length=50, blank=True)

    def __unicode__(self):
        return self.name

class TextElement(models.Model):
    name = models.CharField(max_length=50)
    page = models.ForeignKey(Page, null=True, blank=True, db_column='pageId')
    #page = models.ForeignKey(Page, db_column='pageId')

    def __unicode__(self):
        return self.name

__test__ = {'API_TESTS':"""
>>> TextElement.objects.all()[0:3].select_related('page')
[...]

>>> TextElement.objects.all().select_related('page')
[...]

>>> TextElement.objects.select_related('page')
[...]

>>> TextElement.objects.all()[0:3]
[<TextElement: Main title>, <TextElement: Main picture>, <TextElement: New content>]

#>>> TextElement.objects.all()[0:3].select_related()
#[<TextElement: Main title>, <TextElement: Main picture>, <TextElement: New content>]

#>>> TextElement.objects.all().select_related()[0:3]
#[<TextElement: Main title>, <TextElement: Main picture>, <TextElement: New content>]

#>>> TextElement.objects.select_related()[0:3]
#[<TextElement: Main title>, <TextElement: Main picture>, <TextElement: New content>]

# TODO:
# * Use the depth parameter
# * Test with a FK with null=False, create a new Model pair
# * Another group model with two FKs?

"""}
