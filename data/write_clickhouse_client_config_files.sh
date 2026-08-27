#!/bin/bash
# This script is executed during Clickhouse container initialization (via docker-entrypoint-initdb.d).
# It writes the Clickhouse client configuration files from environment variable settings,
# enabling access to the clickhouse-database from the host environment.

set -eo pipefail

function write_clickhouse_client_config_file_for_user() {
    local outfilepath="$1"
    local user_description="$2"
    local internal_or_external="$3"
    local username="$4"
    local password="$5"
    echo "Writing Clickhouse client config file for ${user_description}..."
    echo -n > "${outfilepath}" # truncate file
    echo "user: ${username}" >> "${outfilepath}"
    echo "password: ${password}" >> "${outfilepath}"
    if [ "$internal_or_external" == "external" ] ; then
        echo "host: ${CP_CLICKHOUSE_HOST}" >> "${outfilepath}"
    else
        echo "host: localhost" >> "${outfilepath}"
    fi
    echo "database: ${CP_CLICKHOUSE_DB}" >> "${outfilepath}"
    if [ "${CP_CLICKHOUSE_USE_SECURE_TRANSPORT}" == "yes" ] ; then
        echo "port: ${CP_CLICKHOUSE_NATIVE_SECURE_PORT}" >> "${outfilepath}"
        echo "secure: true" >> "${outfilepath}"
    else
        echo "port: ${CP_CLICKHOUSE_NATIVE_INSECURE_PORT}" >> "${outfilepath}"
        echo "secure: false" >> "${outfilepath}"
    fi
}

write_clickhouse_client_config_file_for_user \
        ".${CP_CLICKHOUSE_CLIENT_INTERNAL_CONFIG_FOR_DB_ADMIN_PATH}" \
        "db admin user" \
        "internal" \
        "${CP_CLICKHOUSE_USER_FOR_DB_ADMIN}" \
        "${CP_CLICKHOUSE_PASSWORD_FOR_DB_ADMIN}"
write_clickhouse_client_config_file_for_user \
        ".${CP_CLICKHOUSE_CLIENT_INTERNAL_CONFIG_FOR_DB_UPDATE_PATH}" \
        "db update user" \
        "internal" \
        "${CP_CLICKHOUSE_USER_FOR_CBIOPORTAL_DB_UPDATE}" \
        "${CP_CLICKHOUSE_PASSWORD_FOR_CBIOPORTAL_DB_UPDATE}"
write_clickhouse_client_config_file_for_user \
        ".${CP_CLICKHOUSE_CLIENT_INTERNAL_CONFIG_FOR_WEB_APP_PATH}" \
        "web app user" \
        "internal" \
        "${CP_CLICKHOUSE_USER_FOR_CBIOPORTAL_WEB_APP}" \
        "${CP_CLICKHOUSE_PASSWORD_FOR_CBIOPORTAL_WEB_APP}"
write_clickhouse_client_config_file_for_user \
        "${CP_CLICKHOUSE_CLIENT_EXTERNAL_CONFIG_FOR_DB_ADMIN_PATH}" \
        "db admin user" \
        "external" \
        "${CP_CLICKHOUSE_USER_FOR_DB_ADMIN}" \
        "${CP_CLICKHOUSE_PASSWORD_FOR_DB_ADMIN}"
write_clickhouse_client_config_file_for_user \
        "${CP_CLICKHOUSE_CLIENT_EXTERNAL_CONFIG_FOR_DB_UPDATE_PATH}" \
        "db update user" \
        "external" \
        "${CP_CLICKHOUSE_USER_FOR_CBIOPORTAL_DB_UPDATE}" \
        "${CP_CLICKHOUSE_PASSWORD_FOR_CBIOPORTAL_DB_UPDATE}"
write_clickhouse_client_config_file_for_user \
        "${CP_CLICKHOUSE_CLIENT_EXTERNAL_CONFIG_FOR_WEB_APP_PATH}" \
        "web app user" \
        "external" \
        "${CP_CLICKHOUSE_USER_FOR_CBIOPORTAL_WEB_APP}" \
        "${CP_CLICKHOUSE_PASSWORD_FOR_CBIOPORTAL_WEB_APP}"
