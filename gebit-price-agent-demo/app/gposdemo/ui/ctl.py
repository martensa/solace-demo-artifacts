"""``python -m gposdemo.ui.ctl``: operator commands, run inside ``deploy/gpos-ui``.

  reset [--scope booth|day]          POST /api/demo/reset of the local BFF (11.7)
  state                              GET /api/state of the local BFF
  probe r1|r3|r4|p1|p3|p4|notify     SMF Direct probe into SAM, PASS = done/<rule>
                                     within 15 s (9.7, 9.8 step 6/10), for r3/p3 also
                                     exactly one close_review call (telemetry, hard
                                     rule 6); exit 0 on PASS
  tools-list pos|wws|loyalty|engine|gate
                                     live MCP tools/list of the running service (8.5)

Probes publish with ``gposdemo.common.bus.SolaceBus`` (``bytearray``, user properties),
the real path of the services (A-17). Credentials come from the pod environment and
are never printed.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..common import topics
from ..common.bus import Bus, make_bus
from ..common.config import DEFAULT_PORTS, Settings, load_settings
from ..common.jsonutil import compact
from .feed import decode, sam_error_text, unwrap_sam

PROBE_NAMES = ("r1", "r3", "r4", "p1", "p3", "p4", "notify")
MCP_SERVICES = ("pos", "wws", "loyalty", "engine", "gate")
PROBE_TIMEOUT_S = 15.0
# the run's telemetry is published before SAM's done output, but by another client:
# wait this long after done before counting the tool calls
TOOL_GRACE_S = 1.0
# 9.8 step 6 / 9.5: a review probe runs close_review exactly once (skip, never conclude)
ONCE_TOOLS = {"3": ("engine", "close_review")}
PROBE_TYPE = "gpos.probe.Probe"
NOTIFY_SCOPE = "notify:_:send"
NOTIFY_HINT = "einmal in der SAM-WebUI als marktleitung anmelden"
MCP_PROTOCOL = "2025-06-18"
HTTP_TIMEOUT_S = 30.0


# --------------------------------------------------------------------- probes
@dataclass(frozen=True)
class Probe:
    """One probe: what to publish and which ``done`` output means PASS."""

    name: str
    rule: str
    probe_id: str
    topic: str
    payload: dict[str, Any]
    expect: dict[str, str]
    once_tool: tuple[str, str] | None = None  # (service, tool) called exactly once

    def matches(self, output: Any) -> bool:
        """``done`` output carries every expected key/value."""
        return isinstance(output, dict) and all(
            str(output.get(k, "")) == v for k, v in self.expect.items())

    @property
    def props(self) -> dict[str, str]:
        event_type = PROBE_TYPE if workflow_of(self.rule) == "1" else f"probe.{self.rule}"
        return {"eventType": event_type, "source": "gpos-ui", "apiVersion": "gpos-v1",
                "traceId": self.probe_id}


def workflow_of(rule: str) -> str:
    """``r1``/``p1`` -> ``"1"`` (gpos-pos-event), ``"3"`` basket review, ``"4"`` approval."""
    return rule[1:]


def build_probe(name: str, s: Settings, token: str | None = None) -> Probe:
    """Probe of 9.8 step 6 (``p*``, probe till 199/98) / step 10 (``r*``, booth 101/01)
    and the login check ``notify`` (9.7, on ``p4``)."""
    if name not in PROBE_NAMES:
        raise ValueError(f"probe must be one of {PROBE_NAMES}, got {name!r}")
    token = token or str(uuid.uuid4())
    rule = "p4" if name == "notify" else name
    location = s.booth_location if rule.startswith("r") else s.probe_location
    country, company, store, till = topics.parse_location(location)
    if name == "notify":
        pid = f"probe-notify-{token}"
        return Probe(name, rule, pid, topics.approval_request(store, till, pid),
                     {"schema_version": "1", "proposal_id": pid},
                     {"proposal_id": pid, "outcome": "probe"})
    pid = f"probe-{token}"
    if workflow_of(rule) == "1":
        topic = topics.gebit_event("purchase_transaction", "PurchaseTransactionCancelled",
                                   country, company, store, till, pid)
        return Probe(name, rule, pid, topic,
                     {"@type": f"type.googleapis.com/{PROBE_TYPE}", "probe": name},
                     {"verdict": "ignore"})
    if workflow_of(rule) == "3":
        return Probe(name, rule, pid, topics.review_request(store, till, pid),
                     {"schema_version": "1", "review_id": pid},
                     {"review_id": pid, "decision": "unknown"}, ONCE_TOOLS["3"])
    return Probe(name, rule, pid, topics.approval_request(store, till, pid),
                 {"schema_version": "1", "proposal_id": pid},
                 {"proposal_id": pid, "outcome": "unknown"})


@dataclass
class ProbeResult:
    passed: bool
    seconds: float
    detail: str
    notes: list[str] = field(default_factory=list)

    def line(self, name: str) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        text = f"probe {name}: {verdict} in {self.seconds:.2f} s ({self.detail})"
        return text + "".join(f"\n  note: {n}" for n in self.notes)


class _Waiter:
    """Collects ``done``/``error`` of one rule (and the probe's tool calls) until the
    probe is decided."""

    def __init__(self, probe: Probe):
        self.probe = probe
        self.done = threading.Event()  # decided, or done matched (tool count pending)
        self.result: tuple[bool, str] | None = None
        self.output = ""  # compact done output once it matched
        self.tool_calls = 0
        self.notes: list[str] = []
        self._lock = threading.Lock()

    def on_done(self, _topic: str, payload: bytes, _props: dict[str, str]) -> None:
        output = unwrap_sam(decode(payload))
        if not self.probe.matches(output):
            return
        if self.probe.once_tool is None:
            self._decide(True, compact(output)[:200])
        else:
            self.output = compact(output)[:200]
            self.done.set()

    def on_error(self, _topic: str, payload: bytes, _props: dict[str, str]) -> None:
        body = decode(payload)
        error = sam_error_text(body)
        whole = body if isinstance(body, str) else compact(body)
        if NOTIFY_SCOPE in whole and self.probe.name == "notify":
            self._decide(False, f"{error[:200]} -> {NOTIFY_HINT}")
        elif self.probe.probe_id in whole:
            self._decide(False, error[:200])
        else:
            self.notes.append(f"error/{self.probe.rule} (other run?): {error[:160]}")

    def on_tool(self, _topic: str, payload: bytes, _props: dict[str, str]) -> None:
        """Telemetry of the checked tool (7.2): count the calls of this probe's run."""
        body = decode(payload)
        if isinstance(body, dict) and body.get("ref") == self.probe.probe_id:
            with self._lock:
                self.tool_calls += 1

    def settle(self) -> None:
        """Decide a probe whose done output matched by its tool count (exactly one)."""
        if self.result is not None or not self.output or self.probe.once_tool is None:
            return
        tool = self.probe.once_tool[1]
        with self._lock:
            calls = self.tool_calls
        if calls == 1:
            self._decide(True, f"{self.output}, {tool} 1x")
        else:
            self._decide(False, f"{tool} {calls}x, expected exactly 1 ({self.output})")

    def _decide(self, passed: bool, detail: str) -> None:
        if self.result is None:
            self.result = (passed, detail)
            self.done.set()


def run_probe(bus: Bus, probe: Probe, timeout: float = PROBE_TIMEOUT_S,
              tool_grace: float = TOOL_GRACE_S) -> ProbeResult:
    """Subscribe ``done``/``error`` of the rule (and the telemetry of the checked tool),
    publish Direct, wait for the verdict."""
    waiter = _Waiter(probe)
    bus.subscribe(topics.sam_done(probe.rule), waiter.on_done)
    bus.subscribe(topics.sam_error(probe.rule), waiter.on_error)
    if probe.once_tool is not None:
        bus.subscribe(topics.telemetry_tool(*probe.once_tool), waiter.on_tool)
    started = time.monotonic()
    bus.publish(probe.topic, compact(probe.payload), props=probe.props)
    waiter.done.wait(timeout)
    if waiter.result is None and waiter.output:
        time.sleep(tool_grace)
        waiter.settle()
    seconds = time.monotonic() - started
    if waiter.result is None:
        return ProbeResult(False, seconds, f"no done/{probe.rule} with {compact(probe.expect)} "
                           f"within {timeout:.0f} s", waiter.notes)
    passed, detail = waiter.result
    return ProbeResult(passed, seconds, detail, waiter.notes)


# --------------------------------------------------------------------- MCP
def _host(target: str) -> str:
    """``gpos-wws:50053`` / ``http://gpos-engine:8765`` -> host name."""
    netloc = urlsplit(target).netloc if "://" in target else target
    return netloc.rpartition(":")[0] or netloc


def mcp_base_url(s: Settings, service: str) -> str:
    """Base URL of a service's MCP server, derived from the settings: POS admin and
    engine URL directly; WWS/Loyalty from the gRPC host with the MCP port of 2.2;
    the gate next to the engine (``gpos-engine`` -> ``gpos-gate``, local host kept)."""
    if service == "pos":
        return s.pos_admin_url
    if service == "engine":
        return s.engine_url
    if service in ("wws", "loyalty"):
        target = s.wws_grpc if service == "wws" else s.loyalty_grpc
        return f"http://{_host(target)}:{DEFAULT_PORTS[service][1]}"
    if service == "gate":
        host = _host(s.engine_url)
        if host.startswith("gpos-engine"):
            host = "gpos-gate" + host.removeprefix("gpos-engine")
        return f"http://{host}:{DEFAULT_PORTS['gate'][1]}"
    raise ValueError(f"service must be one of {MCP_SERVICES}, got {service!r}")


class McpClient:
    """Stateless streamable-HTTP JSON-RPC (``json_response``; SSE framing tolerated)."""

    def __init__(self, http: httpx.Client, base_url: str):
        self.http = http
        self.url = f"{base_url.rstrip('/')}/mcp"
        self._ids = itertools.count(1)

    def rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self.http.post(
            self.url, json={"jsonrpc": "2.0", "id": next(self._ids), "method": method,
                            "params": params},
            headers={"Accept": "application/json, text/event-stream",
                     "MCP-Protocol-Version": MCP_PROTOCOL})
        response.raise_for_status()
        body = response.text
        for line in body.splitlines():
            if line.startswith("data:"):
                body = line[5:].strip()
        message = json.loads(body)
        if "error" in message:
            raise RuntimeError(f"{self.url} {method}: {message['error']}")
        return message["result"]

    def tools(self) -> list[dict[str, Any]]:
        """``initialize``, then ``tools/list`` (all pages)."""
        self.rpc("initialize", {"protocolVersion": MCP_PROTOCOL, "capabilities": {},
                                "clientInfo": {"name": "gpos-ui-ctl", "version": "1"}})
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            result = self.rpc("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                return tools


# --------------------------------------------------------------------- CLI
def _bff_url(s: Settings, override: str | None) -> str:
    return (override or f"http://127.0.0.1:{s.http_port or 8090}").rstrip("/")


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1))


def cmd_reset(args: argparse.Namespace, s: Settings, http: httpx.Client) -> int:
    response = http.post(f"{_bff_url(s, args.bff)}/api/demo/reset", json={"scope": args.scope})
    body = response.json()
    _print_json(body)
    return 0 if response.status_code == 200 and body.get("ok") else 1


def cmd_state(args: argparse.Namespace, s: Settings, http: httpx.Client) -> int:
    response = http.get(f"{_bff_url(s, args.bff)}/api/state")
    _print_json(response.json())
    return 0 if response.status_code == 200 else 1


def cmd_probe(args: argparse.Namespace, s: Settings,
              bus_factory: Callable[[Settings], Bus]) -> int:
    probe = build_probe(args.name, s)
    try:
        bus = bus_factory(s)
    except Exception as exc:  # noqa: BLE001 - SDK errors of any kind end the probe
        print(f"probe {args.name}: FAIL (broker not reachable: {type(exc).__name__})")
        return 1
    try:
        result = run_probe(bus, probe, args.timeout)
    except Exception as exc:  # noqa: BLE001 - a failed publish is a failed probe
        print(f"probe {args.name}: FAIL (publish failed: {type(exc).__name__}: {exc})")
        return 1
    finally:
        bus.close()
    print(result.line(args.name))
    return 0 if result.passed else 1


def cmd_tools_list(args: argparse.Namespace, s: Settings, http: httpx.Client) -> int:
    base = args.url or mcp_base_url(s, args.service)
    _print_json(McpClient(http, base).tools())
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m gposdemo.ui.ctl", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    reset = sub.add_parser("reset", help="reset chain via the local BFF")
    reset.add_argument("--scope", choices=("booth", "day"), default="booth")
    reset.add_argument("--bff", help="BFF base URL (default http://127.0.0.1:HTTP_PORT)")
    state = sub.add_parser("state", help="GET /api/state of the local BFF")
    state.add_argument("--bff", help="BFF base URL")
    probe = sub.add_parser("probe", help="SAM probe over SMF Direct")
    probe.add_argument("name", choices=PROBE_NAMES)
    probe.add_argument("--timeout", type=float, default=PROBE_TIMEOUT_S)
    tools = sub.add_parser("tools-list", help="live MCP tools/list of a service")
    tools.add_argument("service", choices=MCP_SERVICES)
    tools.add_argument("--url", help="MCP base URL (default derived from the settings)")
    return ap


def main(argv: Sequence[str] | None = None,
         bus_factory: Callable[[Settings], Bus] = lambda s: make_bus(s, "gpos-ui-ctl"),
         http: httpx.Client | None = None) -> int:
    args = parser().parse_args(argv)
    s = load_settings("ui")
    if args.command == "probe":
        return cmd_probe(args, s, bus_factory)
    client = http or httpx.Client(timeout=HTTP_TIMEOUT_S)
    commands = {"reset": cmd_reset, "state": cmd_state, "tools-list": cmd_tools_list}
    try:
        return commands[args.command](args, s, client)
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        print(f"{args.command} failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if http is None:
            client.close()


if __name__ == "__main__":
    sys.exit(main())
