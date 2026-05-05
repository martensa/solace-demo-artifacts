# ADR 0001: Baseline Architecture

- Status: Accepted
- Date: 2026-05-05
- Deciders: Topic Compaction MI maintainers

## Context

The Topic Compaction Micro-Integration is the first Solace MI in the
`solace-demo-artifacts` repository. It needs a clear architectural
baseline that future ADRs can amend.

The MI must, at minimum:

- Persist the latest message per Solace topic in a key-value store.
- Republish the stored payload on demand via a command event.
- Answer synchronous lookup requests via Solace Request/Reply.
- Expose a REST surface for direct lookups and operational use.
- Run as a single Spring Boot application packaged as a container.

## Decision

We adopt the following architecture for v1.x:

### Workflows

Three Solace workflows backed by Spring Cloud Stream bindings:

1. **Compaction** - inbound queue subscribed to a configurable topic
   pattern (default `orders/>`). Each message is upserted into the KV
   store keyed by the inbound Solace destination. An audit event is
   published to `<topic>/compacted-ack`.
2. **Replay** - inbound queue subscribed to `compacted/command/>`. The
   payload is parsed as a JSON command. For `REPLAY` the stored payload
   for the requested key is republished to `<key>/compacted` with a
   loop-protection header. Bulk-replay and `DELETE` are added in
   subsequent ADRs.
3. **Lookup** - inbound queue subscribed to `compacted/lookup/>`. Each
   request is treated as Solace Request/Reply: the MI loads the stored
   record and replies on the request's `replyTo`.

### Storage Backend

RocksDB on local disk. Persistent across pod restarts when run on K8s
with a PersistentVolumeClaim. A Caffeine in-memory backend is available
as a development convenience but is not the default. Both backends share
a common `KvStore` interface.

The stored value is a `CompactedRecord` containing the payload, original
headers (filtered), original topic, ingest timestamp, and optional
sender timestamp.

### REST Surface

Spring Boot Web exposes a versioned REST API at `/api/v1/kv/...` for
direct read/list/delete. Spring Boot Actuator exposes operational
endpoints under `/actuator/...` (health, metrics, prometheus).

### Observability

Three pillars, each routed to the cluster-internal LGTM stack:

- Metrics via Micrometer Prometheus to the kube-prometheus stack.
- Logs as JSON to stdout, harvested by Promtail/Grafana-Agent into Loki.
- Traces via OpenTelemetry OTLP gRPC to Tempo.

Trace IDs are propagated into the logging MDC for cross-pillar
correlation.

### Configuration Strategy

Internal defaults live in `src/main/resources/application.yml` (packed
into the image, not operator-editable). Operator overrides are loaded
from `/app/external/spring/config/application.yml` mounted at runtime by
docker-compose or by a Kubernetes ConfigMap. Sensitive values come from
environment variables backed by `.env` (docker-compose) or a `Secret`
(K8s).

### Deployment Targets

Two supported deployment modes from the same image:

- docker-compose for local development. The broker is external (Solace
  Cloud or any reachable PubSub+).
- Kubernetes with a curated manifest set in `deploy/k8s/` for the
  `mi-solace-lab` namespace. Monitoring artifacts (ServiceMonitor,
  PrometheusRule, Grafana dashboard ConfigMap) are deployed alongside
  the application and removed on teardown.

### Build and Release

Maven with the MI Framework parent POM. Image built via the Jib Maven
plugin (no Dockerfile, reproducible layered image). Tagged releases of
form `1.x.y`; release notes maintained in `CHANGELOG.md`.

## Consequences

### Positive

- Each workflow is independently testable via its own input queue.
- Stateless code paths around the `KvStore`; tests exercise the store
  via a contract test.
- Single binary with two deployment modes simplifies the dev loop.
- Observability is wire-up-once through standard Spring Boot mechanisms.

### Negative / Trade-offs

- Single-replica deployment in v1.x means a pod restart drops in-flight
  Solace ACKs and pauses replay/lookup until the new pod is ready. HA
  is intentionally deferred to V2 (see ADR 0002).
- RocksDB on a single PVC is a single point of failure for state. Backup
  and restore tooling (introduced in a later ADR) is the v1.x mitigation.

## Alternatives Considered

- **Kafka Connect compaction** - would couple the MI to Kafka and lose
  the Solace-native advantages (immediate compaction, hierarchical topic
  wildcards, request/reply lookup).
- **Embedded H2 instead of RocksDB** - rejected for write throughput.
  RocksDB is purpose-built for this workload.
- **Pure in-memory** - rejected for state durability across restarts.
  Caffeine backend remains as a dev convenience.

## References

- `README.md` for user-facing overview.
- `docs/ARCHITECTURE.md` for runtime sequence diagrams.
- `docs/DIFFERENTIATORS.md` for the Kafka log-compaction comparison.
