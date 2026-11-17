"""``record_outcome``: the outcome comes from the DATABASE and the engine clock, never
from the model alone (UC1-BUILD-SPEC 11.5).

Inputs besides the database: the approver's ``agent_status`` (model-relayed), the SAM
error text of ``on_exit`` (``workflow.error.message``; the prefix "Agent reported
error:" is the platform's, the rest model wording), the approver's copy of the gated
tool result's ``message`` (``tool_message``; on a denial SAM writes "Tool call denied
by user.", on an HIL timeout "Tool approval timed out after 2 minutes.") and
``elapsed`` = now - ``approval.checked_at``. A ``tool_message`` counts only while the
gate is untouched (then the tool never ran and the text is SAM's) and never when it is
an unresolved ``{{…}}`` reference. The approval request exists only ~1.6-3.5 s after
``checked_at`` (A-14) and the HIL window ends ``HIL_TIMEOUT_S`` (120 s) after it, so a
human answer is impossible below ``GATE_MIN_DELAY_S`` and an HIL timeout impossible
below ``HIL_TIMEOUT_S``. "Untouched" = ``apply_calls`` 0 and no ``last_apply_status``:
a necessary condition of a denial, never a proof (a timeout, a call that never
happened, an LLM error or a gate rollback leave the gate untouched too).

Rules (the first match wins; texts in ``texts.py``):

R1 a ``price_change`` exists -> ``approved`` (a different agent status is audited);
R2 proposal ``superseded``/``expired``/``failed`` (watchdog, R4 error, reset) -> unchanged;
R3a a timeout text (error text or ``tool_message``) -> ``expired``, but only once
    ``elapsed >= HIL_TIMEOUT_S`` (or without ``checked_at``, legacy); a timeout text
    before that falls through to R7m/R7;
R3b untouched gate, ``elapsed >= HIL_TIMEOUT_S``, no technical text (error text or
    ``tool_message``) and the agent does not claim ``applied``/``blocked`` -> ``expired``
    (audit ``expired_by_window``); a denial in ``tool_message`` does not count here;
R4 last ``apply_price`` status ``blocked`` -> ``blocked`` with the gate's message;
R7m ``tool_message`` is a timeout inside the window (impossible for a human answer), or,
    while the agent says ``denied``, technical or a tool error without a denial word
    (``approval_text.is_tool_error``) -> ``failed`` (technical);
R5m ``tool_message`` is a denial (SAM's words), known ``elapsed``, agent status
    ``""``/``error``/``denied``/other, no technical or timeout error text: the checks of
    R5 (too early, F2 ``approved_at``), else ``rejected`` "Abgelehnt in Agent Mesh"
    (audit ``deny_via_message``);
R5 untouched gate, agent status exactly ``denied`` (classify_status), no error text:
    earlier than ``GATE_MIN_DELAY_S`` -> ``failed`` (too early); F2 with a valid
    approval time (``approved_at``) -> ``failed`` (audit ``deny_after_approval``);
    else ``rejected`` "Abgelehnt in Agent Mesh";
R6 untouched gate, no agent status, the error text is a denial with approval context
    and no technical or timeout word (``common.approval_text``), inside the window ->
    ``rejected`` "… (Agent meldete einen Fehler)" (audit ``deny_via_error``);
R7 any other error text (technical, other, an early timeout or denial) -> ``failed``
    with the shortened text;
R8 no error text: agent claims ``applied``/``blocked``/``denied`` -> ``failed``
    (contradiction); no status -> ``failed`` (no status); else ``failed`` (technical).

Every misclassification still ends without a price; only the label differs. A second
call for the same proposal returns the recorded outcome (idempotent). Every decision
leaves an audit row ``outcome_evidence`` (rule, evidence path, ``tool_message``) that
``GET /api/proposals/{id}`` shows as ``approval.evidence``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ..common import approval_text
from . import notify, store, texts
from .context import Context
from .models import OutcomeResult
from .records import ProposalRecord
from .texts import (
    REASON_CONTRADICTION,
    REASON_DENY_AFTER_APPROVAL,
    REASON_DENY_TOO_EARLY,
    REASON_EXPIRED,
    REASON_NO_STATUS,
    REASON_REJECTED,
    REASON_REJECTED_ERROR,
    REASON_TECHNICAL,
)

log = logging.getLogger(__name__)

HIL_TIMEOUT_S = 120.0              # default of settings.hil_timeout_s = hil.timeout "2m"
APPROVED_AT_TOLERANCE_S = 2.0      # = gate.service.F2_FUTURE_TOLERANCE_S (unit test)
UNCHANGED = ("superseded", "expired", "failed")
AUDIT_SHORT = 300
MESSAGE_SHORT = 200                # = the approver prompt's limit for message
# agent statuses (classify_status) under which a denial message counts (R5m); applied,
# blocked and timeout contradict it and fall through to R8
MESSAGE_DENY_AGENT = ("", "error", "denied", "other")
EVIDENCE_AUDIT = "outcome_evidence"

__all__ = ["APPROVED_AT_TOLERANCE_S", "EVIDENCE_AUDIT", "HIL_TIMEOUT_S",
           "REASON_CONTRADICTION", "REASON_DENY_AFTER_APPROVAL", "REASON_DENY_TOO_EARLY",
           "REASON_EXPIRED", "REASON_NO_STATUS", "REASON_REJECTED", "REASON_REJECTED_ERROR",
           "REASON_TECHNICAL", "UNCHANGED", "Decision", "Outcomes", "approval_time_ok",
           "decide_outcome", "evidence_text"]


@dataclass(frozen=True)
class Decision:
    outcome: str
    status_reason: str
    rule: str = ""
    # what decided: price_change|state|status|message|error|window|gate (e2e, audit)
    evidence: str = ""


def evidence_text(text: str) -> str:
    """``text`` folded to one line, or ``""`` when it is empty or an unresolved
    workflow reference (``{{…}}`` stays text when SAM cannot resolve it, 9.1)."""
    folded = " ".join((text or "").split())
    return "" if "{{" in folded else folded


def decide_outcome(*, status: str, has_price_change: bool, agent_status: str, error: str,
                   last_apply_status: str | None, apply_error: str | None,
                   status_reason: str | None, apply_calls: int = 0,
                   elapsed_s: float | None = None, min_delay_s: float = 3.0,
                   hil_timeout_s: float = HIL_TIMEOUT_S,
                   approved_at_ok: bool = False, tool_message: str = "") -> Decision:
    """The table R1-R8 of 11.5 with R5m/R7m as a pure function (module docstring)."""
    agent = approval_text.classify_status(agent_status)
    err = approval_text.classify_error(error)
    untouched = apply_calls == 0 and not last_apply_status
    # SAM's words count only while the tool never ran (a touched gate wrote its own)
    text = evidence_text(tool_message) if untouched else ""
    msg = approval_text.classify_error(text)
    known = elapsed_s is not None          # unknown only without check_proposal (legacy)
    after_window = known and elapsed_s >= hil_timeout_s  # type: ignore[operator]
    early = known and elapsed_s < min_delay_s  # type: ignore[operator]
    # R1 a price change always wins
    if has_price_change:
        return Decision("approved", "", "R1", "price_change")
    # R2 watchdog / R4 error / reset already decided
    if status in UNCHANGED:
        return Decision(status, status_reason or "", "R2", "state")
    # R3a a timeout text is the approval timeout only once the window is over
    if "timeout" in (err, msg) and (after_window or not known):
        return Decision("expired", REASON_EXPIRED, "R3a",
                        "error" if err == "timeout" else "message")
    # R3b after the window nobody can answer any more: an untouched gate without a
    #     technical text (error text or tool message) is the approval timeout, whatever
    #     the agent reports
    if (untouched and after_window and "technical" not in (err, msg)
            and agent not in ("applied", "blocked")):
        return Decision("expired", REASON_EXPIRED, "R3b", "window")
    # R4 gate refused
    if last_apply_status == "blocked":
        return Decision("blocked", apply_error or "Blockiert durch Leitplanke", "R4", "gate")
    # R7m SAM's timeout inside the window, or a technical or failed tool result the agent
    #     calls a denial: never a human answer
    if msg == "timeout" or (agent == "denied" and (
            msg == "technical" or (msg == "other" and approval_text.is_tool_error(text)))):
        return Decision("failed", REASON_TECHNICAL, "R7m", "message")
    # R5m SAM's denial text, whatever (non-contradicting) status the agent reported
    if (msg == "denied" and known and agent in MESSAGE_DENY_AGENT
            and err not in ("timeout", "technical")):
        if early:
            return Decision("failed", REASON_DENY_TOO_EARLY, "R5m", "message")
        if approved_at_ok:
            return Decision("failed", REASON_DENY_AFTER_APPROVAL, "R5m", "message")
        return Decision("rejected", REASON_REJECTED, "R5m", "message")
    # R5 clean denial: only the exact status denied (a human needs the request first)
    if untouched and agent == "denied" and not error.strip():
        if early:
            return Decision("failed", REASON_DENY_TOO_EARLY, "R5", "status")
        if approved_at_ok:
            return Decision("failed", REASON_DENY_AFTER_APPROVAL, "R5", "status")
        return Decision("rejected", REASON_REJECTED, "R5", "status")
    # R6 deterministic fallback: the agent ended its task with the denial as an error
    if untouched and agent == "" and err == "denied" and known and not early:
        return Decision("rejected", REASON_REJECTED_ERROR, "R6", "error")
    # R7 any other error text: technical, other, a timeout inside the window, an early
    #    denial
    if error.strip():
        return Decision("failed", texts.shorten(" ".join(error.split()), 200), "R7", "error")
    # R8 no error text
    if agent in ("applied", "blocked", "denied"):
        return Decision("failed", REASON_CONTRADICTION, "R8", "status")
    if agent == "":
        return Decision("failed", REASON_NO_STATUS, "R8", "status")
    return Decision("failed", REASON_TECHNICAL, "R8", "status")   # error, early timeout, other


def _parse_aware(text: str) -> datetime | None:
    """ISO 8601 with an offset (same parse as ``gate.service._parse_aware``)."""
    try:
        value = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo is not None else None


def approval_time_ok(approved_at: str, checked: datetime | None, now: datetime,
                     min_delay_s: float) -> bool:
    """F2: ``approved_at`` is a real approval time of this request, i.e. within
    ``[checked + min_delay, now + APPROVED_AT_TOLERANCE_S]`` on the engine clock."""
    if checked is None or not (approved_at or "").strip():
        return False
    at = _parse_aware(approved_at)
    if at is None:
        return False
    return (checked + timedelta(seconds=min_delay_s) <= at
            <= now + timedelta(seconds=APPROVED_AT_TOLERANCE_S))


class Outcomes:
    """Implements ``record_outcome``."""

    def __init__(self, ctx: Context):
        self.ctx = ctx

    def record(self, proposal_id: str, run_id: str, agent_status: str, action_id: str,
               error: str, approved_at: str = "", tool_message: str = "") -> OutcomeResult:
        settings = self.ctx.settings
        with self.ctx.db.tx() as conn:
            p = store.proposal(conn, proposal_id, lock=True)
            if p is None:
                return OutcomeResult(outcome="unknown", proposal_id=proposal_id)
            approval = store.approval(conn, proposal_id, lock=True)
            change = store.price_change(conn, proposal_id)
            applied_id = change["action_id"] if change else ""
            if approval is not None and approval["outcome"]:
                return self._result(p, approval["outcome"], applied_id)
            now = self.ctx.clock()
            checked = approval["checked_at"] if approval else None
            elapsed_s = (now - checked).total_seconds() if checked else None
            decision = decide_outcome(
                status=p.status, has_price_change=change is not None,
                agent_status=agent_status, error=error,
                last_apply_status=approval["last_apply_status"] if approval else None,
                apply_error=approval["error"] if approval else None,
                status_reason=p.status_reason,
                apply_calls=int(approval["apply_calls"] or 0) if approval else 0,
                elapsed_s=elapsed_s, min_delay_s=settings.gate_min_delay_s,
                hil_timeout_s=settings.hil_timeout_s,
                approved_at_ok=approval_time_ok(approved_at, checked, now,
                                                settings.gate_min_delay_s),
                tool_message=tool_message)
            if change is not None and approval_text.classify_status(agent_status) != "applied":
                log.warning("record_outcome %s: agent said %r, database says approved "
                            "(%s)", proposal_id, agent_status, applied_id)
                store.audit(conn, "outcome_mismatch", proposal_id,
                            {"agent_status": agent_status, "agent_action_id": action_id,
                             "action_id": applied_id, "run_id": run_id}, now)
            self._audit(conn, proposal_id, decision, agent_status, error, approved_at,
                        tool_message, elapsed_s, run_id, now)
            self._write_approval(conn, proposal_id, approval, decision, agent_status, error,
                                 run_id, now)
            if p.is_open:
                p = store.set_proposal(conn, proposal_id, status=decision.outcome,
                                       status_reason=decision.status_reason or None,
                                       decided_at=now)
                self.ctx.emitter.proposal_state(conn, p, run_id, action_id=applied_id)
        return self._result(p, decision.outcome, applied_id)

    def _audit(self, conn: store.Conn, proposal_id: str, decision: Decision,
               agent_status: str, error: str, approved_at: str, tool_message: str,
               elapsed_s: float | None, run_id: str, now: datetime) -> None:
        """``outcome_evidence`` for every decision, plus the rows of the evidence-based
        rules (R6, R5m, R3b, R5/R5m after an approval)."""
        elapsed = None if elapsed_s is None else round(elapsed_s, 1)
        short = texts.shorten(" ".join(error.split()), AUDIT_SHORT)
        message = texts.shorten(" ".join((tool_message or "").split()), MESSAGE_SHORT)
        store.audit(conn, EVIDENCE_AUDIT, proposal_id,
                    {"rule": decision.rule, "evidence": decision.evidence,
                     "outcome": decision.outcome, "agent_status": agent_status,
                     "tool_message": message, "elapsed_s": elapsed, "run_id": run_id}, now)
        if decision.rule == "R5m":
            log.info("record_outcome %s: denial recognised in the tool message (%s)",
                     proposal_id, decision.outcome)
            store.audit(conn, "deny_via_message", proposal_id,
                        {"tool_message": message, "agent_status": agent_status,
                         "outcome": decision.outcome, "elapsed_s": elapsed,
                         "run_id": run_id}, now)
        if decision.rule == "R6":
            log.info("record_outcome %s: denial recognised in the error text", proposal_id)
            store.audit(conn, "deny_via_error", proposal_id,
                        {"error": short, "elapsed_s": elapsed, "run_id": run_id}, now)
        elif decision.rule == "R3b":
            store.audit(conn, "expired_by_window", proposal_id,
                        {"agent_status": agent_status, "error": short, "elapsed_s": elapsed,
                         "run_id": run_id}, now)
        elif (decision.rule in ("R5", "R5m")
              and decision.status_reason == REASON_DENY_AFTER_APPROVAL):
            log.warning("record_outcome %s: agent reports denied after an approval",
                        proposal_id)
            store.audit(conn, "deny_after_approval", proposal_id,
                        {"approved_at": approved_at, "elapsed_s": elapsed,
                         "run_id": run_id}, now)

    def _write_approval(self, conn: store.Conn, proposal_id: str,
                        approval: dict[str, Any] | None, decision: Decision,
                        agent_status: str, error: str, run_id: str, now: Any) -> None:
        if approval is None:
            conn.execute(
                "insert into engine.approval (proposal_id, run_id, checked_at, agent_status, "
                "outcome, error, decided_at) values (%s, %s, %s, %s, %s, %s, %s)",
                (proposal_id, run_id, now, agent_status or None, decision.outcome,
                 error or None, now))
            return
        changes: dict[str, Any] = {"agent_status": agent_status or None,
                                   "outcome": decision.outcome, "decided_at": now}
        if error and not approval["error"]:
            changes["error"] = texts.shorten(error, 500)
        store.set_approval(conn, proposal_id, **changes)

    def _result(self, p: ProposalRecord, outcome: str, action_id: str) -> OutcomeResult:
        title, message = notify.tell(outcome, p, self.ctx.zone, action_id,
                                     p.status_reason or "")
        return OutcomeResult(outcome=outcome, proposal_id=p.proposal_id, action_id=action_id,
                             notify="yes" if title else "no", notify_title=title,
                             notify_message=message)
