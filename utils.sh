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
    source "$SCRIPT_DIR/.env.defaults"
fi

# Override with .env if it exists
if [ -f "$SCRIPT_DIR/.env" ]; then
    echo "[INFO] Loading configuration overrides from .env"
    source "$SCRIPT_DIR/.env"
fi

# Enable debug logging if requested
if [ "$DEBUG_MODE" = "true" ]; then
    set -x
fi

# Function to download files with retries and progress bar
download_with_retry() {
    local url="$1"
    local destination="$2"
    local max_retries="${3:-$DOWNLOAD_RETRY_COUNT}"
    local retry_delay="${4:-$DOWNLOAD_RETRY_DELAY}"
    local timeout="${DOWNLOAD_TIMEOUT:-30}"
    local attempt=1
    local report_file="$SCRIPT_DIR/../init_report.txt"
    
    # Check if file already exists
    if [ -f "$destination" ]; then
        echo "[INFO] File already exists: $destination (skipping download)"
        # Add to summary report
        echo "SUCCESS: $(basename "$destination") already exists (skipped download)" >> "$report_file"
        return 0
    fi
    
    echo "[INFO] Downloading $url to $destination (max $max_retries attempts)"
    
    # Create a temporary file to track progress
    local temp_log=$(mktemp)
    
    while [ $attempt -le $max_retries ]; do
        echo "[INFO] Download attempt $attempt of $max_retries"
        
        # Try to download with wget and show progress bar
        if wget --no-verbose --continue --timeout=$timeout \
                --progress=bar:force --show-progress \
                -O "$destination" "$url" 2>&1 | tee "$temp_log"; then
            echo "[SUCCESS] Download completed successfully on attempt $attempt"
            # Add to summary report
            echo "SUCCESS: Downloaded $(basename "$destination") on attempt $attempt" >> "$report_file"
            rm -f "$temp_log"
            return 0
        fi
        
        attempt=$((attempt + 1))
        if [ $attempt -le $max_retries ]; then
            echo "[INFO] Retrying download in $retry_delay seconds..."
            sleep $retry_delay
        else
            echo "[ERROR] Failed to download after $max_retries attempts" >&2
            # Add to summary report
            echo "FAILED: Download of $(basename "$destination") after $max_retries attempts" >> "$report_file"
            rm -f "$temp_log"
            return 1
        fi
    done
}

# Function to extract archives with validation
extract_with_validation() {
    local archive="$1"
    local extract_dir="$2"
    local report_file="$SCRIPT_DIR/../init_report.txt"

    if [ -d "$extract_dir" ] && [ "$(ls -A "$extract_dir")" ]; then
        echo "[INFO] Extraction already completed: $extract_dir (skipping)"
        echo "SUCCESS: Extraction of $(basename "$archive") already completed (skipped)" >> "$report_file"
        return 0
    fi

    echo "[INFO] Extracting $archive to $extract_dir"

    if [ ! -s "$archive" ]; then
        echo "[ERROR] Archive $archive does not exist or is empty" >&2
        echo "FAILED: Extraction of $(basename "$archive") - file does not exist or is empty" >> "$report_file"
        return 1
    fi

    mkdir -p "$extract_dir"

    case "$archive" in
        *.tar.gz) 
            if tar xzf "$archive" -C "$extract_dir"; then
                echo "[SUCCESS] Extraction completed successfully"
                echo "SUCCESS: Extracted $(basename "$archive") to $(basename "$extract_dir")" >> "$report_file"
                return 0
            else
                echo "[ERROR] Failed to extract tar.gz archive" >&2
                echo "FAILED: Extraction of $(basename "$archive") - tar extraction error" >> "$report_file"
                return 1
            fi ;;
        *.zip) 
            if unzip -q "$archive" -d "$extract_dir"; then
                echo "[SUCCESS] Extraction completed successfully"
                echo "SUCCESS: Extracted $(basename "$archive") to $(basename "$extract_dir")" >> "$report_file"
                return 0
            else
                echo "[ERROR] Failed to extract zip archive" >&2
                echo "FAILED: Extraction of $(basename "$archive") - unzip extraction error" >> "$report_file"
                return 1
            fi ;;
        *) 
            echo "[ERROR] Unsupported archive format" >&2
            echo "FAILED: Extraction of $(basename "$archive") - unsupported format" >> "$report_file"
            return 1 ;;
    esac
}

# Function to generate a summary report
generate_summary_report() {
    local report_file="$SCRIPT_DIR/../init_report.txt"
    
    echo "========================================"
    echo "cBioPortal Initialization Summary Report"
    echo "========================================"
    echo "Generated at: $(date)"
    echo ""
    
    if [ -f "$report_file" ]; then
        echo "Operation Summary:"
        echo "-----------------"
        grep "SUCCESS:" "$report_file" | wc -l | xargs echo "Total successful operations:"
        grep "FAILED:" "$report_file" | wc -l | xargs echo "Total failed operations:"
        echo ""
        
        if grep -q "FAILED:" "$report_file"; then
            echo "Failed Operations:"
            echo "-----------------"
            grep "FAILED:" "$report_file"
            echo ""
        fi
        
        echo "Details:"
        echo "--------"
        cat "$report_file"
    else
        echo "No operations recorded"
    fi
}

# Initialize report file
init_report() {
    local report_file="$SCRIPT_DIR/../init_report.txt"
    echo "# cBioPortal Initialization Report - $(date)" > "$report_file"
    echo "# ====================================" >> "$report_file"
    echo "" >> "$report_file"
}

# Make sure the report file exists
if [ ! -f "$SCRIPT_DIR/../init_report.txt" ]; then
    init_report
fi