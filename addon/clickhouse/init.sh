#!/bin/bash
set -eo pipefail

mkdir -p /workdir && cd /workdir

CH_CLIENT="clickhouse-client --host ${CLICKHOUSE_HOST} --port ${CLICKHOUSE_PORT} --user ${CLICKHOUSE_USER} --password ${CLICKHOUSE_PASSWORD} --database ${CLICKHOUSE_DB} --multiquery"

# Step 1: Apply base schema
echo "Downloading base schema..."
wget -q -O /tmp/schema.sql \
    "https://raw.githubusercontent.com/cBioPortal/cbioportal/refs/heads/add-clickhoue-database-schema-and-seed/src/main/resources/db-scripts/clickhouse/init/schema.sql"

echo "Applying base schema..."
$CH_CLIENT < /tmp/schema.sql

# Step 2: Download and apply seed data
echo "Downloading seed data..."
wget -q -O /tmp/seed.sql.gz \
    "https://github.com/cBioPortal/cbioportal/raw/refs/heads/add-clickhoue-database-schema-and-seed/src/main/resources/db-scripts/clickhouse/init/seed-cbioportal_hg19_hg38_v2.14.5.sql.gz"

echo "Applying seed data..."
gunzip -c /tmp/seed.sql.gz | $CH_CLIENT

# Step 3: Apply derived tables (extracted from app.jar by schema extractor)
echo "Applying derived tables..."
$CH_CLIENT < /workdir/sql/clickhouse.sql

# Set up import support scripts from cbioportal-core
echo "Setting up import support scripts..."
rm -rf cbioportal-core
git clone --depth 1 --branch "$APP_CBIOPORTAL_CORE_BRANCH" "https://github.com/cBioPortal/cbioportal-core.git"
cp -r cbioportal-core/scripts/clickhouse_import_support/* /workdir
chmod +x /workdir/*.sh
rm -rf cbioportal-core

echo "Clickhouse database successfully initialized. Portal Application is now ready!"
touch /workdir/init-complete.txt

tail -f /dev/null
