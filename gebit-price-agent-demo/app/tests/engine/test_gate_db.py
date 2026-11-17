"""``check_proposal``, ``apply_price`` and ``record_outcome`` on the scratch DB
(11.4, 11.5 R1-R8 with the engine clock; integration cases I2-I4, I8, I14-I16)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import grpc
import pytest

from gposdemo.common.bus import MemoryBus
from gposdemo.engine import Engine
from gposdemo.engine.gate import Gate
from gposdemo.engine.models import CheckResult
from gposdemo.engine.texts import (
    REASON_DENY_AFTER_APPROVAL,
    REASON_DENY_TOO_EARLY,
    REASON_EXPIRED,
    REASON_REJECTED,
    REASON_REJECTED_ERROR,
    REASON_TECHNICAL,
)
from tests.engine.fakes import ENTE, Backends, FakeClock, PosWriter
from tests.engine.flow import approval_row, approve, card, checked, prepared, published, staged

pytestmark = pytest.mark.db


def pending(engine: Engine, pos: PosWriter, till: str = "01") -> CheckResult:
    """S1 staged and checked: proposal ``pending`` with its approval row."""
    stage = staged(engine, prepared(engine, pos, [ENTE], till=till), ENTE, "slow_seller", "20")
    return checked(engine, stage)


def state(engine: Engine, proposal_id: str) -> str:
    proposal = engine.service.proposal(proposal_id)
    assert proposal is not None
    return str(proposal["state"])


def test_check_proposal_statuses(engine: Engine, pos: PosWriter, memory_bus: MemoryBus,
                                 clock: FakeClock) -> None:
    service = engine.service
    probe = service.check_proposal("probe-notify-4f1c", "run-p4")
    assert (probe.status, probe.notify_title, probe.notify_message) == (
        "probe", "gpos Preflight: Benachrichtigung ok",
        "Testmeldung der Anmeldeprüfung, keine Aktion nötig.")
    assert service.check_proposal("probe-4f1c").status == "unknown"
    assert service.check_proposal("GP-270216-9999").status == "unknown"
    check = pending(engine, pos)
    assert service.check_proposal(check.proposal_id, "run-dup").status == "decided"
    [event] = published(engine, memory_bus, "gpos/v1/proposal/pending/101/01/>")
    assert event["state"] == "pending" and event["run_id"] == "run-r4"
    service.reset("booth", "101")
    assert service.check_proposal(check.proposal_id).status == "superseded"
    late = staged(engine, prepared(engine, pos, [ENTE]), ENTE, "slow_seller", "20")
    clock.advance(61)
    assert service.check_proposal(late.proposal_id).status == "stale"
    proposal = service.proposal(late.proposal_id)
    assert proposal is not None and (proposal["state"], proposal["status_reason"]) == (
        "failed", "Freigabe-Lauf zu spät gestartet")


def test_gate_refuses_a_card_that_differs(engine: Engine, gate: Gate, pos: PosWriter,
                                          stubs: Backends, clock: FakeClock) -> None:
    """Steps 5-7 and I14: every refusal leaves the proposal pending and no price."""
    check = pending(engine, pos)
    card_text = "Freigabetext weicht ab"  # 11.4 step 7, verbatim (shown by 11.6)
    cases = [({"proposal_hash": "ffffffffff"}, "Hash passt nicht"),
             ({"run_id": "run-other"}, "Fremder Lauf"),
             ({"old_price": "10,99"}, card_text),
             ({"new_price": "6,99"}, card_text),
             ({"pct_label": "−20 %"}, card_text),
             ({"article_name": "GEBIT Ente"}, card_text),
             ({"reason_label": "Saisonende"}, card_text),
             ({"valid_to_label": "Mi 24.02. 20:00"}, card_text)]
    for changes, message in cases:
        clock.advance(4)
        result = gate.service.apply_price(**card(check, **changes))
        assert (result.status, result.message, result.action_id) == ("blocked", message, "")
    assert state(engine, check.proposal_id) == "pending" and not stubs.showcase.requests
    approval = approval_row(engine, check.proposal_id)
    assert (approval["apply_calls"], approval["last_apply_status"], approval["error"]) == (
        8, "blocked", card_text)
    outcome = engine.service.record_outcome(check.proposal_id, "run-r4", "blocked", "", "")
    assert (outcome.outcome, outcome.notify) == ("blocked", "yes")
    assert outcome.notify_title == "Nicht angewendet: GEBIT Ente (Quietscheente gelb)"
    assert outcome.notify_message == f"Freigabetext weicht ab. Ref {check.proposal_id}."
    assert state(engine, check.proposal_id) == "blocked"


def test_guard_block_warn_and_f2(engine: Engine, make_gate: Callable[..., Gate],
                                 pos: PosWriter, stubs: Backends, memory_bus: MemoryBus,
                                 clock: FakeClock) -> None:
    check = pending(engine, pos)
    blocked = approve(make_gate(), clock, check, after_s=1.5)
    assert (blocked.status, blocked.message) == (
        "blocked", "Freigabe schneller als möglich – Gate prüfen")
    f2 = make_gate(GATE_GUARD="f2")
    assert approve(f2, clock, check, after_s=3).message == \
        "Freigabezeit fehlt oder passt nicht – Gate prüfen"
    checked_at = clock.now - timedelta(seconds=4.5)
    early = (checked_at + timedelta(seconds=1)).isoformat()
    assert approve(f2, clock, check, after_s=0, approved_at=early).status == "blocked"
    assert state(engine, check.proposal_id) == "pending"
    good = clock.now.isoformat()
    applied = approve(f2, clock, check, after_s=0.5, approved_at=good)
    assert applied.status == "applied"

    engine.service.reset("booth", "101")
    stubs.showcase.reset()  # reset chain step 2: WWS ends the booth action
    second = pending(engine, pos)
    warned = approve(make_gate(GATE_GUARD="warn"), clock, second, after_s=1)
    assert warned.status == "applied"
    approval = approval_row(engine, second.proposal_id)
    assert approval["error"] == "Gate prüfen: Aufruf nach 1 s"
    events = published(engine, memory_bus,
                       f"gpos/v1/proposal/approved/101/01/{second.proposal_id}")
    assert [e["status_reason"] for e in events] == ["Gate prüfen"]


def test_gate_after_reset_expiry_and_sam_error(engine: Engine, gate: Gate, pos: PosWriter,
                                               clock: FakeClock) -> None:
    """I8 (superseded), watchdog expiry (expired), I15 (failed -> blocked)."""
    assert gate.service.apply_price("GP-270216-9999", "x", "x", "1", "1", "x", "x",
                                    "x").status == "unknown"
    check = pending(engine, pos)
    engine.service.reset("booth", "101")
    assert (approve(gate, clock, check).status, state(engine, check.proposal_id)) == (
        "superseded", "superseded")
    check = pending(engine, pos)
    clock.advance(151)
    assert engine.service.maintenance.sweep()["proposals_pending"] == 1
    assert approve(gate, clock, check).status == "expired"
    check = pending(engine, pos)
    assert engine.service.sam_error("r4", "101", "01", "awe restarted")["status"] == "noted"
    clock.advance(6)
    assert engine.service.maintenance.settle_sam_errors() == 1
    late = approve(gate, clock, check)
    assert (late.status, late.message) == ("blocked",
                                           "Vorschlag ist nicht freigabebereit (failed)")
    outcome = engine.service.record_outcome(check.proposal_id, "", "", "", "boom")
    assert outcome.outcome == "failed"
    assert outcome.notify_message == f"SAM-Lauf abgebrochen. Ref {check.proposal_id}."


def test_wws_refusal_keeps_the_proposal_pending(engine: Engine, gate: Gate, pos: PosWriter,
                                                stubs: Backends, clock: FakeClock) -> None:
    check = pending(engine, pos)
    stubs.showcase.fail_request = (grpc.StatusCode.FAILED_PRECONDITION, "WWS-011")
    refused = approve(gate, clock, check)
    assert (refused.status, refused.message) == ("blocked",
                                                 "Warenwirtschaft lehnt ab (WWS-011)")
    assert state(engine, check.proposal_id) == "pending"
    stubs.showcase.fail_request = None
    assert approve(gate, clock, check, after_s=1).status == "applied"
    assert state(engine, check.proposal_id) == "approved"


DENY_TEXT = "Agent reported error: Price approval was denied by store manager"  # 12.11.
DUCK = "GEBIT Ente (Quietscheente gelb)"
NOT_APPLIED = f"Nicht angewendet: {DUCK}"


@pytest.mark.parametrize(("agent_status", "error", "after_s", "outcome", "title"), [
    ("denied", "", 4, "rejected", f"Abgelehnt: {DUCK} bleibt bei 9,99 €"),
    ("", "", 4, "failed", NOT_APPLIED),                            # no status (R8)
    ("", "Tool approval timed out after 2 minutes", 125, "expired",
     f"Abgelaufen: {DUCK} bleibt bei 9,99 €"),
    ("", "Agent node failed", 4, "failed", NOT_APPLIED),
    ("applied", "", 4, "failed", NOT_APPLIED),
])
def test_record_outcome_from_the_database(engine: Engine, pos: PosWriter,
                                          memory_bus: MemoryBus, clock: FakeClock,
                                          agent_status: str, error: str, after_s: float,
                                          outcome: str, title: str) -> None:
    """I2 (deny), I3 (timeout) and the other rows of 11.5 without a price change."""
    check = pending(engine, pos)
    clock.advance(after_s)
    result = engine.service.record_outcome(check.proposal_id, "run-r4", agent_status,
                                           "PA-FAKE" if agent_status else "", error)
    assert (result.outcome, result.action_id, result.notify, result.notify_title) == (
        outcome, "", "yes", title)
    assert state(engine, check.proposal_id) == outcome
    [event] = published(engine, memory_bus, f"gpos/v1/proposal/{outcome}/101/01/>")
    assert event["status_reason"] != "" or outcome == "approved"
    approval = approval_row(engine, check.proposal_id)
    assert (approval["outcome"], approval["agent_status"]) == (outcome, agent_status or None)
    again = engine.service.record_outcome(check.proposal_id, "run-r4", "applied", "", "")
    assert again.outcome == outcome


def test_record_outcome_trusts_the_price_change(engine: Engine, gate: Gate, pos: PosWriter,
                                                clock: FakeClock) -> None:
    check = pending(engine, pos)
    applied = approve(gate, clock, check)
    result = engine.service.record_outcome(check.proposal_id, "", "", "",
                                           "Tool approval timed out after 2 minutes")
    assert (result.outcome, result.action_id) == ("approved", applied.action_id)
    audit = engine.service.ctx.db.fetch(
        "select payload from engine.audit_event where kind = 'outcome_mismatch'")
    assert audit[0]["payload"]["action_id"] == applied.action_id
    assert engine.service.record_outcome("GP-270216-9999").model_dump() == {
        "outcome": "unknown", "proposal_id": "GP-270216-9999", "action_id": "", "notify": "no",
        "notify_title": "", "notify_message": ""}


def test_double_request_applies_once(engine: Engine, gate: Gate, pos: PosWriter,
                                     stubs: Backends, clock: FakeClock) -> None:
    """I4: the second approval answers already_applied with the same action."""
    check = pending(engine, pos)
    first = approve(gate, clock, check)
    second = gate.service.apply_price(**card(check))
    assert (first.status, second.status, second.action_id) == (
        "applied", "already_applied", first.action_id)
    assert len(stubs.showcase.requests) == 1 and len(stubs.showcase.actions) == 1


def audits(engine: Engine, kind: str) -> list[dict[str, Any]]:
    return [r["payload"] for r in engine.service.ctx.db.fetch(
        "select payload from engine.audit_event where kind = %s order by ts", (kind,))]


@pytest.mark.parametrize(("agent_status", "error", "after_s", "outcome", "reason", "audit"), [
    ("denied", "", 4, "rejected", REASON_REJECTED, ""),             # clean deny (R5)
    ("", DENY_TEXT, 4, "rejected", REASON_REJECTED_ERROR, "deny_via_error"),     # R6
    ("", DENY_TEXT, 1, "failed", DENY_TEXT, ""),                     # earlier than a human
    ("", DENY_TEXT, 125, "expired", REASON_EXPIRED, "expired_by_window"),       # R3b
    ("", "Permission denied: connector scope missing", 4, "failed",
     "Permission denied: connector scope missing", ""),
    ("timeout", "", 125, "expired", REASON_EXPIRED, "expired_by_window"),
    ("timeout", "", 5, "failed", REASON_TECHNICAL, ""),
    ("error", "", 4, "failed", REASON_TECHNICAL, ""),
])
def test_deny_timeout_and_errors_by_the_engine_clock(
        engine: Engine, pos: PosWriter, memory_bus: MemoryBus, clock: FakeClock,
        agent_status: str, error: str, after_s: float, outcome: str, reason: str,
        audit: str) -> None:
    """UC1-27: rejected only with positive evidence inside the approval window."""
    check = pending(engine, pos)
    clock.advance(after_s)
    result = engine.service.record_outcome(check.proposal_id, "run-r4", agent_status, "",
                                           error)
    proposal = engine.service.proposal(check.proposal_id)
    assert proposal is not None
    assert (result.outcome, proposal["state"], proposal["status_reason"]) == (
        outcome, outcome, reason)
    if outcome == "rejected":
        assert result.notify_title == f"Abgelehnt: {DUCK} bleibt bei 9,99 €"
        assert result.notify_message == (f"{reason}. Kein neuer Preis. "
                                         f"Ref {check.proposal_id}.")
    elif outcome == "failed":
        assert result.notify_title == NOT_APPLIED
    [event] = published(engine, memory_bus, f"gpos/v1/proposal/{outcome}/101/01/>")
    assert event["status_reason"] == reason
    if audit:
        [row] = audits(engine, audit)
        assert row["elapsed_s"] == after_s
    assert not audits(engine, "deny_via_error") or audit == "deny_via_error"
    assert approval_row(engine, check.proposal_id)["apply_calls"] == 0


SAM_DENIED = "Tool call denied by user."                 # SAM webui DB, task_events 12.11.
SAM_TIMEOUT = "Tool approval timed out after 2 minutes."
UNRESOLVED = "{{approve.output.message}}"


@pytest.mark.parametrize(
    ("agent_status", "message", "after_s", "outcome", "reason", "rule", "path"), [
        ("error", SAM_DENIED, 4, "rejected", REASON_REJECTED, "R5m", "message"),  # F1 12.11.
        ("denied", SAM_DENIED, 4, "rejected", REASON_REJECTED, "R5m", "message"),
        ("", SAM_DENIED, 1, "failed", REASON_DENY_TOO_EARLY, "R5m", "message"),
        ("error", SAM_TIMEOUT, 125, "expired", REASON_EXPIRED, "R3a", "message"),
        ("timeout", SAM_TIMEOUT, 5, "failed", REASON_TECHNICAL, "R7m", "message"),
        ("error", UNRESOLVED, 4, "failed", REASON_TECHNICAL, "R8", "status"),
        ("denied", "", 4, "rejected", REASON_REJECTED, "R5", "status"),        # legacy
    ])
def test_sams_tool_message_decides_and_is_shown(
        engine: Engine, pos: PosWriter, memory_bus: MemoryBus, clock: FakeClock,
        agent_status: str, message: str, after_s: float, outcome: str, reason: str,
        rule: str, path: str) -> None:
    """UC1-29: ``tool_message`` reaches decide_outcome; ``outcome_evidence`` (every
    decision) and ``deny_via_message`` (R5m) are audited and ``approval.evidence`` shows
    rule, path and message read-only."""
    check = pending(engine, pos)
    clock.advance(after_s)
    result = engine.service.record_outcome(check.proposal_id, "run-r4", agent_status, "",
                                           "", tool_message=message)
    assert result.outcome == outcome
    [event] = published(engine, memory_bus, f"gpos/v1/proposal/{outcome}/101/01/>")
    assert event["status_reason"] == reason
    approval = approval_row(engine, check.proposal_id)
    assert (approval["outcome"], approval["agent_status"]) == (outcome, agent_status or None)
    assert approval["evidence"] == {"rule": rule, "path": path, "tool_message": message,
                                    "elapsed_s": after_s}
    [row] = audits(engine, "outcome_evidence")
    assert (row["rule"], row["outcome"], row["run_id"]) == (rule, outcome, "run-r4")
    via = audits(engine, "deny_via_message")
    assert [(r["outcome"], r["agent_status"], r["tool_message"]) for r in via] == (
        [(outcome, agent_status, message)] if rule == "R5m" else [])
    assert approval["apply_calls"] == 0
    again = engine.service.record_outcome(check.proposal_id, "run-r4", "applied", "", "",
                                          tool_message="")
    assert again.outcome == outcome and len(audits(engine, "outcome_evidence")) == 1


def test_f2_sams_denial_after_a_real_approval_is_no_rejection(engine: Engine, pos: PosWriter,
                                                              clock: FakeClock) -> None:
    """R5m keeps the F2 check of R5: SAM's denial text with a valid approval time."""
    check = pending(engine, pos)
    checked_at = clock.now
    clock.advance(5)
    result = engine.service.record_outcome(
        check.proposal_id, "run-r4", "denied", "", "",
        approved_at=(checked_at + timedelta(seconds=4)).isoformat(), tool_message=SAM_DENIED)
    assert result.outcome == "failed"
    assert [len(audits(engine, k)) for k in ("deny_after_approval", "deny_via_message")] == [
        1, 1]
    assert approval_row(engine, check.proposal_id)["evidence"]["rule"] == "R5m"


def test_approval_evidence_is_empty_before_the_outcome(engine: Engine, pos: PosWriter) -> None:
    check = pending(engine, pos)
    assert approval_row(engine, check.proposal_id)["evidence"] is None


def test_gate_rollback_is_no_denial(engine: Engine, gate: Gate, pos: PosWriter,
                                    clock: FakeClock, monkeypatch: pytest.MonkeyPatch) -> None:
    """Finding 1: an exception inside apply_price rolls apply_calls back to 0; the agent's
    error then ends ``failed`` and never „Abgelehnt“."""
    check = pending(engine, pos)

    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("WWS client crashed")

    monkeypatch.setattr(gate.service.wws, "request_price_change", broken)
    with pytest.raises(RuntimeError):
        approve(gate, clock, check)
    approval = approval_row(engine, check.proposal_id)
    assert (approval["apply_calls"], approval["last_apply_status"]) == (0, None)
    result = engine.service.record_outcome(check.proposal_id, "run-r4", "error", "", "")
    assert (result.outcome, result.notify_title) == ("failed", NOT_APPLIED)
    assert "Abgelehnt" not in result.notify_message


def test_f2_denied_after_a_real_approval_is_no_rejection(engine: Engine, pos: PosWriter,
                                                         clock: FakeClock) -> None:
    """4.3/11.5 R5: F2 passes the gated tool's time; denied with a valid time -> failed."""
    check = pending(engine, pos)
    checked_at = clock.now
    clock.advance(5)
    result = engine.service.record_outcome(
        check.proposal_id, "run-r4", "denied", "", "",
        approved_at=(checked_at + timedelta(seconds=4)).isoformat())
    assert result.outcome == "failed"
    assert result.notify_message == (f"{REASON_DENY_AFTER_APPROVAL}. "
                                     f"Ref {check.proposal_id}.")
    [row] = audits(engine, "deny_after_approval")
    assert row["elapsed_s"] == 5 and row["approved_at"].startswith(
        (checked_at + timedelta(seconds=4)).isoformat()[:19])
    engine.service.reset("booth", "101")
    second = pending(engine, pos)
    clock.advance(5)
    assert engine.service.record_outcome(second.proposal_id, "run-r4", "denied", "", "",
                                         approved_at="").outcome == "rejected"
