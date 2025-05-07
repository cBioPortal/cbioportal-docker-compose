#!/usr/bin/env bash

# Function to download files with retries
# Usage: download_with_retry URL DESTINATION MAX_RETRIES RETRY_DELAY
download_with_retry() {
    local url="$1"
    local destination="$2"
    local max_retries="${3:-3}" 
    local retry_delay="${4:-10}" 
    local attempt=1
    local http_code=0
    
    echo "[INFO] Downloading $url to $destination (max $max_retries attempts)"
    
    while [ $attempt -le $max_retries ]; do
        echo "[INFO] Download attempt $attempt of $max_retries"
        
       
        if wget --spider --server-response "$url" 2>&1 | grep -q "200 OK"; then
            if wget --no-verbose --continue --timeout=30 -O "$destination" "$url"; then
                echo "[SUCCESS] Download completed successfully on attempt $attempt"
                return 0
            fi
        else
            echo "[WARNING] URL not accessible or returned non-200 status"
        fi
        
        attempt=$((attempt + 1))
        if [ $attempt -le $max_retries ]; then
            echo "[INFO] Retrying download in $retry_delay seconds..."
            sleep $retry_delay
        else
            echo "[ERROR] Failed to download after $max_retries attempts" >&2
            return 1
        fi
    done
}

# Function to extract archives with validation
# Usage: extract_with_validation ARCHIVE_PATH EXTRACT_DIR
extract_with_validation() {
    local archive="$1"
    local extract_dir="$2"
    
    echo "[INFO] Extracting $archive to $extract_dir"
    
    
    if [ ! -s "$archive" ]; then
        echo "[ERROR] Archive $archive does not exist or is empty" >&2
        return 1
    fi
    
    
    mkdir -p "$extract_dir"
    
    
    if [[ "$archive" == *.tar.gz ]]; then
        if ! tar xzf "$archive" -C "$extract_dir"; then
            echo "[ERROR] Failed to extract tar.gz archive" >&2
            return 1
        fi
    elif [[ "$archive" == *.zip ]]; then
        if ! unzip -q "$archive" -d "$extract_dir"; then
            echo "[ERROR] Failed to extract zip archive" >&2
            return 1
        fi
    else
        echo "[ERROR] Unsupported archive format" >&2
        return 1
    fi
    
    echo "[SUCCESS] Extraction completed successfully"
    return 0
}
