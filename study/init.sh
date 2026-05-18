#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

# Pull study_es_0 out of the cBioPortal image
VERSION=$(grep DOCKER_IMAGE_CBIOPORTAL "${SCRIPT_DIR}/../.env" | tail -n 1 | cut -d '=' -f 2-)
CONTAINER=$(docker create "$VERSION")
trap 'docker rm $CONTAINER' EXIT
docker cp "$CONTAINER:/cbioportal/test/study_es_0" "${SCRIPT_DIR}/study_es_0"

# Download datahub studies
DATAHUB_STUDIES="${DATAHUB_STUDIES:-lgg_ucsf_2014 msk_impact_2017}"
for study in ${DATAHUB_STUDIES}; do
    curl -fL -o "${study}.tar.gz" "https://datahub.assets.cbioportal.org/${study}.tar.gz"
    tar xfz "${study}.tar.gz"
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

# Download genesets for study_es_0
GENESET_BASE="https://raw.githubusercontent.com/cBioPortal/cbioportal-core/refs/heads/main/src/test/resources/genesets"
for f in study_es_0_genesets.gmt study_es_0_tree.yaml study_es_0_supp-genesets.txt; do
    curl -fL -o "${SCRIPT_DIR}/reference_data/${f}" "${GENESET_BASE}/${f}"
done
