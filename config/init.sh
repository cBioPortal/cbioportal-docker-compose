#!/usr/bin/env bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

VERSION=$(grep DOCKER_IMAGE_CBIOPORTAL ../.env | cut -d '=' -f 2-)

docker run --rm -it $VERSION cat /cbioportal-webapp/WEB-INF/classes/portal.properties | \
    sed 's|db.host=.*||' | \
    sed 's|db.portal_db_name=.*||' | \
    sed 's|db.use_ssl=.*||' | \
    sed 's|db.connection_string=.*|db.connection_string=jdbc:mysql://cbioportal-database:3306/cbioportal?useSSL=false\&allowPublicKeyRetrieval=true|' \
> portal.properties
