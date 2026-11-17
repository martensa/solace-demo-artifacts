#!/usr/bin/env bash
# G0-07 checks over the lab ingress with real grpcurl and curl.
# gpos-grpc.solace.lab / gpos-g0-upload.solace.lab have no DNS entry on the
# Mac, so grpcurl dials 127.0.0.1:443 with -authority (sets :authority, SNI
# and the name verified against the lab CA); curl uses --resolve.
#
#   CA=/path/solace-lab-root-ca.crt ./test.sh [all|kyverno|grpc|body]
#
# Export the CA once (public cert only):
#   kubectl get secret -n cert-manager root-ca-secret \
#     -o jsonpath='{.data.tls\.crt}' | base64 -d > solace-lab-root-ca.crt
set -uo pipefail
cd "$(dirname "$0")"

NS=gpos-g0
CA="${CA:?set CA to the lab root CA PEM}"
ADDR="${INGRESS_ADDR:-127.0.0.1:443}"
HOST=gpos-grpc.solace.lab
UPHOST=gpos-g0-upload.solace.lab
SVC=de.gebit.rp.purchase.purchase.v2.service.PurchaseTransactionService
WORK="${WORK:-$(mktemp -d)}"
G=(grpcurl -cacert "$CA" -authority "$HOST")

step() { printf '\n### %s\n' "$*"; }
run() { printf '$ %s\n' "$*"; "$@"; printf '[rc=%s]\n' "$?"; }

kyverno() {
  step "Kyverno: server dry-run of the real ingress and two probes"
  run kubectl apply --dry-run=server -f k8s/30-ingress-grpc.yaml
  run kubectl apply --dry-run=server -f k8s/negative/ingress-no-ssl-redirect.yaml
  run kubectl apply --dry-run=server -f k8s/negative/ingress-no-tls.yaml
}

grpc_checks() {
  step "TLS handshake (SNI $HOST, verify against lab CA, ALPN h2)"
  openssl s_client -connect "$ADDR" -servername "$HOST" -alpn h2 \
    -CAfile "$CA" -verify_hostname "$HOST" </dev/null 2>/dev/null \
    | grep -E 'Verification|ALPN|Verify return code'

  step "list / describe"
  run "${G[@]}" "$ADDR" list
  "${G[@]}" "$ADDR" describe "$SVC" > "$WORK/describe.txt"
  printf 'describe %s: rc=%s, %s rpc lines\n' "$SVC" "$?" \
    "$(grep -c ' rpc ' "$WORK/describe.txt")"
  rm -f "$WORK/describe.txt"   # derived from vendor descriptors, do not keep
  run "${G[@]}" "$ADDR" describe grpc.health.v1.Health
  run "${G[@]}" "$ADDR" describe "$SVC.AddArticle"

  step "call CreatePurchaseTransaction + AddArticle"
  out=$("${G[@]}" -d '{"location":"Root.DE.999.101.01","employeeId":"ID199901",
    "header":{"traceId":"g0-07-create"}}' "$ADDR" "$SVC/CreatePurchaseTransaction")
  printf '%s\n[rc=%s]\n' "$out" "$?"
  TX=$(printf '%s' "$out" | python3 -c \
    'import json,sys; print(json.load(sys.stdin)["purchaseTransactionId"])')
  run "${G[@]}" -d "{\"purchaseTransactionId\":\"$TX\",\"articleId\":\"IDarticle004\",
    \"itemCount\":1,\"header\":{\"traceId\":\"g0-07-add\"}}" "$ADDR" "$SVC/AddArticle"
  run "${G[@]}" -d '{}' "$ADDR" "$SVC/GetPurchaseTransaction"

  step "health"
  run "${G[@]}" "$ADDR" grpc.health.v1.Health/Check
  run "${G[@]}" -d "{\"service\":\"$SVC\"}" "$ADDR" grpc.health.v1.Health/Check

  step "reflection v1alpha called explicitly"
  run "${G[@]}" -d '{"listServices":""}' "$ADDR" \
    grpc.reflection.v1alpha.ServerReflection/ServerReflectionInfo

  step "which reflection API answered (ingress access log)"
  sleep 2
  kubectl logs -n ingress-nginx deploy/ingress-nginx-controller --since=60s \
    | grep 'gpos-g0-gpos-g0-grpc' | awk '{print $6, $7, $9, $12, $13}' \
    | sort | uniq -c
}

wait_annotation() {  # $1 ingress, $2 expected value ("" = absent)
  for _ in $(seq 1 20); do
    v=$(kubectl get ingress -n "$NS" "$1" \
      -o jsonpath='{.metadata.annotations.nginx\.ingress\.kubernetes\.io/proxy-body-size}')
    [[ "$v" == "$2" ]] && break
    sleep 1
  done
  sleep 6   # controller sync + nginx reload
}

body_checks() {
  python3 - "$WORK" <<'PY'
import json, os, sys
w = sys.argv[1]
blob = os.urandom(2 * 1024 * 1024)
open(os.path.join(w, "upload-2mib.bin"), "wb").write(blob)
json.dump({"articleId": "IDarticle004", "itemCount": 1,
           "capturingInformation": {"inputValue": "x" * (2 * 1024 * 1024)}},
          open(os.path.join(w, "addarticle-2mib.json"), "w"))
PY
  printf 'upload sha256 %s\n' "$(shasum -a 256 "$WORK/upload-2mib.bin" | cut -c1-16)"
  TX=$("${G[@]}" -d '{"location":"Root.DE.999.101.01","employeeId":"ID199901"}' \
    "$ADDR" "$SVC/CreatePurchaseTransaction" | python3 -c \
    'import json,sys; print(json.load(sys.stdin)["purchaseTransactionId"])')
  python3 - "$WORK/addarticle-2mib.json" "$TX" <<'PY'
import json, sys
p, tx = sys.argv[1], sys.argv[2]
d = json.load(open(p)); d["purchaseTransactionId"] = tx; json.dump(d, open(p, "w"))
PY

  for phase in default 4m; do
    if [[ "$phase" == default ]]; then
      step "body size: annotation removed (controller default)"
      kubectl annotate -n "$NS" ingress gpos-g0-grpc gpos-g0-upload \
        nginx.ingress.kubernetes.io/proxy-body-size-
      wait_annotation gpos-g0-grpc ""
    else
      step "body size: proxy-body-size 4m (manifests)"
      kubectl apply -f k8s/30-ingress-grpc.yaml -f k8s/40-upload.yaml >/dev/null
      wait_annotation gpos-g0-grpc 4m
    fi
    printf -- '- gRPC AddArticle, 2 MiB request message:\n'
    "${G[@]}" -max-msg-sz 8388608 -d @ "$ADDR" "$SVC/AddArticle" \
      < "$WORK/addarticle-2mib.json" 2>&1 | head -4
    printf '[rc=%s]\n' "${PIPESTATUS[0]}"
    printf -- '- HTTP POST, 2 MiB body:\n'
    curl -sS --cacert "$CA" --resolve "$UPHOST:443:${ADDR%:*}" \
      -o "$WORK/upload-resp.txt" -w 'http=%{http_code} sent=%{size_upload}\n' \
      --data-binary @"$WORK/upload-2mib.bin" \
      -H 'Content-Type: application/octet-stream' "https://$UPHOST/upload"
    head -c 200 "$WORK/upload-resp.txt" | tr '\n' ' ' | sed 's/<[^>]*>//g'; echo
  done
  rm -f "$WORK/upload-2mib.bin" "$WORK/addarticle-2mib.json"
}

case "${1:-all}" in
  kyverno) kyverno ;;
  grpc) grpc_checks ;;
  body) body_checks ;;
  all) kyverno; grpc_checks; body_checks ;;
esac
