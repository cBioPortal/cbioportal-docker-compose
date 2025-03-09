#!/usr/bin/env bash


set -eo pipefail
if [ "${DEBUG_MODE}" = "true" ]; then
    set -x
fi


SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

#this  Extracts Docker image version from .env
VERSION=$(grep DOCKER_IMAGE_CBIOPORTAL "$SCRIPT_DIR/../.env" | tail -n 1 | cut -d '=' -f 2-)
if [ -z "$VERSION" ]; then
    echo " Error: Unable to extract DOCKER_IMAGE_CBIOPORTAL version from .env." >&2
    exit 1
fi

# This Fetchs the schema file (cgds.sql)
echo " Fetching schema file (cgds.sql) from Docker image: $VERSION"
if ! docker run --rm -i "$VERSION" cat /cbioportal/db-scripts/cgds.sql > "$SCRIPT_DIR/cgds.sql"; then
    echo "Error: Failed to fetch cgds.sql from Docker image." >&2
    exit 2
fi

# This Validates that cgds.sql was created successfully
if [ ! -f "$SCRIPT_DIR/cgds.sql" ]; then
    echo " Error: cgds.sql file was not created." >&2
    exit 3
fi

echo " Schema file (cgds.sql) fetched successfully."

# This  Downloads the seed database (seed.sql.gz)
SEED_URL="https://github.com/cBioPortal/datahub/raw/master/seedDB/seed-cbioportal_hg19_hg38_v2.13.1.sql.gz"
echo " Downloading seed database from: $SEED_URL"
if ! wget -O "$SCRIPT_DIR/seed.sql.gz" "$SEED_URL"; then
    echo " Error: Failed to download seed database from $SEED_URL." >&2
    exit 4
fi

# this Validates that seed.sql.gz was downloaded successfully
if [ ! -f "$SCRIPT_DIR/seed.sql.gz" ]; then
    echo " Error: seed.sql.gz file was not downloaded." >&2
    exit 5
fi

echo " Seed database (seed.sql.gz) downloaded successfully."

echo "=== Data initialization completed successfully ==="
