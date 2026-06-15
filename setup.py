# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from os import path
from setuptools import find_packages, setup

CLASSIFIERS = [
    'License :: OSI Approved :: BSD License',
    'Framework :: Django',
    "Operating System :: POSIX :: Linux",
    "Operating System :: Microsoft :: Windows",
    'Programming Language :: Python',
    'Programming Language :: Python :: 3',
    'Programming Language :: Python :: 3.8',
    'Programming Language :: Python :: 3.9',
    'Programming Language :: Python :: 3.10',
    'Programming Language :: Python :: 3.11',
    'Programming Language :: Python :: 3.12',
    'Programming Language :: Python :: 3.13',
    'Programming Language :: Python :: 3.14',
    'Framework :: Django :: 3.2',
    'Framework :: Django :: 4.0',
    'Framework :: Django :: 4.1',
    'Framework :: Django :: 4.2',
    'Framework :: Django :: 5.0',
    'Framework :: Django :: 5.1',
    'Framework :: Django :: 5.2',
    'Framework :: Django :: 6.0',
]

this_directory = path.abspath(path.dirname(__file__))
with open(path.join(this_directory, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='mssql-django',
    version='1.7.2',
    description='Django backend for Microsoft SQL Server',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='Microsoft',
    author_email='opencode@microsoft.com',
    url='https://github.com/microsoft/mssql-django',
    project_urls={
    'Release Notes': 'https://github.com/microsoft/mssql-django/releases',
    },
    license='BSD',
    packages=find_packages(exclude=['testapp', 'testapp.*']),
    python_requires='>=3.8',
    install_requires=[
        'django>=3.2,<6.1',
        'pyodbc>=3.0',
        # zoneinfo (used in mssql/operations.py) is stdlib on 3.9+;
        # use backports.zoneinfo on 3.8.
        'backports.zoneinfo; python_version < "3.9"',
        # zoneinfo needs an IANA tz database at runtime. system
        # tzdata is not guaranteed (Windows ships without one;
        # minimal Linux images like alpine/distroless/scratch and
        # slim Lambda layers strip it). always installing the
        # tzdata pip package guarantees consistent behavior across
        # all hosts. it is ~340KB and zoneinfo prefers system tz
        # data when present, so it's a no-op on full Linux/macOS.
        'tzdata',
    ],
    extras_require={
        'test': ['unittest-xml-reporting>=3.2.0'],
    },
    package_data={'mssql': ['regex_clr.dll']},
    classifiers=CLASSIFIERS,
    keywords='django',
)
