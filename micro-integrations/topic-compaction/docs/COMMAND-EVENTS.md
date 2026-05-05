# Command Events

Clients drive the replay/delete flows by publishing JSON command
events to the command queue (default subscription:
`compacted/command/>`).

The on-the-wire envelope is validated against the JSON Schema at
`src/main/resources/schemas/command-event-v1.json` before the MI
acts on it. Schema violations result in a small failure document
published to `topic-compaction/replay/failed`.

## V1.0 Schema

```json
{
  "command": "REPLAY",
  "key": "orders/created/12345",
  "options": {
    "destinationSuffix": "/compacted",
    "correlationId": "trace-abc",
    "includeOriginalHeaders": true
  }
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `command` | string | yes | `REPLAY`, `BULK_REPLAY`, or `DELETE`. Case-insensitive. |
| `key` | string | for REPLAY and DELETE | The KV key to replay or tombstone |
| `pattern` | string | for BULK_REPLAY | Solace topic pattern with `*` (one level) or `>` (multi-level) wildcards |
| `options` | object | no | Forward-compat extension; unknown fields tolerated |

### Common options

| Field | Type | Applies to | Notes |
|---|---|---|---|
| `destinationSuffix` | string | REPLAY, BULK_REPLAY | Override the per-replay target-suffix (default: `/compacted`) |
| `correlationId` | string | all | Echoed onto the result message as `x-original-correlation-id` |
| `includeOriginalHeaders` | boolean | REPLAY, BULK_REPLAY | Default `true`; set `false` to drop original headers |

### BULK_REPLAY-specific options

| Field | Type | Notes |
|---|---|---|
| `rateLimit` | integer | Maximum messages per second (default 1000, max 100000) |

### DELETE-specific options

| Field | Type | Notes |
|---|---|---|
| `cascade` | string | Optional Solace pattern for bulk deletion |

## REPLAY

Single-key replay. Looks up the requested key in the KV store and
re-publishes its latest payload to `<key><destinationSuffix>`.

```json
{ "command": "REPLAY", "key": "orders/created/12345" }
```

Behaviour:

- Look up `key` in the KV store.
- If found: publish the stored payload to `<key><destinationSuffix>`.
- Set Solace user property `x-compacted-replay: true` on the replay
  message (loop guard).
- Optionally include original headers from the stored record.
- Emit `x-original-correlation-id` if `correlationId` was provided.

On failure (key not in KV, schema violation): publish a small JSON
failure document to `topic-compaction/replay/failed`.

## BULK_REPLAY

Pattern-based fanout replay. Iterates the KV store and re-publishes
every record whose key matches the supplied Solace pattern.

```json
{
  "command": "BULK_REPLAY",
  "pattern": "orders/created/>",
  "options": {
    "rateLimit": 500,
    "correlationId": "bootstrap-2026-05-05"
  }
}
```

Pattern syntax (matches Solace topic-subscription wildcards):

- `*` matches exactly one topic level.
- `>` matches the remainder of the topic (one or more levels). May
  only appear as the final character.

Behaviour:

- Iterate the KV store using a RocksDB prefix-iterator seeded with
  the longest non-wildcard prefix.
- For each match: publish the stored payload to
  `<key><destinationSuffix>` via the `output-3` (fanout) binding.
  Loop-protection header is set on every message.
- Throttle to `rateLimit` messages per second (Bucket4j).
- After the iteration, publish a JSON summary to
  `topic-compaction/replay/bulk-result`:

  ```json
  {
    "status": "completed",
    "pattern": "orders/created/>",
    "matched": 1247,
    "replayed": 1247,
    "failed": 0,
    "durationMs": 3400,
    "correlationId": "bootstrap-2026-05-05"
  }
  ```

On failure (invalid pattern, missing pattern): publish a failure
document to `topic-compaction/replay/failed`.

## DELETE

Tombstones a key (and optionally a pattern). Deferred to Phase 3.3.

```json
{ "command": "DELETE", "key": "orders/created/12345" }
```

```json
{
  "command": "DELETE",
  "key": "orders/created/legacy",
  "options": { "cascade": "orders/created/legacy/*" }
}
```

## Forward Compatibility

- The MI tolerates unknown top-level fields (Jackson is configured
  with `ignoreUnknown = true`).
- Unknown fields inside `options` are tolerated; the schema marks
  `additionalProperties: true`.
- Adding a new command: extend the JSON Schema's enum, add a
  `CommandType` enum value, route in
  `ReplayProducerInterceptorFactory.before(...)`. Old clients keep
  working because the schema is the boundary.

## End-to-End Examples

### REPLAY via REST publish

```bash
curl -X POST -u "$SOLACE_REST_USER:$SOLACE_REST_PASS" \
  "$SOLACE_REST_HOST/TOPIC/compacted/command/replay" \
  -H 'Content-Type: application/json' \
  -d '{"command":"REPLAY","key":"orders/created/12345"}'
```

### BULK_REPLAY via REST publish

```bash
curl -X POST -u "$SOLACE_REST_USER:$SOLACE_REST_PASS" \
  "$SOLACE_REST_HOST/TOPIC/compacted/command/bulk-replay" \
  -H 'Content-Type: application/json' \
  -d '{"command":"BULK_REPLAY","pattern":"orders/created/>"}'
```

Subscribe to `topic-compaction/replay/bulk-result` (or to your
specific replay destinations under `<key>/compacted`) to observe
the result events.
