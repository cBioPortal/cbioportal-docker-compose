#!/bin/bash
set -eo pipefail

echo "Creating derived tables..."
clickhouse-client \
    --user "${CLICKHOUSE_USER}" \
    --password "${CLICKHOUSE_PASSWORD}" \
    --database "${CLICKHOUSE_DB}" \
    --multiquery \
    --param_optimize_backoff_secs="${CLICKHOUSE_OPTIMIZE_BACKOFF_SECS:-0}" \
    < /data/clickhouse.sql
echo "Successfully created derived tables."
