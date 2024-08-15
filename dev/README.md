# Tools for development

In this folder is some additional configuration that can be useful for local development. None of this should be deployed directly to production

# Set up keycloak for Spring Boot cBioPortal

These steps should work for spinning up keycloak for use with the Spring Boot refactoring of cBioPortal (see [RFC72](https://docs.google.com/document/d/1SoFaiQ-UGdXXSmkl0-lKEAZz3PCBp5zgJ9US0JhJmrk/edit) and related ticket https://github.com/cBioPortal/cbioportal/issues/10356). It has been tested with the `demo-rfc72` image.

1. Navigate to the Root folder and run components needed for local development (cbioportal database, session service, keycloak).
These services have portal open for external connection (resp. 3306, 5000, 8084):

```
 docker compose -f docker-compose.yml -f ./dev/keycloak.yml -f ./dev/open-ports.yml up -d kcdb keycloak cbioportal-database cbioportal-session cbioportal-session-database 
```

2. Retrieve the SAML2 IDP metadata xml file:

```
 wget http://localhost:8084/auth/realms/cbio/protocol/saml/descriptor -O saml2-idp-metadata.xml
```

3. Copy file _saml2-idp-metadata.xml_ into the classpath of the Spring Boot cBioPortal artifact.
4. Activate SAML2 authentication-mode in _portal.properties_ and reference the _saml2-idp-metadata.xml_ file:

```
authenticate=saml
spring.security.saml2.relyingparty.registration.cbio-idp.identityprovider.metadata-uri=classpath://saml2-idp-metadata.xml
```

6. Start cBioPortal application. The login credentials are `testuser:P@assword1` (they can be found in [keycloak-config.json](./keycloak-config.json)).

⚠️ Warning: Do not use this directly for production use as it takes several shortcuts to get a quick keycloak instance up. It e.g. does not use AuthN request signing
