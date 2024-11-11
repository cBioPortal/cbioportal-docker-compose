#!/usr/bin/env bash

# Load all environment variables
set -o allexport
source '.env'
set +o allexport

# Load dev environment variables
if [ $# -ge 1 ] && [ "$1" = "--dev" ]; then
  set -o allexport;
  source '.env.dev';
  set +o allexport;
fi


for d in config data study; do
    cd $d; ./init.sh
    cd ..
done

# add override docker file for arm64
# see https://github.com/cBioPortal/cbioportal/issues/9829
if [[ ! -f "docker-compose.override.yml" ]] && [[ "$(arch)" = "arm64" ]]; then
    cp docker-compose.arm64.yml docker-compose.override.yml
fi