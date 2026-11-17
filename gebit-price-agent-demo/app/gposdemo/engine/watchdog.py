"""Watchdog, R4 error handling and reset (UC1-BUILD-SPEC 11.7, 11.8).

Watchdog (every 5 s, technical time):

* review ``requested`` > 60 s -> ``failed`` ("SAM-Lauf nicht gestartet"); ``prepared``
  > 180 s -> ``failed`` ("Agent-Zeitüberschreitung"; R3 has two agent nodes, 150 s);
* proposal ``ready`` > 60 s -> ``failed`` ("Freigabe-Lauf nicht gestartet");
  ``pending`` > ``PROPOSAL_EXPIRY_SECONDS`` without outcome -> ``expired``;
* R4 errors reported by the BFF (``sam_error``) are settled after a 5 s grace (so the
  ``on_exit`` node ``record_fail`` writes first): a proposal of that till that is still
  ``pending`` without outcome is classified like ``record_outcome`` does (11.5 R1-R8,
  ``decide_outcome`` on the joined error texts and ``sam_error_at - checked_at``):
  ``expired``/``rejected``/``blocked`` with the rule's reason, else ``failed`` ("SAM-Lauf
  abgebrochen").

Every change publishes the new state.
"""

from __future__ import annotations

import logging
import threading
from datetime import timedelta
from typing import Any

from . import store
from .context import Context
from .outcome import decide_outcome
from .proposals import READY_TIMEOUT_S
from .records import ProposalRecord
from .texts import REASON_EXPIRED

log = logging.getLogger(__name__)

INTERVAL_S = 5.0
REVIEW_REQUESTED_TIMEOUT_S = 60
REVIEW_PREPARED_TIMEOUT_S = 180
SAM_ERROR_GRACE_S = 5.0
SAM_ERROR_RULES = ("r4", "p4")
SAM_ERROR_JOIN = " | "
REASON_NOT_STARTED = "SAM-Lauf nicht gestartet"
REASON_AGENT_TIMEOUT = "Agent-Zeitüberschreitung"
REASON_APPROVAL_NOT_STARTED = "Freigabe-Lauf nicht gestartet"
REASON_SAM_ABORTED = "SAM-Lauf abgebrochen"
REASON_RESET = "Zurückgesetzt"
RESET_SCOPES = ("booth", "day")
DAY_TABLES = ("engine.event_inbox", "engine.insight", "engine.tool_call", "engine.price_change",
              "engine.approval", "engine.proposal", "engine.review")


class Maintenance:
    """Timeouts, R4 errors and reset; every method is safe to call repeatedly."""

    def __init__(self, ctx: Context):
        self.ctx = ctx

    # ------------------------------------------------------------- watchdog
    def sweep(self) -> dict[str, int]:
        """One watchdog round; returns how many objects changed per rule."""
        now = self.ctx.clock()
        expiry = self.ctx.settings.proposal_expiry_seconds
        counts = {
            "reviews_requested": self._fail_reviews(
                "requested", "created_at", now - timedelta(seconds=REVIEW_REQUESTED_TIMEOUT_S),
                REASON_NOT_STARTED),
            "reviews_prepared": self._fail_reviews(
                "prepared", "prepared_at", now - timedelta(seconds=REVIEW_PREPARED_TIMEOUT_S),
                REASON_AGENT_TIMEOUT),
            "proposals_ready": self._end_proposals(
                "ready", "created_at", now - timedelta(seconds=READY_TIMEOUT_S),
                "failed", REASON_APPROVAL_NOT_STARTED),
            "proposals_pending": self._end_proposals(
                "pending", "pending_at", now - timedelta(seconds=expiry), "expired",
                REASON_EXPIRED),
            "sam_errors": self.settle_sam_errors()}
        if any(counts.values()):
            log.info("watchdog: %s", counts)
        return counts

    def _fail_reviews(self, status: str, column: str, before: Any, reason: str) -> int:
        with self.ctx.db.tx() as conn:
            ids = [r["review_id"] for r in conn.execute(
                f"select review_id from engine.review where status = %s and {column} < %s",
                (status, before)).fetchall()]
        changed = 0
        for review_id in ids:
            with self.ctx.db.tx() as conn:
                review = store.review(conn, review_id, lock=True)
                if review is None or review.status != status:
                    continue
                updated = store.set_review(conn, review_id, status="failed", error=reason,
                                           decided_at=self.ctx.clock())
                self.ctx.emitter.review_state(conn, updated, "")
                changed += 1
        return changed

    def _end_proposals(self, status: str, column: str, before: Any, outcome: str,
                       reason: str) -> int:
        with self.ctx.db.tx() as conn:
            ids = [r["proposal_id"] for r in conn.execute(
                f"select proposal_id from engine.proposal where status = %s and {column} < %s",
                (status, before)).fetchall()]
        return sum(self._end(proposal_id, status, outcome, reason) for proposal_id in ids)

    def _end(self, proposal_id: str, status: str, outcome: str, reason: str) -> int:
        """End one proposal still in ``status`` without outcome; 1 if it changed."""
        with self.ctx.db.tx() as conn:
            p = store.proposal(conn, proposal_id, lock=True)
            approval = store.approval(conn, proposal_id, lock=True)
            if p is None or p.status != status or (approval and approval["outcome"]):
                return 0
            self._finish(conn, p, approval is not None, outcome, reason)
        return 1

    def _finish(self, conn: store.Conn, p: ProposalRecord, has_approval: bool, outcome: str,
                reason: str) -> None:
        now = self.ctx.clock()
        if has_approval:
            store.set_approval(conn, p.proposal_id, outcome=outcome, decided_at=now)
        updated = store.set_proposal(conn, p.proposal_id, status=outcome, status_reason=reason,
                                     decided_at=now)
        self.ctx.emitter.proposal_state(conn, updated, p.run_id_approval or "")

    # ------------------------------------------------------------- R4 errors
    def sam_error(self, rule: str, store_id: str, till_id: str, error: str) -> dict[str, Any]:
        """``POST /api/sam-error``: mark the pending proposal of the till; settled after
        :data:`SAM_ERROR_GRACE_S`. Idempotent (``errorOutput`` arrives twice)."""
        if rule not in SAM_ERROR_RULES:
            raise ValueError(f"rule must be one of {SAM_ERROR_RULES}, got {rule!r}")
        with self.ctx.db.tx() as conn:
            p = store.open_proposal(conn, store_id, till_id, lock=True)
            approval = store.approval(conn, p.proposal_id, lock=True) if p else None
            if p is None or p.status != "pending" or approval is None:
                return {"status": "no_pending_proposal", "store": store_id, "till": till_id}
            now = self.ctx.clock()
            conn.execute("update engine.approval set sam_error_at = coalesce(sam_error_at, %s) "
                         "where proposal_id = %s", (now, p.proposal_id))
            store.audit(conn, "sam_error", p.proposal_id, {"rule": rule, "error": error}, now)
        return {"status": "noted", "proposal_id": p.proposal_id,
                "settle_after_s": SAM_ERROR_GRACE_S}

    def settle_sam_errors(self) -> int:
        """Settle every R4 error older than the grace; returns how many proposals ended."""
        settings = self.ctx.settings
        before = self.ctx.clock() - timedelta(seconds=SAM_ERROR_GRACE_S)
        with self.ctx.db.tx() as conn:
            rows = conn.execute(
                "select a.proposal_id, a.checked_at, a.apply_calls, a.last_apply_status, "
                "a.error, a.sam_error_at from engine.approval a join engine.proposal p "
                "using (proposal_id) where p.status = 'pending' and a.outcome is null "
                "and a.sam_error_at is not null and a.sam_error_at <= %s",
                (before,)).fetchall()
        changed = 0
        for row in rows:
            proposal_id = row["proposal_id"]
            with self.ctx.db.tx() as conn:
                errors = [r["error"] for r in conn.execute(
                    "select payload->>'error' as error from engine.audit_event "
                    "where kind = 'sam_error' and ref = %s order by ts",
                    (proposal_id,)).fetchall()]
            checked = row["checked_at"]
            decision = decide_outcome(
                status="pending", has_price_change=False, agent_status="",
                error=SAM_ERROR_JOIN.join(e for e in errors if e),
                last_apply_status=row["last_apply_status"], apply_error=row["error"],
                status_reason=None, apply_calls=int(row["apply_calls"] or 0),
                elapsed_s=((row["sam_error_at"] - checked).total_seconds()
                           if checked else None),
                min_delay_s=settings.gate_min_delay_s, hil_timeout_s=settings.hil_timeout_s)
            reason = (REASON_SAM_ABORTED if decision.outcome == "failed"
                      else decision.status_reason)
            log.info("sam_error %s: %s (%s)", proposal_id, decision.outcome, decision.rule)
            changed += self._end(proposal_id, "pending", decision.outcome, reason)
        return changed

    # ------------------------------------------------------------- reset
    def reset(self, scope: str, store_id: str) -> dict[str, Any]:
        """Step 1 of the reset chain (11.7): open reviews and proposals of the store
        ``superseded``; scope ``day`` additionally empties the runtime tables. Sequences
        are never reset (WWS keeps proposal ids of ended actions)."""
        if scope not in RESET_SCOPES:
            raise ValueError(f"scope must be one of {RESET_SCOPES}, got {scope!r}")
        reviews = proposals = 0
        with self.ctx.db.tx() as conn:
            now = self.ctx.clock()
            for row in conn.execute(
                    "select review_id from engine.review where store_id = %s "
                    "and status in ('requested', 'prepared') for update", (store_id,)).fetchall():
                updated = store.set_review(conn, row["review_id"], status="superseded",
                                           error=REASON_RESET, decided_at=now)
                self.ctx.emitter.review_state(conn, updated, "")
                reviews += 1
            for row in conn.execute(
                    "select proposal_id from engine.proposal where store_id = %s "
                    "and status in ('ready', 'pending') for update", (store_id,)).fetchall():
                p = store.proposal(conn, row["proposal_id"])
                assert p is not None
                approval = store.approval(conn, p.proposal_id, lock=True)
                self._finish(conn, p, approval is not None, "superseded", REASON_RESET)
                proposals += 1
            if scope == "day":
                conn.execute(f"truncate {', '.join(DAY_TABLES)}")
            store.audit(conn, "reset", store_id, {"scope": scope, "reviews": reviews,
                                                  "proposals": proposals}, now)
        return {"scope": scope, "store_id": store_id, "reviews_superseded": reviews,
                "proposals_superseded": proposals, "truncated": scope == "day"}


class Watchdog(threading.Thread):
    """Runs :meth:`Maintenance.sweep` every :data:`INTERVAL_S` seconds."""

    def __init__(self, maintenance: Maintenance, interval_s: float = INTERVAL_S):
        super().__init__(name="engine-watchdog", daemon=True)
        self._maintenance = maintenance
        self._interval = interval_s
        self._halt = threading.Event()

    def run(self) -> None:
        while not self._halt.wait(self._interval):
            try:
                self._maintenance.sweep()
            except Exception:
                log.exception("watchdog round failed")

    def settle_later(self) -> None:
        """Settle R4 errors right after the grace instead of the next round."""
        timer = threading.Timer(SAM_ERROR_GRACE_S + 0.1, self._settle)
        timer.daemon = True
        timer.start()

    def _settle(self) -> None:
        if self._halt.is_set():
            return
        try:
            self._maintenance.settle_sam_errors()
        except Exception:
            log.exception("settling R4 errors failed")

    def stop(self, timeout: float = 5.0) -> None:
        self._halt.set()
        if self.is_alive():
            self.join(timeout)
