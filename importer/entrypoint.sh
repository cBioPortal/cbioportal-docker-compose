#!/bin/bash
set -eo pipefail

mkdir -p /workdir && cd /workdir

CH_CLIENT="clickhouse-client --host ${CLICKHOUSE_HOST} --port ${CLICKHOUSE_PORT} --user ${CLICKHOUSE_USER} --password ${CLICKHOUSE_PASSWORD} --database ${CLICKHOUSE_DB} --multiquery"

# Step 1: Apply base schema
echo "Applying base schema..."
$CH_CLIENT < /opt/schema.sql

# Step 2: Apply seed data
echo "Applying seed data..."
gunzip -c /opt/seed.sql.gz | $CH_CLIENT

# Step 3: Import studies into ClickHouse
echo "Importing studies..."
cd /cbioportal-core/scripts
for study in ${DATAHUB_STUDIES}; do
    echo "  Importing ${study}..."
    python3 -m importer.metaImport -s /study/${study} -n -o
done
cd /workdir

# Step 5: Apply derived tables
echo "Applying derived tables..."
cat > /tmp/clickhouse.properties << EOF
clickhouse_host=${CLICKHOUSE_HOST}
clickhouse_port=${CLICKHOUSE_PORT}
clickhouse_database_name=${CLICKHOUSE_DB}
clickhouse_user=${CLICKHOUSE_USER}
clickhouse_password=${CLICKHOUSE_PASSWORD}
EOF

bash /workdir/create_derived_tables_in_clickhouse_database.sh \
    /tmp/clickhouse.properties \
    "${CLICKHOUSE_DB}" \
    /workdir/sql/clickhouse.sql

echo "Clickhouse database successfully initialized. Portal Application is now ready!"
touch /workdir/init-complete.txt

tail -f /dev/null
