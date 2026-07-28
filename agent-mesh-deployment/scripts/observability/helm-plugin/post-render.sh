#!/usr/bin/env bash
set -euo pipefail

# =============================================================
# post-render.sh -- Helm 4 postrenderer/v1 plugin entrypoint.
# =============================================================
# stdin:  the fully rendered release (manifests incl. hooks)
# stdout: the same stream with the SAM observability overlay
#         applied (kustomize: configMapGenerator + SMP patches)
#
# The final per-component config files are built here from the
# pristine image-baked copies (configs/*.base, drift-checked by
# start.sh) plus the appended management_server block.
# =============================================================

plugin_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
kustomize_dir="$plugin_dir/../kustomize"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# Normalize the helm output: the persistence-layer subchart emits
# duplicate label keys (app.kubernetes.io/service twice), which
# kubectl/helm tolerate (last wins) but kustomize's strict YAML
# parser rejects. PyYAML applies the same last-wins semantics and
# re-emits clean documents.
python3 -c "
import sys, yaml
docs = [d for d in yaml.safe_load_all(sys.stdin) if d is not None]
yaml.safe_dump_all(docs, sys.stdout, sort_keys=False, width=10000)
" > "$tmp/all.yaml"

cp "$kustomize_dir/kustomization.yaml" \
   "$kustomize_dir/patch-gwe.yaml" \
   "$kustomize_dir/patch-awe.yaml" \
   "$kustomize_dir/patch-str.yaml" "$tmp/"

snippet="$kustomize_dir/configs/management_server.yaml"
cat "$kustomize_dir/configs/gwe.yaml.base"     "$snippet" > "$tmp/gwe.yaml"
cat "$kustomize_dir/configs/awe-sam.yaml.base" "$snippet" > "$tmp/sam.yaml"
cat "$kustomize_dir/configs/str.yaml.base"     "$snippet" > "$tmp/str.yaml"

out="$(kubectl kustomize "$tmp")"

# Sanity: the overlay must have landed in all three deployments;
# a vendor rename of deployment/container names must fail loudly.
count="$(grep -c "subPath: " <<<"$out" || true)"
if ! grep -q "name: sam-observability" <<<"$out" || [ "$count" -lt 3 ]; then
  echo "post-render: observability overlay did not apply" \
       "(vendor rename? subPath count=$count)" >&2
  exit 1
fi

printf '%s\n' "$out"
