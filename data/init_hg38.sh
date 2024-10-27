#!/usr/bin/env bash

# Download the schema
wget -O cgds.sql "https://raw.githubusercontent.com/cBioPortal/cbioportal/v5.3.14/db-scripts/src/main/resources/cgds.sql"
# Download the seed database
wget -O seed.sql.gz "https://github.com/cBioPortal/datahub/raw/master/seedDB/seed-cbioportal_hg19_hg38_v2.13.1.sql.gz"
