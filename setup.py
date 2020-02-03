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
    name='django-mssql-backend',
    version='2.7.0',
    description='Django backend for Microsoft SQL Server',
    long_description=open('README.rst').read(),
    author='ES Solutions AB',
    author_email='info@essolutions.se',
    url='https://github.com/ESSolutions/django-mssql-backend',
    license='BSD',
    packages=find_packages(),
    install_requires=[
        'pyodbc>=3.0',
    ],
    classifiers=CLASSIFIERS,
    keywords='django',
)
