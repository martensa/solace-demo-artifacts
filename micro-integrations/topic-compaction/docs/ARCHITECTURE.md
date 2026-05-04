# Architecture

## Overview

```
                              +-------------------------+
                              |   Solace PubSub+ Broker |
                              +-------------------------+
                              |  topics:                |
                              |   orders/>              |
                              |   compacted/command/>   |
                              |   compacted/lookup/>    |
                              +------+-------+-------+--+
                                     |       |       |
              +-----------data-------+       |       +----------lookup---+
              |  (subscribe)                 | (subscribe)               |
              v                              v                           v
    +---------------------+   +-------------------------+   +-------------------------+
    | Workflow 0          |   | Workflow 1              |   | Workflow 2              |
    | input-0:            |   | input-1:                |   | input-2:                |
    |   compaction.data   |   |   compaction.commands   |   |   compaction.lookup     |
    |                     |   |                         |   |                         |
    | ConsumerInterceptor |   | ProducerInterceptor:    |   | ProducerInterceptor:    |
    |   - loop-skip       |   |   - parse Command JSON  |   |   - extract key         |
    |   - extract topic   |   |   - kvStore.get(key)    |   |   - kvStore.get(key)    |
    |   - kvStore.put()   |   |   - rewrite payload     |   |   - rewrite payload     |
    |                     |   |   - destination =       |   |   - destination =       |
    | ProducerInterceptor:|   |       key + /compacted  |   |       solace_replyTo    |
    |   - audit JSON      |   |   - set loop-flag       |   |                         |
    |                     |   |                         |   |                         |
    | output-0:           |   | output-1:               |   | output-2:               |
    |   <topic>/          |   |   <key>/compacted       |   |   <client reply-to>     |
    |   compacted-ack     |   |                         |   |                         |
    +---------+-----------+   +-----------+-------------+   +-----------+-------------+
              |                           |                             |
              +-------------+-------------+-----------------------------+
                            |
                            v
              +---------------------------+
              |     RocksDB KV Store      |
              |  (persistent, embedded)   |
              +-----------+---------------+
                          ^
                          | reads
              +-----------+---------------+
              |  REST API @ port 8090     |
              |   GET /api/v1/kv/{key}    |
              |   GET /api/v1/kv          |
              |   DELETE /api/v1/kv/{key} |
              +---------------------------+
```

## Workflow Lifecycle

The MI Framework controls each workflow's start/stop independently, gated by
`solace.connector.workflows.<idx>.enabled`. All three workflows publish health
into the same MI's `/actuator/health` endpoint.

## Why Interceptors and not Spring Cloud Stream Functions?

The MI Framework expects every workflow to be `input-binding -> transform ->
output-binding`. We wanted to keep Compaction as a true MI workflow visible in
the Connector Manager (rather than a side-channel `Consumer<>` bean), so we use
`ConsumerBindingMessageInterceptor` to perform the KV-store update as the
consumer side-effect, then `ProducerBindingMessageInterceptor` to rewrite the
output message into an audit event.

This pattern lets the MI Framework manage start/stop, retries, ack-bridging,
and health for our workflow, while we stay in pure Java for the business logic.

## Key Storage Format

Records are stored using a length-prefixed binary format (see `RecordCodec`):
- 1-byte version
- VarInt-prefixed UTF-8 strings
- 8-byte ingest + sender timestamps
- Type-tagged headers (string/long/int/bytes/bool, fallback `toString()`)
- VarInt-prefixed payload bytes

We deliberately avoid Java serialization (insecure) and Jackson (overhead) for
the on-disk representation. RocksDB stores opaque bytes; the codec keeps the
schema explicit.

## Loop Protection

Every replay message gets the header `x-compacted-replay: true`. The compaction
interceptor checks this header first and returns immediately if set, without
touching the KV store. This prevents an obvious infinite loop where:

1. Replay publishes `<key>/compacted`
2. The compaction queue subscribes to `>` and re-consumes it
3. Compaction stores it back under `<key>/compacted` as a new key
4. ...

In practice the operator should also avoid subscribing the data queue to
`*/compacted` patterns; the header check is defense in depth.

## Idempotency / Out-of-Order Handling

Optional. When `topic-compaction.compaction.ordering.header` names a header
containing a parseable `long` (e.g. `senderTimestamp`), the compaction
interceptor compares the incoming value against any existing record's stored
sender timestamp and skips writes that would replace a newer value with an
older one.

Default: empty header name -> always-last-wins (Kafka log-compaction parity).
