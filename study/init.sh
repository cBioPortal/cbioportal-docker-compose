#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
DATAHUB_STUDIES="${DATAHUB_STUDIES:-lgg_ucsf_2014 msk_impact_2017}"

if ! git lfs version &>/dev/null; then
    echo "Error: git-lfs is not installed. See https://git-lfs.com" >&2
    exit 1
fi

DATAHUB_DIR="${SCRIPT_DIR}/.datahub"

GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 --filter=blob:none --sparse \
    https://github.com/cBioPortal/datahub.git "${DATAHUB_DIR}"

cd "${DATAHUB_DIR}"
git sparse-checkout set $(for s in ${DATAHUB_STUDIES}; do echo "public/$s"; done)
git lfs pull

for study in ${DATAHUB_STUDIES}; do
    cp -r "public/${study}" "${SCRIPT_DIR}/"
done

cd "${SCRIPT_DIR}"
rm -rf "${DATAHUB_DIR}"
