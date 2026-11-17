#!/bin/bash
# G0-13 Teil A: DDL aller Schemas auf dem Lab-Postgres (Host-Container
# "postgres") in einer Wegwerf-DB pruefen.
#
#   ./run_ddl.sh run       Wegwerf-DB anlegen, Original-RL-Dateien pruefen,
#                          00..40 zweimal, Seeds zweimal, 00..40 ein drittes
#                          Mal auf befuellter DB, Plausibilitaet
#   ./run_ddl.sh run-nonsuper  dasselbe als Admin ohne Superuser
#                          (gpos_g0_admin: CREATEROLE, CREATEDB; Naeherung
#                          an den Admin von PG Flexible)
#   ./run_ddl.sh cleanup   Wegwerf-DB und gpos_g0_*-Rollen entfernen
#   ./run_ddl.sh all       run + cleanup + run-nonsuper + cleanup
#
# Fasst nur die DB gpos_g0_scratch und Rollen mit Praefix gpos_g0_ an.
# psql laeuft im Container (docker exec, lokale Verbindung, kein Passwort).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SQL="$HERE/sql"
CHK="$HERE/checks"
RL="$HERE/../../loyalty-sql"
DB=gpos_g0_scratch
PREFIX=gpos_g0
PG=postgres
RUN_AS=postgres                      # run-nonsuper: ${PREFIX}_admin

psql_admin() { docker exec -i "$PG" psql -X -U postgres -v ON_ERROR_STOP=1 "$@"; }
psql_db() { docker exec -i "$PG" psql -X -U "$RUN_AS" -v ON_ERROR_STOP=1 -d "$DB" -v role_prefix="$PREFIX" "$@"; }
fp() { psql_db -q -f - < "$CHK/fingerprint.sql"; }

run_file() {   # run_file <file> <label>: zeigt Ergebnis, NOTICE- und ERROR-Zahl
  local f=$1 label=$2 out rc
  set +e
  out=$(psql_db -q -f - < "$f" 2>&1)
  rc=$?
  set -e
  printf '%-28s %-8s rc=%s notices=%s errors=%s\n' "$(basename "$f")" "$label" "$rc" \
    "$(grep -c 'NOTICE' <<<"$out" || true)" "$(grep -c 'ERROR' <<<"$out" || true)"
  if [ "$rc" -ne 0 ]; then
    grep -m3 -E 'ERROR|FATAL' <<<"$out" | sed 's/^/    /'
  fi
  return "$rc"
}

do_run() {
  echo "== Version"
  docker exec "$PG" postgres --version
  psql_admin -tAc "show server_version"
  psql_admin -tAc "select 'databases=' || string_agg(datname, ',' order by datname) from pg_database"

  if psql_admin -tAc "select 1 from pg_database where datname = '$DB'" | grep -q 1; then
    echo "ERROR: $DB existiert schon (alter Lauf?) - erst ./run_ddl.sh cleanup" >&2
    exit 1
  fi
  if [ -n "$(psql_admin -tAc "select string_agg(rolname, ',') from pg_roles where rolname like '${PREFIX}\_%'")" ]; then
    echo "ERROR: Rollen ${PREFIX}_* existieren schon - erst ./run_ddl.sh cleanup" >&2
    exit 1
  fi
  echo "== Wegwerf-DB (angelegt von $RUN_AS)"
  if [ "$RUN_AS" != postgres ]; then
    psql_admin -q -c "create role $RUN_AS login createrole createdb"
    psql_admin -tAc "select rolname, rolsuper, rolcreaterole, rolcreatedb from pg_roles where rolname = '$RUN_AS'"
  fi
  docker exec -i "$PG" psql -X -U "$RUN_AS" -d postgres -v ON_ERROR_STOP=1 -q -c "create database $DB"
  psql_admin -tAc "select datname, pg_encoding_to_char(encoding), datcollate from pg_database where datname = '$DB'"

  echo "== Phase 0: Original-RL-Dateien (spikes/loyalty-sql) als Admin, je zweimal"
  for i in 1 2; do
    run_file "$RL/10-loyalty-schema.sql" "orig#$i" || true
  done
  for i in 1 2; do
    run_file "$RL/20-loyalty-seed.sql" "orig#$i" || true
  done
  psql_db -q -c "drop schema loyalty cascade" 2>/dev/null
  echo "   (Schema loyalty des Originals wieder entfernt)"

  echo "== Phase 1: DDL 00..40, zweimal"
  fp0=$(fp); echo "   leer:    $fp0"
  for i in 1 2; do
    for f in "$SQL"/00-roles.sql "$SQL"/10-pos.sql "$SQL"/20-engine.sql \
             "$SQL"/30-loyalty.sql "$SQL"/40-media.sql; do
      run_file "$f" "ddl#$i"
    done
    eval "fp_ddl$i=\$(fp)"; eval "echo \"   nach #$i: \$fp_ddl$i\""
  done
  [ "${fp_ddl1%% data=*}" = "${fp_ddl2%% data=*}" ] && echo "   DDL-Fingerabdruck #1 = #2: idempotent" \
    || { echo "   DDL-Fingerabdruck #1 != #2"; exit 1; }

  echo "== Phase 2: Seeds 90, 91, zweimal"
  for i in 1 2; do
    run_file "$SQL/90-seed.sql" "seed#$i"
    run_file "$SQL/91-loyalty-seed.sql" "seed#$i"
    eval "fp_seed$i=\$(fp)"; eval "echo \"   nach #$i: \$fp_seed$i\""
  done
  [ "$fp_seed1" = "$fp_seed2" ] && echo "   Fingerabdruck (DDL+Daten) Seed #1 = #2: idempotent" \
    || { echo "   Seed #1 != #2"; exit 1; }

  echo "== Phase 3: DDL 00..40 ein drittes Mal auf befuellter DB"
  for f in "$SQL"/00-roles.sql "$SQL"/10-pos.sql "$SQL"/20-engine.sql \
           "$SQL"/30-loyalty.sql "$SQL"/40-media.sql; do
    run_file "$f" "ddl#3"
  done
  fp3=$(fp); echo "   nach #3: $fp3"
  [ "$fp3" = "$fp_seed2" ] && echo "   unveraendert (DDL und Daten)" || { echo "   veraendert"; exit 1; }

  echo "== Phase 4: Plausibilitaet"
  psql_db -f - < "$CHK/95-sanity.sql" 2>&1 | sed -e 's/^psql:<stdin>:[0-9]*: //'
  fp4=$(fp)
  [ "$fp4" = "$fp_seed2" ] && echo "   DB nach den Pruefungen unveraendert" || { echo "   DB veraendert"; exit 1; }
}

do_cleanup() {
  echo "== Aufraeumen"
  psql_admin -q -c "drop database if exists $DB"
  local roles
  roles=$(psql_admin -tAc "select string_agg(quote_ident(rolname), ', ') from pg_roles where rolname in ('${PREFIX}_pos','${PREFIX}_engine','${PREFIX}_loyalty','${PREFIX}_ui','${PREFIX}_admin')")
  if [ -n "$roles" ]; then
    psql_admin -q -c "drop role $roles"
  fi
  psql_admin -tAc "select 'db_left=' || count(*) from pg_database where datname = '$DB'"
  psql_admin -tAc "select 'roles_left=' || count(*) from pg_roles where rolname like '${PREFIX}\_%'"
  psql_admin -tAc "select 'databases=' || string_agg(datname, ',' order by datname) from pg_database"
}

case "${1:-}" in
  run) do_run ;;
  run-nonsuper) RUN_AS=${PREFIX}_admin; do_run ;;
  cleanup) do_cleanup ;;
  all) do_run; do_cleanup; RUN_AS=${PREFIX}_admin; do_run; do_cleanup ;;
  *) echo "usage: $0 run|run-nonsuper|cleanup|all" >&2; exit 2 ;;
esac
