# End-to-End Smoke Test

Reproducible E2E test for the Topic Compaction MI on docker-compose.

## Prerequisites

- Docker (Rancher Desktop / Docker Desktop / Podman)
- Java 17, Maven (or use the bundled `mvnw`)
- `curl`, `jq` (optional)
- A Solace PubSub+ broker (Solace Cloud, agent-mesh-deployment, etc.)

## Setup

```bash
# 1. Configure broker connection
make env-init            # creates .env from .env.example
$EDITOR .env             # fill in SOLACE_HOST, SOLACE_VPN, SOLACE_USERNAME, SOLACE_PASSWORD

# 2. Provision queues + subscriptions on your broker
#    (set SEMP_URL inside .env first - see .env.example for the URL format)
make provision-queues

# 3. Pull the base image (one-time, docker.io anonymous-pull quirk)
docker pull eclipse-temurin:17-jre

# 4. Build the container image into the local Docker daemon
make image

# 5. Start the MI
make up
```

The MI takes ~40 seconds to fully connect to the broker and report all
workflows ready.

All `curl` commands below assume `.env` is loaded:

```bash
set -a; . ./.env; set +a
```

## Wait for ready

```bash
until curl -fsS http://localhost:${MI_PORT}/actuator/health > /dev/null 2>&1; do
  sleep 2
done
echo "MI is up"
```

## Verify all 3 workflows are UP

```bash
curl -fsS http://localhost:${MI_PORT}/actuator/health \
  | jq '.components.binders.components.solace.components.bindings.components | keys'
# Expected: ["input-0", "input-1", "input-2"]
```

## Test 1: Compaction

```bash
# Publish 3 messages on different topics matching orders/>
for k in A B C; do
  curl -fsS -u "${SOLACE_REST_USER}:${SOLACE_REST_PASS}" \
    -X POST "${SOLACE_REST_HOST}/TOPIC/orders/created/${k}" \
    -H 'Content-Type: application/json' \
    -d "{\"orderId\":\"${k}\",\"amount\":${RANDOM}}"
done

# Verify all 3 keys are stored
curl -fsS "http://localhost:${MI_PORT}/api/v1/kv?prefix=orders/" | jq
# Expected: count=3, keys contains orders/created/A, /B, /C
```

## Test 2: Update + last-wins

```bash
curl -fsS -u "${SOLACE_REST_USER}:${SOLACE_REST_PASS}" \
  -X POST "${SOLACE_REST_HOST}/TOPIC/orders/created/A" \
  -H 'Content-Type: application/json' \
  -d '{"orderId":"A","amount":99,"updated":true}'

sleep 1
curl -fsS "http://localhost:${MI_PORT}/api/v1/kv?prefix=orders/" | jq '.count'
# Expected: 3
```

## Test 3: Replay command

In one terminal, subscribe to the replay-target topic:
```bash
curl -fsSN -u "${SOLACE_REST_USER}:${SOLACE_REST_PASS}" \
  "${SOLACE_REST_HOST}/SUBSCRIBE/orders/created/A/compacted"
```

In another terminal, send a REPLAY command:
```bash
curl -fsS -u "${SOLACE_REST_USER}:${SOLACE_REST_PASS}" \
  -X POST "${SOLACE_REST_HOST}/TOPIC/compacted/command/replay" \
  -H 'Content-Type: application/json' \
  -d '{"command":"REPLAY","key":"orders/created/A"}'
```

The first terminal should receive the latest stored payload for `orders/created/A`.

## Test 4: Loop protection

After test 3, check the MI logs:
```bash
make logs | grep -i "loop"
# Expected:
#   Skipping compaction: message has loop-protection header x-compacted-replay=true
```

## Test 5: Tombstone via REST

```bash
curl -fsS -X DELETE "http://localhost:${MI_PORT}/api/v1/kv/orders%2Fcreated%2FC"
curl -fsS "http://localhost:${MI_PORT}/api/v1/kv?prefix=orders/" | jq '.count'
# Expected: 2 (C is gone)
```

## Test 6: Failure path

```bash
curl -fsS -u "${SOLACE_REST_USER}:${SOLACE_REST_PASS}" \
  -X POST "${SOLACE_REST_HOST}/TOPIC/compacted/command/replay" \
  -H 'Content-Type: application/json' \
  -d '{"command":"REPLAY","key":"this-was-never-stored"}'

make logs | grep -i "replay"
# Expected: Replay command failed: No record stored for key: this-was-never-stored
```

A failure document should also be published to `topic-compaction/replay/failed`.

## Teardown

```bash
make clean       # docker compose down -v + rm target/
```
