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

For documentation and usage instructions, see here: https://docs.cbioportal.org/deployment/docker/
