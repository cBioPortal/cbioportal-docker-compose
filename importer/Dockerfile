FROM ubuntu:22.04 AS builder
ARG DEBIAN_FRONTEND=noninteractive
ARG CBIOPORTAL_CORE_BRANCH

RUN apt-get update && apt-get install -y -q --no-install-recommends \
    git \
    openjdk-21-jdk \
    maven && \
    rm -rf /var/lib/apt/lists/*

ARG CACHEBUST=1
RUN git clone --depth 1 --branch ${CBIOPORTAL_CORE_BRANCH} \
    https://github.com/cBioPortal/cbioportal-core.git /cbioportal-core

RUN cd /cbioportal-core && mvn clean install -DskipTests -q && rm -rf target


FROM ubuntu:22.04
ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y -q --no-install-recommends \
    git \
    curl \
    openjdk-21-jre-headless \
    python3 \
    python3-pip \
    python3-requests \
    python3-yaml && \
    rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://clickhouse.com/ | sh && ./clickhouse install

COPY --from=builder /cbioportal-core /cbioportal-core
RUN pip3 install -r /cbioportal-core/requirements.txt
