#!/usr/bin/env bash
for d in config study; do
    cd $d; ./init.sh
    cd ..
done
for d in data; do
    cd $d; ./init_hg38.sh
    cd ..
done

# add override docker file for arm64
# see https://github.com/cBioPortal/cbioportal/issues/9829
if [[ ! -f "docker-compose.override.yml" ]] && [[ "$(arch)" = "arm64" ]]; then
    cp docker-compose.arm64.yml docker-compose.override.yml
fi
