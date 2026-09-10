#!/bin/bash
set -euo pipefail

# =============================================================
# seed.sh -- create + seed the Acme Insurance postgres DB
# (acme_insurance) in the host `postgres` container. Idempotent:
# the database is created if absent, the SQL file drops +
# recreates its six tables on every run and prints the storyline
# counts as NOTICEs (10,400 claims, 412 stalled, 640 at
# P-BRAENDLE, 3,900 payment items ...).
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PGUSER="${INS_DB_USERNAME:-postgres}"

if [ "$(docker inspect -f '{{.State.Running}}' postgres 2>/dev/null)" != "true" ]; then
  echo "ERROR: host container 'postgres' is not running" >&2
  echo "  docker start postgres" >&2
  exit 1
fi

# db:sqlfile pairs (macOS bash 3.2: no associative arrays)
for pair in \
    "acme_insurance:01-acme_insurance.sql"; do
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

echo "Insurance database ready."
