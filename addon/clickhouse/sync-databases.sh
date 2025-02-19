#!/bin/bash

set -o pipefail

# Set up a working directory
cd /workdir

# Drop tables in clickhouse
./drop_tables_in_clickhouse_database.sh sling.properties

# Copy tables from mysql to clickhouse
./copy_mysql_database_tables_to_clickhouse.sh sling.properties

# Download clickhouse scripts from the repo
python3 download_clickhouse_sql_scripts_py3.py /workdir/

# Create derived tables
./create_derived_tables_in_clickhouse_database.sh sling.properties *.sql