# Differentiators vs Kafka Log Compaction

Kafka log compaction is the well-known reference design for "keep the last
value per key" semantics. This MI implements the same pattern but on Solace
PubSub+ with several material advantages.

| Aspect | Kafka Log Compaction | Topic Compaction MI |
|--------|----------------------|---------------------|
| **Cleanup model** | Eventual / async; runs in a Log Cleaner background thread, may take minutes to hours | **Immediate**: every consumed message updates the KV store synchronously before ack |
| **Direct lookup** | Not supported. To get latest per key you must consume the entire compacted topic and rebuild state | **O(1) lookup** via REST (`GET /api/v1/kv/{key}`) and Solace Request/Reply |
| **Tombstones** | `null` payload at a key, fragile (some serializers reject null), interpreted by background cleaner | Explicit `DELETE` command (event or REST), with optional cascade pattern. Clean semantics, auditable result events |
| **Topic / key model** | Flat - each Kafka topic is independent; you partition manually | **Hierarchical**: one MI handles a whole topic tree via Solace wildcard subscriptions (`orders/>`) |
| **Replay-on-demand** | Not supported. Consumers must rewind offsets and re-process | **Command-driven replay**: publish a JSON command, the MI republishes the latest value to `<key>/compacted`. Single-key REPLAY and pattern-based BULK_REPLAY both supported |
| **Bulk re-bootstrap** | Re-consume the whole topic | `BULK_REPLAY` command iterates the KV store and re-publishes only the surviving records to a downstream consumer |
| **TTL / retention** | Time-based policy at the topic level; one knob per topic | Per-prefix retention rules (e.g. `orders/` -> 7d, `ephemeral/` -> 1h) with a configurable sweeper |
| **Backup / restore** | rsync the log segments; risky and ad-hoc | Streaming line-delimited JSON via `POST /api/v1/admin/backup` and `/restore`. Roundtrip-tested |
| **State recovery on restart** | Re-read the entire compacted topic from offset 0 (slow, expensive) | **Local persistent state** in RocksDB - restart picks up exactly where it left off |
| **Partition planning** | Required, hard to change after the fact | None. Solace routes by topic |
| **Partition skew problems** | Hot keys hit single brokers / consumers | None. KV store is single-flight per key |
| **Audit / observability** | Difficult: cleanup happens in background, hard to verify | **Audit topic**: every compaction emits to `<topic>/compacted-ack` with size + outcome |
| **Multi-tenancy** | Cluster-bound; cross-cluster needs MirrorMaker | Solace VPNs + topic prefixes give native isolation |
| **Embedded backend** | Kafka + ZooKeeper / KRaft cluster required | Single Spring Boot JAR + RocksDB (no external services) |
| **State store backend** | Internal LSM in the cleaner thread | RocksDB - same battle-tested LSM that Kafka Streams uses internally for its state stores |

## What we use from "the enemy's" toolkit

- **RocksDB** - we deliberately picked the same LSM-tree state store backend
  that Kafka Streams uses internally. We expose it cleanly while Kafka hides
  it. Microsecond p99 reads.
- **Length-prefixed binary record format** - similar disciplined approach to
  Kafka's record format, but explicit about supported header types.

## What we do that Kafka can't

- **Direct lookup API** - Kafka forces you to build a stream-table topology and
  query state stores through Kafka Streams or KSQL. We give you a REST endpoint.
- **On-demand replay to a different topic** - Kafka has no concept of "publish
  the current value of key X to a new topic on demand."
- **Hierarchical wildcard ingestion** - one MI instance compacts every topic
  matching `orders/>`, no per-topic configuration.
- **Solace Request/Reply lookup** - clients can do a single Solace
  request/reply for the latest value, no Kafka client SDK needed.

## Where Kafka still wins

- **Multi-broker write throughput on a single topic** - Kafka's partitions
  scale write throughput linearly. This MI is single-instance per VPN
  today (ADR 0002). A future V2 with active-standby (and possibly
  active-active read replicas) will close part of this gap; in practice
  most compaction use cases are read-dominant.
- **Mature operator tooling** - Kafka has decades of dashboards, alerting,
  rebalancing tools. V1.0 of this MI ships its own LGTM-stack-aware
  observability bundle: a Grafana dashboard, an SLO-based PrometheusRule
  with five named alerts, and a runbook (`docs/OPERATIONS.md`); the
  dashboard panels and alerts share recording rules so they never
  drift. That closes most of the everyday gap.
