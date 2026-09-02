#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_ENV=(
  AWS_ENDPOINT_URL=http://ecs.example.invalid:9020
  AWS_ACCESS_KEY_ID=test-access-key
  AWS_SECRET_ACCESS_KEY=test-secret-key
  WSI_AUTH_SECRET=test-wsi-capability-secret
  WSI_ALLOWED_SOURCE_PREFIXES=s3://test-slides/
  WSI_ALLOWED_THUMBNAIL_PREFIXES=s3://test-thumbnails/
  SLIDE_VIEWER_IMAGE=cbioportal/slide-viewer:test
  SLIDE_VIEWER_REDIS_PASSWORD=test-redis-password
  DOCKER_IMAGE_MYSQL=mysql:8.0
)

render_config() {
  local output_file="$1"
  shift
  (
    cd "$ROOT_DIR"
    env "${COMPOSE_ENV[@]}" docker compose "$@" config >"$output_file"
  )
}

assert_contains() {
  local file="$1"
  local expected="$2"
  if ! grep -Fq -- "$expected" "$file"; then
    echo "Compose config is missing: $expected" >&2
    return 1
  fi
}

authenticated_config="$(mktemp)"
development_config="$(mktemp)"
trap 'rm -f "$authenticated_config" "$development_config"' EXIT

render_config "$authenticated_config" \
  -f docker-compose.yml \
  -f dev/keycloak/keycloak.yml \
  -f addon/slide-viewer/docker-compose.slide-viewer.yml \
  -f addon/wsi-nginx/docker-compose.wsi-nginx.yml
assert_contains "$authenticated_config" --authenticate=saml
assert_contains "$authenticated_config" "WSI_LOCAL_AUTH_BYPASS: \"false\""
assert_contains "$authenticated_config" "WSI_ACCESS_TOKEN_SECRET: test-wsi-capability-secret"
assert_contains "$authenticated_config" "WSI_AUTH_SECRET: test-wsi-capability-secret"
assert_contains "$authenticated_config" "WSI_ALLOWED_SOURCE_PREFIXES: s3://test-slides/"
assert_contains "$authenticated_config" "WSI_ALLOWED_THUMBNAIL_PREFIXES: s3://test-thumbnails/"
assert_contains "$authenticated_config" "/etc/clickhouse-server/users.d/user_settings.xml"

render_config "$development_config" \
  -f docker-compose.yml \
  -f addon/slide-viewer/docker-compose.slide-viewer.yml \
  -f addon/slide-viewer/docker-compose.slide-viewer.dev.yml \
  -f addon/wsi-nginx/docker-compose.wsi-nginx.yml
assert_contains "$development_config" --authenticate=false
assert_contains "$development_config" "WSI_LOCAL_AUTH_BYPASS: \"true\""
assert_contains "$development_config" "WSI_ALLOWED_SOURCE_PREFIXES: s3://test-slides/"
assert_contains "$development_config" "/etc/clickhouse-server/users.d/user_settings.xml"

echo "WSI Compose authenticated and development profiles are valid"
