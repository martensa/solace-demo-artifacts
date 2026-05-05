# ADR 0003: Kubernetes Deployment Topology

- Status: Accepted
- Date: 2026-05-05
- Deciders: Topic Compaction MI maintainers
- Related: ADR 0001 (architecture), ADR 0002 (no HA in V1)

## Context

V1.0 ships two deployment modes from a single image:

- docker-compose for local development.
- Kubernetes for the lab (and any production-shaped target).

The Kubernetes side needs decisions on namespace placement,
hardening posture, monitoring integration, and lifecycle scripting.
This ADR records those.

## Decision

### Namespace

A new namespace `mi-solace-lab` hosts all current and future MIs in
the demo cluster. The Topic Compaction MI is its first tenant.
Reasons for a dedicated namespace rather than reusing
`sam-solace-lab-shared`:

- Each MI is a logical layer of its own (orthogonal to SAM agents
  and the SAM platform).
- Per-namespace ResourceQuota and NetworkPolicy are cleaner.
- The Pod Security Admission level can be set to `restricted`
  cluster-wide for MIs without affecting SAM agents (which may need
  a more permissive level).

### Pod hardening

The deployment runs the container with the strict-mode posture:

- `runAsNonRoot: true`, `runAsUser: 1000`, `fsGroup: 1000`.
- `readOnlyRootFilesystem: true`. RocksDB writes go to a PVC at
  `/var/lib/topic-compaction/rocksdb`; transient files go to a
  `tmp` emptyDir.
- `allowPrivilegeEscalation: false`, `capabilities: drop ALL`.
- `seccompProfile: RuntimeDefault`.

### Storage

A 10 Gi `ReadWriteOnce` PVC backs the RocksDB store. The Deployment
uses `strategy: Recreate` (not RollingUpdate) because the volume is
RWO and a second pod cannot mount it during a rollout. The trade-off
is a brief unavailability window during deploys, which is acceptable
because (a) Solace queues persist messages while the pod is down,
and (b) the MI is single-replica per ADR 0002 anyway.

### Network policy

Default-deny is achieved by the `restricted` PodSecurity level plus
an explicit `NetworkPolicy`. Allowed traffic:

- Ingress: monitoring namespace (Prometheus scraping), intra-MI
  namespace (other MIs / port-forward).
- Egress: kube-dns, in-cluster Tempo (4317/TCP), and Solace Cloud
  ports (55555 SMF, 55443 SMF/TLS, 9000/9443 REST, 943 SEMP) via
  cluster egress with private-range exceptions.

### Monitoring artifacts in the monitoring namespace

The `ServiceMonitor` and `PrometheusRule` are deployed into the
`monitoring` namespace with the `prometheus: kube-prometheus` label
so the operator picks them up. They cross-namespace-select the
service via `namespaceSelector: matchNames: [mi-solace-lab]`.

Grafana dashboards (introduced in Phase 6) follow the same pattern -
ConfigMap labelled `grafana_dashboard: "1"` in the `monitoring`
namespace.

The teardown script removes these artifacts as part of the normal
`stop.sh` flow so the monitoring namespace stays clean when the MI
is retired.

### Configuration model

Three config layers, lowest to highest precedence:

1. In-image `application.yml` (defaults, never operator-edited).
2. Mounted `application.yml` from a `ConfigMap`
   (`/app/external/spring/config/application.yml`).
3. Environment variables from a `Secret` (`envFrom` reference).

Sensitive values (`SOLACE_*` credentials, REST `MI_USER_*` /
`MI_ADMIN_*`) live only in the `Secret`, which is rendered from
`20-secret.yaml.template` at deploy time. The rendered file is
gitignored.

### Image tag policy

Releases are tagged `1.x.y` and pushed to
`registry.solace.lab/sam-topic-compaction-mi`. The image tag in
`40-deployment.yaml` is pinned (no `:latest`); `imagePullPolicy:
IfNotPresent` for build determinism.

## Consequences

### Positive

- Clean per-MI isolation in `mi-solace-lab`.
- Hardened pod posture out of the box.
- Single-replica simplicity matches ADR 0002 and the V1.0 scope.
- Monitoring artifacts ship with the workload, so observability is
  not bolted on after deployment.

### Negative / Trade-offs

- `strategy: Recreate` causes a short outage on rollouts. Mitigated
  by Solace queue persistence.
- Egress NetworkPolicy is permissive (broad public-CIDR allow with
  port restrictions). A tighter rule set would require knowing the
  exact Solace Cloud egress IPs, which can change. Trade-off:
  current rule prevents east-west exfiltration, which is the more
  realistic threat in this lab.

## Alternatives Considered

- **Reuse `sam-solace-lab-shared`**: rejected to avoid coupling MIs
  to SAM lifecycle.
- **Helm chart instead of raw manifests + script**: more idiomatic
  but adds a Helm dependency for a simple single-deploy use case.
  Revisit if the MI grows multi-tenant.
- **`StatefulSet` instead of `Deployment` + PVC**: the StatefulSet
  is the canonical home for stateful single-replica workloads. We
  chose `Deployment` for simplicity (no need for stable network
  identity, no need for ordered rolling updates with single
  replica). May revisit when V2 introduces HA.
- **Distroless base image**: would harden further. Current Eclipse
  Temurin base is acceptable for V1; revisit in a future iteration.

## References

- `deploy/k8s/` for the full manifest set.
- `deploy/k8s/scripts/start.sh`, `stop.sh` for the deploy/teardown
  flow.
- `docs/OPERATIONS.md` (added in Phase 6) for the runbook.
