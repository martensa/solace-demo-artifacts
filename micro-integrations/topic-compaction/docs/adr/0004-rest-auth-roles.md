# ADR 0004: REST Authentication and Role Model

- Status: Accepted
- Date: 2026-05-05
- Deciders: Topic Compaction MI maintainers

## Context

The V0 MVP shipped without authentication on the REST surface,
relying on network-level isolation (docker-compose host-port,
cluster-internal Service). For V1.0 we want the REST endpoints
gated by a real authentication mechanism so that the MI can be
exposed beyond the cluster boundary (Ingress, port-forward,
admin tooling).

The MI Framework provides its own `SecurityAutoConfiguration` that
wires a `PasswordEncoder` and an in-memory `UserDetailsService` from
`solace.connector.security.users[]`. It is single-role and
ALL-or-NOTHING (auth on/off). That is too coarse for our needs:
the admin endpoints (`backup`, `restore`, `delete`) are
data-destructive while the read endpoints (`get`, `list`) are
relatively safe.

## Decision

Introduce a dedicated `WebSecurityConfig` in this MI that:

- **Excludes** the framework's `SecurityAutoConfiguration` (via
  `@SpringBootApplication(exclude = ...)`) - because it conflicts
  on bean names.
- Defines a two-role in-memory user store:
  - `mi-user` (role `USER`) - read access to `/api/v1/kv/...` only.
  - `mi-admin` (role `ADMIN`) - everything `USER` can do, plus
    `DELETE /api/v1/kv/...`, `/api/v1/admin/*`, and the actuator
    endpoints other than the public `/actuator/health` and
    `/actuator/prometheus`.
- Always leaves `/actuator/health` and `/actuator/prometheus`
  public. K8s probes do not authenticate, and Prometheus operator
  scraping is gated by `NetworkPolicy` (only the monitoring
  namespace is allowed inbound).
- Uses HTTP Basic auth, stateless. CSRF disabled (every call is
  an idempotent REST verb authenticated per-request).
- Reads credentials from the `topic-compaction.security.*` config
  prefix, which in turn maps to env vars
  `MI_USER_NAME`, `MI_USER_PASSWORD`, `MI_ADMIN_NAME`,
  `MI_ADMIN_PASSWORD`. In K8s these come from a `Secret`; in
  docker-compose from `.env`.
- Disabled by default (`topic-compaction.security.enabled=false`)
  for the dev mode. The K8s overlay enables it unconditionally.

## Consequences

### Positive

- Clean separation of read-only and admin operations.
- Follows the principle of least privilege.
- Dev mode keeps the REST endpoints open for fast iteration.
- The cluster overlay is secure-by-default.

### Negative / Trade-offs

- Excluding `SecurityAutoConfiguration` means we own the security
  surface entirely. The framework's `solace.connector.security.*`
  config knobs are inert in this MI.
- In-memory user store does not scale to per-deployment user
  rotation; for V2 we plan to swap to a directory-backed provider
  or OIDC.
- Basic auth over HTTP - acceptable inside the cluster, but for
  Ingress exposure HTTPS termination at the Ingress controller is
  required. This is the lab's existing pattern (cert-manager is
  in `solace-lab-infrastructure/pki`).

## Alternatives Considered

- **Use the MI Framework's auth verbatim**: rejected for being
  single-role.
- **OAuth 2.0 / OIDC against Keycloak**: more capable, but heavy
  for the V1.0 scope and not all client tooling speaks OIDC. Plan
  for V2.
- **mTLS-only authentication**: would require client certificate
  distribution. The PKI exists in
  `solace-lab-infrastructure/pki` (see `pki/docs/spring-boot-tls.md`)
  and we may layer it on top of basic auth in V2.
- **Disable auth entirely in K8s and rely on NetworkPolicy +
  Ingress**: rejected because intra-cluster compromise should not
  give automatic access to data-destructive operations.

## References

- `security/WebSecurityConfig.java`, `security/SecurityProperties.java`
- `40-deployment.yaml` `envFrom` -> `topic-compaction-mi-secret`
- `20-secret.yaml.template`
- `docs/SECURITY.md` (added in Phase 6)
