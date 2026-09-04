# Run cBioPortal using Docker Compose

Welcome to the cBioPortal Docker Compose repository!

## Shared WSI nginx rehearsal

When the frontend dev server is running on the host at `:3000`, start the
browser-visible nginx origin and the Compose-backed WSI services with:

```bash
docker compose -f docker-compose.yml \
  -f dev/keycloak/keycloak.yml \
  -f addon/slide-viewer/docker-compose.slide-viewer.yml \
  -f addon/wsi-nginx/docker-compose.wsi-nginx.yml up -d keycloak wsi-nginx
```

The standard overlay is fail-closed: it requires the cBioPortal/Keycloak
authentication setup and a Redis password. For an intentionally anonymous,
local-only rehearsal, add the explicit development override:

```bash
docker compose -f docker-compose.yml \
  -f addon/slide-viewer/docker-compose.slide-viewer.yml \
  -f addon/slide-viewer/docker-compose.slide-viewer.dev.yml \
  -f addon/wsi-nginx/docker-compose.wsi-nginx.yml up -d wsi-nginx
```

The development override binds the tile service to `0.0.0.0:8081` by default,
because direct WSI mode derives the endpoint from the browser hostname. Set
`WSI_BIND_ADDRESS=127.0.0.1` when the rehearsal is browser-local, or set an
explicit host address when the browser is remote.
Set `SLIDE_VIEWER_REDIS_PASSWORD` in the local environment for both modes.
The dev override also mounts the tile-server checkout's read-only
`tests/testdata` directory at `/app/testdata` and enables local `file://`
sources only for those fixtures. Production and the standard overlay remain
S3-only; use `WSI_TESTDATA_DIR` to point a local rehearsal at another fixture
directory.
Production images should be resolved to registry digests during release review;
the tile-server image is supplied through `SLIDE_VIEWER_IMAGE`.

The rehearsal origin is `http://<host>:3001`. Set `WSI_RUNTIME_MODE=proxied`
when starting the frontend so its WSI URLs use that origin. nginx routes
`/wsi/*` to the Compose tile server, `/api/*` to cBioPortal, and all other
paths to the frontend. Access logs are available in the `wsi-nginx-logs`
volume.

This rehearsal listens on HTTP. For HTTPS, put the nginx container behind a
TLS-terminating development load balancer or add a separately managed
certificate overlay.

## WSI data-preparation boundary

Compose runs the portal, tile server, Redis, and optional nginx rehearsal. It
does not run the production thumbnail publication or Databricks jobs. Before a
WSI release is imported, a separate cron, Slurm, or equivalent scheduled
process must run the tile-server thumbnail batch, write master JPEGs to the
S3/Dell ECS-compatible store, and populate
`cdsi_prod.pathology_data_mining.slide_thumbnail_registry` with the artifact
URI, `tile_metadata_json`, dimensions, and content type. The production
Databricks WSI bundle is maintained in
[`pdm_databricks_pipelines`](https://github.com/pathology-data-mining/pdm_databricks_pipelines/tree/main/pathology_data_mining/wsi_summary)
and runs the `wsi_summary_job`; its refresh must wait for the thumbnail job's
completion watermark, and the
standard cBioPortal core `metaImport.py` flow must then import the complete
study-file snapshot.

The frontend and online tile server are read-only and do not generate or
upload thumbnails. The Compose overlay supplies the shared WSI capability
secret to the portal and tile server, but it does not replace the upstream
artifact batch.

After importing a release, run the catalog-wide acceptance gate from the stack
host before testing it in the browser. Container health checks only prove that
processes are running; this gate proves that the portal catalog and every
admitted study are complete and that real browser pixel requests work.

Create a host-local manifest from the exact snapshot directories used by the
import. Start with [`stack-release-manifest.example.json`](stack-release-manifest.example.json).
Each entry must describe one and only one study in the running portal. Its
snapshot must contain `meta_wsi.txt`, `data_wsi.txt`,
`wsi_snapshot_manifest.json`, and a valid `data_filename` for every other
`meta_*.txt` declaration. A WSI release must include the generated pathology
timeline metadata/data pair; a snapshot that contains slides but no timeline
pair is rejected rather than imported with an empty clinical-event view.
The WSI snapshot manifest must also report `incomplete_asset_count: 0` and
`filtered_row_count: 0`.
The Databricks exporter fails closed when the canonical table says a slide is
servable but the thumbnail registry is missing source, thumbnail, or tile
metadata. Explicitly non-servable associations—including matched BLOCK/PART
rows with no inventory-backed source—remain in the WSI hierarchy with empty
pixel fields so the pathology provenance and timeline counts are complete.

Run the gate on the stack host, where the portal and ClickHouse containers are
reachable:

```bash
STACK_STUDY_MANIFEST=/path/to/release-manifest.json \
PORTAL_URL=http://localhost:8080 \
CLICKHOUSE_CONTAINER=cbioportal-database-container \
EXPECTED_WSI_TILE_SERVER_URL=http://localhost:8081 \
scripts/verify-stack-release.sh
```

The gate requires an exact catalog/manifest match, checks every patient
hierarchy and every slide association, compares WSI clinical counts with
ClickHouse, and samples three real servable slides per study (early, middle,
late; preferring distinct patients) through access, thumbnail, and tile
requests. Set `VERIFY_ALL_TILES=1` for a pixel request for every servable
slide. The portal's live `config_service` tile URL is authoritative; the
expected URL is only an optional deployment assertion. Cross-origin requests
also require a matching CORS preflight for the portal origin.

For a focused diagnosis of one study, use the per-study wrapper. It enables
the complete study, timeline, hierarchy, access-bundle, clinical-count, and
source-versus-ClickHouse checks together:

```bash
STUDY_ID=<study_id> \
STUDY_DIR=/releases/<study_id> \
PORTAL_URL=http://localhost:8080 \
CLICKHOUSE_CONTAINER=cbioportal-database-container \
EXPECTED_WSI_TILE_SERVER_URL=http://localhost:8081 \
scripts/verify-wsi-release.sh
```

The lower-level command remains useful for a smaller smoke check or for
passing explicit expected counts:

```bash
python3 scripts/verify-study-load.py \
  --portal-url http://localhost:8080 \
  --study-id <study_id> \
  --study-dir study/<study_id> \
  --timeline-dir study/<study_id> \
  --clickhouse-container cbioportal-database-container \
  --check-study-view \
  --check-timeline \
  --require-wsi --check-all-wsi --check-all-access \
  --check-wsi-clinical-counts \
  --expected-tile-url http://localhost:8081
```

For a complete study release, add `--check-all-data`. It requires both
`--study-dir` and `--clickhouse-container` and compares the source snapshot
with ClickHouse for clinical patients/samples, every mutation row, discrete CNA
events, structural variants, copy-number segments, and every gene-panel
mapping. The mutation meta file must explicitly set
`variant_classification_filter: __NONE__` to require all source mutations (or
list intentional exclusions). It also verifies that all mutation/CNA symbols
resolve through the canonical gene or alias seed and that no
structural-variant row has both genes unresolved. A successful importer process
or a healthy HTTP endpoint is not a completeness check; use this flag as the
release gate:

```bash
python3 scripts/verify-study-load.py \
  --portal-url http://localhost:8080 \
  --study-id <study_id> \
  --study-dir study/<study_id> \
  --clickhouse-container cbioportal-database-container \
  --check-study-view --check-all-data
```

For an authenticated deployment, provide a short-lived portal session cookie
with `--cookie` (or `VERIFY_COOKIE`) for the hierarchy and access checks. The
command exits non-zero on a missing catalog entry, empty WSI hierarchy, invalid
snapshot manifest, incomplete access bundle, or failed thumbnail request; it
also compares the imported ClickHouse WSI row/servable counts when
`--clickhouse-container` is supplied. `--check-study-view` additionally catches
an import where raw tables are populated but ClickHouse derived tables were not
rebuilt. `--check-all-wsi` compares every patient hierarchy and slide to the
snapshot; `--check-all-access` validates every servable slide's access bundle
and thumbnail request. Add `--check-all-tiles` to issue an authenticated tile
request for every servable slide as well; this is intentionally opt-in because
it can be expensive for large remote slides. For a large study, combine it
with `--max-tile-checks N` to retain full hierarchy/access/thumbnail coverage
while issuing tile requests for only the first N servable slides. `--check-timeline` validates
pathology event counts and linkouts. When `--wsi-patient-id` is supplied with a
WSI snapshot, it also requires every slide for that patient to be represented
in the timeline. When `--check-all-wsi` or `--wsi-patient-id` is used with
`--check-timeline`, every timeline linkout is resolved against the live
hierarchy and its `IMAGE_COUNT`/`NON_SERVABLE_IMAGE_COUNT` values are checked
against `canServeTiles`; a linkout for a wholly non-servable group fails the
release gate.
`--check-wsi-clinical-counts` verifies the
sample- and patient-level attributes in ClickHouse and confirms the portal
clinical-data API exposes patient-level WSI values used to populate the Study
View WSI columns. Set `CLICKHOUSE_PASSWORD` in the environment rather than
putting it in a command or checked-in file. The check does not print source
URLs, slide identifiers, or tokens; an explicitly requested
`--wsi-patient-id` is echoed in the summary so the targeted result is
unambiguous.

### Databricks-to-portal E2E gate

The local release verifier accepts a study snapshot, but that alone cannot
prove that the snapshot came from the current Databricks tables. Run the
Databricks-backed gate when the stack and a read-only Databricks identity are
available:

```bash
STUDY_ID=mskimpact \
STUDY_DIR=/path/to/study/mskimpact \
PORTAL_URL=http://localhost:19290 \
CLICKHOUSE_CONTAINER=codex-wsi-full-clickhouse-1 \
EXPECTED_WSI_TILE_SERVER_URL=http://localhost:19391 \
scripts/verify-databricks-wsi-e2e.sh
```

This command stages the study with hard links, invokes
`export_databricks_wsi_snapshot.py` against the configured Databricks SQL
warehouse and canonical/thumbnail tables, validates the Databricks manifest,
and then runs the portal, ClickHouse, WSI hierarchy, clinical-count,
access-bundle, thumbnail, and tile checks against that exact staged snapshot.
The source study directory and Databricks tables are never modified. The
default run checks every patient hierarchy and three real slides; set
`VERIFY_ALL_ACCESS=1` for every servable access bundle and
`VERIFY_ALL_TILES=1` for a tile request for each of them. Set
`KEEP_E2E_STAGE=1` to retain the generated snapshot for diagnosis.

The exporter uses `WSI_ALLOWED_SOURCE_PREFIXES` as its S3 source policy. Set it
to the same comma-separated prefixes configured on the tile server (including
approved `s3://pathology/.../` prefixes when applicable); it does not assume
that every valid slide is under the reef prefix. Individual prefixes can also
be supplied with repeated `--allowed-source-prefix` arguments when invoking
the exporter directly.

For an already-materialized study whose WSI and timeline jobs were run
separately, `scripts/reconcile_pathology_timeline_capabilities.py` can repair
the timeline from the final `data_wsi.txt` contract before re-importing it.
Use `--check-only` first; unresolved linkouts fail closed by default. The
`--unresolved-as-non-servable` option is an explicit repair-mode choice that
removes those unusable links and preserves their counts as non-servable.
If an old timeline contains associations absent from the final hierarchy,
use `--drop-unresolved` instead so those phantom events are omitted rather
than inflating the timeline beyond the WSI snapshot.

Use `--wsi-patient-id <patient_id>` with `--study-dir` to target a specific
patient when investigating a missing-slide report; the hierarchy and access
smoke checks then run against that patient instead of an arbitrary servable
patient. Combine it with `--check-all-access` (and optionally
`--check-all-tiles`) to validate every slide for that patient without running
the expensive whole-study check.

### Deployed-bundle browser gate

After the stack-host acceptance gate passes, run the browser smoke from the
same host (or another host that can read the release manifest). It runs one
test per manifest study, derives a servable patient from each WSI snapshot,
opens the real portal route without a `resourceUrl`, and requires hierarchy,
access, thumbnail, and native tile traffic from the configured tile origin:

```bash
cd /path/to/cbioportal-frontend/end-to-end-test-playwright
WSI_DEPLOYMENT_SMOKE=1 LOCALDEV=0 \
CBIOPORTAL_URL=http://localhost:8080 \
STACK_STUDY_MANIFEST=/path/to/release-manifest.json \
PW_SUITE=wsi pnpm exec playwright test tests/wsi-deployment-smoke.spec.ts
```

If the deployed bundle or its configured `frontendUrl` is unreachable, the
test fails with the failed asset and page-error details instead of reporting a
healthy-but-empty viewer. Use `WSI_STUDY_ID` and `WSI_PATIENT_ID` only for a
focused diagnosis when a full manifest run is not appropriate.

For documentation and usage instructions, see here: https://docs.cbioportal.org/deployment/docker/
