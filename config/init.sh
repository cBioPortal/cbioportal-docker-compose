#!/usr/bin/env bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

function output_setting_from_main_env_file() {
    setting_name="$1"
    echo "$(egrep "^"${setting_name} ../.env | tail -n 1 | cut -d '=' -f 2-)"
}

# get needed settings for configuring spring.datasource.clickhouse.url in application.properties from the main docker compose .env file
CP_DOCKER_IMAGE_CBIOPORTAL="$(output_setting_from_main_env_file CP_DOCKER_IMAGE_CBIOPORTAL)"
CP_CLICKHOUSE_HOST="$(output_setting_from_main_env_file CP_CLICKHOUSE_HOST)"
CP_CLICKHOUSE_HTTP_INSECURE_PORT="$(output_setting_from_main_env_file CP_CLICKHOUSE_HTTP_INSECURE_PORT)"
CP_CLICKHOUSE_HTTP_SECURE_PORT="$(output_setting_from_main_env_file CP_CLICKHOUSE_HTTP_SECURE_PORT)"
CP_CLICKHOUSE_DB="$(output_setting_from_main_env_file CP_CLICKHOUSE_DB)"
CP_CLICKHOUSE_USE_SECURE_TRANSPORT="$(output_setting_from_main_env_file CP_CLICKHOUSE_USE_SECURE_TRANSPORT)"
if [ "$CP_CLICKHOUSE_USE_SECURE_TRANSPORT" == "no" ] ; then
    CP_CLICKHOUSE_URL="jdbc:ch://${CP_CLICKHOUSE_HOST}:${CP_CLICKHOUSE_HTTP_INSECURE_PORT}/${CP_CLICKHOUSE_DB}"
else
    CP_CLICKHOUSE_URL="jdbc:ch://${CP_CLICKHOUSE_HOST}:${CP_CLICKHOUSE_HTTP_SECURE_PORT}/${CP_CLICKHOUSE_DB}"
fi

# This is a hack. Docker run doesn't escape '&' but docker compose does.
sed 's/&/\\&/g' ../.env > ../.env.temp

# add needed environment to .env.temp
echo "CP_CLICKHOUSE_URL_FINAL=${CP_CLICKHOUSE_URL}" >> ../.env.temp

# update docker image copy of application.properties
docker run --rm -i --env-file ../.env.temp $CP_DOCKER_IMAGE_CBIOPORTAL bin/sh -c 'cat /cbioportal-webapp/application.properties |
    sed "s|spring.datasource.password=.*|spring.datasource.password=${CP_CLICKHOUSE_PASSWORD_FOR_CBIOPORTAL_DB_UPDATE}|" | \
    sed "s|spring.datasource.username=.*|spring.datasource.username=${CP_CLICKHOUSE_USER_FOR_CBIOPORTAL_DB_UPDATE}|" | \
    sed "s|spring.datasource.url=.*|spring.datasource.url=${CP_CLICKHOUSE_URL_FINAL}|" | \
    sed "s|.*spring.datasource.clickhouse.username=.*|spring.datasource.clickhouse.username=${CP_CLICKHOUSE_USER_FOR_CBIOPORTAL_DB_UPDATE}|" | \
    sed "s|.*spring.datasource.clickhouse.password=.*|spring.datasource.clickhouse.password=${CP_CLICKHOUSE_PASSWORD_FOR_CBIOPORTAL_DB_UPDATE}|" | \
    sed "s|.*spring.datasource.clickhouse.url=.*|spring.datasource.clickhouse.url=${CP_CLICKHOUSE_URL_FINAL}|"' \
> application.properties

# Cleanup for the hack above
rm ../.env.temp
