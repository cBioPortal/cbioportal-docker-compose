# Run cBioPortal using Docker Compose

## Prerequisites

**Docker** must be installed and the daemon running before any step below will work. See [Get Docker](https://docs.docker.com/get-started/get-docker/) for platform-specific installation instructions.

---

## Quick Start

### 1. Download config, schema, seed data, and studies

```
./init.sh
```

This runs three sub-scripts:
- `config/init.sh` — extracts `application.properties` from the cBioPortal image and patches in your database credentials
- `data/init.sh` — downloads the ClickHouse base schema and seed SQL files from the cBioPortal image
- `study/init.sh` — downloads example studies from the cBioPortal datahub

### 2. Start all containers

```
docker compose up
```

This starts cBioPortal at [localhost:8080](http://localhost:8080). On first run, ClickHouse applies the schema and seed data automatically before the web app becomes available.

### 3. Import studies

The portal starts with only reference seed data. Import the studies downloaded in step 1 under the `study/` directory:

```
docker compose exec cbioportal metaImport.py -s /study/lgg_ucsf_2014/ -n -o
docker compose exec cbioportal metaImport.py -s /study/msk_impact_2017/ -n -o
docker compose restart cbioportal
```

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
# Export ClickHouse vars first -- eg. 'source .env'
docker compose exec cbioportal-database \
    sh -c 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB"'
```

### Import an additional study manually

```
docker compose exec cbioportal \
    metaImport.py -s /study/your_study/ -n -o
```

Restart cBioPortal after importing so it picks up the new study:

```
docker compose restart cbioportal
```

---

## Advanced Topics

### Run a different cBioPortal version

Edit `DOCKER_IMAGE_CBIOPORTAL` in `.env`:

```
DOCKER_IMAGE_CBIOPORTAL=cbioportal/cbioportal:<desired_version>
```

Then re-run `config/init.sh` to regenerate `application.properties` for the new image, and restart:

```
docker compose restart cbioportal
```

### Download different studies

In your terminal session, export `DATAHUB_STUDIES` as a list of (space-separated study IDs from the [cBioPortal datahub](https://github.com/cBioPortal/datahub)). Then re-run `study/init.sh` to download them, and restart compose so the importer picks them up.

```
export DATAHUB_STUDIES="lgg_ucsf_2014 msk_impact_2017"
cd study/ && ./init.sh
# Import the studies using metaImport.py as described above
```

### Change the heap size

Edit the `java -Xms2g -Xmx4g` flags in the `command:` section of the `cbioportal` service in `docker-compose.yml`.

### Keycloak Authentication

To set up a Keycloak server with your cBioPortal instance for development, see the [dev documentation](./dev/README.md).
