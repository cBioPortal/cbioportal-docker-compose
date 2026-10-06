# Run cBioPortal using Docker Compose

Welcome to the cBioPortal Docker Compose repository!

For documentation and usage instructions, see here: https://docs.cbioportal.org/deployment/docker/

## License

The files in this repository are licensed under the [Apache License 2.0](./LICENSE).

The container images it runs are distributed under their own licenses:

- cBioPortal (`cbioportal/cbioportal`) and session-service (`cbioportal/session-service`): Apache-2.0 for releases from October 2026; earlier releases are AGPL-3.0
- ClickHouse (`clickhouse/clickhouse-server`): Apache-2.0
- MongoDB (`mongo`): Server Side Public License (SSPL)
- Keycloak (`quay.io/keycloak/keycloak`, `dev/` setup only): Apache-2.0
