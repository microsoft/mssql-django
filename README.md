# SQL Server backend for Django

Welcome to the MSSQL-Django 3rd party backend project!

*mssql-django* is a fork of [django-mssql-backend](https://pypi.org/project/django-mssql-backend/). This project provides an enterprise database connectivity option for the Django Web Framework, with support for Microsoft SQL Server and Azure SQL Database.

We'd like to give thanks to the community that made this project possible, with particular recognition of the contributors: OskarPersson, michiya, dlo and the original Google Code django-pyodbc team. Moving forward we encourage partipation in this project from both old and new contributors!

We hope you enjoy using the MSSQL-Django 3rd party backend.

## Features

-  Supports Django 2.2, 3.0, 3.1, 3.2 and 4.0
-  Tested on Microsoft SQL Server 2016, 2017, 2019
-  Passes most of the tests of the Django test suite
-  Compatible with
   [Micosoft ODBC Driver for SQL Server](https://docs.microsoft.com/en-us/sql/connect/odbc/microsoft-odbc-driver-for-sql-server),
   [SQL Server Native Client](https://msdn.microsoft.com/en-us/library/ms131321(v=sql.120).aspx),
   and [FreeTDS](https://www.freetds.org/) ODBC drivers

## Dependencies

-  pyodbc 3.0 or newer

## Installation

1. Install pyodbc 3.0 (or newer) and Django
2. Install mssql-django:

       pip install mssql-django

3. Set the `ENGINE` setting in the `settings.py` file used by
   your Django application or project to `'mssql'`:

       'ENGINE': 'mssql'

## Configuration

### Standard Django settings

The following entries in a database-level settings dictionary
in DATABASES control the behavior of the backend:

-  ENGINE

   String. It must be `"mssql"`.

-  NAME

   String. Database name. Required.

-  HOST

   String. SQL Server instance in `"server\instance"` format.

-  PORT

   String. Server instance port.
   An empty string means the default port.

-  USER

   String. Database user name in `"user"` format.
   If not given then MS Integrated Security will be used.

-  PASSWORD

   String. Database user password.

-  AUTOCOMMIT

   Boolean. Set this to `False` if you want to disable
   Django's transaction management and implement your own.

-  Trusted_Connection

   String. Default is `"yes"`. Can be set to `"no"` if required.

and the following entries are also available in the `TEST` dictionary
for any given database-level settings dictionary:

-  NAME

   String. The name of database to use when running the test suite.
   If the default value (`None`) is used, the test database will use
   the name `"test_" + NAME`.

-  COLLATION

   String. The collation order to use when creating the test database.
   If the default value (`None`) is used, the test database is assigned
   the default collation of the instance of SQL Server.

-  DEPENDENCIES

   String. The creation-order dependencies of the database.
   See the official Django documentation for more details.

-  MIRROR

   String. The alias of the database that this database should
   mirror during testing. Default value is `None`.
   See the official Django documentation for more details.

### OPTIONS

Dictionary. Current available keys are:

-  driver

   String. ODBC Driver to use (`"ODBC Driver 17 for SQL Server"`,
   `"SQL Server Native Client 11.0"`, `"FreeTDS"` etc).
   Default is `"ODBC Driver 17 for SQL Server"`.

-  isolation_level

   String. Sets [transaction isolation level](https://docs.microsoft.com/en-us/sql/t-sql/statements/set-transaction-isolation-level-transact-sql)
   for each database session. Valid values for this entry are
   `READ UNCOMMITTED`, `READ COMMITTED`, `REPEATABLE READ`,
   `SNAPSHOT`, and `SERIALIZABLE`. Default is `None` which means
   no isolation levei is set to a database session and SQL Server default
   will be used.

-  dsn

   String. A named DSN can be used instead of `HOST`.

-  host_is_server

   Boolean. Only relevant if using the FreeTDS ODBC driver under
   Unix/Linux.

   By default, when using the FreeTDS ODBC driver the value specified in
   the ``HOST`` setting is used in a ``SERVERNAME`` ODBC connection
   string component instead of being used in a ``SERVER`` component;
   this means that this value should be the name of a *dataserver*
   definition present in the ``freetds.conf`` FreeTDS configuration file
   instead of a hostname or an IP address.

   But if this option is present and its value is ``True``, this
   special behavior is turned off. Instead, connections to the database
   server will be established using ``HOST`` and ``PORT`` options, without
   requiring ``freetds.conf`` to be configured.

   See https://www.freetds.org/userguide/dsnless.html for more information.

-  unicode_results

   Boolean. If it is set to ``True``, pyodbc's *unicode_results* feature
   is activated and strings returned from pyodbc are always Unicode.
   Default value is ``False``.

-  extra_params

   String. Additional parameters for the ODBC connection. The format is
   ``"param=value;param=value"``, [Azure AD Authentication](https://github.com/microsoft/mssql-django/wiki/Azure-AD-Authentication) (Service Principal, Interactive, Msi) can be added to this field.

-  collation

   String. Name of the collation to use when performing text field
   lookups against the database. Default is ``None``; this means no
   collation specifier is added to your lookup SQL (the default
   collation of your database will be used). For Chinese language you
   can set it to ``"Chinese_PRC_CI_AS"``.

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

### Backend-specific settings

The following project-level settings also control the behavior of the backend:

-  DATABASE_CONNECTION_POOLING

   Boolean. If it is set to ``False``, pyodbc's connection pooling feature
   won't be activated.

### Example

Here is an example of the database settings:

```python
    DATABASES = {
        'default': {
            'ENGINE': 'mssql',
            'NAME': 'mydb',
            'USER': 'user@myserver',
            'PASSWORD': 'password',
            'HOST': 'myserver.database.windows.net',
            'PORT': '',

            'OPTIONS': {
                'driver': 'ODBC Driver 17 for SQL Server',
            },
        },
    }

    # set this to False if you want to turn off pyodbc's connection pooling
    DATABASE_CONNECTION_POOLING = False
```

## Limitations

The following features are currently not fully supported:
- Altering a model field from or to AutoField at migration
- Django annotate functions have floating point arithmetic problems in some cases
- Annotate function with exists
- Exists function in order_by
- Righthand power and arithmetic with datatimes
- Timezones, timedeltas not fully supported
- Rename field/model with foreign key constraint
- Database level constraints
- Math degrees power or radians
- Bit-shift operators
- Filtered index
- Date extract function
- Hashing functions

JSONField lookups have limitations, more details [here](https://github.com/microsoft/mssql-django/wiki/JSONField).

## Contributing

More details on contributing can be found [here](CONTRIBUTING.md).

This project welcomes contributions and suggestions.  Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit https://cla.opensource.microsoft.com.

When you submit a pull request, a CLA bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

## Security Reporting Instructions

For security reporting instructions please refer to the [`SECURITY.md`](SECURITY.md) file in this repository.

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft
trademarks or logos is subject to and must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.
