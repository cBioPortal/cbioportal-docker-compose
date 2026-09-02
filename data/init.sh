#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

VERSION=$(grep DOCKER_IMAGE_CBIOPORTAL "${SCRIPT_DIR}/../.env" | tail -n 1 | cut -d '=' -f 2-)

CONTAINER=$(docker create "$VERSION")
TEMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/cbioportal-clickhouse-init.XXXXXX")
trap 'docker rm "$CONTAINER" >/dev/null; rm -rf "$TEMP_DIR"' EXIT

# Copy into a fresh directory first. This avoids Docker's surprising behavior
# of copying a file *inside* an existing directory when a previous interrupted
# run left (for example) data/seed.sql.gz as a directory. Refuse to replace a
# non-empty target so a real user file cannot be destroyed accidentally.
replace_generated_file() {
    source_path="$1"
    target_path="$2"
    temp_path="$TEMP_DIR/$(basename "$target_path")"
    docker cp "$CONTAINER:$source_path" "$temp_path"
    if [ -d "$target_path" ]; then
        if [ -n "$(find "$target_path" -mindepth 1 -print -quit)" ]; then
            echo "Refusing to replace non-empty generated target: $target_path" >&2
            exit 1
        fi
        rmdir "$target_path"
    fi
    mv -f "$temp_path" "$target_path"
}

replace_generated_file /cbioportal/db-scripts/clickhouse/init/schema.sql "${SCRIPT_DIR}/schema.sql"
replace_generated_file /cbioportal/db-scripts/clickhouse/init/seed-cbioportal_hg19_hg38_v2.14.5.sql.gz "${SCRIPT_DIR}/seed.sql.gz"
replace_generated_file /cbioportal/db-scripts/clickhouse/clickhouse.sql "${SCRIPT_DIR}/clickhouse.sql"
