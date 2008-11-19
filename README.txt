=============
django-pyodbc
=============

A Django_ MS SQL Server external DB backend that uses ODBC by employing
the pyodbc_ library. It supports SQL Server 2000 and 2005.

.. _Django: http://djangoproject.com/
.. _pyodbc: http://pyodbc.sourceforge.net

Features
========

* Supports LIMIT+OFFSET and offset w/o LIMIT emulation under SS2005.
* Supports LIMIT+OFFSET under SS2000.
* Transparently supports Django's TextField both under SS2000 and SS2005.
* Passes most of the tests of the Django test suite.
* Compatible with SQL Server and SQL Server Native Client from Microsoft
  (Windows) and FreeTDS ODBC drivers (Linux).

Dependencies
============

* Django from SVN, revision 8328 or newer (1.0 is r8961.)
* pyodbc 2.0.58 or newer

Installation
============

 1. Install pyodbc.

 2. Add the directory where you have copied the project files to your Python
    path. So, for example, if you have the following directory structure::

        /home/user/src/django-pyodbc
            |
            +- sql_server
                  |
                  +- pyodbc

    you should add ``/home/user/src/django-pyodbc`` to you Python module search
    path. One way to do this is setting the ``PYTHONPATH`` environment
    variable::

       $ export PYTHONPATH=/home/user/src/django-pyodbc

 3. Now you can point the ``DATABASE_ENGINE`` setting in the settings file used
    by your Django application or project to the ``'sql_server.pyodbc'``
    module path::

        DATABASE_ENGINE='sql_server.pyodbc'

Configuration
=============

Standard Django settings
------------------------

``DATABASE_NAME``
    String. Database name. Required.

``DATABASE_HOST``
    String. SQL Server instance in ``"server\instance"`` format.

``DATABASE_PORT``
    String. Server instance port.

``DATABASE_USER``
    String. Database user name. If not given then MS Integrated Security will
    be used.

``DATABASE_PASSWORD``
    String. Database user password.

``DATABASE_OPTIONS``
    Dictionary. Current available keys are:

    ``autocommit``
        Boolean. Indicates if pyodbc should direct the the ODBC driver to
        activate the autocommit feature. Default value is ``False``.

    ``MARS_Connection``
        Boolean. Only relevant when running on Windows and with SQL Server 2005
        or later through MS *SQL Server Native client* driver (i.e. setting
	``DATABASE_ODBC_DRIVER`` to ``"SQL Native Client"``). See
        http://msdn.microsoft.com/en-us/library/ms131686.aspx.
        Default value is ``False``.

``django-pyodbc``-specific settings
-----------------------------------

``DATABASE_ODBC_DSN``
    String. A named DSN can be used instead of ``DATABASE_HOST``.

``DATABASE_ODBC_DRIVER``
    String. ODBC Driver to use. Default is ``"SQL Server"`` on Windows and
    ``"FreeTDS"`` on other platforms.

``DATABASE_EXTRA_PARAMS``
    String. Additional parameters for the ODBC connection. The format is
    ``"param=value;param=value"``.

``DATABASE_COLLATION``
    String. Name of the collation to use when performing text field lookups
    against the database. Default value is ``"Latin1_General_CI_AS"``.
    For Chinese language you can set it to ``"Chinese_PRC_CI_AS"``.

License
=======

New BSD LICENSE

Credits
=======

* Filip Wasilewski (http://code.djangoproject.com/ticket/5246)
* mamcx(http://code.djangoproject.com/ticket/5062)
* Wei guangjing `<http://djangopeople.net/vcc/>`_
* Peter hausel  `<http://djangopeople.net/pk11/>`_
* Ramiro Morales `<http://djangopeople.net/ramiro/>`_
