#!/usr/bin/env bash
for d in config study; do
    cd $d; ./init.sh
    cd ..
done
for d in data; do
    cd $d; ./init_hg38.sh
    cd ..
done
