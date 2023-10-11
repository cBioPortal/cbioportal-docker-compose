# Set up keycloak for Spring Boot cBioPortal

1. Run components needed for local developent (cbioportal database, session service, keycloak).
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

6. Start cBioPortal application.
