#!/bin/bash
set -eo pipefail

clickhouse-client --database="${CLICKHOUSE_DB}" --multiquery < /init-sql/schema.sql
gunzip -c /init-sql/seed.sql.gz | clickhouse-client --database="${CLICKHOUSE_DB}" --multiquery
