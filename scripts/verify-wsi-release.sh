#!/usr/bin/env bash
set -euo pipefail

# Complete post-import gate for a WSI study.  The Python verifier is kept as
# the single source of truth; this wrapper supplies the flags that are easy to
# omit when doing a manual smoke test.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'USAGE'
Usage: scripts/verify-wsi-release.sh

Required environment:
  STUDY_ID       imported study identifier
  STUDY_DIR      source study directory (defaults to study/$STUDY_ID)

Optional environment:
  PORTAL_URL             portal base URL (default: http://localhost:8080)
  TIMELINE_DIR           pathology timeline directory (default: STUDY_DIR)
  CLICKHOUSE_CONTAINER   ClickHouse container (default: cbioportal-database-container)
  CLICKHOUSE_USER        ClickHouse user (default: cbio_user)
  CLICKHOUSE_DB          ClickHouse database (default: cbioportal)
  EXPECTED_WSI_TILE_SERVER_URL  optional assertion for the portal-advertised tile URL
  WSI_TILE_SERVER_URL            deprecated alias for EXPECTED_WSI_TILE_SERVER_URL
  WSI_SAMPLE_SIZE                servable slide sample size (default: 3)
  WSI_PATIENT_ID         target one patient instead of the whole hierarchy
  VERIFY_ALL_TILES       set to 1 to request a tile for every servable slide
  VERIFY_HTTP_TIMEOUT_SECONDS  portal API timeout (default: 120)
  VERIFY_COOKIE           short-lived portal session cookie for authenticated checks
  CLICKHOUSE_PASSWORD    ClickHouse password (read by the verifier, never echoed)
USAGE
  exit 0
fi

study_id="${STUDY_ID:-}"
if [[ -z "$study_id" ]]; then
  echo "STUDY_ID is required" >&2
  exit 2
fi

study_dir="${STUDY_DIR:-$ROOT_DIR/study/$study_id}"
timeline_dir="${TIMELINE_DIR:-$study_dir}"
portal_url="${PORTAL_URL:-http://localhost:8080}"
clickhouse_container="${CLICKHOUSE_CONTAINER:-cbioportal-database-container}"
clickhouse_user="${CLICKHOUSE_USER:-cbio_user}"
clickhouse_db="${CLICKHOUSE_DB:-cbioportal}"
expected_tile_url="${EXPECTED_WSI_TILE_SERVER_URL:-${WSI_TILE_SERVER_URL:-}}"
wsi_sample_size="${WSI_SAMPLE_SIZE:-3}"

args=(
  --portal-url "$portal_url"
  --study-id "$study_id"
  --study-dir "$study_dir"
  --timeline-dir "$timeline_dir"
  --clickhouse-container "$clickhouse_container"
  --clickhouse-user "$clickhouse_user"
  --clickhouse-database "$clickhouse_db"
  --check-study-view
  --check-timeline
  --require-wsi
  --check-all-wsi
  --check-all-access
  --check-wsi-clinical-counts
  --check-all-data
  --expected-tile-url "$expected_tile_url"
  --wsi-sample-size "$wsi_sample_size"
)

if [[ -n "${WSI_PATIENT_ID:-}" ]]; then
  args+=(--wsi-patient-id "$WSI_PATIENT_ID")
fi
if [[ "${VERIFY_ALL_TILES:-0}" == "1" ]]; then
  args+=(--check-all-tiles)
fi

exec python3 "$ROOT_DIR/scripts/verify-study-load.py" "${args[@]}"
