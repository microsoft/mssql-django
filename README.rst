django-pyodbc-azure
===================

*django-pyodbc-azure* is a refined fork of
`django-pyodbc <https://github.com/avidal/django-pyodbc>`__, a
`Django <http://djangoproject.com/>`__ MS SQL Server external DB backend
that uses ODBC by employing the
`pyodbc <https://code.google.com/p/pyodbc/>`__ library. It supports MS
SQL Server and Windows Azure SQL Database.

Features
--------

-  Supports Django 1.6
-  Supports MS SQL Server 2005, 2008/2008R2, 2012, and Windows Azure SQL
   Database
-  Supports LIMIT+OFFSET and offset w/o LIMIT emulation.
-  Passes most of the tests of the Django test suite.
-  Compatible with *SQL Server* and *SQL Server Native Client* (Windows),
   *Micosoft ODBC Driver for SQL Server* and *FreeTDS* (Linux) ODBC drivers.

Dependencies
------------

-  Django 1.6
-  pyodbc 3.0 or newer

Installation
------------

1. Install pyodbc and Django

2. Install django-pyodbc-azure ::

    pip install django-pyodbc-azure

3. Now you can point the ``ENGINE`` setting in the settings file used by
   your Django application or project to the ``'sql_server.pyodbc'``
   module path ::

    'ENGINE': 'sql_server.pyodbc'

Configuration
-------------

The following database-level settings control the behavior of the backend:

Standard Django settings
~~~~~~~~~~~~~~~~~~~~~~~~

-  ENGINE

   String. It must be ``"sql_server.pyodbc"``.

-  NAME

   String. Database name. Required.

-  HOST

   String. SQL Server instance in ``"server\instance"`` (on-premise) or
   ``"server.database.windows.net"`` (Windows Azure SQL Database) format.

-  PORT

   String. Server instance port.
   An empty string means the default port.

-  USER

   String. Database user name in ``"user"`` (on-premise) or
   ``"user@server"`` (Windows Azure SQL Database) format.
   If not given then MS Integrated Security will be used.

-  PASSWORD

   String. Database user password.

-  AUTOCOMMIT

   Boolean. Set this to False if you want to disable
   Django's transaction management and implement your own.

-  TEST_NAME

   String. The name of database to use when running the test suite.
   If the default value (``None``) is used, the test database will use
   the name "test\_" + ``NAME``.

-  TEST_COLLATION

   String. The collation order to use when creating the test database.
   If the default value (``None``) is used, the test database is assigned
   the default collation of the instance of SQL Server.

-  TEST_CREATE

   Boolean. If it is set to ``False``, the test database won’t be
   automatically created at the beginning of the tests and dropped at the end.
   This is useful not to be charged too much for creating new databases
   in every test when you run tests with Windows Azure SQL Database.

-  TEST_DEPENDENCIES

   String. The creation-order dependencies of the database.
   See the official Django documentation for more details.

-  TEST_MIRROR

   String. The alias of the database that this database should
   mirror during testing. Default value is ``None``.
   See the official Django documentation for more details.

OPTIONS
~~~~~~~

Dictionary. Current available keys are:

-  MARS_Connection

   Boolean. Only relevant when using Microsoft's SQL Server drivers
   (SQL Server Native Client or ODBC Driver for SQL Server).
   Default value is ``False``.

-  driver

   String. ODBC Driver to use (``"SQL Server Native Client 11.0"`` etc).
   See http://msdn.microsoft.com/en-us/library/ms130892.aspx. Default is
   ``"SQL Server"`` on Windows and ``"FreeTDS"`` on other platforms.

-  dsn

   String. A named DSN can be used instead of ``HOST``.

-  host_is_server

   Boolean. Only relevant if using the FreeTDS ODBC driver under
   Unix/Linux.

   By default, when using the FreeTDS ODBC driver the value specified in
   the ``HOST`` setting is used in a ``SERVERNAME`` ODBC connection
   string component instead of being used in a ``SERVER`` component;
   this means that this value should be the name of a *dataserver*
   definition present in the ``freetds.conf`` FreeTDS configuration file
   instead of a hostname or an IP address.

   But if this option is present and it's value is ``True``, this
   special behavior is turned off.

   See http://www.freetds.org/userguide/dsnless.htm for more information.

-  extra_params

   String. Additional parameters for the ODBC connection. The format is
   ``"param=value;param=value"``.

-  collation

   String. Name of the collation to use when performing text field
   lookups against the database. Default is ``None``; this means no
   collation specifier is added to your lookup SQL (the default
   collation of your database will be used). For Chinese language you
   can set it to ``"Chinese_PRC_CI_AS"``.

-  use_legacy_datetime

   Boolean. ``DateField``, ``TimeField`` and ``DateTimeField`` of models
   are mapped to SQL Server's legacy ``datetime`` type if the value is ``True``
   (the same behavior as the original ``django-pyodbc``). Otherwise, they
   are mapped to new dedicated data types (``date``, ``time``, ``datetime2``).
   Default value is ``False``, and note that the feature is always activated
   when you use SQL Server 2005 or FreeTDS.

backend-specific settings
~~~~~~~~~~~~~~~~~~~~~~~~~
The following project-level settings also control the behavior of the backend:

-  DATABASE_CONNECTION_POOLING

   Boolean. If it is set to ``False``, pyodbc's connection pooling feature
   won't be activated.

Example
~~~~~~~

Here is an example of the database settings:

::

    DATABASES = {
        'default': {
            'ENGINE': 'sql_server.pyodbc',
            'NAME': 'mydb',
            'USER': 'user@myserver',             
            'PASSWORD': 'password',
            'HOST': 'myserver.database.windows.net',
            'PORT': '',

            'OPTIONS': {
                'driver': 'SQL Server Native Client 11.0',
                'MARS_Connection': True,
            },
        },
    }
    
    # set this to False if you want to turn off pyodbc's connection pooling
    DATABASE_CONNECTION_POOLING = False

Notice
------

This version of *django-pyodbc-azure* only supports Django 1.6.
Specify the old version (1.0.x) at installation if you want to use it
on Django 1.5 or earlier: ::

    pip install "django-pyodbc-azure<1.1"

License
-------

New BSD LICENSE

Credits
-------

-  `Ramiro Morales <https://people.djangoproject.com/ramiro/>`__
-  `Filip Wasilewski <http://code.djangoproject.com/ticket/5246>`__
-  `Wei guangjing <https://people.djangoproject.com/vcc/>`__
-  `mamcx <http://code.djangoproject.com/ticket/5062>`__
-  `Alex Vidal <http://github.com/avidal/>`__
-  `Michiya Takahashi <http://github.com/michiya/>`__
