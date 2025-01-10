#!/usr/bin/env bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

VERSION=$(grep DOCKER_IMAGE_CBIOPORTAL ../.env | tail -n 1 | cut -d '=' -f 2-)

# Get the schema
docker run --rm -i $VERSION cat /cbioportal/db-scripts/cgds.sql > cgds.sql
# Download the seed database
wget -O seed.sql.gz "https://github.com/cBioPortal/datahub/raw/master/seedDB/seedDB_hg19_archive/seed-cbioportal_hg19_v2.12.14.sql.gz"
