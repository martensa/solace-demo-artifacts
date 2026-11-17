#!/bin/bash
# port_forward.sh -- every port of spec 12.4 on localhost until Ctrl-C:
#   gRPC 50051 (pos) 50052 (loyalty) 50053 (wws), MCP 8765 (engine) 8766 (gate)
#   8771 (pos) 8772 (loyalty) 8773 (wws), UI http://localhost:8090
# The gRPC host names resolve via /etc/hosts (spec 12.4): emergency fallback for wws
# and loyalty; POS gRPC only this way until the owner applies Ingress gpos-grpc.
set -euo pipefail
. "$(dirname "$0")/lib.sh"
trap 'kill $(jobs -p) 2>/dev/null' EXIT INT TERM
kubectl -n "$NS" port-forward svc/gpos-pos 50051:50051 8771:8771 &
kubectl -n "$NS" port-forward svc/gpos-loyalty 50052:50052 8772:8772 &
kubectl -n "$NS" port-forward svc/gpos-wws 50053:50053 8773:8773 &
kubectl -n "$NS" port-forward svc/gpos-engine 8765:8765 &
kubectl -n "$NS" port-forward svc/gpos-gate 8766:8766 &
kubectl -n "$NS" port-forward svc/gpos-ui 8090:80 &
wait
