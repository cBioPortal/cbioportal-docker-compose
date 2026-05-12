#!/bin/bash
set -eo pipefail

mkdir -p /workdir && cd /workdir

CH_CLIENT="clickhouse-client --host ${CLICKHOUSE_HOST} --port ${CLICKHOUSE_NATIVE_PORT} --user ${CLICKHOUSE_USER} --password ${CLICKHOUSE_PASSWORD} --database ${CLICKHOUSE_DB} --multiquery"

# Run derived table script (necessary even though the db is empty for the website to work properly)
echo "Running derived table script..."
python3 metaImport.py derive-tables
echo "Derived tables initialized."

echo "Clickhouse database has been successfully initialized with reference data."
echo "Please import your studies using 'docker compose exec cbioportal metaImport.py ...' first before attempting to view the website."

## HACK: inject application.properties into the importer JAR so it overrides the bundled one
cd /tmp && cp /cbioportal-webapp/application.properties . && jar uf /core/core-IMPORTER.jar application.properties

exec "$@"
