try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

CLASSIFIERS=[
    'Development Status :: 4 - Beta',
    'License :: OSI Approved :: BSD License',
    'Framework :: Django',
    'Programming Language :: Python',
    'Programming Language :: Python :: 2',
    'Programming Language :: Python :: 2.4',
    'Programming Language :: Python :: 2.5',
    'Programming Language :: Python :: 2.6',
    'Programming Language :: Python :: 2.7',
    'Programming Language :: Python :: 3',
    'Programming Language :: Python :: 3.2',
    'Programming Language :: Python :: 3.3',
    'Topic :: Internet :: WWW/HTTP',
]

setup(
    name='django-pyodbc-azure',
    version='1.0.11',
    description='Django backend for MS SQL Server and Windows Azure SQL Database using pyodbc',
    long_description=open('README.rst').read(),
    author='Michiya Takahashi',
    url='https://github.com/michiya/django-pyodbc-azure',
    license='BSD',
    packages=['sql_server', 'sql_server.pyodbc', 'sql_server.extra'],
    install_requires=[
        'Django>=1.2,<1.6',
        'pyodbc>=2.1',
    ],
    classifiers=CLASSIFIERS,
    keywords='azure django',
)
