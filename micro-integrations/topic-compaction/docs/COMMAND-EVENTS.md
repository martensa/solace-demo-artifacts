# Command Events

Clients drive the replay flow by publishing JSON command events to the command
queue (default subscription: `compacted/command/>`).

## V1 Schema

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
| `command` | string | yes | currently only `REPLAY`. Case-insensitive. |
| `key` | string | yes | the topic whose latest message should be republished |
| `options` | object | no | extension point for forward-compat; unknown fields are ignored |
| `options.destinationSuffix` | string | no | overrides `topic-compaction.replay.target-suffix` |
| `options.correlationId` | string | no | echoed onto the replay message as `x-original-correlation-id` |
| `options.includeOriginalHeaders` | boolean | no | default `true`; set `false` to drop the original headers from the replay |

## Behavior

On a successful REPLAY:
- Look up `key` in the KV store
- Publish the stored payload to `<key><destinationSuffix>` (default: `<key>/compacted`)
- Set Solace user property `x-compacted-replay: true` on the replay message (loop guard)
- Optionally include original headers from the stored record
- Emit `x-original-correlation-id` if `correlationId` was provided

On failure (unknown command, missing key, key not in KV store):
- Publish a small JSON failure document to `topic-compaction/replay/failed`
- The original command message is acked (it was processed correctly even though the lookup failed)

## Example: minimal

```json
{ "command": "REPLAY", "key": "orders/created/12345" }
```

## Example: with correlation

```json
{
  "command": "REPLAY",
  "key": "users/profile/u-42",
  "options": {
    "correlationId": "ticket-9923"
  }
}
```

## Reserved for V2

These commands are recognized as reserved (will fail with "not supported in V1"
rather than "unknown"):
- `DELETE` - tombstone a key
- `BULK_REPLAY` - replay all keys matching a pattern

## Forward Compatibility

The MI ignores unknown top-level fields in the command JSON, so newer clients
can send richer payloads against older MI versions without breaking. Unknown
fields inside `options` are also tolerated.
