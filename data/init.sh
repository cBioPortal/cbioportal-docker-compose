#!/usr/bin/env bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

# Download the ClickHouse base schema (table definitions)
wget -q -O schema.sql "https://raw.githubusercontent.com/cBioPortal/cbioportal/refs/heads/add-clickhoue-database-schema-and-seed/src/main/resources/db-scripts/clickhouse/init/schema.sql"

# Download the ClickHouse-compatible seed database (genes, cancer types, etc.)
wget -O seed.sql.gz "https://github.com/cBioPortal/cbioportal/raw/refs/heads/add-clickhoue-database-schema-and-seed/src/main/resources/db-scripts/clickhouse/init/seed-cbioportal_hg19_hg38_v2.14.5.sql.gz"
