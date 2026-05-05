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
