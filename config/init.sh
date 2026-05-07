#!/usr/bin/env bash
set -eo pipefail
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

VERSION=$(grep DOCKER_IMAGE_CBIOPORTAL ../.env | tail -n 1 | cut -d '=' -f 2-)

source <(grep -v '^#' ../.env | sed 's/^/export /')

CONTAINER=$(docker create $VERSION)
docker cp $CONTAINER:/cbioportal-webapp/app.jar "${SCRIPT_DIR}/app.jar"
docker rm $CONTAINER

unzip -p "${SCRIPT_DIR}/app.jar" BOOT-INF/classes/application.properties | \
    sed "s|spring.datasource.password=.*|spring.datasource.password=${CLICKHOUSE_PASSWORD}|" | \
    sed "s|spring.datasource.username=.*|spring.datasource.username=${CLICKHOUSE_USER}|" | \
    sed "s|spring.datasource.url=.*|spring.datasource.url=${DB_CLICKHOUSE_URL}|" | \
    sed "s|.*spring.datasource.clickhouse.username=.*|spring.datasource.clickhouse.username=${CLICKHOUSE_USER}|" | \
    sed "s|.*spring.datasource.clickhouse.password=.*|spring.datasource.clickhouse.password=${CLICKHOUSE_PASSWORD}|" | \
    sed "s|.*spring.datasource.clickhouse.url=.*|spring.datasource.clickhouse.url=${DB_CLICKHOUSE_URL}|" | \
    sed "s|.*spring.datasource.clickhouse.driver-class-name=.*|spring.datasource.clickhouse.driver-class-name=com.clickhouse.jdbc.ClickHouseDriver|" \
    > "${SCRIPT_DIR}/application.properties"

rm "${SCRIPT_DIR}/app.jar"
