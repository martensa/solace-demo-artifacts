# Configuration

All configuration is Spring Boot YAML + environment variables. Two layers:

1. **Internal** (`src/main/resources/application.yml`, packed in the JAR) -
   framework defaults. Don't edit unless you're rebuilding the image.
2. **External** (`deploy/docker-compose/mi-config/application.yml`, mounted at
   `/app/external/spring/config/` in the container) - operator overrides.
   Uses `${VAR}` placeholders for secrets; real values come from `.env`.

## Secrets management

`.env` (gitignored) holds real credentials; `.env.example` (committed) has
placeholder values. Both Docker Compose and the smoke test script read `.env`
directly. The MI's `application.yml` references variables via Spring Boot's
native `${VAR}` syntax and resolves them from the container's environment.

```bash
make env-init           # cp .env.example .env
$EDITOR .env            # fill in real values
make env-check          # validate before bringing the stack up
```

Required keys in `.env`:

| Key | Used by | Example |
|-----|---------|---------|
| `SOLACE_HOST` | MI (SMF connection) | `tcp://mr-connection-XXX.messaging.solace.cloud:55555` |
| `SOLACE_VPN` | MI | `mdm-eu` |
| `SOLACE_USERNAME` | MI | `solace-cloud-client` |
| `SOLACE_PASSWORD` | MI | (replace-me) |
| `SOLACE_REST_HOST` | smoke test (curl) | `http://mr-connection-XXX.messaging.solace.cloud:9000` |
| `SOLACE_REST_USER` | smoke test | usually same as `SOLACE_USERNAME` |
| `SOLACE_REST_PASS` | smoke test | usually same as `SOLACE_PASSWORD` |
| `MI_PORT` | docker-compose port mapping | `18090` |
| `MI_IMAGE` | docker-compose image tag | `registry.solace.lab/sam-topic-compaction-mi:1.0.0-SNAPSHOT` |

## Solace connection (referenced from `.env`)

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
