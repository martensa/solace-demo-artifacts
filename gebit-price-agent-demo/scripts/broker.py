#!/usr/bin/env python3
"""Broker side of the gpos demo on solace-1 via SEMP v2 (spec 9.6, hard rule 4).

  broker.py r1-create            converge queue gpos-booth-r1 (never delete + create)
  broker.py r1-show              counters and txFlows (preflight: exactly one flow)
  broker.py r1-switch OLD NEW    after an R1_MODE switch: sam->own deletes the SAM
                                 queue of rule r1_booth_till, own->sam removes the
                                 subscriptions of gpos-booth-r1
  broker.py r1-delete            delete gpos-booth-r1 (uninstall only)
  broker.py orphans              queues under sam-solace-lab/q/eventmesh/ with 0 txFlows
  broker.py txflows QUEUE        number of txFlows of one queue
  broker.py ready ENTRYPOINT     readiness after an apply (spec 9.8 step 4.5): platform
                                 status deployed/running, last deployment success,
                                 exactly one txFlow per rule queue (up to --timeout s)

The SEMP admin password is read at runtime from SEMP_PASSWORD_FROM (the
event-mesh terraform.tfvars, key solace_1_password) and never printed; it only
goes into the Authorization header of this process.

TARGET=aks (AKS-MIGRATION-PLAN 1.4, A18): the password is the Key Vault secret
SEMP_PASSWORD_KV (no tfvars fallback), SEMP_URL is a local port-forward
(http://127.0.0.1:18080). Before the first SEMP call the port is probed: a
listener there must answer SEMP v2 /monitor/about/api with the AKS admin password
and must not have the lab-only VPN amartens-test ("Lab-Broker": abort); an open
forward is reused, otherwise this process opens `kubectl port-forward -n solace
svc/solace-pubsubplus 18080:8080` with the AKS kubeconfig and context itself and
closes it at exit.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import http.client
import json
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opslib import OpsError, SamApi, demo_env, demo_path, kubectl_base, kv_secret, target_of
from render_mesh import RULES, r1_mode, r1_topics

LAB_ONLY_VPN = "amartens-test"
AKS_SEMP_HOST = "127.0.0.1"
AKS_BROKER = ("solace", "svc/solace-pubsubplus", 8080)     # namespace, service, SEMP port
FORWARD_WAIT_S = 20.0
SAM_QUEUE_PREFIX_DEFAULT = "sam-solace-lab/q/eventmesh/"
BOOTH_ENTRYPOINT = "gpos-booth-events"
R1_RULE = "r1_booth_till"
R1_ATTRIBUTES: dict[str, Any] = {
    "accessType": "exclusive",
    "permission": "consume",
    "respectTtlEnabled": True,
    "maxTtl": 20,
    "maxRedeliveryCount": 1,
    "maxMsgSpoolUsage": 50,
    "ingressEnabled": True,
    "egressEnabled": True,
}
EXIT_FINDING = 3


def read_semp_password(path: Path, key: str) -> str:
    if not path.is_file():
        raise OpsError(f"SEMP password file {path} missing (SEMP_PASSWORD_FROM)")
    pattern = re.compile(rf'^\s*{re.escape(key)}\s*=\s*"?([^"\n]*)"?\s*$')
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match and match.group(1):
            return match.group(1)
    raise OpsError(f"{key} not found in {path}")


def quote(name: str) -> str:
    return urllib.parse.quote(name, safe="")


@dataclass
class Semp:
    """Minimal SEMP v2 client (config and monitor API)."""

    base: str
    vpn: str
    auth: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Semp:
        if target_of(env) == "aks":
            key, url = env.get("SEMP_PASSWORD_KV", ""), env.get("SEMP_URL", "")
            if not (key and url):
                raise OpsError("TARGET=aks: SEMP_PASSWORD_KV and SEMP_URL must be set in "
                               ".env.aks (no tfvars fallback)")
            password = kv_secret(env, key)
        else:
            password = read_semp_password(
                demo_path(env.get("SEMP_PASSWORD_FROM",
                                  "../event-mesh-deployment/terraform/terraform.tfvars")),
                env.get("SEMP_PASSWORD_KEY", "solace_1_password"))
        token = base64.b64encode(f"{env.get('SEMP_USER', 'admin')}:{password}".encode()).decode()
        return cls(env.get("SEMP_URL", "http://localhost:8080").rstrip("/"),
                   env.get("BROKER_VPN", "default"), f"Basic {token}")

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, dict]:
        url = path if path.startswith("http") else f"{self.base}/SEMP/v2/{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Authorization": self.auth,
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read() or b"{}")
            except ValueError:
                return exc.code, {}
        except urllib.error.URLError as exc:
            raise OpsError(f"SEMP {self.base} unreachable: {exc.reason}") from exc

    def ok(self, method: str, path: str, body: Any = None) -> dict:
        code, data = self.request(method, path, body)
        if code >= 300:
            err = (data.get("meta") or {}).get("error") or {}
            raise OpsError(f"SEMP {method} {path.split('?')[0]} -> {code} "
                           f"{err.get('status', '')} {err.get('description', '')}".rstrip())
        return data

    def queue_path(self, api: str, queue: str) -> str:
        return f"{api}/msgVpns/{quote(self.vpn)}/queues/{quote(queue)}"

    @staticmethod
    def not_found(code: int, data: dict) -> bool:
        return code == 404 or (code == 400 and "NOT_FOUND" in json.dumps(data))

    def get_queue(self, queue: str) -> dict | None:
        code, data = self.request("GET", self.queue_path("config", queue))
        if self.not_found(code, data):
            return None
        if code >= 300:
            raise OpsError(f"SEMP GET queue {queue} -> {code}")
        return data.get("data") or {}

    def collection(self, path: str) -> list[dict]:
        items: list[dict] = []
        while path:
            data = self.ok("GET", path)
            items.extend(data.get("data") or [])
            path = ((data.get("meta") or {}).get("paging") or {}).get("nextPageUri", "")
        return items

    def subscriptions(self, queue: str) -> list[str]:
        rows = self.collection(f"{self.queue_path('config', queue)}/subscriptions?count=100")
        return [r["subscriptionTopic"] for r in rows]

    def txflows(self, queue: str) -> list[dict]:
        """txFlows of a queue; [] when the queue does not exist (yet)."""
        path = f"{self.queue_path('monitor', queue)}/txFlows?count=100"
        code, data = self.request("GET", path)
        if self.not_found(code, data):
            return []
        if code >= 300:
            raise OpsError(f"SEMP GET txFlows {queue} -> {code}")
        flows = list(data.get("data") or [])
        next_uri = ((data.get("meta") or {}).get("paging") or {}).get("nextPageUri", "")
        return flows + (self.collection(next_uri) if next_uri else [])


# -------------------------------------------------------------- AKS preflight


def aks_semp_port(url: str) -> int:
    """Local port of SEMP_URL on aks: only http://127.0.0.1:<port> (a port-forward;
    the lab broker owns the Mac's 8080)."""
    parts = urllib.parse.urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        port = None
    if parts.scheme != "http" or parts.hostname != AKS_SEMP_HOST or not port:
        raise OpsError(f"TARGET=aks: SEMP_URL must be http://{AKS_SEMP_HOST}:<port> "
                       "(port-forward to the AKS broker, runbook A13)")
    return port


def listening(port: int, timeout: float = 1.0) -> bool:
    """Something accepts TCP connections on 127.0.0.1:port."""
    try:
        with socket.create_connection((AKS_SEMP_HOST, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_broker_identity(semp: Semp) -> str:
    """The broker behind the forward speaks SEMP v2, accepts the AKS admin password
    and is not the lab broker (VPN amartens-test exists only there). Returns the
    sempVersion of /monitor/about/api (the SEMP API version, not the broker's)."""
    try:
        code, data = semp.request("GET", "monitor/about/api")
        about = data.get("data") if isinstance(data, dict) else None
        if code in (401, 403):
            raise OpsError(f"SEMP {semp.base} rejects the AKS admin password (Key Vault "
                           "SEMP_PASSWORD_KV): another broker listens there (Lab-Broker?); "
                           "close that port-forward")
        if code != 200 or not isinstance(about, dict) or "sempVersion" not in about:
            raise OpsError(f"SEMP {semp.base}: /monitor/about/api answered {code}, "
                           "not a SEMP v2 broker")
        vpns = {str(row.get("msgVpnName")) for row in
                semp.collection("config/msgVpns?count=100&select=msgVpnName")}
    except (ValueError, OSError, http.client.HTTPException) as exc:
        # HTTPException: a listener that is not HTTP at all (e.g. BadStatusLine)
        raise OpsError(f"SEMP {semp.base}: no SEMP v2 answer ({type(exc).__name__})") from exc
    if LAB_ONLY_VPN in vpns:
        raise OpsError(f"SEMP {semp.base} has VPN {LAB_ONLY_VPN}: that is the Lab-Broker, "
                       "abort (close the port-forward on this port)")
    print(f"SEMP {semp.base}: AKS broker, SEMP API {about['sempVersion']}, VPNs "
          f"{', '.join(sorted(vpns))}", file=sys.stderr)
    return str(about["sempVersion"])


@contextlib.contextmanager
def port_forward(env: Mapping[str, str], port: int) -> Iterator[None]:
    """`kubectl port-forward -n solace svc/solace-pubsubplus PORT:8080` with the AKS
    kubeconfig and context, until the block ends (closed on every exit path)."""
    ns, svc, remote = AKS_BROKER
    cmd = kubectl_base(env) + ["-n", ns, "port-forward", "--address", AKS_SEMP_HOST, svc,
                               f"{port}:{remote}"]
    with tempfile.TemporaryFile() as errlog:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=errlog)
        try:
            deadline = time.monotonic() + FORWARD_WAIT_S
            while not listening(port, 0.5):
                if proc.poll() is not None or time.monotonic() >= deadline:
                    errlog.seek(0)
                    detail = " ".join(errlog.read().decode(errors="replace").split())[-240:]
                    raise OpsError(f"kubectl port-forward {ns}/{svc} {port}:{remote} failed: "
                                   f"{detail or f'no listener after {FORWARD_WAIT_S:.0f} s'}")
                time.sleep(0.2)
            print(f"SEMP: port-forward {AKS_SEMP_HOST}:{port} -> {ns}/{svc}:{remote} opened "
                  "(closed at exit)", file=sys.stderr)
            yield
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


@contextlib.contextmanager
def semp_session(env: Mapping[str, str]) -> Iterator[Semp]:
    """The SEMP client of the target. lab: as before, no probe. aks: an open forward
    on SEMP_URL is reused, otherwise opened here; the identity check runs before the
    caller's first SEMP call; the password comes from the Key Vault."""
    if target_of(env) != "aks":
        yield Semp.from_env(env)
        return
    port = aks_semp_port(env.get("SEMP_URL", ""))
    with contextlib.ExitStack() as stack:
        if not listening(port):
            stack.enter_context(port_forward(env, port))
        semp = Semp.from_env(env)
        check_broker_identity(semp)
        yield semp


def converge_r1(semp: Semp, queue: str, topics: list[str]) -> list[str]:
    """Create the queue or patch its attributes and subscriptions to the target
    state; returns the actions taken (never deletes the queue)."""
    actions = []
    current = semp.get_queue(queue)
    if current is None:
        semp.ok("POST", f"config/msgVpns/{quote(semp.vpn)}/queues",
                {"queueName": queue, **R1_ATTRIBUTES})
        actions.append(f"created queue {queue}")
    else:
        drift = {k: v for k, v in R1_ATTRIBUTES.items() if current.get(k) != v}
        if drift:
            semp.ok("PATCH", semp.queue_path("config", queue), drift)
            actions.append(f"patched {', '.join(sorted(drift))}")
    have = set(semp.subscriptions(queue))
    for topic in topics:
        if topic not in have:
            semp.ok("POST", f"{semp.queue_path('config', queue)}/subscriptions",
                    {"subscriptionTopic": topic})
            actions.append(f"+ {topic}")
    for topic in sorted(have - set(topics)):
        semp.ok("DELETE", f"{semp.queue_path('config', queue)}/subscriptions/{quote(topic)}")
        actions.append(f"- {topic}")
    return actions


def booth_entrypoint_id(env: Mapping[str, str]) -> str:
    entry = SamApi(env).find_by_name("/api/v2/platform/entrypoints", BOOTH_ENTRYPOINT)
    if not entry:
        raise OpsError(f"entrypoint {BOOTH_ENTRYPOINT} not on the platform")
    return str(entry["id"])


def cmd_r1_create(semp: Semp, env: Mapping[str, str], queue: str) -> int:
    actions = converge_r1(semp, queue, r1_topics(env))
    print(f"queue {queue} on VPN {semp.vpn}: " + ("; ".join(actions) or "already converged"))
    return 0


def cmd_r1_show(semp: Semp, queue: str) -> int:
    code, data = semp.request("GET", semp.queue_path("monitor", queue))
    if code >= 300:
        print(f"queue {queue}: not present on VPN {semp.vpn}")
        return EXIT_FINDING
    q = data.get("data") or {}
    keys = ("accessType", "permission", "respectTtlEnabled", "maxTtl", "maxRedeliveryCount",
            "maxMsgSpoolUsage", "ingressEnabled", "egressEnabled", "spooledMsgCount",
            "maxTtlExpiredDiscardedMsgCount", "maxTtlExpiredToDmqMsgCount",
            "maxRedeliveryExceededDiscardedMsgCount", "redeliveredMsgCount")
    print(json.dumps({"queue": queue, **{k: q.get(k) for k in keys}}))
    print("subscriptions: " + ", ".join(semp.subscriptions(queue)))
    flows = semp.txflows(queue)
    print(f"txFlows: {len(flows)} " + ", ".join(str(f.get("clientName")) for f in flows))
    return 0 if len(flows) == 1 else EXIT_FINDING


def cmd_r1_switch(semp: Semp, env: Mapping[str, str], queue: str, old: str, new: str,
                  prefix: str) -> int:
    if {old, new} != {"own", "sam"}:
        raise OpsError("r1-switch needs OLD and NEW out of own|sam, different")
    if new == "own":
        sam_queue = f"{prefix}{booth_entrypoint_id(env)}/{R1_RULE}"
        if semp.get_queue(sam_queue) is None:
            print(f"SAM queue {sam_queue}: already gone")
        else:
            semp.ok("DELETE", semp.queue_path("config", sam_queue))
            print(f"deleted SAM queue {sam_queue} (finding 21)")
    else:
        if semp.get_queue(queue) is None:
            print(f"queue {queue}: not present, nothing to unsubscribe")
            return 0
        for topic in semp.subscriptions(queue):
            semp.ok("DELETE", f"{semp.queue_path('config', queue)}/subscriptions/{quote(topic)}")
            print(f"- {topic}")
        print(f"queue {queue}: no subscriptions left (R1 now on the SAM queue)")
    return 0


def cmd_r1_delete(semp: Semp, queue: str) -> int:
    if semp.get_queue(queue) is None:
        print(f"queue {queue}: not present")
        return 0
    semp.ok("DELETE", semp.queue_path("config", queue))
    print(f"queue {queue}: deleted")
    return 0


def cmd_orphans(semp: Semp, prefix: str) -> int:
    where = urllib.parse.quote(f"queueName=={prefix}*", safe="=*")
    queues = semp.collection(f"monitor/msgVpns/{quote(semp.vpn)}/queues?count=100"
                             f"&select=queueName&where={where}")
    orphans = [q["queueName"] for q in queues if not semp.txflows(q["queueName"])]
    print(f"queues under {prefix}: {len(queues)}, without txFlows: {len(orphans)}")
    for name in orphans:
        print(f"  ORPHAN {name}")
    if orphans:
        print("  -> hard rule 4: delete with care (only queues of removed gpos rules)")
    return EXIT_FINDING if orphans else 0


def rule_queues(entrypoint_id: str, part: str, mode: str, r1_queue: str,
                prefix: str) -> list[str]:
    """The queue each rule of an entrypoint consumes from: the own queue for
    r1_booth_till with R1_MODE=own, the SAM queue otherwise."""
    queues = []
    for rule in RULES[part]:
        if part == "booth" and rule == R1_RULE and mode == "own":
            queues.append(r1_queue)
        else:
            queues.append(f"{prefix}{entrypoint_id}/{rule}")
    return queues


def platform_state(api: SamApi, name: str) -> tuple[str, str]:
    """(entrypoint id, 'deploymentStatus/runtimeStatus/last deployment')."""
    entry = api.find_by_name("/api/v2/platform/entrypoints", name)
    if not entry:
        return "", "absent"
    deps = api.call("GET", f"/api/v2/platform/entrypointDeployments?entrypointId="
                           f"{entry['id']}&pageSize=1")
    last = ((deps.get("data") or [{}])[0] if isinstance(deps, dict) else {}).get("status")
    runtime = (entry.get("runtimeStatus") or {}).get("status")
    return str(entry["id"]), f"{entry.get('deploymentStatus')}/{runtime}/{last}"


def cmd_ready(semp: Semp, env: Mapping[str, str], name: str, timeout: float,
              r1_queue: str, prefix: str) -> int:
    part = next((p for p, n in (("booth", BOOTH_ENTRYPOINT), ("probe", "gpos-probe-events"))
                 if n == name), None)
    if part is None:
        raise OpsError(f"ready: unknown entrypoint {name}")
    api, mode = SamApi(env), r1_mode(env)
    deadline = time.monotonic() + timeout
    while True:
        entry_id, state = platform_state(api, name)
        flows: dict[str, int] = {}
        if state == "deployed/running/success":
            flows = {q: len(semp.txflows(q))
                     for q in rule_queues(entry_id, part, mode, r1_queue, prefix)}
            if all(n == 1 for n in flows.values()):
                print(f"{name} ready: {entry_id}, one txFlow on each of "
                      f"{', '.join(flows)}")
                return 0
        if time.monotonic() >= deadline:
            detail = ", ".join(f"{q}={n}" for q, n in flows.items())
            print(f"ERROR: {name} not ready after {timeout:.0f} s: {state}"
                  f"{' / txFlows ' + detail if detail else ''}", file=sys.stderr)
            return EXIT_FINDING
        time.sleep(3)


def run(args: argparse.Namespace, semp: Semp, env: Mapping[str, str]) -> int:
    queue = env.get("R1_QUEUE", "gpos-booth-r1")
    prefix = env.get("SAM_QUEUE_PREFIX", SAM_QUEUE_PREFIX_DEFAULT)
    if args.cmd == "r1-create":
        return cmd_r1_create(semp, env, queue)
    if args.cmd == "r1-show":
        return cmd_r1_show(semp, queue)
    if args.cmd == "r1-switch":
        return cmd_r1_switch(semp, env, queue, args.old, args.new, prefix)
    if args.cmd == "r1-delete":
        return cmd_r1_delete(semp, queue)
    if args.cmd == "orphans":
        return cmd_orphans(semp, prefix)
    if args.cmd == "ready":
        return cmd_ready(semp, env, args.entrypoint, args.timeout, queue, prefix)
    print(len(semp.txflows(args.queue)))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("r1-create", "r1-show", "r1-delete", "orphans"):
        sub.add_parser(name)
    switch = sub.add_parser("r1-switch")
    switch.add_argument("old", choices=("own", "sam"))
    switch.add_argument("new", choices=("own", "sam"))
    flows = sub.add_parser("txflows")
    flows.add_argument("queue")
    ready = sub.add_parser("ready")
    ready.add_argument("entrypoint", choices=(BOOTH_ENTRYPOINT, "gpos-probe-events"))
    ready.add_argument("--timeout", type=float, default=60)
    args = ap.parse_args(argv)
    try:
        env = demo_env()
        with semp_session(env) as semp:
            return run(args, semp, env)
    except OpsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
