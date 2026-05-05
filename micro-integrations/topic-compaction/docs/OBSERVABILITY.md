# Observability

This document is the operator's reference for the three telemetry
pillars of the Topic Compaction MI. It covers metrics, structured
logs, and distributed traces, plus how they correlate.

## Architecture

```text
Topic Compaction MI (pod)
  +- Spring Boot Actuator
  |    +- /actuator/health/{liveness,readiness}  K8s probes
  |    +- /actuator/prometheus                   Prometheus scrape
  |
  +- Logback (logback-spring.xml)
  |    +- profile dev:  pretty single-line console
  |    +- profile k8s:  JSON to stdout, MDC-tagged
  |
  +- Micrometer Tracing -> OpenTelemetry SDK
       +- OTLP gRPC exporter
       +- endpoint: ${OTEL_EXPORTER_OTLP_ENDPOINT}
       +- traceId/spanId in MDC for log correlation

Cluster collectors (monitoring namespace):
  +- Prometheus  -> scrapes ServiceMonitor (Phase 5)
  +- Loki        -> Promtail tails pod stdout
  +- Tempo       -> receives OTLP gRPC on :4317
  +- Grafana     -> single pane, all three pillars
```

The three pillars are stitched together by the trace ID:

- A workflow span (e.g. {compaction.process}) generates a trace ID.
- Micrometer Tracing's bridge puts {traceId} and {spanId} into the
  SLF4J MDC. Every log line emitted inside the span carries them.
- The same trace ID is exported to Tempo. Grafana's "Logs to traces"
  feature in a Loki query lets you pivot from a log line directly to
  the matching trace.

## Configuration

| Property | Default | Purpose |
|---|---|---|
| {OTEL_EXPORTER_OTLP_ENDPOINT} | `http://localhost:4317` | OTLP gRPC endpoint - Tempo in K8s |
| {management.tracing.sampling.probability} | {1.0} | 100% sampling in lab; lower in prod |
| {management.tracing.enabled} | {true} | Master switch for tracing |
| {KUBERNETES_NAMESPACE} | {local} | Common-tag value for metrics |
| {topic-compaction.version} | {dev} | Common-tag value for metrics |
| {SPRING_PROFILES_ACTIVE} | {default} | {k8s} flips logback to JSON |

## Metrics

All metric names are prefixed {topic_compaction_} (snake_case for
Prometheus). Common tags {application}, {namespace}, {version} are
attached automatically by {observability.MetricsConfig}.

### Application Metrics

| Metric | Type | Tags | Description |
|---|---|---|---|
| {topic_compaction_upserts_total} | counter | -- | Compactions written to KV store |
| {topic_compaction_skipped_total} | counter | {reason} = loop, out_of_order, no_topic | Compactions skipped |
| {topic_compaction_replays_total} | counter | -- | Replay events successfully published |
| {topic_compaction_lookups_total} | counter | -- | KV lookup requests received |
| {topic_compaction_lookup_misses_total} | counter | -- | KV lookups that returned nothing |
| {topic_compaction_kvstore_size} | gauge | -- | Current key count in KV store |

(Future, added in later phases:)

| Metric | Type | Tags | Description |
|---|---|---|---|
| {topic_compaction_kv_size_bytes} | gauge | -- | RocksDB on-disk size |
| {topic_compaction_command_duration_seconds} | histogram | {workflow,outcome} | Command-handling latency |
| {topic_compaction_retention_evicted_total} | counter | {prefix} | TTL evictions |

### Spring + JVM Metrics

Standard Spring Boot Actuator exports are also visible at
{/actuator/prometheus}. Useful filters:

- {jvm_memory_used_bytes{area="heap"}} -- heap pressure
- {http_server_requests_seconds_count} -- REST request rate
- {http_server_requests_seconds_bucket} -- latency histogram
- {process_cpu_usage} -- container CPU
- {tomcat_sessions_active_current} -- (none, MI is sessionless)

## Logs

### Local development (default profile)

Pretty single-line format:

```text
2026-05-05 09:50:47.220 DEBUG [solace-scst-consumer-input-01]
[40c3b74658af7e1874a11bdf960e0679,e9b1616a2bdfb5a5]
c.s.l.m.t.c.CompactionService - Compacted topic=orders/created/A
(30 bytes)
```

Format breakdown:

- {2026-05-05 09:50:47.220} timestamp
- {DEBUG} level
- {[solace-scst-consumer-input-01]} thread name
- {[traceId,spanId]} - empty when no active span
- {c.s.l.m.t.c.CompactionService} truncated logger name
- {- Compacted topic=...} message

### Kubernetes ({k8s} or {prod} profile)

JSON-per-line via Logstash Logback Encoder. Sample:

```json
{
  "@timestamp": "2026-05-05T11:50:47.220Z",
  "@version": 1,
  "level": "DEBUG",
  "logger": "com.solace.labs.mi.topiccompaction.compaction.CompactionService",
  "thread": "solace-scst-consumer-input-01",
  "message": "Compacted topic=orders/created/A (30 bytes)",
  "service": "compaction",
  "key": "orders/created/A",
  "traceId": "40c3b74658af7e1874a11bdf960e0679",
  "spanId": "e9b1616a2bdfb5a5"
}
```

Promtail / Grafana Agent picks up pod stdout and forwards to Loki.
LogQL queries:

```logql
{app="topic-compaction-mi"} | json
{app="topic-compaction-mi"} | json | level = "ERROR"
{app="topic-compaction-mi"} | json | service = "replay" |~ "failed"
{app="topic-compaction-mi"} | json | traceId = "40c3..."
```

### MDC Keys

Application MDC keys attached by the workflow services:

| Key | Set in | Value |
|---|---|---|
| {service} | all services | {compaction}, {replay}, {lookup} |
| {key} | replay, lookup | the KV key being processed |
| {command} | replay | parsed command type, e.g. {REPLAY} |
| {traceId} | OTel bridge | 32-char hex trace identifier |
| {spanId} | OTel bridge | 16-char hex span identifier |

## Traces

### Span Topology

| Span | Created in | Tags |
|---|---|---|
| {compaction.process} | {CompactionService.compact} | {workflow=compaction} |
| {replay.parse-and-process} | {ReplayService.process(byte[])} | {workflow=replay} |
| {lookup.resolve} | {LookupService.resolve} | {workflow=lookup} |
| {http.server.requests} | Spring auto-instrumentation | route, status |
| {jdbc.*} | none (no JDBC) | -- |

The MI spans are created by the
{io.micrometer.observation.annotation.Observed} annotation, wired
through {observability.TracingConfig}. They include the configured
{contextualName} as the operation name and the
{lowCardinalityKeyValues} as searchable attributes.

### Sampling and Cost

Lab default is 100% sampling ({management.tracing.sampling.probability:
1.0}). For production this should be tuned -- 1% is a reasonable
starting point and individual high-value traces can be sampled
deterministically by setting {OTEL_TRACES_SAMPLER=traceidratio} with
a desired ratio.

### Trace -> Log Correlation

Workflow steps automatically expose {traceId} and {spanId} via SLF4J
MDC. To correlate from Tempo to Loki, copy the trace ID from the
Tempo trace view and run a LogQL query:

```logql
{app="topic-compaction-mi"} | json | traceId = "<paste-trace-id>"
```

In Grafana the "Logs for this trace" panel does this automatically
when the data sources are linked.

## Health Probes

| Probe | Endpoint | Includes |
|---|---|---|
| Liveness | {/actuator/health/liveness} | {livenessState} |
| Readiness | {/actuator/health/readiness} | {readinessState} + Solace binders |
| Aggregate | {/actuator/health} | full tree |

In Kubernetes (Phase 5):

```yaml
livenessProbe:
  httpGet: { path: /actuator/health/liveness, port: 8090 }
readinessProbe:
  httpGet: { path: /actuator/health/readiness, port: 8090 }
```

The readiness probe is intentionally stricter than liveness: it
includes the Solace binders, so traffic is held off the pod until
all three workflow bindings are UP.

## Troubleshooting

| Symptom | Likely cause | Resolution |
|---|---|---|
| {/actuator/prometheus} returns empty payload | MI Framework's NoOp meter registry took precedence | {observability.MetricsConfig} should fix; verify {prometheusMeterRegistry} bean is {@Primary} |
| No spans in Tempo | OTLP endpoint unreachable | Check {OTEL_EXPORTER_OTLP_ENDPOINT}; the MI logs do not error on export failure |
| Logs missing traceId | Active span not propagated | Check that the entry method has {@Observed}; AOP only proxies external calls |
| Loki shows plain-text logs | Wrong profile | Set {SPRING_PROFILES_ACTIVE=k8s} |
| {compaction_messages_total} flat despite producer activity | Subscription on {compaction.data} queue missing | See {docs/OPERATIONS.md} runbook for queue subscription verification |

## References

- ADR 0001 -- baseline architecture, including the three-pillar
  observability decision
- {logback-spring.xml} -- the logging profile definitions
- {observability.MetricsConfig} -- Prometheus registry wiring
- {observability.TracingConfig} -- AOP aspect registration
