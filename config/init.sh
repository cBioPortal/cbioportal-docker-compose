#!/usr/bin/env bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

docker run --rm -it cbioportal/cbioportal:3.4.4 cat /cbioportal-webapp/WEB-INF/classes/portal.properties | \
    sed 's/db.host=.*/db.host=cbioportal_database:3306/g' | \
    sed 's|db.connection_string=.*|db.connection_string=jdbc:mysql://cbioportal_database:3306/|g' \
> portal.properties
