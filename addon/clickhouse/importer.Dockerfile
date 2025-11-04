FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive

# Install base pacakages
RUN apt-get update && apt-get install -y -q --no-install-recommends \
    git \
    curl \
    wget \
    unzip \
    jq \
    build-essential \
    software-properties-common \
    mysql-client && \
    rm -rf /var/lib/apt/lists/*

# Install clickhouse cli
RUN curl https://clickhouse.com/ | sh && \
    ./clickhouse install

# Install sling
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then \
        SLING_URL="https://github.com/slingdata-io/sling-cli/releases/download/v1.2.14/sling_linux_amd64.tar.gz"; \
    elif [ "$ARCH" = "aarch64" ]; then \
        SLING_URL="https://github.com/slingdata-io/sling-cli/releases/download/v1.2.14/sling_linux_arm64.tar.gz"; \
    else \
        echo "Unsupported architecture: $ARCH" && exit 1; \
    fi && \
    curl -LO "$SLING_URL" && \
    tar xf $(basename "$SLING_URL") && \
    chmod +x sling && \
    mv sling /usr/local/bin/

# Clone cbioportal-core (locked to a single commit)
ARG BRANCH
RUN \
    mkdir /workdir && \
    git clone --depth 1 --branch $BRANCH "https://github.com/cBioPortal/cbioportal-core.git" && \
    cd cbioportal-core && \
    cp -r scripts/clickhouse_import_support/* /workdir && \
    python3 /workdir/download_clickhouse_sql_scripts_py3.py /workdir/ && \
    chmod +x /workdir/*.sh && \
    rm -rf /cbioportal-core
