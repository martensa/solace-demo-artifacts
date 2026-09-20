#!/bin/bash
set -euo pipefail

# =============================================================
# grant-grafana-platform-db.sh -- let Grafana read the SAM
# PLATFORM DB (idempotent; safe to re-run).
# =============================================================
# The lab's Grafana role grafana_ro (infra repo) may read the
# WebUI DB (datasource sam-platform-db) but has NO SELECT on the
# platform DB `sam-solace-lab_platform` (agents, RBAC, workflows,
# model aliases, eval runs) -- the governance dashboards need it.
#
# What it does (each step is idempotent):
#   1. GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_ro
#      + ALTER DEFAULT PRIVILEGES ... GRANT SELECT ON TABLES (so
#      tables created by future platform migrations are covered;
#      FOR ROLE <table owner> when the owner is not postgres)
#      -- runs inside the postgres pod via kubectl exec
#   2. kubectl apply the datasource ConfigMap
#      manifests/observability/grafana-datasource-sam-platform-config.yaml
#      (uid sam-platform-config-db; the sidecar reloads Grafana)
#   3. verify with has_table_privilege('grafana_ro','eval_runs','SELECT')
#
# stop.sh destroys the platform DB and with it this grant: re-run
# after a rebuild (the demo install scripts call it anyway).
#
#   ./grant-grafana-platform-db.sh
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AMD_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
NS="sam-solace-lab"
POD="agent-mesh-postgresql-0"
DB="sam-solace-lab_platform"
ROLE="grafana_ro"
ROLE_PASSWORD="grafana_ro"   # lab demo credential, matches the infra datasource
DS_FILE="$AMD_DIR/manifests/observability/grafana-datasource-sam-platform-config.yaml"

case "${1:-}" in
  -h|--help) grep '^#   \./' "$0" | sed 's/^#   //'; exit 0 ;;
  "") ;;
  *) echo "Unknown argument: $1" >&2; exit 1 ;;
esac

pg() {  # pg SQL -> psql -tA output, run as postgres inside the pod
  # The SQL travels on stdin: identifiers such as the table owner
  # "sam-solace-lab_platform" need double quotes, which would not
  # survive the nested bash -c quoting of a -c argument.
  kubectl exec -i -n "$NS" "$POD" -- bash -c \
    "PGPASSWORD=\$POSTGRES_PASSWORD psql -U postgres -d $DB -v ON_ERROR_STOP=1 -tAq" \
    <<<"$1"
}

if ! kubectl get pod -n "$NS" "$POD" >/dev/null 2>&1; then
  echo "ERROR: pod $NS/$POD not found -- is the agent mesh running?" >&2
  exit 1
fi

echo "== grafana_ro on $DB (pod $NS/$POD)"
if [ "$(pg "SELECT 1 FROM pg_roles WHERE rolname='$ROLE'")" != "1" ]; then
  # Normally created by the infra repo for the WebUI datasource;
  # create it here only when it is missing (fresh cluster).
  pg "CREATE ROLE $ROLE LOGIN PASSWORD '$ROLE_PASSWORD'" >/dev/null
  echo "   role $ROLE: created (was missing)"
else
  echo "   role $ROLE: present"
fi

BEFORE=$(pg "SELECT has_table_privilege('$ROLE','eval_runs','SELECT')")
OWNER=$(pg "SELECT tableowner FROM pg_tables WHERE schemaname='public' AND tablename='eval_runs'")
pg "GRANT USAGE ON SCHEMA public TO $ROLE" >/dev/null
pg "GRANT SELECT ON ALL TABLES IN SCHEMA public TO $ROLE" >/dev/null
echo "   GRANT SELECT ON ALL TABLES IN SCHEMA public TO $ROLE: done"
if [ -n "$OWNER" ] && [ "$OWNER" != "postgres" ]; then
  # The platform's tables are owned by the platform DB role (verified:
  # "sam-solace-lab_platform"); default privileges are per creator.
  pg "ALTER DEFAULT PRIVILEGES FOR ROLE \"$OWNER\" IN SCHEMA public GRANT SELECT ON TABLES TO $ROLE" >/dev/null
  echo "   ALTER DEFAULT PRIVILEGES FOR ROLE \"$OWNER\" ... GRANT SELECT ON TABLES: done"
else
  pg "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO $ROLE" >/dev/null
  echo "   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES: done"
fi

echo "== Datasource ConfigMap (ns monitoring, uid sam-platform-config-db)"
kubectl apply -f "$DS_FILE" | sed 's/^/   /'

echo "== Verify"
AFTER=$(pg "SELECT has_table_privilege('$ROLE','eval_runs','SELECT')")
if [ "$AFTER" = "t" ]; then
  if [ "$BEFORE" = "t" ]; then
    echo "   $ROLE SELECT on eval_runs: t (was already granted)"
  else
    echo "   $ROLE SELECT on eval_runs: t (newly granted)"
  fi
else
  echo "ERROR: has_table_privilege('$ROLE','eval_runs','SELECT') = '$AFTER'" >&2
  echo "(table missing? platform not migrated yet?)" >&2
  exit 1
fi
