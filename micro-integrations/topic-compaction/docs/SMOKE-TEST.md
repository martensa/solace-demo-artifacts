# End-to-End Smoke Test

Reproducible E2E test for the Topic Compaction MI on docker-compose.

## Prerequisites

- Docker (Rancher Desktop / Docker Desktop / Podman)
- Java 17, Maven (or use the bundled `mvnw`)
- `curl`, `jq` (optional)

## Setup

```bash
# 1. Build the MI (jar)
./mvnw clean package -DskipTests

# 2. Pull the base image (one-time, due to docker.io auth quirks)
docker pull eclipse-temurin:17-jre

# 3. Build the container image into the local Docker daemon
DOCKER_CONFIG=$HOME/.docker ./mvnw jib:dockerBuild -DskipTests

# 4. Start the stack (broker + MI + queue initializer)
cd deploy/docker-compose && docker compose up -d
```

The MI takes ~40 seconds to come up (Solace broker init + MI workflow start).

## Wait for ready

```bash
until curl -fsS http://localhost:18090/actuator/health 2>/dev/null > /dev/null; do
  sleep 2
done
echo "MI is up"
```

## Verify all 3 workflows are UP

```bash
curl -fsS http://localhost:18090/actuator/health | jq '.components.binders.components.solace.components.bindings.components | keys'
# Expected: ["input-0", "input-1", "input-2"]
```

## Test 1: Compaction

```bash
# Publish 3 messages on different topics matching orders/>
for k in A B C; do
  curl -fsS -u default:default \
    -X POST "http://localhost:19000/TOPIC/orders/created/${k}" \
    -H 'Content-Type: application/json' \
    -d "{\"orderId\":\"${k}\",\"amount\":${RANDOM}}"
done

# Verify all 3 keys are stored
curl -fsS 'http://localhost:18090/api/v1/kv?prefix=orders/' | jq
# Expected: count=3, keys contains orders/created/A, /B, /C
```

## Test 2: Update + last-wins

```bash
# Publish a NEW message for orders/created/A
curl -fsS -u default:default \
  -X POST 'http://localhost:19000/TOPIC/orders/created/A' \
  -H 'Content-Type: application/json' \
  -d '{"orderId":"A","amount":99,"updated":true}'

sleep 1

# Verify the count is still 3 (replace, not append)
curl -fsS 'http://localhost:18090/api/v1/kv?prefix=orders/' | jq '.count'
# Expected: 3
```

## Test 3: Replay command

In one terminal, subscribe to the replay-target topic:
```bash
curl -fsSN -u default:default 'http://localhost:19000/SUBSCRIBE/orders/created/A/compacted'
```

In another terminal, send a REPLAY command:
```bash
curl -fsS -u default:default \
  -X POST 'http://localhost:19000/TOPIC/compacted/command/replay' \
  -H 'Content-Type: application/json' \
  -d '{"command":"REPLAY","key":"orders/created/A"}'
```

The first terminal should receive the latest stored payload for `orders/created/A`.

## Test 4: Loop protection

After test 3, check the MI logs:
```bash
docker compose logs topic-compaction-mi --since=1m | grep -i "loop"
# Expected: at least one line:
#   Skipping compaction: message has loop-protection header x-compacted-replay=true
```

This proves the replay didn't get re-compacted (no infinite cycle).

## Test 5: Tombstone via REST

```bash
curl -fsS -X DELETE 'http://localhost:18090/api/v1/kv/orders%2Fcreated%2FC'
curl -fsS 'http://localhost:18090/api/v1/kv?prefix=orders/' | jq '.count'
# Expected: 2 (C is gone)
```

## Test 6: Failure path

Send a REPLAY for an unknown key:
```bash
curl -fsS -u default:default \
  -X POST 'http://localhost:19000/TOPIC/compacted/command/replay' \
  -H 'Content-Type: application/json' \
  -d '{"command":"REPLAY","key":"this-was-never-stored"}'
```

In the MI logs:
```bash
docker compose logs topic-compaction-mi --since=10s | grep -i "replay"
# Expected: Replay command failed: No record stored for key: this-was-never-stored
```

A failure document should also be published to `topic-compaction/replay/failed`.

## Teardown

```bash
docker compose down -v
```
