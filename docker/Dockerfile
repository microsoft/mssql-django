FROM python:3.6

ENV APT_KEY_DONT_WARN_ON_DANGEROUS_USAGE=DontWarn

RUN apt-get update && apt-get install -y apt-transport-https git

RUN curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -
RUN curl https://packages.microsoft.com/config/debian/9/prod.list > /etc/apt/sources.list.d/mssql-release.list
RUN apt-get update
RUN ACCEPT_EULA=Y apt-get install -y msodbcsql17 g++ unixodbc-dev

ADD . /code
WORKDIR /code
RUN pip install -e .["tests"]

ENV PYTHONPATH=$PYTHONPATH:/code

RUN git clone --branch=stable/2.2.x https://github.com/django/django.git "/code/django" --depth=1

RUN pip install -r /code/django/tests/requirements/py3.txt
