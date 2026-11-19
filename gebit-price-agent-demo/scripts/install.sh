#!/bin/bash
# install.sh -- idempotent install of the gpos demo (spec 9.8, 12.6).
#   scripts/install.sh pg     TARGET=aks only (lab: no-op): namespace gpos-data,
#                             Secret gpos-postgres-admin (random, only if absent),
#                             k8s/postgres-aks, rollout, pg_isready
#   scripts/install.sh db     DB gpos (lab: host container; aks: gpos-postgres-0
#                             via kubectl exec): roles, schemas, passwords
#                             (stdin), seed, 95-checks
#   scripts/install.sh k8s    namespace gpos-demo: Secrets from .env / .env.aks,
#                             kubectl apply of k8s/overlays/$TARGET
#                             (scripts/k8s_render.py), rollout restart; lab:
#                             Kyverno pull secret, Certificate, lab CA export;
#                             aks: Secret acr-pull, image $GPOS_IMAGE:$GPOS_VERSION,
#                             gpos-broker from the Key Vault through pipes only
#   scripts/install.sh mesh [--switch-r1] [--fallback-f2] [--no-booth]
#                             SAM: RBAC, connectors/agents/workflows, hygiene,
#                             probe entrypoint, probes, gate verification (approve
#                             x3, A9 deny x5, A10 timeout x2 on probe till 98), R1
#                             queue, booth entrypoint, booth probes; --no-booth
#                             stops after the gate verification (spec 9.8 step 7)
#   scripts/install.sh all    lab: db, k8s, mesh; aks: pg, db, k8s, mesh
# TARGET=lab|aks selects the installation (scripts/lib.sh; default lab).
# Refuses to start when scripts/check_hygiene.sh fails. Never `--prune`, never a
# restart of gwe/awe/str, nothing outside gpos-* / gpos-demo / gpos-data / DB gpos.
# Written for /bin/bash 3.2 (macOS): no empty-array expansions under set -u.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

PART="${1:-all}"
[ $# -gt 0 ] && shift
SWITCH_FLAG=""   # --switch-r1: allow an R1_MODE change (hard rule 4)
F2_FLAG=""       # --fallback-f2: also apply mesh/fallback (spec 9.9)
NO_BOOTH=""      # --no-booth: stop after the gate verification (spec 9.8 step 7)
for arg in "$@"; do
  case "$arg" in
    --switch-r1) SWITCH_FLAG=--switch-r1 ;;
    --fallback-f2) F2_FLAG=--fallback-f2 ;;
    --no-booth) NO_BOOTH=1 ;;
    *) die "unknown option $arg" ;;
  esac
done
ROLES="pos wws loyalty engine"
SQL_DIR="$DEMO_DIR/postgres/sql"
SEED_DIR="$DEMO_DIR/postgres/.generated"
DB_ENV="$RENDERED/db.env"
WORK=""
trap '[ -n "$WORK" ] && rm -rf "$WORK"' EXIT

upper() { printf '%s' "$1" | tr '[:lower:]' '[:upper:]'; }

apply_namespace() {  # apply_namespace KUSTOMIZE_DIR NAME -- that render's Namespace first
  local doc
  doc="$(kubectl kustomize "$1" | "$PY" -c '
import sys, yaml
docs = [d for d in yaml.safe_load_all(sys.stdin) if d and d.get("kind") == "Namespace"
        and (d.get("metadata") or {}).get("name") == sys.argv[1]]
if docs:
    yaml.safe_dump(docs[0], sys.stdout, sort_keys=False)' "$2")" \
    || die "kustomize render of $1 failed"
  [ -n "$doc" ] || die "no Namespace $2 in the render of $1"
  printf '%s\n' "$doc" | kubectl apply -f - >/dev/null
}

# ------------------------------------------------------------------------ pg

install_pg() {  # aks only: the demo DB's Postgres 18 in namespace gpos-data
  if [ "$TARGET" != aks ]; then
    echo "   TARGET=$TARGET: nothing to do (the demo DB runs in the host container $PG_CONTAINER)"
    return 0
  fi
  local dir="$DEMO_DIR/k8s/postgres-aks" existing
  step "Postgres on AKS ($PG_NS/$PG_POD)"
  [ -f "$dir/kustomization.yaml" ] || die "missing $dir/kustomization.yaml"
  apply_namespace "$dir" "$PG_NS"
  # the superuser password exists only in this Secret: generated once, never shown or
  # stored elsewhere; psql always runs as postgres over the local socket (kubectl exec)
  existing="$(kubectl -n "$PG_NS" get secret gpos-postgres-admin --ignore-not-found -o name)" \
    || die "cannot read secrets in $PG_NS"
  if [ -z "$existing" ]; then
    # jq emits the whole Secret only for a 48-hex-digit password: a failed openssl gives
    # kubectl apply no object (it fails), never a kept Secret with an empty password
    openssl rand -hex 24 \
      | jq -Rsc --arg ns "$PG_NS" 'rtrimstr("\n") as $p
          | if ($p | test("^[0-9a-f]{48}$")) then
              {apiVersion: "v1", kind: "Secret", type: "Opaque",
               metadata: {name: "gpos-postgres-admin", namespace: $ns},
               data: {password: ($p | @base64)}}
            else error("openssl rand -hex 24 gave no password") end' \
      | kubectl apply --server-side --field-manager=gpos-install -f - >/dev/null
    echo "   secret gpos-postgres-admin created (random, only in the cluster)"
  else
    echo "   secret gpos-postgres-admin present (kept)"
  fi
  kubectl apply -k "$dir"
  kubectl -n "$PG_NS" rollout status sts/gpos-postgres --timeout=300s
  for _ in $(seq 1 30); do pg_ready && break; sleep 2; done
  pg_ready || die "pg_isready: $PG_NS/$PG_POD does not accept connections"
  echo "   pg_isready: $PG_NS/$PG_POD accepts connections"
}

# ------------------------------------------------------------------------ db

ensure_db_passwords() {  # one 24-char password per role, kept in db.env (chmod 600)
  mkdir -p "$RENDERED" && chmod 700 "$RENDERED"
  (umask 077 && touch "$DB_ENV") && chmod 600 "$DB_ENV"
  local r key
  for r in $ROLES; do
    key="PG_PASSWORD_$(upper "$r")"
    grep -q "^$key=" "$DB_ENV" || printf '%s=%s\n' "$key" "$(openssl rand -hex 12)" >> "$DB_ENV"
  done
}

db_password() {  # db_password ROLE -> password from db.env (only ever piped)
  sed -n "s/^PG_PASSWORD_$(upper "$1")=//p" "$DB_ENV"
}

run_sql() {  # run_sql FILE -- as the container superuser, role_prefix gpos
  [ -f "$1" ] || die "missing $1"
  printf '   %s\n' "$(basename "$1")"
  psql_admin -q -d "$PG_DB" -v role_prefix=gpos -f - < "$1" >/dev/null
}

install_db() {
  if [ "${PG_MODE:-docker}" = kubectl ]; then
    step "Postgres ($PG_NS/$PG_POD, DB $PG_DB)"
    pg_ready || die "$PG_NS/$PG_POD is not ready (TARGET=aks scripts/install.sh pg)"
  else
    step "Postgres ($PG_CONTAINER, DB $PG_DB)"
    docker inspect -f '{{.State.Running}}' "$PG_CONTAINER" 2>/dev/null | grep -q true \
      || die "container $PG_CONTAINER is not running"
  fi
  if ! psql_admin -d postgres -tAc "select 1 from pg_database where datname = '$PG_DB'" \
      | grep -q 1; then
    psql_admin -q -d postgres -c "create database $PG_DB"
    echo "   database $PG_DB created"
  fi
  local f r
  for f in 00-roles 10-pos 20-wws 30-loyalty 31-loyalty-uc1 40-engine; do
    run_sql "$SQL_DIR/$f.sql"
  done
  ensure_db_passwords
  for r in $ROLES; do  # via stdin, never as an argument or in a SQL file
    printf "alter role gpos_%s password '%s';\n" "$r" "$(db_password "$r")" \
      | psql_admin -q -d "$PG_DB" -f - >/dev/null
  done
  echo "   passwords of gpos_pos, gpos_wws, gpos_loyalty, gpos_engine set (db.env, chmod 600)"
  "$PY" "$DEMO_DIR/postgres/gen_seed.py" --demo-date "${GPOS_DEMO_DATE:-2027-02-16}" \
    --out "$SEED_DIR"
  for f in 90-seed-wws 91-seed-loyalty 92-seed-pos; do run_sql "$SEED_DIR/$f.sql"; done
  run_sql "$SQL_DIR/95-checks.sql"
}

# ----------------------------------------------------------------------- k8s

apply_secret() {  # apply_secret NAME ARGS... -- server-side apply, no last-applied copy
  local name="$1"; shift
  kubectl -n "$NS" create secret generic "$name" "$@" --dry-run=client -o yaml \
    | kubectl apply --server-side --force-conflicts --field-manager=gpos-install -f - >/dev/null
  echo "   secret $name applied"
}

db_exists_or_die() {  # aks: DB and roles exist, else an old db.env meets an empty Postgres
  local found
  pg_ready || die "$PG_NS/$PG_POD is not ready (TARGET=aks scripts/install.sh pg)"
  found="$(psql_admin -d postgres -tAc "select (select count(*) from pg_database
    where datname = '$PG_DB') || '/' || (select count(*) from pg_roles where rolname in
    ('gpos_pos', 'gpos_wws', 'gpos_loyalty', 'gpos_engine'))")" \
    || die "cannot query $PG_NS/$PG_POD"
  [ "$found" = 1/4 ] \
    || die "DB $PG_DB or roles gpos_* missing in $PG_NS/$PG_POD: run TARGET=aks scripts/install.sh db"
}

aks_image_or_die() {  # aks: the demo image comes from the ACR named in .env.aks
  case "${GPOS_IMAGE:-}" in
    "${AKS_ACR:-}".azurecr.io/*) [ -n "${AKS_ACR:-}" ] && [ -n "${GPOS_VERSION:-}" ] && return 0 ;;
  esac
  die "GPOS_IMAGE/GPOS_VERSION in .env.aks must name the ACR image (AKS_ACR set?)"
}

configmap_overrides() {  # .env keys that also live in gpos-config win over the configmap
  local patch
  patch=$("$PY" - <<'PY'
import json, os
keys = ("GPOS_DEMO_DATE", "GPOS_BOOTH_LOCATION", "GPOS_TEST_LOCATION", "GPOS_PROBE_LOCATION",
        "GPOS_DELIVERY", "GATE_MIN_DELAY_S", "GATE_GUARD", "SAM_URL")
data = {k: os.environ[k] for k in keys if os.environ.get(k)}
print(json.dumps({"data": data}) if data else "")
PY
)
  [ -z "$patch" ] && return 0
  kubectl -n "$NS" patch configmap gpos-config --type merge -p "$patch" >/dev/null
  echo "   gpos-config from $ENV_NAME: $(printf '%s' "$patch" | "$PY" -c 'import json, sys
print(", ".join(f"{k}={v}" for k, v in json.load(sys.stdin)["data"].items()))')"
}

install_k8s() {
  step "Kubernetes ($NS)"
  [ -f "$DB_ENV" ] || die "$DB_ENV missing: run scripts/install.sh db first"
  local overlay="$DEMO_DIR/k8s/overlays/$TARGET"
  [ -f "$overlay/kustomization.yaml" ] || die "missing $overlay/kustomization.yaml"
  local desc="${GEBIT_DESCRIPTOR_DIR:-$HOME/Downloads/Gebit}"
  local purchase="$desc/purchase-api-2.50.0.pb" receipt="$desc/receipt-api-2.13.0.pb"
  local f r d
  local image_args=()
  for f in "$purchase" "$receipt"; do [ -r "$f" ] || die "missing descriptor set $f"; done
  if [ "$TARGET" = aks ]; then
    aks_image_or_die
    image_args=(--image "$GPOS_IMAGE:$GPOS_VERSION")
    db_exists_or_die
  fi

  apply_namespace "$overlay" "$NS"
  if [ "$TARGET" = aks ]; then  # no Kyverno on AKS: the pull secret comes from the Key Vault
    apply_acr_pull "$NS" || die "secret acr-pull failed (Key Vault secret acr-pull-token)"
    echo "   secret acr-pull applied (ACR token from the Key Vault)"
  else
    for _ in $(seq 1 30); do  # Kyverno clones the pull secret into the namespace
      kubectl -n "$NS" get secret registry-pull-secret >/dev/null 2>&1 && break
      sleep 2
    done
    kubectl -n "$NS" get secret registry-pull-secret >/dev/null 2>&1 \
      || echo "   WARNING: registry-pull-secret not (yet) cloned by Kyverno"
  fi

  WORK="$(mktemp -d "${TMPDIR:-/tmp}/gpos-k8s.XXXXXX")" && chmod 700 "$WORK"
  if [ "$TARGET" = aks ]; then  # the Key Vault password goes through pipes only, no file
    apply_broker_secret "$NS" \
      || die "secret gpos-broker failed (Key Vault secret ${BROKER_PASSWORD_KV:-?})"
    echo "   secret gpos-broker applied"
  else
    "$PY" "$DEMO_DIR/scripts/render_mesh.py" --write-broker-env "$WORK/broker.env"
    apply_secret gpos-broker --from-env-file="$WORK/broker.env"
  fi
  (umask 077 && : > "$WORK/db.env")
  for r in $ROLES; do
    printf 'DSN_%s=postgresql://gpos_%s:%s@%s:%s/%s\n' "$(upper "$r")" "$r" \
      "$(db_password "$r")" "${PG_HOST_FROM_PODS:-host.docker.internal}" \
      "${PG_PORT:-5432}" "$PG_DB" >> "$WORK/db.env"
  done
  apply_secret gpos-db --from-env-file="$WORK/db.env"
  apply_secret gpos-gebit-descriptors \
    --from-file=purchase-api-2.50.0.pb="$purchase" --from-file=receipt-api-2.13.0.pb="$receipt"
  rm -f "$WORK/broker.env" "$WORK/db.env"

  # = kubectl apply -k k8s/overlays/$TARGET, minus an Ingress whose host another namespace
  # already serves (the ingress-nginx webhook would refuse it; other namespaces stay
  # untouched); aks: the ACR image of .env.aks in every demo Deployment
  kubectl get ingress -A -o json > "$WORK/ingresses.json"
  kubectl kustomize "$overlay" \
    | "$PY" "$DEMO_DIR/scripts/k8s_render.py" --namespace "$NS" \
        --cluster-ingresses "$WORK/ingresses.json" ${image_args[@]+"${image_args[@]}"} \
    | kubectl apply -f -
  configmap_overrides
  # imagePullPolicy Always: a restart also pulls an image re-pushed under the same tag
  kubectl -n "$NS" rollout restart deploy >/dev/null
  for d in $DEPLOYMENTS; do
    kubectl -n "$NS" rollout status "deploy/$d" --timeout=180s
  done
  if [ "$TARGET" = aks ]; then  # TLS: the Traefik default certificate, no lab CA
    echo "   TLS: Traefik default certificate (no Certificate in $NS), E2E_CA_FILE=$E2E_CA_FILE"
    return 0
  fi
  kubectl -n "$NS" wait certificate/gpos-demo --for=condition=Ready --timeout=120s >/dev/null \
    || echo "   WARNING: certificate gpos-demo not Ready yet"
  mkdir -p "$BUILD_DIR"
  kubectl -n cert-manager get secret root-ca-secret -o jsonpath='{.data.tls\.crt}' \
    | base64 -d > "$BUILD_DIR/lab-ca.crt"
  echo "   lab root CA (public certificate) -> build/lab-ca.crt"
}

# ---------------------------------------------------------------------- mesh

broker() { "$DEMO_DIR/scripts/broker.sh" "$@"; }

probe() {  # probe NAME -- gposdemo.ui.ctl probe in the pod (SMF Direct, done/<rule> in 15 s)
  if ui_ctl probe "$1"; then echo "   probe $1: PASS"; else die "probe $1 failed"; fi
}

gate_verify_if_needed() {  # 9.8 step 7: stop before the booth unless the gate is verified
  # PASS = approve x3, A9 deny x5 and A10 timeout x2 on probe till 98 for the current
  # hash of mesh/connectors, mesh/agents and mesh/workflows (e2e.py --gate-status)
  # shellcheck disable=SC2086 # F2_FLAG is empty or one word
  if "$PY" "$DEMO_DIR/scripts/e2e.py" --gate-status $F2_FLAG; then
    echo "   ${BUILD_DIR#"$DEMO_DIR"/}/gate-verified: PASS (approve x3, deny x5, timeout x2)" \
      "for the current mesh/connectors, mesh/agents and mesh/workflows"
    return 0
  fi
  step "gate verification on probe till 98, incl. A9 and A10 (make gate-verify, ~11 min)"
  # shellcheck disable=SC2086
  "$PY" "$DEMO_DIR/scripts/e2e.py" --gate-verify $F2_FLAG \
    || die "gate verification failed: the booth entrypoint is NOT applied (spec 9.9)"
}

install_mesh() {
  local mode prev p
  mode="${R1_MODE:-own}"
  prev="$(cat "$RENDERED/r1_mode" 2>/dev/null || true)"
  if [ -n "$F2_FLAG" ] && [ "${GATE_GUARD:-block}" != f2 ]; then
    die "--fallback-f2 needs GATE_GUARD=f2 in $ENV_NAME and scripts/install.sh k8s (spec 9.9)"
  fi
  step "preflight: connector manifests against the running services (spec 8.5)"
  "$PY" "$DEMO_DIR/scripts/check_manifests.py" \
    || die "connector manifests do not match the running services (make manifests)"
  sam_login

  step "4.1 RBAC (always; apply replaces the role, the users grant stays in the file)"
  sam_apply "$DEMO_DIR/mesh" manifest-rbac.yaml
  step "4.2 connectors, agents, workflows"
  sam_apply "$DEMO_DIR/mesh" manifest.yaml
  if [ -n "$F2_FLAG" ]; then
    step "4.2 fallback F2 (gpos-price-apply, gpos-price-approver-f2, F2 workflow)"
    sam_apply "$DEMO_DIR/mesh/fallback" manifest.yaml
  fi
  step "4.3 platform hygiene"
  "$DEMO_DIR/scripts/check_hygiene.sh" --platform || die "platform hygiene failed"

  step "4.4 probe entrypoint gpos-probe-events"
  # shellcheck disable=SC2086
  "$PY" "$DEMO_DIR/scripts/render_mesh.py" $SWITCH_FLAG
  sam_apply "$RENDERED" manifest-probe.yaml
  step "4.5 readiness (platform API + SEMP txFlows, up to 60 s)"
  broker ready gpos-probe-events || die "gpos-probe-events not ready"
  step "4.6 probes on probe till 98"
  for p in p1 p3 p4 notify; do probe "$p"; done
  step "4.7 gate verification"
  gate_verify_if_needed
  if [ -n "$NO_BOOTH" ]; then
    echo "   --no-booth: booth entrypoint NOT applied; scripts/install.sh mesh applies it"
    return 0
  fi

  step "4.8 R1 queue (R1_MODE=$mode)"
  if [ "$mode" = own ]; then broker r1-create; else echo "   R1 on the SAM queue"; fi
  step "4.9 booth entrypoint gpos-booth-events"
  sam_apply "$RENDERED" manifest-booth.yaml
  broker ready gpos-booth-events || die "gpos-booth-events not ready"
  if [ -n "$prev" ] && [ "$prev" != "$mode" ]; then
    step "R1_MODE switch $prev -> $mode (hard rule 4)"
    broker r1-switch "$prev" "$mode"
  fi
  "$PY" "$DEMO_DIR/scripts/render_mesh.py" --mark-applied
  broker orphans || echo "   WARNING: orphaned queues (see above, hard rule 4)"
  step "4.10 probes on the booth till"
  for p in r1 r3 r4; do probe "$p"; done
}

hygiene_or_die
case "$PART" in
  pg) install_pg ;;
  db) install_db ;;
  k8s) install_k8s ;;
  mesh) install_mesh ;;
  all)
    if [ "$TARGET" = aks ]; then
      install_pg; install_db; install_k8s; install_mesh
    else
      install_db; install_k8s; install_mesh
    fi ;;
  *) die "usage: $0 pg|db|k8s|mesh|all [--switch-r1] [--fallback-f2] [--no-booth]" ;;
esac
step "done ($PART)"
