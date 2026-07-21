# Run cBioPortal using Docker Compose

Welcome to the cBioPortal Docker Compose repository!

## Shared WSI nginx rehearsal

When the frontend dev server is running on the host at `:3000` and the slide
viewer is running at `:8081`, start the browser-visible nginx container with:

```bash
docker compose -f docker-compose.yml \
  -f addon/slide-viewer/docker-compose.slide-viewer.yml \
  -f addon/wsi-nginx/docker-compose.wsi-nginx.yml up -d wsi-nginx
```

The rehearsal origin is `http://<host>:3001`. Set `WSI_RUNTIME_MODE=proxied`
when starting the frontend so its WSI URLs use that origin. nginx routes
`/wsi/*` to the tile server and sends all other paths to the frontend. The
tile server exposes its existing API under this namespace. Access logs are
available in the `wsi-nginx-logs` volume.

This rehearsal listens on HTTP. For HTTPS, put the nginx container behind a
TLS-terminating development load balancer or add a separately managed
certificate overlay.

For documentation and usage instructions, see here: https://docs.cbioportal.org/deployment/docker/
