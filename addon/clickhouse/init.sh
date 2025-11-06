#!/bin/bash

set -eo pipefail

# Set up a working directory
mkdir -p /workdir && cd /workdir

# Add database credentials to properties file
cat /workdir/manage_cbioportal_databases_tool.properties | \
sed "s|mysql_database_name=.*|mysql_database_name=${MYSQL_DB}|" | \
sed "s|mysql_server_username=.*|mysql_server_username=${MYSQL_USER}|" | \
sed "s|mysql_server_password=.*|mysql_server_password=${MYSQL_PASSWORD}|" | \
sed "s|mysql_server_host_name=.*|mysql_server_host_name=${MYSQL_HOST}|" | \
sed "s|mysql_server_port=.*|mysql_server_port=${MYSQL_PORT}|" | \
sed "s|mysql_server_additional_args=.*|mysql_server_additional_args=${MYSQL_SERVER_ADDITIONAL_ARGS}|" | \
sed "s|clickhouse_database_name=.*|clickhouse_database_name=${CLICKHOUSE_DB}|" | \
sed "s|clickhouse_server_username=.*|clickhouse_server_username=${CLICKHOUSE_USER}|" | \
sed "s|clickhouse_server_password=.*|clickhouse_server_password=${CLICKHOUSE_PASSWORD}|" | \
sed "s|clickhouse_server_host_name=.*|clickhouse_server_host_name=${CLICKHOUSE_HOST}|" | \
sed "s|clickhouse_server_port=.*|clickhouse_server_port=${CLICKHOUSE_PORT}|" | \
sed "s|clickhouse_server_additional_args=.*|clickhouse_server_additional_args=${CLICKHOUSE_SERVER_ADDITIONAL_ARGS}|" | \
sed "s|clickhouse_max_memory_use_target=.*|clickhouse_max_memory_use_target=${CLICKHOUSE_MAX_MEM}|" \
> /workdir/sling.properties

# Use sling to populate clickhouse database
bash /workdir/sync-databases.sh
echo "Clickhouse database successfully initialized. Portal Application is now ready!"
touch /workdir/init-complete.txt

tail -f /dev/null