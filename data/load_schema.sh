#!/bin/bash
# This script is executed during Clickhouse container initialization (via docker-entrypoint-initdb.d).
# It loads the base schema from the SQL file.
set -eo pipefail

echo "Loading schema..."
clickhouse client \
    --config-file ".${CP_CLICKHOUSE_CLIENT_INTERNAL_CONFIG_FOR_DB_UPDATE_PATH}" \
    --multiquery \
    < /data/schema.sql
echo "Successfully loaded schema."
