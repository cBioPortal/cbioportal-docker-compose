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

# A partial/minimal gene fixture lets imports finish while silently dropping
# mutations and structural-variant sites. Treat the canonical seed as a
# startup invariant so the database cannot become "healthy" with incomplete
# molecular data.
gene_count=$(clickhouse-client \
  --user "${CLICKHOUSE_USER}" \
  --password "${CLICKHOUSE_PASSWORD}" \
  --database "${CLICKHOUSE_DB}" \
  --format TabSeparatedRaw \
  --query "SELECT count() FROM gene")
alias_count=$(clickhouse-client \
  --user "${CLICKHOUSE_USER}" \
  --password "${CLICKHOUSE_PASSWORD}" \
  --database "${CLICKHOUSE_DB}" \
  --format TabSeparatedRaw \
  --query "SELECT count() FROM gene_alias")
genetic_entity_count=$(clickhouse-client \
  --user "${CLICKHOUSE_USER}" \
  --password "${CLICKHOUSE_PASSWORD}" \
  --database "${CLICKHOUSE_DB}" \
  --format TabSeparatedRaw \
  --query "SELECT count() FROM genetic_entity")
if [ "${gene_count}" -lt 10000 ] \
  || [ "${alias_count}" -lt 1000 ] \
  || [ "${genetic_entity_count}" -lt 10000 ]; then
  echo "Canonical ClickHouse seed is incomplete (genes=${gene_count}, aliases=${alias_count}, genetic_entities=${genetic_entity_count})" >&2
  exit 1
fi
echo "Successfully loaded canonical seed data (genes=${gene_count}, aliases=${alias_count}, genetic_entities=${genetic_entity_count})."
