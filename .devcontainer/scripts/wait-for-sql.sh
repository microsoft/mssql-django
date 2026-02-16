#!/usr/bin/env bash
# wait-for-sql.sh — poll SQL Server until it accepts connections
set -euo pipefail

HOST="${MSSQL_HOST:-db}"
PORT="${MSSQL_PORT:-1433}"
USER="${MSSQL_USER:-sa}"
PASSWORD="${MSSQL_PASSWORD:-MyPassword42}"
MAX_RETRIES="${MSSQL_MAX_RETRIES:-30}"
SLEEP_INTERVAL=2

echo "Waiting for SQL Server at ${HOST}:${PORT}..."

for i in $(seq 1 "$MAX_RETRIES"); do
    # -C trusts the server certificate (bypasses TLS validation for local dev)
    if sqlcmd -S "${HOST},${PORT}" -U "${USER}" -P "${PASSWORD}" -C \
              -Q "SELECT 1" -b -o /dev/null 2>/dev/null; then
        echo "SQL Server is ready! (attempt ${i}/${MAX_RETRIES})"
        exit 0
    fi
    echo "  attempt ${i}/${MAX_RETRIES} — not ready yet, retrying in ${SLEEP_INTERVAL}s..."
    sleep "$SLEEP_INTERVAL"
done

echo "ERROR: SQL Server did not become available after ${MAX_RETRIES} attempts."
exit 1
