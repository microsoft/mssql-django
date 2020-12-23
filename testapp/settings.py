# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

DATABASES = {
    "default": {
        "ENGINE": "mssql",
        "NAME": "default",
        "USER": "sa",
        "PASSWORD": "MyPassword42",
        "HOST": "localhost",
        "PORT": "1433",
        "OPTIONS": {"driver": "ODBC Driver 17 for SQL Server", },
    },
    'other': {
        "ENGINE": "mssql",
        "NAME": "other",
        "USER": "sa",
        "PASSWORD": "MyPassword42",
        "HOST": "localhost",
        "PORT": "1433",
        "OPTIONS": {"driver": "ODBC Driver 17 for SQL Server", },
    },
}

INSTALLED_APPS = (
    'django.contrib.contenttypes',
    'django.contrib.staticfiles',
    'django.contrib.auth',
    'mssql',
    'testapp',
)

SECRET_KEY = "django_tests_secret_key"

# Use a fast hasher to speed up tests.
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]
