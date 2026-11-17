"""Scenarios S1-S8 and S1b through engine and gate, as the workflows call them (1.3, 6.8,
8.2.2, 11.2-11.5; integration cases I1, I5-I13 without SAM)."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

import pytest

from gposdemo.common.bus import MemoryBus
from gposdemo.common.jsonutil import sha256_hex
from gposdemo.engine import Engine, store
from gposdemo.engine.gate import Gate
from gposdemo.engine.review import EVIDENCE_MAX_BYTES, NUMBERS_MAX, NUMBERS_SHORT
from tests.engine.fakes import (
    BANANEN,
    CREMA,
    CROISSANTS,
    ENTE,
    ESPRESSO,
    GLUEHWEIN,
    HASE,
    KOCHBUCH,
    MILCH,
    PRALINEN,
    TOAST,
    WASSER,
    ZONE,
    Backends,
    FakeClock,
    PosWriter,
    gebit_event,
)
from tests.engine.flow import (
    NONE_SLOT,
    S1_EVIDENCE,
    S1_TEXTS,
    approval_row,
    approve,
    checked,
    evidenced,
    prepared,
    published,
    staged,
)
from tests.engine.test_contracts import NUMBERS_160, S3_AGENT_INPUT, S3_NUMBERS

pytestmark = pytest.mark.db


def proposal_row(engine: Engine, proposal_id: str) -> store.ProposalRecord:
    with engine.service.ctx.db.tx() as conn:
        p = store.proposal(conn, proposal_id)
    assert p is not None
    return p


def test_s1_end_to_end(engine: Engine, gate: Gate, pos: PosWriter, stubs: Backends,
                       memory_bus: MemoryBus, clock: FakeClock) -> None:
    prep = prepared(engine, pos, [ENTE, BANANEN, MILCH])
    assert (prep.candidate, prep.lines, prep.candidates, prep.reason) == (
        "yes", 3, 1, "has_candidates")
    agent_input = json.loads(prep.agent_input)
    assert len(prep.agent_input.encode()) <= 1000 and agent_input["tx_id"] == prep.tx_id
    assert [c["a"] for c in agent_input["candidates"]] == [ENTE]
    assert agent_input["no_action"] == ["Bio-Bananen", "Vollmilch 3,5 %"]
    [state] = published(engine, memory_bus, "gpos/v1/review/state/prepared/101/01/>")
    assert state["candidates"] == 1 and state["membership"] is None
    assert state["lines"][0] == {
        "article_number": ENTE, "name": "GEBIT Ente (Quietscheente gelb)",
        "signals": ["slow_seller"], "candidate": True, "blocked": "", "suggested_step_pct": 20,
        "max_step_pct": 20,
        "facts": "9 von 35 geplanten Stück verkauft (7 Tage), Reichweite 6,5 Wochen, Bestand 96"}
    assert state["lines"][1] == {"article_number": BANANEN, "name": "Bio-Bananen",
                                 "signals": [], "candidate": False, "blocked": "",
                                 "facts": "läuft nach Plan (180/180)"}
    assert "evidence" not in state and "decision" not in state

    # node note: the engine checks and stores the evidence of the fast agent (8.2.2)
    noted = evidenced(engine, prep)
    assert (noted.status, noted.checked, noted.holding) == ("noted", 1, 1)
    assert json.loads(noted.evidence) == {"model": "fast", "tx": "closed", "items": [
        {"a": ENTE, "name": "GEBIT Ente (Quietscheente gelb)", "reason": "slow_seller",
         "holds": "yes", "numbers": S1_EVIDENCE["numbers"],
         "tools": ["get_sales_performance"]}]}
    first, again = published(engine, memory_bus, "gpos/v1/review/state/prepared/101/01/>")
    assert first == state and again["evidence"] == json.loads(noted.evidence)
    assert again["candidates"] == 1 and "decision" not in again

    stage = staged(engine, prep, ENTE, "slow_seller", "20")
    assert (stage.status, stage.old_price, stage.new_price, stage.pct_label, stage.step_pct,
            stage.clamped, stage.reason_label, stage.text_source) == (
        "ready", "9,99", "7,99", "-20 %", 20, False, "Ladenhüter", "ai")
    p = proposal_row(engine, stage.proposal_id)
    assert (p.ref30, p.margin_pct_new, p.pct_shown, p.base_price_label, p.note) == (
        Decimal("9.99"), Decimal("22.6"), 20, None, "")
    assert p.valid_to.astimezone(ZONE).isoformat() == "2027-02-23T20:00:00+01:00"
    assert p.valid_from.astimezone(ZONE).isoformat() == "2027-02-16T00:00:00+01:00"
    assert p.proposal_hash == sha256_hex(
        f"{p.proposal_id}|100001|9.99|7.99|2027-02-23T20:00:00+01:00")[:10]
    assert len(p.guardrails) == 8 and p.guardrails[-1]["rule"] == "−30 % gesperrt"
    [ready] = published(engine, memory_bus, "gpos/v1/proposal/ready/101/01/>")
    assert (ready["pct_label"], ready["margin_pct_new"], ready["valid_to_label"]) == (
        "−20 %", "22,6", "Di 23.02. 20:00")
    [request] = published(engine, memory_bus, "gpos/v1/approval/request/101/01/>")
    assert request == {"schema_version": "1", "proposal_id": stage.proposal_id,
                       "store": "101", "till": "01"}
    [proposed] = published(engine, memory_bus, "gpos/v1/review/state/proposed/>")
    assert proposed["proposal_id"] == stage.proposal_id
    assert proposed["decision"]["step_pct"] == "20"
    assert proposed["decision"]["model"] == "planning" and "evidence" not in proposed[
        "decision"]
    assert proposed["evidence"] == again["evidence"]
    assert ready["ai_model"] == "planning" and p.ai_model == "planning"
    assert [m["state"] for m in published(engine, memory_bus, "gpos/v1/review/state/>")] == [
        "requested", "prepared", "prepared", "proposed"]

    check = checked(engine, stage)
    assert (check.proposal_hash, check.article_name, check.old_price, check.new_price,
            check.pct_label, check.reason_label, check.valid_to_label) == (
        p.proposal_hash, "GEBIT Ente (Quietscheente gelb)", "9,99", "7,99", "-20 %",
        "Ladenhüter", "Di 23.02. 20:00")
    assert check.notify_title == ("Preisvorschlag GEBIT Ente (Quietscheente gelb): "
                                  "9,99 € → 7,99 € (−20 %)")
    assert approval_row(engine, stage.proposal_id)["apply_calls"] == 0

    applied = approve(gate, clock, check)
    assert (applied.status, applied.new_price) == ("applied", "7,99")
    assert applied.action_id.startswith("PA-270216-")
    [req] = stubs.showcase.requests
    assert (req["article_number"], req["store_id"], req["proposal_id"], req["pct_shown"],
            req["reason_code"]) == (ENTE, "101", stage.proposal_id, 20,
                                    "REASON_CODE_SLOW_SELLER")
    assert (req["header"]["originator"]["identity_id"],
            req["header"]["approver"]["identity_id"]) == ("gpos-engine", "role:marktleitung")
    assert (req["valid_from"], req["valid_to"]) == ({"seconds": "1802732400", "offset": 60},
                                                    {"seconds": "1803409200", "offset": 60})
    approved = published(engine, memory_bus, "gpos/v1/proposal/approved/101/01/>")
    assert [(m["action_id"], m["status_reason"]) for m in approved] == [(applied.action_id, "")]
    assert approved[0]["decided_at"]

    outcome = engine.service.record_outcome(stage.proposal_id, "run-r4", "applied",
                                            applied.action_id, "")
    assert (outcome.outcome, outcome.action_id, outcome.notify) == (
        "approved", applied.action_id, "yes")
    assert outcome.notify_title == ("Preis aktiv: GEBIT Ente (Quietscheente gelb) 7,99 € bis "
                                    "Di 23.02. 20:00")
    assert len(published(engine, memory_bus, "gpos/v1/proposal/approved/>")) == 1

    duplicate = gate.service.apply_price(**{**{k: getattr(check, k) for k in (
        "proposal_id", "proposal_hash", "article_name", "old_price", "new_price", "pct_label",
        "reason_label", "valid_to_label")}, "run_id": "run-r4"})
    assert (duplicate.status, duplicate.action_id) == ("already_applied", applied.action_id)
    [signal] = published(engine, memory_bus, "gpos/v1/proposal/duplicate_request/>")
    assert signal["state"] == "duplicate_request" and signal["action_id"] == applied.action_id
    assert len(stubs.showcase.requests) == 1
    again = engine.service.record_outcome(stage.proposal_id, "run-r4", "applied",
                                          applied.action_id, "")
    assert again == outcome
    approval = approval_row(engine, stage.proposal_id)
    assert approval["apply_calls"] == 2 and approval["outcome"] == "approved"
    gap = (datetime.fromisoformat(approval["first_apply_at"])
           - datetime.fromisoformat(approval["checked_at"])).total_seconds()
    assert gap >= 3

    # S1b: the next scan charges the booth price, the review sees the running action
    basket = pos.basket([ENTE], status="OPEN")
    chip = engine.service.assess_event(gebit_event(
        "PositionAdded", basket.tx_id, 2, clock(), positionId=basket.positions[0]))
    assert (chip.insight_code, chip.insight_text) == ("action",
                                                      "Messe-Aktion aktiv bis Di 23.02. 20:00")
    s1b = prepared(engine, pos, [ENTE])
    assert (s1b.candidate, s1b.reason) == ("no", "only_blocked")
    review = engine.service.review(s1b.review_id)
    assert review is not None and review["lines"][0]["blocked"] == "Messe-Aktion läuft bis 23.02."


def test_s2_season_end(engine: Engine, gate: Gate, pos: PosWriter, clock: FakeClock) -> None:
    prep = prepared(engine, pos, [PRALINEN, CREMA])
    stage = staged(engine, prep, PRALINEN, "season_end", "30",
                   headline="Herzpralinen: Saisonrest abverkaufen",
                   rationale="Valentinstag ist vorbei, 46 Packungen liegen noch im Lager.",
                   facts_line="Saisonende 14.02. · Restbestand 46")
    assert (stage.status, stage.old_price, stage.new_price, stage.pct_label) == (
        "ready", "7,99", "5,49", "-31 %")
    p = proposal_row(engine, stage.proposal_id)
    assert (p.base_price_label, p.margin_pct_new, p.ref30) == ("27,45 €/kg", Decimal("39.6"),
                                                               Decimal("7.99"))
    assert {"rule": "Preispunkt ,49", "ok": True} in p.guardrails
    assert "Preispunkt ,49." in checked(engine, stage).notify_message


def test_s3_customer_behaviour(engine: Engine, pos: PosWriter, memory_bus: MemoryBus) -> None:
    prep = prepared(engine, pos, [ESPRESSO, CROISSANTS], membership_id="M-1001")
    expected = (S3_AGENT_INPUT.replace("GR-270216-0007", prep.review_id)
                .replace("5b1f0c2e-8d1e-4a43-9a51-0c7a2f0e1b11", prep.tx_id))
    assert prep.agent_input == expected
    assert prep.membership_id == "M-1001"
    [state] = published(engine, memory_bus, "gpos/v1/review/state/prepared/>")
    assert state["membership"] == {"membership_id": "M-1001", "persona": "Kaffeepause",
                                   "consent_profiling": True}
    stage = staged(engine, prep, ESPRESSO, "customer_behaviour", "10",
                   headline="Espresso: Stammkundin zurückgewinnen",
                   rationale="Die Karte kauft seit 35 Tagen nicht mehr, sonst alle 14 Tage.",
                   facts_line="zuletzt vor 35 Tagen · Kartenkunden −47 %")
    assert (stage.status, stage.new_price, stage.pct_label) == ("ready", "12,99", "-10 %")
    p = proposal_row(engine, stage.proposal_id)
    assert (p.note, p.base_price_label) == ("Rücknahme der Preiserhöhung vom 11.01.",
                                            "12,99 €/kg")
    assert {"rule": "−20 % gesperrt", "ok": False, "value": "Marge 17,1 %",
            "info": True} in p.guardrails


@pytest.mark.parametrize(("headline", "source"), [
    ("Espresso: Kartenkunden kaufen 46,7 % seltener", "ai"),
    ("Espresso: 11 % günstiger für die Karte", "template")])
def test_s3_last_change_allows_no_percentage(engine: Engine, pos: PosWriter, headline: str,
                                             source: str) -> None:
    """11.3 step 7 (UC1-32): the full S3 evidence reaches the engine; the date and prices
    of ``last_change`` allow no percentage, its other numbers still do."""
    prep = prepared(engine, pos, [ESPRESSO, CROISSANTS], membership_id="M-1001")
    noted = evidenced(engine, prep, [
        {"article": ESPRESSO, "reason": "customer_behaviour", "holds": "yes",
         "numbers": S3_NUMBERS, "tools": "get_purchase_behaviour, get_article"}])
    assert json.loads(noted.evidence)["items"][0]["numbers"] == S3_NUMBERS
    stage = staged(engine, prep, ESPRESSO, "customer_behaviour", "10", headline=headline,
                   rationale="Die Karte kauft seit 35 Tagen nicht mehr, sonst alle 14 Tage.",
                   facts_line="zuletzt vor 35 Tagen · Kartenkunden −47 %")
    assert (stage.status, stage.pct_label, stage.text_source) == ("ready", "-10 %", source)

def test_s3_repeats_after_a_booth_purchase(engine: Engine, pos: PosWriter) -> None:
    """I11: booth purchases carry business date D and never count (2 / 35 / 14 twice)."""
    for _ in range(2):
        prep = prepared(engine, pos, [ESPRESSO], membership_id="M-1001")
        candidate = json.loads(prep.agent_input)["candidates"][0]
        assert candidate["facts"].startswith("Stammartikel der Karte: zuletzt vor 35 Tagen "
                                             "(sonst alle 14 Tage)")
        engine.service.close_review(prep.review_id, "no_action", "Test", "run-r3")


@pytest.mark.parametrize(("numbers", "membership", "reason", "blocked"), [
    ([BANANEN, TOAST, WASSER], None, "no_candidates", []),
    ([GLUEHWEIN, KOCHBUCH], None, "only_blocked", ["Zentralaktion läuft bis 21.02.",
                                                   "Preisbindung"]),
    ([ESPRESSO], "M-1003", "no_candidates", []),
])
def test_s4_s5_s6_without_agent(engine: Engine, pos: PosWriter, memory_bus: MemoryBus,
                                numbers: list[str], membership: str | None, reason: str,
                                blocked: list[str]) -> None:
    prep = prepared(engine, pos, numbers, membership_id=membership)
    assert (prep.candidate, prep.reason, prep.candidates, prep.agent_input) == (
        "no", reason, 0, "")
    review = engine.service.review(prep.review_id)
    assert review is not None and review["state"] == reason
    assert [line["blocked"] for line in review["lines"] if line["blocked"]] == blocked
    skip = engine.service.close_review(prep.review_id, prep.reason, "", "run-r3")
    assert (skip.status, skip.verdict) == ("closed", reason)
    assert len(published(engine, memory_bus, f"gpos/v1/review/state/{reason}/>")) == 1


def test_s7_two_candidates(engine: Engine, pos: PosWriter) -> None:
    prep = prepared(engine, pos, [ENTE, PRALINEN])
    doc = json.loads(prep.agent_input)
    assert [(c["a"], c["signals"]) for c in doc["candidates"]] == [
        (PRALINEN, ["season_end"]), (ENTE, ["slow_seller"])]
    stage = staged(engine, prep, PRALINEN, "season_end", "30",
                   headline="Herzpralinen: Restposten nach dem Valentinstag")
    assert (stage.status, stage.new_price) == ("ready", "5,49")


def test_s8_agent_says_no(engine: Engine, pos: PosWriter, memory_bus: MemoryBus) -> None:
    prep = prepared(engine, pos, [HASE, MILCH])
    [candidate] = json.loads(prep.agent_input)["candidates"]
    assert (candidate["a"], candidate["suggested_step_pct"], candidate["max_step_pct"]) == (
        HASE, 10, 30)
    noted = evidenced(engine, prep, [{
        "article": HASE, "reason": "slow_seller", "holds": "no",
        "numbers": "trend=rising; sold_7d=14; plan_7d=10; weekly_first=4; weekly_last=14",
        "tools": "get_sales_performance"}])
    assert (noted.status, noted.checked, noted.holding) == ("noted", 1, 0)
    closed = engine.service.close_review(
        prep.review_id, "no_action",
        "Der Abverkauf steigt von 4 auf 14 Stück je Woche.\nKeine Senkung nötig.", "run-r3",
        model="planning")
    assert (closed.status, closed.verdict) == ("closed", "no_action")
    [state] = published(engine, memory_bus, "gpos/v1/review/state/no_action/>")
    assert state["decision"] == {"decision": "no_action", "model": "planning", "rationale": (
        "Der Abverkauf steigt von 4 auf 14 Stück je Woche. Keine Senkung nötig.")}
    assert state["evidence"] == json.loads(noted.evidence)          # kept by close_review
    assert state["evidence"]["items"][0]["holds"] == "no"
    again = engine.service.close_review(prep.review_id, "failed", "late", "run-x")
    assert (again.status, again.verdict) == ("closed", "no_action")
    assert engine.service.state("101", "01")["proposal"] is None
    assert engine.service.close_review("probe-123", "unknown", "", "").status == "noted"
    assert engine.service.close_review("GR-270216-9999", "failed", "x", "").status == "unknown"


def test_deferred_before_the_agent(engine: Engine, pos: PosWriter,
                                   memory_bus: MemoryBus) -> None:
    """I7: a second review of the till while a proposal is open ends deferred, no model."""
    first = prepared(engine, pos, [ENTE])
    assert staged(engine, first, ENTE, "slow_seller", "20").status == "ready"
    second = prepared(engine, pos, [PRALINEN])
    assert (second.candidate, second.reason, second.agent_input) == ("no", "deferred", "")
    review = engine.service.review(second.review_id)
    assert review is not None and review["state"] == "deferred"
    assert published(engine, memory_bus, "gpos/v1/review/state/deferred/>")
    other_till = prepared(engine, pos, [PRALINEN], till="99")
    assert other_till.candidate == "yes"


def test_stage_race_caught_by_the_unique_index(engine: Engine, pos: PosWriter,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    first = prepared(engine, pos, [ENTE])
    second = prepared(engine, pos, [PRALINEN])
    assert staged(engine, first, ENTE, "slow_seller", "20").status == "ready"
    monkeypatch.setattr(store, "open_proposal", lambda *_a, **_k: None)
    result = staged(engine, second, PRALINEN, "season_end", "30",
                    headline="Herzpralinen: Saisonrest")
    assert (result.status, result.blocked_rule) == ("deferred",
                                                    "Offene Freigabe an dieser Kasse")
    review = engine.service.review(second.review_id)
    assert review is not None and review["state"] == "deferred"


def test_stage_checks(engine: Engine, pos: PosWriter, stubs: Backends) -> None:
    """I9, I10 and the race with a price change."""
    prep = prepared(engine, pos, [ENTE, GLUEHWEIN])
    invalid = staged(engine, prep, GLUEHWEIN, "slow_seller", "20")
    assert (invalid.status, invalid.blocked_rule) == ("invalid",
                                                      "Agent wählte keinen gültigen Kandidaten")
    review = engine.service.review(prep.review_id)
    assert review is not None and (review["state"], review["error"]) == (
        "blocked", "Agent wählte keinen gültigen Kandidaten")
    assert staged(engine, prep, ENTE, "slow_seller", "20").blocked_rule == \
        "Review nicht vorbereitet"

    for agent_step in ("10", "30", "zwanzig"):
        prep = prepared(engine, pos, [ENTE])
        stage = staged(engine, prep, ENTE, "none", agent_step)
        assert (stage.status, stage.step_pct, stage.clamped, stage.new_price) == (
            "ready", 20, True, "7,99")
        p = proposal_row(engine, stage.proposal_id)
        assert p.status_reason == f"Anlass korrigiert; Stufe korrigiert ({agent_step} → 20 %)"
        assert p.step_requested == (0 if agent_step == "zwanzig" else int(agent_step))
        engine.service.reset("booth", "101")

    prep = prepared(engine, pos, [ENTE])
    stage = staged(engine, prep, ENTE, "slow_seller", "20",
                   rationale="Für 6,99 € wäre die Ente ein Schnäppchen.")
    assert (stage.status, stage.text_source) == ("ready", "template")
    p = proposal_row(engine, stage.proposal_id)
    assert p.headline == "GEBIT Ente (Quietscheente gelb): Abverkauf ankurbeln"
    assert p.rationale.startswith("9 von 35 geplanten Stück verkauft")
    engine.service.reset("booth", "101")

    prep = prepared(engine, pos, [ENTE])
    stubs.showcase.actions[("101", ENTE)] = type(
        "Action", (), {"price": Decimal("8.99"), "action_id": "PA-RACE",
                       "valid_from": datetime(2027, 2, 16, tzinfo=ZONE),
                       "valid_to": datetime(2027, 2, 23, 20, tzinfo=ZONE)})()
    blocked = staged(engine, prep, ENTE, "slow_seller", "20")
    assert (blocked.status, blocked.blocked_rule) == ("blocked",
                                                      "Messe-Aktion läuft bis 23.02.")
    review = engine.service.review(prep.review_id)
    assert review is not None and review["state"] == "blocked"


def test_note_evidence_validates_the_agent_output(engine: Engine, pos: PosWriter,
                                                  memory_bus: MemoryBus) -> None:
    """8.2.2 rules 1-12: only free candidates, known enums, capped lengths and tools."""
    prep = prepared(engine, pos, [PRALINEN, ENTE, GLUEHWEIN])
    noted = evidenced(engine, prep, [
        {"article": GLUEHWEIN, "reason": "season_end", "holds": "yes", "numbers": "x",
         "tools": "get_season_info"},                       # blocked: dropped
        {"article": ENTE, "reason": "season_end", "holds": "YES",       # wrong reason
         "numbers": "trend=falling;\nsold_7d=9 " + "n" * 200,
         "tools": "get_sales_performance, list_artifacts; get_sales_performance get_article "
                  "get_transaction get_season_info"}], model="gpt", tx_status="CLOSED")
    doc = json.loads(noted.evidence)
    assert (noted.status, noted.checked, noted.holding) == ("noted", 1, 0)
    assert (doc["model"], doc["tx"]) == ("fast", "closed")
    [item] = doc["items"]
    assert (item["a"], item["name"], item["reason"], item["holds"]) == (
        ENTE, "GEBIT Ente (Quietscheente gelb)", "slow_seller", "unknown")
    assert len(item["numbers"]) <= NUMBERS_MAX
    assert item["numbers"].startswith("trend=falling; sold")
    assert item["tools"] == ["get_sales_performance", "get_article", "get_transaction"]

    again = evidenced(engine, prep, [
        {"article": "{{gather.output.c1_article}}", "reason": "slow_seller", "holds": "yes",
         "numbers": "x", "tools": "get_sales_performance"},
        {"article": PRALINEN, "reason": "season_end", "holds": "maybe", "numbers": "null",
         "tools": "-"}], tx_status="{{gather.output.tx_status}}")
    doc = json.loads(again.evidence)                              # overwrites the first
    assert doc == {"model": "fast", "tx": "unknown", "items": [
        {"a": PRALINEN, "name": "Herzpralinen Valentin", "reason": "season_end",
         "holds": "unknown", "numbers": "", "tools": []}]}
    review = engine.service.review(prep.review_id)
    assert review is not None and review["state"] == "prepared"
    assert review["evidence"] == doc and "decision" not in review

    full = evidenced(engine, prep, [                     # UC1-32: 160 characters stay
        {"article": PRALINEN, "reason": "season_end", "holds": "yes", "numbers": NUMBERS_160,
         "tools": "get_season_info, get_article, get_purchase_behaviour"},
        {"article": ENTE, "reason": "slow_seller", "holds": "unknown", "numbers": NUMBERS_160,
         "tools": "get_sales_performance, get_article, get_purchase_behaviour"}],
        model="planning", tx_status="not_closed")
    doc = json.loads(full.evidence)
    assert [(i["a"], i["numbers"], len(i["tools"])) for i in doc["items"]] == [
        (PRALINEN, NUMBERS_160, 3), (ENTE, NUMBERS_160, 3)]
    assert len(full.evidence.encode()) <= EVIDENCE_MAX_BYTES

    two = evidenced(engine, prep, [
        {"article": PRALINEN, "reason": "season_end", "holds": "yes",
         "numbers": "ö" * 160, "tools": "get_season_info"},
        {"article": ENTE, "reason": "slow_seller", "holds": "yes", "numbers": "ä" * 160,
         "tools": "get_sales_performance"}])
    doc = json.loads(two.evidence)
    assert len(two.evidence.encode()) <= EVIDENCE_MAX_BYTES
    assert two.checked == len(doc["items"]) == 2
    assert all(len(i["numbers"]) <= NUMBERS_SHORT for i in doc["items"])  # cut first
    assert two.holding == 2
    dup = evidenced(engine, prep, [dict(S1_EVIDENCE), dict(S1_EVIDENCE)])
    assert dup.checked == 1                                       # same article twice
    assert evidenced(engine, prep, [NONE_SLOT, NONE_SLOT]).checked == 0

    engine.service.reset("booth", "101")
    assert evidenced(engine, prep).status == "stale"
    assert engine.service.note_evidence("GR-270216-9999").status == "unknown"
    assert len(published(engine, memory_bus, "gpos/v1/review/state/prepared/>")) == 7


def test_stage_needs_a_confirmed_evidence_item(engine: Engine, pos: PosWriter,
                                               memory_bus: MemoryBus) -> None:
    """11.3 step 2b: the planner may only choose a candidate whose evidence holds."""
    prep = prepared(engine, pos, [HASE])
    evidenced(engine, prep, [{"article": HASE, "reason": "slow_seller", "holds": "no",
                              "numbers": "trend=rising", "tools": "get_sales_performance"}])
    result = staged(engine, prep, HASE, "slow_seller", "10",
                    headline="Plüschhase: Abverkauf ankurbeln")
    assert (result.status, result.blocked_rule) == ("invalid",
                                                    "KI-Empfehlung ohne bestätigten Beleg")
    [blocked] = published(engine, memory_bus, "gpos/v1/review/state/blocked/>")
    assert blocked["error"] == "KI-Empfehlung ohne bestätigten Beleg"
    assert (blocked["decision"]["article_number"], blocked["decision"]["model"]) == (
        HASE, "planning")
    assert blocked["evidence"]["items"][0]["holds"] == "no"

    other = prepared(engine, pos, [ENTE], till="99")
    evidenced(engine, other, [])                                    # no item at all
    assert staged(engine, other, ENTE, "slow_seller", "20").blocked_rule == \
        "KI-Empfehlung ohne bestätigten Beleg"


def test_legacy_stage_without_model_and_evidence(engine: Engine, pos: PosWriter,
                                                 memory_bus: MemoryBus) -> None:
    """The old R3 during the deploy window: no note_evidence, no model -> ai_model ""."""
    prep = prepared(engine, pos, [ENTE])
    stage = engine.service.stage_proposal(prep.review_id, ENTE, "slow_seller", "20",
                                          run_id="run-old", **S1_TEXTS)
    assert stage.status == "ready"
    [ready] = published(engine, memory_bus, "gpos/v1/proposal/ready/>")
    assert ready["ai_model"] == ""
    [proposed] = published(engine, memory_bus, "gpos/v1/review/state/proposed/>")
    assert proposed["decision"]["model"] == "" and "evidence" not in proposed
    state = engine.service.state("101", "01")
    assert state["proposal"]["ai_model"] == ""
    bad = prepared(engine, pos, [PRALINEN], till="99")
    staged_bad = engine.service.stage_proposal(bad.review_id, PRALINEN, "season_end", "30",
                                               run_id="r", model="gpt-x", **S1_TEXTS)
    review = engine.service.review(bad.review_id)
    assert review is not None and review["decision"]["model"] == ""  # not an alias
    assert staged_bad.status in ("ready", "deferred")
