"""Pure parts of scripts/e2e.py and the gate hash (spec 1.3, 6.8, 9.9, 13.4)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import e2e
from conftest import ROOT, load
from opslib import GATE_MODES, GATE_MODES_TEXT, OpsError, gate_hash, gate_verified


def test_golden_outcomes_of_the_scenarios() -> None:
    assert {k: (v.review_state, v.article, v.reason, v.new_price)
            for k, v in e2e.EXPECT.items()} == {
        "S1": ("proposed", "100001", "slow_seller", "7,99"),
        "S2": ("proposed", "100008", "season_end", "5,49"),
        "S3": ("proposed", "100012", "customer_behaviour", "12,99"),
        "S4": ("no_candidates", "", "", ""),
        "S5": ("only_blocked", "", "", ""),
        "S6": ("no_candidates", "", "", ""),
        "S7": ("proposed", "100008", "season_end", "5,49"),
        "S8": ("no_action", "", "", ""),
    }
    assert [k for k, v in e2e.EXPECT.items() if not v.agent] == ["S4", "S5", "S6"]   # A12
    assert [k for k, v in e2e.EXPECT.items() if v.loyalty] == ["S3"]
    assert {k: v.api_queries for k, v in e2e.EXPECT.items()} == {
        "S1": 2, "S2": 2, "S3": 3, "S4": 0, "S5": 0, "S6": 0, "S7": 3, "S8": 2}
    assert e2e.TALK_TRACK_SCENARIOS == ("S1",)
    assert e2e.OUR_AGENTS[:2] == ("gpos-pricing-agent", "gpos-price-planner")


def test_cash_is_the_next_full_five_euro() -> None:
    assert e2e.cash_cents(Decimal("16.98")) == 2000
    assert e2e.cash_cents(Decimal("20.00")) == 2000
    assert e2e.cash_cents(Decimal("20.01")) == 2500
    assert e2e.cash_cents(Decimal("0.99")) == 500


def test_percentiles_and_summary() -> None:
    assert e2e.percentile([], 0.5) is None
    assert e2e.percentile([4.0, 1.0, 3.0, 2.0], 0.5) == 2.5
    assert e2e.percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.9) == 4.6
    runs = [e2e.RunResult(1, "01", "S1", "approve", data={
                "a4_closed_ready_s": 9.0, "a1_scan_row_s": [0.2, 0.3], "correct": True,
                "duplicates": ["cancel"], "a4a_closed_evidence_s": 5.0,
                "a4b_evidence_decided_s": 6.5}),
            e2e.RunResult(2, "01", "S1", "approve", errors=["x"], data={
                "a4_closed_ready_s": 11.0, "a1_scan_row_s": [0.4], "wrong_price": True})]
    out = e2e.summary(runs)
    assert (out["runs"], out["ok"], out["correct"], out["wrong_price"], out["duplicates"]) == (
        2, 1, 1, 1, 1)
    assert out["a4_closed_ready_s"]["p50"] == 10.0 and out["a1_scan_row_s"]["n"] == 3
    assert out["a4a_closed_evidence_s"]["n"] == out["a4b_evidence_decided_s"]["n"] == 1
    assert "deny_paths" not in out
    deny = [e2e.RunResult(n, "98", "S1", "deny", data={"deny_path": p})
            for n, p in enumerate(("clean", "error_fallback", "clean"), 1)]
    assert e2e.summary(deny)["deny_paths"] == {"clean": 2, "error_fallback": 1, "unknown": 0}
    timeout = [e2e.RunResult(1, "98", "S1", "timeout", data={"timeout_path": "clean"})]
    assert e2e.summary(timeout)["timeout_paths"] == {"clean": 1, "error_fallback": 0,
                                                     "unknown": 0}


def test_scenario_steps_match_data_scenarios_when_present() -> None:
    path = ROOT / "data" / "scenarios.yaml"
    if not path.is_file():
        pytest.skip("data/scenarios.yaml (WP-B) not written yet")
    ids = [s["id"] for s in load("data/scenarios.yaml")]
    assert set(e2e.EXPECT) <= set(ids)


def copy_mesh(tmp_path: Path) -> Path:
    for rel in ("mesh/connectors", "mesh/agents", "mesh/workflows", "mesh/fallback"):
        shutil.copytree(ROOT / rel, tmp_path / rel)
    return tmp_path


def test_gate_hash_tracks_connectors_agents_and_workflows(tmp_path: Path) -> None:
    root = copy_mesh(tmp_path)
    base, f2 = gate_hash(root), gate_hash(root, fallback_f2=True)
    assert base != f2
    (root / "mesh/fallback/manifest.yaml").write_text("changed")
    assert gate_hash(root) == base and gate_hash(root, fallback_f2=True) != f2
    (root / "mesh/agents/gpos-price-approver.yaml").write_text("changed")
    assert gate_hash(root) != base


@pytest.mark.parametrize("workflow", ["gpos-price-approval.yaml", "gpos-basket-review.yaml"])
def test_gate_hash_tracks_the_workflows(tmp_path: Path, workflow: str) -> None:
    """R4 carries the deny/timeout split, R3 the planner stage (9.9 PASS criteria): a
    workflow-only change must rerun the gate verification (9.8 step 7)."""
    root = copy_mesh(tmp_path)
    base = gate_hash(root)
    path = root / "mesh/workflows" / workflow
    path.write_text(path.read_text() + "# changed\n")
    assert gate_hash(root) != base


def test_gate_verified_needs_pass_the_runs_and_the_current_hash(tmp_path: Path) -> None:
    root = copy_mesh(tmp_path)
    record = root / "build" / "gate-verified"
    record.parent.mkdir()
    assert not gate_verified(root)
    record.write_text(f"result=FAIL\nhash={gate_hash(root)}\nmodes={GATE_MODES_TEXT}\n")
    assert not gate_verified(root)
    record.write_text(f"result=PASS\nhash={gate_hash(root)}\n")
    assert not gate_verified(root)                       # no runs recorded: fail closed
    record.write_text(f"result=PASS\nhash={gate_hash(root)}\n"
                      "modes=approve:3,deny:1,timeout:1\n")
    assert not gate_verified(root)                       # older run plan without A9/A10
    record.write_text(f"result=PASS\nhash={gate_hash(root)}\nmodes={GATE_MODES_TEXT}\n")
    assert gate_verified(root)
    (root / "mesh/connectors/gpos-price-gate.yaml").write_text("changed")
    assert not gate_verified(root)                       # 9.8 step 7 reruns


def test_gate_runs_include_a9_and_a10() -> None:
    """13.5 A9 (deny x5) and A10 (timeout x2) are mandatory before the booth entrypoint
    and therefore part of the gate verification (9.9)."""
    assert dict(GATE_MODES) == {"approve": 3, "deny": 5, "timeout": 2}
    assert GATE_MODES_TEXT == "approve:3,deny:5,timeout:2"


def test_gate_record_lines_count_paths_per_mode() -> None:
    results = [e2e.RunResult(1, "98", "S1", "approve", data={}),
               e2e.RunResult(2, "98", "S1", "deny", data={"deny_path": "clean"}),
               e2e.RunResult(3, "98", "S1", "deny", data={"deny_path": "error_fallback"}),
               e2e.RunResult(4, "98", "S1", "deny", errors=["x"], data={}),
               e2e.RunResult(5, "98", "S1", "timeout", data={"timeout_path": "clean"}),
               e2e.RunResult(6, "98", "S1", "timeout", data={
                   "timeout_path": "error_fallback", "status_reason": "Abgelaufen  in\nSAM"})]
    lines = dict(line.split("=", 1) for line in e2e.gate_path_lines(results))
    assert json.loads(lines["deny_paths"]) == {"clean": 1, "error_fallback": 1, "unknown": 1}
    assert json.loads(lines["timeout_paths"]) == {"clean": 1, "error_fallback": 1,
                                                  "unknown": 0}
    assert lines["timeout_text"] == "Abgelaufen in SAM"


def test_gate_status_cli_uses_the_record(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(e2e, "gate_verified", lambda fallback_f2=False: fallback_f2)
    assert e2e.main(["--gate-status"]) == 1
    assert e2e.main(["--gate-status", "--fallback-f2"]) == 0


# ------------------------------------------------------------------ awe log (A-33)
AGENTS = [{"id": "01a1c9fe-7ab8-7ec8-899b-8a6701366f52", "name": "gpos-pricing-agent"},
          {"id": "01a1c9fe-0000-7ec8-899b-8a6701366f53", "name": "gpos-price-planner"},
          {"id": "01A1C9FE-1111-7EC8-899B-8A6701366F54", "name": "gpos-price-approver"},
          {"id": "01a1c9fe-2222-7ec8-899b-8a6701366f55", "name": "WebResearchAgent"}]


def awe_line(agent_id: str, tool: str, ok: bool = True, **extra: Any) -> str:
    """One awe JSON line in the layout observed on 12.11. (keys only)."""
    return json.dumps({"timestamp": "2026-11-12T11:00:00Z", "level": "INFO",
                       "message": f"tool execution {'succeeded' if ok else 'failed'}",
                       "component": "sam-awe", "agentName": agent_id, "tool": tool,
                       "sessionID": "s-1", "duration_ms": 12, **extra})


def test_agent_ids_are_normalised_for_the_awe_log() -> None:
    assert e2e.norm_agent_id("agent_01a1c9fe_7ab8_7ec8_899b_8a6701366f52") == \
        e2e.norm_agent_id("01a1c9fe-7ab8-7ec8-899b-8a6701366f52")
    ids = e2e.agent_id_map(AGENTS, e2e.OUR_AGENTS)
    assert sorted(ids.values()) == ["gpos-price-approver", "gpos-price-planner",
                                    "gpos-pricing-agent"]
    assert ids["01a1c9fe_1111_7ec8_899b_8a6701366f54"] == "gpos-price-approver"


def test_awe_parser_reads_the_observed_layout() -> None:
    ids = e2e.agent_id_map(AGENTS, e2e.OUR_AGENTS)
    lines = [
        awe_line("agent_01a1c9fe_7ab8_7ec8_899b_8a6701366f52", "get_transaction"),
        awe_line("agent_01a1c9fe_7ab8_7ec8_899b_8a6701366f52", "get_sales_performance"),
        awe_line("agent_01a1c9fe_1111_7ec8_899b_8a6701366f54", "apply_price", ok=False,
                 approvalRefusal="denied", error="tool_error"),
        awe_line("agent_01a1c9fe_2222_7ec8_899b_8a6701366f55", "web_search"),  # not ours
        json.dumps({"message": "node failed", "agentName": "workflow_01a1", "tool": "x"}),
        "not json", "[1, 2]",
        awe_line("gpos-price-planner", "list_artifacts"),   # name directly: counted
    ]
    awe = e2e.parse_awe(lines, ids)
    assert awe.tools == {"gpos-price-approver": ["apply_price"],
                         "gpos-price-planner": ["list_artifacts"],
                         "gpos-pricing-agent": ["get_sales_performance", "get_transaction"]}
    assert awe.refusals == ["denied"]
    assert e2e.parse_awe(lines, {}).tools == {"gpos-price-planner": ["list_artifacts"]}


def test_awe_checks_fail_closed() -> None:
    approver = "gpos-price-approver"
    empty = e2e.AweTools()
    data = {"agent_tools": ["pos.get_transaction"], "apply_calls_before": 0}
    errors = e2e.awe_checks("approve", data, empty, approver)
    assert [e.split(":")[0] for e in errors] == ["awe log not parsed", "awe log not parsed"]
    full = e2e.AweTools({"gpos-pricing-agent": ["get_transaction"],
                         approver: ["apply_price"]})
    assert e2e.awe_checks("deny", data, full, approver) == []
    # timeout: the approver line is reported only (format unverified)
    assert e2e.awe_checks("timeout", data, e2e.AweTools(
        {"gpos-pricing-agent": ["get_transaction"]}), approver) == []
    # no agent API query (S4-S6): nothing to find in the log
    assert e2e.awe_checks("approve", {}, empty, approver) == []
    planner = e2e.AweTools({**full.tools, "gpos-price-planner": ["get_article"]})
    assert e2e.awe_checks("approve", data, planner, approver) == [
        "planner called a tool: ['get_article']"]
    artifact = e2e.AweTools({**full.tools, "gpos-pricing-agent": ["list_artifacts"]})
    assert e2e.awe_checks("approve", data, artifact, approver) == [
        "artifact tool(s) called: ['list_artifacts'] (hard rule 5)"]


@pytest.mark.parametrize("agent,tool", [
    ("gpos-price-approver", "delete_artifact"),
    ("gpos-price-approver", "artifact_grep"),
    ("gpos-pricing-agent", "query_data_with_sql"),
    ("gpos-pricing-agent", "reinterpret_artifact"),
    ("gpos-price-approver-f2", "create_chart_from_plotly_config"),
])
def test_awe_checks_flag_every_excluded_tool(agent: str, tool: str) -> None:
    """Hard rule 5 / A-21 (review UC1-29): all 12 excluded tools fail a run, also for
    the evidence agent and the approvers (the planner fails on any tool anyway)."""
    approver = "gpos-price-approver"
    data = {"agent_tools": ["pos.get_transaction"], "apply_calls_before": 0}
    tools = {"gpos-pricing-agent": ["get_transaction"], approver: ["apply_price"]}
    tools[agent] = sorted(tools.get(agent, []) + [tool])
    assert e2e.awe_checks("deny", data, e2e.AweTools(tools), approver) == [
        f"artifact tool(s) called: ['{tool}'] (hard rule 5)"]


def test_awe_checks_expect_the_gated_tool_of_the_f2_approver() -> None:
    """F2 (9.9): the agent calls only the gated builtin time tool; apply_price runs in
    a workflow tool node and never appears for the agent in the awe log."""
    f2 = "gpos-price-approver-f2"
    data = {"agent_tools": ["pos.get_transaction"], "apply_calls_before": 0}
    evidence = {"gpos-pricing-agent": ["get_transaction"]}
    for mode in ("approve", "deny"):
        assert e2e.awe_checks(mode, data, e2e.AweTools(
            {**evidence, f2: ["get_current_time"]}), f2) == []
        assert e2e.awe_checks(mode, data, e2e.AweTools(evidence), f2) == [
            f"awe log not parsed: no get_current_time of {f2}"]
    lines = [awe_line(f2, "get_current_time", ok=False, approvalRefusal="denied"),
             awe_line("gpos-pricing-agent", "get_article", approvalRefusal="denied")]
    awe = e2e.parse_awe(lines, {})
    assert awe.tools[f2] == ["get_current_time"] and awe.refusals == ["denied"]


def test_unreadable_awe_log_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = object.__new__(e2e.E2E)
    runner.agent_ids = {}
    calls: list[list[str]] = []

    def run(cmd: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", "forbidden")

    monkeypatch.setattr(e2e.subprocess, "run", run)
    with pytest.raises(OpsError, match="awe log unreadable"):
        runner.awe_tools(60)
    assert calls[0][:7] == ["kubectl", "-n", "sam-solace-lab", "logs",
                            "deploy/agent-mesh-solace-agent-mesh-awe", "-c", "awe"]


def test_preflight_needs_every_agent_on_the_platform() -> None:
    class Sam:
        def __init__(self, agents: list[dict]) -> None:
            self.agents = agents

        def list_all(self, path: str) -> list[dict]:
            assert path == "/api/v2/platform/agents"
            return self.agents

    runner = object.__new__(e2e.E2E)
    runner.approver = "gpos-price-approver"
    runner.sam = Sam(AGENTS)
    runner.resolve_agents()
    assert len(runner.agent_ids) == 3
    runner.sam = Sam(AGENTS[:1] + AGENTS[2:])
    with pytest.raises(OpsError, match="gpos-price-planner"):
        runner.resolve_agents()
    runner.approver = "gpos-price-approver-f2"
    runner.sam = Sam(AGENTS)
    with pytest.raises(OpsError, match="gpos-price-approver-f2"):
        runner.resolve_agents()


def test_approval_path_of_deny_and_timeout_runs() -> None:
    assert e2e.approval_path([(103.0, True)], 100.0) == "clean"
    assert e2e.approval_path([(101.8, False)], 100.0) == "error_fallback"
    assert e2e.approval_path([(80.0, True), (111.0, False)], 100.0) == "unknown"
    assert e2e.approval_path([(150.0, True)], 100.0, 60) == "clean"
    assert e2e.approval_path([], 100.0) == "unknown"


def test_gate_verify_runs_a9_a10_and_records_them(monkeypatch: pytest.MonkeyPatch,
                                                  tmp_path: Path) -> None:
    """--gate-verify runs GATE_MODES in order and writes the record gate_verified reads
    (no SAM: E2E, run_series and kubectl are stubbed)."""
    calls: list[tuple[str, int]] = []

    class FakeSse:
        stop = type("S", (), {"set": lambda self: None})()

    class FakeE2E:
        def __init__(self, env: Any, args: Any) -> None:
            self.args, self.approver, self.sse = args, e2e.APPROVER_AGENTS[0], FakeSse()

        def preflight(self) -> None:
            pass

    def fake_series(obj: Any, runs: int, out: Path) -> list[e2e.RunResult]:
        calls.append((obj.args.mode, runs))
        tools = {e2e.EVIDENCE_AGENT: ["get_transaction"], obj.approver: ["apply_price"]}
        return [e2e.RunResult(n, "98", "S1", obj.args.mode, data={"awe_tools": tools})
                for n in range(runs)]

    record = tmp_path / "gate-verified"
    monkeypatch.setattr(e2e, "E2E", FakeE2E)
    monkeypatch.setattr(e2e, "run_series", fake_series)
    monkeypatch.setattr(e2e, "GATE_FILE", record)
    monkeypatch.setattr(e2e, "kubectl_ui", lambda *a, **k: subprocess.CompletedProcess(a, 0))
    base = e2e.argparse.Namespace(till="01", scenario="S1", mode="approve", runs=1,
                                  answer_delay=0.0, fallback_f2=False)
    out = e2e.DEMO_DIR / "build" / "e2e" / "test.jsonl"
    assert e2e.gate_verify({}, base, out, False)
    assert calls == list(GATE_MODES)
    fields = dict(line.split("=", 1) for line in record.read_text().splitlines())
    assert (fields["result"], fields["modes"], fields["runs"]) == (
        "PASS", GATE_MODES_TEXT, "10/10 ok")
    assert fields["hash"] == gate_hash()
    assert json.loads(fields["deny_paths"])["unknown"] == 5     # stubs carry no path
    assert (fields["planner_retried_runs"], fields["planner_internal_tool_calls"]) == (
        "0/10", "0")


# ------------------------------------------------------------ engine evidence (UC1-29)
def approval_block(rule: str, path: str, message: str = "", agent: str | None = "error",
                   **extra: Any) -> dict[str, Any]:
    """``approval`` of ``GET /api/proposals/{id}`` with the ``evidence`` view."""
    return {"agent_status": agent, "apply_calls": 0, **extra,
            "evidence": {"rule": rule, "path": path, "tool_message": message,
                         "elapsed_s": 6.1}}


def test_approval_evidence_reads_the_engines_view() -> None:
    assert e2e.approval_evidence(approval_block("R5m", "message",
                                                "Tool call denied by user.")) == {
        "agent_status": "error", "evidence_path": "message", "engine_rule": "R5m",
        "tool_message": "Tool call denied by user."}
    assert e2e.approval_evidence(approval_block("R5", "status", agent="denied"))[
        "evidence_path"] == "status"
    assert e2e.approval_evidence(approval_block("R6", "error", agent=None)) == {
        "agent_status": "", "evidence_path": "error", "engine_rule": "R6",
        "tool_message": ""}
    assert e2e.approval_evidence(approval_block("R3b", "window"))["evidence_path"] == "window"
    # older engine, watchdog ending, odd values: unknown, never an exception
    for approval in (None, {}, {"agent_status": "denied", "evidence": None},
                     {"evidence": "R5"}, approval_block("R1", "price_change")):
        assert e2e.approval_evidence(approval)["evidence_path"] == "unknown"
    long = e2e.approval_evidence(approval_block("R7m", "message", "x  y\n" * 100))
    assert len(long["tool_message"]) == e2e.TEXT_MAX and "\n" not in long["tool_message"]
    assert e2e.EVIDENCE_PATHS == ("status", "message", "error", "window", "unknown")


def checker(mode: str, approval: dict[str, Any]) -> Any:
    """An E2E whose BFF and SSE reads are stubbed (check_outcome only)."""
    runner = object.__new__(e2e.E2E)
    runner.args = e2e.argparse.Namespace(mode=mode)
    runner.apply_calls = lambda pid: (int(approval.get("apply_calls") or 0), approval)
    runner.run_path = lambda *a, **k: "clean"
    return runner


@pytest.mark.parametrize(("rule", "path", "agent"), [
    ("R5", "status", "denied"), ("R5m", "message", "error"), ("R6", "error", None)])
def test_deny_passes_on_every_evidence_path(rule: str, path: str, agent: str | None) -> None:
    """A9: rejected without a price is the acceptance, whichever evidence decided."""
    result = e2e.RunResult(1, "98", "S1", "deny")
    outcome = e2e.Ev(102.0, "proposal", {"state": "rejected"})
    checker("deny", approval_block(rule, path, agent=agent)).check_outcome(
        "GP-1", outcome, 100.0, 90.0, 0, result)
    assert result.errors == []
    assert (result.data["evidence_path"], result.data["engine_rule"],
            result.data["agent_status"], result.data["deny_path"]) == (
        path, rule, agent or "", "clean")


def test_deny_still_fails_without_rejection_or_with_a_price() -> None:
    failed = e2e.RunResult(1, "98", "S1", "deny")
    checker("deny", approval_block("R8", "status")).check_outcome(
        "GP-1", e2e.Ev(102.0, "proposal", {"state": "failed"}), 100.0, 90.0, 0, failed)
    assert failed.errors == ["deny: outcome failed, apply_calls 0"]
    assert failed.data["evidence_path"] == "status"
    priced = e2e.RunResult(2, "98", "S1", "deny")
    checker("deny", approval_block("R5m", "message", apply_calls=1)).check_outcome(
        "GP-1", e2e.Ev(102.0, "proposal", {"state": "rejected"}), 100.0, 90.0, 0, priced)
    assert priced.errors == ["deny: outcome rejected, apply_calls 1"]


def test_timeout_reports_the_engines_evidence() -> None:
    result = e2e.RunResult(1, "98", "S1", "timeout")
    checker("timeout", approval_block("R3a", "message",
                                      "Tool approval timed out after 2 minutes.",
                                      agent="timeout")).check_outcome(
        "GP-1", e2e.Ev(221.0, "proposal", {"state": "expired"}), 100.0, 100.0, 0, result)
    assert result.errors == []
    assert (result.data["evidence_path"], result.data["engine_rule"],
            result.data["agent_status"], result.data["expired_after_s"]) == (
        "message", "R3a", "timeout", 121.0)


def test_summary_and_gate_record_count_the_evidence_paths() -> None:
    results = [e2e.RunResult(1, "98", "S1", "approve", data={}),
               e2e.RunResult(2, "98", "S1", "deny", data={"evidence_path": "message"}),
               e2e.RunResult(3, "98", "S1", "deny", data={"evidence_path": "message"}),
               e2e.RunResult(4, "98", "S1", "deny", data={"evidence_path": "status"}),
               e2e.RunResult(5, "98", "S1", "deny", errors=["x"], data={}),
               e2e.RunResult(6, "98", "S1", "timeout", data={"evidence_path": "window"})]
    out = e2e.summary(results)
    assert out["deny_evidence"] == {"status": 1, "message": 2, "error": 0, "window": 0,
                                    "unknown": 0}
    assert out["timeout_evidence"]["window"] == 1 and "approve_evidence" not in out
    lines = dict(line.split("=", 1) for line in e2e.gate_path_lines(results))
    assert json.loads(lines["deny_evidence"]) == {"status": 1, "message": 2, "error": 0,
                                                  "window": 0, "unknown": 1}
    assert json.loads(lines["timeout_evidence"])["window"] == 1


# ------------------------------------------------------- planner robustness (UC1-30)
PLANNER_ID = "agent_01a1c9fe_0000_7ec8_899b_8a6701366f53"     # gpos-price-planner of AGENTS
EVIDENCE_ID = "agent_01a1c9fe_7ab8_7ec8_899b_8a6701366f52"
REVIEW_WF = "workflow_01a1cec5_8663_7d20_83ff_b15e50188140"
SINCE = "2026-11-12T16:26:40Z"                                 # wall clock of the run start
DROP = ("dropping LLM-generated _notify_artifact_save call — synthesising error so "
        "the LLM retries")
CONT = "LLM emitted internal continuation call; auto-continuing"


def awe_entry(message: str, ts: str, **fields: Any) -> str:
    """One awe JSON line with its own time (layout of 12.11., keys only)."""
    return json.dumps({"timestamp": ts, "level": "INFO", "message": message,
                       "component": "sam-awe", "contextID": "", **fields})


def review_trace(trace: str, ts: str, workflow: str = REVIEW_WF,
                 tool: str = e2e.REVIEW_TOOL) -> list[str]:
    """The start lines of one gpos-basket-review run and its first tool call (lab
    layout: key ``agent``, no ``agentName``)."""
    return [*(awe_entry(m, ts, agentName=workflow, traceID=trace, taskID=f"wf-{trace}")
              for m in e2e.WORKFLOW_START),
            awe_entry("mcp_tool_call", ts, agent=workflow, tool=tool, traceID=trace)]


def planner_line(message: str, ts: str, trace: str = "t-run", task: str = "p-1",
                 level: str = "WARN", **fields: Any) -> str:
    return awe_entry(message, ts, level=level, logger_name="agent", agentName=PLANNER_ID,
                     traceID=trace, taskID=task, sessionID="s-1", **fields)


def stuck_run_lines() -> list[str]:
    """Lab 12.11. (third gate run): the previous run's stuck planner logs on under its
    own trace while this run's review starts; this run's first attempt gets stuck."""
    return [
        *review_trace("t-prev", "2026-11-12T16:25:35.811290215Z"),
        planner_line(CONT, "2026-11-12T16:26:54.730Z", trace="t-prev", task="p-prev"),
        *review_trace("t-run", "2026-11-12T16:26:48.143Z"),
        planner_line(DROP, "2026-11-12T16:27:00.927038867Z", id="tooluse_1"),
        planner_line(CONT, "2026-11-12T16:27:07.100Z", implicitContinuations="1"),
        planner_line(CONT, "2026-11-12T16:27:12.100Z", implicitContinuations="2"),
        planner_line("implicit continuation limit reached; treating response as final",
                     "2026-11-12T16:27:30.976Z"),
        # the agent's own retry inside the same sub-task: neither warning nor node retry
        planner_line("structured invocation retry (main loop)", "2026-11-12T16:27:30.977Z",
                     level="INFO", nodeID="recommend", retry="1"),
        # card line of the planner (no trace, no task): no sub-task
        awe_entry("published initial agent card", "2026-11-12T16:27:20Z",
                  agentName=PLANNER_ID),
        # a warning of the evidence agent is not the planner's
        awe_entry(CONT, "2026-11-12T16:26:52Z", level="WARN", agentName=EVIDENCE_ID,
                  traceID="t-run", taskID="e-1"),
        # a planner warning without traceID counts by its own time
        awe_entry(CONT, "2026-11-12T16:27:25Z", level="WARN", agentName=PLANNER_ID,
                  taskID="p-1"),
        awe_entry(CONT, "2026-11-12T16:26:10Z", level="WARN", agentName=PLANNER_ID,
                  taskID="p-prev"),
    ]


def test_awe_parser_counts_the_planners_internal_tool_calls_of_this_run(
        monkeypatch: pytest.MonkeyPatch) -> None:
    ids = e2e.agent_id_map(AGENTS, e2e.OUR_AGENTS)
    since = e2e.iso_seconds(SINCE)
    awe = e2e.parse_awe(stuck_run_lines(), ids, since=since)
    assert (awe.planner_warnings, awe.planner_tasks, awe.recommend_retries,
            awe.recommend_seen) == (4, 1, 0, True)
    assert awe.tools == {}                         # no tool execution: no planner tool
    # without a run start every trace counts (the previous run's lines included)
    everything = e2e.parse_awe(stuck_run_lines(), ids)
    assert (everything.planner_warnings, everything.planner_tasks) == (6, 2)
    # E2E.awe_tools hands the run start to the parser
    runner = object.__new__(e2e.E2E)
    runner.agent_ids = ids
    monkeypatch.setattr(e2e.subprocess, "run", lambda cmd, **_kw: subprocess.CompletedProcess(
        cmd, 0, "\n".join(stuck_run_lines()), ""))
    assert runner.awe_tools(90, since).planner_warnings == 4
    assert e2e.PLANNER_WARNINGS == ("dropping LLM-generated _notify_artifact_save call",
                                    "LLM emitted internal continuation call")


def test_awe_parser_counts_each_retry_of_recommend_once() -> None:
    """SAM's retry lines (format from the awe binary, not lab-verified): a retry logged
    with both messages counts once; other nodes and earlier traces do not count."""
    since = e2e.iso_seconds(SINCE)

    def node_line(message: str, ts: str, trace: str = "t-run", **fields: Any) -> str:
        return awe_entry(message, ts, agentName=REVIEW_WF, traceID=trace, taskID="wf",
                         **fields)

    lines = [*review_trace("t-prev", "2026-11-12T16:25:35Z"),
             node_line("retrying node", "2026-11-12T16:26:42Z", trace="t-prev",
                       node="recommend"),
             *review_trace("t-run", "2026-11-12T16:26:48Z"),
             node_line("scheduling node retry", "2026-11-12T16:27:33Z", node="recommend",
                       attempt="1"),
             node_line("retrying node", "2026-11-12T16:27:34Z", node="recommend"),
             node_line("retrying node", "2026-11-12T16:27:00Z", node="gather")]
    awe = e2e.parse_awe(lines, {}, since=since)
    assert (awe.recommend_retries, awe.recommend_seen, awe.planner_tasks) == (1, True, 0)
    assert e2e.planner_attempts(awe, "proposed", 48.2) == 2
    alt = [*review_trace("t-run", "2026-11-12T16:26:48Z"),
           node_line("retrying node", "2026-11-12T16:27:34Z", nodeID="recommend")]
    assert e2e.parse_awe(alt, {}, since=since).recommend_retries == 1
    failed = [*review_trace("t-run", "2026-11-12T16:26:48Z"),
              node_line("node failed", "2026-11-12T16:27:18Z", node="recommend",
                        error='node "recommend" timed out after 30s')]
    awe = e2e.parse_awe(failed, {}, since=since)
    assert (awe.recommend_retries, awe.recommend_seen, awe.recommend_timed_out) == (
        0, True, True)
    # "node failed" on the per-attempt timeout comes after the last attempt
    assert e2e.planner_attempts(awe, "failed", None) == 1 + e2e.RECOMMEND_RETRIES == 2
    # lab 12.11. third gate run: older workflow, 50 s and no retry -> one attempt
    old = [*review_trace("t-run", "2026-11-12T16:26:48Z"),
           node_line("node failed", "2026-11-12T16:27:38Z", node="recommend",
                     error='node "recommend" timed out after 50s')]
    awe = e2e.parse_awe(old, {}, since=since)
    assert (awe.recommend_seen, awe.recommend_timed_out) == (True, False)
    assert e2e.planner_attempts(awe, "failed", None) == 1
    # node "recommend" of another workflow of the shared awe (no prepare_review in its
    # trace, e.g. sam-manufacturing-ops-demo supply-replenishment) is not ours
    other = "workflow_01a1cec5_9999_7d20_83ff_b15e50188141"
    foreign = [*review_trace("t-other", "2026-11-12T16:26:50Z", workflow=other,
                             tool="check_stock"),
               awe_entry("node failed", "2026-11-12T16:27:18Z", level="ERROR",
                         agentName=other, traceID="t-other", taskID="wf",
                         node="recommend", error='node "recommend" timed out after 30s'),
               awe_entry("retrying node", "2026-11-12T16:27:19Z", agentName=other,
                         traceID="t-other", taskID="wf", node="recommend")]
    awe = e2e.parse_awe(foreign, {}, since=since)
    assert (awe.recommend_retries, awe.recommend_seen, awe.recommend_timed_out) == (
        0, False, False)
    assert e2e.planner_attempts(awe, "no_candidates", None) == 0


def test_planner_attempts() -> None:
    none = e2e.AweTools()
    assert e2e.planner_attempts(none, "no_candidates", None) == 0     # S4-S6: no planner
    assert e2e.planner_attempts(none, "failed", None) == 0
    assert e2e.planner_attempts(none, "proposed", 12.4) == 1
    limit = e2e.RECOMMEND_TIMEOUT_S + e2e.STAGE_MARGIN_S
    assert e2e.planner_attempts(none, "no_action", limit) == 1
    # longer than one attempt can take: SAM retried even when the log shows no retry
    assert e2e.planner_attempts(none, "proposed", limit + 0.1) == 2
    assert e2e.planner_attempts(e2e.AweTools(recommend_retries=1, recommend_seen=True),
                                "proposed", 12.4) == 2
    assert e2e.planner_attempts(e2e.AweTools(planner_tasks=2, recommend_seen=True),
                                "failed", None) == 2
    # both attempts failed without a planner line under its own sub-task
    assert e2e.planner_attempts(e2e.AweTools(recommend_seen=True, recommend_timed_out=True),
                                "failed", None) == 2


def test_planner_constants_follow_the_workflow_and_the_watchdog() -> None:
    """RECOMMEND_TIMEOUT_S is the per-attempt timeout of node recommend, the only node
    of the planner and of that id in our workflows; REVIEW_WAIT_S outlasts R3 and the
    engine watchdog, so a retried review does not fail the run."""
    review = load("mesh/workflows/gpos-basket-review.yaml")["spec"]["appConfig"]
    by_id = {n["id"]: n for n in review["nodes"]}
    recommend = by_id[e2e.PLANNER_NODE]
    assert recommend["agent_name"] == e2e.PLANNER_AGENT
    assert int(recommend["timeout"].rstrip("s")) == e2e.RECOMMEND_TIMEOUT_S
    assert recommend["retry_strategy"]["limit"] == e2e.RECOMMEND_RETRIES
    assert recommend["retry_strategy"]["retry_policy"] == "Always"
    others = [load(f"{root}/workflows/{name}.yaml")["spec"]["appConfig"]["nodes"]
              for root, name in (("mesh", "gpos-pos-event"), ("mesh", "gpos-price-approval"),
                                 ("mesh/fallback", "gpos-price-approval"))]
    assert not [n for ns in others for n in ns if n["id"] == e2e.PLANNER_NODE
                or n.get("agent_name") == e2e.PLANNER_AGENT]
    # REVIEW_TOOL is the first node of gpos-basket-review and called by no other workflow
    assert review["nodes"][0]["tool"] == e2e.REVIEW_TOOL
    assert not [n for ns in others for n in ns if n.get("tool") == e2e.REVIEW_TOOL]
    app = str(ROOT / "app")
    if app not in sys.path:
        sys.path.insert(0, app)
    from gposdemo.engine.watchdog import INTERVAL_S, REVIEW_PREPARED_TIMEOUT_S
    workflow_s = int(review["workflow_timeout"].rstrip("s"))
    assert e2e.REVIEW_WAIT_S >= REVIEW_PREPARED_TIMEOUT_S + INTERVAL_S > workflow_s


def test_summary_and_gate_record_report_planner_robustness() -> None:
    results = [e2e.RunResult(1, "98", "S1", "approve", data={
                   "planner_attempts": 2, "planner_internal_tool_calls": 6}),
               e2e.RunResult(2, "98", "S1", "approve", data={
                   "planner_attempts": 1, "planner_internal_tool_calls": 1}),
               e2e.RunResult(3, "98", "S1", "deny", errors=["x"], data={
                   "planner_attempts": 2, "planner_internal_tool_calls": 0}),
               e2e.RunResult(4, "98", "S1", "timeout", data={})]   # no awe data: 0
    out = e2e.summary(results)
    assert (out["planner_retried_runs"], out["planner_internal_tool_calls"]) == (2, 7)
    assert dict(line.split("=", 1) for line in e2e.gate_planner_lines(results)) == {
        "planner_retried_runs": "2/4", "planner_internal_tool_calls": "7"}
    assert e2e.summary([])["planner_retried_runs"] == 0


def test_a_retried_run_that_ends_correct_stays_ok() -> None:
    """run_once reports the planner fields from the awe log and the run start, and
    neither a retry nor internal-tool warnings fail the run."""
    runner = object.__new__(e2e.E2E)
    runner.till, runner.approver = "98", e2e.APPROVER_AGENTS[0]
    runner.args = e2e.argparse.Namespace(scenario="S1", mode="approve")
    runner.sse = type("S", (), {"mark": lambda self: 0})()
    seen: dict[str, Any] = {}

    def review(since: int, tx_id: str, result: e2e.RunResult) -> e2e.Ev:
        result.data.update(review_id="GR-1", review_state="proposed",
                           a4b_evidence_decided_s=48.2, _closed=1.0)
        return e2e.Ev(2.0, "review", {"state": "proposed"})

    def awe_tools(seconds: float, since: float | None = None) -> e2e.AweTools:
        seen["since"] = since
        return e2e.AweTools({e2e.EVIDENCE_AGENT: ["get_transaction"],
                             runner.approver: ["apply_price"]}, planner_warnings=5,
                            planner_tasks=1, recommend_retries=1, recommend_seen=True)

    runner.reset = lambda result: None
    runner.play = lambda scenario, result: "tx-1"
    runner.await_review = review
    runner.scan_latencies = lambda *a: None
    runner.approval_flow = lambda since, result: result.data.update(apply_calls_before=0)
    runner.check_expectation = lambda result: result.data.update(correct=True)
    runner.check_agent = lambda since, result: result.data.update(
        agent_tools=["pos.get_transaction", "wws.get_sales_performance"])
    runner.awe_tools = awe_tools
    line = runner.run_once(1).line()
    assert line["ok"] and line["errors"] == [] and "_closed" not in line
    assert (line["planner_attempts"], line["planner_retry_lines"],
            line["planner_internal_tool_calls"]) == (2, 1, 5)
    assert isinstance(seen["since"], float)
