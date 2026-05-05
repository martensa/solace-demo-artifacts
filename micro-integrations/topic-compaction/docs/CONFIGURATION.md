# Configuration Reference

All Topic Compaction MI configuration is Spring Boot YAML +
environment variables, layered as follows (lowest to highest
precedence):

1. **In-image** (`src/main/resources/application.yml`): framework
   defaults; not operator-edited.
2. **Operator overlay** (`/app/external/spring/config/
   application.yml`): mounted from a `ConfigMap` in K8s, or from
   `deploy/docker-compose/mi-config/` locally.
3. **Environment variables**: from a `Secret` in K8s or `.env`
   locally. Sensitive values only.

## Secrets management

`.env` (gitignored) holds real credentials; `.env.example`
(committed) carries placeholders. Both `docker compose` and the
smoke test script source `.env` directly. The MI's `application.yml`
references variables via Spring Boot's `${VAR}` syntax and resolves
them from the container environment.

```bash
make env-init           # cp .env.example .env
$EDITOR .env            # fill in real values
make env-check          # validate before bringing the stack up
```

### Required environment variables

| Variable | Used by | Example |
|---|---|---|
| `SOLACE_HOST` | MI (SMF) | `tcp://mr-connection-XXX.messaging.solace.cloud:55555` |
| `SOLACE_VPN` | MI | `mdm-eu` |
| `SOLACE_USERNAME` | MI | `solace-cloud-client` |
| `SOLACE_PASSWORD` | MI | (per service) |
| `SOLACE_REST_HOST` | smoke test (curl) | `http://mr-connection-XXX.messaging.solace.cloud:9000` |
| `SOLACE_REST_USER` | smoke test | usually = `SOLACE_USERNAME` |
| `SOLACE_REST_PASS` | smoke test | usually = `SOLACE_PASSWORD` |
| `MI_PORT` | docker-compose | `18090` |
| `MI_IMAGE` | docker-compose | `registry.solace.lab/sam-topic-compaction-mi:1.0.0` |

### Optional (V1.0 / Phase 4 hardening)

| Variable | Default | Purpose |
|---|---|---|
| `MI_SECURITY_ENABLED` | `false` | Toggle REST + Actuator authentication |
| `MI_USER_NAME` | `mi-user` | Read-only role username |
| `MI_USER_PASSWORD` | `change-me-user` | Read-only role password |
| `MI_ADMIN_NAME` | `mi-admin` | Admin role username |
| `MI_ADMIN_PASSWORD` | `change-me-admin` | Admin role password |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | OTLP gRPC for Tempo |
| `KUBERNETES_NAMESPACE` | `local` | Common-tag value |
| `SPRING_PROFILES_ACTIVE` | (dev) | Set to `k8s` to enable JSON logs |

## Solace connection

```yaml
solace:
  java:
    host: ${SOLACE_HOST}
    msg-vpn: ${SOLACE_VPN}
    client-username: ${SOLACE_USERNAME}
    client-password: ${SOLACE_PASSWORD}
    connect-retries: -1
    reconnect-retries: -1
```

## Workflow lifecycle

```yaml
solace:
  connector:
    workflows:
      0: {enabled: true}     # Compaction
      1: {enabled: true}     # Replay (single + bulk + delete)
      2: {enabled: true}     # Lookup (Solace request/reply)
      3: {enabled: false}    # reserved (output-3 used as
                             # bulk-replay fanout via StreamBridge)
      # 4-7: reserved for future MIs
```

## Workflow bindings

```yaml
spring:
  cloud:
    stream:
      bindings:
        input-0:
          destination: compaction.data
          binder: solace
        output-0:
          destination: placeholder/compacted-ack
          binder: solace
        input-1:
          destination: compaction.commands
          binder: solace
          consumer:
            concurrency: 1            # Phase 4.5 - keeps bulk
                                      # replay rate-limit deterministic
        output-1:
          destination: placeholder/compacted
          binder: solace
        input-2:
          destination: compaction.lookup
          binder: solace
        output-2:
          destination: placeholder/lookup-reply
          binder: solace
        # output-3 is the bulk-replay fanout binding; no input
        # is consumed (workflow 3 stays disabled).
        output-3:
          destination: placeholder/bulk-replay-fanout
          binder: solace
          producer:
            auto-startup: true        # not driven by an MI workflow
```

## KV store

```yaml
topic-compaction:
  kvstore:
    backend: rocksdb               # rocksdb (default) | caffeine
    rocksdb:
      path: /app/data/rocksdb       # docker-compose default
      max-open-files: 1000
    caffeine:
      maximum-size: 1000000
```

| Property | Default | Notes |
|---|---|---|
| `kvstore.backend` | `rocksdb` | `caffeine` is dev/test only |
| `kvstore.rocksdb.path` | `./data/rocksdb` (in-image), `/app/data/rocksdb` (compose), `/var/lib/topic-compaction/rocksdb` (K8s) | Must point at a writable volume |
| `kvstore.rocksdb.max-open-files` | `1000` | Tune for store size |
| `kvstore.caffeine.maximum-size` | `1000000` | LRU bound for Caffeine backend |

## Compaction (Workflow 0)

```yaml
topic-compaction:
  compaction:
    binding-names: [input-0]
    audit-suffix: /compacted-ack
    loop-protection-header: x-compacted-replay
    ordering:
      header: ""               # empty = always-last-wins
```

| Property | Default | Notes |
|---|---|---|
| `binding-names` | `[input-0]` | Solace consumer bindings to attach the compaction interceptor to |
| `audit-suffix` | `/compacted-ack` | suffix appended to the original topic for the audit event |
| `loop-protection-header` | `x-compacted-replay` | header replays carry; compaction skips messages with this header set |
| `ordering.header` | `""` | name of an optional sender-timestamp header for out-of-order detection; default = always-last-wins |

## Replay (Workflow 1)

```yaml
topic-compaction:
  replay:
    binding-names: [input-1]
    target-suffix: /compacted
    loop-protection-header: x-compacted-replay
```

| Property | Default | Notes |
|---|---|---|
| `binding-names` | `[input-1]` | Solace consumer bindings to attach the replay interceptor to |
| `target-suffix` | `/compacted` | suffix on the replay destination (`<key><target-suffix>`); per-command overridable via `options.destinationSuffix` |
| `loop-protection-header` | `x-compacted-replay` | same header replays set so compaction can recognise them |

## Lookup (Workflow 2)

```yaml
topic-compaction:
  lookup:
    binding-names: [input-2]
    key-header: x-compaction-key
    topic-key-prefix: "compacted/lookup/"
```

The MI extracts the requested key from EITHER the user-property
`key-header` OR the request topic by stripping
`topic-key-prefix`. The header takes precedence.

## Retention (Phase 3.4)

```yaml
topic-compaction:
  retention:
    enabled: false             # off by default
    check-interval: PT5M
    default-ttl: PT24H         # null = keep forever
    rules:
      - prefix: "orders/"
        ttl: PT7D
      - prefix: "ephemeral/"
        ttl: PT1H
```

| Property | Default | Notes |
|---|---|---|
| `enabled` | `false` | Master switch |
| `check-interval` | `PT5M` | How often the sweeper runs |
| `default-ttl` | (null) | Fallback TTL when no rule matches; null = no eviction |
| `rules[].prefix` | -- | Key prefix for the rule |
| `rules[].ttl` | -- | TTL for keys under this prefix |

Longest-prefix-first rule selection. Sweeper iterates the entire
KV store on each tick (streaming, no full snapshot in memory).

## Provisioning (Phase 4.2)

```yaml
topic-compaction:
  provisioning:
    enabled: false             # off by default
    fail-on-error: false
    semp:
      url: https://mr-connection-XXX.messaging.solace.cloud:943
      username: mission-control-manager
      password: ${SEMP_PASSWORD}
      msg-vpn: my-vpn
    queues:
      - name: compaction.data
        subscriptions: [orders/>]
      - name: compaction.commands
        subscriptions: [compacted/command/>]
      - name: compaction.lookup
        subscriptions: [compacted/lookup/>]
```

When enabled and SEMP credentials are valid, an
`ApplicationRunner` creates the queues + subscriptions
idempotently on startup. `400` from SEMP (already exists) is
treated as success.

## Security (Phase 4.1)

```yaml
topic-compaction:
  security:
    enabled: ${MI_SECURITY_ENABLED:false}
    user:
      name: ${MI_USER_NAME:mi-user}
      password: ${MI_USER_PASSWORD:change-me-user}
    admin:
      name: ${MI_ADMIN_NAME:mi-admin}
      password: ${MI_ADMIN_PASSWORD:change-me-admin}
```

| Role | Permissions |
|---|---|
| `USER` | `GET /api/v1/kv/...` (read, list) |
| `ADMIN` | `USER` + `DELETE /api/v1/kv/...` + `/api/v1/admin/*` + actuator endpoints other than health/prometheus |

`/actuator/health` and `/actuator/prometheus` are public regardless
of the `enabled` flag.

See `docs/SECURITY.md` for the threat model and the rationale.

## Observability (Phase 2)

```yaml
management:
  defaults:
    metrics:
      export:
        enabled: false
  prometheus:
    metrics:
      export:
        enabled: true
  endpoints:
    web:
      exposure:
        include: "health,metrics,prometheus,info"
  endpoint:
    health:
      probes:
        enabled: true
      group:
        liveness:
          include: livenessState
        readiness:
          include: readinessState,binders
  tracing:
    sampling:
      probability: 1.0
    enabled: true
  otlp:
    tracing:
      endpoint: ${OTEL_EXPORTER_OTLP_ENDPOINT:http://localhost:4317}
      transport: grpc
```

See `docs/OBSERVABILITY.md` for metric reference, log schema,
and trace topology.

## Logging profiles

`logback-spring.xml` defines three profiles:

- `dev` (and unset, default): pretty single-line console with
  `[traceId,spanId]`.
- `k8s`, `prod`: JSON via Logstash Logback Encoder, picked up by
  Promtail / Grafana Agent into Loki.

Activate via `SPRING_PROFILES_ACTIVE=k8s`.

## Graceful shutdown (Phase 4.3)

```yaml
server:
  port: 8090
  shutdown: graceful

spring.lifecycle.timeout-per-shutdown-phase: 25s
```

Pairs with `terminationGracePeriodSeconds: 30` in the K8s
deployment so the JVM has a 5s safety margin to flush RocksDB
WAL after Spring's drain completes.

## Full property index

| Prefix | Section above | Phase |
|---|---|---|
| `solace.java.*` | Solace connection | (V0) |
| `solace.connector.workflows.*` | Workflow lifecycle | (V0) |
| `spring.cloud.stream.bindings.*` | Workflow bindings | (V0) |
| `topic-compaction.kvstore.*` | KV store | (V0) |
| `topic-compaction.compaction.*` | Workflow 0 | (V0) |
| `topic-compaction.replay.*` | Workflow 1 | (V0) |
| `topic-compaction.lookup.*` | Workflow 2 | (V0) |
| `topic-compaction.retention.*` | Retention | 3.4 |
| `topic-compaction.provisioning.*` | SEMP provisioning | 4.2 |
| `topic-compaction.security.*` | REST auth | 4.1 |
| `management.*` | Actuator + observability | 1.3, 2 |
| `server.shutdown`, `spring.lifecycle.*` | Graceful shutdown | 4.3 |
