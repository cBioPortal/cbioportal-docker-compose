#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

VERSION=$(grep DOCKER_IMAGE_CBIOPORTAL "${SCRIPT_DIR}/../.env" | tail -n 1 | cut -d '=' -f 2-)

CONTAINER=$(docker create $VERSION)
trap 'docker rm $CONTAINER' EXIT

docker cp $CONTAINER:/cbioportal/db-scripts/clickhouse/init/schema.sql "${SCRIPT_DIR}/schema.sql"
docker cp $CONTAINER:/cbioportal/db-scripts/clickhouse/init/seed-cbioportal_hg19_hg38_v2.14.5.sql.gz "${SCRIPT_DIR}/seed.sql.gz"
docker cp $CONTAINER:/cbioportal/db-scripts/clickhouse/clickhouse.sql "${SCRIPT_DIR}/clickhouse.sql"
