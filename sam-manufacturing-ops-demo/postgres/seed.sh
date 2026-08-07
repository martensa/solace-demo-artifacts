#!/bin/bash
set -euo pipefail

# =============================================================
# seed.sh -- create + seed the Acme Manufacturing postgres DBs
# (mfg_crm, mfg_oms, mfg_pdm, mfg_scm) in the host `postgres`
# container. Idempotent: databases are created if absent, the
# SQL files drop + recreate their tables on every run.
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PGUSER="${MFG_DB_USERNAME:-postgres}"

if [ "$(docker inspect -f '{{.State.Running}}' postgres 2>/dev/null)" != "true" ]; then
  echo "ERROR: host container 'postgres' is not running" >&2
  echo "  docker start postgres" >&2
  exit 1
fi

# db:sqlfile pairs (macOS bash 3.2: no associative arrays)
for pair in \
    "mfg_crm:01-mfg_crm.sql" \
    "mfg_oms:02-mfg_oms.sql" \
    "mfg_pdm:03-mfg_pdm.sql" \
    "mfg_scm:04-mfg_scm.sql"; do
  db="${pair%%:*}"; sql="${pair#*:}"
  if ! docker exec postgres psql -U "$PGUSER" -tAc \
      "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1; then
    docker exec postgres psql -U "$PGUSER" -q -c "CREATE DATABASE $db"
    echo "   $db: database created"
  fi
  docker exec -i postgres psql -U "$PGUSER" -d "$db" -q \
    < "$SCRIPT_DIR/sql/$sql"
  echo "   $db: seeded ($sql)"
done

echo "Manufacturing databases ready."
