#!/usr/bin/env bash
set -euo pipefail  

LOG_FILE="setup.log"
echo "Starting initialization..." | tee "$LOG_FILE"

for d in config study data; do
    if [[ -d "$d" ]]; then
        echo "Entering directory: $d" | tee -a "$LOG_FILE"
        cd "$d"

        if [[ -x "./init.sh" ]]; then
            ./init.sh 2>&1 | tee -a "../$LOG_FILE"
        else
            echo "Error: init.sh not found or not executable in $d" | tee -a "../$LOG_FILE"
            exit 1
        fi

        cd ..
    else
        echo "Error: Directory $d not found!" | tee -a "$LOG_FILE"
        exit 1
    fi
done

echo "Initialization completed successfully!" | tee -a "$LOG_FILE"
