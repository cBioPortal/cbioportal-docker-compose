#/usr/bash

set -eo pipefail

function execute_clickhouse_statement() {
    local statement_string="$1"
    clickhouse client --config-file .${CP_CLICKHOUSE_CLIENT_INTERNAL_CONFIG_FOR_DB_ADMIN_PATH} --host localhost --database system --query "$statement_string"
}

execute_clickhouse_statement "CREATE DATABASE ${CP_CLICKHOUSE_DB}"
