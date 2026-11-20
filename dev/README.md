# Tools for development

In this folder is some additional configuration that can be useful for local development. None of this should be deployed directly to production.

# Set up keycloak for cBioPortal

[keycloak/keycloak.yml](keycloak/keycloak.yml) is an optional compose file that adds a Keycloak identity provider to the stack and switches cBioPortal to SAML login.

1. Navigate to the Root folder and start cBioPortal together with keycloak:

```shell
./init.sh
docker compose -f docker-compose.yml -f dev/keycloak/keycloak.yml up
```

2. Access cBioPortal at [localhost:8080](http://localhost:8080). The login credentials are `testuser:P@ssword1` (they can be found in [keycloak-config.json](keycloak/keycloak-config.json)).

The keycloak admin console is available at [localhost:8081](http://localhost:8081) with the credentials `admin:admin`.

To run without keycloak, leave out the extra compose file (`docker compose up`).

## Configuration

The following optional environment variables can be set (e.g. in `.env`):

| Variable | Default | Description |
| --- | --- | --- |
| `DOCKER_IMAGE_KEYCLOAK` | `quay.io/keycloak/keycloak:26.7` | Keycloak image |
| `KEYCLOAK_PORT` | `8081` | Port on the host where keycloak is reachable |
| `KEYCLOAK_CONFIG_PATH` | `./dev/keycloak/keycloak-config.json` | Realm that is imported when keycloak starts |
| `KEYCLOAK_CRT_PATH` | `./dev/keycloak/keycloak.crt` | Certificate cBioPortal signs SAML requests with |
| `KEYCLOAK_KEY_PATH` | `./dev/keycloak/keycloak.key` | Private key cBioPortal signs SAML requests with |

⚠️ Warning: Do not use this directly for production use as it takes several shortcuts to get a quick keycloak instance up. It e.g. runs keycloak in development mode over plain HTTP, keeps keycloak's data inside the container (changes made in the admin console are lost when the container is removed) and uses well-known credentials and keys.
