FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
ARG CBIOPORTAL_CORE_BRANCH

# Install base packages and Python deps for metaImport
RUN apt-get update && apt-get install -y -q --no-install-recommends \
    git \
    curl \
    wget \
    unzip \
    jq \
    build-essential \
    software-properties-common \
    python3 \
    python3-pip \
    python3-requests \
    python3-yaml && \
    rm -rf /var/lib/apt/lists/*

# Install clickhouse cli
RUN curl https://clickhouse.com/ | sh && \
    ./clickhouse install

# Clone cbioportal-core and install Python dependencies
RUN git clone --depth 1 --branch ${CBIOPORTAL_CORE_BRANCH} \
    https://github.com/cBioPortal/cbioportal-core.git /cbioportal-core
RUN pip3 install -r /cbioportal-core/requirements.txt

COPY data/schema.sql /opt/schema.sql
COPY data/seed.sql.gz /opt/seed.sql.gz
