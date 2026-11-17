"""``EngineService``: the pure methods behind ``gpos-booth-tools`` and the engine HTTP
API (UC1-BUILD-SPEC 2.4 service contract, 8.2, 11).

One method per MCP tool with the same ``str`` parameters in the same order (5.1: new
optional parameters are appended after ``run_id``; the MCP tools call with keywords
only), plus ``reset``, ``sam_error`` and the read models of 11.8.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from ..common.clock import iso_ts
from . import store
from .context import Context
from .ingest import Ingest
from .models import (
    AssessResult,
    CheckResult,
    EvidenceResult,
    OutcomeResult,
    PrepareReviewResult,
    ReviewTriggerResult,
    StageResult,
    StatusResult,
)
from .outcome import EVIDENCE_AUDIT, Outcomes
from .proposals import Proposals
from .records import ProposalRecord, ReviewRecord
from .review import Reviews, Slot
from .state import proposal_payload, review_payload
from .watchdog import Maintenance

APPROVAL_TIMES = ("checked_at", "first_apply_at", "sam_error_at", "decided_at")
# read-only view of the outcome_evidence audit row (11.5): rule, evidence path, message
EVIDENCE_KEYS = {"rule": "rule", "path": "evidence", "tool_message": "tool_message",
                 "elapsed_s": "elapsed_s"}


class EngineService:
    """Business methods of ``gpos-engine``; returns Pydantic models or dicts."""

    def __init__(self, ctx: Context, on_sam_error: Callable[[], None] | None = None):
        self.ctx = ctx
        self._ingest = Ingest(ctx)
        self._reviews = Reviews(ctx)
        self._proposals = Proposals(ctx)
        self._outcomes = Outcomes(ctx)
        self.maintenance = Maintenance(ctx)
        self._on_sam_error = on_sam_error

    # ------------------------------------------------------------- workflow tools
    def assess_event(self, raw: str, run_id: str = "") -> AssessResult:
        return self._ingest.assess(raw, run_id)

    def raise_basket_review(self, tx_id: str, run_id: str = "") -> ReviewTriggerResult:
        return self._reviews.raise_review(tx_id, run_id)

    def note_event(self, event_key: str, verdict: str, run_id: str = "") -> StatusResult:
        """Nothing to do but telemetry (the MCP layer publishes it)."""
        return StatusResult(status="noted", event_key=event_key, verdict=verdict)

    def prepare_review(self, review_id: str, run_id: str = "") -> PrepareReviewResult:
        return self._reviews.prepare(review_id, run_id)

    def note_evidence(self, review_id: str, model: str = "", tx_status: str = "",
                      c1_article: str = "", c1_reason: str = "", c1_holds: str = "",
                      c1_numbers: str = "", c1_tools: str = "", c2_article: str = "",
                      c2_reason: str = "", c2_holds: str = "", c2_numbers: str = "",
                      c2_tools: str = "", run_id: str = "") -> EvidenceResult:
        slots = [Slot(c1_article, c1_reason, c1_holds, c1_numbers, c1_tools),
                 Slot(c2_article, c2_reason, c2_holds, c2_numbers, c2_tools)]
        return self._reviews.note_evidence(review_id, model, tx_status, slots, run_id)

    def stage_proposal(self, review_id: str, article_number: str, reason: str, step_pct: str,
                       headline: str, rationale: str, facts_line: str,
                       run_id: str = "", model: str = "") -> StageResult:
        return self._proposals.stage(review_id, article_number, reason, step_pct, headline,
                                     rationale, facts_line, run_id=run_id, model=model)

    def close_review(self, review_id: str, outcome: str, rationale: str,
                     run_id: str = "", model: str = "") -> StatusResult:
        return self._reviews.close(review_id, outcome, rationale, run_id, model=model)

    def check_proposal(self, proposal_id: str, run_id: str = "") -> CheckResult:
        return self._proposals.check(proposal_id, run_id)

    def record_outcome(self, proposal_id: str, run_id: str = "", agent_status: str = "",
                       action_id: str = "", error: str = "", approved_at: str = "",
                       tool_message: str = "") -> OutcomeResult:
        return self._outcomes.record(proposal_id, run_id, agent_status, action_id, error,
                                     approved_at=approved_at, tool_message=tool_message)

    # ------------------------------------------------------------- 2.4 extras
    def reset(self, scope: str, store_id: str) -> dict[str, Any]:
        return self.maintenance.reset(scope, store_id)

    def sam_error(self, rule: str, store: str, till: str, error: str) -> dict[str, Any]:
        result = self.maintenance.sam_error(rule, store, till, error)
        if result["status"] == "noted" and self._on_sam_error is not None:
            self._on_sam_error()
        return result

    # ------------------------------------------------------------- read models (11.8)
    def state(self, store_id: str, till_id: str) -> dict[str, Any]:
        """``GET /api/state``: last review, open or last proposal, counters."""
        with self.ctx.db.tx() as conn:
            review = store.latest_review(conn, store_id, till_id)
            p = (store.open_proposal(conn, store_id, till_id)
                 or store.latest_proposal(conn, store_id, till_id))
            counts = conn.execute(
                "select (select count(*) from engine.review where store_id = %(s)s "
                "and till_id = %(t)s) as reviews, (select count(*) from engine.proposal "
                "where store_id = %(s)s and till_id = %(t)s) as proposals, "
                "(select count(*) from engine.proposal where store_id = %(s)s "
                "and till_id = %(t)s and status = 'approved') as approved",
                {"s": store_id, "t": till_id}).fetchone()
            assert counts is not None
            return {"review": self._review_json(conn, review) if review else None,
                    "proposal": self._proposal_json(conn, p) if p else None,
                    "counts": {k: int(counts[k]) for k in ("reviews", "proposals", "approved")}}

    def review(self, review_id: str) -> dict[str, Any] | None:
        """``GET /api/reviews/{id}``"""
        with self.ctx.db.tx() as conn:
            review = store.review(conn, review_id)
            return self._review_json(conn, review) if review else None

    def proposal(self, proposal_id: str) -> dict[str, Any] | None:
        """``GET /api/proposals/{id}`` including the ``approval`` row."""
        with self.ctx.db.tx() as conn:
            p = store.proposal(conn, proposal_id)
            return self._proposal_json(conn, p) if p else None

    def _iso(self, value: datetime | None) -> str | None:
        return iso_ts(value, self.ctx.settings.tz) if value else None

    def _review_json(self, conn: store.Conn, r: ReviewRecord) -> dict[str, Any]:
        row = conn.execute("select proposal_id from engine.proposal where review_id = %s",
                           (r.review_id,)).fetchone()
        body = review_payload(r, r.status, r.run_id_review or r.run_id_raise or "",
                              self.ctx.emitter.ts(),
                              proposal_id=row["proposal_id"] if row else "")
        body.update(agent_input=r.agent_input, created_at=self._iso(r.created_at),
                    prepared_at=self._iso(r.prepared_at), decided_at=self._iso(r.decided_at))
        return body

    def _proposal_json(self, conn: store.Conn, p: ProposalRecord) -> dict[str, Any]:
        change = store.price_change(conn, p.proposal_id)
        approval = store.approval(conn, p.proposal_id)
        body = proposal_payload(p, p.status, p.run_id_approval or p.run_id_stage or "",
                                self.ctx.emitter.ts(), self.ctx.zone,
                                action_id=change["action_id"] if change else "")
        body.update(status_reason=p.status_reason or "", proposal_hash=p.proposal_hash,
                    step_requested=p.step_requested, created_at=self._iso(p.created_at),
                    pending_at=self._iso(p.pending_at), decided_at=self._iso(p.decided_at),
                    approval=self._approval_json(conn, approval) if approval else None)
        return body

    def _approval_json(self, conn: store.Conn, approval: dict[str, Any]) -> dict[str, Any]:
        """The ``approval`` row plus ``evidence`` (what ``record_outcome`` decided by:
        rule, path, ``tool_message``; ``None`` before an outcome)."""
        out = dict(approval)
        for key in APPROVAL_TIMES:
            out[key] = self._iso(approval[key])
        audit = store.latest_audit(conn, EVIDENCE_AUDIT, approval["proposal_id"])
        out["evidence"] = ({key: audit.get(src) for key, src in EVIDENCE_KEYS.items()}
                           if audit else None)
        return out
