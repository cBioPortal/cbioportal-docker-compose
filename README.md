# Run cBioPortal using Docker Compose

## Quick Start

### 1. Download config, schema, seed data, and studies

```
./init.sh
```

This runs three sub-scripts:
- `config/init.sh` — extracts `application.properties` from the cBioPortal image and patches in your database credentials
- `data/init.sh` — downloads the ClickHouse base schema and seed SQL files (needed to build the importer image)
- `study/init.sh` — downloads example studies from the cBioPortal datahub via Git LFS

> **Requires:** [git-lfs](https://git-lfs.com) installed on the host (`brew install git-lfs` on macOS)

### 2. Build and start all containers

```
docker compose up
```

This starts cBioPortal at [localhost:8080](http://localhost:8080). The first run takes several minutes as the importer container applies the ClickHouse schema, seeds the database, and imports the example studies automatically.

---

## Configuration

All configuration lives in `.env`. Edit that file to change database credentials, the cBioPortal image version, heap sizes, or which studies to download.

The compose file uses Docker volumes to persist data between restarts. To wipe everything and start fresh:

```
docker compose down -v
```

---

## Example Commands

### Connect to the ClickHouse database

```
docker compose exec cbioportal-clickhouse-database \
    sh -c 'clickhouse-client -u "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB"'
```

### Import an additional study manually

```
docker compose exec cbioportal-clickhouse-importer \
    python3 -m importer.metaImport -s /study/your_study/ -n -o
```

Restart cBioPortal after importing:

```
docker compose restart cbioportal
```

---

## Advanced Topics

### Run a different cBioPortal version

Edit `DOCKER_IMAGE_CBIOPORTAL` in `.env`:

```
DOCKER_IMAGE_CBIOPORTAL=cbioportal/cbioportal:6.2.0
```

Then re-run `config/init.sh` to regenerate `application.properties` for the new image, and restart:

```
docker compose restart cbioportal
```

### Download different studies

Edit `DATAHUB_STUDIES` in `.env` (space-separated study IDs from the [cBioPortal datahub](https://github.com/cBioPortal/datahub)):

```
DATAHUB_STUDIES=lgg_ucsf_2014 msk_impact_2017
```

Then re-run `study/init.sh` to download them, and restart compose so the importer picks them up.

### Keycloak Authentication

To set up a Keycloak server with your cBioPortal instance for development, see the [dev documentation](./dev/README.md).

### Change the heap size

#### Web app

Edit the `java -Xms2g -Xmx4g` flags in the `command:` section of the `cbioportal` service in `docker-compose.yml`.

#### Importer

Add `JAVA_TOOL_OPTIONS` to the `.env` file and set the desired JVM parameters (e.g. `JAVA_TOOL_OPTIONS=-Xms4g -Xmx8g`).
