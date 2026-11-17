#!/bin/bash
# smoke.sh -- lab smoke test without SAM (spec 13.3): runs scripts/smoke.py inside
# deploy/gpos-ui (cluster DNS, broker Secret, gposdemo package), test till 99 of
# store 199, never triggers SAM. Prints READY / NOT READY with the first error.
set -euo pipefail
. "$(dirname "$0")/lib.sh"
kubectl -n "$NS" exec -i deploy/gpos-ui -- python - "$@" < "$DEMO_DIR/scripts/smoke.py"
