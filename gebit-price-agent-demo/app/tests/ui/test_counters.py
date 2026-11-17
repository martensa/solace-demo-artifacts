"""Booth counters of 10.2: since the last reset, only 101/01, probe rules never; agent
runs per model alias (fast evidence, planning recommendation, fast approver)."""

from __future__ import annotations

from typing import Any

import pytest

from gposdemo.ui.counters import Counters

BOOTH = {"store": "101", "till": "01"}
PROBE = {"store": "199", "till": "98"}
S1_POS_EVENTS = (
    "PurchaseTransactionCreated", "PurchaseTransactionOpened", "PositionAdded",
    "FiscalTransactionAssigned", "PositionAdded", "PositionAdded", "PaymentProcessStarted",
    "CashPaymentPositionCreated", "CashPaymentPositionCreated", "PaymentProcessCompleted",
    "PurchaseTransactionInChargingFinancialTransaction", "PurchaseTransactionInClosing",
    "PurchaseTransactionClosed")
# telemetry of S1 in run order (7.2, 8.2-8.4): service, tool, caller, ref
S1_TOOL_CALLS = (
    ("engine", "assess_event", "workflow", "tx-1:3"),
    ("engine", "raise_basket_review", "workflow", "tx-1"),
    ("engine", "prepare_review", "workflow", "GR-1"),
    ("pos", "get_transaction", "agent", "GR-1"),
    ("wws", "get_sales_performance", "agent", "GR-1"),
    ("engine", "note_evidence", "workflow", "GR-1"),
    ("engine", "stage_proposal", "workflow", "GR-1"),
    ("engine", "check_proposal", "workflow", "GP-1"),
    ("gate", "apply_price", "agent", "GP-1"),
    ("engine", "record_outcome", "workflow", "GP-1"),
)


# 8.2.2 evidence document of S1 (note_evidence) and the planning decision (stage_proposal)
S1_EVIDENCE = {"model": "fast", "tx": "closed", "items": [
    {"a": "100001", "name": "GEBIT Ente (Quietscheente gelb)", "reason": "slow_seller",
     "holds": "yes", "numbers": "trend=falling; sold_7d=9; plan_7d=35; weeks_of_supply=6.5; "
     "weekly_first=34; weekly_last=9", "tools": ["get_sales_performance"]}]}
S1_DECISION = {"decision": "propose", "article_number": "100001", "reason": "slow_seller",
               "step_pct": "20", "headline": "GEBIT Ente: Preis senken",
               "rationale": "Abverkauf fällt.", "facts_line": "9 von 35", "model": "planning"}


def review(state: str, rid: str = "GR-1", where: dict[str, str] = BOOTH,
           **extra: Any) -> dict[str, Any]:
    return {"state": state, "review_id": rid, **where, **extra}


def play_s1(counters: Counters, where: dict[str, str] = BOOTH, rules: str = "r") -> None:
    """The events of the main demo S1 (1.4), as the BFF receives them."""
    for event in S1_POS_EVENTS:
        counters.on_event("pos_event", {"event": event, "tx_id": "tx-1", **where})
    for rule in ("1", "1", "1", "1", "3"):
        counters.on_event("sam_run", {"rule": f"{rules}{rule}", "ok": True})
    counters.on_event("review", review("requested", where=where))
    counters.on_event("review", review("prepared", where=where))
    for service, tool, caller, ref in S1_TOOL_CALLS[:5]:
        counters.on_event("tool_call", {"service": service, "tool": tool, "caller": caller,
                                        "ref": ref})
    # note_evidence publishes "prepared" again, now with the evidence (7.1)
    counters.on_event("review", review("prepared", where=where, evidence=S1_EVIDENCE))
    for service, tool, caller, ref in S1_TOOL_CALLS[5:]:
        counters.on_event("tool_call", {"service": service, "tool": tool, "caller": caller,
                                        "ref": ref})
    counters.on_event("review", review("proposed", where=where, evidence=S1_EVIDENCE,
                                       decision=S1_DECISION))
    for state in ("ready", "pending", "approved"):
        counters.on_event("proposal", {"state": state, "proposal_id": "GP-1", **where})
    counters.on_event("price_change", {"event": "PriceChangeApplied", "store": where["store"]})
    # record_outcome publishes the outcome again, then R4 finishes
    counters.on_event("proposal", {"state": "approved", "proposal_id": "GP-1", **where})
    counters.on_event("sam_run", {"rule": f"{rules}4", "ok": True})


def values(counters: Counters) -> dict[str, Any]:
    data = counters.to_dict()
    return {k: data[k] for k in ("pos_events", "sam_runs", "agent_runs", "agent_tool_calls",
                                 "approvals", "rejections", "price_changes")}


def test_s1_gives_the_numbers_of_1_4() -> None:
    counters = Counters("101", "01")
    play_s1(counters)
    assert values(counters) == {"pos_events": 13, "sam_runs": 6, "agent_runs": 3,
                                "agent_tool_calls": 2, "approvals": 1, "rejections": 0,
                                "price_changes": 1}
    data = counters.to_dict()
    assert data["sam_runs_by_rule"] == {"r1": 4, "r3": 1, "r4": 1}
    assert data["agent_runs_by_model"] == {"fast": 2, "planning": 1}
    assert data["line"] == ("13 Kassenereignisse → 6 SAM-Läufe → 3 KI-Agenten-Läufe "
                            "(fast 2, planning 1) · 2 API-Abfragen der Agenten → "
                            "1 Freigabe(n)")


def test_evidence_counts_once_per_review_although_every_later_event_carries_it() -> None:
    counters = Counters("101", "01")
    assert counters.on_event("review", review("prepared", evidence=S1_EVIDENCE))
    assert not counters.on_event("review", review("prepared", evidence=S1_EVIDENCE))
    assert counters.on_event("review", review("proposed", evidence=S1_EVIDENCE,
                                              decision=S1_DECISION))
    assert not counters.on_event("review", review("proposed", evidence=S1_EVIDENCE,
                                                  decision=S1_DECISION))
    assert counters.to_dict()["agent_runs_by_model"] == {"fast": 1, "planning": 1}


def test_legacy_review_without_evidence_and_model_counts_once_fast() -> None:
    """Old R3 against the new engine (deploy window) or legacy data: missing model = fast."""
    counters = Counters("101", "01")
    legacy = {k: v for k, v in S1_DECISION.items() if k != "model"}
    counters.on_event("review", review("proposed", decision=legacy))
    counters.on_event("review", review("proposed", decision=legacy))
    counters.on_event("review", review("no_action", rid="GR-2",
                                       decision={"decision": "no_action", "rationale": "x",
                                                 "model": ""}))
    data = counters.to_dict()
    assert data["agent_runs"] == 2
    assert data["agent_runs_by_model"] == {"fast": 2, "planning": 0}


def test_blocked_with_a_planning_decision_counts_planning() -> None:
    counters = Counters("101", "01")
    counters.on_event("review", review("blocked", evidence=S1_EVIDENCE, decision=S1_DECISION,
                                       error="KI-Empfehlung ohne bestätigten Beleg"))
    # blocked without a decision (no AI recommendation) counts nothing
    counters.on_event("review", review("blocked", rid="GR-2"))
    assert counters.to_dict()["agent_runs_by_model"] == {"fast": 1, "planning": 1}
    assert values(counters)["agent_runs"] == 2


def test_failed_review_counts_only_the_evidence_run() -> None:
    counters = Counters("101", "01")
    counters.on_event("review", review("prepared", evidence=S1_EVIDENCE))
    counters.on_event("review", review("failed", evidence=S1_EVIDENCE,
                                       error="Agent reported error: planning timed out"))
    counters.on_event("review", review("failed", rid="GR-2", decision=S1_DECISION))
    assert counters.to_dict()["agent_runs_by_model"] == {"fast": 1, "planning": 0}
    assert values(counters)["agent_runs"] == 1


def test_unknown_evidence_model_counts_as_fast() -> None:
    counters = Counters("101", "01")
    counters.on_event("review", review("prepared", evidence={"model": "sonnet", "items": []}))
    counters.on_event("review", review("proposed", rid="GR-2",
                                       decision={**S1_DECISION, "model": None}))
    assert counters.to_dict()["agent_runs_by_model"] == {"fast": 2, "planning": 0}


def test_probe_till_and_probe_rules_never_count() -> None:
    counters = Counters("101", "01")
    play_s1(counters, where=PROBE, rules="p")
    # the agent's tool calls carry the ref of a probe-till review: left out as well
    assert values(counters) == dict.fromkeys(values(counters), 0)
    assert counters.to_dict()["agent_runs_by_model"] == {"fast": 0, "planning": 0}


def test_agent_tool_calls_with_unknown_ref_count() -> None:
    counters = Counters("101", "01")
    counters.on_event("review", {"state": "requested", "review_id": "GR-9", **PROBE})
    assert not counters.on_event("tool_call", {"service": "pos", "tool": "get_transaction",
                                               "caller": "agent", "ref": "GR-9"})
    assert counters.on_event("tool_call", {"service": "pos", "tool": "get_transaction",
                                           "caller": "agent", "ref": ""})
    assert not counters.on_event("tool_call", {"service": "engine", "tool": "assess_event",
                                               "caller": "workflow", "ref": ""})
    assert values(counters)["agent_tool_calls"] == 1


@pytest.mark.parametrize("service, counted", [
    ("pos", True), ("wws", True), ("loyalty", True), ("gate", False), ("engine", False)])
def test_only_the_three_api_families_are_agent_api_queries(service: str,
                                                            counted: bool) -> None:
    """10.2/1.4: "API-Abfragen der Agenten" are the calls on Kasse, Warenwirtschaft and
    Loyalty; the approver's gated apply_price (caller agent, 8.3) is none."""
    counters = Counters("101", "01")
    assert counters.on_event("tool_call", {"service": service, "tool": "t",
                                           "caller": "agent", "ref": "GR-1"}) is counted
    assert values(counters)["agent_tool_calls"] == int(counted)


def test_rejection_and_expiry_count_as_fast_approver_runs() -> None:
    counters = Counters("101", "01")
    counters.on_event("proposal", {"state": "rejected", "proposal_id": "GP-1", **BOOTH})
    counters.on_event("proposal", {"state": "rejected", "proposal_id": "GP-1", **BOOTH})
    counters.on_event("proposal", {"state": "expired", "proposal_id": "GP-2", **BOOTH})
    counters.on_event("proposal", {"state": "superseded", "proposal_id": "GP-3", **BOOTH})
    counters.on_event("proposal", {"state": "failed", "proposal_id": "GP-4", **BOOTH})
    assert values(counters) == {"pos_events": 0, "sam_runs": 0, "agent_runs": 2,
                                "agent_tool_calls": 0, "approvals": 0, "rejections": 1,
                                "price_changes": 0}
    assert counters.to_dict()["agent_runs_by_model"] == {"fast": 2, "planning": 0}


def test_review_without_ai_is_no_agent_run() -> None:
    counters = Counters("101", "01")
    for state in ("no_candidates", "only_blocked", "deferred", "failed", "superseded"):
        counters.on_event("review", {"state": state, "review_id": f"GR-{state}", **BOOTH})
    assert values(counters)["agent_runs"] == 0
    # S8: fast belegt steigenden Abverkauf, planning empfiehlt no_action (A12: 2 runs)
    evidence = {"model": "fast", "tx": "closed", "items": [
        {"a": "100002", "name": "Plüschhase", "reason": "slow_seller", "holds": "no",
         "numbers": "trend=rising", "tools": ["get_sales_performance"]}]}
    counters.on_event("review", review("prepared", rid="GR-8", evidence=evidence))
    counters.on_event("review", review("no_action", rid="GR-8", evidence=evidence,
                                       decision={"decision": "no_action", "rationale": "x",
                                                 "model": "planning"}))
    assert values(counters)["agent_runs"] == 2
    assert counters.to_dict()["agent_runs_by_model"] == {"fast": 1, "planning": 1}


def test_duplicate_signal_and_foreign_price_changes_do_not_count() -> None:
    counters = Counters("101", "01")
    counters.on_event("proposal", {"state": "approved", "proposal_id": "GP-1",
                                   "signal": "duplicate_request", **BOOTH})
    counters.on_event("price_change", {"event": "PriceChangeApplied", "store": "199"})
    counters.on_event("price_change", {"event": "PriceChangeEnded", "store": "101"})
    assert values(counters) == dict.fromkeys(values(counters), 0)


def test_reset_and_version() -> None:
    counters = Counters("101", "01")
    start = counters.version
    assert counters.on_event("pos_event", {"event": "PositionAdded", **BOOTH})
    assert not counters.on_event("pos_event", {"event": "PositionAdded", **PROBE})
    assert counters.version == start + 1
    counters.reset()
    assert counters.version == start + 2
    assert values(counters) == dict.fromkeys(values(counters), 0)
    assert counters.to_dict()["sam_runs_by_rule"] == {"r1": 0, "r3": 0, "r4": 0}


def test_reset_clears_the_runs_by_model() -> None:
    counters = Counters("101", "01")
    play_s1(counters)
    assert counters.to_dict()["agent_runs_by_model"] == {"fast": 2, "planning": 1}
    counters.reset()
    data = counters.to_dict()
    assert data["agent_runs_by_model"] == {"fast": 0, "planning": 0}
    assert "(fast 0, planning 0)" in data["line"]
    # after the reset the same review counts again (a new demo run)
    play_s1(counters)
    assert counters.to_dict()["agent_runs_by_model"] == {"fast": 2, "planning": 1}


@pytest.mark.parametrize("rule", ["p1", "p3", "p4"])
def test_probe_rules_are_ignored(rule: str) -> None:
    counters = Counters("101", "01")
    assert not counters.on_event("sam_run", {"rule": rule, "ok": False})
    assert values(counters)["sam_runs"] == 0
