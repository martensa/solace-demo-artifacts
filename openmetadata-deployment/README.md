# OpenMetadata Deployment

Helm-based deployment of OpenMetadata 1.6.x on Kubernetes, sized for the
Solace Lab cluster.

This is the **base** OM install. The Solace Event Portal custom
connector (sibling project `om-connector/`) and the webhook bridge get
plugged in once OM is up.

## What gets deployed

- **PostgreSQL** (Bitnami chart) for OM and Airflow databases
- **OpenSearch** (Apache 2.0, single node) as search backend
- **Airflow** running the `openmetadata/ingestion` image for pipeline
  execution
- **OpenMetadata server** with Basic + JWT authentication

```text
Ingress (openmetadata.solace.lab)
   |
   v
openmetadata (server)  --->  openmetadata-postgresql
   |
   |--->  opensearch
   |
   '--->  openmetadata-dependencies-web (Airflow REST API)
                  |
                  '--->  KubernetesExecutor workers (ingestion image)
```

## Cluster Dependencies

Assumes the following from
[`solace-lab-infrastructure`](https://github.com/martensa/solace-lab-infrastructure):

- NGINX Ingress Controller (`ingress-nginx`)
- cert-manager + ClusterIssuer `solace-lab-ca-issuer`
- trust-manager bundle `solace-lab-ca-trust-bundle` plus Kyverno policy
  `inject-solace-lab-ca-trust-bundle` (so pods see the lab CA out of
  the box -- no per-deployment cert config required)

`start.sh` registers `openmetadata.solace.lab` in CoreDNS NodeHosts so
the hostname resolves both externally and inside the cluster.

## Start and Stop

```bash
./scripts/start.sh   # adds helm repo, generates JWT keys, installs both charts
./scripts/stop.sh    # full teardown incl. PVCs
```

Re-running `start.sh` is safe: it does a `helm upgrade --install` and
leaves the JWT secret alone if it already exists.

## First-time login

OpenMetadata starts with **basic auth + self-signup** enabled. The user
whose email matches `<initialAdmin>@<principalDomain>` becomes admin on
sign-up.

1. Open https://openmetadata.solace.lab/signin
2. Click "Create Account" and sign up with
   - email: `admin@open-metadata.org`
   - password: your choice (>=8 chars, 1 digit, 1 upper, 1 special)
3. You are logged in as admin.

To restrict signup later, set
`openmetadata.config.authentication.enableSelfSignup: false` in
`local-k8s-values.yaml` and `helm upgrade`.

## Getting the ingestion-bot JWT

The Solace connector and the webhook bridge both authenticate to OM
with the ingestion-bot JWT:

1. Login as admin.
2. **Settings -> Bots -> ingestion-bot**.
3. Click the JWT token field to reveal it, then copy.
4. Paste into `.env` as `OM_INGESTION_BOT_TOKEN` (or directly into the
   connector workflow YAML).

## Customizing

| Want to change       | Where                                                                |
| -------------------- | -------------------------------------------------------------------- |
| Hostname             | `local-k8s-values.yaml` -> `ingress.hosts[0].host` + `start.sh` DNS  |
| Admin email          | `local-k8s-values.yaml` -> `authorizer.principalDomain`              |
| DB password          | `local-k8s-deps-values.yaml` AND `local-k8s-values.yaml`             |
| OpenSearch resources | `local-k8s-deps-values.yaml` -> `opensearch.resources`               |
| Disable self-signup  | `local-k8s-values.yaml` -> `authentication.enableSelfSignup: false`  |

## Files

- `local-k8s-deps-values.yaml` -- PostgreSQL + OpenSearch + Airflow
- `local-k8s-values.yaml` -- OM server (auth, ingress, JWT keys, DB
  connection, Airflow client)
- `scripts/setup-rsa-keys.sh` -- idempotent RSA-2048 keypair + Secret
- `scripts/start.sh` -- end-to-end install
- `scripts/stop.sh` -- end-to-end teardown
- `.env.example` -- placeholder for future per-deployment secrets

## What's intentionally NOT done in this MVP

- **Keycloak OIDC**: basic auth keeps the first deploy minimal. To
  switch later: add `setup-keycloak-client.sh` script (analog to the
  agent-mesh one), set `authentication.provider: oidc` in the server
  values, drop in client id/secret via `--set`.
- **Custom ingestion image with the Solace EP connector**: planned as
  Step 2. The vanilla `docker.getcollate.io/openmetadata/ingestion` is
  used today; the connector will be either baked into a custom image
  or `pip install`-ed at workflow time.
- **Mirrored images in `registry.solace.lab`**: relies on cluster
  egress to `docker.getcollate.io`. Switch via the `image.repository`
  values once mirrored.

## References

- OpenMetadata docs: <https://docs.open-metadata.org/>
- OM Helm charts: <https://github.com/open-metadata/openmetadata-helm-charts>
- OM basic auth flow:
  <https://docs.open-metadata.org/v1.6.x/deployment/security/basic-auth>
