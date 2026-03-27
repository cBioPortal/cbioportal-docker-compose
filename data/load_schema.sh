#!/bin/bash
# This script is executed during ClickHouse container initialization (via docker-entrypoint-initdb.d).
# It loads the base schema from the SQL file, substituting SharedMergeTree with MergeTree on-the-fly.
#
# NOTE: cgds_clickhouse.sql uses SharedMergeTree which is a ClickHouse Cloud-only engine.
# Open-source / local Docker ClickHouse does not support SharedMergeTree; MergeTree is the
# correct single-node equivalent. This sed substitution is intentional and must stay until
# the upstream schema ships separate Cloud vs. community variants.
set -eo pipefail

sed "s/SharedMergeTree('[^']*','[^']*')/MergeTree()/g" /data/cgds_clickhouse.sql \
  | clickhouse-client \
      --user "${CLICKHOUSE_USER}" \
      --password "${CLICKHOUSE_PASSWORD}" \
      --database "${CLICKHOUSE_DB}" \
      --multiquery
