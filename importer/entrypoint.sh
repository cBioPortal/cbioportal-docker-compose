#!/bin/bash
set -eo pipefail

mkdir -p /workdir && cd /workdir

CH_CLIENT="clickhouse-client --host ${CLICKHOUSE_HOST} --port ${CLICKHOUSE_PORT} --user ${CLICKHOUSE_USER} --password ${CLICKHOUSE_PASSWORD} --database ${CLICKHOUSE_DB} --multiquery"

# Step 1: Apply base schema
echo "Applying base schema..."
$CH_CLIENT < /cbioportal/schema.sql

# Step 2: Apply seed data
echo "Applying seed data..."
gunzip -c /cbioportal/seed.sql.gz | $CH_CLIENT

echo "Clickhouse database successfully initialized with seed data."
echo "Please import your studies using 'docker exec cbioportal metaImport.py ...' first before attempting to view the website."

tail -f /dev/null
