#!/usr/bin/env bash

# Script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

# Default configuration values
DEFAULT_DOWNLOAD_RETRY_COUNT=3
DEFAULT_DOWNLOAD_RETRY_DELAY=10
DEFAULT_DOWNLOAD_TIMEOUT=30
DEFAULT_DATAHUB_STUDIES="lgg_ucsf_2014 msk_impact_2017"
DEFAULT_DATAHUB_BASE_URL="https://cbioportal-datahub.s3.amazonaws.com"
DEFAULT_SEED_DB_URL="https://github.com/cBioPortal/datahub/raw/master/seedDB/seed-cbioportal_hg19_hg38_v2.13.1.sql.gz"
DEFAULT_VERBOSE_LOGS=true
DEFAULT_DEBUG_MODE=false

# Initialize with default values
DOWNLOAD_RETRY_COUNT=${DEFAULT_DOWNLOAD_RETRY_COUNT}
DOWNLOAD_RETRY_DELAY=${DEFAULT_DOWNLOAD_RETRY_DELAY}
DOWNLOAD_TIMEOUT=${DEFAULT_DOWNLOAD_TIMEOUT}
DATAHUB_STUDIES=${DEFAULT_DATAHUB_STUDIES}
DATAHUB_BASE_URL=${DEFAULT_DATAHUB_BASE_URL}
SEED_DB_URL=${DEFAULT_SEED_DB_URL}
VERBOSE_LOGS=${DEFAULT_VERBOSE_LOGS}
DEBUG_MODE=${DEFAULT_DEBUG_MODE}

# Load .env.defaults if it exists
if [ -f "$SCRIPT_DIR/.env.defaults" ]; then
    echo "[INFO] Loading configuration from .env.defaults"
    source <(grep -E "^(DOWNLOAD_RETRY_COUNT|DOWNLOAD_RETRY_DELAY|DOWNLOAD_TIMEOUT|DATAHUB_STUDIES|DATAHUB_BASE_URL|SEED_DB_URL|VERBOSE_LOGS|DEBUG_MODE)=" "$SCRIPT_DIR/.env.defaults")
fi

# Override with .env if it exists
if [ -f "$SCRIPT_DIR/.env" ]; then
    echo "[INFO] Loading configuration overrides from .env"
    source <(grep -E "^(DOWNLOAD_RETRY_COUNT|DOWNLOAD_RETRY_DELAY|DOWNLOAD_TIMEOUT|DATAHUB_STUDIES|DATAHUB_BASE_URL|SEED_DB_URL|VERBOSE_LOGS|DEBUG_MODE)=" "$SCRIPT_DIR/.env")
fi

# Enable debug logging if requested
if [ "$DEBUG_MODE" = "true" ]; then
    set -x
fi

# Function to download files with retries
download_with_retry() {
    local url="$1"
    local destination="$2"
    local max_retries="${3:-$DOWNLOAD_RETRY_COUNT}"
    local retry_delay="${4:-$DOWNLOAD_RETRY_DELAY}"
    local timeout="${DOWNLOAD_TIMEOUT:-30}"
    local attempt=1

    if [ -f "$destination" ]; then
        echo "[INFO] File already exists: $destination (skipping download)"
        return 0
    fi

    echo "[INFO] Downloading $url to $destination (max $max_retries attempts)"

    while [ $attempt -le $max_retries ]; do
        echo "[INFO] Attempt $attempt of $max_retries"

        if wget --progress=dot:giga --timeout="$timeout" -O "$destination" "$url"; then
            echo "[SUCCESS] Download completed successfully on attempt $attempt"
            return 0
        fi

        echo "[WARNING] Download failed. Retrying in $retry_delay seconds..."
        sleep "$retry_delay"
        attempt=$((attempt + 1))
    done

    echo "[ERROR] Failed to download after $max_retries attempts" >&2
    return 1
}

# Function to extract archives with validation
extract_with_validation() {
    local archive="$1"
    local extract_dir="$2"

    if [ -d "$extract_dir" ] && [ "$(ls -A "$extract_dir")" ]; then
        echo "[INFO] Extraction already completed: $extract_dir (skipping)"
        return 0
    fi

    echo "[INFO] Extracting $archive to $extract_dir"

    if [ ! -s "$archive" ]; then
        echo "[ERROR] Archive $archive does not exist or is empty" >&2
        return 1
    fi

    mkdir -p "$extract_dir"

    case "$archive" in
        *.tar.gz) tar xzf "$archive" -C "$extract_dir" || { echo "[ERROR] Failed to extract tar.gz archive" >&2; return 1; } ;;
        *.zip) unzip -q "$archive" -d "$extract_dir" || { echo "[ERROR] Failed to extract zip archive" >&2; return 1; } ;;
        *) echo "[ERROR] Unsupported archive format" >&2; return 1 ;;
    esac

    echo "[SUCCESS] Extraction completed successfully"
    return 0
}
