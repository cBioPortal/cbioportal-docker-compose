#!/usr/bin/env bash


set -eo pipefail
if [ "${DEBUG_MODE}" = "true" ]; then
    set -x
fi

PS4='+ $(date "+%Y-%m-%d %H:%M:%S") : '


DEBUG_LOG="debug_$(date +%Y%m%d%H%M%S).log"
exec > >(tee -a "$DEBUG_LOG") 2>&1

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

# Source utility functions
source "$SCRIPT_DIR/utils.sh"


init_report

echo "=== Starting initialization at $(date) ==="

for d in config study data; do
    echo " Entering directory: $d"
    if [ ! -f "$d/init.sh" ]; then
        echo " Error: Missing $d/init.sh" >&2
        echo "FAILED: Missing $d/init.sh script" >> "$SCRIPT_DIR/init_report.txt"
        exit 1
    fi
    
    # Ensure execute permissions
    chmod +x "$d/init.sh" || {
        echo " Failed to set execute permissions on $d/init.sh" >&2
        echo "FAILED: Setting permissions on $d/init.sh" >> "$SCRIPT_DIR/init_report.txt"
        exit 2
    }

    # Execute the subdirectory's init.sh script
    if ! cd "$d"; then
        echo " Failed to enter directory $d" >&2
        echo "FAILED: Changing to directory $d" >> "$SCRIPT_DIR/init_report.txt"
        exit 3
    fi
    
    echo " Running init.sh in $d"
    start_time=$(date +%s)
    if ! ./init.sh; then
        echo " Critical failure in $d/init.sh" >&2
        echo "FAILED: Executing $d/init.sh" >> "$SCRIPT_DIR/../init_report.txt"
        exit 4
    fi
    end_time=$(date +%s)
    duration=$((end_time - start_time))
    echo "SUCCESS: Executed $d/init.sh (took ${duration}s)" >> "$SCRIPT_DIR/../init_report.txt"
    
    cd ..
done

echo "=== Initialization completed successfully at $(date) ==="


generate_summary_report | tee "init_summary_$(date +%Y%m%d%H%M%S).txt"