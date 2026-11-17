#!/bin/bash
# G0-08a main run: sampler (read-only, every 60 s) + load generator
# (450 runs/h, bursts of 7 every 56 s, 30 min) against the G0-01 stub
# workflow. Broker creds for MQTT from bsg-trading-desk-demo/.env.
#   ./run.sh <events.jsonl> <tag>
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
EVENTS="$1"; TAG="${2:-main}"
PY="${PY:-python3}"
set -a; . "$HERE/../../../../bsg-trading-desk-demo/.env"; set +a
cd "$HERE"
SINCE=$(date +%s)
"$PY" sample_lab.py --out "logs/$TAG-samples.jsonl" --tasks-out "logs/$TAG-tasks.jsonl" \
  --duration "${SAMPLE_S:-1950}" --interval 60 --since "$SINCE" > "logs/$TAG-samples.txt" 2>&1 &
SPID=$!
sleep 10
"$PY" load_gen.py --events "$EVENTS" --log "logs/$TAG-run.jsonl" --rate 450 --burst 7 \
  --duration "${DURATION_S:-1800}" --timeout 60 --tag "$TAG" > "logs/$TAG-run.txt" 2>&1
echo "load_gen exit $?" >> "logs/$TAG-run.txt"
wait "$SPID"
echo "sampler exit $?" >> "logs/$TAG-samples.txt"
