# Security

This document captures the V1.0 security model of the Topic
Compaction MI: what is in scope, what is out of scope, and the
specific controls in place.

## Threat model

The MI runs as a single tenant inside a trusted Kubernetes
cluster. The threats considered:

| Threat | In scope | Mitigation |
|---|---|---|
| Unauthorised REST callers reading the KV store | yes | HTTP Basic auth, role-gated endpoints, NetworkPolicy |
| Unauthorised callers calling admin endpoints (backup, restore, delete) | yes | ADMIN role only |
| Cross-namespace lateral movement | yes | NetworkPolicy: ingress only from monitoring + same namespace |
| Container breakout / privilege escalation | yes | non-root user, read-only root filesystem, dropped capabilities, seccomp default |
| Path-traversal via REST | yes | Solace topic keys never used as filesystem paths or shell args; URL decoding is bounded |
| DoS via huge bulk replay | yes | `concurrency: 1` on command queue + `rateLimit` per command + Bucket4j |
| Secret leak via logs | yes | StartupBanner masks usernames; no passwords logged |
| Secret leak via Git | yes | `.env` and rendered K8s secrets gitignored; only templates committed |
| Container image tampering | partial | Pinned image tag (no `:latest`); registry auth required |
| Compromise of the Solace broker | out | Mitigated at the Solace layer (out of scope for MI) |
| Compromise of cluster control plane | out | Cluster-level security is the operator's concern |

V2 will add: mTLS at the REST surface, OIDC for human
operators, image signing and admission policy enforcement.

## Authentication

REST + Actuator authentication is HTTP Basic, gated by
`topic-compaction.security.enabled` (Phase 4.1).

Two roles, both backed by an in-memory user store:

| Role | Default username | Permissions |
|---|---|---|
| `USER` | `mi-user` | `GET /api/v1/kv/...` (read, list) |
| `ADMIN` | `mi-admin` | `USER` + `DELETE /api/v1/kv/...` + `/api/v1/admin/*` + actuator endpoints other than health/prometheus |

Always public:

- `/actuator/health` (incl. `/liveness` and `/readiness`) - K8s
  probes.
- `/actuator/prometheus` - Prometheus operator scraping.

Both rely on NetworkPolicy to restrict who can reach them in the
first place.

Credential rotation:

```bash
$EDITOR .env       # change MI_USER_PASSWORD / MI_ADMIN_PASSWORD
make k8s-deploy    # re-render Secret + apply
make k8s-restart   # pod picks up new env values
```

## Network controls

NetworkPolicy in `70-networkpolicy.yaml`:

**Ingress** -- allow only:

- The `monitoring` namespace (Prometheus scraping).
- Same namespace `mi-solace-lab` (other MIs, port-forward via
  the dev's local proxy).

**Egress** -- allow only:

- `kube-system` UDP/TCP 53 (DNS).
- `monitoring` namespace TCP 4317 (OTLP gRPC to Tempo).
- Public CIDR with port restrictions (Solace Cloud SMF / REST /
  SEMP) - private RFC1918 ranges excluded.

The Pod Security Admission level for the namespace is
`restricted`, which enforces the pod-level controls below.

## Pod-level hardening

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  fsGroup: 1000
  seccompProfile:
    type: RuntimeDefault

containers:
  securityContext:
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    capabilities:
      drop: ["ALL"]
```

- Non-root: the JVM runs as UID 1000.
- Read-only root filesystem: no run-time tampering. RocksDB
  writes go to a PVC at `/var/lib/topic-compaction`; transient
  files go to a `tmp` emptyDir mount.
- All Linux capabilities dropped.
- seccomp default profile (Kubernetes' RuntimeDefault).

## Secrets handling

- Real values live ONLY in the Kubernetes `Secret` (rendered
  from `20-secret.yaml.template` at deploy time) and in
  `.env` for local dev. Both are gitignored.
- Only template files are checked in.
- The container reads via `envFrom: secretRef` so values are
  injected as environment variables (not mounted as files).
- The StartupBanner logs resolved configuration with usernames
  masked (e.g. `m***`); passwords are never logged.

## Dependency hygiene

- Spring Boot starter parent provides curated dependency
  versions.
- `maven-enforcer-plugin` checks `requireUpperBoundDeps` to
  prevent silent transitive downgrades.
- `flatten-maven-plugin` scrubs the published POM of build-time
  metadata.
- Dependencies surveyed on each release: as of V1.0 the
  Spring Boot stack pulls Spring Security 6.x, OpenTelemetry
  1.51, RocksDB 9.7, Bucket4j 8.14.

## Input validation

- REST path / query params: `IllegalArgumentException` thrown
  on invalid `format` and `limit` values; mapped to RFC-7807
  problem details by `RestExceptionHandler`.
- Command JSON: validated against
  `schemas/command-event-v1.json` before mapping. Schema
  violations land on `topic-compaction/replay/failed`.
- Solace pattern: `SolacePatternMatcher` throws
  `IllegalArgumentException` on malformed patterns (e.g. `>` not
  at the end), surfaced as a failure summary on
  `bulk-result`.
- Backup restore: format-version check on the header line;
  malformed records counted as `skipped` and logged at WARN.

## Backup / restore safety

- Backup is admin-only (`/api/v1/admin/backup` requires the
  `ADMIN` role).
- The streaming format is line-delimited JSON; payloads are
  base64-encoded so binary bodies survive UTF-8 transcoding.
- Restore wipes existing keys before loading. There is no
  read-only mode in V1.0; operators must isolate the MI from
  inbound traffic before running a production restore (e.g.
  scale producers to zero).

## Logging hygiene

- Profile `k8s` / `prod` emits JSON via the Logstash Logback
  Encoder. Stdout is the only sink.
- MDC fields include `traceId` / `spanId` (for correlation
  with Tempo) and `service` / `key` / `command` (for filtering
  in Loki). No passwords or full payloads are logged.
- The actuator `env` endpoint masks values by default
  (`management.endpoint.env.show-values=WHEN_AUTHORIZED`).

## Known V1.0 limitations

- HTTP only at the MI listener. Use cluster Ingress with
  TLS termination for external exposure. mTLS at the MI itself
  is on the V2 roadmap.
- In-memory user store does not support per-user rotation
  without a pod restart; OIDC is on the V2 roadmap.
- Image is not signed. Admission policy enforcement (cosign,
  Kyverno) is a cluster-level concern handled by
  `solace-lab-infrastructure` and is not part of V1.0.

## Reporting a vulnerability

Internal: open an issue against the
`solace-demo-artifacts` repository with the label `security`.
For demo purposes the public repo is the right channel; in a
production deployment the standard Solace responsible-disclosure
process applies.

## Related

- ADR 0004 -- REST authentication and role model
- `docs/CONFIGURATION.md` -- security properties reference
- `docs/OPERATIONS.md` -- credential rotation runbook
- `solace-lab-infrastructure/pki` -- cluster PKI (future mTLS)
