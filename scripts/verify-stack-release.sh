#!/usr/bin/env bash
set -euo pipefail

# Catalog-wide post-start acceptance gate. This is the command that may report
# a WSI stack as accepted; container health checks alone are intentionally not
# sufficient.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'USAGE'
Usage: scripts/verify-stack-release.sh

Required environment:
  STACK_STUDY_MANIFEST       host-local JSON manifest of every admitted study
  CLICKHOUSE_CONTAINER       running ClickHouse container name

Optional environment:
  PORTAL_URL                 browser-reachable portal URL (default: http://localhost:8080)
  CLICKHOUSE_USER            ClickHouse user (default: cbio_user)
  CLICKHOUSE_DB              ClickHouse database (default: cbioportal)
  EXPECTED_WSI_TILE_SERVER_URL  optional assertion for portal tile configuration
  WSI_TILE_SERVER_URL        deprecated alias for EXPECTED_WSI_TILE_SERVER_URL
  WSI_SAMPLE_SIZE            real servable slides per study (default: 3)
  TIMELINE_PATIENT_SAMPLE    event-bearing patients checked per study (default: 24)
  VERIFY_ALL_TILES           set to 1 to validate every slide's pixel path
  VERIFY_STUDY_TIMEOUT_SECONDS  per-study timeout (default: 1800)
  VERIFY_COOKIE              short-lived portal session cookie
  CLICKHOUSE_PASSWORD        ClickHouse password; never echoed

The manifest must use version 1 and contain one entry per study, with
study_id and study_dir. Every entry must contain meta_wsi.txt and a valid
wsi_snapshot_manifest.json with non-zero association, servable, and patient
counts and incomplete_asset_count=0. Studies without a complete WSI asset
contract are rejected.
USAGE
  exit 0
fi

manifest="${STACK_STUDY_MANIFEST:-}"
if [[ -z "$manifest" ]]; then
  echo "STACK_STUDY_MANIFEST is required" >&2
  exit 2
fi
clickhouse_container="${CLICKHOUSE_CONTAINER:-}"
if [[ -z "$clickhouse_container" ]]; then
  echo "CLICKHOUSE_CONTAINER is required" >&2
  exit 2
fi

expected_tile_url="${EXPECTED_WSI_TILE_SERVER_URL:-${WSI_TILE_SERVER_URL:-}}"

args=(
  --manifest "$manifest"
  --portal-url "${PORTAL_URL:-http://localhost:8080}"
  --clickhouse-container "$clickhouse_container"
  --clickhouse-user "${CLICKHOUSE_USER:-cbio_user}"
  --clickhouse-database "${CLICKHOUSE_DB:-cbioportal}"
  --expected-tile-url "$expected_tile_url"
  --wsi-sample-size "${WSI_SAMPLE_SIZE:-3}"
  --study-timeout-seconds "${VERIFY_STUDY_TIMEOUT_SECONDS:-1800}"
)
if [[ -n "${VERIFY_COOKIE:-}" ]]; then
  args+=(--cookie "$VERIFY_COOKIE")
fi
if [[ "${VERIFY_ALL_TILES:-0}" == "1" ]]; then
  args+=(--all-tiles)
fi
args+=(--timeline-patient-sample "${TIMELINE_PATIENT_SAMPLE:-24}")

exec python3 "$ROOT_DIR/scripts/verify-stack-release.py" "${args[@]}"
