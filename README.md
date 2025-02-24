# Run cBioPortal using Docker Compose
Download necessary files (seed data, example config and example study from
datahub):
```
./init.sh
```

Start docker containers. This can take a few minutes the first time because the
database needs to import some data.
```
docker compose up
```
The cbioportal application should now be running at [localhost:8080](localhost:8080), with the one of the studies already loaded in it.

If you are developing and want to expose the MySQL database for inspection through a program like Sequel Pro, run:
```
docker compose -f docker-compose.yml -f dev/open-ports.yml up
```

The compose file uses docker volumes which persist data between reboots. To completely remove all data run:

```
docker compose down -v
```

If you were able to successfully set up a local installation of cBioPortal, please add it here: https://www.cbioportal.org/installations. Thank you!

## Loading custom studies
By default, the cbioportal docker compose setup comes preloaded with the `lgg_ucsf_2014` study, which is imported as part of the `DOCKER_IMAGE_MYSQL` environment variable [here](.env). If you want to load custom studies, run the following commands.
```shell
# Start docker compose if not already running
docker compose up

# In a separate terminal, import custom study
docker compose exec cbioportal metaImport.py -u http://cbioportal:8080 -s study/lgg_ucsf_2014/ -o

# Sync clickhouse (ONLY for clickhouse mode, see below)
docker compose exec cbioportal-clickhouse-importer bash /workdir/sync-databases.sh

# Restart cBioPortal
docker compose restart cbioportal
```

The example study in the `study/` directory is based on hg19. When importing hg38 data, be sure to set `reference_genome: hg38` in the [meta_study.txt](https://docs.cbioportal.org/5.1-data-loading/data-loading/file-formats#meta-file-4).

## Clickhouse Mode
For cBioPortal instances with large cohorts (>100K samples), we developed a "Clickhouse mode" of the Study View. This mode uses Clickhouse as an additional database next to MySQL for 10x faster querying (see [video](https://www.youtube.com/watch?v=8PAJRCeycU4)). The mode is experimental and is currently used only by the public-facing [GENIE instance](https://genie.cbioportal.org). We plan to roll it out to other portals later this year (see [roadmap ticket](https://github.com/orgs/cBioPortal/projects/16?query=sort%3Aupdated-desc+is%3Aopen&pane=issue&itemId=92222076&issue=cBioPortal%7Croadmap%7C1)). Follow the steps below to run cBioPortal Docker Compose in clickhouse mode.
1. Modify [.env](.env) to use clickhouse-compatible release of cBioPortal.
    ```text
    ...
    DOCKER_IMAGE_CBIOPORTAL=cbioportal/cbioportal:6.0.26
    ...
    ```
2. Run init script
    ```shell
    ./init.sh
    ```
3. Start cBioPortal with clickhouse
    ```shell
    docker compose -f docker-compose.yml -f addon/clickhouse/docker-compose.clickhouse.yml up
    ```

## Example Commands
### Connect to the database
```
docker compose exec cbioportal-database \
    sh -c 'mysql -hcbioportal-database -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"'
```

## Advanced topics
### Run different cBioPortal version

A different version of cBioPortal can be run using docker compose by declaring the `DOCKER_IMAGE_CBIOPORTAL`
environmental variable. This variable can point a DockerHub image like so:

```
export DOCKER_IMAGE_CBIOPORTAL=cbioportal/cbioportal:3.1.0
docker compose up
```

which will start the v3.1.0 portal version rather than the newer default version.

### Run the 'web-shenandoah' cBioPortal image
A web-only version of cBioPortal (suffixed -web-shenandoah) can be run using docker compose by declaring the `DOCKER_IMAGE_CBIOPORTAL`
environmental variable to point to the corresponding image:

```
export DOCKER_IMAGE_CBIOPORTAL=cbioportal/cbioportal:6.0.20-web-shenandoah
docker compose -f docker-compose.yml -f dev/docker-compose.web.yml up
```

which will start the v6.0.20-web-shenandoah version rather than the newest default version.

### Keycloak Authentication
To set up a keycloak server with your cBioPortal instance for development purposes, check out the [documentation](./dev/README.md).

### Change the heap size
#### Web app
You can change the heap size in the command section of the cbioportal container

#### Importer
For the importer you can't directly edit the java command used to import a study. Instead add `JAVA_TOOL_OPTIONS` as an environment variable to the cbioportal container and set the desired JVM parameters there (e.g. `JAVA_TOOL_OPTIONS: "-Xms4g -Xmx8g"`).
