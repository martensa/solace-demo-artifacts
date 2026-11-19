"""Shared helpers of the Mac-side operator scripts of the gpos demo (UC1).

Used by render_mesh.py, broker.py, sam_inbox.py, e2e.py and check_manifests.py.
Nothing here prints a credential: values read from .env files, credential files,
the Key Vault or the SAM CLI are only returned to the caller.

Target switch (AKS-MIGRATION-PLAN 1.4): the environment variable TARGET selects
the installation, ``lab`` (default: everything as before) or ``aks``. On aks
:func:`demo_env` reads only ``.env.aks`` (never ``.env``) and refuses lab values
(:func:`check_aks_env`), kubectl runs with the AKS kubeconfig and context
(:func:`kubectl_base`), the SAM CLI with its own ``SAM_HOME`` and ``--url
SAM_URL``, secrets come from the Key Vault at runtime (:func:`kv_secret`), and
the rendered files and build records live in ``mesh/.rendered/aks`` and
``build/aks``.

Only the standard library and PyYAML at import time; httpx is imported lazily
by Bff (the .venv has it, the system python3 may not).
"""

from __future__ import annotations

import contextlib
import dataclasses
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEMO_DIR = Path(__file__).resolve().parent.parent
NS_DEFAULT = "gpos-demo"
RUN_IDENTITY_DEFAULT = "marktleitung@solace.lab"
SAM_TARGET_DEFAULT = "solace-lab"
# `sam api --target <name>` sends no Authorization header in 2.542.1 (13.11.2026:
# 401 "Missing authorization header" right after `sam auth login`); `--manifest`
# with the oauth target of mesh/manifest.yaml uses the login cache. With `--url`
# the CLI still looks the token up under the manifest's target name (19.11.2026,
# empty SAM_HOME: 'no cached OAuth credentials ... (target "solace-lab")').
SAM_MANIFEST = DEMO_DIR / "mesh" / "manifest.yaml"
SAM_LOGIN_HINT_LAB = "sam auth login solace-lab --url https://sam.solace.lab"
SAM_AUTH_PATTERN_LAB = r"\b401\b|Unauthorized|Not authenticated|no cached token"
SAM_AUTH_PATTERN_AKS = SAM_AUTH_PATTERN_LAB + r"|no cached OAuth"
BROKER_CREDENTIALS_DEFAULT = "../bsg-trading-desk-demo/.env"

# ------------------------------------------------------------------ target switch
TARGETS = ("lab", "aks")
AKS_ENV_FILE = ".env.aks"
# set in the environment of an aks run, these would carry lab or amd secrets into it
# (the LLM key variable is spelled in two parts: check_hygiene.sh forbids the name)
AKS_REFUSED_ENV = ("SAM_ENV_FILE", "LLM_SERVICE_" + "API_KEY", "KEYCLOAK_CLIENT_SECRET")
# URL-ish values whose code defaults are lab values: required on aks, never lab-like
AKS_URL_KEYS = ("SAM_URL", "E2E_BASE_URL", "BROKER_SMF_URL", "BROKER_WS_URL", "SEMP_URL",
                "PG_HOST_FROM_PODS", "E2E_CA_FILE")
AKS_HTTPS_KEYS = ("SAM_URL", "E2E_BASE_URL")
LAB_URL_MARKERS = ("solace.lab", "host.docker.internal", "localhost", ":8080")
LAB_SAM_HOME = Path.home() / "Library" / "Application Support" / "sam"
AKS_API_SERVER = "https://aks-eurocis-*.hcp.germanywestcentral.azmk8s.io:443"
SAM_TOKEN_ENV = ("SAM_AUTH_TOKEN", "SAM_PLATFORM_TOKEN")


def target_dirs(target: str) -> tuple[Path, Path]:
    """(rendered dir, build dir) of a target: the lab keeps today's paths, every
    other target gets its own subdirectory (mesh/.rendered/aks, build/aks)."""
    if target == "lab":
        return DEMO_DIR / "mesh" / ".rendered", DEMO_DIR / "build"
    return DEMO_DIR / "mesh" / ".rendered" / target, DEMO_DIR / "build" / target


# TARGET of this process, fixed at import (the shell sets it before the start). An
# unknown value never falls back to the lab's state; every entry point refuses it
# (current_target via demo_env, e2e.py --gate-status).
TARGET = os.environ.get("TARGET") or "lab"
RENDERED, BUILD = target_dirs(TARGET if TARGET in TARGETS else "aks")
LOCK_FILE = BUILD / "sam_inbox.lock"
GATE_FILE = BUILD / "gate-verified"
GATE_HASH_DIRS = ("mesh/connectors", "mesh/agents", "mesh/workflows")
GATE_HASH_DIRS_F2 = ("mesh/fallback",)
# runs of the gate verification on probe till 98 (9.9): approve x3, A9 deny x5,
# A10 timeout x2; build/gate-verified must name exactly these (key "modes")
GATE_MODES = (("approve", 3), ("deny", 5), ("timeout", 2))
GATE_MODES_TEXT = ",".join(f"{mode}:{runs}" for mode, runs in GATE_MODES)

APPROVER_AGENTS = ("gpos-price-approver", "gpos-price-approver-f2")
REF_RE = re.compile(r"\bRef (GP-\d{6}-\d{4})\b")
_DOTENV_LINE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_VAR_REF = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")


class OpsError(RuntimeError):
    """An operator-facing failure with a message that is safe to print."""


class SamAuthError(OpsError):
    """The SAM CLI has no valid login for the target."""


# --------------------------------------------------------------------------- env


def _expand(value: str, scope: Mapping[str, str]) -> str:
    return _VAR_REF.sub(lambda m: scope.get(m.group(1) or m.group(2), ""), value)


def _dotenv_value(raw: str, scope: Mapping[str, str]) -> str:
    raw = raw.strip()
    if raw[:1] in ("'", '"'):
        quote = raw[0]
        end = raw.find(quote, 1)
        inner = raw[1:end] if end > 0 else raw[1:]
        return inner if quote == "'" else _expand(inner, scope)
    raw = re.split(r"\s+#", raw, maxsplit=1)[0].strip()
    return _expand(raw, scope)


def parse_dotenv(path: Path, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Read KEY=VALUE lines the way `set -a; . file` sees this demo's files:
    comment lines, inline ' # comments', optional quotes, $VAR / ${VAR}
    expansion against the process environment and earlier keys."""
    scope: dict[str, str] = dict(os.environ if base is None else base)
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _DOTENV_LINE.match(stripped)
        if not match:
            continue
        key, value = match.group(1), _dotenv_value(match.group(2), scope)
        values[key] = value
        scope[key] = value
    return values


def current_target(environ: Mapping[str, str] | None = None) -> str:
    """TARGET of the process environment (or of ``environ``): lab (default) or aks."""
    raw = (os.environ if environ is None else environ).get("TARGET", "")
    value = raw or "lab"
    if value not in TARGETS:
        raise OpsError(f"TARGET={raw!r}: expected lab or aks")
    return value


def target_of(env: Mapping[str, str]) -> str:
    """TARGET of an env mapping from :func:`demo_env`; a mapping without TARGET
    takes the one of the process (never silently lab while the process is aks)."""
    return current_target({"TARGET": env.get("TARGET") or os.environ.get("TARGET", "")})


def check_aks_env(env: Mapping[str, str]) -> None:
    """Refusals and lab-URL guard of TARGET=aks (fail closed, before anything runs):
    no amd/lab secret variable in the environment, every URL-ish value set (their
    code defaults are lab values), none of them lab-like, https for SAM and the BFF,
    no lab CA or lab image, the AKS kubeconfig and context set, the namespaces and
    pod of runbook 1.4, and a SAM_HOME of its own (never the lab login cache). The
    same checks as aks_env_check in scripts/lib.sh. Messages name keys only."""
    errors = [f"{key} is set (aks never uses the lab or amd env; fresh shell, "
              "aks.sh sourced)" for key in AKS_REFUSED_ENV if key in env]
    for key in AKS_URL_KEYS:
        value = env.get(key, "")
        if not value:
            errors.append(f"{key} missing in {AKS_ENV_FILE}")
            continue
        hits = [m for m in LAB_URL_MARKERS if m in value.lower()]
        if hits:
            errors.append(f"{key} points to the lab ({hits[0]})")
    for key in AKS_HTTPS_KEYS:
        if env.get(key) and not env[key].startswith("https://"):
            errors.append(f"{key} must be https://")
    if "lab-ca" in env.get("E2E_CA_FILE", ""):
        errors.append("E2E_CA_FILE is the lab CA")
    errors += [f"{key} missing in {AKS_ENV_FILE}" for key in ("AKS_KUBECONFIG", "KUBE_CONTEXT")
               if not env.get(key)]
    if env.get("PG_MODE") != "kubectl":
        errors.append("PG_MODE must be kubectl")
    # the only namespaces and pod this demo creates, uses and deletes on AKS (runbook 1.4)
    if (env.get("GPOS_NS") or NS_DEFAULT) != NS_DEFAULT:
        errors.append(f"GPOS_NS must be {NS_DEFAULT}")
    for key, value in (("PG_NS", "gpos-data"), ("PG_POD", "gpos-postgres-0")):
        if env.get(key) != value:
            errors.append(f"{key} must be {value}")
    home = env.get("SAM_HOME", "")
    if not home:
        errors.append(f"SAM_HOME missing in {AKS_ENV_FILE} (own sam login cache for AKS)")
    elif not Path(os.path.expanduser(home)).is_absolute():
        errors.append("SAM_HOME must be an absolute path")
    elif Path(os.path.expanduser(home)).resolve() == Path.home().resolve():
        errors.append("SAM_HOME is the real HOME (the sam CLI would use the lab login cache)")
    elif Path(os.path.expanduser(home)).resolve() == LAB_SAM_HOME.resolve():
        errors.append("SAM_HOME is the lab sam home (AKS needs its own login cache)")
    if "solace.lab" in env.get("GPOS_IMAGE", ""):
        errors.append("GPOS_IMAGE is a lab image")
    if errors:
        raise OpsError("TARGET=aks refused: " + "; ".join(errors))


def demo_env(env_file: Path | None = None) -> dict[str, str]:
    """The demo's .env overlaid by the process environment (which wins, so an
    operator or a test can override single keys).

    TARGET=aks: ``.env.aks`` instead (``env_file`` may name another file, never
    one called ``.env``), then :func:`check_aks_env` on the merged result; the
    optional ZeroSSL key ACME_EAB_HMAC of ``.env.aks`` is dropped (only aks.sh's
    zerossl_on uses it).

    The lab refuses to run inside aks_sam/aks_kc of infra/aks/aks.sh (SAM_ENV_FILE
    set, KUBECONFIG = the AKS file), like scripts/lib.sh."""
    target = current_target()
    if target == "lab":
        if "SAM_ENV_FILE" in os.environ:
            raise OpsError("TARGET=lab inside an AKS subshell (SAM_ENV_FILE is set, "
                           "aks_sam/aks_kc): run TARGET=aks scripts/... in a plain shell")
        path = env_file if env_file is not None else DEMO_DIR / ".env"
        merged = parse_dotenv(path) if path.is_file() else {}
        merged.update(os.environ)
        return merged
    if target != TARGET:
        raise OpsError(f"TARGET={target} but this process started with TARGET={TARGET}")
    path = env_file if env_file is not None else DEMO_DIR / AKS_ENV_FILE
    if path.name == ".env":
        raise OpsError(f"TARGET=aks never reads {path} (only {AKS_ENV_FILE})")
    if not path.is_file():
        raise OpsError(f"TARGET=aks: {path} missing (template infra/aks/env.aks.example, "
                       "runbook 1.3)")
    merged = parse_dotenv(path)
    merged.update(os.environ)
    merged.pop("ACME_EAB_HMAC", None)
    merged["TARGET"] = target
    check_aks_env(merged)
    return merged


def demo_path(value: str) -> Path:
    """A path from .env: absolute as given, relative to the demo root otherwise."""
    path = Path(os.path.expanduser(value))
    return path if path.is_absolute() else (DEMO_DIR / path).resolve()


def _az_reason(stderr: str) -> str:
    """A short cause of a failed `az keyvault secret show`; az's own text is never
    passed on (it could quote anything)."""
    text = stderr.lower()
    for needle, reason in (("secretnotfound", "secret not found"),
                           ("vaultnotfound", "vault not found (AKS_KV?)"),
                           ("failed to resolve", "vault not found (AKS_KV?)"),
                           ("az login", "not logged in (az login)"),
                           ("aadsts", "not logged in (az login)"),
                           ("forbidden", "no access (Key Vault access policy)"),
                           ("not found", "not found")):
        if needle in text:
            return reason
    return "unknown; rerun the az command by hand with -o none"


def kv_secret(env: Mapping[str, str], name: str) -> str:
    """Value of the Key Vault secret ``name`` (vault AKS_KV), for pipes and child
    processes only: captured from `az keyvault secret show ... -o tsv`, never
    printed, never in argv, never in an exception message (az's output neither)."""
    vault = env.get("AKS_KV", "")
    if not vault:
        raise OpsError(f"Key Vault secret {name}: AKS_KV not set in {AKS_ENV_FILE}")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,127}", name):
        raise OpsError(f"Key Vault secret name {name!r} is invalid")
    cmd = ["az", "keyvault", "secret", "show", "--vault-name", vault, "-n", name,
           "--query", "value", "-o", "tsv"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False,
                              stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise OpsError("az CLI not found (needed for Key Vault secrets on aks)") from None
    except subprocess.TimeoutExpired:
        raise OpsError(f"Key Vault secret {name}: az timed out") from None
    if proc.returncode != 0:
        raise OpsError(f"Key Vault secret {name}: az rc {proc.returncode} "
                       f"({_az_reason(proc.stderr)})")
    value = proc.stdout.rstrip("\r\n")
    if not value:
        raise OpsError(f"Key Vault secret {name}: empty")
    return value


def broker_credentials(env: Mapping[str, str]) -> tuple[str, str]:
    """BROKER_USERNAME/BROKER_PASSWORD when both are set, else
    MQTT_USERNAME/MQTT_PASSWORD from BROKER_CREDENTIALS_FROM (spec 9.6).

    TARGET=aks: BROKER_USERNAME and the Key Vault secret BROKER_PASSWORD_KV only
    (no BROKER_PASSWORD, no credentials file)."""
    if target_of(env) == "aks":
        user, key = env.get("BROKER_USERNAME", ""), env.get("BROKER_PASSWORD_KV", "")
        if not (user and key):
            raise OpsError(f"broker credentials: BROKER_USERNAME and BROKER_PASSWORD_KV must "
                           f"be set in {AKS_ENV_FILE}")
        return user, kv_secret(env, key)
    user, password = env.get("BROKER_USERNAME", ""), env.get("BROKER_PASSWORD", "")
    if user and password:
        return user, password
    source = demo_path(env.get("BROKER_CREDENTIALS_FROM", BROKER_CREDENTIALS_DEFAULT))
    if not source.is_file():
        raise OpsError(f"broker credentials: {source} missing (BROKER_CREDENTIALS_FROM)")
    creds = parse_dotenv(source, base={})
    user, password = creds.get("MQTT_USERNAME", ""), creds.get("MQTT_PASSWORD", "")
    if not (user and password):
        raise OpsError(f"broker credentials: MQTT_USERNAME/MQTT_PASSWORD not set in {source}")
    return user, password


def location_parts(location: str) -> tuple[str, str, str, str]:
    """Root.DE.999.101.01 -> ("DE", "999", "101", "01")."""
    parts = location.split(".")
    if len(parts) != 5 or parts[0] != "Root" or not all(parts[1:]):
        raise OpsError(f"invalid location {location!r} (expected Root.<country>.<company>."
                       "<store>.<till>)")
    return parts[1], parts[2], parts[3], parts[4]


def write_private(path: Path, text: str) -> None:
    """Write a file readable only by the owner (chmod 600, directory 700)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(path, 0o600)


# ------------------------------------------------------------------- gate hash


def gate_hash(root: Path = DEMO_DIR, fallback_f2: bool = False) -> str:
    """sha256 over path and content of every file the gate verification
    covers (mesh/connectors, mesh/agents, mesh/workflows; with F2 also
    mesh/fallback)."""
    digest = hashlib.sha256()
    dirs = GATE_HASH_DIRS + (GATE_HASH_DIRS_F2 if fallback_f2 else ())
    for rel in dirs:
        for path in sorted(p for p in (root / rel).rglob("*") if p.is_file()):
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def gate_verified(root: Path = DEMO_DIR, fallback_f2: bool = False,
                  target: str | None = None) -> bool:
    """True when build/gate-verified records PASS for the current hash and for the runs
    of :data:`GATE_MODES` (A9 deny x5 and A10 timeout x2 included, so a record of an
    older, shorter verification never lets the booth entrypoint through).

    Per target: the lab reads build/gate-verified, aks build/aks/gate-verified, whose
    record must also name ``target=aks`` (a lab PASS never counts for AKS)."""
    target = target or (TARGET if TARGET in TARGETS else "aks")
    path = root / target_dirs(target)[1].relative_to(DEMO_DIR) / "gate-verified"
    if not path.is_file():
        return False
    fields = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
    if target != "lab" and fields.get("target") != target:
        return False
    return (fields.get("result") == "PASS" and fields.get("modes") == GATE_MODES_TEXT
            and fields.get("hash") == gate_hash(root, fallback_f2))


# --------------------------------------------------------------------- SAM CLI


def resolve_sam_cli(env: Mapping[str, str]) -> str:
    """SAM_CLI_PATH from .env, else `sam` on the PATH (like common.sh)."""
    for candidate in (env.get("SAM_CLI", ""), env.get("SAM_CLI_PATH", "")):
        if candidate and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which("sam")
    if not found:
        raise OpsError("sam CLI not found: set SAM_CLI_PATH in .env or put sam on the PATH")
    return found


def _json_from_cli(stdout: str) -> Any:
    text = stdout.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except ValueError:
        start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
        if start < 0:
            raise
        return json.loads(text[start:])


def sam_cli_seam(env: Mapping[str, str]) -> tuple[list[str], str | None, str]:
    """(extra argv, SAM_HOME for the child, login hint) of the SAM CLI for the target.

    lab: nothing extra, the inherited environment (as before). aks: ``--url
    SAM_URL`` (it overrides the manifest's URL; the token is still looked up under
    the manifest's target name), ``SAM_HOME`` of the demo env (own login cache)
    and no SAM_AUTH_TOKEN/SAM_PLATFORM_TOKEN inherited from the shell (a lab token
    must never go to the public name). ``--no-dotenv`` belongs to `sam config`
    only; `sam api` refuses it (2.542.1: "unknown flag: --no-dotenv")."""
    if target_of(env) == "lab":
        return [], None, SAM_LOGIN_HINT_LAB
    url, home = env.get("SAM_URL", ""), env.get("SAM_HOME", "")
    if not (url and home):
        raise OpsError(f"SAM_URL and SAM_HOME must be set in {AKS_ENV_FILE}")
    hint = f"aks_sam sam auth login solace-lab --url {url}"
    return ["--url", url], os.path.expanduser(home), hint


def sam_child_env(sam_home: str | None) -> dict[str, str] | None:
    """Environment of one SAM CLI call: inherited unchanged without ``sam_home`` (lab),
    else the process environment with HOME and SAM_HOME set to ``sam_home`` and
    without the shell's tokens. sam 2.542.1 keeps its OAuth login cache under
    ``$HOME/Library/Application Support/sam/auth`` and ignores SAM_HOME for it, so
    only HOME separates the AKS login from the lab login."""
    if sam_home is None:
        return None
    child = {k: v for k, v in os.environ.items() if k not in SAM_TOKEN_ENV}
    child["HOME"] = sam_home
    child["SAM_HOME"] = sam_home
    return child


class SamApi:
    """`sam api` as a subprocess. The CLI authenticates from its own login cache
    through the oauth target of mesh/manifest.yaml (or SAM_AUTH_TOKEN when the
    caller exported it); no token passes through this process's arguments or
    output. An explicit ``target`` addresses a cache entry by name instead.
    TARGET=aks adds ``--url SAM_URL`` and the AKS SAM_HOME (:func:`sam_cli_seam`)."""

    def __init__(self, env: Mapping[str, str], target: str | None = None, timeout: float = 30):
        self.cli = resolve_sam_cli(env)
        self.target = target or env.get("SAM_TARGET", "")
        self.timeout = timeout
        self.url_args, self.sam_home, self.login_hint = sam_cli_seam(env)
        # aks also treats the 2.542.1 wording "no cached OAuth credentials" as a missing
        # login (refresh, retry, then the aks_sam login hint); the lab keeps its pattern
        # (lab behaviour unchanged: that answer stays one call and an OpsError)
        self.auth_pattern = (SAM_AUTH_PATTERN_LAB if self.sam_home is None
                             else SAM_AUTH_PATTERN_AKS)

    def refresh(self) -> None:
        """A read-only CLI call refreshes the OAuth login cache (BSG pattern)."""
        subprocess.run([self.cli, "config", "plan", "--no-dotenv", "--no-interactive",
                        *self.url_args],
                       cwd=DEMO_DIR / "mesh", capture_output=True, text=True,
                       timeout=60, check=False, env=sam_child_env(self.sam_home))

    def call(self, method: str, path: str, body: Any = None) -> Any:
        try:
            return self._call(method, path, body)
        except SamAuthError:
            self.refresh()
            return self._call(method, path, body)

    def _call(self, method: str, path: str, body: Any = None) -> Any:
        where = ["--target", self.target] if self.target else ["--manifest", str(SAM_MANIFEST)]
        cmd = [self.cli, "api", "-X", method, path, *where, *self.url_args]
        payload = None
        if body is not None:
            cmd += ["--input", "-"]
            payload = json.dumps(body, ensure_ascii=False)
        proc = subprocess.run(cmd, input=payload, capture_output=True, text=True,
                              timeout=self.timeout, check=False,
                              env=sam_child_env(self.sam_home))
        blob = f"{proc.stdout}\n{proc.stderr}"
        if re.search(self.auth_pattern, blob):
            raise SamAuthError(f"SAM login missing or expired: {self.login_hint}")
        if proc.returncode != 0:
            detail = " ".join(proc.stderr.split())[-240:]
            raise OpsError(f"sam api {method} {path.split('?')[0]} failed: {detail}")
        try:
            return _json_from_cli(proc.stdout)
        except ValueError as exc:
            raise OpsError(f"sam api {method} {path.split('?')[0]}: no JSON in the answer") from exc

    def list_all(self, path: str) -> list[dict]:
        """GET a v2 list endpoint page by page (pageSize 100)."""
        items: list[dict] = []
        page = 1
        sep = "&" if "?" in path else "?"
        while True:
            body = self.call("GET", f"{path}{sep}pageSize=100&pageNumber={page}")
            data = body.get("data", []) if isinstance(body, dict) else body
            items.extend(data or [])
            if not data or len(data) < 100:
                return items
            page += 1

    def find_by_name(self, path: str, name: str) -> dict | None:
        return next((x for x in self.list_all(path) if x.get("name") == name), None)


# ----------------------------------------------------------------------- inbox


@dataclass(frozen=True)
class InboxItem:
    """One SAM notify inbox entry, reduced to what the gpos tools need."""

    id: str
    created_at: str
    prompt_state: str
    ref: str | None
    agent: str | None


def _info_text(raw: Mapping[str, Any]) -> str:
    surface = raw.get("surface") or {}
    for comp in surface.get("components", []) if isinstance(surface, dict) else []:
        if isinstance(comp, dict) and comp.get("id") == "info":
            text = comp.get("text") or {}
            return str(text.get("literalString") or "") if isinstance(text, dict) else str(text)
    return ""


def parse_item(raw: Mapping[str, Any]) -> InboxItem:
    blob = json.dumps(raw, ensure_ascii=False)
    ref_match = REF_RE.search(blob)
    info = _info_text(raw)
    agent = next((a for a in sorted(APPROVER_AGENTS, key=len, reverse=True)
                  if f'Agent "{a}"' in info or f'Agent \\"{a}\\"' in blob), None)
    return InboxItem(id=str(raw.get("id", "")), created_at=str(raw.get("createdAt", "")),
                     prompt_state=str(raw.get("promptState", "")),
                     ref=ref_match.group(1) if ref_match else None, agent=agent)


def is_gpos(item: InboxItem) -> bool:
    """A gpos approval: the rendered approval message names `Ref GP-...`, or
    (fallback A-6) the A2UI info names one of our approver agents."""
    return item.ref is not None or item.agent is not None


class Inbox:
    """hil entries of the run identity, via the notify REST API (G0-02 T6/T8)."""

    def __init__(self, api: SamApi, user: str = RUN_IDENTITY_DEFAULT):
        self.api = api
        self.user = user

    def items(self) -> list[InboxItem]:
        body = self.api.call("GET", f"/api/v1/notify/inbox?userId={self.user}&category=hil"
                                    "&pageSize=100")
        data = body.get("data") if isinstance(body, dict) else body
        if isinstance(data, dict):
            data = data.get("items")
        return [parse_item(raw) for raw in (data or []) if isinstance(raw, dict)]

    def pending_gpos(self) -> list[InboxItem]:
        return sorted((i for i in self.items() if i.prompt_state == "pending" and is_gpos(i)),
                      key=lambda i: i.created_at)

    def respond(self, item_id: str, approved: bool | None) -> None:
        """approved True/False answers the request, None cancels it."""
        if approved is None:
            body: dict[str, Any] = {"status": "cancelled", "data": {}}
        else:
            body = {"status": "answered", "data": {"approved": approved}}
        result = self.api.call("POST", f"/api/v1/notify/inbox/{item_id}/respond"
                                       f"?userId={self.user}", body)
        if isinstance(result, dict) and result.get("errorType"):
            raise OpsError(f"inbox respond {item_id}: {result.get('errorType')}")


@dataclass(frozen=True)
class Decision:
    """What the inbox watcher does with one open request."""

    item_id: str
    ref: str | None
    action: str          # keep | approve | cancel
    reason: str


def decide(pending: list[InboxItem], proposals: Mapping[str, dict | None],
           first_by_ref: dict[str, str]) -> list[Decision]:
    """Watcher rules (spec 12.6), pure so e2e and watch share them.

    pending       open gpos requests, oldest first
    proposals     ref -> proposal JSON from BFF GET /api/proposals/{id}, None when
                  the proposal is unknown (404); a ref missing from the mapping
                  could not be read and is left alone this round
    first_by_ref  ref -> id of the first request seen for that ref; updated here

    - proposal pending: the first request of the ref stays for the store
      manager, every further one is a duplicate request -> cancel (no price yet)
    - proposal approved (price active): every request -> approve, the gate
      answers already_applied and the monitor shows the duplicate banner
    - any other state, or unknown proposal: orphaned request -> cancel
    """
    decisions = []
    for item in pending:
        if item.ref is None or item.ref not in proposals:
            continue
        proposal = proposals[item.ref]
        state = str((proposal or {}).get("state") or (proposal or {}).get("status") or "")
        if proposal is None:
            decisions.append(Decision(item.id, item.ref, "cancel", "proposal unknown"))
        elif state == "approved":
            decisions.append(Decision(item.id, item.ref, "approve",
                                      "duplicate request, price already active"))
        elif state == "pending":
            first = first_by_ref.setdefault(item.ref, item.id)
            if first == item.id:
                decisions.append(Decision(item.id, item.ref, "keep", "first request"))
            else:
                decisions.append(Decision(item.id, item.ref, "cancel",
                                          "duplicate request, price not active"))
        else:
            decisions.append(Decision(item.id, item.ref, "cancel", f"proposal {state or '?'}"))
    return decisions


def with_ref(items: list[InboxItem], ref: str | None) -> list[InboxItem]:
    """Fallback A-6: give requests without `Ref GP-...` (approver agent named in
    the A2UI info only) the proposal they belong to, when the caller knows it."""
    if not ref:
        return items
    return [dataclasses.replace(i, ref=ref) if i.ref is None else i for i in items]


@contextlib.contextmanager
def exclusive_lock(holder: str, path: Path = LOCK_FILE) -> Iterator[None]:
    """build/sam_inbox.lock: `sam_inbox.py watch` and e2e.py never run together."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.seek(0)
            other = handle.read().strip() or "another process"
            raise OpsError(f"{path.name} is held by {other}; stop it first") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"{holder} pid={os.getpid()} since={time.strftime('%H:%M:%S')}\n")
        handle.flush()
        yield
    finally:
        handle.close()


# ------------------------------------------------------------------------- BFF


def system_trust() -> ssl.SSLContext | bool:
    """E2E_CA_FILE=system: the client's system trust store (macOS keychain through
    truststore when the .venv has it), else httpx's default public roots (certifi).
    Both trust Let's Encrypt; the python.org build has no OpenSSL cafile of its own."""
    try:
        import truststore  # noqa: PLC0415 -- optional
    except ImportError:
        return True
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


class Bff:
    """Read-only client of the BFF (spec 10.1) from the Mac: HTTPS with the lab
    root CA (E2E_CA_FILE, certifi-style file, not the keychain); with
    E2E_CA_FILE=system (AKS, public certificate) the system trust store."""

    def __init__(self, env: Mapping[str, str], timeout: float = 10):
        import httpx  # noqa: PLC0415 -- only the .venv has it

        base = env.get("E2E_BASE_URL", "https://gpos.solace.lab").rstrip("/")
        verify: bool | str | ssl.SSLContext = True
        if base.startswith("https://"):
            ca = env.get("E2E_CA_FILE", "build/lab-ca.crt")
            if ca == "system":
                verify = system_trust()
            else:
                ca_file = demo_path(ca)
                if not ca_file.is_file():
                    raise OpsError(f"{ca_file} missing: scripts/install.sh k8s exports the "
                                   "lab CA")
                verify = str(ca_file)
        self.base = base
        self.http = httpx.Client(base_url=base, verify=verify, timeout=timeout)

    def get(self, path: str) -> Any:
        response = self.http.get(path)
        response.raise_for_status()
        return response.json()

    def post(self, path: str, body: Any) -> tuple[int, Any]:
        response = self.http.post(path, json=body)
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {"raw": response.text[:200]}

    def proposal(self, proposal_id: str) -> dict | None:
        response = self.http.get(f"/api/proposals/{proposal_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def booth_proposal_id(self) -> str | None:
        """Open or last proposal of the booth till from GET /api/state."""
        proposal = (self.get("/api/state") or {}).get("proposal") or {}
        return proposal.get("proposal_id") if isinstance(proposal, dict) else None

    def close(self) -> None:
        self.http.close()


# --------------------------------------------------------------------- kubectl


def check_aks_kubeconfig(path: Path, context: str) -> None:
    """The context of the AKS kubeconfig points to the AKS API server (like aks_guard
    in infra/aks/aks.sh): never the lab cluster under an AKS name."""
    import yaml  # noqa: PLC0415 -- PyYAML, only needed on aks

    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise OpsError(f"{path}: not a readable kubeconfig") from exc
    ctx = next((c.get("context") or {} for c in config.get("contexts") or []
                if isinstance(c, dict) and c.get("name") == context), None)
    if ctx is None:
        raise OpsError(f"{path}: context {context} missing (KUBE_CONTEXT)")
    cluster = next((c.get("cluster") or {} for c in config.get("clusters") or []
                    if isinstance(c, dict) and c.get("name") == ctx.get("cluster")), {})
    if not fnmatch.fnmatchcase(str(cluster.get("server") or ""), AKS_API_SERVER):
        raise OpsError(f"{path}: the server of context {context} is not {AKS_API_SERVER}")


def kubectl_base(env: Mapping[str, str]) -> list[str]:
    """argv prefix of every kubectl call: lab plain `kubectl` (current context, as
    before); aks `kubectl --kubeconfig AKS_KUBECONFIG --context KUBE_CONTEXT`, only
    when that file exists and its context is the AKS API server."""
    if target_of(env) == "lab":
        return ["kubectl"]
    kubeconfig, context = env.get("AKS_KUBECONFIG", ""), env.get("KUBE_CONTEXT", "")
    if not (kubeconfig and context):
        raise OpsError(f"AKS_KUBECONFIG and KUBE_CONTEXT must be set in {AKS_ENV_FILE}")
    path = Path(os.path.expanduser(kubeconfig))
    if not path.is_file():
        raise OpsError(f"{path} missing (admin kubeconfig, runbook A4)")
    check_aks_kubeconfig(path, context)
    return ["kubectl", "--kubeconfig", str(path), "--context", context]


def kubectl_ui(env: Mapping[str, str], args: list[str], stdin: str | None = None,
               timeout: float = 60) -> subprocess.CompletedProcess[str]:
    """Run `python ...` inside deploy/gpos-ui (cluster DNS, broker Secret)."""
    ns = env.get("GPOS_NS", NS_DEFAULT)
    cmd = kubectl_base(env) + ["-n", ns, "exec"] + (["-i"] if stdin is not None else [])
    cmd += ["deploy/gpos-ui", "--", "python"] + args
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True,
                          timeout=timeout, check=False)
