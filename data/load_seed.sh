#!/bin/bash
# This script is executed during ClickHouse container initialization (via docker-entrypoint-initdb.d).
# It loads the seed database (reference data: genes, cancer types, etc.) from the compressed SQL dump.
set -eo pipefail

echo "Loading seed data..."
gunzip -c /data/seed.sql.gz | clickhouse-client \
  --user "${CLICKHOUSE_USER}" \
  --password "${CLICKHOUSE_PASSWORD}" \
  --database "${CLICKHOUSE_DB}" \
  --multiquery
echo "Successfully loaded seed data."
