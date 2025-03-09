#!/usr/bin/env bash

# Enable strict error handling
set -eo pipefail
if [ "${DEBUG_MODE}" = "true" ]; then
    set -x
fi

PS4='+ $(date "+%Y-%m-%d %H:%M:%S") : '

# Initialize debug log
DEBUG_LOG="debug_$(date +%Y%m%d%H%M%S).log"
exec > >(tee -a "$DEBUG_LOG") 2>&1

echo "=== Starting initialization at $(date) ==="

for d in config study data; do
    echo "▶ Entering directory: $d"
    if [ ! -f "$d/init.sh" ]; then
        echo " Error: Missing $d/init.sh" >&2
        exit 1
    fi
    
    # Ensure execute permissions
    chmod +x "$d/init.sh" || {
        echo " Failed to set execute permissions on $d/init.sh" >&2
        exit 2
    }

    # Execute the subdirectory's init.sh script
    if ! cd "$d"; then
        echo " Failed to enter directory $d" >&2 
        exit 3
    fi
    
    echo "⚙️ Running init.sh in $d"
    if ! ./init.sh; then
        echo " Critical failure in $d/init.sh" >&2
        exit 4
    fi
    
    cd ..
done

echo "=== Initialization completed successfully at $(date) ==="
