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
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opslib import OpsError, SamApi, demo_env, demo_path
from render_mesh import RULES, r1_mode, r1_topics

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
        semp = Semp.from_env(env)
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
    except OpsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
