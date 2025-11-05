#!/bin/bash

set -eo pipefail

# Set up a working directory
cd /workdir

# Drop tables in clickhouse
./drop_tables_in_clickhouse_database.sh sling.properties

# Copy tables from mysql to clickhouse
./copy_mysql_database_tables_to_clickhouse.sh sling.properties

# Create derived tables
./create_derived_tables_in_clickhouse_database.sh sling.properties *.sql

# --github_branch_name