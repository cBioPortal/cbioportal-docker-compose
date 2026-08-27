#/usr/bash

set -eo pipefail

function compare_version() {
    local ver="$1"
    local reference_ver="$2"
    local compare_type="$3"

    local ver_minor_with_tail="${ver#*.}"
    local ver_major_len=$((${#ver}-${#ver_minor_with_tail}-1))
    local ver_major="${ver:0:ver_major_len}"
    local ver_tail="${ver_minor_with_tail#*.}"
    local ver_minor="${ver_minor_with_tail%%.*}"
    local reference_ver_minor_with_tail="${reference_ver#*.}"
    local reference_ver_major_len=$((${#reference_ver}-${#reference_ver_minor_with_tail}-1))
    local reference_ver_major="${reference_ver:0:reference_ver_major_len}"
    local reference_ver_tail="${reference_ver_minor_with_tail#*.}"
    local reference_ver_minor="${reference_ver_minor_with_tail%%.*}"
    case "$compare_type" in
        "lt")
            if [ "$ver_major" -lt "$reference_ver_major" ] ; then
                return 0
            fi
            if [ "$ver_major" -eq "$reference_ver_major" ] && [ "$ver_minor" -lt "$reference_ver_minor" ] ; then
                return 0
            fi
            ;;
        "eq")
            if [ "$ver_major" -eq "$reference_ver_major" ] && [ "$ver_minor" -eq "$reference_ver_minor" ] ; then
                return 0
            fi
            ;;
        "le")
            if [ "$ver_major" -lt "$reference_ver_major" ] ; then
                return 0
            fi
            if [ "$ver_major" -eq "$reference_ver_major" ] && [ "$ver_minor" -le "$reference_ver_minor" ] ; then
                return 0
            fi
            ;;
        *)
            echo "Warning : called compare_version() bash function on unknown compare_type argument: '$compare_type'" >&2
            ;;
    esac
    return 1 # catchall for false/fail return
}

function version_is_older() {
    local ver="$1"
    local reference_ver="$2"
    if compare_version "$ver" "$reference_ver" "lt" ; then
        return 0
    fi
    return 1
}

function version_is_equal() {
    local ver="$1"
    local reference_ver="$2"
    if compare_version "$ver" "$reference_ver" "eq" ; then
        return 0
    fi
    return 1
}

function version_is_older_or_equal() {
    local ver="$1"
    local reference_ver="$2"
    if compare_version "$ver" "$reference_ver" "le" ; then
        return 0
    fi
    return 1
}

function execute_clickhouse_statement() {
    local statement_string="$1"
    clickhouse client --config-file .${CP_CLICKHOUSE_CLIENT_INTERNAL_CONFIG_FOR_DB_ADMIN_PATH} --query "$statement_string"
}

# account may alredy exist if user has configured all three roles (db_admin / db_updater / web_app) to use the same (root privileged) account 
sql_statement="SELECT count() FROM system.users WHERE name = '${CP_CLICKHOUSE_USER_FOR_CBIOPORTAL_WEB_APP}'"
account_for_web_app_user_already_exists="$(execute_clickhouse_statement "${sql_statement}")"
if [ "$account_for_web_app_user_already_exists" == "0" ] ; then
    execute_clickhouse_statement "CREATE USER ${CP_CLICKHOUSE_USER_FOR_CBIOPORTAL_WEB_APP} IDENTIFIED WITH sha256_password BY '${CP_CLICKHOUSE_PASSWORD_FOR_CBIOPORTAL_WEB_APP}'"
    execute_clickhouse_statement "GRANT SELECT ON ${CP_CLICKHOUSE_DB}.* TO ${CP_CLICKHOUSE_USER_FOR_CBIOPORTAL_WEB_APP}"
    execute_clickhouse_statement "GRANT INSERT, ALTER, TRUNCATE ON ${CP_CLICKHOUSE_DB}.data_access_token TO ${CP_CLICKHOUSE_USER_FOR_CBIOPORTAL_WEB_APP}"
fi
sql_statement="SELECT count() FROM system.users WHERE name = '${CP_CLICKHOUSE_USER_FOR_CBIOPORTAL_DB_UPDATE}'"
account_for_db_update_user_already_exists="$(execute_clickhouse_statement "${sql_statement}")"
if [ "$account_for_db_update_user_already_exists" == "0" ] ; then
    execute_clickhouse_statement "CREATE USER ${CP_CLICKHOUSE_USER_FOR_CBIOPORTAL_DB_UPDATE} IDENTIFIED WITH sha256_password BY '${CP_CLICKHOUSE_PASSWORD_FOR_CBIOPORTAL_DB_UPDATE}'"
    execute_clickhouse_statement "GRANT SHOW TABLES, SHOW COLUMNS, SELECT, INSERT, ALTER, CREATE TABLE, CREATE VIEW, DROP TABLE, DROP VIEW, TRUNCATE, OPTIMIZE ON ${CP_CLICKHOUSE_DB}.* TO ${CP_CLICKHOUSE_USER_FOR_CBIOPORTAL_DB_UPDATE}" 
    execute_clickhouse_statement "GRANT SHOW COLUMNS, SELECT ON system.tables TO ${CP_CLICKHOUSE_USER_FOR_CBIOPORTAL_DB_UPDATE}"
    execute_clickhouse_statement "GRANT SHOW COLUMNS, SELECT ON system.parts TO ${CP_CLICKHOUSE_USER_FOR_CBIOPORTAL_DB_UPDATE}"
    execute_clickhouse_statement "GRANT SHOW COLUMNS, SELECT ON system.mutations TO ${CP_CLICKHOUSE_USER_FOR_CBIOPORTAL_DB_UPDATE}"
    execute_clickhouse_statement "GRANT SHOW COLUMNS, SELECT ON system.one TO ${CP_CLICKHOUSE_USER_FOR_CBIOPORTAL_DB_UPDATE}"
    detected_clickhouse_version="$(execute_clickhouse_statement 'SELECT version()')"
    if version_is_older "$detected_clickhouse_version" "24.10.x" ; then
        echo "Warning : initialization of clickhouse versions before 24.10 is unsupported and may result in a system which fails to properly import studies" >&2
    fi
    if version_is_older_or_equal "$detected_clickhouse_version" "25.6.x" ; then
        execute_clickhouse_statement "GRANT CLUSTER ON *.* TO ${CP_CLICKHOUSE_USER_FOR_CBIOPORTAL_DB_UPDATE}"
    else
        if version_is_older_or_equal "$detected_clickhouse_version" "26.4.x" ; then
            execute_clickhouse_statement "GRANT READ ON REMOTE TO ${CP_CLICKHOUSE_USER_FOR_CBIOPORTAL_DB_UPDATE}"
        else
            echo "Warning : initialization of clickhouse versions after 26.4 has not yet been evaluated. Problems are not expected, but be advised that version '$ver' has not yet been tested." >&2
            execute_clickhouse_statement "GRANT READ ON REMOTE TO ${CP_CLICKHOUSE_USER_FOR_CBIOPORTAL_DB_UPDATE}"
        fi
    fi
fi


