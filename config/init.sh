#!/usr/bin/env bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

VERSION=$(grep DOCKER_IMAGE_CBIOPORTAL ../.env | tail -n 1 | cut -d '=' -f 2-)

# This is a hack. Docker run doesn't escape '&' but docker compose does.
sed 's/&/\\&/g' ../.env > ../.env.temp

# TODO: The pound (#) signs in the command below should be removed once the application.properties are changed.
docker run --rm -i --env-file ../.env.temp $VERSION bin/sh -c 'cat /cbioportal-webapp/application.properties |
    sed "s|spring.datasource.password=.*|spring.datasource.password=${DB_MYSQL_PASSWORD}|" | \
    sed "s|spring.datasource.username=.*|spring.datasource.username=${DB_MYSQL_USERNAME}|" | \
    sed "s|spring.datasource.url=.*|spring.datasource.url=${DB_MYSQL_URL}|" | \
    sed "s|#spring.datasource.mysql.username=.*|spring.datasource.mysql.username=${DB_MYSQL_USERNAME}|" | \
    sed "s|#spring.datasource.mysql.password=.*|spring.datasource.mysql.password=${DB_MYSQL_PASSWORD}|" | \
    sed "s|#spring.datasource.mysql.url=.*|spring.datasource.mysql.url=${DB_MYSQL_URL}|" | \
    sed "s|#spring.datasource.clickhouse.username=.*|spring.datasource.clickhouse.username=${DB_CLICKHOUSE_USERNAME}|" | \
    sed "s|#spring.datasource.clickhouse.password=.*|spring.datasource.clickhouse.password=${DB_CLICKHOUSE_PASSWORD}|" | \
    sed "s|#spring.datasource.clickhouse.url=.*|spring.datasource.clickhouse.url=${DB_CLICKHOUSE_URL}|" | \
    sed "s|#spring.datasource.mysql.driver-class-name=com.mysql.jdbc.Driver|spring.datasource.mysql.driver-class-name=com.mysql.jdbc.Driver|" | \
    sed "s|#spring.datasource.clickhouse.driver-class-name=com.clickhouse.jdbc.ClickHouseDriver|spring.datasource.clickhouse.driver-class-name=com.clickhouse.jdbc.ClickHouseDriver|"' \
> application.properties

# Cleanup for the hack above
rm ../.env.temp