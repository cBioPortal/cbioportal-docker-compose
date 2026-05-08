#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

# Extract schema and derived tables scripts from the cBioPortal image
VERSION=$(grep DOCKER_IMAGE_CBIOPORTAL ../.env | tail -n 1 | cut -d '=' -f 2-)

trap 'rm -f "${SCRIPT_DIR}/app.jar"' EXIT

CONTAINER=$(docker create $VERSION)
docker cp $CONTAINER:/cbioportal-webapp/app.jar "${SCRIPT_DIR}/app.jar"
docker rm $CONTAINER

# Schema file for this Docker image
unzip -p "${SCRIPT_DIR}/app.jar" BOOT-INF/classes/db-scripts/clickhouse/init/schema.sql \
    > "${SCRIPT_DIR}/schema.sql"

# Download the ClickHouse-compatible seed database (genes, cancer types, etc.)
wget -O seed.sql.gz "https://github.com/cBioPortal/cbioportal/raw/refs/heads/add-clickhoue-database-schema-and-seed/src/main/resources/db-scripts/clickhouse/init/seed-cbioportal_hg19_hg38_v2.14.5.sql.gz"

# clickhouse.sql for this Docker image
unzip -p "${SCRIPT_DIR}/app.jar" BOOT-INF/classes/db-scripts/clickhouse/clickhouse.sql \
    > "${SCRIPT_DIR}/clickhouse.sql"
