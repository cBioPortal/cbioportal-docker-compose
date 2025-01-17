# Tools for development

In this folder is some additional configuration that can be useful for local development. None of this should be deployed directly to production.

# Set up keycloak for cBioPortal

These steps should work for spinning up keycloak for use with cBioPortal.

1. Navigate to the Root folder and run keycloak instance:

```shell
./init.sh
docker compose -f docker-compose.yml -f dev/keycloak/keycloak.yml up keycloak
```

2. In another terminal, retrieve the SAML2 IDP metadata xml file:

```shell
wget http://localhost:8081/auth/realms/cbio/protocol/saml/descriptor -O ./dev/keycloak/idp-metadata.xml
```

3. Restart keycloak instance together with cBioPortal

```shell
docker compose -f docker-compose.yml -f dev/keycloak/keycloak.yml up
```

4. Access cBioPortal at [localhost:8080](localhost:8080). The login credentials are `testuser:P@assword1` (they can be found in [keycloak-config.json](keycloak/keycloak-config.json)).

⚠️ Warning: Do not use this directly for production use as it takes several shortcuts to get a quick keycloak instance up. It e.g. does not use AuthN request signing