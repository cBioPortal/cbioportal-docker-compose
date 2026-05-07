#!/bin/bash
# This script is executed during ClickHouse container initialization (via docker-entrypoint-initdb.d).
# It loads the base schema from the SQL file.
set -eo pipefail

clickhouse-client \
    --user "${CLICKHOUSE_USER}" \
    --password "${CLICKHOUSE_PASSWORD}" \
    --database "${CLICKHOUSE_DB}" \
    --multiquery \
    < /data/schema.sql
