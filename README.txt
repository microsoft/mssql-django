Django mssql backend using pyodbc
=================================

The external database backends for Django that support Microsoft SQL Server using pyodbc, work both on Linux and Windows.

INSTALL
=======

First install `pyodbc <http://pyodbc.sourceforge.net>`_, then copy "mssql" folder to your PYTHONPATH, e.g. lib/site-packages ,django/db/backends. and patch the django use django_r7671.diff.

LICENSE
=======

New BSD LICENSE

CREDITS
=======
Filip Wasilewski (http://code.djangoproject.com/ticket/5246)
mamcx(http://code.djangoproject.com/ticket/5062) 
Wei guangjing `<http://djangopeople.net/vcc/>`_
Peter hausel  `<http://djangopeople.net/pk11/>`_

let us know if we missed anybody!



