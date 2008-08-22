Django mssql backend using pyodbc
=================================

The external database backends for Django that support Microsoft SQL Server using pyodbc, work both on Linux and Windows.

INSTALL
=======

 1. Install pyodbc.

 2. Add the directory where you have copied the project files to your Python
    path. So, for example, if you have the following directory structure::

        /home/user/src/django-sql-server
            |
            +- docs (the directory that contains this file)
            |
            +- sql_server
                  |
                  +- pyodbc

    you should add /home/user/src/django-sql-server to you Python path. One
    way to do this is setting the PYTHONPATH environment variable::

       $ export PYTHONPATH=/home/user/src/django-sql-server

 3. Now you can point the `DATABASE_ENGINE` setting in the settings file used by
    your Django application or project to the `'sql_server.pyodbc'`
    module path::

        DATABASE_ENGINE='sql_server.pyodbc'

LICENSE
=======

New BSD LICENSE

CREDITS
=======

Filip Wasilewski (http://code.djangoproject.com/ticket/5246)
mamcx(http://code.djangoproject.com/ticket/5062)
Wei guangjing `<http://djangopeople.net/vcc/>`_
Peter hausel  `<http://djangopeople.net/pk11/>`_
Ramiro Morales `<http://djangopeople.net/ramiro/>`_

Let us know if we missed anybody!
