django-pyodbc-azure
===================

.. image:: http://img.shields.io/pypi/v/django-pyodbc-azure.svg?style=flat
    :target: https://pypi.python.org/pypi/django-pyodbc-azure

.. image:: http://img.shields.io/pypi/l/django-pyodbc-azure.svg?style=flat
    :target: http://opensource.org/licenses/BSD-3-Clause

*django-pyodbc-azure* is a modern fork of
`django-pyodbc <https://code.google.com/archive/p/django-pyodbc/>`__, a
`Django <https://www.djangoproject.com/>`__ Microsoft SQL Server external
DB backend that uses ODBC by employing the
`pyodbc <https://github.com/mkleehammer/pyodbc>`__ library. It supports
Microsoft SQL Server and Azure SQL Database.

Features
--------

-  Supports Django 1.11.13
-  Supports Microsoft SQL Server 2005, 2008/2008R2, 2012, 2014, 2016, 2017 and
   Azure SQL Database
-  Passes most of the tests of the Django test suite
-  Compatible with
   `Micosoft ODBC Driver for SQL Server <https://msdn.microsoft.com/library/mt654048(v=sql.1).aspx>`__,
   `SQL Server Native Client <https://msdn.microsoft.com/library/ms130892(v=sql.120).aspx>`__,
   `SQL Server <https://msdn.microsoft.com/library/aa968814(vs.85).aspx>`__
   and `FreeTDS <http://www.freetds.org/>`__ ODBC drivers

Dependencies
------------

-  Django 1.11.13
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

Standard Django settings
~~~~~~~~~~~~~~~~~~~~~~~~

The following entries in a database-level settings dictionary
in DATABASES control the behavior of the backend:

-  ENGINE

   String. It must be ``"sql_server.pyodbc"``.

-  NAME

   String. Database name. Required.

-  HOST

   String. SQL Server instance in ``"server\instance"`` (on-premise) or
   ``"server.database.windows.net"`` (Azure SQL Database) format.

-  PORT

   String. Server instance port.
   An empty string means the default port.

-  USER

   String. Database user name in ``"user"`` (on-premise) or
   ``"user@server"`` (Azure SQL Database) format.
   If not given then MS Integrated Security will be used.

-  PASSWORD

   String. Database user password.

-  AUTOCOMMIT

   Boolean. Set this to False if you want to disable
   Django's transaction management and implement your own.

and the following entries are also available in the TEST dictionary
for any given database-level settings dictionary:

-  NAME

   String. The name of database to use when running the test suite.
   If the default value (``None``) is used, the test database will use
   the name "test\_" + ``NAME``.

-  COLLATION

   String. The collation order to use when creating the test database.
   If the default value (``None``) is used, the test database is assigned
   the default collation of the instance of SQL Server.

-  DEPENDENCIES

   String. The creation-order dependencies of the database.
   See the official Django documentation for more details.

-  MIRROR

   String. The alias of the database that this database should
   mirror during testing. Default value is ``None``.
   See the official Django documentation for more details.

OPTIONS
~~~~~~~

Dictionary. Current available keys are:

-  driver

   String. ODBC Driver to use (``"ODBC Driver 11 for SQL Server"`` etc).
   See http://msdn.microsoft.com/en-us/library/ms130892.aspx. Default is
   ``"SQL Server"`` on Windows and ``"FreeTDS"`` on other platforms.

-  isolation_level

   String. Sets `transaction isolation level
   <https://docs.microsoft.com/en-us/sql/t-sql/statements/set-transaction-isolation-level-transact-sql>`__
   for each database session. Valid values for this entry are
   ``READ UNCOMMITTED``, ``READ COMMITTED``, ``REPEATABLE READ``,
   ``SNAPSHOT``, and ``SERIALIZABLE``. Default is ``None`` which means
   no isolation levei is set to a database session and SQL Server default
   will be used.

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

-  unicode_results

   Boolean. If it is set to ``True``, pyodbc's *unicode_results* feature
   is activated and strings returned from pyodbc are always Unicode.
   Default value is ``False``.

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
   when you use SQL Server 2005, or the outdated ODBC drivers (``"FreeTDS"``
   with TDS protocol v7.2 or earlier/``"SQL Server"``/``"SQL Native Client"``).

-  connection_timeout

   Integer. Sets the timeout in seconds for the database connection process.
   Default value is ``0`` which disables the timeout.

-  connection_retries

   Integer. Sets the times to retry the database connection process.
   Default value is ``5``.

-  connection_retry_backoff_time

   Integer. Sets the back off time in seconds for reries of
   the database connection process. Default value is ``5``.

-  query_timeout

   Integer. Sets the timeout in seconds for the database query.
   Default value is ``0`` which disables the timeout.

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
                'driver': 'ODBC Driver 13 for SQL Server',
            },
        },
    }
    
    # set this to False if you want to turn off pyodbc's connection pooling
    DATABASE_CONNECTION_POOLING = False

Limitations
-----------

The following features are currently not supported:

- Altering a model field from or to AutoField at migration

Notice
------

This version of *django-pyodbc-azure* only supports Django 1.11.
If you want to use it on older versions of Django,
specify an appropriate version number (1.10.x.x for Django 1.10)
at installation like this: ::

    pip install "django-pyodbc-azure<1.11"
