#!/usr/bin/env bash
set -euo pipefail

# Export the study from Databricks into an isolated staging directory and run
# the complete portal/ClickHouse/WSI release verifier against that exact
# snapshot.  This is intentionally a read-only Databricks integration check:
# it never writes to the Databricks workspace or to the source study directory.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'USAGE'
Usage: scripts/verify-databricks-wsi-e2e.sh

Required environment:
  STUDY_ID                  cBioPortal study identifier
  STUDY_DIR                 source cBioPortal study directory

Stack configuration:
  PORTAL_URL                portal base URL (default: http://localhost:19290)
  CLICKHOUSE_CONTAINER      ClickHouse container (default: codex-wsi-full-clickhouse-1)
  CLICKHOUSE_USER           ClickHouse user (default: cbio_user)
  CLICKHOUSE_DB             ClickHouse database (default: cbioportal)
  EXPECTED_WSI_TILE_SERVER_URL optional assertion for the portal-advertised tile URL
  WSI_TILE_SERVER_URL          deprecated alias for EXPECTED_WSI_TILE_SERVER_URL
  WSI_SAMPLE_SIZE              servable slide sample size (default: 3)
  TIMELINE_PATIENT_SAMPLE      event-bearing patients checked with --check-all-wsi
                                (default: 24; 0 requests every patient)

Databricks configuration:
  DATABRICKS_WAREHOUSE_ID   SQL warehouse (default: exporter default)
  DATABRICKS_TARGET          table target, dev or prod (default: dev)
  DATABRICKS_CANONICAL_TABLE canonical association table (target default)
  DATABRICKS_REGISTRY_TABLE thumbnail registry table (target default)
  DATABRICKS_CONFIG_PROFILE optional SDK profile selected by the environment
  WSI_ALLOWED_SOURCE_PREFIXES comma-separated approved S3 prefixes (defaults
                            to the stack's full tile-server publication list)

Coverage controls:
  VERIFY_ALL_ACCESS         set to 1 to validate every servable access bundle
  VERIFY_ALL_TILES          set to 1 to request tiles for all access bundles
  MAX_TILE_CHECKS            cap tile requests while retaining access coverage
  VERIFY_HTTP_TIMEOUT_SECONDS portal API timeout (default: 120)
  VERIFY_COOKIE              short-lived portal session cookie, if required
  KEEP_E2E_STAGE             set to 1 to retain the temporary snapshot for debugging

The exporter fails closed by default if Databricks marks a row servable while
the thumbnail registry lacks a complete source/thumbnail/tile-metadata
contract. Explicitly non-servable rows remain in the hierarchy as provenance,
including matched rows whose source is not inventory-backed. Use the
exporter's explicit --allow-incomplete-assets flag only for diagnosis; it is
not valid for an accepted study release.

The default run checks every WSI patient hierarchy, a bounded sample of 24
event-bearing patients, and three real access, thumbnail, and tile paths. Set
TIMELINE_PATIENT_SAMPLE=0 only when a complete patient-by-patient event check
is affordable. Set VERIFY_ALL_ACCESS=1 for the expensive complete
access-bundle check; VERIFY_ALL_TILES=1 additionally checks pixel tiles.
USAGE
  exit 0
fi

study_id="${STUDY_ID:-}"
study_dir="${STUDY_DIR:-}"
if [[ -z "$study_id" || -z "$study_dir" ]]; then
  echo "STUDY_ID and STUDY_DIR are required" >&2
  exit 2
fi
if [[ ! -d "$study_dir" ]]; then
  echo "study directory does not exist: $study_dir" >&2
  exit 2
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 2
fi
if ! python3 -c 'import databricks.sdk' >/dev/null 2>&1; then
  echo "the databricks-sdk Python package is required for the Databricks export" >&2
  exit 2
fi

portal_url="${PORTAL_URL:-http://localhost:19290}"
clickhouse_container="${CLICKHOUSE_CONTAINER:-codex-wsi-full-clickhouse-1}"
clickhouse_user="${CLICKHOUSE_USER:-cbio_user}"
clickhouse_db="${CLICKHOUSE_DB:-cbioportal}"
expected_tile_url="${EXPECTED_WSI_TILE_SERVER_URL:-${WSI_TILE_SERVER_URL:-}}"
wsi_sample_size="${WSI_SAMPLE_SIZE:-3}"

# Keep the staging directory beside the study where possible so cp -al can
# hard-link large molecular files instead of copying them.  The fallback copy
# remains safe when the study and temporary directory are on different mounts.
parent_dir="$(cd "$(dirname "$study_dir")" && pwd)"
stage_dir="$(mktemp -d "$parent_dir/.databricks-wsi-e2e.XXXXXX")"
cleanup() {
  if [[ "${KEEP_E2E_STAGE:-0}" == "1" ]]; then
    echo "retained Databricks E2E snapshot: $stage_dir" >&2
    return
  fi
  rm -rf -- "$stage_dir"
}
trap cleanup EXIT

if ! cp -al "$study_dir"/. "$stage_dir"/ 2>/dev/null; then
  # cp -al is an optimization only; do not make cross-filesystem staging a
  # reason to skip the integration test.
  cp -a "$study_dir"/. "$stage_dir"/
fi

export_args=(
  --study-dir "$stage_dir"
  --output-dir "$stage_dir"
)
if [[ -n "${DATABRICKS_WAREHOUSE_ID:-}" ]]; then
  export_args+=(--warehouse-id "$DATABRICKS_WAREHOUSE_ID")
fi

databricks_target="${DATABRICKS_TARGET:-dev}"
case "$databricks_target" in
  dev)
    canonical_default="cdsi_prod.pathology_data_mining_dev.canonical_slide_associations"
    registry_default="cdsi_prod.pathology_data_mining_dev.slide_thumbnail_registry"
    ;;
  prod)
    canonical_default="cdsi_prod.pathology_data_mining.canonical_slide_associations"
    registry_default="cdsi_prod.pathology_data_mining.slide_thumbnail_registry"
    ;;
  *)
    echo "DATABRICKS_TARGET must be dev or prod (got: $databricks_target)" >&2
    exit 2
    ;;
esac
export_args+=(
  --canonical-table "${DATABRICKS_CANONICAL_TABLE:-$canonical_default}"
  --registry-table "${DATABRICKS_REGISTRY_TABLE:-$registry_default}"
)

# Keep the exporter and tile service on the same publication boundary.  The
# explicit list is also used by the rehydration stack; callers can replace it
# for a different deployment, but a bare dev verification must cover all valid
# pathology source prefixes, not only reef-slides.
default_source_prefixes='s3://mskmind-bkt/reef-slides/,s3://mskmind-bkt/reef-slides-reprocess-staging/,s3://mskmind-bkt/reef-slides-reprocess-backup/,s3://mskmind-bkt/reef-slides-reprocess-backups/,s3://mskmind-bkt/reef-slides-remediated/,s3://ocra/,s3://pathology/CRC_21-167/,s3://pathology/BR_20-226/,s3://pathology/NB_16-1335/,s3://pathology/LUNG_18-193/,s3://pathology/CART_19-373/,s3://pathology/BR_16-512/,s3://pathology/MYE_16-1591/,s3://pathology/LUNG_18-193-dev/,s3://pathology/LUNG-HNE/,s3://pathology/LUNG_18-193-dev-2/,s3://pathology/TCGA/,s3://pathology/TCGA-BRCA/,s3://pathology/TCGA-COAD/,s3://pathology/crc-genetic-ancestry/,s3://pathology/TOX_19-114/,s3://pathology/SPECTRUM/,s3://pathology/sample/'
source_prefixes="${WSI_ALLOWED_SOURCE_PREFIXES:-$default_source_prefixes}"
IFS=',' read -r -a source_prefix_array <<< "$source_prefixes"
for source_prefix in "${source_prefix_array[@]}"; do
  [[ -n "$source_prefix" ]] && export_args+=(--allowed-source-prefix "$source_prefix")
done

echo "exporting $study_id WSI associations from Databricks" >&2
python3 "$ROOT_DIR/scripts/export_databricks_wsi_snapshot.py" "${export_args[@]}"

# The exporter writes a manifest whose source is intentionally fixed to the
# de-identified Databricks contract.  Check it explicitly so a future script
# substitution cannot turn this into a local-file-only test.
python3 - "$stage_dir/wsi_snapshot_manifest.json" "$study_id" <<'PY'
import json
import sys

manifest_path, study_id = sys.argv[1:]
with open(manifest_path, encoding="utf-8") as handle:
    manifest = json.load(handle)
if manifest.get("study_id") != study_id:
    raise SystemExit("Databricks snapshot manifest study_id does not match STUDY_ID")
if not str(manifest.get("source", "")).startswith("Databricks "):
    raise SystemExit("snapshot manifest is not marked as a Databricks export")
if int(manifest.get("association_row_count", 0)) <= 0:
    raise SystemExit("Databricks export returned no WSI associations")
if int(manifest.get("timeline_event_count", 0)) <= 0:
    raise SystemExit("Databricks export returned no pathology timeline events")
print(
    "Databricks snapshot: "
    f"{manifest['association_row_count']} rows, "
    f"{manifest.get('servable_row_count', 0)} servable, "
    f"{manifest.get('patient_count', 0)} patients"
)
PY

verify_args=(
  --portal-url "$portal_url"
  --study-id "$study_id"
  --study-dir "$stage_dir"
  --timeline-dir "$stage_dir"
  --clickhouse-container "$clickhouse_container"
  --clickhouse-user "$clickhouse_user"
  --clickhouse-database "$clickhouse_db"
  --check-study-view
  --check-timeline
  --require-wsi
  --check-all-wsi
  --timeline-patient-sample "${TIMELINE_PATIENT_SAMPLE:-24}"
  --check-wsi-clinical-counts
  --check-access
  --expected-tile-url "$expected_tile_url"
  --wsi-sample-size "$wsi_sample_size"
)

if [[ "${VERIFY_ALL_ACCESS:-0}" == "1" ]]; then
  verify_args+=(--check-all-access)
fi
if [[ "${VERIFY_ALL_TILES:-0}" == "1" ]]; then
  # --check-all-tiles requires --check-all-access in the verifier.  Enabling
  # all tiles therefore also enables all access-bundle checks.
  verify_args+=(--check-all-access --check-all-tiles)
fi
if [[ -n "${MAX_TILE_CHECKS:-}" ]]; then
  verify_args+=(--max-tile-checks "$MAX_TILE_CHECKS")
fi

echo "verifying the Databricks snapshot through portal, ClickHouse, and tiles" >&2
python3 "$ROOT_DIR/scripts/verify-study-load.py" "${verify_args[@]}"
echo "Databricks-backed WSI E2E verification passed" >&2
