#!/usr/bin/env bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

# Download the ClickHouse base schema (table definitions)
wget -q -O cgds_clickhouse.sql "https://github.com/cBioPortal/seed_db_test/raw/main/seedDB/current/cgds_clickhouse.sql"

# Download the ClickHouse-compatible seed database (genes, cancer types, etc.)
wget -O seed.sql.gz "https://github.com/cBioPortal/seed_db_test/raw/main/seedDB/current/seed-cbioportal_hg19_hg38_v2.14.5_1.0.9.sql.gz"
