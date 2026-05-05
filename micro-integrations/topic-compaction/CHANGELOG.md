# Changelog

All notable changes to the Topic Compaction Micro-Integration are
documented in this file.

The format is based on [Keep a Changelog][kac], and this project adheres
to [Semantic Versioning][semver].

[kac]: https://keepachangelog.com/en/1.1.0/
[semver]: https://semver.org/spec/v2.0.0.html

## [Unreleased]

### Added

- Phase 0: project skeleton for v1.0.0 - dedicated `CLAUDE.md`,
  `CHANGELOG.md`, `.markdownlint.json`, and the ADR directory with
  `0001-architecture.md` and `0002-no-ha-in-v1.md`.
- Phase 1: REST controller now accepts both unencoded multi-segment
  paths (`/api/v1/kv/orders/created/A`) and URL-encoded slashes
  (`/api/v1/kv/orders%2Fcreated%2FA`). Implementation switches the
  mapping to Spring `PathPattern` style `/{*key}` and decodes any
  remaining percent-encoded chars in the controller.
- Phase 1: `RestExceptionHandler` (`@ControllerAdvice` scoped to the
  API package) translates known exceptions into RFC-7807
  `application/problem+json` responses with consistent title and
  detail fields.
- Phase 1: programmatic input validation on REST path and query
  parameters (`format`, `limit`) raises `IllegalArgumentException`
  which the exception handler converts to 400 problem details.
- Phase 1: `observability.MetricsConfig` registers a `@Primary`
  `PrometheusMeterRegistry` that shares the auto-configured
  `PrometheusRegistry`, so `/actuator/prometheus` exposes the MI's
  Micrometer counters and gauges. Common tags `application`,
  `version`, `namespace` are attached via a `MeterFilter`.
- Phase 1: `api.WebServerConfig` relaxes the Tomcat connector to
  `passthrough` encoded-solidus handling, and `api.HttpFirewallConfig`
  configures `StrictHttpFirewall` to allow URL-encoded slashes - both
  required for legacy clients sending `%2F` in path variables.
- Phase 1: liveness and readiness health groups (`/actuator/health/
  liveness`, `/actuator/health/readiness`). Readiness includes the
  Solace binder so Kubernetes holds traffic until bindings are UP.
- Phase 2: structured JSON logging via `logstash-logback-encoder`
  under the `k8s` and `prod` Spring profiles; pretty single-line
  console under `dev` and the default profile. MDC fields include
  `traceId`, `spanId`, `service`, `key`, and `command`.
- Phase 2: OpenTelemetry tracing pipeline with OTLP gRPC exporter.
  `application.yml` defaults the endpoint to `localhost:4317` so a
  missing collector does not crash the app; the K8s ConfigMap
  overrides to the in-cluster Tempo service.
- Phase 2: `observability.TracingConfig` registers the AOP aspects
  (`ObservedAspect`, `TimedAspect`, `CountedAspect`) so the Micrometer
  annotations on workflow entry points actually create spans.
- Phase 2: `@Observed` annotations on `CompactionService.compact`,
  `ReplayService.process`, and `LookupService.resolve` create the
  workflow-level spans. `MDC.MDCCloseable` populates structured
  context (`service`, `key`, `command`) for the duration of each call.
- Phase 2: `docs/OBSERVABILITY.md` -- metric reference, log schema,
  trace topology, configuration matrix, and troubleshooting table.
- Phase 2: 6 new `KvStoreControllerTest` cases exercising
  url-encoded keys, embedded slashes, the `?format=meta` query
  parameter, and limit-validation rejection.

### Changed

- Phase 1: `KvStoreController` mappings moved from `/{key}` and
  `/{key}/meta` to a single `/{*key}` with optional `?format=meta`
  query parameter. The `/meta` sub-path is removed (was already
  broken for slashed keys). See migration note below.
- Phase 1: `application.yml` keeps `management.defaults.metrics.export.
  enabled: false` and adds `management.prometheus.metrics.export.
  enabled: true` so Prometheus is the only registered exporter.
- Phase 1: actuator endpoint `prometheus` exposed read-only (Spring
  Boot 3 `access: read_only` style).

### Security

- Phase 1: explicit `StrictHttpFirewall` configuration in
  `HttpFirewallConfig` allows URL-encoded slashes only. All other
  hardening defaults (encoded percent-encoded chars, control
  characters, encoded period) remain in effect. Documented as safe
  in V1 because captured keys are never used as filesystem paths or
  shell arguments.
- (Full REST authentication arrives in Phase 4.)

### Migration Notes

- The legacy `GET /api/v1/kv/{key}/meta` endpoint is replaced by
  `GET /api/v1/kv/{key}?format=meta`. Operations scripts that hit the
  old path must be updated. Both URL-encoded and unencoded slashes
  are supported in the new mapping.

### Phase 3 - new commands and operations

#### Added

- Phase 3.1: JSON-Schema validation for command events. Schema lives
  at `src/main/resources/schemas/command-event-v1.json`, version 1.
  `CommandEventParser` validates inbound JSON before mapping it to
  `CommandEvent`; schema violations result in a structured failure
  document on `topic-compaction/replay/failed`.
- Phase 3.1: `pattern` field on `CommandEvent` (used by
  `BULK_REPLAY`); the legacy 3-argument constructor is preserved as
  an overload for backward compatibility with existing tests.
- Phase 3.2: `BULK_REPLAY` command. Iterates the KV store using a
  `SolacePatternMatcher` (Solace topic-style wildcards `*` and `>`)
  and republishes the latest record of every match via the
  `output-3` fanout binding. Throughput is capped by an optional
  client-supplied `rateLimit` (default 1000 msg/s; Bucket4j).
  Results in a JSON summary on
  `topic-compaction/replay/bulk-result`.
- Phase 3.2: `SolacePatternMatcher` with RocksDB prefix-iterator
  optimisation (longest non-wildcard prefix used as seek key).
- Phase 3.3: `DELETE` command. Single-key tombstone plus optional
  `options.cascade` Solace pattern for bulk delete. Result event on
  `topic-compaction/delete/result`.
- Phase 3.3: `topic_compaction_deletes_total` counter tracks all
  records tombstoned via the command path or the REST DELETE.
- Phase 3.4: TTL/Retention policy. Operator-tunable via
  `topic-compaction.retention.*`. Disabled by default; when enabled,
  a `RetentionService` background sweeper iterates the store on a
  fixed delay and evicts records past their TTL. Per-prefix rules
  override a default TTL with longest-prefix-first matching.
- Phase 3.4: `topic_compaction_retention_evicted_total` counter.
- Phase 3.5: Backup and restore tooling. Streaming line-delimited
  JSON format (one record per line; first line is a header with
  format version and timestamp). REST endpoints `POST
  /api/v1/admin/backup` and `POST /api/v1/admin/restore`.
- Phase 3: 30+ new unit tests across pattern matcher, bulk replay,
  delete service, retention sweeper, and backup roundtrip
  (105 tests total, was 67).

#### Changed

- Phase 3.1: `ReplayService.process(byte[])` delegates JSON parsing
  to `CommandEventParser`; the prior direct ObjectMapper call is
  gone.
- Phase 3.2: `ReplayProducerInterceptorFactory` now dispatches by
  command type:
  `REPLAY` -> `ReplayService`,
  `BULK_REPLAY` -> `BulkReplayService`,
  `DELETE` -> `DeleteCommandService`.
- Phase 3.2: `mi-config/application.yml` configures the `output-3`
  binding with a placeholder destination and explicit
  `producer.auto-startup: true` so `BulkReplayService` can publish
  via `StreamBridge` without a separate workflow.

#### Documentation

- `docs/COMMAND-EVENTS.md` rewritten for V1.0 - covers the JSON
  schema, all three command types, options reference, and
  end-to-end REST examples for `REPLAY` and `BULK_REPLAY`.

### Phase 4 - security, robustness, ops hardening

#### Added

- Phase 4.1: `WebSecurityConfig` and `SecurityProperties`. Two
  in-memory roles (`USER`, `ADMIN`) with HTTP Basic auth.
  Whitelist for `/actuator/health` and `/actuator/prometheus`. The
  framework's `SecurityAutoConfiguration` is excluded to avoid
  bean conflicts. ADR 0004 records the rationale.
- Phase 4.1: `MI_SECURITY_ENABLED`, `MI_USER_*`, `MI_ADMIN_*` env
  vars added to `.env.example` and the docker-compose mi-config.
  Disabled by default in dev mode; the K8s overlay enables it.
- Phase 4.2: `BrokerProvisioner` (`ApplicationRunner`) idempotently
  creates the workflow queues and topic subscriptions via SEMP
  v2 on startup. Conditional on
  `topic-compaction.provisioning.enabled`. 400 ("already exists")
  is treated as success.
- Phase 4.3: graceful shutdown wired - `server.shutdown=graceful`,
  `spring.lifecycle.timeout-per-shutdown-phase=25s`. `compose.yaml`
  sets `stop_grace_period=30s` and a healthcheck. The existing
  `RocksDbKvStore.@PreDestroy` already syncs the WAL before close.
- Phase 4.4: `StartupBanner` logs a one-shot summary of resolved
  config on `ApplicationReadyEvent`. Sensitive values (usernames)
  are masked. Gives operators sanity-check at boot.
- Phase 4.5: `consumer.concurrency: 1` on the command queue
  (input-1) so `BULK_REPLAY` cannot be parallelised across
  consumers, keeping the rate limiter deterministic.

### Phase 5 - Kubernetes deployment

#### Added

- `deploy/k8s/00-namespace.yaml` through `81-prometheusrule.yaml`
  - Namespace `mi-solace-lab` with PodSecurity `restricted`.
  - ConfigMap with the K8s overlay of `application.yml`.
  - Secret template (rendered via envsubst at deploy time;
    rendered file gitignored).
  - 10 Gi `ReadWriteOnce` PVC for RocksDB at
    `/var/lib/topic-compaction/rocksdb`.
  - Single-replica Deployment with `Recreate` strategy, hardened
    pod (non-root, read-only-rootFS, dropped capabilities,
    seccomp), liveness/readiness/startup probes.
  - ClusterIP Service exposing actuator port.
  - PodDisruptionBudget `minAvailable: 0` for clean drains.
  - NetworkPolicy: ingress from monitoring + same-namespace,
    egress to DNS, in-cluster Tempo (4317), and Solace Cloud
    SMF/REST/SEMP ports.
  - `ServiceMonitor` and `PrometheusRule` in the `monitoring`
    namespace with `prometheus: kube-prometheus` label so the
    operator picks them up.
  - Six initial alerts: pod absence, Solace binder down, skip
    rate, KV growth, lookup latency, pod memory.
- `deploy/k8s/scripts/start.sh` and `stop.sh` -- idempotent deploy
  and teardown. `start.sh` validates the env, renders the secret
  template, stamps a config-checksum annotation on the
  Deployment, applies all manifests, and waits for rollout.
  `stop.sh` removes monitoring artifacts then the workload, and
  optionally the PVC and namespace via flags.
- `Makefile` targets `k8s-deploy`, `k8s-status`, `k8s-logs`,
  `k8s-port-forward`, `k8s-restart`, `k8s-undeploy`,
  `k8s-undeploy-purge`.
- ADR 0003 (K8s deployment topology) and ADR 0004 (REST auth and
  role model).

#### Changed

- Image tag bumped from `1.0.0-SNAPSHOT` to `1.0.0` and pushed to
  `registry.solace.lab/sam-topic-compaction-mi:1.0.0`.
- `MetricsConfig.prometheusMeterRegistry` is now
  `@ConditionalOnBean(PrometheusRegistry.class)` so test contexts
  without the auto-config can still load.
- `TopicCompactionApplication` excludes the framework's
  `SecurityAutoConfiguration` (replaced by `WebSecurityConfig`).

#### Verified

- 105 unit tests green.
- Local docker-compose smoke test green with security disabled
  AND with security enabled (full role-matrix verified against
  the running container).
- K8s deployment in `mi-solace-lab` successfully rolled out in
  Rancher Desktop. Pod READY, PVC bound, ServiceMonitor + PrometheusRule
  visible in the `monitoring` namespace, security role matrix
  (10 checks) verified via port-forward.

### Phase 6 - Grafana dashboard, SLO alerts, runbook

#### Added

- `81-prometheusrule.yaml` rewritten into four groups:
  recording rules (`topic-compaction.recording` group), symptom
  alerts (pod absence, NotReady, memory), SLO alerts (compaction
  success rate, lookup p95, lookup miss ratio), capacity alerts
  (KV growth, PVC fill).
- Three recording rules computing SLIs once at scrape time:
  `topic_compaction:compaction_success_rate:5m`,
  `topic_compaction:lookup_p95_seconds:5m`,
  `topic_compaction:lookup_miss_ratio:5m`. Dashboards and alerts
  read the same series.
- Every alert now carries a `runbook` label that maps to a
  section in `docs/OPERATIONS.md`.
- `82-grafana-dashboard.yaml` -- ConfigMap with the
  `grafana_dashboard: "1"` label so the kube-prometheus-stack
  Grafana sidecar auto-imports it. Dashboard "Topic Compaction
  MI" with five rows: status stat-row, throughput (RED),
  latency, resources, storage. Templated by namespace + pod.
- `docs/OPERATIONS.md` -- runbook covering the SLO definitions,
  per-alert response (verify + recovery), routine ops
  (restart, credential rotation, retention), backup/restore
  procedure, disaster-recovery scenarios, and capacity planning.
- ADR 0005 -- SLO + alert strategy: SLI/SLO definitions, alert
  taxonomy (symptom / SLO / capacity), severity policy,
  recording-rule naming convention, and the rationale for
  deferring multi-window burn-rate alerts to a future iteration.
- `start.sh` and `stop.sh` updated to apply / remove the
  Grafana dashboard ConfigMap alongside the other monitoring
  artifacts.

### Phase 7 - test strategy + load harness

#### Added

- JaCoCo coverage plugin in `pom.xml` with a `mvn verify`
  threshold check (>= 75% line, >= 65% branch on the testable
  bundle). Spring `@Configuration` wiring classes are excluded
  because their behaviour is verified by integration tests, not
  unit tests.
- `EndToEndIntegrationTest` (6 cases) exercises the full service
  stack against a real per-test RocksDB instance:
  compaction-then-replay cycle, bulk-replay fanout, cascade
  delete, retention eviction, backup/restore roundtrip, and
  RocksDB persistence across a close+reopen.
- `examples/load-test.sh` -- bash + curl harness driving
  configurable producer load via the broker REST endpoint and
  sampling Prometheus metrics. Suitable for sanity load up to
  ~200 msg/s; production benchmarking should switch to sdkperf.
- `docs/PERFORMANCE.md` -- V1.0 baseline numbers
  (throughput, latency, resource use), bulk-replay benchmark
  table, capacity-planning rules of thumb, known performance
  limits, and explicit V1.1 future-work backlog.
- `Makefile` targets `verify`, `coverage`, `load-test`.

#### Changed

- `examples/smoke-test.sh` rewritten as fully non-interactive,
  exit-code-clean, with 10 assertions across health, compaction,
  replay, bulk-replay, tombstone, and admin/backup. Optional
  `--k8s` mode port-forwards the cluster service.
- `RocksDbKvStore.close()` visibility raised from package-private
  to public so integration tests outside the kvstore package can
  drive the close/reopen cycle.

#### Verified

- 111 tests green (was 105; +6 integration tests).
- Coverage check passes (`mvn verify` exits 0).
- Smoke test exits 0 with 10/10 assertions passing against the
  docker-compose deployment.
- Load test runs to completion with the expected throughput
  numbers logged in PERFORMANCE.md.

#### Deferred to V1.1

- Testcontainers-based integration tests with a real Solace
  broker. The `@SpringBootTest` setup conflicts with the MI
  Framework's auto-configuration; the existing
  `EndToEndIntegrationTest` covers the service-layer
  end-to-end, and `examples/smoke-test.sh` covers
  broker-integrated end-to-end.
- sdkperf-based load harness for sustained > 500 msg/s
  benchmarking.
- Per-workflow latency histograms (compaction, replay, lookup)
  separate from the generic `http.server.requests` series.

## [0.x] (pre-release MVP, V1)

The MVP shipped before this CHANGELOG was introduced. See git history
prior to commit `bf3859e` for the per-commit detail. High-level summary:

- Three workflows: Compaction, Replay (single only), Lookup.
- Direct REST surface for KV lookup/list/delete (with the slash-encoding
  caveat noted above).
- Docker-compose deployment, bring-your-own-broker.
- 61 unit tests across kvstore, compaction, replay, command, lookup, and
  api packages.
- Audit events on compaction, request/reply lookup, end-to-end smoke
  test.
