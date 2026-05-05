# Topic Compaction Micro-Integration

A Solace Micro-Integration that maintains a key-value store of the
last-seen message per Solace topic, with on-demand single + bulk
replay, synchronous request/reply lookup, REST admin surface,
TTL retention, and streaming backup/restore. A Solace-native
alternative to Kafka log compaction.

> **Built on**: Solace MDK 3.0.6 + Spring Boot 3.5 + Spring Cloud
> Stream Solace binder + RocksDB.
>
> **Status**: V1.0.0 -- production-ready single-replica deployment
> on Kubernetes. HA is a V2 deliverable (see ADR 0002).

## What it does

| Workflow | Input | Action | Output |
|---|---|---|---|
| **0 - Compaction** | `compaction.data` (default sub: `orders/>`) | Stores latest message per topic in RocksDB | `<topic>/compacted-ack` audit JSON |
| **1 - Replay (single)** | `compaction.commands` (`compacted/command/>`) | Looks up KV, republishes | `<key>/compacted` |
| **1 - Bulk replay** | same | Pattern-iterates, fans out via output-3, throttled | `<key>/compacted` per match + summary on `topic-compaction/replay/bulk-result` |
| **1 - Delete** | same | Tombstones key (+ optional cascade pattern) | `topic-compaction/delete/result` |
| **2 - Lookup** | `compaction.lookup` (`compacted/lookup/>`) | Solace Request/Reply | `solace_replyTo` of the request |
| **REST KV** | HTTP `:8090/api/v1/kv` | Direct GET/list/DELETE | JSON / raw payload |
| **REST Admin** | HTTP `:8090/api/v1/admin` | Streaming backup / restore | NDJSON |
| **Retention** | scheduled sweeper | Per-prefix TTL eviction | metric increments |

## Why this exists

See `docs/DIFFERENTIATORS.md` for the full comparison vs Kafka log
compaction. Highlights:

- **Immediate compaction** (no eventual cleanup background process)
- **Direct O(1) lookup** via REST and Solace Request/Reply
- **Pattern-based bulk replay** for cache-warmup / disaster recovery
- **Per-prefix TTL retention** instead of a single topic-level knob
- **Streaming backup / restore** with a versioned NDJSON format
- **Hierarchical topic ingestion** via Solace wildcards (`orders/>`)

## Two deployment modes

### docker-compose (local / dev)

```bash
make env-init         # cp .env.example .env
$EDITOR .env          # broker creds, optional REST auth
make build            # mvn package
make image            # build container via jib
make up               # docker compose up -d
make smoke            # 10 assertions, exit 0 on success
make down             # tear down (volumes preserved)
```

### Kubernetes (lab / production-shaped)

```bash
make k8s-deploy       # idempotent: namespace, ConfigMap, Secret,
                      # PVC, Deployment, Service, NetworkPolicy,
                      # ServiceMonitor, PrometheusRule,
                      # Grafana dashboard
make k8s-status       # pods, svc, pvc, monitoring
make k8s-logs         # tail JSON logs
make k8s-port-forward # 18090 -> service:8090
make k8s-undeploy     # tear down (PVC + namespace preserved)
make k8s-undeploy-purge   # full teardown including PVC
```

The K8s overlay deploys the MI to namespace `mi-solace-lab`, with
hardened pod (non-root, read-only-rootFS, dropped capabilities,
seccomp), 10 Gi PVC, NetworkPolicy + PodDisruptionBudget. The
monitoring artifacts (ServiceMonitor, PrometheusRule, Grafana
dashboard) deploy into the cluster's `monitoring` namespace
alongside the kube-prometheus stack. See ADR 0003 for the
topology decisions.

## V1.0 features at a glance

| Phase | Feature |
|---|---|
| 0 | `CLAUDE.md`, `CHANGELOG.md`, ADRs, branch `release/v1.0.0` |
| 1 | REST `/{*key}` PathPattern, RFC-7807 error handler, Prometheus endpoint export |
| 2 | Structured JSON logs (Logstash encoder), OpenTelemetry tracing, manual spans + MDC, `docs/OBSERVABILITY.md` |
| 3 | JSON-Schema validated commands, `BULK_REPLAY` with rate limit, `DELETE` (single + cascade), per-prefix TTL retention, streaming backup/restore |
| 4 | REST auth (USER + ADMIN), SEMP-driven queue provisioning, graceful shutdown, startup banner, command-queue concurrency |
| 5 | K8s manifests, ServiceMonitor + PrometheusRule, NetworkPolicy, PDB, idempotent `start.sh` / `stop.sh`, ADRs 0003 + 0004 |
| 6 | SLO recording rules + alerts, Grafana dashboard, `docs/OPERATIONS.md` runbook, ADR 0005 |
| 7 | JaCoCo coverage threshold, integration test suite, non-interactive smoke test, load harness, `docs/PERFORMANCE.md` |
| 8 | Comprehensive doc pass: ARCHITECTURE, CONFIGURATION, SECURITY, DIFFERENTIATORS, SMOKE-TEST, README updates |

## Make targets

```text
Setup
  env-init              Copy .env.example to .env (run once)
  env-check             Verify .env exists and has required keys
  provision-queues      Run examples/init-queues.sh against your broker

Build
  build                 ./mvnw clean package
  test                  ./mvnw test (unit + integration)
  verify                ./mvnw verify (test + coverage check)
  coverage              Open the JaCoCo HTML report
  image                 Build container image into local Docker daemon

Run (docker-compose)
  up                    Start the MI
  down                  Stop the MI (keeps volumes)
  restart               Restart only the MI container
  logs                  Tail MI logs
  status                docker compose ps

Test
  smoke                 Run the end-to-end smoke test
  load-test             Drive synthetic load + sample metrics

Cleanup
  clean                 Down + remove volumes + remove target/

Kubernetes
  k8s-deploy            Idempotent deploy to mi-solace-lab
  k8s-status            Show pod / svc / pvc / monitoring
  k8s-logs              Tail MI logs
  k8s-port-forward      Forward 18090 -> service:8090
  k8s-restart           Rollout restart the deployment
  k8s-undeploy          Remove workload + monitoring; keep PVC
  k8s-undeploy-purge    Remove everything incl. PVC + namespace
```

## Documentation map

| Document | Purpose |
|---|---|
| `CLAUDE.md` | Agentic context for the sub-project (build/test, naming, pitfalls) |
| `CHANGELOG.md` | Per-release entries (Keep a Changelog format) |
| `docs/ARCHITECTURE.md` | Components, workflows, data flow, lifecycle (Mermaid) |
| `docs/CONFIGURATION.md` | Full property reference, all phases |
| `docs/COMMAND-EVENTS.md` | Replay / Bulk / Delete command JSON schema + examples |
| `docs/OBSERVABILITY.md` | Metrics, logs, traces; LGTM stack integration |
| `docs/OPERATIONS.md` | On-call runbook, SLO definitions, alert response |
| `docs/SECURITY.md` | Threat model, controls, secrets handling |
| `docs/PERFORMANCE.md` | Baseline numbers, bulk-replay benchmark, capacity planning |
| `docs/DIFFERENTIATORS.md` | Comparison vs Kafka log compaction |
| `docs/SMOKE-TEST.md` | E2E test guide; `examples/smoke-test.sh` |
| `docs/adr/0001-architecture.md` | Baseline architecture |
| `docs/adr/0002-no-ha-in-v1.md` | HA deferred to V2 |
| `docs/adr/0003-k8s-deployment.md` | K8s topology |
| `docs/adr/0004-rest-auth-roles.md` | REST role model |
| `docs/adr/0005-slo-and-alert-strategy.md` | SLO + alert design |

## Repository layout

```text
topic-compaction/
+-- Makefile
+-- pom.xml
+-- .env.example
+-- src/
|   +-- main/java/com/solace/labs/mi/topiccompaction/
|   |   +-- TopicCompactionApplication.java
|   |   +-- admin/                REST admin surface (backup/restore)
|   |   +-- api/                  REST KV controller + Spring config
|   |   +-- command/              Command DTO, parser, JSON schema
|   |   +-- compaction/           Workflow 0 implementation
|   |   +-- delete/               DELETE command service
|   |   +-- kvstore/              RocksDB / Caffeine backends + codec
|   |   +-- lookup/               Workflow 2 (request/reply)
|   |   +-- metrics/              Micrometer counters + gauges
|   |   +-- observability/        Metrics + tracing + startup banner
|   |   +-- provisioning/         SEMP-driven queue creation
|   |   +-- replay/               Workflow 1 (single + bulk + matcher)
|   |   +-- retention/            TTL sweeper
|   |   +-- security/             Spring Security config + properties
|   +-- main/resources/
|   |   +-- application.yml       Internal defaults
|   |   +-- logback-spring.xml    Profile-aware logging
|   |   +-- schemas/command-event-v1.json
|   +-- test/                     105 unit + 6 integration tests
+-- deploy/
|   +-- docker-compose/           compose.yaml + mi-config overlay
|   +-- k8s/                      00 .. 82 manifests + start.sh/stop.sh
+-- docs/                         12 doc files + 5 ADRs (see above)
+-- examples/
    +-- command-events/           sample command JSON
    +-- init-queues.sh            SEMP queue provisioning
    +-- smoke-test.sh             non-interactive E2E test
    +-- load-test.sh              synthetic load harness
```

## Tests

```bash
./mvnw test               # 111 tests (105 unit + 6 integration)
./mvnw verify             # adds JaCoCo coverage check
make smoke                # broker-integrated 10-assertion check
make load-test            # bash + curl harness
```

End-to-end testing is documented in `docs/SMOKE-TEST.md`.

## V1.x backlog

Items deliberately deferred from V1.0 (with rationale in CHANGELOG):

- High availability via active-standby + state replication
  (ADR 0002).
- Testcontainers-based end-to-end tests with a real Solace
  broker (replaces the smoke-test.sh approach for CI).
- sdkperf-based load harness for sustained > 500 msg/s.
- Per-workflow latency histograms separate from the generic
  Spring `http.server.requests` series.
- mTLS at the REST listener (HTTP today; Ingress TLS termination
  is the V1 pattern).
- OIDC for human operators (in-memory user store today).

## License

This project is shipped as a demo artifact alongside the
`solace-demo-artifacts` repository. Refer to that repository's
license for redistribution terms.
