#!/bin/bash
# check_hygiene.sh -- hard rules 1 and 2 of the gpos demo (spec 12.6, 9.1).
#   scripts/check_hygiene.sh             repo: no GEBIT vendor files, no LLM key,
#                                        no key-bearing config, no ${...} in mesh/,
#                                        no LLM proxy host (also in the top-level *.md)
#   scripts/check_hygiene.sh --platform  additionally every gpos-* workflow, agent,
#                                        connector and entrypoint on the platform
#                                        (sam api, read-only) is free of key fields;
#                                        TARGET=aks: the AKS platform (the CLI with
#                                        HOME=$SAM_HOME and --url SAM_URL, .env.aks)
# Exit 0 = clean. Prints file names and line numbers only, never the hit itself.
# This file is the only one allowed to name the forbidden patterns.
set -uo pipefail
DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DEMO_DIR" || exit 2

FAIL=0
fail() { echo "HYGIENE FAIL: $*" >&2; FAIL=1; }

SCAN=()
for d in app data infra policy proto k8s mesh scripts; do [ -e "$d" ] && SCAN+=("$d"); done
for f in .env .env.*; do [ -f "$f" ] && SCAN+=("$f"); done
EXCLUDES=(--exclude-dir=.rendered --exclude-dir=__pycache__ --exclude-dir=.generated
          --exclude=check_hygiene.sh)

# 1. GEBIT vendor material never in the demo tree (hard rule 2)
vendor=$(find . \( -path ./.venv -o -path ./.git \) -prune -o -type f \
  \( -name 'purchase-api*' -o -name 'receipt-api*' -o -name 'simpleSale*' \) -print)
[ -n "$vendor" ] && fail "GEBIT vendor files in the demo tree:"$'\n'"$vendor"
gebit_protos=$(find . \( -path ./.venv -o -path ./.git \) -prune -o -type f -name '*.proto' \
  -exec grep -lE '^[[:space:]]*package[[:space:]]+de\.gebit' {} + 2>/dev/null)
[ -n "$gebit_protos" ] && fail "GEBIT protos in the demo tree:"$'\n'"$gebit_protos"

# 2. no LLM key and no key-bearing config (hard rule 1)
if [ "${#SCAN[@]}" -gt 0 ]; then
  for pattern in 'api_key' 'LLM_SERVICE_API_KEY' 'sk-[A-Za-z0-9]{20,}' 'tool_config'; do
    hits=$(grep -rInE "${EXCLUDES[@]}" -e "$pattern" "${SCAN[@]}" 2>/dev/null \
      | cut -d: -f1,2)
    [ -n "$hits" ] && fail "forbidden pattern /$pattern/ at:"$'\n'"$hits"
  done
fi

# 3. no ${...} in mesh/: sam config apply would fill it from the environment
if [ -d mesh ]; then
  hits=$(grep -rIn "${EXCLUDES[@]}" -F -e '${' mesh 2>/dev/null | cut -d: -f1,2)
  [ -n "$hits" ] && fail "\${ placeholder in mesh/ (sam config apply expands it):"$'\n'"$hits"
fi

# 4. no LLM endpoint: the LiteLLM proxy host lives only in SAM's model configuration
#    (hard rule 1); also the top-level documents (spikes/ and research/ are history)
DOCS=()
for f in *.md; do [ -f "$f" ] && DOCS+=("$f"); done
if [ "$((${#SCAN[@]} + ${#DOCS[@]}))" -gt 0 ]; then
  hits=$(grep -rIinE "${EXCLUDES[@]}" -e 'lite-?llm\.[a-z0-9-]+\.[a-z]{2,}' \
    ${SCAN[@]+"${SCAN[@]}"} ${DOCS[@]+"${DOCS[@]}"} 2>/dev/null | cut -d: -f1,2)
  [ -n "$hits" ] && fail "LLM proxy host (endpoint) at:"$'\n'"$hits"
fi

platform_check() {
  # shellcheck source=/dev/null
  . "$DEMO_DIR/scripts/lib.sh"
  resolve_sam_cli >/dev/null 2>&1 || { fail "--platform: sam CLI not found"; return; }
  # --manifest: --target sends no token (2.542.1); its target name finds the login in
  # the CLI's cache under $HOME. TARGET=aks: --url SAM_URL wins over the manifest's lab
  # URL and the CLI runs with HOME=$SAM_HOME of .env.aks (via lib.sh), the AKS login
  # cache; sam api has no --no-dotenv flag
  local login="sam auth login solace-lab --url $SAM_URL"
  local target_args=(--manifest "$DEMO_DIR/mesh/manifest.yaml")
  if [ "$TARGET" = aks ]; then
    target_args+=(--url "$SAM_URL")
    login="aks_sam sam auth login solace-lab --url $SAM_URL"
  fi
  "$PY" - "$SAM_CLI" "$login" "${target_args[@]}" <<'PY' || FAIL=1
import json, os, subprocess, sys

cli, login, target = sys.argv[1], sys.argv[2], sys.argv[3:]
# aks: the CLI takes the token from its login cache under HOME=SAM_HOME (sam 2.542.1
# ignores SAM_HOME for that cache), never one the shell exported (a lab token must not
# go to the public name); lab: environment as before
TOKENS = ("SAM_AUTH_TOKEN", "SAM_PLATFORM_TOKEN")
child_env = None
if os.environ.get("TARGET") == "aks":
    child_env = {k: v for k, v in os.environ.items() if k not in TOKENS}
    child_env["HOME"] = os.environ["SAM_HOME"]
FORBIDDEN = ("api_key", "tool_config", "LLM_SERVICE_API_KEY")
KINDS = ("workflows", "agents", "connectors", "entrypoints")


def sam(path):
    p = subprocess.run([cli, "api", path, *target], capture_output=True,
                       text=True, timeout=30, check=False, env=child_env)
    if p.returncode != 0:
        raise SystemExit(f"HYGIENE FAIL: --platform: sam api GET {path.split('?')[0]} failed "
                         f"(login? {login})")
    return p.stdout


bad, checked = [], 0
for kind in KINDS:
    page, names = 1, []
    while True:
        body = json.loads(sam(f"/api/v2/platform/{kind}?pageSize=100&pageNumber={page}"))
        data = body.get("data") or []
        names += [(x["id"], x["name"]) for x in data if str(x.get("name", "")).startswith("gpos-")]
        if len(data) < 100:
            break
        page += 1
    for rid, name in names:
        text = sam(f"/api/v2/platform/{kind}/{rid}")
        checked += 1
        if any(word in text for word in FORBIDDEN):
            bad.append(f"{kind}/{name}")
print(f"--platform: {checked} gpos-* resources checked")
for item in bad:
    print(f"HYGIENE FAIL: platform resource {item} carries a key field", file=sys.stderr)
sys.exit(1 if bad else 0)
PY
}

[ "${1:-}" = "--platform" ] && platform_check

if [ "$FAIL" -ne 0 ]; then
  echo "check_hygiene: FAILED" >&2
  exit 1
fi
echo "check_hygiene: clean${1:+ ($1)}"
