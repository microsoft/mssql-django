#!/usr/bin/env bash
# run-tests.sh — convenience wrapper for running tests
#
# Usage:
#   bash .devcontainer/scripts/run-tests.sh              # run mssql-django tests
#   bash .devcontainer/scripts/run-tests.sh --django      # run Django's test suite (test.sh)
#   bash .devcontainer/scripts/run-tests.sh --module queries  # run a specific Django test module
#   bash .devcontainer/scripts/run-tests.sh --coverage    # run with coverage report
set -euo pipefail

cd /workspaces/mssql-django

case "${1:-}" in
    --django)
        echo "==> Running Django's own test suite via test.sh..."
        bash test.sh
        ;;
    --module)
        shift
        MODULE="${1:?'Provide a module name, e.g.: --module queries'}"
        echo "==> Running Django test module: ${MODULE}..."
        cd django
        DJANGO_VERSION="$(python -m django --version)"
        # Ensure checkout matches installed Django version
        CURRENT_REF="$(git describe --tags --exact-match 2>/dev/null || echo 'unknown')"
        if [ "${CURRENT_REF}" != "${DJANGO_VERSION}" ]; then
            echo "==> Switching Django checkout from ${CURRENT_REF} to ${DJANGO_VERSION}..."
            git fetch --depth=1 origin +refs/tags/*:refs/tags/* 2>/dev/null || true
            git checkout "${DJANGO_VERSION}" 2>/dev/null || true
        fi
        pip install -q -r tests/requirements/py3.txt 2>/dev/null || true
        coverage run tests/runtests.py --settings=testapp.settings --noinput "${MODULE}"
        coverage report --include='*mssql*' --omit='*virtualenvs*'
        coverage xml --include='*mssql*' --omit='*virtualenvs*' -o coverage.xml
        echo "Coverage report written to coverage.xml"
        ;;
    --coverage)
        echo "==> Running mssql-django tests with coverage..."
        coverage run manage.py test testapp --noinput -v2
        coverage report --include='*mssql*' --omit='*virtualenvs*'
        coverage xml --include='*mssql*' --omit='*virtualenvs*' -o coverage.xml
        echo "Coverage report written to coverage.xml"
        ;;
    *)
        echo "==> Running mssql-django tests..."
        python manage.py test testapp --noinput -v2
        ;;
esac
