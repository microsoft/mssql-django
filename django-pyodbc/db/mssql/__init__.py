# monkeypatching django
from django.contrib.sessions.backends.db import SessionStore
from django-pyodbc.contrib.sessions.backends.db import SessionStore as NewSessionStore
from django-pyodbc.db.models.base import Model
from django-pyodbc.db.models.base import Model as NewModel
import django.models.fields
import django-pyodbc.models.fields
from django.models.fields import TimeField, Field, DateTimeField
from django-pyodbc.models.fields import TimeField as NewTimeField, Field as NewField, DateTimeField as NewDateTimeField
from django.test.utils import _set_autocommit
from django.pyodbc.test.utils import _set_autocommitNew

#SessionStore.load - millisec
SessionStore.load = NewSessionStore.load

#Model.save - You can't insert an auto value into an identity column in MSSQL unless you do it explicitly 
Model.save = NewModel.save

#django.models.fields.prep_for_like_query
django.models.fields.prep_for_like_query = django-pyodbc.models.fields.prep_for_like_query

#Field.__init__ - add collation
Field.__init__ = NewField.__init__

#Field.get_db_prep_lookup - millisec
Field.get_db_prep_lookup = NewField.get_db_prep_lookup

#Field.get_db_prep_save - millisec
Field.get_db_prep_save = NewField.get_db_prep_save

#TimeField.get_db_prep_lookup - millisec
TimeField.get_db_prep_lookup = NewTimeField.get_db_prep_lookup

#TimeField.get_db_prep_save - millisec
TimeField.get_db_prep_save = NewTimeField.get_db_prep_save

#DateTimeField.get_db_prep_lookup - millisec
DateTimeField.get_db_prep_lookup = NewDateTimeField.get_db_prep_lookup

#DateTimeField.get_db_prep_save - millisec
DateTimeField.get_db_prep_save = NewDateTimeField.get_db_prep_save 

#test autocommit
_set_autocommit=_set_autocommitNew

