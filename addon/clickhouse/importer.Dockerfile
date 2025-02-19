FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive

# Install base pacakages
RUN apt update && apt install -y \
    git \
    curl \
    wget \
    unzip \
    jq \
    build-essential \
    software-properties-common

# Install python
RUN add-apt-repository ppa:deadsnakes/ppa && \
    apt install -y python3.9 && \
    ln -sf /usr/bin/python3.9 /usr/bin/python3

# Install clickhouse cli
RUN curl https://clickhouse.com/ | sh && \
    ./clickhouse install

# Install mysql
RUN apt install -y mysql-client

# Install sling
RUN curl -LO 'https://github.com/slingdata-io/sling-cli/releases/download/v1.2.14/sling_linux_arm64.tar.gz'

RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then \
        SLING_URL="https://github.com/slingdata-io/sling-cli/releases/download/v1.2.14/sling_linux_amd64.tar.gz"; \
    elif [ "$ARCH" = "aarch64" ]; then \
        SLING_URL="https://github.com/slingdata-io/sling-cli/releases/download/v1.2.14/sling_linux_arm64.tar.gz"; \
    else \
        echo "Unsupported architecture: $ARCH" && exit 1; \
    fi && \
    curl -LO "$SLING_URL" && \
    tar xf sling_linux_*.tar.gz && \
    chmod +x sling && \
    mv sling /usr/local/bin/

# Clone cbioportal-core
RUN \
    mkdir /workdir && \
    git clone --single-branch -b clickhouse-dependent-import-process 'https://github.com/sheridancbio/cbioportal-core.git' && \
    cp cbioportal-core/scripts/clickhouse_import_support/* /workdir && \
    chmod +x /workdir/*.sh
