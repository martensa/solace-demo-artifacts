"""Contracts without a database: agent input (8.2.1), SAM input keys (7.2), outcome table
(11.5 R1-R8), gate checks (11.4), tool lists, keyword calls and result sizes (8.1, 8.2,
8.2.2, 8.3, 5.1)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from gposdemo.common import mcputil
from gposdemo.common.jsonutil import compact
from gposdemo.engine import notify, signals, state
from gposdemo.engine.gate.service import F2_FUTURE_TOLERANCE_S, ApplyArgs, card_mismatch, guard
from gposdemo.engine.gate.tools import build_mcp as build_gate_mcp
from gposdemo.engine.models import (
    ApplyResult,
    AssessResult,
    CheckResult,
    EvidenceResult,
    OutcomeResult,
    PrepareReviewResult,
    ReviewTriggerResult,
    StageResult,
    StatusResult,
)
from gposdemo.engine.outcome import (
    APPROVED_AT_TOLERANCE_S,
    REASON_CONTRADICTION,
    REASON_DENY_AFTER_APPROVAL,
    REASON_DENY_TOO_EARLY,
    REASON_EXPIRED,
    REASON_NO_STATUS,
    REASON_REJECTED,
    REASON_REJECTED_ERROR,
    REASON_TECHNICAL,
    approval_time_ok,
    decide_outcome,
    evidence_text,
)
from gposdemo.engine.policy import Policy
from gposdemo.engine.records import ReviewRecord
from gposdemo.engine.review import (
    EVIDENCE_MAX_BYTES,
    NUMBERS_MAX,
    NUMBERS_SHORT,
    BasketView,
    Slot,
    agent_input,
    evidence_doc,
    fit,
    fit_evidence,
)
from gposdemo.engine.signals import Assessment
from gposdemo.engine.tools import build_mcp as build_engine_mcp
from tests.engine.fakes import CROISSANTS, ENTE, ESPRESSO, PRALINEN, ZONE, D, Facts
from tests.engine.test_texts_pricing import proposal

TX = "5b1f0c2e-8d1e-4a43-9a51-0c7a2f0e1b11"
S3_AGENT_INPUT = (
    '{"review_id":"GR-270216-0007","tx_id":"5b1f0c2e-8d1e-4a43-9a51-0c7a2f0e1b11",'
    '"till":"01","card":{"membership_id":"M-1001","persona":"Kaffeepause",'
    '"consent_profiling":true},"candidates":[{"a":"100012","name":"Espresso Bohnen kräftig",'
    '"signals":["customer_behaviour"],"facts":"Stammartikel der Karte: zuletzt vor 35 Tagen '
    '(sonst alle 14 Tage); Kartenkunden kaufen 47 % seltener","suggested_step_pct":10,'
    '"max_step_pct":10}],"blocked":[],"no_action":["Butter-Croissants"]}')


def review(review_id: str = "GR-270216-0007") -> ReviewRecord:
    return ReviewRecord(review_id=review_id, tx_id=TX, store_id="101", till_id="01",
                        membership_id=None, status="requested", lines=[], agent_input=None,
                        agent_decision=None, run_id_raise=None, run_id_review=None, error=None,
                        created_at=datetime.now(ZONE), prepared_at=None, decided_at=None)


def evaluated(get_facts: Callable[..., Facts], policy: Policy, number: str,
              membership_id: str | None = None) -> Assessment:
    f = get_facts(number, membership_id=membership_id)
    return signals.evaluate(f.article, f.sales, f.season, f.behaviour, policy, D)


# ------------------------------------------------------------------ agent input (8.2.1)
def test_agent_input_of_s3_is_the_spec_example(get_facts: Callable[..., Facts],
                                               policy: Policy) -> None:
    view = BasketView([evaluated(get_facts, policy, ESPRESSO, "M-1001"),
                       evaluated(get_facts, policy, CROISSANTS, "M-1001")],
                      {"membership_id": "M-1001", "persona": "Kaffeepause",
                       "consent_profiling": True})
    text = agent_input(review(), view, policy)
    assert text == S3_AGENT_INPUT
    assert len(text.encode("utf-8")) == 469


def test_agent_input_of_s7_puts_season_end_first(get_facts: Callable[..., Facts],
                                                 policy: Policy) -> None:
    view = BasketView([evaluated(get_facts, policy, ENTE),
                       evaluated(get_facts, policy, PRALINEN)], None)
    doc = json.loads(agent_input(review(), view, policy))
    assert doc["card"] is None
    assert [(c["a"], c["suggested_step_pct"], c["max_step_pct"]) for c in doc["candidates"]] \
        == [(PRALINEN, 30, 30), (ENTE, 20, 20)]
    assert all("blocked" not in c for c in doc["candidates"])


FACTS = {"slow_seller": "9 von 35 geplanten Stück verkauft (7 Tage), Reichweite 6,5 Wochen, "
                         "Bestand 96",
         "season_end": "Saison Winter endet am 28.02. (12 Tage), Restbestand 120",
         "customer_behaviour": "Stammartikel der Karte: zuletzt vor 35 Tagen (sonst alle 14 "
                               "Tage); Kartenkunden kaufen 47 % seltener"}


def _synthetic(name: str, signal_list: tuple[str, ...], blocked: str = "",
               stock_value: int = 100) -> Assessment:
    facts = {s: FACTS[s] for s in signal_list}
    return Assessment(article_number=name[-6:], name=name, signals=signal_list, facts=facts,
                      blocked=blocked, max_step_pct=30 if signal_list else 0,
                      suggested_step_pct=20 if signal_list else 0,
                      line_facts="; ".join(facts.values()) or "läuft nach Plan (99/100)",
                      stock_value=Decimal(stock_value))


def overflow_view() -> BasketView:
    free = [_synthetic("Glühwein Sonderedition 100008", ("season_end", "slow_seller")),
            _synthetic("GEBIT Ente (Quietscheente gelb) 100001", ("slow_seller",), "", 500),
            _synthetic("Plüschhase Hoppel 25 cm 100002", ("slow_seller",), "", 400),
            _synthetic("Espresso Bohnen kräftig 100012", ("customer_behaviour",))]
    blocked = [_synthetic(f"Gesperrt {i} 10002{i}", ("slow_seller",), "Preisbindung")
               for i in range(4)]
    plain = [_synthetic(f"Artikel {i} 10003{i}", ()) for i in range(6)]
    return BasketView(free + blocked + plain, {"membership_id": "M-1001",
                                               "persona": "Kaffeepause",
                                               "consent_profiling": True})


def test_overflow_rule_keeps_agent_input_within_1000_bytes(policy: Policy) -> None:
    view = overflow_view()
    r = review()
    limits = policy.review
    free = sorted((a for a in view.assessments if a.free),
                  key=lambda a: (policy.priority(a.signals[0]), -a.stock_value))
    raw = {"review_id": r.review_id, "tx_id": r.tx_id, "till": r.till_id, "card": view.card,
           "candidates": [{"a": a.article_number, "name": a.name, "signals": list(a.signals),
                           "facts": a.line_facts, "suggested_step_pct": 20, "max_step_pct": 30}
                          for a in free],
           "blocked": [{"name": a.name, "why": a.blocked} for a in view.assessments
                       if a.blocked],
           "no_action": [a.name for a in view.assessments if not a.candidate]}
    assert 1300 <= len(compact(raw).encode()) <= 1600  # without the rule (spec: ~1380 B)
    text = agent_input(r, view, policy)
    doc = json.loads(text)
    assert len(text.encode("utf-8")) <= limits.agent_input_max_bytes
    assert all(len(c["facts"]) <= limits.facts_short_chars for c in doc["candidates"])
    assert any(c["facts"].endswith("…") for c in doc["candidates"])
    assert [c["a"] for c in doc["candidates"]][:2] == ["100008", "100001"]
    assert doc["card"]["membership_id"] == "M-1001"
    result = PrepareReviewResult(candidate="yes", review_id=r.review_id, tx_id=TX,
                                 membership_id="M-1001", lines=14, candidates=4,
                                 reason="has_candidates", agent_input=text)
    full, text_bytes = mcputil.measure(
        mcputil.structured_result("prepare_review", result, "yes 4 candidates"))
    assert full <= 1800 and text_bytes <= 1500


def test_overflow_steps_in_order(policy: Policy) -> None:
    doc: dict[str, Any] = {"candidates": [{"facts": "x" * 50}], "no_action": ["n" * 500],
                           "blocked": [{"name": "b" * 500, "why": "w"}]}
    assert fit(json.loads(json.dumps({**doc, "no_action": []})), policy)["blocked"]
    fitted = fit(json.loads(json.dumps(doc)), policy)
    assert fitted["no_action"] == [] and fitted["blocked"] == [{"name": "b" * 500, "why": "w"}]
    assert fitted["candidates"] == [{"facts": "x" * 50}]
    doc["blocked"].append({"name": "c" * 500, "why": "w"})
    fitted = fit(json.loads(json.dumps(doc)), policy)
    assert fitted["no_action"] == [] and fitted["blocked"] == []
    assert fitted["candidates"] == [{"facts": "x" * 50}]
    many = {"candidates": [{"name": f"{i}" * 250, "facts": "f" * 300} for i in range(6)],
            "no_action": [], "blocked": []}
    fitted = fit(many, policy)
    assert len(compact(fitted).encode()) <= 1000
    assert [c["name"][0] for c in fitted["candidates"]] == ["0", "1"]  # dropped from the end
    assert fitted["candidates"][0]["facts"] == "f" * 79 + "…"


# ------------------------------------------------------------------ SAM input keys (7.2)
def test_sam_input_payloads_have_exactly_the_declared_keys() -> None:
    r = review()
    assert state.review_request(r) == {"schema_version": "1", "review_id": "GR-270216-0007",
                                       "tx_id": TX, "store": "101", "till": "01"}
    assert tuple(state.review_request(r)) == state.REVIEW_REQUEST_KEYS
    p = proposal()
    assert state.approval_request(p) == {"schema_version": "1",
                                         "proposal_id": "GP-270216-0003", "store": "101",
                                         "till": "01"}
    assert tuple(state.approval_request(p)) == state.APPROVAL_REQUEST_KEYS


def test_proposal_payload_matches_the_7_2_example() -> None:
    p = proposal(status="ready", guardrails=[{"rule": "Nur Senkung", "ok": True}])
    body = state.proposal_payload(p, "ready", "run-1", "2026-11-11T14:20:01.412+01:00", ZONE)
    assert list(body) == [
        "schema_version", "type", "state", "ts", "proposal_id", "review_id", "store", "till",
        "article_number", "article_name", "reason", "reason_label", "step_pct", "clamped",
        "old_price", "new_price", "pct_shown", "pct_label", "ref30", "margin_pct_new",
        "base_price_label", "valid_to", "valid_to_label", "headline", "rationale",
        "facts_line", "note", "text_source", "ai_model", "run_id", "guardrails"]
    assert body["ai_model"] == ""                         # legacy: the UI shows fast
    assert state.proposal_payload(proposal(ai_model="planning"), "ready", "r", "ts",
                                  ZONE)["ai_model"] == "planning"
    assert (body["old_price"], body["new_price"], body["pct_label"], body["margin_pct_new"],
            body["valid_to"], body["valid_to_label"], body["reason_label"]) == (
        "9,99", "7,99", "−20 %", "22,6", "2027-02-23T20:00:00+01:00", "Di 23.02. 20:00",
        "Ladenhüter")
    approved = state.proposal_payload(
        proposal(status="approved", decided_at=datetime(2027, 2, 16, 15, tzinfo=ZONE)),
        "approved", "run-1", "ts", ZONE, action_id="PA-270216-0003")
    assert (approved["action_id"], approved["status_reason"]) == ("PA-270216-0003", "")
    assert approved["decided_at"].startswith("2027-02-16T15:00:00")


EVIDENCE = {"model": "fast", "tx": "closed", "items": [
    {"a": "100001", "name": "GEBIT Ente (Quietscheente gelb)", "reason": "slow_seller",
     "holds": "yes", "numbers": "trend=falling; sold_7d=9", "tools": ["get_sales_performance"]}]}


def test_review_payload_splits_evidence_and_decision() -> None:
    base = review()
    body = state.review_payload(base, "requested", "r", "ts")
    assert "evidence" not in body and "decision" not in body
    noted = replace(base, status="prepared", agent_decision={"evidence": EVIDENCE})
    body = state.review_payload(noted, "prepared", "r", "ts")
    assert body["evidence"] == EVIDENCE and "decision" not in body
    decided = replace(base, status="proposed", agent_decision={
        "decision": "propose", "article_number": "100001", "model": "planning",
        "evidence": EVIDENCE})
    body = state.review_payload(decided, "proposed", "r", "ts")
    assert body["evidence"] == EVIDENCE
    assert body["decision"] == {"decision": "propose", "article_number": "100001",
                                "model": "planning"}
    legacy = replace(base, status="no_action", agent_decision={"decision": "no_action",
                                                                "rationale": "x"})
    body = state.review_payload(legacy, "no_action", "r", "ts")
    assert body["decision"] == {"decision": "no_action", "rationale": "x"}
    assert "evidence" not in body


# ------------------------------------------------------------------ outcome table (11.5)
@pytest.mark.parametrize(("status", "change", "agent", "error", "last", "expected"), [
    ("pending", True, "denied", "", None, "approved"),
    ("pending", True, "", "Tool approval timed out after 2 minutes", None, "approved"),
    ("superseded", False, "applied", "", None, "superseded"),
    ("expired", False, "", "", None, "expired"),
    ("failed", False, "denied", "", "blocked", "failed"),
    ("pending", False, "", "Tool approval timed out after 2 minutes", None, "expired"),
    ("pending", False, "blocked", "", "blocked", "blocked"),
    ("pending", False, "denied", "", None, "rejected"),
    ("pending", False, "", "", None, "failed"),           # was rejected: no status (R8)
    ("pending", False, "", "agent crashed", None, "failed"),
    ("pending", False, "applied", "", None, "failed"),
])
def test_outcome_table(status: str, change: bool, agent: str, error: str, last: str | None,
                       expected: str) -> None:
    decision = decide_outcome(status=status, has_price_change=change, agent_status=agent,
                              error=error, last_apply_status=last, apply_error="Hash passt nicht",
                              status_reason="vorher")
    assert decision.outcome == expected


def test_outcome_reasons() -> None:
    def reason(**kw: object) -> str:
        args = {"status": "pending", "has_price_change": False, "agent_status": "",
                "error": "", "last_apply_status": None, "apply_error": None,
                "status_reason": None, **kw}
        return decide_outcome(**args).status_reason  # type: ignore[arg-type]

    assert reason(agent_status="applied") == "Agent-Antwort widerspricht der Datenbank"
    assert reason(last_apply_status="blocked", apply_error="Hash passt nicht") == \
        "Hash passt nicht"
    assert reason(error="x timed out") == "Keine Antwort binnen 2 Minuten"
    assert reason(status="failed", status_reason="SAM-Lauf abgebrochen") == \
        "SAM-Lauf abgebrochen"
    assert reason() == REASON_NO_STATUS == "Agent meldete keinen Status – kein neuer Preis"
    assert reason(agent_status="denied") == REASON_REJECTED == "Abgelehnt in Agent Mesh"


DENY_TEXT = "Agent reported error: Price approval was denied by store manager"
MODEL_TEXTS = ("Agent reported error: model refused to answer (stop_reason refusal)",
               "apply_price request was rejected by server (HTTP 500)",
               "Permission denied: connector scope missing")


def window(**kw: Any) -> tuple[str, str]:
    """``decide_outcome`` with the defaults of the R1-R8 table: pending, no price
    change, untouched gate, ``min_delay_s`` 3, ``hil_timeout_s`` 120."""
    args: dict[str, Any] = {"status": "pending", "has_price_change": False,
                            "agent_status": "", "error": "", "last_apply_status": None,
                            "apply_error": None, "status_reason": None, "apply_calls": 0,
                            "min_delay_s": 3.0, "hil_timeout_s": 120.0, **kw}
    decision = decide_outcome(**args)
    return decision.outcome, decision.status_reason


@pytest.mark.parametrize(("kw", "outcome", "reason"), [
    ({"agent_status": "denied", "elapsed_s": 6}, "rejected", REASON_REJECTED),
    ({"agent_status": "denied", "elapsed_s": 1}, "failed", REASON_DENY_TOO_EARLY),
    ({"agent_status": "denied", "elapsed_s": 6, "approved_at_ok": True}, "failed",
     REASON_DENY_AFTER_APPROVAL),
    ({"agent_status": "denied", "elapsed_s": 122}, "expired", REASON_EXPIRED),
    ({"agent_status": "denied", "apply_calls": 1, "elapsed_s": 6}, "failed",
     REASON_CONTRADICTION),
    ({"agent_status": "", "elapsed_s": 6}, "failed", REASON_NO_STATUS),
    ({"agent_status": "error", "elapsed_s": 6}, "failed", REASON_TECHNICAL),
    ({"agent_status": "timeout", "elapsed_s": 5}, "failed", REASON_TECHNICAL),
    ({"agent_status": "timeout", "elapsed_s": 122}, "expired", REASON_EXPIRED),
    ({"error": DENY_TEXT, "elapsed_s": 6}, "rejected", REASON_REJECTED_ERROR),
    ({"error": DENY_TEXT, "elapsed_s": 1}, "failed", DENY_TEXT),
    ({"error": DENY_TEXT, "elapsed_s": 125}, "expired", REASON_EXPIRED),
    ({"error": MODEL_TEXTS[2], "elapsed_s": 6}, "failed", MODEL_TEXTS[2]),
    ({"error": MODEL_TEXTS[2], "elapsed_s": 125}, "failed", MODEL_TEXTS[2]),
    ({"error": "Tool approval timed out after 2 minutes", "elapsed_s": 122}, "expired",
     REASON_EXPIRED),
    ({"error": "litellm Timeout: request timed out", "elapsed_s": 30}, "failed",
     "litellm Timeout: request timed out"),
    ({"error": "agent crashed", "elapsed_s": 125}, "expired", REASON_EXPIRED),
    ({"error": "agent crashed", "elapsed_s": 6}, "failed", "agent crashed"),
    ({"error": MODEL_TEXTS[0], "elapsed_s": 6}, "failed", MODEL_TEXTS[0]),
    ({"error": MODEL_TEXTS[1], "elapsed_s": 6}, "failed", MODEL_TEXTS[1]),
    ({"error": "timed out", "elapsed_s": None}, "expired", REASON_EXPIRED),   # legacy
    ({"agent_status": "applied", "elapsed_s": 125}, "failed", REASON_CONTRADICTION),
    ({"agent_status": "blocked", "last_apply_status": "blocked", "apply_error": "Hash",
      "elapsed_s": 6}, "blocked", "Hash"),
    ({"agent_status": "denied", "has_price_change": True, "elapsed_s": 6}, "approved", ""),
])
def test_outcome_rules_with_the_engine_clock(kw: dict[str, Any], outcome: str,
                                             reason: str) -> None:
    assert window(**kw) == (outcome, reason)


def test_outcome_rules_name_the_rule() -> None:
    rules = {decide_outcome(status="pending", has_price_change=False, agent_status=a,
                            error=e, last_apply_status=None, apply_error=None,
                            status_reason=None, elapsed_s=t).rule
             for a, e, t in (("denied", "", 6), ("", DENY_TEXT, 6), ("", "agent crashed", 125),
                             ("", "Tool approval timed out", 125), ("", "boom", 6),
                             ("", "", 6))}
    assert rules == {"R5", "R6", "R3b", "R3a", "R7", "R8"}
    sam = {message_decision(agent_status="error", tool_message=m, elapsed_s=6).rule
           for m in ("Tool call denied by user.", "Tool approval timed out after 2 minutes.")}
    assert sam == {"R5m", "R7m"}


# ---------------------------------------------- SAM's tool message as evidence (UC1-29)
SAM_DENIED = "Tool call denied by user."                 # SAM webui DB, task_events 12.11.
SAM_TIMEOUT = "Tool approval timed out after 2 minutes."
WHEN = {"early": 1.0, "window": 6.0, "after": 122.0}     # min_delay 3 s, window 120 s
EXPIRED_R3A = ("expired", REASON_EXPIRED, "R3a")
EXPIRED_R3B = ("expired", REASON_EXPIRED, "R3b")
TECHNICAL_R7M = ("failed", REASON_TECHNICAL, "R7m")
TOO_EARLY = ("failed", REASON_DENY_TOO_EARLY, "R5m")
# (message, when) -> (expected without, expected with a valid F2 approved_at) for the
# agent statuses error, denied and "" (the approver copies SAM's result status "error")
SAM_TABLE = {
    (SAM_DENIED, "early"): (TOO_EARLY, TOO_EARLY),
    (SAM_DENIED, "window"): (("rejected", REASON_REJECTED, "R5m"),
                             ("failed", REASON_DENY_AFTER_APPROVAL, "R5m")),
    (SAM_DENIED, "after"): (EXPIRED_R3B, EXPIRED_R3B),
    (SAM_TIMEOUT, "early"): (TECHNICAL_R7M, TECHNICAL_R7M),
    (SAM_TIMEOUT, "window"): (TECHNICAL_R7M, TECHNICAL_R7M),
    (SAM_TIMEOUT, "after"): (EXPIRED_R3A, EXPIRED_R3A),
}
# agent status "timeout" contradicts SAM's denial: no human denial (R8 technical)
TIMEOUT_AGENT = {
    (SAM_DENIED, "early"): ("failed", REASON_TECHNICAL, "R8"),
    (SAM_DENIED, "window"): ("failed", REASON_TECHNICAL, "R8"),
    (SAM_DENIED, "after"): EXPIRED_R3B,
    (SAM_TIMEOUT, "early"): TECHNICAL_R7M,
    (SAM_TIMEOUT, "window"): TECHNICAL_R7M,
    (SAM_TIMEOUT, "after"): EXPIRED_R3A,
}


def message_decision(**kw: Any) -> Any:
    args: dict[str, Any] = {"status": "pending", "has_price_change": False,
                            "agent_status": "", "error": "", "last_apply_status": None,
                            "apply_error": None, "status_reason": None, "apply_calls": 0,
                            "min_delay_s": 3.0, "hil_timeout_s": 120.0, **kw}
    return decide_outcome(**args)


@pytest.mark.parametrize("approved_ok", [False, True], ids=["no-time", "f2-time"])
@pytest.mark.parametrize("when", list(WHEN))
@pytest.mark.parametrize("agent", ["error", "denied", "", "timeout"])
@pytest.mark.parametrize("message", [SAM_DENIED, SAM_TIMEOUT], ids=["denied", "timed-out"])
def test_sams_tool_message_by_agent_status_and_clock(message: str, agent: str, when: str,
                                                     approved_ok: bool) -> None:
    """UC1-29 (11.5 R5m/R7m/R3a): SAM's exact texts as the approver copies them, for
    every agent status, before, inside and after the window, with and without F2 time."""
    decision = message_decision(agent_status=agent, tool_message=message,
                                elapsed_s=WHEN[when], approved_at_ok=approved_ok)
    if agent == "timeout":
        expected = TIMEOUT_AGENT[(message, when)]
    else:
        expected = SAM_TABLE[(message, when)][approved_ok]
    assert (decision.outcome, decision.status_reason, decision.rule) == expected
    assert decision.evidence == {"R3b": "window", "R8": "status"}.get(decision.rule,
                                                                      "message")


@pytest.mark.parametrize(("kw", "expected"), [
    # an unresolved reference is no evidence: the existing rules decide
    ({"agent_status": "error", "tool_message": "{{approve.output.message}}"},
     ("failed", REASON_TECHNICAL, "R8")),
    ({"agent_status": "", "tool_message": "{{ approve.output.message }}"},
     ("failed", REASON_NO_STATUS, "R8")),
    ({"agent_status": "denied", "tool_message": "{{approve.output.message}}"},
     ("rejected", REASON_REJECTED, "R5")),
    # legacy and F2 without message: unchanged
    ({"agent_status": "denied", "tool_message": ""}, ("rejected", REASON_REJECTED, "R5")),
    ({"agent_status": "error", "tool_message": ""}, ("failed", REASON_TECHNICAL, "R8")),
    # a technical result is never a human denial, whatever the agent calls it
    ({"agent_status": "denied", "tool_message": "MCP server gpos-price-gate unreachable"},
     ("failed", REASON_TECHNICAL, "R7m")),
    ({"agent_status": "error", "tool_message": "Connection refused"},
     ("failed", REASON_TECHNICAL, "R8")),
    # the gate's own message (touched gate) is not SAM's: the gate decides
    ({"agent_status": "error", "tool_message": SAM_DENIED, "apply_calls": 1,
      "last_apply_status": "superseded"}, ("failed", REASON_TECHNICAL, "R8")),
    ({"agent_status": "blocked", "tool_message": "Hash passt nicht", "apply_calls": 1,
      "last_apply_status": "blocked", "apply_error": "Hash passt nicht"},
     ("blocked", "Hash passt nicht", "R4")),
    # contradictions of SAM's denial: applied/blocked without the gate
    ({"agent_status": "applied", "tool_message": SAM_DENIED},
     ("failed", REASON_CONTRADICTION, "R8")),
    ({"agent_status": "other words", "tool_message": SAM_DENIED},
     ("rejected", REASON_REJECTED, "R5m")),
    # a technical or timeout error text beside SAM's denial wins
    ({"agent_status": "", "tool_message": SAM_DENIED, "error": "Permission denied: scope"},
     ("failed", "Permission denied: scope", "R7")),
    # a success message without a price change decides nothing
    ({"agent_status": "applied", "tool_message": "Neuer Preis 7,99 € aktiv"},
     ("failed", REASON_CONTRADICTION, "R8")),
    ({"agent_status": "applied", "tool_message": "Neuer Preis 7,99 € aktiv",
      "has_price_change": True}, ("approved", "", "R1")),
])
def test_tool_message_edge_cases(kw: dict[str, Any], expected: tuple[str, str, str]) -> None:
    decision = message_decision(elapsed_s=6.0, **kw)
    assert (decision.outcome, decision.status_reason, decision.rule) == expected


TOOL_ERRORS = ("Error executing tool apply_price: ClosedResourceError",
               "Tool execution failed", "MCP tool call failed",
               "tool call failed: context deadline exceeded",
               "Approval request could not be delivered")


@pytest.mark.parametrize("message", TOOL_ERRORS)
def test_a_failed_tool_call_called_denied_is_no_rejection(message: str) -> None:
    """Review UC1-29 no. 5: status ``denied`` beside a result message that reads like a
    failed call (no TECHNICAL word, class ``other``) is technical (R7m), never R5."""
    decision = message_decision(agent_status="denied", tool_message=message, elapsed_s=6.0)
    assert (decision.outcome, decision.status_reason, decision.rule,
            decision.evidence) == ("failed", REASON_TECHNICAL, "R7m", "message")
    error = message_decision(agent_status="error", tool_message=message, elapsed_s=6.0)
    assert (error.outcome, error.status_reason, error.rule) == ("failed", REASON_TECHNICAL,
                                                                "R8")


@pytest.mark.parametrize("message", ["Tool call denied.", "The user did not approve the "
                                     "tool call", "approved: no"])
def test_a_paraphrased_denial_with_status_denied_stays_rejected(message: str) -> None:
    """A paraphrase without SAM's context word and without error wording is no tool
    error: the clean status decides (R5), as before UC1-29."""
    decision = message_decision(agent_status="denied", tool_message=message, elapsed_s=6.0)
    assert (decision.outcome, decision.rule) == ("rejected", "R5")


@pytest.mark.parametrize(("agent", "message", "expected"), [
    # a technical result after the window is no timeout (R3b: no technical text)
    ("denied", "Connection refused", ("failed", REASON_TECHNICAL, "R7m")),
    ("error", "Connection refused", ("failed", REASON_TECHNICAL, "R8")),
    ("", "MCP server gpos-price-gate unreachable", ("failed", REASON_NO_STATUS, "R8")),
    # SAM's timeout text after the window stays the timeout
    ("error", SAM_TIMEOUT, EXPIRED_R3A),
    # deliberately unchanged (spec order R3b before R5m, 16.1 no. 37): a denial after
    # the window, and a non-technical tool error, are the window's timeout
    ("denied", SAM_DENIED, EXPIRED_R3B),
    ("error", SAM_DENIED, EXPIRED_R3B),
    ("denied", "Tool execution failed", EXPIRED_R3B),
    ("denied", "", EXPIRED_R3B),
])
def test_the_window_rule_needs_a_non_technical_message(agent: str, message: str,
                                                       expected: tuple[str, str, str]) -> None:
    """Review UC1-29 no. 4: R3b's "no technical text" covers ``tool_message`` too."""
    decision = message_decision(agent_status=agent, tool_message=message,
                                elapsed_s=WHEN["after"])
    assert (decision.outcome, decision.status_reason, decision.rule) == expected


def test_sams_timeout_message_without_checked_at_is_the_timeout() -> None:
    """R3a legacy (no check_proposal): a timeout text expires the proposal."""
    decision = message_decision(agent_status="error", tool_message=SAM_TIMEOUT)
    assert (decision.outcome, decision.rule, decision.evidence) == ("expired", "R3a",
                                                                    "message")
    denied = message_decision(agent_status="error", tool_message=SAM_DENIED)
    assert (denied.outcome, denied.rule) == ("failed", "R8")   # R5m needs the clock


def test_evidence_text_drops_unresolved_references() -> None:
    assert evidence_text("  Tool call denied\n by user.  ") == "Tool call denied by user."
    assert evidence_text("{{approve.output.message}}") == ""
    assert evidence_text("x {{ approve.output.message }} y") == ""
    assert evidence_text("") == evidence_text(None) == ""  # type: ignore[arg-type]


def test_evidence_paths_name_what_decided() -> None:
    paths = {message_decision(**kw).evidence for kw in (
        {"has_price_change": True}, {"status": "expired"},
        {"error": "Tool approval timed out", "elapsed_s": 125},
        {"agent_status": "denied", "elapsed_s": 125},
        {"last_apply_status": "blocked", "apply_calls": 1, "elapsed_s": 6},
        {"agent_status": "denied", "elapsed_s": 6},
        {"agent_status": "error", "tool_message": SAM_DENIED, "elapsed_s": 6},
        {"error": DENY_TEXT, "elapsed_s": 6})}
    assert paths == {"price_change", "state", "error", "window", "gate", "status",
                     "message"}


def test_approval_time_of_f2() -> None:
    checked = datetime(2027, 2, 16, 14, 0, tzinfo=ZONE)
    now = checked + timedelta(seconds=10)
    assert APPROVED_AT_TOLERANCE_S == F2_FUTURE_TOLERANCE_S
    assert approval_time_ok((checked + timedelta(seconds=4)).isoformat(), checked, now, 3)
    assert approval_time_ok((now + timedelta(seconds=2)).isoformat(), checked, now, 3)
    for bad in ("", "gestern", (checked + timedelta(seconds=2)).isoformat(),
                (now + timedelta(seconds=3)).isoformat(), "2027-02-16T14:00:05"):
        assert not approval_time_ok(bad, checked, now, 3), bad
    assert not approval_time_ok(now.isoformat(), None, now, 3)


# ------------------------------------------------------------------ gate checks (11.4)
def card_args(**changes: str) -> ApplyArgs:
    base = {"proposal_id": "GP-270216-0003", "proposal_hash": "0123456789",
            "article_name": "GEBIT Ente (Quietscheente gelb)", "old_price": "9,99",
            "new_price": "7,99", "pct_label": "-20 %", "reason_label": "Ladenhüter",
            "valid_to_label": "Di 23.02. 20:00"}
    return ApplyArgs(**{**base, **changes})


def test_card_matches_the_stored_proposal() -> None:
    p = proposal()
    assert card_mismatch(p, card_args(), ZONE) == ""
    assert card_mismatch(p, card_args(old_price="9.99", new_price=" 7,99 €"), ZONE) == ""
    assert card_mismatch(p, card_args(article_name="GEBIT Ente (Quietscheente gelb) "),
                         ZONE) == ""


@pytest.mark.parametrize(("field", "value"), [
    ("old_price", "10,99"), ("new_price", "6,99"), ("new_price", "sieben"),
    ("article_name", "GEBIT Ente"), ("pct_label", "−20 %"), ("pct_label", "-30 %"),
    ("reason_label", "Saisonende"), ("valid_to_label", "Mi 24.02. 20:00")])
def test_card_mismatch_names_the_field(field: str, value: str) -> None:
    assert card_mismatch(proposal(), card_args(**{field: value}), ZONE) == field


def test_guard_modes() -> None:
    checked = datetime(2027, 2, 16, 14, 0, tzinfo=ZONE)
    early, late = checked + timedelta(seconds=1.6), checked + timedelta(seconds=19)
    assert guard("block", checked, early, 3, "").action == "block"
    assert guard("block", checked, early, 3, "").message == \
        "Freigabe schneller als möglich – Gate prüfen"
    assert guard("block", checked, late, 3, "").action == "apply"
    assert (guard("warn", checked, early, 3, "").action,
            guard("warn", checked, early, 3, "").message) == (
        "warn", "Gate prüfen: Aufruf nach 1,6 s")
    assert guard("warn", checked, late, 3, "").action == "apply"
    ok = (checked + timedelta(seconds=10)).isoformat()
    assert guard("f2", checked, late, 3, ok).action == "apply"
    assert guard("f2", checked, early, 3, ok).action == "block"
    for bad in ("", "gestern", (checked + timedelta(seconds=2)).isoformat(),
                (late + timedelta(seconds=5)).isoformat(), "2027-02-16T14:00:10"):
        assert guard("f2", checked, late, 3, bad).action == "block", bad


# ------------------------------------------------------------------ tools and sizes
def test_booth_tool_list() -> None:
    tools = {t["name"]: t for t in mcputil.tools_list(build_engine_mcp(None, None))}
    assert list(tools) == ["assess_event", "raise_basket_review", "note_event",
                           "prepare_review", "note_evidence", "stage_proposal",
                           "close_review", "check_proposal", "record_outcome"]
    params = {name: list(t["inputSchema"]["properties"]) for name, t in tools.items()}
    assert params["note_evidence"] == [
        "review_id", "model", "tx_status", "c1_article", "c1_reason", "c1_holds", "c1_numbers",
        "c1_tools", "c2_article", "c2_reason", "c2_holds", "c2_numbers", "c2_tools", "run_id"]
    assert params["stage_proposal"] == ["review_id", "article_number", "reason", "step_pct",
                                        "headline", "rationale", "facts_line", "run_id",
                                        "model"]
    assert params["close_review"] == ["review_id", "outcome", "rationale", "run_id", "model"]
    assert params["record_outcome"] == ["proposal_id", "run_id", "agent_status", "action_id",
                                        "error", "approved_at", "tool_message"]
    assert tools["note_evidence"]["inputSchema"]["required"] == ["review_id"]
    for tool in tools.values():
        assert all(p["type"] == "string" for p in tool["inputSchema"]["properties"].values())
        assert "run_id" not in tool["inputSchema"].get("required", [])
        assert "outputSchema" in tool
    outputs = {name: list(t["outputSchema"]["properties"]) for name, t in tools.items()}
    assert outputs["prepare_review"] == list(PrepareReviewResult.model_fields)
    assert outputs["check_proposal"] == list(CheckResult.model_fields)
    assert outputs["note_evidence"] == ["status", "review_id", "checked", "holding",
                                        "evidence"]


class RecordingService:
    """Stands in for ``EngineService``: records the keyword arguments of each call."""

    RESULTS = {"note_evidence": EvidenceResult(status="noted", review_id="GR-1"),
               "stage_proposal": StageResult(status="ready"),
               "close_review": StatusResult(status="closed"),
               "record_outcome": OutcomeResult(outcome="rejected", proposal_id="GP-1")}

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Callable[..., Any]:
        def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args, kwargs))
            return self.RESULTS[name]
        return call


@pytest.mark.parametrize(("tool", "arguments", "value"), [
    ("stage_proposal", {"review_id": "GR-1", "article_number": "100001",
                        "reason": "slow_seller", "step_pct": "20", "headline": "h",
                        "rationale": "r", "facts_line": "f"}, ("model", "planning")),
    ("close_review", {"review_id": "GR-1", "outcome": "no_action", "rationale": "r"},
     ("model", "planning")),
    ("record_outcome", {"proposal_id": "GP-1"}, ("approved_at", "2027-02-16T14:00:05+01:00")),
    ("record_outcome", {"proposal_id": "GP-1", "agent_status": "error"},
     ("tool_message", "Tool call denied by user.")),
    ("note_evidence", {"review_id": "GR-1"}, ("model", "fast")),
])
def test_tools_call_the_service_with_keywords_only(tool: str, arguments: dict[str, str],
                                                   value: tuple[str, str]) -> None:
    """5.1: a new optional parameter after run_id reaches the service as itself."""
    service = RecordingService()
    mcp = build_engine_mcp(service, None)  # type: ignore[arg-type]
    asyncio.run(mcp.call_tool(tool, {**arguments, value[0]: value[1]}))
    [(name, args, kwargs)] = service.calls
    assert (name, args) == (tool, ())
    assert kwargs[value[0]] == value[1] and kwargs["run_id"] == ""
    assert {k: kwargs[k] for k in arguments} == arguments


# numbers of the evidence agent from the real tool results (UC1-32 measurement, prompt
# order of 9.4: get_purchase_behaviour before get_article)
S1_NUMBERS = ("trend=falling; sold_7d=9; plan_7d=35; weeks_of_supply=6.5; weekly_first=34; "
              "weekly_last=9")
S3_NUMBERS = ("overdue_factor=2.5; cardholder_drop_pct=46.7; days_since_last=35; "
              "median_interval_days=14; margin_pct=34.3; last_change=2027-01-11 12,99->14,49")
NUMBERS_160 = (S1_NUMBERS + "; " + S3_NUMBERS)[:160]     # ends "…; med", no blank
THREE_TOOLS = "get_purchase_behaviour, get_sales_performance, get_member_profile"


def evidence_review(*lines: tuple[str, str, str]) -> ReviewRecord:
    """A prepared review whose ``lines`` are free candidates ``(a, name, signal)``."""
    return replace(review(), status="prepared", lines=[
        {"article_number": a, "name": name, "signals": [signal], "candidate": True,
         "blocked": None} for a, name, signal in lines])


def item_size(doc: dict[str, Any], n: int) -> int:
    return len(compact(doc["items"][n]).encode("utf-8"))


@pytest.mark.parametrize("second", [
    ("100012", "Espresso Bohnen kräftig", "customer_behaviour"),   # S3 card, with Ente
    ("100028", "Kochbuch „Regional kochen“", "slow_seller")])      # 2nd longest name
def test_two_items_with_160_char_numbers_stay_unshortened(second: tuple[str, str, str]
                                                          ) -> None:
    """8.2.2 steps 5 and 10 (UC1-32, 16.1 Nr. 41): ``numbers`` keeps the 160 characters
    the evidence agent may write (9.4). Two such items with the longest article names of
    data/*.yaml, three tools and the longest enum values stay under the cap, so the
    60-character fallback never applies to a realistic basket."""
    assert (NUMBERS_MAX, NUMBERS_SHORT, len(NUMBERS_160)) == (160, 60, 160)
    rec = evidence_review(("100001", "GEBIT Ente (Quietscheente gelb)", "slow_seller"),
                          second)
    slots = [Slot("100001", "slow_seller", "maybe", NUMBERS_160, THREE_TOOLS),
             Slot(second[0], second[2], "maybe", NUMBERS_160, THREE_TOOLS)]
    doc = evidence_doc(rec, "planning", "not_closed", slots)
    assert [(i["a"], i["holds"], i["numbers"], len(i["tools"])) for i in doc["items"]] == [
        ("100001", "unknown", NUMBERS_160, 3), (second[0], "unknown", NUMBERS_160, 3)]
    size = len(compact(doc).encode("utf-8"))
    assert 740 < size <= EVIDENCE_MAX_BYTES - 30          # measured 755-765 B, margin
    longer = evidence_doc(rec, "fast", "closed", [
        Slot("100001", "slow_seller", "yes", S3_NUMBERS + "; " + S1_NUMBERS, "get_article")])
    [item] = longer["items"]                              # > 160: cut at a word end
    assert len(item["numbers"]) <= NUMBERS_MAX and item["numbers"].endswith("…")
    assert item["numbers"].startswith(S3_NUMBERS)


def test_s3_evidence_keeps_last_change() -> None:
    """GR-270216-0074/-0083: at 120 characters the engine cut S3 after ``margin_pct``, so
    ``last_change`` never reached the planner; at 160 the whole S3 evidence passes."""
    rec = evidence_review(("100012", "Espresso Bohnen kräftig", "customer_behaviour"))
    doc = evidence_doc(rec, "fast", "closed", [Slot(
        "100012", "customer_behaviour", "yes", S3_NUMBERS,
        "get_article, get_purchase_behaviour")])
    [item] = doc["items"]
    assert item["numbers"] == S3_NUMBERS and len(S3_NUMBERS) == 143
    assert item["tools"] == ["get_article", "get_purchase_behaviour"]
    s7 = evidence_doc(evidence_review(
        ("100008", "Herzpralinen Valentin", "season_end"),
        ("100001", "GEBIT Ente (Quietscheente gelb)", "slow_seller")), "fast", "closed", [
        Slot("100008", "season_end", "yes",
             "status=ended; days_to_end=-2; leftover_share=1.0; stock=46", "get_season_info"),
        Slot("100001", "slow_seller", "yes", S1_NUMBERS, "get_sales_performance")])
    assert len(compact(s7).encode("utf-8")) == 450                     # S7 in the lab
    assert [i["numbers"] for i in s7["items"]][1] == S1_NUMBERS


def test_max_evidence_result_fits_the_workflow_limits() -> None:
    """8.2.2: over the cap every ``numbers`` goes to 60 characters, then items from the
    end; the largest uncut document (two items, 160-character ``numbers``, longest names,
    three tools) gives an ``EvidenceResult`` < 1100 B. ``numbers`` full of ``"`` or ``\\``
    (escaped twice in the result) stays within the workflow limits (8.1): equal counts
    with a long name and three tools, and the worst case, a document just under the cap
    with the shortest name, no tools, short enums and unequal counts (1643 B)."""
    item = {"a": "100001", "name": "Kochbuch „Regional kochen“ Sonderausgabe mit Ümläuten",
            "reason": "customer_behaviour", "holds": "unknown",
            "numbers": "overdue_factor=2.5; " + "ä" * 140,
            "tools": ["get_purchase_behaviour", "get_sales_performance", "get_season_info"]}
    doc = fit_evidence({"model": "planning", "tx": "not_closed",
                        "items": [dict(item), {**item, "a": "100002"}]})
    assert len(item["numbers"]) == NUMBERS_MAX
    assert len(compact(doc).encode("utf-8")) <= EVIDENCE_MAX_BYTES
    assert len(doc["items"]) == 2 and all(len(i["numbers"]) <= 60 for i in doc["items"])
    assert doc["items"][0]["numbers"].endswith("…")
    huge = fit_evidence({"model": "fast", "tx": "closed", "items": [
        {**item, "a": str(n), "name": "N" * 300} for n in range(2)]})
    assert len(huge["items"]) == 1 and len(compact(huge).encode()) <= EVIDENCE_MAX_BYTES

    def measured(evidence: str) -> tuple[int, int]:
        result = EvidenceResult(status="noted", review_id="GR-270216-0007", checked=2,
                                holding=0, evidence=evidence)
        return mcputil.measure(mcputil.structured_result("note_evidence", result,
                                                         "noted 0/2"))

    largest = evidence_doc(
        evidence_review(("100001", "GEBIT Ente (Quietscheente gelb)", "customer_behaviour"),
                        ("100028", "Kochbuch „Regional kochen“", "customer_behaviour")),
        "planning", "not_closed",
        [Slot("100001", "customer_behaviour", "unknown", "n" * 200, THREE_TOOLS),
         Slot("100028", "customer_behaviour", "unknown", "n" * 200, THREE_TOOLS)])
    assert [len(i["numbers"]) for i in largest["items"]] == [160, 160]  # 159 + "…"
    full, text = measured(compact(largest))
    assert full <= 1800 and text <= 1500
    assert full < 1100
    for count in range(0, NUMBERS_MAX + 1, 8):     # " and \ are escaped twice in the result
        for char in ('"', "\\"):
            escaped = fit_evidence({"model": "planning", "tx": "not_closed", "items": [
                {**item, "a": str(n), "numbers": char * count} for n in range(2)]})
            assert len(compact(escaped).encode("utf-8")) <= EVIDENCE_MAX_BYTES
            full, text = measured(compact(escaped))
            assert full <= 1800 and text <= 1500, (char, count, full)
    worst = 0                       # least overhead: more of the 800 B are escapes
    for count in range(NUMBERS_MAX + 1):
        for char in ('"', "\\"):
            escaped = fit_evidence({"model": "fast", "tx": "closed", "items": [
                {"a": a, "name": "Butter", "reason": "season_end", "holds": "no",
                 "numbers": char * n, "tools": []}
                for a, n in (("100011", count), ("100023", NUMBERS_MAX))]})
            assert len(compact(escaped).encode("utf-8")) <= EVIDENCE_MAX_BYTES
            full, text = measured(compact(escaped))
            assert full <= 1800 and text <= 1500, (char, count, full)
            worst = max(worst, full)
    assert worst == 1643                         # 8.2.2: margin 157 B to 1800


def test_gate_tool_list() -> None:
    [tool] = mcputil.tools_list(build_gate_mcp(None, None))
    assert tool["name"] == "apply_price"
    assert list(tool["inputSchema"]["properties"]) == [
        "proposal_id", "proposal_hash", "article_name", "old_price", "new_price", "pct_label",
        "reason_label", "valid_to_label", "run_id", "approved_at"]
    assert list(tool["outputSchema"]["properties"]) == ["status", "proposal_id", "action_id",
                                                        "new_price", "message"]


def test_max_results_fit_the_workflow_limits() -> None:
    long_name = "Kochbuch „Regional kochen“ Sonderausgabe mit sehr langem Titel"
    rationale = "Ein sehr langer, aber zulässiger Begründungssatz mit Umlauten äöü. " * 4
    p = proposal(article_name=long_name, rationale=rationale[:240], facts_line="ü" * 120,
                 note="Rücknahme der Preiserhöhung vom 11.01.")
    title, message = notify.inform(p, ZONE, Decimal(20))
    check = CheckResult(status="awaiting_approval", proposal_id=p.proposal_id,
                        proposal_hash="0123456789", article_name=long_name, old_price="24,00",
                        new_price="19,99", pct_label="-20 %", reason_label="Kundenverhalten",
                        valid_to_label="Di 23.02. 20:00", notify_title=title,
                        notify_message=message)
    tell_title, tell_message = notify.tell("approved", p, ZONE, "PA-270216-0003", "")
    results = {
        "assess_event": AssessResult(verdict="scan", event_key=f"{TX}:123456",
                                     event_type="PurchaseTransactionCancelled", tx_id=TX,
                                     store="101", till="01", article_number="100028",
                                     insight_code="customer_behaviour", insight_text="ä" * 120),
        "raise_basket_review": ReviewTriggerResult(status="not_booth_or_test",
                                                   review_id="GR-270216-0007", tx_id=TX),
        "note_event": StatusResult(status="noted", event_key=f"{TX}:999999",
                                   verdict="duplicate"),
        "stage_proposal": StageResult(status="ready", proposal_id="GP-270216-0003",
                                      article_number="100028", article_name=long_name,
                                      old_price="24,00", new_price="19,99", pct_label="-20 %",
                                      reason_label="Kundenverhalten", step_pct=20, clamped=True,
                                      blocked_rule="Agent wählte keinen gültigen Kandidaten",
                                      text_source="template"),
        "check_proposal": check,
        "record_outcome": OutcomeResult(outcome="approved", proposal_id=p.proposal_id,
                                        action_id="PA-270216-0003", notify="yes",
                                        notify_title=tell_title, notify_message=tell_message),
        "apply_price": ApplyResult(status="blocked", proposal_id=p.proposal_id,
                                   action_id="PA-270216-0003", new_price="19,99",
                                   message="ä" * 160)}
    for tool, model in results.items():
        result = mcputil.structured_result(tool, model, "status")
        full, text = mcputil.measure(result)
        assert full <= 1800 and text <= 1500, tool
        if tool not in ("check_proposal", "assess_event"):
            assert full < 700, (tool, full)
    full, _ = mcputil.measure(mcputil.structured_result("check_proposal", check, "x"))
    assert 1100 <= full <= 1800 and len(message) <= 600 and len(title) <= 90
