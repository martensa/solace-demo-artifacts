"""TARGET=lab|aks on the shell side (AKS-MIGRATION-PLAN 1.4): scripts/lib.sh,
install.sh pg, uninstall.sh and check_hygiene.sh --platform in a scratch tree.

Stubs for kubectl, az, docker, openssl and the sam CLI log their argv (and stdin);
nothing reaches a cluster, Azure, a broker or SAM. Proves: the lab argv is the one
of before, aks never reads .env, the refusals and the lab-URL guard, kubectl bound
to the AKS kubeconfig and context, and no secret value ever in an argv.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import ROOT

AMD = ROOT.parent / "agent-mesh-deployment"
FQDN = "eurocis-showcase.germanywestcentral.cloudapp.azure.com"
AKS_SERVER = "https://aks-eurocis-0a1b2c3d.hcp.germanywestcentral.azmk8s.io:443"
LLM_VAR = "LLM_SERVICE_" + "API_KEY"   # check_hygiene.sh is the only file naming it
KV_VALUE = "kv-value-7f3a9c1e"           # stands in for a Key Vault secret
RAND = "0123abcd" * 6                    # stands in for `openssl rand -hex 24`
SAM_TOKEN = "tok-5e1f"

STUB = r'''#!/usr/bin/env python3
import json, os, sys
name, args = os.path.basename(sys.argv[0]), sys.argv[1:]
# read stdin only where the real tool does (a pipe stage must not eat another's input)
reads = any(a == "-" or "/dev/stdin" in a for a in args) or ("exec" in args and "-i" in args)
data = sys.stdin.read() if reads and sys.stdin is not None else ""
with open(os.path.join(os.environ["STUB_DIR"], "calls.jsonl"), "a") as log:
    log.write(json.dumps({"cmd": name, "args": args, "stdin": data, "cwd": os.getcwd(),
                          "sam_home": os.environ.get("SAM_HOME"),
                          "home": os.environ.get("HOME"),
                          "token_env": sorted(k for k in ("SAM_AUTH_TOKEN", "SAM_PLATFORM_TOKEN")
                                              if k in os.environ),
                          "target": os.environ.get("TARGET")}) + "\n")
env = os.environ.get
if name == "kubectl":
    if "config" in args and "view" in args:
        print(env("STUB_SERVER", ""), end="")
    elif "kustomize" in args:
        sys.stdout.write(open(env("STUB_KUSTOMIZE")).read())
    elif "get" in args and "--ignore-not-found" in args:
        print(env("STUB_SECRET_PRESENT", ""))
    elif "create" in args:
        sys.stdout.write("apiVersion: v1\nkind: Secret\n")
    elif "psql" in args and any("pg_roles" in a for a in args):
        print(env("STUB_DB_STATE", "1/4"))
elif name == "az" and "show" in args:
    sys.stdout.write(env("STUB_KV_VALUE", "") + "\n")
    sys.exit(int(env("STUB_AZ_RC", "0")))
elif name == "docker" and "inspect" in args:
    print("true")
elif name == "openssl":
    print(env("STUB_RAND", ""))
elif name == "sam" and args[:1] == ["api"]:
    print('{"data": []}')
'''

NAMESPACE_DOC = """apiVersion: v1
kind: Namespace
metadata:
  name: {name}
---
apiVersion: v1
kind: Service
metadata:
  name: other
  namespace: {name}
"""


def env_aks_text() -> str:
    return f"""# scratch .env.aks (template: infra/aks/env.aks.example)
touch "$STUB_DIR/env-aks-read"
AKS_ACR=acrtest
AKS_KV=kvtest
GPOS_NS=gpos-demo
GPOS_IMAGE=${{AKS_ACR}}.azurecr.io/gpos-demo/gpos-demo
GPOS_VERSION=0.1.3
SAM_URL=https://{FQDN}
SAM_RUN_IDENTITY=marktleitung@solace.lab
SAM_HOME=$HOME/.config/eurocis-aks/sam
AKS_KUBECONFIG=$HOME/.kube/aks-eurocis.yaml
KUBE_CONTEXT=aks-eurocis-admin
BROKER_SMF_URL=tcp://solace-pubsubplus.solace.svc.cluster.local:55555
BROKER_WS_URL=ws://solace-pubsubplus.solace.svc.cluster.local:8008
BROKER_VPN=default
BROKER_USERNAME=gpos
BROKER_PASSWORD_KV=solace-gpos
SEMP_URL=http://127.0.0.1:18080
SEMP_USER=admin
SEMP_PASSWORD_KV=solace-admin
R1_MODE=own
R1_QUEUE=gpos-booth-r1
GPOS_DELIVERY=direct
PG_MODE=kubectl
PG_NS=gpos-data
PG_POD=gpos-postgres-0
PG_HOST_FROM_PODS=gpos-postgres.gpos-data.svc.cluster.local
PG_PORT=5432
PG_DB=gpos
GEBIT_DESCRIPTOR_DIR=$HOME/Downloads/Gebit
GPOS_DEMO_DATE=2027-02-16
GATE_MIN_DELAY_S=3
GATE_GUARD=block
E2E_BASE_URL=https://{FQDN}
E2E_CA_FILE=system
AWE_NS=sam-solace-lab
AWE_DEPLOY=agent-mesh-solace-agent-mesh-awe
"""


class Tree:
    """Scratch copy: <tmp>/gpd/scripts/*.sh + <tmp>/agent-mesh-deployment common.sh."""

    def __init__(self, base: Path) -> None:
        self.base = base
        self.demo = base / "gpd"
        self.home = base / "home"
        self.stub = base / "stubdir"
        self.bin = base / "bin"
        for d in (self.demo / "scripts", self.demo / "mesh", self.home / ".kube", self.stub,
                  self.bin, base / "agent-mesh-deployment" / "scripts" / "lib",
                  self.demo / "k8s" / "postgres-aks", self.demo / ".venv" / "bin"):
            d.mkdir(parents=True, exist_ok=True)
        shutil.copy(AMD / "scripts" / "lib" / "common.sh",
                    base / "agent-mesh-deployment" / "scripts" / "lib" / "common.sh")
        for script in (ROOT / "scripts").glob("*.sh"):
            shutil.copy(script, self.demo / "scripts" / script.name)
        venv_py = self.demo / ".venv" / "bin" / "python"
        venv_py.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        venv_py.chmod(0o755)
        (self.demo / "k8s" / "postgres-aks" / "kustomization.yaml").write_text("resources: []\n")
        (self.demo / ".env").write_text('touch "$STUB_DIR/env-read"\nLAB_MARK=1\n'
                                        "SAM_URL=https://sam.solace.lab\n")
        (self.demo / ".env.aks").write_text(env_aks_text())
        self.kubeconfig = self.home / ".kube" / "aks-eurocis.yaml"
        self.kubeconfig.write_text("apiVersion: v1\nkind: Config\n")
        self.sam_home = self.home / ".config" / "eurocis-aks" / "sam"
        self.kustomize = base / "render.yaml"
        self.kustomize.write_text(NAMESPACE_DOC.format(name="gpos-data"))
        for name in ("kubectl", "az", "docker", "openssl", "sam"):
            (self.bin / name).write_text(STUB)
            (self.bin / name).chmod(0o755)

    def env(self, target: str | None, **extra: str) -> dict[str, str]:
        env = {"PATH": f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(self.home),
               "TMPDIR": str(self.base), "STUB_DIR": str(self.stub), "LANG": "C",
               "STUB_SERVER": AKS_SERVER, "STUB_KUSTOMIZE": str(self.kustomize),
               "STUB_KV_VALUE": KV_VALUE, "STUB_RAND": RAND,
               "SAM_CLI_PATH": str(self.bin / "sam")}
        if target is not None:
            env["TARGET"] = target
        env.update(extra)
        return env

    def bash(self, code: str, target: str | None = "lab", **extra: str
             ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["/bin/bash", "-c", f"set -euo pipefail\n. scripts/lib.sh\n{code}"],
                              cwd=self.demo, env=self.env(target, **extra), capture_output=True,
                              text=True, stdin=subprocess.DEVNULL, check=False)

    def run(self, argv: list[str], target: str | None = "lab", **extra: str
            ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(argv, cwd=self.demo, env=self.env(target, **extra),
                              capture_output=True, text=True, stdin=subprocess.DEVNULL,
                              check=False)

    def calls(self, cmd: str | None = None) -> list[dict]:
        path = self.stub / "calls.jsonl"
        if not path.exists():
            return []
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        return [r for r in rows if cmd is None or r["cmd"] == cmd]

    def read(self, name: str) -> bool:
        return (self.stub / name).exists()


@pytest.fixture
def tree(tmp_path: Path) -> Tree:
    return Tree(tmp_path)


def kv(out: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


SHOW = ('printf "TARGET=%s\\nRENDERED=%s\\nBUILD=%s\\nKUBECTL=%s\\nLAB_MARK=%s\\n'
        'SAM_HOME=%s\\nENV_NAME=%s\\nEXPORTED=%s\\n" "$TARGET" "$RENDERED" "$BUILD_DIR" '
        '"$(type -t kubectl)" "${LAB_MARK:-}" "${SAM_HOME:-}" "$ENV_NAME" '
        '"$(/usr/bin/env | grep -c "^TARGET=")"')


# ------------------------------------------------------------------- env loading


@pytest.mark.parametrize("target", [None, "lab", ""])
def test_lab_reads_dot_env_only_and_keeps_todays_paths(tree: Tree, target: str | None) -> None:
    proc = tree.bash(SHOW, target=target)
    assert proc.returncode == 0, proc.stderr
    got = kv(proc.stdout)
    # lab: TARGET reaches the children only if the shell exported it (as before the switch)
    assert got["TARGET"] == "lab" and got["EXPORTED"] == ("0" if target is None else "1")
    assert got["RENDERED"] == f"{tree.demo}/mesh/.rendered"
    assert got["BUILD"] == f"{tree.demo}/build"
    assert got["KUBECTL"] == "file"               # plain kubectl, no wrapper
    assert got["LAB_MARK"] == "1" and got["ENV_NAME"] == ".env" and got["SAM_HOME"] == ""
    assert tree.read("env-read") and not tree.read("env-aks-read")


def test_aks_reads_env_aks_only(tree: Tree) -> None:
    proc = tree.bash(SHOW, target="aks")
    assert proc.returncode == 0, proc.stderr
    got = kv(proc.stdout)
    assert got["TARGET"] == "aks" and got["EXPORTED"] == "1"
    assert got["RENDERED"] == f"{tree.demo}/mesh/.rendered/aks"
    assert got["BUILD"] == f"{tree.demo}/build/aks"
    assert got["KUBECTL"] == "function"
    assert got["LAB_MARK"] == "" and got["ENV_NAME"] == ".env.aks"
    assert got["SAM_HOME"] == str(tree.sam_home)
    assert tree.read("env-aks-read") and not tree.read("env-read")


def test_aks_never_exports_the_zerossl_key(tree: Tree) -> None:
    with (tree.demo / ".env.aks").open("a") as f:
        f.write("ACME_EAB_KID=kid-1\nACME_EAB_HMAC=hmac-secret-4\n")
    proc = tree.bash('printf "KID=%s\\nHMAC=%s\\nCHILD=%s\\n" "$ACME_EAB_KID" '
                     '"${ACME_EAB_HMAC-unset}" "$(/usr/bin/env | grep -c "^ACME_EAB_HMAC=")"',
                     target="aks")
    assert kv(proc.stdout) == {"KID": "kid-1", "HMAC": "unset", "CHILD": "0"}, proc.stderr


def test_env_file_cannot_switch_the_target(tree: Tree) -> None:
    with (tree.demo / ".env").open("a") as f:
        f.write("TARGET=aks\n")
    with (tree.demo / ".env.aks").open("a") as f:
        f.write("TARGET=lab\n")
    assert kv(tree.bash(SHOW, target="lab").stdout)["TARGET"] == "lab"
    assert kv(tree.bash(SHOW, target="aks").stdout)["TARGET"] == "aks"


@pytest.mark.parametrize("var", ["SAM_ENV_FILE", LLM_VAR, "KEYCLOAK_CLIENT_SECRET"])
@pytest.mark.parametrize("value", ["secret-in-env-9", ""])
def test_aks_refuses_lab_and_amd_variables(tree: Tree, var: str, value: str) -> None:
    proc = tree.bash("echo REACHED", target="aks", **{var: value})
    assert proc.returncode != 0 and "REACHED" not in proc.stdout
    assert var in proc.stderr and "refused" in proc.stderr
    if value:
        assert value not in proc.stdout + proc.stderr
    assert not tree.read("env-read")
    if var != "SAM_ENV_FILE":                    # SAM_ENV_FILE: see the AKS subshell test
        assert tree.bash("echo REACHED", target="lab", **{var: "x"}).returncode == 0


@pytest.mark.parametrize("target", [None, "lab"])
def test_lab_refuses_to_run_inside_an_aks_subshell(tree: Tree, target: str | None) -> None:
    # aks_sam/aks_kc export SAM_ENV_FILE (and KUBECONFIG = the AKS file)
    proc = tree.bash("echo REACHED", target=target, SAM_ENV_FILE="/x/agent-mesh/.env.aks")
    assert proc.returncode != 0 and "REACHED" not in proc.stdout
    assert "AKS subshell" in proc.stderr and not tree.read("env-read")


def test_aks_refuses_a_refused_variable_from_env_aks(tree: Tree) -> None:
    with (tree.demo / ".env.aks").open("a") as f:
        f.write(f"{LLM_VAR}=secret-in-file-3\n")
    proc = tree.bash("echo REACHED", target="aks")
    assert proc.returncode != 0 and LLM_VAR in proc.stderr
    assert "secret-in-file-3" not in proc.stdout + proc.stderr


GUARDED = ["SAM_URL", "E2E_BASE_URL", "BROKER_SMF_URL", "BROKER_WS_URL", "SEMP_URL",
           "PG_HOST_FROM_PODS", "E2E_CA_FILE"]
LAB_VALUES = ["https://sam.solace.lab", "tcp://host.docker.internal:55557",
              "http://localhost:9999", "http://127.0.0.1:8080", "https://GPOS.SOLACE.LAB"]


def replace_key(tree: Tree, key: str, value: str | None) -> None:
    lines = [ln for ln in (tree.demo / ".env.aks").read_text().splitlines()
             if not ln.startswith(f"{key}=")]
    if value is not None:
        lines.append(f"{key}={value}")
    (tree.demo / ".env.aks").write_text("\n".join(lines) + "\n")


@pytest.mark.parametrize("key", GUARDED)
@pytest.mark.parametrize("value", LAB_VALUES)
def test_aks_lab_url_guard(tree: Tree, key: str, value: str) -> None:
    replace_key(tree, key, value)
    proc = tree.bash("echo REACHED", target="aks")
    assert proc.returncode != 0 and "REACHED" not in proc.stdout
    assert f"{key} points to the lab" in proc.stderr
    assert value not in proc.stderr                # names keys, never values


@pytest.mark.parametrize("key", GUARDED + ["AKS_KUBECONFIG", "KUBE_CONTEXT", "SAM_HOME",
                                           "PG_MODE"])
def test_aks_requires_every_key_whose_default_is_lab(tree: Tree, key: str) -> None:
    replace_key(tree, key, None)
    proc = tree.bash("echo REACHED", target="aks")
    assert proc.returncode != 0 and key in proc.stderr


@pytest.mark.parametrize(("key", "value", "message"), [
    ("SAM_HOME", '"$HOME/Library/Application Support/sam"', "lab sam home"),
    ("SAM_HOME", "$HOME", "SAM_HOME is the real HOME"),
    ("SAM_HOME", "$HOME/", "SAM_HOME is the real HOME"),
    ("SAM_HOME", ".config/eurocis-aks/sam", "SAM_HOME must be an absolute path"),
    ("GPOS_NS", "sam-solace-lab", "GPOS_NS must be gpos-demo"),
    ("PG_NS", "solace", "PG_NS must be gpos-data"),
    ("PG_NS", "", "PG_NS must be gpos-data"),
    ("PG_POD", "postgres-0", "PG_POD must be gpos-postgres-0"),
    ("SAM_URL", f"http://{FQDN}", "SAM_URL must be https://"),
    ("E2E_CA_FILE", "build/lab-ca.crt", "lab CA"),
    ("PG_MODE", "docker", "PG_MODE must be kubectl"),
    ("GPOS_IMAGE", "registry.solace.lab/gpos-demo/gpos-demo", "lab image"),
])
def test_aks_other_lab_values_refused(tree: Tree, key: str, value: str, message: str) -> None:
    replace_key(tree, key, value)
    proc = tree.bash("echo REACHED", target="aks")
    assert proc.returncode != 0 and message in proc.stderr


def test_aks_without_env_aks_and_unknown_target(tree: Tree) -> None:
    (tree.demo / ".env.aks").unlink()
    proc = tree.bash("echo REACHED", target="aks")
    assert proc.returncode != 0 and ".env.aks missing" in proc.stderr
    assert not tree.read("env-read")
    proc = tree.bash("echo REACHED", target="AKS")
    assert proc.returncode != 0 and "TARGET must be lab or aks" in proc.stderr


def test_env_aks_template_passes_the_guard(tree: Tree) -> None:
    template = ROOT / "infra" / "aks" / "env.aks.example"
    if not template.exists():
        pytest.skip("infra/aks/env.aks.example not there yet")
    text = template.read_text()
    text = text.replace("AKS_ACR=\n", "AKS_ACR=acrtest\n").replace("AKS_KV=\n", "AKS_KV=kvtest\n")
    (tree.demo / ".env.aks").write_text(text)
    proc = tree.bash(SHOW, target="aks")
    assert proc.returncode == 0, proc.stderr
    assert kv(proc.stdout)["RENDERED"].endswith("/mesh/.rendered/aks")


# ---------------------------------------------------------------- kubectl, psql


def test_aks_kubectl_is_bound_to_the_aks_kubeconfig_and_context(tree: Tree) -> None:
    proc = tree.bash("kubectl -n gpos-demo get pods", target="aks")
    assert proc.returncode == 0, proc.stderr
    calls = tree.calls("kubectl")
    assert calls[-1]["args"] == ["--kubeconfig", str(tree.kubeconfig), "--context",
                                 "aks-eurocis-admin", "-n", "gpos-demo", "get", "pods"]
    assert all(c["args"][:4] == ["--kubeconfig", str(tree.kubeconfig), "--context",
                                 "aks-eurocis-admin"] for c in calls)


@pytest.mark.parametrize("server", ["https://127.0.0.1:6443", "", AKS_SERVER + "/x",
                                    "https://aks-eurocis-1.hcp.westeurope.azmk8s.io:443"])
def test_aks_kubectl_refuses_a_foreign_api_server(tree: Tree, server: str) -> None:
    proc = tree.bash("kubectl -n gpos-demo get pods", target="aks", STUB_SERVER=server)
    assert proc.returncode != 0 and "not the AKS cluster" in proc.stderr
    assert not [c for c in tree.calls("kubectl") if "pods" in c["args"]]


def test_aks_kubectl_refuses_a_missing_kubeconfig(tree: Tree) -> None:
    tree.kubeconfig.unlink()
    proc = tree.bash("kubectl get pods", target="aks")
    assert proc.returncode != 0 and "kubeconfig" in proc.stderr
    assert tree.calls("kubectl") == []


def test_lab_kubectl_is_plain(tree: Tree) -> None:
    assert tree.bash("kubectl -n gpos-demo get pods").returncode == 0
    assert [c["args"] for c in tree.calls("kubectl")] == [["-n", "gpos-demo", "get", "pods"]]


def test_psql_seam(tree: Tree) -> None:
    assert tree.bash("psql_admin -d gpos -c 'select 1'").returncode == 0
    assert tree.calls("docker")[-1]["args"] == [
        "exec", "-i", "postgres", "psql", "-X", "-U", "postgres", "-v", "ON_ERROR_STOP=1",
        "-d", "gpos", "-c", "select 1"]
    proc = tree.bash("psql_admin -d gpos -c 'select 1'", target="aks")
    assert proc.returncode == 0, proc.stderr
    assert tree.calls("kubectl")[-1]["args"] == [
        "--kubeconfig", str(tree.kubeconfig), "--context", "aks-eurocis-admin", "-n",
        "gpos-data", "exec", "-i", "gpos-postgres-0", "--", "psql", "-X", "-U", "postgres",
        "-v", "ON_ERROR_STOP=1", "-d", "gpos", "-c", "select 1"]
    assert [c["args"] for c in tree.calls("docker")] == [
        ["exec", "-i", "postgres", "psql", "-X", "-U", "postgres", "-v", "ON_ERROR_STOP=1",
         "-d", "gpos", "-c", "select 1"]]                      # aks never ran docker


# ------------------------------------------------------------------------ sam CLI


def write_cache(home: Path, token: str = SAM_TOKEN) -> None:
    """The cache `sam auth login solace-lab` writes when the CLI runs with this HOME
    (sam 2.542.1 ignores SAM_HOME and --sam-home for it)."""
    auth = home / "Library" / "Application Support" / "sam" / "auth"
    auth.mkdir(parents=True, exist_ok=True)
    (auth / "solace-lab.json").write_text(json.dumps({"sam_access_token": token}))


def test_sam_argv_lab_is_unchanged(tree: Tree) -> None:
    write_cache(tree.home)
    proc = tree.bash('sam_login; sam_apply "$DEMO_DIR/mesh" manifest-rbac.yaml')
    assert proc.returncode == 0, proc.stderr
    plan, apply = tree.calls("sam")
    assert plan["args"] == ["config", "plan", "--no-dotenv", "--no-interactive"]
    assert apply["args"] == ["config", "apply", "--no-dotenv", "--no-interactive", "-m",
                             "manifest-rbac.yaml"]
    assert plan["sam_home"] is None and apply["cwd"] == str(tree.demo / "mesh")
    assert plan["home"] == apply["home"] == str(tree.home)


def test_sam_argv_aks_has_url_and_aks_home(tree: Tree) -> None:
    write_cache(tree.home, token="lab-token-0")          # the lab login stays untouched
    write_cache(tree.sam_home)
    proc = tree.bash('sam_login; sam_apply "$DEMO_DIR/mesh"; '
                     'test "$SAM_AUTH_TOKEN" = ' + SAM_TOKEN, target="aks",
                     SAM_AUTH_TOKEN="shell-token", SAM_PLATFORM_TOKEN="shell-token")
    assert proc.returncode == 0, proc.stderr
    plan, apply = tree.calls("sam")
    url = f"https://{FQDN}"
    assert plan["args"] == ["config", "plan", "--no-dotenv", "--no-interactive", "--url", url]
    assert apply["args"] == ["config", "apply", "--no-dotenv", "--no-interactive", "-m",
                             "manifest.yaml", "--url", url]
    assert plan["sam_home"] == apply["sam_home"] == str(tree.sam_home)
    assert plan["home"] == apply["home"] == str(tree.sam_home)   # the AKS login cache
    assert plan["token_env"] == apply["token_env"] == []           # no token of the shell
    assert all(SAM_TOKEN not in arg for c in tree.calls() for arg in c["args"])


def test_aks_unsets_the_shells_tokens(tree: Tree) -> None:
    proc = tree.bash('echo "${SAM_AUTH_TOKEN:-none}/${SAM_PLATFORM_TOKEN:-none}"',
                     target="aks", SAM_AUTH_TOKEN="lab-tok", SAM_PLATFORM_TOKEN="lab-tok")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "none/none"
    lab = tree.bash('echo "${SAM_AUTH_TOKEN:-none}"', SAM_AUTH_TOKEN="lab-tok")
    assert lab.stdout.strip() == "lab-tok"                         # lab as before


@pytest.mark.parametrize("cache", ["none", "lab", "sam_home_auth"])
def test_aks_sam_login_needs_the_aks_login(tree: Tree, cache: str) -> None:
    if cache == "lab":                    # only the lab login: never used for AKS
        write_cache(tree.home)
    elif cache == "sam_home_auth":        # where the CLI never writes it
        (tree.sam_home / "auth").mkdir(parents=True)
        (tree.sam_home / "auth" / "solace-lab.json").write_text(
            json.dumps({"sam_access_token": SAM_TOKEN}))
    proc = tree.bash('sam_login || echo "LOGIN FAILED ${SAM_AUTH_TOKEN:-}"', target="aks")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "LOGIN FAILED"
    assert f"aks_sam sam auth login solace-lab --url https://{FQDN}" in proc.stderr
    assert f"HOME={tree.sam_home}" in proc.stderr
    assert SAM_TOKEN not in proc.stdout + proc.stderr


def test_sam_apply_still_refuses_prune(tree: Tree) -> None:
    proc = tree.bash('sam_apply "$DEMO_DIR/mesh" manifest.yaml --prune', target="aks")
    assert proc.returncode != 0 and "--prune is forbidden" in proc.stderr
    assert tree.calls("sam") == []


def test_platform_hygiene_uses_the_targets_sam_flags(tree: Tree) -> None:
    lab = tree.run(["scripts/check_hygiene.sh", "--platform"], target=None,
                   SAM_AUTH_TOKEN="shell-token")
    assert lab.returncode == 0, lab.stderr
    assert {tuple(c["token_env"]) for c in tree.calls("sam")} == {("SAM_AUTH_TOKEN",)}
    manifest = str(tree.demo / "mesh" / "manifest.yaml")
    lab_calls = [c["args"] for c in tree.calls("sam")]
    assert lab_calls and all(a[0] == "api" and a[2:] == ["--manifest", manifest]
                             for a in lab_calls)
    (tree.stub / "calls.jsonl").unlink()
    (tree.stub / "env-read").unlink()
    aks = tree.run(["scripts/check_hygiene.sh", "--platform"], target="aks",
                   SAM_AUTH_TOKEN="shell-token", SAM_PLATFORM_TOKEN="shell-token")
    assert aks.returncode == 0, aks.stderr
    aks_calls = tree.calls("sam")
    assert all(c["token_env"] == [] for c in aks_calls)   # the AKS login cache only
    assert aks_calls and all(c["args"][2:] == ["--manifest", manifest, "--url",
                                               f"https://{FQDN}"] for c in aks_calls)
    assert {c["sam_home"] for c in aks_calls} == {str(tree.sam_home)}
    assert {c["home"] for c in aks_calls} == {str(tree.sam_home)}
    assert {c["home"] for c in tree.calls("sam")} == {str(tree.sam_home)}
    assert not tree.read("env-read")


# ------------------------------------------------------------------ Key Vault


def argv_text(tree: Tree) -> str:
    return "\n".join(" ".join(c["args"]) for c in tree.calls())


def test_kv_secret_pipes_only(tree: Tree) -> None:
    proc = tree.bash("v=$(kv_secret solace-admin); test \"$v\" = " + KV_VALUE +
                     "; kv_secret solace-admin | wc -c", target="aks")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.split()[-1] == str(len(KV_VALUE))            # no newline
    assert tree.calls("az")[-1]["args"] == ["keyvault", "secret", "show", "--vault-name",
                                            "kvtest", "-n", "solace-admin", "--query",
                                            "value", "-o", "tsv"]
    assert KV_VALUE not in argv_text(tree) and KV_VALUE not in proc.stderr


def test_kv_secret_fails_closed(tree: Tree) -> None:
    proc = tree.bash("kv_secret solace-admin")
    assert proc.returncode != 0 and "only with TARGET=aks" in proc.stderr
    assert tree.calls("az") == []
    proc = tree.bash("kv_secret solace-admin >/dev/null", target="aks", STUB_AZ_RC="3")
    assert proc.returncode != 0


def test_acr_pull_secret_built_in_pipes(tree: Tree) -> None:
    proc = tree.bash("apply_acr_pull gpos-demo", target="aks")
    assert proc.returncode == 0, proc.stderr
    create = next(c for c in tree.calls("kubectl") if "create" in c["args"])
    assert create["args"][4:] == ["-n", "gpos-demo", "create", "secret", "generic", "acr-pull",
                                  "--type=kubernetes.io/dockerconfigjson",
                                  "--from-file=.dockerconfigjson=/dev/stdin",
                                  "--dry-run=client", "-o", "yaml"]
    auth = json.loads(create["stdin"])["auths"]["acrtest.azurecr.io"]
    assert auth == {"username": "aks-pull", "password": KV_VALUE,
                    "auth": base64.b64encode(f"aks-pull:{KV_VALUE}".encode()).decode()}
    apply = tree.calls("kubectl")[-1]
    assert "--server-side" in apply["args"] and apply["stdin"].startswith("apiVersion")
    assert KV_VALUE not in argv_text(tree)
    assert tree.calls("az")[-1]["args"][5:7] == ["-n", "acr-pull-token"]


def test_acr_pull_refuses_an_empty_token(tree: Tree) -> None:
    proc = tree.bash("apply_acr_pull gpos-demo", target="aks", STUB_KV_VALUE="")
    assert proc.returncode != 0
    create = next(c for c in tree.calls("kubectl") if "create" in c["args"])
    assert create["stdin"] == ""          # jq refused: no valid dockerconfigjson
    assert tree.bash("apply_acr_pull gpos-demo").returncode != 0   # lab: never


def test_broker_secret_built_in_pipes(tree: Tree) -> None:
    proc = tree.bash("apply_broker_secret gpos-demo", target="aks")
    assert proc.returncode == 0, proc.stderr
    apply = tree.calls("kubectl")[-1]
    assert apply["args"][4:] == ["apply", "--server-side", "--force-conflicts",
                                 "--field-manager=gpos-install", "-f", "-"]
    doc = json.loads(apply["stdin"])
    assert doc["metadata"] == {"name": "gpos-broker", "namespace": "gpos-demo"}
    data = {k: base64.b64decode(v).decode() for k, v in doc["data"].items()}
    assert data == {"SOLACE_HOST": "tcp://solace-pubsubplus.solace.svc.cluster.local:55555",
                    "SOLACE_VPN": "default", "SOLACE_USERNAME": "gpos",
                    "SOLACE_PASSWORD": KV_VALUE}
    assert tree.calls("az")[-1]["args"][5:7] == ["-n", "solace-gpos"]
    assert KV_VALUE not in argv_text(tree) + proc.stdout + proc.stderr
    assert not list(tree.base.glob("gpos-k8s.*"))              # no file


def test_broker_secret_refuses_an_empty_password(tree: Tree) -> None:
    proc = tree.bash("apply_broker_secret gpos-demo", target="aks", STUB_KV_VALUE="")
    assert proc.returncode != 0
    assert tree.calls("kubectl")[-1]["stdin"] == ""            # no object to apply
    assert tree.bash("apply_broker_secret gpos-demo").returncode != 0   # lab: never


# ------------------------------------------------------------- install.sh pg


def test_install_pg_is_a_noop_in_the_lab(tree: Tree) -> None:
    proc = tree.run(["scripts/install.sh", "pg"], target=None)
    assert proc.returncode == 0, proc.stderr
    assert "nothing to do" in proc.stdout and "== done (pg)" in proc.stdout
    assert tree.calls("kubectl") == [] and tree.calls("docker") == []


def test_install_pg_on_aks(tree: Tree) -> None:
    proc = tree.run(["scripts/install.sh", "pg"], target="aks")
    assert proc.returncode == 0, proc.stderr
    assert "secret gpos-postgres-admin created" in proc.stdout
    calls = [c["args"][4:] for c in tree.calls("kubectl")
             if not ("config" in c["args"] and "view" in c["args"])]
    pg = str(tree.demo / "k8s" / "postgres-aks")
    assert calls[0] == ["kustomize", pg]
    assert calls[1] == ["apply", "-f", "-"]
    assert calls[2][:6] == ["-n", "gpos-data", "get", "secret", "gpos-postgres-admin",
                            "--ignore-not-found"]
    assert calls[3] == ["apply", "--server-side", "--field-manager=gpos-install", "-f", "-"]
    assert calls[4] == ["apply", "-k", pg]
    assert calls[5] == ["-n", "gpos-data", "rollout", "status", "sts/gpos-postgres",
                        "--timeout=300s"]
    assert "pg_isready" in calls[6]
    rows = tree.calls("kubectl")
    ns_doc = next(c for c in rows if c["args"][4:] == ["apply", "-f", "-"])["stdin"]
    assert "kind: Namespace" in ns_doc and "name: gpos-data" in ns_doc and "Service" not in ns_doc
    secret = json.loads(next(c for c in rows if "--server-side" in c["args"])["stdin"])
    assert secret["metadata"] == {"name": "gpos-postgres-admin", "namespace": "gpos-data"}
    assert base64.b64decode(secret["data"]["password"]).decode() == RAND   # piped, no newline
    assert RAND not in argv_text(tree) + proc.stdout + proc.stderr
    assert not tree.read("env-read")


def test_install_pg_keeps_an_existing_password(tree: Tree) -> None:
    proc = tree.run(["scripts/install.sh", "pg"], target="aks",
                    STUB_SECRET_PRESENT="secret/gpos-postgres-admin")
    assert proc.returncode == 0, proc.stderr
    assert "present (kept)" in proc.stdout
    assert not [c for c in tree.calls("kubectl") if "--server-side" in c["args"]]
    assert tree.calls("openssl") == []


@pytest.mark.parametrize("rand", ["", "not-hex-" * 6, "0123abcd"])
def test_install_pg_never_applies_a_bad_password(tree: Tree, rand: str) -> None:
    proc = tree.run(["scripts/install.sh", "pg"], target="aks", STUB_RAND=rand)
    assert proc.returncode != 0 and "created" not in proc.stdout
    secret = [c for c in tree.calls("kubectl") if "--server-side" in c["args"]]
    assert [c["stdin"] for c in secret] == [""]          # kubectl apply got no object
    assert not [c for c in tree.calls("kubectl") if "-k" in c["args"]]


def test_install_pg_refuses_a_render_without_its_namespace(tree: Tree) -> None:
    tree.kustomize.write_text(NAMESPACE_DOC.format(name="gpos-other"))
    proc = tree.run(["scripts/install.sh", "pg"], target="aks")
    assert proc.returncode != 0 and "no Namespace gpos-data" in proc.stderr
    assert not [c for c in tree.calls("kubectl") if "apply" in c["args"]]


# ------------------------------------------------------------------ uninstall.sh


def uninstall_calls(tree: Tree) -> list[list[str]]:
    return [c["args"] for c in tree.calls() if c["cmd"] in ("kubectl", "docker")
            and not ("config" in c["args"] and "view" in c["args"])]


def test_uninstall_aks_keeps_gpos_data_without_drop_db(tree: Tree) -> None:
    (tree.demo / "scripts" / "broker.sh").write_text("#!/bin/bash\nexit 0\n")
    proc = tree.run(["scripts/uninstall.sh"], target="aks")
    assert proc.returncode == 0, proc.stderr
    calls = uninstall_calls(tree)
    assert [c[4:] for c in calls] == [["delete", "ns", "gpos-demo", "--ignore-not-found",
                                       "--wait=true"]]
    assert "namespace gpos-data and DB gpos kept" in proc.stdout


def test_uninstall_aks_drop_db_via_the_seam_then_gpos_data(tree: Tree) -> None:
    (tree.demo / "scripts" / "broker.sh").write_text("#!/bin/bash\nexit 0\n")
    proc = tree.run(["scripts/uninstall.sh", "--drop-db"], target="aks")
    assert proc.returncode == 0, proc.stderr
    calls = [c[4:] for c in uninstall_calls(tree)]
    assert calls[0] == ["delete", "ns", "gpos-demo", "--ignore-not-found", "--wait=true"]
    assert calls[1][:6] == ["-n", "gpos-data", "exec", "-i", "gpos-postgres-0", "--"]
    assert "drop database if exists gpos with (force)" in calls[1]
    assert calls[-1] == ["delete", "ns", "gpos-data", "--ignore-not-found", "--wait=true"]
    assert tree.calls("docker") == []


@pytest.mark.parametrize(("target", "key", "value", "message"), [
    (None, "GPOS_NS", "solace", "refusing to delete namespace 'solace'"),
    ("aks", "GPOS_NS", "sam-solace-lab", "GPOS_NS must be gpos-demo"),
    ("aks", "PG_NS", "solace", "PG_NS must be gpos-data"),
])
def test_uninstall_deletes_only_gpos_namespaces(tree: Tree, target: str | None, key: str,
                                                value: str, message: str) -> None:
    (tree.demo / "scripts" / "broker.sh").write_text("#!/bin/bash\nexit 0\n")
    env_file = tree.demo / (".env.aks" if target == "aks" else ".env")
    with env_file.open("a") as f:
        f.write(f"{key}={value}\n")
    proc = tree.run(["scripts/uninstall.sh", "--drop-db"], target=target)
    assert proc.returncode != 0 and message in proc.stderr
    assert uninstall_calls(tree) == [] and tree.calls("sam") == []   # checked first


def test_uninstall_lab_argv_unchanged(tree: Tree) -> None:
    (tree.demo / "scripts" / "broker.sh").write_text("#!/bin/bash\nexit 0\n")
    proc = tree.run(["scripts/uninstall.sh", "--drop-db"], target=None)
    assert proc.returncode == 0, proc.stderr
    assert uninstall_calls(tree) == [
        ["delete", "ns", "gpos-demo", "--ignore-not-found", "--wait=true"],
        ["exec", "-i", "postgres", "psql", "-X", "-U", "postgres", "-v", "ON_ERROR_STOP=1",
         "-q", "-d", "postgres", "-c", "drop database if exists gpos with (force)"],
        *[["exec", "-i", "postgres", "psql", "-X", "-U", "postgres", "-v", "ON_ERROR_STOP=1",
           "-q", "-d", "postgres", "-c", f"drop role if exists gpos_{r}"]
          for r in ("pos", "wws", "loyalty", "engine")]]
    assert "broker (solace-1, VPN default)" in proc.stdout
    assert "gpos-data" not in proc.stdout


# ---------------------------------------------------------------------- Makefile


def make(target: str | None, *goals: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "TARGET"}
    if target is not None:
        env["TARGET"] = target
    return subprocess.run(["make", "-n", *goals], cwd=ROOT, env=env, capture_output=True,
                          text=True, check=False)


def test_makefile_kubectl_recipes_follow_the_target() -> None:
    lab = make(None, "status", "logs")
    assert lab.returncode == 0, lab.stderr
    assert lab.stdout.splitlines()[:2] == [
        "kubectl -n gpos-demo get pods -o wide",
        "kubectl -n gpos-demo exec deploy/gpos-ui -- python -m gposdemo.ui.ctl state"]
    aks = make("aks", "status", "logs")
    lines = [ln for ln in aks.stdout.splitlines() if ln.strip()]
    assert all(ln.startswith("bash -c '. scripts/lib.sh && kubectl \"$@\"' kubectl -n ")
               for ln in lines if "kubectl" in ln)
    assert len([ln for ln in lines if "scripts/lib.sh" in ln]) == 3
    assert make("bogus", "status").returncode != 0


def test_makefile_urls_and_lab_only_recipes() -> None:
    env = {k: v for k, v in os.environ.items() if k != "TARGET"}
    aks = subprocess.run(["make", "urls"], cwd=ROOT, env={**env, "TARGET": "aks"},
                         capture_output=True, text=True, check=True).stdout
    assert f"https://{FQDN}/kasse" in aks and "solace.lab" not in aks
    lab = subprocess.run(["make", "urls"], cwd=ROOT, env=env, capture_output=True, text=True,
                         check=True).stdout
    assert "https://gpos.solace.lab/kasse" in lab and FQDN not in lab
    assert "runs against the lab only" in make("aks", "test-int").stdout
    assert ". ./.env" in make(None, "test-int").stdout
    assert "runs against the lab only" in make("aks", "test-db").stdout
    assert make(None, "test-db").stdout.startswith(".venv/bin/python -m pytest")


@pytest.mark.parametrize("goal", ["build", "push", "k8s-up", "manifests", "demo-up"])
def test_makefile_never_builds_or_pushes_the_lab_image_on_aks(goal: str) -> None:
    aks = make("aks", goal)
    assert aks.returncode == 0, aks.stderr               # -n: printed, not run
    assert f"ERROR: make {goal} builds, pushes or runs the lab image" in aks.stdout
    lines = aks.stdout.splitlines()                      # the refusal and nothing else
    assert lines[0].startswith("echo ") and lines[-1] == "exit 1" and len(lines) == 3
    assert "registry.solace.lab/gpos-demo/gpos-demo:" in make(None, goal).stdout   # lab


def test_makefile_offline_tests_are_target_neutral() -> None:
    assert all(ln.startswith("env -u TARGET ") for ln in make("aks", "test").stdout.splitlines())
    assert all(ln.startswith(".venv/bin/python -m pytest")
               for ln in make(None, "test").stdout.splitlines())
