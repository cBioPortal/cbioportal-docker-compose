#!/usr/bin/env bash
for d in config study data; do
    cd $d; ./init.sh
    cd ..
done

