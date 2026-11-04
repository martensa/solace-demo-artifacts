#!/bin/bash
# reset.sh -- back to the starting state in well under a minute:
#   scenario reset (reference levels back), all watches cleared,
#   issuer status normal, UI event stream cleared.
# Running workflow runs: they finish or time out within
# workflow_timeout (90 s); cancelling them via the platform API is a
# Gate 0 item (README "Open points").
set -euo pipefail
. "$(dirname "$0")/lib.sh"

ui_exec reset
kubectl -n "$NS" exec deploy/demo-ui -- python -c \
  "import httpx; print(httpx.post('http://127.0.0.1:8080/api/reset').json())"
echo "   watches now:"
kubectl -n "$NS" exec deploy/demo-ui -- python -c \
  "import httpx; print(httpx.get('http://feed-watcher.bsg-demo.svc:8080/watches').json())"
