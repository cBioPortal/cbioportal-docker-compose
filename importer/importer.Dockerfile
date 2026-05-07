FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
ARG CBIOPORTAL_CORE_BRANCH=rfc100-rc

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

# Download base schema and seed data
RUN wget -q -O /opt/schema.sql \
    "https://raw.githubusercontent.com/cBioPortal/cbioportal/refs/heads/add-clickhoue-database-schema-and-seed/src/main/resources/db-scripts/clickhouse/init/schema.sql"

RUN wget -q -O /opt/seed.sql.gz \
    "https://github.com/cBioPortal/cbioportal/raw/refs/heads/add-clickhoue-database-schema-and-seed/src/main/resources/db-scripts/clickhouse/init/seed-cbioportal_hg19_hg38_v2.14.5.sql.gz"
