#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

VERSION=$(grep DOCKER_IMAGE_CBIOPORTAL "${SCRIPT_DIR}/../.env" | tail -n 1 | cut -d '=' -f 2-)

CONTAINER=$(docker create $VERSION)
trap 'docker rm $CONTAINER' EXIT

docker cp $CONTAINER:/cbioportal/db-scripts/clickhouse/init/schema.sql "${SCRIPT_DIR}/schema.sql"
docker cp $CONTAINER:/cbioportal/db-scripts/clickhouse/init/seed-cbioportal_hg19_hg38_v2.14.5.sql.gz "${SCRIPT_DIR}/seed.sql.gz"
docker cp $CONTAINER:/cbioportal/db-scripts/clickhouse/generate_derived_tables.sql "${SCRIPT_DIR}/generate_derived_tables.sql"
# migrate_schema.sql / migrate_db.py are NOT extracted here: the migration-runner service in
# docker-compose.yml runs them directly from inside the cbioportal image (which already has
# python3 + a clickhouse client, and already bundles db-scripts/clickhouse/migrate/), instead of
# from a host-mounted copy.
