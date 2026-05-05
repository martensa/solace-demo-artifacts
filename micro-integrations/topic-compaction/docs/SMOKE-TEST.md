# End-to-End Smoke Test

Reproducible end-to-end test for the Topic Compaction MI. The
`examples/smoke-test.sh` script is fully non-interactive,
exit-code-clean, and the canonical CI-style integration check.

## Prerequisites

- Docker (Rancher Desktop / Docker Desktop / Podman)
- Java 17, Maven (or use the bundled `mvnw`)
- `curl`, `python3` (used for JSON parsing in the script)
- A Solace PubSub+ broker (Solace Cloud, agent-mesh-deployment,
  etc.) reachable from the host
- Broker queues + subscriptions provisioned (see
  `examples/init-queues.sh` or the SEMP-driven provisioning in
  Phase 4.2)

## Quick start

```bash
make env-init                         # cp .env.example .env
$EDITOR .env                          # broker creds
make provision-queues                 # one-time SEMP provisioning
make build                            # mvn package
make image                            # build container image
make up                               # docker compose up -d
make smoke                            # the smoke test
```

`make smoke` runs `examples/smoke-test.sh` and exits 0 if all
ten assertions pass.

## Modes

```bash
./examples/smoke-test.sh         # default: docker-compose at localhost:18090
./examples/smoke-test.sh --k8s   # port-forward the K8s service first
```

The `--k8s` mode starts a `kubectl port-forward` to
`mi-solace-lab/topic-compaction-mi`, runs the same assertions
against it, and tears the port-forward down at the end.

## What it checks

```text
=== 1. Sanity ===
  [PASS] health 200
  [PASS] prometheus 200

=== 2. Compaction round trip ===
  [PASS] kv count after 3+1 publishes               (last-wins, count=3)
  [PASS] last-wins on key A

=== 3. Replay ===
  [PASS] replay counter incremented

=== 4. Bulk replay command accepted ===
  [PASS] bulk-replay command published

=== 5. Tombstone via REST ===
  [PASS] delete C returns 204
  [PASS] C is gone (404)

=== 6. Backup admin endpoint ===           (only when admin auth set)
  [PASS] backup returns 200
  [PASS] backup header v1
```

Every assertion drives an exit-code increment; a single failure
returns a non-zero exit so CI can gate on `make smoke`.

## What it does NOT check

- Broker queue + subscription topology -- assumed to be in place
  via `make provision-queues` or external operator action.
- The actual contents of replay messages on the wire -- the
  smoke test asserts the counter increments, not that a
  subscriber received the payload (would require a long-lived
  consumer outside the script's scope).
- Security role matrix -- run `examples/load-test.sh` or use the
  curl matrix in `docs/SECURITY.md` for that.
- Performance characteristics -- see `docs/PERFORMANCE.md` and
  `examples/load-test.sh`.

## Manual exploration

If you want to drive the MI by hand instead of via the script,
the building blocks below mirror what `smoke-test.sh` does
internally. Loading `.env` for the curl examples:

```bash
set -a; . ./.env; set +a
```

### Wait for readiness

```bash
until curl -fsS http://localhost:${MI_PORT}/actuator/health \
        > /dev/null 2>&1; do
  sleep 2
done
echo "MI is up"
```

### Verify all three workflows are UP

```bash
curl -fsS http://localhost:${MI_PORT}/actuator/health/readiness \
  | jq '.components.binders.components.solace.components.bindings'
```

### Compaction

```bash
for k in A B C; do
  curl -fsS -u "${SOLACE_REST_USER}:${SOLACE_REST_PASS}" \
    -X POST "${SOLACE_REST_HOST}/TOPIC/orders/created/${k}" \
    -H 'Content-Type: application/json' \
    -d "{\"orderId\":\"${k}\",\"amount\":${RANDOM}}"
done

curl -fsS "http://localhost:${MI_PORT}/api/v1/kv?prefix=orders/" \
  | jq
```

### Replay command

```bash
curl -fsS -u "${SOLACE_REST_USER}:${SOLACE_REST_PASS}" \
  -X POST "${SOLACE_REST_HOST}/TOPIC/compacted/command/replay" \
  -H 'Content-Type: application/json' \
  -d '{"command":"REPLAY","key":"orders/created/A"}'
```

To observe the replayed message: subscribe a Solace client (Try
Me!, MQTT, sdkperf, ...) to `orders/created/A/compacted` before
publishing the command. The HTTP `/SUBSCRIBE/...` endpoint of
Solace Cloud's REST messaging API does NOT support streaming for
ad-hoc topic subscription; use a real Solace client.

### Bulk replay

```bash
curl -fsS -u "${SOLACE_REST_USER}:${SOLACE_REST_PASS}" \
  -X POST "${SOLACE_REST_HOST}/TOPIC/compacted/command/bulk-replay" \
  -H 'Content-Type: application/json' \
  -d '{"command":"BULK_REPLAY","pattern":"orders/created/*"}'
```

The summary event lands on `topic-compaction/replay/bulk-result`.

### Delete (tombstone)

Via REST:

```bash
curl -fsS -X DELETE \
    -u "${MI_ADMIN_NAME}:${MI_ADMIN_PASSWORD}" \
    "http://localhost:${MI_PORT}/api/v1/kv/orders/created/C"
```

Via command event:

```bash
curl -fsS -u "${SOLACE_REST_USER}:${SOLACE_REST_PASS}" \
  -X POST "${SOLACE_REST_HOST}/TOPIC/compacted/command/delete" \
  -H 'Content-Type: application/json' \
  -d '{"command":"DELETE","key":"orders/created/C"}'
```

### Backup / restore (admin)

```bash
curl -fsS -u "${MI_ADMIN_NAME}:${MI_ADMIN_PASSWORD}" \
    -X POST http://localhost:${MI_PORT}/api/v1/admin/backup \
    -o backup.ndjson

curl -fsS -u "${MI_ADMIN_NAME}:${MI_ADMIN_PASSWORD}" \
    -X POST http://localhost:${MI_PORT}/api/v1/admin/restore \
    -H 'Content-Type: application/x-ndjson' \
    --data-binary @backup.ndjson
```

## Teardown

```bash
make clean       # docker compose down -v + rm target/
```

## See also

- `docs/COMMAND-EVENTS.md` -- full schema for replay / bulk /
  delete commands
- `docs/OPERATIONS.md` -- runbook
- `docs/PERFORMANCE.md` -- load-test harness
- `examples/smoke-test.sh` -- the script under test here
