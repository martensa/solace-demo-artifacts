# OpenMetadata Deployment

Helm-based deployment of OpenMetadata 1.6.x on Kubernetes, sized for the
Solace Lab cluster.

This is the **base** OM install. The Solace Event Portal custom
connector (sibling project `om-connector/`) and the webhook bridge get
plugged in once OM is up.

## What gets deployed

- **MySQL** (Bitnami chart) for OM and Airflow databases. Pinned to
  `bitnamilegacy/mysql:8.0.33-debian-11-r0` because Bitnami moved
  older free images out of `bitnami/` in August 2025.
- **OpenSearch** (Apache 2.0, single node) as search backend
- **Airflow** (KubernetesExecutor) running the
  `openmetadata/ingestion` image for pipeline execution
- **OpenMetadata server** authenticated via the
  `solace-lab` Keycloak realm at `auth.solace.lab`
  (OIDC code flow, confidential client)

```text
Ingress (openmetadata.solace.lab)
   |
   v
openmetadata (server)  --->  mysql
   |
   |--->  opensearch
   |
   '--->  openmetadata-dependencies-web (Airflow REST API)
                  |
                  '--->  KubernetesExecutor workers (ingestion image)
```

## Cluster Dependencies

Assumes the following from `solace-lab-infrastructure`
(<https://github.com/martensa/solace-lab-infrastructure>):

- NGINX Ingress Controller (`ingress-nginx`)
- cert-manager + ClusterIssuer `solace-lab-ca-issuer`
- trust-manager bundle `solace-lab-ca-trust-bundle` plus Kyverno policy
  `inject-solace-lab-ca-trust-bundle` (so pods see the lab CA out of
  the box -- no per-deployment cert config required for python/curl;
  the OM server adds an init container on top to import the bundle
  into a JVM truststore, see CLAUDE.md)
- Keycloak at `auth.solace.lab` with the `solace-lab` realm
  (and an `auth.solace.lab` entry in CoreDNS NodeHosts so the OM
  pod can reach Keycloak for OIDC discovery)

`start.sh` registers `openmetadata.solace.lab` in CoreDNS NodeHosts so
the hostname resolves both externally and inside the cluster.

## Start and Stop

```bash
cp .env.example .env  # set Keycloak admin creds if non-default
./scripts/start.sh    # bootstraps Keycloak client, then helm install
./scripts/stop.sh     # full teardown incl. PVCs + Keycloak client
```

`start.sh` calls `setup-keycloak-client.sh` for you (idempotent --
creates the OIDC client if missing, otherwise just fetches the
existing secret), then writes the resulting `KEYCLOAK_CLIENT_SECRET`
back into `.env` so a `stop.sh` -> `start.sh` round-trip recovers
without any manual paste step.

Re-running `start.sh` is safe end-to-end: `helm upgrade --install`,
JWT secret left alone if it already exists, OIDC client adopted in
place, and the `oidc-secrets` Kubernetes Secret re-applied so a
rotated client secret propagates on the next pod restart.

## First-time login

OpenMetadata is wired to the `solace-lab` Keycloak realm at
`auth.solace.lab`. The first user whose token principal matches
`<initialAdmins>@<principalDomain>` (i.e. `admin@solace.lab`) becomes
OM admin on first login.

1. Open `https://openmetadata.solace.lab/signin`
2. You are redirected to Keycloak. Log in as
   - username: `admin`
   - password: (the `solace-lab` realm admin password)
3. After the callback you land in OM as admin.

Any other user from the `solace-lab` realm can also sign in and gets
a regular (non-admin) OM account auto-provisioned. To promote them,
log in as `admin` and grant the admin role under
**Settings -> Users**.

## Getting the ingestion-bot JWT

The Solace connector and the webhook bridge both authenticate to OM
with the ingestion-bot JWT:

1. Login as admin.
2. **Settings -> Bots -> ingestion-bot**.
3. Click the JWT token field to reveal it, then copy.
4. Paste into `.env` as `OM_INGESTION_BOT_TOKEN` (or directly into the
   connector workflow YAML).

## Customizing

- **Hostname** -- `local-k8s-values.yaml` (`ingress.hosts[0].host`)
  plus `OM_DNS_NAME` in `scripts/start.sh`
- **OM admin principal** -- `local-k8s-values.yaml`
  (`authorizer.initialAdmins`, `principalDomain`)
- **Keycloak realm / issuer** -- `.env` (`KEYCLOAK_REALM`,
  `KEYCLOAK_ISSUER`) plus `discoveryUri`, `authority`, `publicKeys[1]`
  in `local-k8s-values.yaml`
- **OIDC client name** -- `.env` (`KEYCLOAK_CLIENT_ID`, default
  `openmetadata`); the client is provisioned by
  `scripts/setup-keycloak-client.sh`
- **DB password** -- demo creds are hardcoded in the chart's MySQL
  `initdbScripts` and mirrored into the `mysql-secrets` /
  `airflow-mysql-secrets` Kubernetes Secrets by `scripts/start.sh`.
  Changing the password means editing both `start.sh` and reseeding
  MySQL by hand (initdbScripts only run on a fresh data PVC).
- **OpenSearch resources** -- `local-k8s-deps-values.yaml`
  (`opensearch.resources`)
- **JVM heap / OM server resources** -- `local-k8s-values.yaml`
  (`resources`)

To map Keycloak group membership onto OM roles, flip
`authorizer.useRolesFromProvider: true`. The `groups` claim is already
emitted by the client (set up by `scripts/setup-keycloak-client.sh`),
so no Keycloak-side changes are needed.

## Files

- `local-k8s-deps-values.yaml` -- MySQL + OpenSearch + Airflow values
- `local-k8s-values.yaml` -- OM server (OIDC auth, ingress, JWT keys,
  DB connection, Airflow client, JVM truststore init container)
- `scripts/setup-rsa-keys.sh` -- idempotent RSA-2048 keypair + Secret
- `scripts/setup-keycloak-client.sh` -- creates the `openmetadata` OIDC
  client in the `solace-lab` realm via Keycloak Admin REST API
- `scripts/teardown-keycloak-client.sh` -- removes the client (also
  called from `stop.sh`)
- `scripts/start.sh` -- end-to-end install
- `scripts/stop.sh` -- end-to-end teardown
- `.env.example` -- template for Keycloak admin creds and the OIDC
  client secret

## What's intentionally NOT done in this MVP

- **Keycloak role -> OM role mapping**:
  `authorizer.useRolesFromProvider` is left `false`. Admin is granted
  via the `<initialAdmins>@<principalDomain>` match alone. Flip to
  `true` (and add role mappers in Keycloak) once OM-side group/role
  semantics are pinned down.
- **Custom ingestion image with the Solace EP connector**: planned as
  Step 2. The vanilla `docker.getcollate.io/openmetadata/ingestion` is
  used today; the connector will be either baked into a custom image
  or `pip install`-ed at workflow time.
- **Mirrored images in `registry.solace.lab`**: relies on cluster
  egress to `docker.getcollate.io`. Switch via the `image.repository`
  values once mirrored.

## References

- OpenMetadata docs: <https://docs.open-metadata.org/>
- OM Helm charts repository
  (<https://github.com/open-metadata/openmetadata-helm-charts>)
- OM Keycloak SSO on Kubernetes (one-liner search at
  <https://docs.open-metadata.org/>)
