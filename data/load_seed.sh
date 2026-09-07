#!/bin/bash
# This script is executed during Clickhouse container initialization (via docker-entrypoint-initdb.d).
# It loads the seed database (reference data: genes, cancer types, etc.) from the compressed SQL dump.
set -eo pipefail

echo "Loading seed data..."
gunzip -c /data/seed.sql.gz | clickhouse client \
  --config-file ."${CP_CLICKHOUSE_CLIENT_INTERNAL_CONFIG_FOR_DB_UPDATE_PATH}" \
  --multiquery
echo "Successfully loaded seed data."
