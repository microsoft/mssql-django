# TODO:
#
# * m2m_through_regress
# * many_to_one_null

set -e

DJANGO_VERSION="$(python -m django --version)"

cd django
git fetch --depth=1 origin +refs/tags/*:refs/tags/*
git checkout $DJANGO_VERSION
pip install -r tests/requirements/py3.txt

coverage run tests/runtests.py --settings=testapp.settings --noinput introspection

python -m coverage xml --include '*mssql*' --omit '*virtualenvs*' -o coverage.xml

