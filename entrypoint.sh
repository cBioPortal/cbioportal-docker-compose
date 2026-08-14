#!/bin/bash
set -eo pipefail

## Inject application.properties into the importer JAR so it overrides the bundled one
## Note: the official cbioportal image ships a JRE (no `jar`/`zip` binary), so we use
## python3's zipfile module instead of `jar uf`.
cd /tmp && cp /cbioportal-webapp/application.properties . && python3 - <<'PYEOF'
import zipfile, shutil

jar_path = "/core/core-IMPORTER.jar"
new_file = "application.properties"
tmp_path = jar_path + ".tmp"

with zipfile.ZipFile(jar_path, "r") as zin:
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.filename != new_file:
                zout.writestr(item, zin.read(item.filename))
        zout.write(new_file, new_file)

shutil.move(tmp_path, jar_path)
PYEOF

exec "$@"
