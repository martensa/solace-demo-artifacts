#!/bin/bash
# uninstall.sh [--drop-db] -- remove what the gpos demo created, nothing else
# (spec 12.6): SAM entrypoints -> workflows -> agents -> connectors (REST DELETE,
# BSG delete_named, never `sam config apply --prune`), the own R1 queue, the
# namespace gpos-demo, the rendered files. The database gpos and its roles only
# with --drop-db. Left in place on purpose: role gpos_marktleitung and claim
# mapping keycloak-group-marktleitung (shared with Gate 0, spec 9.7).
# TARGET=aks (scripts/lib.sh): the same against AKS; namespace gpos-data (the
# demo DB's Postgres and its volume) stays unless --drop-db, which drops the DB
# and roles via kubectl exec first and then deletes gpos-data.
set -uo pipefail
. "$(dirname "$0")/lib.sh"

DROP_DB=0
case "${1:-}" in
  --drop-db) DROP_DB=1 ;;
  "") ;;
  *) die "usage: $0 [--drop-db]" ;;
esac

gpos_ns_or_die() {  # only the demo's own gpos-* namespaces are ever deleted (spec 12.6)
  case "$1" in
    gpos-*) ;;
    *) die "refusing to delete namespace '$1': uninstall removes only gpos-* namespaces" ;;
  esac
}
# checked before anything is deleted
gpos_ns_or_die "$NS"
if [ "$TARGET" = aks ] && [ "$DROP_DB" = 1 ]; then gpos_ns_or_die "$PG_NS"; fi

step "SAM resources"
if sam_login; then
  for e in gpos-booth-events gpos-probe-events; do
    delete_named entrypoint /api/v1/platform/entrypoints "$e"
  done
  for w in gpos-pos-event gpos-basket-review gpos-price-approval; do
    delete_named workflow /api/v1/platform/workflows "$w"
  done
  for a in gpos-pricing-agent gpos-price-planner gpos-price-approver \
           gpos-price-approver-f2; do
    delete_named agent /api/v1/platform/agents "$a"
  done
  for c in gpos-booth-tools gpos-price-gate gpos-wws-api gpos-loyalty-api gpos-pos-api \
           gpos-price-apply; do
    delete_named connector /api/v1/platform/connectors "$c"
  done
else
  echo "   WARNING: no sam login -- SAM resources left in place"
fi

if [ "$TARGET" = aks ]; then BROKER_LABEL="AKS broker"; else BROKER_LABEL=solace-1; fi
step "broker ($BROKER_LABEL, VPN ${BROKER_VPN:-default})"
"$DEMO_DIR/scripts/broker.sh" r1-delete || echo "   WARNING: r1-delete failed"
"$DEMO_DIR/scripts/broker.sh" orphans || echo "   WARNING: orphaned queues left (hard rule 4)"

step "namespace $NS"
kubectl delete ns "$NS" --ignore-not-found --wait=true

if [ "$DROP_DB" = 1 ]; then
  step "database $PG_DB and roles gpos_*"
  psql_admin -q -d postgres -c "drop database if exists $PG_DB with (force)"
  for r in pos wws loyalty engine; do
    psql_admin -q -d postgres -c "drop role if exists gpos_$r"
  done
  rm -f "$RENDERED/db.env"
  if [ "$TARGET" = aks ]; then
    step "namespace $PG_NS (Postgres of the demo DB, incl. its volume)"
    kubectl delete ns "$PG_NS" --ignore-not-found --wait=true
  fi
elif [ "$TARGET" = aks ]; then
  echo "   namespace $PG_NS and DB $PG_DB kept (scripts/uninstall.sh --drop-db removes them)"
fi
rm -rf "$RENDERED/entrypoints" "$RENDERED/manifest-booth.yaml" \
       "$RENDERED/manifest-probe.yaml" "$RENDERED/r1_mode" "$BUILD_DIR/gate-verified"
step "uninstalled"
