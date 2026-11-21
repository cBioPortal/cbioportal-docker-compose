# Run cBioPortal using Docker Compose

Welcome to the cBioPortal Docker Compose repository!

For documentation and usage instructions, see here: https://docs.cbioportal.org/deployment/docker/

## Upgrading an existing installation to ClickHouse 26.4

This version moves the bundled ClickHouse from 24.10 to 26.4 and renames all settings in `.env` to
use a `CP_` prefix. An existing `cbioportal_clickhouse_data` volume created with 24.10 is upgraded
in place: ClickHouse 26.4 opens the 24.10 data directory directly, and no reload of studies is needed.

1. **Back up the database volume** (recommended; once 26.4 has run on the volume, going back to
   24.10 is not supported):
   ```bash
   docker compose stop cbioportal-database
   docker run --rm -v <project>_cbioportal_clickhouse_data:/data -v "$PWD":/backup alpine \
       tar czf /backup/clickhouse_24.10_backup.tgz -C /data .
   ```
   `<project>` is your compose project name (by default, the name of this folder).

2. **Carry over your `.env` customizations** to the new variable names. If you never edited `.env`,
   skip this step: the defaults are unchanged.

   | Old variable | New variable |
   |---|---|
   | `DOCKER_IMAGE_CBIOPORTAL` | `CP_DOCKER_IMAGE_CBIOPORTAL` |
   | `DOCKER_IMAGE_SESSION_SERVICE` | `CP_DOCKER_IMAGE_SESSION_SERVICE` |
   | `DOCKER_IMAGE_CLICKHOUSE` | `CP_DOCKER_IMAGE_CLICKHOUSE` |
   | `CLICKHOUSE_DB` | `CP_CLICKHOUSE_DB` |
   | `CLICKHOUSE_USER` | `CP_CLICKHOUSE_USER_FOR_DB_ADMIN`, `CP_CLICKHOUSE_USER_FOR_CBIOPORTAL_DB_UPDATE` and `CP_CLICKHOUSE_USER_FOR_CBIOPORTAL_WEB_APP` (set all three to the old value) |
   | `CLICKHOUSE_PASSWORD` | `CP_CLICKHOUSE_PASSWORD_FOR_DB_ADMIN`, `CP_CLICKHOUSE_PASSWORD_FOR_CBIOPORTAL_DB_UPDATE` and `CP_CLICKHOUSE_PASSWORD_FOR_CBIOPORTAL_WEB_APP` (set all three to the old value) |
   | `CLICKHOUSE_HOST` | `CP_CLICKHOUSE_HOST` |
   | `CLICKHOUSE_HTTP_PORT` | `CP_CLICKHOUSE_HTTP_INSECURE_PORT` (or `CP_CLICKHOUSE_HTTP_SECURE_PORT` with `CP_CLICKHOUSE_USE_SECURE_TRANSPORT=yes`) |
   | `CLICKHOUSE_NATIVE_PORT` | `CP_CLICKHOUSE_NATIVE_INSECURE_PORT` (or `CP_CLICKHOUSE_NATIVE_SECURE_PORT`) |
   | `CLICKHOUSE_URL` | `CP_CLICKHOUSE_URL` (append `?custom_settings=enable_http_compression=0`, see below) |
   | `CLICKHOUSE_OPTIMIZE_BACKOFF_SECS` | `CP_CLICKHOUSE_OPTIMIZE_BACKOFF_SECS` |
   | `CLICKHOUSE_SETTINGS_PATH` | `CP_CLICKHOUSE_USER_SETTINGS_PATH` |
   | `CBIOPORTAL_SERVER_PORT` | `CP_CBIOPORTAL_SERVER_PORT` |
   | `SHOW_DEBUG_INFO` | `CP_SHOW_DEBUG_INFO` |
   | `APPLICATION_PROPERTIES_PATH` | `CP_APPLICATION_PROPERTIES_PATH` |
   | `SESSION_SERVICE_SERVER_PORT` | `CP_SESSION_SERVICE_SERVER_PORT` |
   | `SESSION_SERVICE_JAVA_OPTS` | `CP_SESSION_SERVICE_JAVA_OPTS` |
   | `MONGO_INITDB_DATABASE` | `CP_MONGO_INITDB_DATABASE` |

   The `CLICKHOUSE_USER` / `CLICKHOUSE_PASSWORD` lines at the bottom of the new `.env` are derived
   from the `CP_` admin settings and should not be edited directly.

3. **Regenerate `config/application.properties`** with `cd config && ./init.sh`. If you maintain
   your own `application.properties`, add `custom_settings=enable_http_compression=0` to the query
   string of `spring.datasource.url` / `spring.datasource.clickhouse.url`, e.g.
   `jdbc:ch://cbioportal-database:8123/cbioportal?custom_settings=enable_http_compression=0`.
   The cBioPortal ClickHouse driver cannot read HTTP-compressed responses, which ClickHouse
   enables by default since 25.x. (The bundled ClickHouse also disables this in
   `data/clickhouse_user_settings.xml`, but a remote ClickHouse such as ClickHouse Cloud needs the
   URL setting.)

4. **Start the stack** with `docker compose up -d`. The initialization scripts in
   `docker-entrypoint-initdb.d` only run on an empty volume, so they are skipped. The
   `cbioportal-migration` service still applies any pending schema migrations.

5. **Optional: separate database accounts.** On a fresh install, the web app, the importer and the
   database admin can use different ClickHouse accounts (`CP_CLICKHOUSE_USER_FOR_*`). On an
   upgraded volume these accounts are not created automatically. After setting them in `.env`,
   create them with:
   ```bash
   docker compose up -d cbioportal-database
   docker compose exec cbioportal-database /docker-entrypoint-initdb.d/003_create_users_and_write_privileges.sh
   cd config && ./init.sh && cd ..
   docker compose up -d
   ```
