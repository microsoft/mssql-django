
from django.db import models

class Event(models.Model):
    start = models.ForeignKey('TimeRepresentation')

class TimeRepresentation(models.Model):
    hora = models.TimeField(null=True)

__test__ = {'API_TESTS': """
>>> from datetime import time

>>> t = TimeRepresentation.objects.create(hora=time(0, 0))
>>> ev = Event.objects.create(start=t)

# If we access without select_related, it works fine
>>> evs1 = Event.objects.all()
>>> evs1[0].start.hora
datetime.time(0, 0)

# If we access with select_related, it works too
>>> evs2 = Event.objects.all().select_related('start')
>>> evs2[0].start.hora
datetime.time(0, 0)

"""}
