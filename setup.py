# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

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

setup(
    name='mssql-django',
    version='1.0.a1',
    description='Django backend for Microsoft SQL Server',
    long_description=open('README.md').read(),
    author='Microsoft',
    author_email='opencode@microsoft.com',
    url='https://github.com/microsoft/mssql-django',
    license='BSD',
    packages=find_packages(),
    install_requires=[
        'pyodbc>=3.0',
    ],
    package_data={'mssql': ['regex_clr.dll']},
    classifiers=CLASSIFIERS,
    keywords='django',
)
