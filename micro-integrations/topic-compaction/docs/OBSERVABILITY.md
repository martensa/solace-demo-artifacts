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
       +- OTLP gRPC exporter (HTTP also supported)
       +- endpoint: ${OTEL_EXPORTER_OTLP_ENDPOINT}
       +- traceId/spanId in MDC for log correlation
       +- @Observed annotation -> manual workflow spans
       +- Spring Boot auto-instrumentation -> HTTP, security,
          StreamBridge spans

Possible OTLP backends (any combination):
  +- in-cluster Tempo (monitoring namespace, port 4317)
  +- host docker-compose otel-collector
     (host.docker.internal:4317 from Rancher Desktop pods,
      requires NetworkPolicy egress to 192.168.5.0/24)
  +- external SaaS (Datadog, Honeycomb, ...) via HTTPS + headers

Cluster collectors (monitoring namespace, optional):
  +- Prometheus  -> scrapes ServiceMonitor
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

### Tracing

| Property / env var | Default | Purpose |
|---|---|---|
| {OTEL_EXPORTER_OTLP_ENDPOINT} | {http://localhost:4317} | OTLP endpoint URL. K8s default is {http://host.docker.internal:4317} (host docker-compose collector). |
| {OTEL_SERVICE_NAME} | {topic-compaction-mi} | Resource attribute {service.name}. |
| {OTEL_RESOURCE_ATTRIBUTES} | {service.namespace=...,service.version=...} | Comma-separated resource tags applied to every span. Operators add {deployment.environment}, {team}, {k8s.cluster.name} here. |
| {OTEL_EXPORTER_OTLP_HEADERS} | -- | Comma-separated HTTP headers for vendor auth, e.g. {api-key=...,team=mdm}. Read by the OTel SDK directly. |
| {OTEL_TRACES_SAMPLER} | -- | OTel SDK sampler ({always_on}, {parentbased_traceidratio}, ...) - overrides Spring Boot's setting. |
| {OTEL_TRACES_SAMPLER_ARG} | -- | Argument for the chosen sampler (e.g. {0.01} for 1% ratio). |
| {management.tracing.sampling.probability} | {1.0} | Spring Boot's sampler probability. 100% in lab; lower in prod. |
| {management.tracing.enabled} | {true} | Master switch for tracing. |
| {management.otlp.tracing.transport} | {grpc} | {grpc} (port 4317) or {http} (port 4318). |

### General

| Property / env var | Default | Purpose |
|---|---|---|
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

The MI is fully OTLP-instrumented out of the box. Spans are exported
to any OTLP-compatible collector (in-cluster Tempo, host-side OTEL
Collector via docker-compose, vendor SaaS) without any code changes
- only the {OTEL_EXPORTER_OTLP_ENDPOINT} environment variable
needs to point at the collector.

### Span Topology

The MI emits two classes of spans:

**Custom spans** via {@io.micrometer.observation.annotation.Observed}.
The annotation's {contextualName} attribute becomes the Jaeger /
Tempo operation name (NOT the {name} attribute - that's the metric
name). Wired through {observability.TracingConfig} which
registers the {ObservedAspect} bean.

| Operation name (Jaeger) | Metric name | Created in | Workflow tag |
|---|---|---|---|
| {compact-message} | {compaction.process} | {CompactionService.compact} | {workflow=compaction} |
| {lookup-request} | {lookup.resolve} | {LookupService.resolve} | {workflow=lookup} |
| {replay-command} | {replay.parse-and-process} | {ReplayService.process} | {workflow=replay} |
| {bulk-replay} | {replay.bulk} | {BulkReplayService.execute} | {workflow=replay-bulk} |
| {delete-command} | {delete.execute} | {DeleteCommandService.execute} | {workflow=delete} |
| {retention-sweep} | {retention.sweep} | {RetentionService.sweep} | -- |
| {backup-stream} | {admin.backup} | {BackupService.backup} | -- |
| {restore-stream} | {admin.restore} | {BackupService.restore} | -- |

**Auto-instrumented spans** via Spring Boot's OTel auto-config:

| Operation name | Source | Notes |
|---|---|---|
| {http get /api/v1/kv/{*key}} et al. | Spring Web | Status, route template |
| {http post}, {http patch} | Spring Web | for {/actuator/loggers} etc. |
| {secured request}, {authorize request}, {authenticate usernamepassword}, {security filterchain before}, {security filterchain after} | Spring Security | One per filter pass |
| {stream-bridge process} | Spring Cloud Stream | Fires when StreamBridge.send is called - e.g. inside {bulk-replay} for the fan-out, parented to the workflow span |

### Configuration layers

The OTLP setup uses three configuration layers, each overriding
the next:

1. {src/main/resources/application.yml} (in-image default):
   ```yaml
   management:
     tracing:
       sampling.probability: 1.0
       enabled: true
     otlp:
       tracing:
         endpoint: ${OTEL_EXPORTER_OTLP_ENDPOINT:http://localhost:4317}
         transport: grpc
   ```
2. K8s {ConfigMap} ({deploy/k8s/10-configmap.yaml}) - same shape,
   identical defaults today.
3. K8s {Deployment} env vars ({deploy/k8s/40-deployment.yaml}):
   ```yaml
   env:
     - name: OTEL_EXPORTER_OTLP_ENDPOINT
       value: "http://host.docker.internal:4317"
     - name: OTEL_SERVICE_NAME
       value: "topic-compaction-mi"
     - name: OTEL_RESOURCE_ATTRIBUTES
       value: "service.namespace=mi-solace-lab,service.version=1.1.4"
   ```

The env-var layer is the cleanest place to switch endpoints without
rebuilding or restarting. {kubectl set env} suffices.

### Connecting to a collector

#### In-cluster Tempo (Grafana stack)

```bash
kubectl -n mi-solace-lab set env deployment/topic-compaction-mi \
  OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo.monitoring.svc.cluster.local:4317
kubectl -n mi-solace-lab rollout restart deployment/topic-compaction-mi
```

NetworkPolicy ({deploy/k8s/70-networkpolicy.yaml}) already allows
egress to the {monitoring} namespace on 4317.

#### Host-side docker-compose collector (Rancher Desktop)

Useful for local development where the operator runs an OTEL
Collector + Jaeger in docker-compose on the macOS host:

```bash
kubectl -n mi-solace-lab set env deployment/topic-compaction-mi \
  OTEL_EXPORTER_OTLP_ENDPOINT=http://host.docker.internal:4317
kubectl -n mi-solace-lab rollout restart deployment/topic-compaction-mi
```

{host.docker.internal} resolves inside Rancher Desktop K8s pods to
the Lima VM gateway (typically {192.168.5.2}). The MI's
NetworkPolicy explicitly allows egress to {192.168.5.0/24} on ports
{4317} and {4318} (gRPC + HTTP OTLP) - other private RFC1918
ranges remain blocked by the Solace Cloud egress rule. If your
Rancher Desktop version uses a different gateway IP, adjust the
{cidr} in {70-networkpolicy.yaml} accordingly.

Verify the IP by running:
```bash
kubectl run --rm -i --restart=Never --image=busybox:1.36 \
  --namespace=default dnstest \
  -- nslookup host.docker.internal 2>&1 | grep '^Address'
```

#### External SaaS collector (Datadog, Honeycomb, Lightstep, etc.)

For HTTPS endpoints, set the endpoint and any vendor authentication
headers via {OTEL_EXPORTER_OTLP_HEADERS}:

```bash
kubectl -n mi-solace-lab set env deployment/topic-compaction-mi \
  OTEL_EXPORTER_OTLP_ENDPOINT=https://otlp.your-vendor.example.com:4317 \
  OTEL_EXPORTER_OTLP_HEADERS="api-key=...,team=mdm"
kubectl -n mi-solace-lab rollout restart deployment/topic-compaction-mi
```

{OTEL_EXPORTER_OTLP_HEADERS} is OpenTelemetry SDK standard and is
read directly by the SDK - no Spring Boot config required. The
NetworkPolicy already permits the matching public-internet egress
(non-RFC1918, non-private ranges) on ports {55443}, {9443} - extend
the rule if your vendor uses a different port like 443.

#### HTTP transport instead of gRPC

```yaml
# in 10-configmap.yaml or via env override
management:
  otlp:
    tracing:
      transport: http   # default is grpc
      endpoint: http://your-collector:4318   # 4318 is the OTLP/HTTP port
```

Or via env (Spring Boot relaxed binding):

```bash
kubectl -n mi-solace-lab set env deployment/topic-compaction-mi \
  MANAGEMENT_OTLP_TRACING_TRANSPORT=http \
  OTEL_EXPORTER_OTLP_ENDPOINT=http://host.docker.internal:4318
```

### Resource attributes

Every span is tagged with the {OTEL_RESOURCE_ATTRIBUTES} contents
plus {service.name = OTEL_SERVICE_NAME}. To add deployment context:

```yaml
- name: OTEL_RESOURCE_ATTRIBUTES
  value: "service.namespace=mi-solace-lab,service.version=1.1.4,deployment.environment=lab,k8s.cluster.name=rancher-desktop,team=mdm"
```

These appear as searchable resource tags in Tempo, Jaeger, etc.

### Sampling

Lab default: 100% sampling
({management.tracing.sampling.probability: 1.0}). For
production this should be tuned downward - 1% is a reasonable
starting point. Two ways:

1. Spring Boot property:
   ```yaml
   management.tracing.sampling.probability: 0.01
   ```
2. OpenTelemetry SDK env vars (override Spring's setting):
   ```bash
   OTEL_TRACES_SAMPLER=parentbased_traceidratio
   OTEL_TRACES_SAMPLER_ARG=0.01
   ```

The {parentbased_*} samplers preserve sampling decisions made
upstream when distributed-trace propagation is wired - useful
when an upstream system is the source of truth for whether a
trace should be sampled.

### Trace to log correlation

Every log line emitted inside an active span carries {traceId} and
{spanId} fields in the JSON output (set by Micrometer's MDC bridge).
Example log line during a {bulk-replay}:

```json
{
  "@timestamp": "2026-05-07T08:44:16.068Z",
  "logger": "...BulkReplayService",
  "message": "BulkReplay: starting for pattern=...",
  "traceId": "7b1ede9b109af52835383fe37ae302aa",
  "spanId": "48e34757f6acc8c6",
  "service": "topic-compaction-mi"
}
```

To pivot from a Tempo / Jaeger trace to logs, copy the trace ID and
run a LogQL query against Loki:

```logql
{app="topic-compaction-mi"} | json | traceId = "<paste-trace-id>"
```

Grafana's "Logs for this trace" panel does this automatically when
both data sources are linked via the trace-to-logs derived field.

### Verifying the pipeline

End-to-end smoke test - publish a message and confirm the trace
arrives at the collector:

```bash
. .env

# 1) Generate a trace
curl -s -u "$SOLACE_REST_USER:$SOLACE_REST_PASS" -X POST \
  "$SOLACE_REST_HOST/orders/trace-test/$(date +%s)" \
  -H "Content-Type: application/json" \
  --data '{"otel":"smoke"}'

# 2) Find the traceId in the MI's logs
kubectl -n mi-solace-lab logs -l app.kubernetes.io/name=topic-compaction-mi \
  --tail=20 | grep '"traceId"' | tail -1

# 3a) Verify in Jaeger UI (host docker-compose setup)
open http://localhost:16686/api/traces?service=topic-compaction-mi

# 3b) Or query Tempo (in-cluster setup) via Grafana

# 4) Inspect the OTEL Collector's debug exporter to confirm receipt
docker logs otel-collector --tail=20 | \
  grep -E '"otelcol.signal":"traces"'
# Expected: lines like:
# info Traces ... "resource spans": 5, "spans": 5
```

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
| No spans at the collector | OTLP endpoint unreachable | Check {OTEL_EXPORTER_OTLP_ENDPOINT} on the running pod ({kubectl ... -o jsonpath}); MI logs the resolved endpoint at startup in the {StartupBanner}. The exporter does NOT log per-export failures by design. |
| No spans, NetworkPolicy in path | Egress blocked | If using {host.docker.internal} from K8s, ensure the matching {ipBlock} egress rule exists in {70-networkpolicy.yaml}. Test with a debug pod (busybox + nc) in the same namespace with matching {podSelector} labels. |
| {No spans for {compact-message}} but HTTP spans visible | Operation name confusion | Search by the {contextualName} ({compact-message}, {bulk-replay}, etc.) NOT the metric {name} ({compaction.process}, {replay.bulk}). |
| Logs missing traceId | Active span not propagated | Check that the entry method has {@Observed}; AOP only proxies external calls. Self-calls inside the same bean don't trigger the proxy. |
| Loki shows plain-text logs | Wrong profile | Set {SPRING_PROFILES_ACTIVE=k8s} |
| {compaction_messages_total} flat despite producer activity | Subscription on {compaction.data} queue missing | See {docs/OPERATIONS.md} runbook for queue subscription verification |
| OTEL Collector logs show {refused spans > 0} | Backend (Tempo, vendor) returning 429 / 5xx | Check the collector's exporter-side metrics; reduce sampling probability on the MI side or batch interval at the collector. |

## References

- ADR 0001 -- baseline architecture, including the three-pillar
  observability decision
- {logback-spring.xml} -- the logging profile definitions
- Spring Boot Tracing reference:
  https://docs.spring.io/spring-boot/reference/actuator/tracing.html
- OpenTelemetry SDK env-var spec:
  https://opentelemetry.io/docs/specs/otel/protocol/exporter/
- Micrometer Observation @Observed reference:
  https://micrometer.io/docs/observation
- {observability.MetricsConfig} -- Prometheus registry wiring
- {observability.TracingConfig} -- AOP aspect registration
