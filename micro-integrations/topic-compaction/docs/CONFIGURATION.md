# Configuration

All configuration is Spring Boot YAML. The MI ships an internal
`application.yml` (packed in the JAR) with framework defaults; operators
provide an external `application.yml` mounted at
`/app/external/spring/config/`.

## Solace connection

```yaml
solace:
  java:
    host: tcp://solace-broker:55555
    msg-vpn: default
    client-username: default
    client-password: default
    connect-retries: -1
    reconnect-retries: -1
```

## Workflow lifecycle

```yaml
solace:
  connector:
    workflows:
      0: { enabled: true }     # Compaction (data -> KV + audit)
      1: { enabled: true }     # Replay (command -> KV lookup -> publish)
      2: { enabled: true }     # Lookup via Solace Request/Reply
      3: { enabled: false }    # reserved
      # ... up to 7
```

## Workflow bindings

```yaml
spring:
  cloud:
    stream:
      bindings:
        input-0:                       # Workflow 0 input - Solace queue
          destination: compaction.data
          binder: solace
        output-0:                      # Workflow 0 output - audit topic
          destination: placeholder/compacted-ack    # rewritten by interceptor
          binder: solace
        input-1: { destination: compaction.commands, binder: solace }
        output-1: { destination: placeholder/compacted, binder: solace }
        input-2: { destination: compaction.lookup, binder: solace }
        output-2: { destination: placeholder/lookup-reply, binder: solace }

      solace:
        default:
          producer:
            destination-type: topic     # publish to topics, not queues
```

## KV Store

```yaml
topic-compaction:
  kvstore:
    backend: rocksdb               # rocksdb (default) | caffeine
    rocksdb:
      path: /app/data/rocksdb
      max-open-files: 1000
    caffeine:
      maximum-size: 1000000
```

| Property | Default | Notes |
|----------|---------|-------|
| `topic-compaction.kvstore.backend` | `rocksdb` | `rocksdb` for prod (persistent), `caffeine` for tests/in-memory |
| `topic-compaction.kvstore.rocksdb.path` | `./data/rocksdb` | mount as a docker volume in production |
| `topic-compaction.kvstore.rocksdb.max-open-files` | `1000` | tune for your store size |

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
|----------|---------|-------|
| `binding-names` | `[input-0]` | Solace consumer bindings to attach the compaction interceptor |
| `audit-suffix` | `/compacted-ack` | suffix appended to the original topic for the audit event |
| `loop-protection-header` | `x-compacted-replay` | Solace user-property header set by replay; checked here to skip |
| `ordering.header` | `""` | name of an optional sender-timestamp header for out-of-order detection |

## Replay (Workflow 1)

```yaml
topic-compaction:
  replay:
    binding-names: [input-1]
    target-suffix: /compacted
    loop-protection-header: x-compacted-replay
```

## Lookup (Workflow 2 - Solace Request/Reply)

```yaml
topic-compaction:
  lookup:
    binding-names: [input-2]
    key-header: x-compaction-key
    topic-key-prefix: "compacted/lookup/"
```

The MI extracts the requested key from EITHER the user-property header
`key-header` OR the request topic by stripping `topic-key-prefix`. The header
takes precedence when both are present.

## Spring Boot Actuator

```yaml
management:
  endpoint:
    health:
      show-components: always
      show-details: always
  endpoints:
    web:
      exposure:
        include: health,metrics,workflows,bindings,info,env,loggers,channels,leaderelection
```

The MI's REST API (`/api/v1/kv/...`) is served on the same port as actuator
(default: `8090`).
