# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from os import path
from setuptools import find_packages, setup

CLASSIFIERS = [
    'License :: OSI Approved :: BSD License',
    'Framework :: Django',
    "Operating System :: POSIX :: Linux",
    "Operating System :: Microsoft :: Windows",
    'Programming Language :: Python',
    'Programming Language :: Python :: 3',
    'Programming Language :: Python :: 3.5',
    'Programming Language :: Python :: 3.6',
    'Programming Language :: Python :: 3.7',
    'Framework :: Django :: 2.2',
    'Framework :: Django :: 3.0',
]

this_directory = path.abspath(path.dirname(__file__))
with open(path.join(this_directory, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='mssql-django',
    version='1.0b1',
    description='Django backend for Microsoft SQL Server',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='Microsoft',
    author_email='opencode@microsoft.com',
    url='https://github.com/microsoft/mssql-django',
    license='BSD',
    packages=find_packages(),
    install_requires=[
        'django>=2.2,<3.3',
        'pyodbc>=3.0',
        'pytz',
    ],
    package_data={'mssql': ['regex_clr.dll']},
    classifiers=CLASSIFIERS,
    keywords='django',
)
