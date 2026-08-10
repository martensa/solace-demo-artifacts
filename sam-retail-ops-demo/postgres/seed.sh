#!/bin/bash
set -euo pipefail

# =============================================================
# seed.sh -- create + seed the Acme Retail postgres DBs
# (retail_crm, retail_oms, retail_pdm) in the host `postgres`
# container. Idempotent: databases are created if absent, the
# SQL dumps drop + recreate their tables on every run
# (pg_dump --clean --if-exists format).
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PGUSER="${RETAIL_DB_USERNAME:-postgres}"

if [ "$(docker inspect -f '{{.State.Running}}' postgres 2>/dev/null)" != "true" ]; then
  echo "ERROR: host container 'postgres' is not running" >&2
  echo "  docker start postgres" >&2
  exit 1
fi

# db:sqlfile pairs (macOS bash 3.2: no associative arrays)
for pair in \
    "retail_crm:01-retail_crm.sql" \
    "retail_oms:02-retail_oms.sql" \
    "retail_pdm:03-retail_pdm.sql"; do
  db="${pair%%:*}"; sql="${pair#*:}"
  if ! docker exec postgres psql -U "$PGUSER" -tAc \
      "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1; then
    docker exec postgres psql -U "$PGUSER" -q -c "CREATE DATABASE $db"
    echo "   $db: database created"
  fi
  # stdout to /dev/null: the pg_dump preamble's set_config SELECT
  # prints a result row even under -q; errors still stop the run.
  docker exec -i postgres psql -U "$PGUSER" -d "$db" -q \
    -v ON_ERROR_STOP=1 < "$SCRIPT_DIR/sql/$sql" >/dev/null
  echo "   $db: seeded ($sql)"
done

echo "Retail databases ready."
