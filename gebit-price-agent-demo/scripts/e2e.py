#!/usr/bin/env python3
"""End to end with SAM, from the Mac (spec 13.4, gate verification 9.9, 13.5).

  e2e.py --till 01|98 --scenario S1..S8 --mode approve|deny|timeout --runs N
         [--answer-delay S]
  e2e.py --gate-verify [--fallback-f2]   make gate-verify: S1 approve x3, deny x5 (A9)
                                         and timeout x2 (A10) on probe till 98, reset of
                                         store 199, result, runs and hash of
                                         mesh/connectors + mesh/agents + mesh/workflows
                                         in build/gate-verified
  e2e.py --gate-status [--fallback-f2]   exit 0 when build/gate-verified is PASS for the
                                         current hash and these runs (scripts/install.sh
                                         mesh, 9.8 step 7: no booth entrypoint otherwise)

Per invocation: lock build/sam_inbox.lock (never together with `sam_inbox.py
watch`, this script applies the same rules), login/notify check (ui.ctl probe
notify in the pod), GET /api/state over HTTPS with E2E_CA_FILE.
Per run: reset (scripts/reset.sh for till 01, store 199 for till 98), no open
gpos request; scenario over the BFF facade while the SSE stream is recorded;
proposal pending -> answer from the inbox (approve/deny, or none for timeout) at
the earliest GATE_MIN_DELAY_S + 1 s after pending, right after checking
approval.apply_calls == 0; outcome, next scan with the new price; gate check on
the engine clock; agent check from the tool telemetry (evidence agent: API queries;
planner: decision.model "planning" and evidence) and the awe log (no artifact tool,
no tool of the planner). One JSON line per run, a summary with p50/p90/p95 at the
end, everything also in build/e2e/.

The awe log names agents by their internal id (``agentName`` =
``agent_<uuid with underscores>``, A-33): the preflight maps id -> name through the
platform agent list (read-only ``GET /api/v2/platform/agents`` with the e2e login) and
fails when one of our agents is missing. The awe check is fail-closed: telemetry
shows agent API queries but the log names no evidence agent, or an answered approval
without ``apply_price`` of the approver, fails the run ("awe log not parsed").
Deny and timeout runs report the path the SAM run took (``deny_path``/``timeout_path``:
``clean`` = R4 done, ``error_fallback`` = R4 error, engine rule 11.5 R6/R3), the
``approvalRefusal`` of ``apply_price`` in the awe log, ``approval.agent_status`` and
the evidence the engine decided by (``approval.evidence``, UC1-29): ``evidence_path``
``status`` (clean status, R5), ``message`` (SAM's text copied by the approver,
R5m/R3a), ``error`` (error fallback, R6/R3a), ``window`` (R3b) or ``unknown``, plus
``engine_rule`` and ``tool_message``. A deny passes on any of these paths when the
outcome is ``rejected`` without a price.

Planner robustness (UC1-30), counted in the awe lines of the workflow traces that
started in this run (a stuck planner of the previous run logs on under its own
trace): ``planner_attempts`` (attempts of the node ``recommend`` of this run's review:
0 without a planner run, 1, 2 when SAM retried; the largest of 1 + the awe retry
lines, the planner sub-tasks seen, 1 + the retry limit when ``recommend`` failed in
the end on its per-attempt timeout and 2 when A4b is longer than one attempt can take;
node lines count only in the traces of gpos-basket-review), ``planner_retry_lines``
(awe ``retrying node``/``scheduling node retry`` of ``recommend``; not emitted at the
lab's INFO level, 12.11.: stays 0 there, the retry shows in A4b) and
``planner_internal_tool_calls`` (the planner's awe WARN lines when the model calls
SAM's internal tools itself, :data:`PLANNER_WARNINGS`; lines written after the log was
read are missed, so a lower bound). The summary and build/gate-verified add
``planner_retried_runs`` and ``planner_internal_tool_calls``. Neither fails a run: a
retried run that ends correct stays ok.

TARGET=aks (AKS-MIGRATION-PLAN A19, A21): .env.aks only, the BFF on the public name
(E2E_CA_FILE=system), kubectl with the AKS kubeconfig and context, the awe log of
AWE_NS/AWE_DEPLOY, records in build/aks/ (gate-verified with target=aks, e2e/,
sam_inbox.lock); the lab's build/gate-verified never counts for AKS.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from opslib import (APPROVER_AGENTS, BUILD, DEMO_DIR, GATE_FILE, GATE_MODES, GATE_MODES_TEXT,
                    RUN_IDENTITY_DEFAULT, Bff, Inbox, InboxItem, OpsError, SamApi,
                    current_target, decide, demo_env, exclusive_lock, gate_hash,
                    gate_verified, kubectl_base, kubectl_ui, target_of, with_ref)

TILLS = {"01": "", "98": "?till=98"}
INBOX_POLL_S = 0.3
STEP_DELAY_S = 1.2
# A-21 (lab 12.11.): the two toolsets SAM attaches to every agent with all their tools,
# = toolsetExcludedTools of every agent of ours (test_mesh_contract compares); a call of
# any of them by any of our agents fails the run (hard rule 5)
EXCLUDED_TOOLS = {
    "builtin_artifact_tools": ("list_artifacts", "load_artifact", "delete_artifact",
                               "append_to_artifact", "artifact_search_and_replace_regex",
                               "artifact_grep"),
    "data_analysis": ("query_data_with_sql", "create_sqlite_db", "transform_data_with_jmespath",
                      "merge_structured_data", "reinterpret_artifact",
                      "create_chart_from_plotly_config"),
}
ARTIFACT_TOOLS = tuple(t for tools in EXCLUDED_TOOLS.values() for t in tools)
EVIDENCE_AGENT = "gpos-pricing-agent"
PLANNER_AGENT = "gpos-price-planner"
OUR_AGENTS = (EVIDENCE_AGENT, PLANNER_AGENT) + APPROVER_AGENTS
# the gated tool each approver calls itself (F2: the builtin time tool; apply_price runs
# there in a workflow tool node, never in the agent, 9.9)
GATED_TOOL = {APPROVER_AGENTS[0]: "apply_price", APPROVER_AGENTS[1]: "get_current_time"}
PLATFORM_AGENTS = "/api/v2/platform/agents"
AWE_TOOL_MESSAGES = ("tool execution succeeded", "tool execution failed")
APPROVAL_RULES = ("r4", "p4")
PATH_WINDOW_S = 10.0
EVIDENCE_PATHS = ("status", "message", "error", "window", "unknown")
# R3 ends within its workflow_timeout 150 s (recommend 30 s + one retry, UC1-30), the
# engine watchdog ends a review still prepared after 180 s (sweep 5 s, 11.7): a retried
# review (~55 s after Closed) must not fail the run
REVIEW_WAIT_S = 185
TEXT_MAX = 200
REVIEW_END = ("proposed", "no_action", "no_candidates", "only_blocked", "deferred", "blocked",
              "failed", "superseded")
PROPOSAL_END = ("approved", "rejected", "expired", "failed", "superseded", "blocked")
# awe of the lab (namespace, Deployment, container); AWE_NS/AWE_DEPLOY override them
AWE = ("sam-solace-lab", "agent-mesh-solace-agent-mesh-awe", "awe")
# planner robustness (UC1-30): node recommend of gpos-basket-review, RECOMMEND_TIMEOUT_S
# per attempt and RECOMMEND_RETRIES = retry_strategy.limit (test_e2e_helpers compares
# them with the workflow file); REVIEW_TOOL marks the traces of gpos-basket-review (its
# first node; another workflow of the shared awe may have a node "recommend" too)
PLANNER_NODE = "recommend"
RECOMMEND_TIMEOUT_S = 30
RECOMMEND_RETRIES = 1
RECOMMEND_TIMED_OUT = f'"{PLANNER_NODE}" timed out after {RECOMMEND_TIMEOUT_S}s'  # lab text
REVIEW_TOOL = "prepare_review"
STAGE_MARGIN_S = 5.0          # stage/conclude after recommend: < 1 s in the lab
DECIDED = ("proposed", "no_action")
# the planner's awe WARN lines when the model calls SAM's internal tools itself (lab
# 12.11.: the stuck runs; message prefixes)
PLANNER_WARNINGS = ("dropping LLM-generated _notify_artifact_save call",
                    "LLM emitted internal continuation call")
# a node retry in the awe log (strings of the awe binary, not emitted at INFO, lab
# 12.11.; per trace the larger count of the two wins, in case both are logged for one
# retry); "node failed" is logged only after the last attempt
NODE_RETRY_MESSAGES = ("retrying node", "scheduling node retry")
NODE_FAILED = "node failed"
NODE_KEYS = ("node", "nodeID", "nodeId", "node_id")
WORKFLOW_START = ("received task request", "starting workflow execution")
TRACE_SKEW_S = 5.0            # Mac clock vs. awe timestamps


@dataclass(frozen=True)
class Expect:
    """Golden outcome of a scenario from a reset (spec 1.3, 6.8)."""

    review_state: str
    article: str = ""
    reason: str = ""
    new_price: str = ""
    agent: bool = True
    loyalty: bool = False
    api_queries: int = 0        # agent API queries of the evidence agent (13.5 A8)


EXPECT = {
    "S1": Expect("proposed", "100001", "slow_seller", "7,99", api_queries=2),
    "S2": Expect("proposed", "100008", "season_end", "5,49", api_queries=2),
    "S3": Expect("proposed", "100012", "customer_behaviour", "12,99", loyalty=True,
                 api_queries=3),
    "S4": Expect("no_candidates", agent=False),
    "S5": Expect("only_blocked", agent=False),
    "S6": Expect("no_candidates", agent=False),
    "S7": Expect("proposed", "100008", "season_end", "5,49", api_queries=3),
    "S8": Expect("no_action", api_queries=2),
}
TALK_TRACK_SCENARIOS = ("S1",)  # a mismatch of api_queries fails only here (1.4)


def percentile(values: list[float], p: float) -> float | None:
    data = sorted(values)
    if not data:
        return None
    k = (len(data) - 1) * p
    lo, hi = math.floor(k), min(math.floor(k) + 1, len(data) - 1)
    return round(data[lo] + (data[hi] - data[lo]) * (k - lo), 3)


def iso_seconds(value: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def cash_cents(total: Decimal) -> int:
    """The next full 5-euro amount, as /kasse pays (spec 1.3)."""
    return max(5, math.ceil(total / 5) * 5) * 100


# ------------------------------------------------------------------------ awe log


def norm_agent_id(value: Any) -> str:
    """``agent_01a1c9fe_7ab8_…`` (awe) and ``01a1c9fe-7ab8-…`` (platform) -> one key:
    casefold, without ``agent_``, ``-`` as ``_``."""
    text = str(value or "").strip().casefold()
    return text.removeprefix("agent_").replace("-", "_")


def agent_id_map(agents: Iterable[Mapping[str, Any]], names: Iterable[str]) -> dict[str, str]:
    """``{normalised id: name}`` of the platform agents named in ``names``."""
    wanted = set(names)
    return {norm_agent_id(a.get("id")): str(a.get("name")) for a in agents
            if a.get("name") in wanted and a.get("id")}


@dataclass
class AweTools:
    """Tool executions of our agents in one awe log window, and the planner's
    robustness in the workflow traces of this run (UC1-30)."""

    tools: dict[str, list[str]] = field(default_factory=dict)
    refusals: list[str] = field(default_factory=list)  # approvalRefusal of apply_price
    planner_warnings: int = 0       # PLANNER_WARNINGS lines of the planner
    planner_tasks: int = 0          # distinct planner sub-tasks (awe taskID)
    recommend_retries: int = 0      # SAM retries of node recommend
    recommend_seen: bool = False    # planner line, retry or failure of node recommend
    recommend_timed_out: bool = False  # "node failed" of recommend on its per-attempt
                                       # timeout: logged after the last attempt only


def awe_agent(entry: Mapping[str, Any], id_map: Mapping[str, str],
              known: set[str]) -> str:
    """Our agent of an awe line: ``agentName`` through ``id_map`` or named directly."""
    raw = str(entry.get("agentName", ""))
    return raw if raw in known else id_map.get(norm_agent_id(raw), "")


def run_traces(entries: Iterable[Mapping[str, Any]], since: float | None) -> set[str]:
    """traceIDs of the workflow runs that started at or after ``since`` (wall clock,
    less :data:`TRACE_SKEW_S`); ``None``: every trace with a start line."""
    traces = set()
    for entry in entries:
        if entry.get("message") in WORKFLOW_START and entry.get("traceID"):
            started = iso_seconds(entry.get("timestamp"))
            if since is None or (started is not None and started >= since - TRACE_SKEW_S):
                traces.add(str(entry["traceID"]))
    return traces


def planner_robustness(entries: list[Mapping[str, Any]], id_map: Mapping[str, str],
                       known: set[str], since: float | None) -> dict[str, Any]:
    """The UC1-30 fields of :class:`AweTools` from the lines of this run's traces (a
    line without traceID counts by its own time): the planner's
    :data:`PLANNER_WARNINGS` and sub-tasks (``taskID``; its card and audit lines carry
    none), the retries (:data:`NODE_RETRY_MESSAGES`, once per retry and trace) and
    failures of node ``recommend`` in the traces of gpos-basket-review (those with a
    :data:`REVIEW_TOOL` call). The planner's own ``structured invocation retry``
    (same sub-task) is no node retry."""
    traces = run_traces(entries, since)
    reviews = {str(e["traceID"]) for e in entries
               if e.get("tool") == REVIEW_TOOL and e.get("traceID")}
    warnings, tasks, failed, timed_out = 0, set(), False, False
    retries: dict[tuple[str, str], int] = {}
    for entry in entries:
        trace = str(entry.get("traceID") or "")
        if trace and trace not in traces:
            continue
        if not trace and since is not None and (
                iso_seconds(entry.get("timestamp")) or 0) < since - TRACE_SKEW_S:
            continue
        message = str(entry.get("message") or "")
        if awe_agent(entry, id_map, known) == PLANNER_AGENT:
            warnings += int(message.startswith(PLANNER_WARNINGS))
            if entry.get("taskID"):
                tasks.add(str(entry["taskID"]))
        elif trace in reviews and next((str(entry[k]) for k in NODE_KEYS
                                        if entry.get(k)), "") == PLANNER_NODE:
            if message in NODE_RETRY_MESSAGES:
                retries[(trace, message)] = retries.get((trace, message), 0) + 1
            failed = failed or message == NODE_FAILED
            timed_out = timed_out or (message == NODE_FAILED and RECOMMEND_TIMED_OUT in str(
                entry.get("error") or ""))
    per_trace: dict[str, int] = {}
    for (trace, _), count in retries.items():
        per_trace[trace] = max(per_trace.get(trace, 0), count)
    return {"planner_warnings": warnings, "planner_tasks": len(tasks),
            "recommend_retries": sum(per_trace.values()),
            "recommend_seen": bool(tasks or per_trace or failed),
            "recommend_timed_out": timed_out}


def parse_awe(lines: Iterable[str], id_map: Mapping[str, str],
              names: Iterable[str] = OUR_AGENTS, since: float | None = None) -> AweTools:
    """The awe JSON lines ``tool execution succeeded|failed`` of our agents (A-33):
    ``agentName`` through ``id_map`` (a line naming the agent directly counts too),
    ``tool``, and for the approver's gated tool (:data:`GATED_TOOL`) the
    ``approvalRefusal`` (e.g. "denied"); plus :func:`planner_robustness` for the
    traces started since ``since`` (wall clock of the run start)."""
    known = set(names)
    found: dict[str, set[str]] = {}
    refusals: list[str] = []
    entries: list[Mapping[str, Any]] = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        entries.append(entry)
        if entry.get("message") not in AWE_TOOL_MESSAGES:
            continue
        agent = awe_agent(entry, id_map, known)
        tool = entry.get("tool")
        if not agent or not tool:
            continue
        found.setdefault(agent, set()).add(str(tool))
        if tool == GATED_TOOL.get(agent) and entry.get("approvalRefusal"):
            refusals.append(str(entry["approvalRefusal"]))
    return AweTools({k: sorted(v) for k, v in sorted(found.items())}, refusals,
                    **planner_robustness(entries, id_map, known, since))


def planner_attempts(awe: AweTools, review_state: Any, a4b: Any) -> int:
    """Attempts of node ``recommend`` in this run's review (UC1-30): 0 when the planner
    neither decided nor left an awe line (S4-S6, skip path), else the largest of
    1 + SAM's retries, the planner sub-tasks seen, 1 + :data:`RECOMMEND_RETRIES` when
    the node failed in the end on :data:`RECOMMEND_TIMED_OUT` (SAM logs ``node failed``
    after the last attempt only) and 2 when A4b (evidence -> decided) is longer than
    one attempt can take (:data:`RECOMMEND_TIMEOUT_S` + :data:`STAGE_MARGIN_S`; the node
    timeout counts per attempt)."""
    decided = review_state in DECIDED
    if not (decided or awe.recommend_seen):
        return 0
    attempts = max(1 + awe.recommend_retries, awe.planner_tasks)
    if awe.recommend_timed_out:
        attempts = max(attempts, 1 + RECOMMEND_RETRIES)
    if decided and isinstance(a4b, (int, float)) and a4b > RECOMMEND_TIMEOUT_S + STAGE_MARGIN_S:
        attempts = max(attempts, 2)
    return attempts


def awe_checks(mode: str, data: Mapping[str, Any], awe: AweTools,
               approver: str) -> list[str]:
    """Fail-closed checks of one run (hard rule 5, 13.4); ``[]`` = ok."""
    errors = []
    if data.get("agent_tools") and EVIDENCE_AGENT not in awe.tools:
        errors.append("awe log not parsed: no tool of the evidence agent although the "
                      "telemetry shows agent API queries")
    answered = mode in ("approve", "deny") and "apply_calls_before" in data
    gated = GATED_TOOL.get(approver, "apply_price")
    if answered and gated not in awe.tools.get(approver, []):
        errors.append(f"awe log not parsed: no {gated} of {approver}")
    if awe.tools.get(PLANNER_AGENT):
        errors.append(f"planner called a tool: {awe.tools[PLANNER_AGENT]}")
    artifact = sorted({t for ts in awe.tools.values() for t in ts if t in ARTIFACT_TOOLS})
    if artifact:
        errors.append(f"artifact tool(s) called: {artifact} (hard rule 5)")
    return errors


def approval_evidence(approval: Mapping[str, Any] | None) -> dict[str, Any]:
    """``agent_status``, ``evidence_path`` (:data:`EVIDENCE_PATHS`), ``engine_rule`` and
    ``tool_message`` of the engine's ``approval`` block (``approval.evidence`` is the
    read-only view of the ``outcome_evidence`` audit row; missing on an older engine or
    when the watchdog ended the proposal: ``unknown``)."""
    approval = approval or {}
    evidence = approval.get("evidence")
    evidence = evidence if isinstance(evidence, Mapping) else {}
    path = str(evidence.get("path") or "")
    return {"agent_status": str(approval.get("agent_status") or ""),
            "evidence_path": path if path in EVIDENCE_PATHS else "unknown",
            "engine_rule": str(evidence.get("rule") or ""),
            "tool_message": " ".join(str(evidence.get("tool_message") or "").split())[
                :TEXT_MAX]}


def approval_path(runs: Iterable[tuple[float, bool]], t_from: float,
                  window_s: float = PATH_WINDOW_S) -> str:
    """``clean`` (R4/P4 done), ``error_fallback`` (R4/P4 error) or ``unknown``: the
    first approval run ending within ``window_s`` after ``t_from``."""
    for mono, ok in sorted(runs):
        if t_from - 1 <= mono <= t_from + window_s:
            return "clean" if ok else "error_fallback"
    return "unknown"


# ------------------------------------------------------------------------ SSE


@dataclass(frozen=True)
class Ev:
    mono: float
    kind: str
    data: dict


class Sse(threading.Thread):
    """Records GET /api/events (spec 10.2) with arrival times; reconnects."""

    def __init__(self, bff: Bff):
        super().__init__(daemon=True)
        self.bff, self.events, self.lock = bff, [], threading.Lock()
        self.stop = threading.Event()
        self.connected = threading.Event()

    def run(self) -> None:
        while not self.stop.is_set():
            try:
                with self.bff.http.stream("GET", "/api/events", timeout=None) as resp:
                    self.connected.set()
                    self._read(resp.iter_lines())
            except Exception:  # noqa: BLE001 -- the stream drops: reconnect
                time.sleep(1)

    def _read(self, lines: Any) -> None:
        kind, data = "", []
        for line in lines:
            if self.stop.is_set():
                return
            if line.startswith("event:"):
                kind = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
            elif not line and kind:
                try:
                    payload = json.loads("\n".join(data))
                except ValueError:
                    payload = {}
                with self.lock:
                    self.events.append(Ev(time.monotonic(), kind,
                                          payload if isinstance(payload, dict) else {}))
                kind, data = "", []

    def mark(self) -> int:
        with self.lock:
            return len(self.events)

    def select(self, since: int, pred: Callable[[Ev], bool]) -> list[Ev]:
        with self.lock:
            return [e for e in self.events[since:] if pred(e)]

    def wait(self, since: int, pred: Callable[[Ev], bool], timeout: float,
             tick: Callable[[], None] | None = None) -> Ev | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            hits = self.select(since, pred)
            if hits:
                return hits[0]
            if tick:
                tick()
            time.sleep(0.1)
        return None


# ----------------------------------------------------------------------- runs


@dataclass
class RunResult:
    run: int
    till: str
    scenario: str
    mode: str
    errors: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def fail(self, message: str) -> None:
        self.errors.append(message)

    def line(self) -> dict[str, Any]:
        return {"run": self.run, "till": self.till, "scenario": self.scenario,
                "mode": self.mode, "ok": not self.errors, **self.data,
                "errors": self.errors}


class E2E:
    def __init__(self, env: Mapping[str, str], args: argparse.Namespace):
        self.env, self.args = env, args
        self.till = args.till
        self.bff = Bff(env, timeout=20)
        self.sam = SamApi(env)
        self.inbox = Inbox(self.sam, env.get("SAM_RUN_IDENTITY", RUN_IDENTITY_DEFAULT))
        self.sse = Sse(Bff(env))                 # own client: the stream holds a connection
        self.gate_delay = float(env.get("GATE_MIN_DELAY_S", "3"))
        self.catalog: dict[str, dict] = {}
        self.scenarios: dict[str, list[dict]] = {}
        self.approver = APPROVER_AGENTS[1 if getattr(args, "fallback_f2", False) else 0]
        self.agent_ids: dict[str, str] = {}

    # preflight ------------------------------------------------------------
    def preflight(self) -> None:
        self.bff.get("/api/state")
        proc = kubectl_ui(self.env, ["-m", "gposdemo.ui.ctl", "probe", "notify"], timeout=60)
        if proc.returncode != 0:
            raise OpsError("login/notify check failed (spec 9.7): log in once to the SAM "
                           "WebUI as marktleitung, then retry")
        self.resolve_agents()
        self.catalog = {a["gtin"]: a for a in self.bff.get("/api/catalog")["articles"]}
        scenarios = self.bff.get("/api/scenarios")
        if isinstance(scenarios, dict):
            scenarios = scenarios.get("scenarios", [])
        self.scenarios = {s["id"]: s["steps"] for s in scenarios}
        self.sse.start()
        if not self.sse.connected.wait(10):
            raise OpsError("SSE /api/events not reachable")

    def resolve_agents(self) -> None:
        """A-33: awe ``agentName`` is the internal id; map it through the platform agent
        list (read-only GET). Fail-closed: every agent of this run must resolve."""
        self.agent_ids = agent_id_map(self.sam.list_all(PLATFORM_AGENTS), OUR_AGENTS)
        missing = [a for a in (EVIDENCE_AGENT, PLANNER_AGENT, self.approver)
                   if a not in self.agent_ids.values()]
        if missing:
            raise OpsError(f"agent(s) not on the platform, awe log not mappable: {missing} "
                           f"(GET {PLATFORM_AGENTS}; scripts/install.sh mesh?)")

    # reset ----------------------------------------------------------------
    def reset(self, result: RunResult) -> None:
        started = time.monotonic()
        if self.till == "01":
            proc = subprocess.run([str(DEMO_DIR / "scripts" / "reset.sh")], capture_output=True,
                                  text=True, timeout=120, check=False)
            if proc.returncode != 0:
                result.fail(f"reset.sh failed: {proc.stdout.strip().splitlines()[-1:]}")
        else:
            proc = kubectl_ui(self.env, ["-", "--reset-store", "199"],
                              stdin=(DEMO_DIR / "scripts" / "smoke.py").read_text("utf-8"))
            if proc.returncode != 0:
                result.fail("reset of store 199 failed")
            for item in self.inbox.pending_gpos():
                self.inbox.respond(item.id, None)
        result.data["reset_s"] = round(time.monotonic() - started, 2)
        if self.inbox.pending_gpos():
            result.fail("open gpos request after the reset")
        if self.till == "01":
            proposal = (self.bff.get("/api/state") or {}).get("proposal") or {}
            if proposal.get("state") == "pending":
                result.fail("proposal still pending after the reset")

    # scenario -------------------------------------------------------------
    def pos(self, method: str, body: dict) -> dict:
        code, data = self.bff.post(f"/api/pos/{method}{TILLS[self.till]}", body)
        if code != 200 or not data.get("ok"):
            raise OpsError(f"facade {method}: HTTP {code} {data.get('code', '')} "
                           f"{data.get('message', '')}".rstrip())
        return data.get("result") or {}

    def play(self, scenario: str, result: RunResult) -> str:
        tx_id, total, scans = "", Decimal("0"), []
        for step in self.scenarios[scenario]:
            op, value = step["op"], step.get("value", "")
            if op == "new":
                res = self.pos("CreatePurchaseTransaction", {})
                tx_id = str(res.get("purchaseTransactionId") or res.get("value") or "")
            elif op == "card":
                self.pos("AssignLoyaltyMembership", {"purchaseTransactionId": tx_id,
                                                     "membershipIdentificationValue": value})
            elif op == "scan":
                article = self.catalog[value]
                scans.append((time.monotonic(), article["article_number"]))
                self.scan(tx_id, article)
                total += Decimal(article["price"].replace(",", "."))
            elif op == "pay":
                self.pos("StartPaymentProcess", {"purchaseTransactionId": tx_id})
                self.pos("CreateCashPayment", {
                    "purchaseTransactionId": tx_id, "clientId": f"e2e-{self.till}",
                    "clientTransactionId": str(uuid.uuid4()),
                    "amount": {"currency": "EUR",
                               "amount": {"scale": 2, "intVal": str(cash_cents(total))}}})
            time.sleep(STEP_DELAY_S)
        result.data["tx_id"] = tx_id
        result.data["_scans"] = scans
        return tx_id

    def scan(self, tx_id: str, article: dict) -> None:
        self.pos("AddArticle", {
            "purchaseTransactionId": tx_id, "articleId": article["article_id"], "itemCount": 1,
            "capturingInformation": {"inputMethod": "SCANNER", "inputType": "EAN13",
                                     "inputValue": article["gtin"]}})

    def scan_latencies(self, since: int, tx_id: str, result: RunResult) -> None:
        """A1 scan -> monitor row (pos_event), A2 scan -> insight chip (via SAM R1)."""
        a1, a2 = [], []
        for t_scan, number in result.data.pop("_scans"):
            def match(kind: str, e: Ev, n: str = number) -> bool:
                return (e.kind == kind and e.data.get("tx_id") == tx_id
                        and e.data.get("article_number") == n)
            row = next(iter(self.sse.select(since, lambda e: match("pos_event", e)
                                            and e.data.get("event") == "PositionAdded")), None)
            chip = next(iter(self.sse.select(since, lambda e: match("insight", e))), None)
            if row:
                a1.append(round(row.mono - t_scan, 3))
            if chip:
                a2.append(round(chip.mono - t_scan, 3))
        result.data.update(a1_scan_row_s=a1, a2_scan_insight_s=a2)

    # review and proposal --------------------------------------------------
    def await_review(self, since: int, tx_id: str, result: RunResult) -> Ev | None:
        closed = self.sse.wait(since, lambda e: e.kind == "pos_event" and e.data.get("tx_id")
                               == tx_id and e.data.get("event") == "PurchaseTransactionClosed", 15)
        if closed is None:
            result.fail("PurchaseTransactionClosed not seen on SSE")
            return None
        end = self.sse.wait(since, lambda e: e.kind == "review" and e.data.get("tx_id") == tx_id
                            and e.data.get("state") in REVIEW_END, REVIEW_WAIT_S)
        prepared = next(iter(self.sse.select(since, lambda e: e.kind == "review" and e.data.get(
            "tx_id") == tx_id and e.data.get("state") == "prepared")), None)
        if prepared:
            result.data["a3_closed_prepared_s"] = round(prepared.mono - closed.mono, 3)
        evidence = next(iter(self.sse.select(since, lambda e: e.kind == "review" and e.data.get(
            "tx_id") == tx_id and isinstance(e.data.get("evidence"), dict))), None)
        if evidence:
            result.data["a4a_closed_evidence_s"] = round(evidence.mono - closed.mono, 3)
        if end is None:
            result.fail(f"no review end state within {REVIEW_WAIT_S} s")
            return None
        if evidence and end.data.get("state") in ("proposed", "no_action"):
            result.data["a4b_evidence_decided_s"] = round(end.mono - evidence.mono, 3)
        result.data.update(review_id=end.data.get("review_id"), review_state=end.data.get("state"))
        decision = end.data.get("decision") if isinstance(end.data.get("decision"), dict) else {}
        items = (end.data.get("evidence") or {}).get("items") if isinstance(
            end.data.get("evidence"), dict) else None
        result.data.update(ai_model=decision.get("model"),
                           evidence_items=len(items) if isinstance(items, list) else 0)
        result.data["_closed"] = closed.mono
        return end

    def proposal_event(self, since: int, proposal_id: str, states: tuple[str, ...],
                       timeout: float, tick: Callable[[], None] | None = None) -> Ev | None:
        return self.sse.wait(since, lambda e: e.kind == "proposal" and e.data.get(
            "proposal_id") == proposal_id and e.data.get("state") in states, timeout, tick)

    def requests(self, proposal_id: str, since_wall: float) -> list[InboxItem]:
        """Open requests of this proposal, oldest first (fallback A-6 / F2: our
        approver agent named, no Ref, created after `since_wall`)."""
        items = []
        for item in self.inbox.pending_gpos():
            if item.ref is None and (iso_seconds(item.created_at) or 0) >= since_wall - 2:
                item = with_ref([item], proposal_id)[0]
            if item.ref == proposal_id:
                items.append(item)
        return sorted(items, key=lambda i: i.created_at)

    def apply_calls(self, proposal_id: str) -> tuple[int, dict]:
        proposal = self.bff.proposal(proposal_id) or {}
        approval = proposal.get("approval") or {}
        return int(approval.get("apply_calls") or 0), approval

    def approval_flow(self, since: int, result: RunResult) -> None:
        review_id = result.data["review_id"]
        ready = self.sse.wait(since, lambda e: e.kind == "proposal" and e.data.get("review_id")
                              == review_id and e.data.get("state") == "ready", 5)
        pending = self.sse.wait(since, lambda e: e.kind == "proposal" and e.data.get("review_id")
                                == review_id and e.data.get("state") == "pending", 40)
        if ready is None or pending is None:
            result.fail("proposal ready/pending not seen within 40 s")
            return
        pid = pending.data["proposal_id"]
        result.data.update(proposal_id=pid, article=pending.data.get("article_number"),
                           reason=pending.data.get("reason"),
                           new_price=pending.data.get("new_price"),
                           a4_closed_ready_s=round(ready.mono - result.data.pop("_closed"), 3))
        first, seen = self.first_request(pid, ready.mono, result)
        if first is None:
            return
        self.answer(pid, first, pending.mono, since, result, seen)

    def first_request(self, pid: str, t_ready: float, result: RunResult
                      ) -> tuple[InboxItem | None, set[str]]:
        since_wall = time.time() - (time.monotonic() - t_ready)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            items = self.requests(pid, since_wall)
            if items:
                result.data["a5_ready_request_s"] = round(time.monotonic() - t_ready, 3)
                return items[0], {items[0].id}
            time.sleep(INBOX_POLL_S)
        result.fail("no approval request (category hil) in the inbox within 20 s")
        return None, set()

    def answer(self, pid: str, first: InboxItem, t_pending: float, since: int,
               result: RunResult, seen: set[str]) -> None:
        mode, delay = self.args.mode, max(self.gate_delay + 1, self.args.answer_delay)
        dups: list[str] = []
        first_by_ref = {pid: first.id}
        last_poll = [0.0]

        def tick() -> None:  # duplicates are handled like the watcher does (12.6)
            if time.monotonic() - last_poll[0] < INBOX_POLL_S:
                return
            last_poll[0] = time.monotonic()
            items = [i for i in self.requests(pid, time.time() - 600) if i.id not in seen]
            if not items:
                return
            proposals = {pid: self.bff.proposal(pid)}
            for decision in decide(items, proposals, first_by_ref):
                if decision.action != "keep":     # approve, or cancel (never a deny)
                    self.inbox.respond(decision.item_id,
                                       True if decision.action == "approve" else None)
                    seen.add(decision.item_id)
                    dups.append(decision.action)

        while time.monotonic() < t_pending + delay:
            tick()
            time.sleep(0.1)
        calls_before, _ = self.apply_calls(pid)
        result.data["apply_calls_before"] = calls_before
        if calls_before != 0:
            result.fail(f"GATE: apply_price ran {calls_before}x before any answer")
        t_answer = time.monotonic()
        if mode != "timeout":
            self.inbox.respond(first.id, mode == "approve")
        outcome = self.proposal_event(since, pid, PROPOSAL_END,
                                      200 if mode == "timeout" else 60, tick)
        result.data["duplicates"] = dups
        if outcome is None:
            result.fail("no proposal outcome")
            return
        result.data.update(outcome=outcome.data.get("state"),
                           status_reason=outcome.data.get("status_reason", ""),
                           answer_outcome_s=round(outcome.mono - t_answer, 3))
        result.data["_t_answer"] = t_answer
        self.check_outcome(pid, outcome, t_answer, t_pending, since, result)

    def check_outcome(self, pid: str, outcome: Ev, t_answer: float, t_pending: float,
                      since: int, result: RunResult) -> None:
        mode, state = self.args.mode, outcome.data.get("state")
        calls, approval = self.apply_calls(pid)
        result.data["apply_calls_after"] = calls
        if mode == "approve":
            if state != "approved":
                result.fail(f"outcome {state}, expected approved")
                return
            applied = self.sse.wait(since, lambda e: e.kind == "price_change" and e.data.get(
                "proposal_id") == pid and e.data.get("event") == "PriceChangeApplied", 10)
            if applied is None:
                result.fail("PriceChangeApplied not seen")
            else:
                result.data["a6_answer_applied_s"] = round(applied.mono - t_answer, 3)
                result.data["price_change_topic"] = applied.data.get("topic")
            checked, first_apply = (iso_seconds(approval.get("checked_at")),
                                    iso_seconds(approval.get("first_apply_at")))
            gap = (first_apply - checked) if checked and first_apply else None
            result.data["first_apply_minus_checked_s"] = None if gap is None else round(gap, 3)
            if calls < 1 or gap is None or gap < self.gate_delay:
                result.fail(f"GATE: apply_calls {calls}, first_apply-checked {gap}")
            self.next_scan(result)
        elif mode == "deny":
            # any evidence path counts (status, message, error): rejected and no price
            result.data.update(approval_evidence(approval))
            if state != "rejected" or calls != 0:
                result.fail(f"deny: outcome {state}, apply_calls {calls}")
            if outcome.mono - t_answer > 8:
                result.fail("deny: outcome later than 8 s after the answer (A9)")
            result.data["deny_path"] = self.run_path(since, t_answer, outcome.mono, result)
        else:
            result.data.update(approval_evidence(approval))
            expired_after = round(outcome.mono - t_pending, 1)
            result.data["expired_after_s"] = expired_after
            if state != "expired" or calls != 0 or not 105 <= expired_after <= 150:
                result.fail(f"timeout: outcome {state} after {expired_after} s, "
                            f"apply_calls {calls}")
            result.data["timeout_path"] = self.run_path(since, t_pending + 100,
                                                        outcome.mono, result)

    def run_path(self, since: int, t_from: float, t_outcome: float,
                 result: RunResult) -> str:
        """How the R4/P4 run ended after ``t_from`` (``clean``/``error_fallback``/
        ``unknown``); the error text goes to ``sam_error_text``."""
        def approval_run(e: Ev) -> bool:
            return (e.kind == "sam_run" and e.data.get("rule") in APPROVAL_RULES
                    and e.mono >= t_from - 1)
        self.sse.wait(since, approval_run, max(0.0, t_outcome + PATH_WINDOW_S
                                               - time.monotonic()))
        runs = self.sse.select(since, approval_run)
        errors = [str(e.data.get("error") or "") for e in runs if not e.data.get("ok")]
        result.data["sam_error_text"] = " | ".join(t for t in errors if t)[:TEXT_MAX]
        window = max(PATH_WINDOW_S, t_outcome - t_from + PATH_WINDOW_S)
        return approval_path([(e.mono, bool(e.data.get("ok"))) for e in runs], t_from,
                             window)

    def next_scan(self, result: RunResult) -> None:
        """A7: the next AddArticle of the same article shows the new price."""
        article = next(a for a in self.catalog.values()
                       if a["article_number"] == result.data.get("article"))
        mark = self.sse.mark()
        tx_id = str(self.pos("CreatePurchaseTransaction", {}).get("purchaseTransactionId", ""))
        self.scan(tx_id, article)
        row = self.sse.wait(mark, lambda e: e.kind == "pos_event" and e.data.get("tx_id")
                            == tx_id and e.data.get("event") == "PositionAdded", 10)
        self.pos("CancelPurchaseTransaction", {"purchaseTransactionId": tx_id,
                                               "cancellationReason": "e2e",
                                               "cancellationReasonCode": "ABANDONED"})
        ok = bool(row) and row.data.get("price_source") == "BOOTH_ACTION" and row.data.get(
            "price") == result.data.get("new_price")
        result.data["a7_next_scan_ok"] = ok
        if not ok:
            result.fail(f"next scan: {row.data if row else 'no PositionAdded'}")

    # checks ---------------------------------------------------------------
    def check_expectation(self, result: RunResult) -> None:
        expect = EXPECT[result.scenario]
        got = (result.data.get("review_state"), result.data.get("article", ""),
               result.data.get("reason", ""), result.data.get("new_price", ""))
        want = (expect.review_state, expect.article, expect.reason, expect.new_price)
        result.data["correct"] = got == want
        result.data["wrong_price"] = (got[0] == "proposed" and got != want)
        if not result.data["correct"]:
            result.fail(f"expected {want}, got {got}")

    def check_agent(self, since: int, result: RunResult) -> None:
        review_id = result.data.get("review_id")
        calls = self.sse.select(since, lambda e: e.kind == "tool_call" and e.data.get(
            "caller") == "agent" and e.data.get("ref") == review_id)
        tools = [(c.data.get("service"), c.data.get("tool"), c.data.get("ok")) for c in calls]
        result.data["agent_tools"] = [f"{s}.{t}" for s, t, _ in tools]
        result.data["api_queries"] = len(tools)
        expect = EXPECT[result.scenario]
        result.data["api_queries_ok"] = len(tools) == expect.api_queries
        if not result.data["api_queries_ok"] and result.scenario in TALK_TRACK_SCENARIOS:
            result.fail(f"api_queries {len(tools)}, talk track says {expect.api_queries} "
                        "(1.4, A8)")
        if not expect.agent:
            if tools:
                result.fail("agent tools called although no AI run was expected (A12)")
            return
        if result.data.get("review_state") in ("proposed", "no_action"):
            if result.data.get("ai_model") != "planning":
                result.fail(f"decision.model {result.data.get('ai_model')!r}, expected "
                            "'planning' (A8)")
            if not result.data.get("evidence_items"):
                result.fail("review without evidence items (note_evidence)")
        names = {t for _, t, _ in tools}
        wanted = {"get_transaction"} | ({"get_purchase_behaviour"} if expect.loyalty else set())
        if not wanted <= names or not any(s == "wws" for s, _, _ in tools):
            result.fail(f"agent check: {sorted(names)} lacks {sorted(wanted)} or a WWS call")
        if any(ok is False for _, _, ok in tools):
            result.fail("agent check: a tool call failed (rights?)")

    def awe_tools(self, seconds: float, since: float | None = None) -> AweTools:
        """Tool executions of our agents in the awe log (read-only kubectl logs) and the
        planner's robustness in the traces started since ``since`` (wall clock);
        raises ``OpsError`` when the log cannot be read."""
        ns, deploy = self.env.get("AWE_NS") or AWE[0], self.env.get("AWE_DEPLOY") or AWE[1]
        cmd = kubectl_base(self.env) + ["-n", ns, "logs", f"deploy/{deploy}", "-c", AWE[2],
                                        f"--since={int(seconds) + 30}s"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
        if proc.returncode != 0:
            raise OpsError(f"awe log unreadable (kubectl rc {proc.returncode})")
        return parse_awe(proc.stdout.splitlines(), self.agent_ids, since=since)

    # one run --------------------------------------------------------------
    def run_once(self, n: int) -> RunResult:
        result = RunResult(n, self.till, self.args.scenario, self.args.mode)
        started, started_wall = time.monotonic(), time.time()
        try:
            self.reset(result)
            if result.errors:
                return result
            since = self.sse.mark()
            tx_id = self.play(self.args.scenario, result)
            end = self.await_review(since, tx_id, result)
            self.scan_latencies(since, tx_id, result)
            if end is not None and end.data.get("state") == "proposed":
                self.approval_flow(since, result)
            self.check_expectation(result)
            self.check_agent(since, result)
        except Exception as exc:  # noqa: BLE001 -- one broken run must not end a series
            result.fail(f"{type(exc).__name__}: {exc}"[:300])
        try:
            awe = self.awe_tools(time.monotonic() - started, started_wall)
        except (OpsError, OSError, subprocess.SubprocessError) as exc:
            result.fail(f"awe log unreadable: {exc}"[:200])
            awe = None
        if awe is not None:
            result.data["awe_tools"] = awe.tools
            # UC1-30: reported only, a retried run that ends correct stays ok
            result.data.update(
                planner_attempts=planner_attempts(awe, result.data.get("review_state"),
                                                  result.data.get("a4b_evidence_decided_s")),
                planner_retry_lines=awe.recommend_retries,
                planner_internal_tool_calls=awe.planner_warnings)
            if self.args.mode in ("deny", "timeout") and "outcome" in result.data:
                result.data["awe_refusal"] = awe.refusals[-1] if awe.refusals else ""
                if self.args.mode == "deny":
                    result.data["awe_refusal_ok"] = result.data["awe_refusal"] == "denied"
            if self.args.mode == "timeout":     # format unverified: reported only
                result.data["awe_approver_tools"] = awe.tools.get(self.approver, [])
            for error in awe_checks(self.args.mode, result.data, awe, self.approver):
                result.fail(error)
        for key in [k for k in result.data if k.startswith("_")]:
            result.data.pop(key)
        return result


# --------------------------------------------------------------- orchestration


SEGMENTS = ("reset_s", "a1_scan_row_s", "a2_scan_insight_s", "a3_closed_prepared_s",
            "a4_closed_ready_s", "a4a_closed_evidence_s", "a4b_evidence_decided_s",
            "a5_ready_request_s", "a6_answer_applied_s", "answer_outcome_s",
            "expired_after_s")
PATHS = ("clean", "error_fallback", "unknown")


def planner_totals(results: list[RunResult]) -> dict[str, int]:
    """UC1-30: ``planner_retried_runs`` (runs with ``planner_attempts`` > 1) and the sum
    of ``planner_internal_tool_calls``; a run without awe data counts 0."""
    return {"planner_retried_runs": sum(1 for r in results
                                        if int(r.data.get("planner_attempts") or 0) > 1),
            "planner_internal_tool_calls": sum(int(r.data.get("planner_internal_tool_calls")
                                                   or 0) for r in results)}


def summary(results: list[RunResult]) -> dict[str, Any]:
    out: dict[str, Any] = {"summary": True, "runs": len(results),
                           "ok": sum(1 for r in results if not r.errors),
                           "correct": sum(1 for r in results if r.data.get("correct")),
                           "wrong_price": sum(1 for r in results if r.data.get("wrong_price")),
                           "duplicates": sum(len(r.data.get("duplicates", [])) for r in results),
                           **planner_totals(results)}
    for key in ("deny_path", "timeout_path"):
        paths = [r.data[key] for r in results if key in r.data]
        if paths:
            out[key + "s"] = {p: paths.count(p) for p in PATHS}
    for mode in ("deny", "timeout"):
        found = [r.data["evidence_path"] for r in results
                 if r.mode == mode and "evidence_path" in r.data]
        if found:
            out[f"{mode}_evidence"] = {p: found.count(p) for p in EVIDENCE_PATHS}
    for key in SEGMENTS:
        values: list[float] = []
        for r in results:
            v = r.data.get(key)
            values += v if isinstance(v, list) else ([v] if isinstance(v, (int, float)) else [])
        if values:
            out[key] = {"n": len(values), "p50": percentile(values, 0.5),
                        "p90": percentile(values, 0.9), "p95": percentile(values, 0.95),
                        "mean": round(statistics.fmean(values), 3)}
    return out


def run_series(e2e: E2E, runs: int, out: Path) -> list[RunResult]:
    results = []
    with out.open("a", encoding="utf-8") as handle:
        for n in range(1, runs + 1):
            result = e2e.run_once(n)
            line = json.dumps(result.line(), ensure_ascii=False)
            print(line, flush=True)
            handle.write(line + "\n")
            results.append(result)
    return results


def gate_path_lines(results: list[RunResult]) -> list[str]:
    """``deny_paths``/``timeout_paths`` (counts per path, a run without a path counts as
    ``unknown``), ``deny_evidence``/``timeout_evidence`` (the engine's evidence path per
    run, same counting) and ``timeout_text`` (first timeout run with a text, <= 200
    chars) of build/gate-verified."""
    lines = []
    for mode in ("deny", "timeout"):
        paths = [str(r.data.get(f"{mode}_path", "unknown")) for r in results if r.mode == mode]
        lines.append(f"{mode}_paths=" + json.dumps({p: paths.count(p) for p in PATHS}))
    for mode in ("deny", "timeout"):
        found = [str(r.data.get("evidence_path", "unknown")) for r in results
                 if r.mode == mode]
        lines.append(f"{mode}_evidence="
                     + json.dumps({p: found.count(p) for p in EVIDENCE_PATHS}))
    texts = (" ".join(str(r.data.get("status_reason") or r.data.get("sam_error_text")
                          or "").split()) for r in results if r.mode == "timeout")
    lines.append(f"timeout_text={next((t for t in texts if t), '')[:TEXT_MAX]}")
    return lines


def gate_planner_lines(results: list[RunResult]) -> list[str]:
    """``planner_retried_runs`` (retried/all runs) and ``planner_internal_tool_calls``
    of build/gate-verified (UC1-30; reported only, PASS does not depend on them)."""
    totals = planner_totals(results)
    return [f"planner_retried_runs={totals['planner_retried_runs']}/{len(results)}",
            f"planner_internal_tool_calls={totals['planner_internal_tool_calls']}"]


def gate_verify(env: Mapping[str, str], base: argparse.Namespace, out: Path,
                fallback_f2: bool) -> bool:
    """9.9: S1 approve x3 + deny x5 (A9) + timeout x2 (A10) on probe till 98
    (:data:`GATE_MODES`), then reset of store 199. PASS needs every run ok (fail-closed
    awe checks included), the evidence agent and the approver in the awe log, no tool of
    the planner, the reset and the topic. Only a PASS record lets scripts/install.sh mesh
    apply the booth entrypoint (9.8 step 7). The hash is taken before the first run:
    an edit during the ~11 min never inherits this result."""
    verified_hash = gate_hash(fallback_f2=fallback_f2)
    results: list[RunResult] = []
    args = argparse.Namespace(**{**vars(base), "till": "98", "scenario": "S1",
                                 "mode": "approve", "answer_delay": 0.0,
                                 "fallback_f2": fallback_f2})
    e2e = E2E(env, args)
    e2e.preflight()
    for mode, runs in GATE_MODES:
        args.mode = mode
        results += run_series(e2e, runs, out)
    e2e.sse.stop.set()
    proc = kubectl_ui(env, ["-", "--reset-store", "199"],
                      stdin=(DEMO_DIR / "scripts" / "smoke.py").read_text("utf-8"))
    tools: dict[str, set[str]] = {}
    for r in results:
        for agent, names in r.data.get("awe_tools", {}).items():
            tools.setdefault(agent, set()).update(names)
    awe_ok = (EVIDENCE_AGENT in tools and e2e.approver in tools
              and not tools.get(PLANNER_AGENT))
    passed = all(not r.errors for r in results) and proc.returncode == 0 and awe_ok and all(
        "/199/" in str(r.data.get("price_change_topic", "/199/")) for r in results)
    awe_json = json.dumps({k: sorted(v) for k, v in sorted(tools.items())},
                          ensure_ascii=False)
    install = target_of(env)
    lines = [f"result={'PASS' if passed else 'FAIL'}",
             *([] if install == "lab" else [f"target={install}"]),
             f"hash={verified_hash}",
             f"modes={GATE_MODES_TEXT}",
             f"fallback_f2={'yes' if fallback_f2 else 'no'}",
             f"date={datetime.now().astimezone().isoformat(timespec='seconds')}",
             f"runs={sum(1 for r in results if not r.errors)}/{len(results)} ok",
             f"awe_tools={awe_json}",
             *gate_path_lines(results),
             *gate_planner_lines(results),
             f"log={out.relative_to(DEMO_DIR)}"]
    GATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    GATE_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary(results), ensure_ascii=False))
    shown = GATE_FILE.relative_to(DEMO_DIR) if GATE_FILE.is_relative_to(DEMO_DIR) else GATE_FILE
    print(f"gate verification: {'PASS' if passed else 'FAIL'} -> {shown}")
    return passed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--till", choices=tuple(TILLS), default="01")
    ap.add_argument("--scenario", choices=tuple(EXPECT), default="S1")
    ap.add_argument("--mode", choices=("approve", "deny", "timeout"), default="approve")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--answer-delay", type=float, default=0.0,
                    help="seconds after pending before answering (A10: 100)")
    ap.add_argument("--fallback-f2", action="store_true", help="hash includes mesh/fallback")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--gate-verify", action="store_true", help="make gate-verify (9.9)")
    group.add_argument("--gate-status", action="store_true", help="exit 0 if verified")
    args = ap.parse_args(argv)
    try:
        if args.gate_status:
            current_target()
            return 0 if gate_verified(fallback_f2=args.fallback_f2) else 1
        env = demo_env()
        out = BUILD / "e2e" / f"e2e-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock("e2e.py"):
            if args.gate_verify:
                return 0 if gate_verify(env, args, out, args.fallback_f2) else 1
            e2e = E2E(env, args)
            e2e.preflight()
            results = run_series(e2e, args.runs, out)
            e2e.sse.stop.set()
            print(json.dumps(summary(results), ensure_ascii=False))
            return 0 if all(not r.errors for r in results) else 1
    except OpsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
