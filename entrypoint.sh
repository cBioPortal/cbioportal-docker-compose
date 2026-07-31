#!/bin/bash
set -eo pipefail

## Inject application.properties into the importer JAR so it overrides the bundled one.
## The cbioportal image ships a JRE only, so the archive is updated with python3's
## zipfile module rather than the JDK's `jar` tool.
python3 - <<'PY'
import os
import zipfile

JAR = "/core/core-IMPORTER.jar"
ENTRY = "application.properties"
STAGED_JAR = JAR + ".staged"

with open("/cbioportal-webapp/application.properties", "rb") as properties_file:
    properties = properties_file.read()

with zipfile.ZipFile(JAR) as jar:
    if ENTRY in jar.namelist() and jar.read(ENTRY) == properties:
        raise SystemExit(0)
    with zipfile.ZipFile(STAGED_JAR, "w") as staged_jar:
        for member in jar.infolist():
            if member.filename != ENTRY:
                staged_jar.writestr(member, jar.read(member))
        staged_jar.writestr(ENTRY, properties, zipfile.ZIP_DEFLATED)

os.replace(STAGED_JAR, JAR)
PY

exec "$@"
