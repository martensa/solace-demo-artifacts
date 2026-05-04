# Topic Compaction Micro-Integration

A Solace Micro-Integration that maintains a key-value store of last-seen
messages per Solace topic, with on-demand replay via command events. A
Solace-native alternative to Kafka log compaction.

> **Built on**: Solace MDK 3.0.6 + Spring Boot 3.5 + Spring Cloud Stream Solace
> binder + RocksDB.
> **Status**: V1 MVP. End-to-end verified in docker-compose.

## What it does

| Workflow | Input | Action | Output |
|----------|-------|--------|--------|
| **0 - Compaction** | `compaction.data` queue (subscribed to e.g. `orders/>`) | Stores latest message per topic in RocksDB | `<topic>/compacted-ack` (audit JSON) |
| **1 - Replay** | `compaction.commands` queue (subscribed to `compacted/command/>`) | Parses command JSON, looks up KV, republishes | `<key>/compacted` |
| **2 - Lookup** | `compaction.lookup` queue (subscribed to `compacted/lookup/>`) | Solace Request/Reply: returns latest message for the key | `solace_replyTo` of the request |
| **REST API** | HTTP `:8090` | Direct lookup / list / delete | JSON / raw payload |

See [docs/DIFFERENTIATORS.md](docs/DIFFERENTIATORS.md) for how this beats Kafka
log compaction.

## Quick start

```bash
# Build the JAR
./mvnw clean package

# Pull the base image once (works around docker.io anonymous-pull quirks)
docker pull eclipse-temurin:17-jre

# Build the container image
DOCKER_CONFIG=$HOME/.docker ./mvnw jib:dockerBuild -DskipTests

# Run the stack
cd deploy/docker-compose && docker compose up -d
```

The MI is up at `http://localhost:18090` once
`/actuator/health` returns `UP` (~40s after start).

Full walkthrough: [docs/SMOKE-TEST.md](docs/SMOKE-TEST.md).

## Repository layout

```
topic-compaction/
├── pom.xml                        # MI build (parent: micro-integration-build-parent:3.0.6)
├── mvnw, mvnw.cmd, .mvn/
├── src/
│   ├── main/java/com/solace/labs/mi/topiccompaction/
│   │   ├── TopicCompactionApplication.java
│   │   ├── kvstore/                # RocksDB + Caffeine + binary record codec
│   │   ├── compaction/             # Workflow 0: ConsumerInterceptor + ProducerInterceptor (audit)
│   │   ├── replay/                 # Workflow 1: command parsing + ProducerInterceptor
│   │   ├── command/                # Command JSON DTO + enum
│   │   ├── lookup/                 # Workflow 2: Solace Request/Reply
│   │   ├── api/                    # REST controller
│   │   └── metrics/                # Micrometer counters + gauges
│   └── main/resources/application.yml         # internal MI config (workflows, bindings)
├── deploy/
│   └── docker-compose/
│       ├── compose.yaml                       # broker + queue init + MI
│       ├── init-queues.sh
│       └── mi-config/application.yml          # external operator config
├── examples/
│   ├── command-events/replay.json
│   ├── command-events/replay-minimal.json
│   └── smoke-test.sh
├── docs/
│   ├── ARCHITECTURE.md
│   ├── CONFIGURATION.md
│   ├── COMMAND-EVENTS.md
│   ├── DIFFERENTIATORS.md
│   └── SMOKE-TEST.md
└── README.md
```

## Tests

```bash
./mvnw test
# 61 tests across kvstore, compaction, replay, command, lookup, api packages
```

Integration tests are pure Spring/Java unit tests against in-memory Caffeine.
End-to-end tests run via docker-compose (see SMOKE-TEST.md).

## Configuration

Defaults are sensible. See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for
all properties. Reference external config:
[deploy/docker-compose/mi-config/application.yml](deploy/docker-compose/mi-config/application.yml).

## V1.1 backlog

These work but could be polished:

- Prometheus endpoint registration (Spring Boot Actuator + MI Framework's
  NoOp meter registry interaction; metrics are collected internally but not
  exposed at `/actuator/prometheus`)
- URL-encoded slashes in REST `/api/v1/kv/{key}` path (Spring 400s); use the
  list endpoint or query parameter as a workaround for now
- Active-standby HA via MI Framework leader election
- Solace SEMP-driven queue + subscription auto-provisioning (currently
  operator-managed)
