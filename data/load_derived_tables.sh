#!/bin/bash
set -eo pipefail

echo "Creating derived tables..."
clickhouse client \
    --config-file ".${CP_CLICKHOUSE_CLIENT_INTERNAL_CONFIG_FOR_DB_UPDATE_PATH}" \
    --multiquery \
    --param_optimize_backoff_secs="${CP_CLICKHOUSE_OPTIMIZE_BACKOFF_SECS:-0}" \
    < /data/clickhouse.sql
echo "Successfully created derived tables."
