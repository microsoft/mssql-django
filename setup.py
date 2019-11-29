try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

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
]

setup(
    name='django-mssql-backend',
    version='2.4.2',
    description='Django backend for Microsoft SQL Server',
    long_description=open('README.rst').read(),
    author='ES Solutions AB',
    author_email='info@essolutions.se',
    url='https://github.com/ESSolutions/django-mssql-backend',
    license='BSD',
    packages=['sql_server', 'sql_server.pyodbc'],
    install_requires=[
        'pyodbc>=3.0',
    ],
    extras_require={
        'tests': ['dj-database-url==0.5.0'],
    },
    classifiers=CLASSIFIERS,
    keywords='django',
)
