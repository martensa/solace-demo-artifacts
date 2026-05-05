#!/usr/bin/env bash
# =============================================================================
# Load test stub for the Topic Compaction MI.
#
# Drives a configurable producer rate against the broker via REST
# (the `/TOPIC/<topic>` SMF-over-HTTP endpoint), then samples
# `/actuator/prometheus` to derive throughput, lookup latency, and
# KV growth. This is a minimal harness suitable for the lab demo;
# production benchmarking should use sdkperf with the JCSMP client.
#
# Usage:
#   ./examples/load-test.sh [--rate RATE] [--duration SECONDS]
#                           [--keys KEYS] [--prefix PREFIX]
#
#   --rate     target msg/s (default 100; honest cap is whatever
#              your bash + curl can drive, typically a few hundred)
#   --duration test duration in seconds (default 30)
#   --keys     unique key cardinality (default 100)
#   --prefix   topic prefix for the load (default loadtest/orders)
#
# Reads broker creds from ../.env. Reads the MI port from MI_PORT.
#
# Output: one summary line per second to stdout, plus a final
# table comparing the ingest rate to the observed compaction rate
# and lookup p95 latency.
# =============================================================================
set -euo pipefail

ENV_FILE="$(cd "$(dirname "$0")/.." && pwd)/.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
else
  echo "ERROR: ${ENV_FILE} not found." >&2
  exit 1
fi

RATE=100
DURATION=30
KEYS=100
# Default prefix is under `orders/` so the existing
# `compaction.data` queue subscription (`orders/>`) catches it
# without needing a new SEMP subscription.
PREFIX="orders/loadtest"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --rate) RATE="$2"; shift 2 ;;
    --duration) DURATION="$2"; shift 2 ;;
    --keys) KEYS="$2"; shift 2 ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    -h|--help)
      grep "^#" "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown flag: $1" >&2; exit 2 ;;
  esac
done

BROKER_REST="${SOLACE_REST_HOST:-http://localhost:9000}"
BROKER_USER="${SOLACE_REST_USER:-default}"
BROKER_PASS="${SOLACE_REST_PASS:-default}"
MI_REST="http://localhost:${MI_PORT:-18090}"

if [ -n "${MI_USER_NAME:-}" ] && [ -n "${MI_USER_PASSWORD:-}" ]; then
  MI_AUTH=(-u "$MI_USER_NAME:$MI_USER_PASSWORD")
else
  MI_AUTH=()
fi

INTERVAL_NS=$((1000000000 / RATE))

echo "===================================================="
echo " Load test"
echo "----------------------------------------------------"
echo "  rate     : ${RATE} msg/s"
echo "  duration : ${DURATION} s"
echo "  keys     : ${KEYS} unique"
echo "  prefix   : ${PREFIX}"
echo "  broker   : ${BROKER_REST}"
echo "  mi       : ${MI_REST}"
echo "===================================================="

# Snapshot starting metrics
counter() {
  local name="$1"
  curl -fsS "${MI_REST}/actuator/prometheus" 2>/dev/null \
    | awk -v n="^${name}" '$0 ~ n {gsub(/[^0-9.]/,"",$NF); print $NF; exit}' \
    || echo "0"
}

UPSERTS_BEFORE=$(counter "topic_compaction_upserts_total")
UPSERTS_BEFORE=${UPSERTS_BEFORE:-0}

# -----------------------------------------------------------------------------
# Drive the load. Use background curl with a token-bucket style sleep
# in bash (microsecond precision via `printf`+`date`).
# -----------------------------------------------------------------------------
START=$(date +%s)
END=$((START + DURATION))
PID_FILE=$(mktemp -t topic-compaction-load.pids.XXXXXX)
trap 'while read p; do kill "$p" 2>/dev/null; done < "$PID_FILE"; rm -f "$PID_FILE"' EXIT

i=0
while [ "$(date +%s)" -lt "$END" ]; do
  k=$((i % KEYS))
  body="{\"orderId\":${k},\"i\":${i}}"
  curl -fsS --max-time 5 -u "${BROKER_USER}:${BROKER_PASS}" \
      -X POST "${BROKER_REST}/TOPIC/${PREFIX}/${k}" \
      -H 'Content-Type: application/json' \
      -d "$body" >/dev/null 2>&1 &
  echo $! >> "$PID_FILE"
  i=$((i + 1))

  # Pace the loop. bash sleep is sub-second-precision via the
  # built-in float arg.
  sleep_seconds=$(awk -v r="$RATE" 'BEGIN {printf "%.4f", 1/r}')
  sleep "$sleep_seconds"

  # Once a second, print a progress line.
  if [ $((i % RATE)) -eq 0 ]; then
    elapsed=$(($(date +%s) - START))
    upserts_now=$(counter "topic_compaction_upserts_total")
    upserts_now=${upserts_now:-0}
    delta=$(awk -v a="$upserts_now" -v b="$UPSERTS_BEFORE" \
        'BEGIN { printf "%.0f", a - b }')
    rate_observed=$(awk -v d="$delta" -v e="$elapsed" \
        'BEGIN { if (e > 0) printf "%.0f", d / e; else print 0 }')
    printf "  t=%3ds sent=%-6d compactions_observed=%-6d rate=%d/s\n" \
        "$elapsed" "$i" "$delta" "$rate_observed"
  fi
done

# Wait for any remaining background curls.
wait

# -----------------------------------------------------------------------------
# Final summary
# -----------------------------------------------------------------------------
echo
echo "===================================================="
echo " Final"
echo "----------------------------------------------------"
UPSERTS_AFTER=$(counter "topic_compaction_upserts_total")
UPSERTS_AFTER=${UPSERTS_AFTER:-0}
COMPACTIONS=$(awk -v a="$UPSERTS_AFTER" -v b="$UPSERTS_BEFORE" \
    'BEGIN { printf "%.0f", a - b }')
INGEST_RATE_TARGET=$(awk -v r="$RATE" 'BEGIN { print r }')
COMPACT_RATE=$(awk -v c="$COMPACTIONS" -v d="$DURATION" \
    'BEGIN { printf "%.0f", c / d }')

KV_SIZE=$(curl -fsS "${MI_AUTH[@]}" "${MI_REST}/api/v1/kv?prefix=${PREFIX}/" 2>/dev/null \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["count"])' \
    2>/dev/null || echo "?")

LOOKUP_P95=$(curl -fsS "${MI_REST}/actuator/prometheus" 2>/dev/null \
    | awk '/^topic_compaction:lookup_p95_seconds:5m/ {print $NF; exit}' \
    | head -c 12)

printf "  target ingest rate  : %s msg/s\n" "$INGEST_RATE_TARGET"
printf "  observed compactions: %s in %ss = ~%s/s\n" \
    "$COMPACTIONS" "$DURATION" "$COMPACT_RATE"
printf "  unique keys in KV   : %s\n" "$KV_SIZE"
printf "  lookup p95 (5m)     : %ss\n" "${LOOKUP_P95:-n/a}"
echo "===================================================="
