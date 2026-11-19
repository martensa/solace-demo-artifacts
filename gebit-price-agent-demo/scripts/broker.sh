#!/bin/bash
# broker.sh -- broker side of the gpos demo on solace-1 (spec 9.6, 12.6):
#   scripts/broker.sh r1-create | r1-show | r1-switch OLD NEW | r1-delete | orphans
#   scripts/broker.sh txflows QUEUE | ready gpos-booth-events|gpos-probe-events
# SEMP v2 on SEMP_URL; the admin password is read at runtime from
# SEMP_PASSWORD_FROM by scripts/broker.py and never printed. Pattern:
# spikes/g0/g0-10/queue.sh. TARGET=aks (scripts/lib.sh, .env.aks): password
# from the Key Vault (SEMP_PASSWORD_KV), SEMP only via 127.0.0.1:18080 after
# the lab-broker check; broker.py opens the port-forward itself if none runs.
set -euo pipefail
. "$(dirname "$0")/lib.sh"
exec "$PY" "$DEMO_DIR/scripts/broker.py" "$@"
