#!/bin/bash
# Generate an RSA-2048 keypair for OpenMetadata's JWT signing and place
# it into a Kubernetes Secret. Re-running on an existing secret leaves
# the keys untouched (idempotent), so this is safe to call from start.sh.
#
# OM stores ingestion-bot JWTs signed with this key. If the key is
# regenerated, every previously-issued bot token becomes invalid -- be
# deliberate about rotation.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

OM_NAMESPACE="${OM_NAMESPACE:-openmetadata-solace-lab}"
SECRET_NAME="openmetadata-jwt-keys"

command -v kubectl >/dev/null 2>&1 || { echo "ERROR: kubectl not found."; exit 1; }
command -v openssl >/dev/null 2>&1 || { echo "ERROR: openssl not found."; exit 1; }

kubectl create namespace "$OM_NAMESPACE" 2>/dev/null || true

if kubectl get secret "$SECRET_NAME" -n "$OM_NAMESPACE" >/dev/null 2>&1; then
  echo "Secret $SECRET_NAME already exists in $OM_NAMESPACE -- leaving as is."
  exit 0
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "Generating RSA-2048 keypair ..."
openssl genrsa -out "$TMP/private_key.pem" 2048 >/dev/null 2>&1
openssl pkcs8 -topk8 -inform PEM -outform DER \
  -in "$TMP/private_key.pem" -out "$TMP/private_key.der" -nocrypt
openssl rsa -in "$TMP/private_key.pem" -pubout -outform DER \
  -out "$TMP/public_key.der" >/dev/null 2>&1

echo "Creating Secret $SECRET_NAME in namespace $OM_NAMESPACE ..."
kubectl create secret generic "$SECRET_NAME" \
  --namespace "$OM_NAMESPACE" \
  --from-file=private_key.der="$TMP/private_key.der" \
  --from-file=public_key.der="$TMP/public_key.der"

echo "Done."
