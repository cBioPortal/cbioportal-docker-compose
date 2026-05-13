#!/bin/bash
set -eo pipefail

## Inject application.properties into the importer JAR so it overrides the bundled one
cd /tmp && cp /cbioportal-webapp/application.properties . && jar uf /core/core-IMPORTER.jar application.properties

exec "$@"
