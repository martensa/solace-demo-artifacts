# CLAUDE.md - Topic Compaction Micro-Integration

This file contains agentic context specific to the Topic Compaction MI
sub-project. It complements the root `CLAUDE.md` of `solace-demo-artifacts`
which covers the broader demo environment.

## Project Overview

A Solace Micro-Integration that maintains a key-value store of last-seen
messages per Solace topic and supports on-demand replay (single + bulk),
synchronous request/reply lookup, retention/TTL eviction, and
backup/restore. A Solace-native alternative to Kafka log compaction.

Status: targeting v1.0.0 (production-ready, no HA - HA is V2).

## Build / Test / Run

All commands assume cwd = `micro-integrations/topic-compaction/`.

```bash
make env-init           # one-time: copy .env.example to .env
make env-check          # verify .env has required keys
make build              # ./mvnw clean package -DskipTests
make test               # ./mvnw test (full unit + integration)
make image              # build container image via jib (local Docker)
make up                 # docker compose up -d
make logs               # tail MI logs
make smoke              # end-to-end smoke test
make down               # docker compose down (preserves volumes)
make clean              # down + remove volumes + remove target/
```

K8s deployment (V1.0 phase 5+):

```bash
make k8s-deploy         # idempotent: apply all manifests + monitoring
make k8s-status         # show pods, services, monitor status
make k8s-logs           # tail pod logs
make k8s-port-forward   # forward 18090 -> service:8090
make k8s-undeploy       # idempotent: remove all manifests + monitoring
```

## Architecture (high level)

Three workflows over Solace bindings, plus a REST surface and an admin
surface:

| Workflow | Input queue (default subscription) | Output |
|----------|------------------------------------|--------|
| 0 - Compaction | `compaction.data` (`orders/>`) | `<topic>/compacted-ack` audit |
| 1 - Replay | `compaction.commands` (`compacted/command/>`) | `<key>/compacted` |
| 2 - Lookup | `compaction.lookup` (`compacted/lookup/>`) | reply-to of request |

Plus:

| Surface | Endpoint | Notes |
|---------|----------|-------|
| REST KV | `:8090/api/v1/kv/...` | Direct lookup/list/delete |
| REST Admin | `:8090/api/v1/admin/...` | Backup/restore, retention |
| Actuator | `:8090/actuator/...` | Health, metrics, prometheus |

State: RocksDB on local disk, mounted as a PVC in K8s deployment.

For full architecture details and sequence diagrams, see
`docs/ARCHITECTURE.md`.

## Naming Conventions

### Workflow IDs

- `0` - Compaction
- `1` - Replay (single + bulk via same workflow, branching by command)
- `2` - Lookup
- `3-7` - reserved for V2 expansion (do not use without ADR)

### Topic Patterns (defaults; configurable per deployment)

- Data ingress: `orders/>` (operator-tunable)
- Audit egress: `<original-topic>/compacted-ack`
- Replay egress: `<key>/compacted`
- Replay command ingress: `compacted/command/>`
- Lookup request ingress: `compacted/lookup/>`
- Bulk-replay summary: `topic-compaction/replay/bulk-result`
- Replay failures: `topic-compaction/replay/failed`

### Metric Names

All metrics are prefixed `topic_compaction_` (snake_case for Prometheus).
See `docs/OBSERVABILITY.md` for the full reference and tag conventions.

### Java Package Layout

```text
com.solace.labs.mi.topiccompaction
  + TopicCompactionApplication       Entry point
  + api          REST controllers + error handling
  + command      Command-event DTOs and JSON Schema validation
  + compaction   Workflow 0 - inbound message compaction
  + kvstore      RocksDB / Caffeine backends + record codec
  + lookup       Workflow 2 - request/reply lookup
  + metrics      Micrometer counters and gauges
  + replay       Workflow 1 - replay logic (single + bulk)
  + retention    TTL / retention policy enforcement
  + admin        Backup / restore tooling
  + observability Tracing config + OTel customizers
  + security     Spring Security config + REST auth
  + provisioning SEMP-driven queue auto-provisioning
```

## Common Pitfalls

### Spring URL-encoded slashes

Spring's default `MatchingStrategy` does not handle URL-encoded slashes
(`%2F`) in path variables - it returns 400. The MI uses
`@GetMapping("/{*key}")` (PathPattern style) on `KvStoreController` to
accept multi-segment keys via the path. URL-encoding is still required for
`%` or other reserved chars but slashes pass through cleanly.

### MI Framework Meter Registry

The MI Framework registers a `NoOpMeterRegistry` as the primary
`MeterRegistry`. Without intervention, `/actuator/prometheus` returns an
empty payload. The fix is in `observability.MetricsConfig`:

- Register `PrometheusMeterRegistry` as `@Primary` with
  `@Order(Ordered.HIGHEST_PRECEDENCE)`
- Re-enable Prometheus export specifically:
  `management.prometheus.metrics.export.enabled: true`
- Keep the global `management.defaults.metrics.export.enabled: false`
  to avoid accidentally enabling other registries

### Solace `solace_destination` header

Both `CompactionService` and `LookupService` rely on the
`solace_destination` user property to learn the inbound topic. If a
producer publishes via SMF without setting it, compaction silently skips
the message. The metric `topic_compaction_skipped_total{reason="no_topic"}`
flags this; alert on a non-zero rate.

### Loop Protection

Replays are tagged with `x-compacted-replay: true` (configurable via
`topic-compaction.compaction.loop-protection-header`). The compaction
service drops messages bearing this header to avoid infinite republish
loops. Do not rename this header without a coordinated upgrade across
producers and consumers - it is part of the wire protocol.

### MI SDK 3.0.6 Auto-Configuration Quirk

`RequiresTransformEnabledConfigurationValidation` is auto-registered by
`ConfigurationValidationAutoConfiguration` in 3.0.6. Declaring it as an
explicit bean causes `BeanDefinitionOverrideException`. The PDF guide is
out of date - rely on the auto-config.

### Spring Cloud Stream Reserved Headers

`filterAndCopy(...)` in `CompactionService` strips `id`, `timestamp`,
`deliveryAttempt`, and any `scst_*` headers before persisting to the KV
store. Without this, Spring Cloud Stream attempts to recreate them on
replay and conflicts.

### RocksDB Path Inside Read-Only Root Filesystem

The K8s pod sets `readOnlyRootFilesystem: true`. RocksDB writes go to
`/var/lib/topic-compaction` (mounted as PVC). Default config in
`application.yml` is `./data/rocksdb` which is fine for docker-compose
but is overridden in the K8s ConfigMap to the absolute mount path.

## Testing

- Unit tests: `./mvnw test` (61+ in V1.0)
- Integration tests: Testcontainers-based, run with `mvn verify` (Phase 7)
- Smoke test: `./examples/smoke-test.sh` - end-to-end against any broker
- Load test: `./examples/load-test.sh` - sdkperf wrapper (Phase 7)

CI/CD note: there is no CI pipeline yet. Run `make test && make smoke`
locally before tagging a release.

## ADRs

Architecture Decision Records live in `docs/adr/`. Read them in number
order to understand why the current design looks the way it does. Add a
new ADR for any non-trivial decision (data format change, new external
dependency, security model change).

## Related Repositories

- `solace-lab-infrastructure` - K8s base infra (PKI, registry, ingress)
- `solace-demo-artifacts/agent-mesh-deployment` - SAM platform
- `solace-sam-artifacts` - SAM agent definitions
- This MI lives in `solace-demo-artifacts/micro-integrations/topic-compaction/`

## Code Style

- ASCII-only in source files (no unicode dashes, arrows, umlauts)
- English for code, comments, docstrings, and tests
- German is acceptable in operator-facing log messages and runbooks
- Keep markdown linted - lines under 80 chars (MD013), no bare URLs
  (MD034), no HTML (`npx markdownlint-cli docs/*.md *.md`)
- Conventional Commits for git history (`feat:`, `fix:`, `docs:`, etc.)
