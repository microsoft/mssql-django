# Use Debian Bookworm explicitly - Microsoft packages are signed for Debian 12
FROM mcr.microsoft.com/devcontainers/python:3.14-bookworm

ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies (including libmemcached-dev for Django's pylibmc tests)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        gnupg \
        unixodbc-dev \
        libmemcached-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Microsoft ODBC Driver for SQL Server (both 17 and 18)
RUN curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql17 msodbcsql18 mssql-tools18 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Add mssql-tools to PATH
ENV PATH="$PATH:/opt/mssql-tools18/bin"

# Pre-install core Python dependencies so post-create is faster
RUN pip install --no-cache-dir \
        pyodbc \
        pytz \
        coverage

WORKDIR /workspaces/mssql-django
