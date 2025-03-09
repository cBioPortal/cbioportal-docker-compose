#!/usr/bin/env bash


set -eo pipefail
if [ "${DEBUG_MODE}" = "true" ]; then
    set -x
fi

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

# Ensure .env file exists
if [ ! -f "$SCRIPT_DIR/../.env" ]; then
    echo " Error: .env file is missing in the parent directory." >&2
    exit 1
fi


VERSION=$(grep DOCKER_IMAGE_CBIOPORTAL "$SCRIPT_DIR/../.env" | tail -n 1 | cut -d '=' -f 2-)
if [ -z "$VERSION" ]; then
    echo "❌ Error: Unable to extract DOCKER_IMAGE_CBIOPORTAL version from .env." >&2
    exit 1
fi

# Create a temporary .env file to escape special characters (e.g., `&`)
TEMP_ENV_FILE="$SCRIPT_DIR/../.env.temp"
sed 's/&/\\&/g' "$SCRIPT_DIR/../.env" > "$TEMP_ENV_FILE"


echo "⚙️ Generating application.properties using Docker image: $VERSION"
docker run --rm -i --env-file "$TEMP_ENV_FILE" "$VERSION" bin/sh -c 'cat /cbioportal-webapp/application.properties |
    sed "s|spring.datasource.password=.*|spring.datasource.password=${DB_MYSQL_PASSWORD}|" | \
    sed "s|spring.datasource.username=.*|spring.datasource.username=${DB_MYSQL_USERNAME}|" | \
    sed "s|spring.datasource.url=.*|spring.datasource.url=${DB_MYSQL_URL}|" | \
    sed "s|.*spring.datasource.mysql.username=.*|spring.datasource.mysql.username=${DB_MYSQL_USERNAME}|" | \
    sed "s|.*spring.datasource.mysql.password=.*|spring.datasource.mysql.password=${DB_MYSQL_PASSWORD}|" | \
    sed "s|.*spring.datasource.mysql.url=.*|spring.datasource.mysql.url=${DB_MYSQL_URL}|" | \
    sed "s|.*spring.datasource.clickhouse.username=.*|spring.datasource.clickhouse.username=${DB_CLICKHOUSE_USERNAME}|" | \
    sed "s|.*spring.datasource.clickhouse.password=.*|spring.datasource.clickhouse.password=${DB_CLICKHOUSE_PASSWORD}|" | \
    sed "s|.*spring.datasource.clickhouse.url=.*|spring.datasource.clickhouse.url=${DB_CLICKHOUSE_URL}|" | \
    sed "s|.*spring.datasource.mysql.driver-class-name=com.mysql.jdbc.Driver|spring.datasource.mysql.driver-class-name=com.mysql.jdbc.Driver|" | \
    sed "s|.*spring.datasource.clickhouse.driver-class-name=com.clickhouse.jdbc.ClickHouseDriver|spring.datasource.clickhouse.driver-class-name=com.clickhouse.jdbc.ClickHouseDriver|" > application.properties' || {
        echo "❌ Error: Failed to generate application.properties using Docker." >&2
        rm -f "$TEMP_ENV_FILE"
        exit 1
}


rm -f "$TEMP_ENV_FILE"


if [ ! -f application.properties ]; then
    echo " Error: application.properties file was not created." >&2
    exit 1
fi

echo " application.properties generated successfully."
