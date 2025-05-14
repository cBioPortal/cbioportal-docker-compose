#!/usr/bin/env bash


set -eo pipefail
if [ "${DEBUG_MODE}" = "true" ]; then
    set -x
fi


SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"


DATAHUB_STUDIES="${DATAHUB_STUDIES:-lgg_ucsf_2014 msk_impact_2017}"

# Base URL for downloading studies
DATAHUB_BASE_URL="https://cbioportal-datahub.s3.amazonaws.com"


for study in ${DATAHUB_STUDIES}; do
    echo " Processing study: $study"

   
    STUDY_ARCHIVE="${SCRIPT_DIR}/${study}.tar.gz"
    STUDY_DIR="${SCRIPT_DIR}/${study}"

    
    if [ -f "$STUDY_ARCHIVE" ]; then
        echo " Archive already exists: $STUDY_ARCHIVE"
    else
        # Download the study archive
        echo "⬇ Downloading $study from $DATAHUB_BASE_URL"
        if ! wget -O "$STUDY_ARCHIVE" "${DATAHUB_BASE_URL}/${study}.tar.gz"; then
            echo " Error: Failed to download ${study}.tar.gz from $DATAHUB_BASE_URL" >&2
            exit 1
        fi
        echo " Download completed: $STUDY_ARCHIVE"
    fi

    # Extract the archive if it hasn't been extracted yet
    if [ -d "$STUDY_DIR" ]; then
        echo " Study directory already exists: $STUDY_DIR"
    else
        echo " Extracting $STUDY_ARCHIVE to $STUDY_DIR"
        if ! tar xvfz "$STUDY_ARCHIVE" -C "$SCRIPT_DIR"; then
            echo " Error: Failed to extract $STUDY_ARCHIVE" >&2
            exit 2
        fi
        echo " Extraction completed: $STUDY_DIR"
    fi

done

echo "=== All studies processed successfully ==="
