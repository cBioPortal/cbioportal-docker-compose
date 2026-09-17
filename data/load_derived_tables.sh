#!/bin/bash
set -eo pipefail

echo "Populating derived tables..."
clickhouse-client \
    --user "${CLICKHOUSE_USER}" \
    --password "${CLICKHOUSE_PASSWORD}" \
    --database "${CLICKHOUSE_DB}" \
    --multiquery \
    --param_optimize_backoff_secs="${CLICKHOUSE_OPTIMIZE_BACKOFF_SECS:-0}" \
    < /data/populate_derived_tables.sql
echo "Successfully populated derived tables."
