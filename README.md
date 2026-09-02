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
URI, `tile_metadata_json`, dimensions, and content type. The canonical
Databricks refresh must wait for that job's completion watermark, and the
standard cBioPortal core `metaImport.py` flow must then import the complete
study-file snapshot.

The frontend and online tile server are read-only and do not generate or
upload thumbnails. The Compose overlay supplies the shared WSI capability
secret to the portal and tile server, but it does not replace the upstream
artifact batch.

After importing a study, run the release smoke check before testing it in the
browser. This verifies that the catalog entry is visible and, for WSI studies,
that the hierarchy contains slides and that a real thumbnail can be fetched
through the tile service:

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
  --tile-url http://localhost:8081
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
in the timeline.
`--check-wsi-clinical-counts` verifies the
sample- and patient-level attributes in ClickHouse and confirms the portal
clinical-data API exposes patient-level WSI values used to populate the Study
View WSI columns. Set `CLICKHOUSE_PASSWORD` in the environment rather than
putting it in a command or checked-in file. The check does not print source
URLs, slide identifiers, or tokens; an explicitly requested
`--wsi-patient-id` is echoed in the summary so the targeted result is
unambiguous.
Use `--wsi-patient-id <patient_id>` with `--study-dir` to target a specific
patient when investigating a missing-slide report; the hierarchy and access
smoke checks then run against that patient instead of an arbitrary servable
patient. Combine it with `--check-all-access` (and optionally
`--check-all-tiles`) to validate every slide for that patient without running
the expensive whole-study check.

For documentation and usage instructions, see here: https://docs.cbioportal.org/deployment/docker/
