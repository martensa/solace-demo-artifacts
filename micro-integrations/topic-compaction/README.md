# Topic Compaction Micro-Integration

A Solace Micro-Integration that maintains a key-value store of last-seen
messages per Solace topic, with on-demand replay via command events. A
Solace-native alternative to Kafka log compaction.

> **Built on**: Solace MDK 3.0.6 + Spring Boot 3.5 + Spring Cloud Stream Solace
> binder + RocksDB.
> **Status**: V1 MVP. End-to-end verified against Solace PubSub+ Standard.

## What it does

| Workflow | Input | Action | Output |
|----------|-------|--------|--------|
| **0 - Compaction** | `compaction.data` queue (subscribed to e.g. `orders/>`) | Stores latest message per topic in RocksDB | `<topic>/compacted-ack` (audit JSON) |
| **1 - Replay** | `compaction.commands` queue (subscribed to `compacted/command/>`) | Parses command JSON, looks up KV, republishes | `<key>/compacted` |
| **2 - Lookup** | `compaction.lookup` queue (subscribed to `compacted/lookup/>`) | Solace Request/Reply: returns latest message for the key | `solace_replyTo` of the request |
| **REST API** | HTTP `:8090` | Direct lookup / list / delete | JSON / raw payload |

See [docs/DIFFERENTIATORS.md](docs/DIFFERENTIATORS.md) for how this beats Kafka
log compaction.

## Bring your own broker

This stack runs **only the MI**. Point it at any Solace PubSub+ broker:

- **Solace Cloud** (no TLS preset is provided in `.env.example`)
- **agent-mesh-deployment broker** (the one shipping with `solace-demo-artifacts`)
- Any other PubSub+ broker reachable from your Docker host

Provision the three queues + topic subscriptions on YOUR broker before
bringing the MI up. Use [`examples/init-queues.sh`](examples/init-queues.sh)
or your preferred SEMP tool.

## Quick start

```bash
# 1. One-time setup: copy the env template and fill in your broker creds
make env-init                       # creates .env from .env.example
$EDITOR .env                        # set SOLACE_HOST, SOLACE_VPN, etc.

# 2. Provision queues on your broker (set SEMP_URL in .env first)
make provision-queues

# 3. Build + run
make build                          # mvn package + 61 tests
make image                          # build container image via jib
make up                             # docker compose up -d

# 4. Verify
curl http://localhost:18090/actuator/health
make smoke                          # end-to-end smoke test
```

## Make targets

| Target | What it does |
|--------|--------------|
| `make env-init` | Copy `.env.example` to `.env` (only if `.env` does not exist) |
| `make env-check` | Verify `.env` exists and has required keys |
| `make build` | `./mvnw clean package` |
| `make test` | `./mvnw test` (61 unit tests) |
| `make image` | Build container image into local Docker daemon (jib) |
| `make up` | `docker compose up -d` with `.env` |
| `make down` | Stop the MI (volumes preserved) |
| `make restart` | Restart only the MI container |
| `make logs` | Tail MI logs |
| `make provision-queues` | Run `examples/init-queues.sh` against your broker |
| `make smoke` | Run end-to-end smoke test |
| `make clean` | `make down -v` + remove `target/` |

## Repository layout

```
topic-compaction/
├── Makefile                       # convenience targets
├── .env.example                   # template; copy to .env (gitignored)
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
│       ├── compose.yaml                       # MI only - bring your own broker
│       └── mi-config/application.yml          # external operator config (uses ${VAR})
├── examples/
│   ├── command-events/replay.json
│   ├── command-events/replay-minimal.json
│   ├── init-queues.sh                         # provision queues + subscriptions on any broker
│   └── smoke-test.sh                          # end-to-end test driven by .env
├── docs/
│   ├── ARCHITECTURE.md
│   ├── CONFIGURATION.md
│   ├── COMMAND-EVENTS.md
│   ├── DIFFERENTIATORS.md
│   └── SMOKE-TEST.md
└── README.md
```

## Configuration

All config is YAML + env vars. Real credentials live in `.env` (gitignored)
and are referenced from `deploy/docker-compose/mi-config/application.yml` via
`${SOLACE_HOST}` / `${SOLACE_VPN}` / `${SOLACE_USERNAME}` / `${SOLACE_PASSWORD}`.

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for all properties.

## Tests

```bash
./mvnw test
# 61 tests across kvstore, compaction, replay, command, lookup, api packages
```

End-to-end tests run via docker-compose (see [docs/SMOKE-TEST.md](docs/SMOKE-TEST.md)).

## V1.1 backlog

These work but could be polished:

- Prometheus endpoint registration (Spring Boot Actuator + MI Framework's
  NoOp meter registry interaction; metrics are collected internally but not
  exposed at `/actuator/prometheus`)
- URL-encoded slashes in REST `/api/v1/kv/{key}` path (Spring 400s); use the
  list endpoint or query parameter as a workaround for now
- Active-standby HA via MI Framework leader election
- Solace SEMP-driven queue + subscription auto-provisioning
