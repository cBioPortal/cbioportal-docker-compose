FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive

# Install base pacakages
RUN apt-get update && apt-get install -y \
    git \
    curl \
    wget \
    unzip \
    jq \
    build-essential \
    software-properties-common

# Install python
RUN add-apt-repository ppa:deadsnakes/ppa && \
    apt-get install -y python3.9 && \
    ln -sf /usr/bin/python3.9 /usr/bin/python3

# Install clickhouse cli
RUN curl https://clickhouse.com/ | sh && \
    ./clickhouse install

# Install mysql
RUN apt-get install -y mysql-client

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
    tar xf $(basename "$SLING_URL") && \
    chmod +x sling && \
    mv sling /usr/local/bin/

# Clone cbioportal-core (locked to a single commit)
ARG OWNER
ARG REPO
ARG BRANCH
ARG COMMIT
RUN \
    mkdir /workdir && \
    git clone --single-branch -b $BRANCH "https://github.com/$OWNER/$REPO.git" && \
    cd $REPO && \
    git checkout $COMMIT && \
    if [ "$(git rev-parse HEAD)" != "$COMMIT" ]; then \
      echo "ERROR: Unable to checkout given commit: $COMMIT";  \
      exit 1; \
    fi && \
    cp scripts/clickhouse_import_support/* /workdir && \
    chmod +x /workdir/*.sh
