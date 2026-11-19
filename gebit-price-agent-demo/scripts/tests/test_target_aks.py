"""TARGET=aks on the Python side (AKS-MIGRATION-PLAN 1.4, A18/A19): env loader and
guard, Key Vault secrets, SAM CLI seam, kubectl, BFF trust, gate record per target
and the SEMP preflight of broker.py. Offline: stub az/kubectl/sam on the PATH, a
local fake SEMP server, no cluster, no Azure, no SAM."""

from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import ROOT, SCRIPTS

import broker
import e2e
import opslib
import render_mesh
from opslib import OpsError

FQDN = "eurocis-showcase.germanywestcentral.cloudapp.azure.com"
AKS_SERVER = "https://aks-eurocis-dns-1a2b3c4d.hcp.germanywestcentral.azmk8s.io:443"
LLM_KEY = "LLM_SERVICE_" + "API_KEY"          # check_hygiene.sh forbids the name itself
SECRET = "s3cr3t-value-not-for-output"
CLEARED = (
    "TARGET", "SAM_URL", "E2E_BASE_URL", "E2E_CA_FILE", "BROKER_SMF_URL", "BROKER_WS_URL",
    "BROKER_VPN", "BROKER_USERNAME", "BROKER_PASSWORD", "BROKER_PASSWORD_KV",
    "BROKER_CREDENTIALS_FROM", "SEMP_URL", "SEMP_USER", "SEMP_PASSWORD_KV",
    "SEMP_PASSWORD_FROM", "SEMP_PASSWORD_KEY", "PG_HOST_FROM_PODS", "SAM_HOME", "AKS_KV",
    "AKS_KUBECONFIG", "KUBE_CONTEXT", "AWE_NS", "AWE_DEPLOY", "GPOS_NS", "R1_MODE",
    "R1_QUEUE", "SAM_ENV_FILE", LLM_KEY, "KEYCLOAK_CLIENT_SECRET", "SAM_AUTH_TOKEN",
    "SAM_PLATFORM_TOKEN", "SAM_TARGET", "SAM_CLI", "SAM_CLI_PATH", "GPOS_BOOTH_LOCATION",
    "GPOS_PROBE_LOCATION", "SAM_RUN_IDENTITY", "PG_MODE", "PG_NS", "PG_POD", "GPOS_IMAGE",
    "ACME_EAB_HMAC")


def aks_values(tmp: Path, semp_port: int = 18080) -> dict[str, str]:
    """The .env.aks of COMMON with test paths (no secret anywhere)."""
    return {
        "AKS_ACR": "", "AKS_KV": "kv-test", "GPOS_NS": "gpos-demo",
        "SAM_URL": f"https://{FQDN}", "SAM_RUN_IDENTITY": "marktleitung@solace.lab",
        "SAM_HOME": str(tmp / "aks-sam-home"), "AKS_KUBECONFIG": str(tmp / "aks.yaml"),
        "KUBE_CONTEXT": "aks-eurocis-admin",
        "BROKER_SMF_URL": "tcp://solace-pubsubplus.solace.svc.cluster.local:55555",
        "BROKER_WS_URL": "ws://solace-pubsubplus.solace.svc.cluster.local:8008",
        "BROKER_VPN": "default", "BROKER_USERNAME": "gpos", "BROKER_PASSWORD_KV": "solace-gpos",
        "SEMP_URL": f"http://127.0.0.1:{semp_port}", "SEMP_USER": "admin",
        "SEMP_PASSWORD_KV": "solace-admin", "R1_MODE": "own", "R1_QUEUE": "gpos-booth-r1",
        "PG_MODE": "kubectl", "PG_NS": "gpos-data", "PG_POD": "gpos-postgres-0",
        "PG_HOST_FROM_PODS": "gpos-postgres.gpos-data.svc.cluster.local",
        "E2E_BASE_URL": f"https://{FQDN}", "E2E_CA_FILE": "system",
        "AWE_NS": "sam-solace-lab", "AWE_DEPLOY": "agent-mesh-solace-agent-mesh-awe",
    }


def write_env(path: Path, values: dict[str, str]) -> Path:
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    return path


def write_kubeconfig(path: Path, server: str = AKS_SERVER,
                     context: str = "aks-eurocis-admin") -> Path:
    path.write_text(yaml.safe_dump({
        "apiVersion": "v1", "kind": "Config", "current-context": context,
        "clusters": [{"name": "aks-eurocis", "cluster": {"server": server}}],
        "contexts": [{"name": context, "context": {"cluster": "aks-eurocis",
                                                   "user": "admin"}}],
        "users": [{"name": "admin", "user": {}}]}), encoding="utf-8")
    return path


def stub(bin_dir: Path, name: str, body: str) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    path = bin_dir / name
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for key in CLEARED:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(opslib, "TARGET", "lab")
    return monkeypatch


@pytest.fixture
def aks(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """TARGET=aks in a scratch demo tree with a lab .env and an .env.aks."""
    demo = tmp_path / "demo"
    demo.mkdir()
    values = aks_values(tmp_path)
    write_env(demo / ".env.aks", values)
    write_env(demo / ".env", {"SAM_URL": "https://sam.solace.lab", "LAB_ONLY_KEY": "lab"})
    write_kubeconfig(tmp_path / "aks.yaml")
    clean_env.setenv("TARGET", "aks")
    clean_env.setattr(opslib, "TARGET", "aks")
    clean_env.setattr(opslib, "DEMO_DIR", demo)
    return {"demo": demo, "values": values, "tmp": tmp_path, "mp": clean_env}


# --------------------------------------------------------------- import-time paths


def import_paths(target: str | None) -> dict[str, str]:
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"),
           "PYTHONPATH": str(SCRIPTS)}
    if target is not None:
        env["TARGET"] = target
    code = ("import json, opslib, render_mesh, e2e\n"
            "d = opslib.DEMO_DIR\n"
            "print(json.dumps({k: str(getattr(opslib, k).relative_to(d)) for k in "
            "('RENDERED', 'BUILD', 'GATE_FILE', 'LOCK_FILE')} | "
            "{'render_mesh': str(render_mesh.RENDERED.relative_to(d)), "
            "'e2e_gate': str(e2e.GATE_FILE.relative_to(d))}))")
    proc = subprocess.run([sys.executable, "-c", code], env=env, cwd=SCRIPTS,
                          capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


def test_lab_paths_are_unchanged() -> None:
    lab = {"RENDERED": "mesh/.rendered", "BUILD": "build", "GATE_FILE": "build/gate-verified",
           "LOCK_FILE": "build/sam_inbox.lock", "render_mesh": "mesh/.rendered",
           "e2e_gate": "build/gate-verified"}
    assert import_paths(None) == lab
    assert import_paths("lab") == lab


def test_aks_paths_have_their_own_directories() -> None:
    assert import_paths("aks") == {
        "RENDERED": "mesh/.rendered/aks", "BUILD": "build/aks",
        "GATE_FILE": "build/aks/gate-verified", "LOCK_FILE": "build/aks/sam_inbox.lock",
        "render_mesh": "mesh/.rendered/aks", "e2e_gate": "build/aks/gate-verified"}
    # an unknown TARGET never falls back to the lab's state
    assert import_paths("prod")["GATE_FILE"] != "build/gate-verified"


# --------------------------------------------------------------------- env loader


def test_aks_reads_only_env_aks(aks: dict[str, Any]) -> None:
    lab_env = aks["demo"] / ".env"
    lab_env.chmod(0)                                  # reading it would raise
    try:
        env = opslib.demo_env()
    finally:
        lab_env.chmod(0o600)
    assert env["TARGET"] == "aks"
    assert env["SAM_URL"] == f"https://{FQDN}" and "LAB_ONLY_KEY" not in env
    assert env["SEMP_URL"] == "http://127.0.0.1:18080"


def test_aks_refuses_a_dot_env_and_a_missing_env_aks(aks: dict[str, Any]) -> None:
    with pytest.raises(OpsError, match=r"never reads .*\.env"):
        opslib.demo_env(aks["demo"] / ".env")
    (aks["demo"] / ".env.aks").unlink()
    with pytest.raises(OpsError, match=r"\.env\.aks missing"):
        opslib.demo_env()


@pytest.mark.parametrize("key,value", [
    ("SAM_URL", "https://sam.solace.lab"),
    ("E2E_BASE_URL", "https://gpos.solace.lab"),
    ("BROKER_WS_URL", "ws://host.docker.internal:8008"),
    ("BROKER_SMF_URL", "tcp://host.docker.internal:55557"),
    ("SEMP_URL", "http://localhost:18080"),
    ("SEMP_URL", "http://127.0.0.1:8080"),
    ("PG_HOST_FROM_PODS", "host.docker.internal"),
    ("E2E_CA_FILE", "/tmp/auth.solace.lab.crt"),
])
def test_aks_guard_rejects_lab_urls(aks: dict[str, Any], key: str, value: str) -> None:
    aks["mp"].setenv(key, value)                      # the process env wins, then the guard
    with pytest.raises(OpsError, match=f"{key} points to the lab"):
        opslib.demo_env()


def test_aks_guard_needs_every_url_key_and_https(aks: dict[str, Any]) -> None:
    values = dict(aks["values"])
    del values["BROKER_WS_URL"]                       # the code default is the lab's
    write_env(aks["demo"] / ".env.aks", values)
    with pytest.raises(OpsError, match=r"BROKER_WS_URL missing in \.env\.aks"):
        opslib.demo_env()
    write_env(aks["demo"] / ".env.aks", aks["values"])
    aks["mp"].setenv("SAM_URL", f"http://{FQDN}")
    with pytest.raises(OpsError, match="SAM_URL must be https://"):
        opslib.demo_env()


def test_aks_guard_needs_an_own_sam_home(aks: dict[str, Any]) -> None:
    aks["mp"].setenv("SAM_HOME", str(opslib.LAB_SAM_HOME))
    with pytest.raises(OpsError, match="lab sam home"):
        opslib.demo_env()
    aks["mp"].delenv("SAM_HOME")
    values = dict(aks["values"])
    del values["SAM_HOME"]
    write_env(aks["demo"] / ".env.aks", values)
    with pytest.raises(OpsError, match="SAM_HOME missing"):
        opslib.demo_env()


@pytest.mark.parametrize("key", ["SAM_ENV_FILE", LLM_KEY, "KEYCLOAK_CLIENT_SECRET"])
def test_aks_refuses_lab_and_amd_variables(aks: dict[str, Any], key: str) -> None:
    aks["mp"].setenv(key, SECRET)
    with pytest.raises(OpsError) as info:
        opslib.demo_env()
    assert key in str(info.value) and SECRET not in str(info.value)


# the same bad .env.aks through scripts/lib.sh (aks_env_check) and opslib (check_aks_env):
# Python entry points without lib.sh (make demo-watch, e2e.py, broker.py, ...) refuse
# exactly what the shell scripts refuse
GUARD_PARITY = [
    ("GPOS_NS", "sam-solace-lab", "GPOS_NS must be gpos-demo"),
    ("PG_NS", "solace", "PG_NS must be gpos-data"),
    ("PG_NS", None, "PG_NS must be gpos-data"),
    ("PG_POD", "postgres-0", "PG_POD must be gpos-postgres-0"),
    ("PG_MODE", "docker", "PG_MODE must be kubectl"),
    ("AKS_KUBECONFIG", None, "AKS_KUBECONFIG missing in .env.aks"),
    ("KUBE_CONTEXT", None, "KUBE_CONTEXT missing in .env.aks"),
    ("E2E_CA_FILE", "build/lab-ca.crt", "E2E_CA_FILE is the lab CA"),
    ("GPOS_IMAGE", "registry.solace.lab/gpos-demo/gpos-demo", "GPOS_IMAGE is a lab image"),
]


@pytest.mark.parametrize("key,value,message", [("", None, "")] + GUARD_PARITY)
def test_shell_and_python_guards_refuse_the_same_env_aks(
        clean_env: pytest.MonkeyPatch, tmp_path: Path, key: str, value: str | None,
        message: str) -> None:
    from test_target_shell import Tree, replace_key  # noqa: PLC0415 -- scratch tree helper

    tree = Tree(tmp_path / "shell")
    if key:
        replace_key(tree, key, value)
    proc = tree.bash("echo REACHED", target="aks")
    demo = tmp_path / "py"
    demo.mkdir()
    shutil.copy(tree.demo / ".env.aks", demo / ".env.aks")
    clean_env.setenv("HOME", str(tree.home))          # $HOME of the file = the scratch home
    clean_env.setenv("TARGET", "aks")
    clean_env.setattr(opslib, "TARGET", "aks")
    clean_env.setattr(opslib, "DEMO_DIR", demo)
    if not key:                                       # control: the unchanged file passes both
        assert proc.returncode == 0 and "REACHED" in proc.stdout, proc.stderr
        assert opslib.demo_env()["PG_POD"] == "gpos-postgres-0"
        return
    assert proc.returncode != 0 and message in proc.stderr
    with pytest.raises(OpsError, match=re.escape(message)):
        opslib.demo_env()


def test_lab_refuses_to_run_inside_an_aks_subshell(clean_env: pytest.MonkeyPatch,
                                                   tmp_path: Path) -> None:
    lab = write_env(tmp_path / ".env", {"SAM_URL": "https://sam.solace.lab"})
    assert opslib.demo_env(lab)["SAM_URL"] == "https://sam.solace.lab"
    # aks_sam/aks_kc export SAM_ENV_FILE (and KUBECONFIG = the AKS file), as lib.sh
    clean_env.setenv("SAM_ENV_FILE", "/x/agent-mesh-deployment/.env.aks")
    with pytest.raises(OpsError, match="AKS subshell"):
        opslib.demo_env(lab)


def test_aks_drops_the_zerossl_key(aks: dict[str, Any]) -> None:
    with (aks["demo"] / ".env.aks").open("a", encoding="utf-8") as f:
        f.write(f"ACME_EAB_KID=kid-1\nACME_EAB_HMAC={SECRET}\n")
    env = opslib.demo_env()
    assert env["ACME_EAB_KID"] == "kid-1" and "ACME_EAB_HMAC" not in env
    assert SECRET not in json.dumps(env)


def test_unknown_or_switched_target_is_refused(clean_env: pytest.MonkeyPatch,
                                               capsys: pytest.CaptureFixture) -> None:
    clean_env.setenv("TARGET", "prod")
    with pytest.raises(OpsError, match="expected lab or aks"):
        opslib.demo_env()
    assert e2e.main(["--gate-status"]) == 2
    assert "expected lab or aks" in capsys.readouterr().err
    clean_env.setenv("TARGET", "aks")                # process started as lab (opslib.TARGET)
    with pytest.raises(OpsError, match="started with TARGET=lab"):
        opslib.demo_env()


def test_lab_env_loader_is_unchanged(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lab = write_env(tmp_path / ".env", {"SAM_URL": "https://sam.solace.lab",
                                        "SEMP_URL": "http://localhost:8080"})
    clean_env.setenv("SEMP_URL", "http://override:1")
    env = opslib.demo_env(lab)
    assert env["SAM_URL"] == "https://sam.solace.lab" and env["SEMP_URL"] == "http://override:1"
    assert "TARGET" not in env
    clean_env.setattr(opslib, "DEMO_DIR", tmp_path)
    assert opslib.demo_env()["SAM_URL"] == "https://sam.solace.lab"


# ------------------------------------------------------------------------ Key Vault

AZ = """#!/bin/bash
for a in "$@"; do printf '%s\\n' "$a"; done >> "$FAKE_AZ_LOG"
if [ -n "${FAKE_AZ_FAIL:-}" ]; then
  printf 'partial %s' "$FAKE_AZ_VALUE"
  echo "ERROR: (Forbidden) access denied near $FAKE_AZ_VALUE" >&2
  exit 3
fi
printf '%s\\n' "$FAKE_AZ_VALUE"
"""


@pytest.fixture
def fake_az(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    stub(tmp_path / "bin", "az", AZ)
    log = tmp_path / "az.log"
    clean_env.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    clean_env.setenv("FAKE_AZ_LOG", str(log))
    clean_env.setenv("FAKE_AZ_VALUE", SECRET)
    return log


def test_kv_secret_reads_by_pipe_only(fake_az: Path, capsys: pytest.CaptureFixture) -> None:
    assert opslib.kv_secret({"AKS_KV": "kv-test"}, "solace-gpos") == SECRET
    argv = fake_az.read_text().splitlines()
    assert argv == ["keyvault", "secret", "show", "--vault-name", "kv-test", "-n",
                    "solace-gpos", "--query", "value", "-o", "tsv"]
    printed = capsys.readouterr()
    assert SECRET not in fake_az.read_text() + printed.out + printed.err


def test_kv_secret_errors_never_carry_the_value(fake_az: Path,
                                                clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("FAKE_AZ_FAIL", "1")
    with pytest.raises(OpsError) as info:
        opslib.kv_secret({"AKS_KV": "kv-test"}, "solace-admin")
    assert str(info.value) == ("Key Vault secret solace-admin: az rc 3 "
                               "(no access (Key Vault access policy))")
    assert info.value.__cause__ is None and SECRET not in str(info.value)
    with pytest.raises(OpsError, match="AKS_KV not set"):
        opslib.kv_secret({}, "solace-admin")
    with pytest.raises(OpsError, match="invalid"):
        opslib.kv_secret({"AKS_KV": "kv-test"}, "a b;rm")
    clean_env.setenv("PATH", str(fake_az.parent / "empty"))
    with pytest.raises(OpsError, match="az CLI not found"):
        opslib.kv_secret({"AKS_KV": "kv-test"}, "solace-admin")


def test_broker_credentials_on_aks_come_from_the_vault(aks: dict[str, Any]) -> None:
    calls: list[str] = []
    aks["mp"].setattr(opslib, "kv_secret", lambda env, name: calls.append(name) or SECRET)
    aks["mp"].setenv("BROKER_PASSWORD", "lab-password")          # never used on aks
    aks["mp"].setenv("BROKER_CREDENTIALS_FROM", "/nonexistent")  # never read on aks
    env = opslib.demo_env()
    assert opslib.broker_credentials(env) == ("gpos", SECRET) and calls == ["solace-gpos"]
    with pytest.raises(OpsError, match="BROKER_PASSWORD_KV"):
        opslib.broker_credentials({**env, "BROKER_PASSWORD_KV": ""})


def test_render_mesh_on_aks(aks: dict[str, Any], capsys: pytest.CaptureFixture) -> None:
    aks["mp"].setattr(opslib, "kv_secret", lambda env, name: SECRET)
    out = aks["tmp"] / "rendered"
    assert render_mesh.main(["--out", str(out)]) == 0
    booth = yaml.safe_load((out / "entrypoints/gpos-booth-events.yaml").read_text())
    values = booth["spec"]["values"]
    assert values["broker_url"] == "ws://solace-pubsubplus.solace.svc.cluster.local:8008"
    assert (values["broker_username"], values["broker_password"]) == ("gpos", SECRET)
    manifest_text = (out / "manifest-booth.yaml").read_text()
    assert yaml.safe_load(manifest_text)["target"] == {
        "name": "solace-lab", "url": f"https://{FQDN}", "auth": {"type": "oauth"}}
    # the manual apply goes only through aks_sam (AKS SAM_HOME; runbook 1.6), never a
    # plain `sam` of the shell, whose login cache is the lab's
    assert manifest_text.splitlines()[2] == (
        f'#   cd "$GPD/mesh/.rendered/aks" && aks_sam sam config apply --url https://{FQDN} '
        "--no-dotenv -m manifest-booth.yaml")
    assert "solace.lab" not in manifest_text.replace("name: solace-lab", "")
    broker_env = aks["tmp"] / "broker.env"
    assert render_mesh.main(["--write-broker-env", str(broker_env)]) == 0
    lines = dict(line.split("=", 1) for line in broker_env.read_text().splitlines())
    assert lines["SOLACE_HOST"] == "tcp://solace-pubsubplus.solace.svc.cluster.local:55555"
    assert lines["SOLACE_PASSWORD"] == SECRET
    printed = capsys.readouterr()
    assert SECRET not in printed.out + printed.err


# ------------------------------------------------------------------------- SAM CLI

SAM = """#!/bin/bash
{ printf 'ARGV'; for a in "$@"; do printf ' %s' "$a"; done; printf '\\n'
  printf 'HOME=%s TOKEN=%s\\n' "${SAM_HOME:-}" "${SAM_AUTH_TOKEN:+set}"; } >> "$FAKE_SAM_LOG"
if [ -n "${FAKE_SAM_NOLOGIN:-}" ]; then
  echo 'sam api: no cached OAuth credentials; run `sam auth login` (target "solace-lab")' >&2
  exit 1
fi
echo '{"data": []}'
"""


@pytest.fixture
def fake_sam(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    cli = stub(tmp_path / "bin", "sam", SAM)
    log = tmp_path / "sam.log"
    clean_env.setenv("FAKE_SAM_LOG", str(log))
    clean_env.setenv("SAM_AUTH_TOKEN", "lab-token")
    return cli, log


def test_sam_cli_lab_argv_is_unchanged(fake_sam: tuple[Path, Path]) -> None:
    cli, log = fake_sam
    api = opslib.SamApi({"SAM_CLI_PATH": str(cli)})
    assert api.call("GET", "/api/v1/user") == {"data": []}
    api.refresh()
    lines = log.read_text().splitlines()
    assert lines[0] == f"ARGV api -X GET /api/v1/user --manifest {opslib.SAM_MANIFEST}"
    assert lines[1] == "HOME= TOKEN=set"               # inherited as before
    assert lines[2] == "ARGV config plan --no-dotenv --no-interactive"


def test_sam_cli_lab_missing_oauth_cache_stays_one_call(fake_sam: tuple[Path, Path],
                                                        clean_env: pytest.MonkeyPatch) -> None:
    """Lab unchanged: the 2.542.1 answer "no cached OAuth credentials" stays one CLI call
    and an OpsError with the CLI's text (no refresh and retry); only aks maps it to
    SamAuthError."""
    cli, log = fake_sam
    clean_env.setenv("FAKE_SAM_NOLOGIN", "1")
    with pytest.raises(OpsError, match="api GET /api/v1/user failed: .*no cached OAuth") as info:
        opslib.SamApi({"SAM_CLI_PATH": str(cli)}).call("GET", "/api/v1/user")
    assert not isinstance(info.value, opslib.SamAuthError)
    assert [x for x in log.read_text().splitlines() if x.startswith("ARGV")] == [
        f"ARGV api -X GET /api/v1/user --manifest {opslib.SAM_MANIFEST}"]


def test_sam_cli_on_aks_has_url_home_and_no_shell_token(fake_sam: tuple[Path, Path],
                                                        clean_env: pytest.MonkeyPatch,
                                                        tmp_path: Path) -> None:
    cli, log = fake_sam
    env = {**aks_values(tmp_path), "TARGET": "aks", "SAM_CLI_PATH": str(cli)}
    api = opslib.SamApi(env)
    api.call("POST", "/api/v1/notify/inbox/x/respond", {"status": "cancelled"})
    api.refresh()
    lines = log.read_text().splitlines()
    assert lines[0] == (f"ARGV api -X POST /api/v1/notify/inbox/x/respond --manifest "
                        f"{opslib.SAM_MANIFEST} --url https://{FQDN} --input -")
    assert lines[1] == f"HOME={tmp_path / 'aks-sam-home'} TOKEN="
    assert lines[2] == f"ARGV config plan --no-dotenv --no-interactive --url https://{FQDN}"
    assert lines[3] == f"HOME={tmp_path / 'aks-sam-home'} TOKEN="
    assert os.environ["SAM_AUTH_TOKEN"] == "lab-token"   # the shell keeps its own
    clean_env.setenv("FAKE_SAM_NOLOGIN", "1")
    with pytest.raises(opslib.SamAuthError,
                       match=f"aks_sam sam auth login solace-lab --url https://{FQDN}"):
        api.call("GET", "/api/v1/user")
    argv = [x for x in log.read_text().splitlines() if x.startswith("ARGV")][2:]
    assert argv == [f"ARGV api -X GET /api/v1/user --manifest {opslib.SAM_MANIFEST} "
                    f"--url https://{FQDN}",
                    f"ARGV config plan --no-dotenv --no-interactive --url https://{FQDN}",
                    f"ARGV api -X GET /api/v1/user --manifest {opslib.SAM_MANIFEST} "
                    f"--url https://{FQDN}"]                # refresh, then one retry


# ------------------------------------------------------------------------- kubectl


def test_kubectl_lab_and_aks(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert opslib.kubectl_base({}) == ["kubectl"]
    env = {**aks_values(tmp_path), "TARGET": "aks"}
    with pytest.raises(OpsError, match="aks.yaml missing"):
        opslib.kubectl_base(env)
    write_kubeconfig(tmp_path / "aks.yaml", server="https://127.0.0.1:6443")
    with pytest.raises(OpsError, match="is not https://aks-eurocis-"):
        opslib.kubectl_base(env)
    write_kubeconfig(tmp_path / "aks.yaml", context="rancher-desktop")
    with pytest.raises(OpsError, match="context aks-eurocis-admin missing"):
        opslib.kubectl_base(env)
    write_kubeconfig(tmp_path / "aks.yaml")
    assert opslib.kubectl_base(env) == ["kubectl", "--kubeconfig", str(tmp_path / "aks.yaml"),
                                        "--context", "aks-eurocis-admin"]
    # a mapping without TARGET follows the process: never plain kubectl under aks
    clean_env.setenv("TARGET", "aks")
    assert opslib.kubectl_base({k: v for k, v in env.items() if k != "TARGET"})[1] == (
        "--kubeconfig")


def test_kubectl_ui_and_awe_log_argv(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(cmd: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    clean_env.setattr(opslib.subprocess, "run", run)
    opslib.kubectl_ui({}, ["-m", "gposdemo.ui.ctl", "probe", "notify"])
    assert calls[-1] == ["kubectl", "-n", "gpos-demo", "exec", "deploy/gpos-ui", "--",
                         "python", "-m", "gposdemo.ui.ctl", "probe", "notify"]
    env = {**aks_values(tmp_path), "TARGET": "aks", "AWE_NS": "sam-x", "AWE_DEPLOY": "awe-y"}
    write_kubeconfig(tmp_path / "aks.yaml")
    base = ["kubectl", "--kubeconfig", str(tmp_path / "aks.yaml"), "--context",
            "aks-eurocis-admin"]
    opslib.kubectl_ui(env, ["-", "--reset-store", "199"], stdin="x")
    assert calls[-1] == base + ["-n", "gpos-demo", "exec", "-i", "deploy/gpos-ui", "--",
                                "python", "-", "--reset-store", "199"]
    runner = object.__new__(e2e.E2E)
    runner.agent_ids, runner.env = {}, env
    runner.awe_tools(60)
    assert calls[-1] == base + ["-n", "sam-x", "logs", "deploy/awe-y", "-c", "awe",
                                "--since=90s"]


# ----------------------------------------------------------------------- BFF trust


def test_bff_with_the_system_trust_store(tmp_path: Path) -> None:
    bff = opslib.Bff({"E2E_BASE_URL": f"https://{FQDN}", "E2E_CA_FILE": "system"})
    assert bff.base == f"https://{FQDN}"
    bff.close()
    trust = opslib.system_trust()
    assert trust is True or hasattr(trust, "wrap_socket")
    with pytest.raises(OpsError, match="lab-ca.crt missing: scripts/install.sh k8s exports"):
        opslib.Bff({"E2E_BASE_URL": "https://gpos.solace.lab",
                    "E2E_CA_FILE": str(tmp_path / "lab-ca.crt")})


# ----------------------------------------------------------------- gate per target


def copy_mesh(root: Path) -> Path:
    import shutil  # noqa: PLC0415

    for rel in ("mesh/connectors", "mesh/agents", "mesh/workflows", "mesh/fallback"):
        shutil.copytree(ROOT / rel, root / rel)
    return root


def test_a_lab_gate_pass_never_counts_for_aks(tmp_path: Path) -> None:
    root = copy_mesh(tmp_path)
    record = (f"result=PASS\nhash={opslib.gate_hash(root)}\n"
              f"modes={opslib.GATE_MODES_TEXT}\n")
    (root / "build").mkdir()
    (root / "build" / "gate-verified").write_text(record)
    assert opslib.gate_verified(root, target="lab")
    assert not opslib.gate_verified(root, target="aks")
    (root / "build" / "aks").mkdir()
    (root / "build" / "aks" / "gate-verified").write_text(record)     # copied lab record
    assert not opslib.gate_verified(root, target="aks")
    (root / "build" / "aks" / "gate-verified").write_text("target=aks\n" + record)
    assert opslib.gate_verified(root, target="aks")


def test_gate_verify_records_the_target(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FakeSse:
        stop = type("S", (), {"set": lambda self: None})()

    class FakeE2E:
        def __init__(self, env: Any, args: Any) -> None:
            self.args, self.approver, self.sse = args, e2e.APPROVER_AGENTS[0], FakeSse()

        def preflight(self) -> None:
            pass

    def fake_series(obj: Any, runs: int, out: Path) -> list[e2e.RunResult]:
        tools = {e2e.EVIDENCE_AGENT: ["get_transaction"], obj.approver: ["apply_price"]}
        return [e2e.RunResult(n, "98", "S1", obj.args.mode, data={"awe_tools": tools})
                for n in range(runs)]

    record = tmp_path / "gate-verified"
    clean_env.setattr(e2e, "E2E", FakeE2E)
    clean_env.setattr(e2e, "run_series", fake_series)
    clean_env.setattr(e2e, "GATE_FILE", record)
    clean_env.setattr(e2e, "kubectl_ui", lambda *a, **k: subprocess.CompletedProcess(a, 0))
    base = e2e.argparse.Namespace(till="01", scenario="S1", mode="approve", runs=1,
                                  answer_delay=0.0, fallback_f2=False)
    out = e2e.DEMO_DIR / "build" / "aks" / "e2e" / "test.jsonl"
    assert e2e.gate_verify({"TARGET": "aks"}, base, out, False)
    lines = record.read_text().splitlines()
    assert lines[:2] == ["result=PASS", "target=aks"]
    assert e2e.gate_verify({}, base, out, False)
    assert not any(line.startswith("target=") for line in record.read_text().splitlines())


# ------------------------------------------------------------------ SEMP preflight


class FakeSempState:
    def __init__(self, vpns: list[str], password: str = SECRET, html: bool = False) -> None:
        self.vpns, self.password, self.html = vpns, password, html
        self.paths: list[str] = []


def semp_handler(state: FakeSempState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            pass

        def send(self, code: int, body: Any, ctype: str = "application/json") -> None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            state.paths.append(self.path)
            if state.html:
                self.send(200, b"<html>not semp</html>", "text/html")
                return
            want = "Basic " + base64.b64encode(f"admin:{state.password}".encode()).decode()
            if self.headers.get("Authorization") != want:
                self.send(401, {"meta": {"responseCode": 401}})
            elif self.path.startswith("/SEMP/v2/monitor/about/api"):
                self.send(200, {"data": {"platform": "VMR", "sempVersion": "2.48"},
                                "meta": {"responseCode": 200}})
            elif self.path.startswith("/SEMP/v2/config/msgVpns"):
                self.send(200, {"data": [{"msgVpnName": v} for v in state.vpns],
                                "meta": {"responseCode": 200}})
            else:
                self.send(400, {"meta": {"error": {"status": "NOT_FOUND"}}})
    return Handler


@pytest.fixture
def semp_server() -> Iterator[tuple[FakeSempState, int]]:
    state = FakeSempState(["default", "sam"])
    server = ThreadingHTTPServer(("127.0.0.1", 0), semp_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield state, server.server_address[1]
    server.shutdown()
    server.server_close()


def aks_semp_env(tmp: Path, port: int) -> dict[str, str]:
    write_kubeconfig(tmp / "aks.yaml")
    return {**aks_values(tmp, port), "TARGET": "aks"}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def vault(clean_env: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    clean_env.setattr(broker, "kv_secret", lambda env, name: calls.append(name) or SECRET)
    return calls


def test_semp_preflight_accepts_the_aks_broker(semp_server: tuple[FakeSempState, int],
                                               vault: list[str], tmp_path: Path,
                                               capsys: pytest.CaptureFixture) -> None:
    state, port = semp_server
    with broker.semp_session(aks_semp_env(tmp_path, port)) as semp:
        assert semp.base == f"http://127.0.0.1:{port}" and semp.vpn == "default"
    assert vault == ["solace-admin"]
    assert state.paths[0] == "/SEMP/v2/monitor/about/api"
    assert state.paths[1].startswith("/SEMP/v2/config/msgVpns")
    err = capsys.readouterr().err
    assert "AKS broker, SEMP API 2.48, VPNs default, sam" in err and SECRET not in err


def test_semp_preflight_aborts_on_the_lab_broker(semp_server: tuple[FakeSempState, int],
                                                 vault: list[str], tmp_path: Path) -> None:
    state, port = semp_server
    state.vpns = ["amartens-test", "default", "sam"]
    entered = []
    with pytest.raises(OpsError, match="amartens-test: that is the Lab-Broker"):
        with broker.semp_session(aks_semp_env(tmp_path, port)):
            entered.append(1)
    assert entered == [] and len(state.paths) == 2      # nothing after the VPN list


def test_semp_preflight_aborts_on_a_foreign_password_or_no_semp(
        semp_server: tuple[FakeSempState, int], vault: list[str], tmp_path: Path) -> None:
    state, port = semp_server
    state.password = "the-lab-password"
    with pytest.raises(OpsError, match="rejects the AKS admin password"):
        with broker.semp_session(aks_semp_env(tmp_path, port)):
            pass
    state.html = True
    with pytest.raises(OpsError, match="no SEMP v2 answer|not a SEMP v2 broker"):
        with broker.semp_session(aks_semp_env(tmp_path, port)):
            pass



@pytest.fixture
def raw_listener() -> Iterator[int]:
    """A TCP listener that is not HTTP at all (a forward to another service)."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    stop = threading.Event()

    def serve() -> None:
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except OSError:
                continue
            with conn:
                conn.sendall(b"SSH-2.0-OpenSSH_9.0\r\n")
                with contextlib.suppress(OSError):
                    conn.recv(4096)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield server.getsockname()[1]
    stop.set()
    thread.join(2)
    server.close()


def test_semp_preflight_aborts_cleanly_on_a_non_http_listener(
        raw_listener: int, aks: dict[str, Any], vault: list[str],
        capsys: pytest.CaptureFixture) -> None:
    """BadStatusLine is no OSError: it must still end as the OpsError (exit 2), not as a
    traceback."""
    with pytest.raises(OpsError, match="no SEMP v2 answer"):
        with broker.semp_session(aks_semp_env(aks["tmp"], raw_listener)):
            pass
    write_env(aks["demo"] / ".env.aks", aks_values(aks["tmp"], raw_listener))
    assert broker.main(["r1-show"]) == 2
    err = capsys.readouterr().err
    assert "no SEMP v2 answer" in err and SECRET not in err


KUBECTL = """#!{python}
import json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
with open(os.environ["FAKE_KUBECTL_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
if os.environ.get("FAKE_KUBECTL_FAIL"):
    sys.stderr.write("error: unable to forward port: pod not running\\n")
    sys.exit(1)
port = int(sys.argv[-1].split(":")[0])

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def do_GET(self):
        if "about/api" in self.path:
            body = {{"data": {{"sempVersion": "2.48"}}}}
        else:
            body = {{"data": [{{"msgVpnName": "default"}}, {{"msgVpnName": "sam"}}]}}
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

HTTPServer(("127.0.0.1", port), H).serve_forever()
"""


@pytest.fixture
def fake_kubectl(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    stub(tmp_path / "bin", "kubectl", KUBECTL.format(python=sys.executable))
    log = tmp_path / "kubectl.log"
    clean_env.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    clean_env.setenv("FAKE_KUBECTL_LOG", str(log))
    return log


def test_semp_preflight_opens_and_closes_its_own_forward(fake_kubectl: Path, vault: list[str],
                                                         tmp_path: Path) -> None:
    port = free_port()
    with broker.semp_session(aks_semp_env(tmp_path, port)) as semp:
        assert broker.listening(port)
        assert semp.request("GET", "monitor/about/api")[0] == 200
    argv = json.loads(fake_kubectl.read_text().splitlines()[0])
    assert argv == ["--kubeconfig", str(tmp_path / "aks.yaml"), "--context",
                    "aks-eurocis-admin", "-n", "solace", "port-forward", "--address",
                    "127.0.0.1", "svc/solace-pubsubplus", f"{port}:8080"]
    deadline = time.monotonic() + 5
    while broker.listening(port, 0.2) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not broker.listening(port, 0.2)              # closed at exit


def test_semp_preflight_reuses_an_open_forward(semp_server: tuple[FakeSempState, int],
                                               fake_kubectl: Path, vault: list[str],
                                               tmp_path: Path) -> None:
    _, port = semp_server
    with broker.semp_session(aks_semp_env(tmp_path, port)):
        pass
    assert not fake_kubectl.exists()                    # kubectl never called


def test_semp_preflight_reports_a_failed_forward(fake_kubectl: Path, vault: list[str],
                                                 clean_env: pytest.MonkeyPatch,
                                                 tmp_path: Path) -> None:
    clean_env.setenv("FAKE_KUBECTL_FAIL", "1")
    with pytest.raises(OpsError, match="port-forward .* failed: error: unable to forward"):
        with broker.semp_session(aks_semp_env(tmp_path, free_port())):
            pass
    assert vault == []                                  # no secret read before the forward


def test_aks_semp_has_no_tfvars_fallback(vault: list[str], tmp_path: Path) -> None:
    tfvars = tmp_path / "terraform.tfvars"
    tfvars.write_text('solace_1_password = "lab"\n')
    env = {**aks_values(tmp_path), "TARGET": "aks", "SEMP_PASSWORD_KV": "",
           "SEMP_PASSWORD_FROM": str(tfvars)}
    with pytest.raises(OpsError, match="no tfvars fallback"):
        broker.Semp.from_env(env)
    assert vault == []


@pytest.mark.parametrize("url", ["http://localhost:18080", "https://127.0.0.1:18080",
                                 "http://127.0.0.1", "http://10.0.0.5:18080", "",
                                 "http://127.0.0.1:99999"])
def test_aks_semp_url_must_be_a_local_forward(url: str) -> None:
    with pytest.raises(OpsError, match="SEMP_URL must be http://127.0.0.1:<port>"):
        broker.aks_semp_port(url)
    assert broker.aks_semp_port("http://127.0.0.1:18080") == 18080


def test_broker_main_on_aks(aks: dict[str, Any], semp_server: tuple[FakeSempState, int],
                            vault: list[str], capsys: pytest.CaptureFixture) -> None:
    _, port = semp_server
    write_env(aks["demo"] / ".env.aks", aks_values(aks["tmp"], port))
    assert broker.main(["txflows", "gpos-booth-r1"]) == 0
    printed = capsys.readouterr()
    assert printed.out == "0\n"                          # stdout stays parseable
    assert "AKS broker" in printed.err and SECRET not in printed.out + printed.err
    semp_server[0].vpns.append("amartens-test")
    assert broker.main(["r1-show"]) == 2
    assert "Lab-Broker" in capsys.readouterr().err
