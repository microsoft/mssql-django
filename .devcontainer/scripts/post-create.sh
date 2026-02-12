#!/usr/bin/env bash
# post-create.sh — runs once after the dev container is built
set -euo pipefail

echo "🚀 Setting up mssql-django development environment..."

echo "📦 Installing mssql-django in editable mode..."
pip install -e .

echo "📦 Installing dev/test dependencies..."
pip install \
    pyodbc \
    pytz \
    coverage \
    unittest-xml-reporting \
    django-debug-toolbar \
    tox

# Clone Django source for running Django's own test suite (test.sh)
if [ ! -d "django" ]; then
    echo "📥 Cloning Django source for integration tests..."
    DJANGO_VERSION="$(python -m django --version)"
    git clone --depth 1 --branch "${DJANGO_VERSION}" \
        https://github.com/django/django.git django 2>/dev/null || \
    git clone --depth 1 https://github.com/django/django.git django
fi

# Set up useful shell aliases
echo "⚡ Setting up aliases..."
cat > ~/.shell_aliases << 'EOF'
# mssql-django development aliases
alias test='python manage.py test testapp'
alias testall='bash test.sh'
alias migrate='python manage.py migrate'
alias makemigrations='python manage.py makemigrations'
alias shell='python manage.py shell'
alias dbshell='python manage.py dbshell'
alias sqlcmd='sqlcmd -S db -U sa -P MyPassword42 -C'
EOF

# Ensure aliases are sourced in both shells
grep -qxF 'source ~/.shell_aliases' ~/.bashrc 2>/dev/null || echo 'source ~/.shell_aliases' >> ~/.bashrc
grep -qxF 'source ~/.shell_aliases' ~/.zshrc 2>/dev/null || echo 'source ~/.shell_aliases' >> ~/.zshrc

# Wait for SQL Server to be ready, then verify connectivity
echo "⏳ Waiting for SQL Server..."
bash .devcontainer/scripts/wait-for-sql.sh

echo ""
echo "=============================================="
echo "🎉 mssql-django dev environment is ready!"
echo "=============================================="
echo ""
echo "📦 What's ready:"
echo "  ✅ mssql-django installed (editable)"
echo "  ✅ SQL Server running (db:1433)"
echo "  ✅ Django source cloned for test suite"
echo ""
echo "🚀 Quick start - just type these commands:"
echo "  test            → Run testapp tests"
echo "  testall         → Run full Django test suite"
echo "  migrate         → Run migrations"
echo "  shell           → Django shell"
echo "  sqlcmd          → Connect to SQL Server"
echo ""
echo "=============================================="
