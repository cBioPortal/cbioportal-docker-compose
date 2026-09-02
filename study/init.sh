#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

# Clone cbioportal repo (shallow) and pull study_es_0 and genesets from it
CBIO_REPO="${SCRIPT_DIR}/cbioportal"
trap 'rm -rf "$CBIO_REPO"' EXIT
git clone --depth 1 https://github.com/cBioPortal/cbioportal.git "$CBIO_REPO"
rm -rf "${SCRIPT_DIR}/study_es_0"
cp -r "$CBIO_REPO/test/test_data/study_es_0" "${SCRIPT_DIR}/study_es_0"

# Download datahub studies
DATAHUB_STUDIES="${DATAHUB_STUDIES:-lgg_ucsf_2014 msk_impact_2017 msk_spectrum_tme_2022}"
for study in ${DATAHUB_STUDIES}; do
    curl -fL -o "${study}.tar.gz" "https://datahub.assets.cbioportal.org/${study}.tar.gz"
    tar xfz "${study}.tar.gz"
    rm "${study}.tar.gz"

    # The release gate treats an omitted mutation filter as a dangerous
    # default: cBioPortal silently drops non-coding classifications in that
    # mode.  Keep the complete MSK-IMPACT source snapshot explicit so a fresh
    # stack imports every source mutation row and the verifier can enforce it.
    if [ "${study}" = "msk_impact_2017" ] \
        && [ -f "${SCRIPT_DIR}/${study}/meta_mutations.txt" ] \
        && ! grep -q '^variant_classification_filter:' "${SCRIPT_DIR}/${study}/meta_mutations.txt"; then
        printf '\nvariant_classification_filter: __NONE__\n' \
            >> "${SCRIPT_DIR}/${study}/meta_mutations.txt"
    fi
done

# Collect gene panel reference data
mkdir -p "${SCRIPT_DIR}/reference_data"

# Copy test panels bundled with study_es_0
cp "${SCRIPT_DIR}/study_es_0/data_gene_panel_testpanel1.txt" "${SCRIPT_DIR}/reference_data/"
cp "${SCRIPT_DIR}/study_es_0/data_gene_panel_testpanel2.txt" "${SCRIPT_DIR}/reference_data/"

# Download IMPACT panels from datahub
PANEL_BASE="https://media.githubusercontent.com/media/cBioPortal/datahub/refs/heads/master/reference_data/gene_panels"
for panel in data_gene_panel_impact341.txt data_gene_panel_impact410.txt; do
    curl -fL -o "${SCRIPT_DIR}/reference_data/${panel}" "${PANEL_BASE}/${panel}"
done

# Copy genesets from cloned repo
cp "$CBIO_REPO/test/test_data/genesets/"* "${SCRIPT_DIR}/reference_data/"
