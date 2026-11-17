#!/bin/bash
# reset.sh [--scope booth|day] [--preflight] -- back to the starting state (spec 11.7)
#   1-5  BFF reset chain in the pod: engine (open reviews and proposals ->
#        superseded), WWS (booth actions ended), POS (open baskets), loyalty,
#        BFF counters; scope day also clears the runtime data of the day
#   6    open gpos approval requests in the SAM inbox -> cancelled, strictly
#        AFTER step 1 (a late approval then ends `superseded` in the gate)
#   7    scope day: inbox hygiene (A-23, count only)
#   +    orphaned SAM queues under .../eventmesh/ (hard rule 4)
#   --preflight: login/notify check on probe till 98 (spec 9.7)
# Target < 15 s (A14). Run before every fair day and every probe, not only the
# reset button of /kasse (which cannot reach the SAM inbox).
set -euo pipefail
. "$(dirname "$0")/lib.sh"

SCOPE=booth; PREFLIGHT=0
while [ $# -gt 0 ]; do
  case "$1" in
    --scope) SCOPE="${2:-}"; shift 2 ;;
    --preflight) PREFLIGHT=1; shift ;;
    *) die "usage: $0 [--scope booth|day] [--preflight]" ;;
  esac
done
case "$SCOPE" in booth|day) ;; *) die "--scope must be booth or day" ;; esac

START=$SECONDS
RC=0
step "1-5 reset chain via the BFF (scope $SCOPE)"
ui_ctl reset --scope "$SCOPE" || die "ui.ctl reset failed"
step "6 open gpos approval requests"
# sam api uses the CLI login cache; opslib refreshes it once on a 401
"$PY" "$DEMO_DIR/scripts/sam_inbox.py" cancel-gpos || { echo "   ERROR: inbox not cleared"; RC=1; }
if [ "$SCOPE" = day ]; then
  step "7 inbox hygiene"
  "$PY" "$DEMO_DIR/scripts/sam_inbox.py" hygiene || true
fi
step "orphaned SAM queues (hard rule 4)"
"$DEMO_DIR/scripts/broker.sh" orphans || { echo "   WARNING: A14 expects none"; }
if [ "$PREFLIGHT" = 1 ]; then
  step "preflight: login/notify check (gpos/v1/sam/done/p4 within 15 s)"
  if ui_ctl probe notify; then
    echo "   notify probe: PASS"
  else
    echo "   notify probe: FAIL -- log in once to the SAM WebUI as marktleitung"
    RC=1
  fi
fi
ELAPSED=$((SECONDS - START))
echo "== reset done in ${ELAPSED} s (target < 15 s)$([ "$RC" -ne 0 ] && echo ', WITH ERRORS')"
exit "$RC"
