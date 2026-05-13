#!/bin/bash
set -eo pipefail

clickhouse-client --database=cbioportal --multiquery < /init-sql/schema.sql
gunzip -c /init-sql/seed.sql.gz | clickhouse-client --database=cbioportal --multiquery
