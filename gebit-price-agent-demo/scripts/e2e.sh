#!/bin/bash
# e2e.sh -- end to end with SAM from the Mac (spec 13.4), see scripts/e2e.py --help:
#   scripts/e2e.sh --till 01 --scenario S1 --mode approve --runs 20
#   scripts/e2e.sh --gate-verify            (make gate-verify, spec 9.9)
# HTTPS against E2E_BASE_URL with E2E_CA_FILE; broker probes run in the pod.
set -euo pipefail
. "$(dirname "$0")/lib.sh"
[ -x "$DEMO_DIR/.venv/bin/python" ] || die ".venv missing: make venv"
exec "$DEMO_DIR/.venv/bin/python" "$DEMO_DIR/scripts/e2e.py" "$@"
