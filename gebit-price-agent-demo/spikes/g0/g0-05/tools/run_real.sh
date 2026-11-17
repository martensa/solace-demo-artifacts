#!/bin/bash
# G0-05 real prop photos: read every real/*.jpg through
#   s3a    = workflow, agent node gpos-spike-p05-scout-la (load_artifact),
#            same model and node as fallback A2b (only the transport differs)
#   s3b/iv = agent target with inline vision (fallback A2)
# and write results/real-<rule>.jsonl. Expected values: real/expected.json.
#   ./tools/run_real.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PY=${PY:-python3}
set -a; . "$HERE/../../../../bsg-trading-desk-demo/.env"; set +a
cd "$HERE"
for f in real/*.jpg; do
  "$PY" tools/photo_probe.py --rule s3a --img "$f" --prefix user: --wait 40 \
    >> results/real-s3a.jsonl
  "$PY" tools/photo_probe.py --rule s3b/iv --img "$f" --wait 40 \
    >> results/real-s3biv.jsonl
done
echo "done: results/real-s3a.jsonl results/real-s3biv.jsonl"
