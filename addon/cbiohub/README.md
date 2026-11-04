# cBioHub add-on

Runs cBioHub next to the portal: a study catalog where people can browse studies, see validation results, add data sources and request imports, with an Airflow server that runs the validation and import DAGs against this portal's database.

```
cBioHub webapp ─► cBioHub Postgres (catalog, Airflow metadata)
      │
      └─► cBioHub Airflow ─► validate_studies        (validateData.py against the portal)
                          ├─► import_studies__local  (metaImport.py into the portal's ClickHouse)
                          └─► sync_github_sources    (GitHub repos mirrored to a shared volume)
```

## Run

From the root of this repository, after the usual setup (`./init.sh`):

```bash
docker compose -f docker-compose.yml -f addon/cbiohub/docker-compose.cbiohub.yml up -d --build
```

| | |
|---|---|
| cBioPortal | http://localhost:8080 |
| cBioHub | http://localhost:8000 |
| Airflow | http://localhost:8082 (admin / admin) |

The images build from a cBioHub checkout at `CBIOHUB_SRC`, by default `../cbiohub` next to this repository.

## What you get

- **Studies in `./study`** are added as the first data source. Each folder with a `meta_study.txt` shows up in cBioHub within a few minutes and is validated automatically.
- **Validation** runs cBioPortal's validator against this portal, so gene and gene panel checks use its database. Results show in cBioHub, with the HTML report one click away.
- **Import** to "This portal" runs `import_studies__local`. It imports each study, rebuilds the derived tables once for the batch, and records the result in cBioHub.
- **Data sources** (top bar, admins only): add a folder inside `./study`, an S3 bucket, or a GitHub repository holding many studies, which is mirrored every 15 minutes.

## How it's wired

- **Same importer as the portal.** The Airflow image is built `FROM ${DOCKER_IMAGE_CBIOPORTAL}` and copies `/core` (importer jar and scripts), the JRE and the `clickhouse` client out of it, so imports always use the portal's own importer version. `DOCKER_IMAGE_CBIOPORTAL` must be a web-and-data image.
- **Same database as the portal.** Airflow mounts the portal's `application.properties` (baked into the importer jar at startup, as the portal's `entrypoint.sh` does) and `data/populate_derived_tables.sql`, and reads `CLICKHOUSE_*` from `.env`. It waits for `cbioportal-migration`, so it never imports into an outdated schema.
- **Shared folders.** `./study` is mounted read-only into the webapp and Airflow at `/study`. The `cbiohub_data` volume holds GitHub mirrors and validation reports: Airflow writes it, the webapp reads it.
- **cBioHub's own Postgres** holds the catalog and Airflow's metadata (database `airflow`). `initdb/10-destinations.sql` replaces cBioHub's default staging/production destinations with this one portal.

## Settings

Set these in the shell or in `.env`:

| Variable | Default | |
|---|---|---|
| `CBIOHUB_SRC` | `../cbiohub` | cBioHub checkout to build from |
| `CBIOHUB_PORT` | `8000` | cBioHub web port |
| `CBIOHUB_AIRFLOW_PORT` | `8082` | Airflow web port |
| `CBIOHUB_USER`, `CBIOHUB_ADMIN_EMAILS` | `admin@localhost` | Who everyone is (there's no sign-in yet), and who can manage data sources |
| `CBIOHUB_AIRFLOW_USER`, `CBIOHUB_AIRFLOW_PASSWORD` | `admin` / `admin` | Airflow login, also used by cBioHub to call Airflow's API |
| `CBIOHUB_POSTGRES_PASSWORD` | `cbiohub` | |
| `CBIOHUB_AWS_ACCESS_KEY_ID`, `CBIOHUB_AWS_SECRET_ACCESS_KEY`, `AWS_REGION` | none | Only for S3 sources: an IAM user that can read the buckets you add. `.env` is checked in, so keep these out of it: put them in `.env.aws` (gitignored) and load it into the shell before `up` (`set -a; . ./.env.aws; set +a`) |
| `CBIOHUB_SCAN_INTERVAL_MINUTES` | `5` | How often folder and S3 sources are rescanned |

## Limits

- **No sign-in.** Everyone is `CBIOHUB_USER`, who is an admin. Don't expose port 8000 beyond your machine without an auth proxy in front that sets `X-Forwarded-Email`. The Airflow passwords are defaults too.
- **Batch visibility depends on the importer.** With cBioPortal 7.1.2, each study in a batch is visible as soon as it's imported, so a failed batch can leave earlier studies in the portal. With a newer importer (one with `make-studies-available`), the DAG keeps the batch hidden until every study has imported.
- **One portal.** The Airflow image imports into the database in the mounted `application.properties`.
- **Fresh portals lack reference data.** Studies that use gene panels or gene sets fail validation until those are imported (e.g. `study_es_0`, `msk_impact_2017` here).

To remove the add-on and its data: `docker compose -f docker-compose.yml -f addon/cbiohub/docker-compose.cbiohub.yml down`, then `docker volume rm cbioportal-docker-compose_cbiohub_pgdata cbioportal-docker-compose_cbiohub_data`.
