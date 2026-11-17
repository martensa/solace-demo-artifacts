"""Own event payloads of engine and gate (UC1-BUILD-SPEC 7.2, 7.3) and their outbox.

UI payloads carry ``schema_version``, ``type`` and ``ts``. The SAM inputs
``review/request`` and ``approval/request`` carry EXACTLY the keys of 7.2 and nothing
else: every key must be declared in the ``input_schema`` of the target workflow, an
undeclared one silently empties the whole input (finding 3).

Aggregates of the ``engine`` outbox: ``review_id`` for review events, ``proposal_id``
for proposal events and the approval request; offsets via ``OutboxWriter.next_offset``
under the row lock the caller holds.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..common import topics
from ..common.clock import iso_ts
from ..common.jsonutil import compact
from ..common.outbox import OutboxWriter
from .records import ProposalRecord, ReviewRecord
from .store import Conn

REVIEW_REQUEST_KEYS = ("schema_version", "review_id", "tx_id", "store", "till")
APPROVAL_REQUEST_KEYS = ("schema_version", "proposal_id", "store", "till")
END_STATES = ("approved", "rejected", "expired", "failed", "superseded", "blocked")


def review_request(r: ReviewRecord) -> dict[str, Any]:
    """Input of R3 (``gpos-basket-review``): exactly :data:`REVIEW_REQUEST_KEYS`."""
    return {"schema_version": "1", "review_id": r.review_id, "tx_id": r.tx_id,
            "store": r.store_id, "till": r.till_id}


def approval_request(p: ProposalRecord) -> dict[str, Any]:
    """Input of R4 (``gpos-price-approval``): exactly :data:`APPROVAL_REQUEST_KEYS`."""
    return {"schema_version": "1", "proposal_id": p.proposal_id, "store": p.store_id,
            "till": p.till_id}


def card_of(r: ReviewRecord) -> dict[str, Any] | None:
    """Loyalty card of a review: from ``agent_input`` when prepared, else the id only."""
    if not r.membership_id:
        return None
    if r.agent_input:
        card = json.loads(r.agent_input).get("card")
        if isinstance(card, dict):
            return card
    return {"membership_id": r.membership_id}


def free_candidates(r: ReviewRecord) -> int:
    return sum(1 for line in r.lines if line.get("candidate") and not line.get("blocked"))


def split_decision(agent_decision: dict[str, Any] | None
                   ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """``(evidence, decision)`` of ``review.agent_decision`` (7.2): ``evidence`` = what
    ``note_evidence`` stored (fast), ``decision`` = the rest, only once it holds the key
    ``decision`` (planning; ``model`` missing or ``""`` = legacy, read as ``fast``)."""
    stored = agent_decision or {}
    evidence = stored.get("evidence")
    decision = ({k: v for k, v in stored.items() if k != "evidence"}
                if "decision" in stored else None)
    return (evidence if isinstance(evidence, dict) else None), decision


def review_payload(r: ReviewRecord, state: str, run_id: str, ts: str, *,
                   card: dict[str, Any] | None = None,
                   proposal_id: str = "") -> dict[str, Any]:
    """``gpos/v1/review/state/…`` (7.2); ``evidence`` from the evidence step on,
    ``decision`` once the planner decided."""
    body: dict[str, Any] = {
        "schema_version": "1", "type": "review", "state": state, "ts": ts,
        "review_id": r.review_id, "tx_id": r.tx_id, "store": r.store_id, "till": r.till_id,
        "membership": card if card is not None else card_of(r),
        "candidates": free_candidates(r), "run_id": run_id, "lines": r.lines}
    evidence, decision = split_decision(r.agent_decision)
    if evidence is not None:
        body["evidence"] = evidence
    if decision is not None:
        body["decision"] = decision
    if proposal_id:
        body["proposal_id"] = proposal_id
    if r.error:
        body["error"] = r.error
    return body


def proposal_payload(p: ProposalRecord, state: str, run_id: str, ts: str, zone: ZoneInfo, *,
                     action_id: str = "") -> dict[str, Any]:
    """``gpos/v1/proposal/{state}/…`` (7.2); ``approved`` adds ``action_id`` and
    ``decided_at``, every end state ``status_reason``. ``ai_model`` is the alias of the
    KI-Empfehlung (``planning``; ``""`` = legacy, the UI shows ``fast``)."""
    body: dict[str, Any] = {
        "schema_version": "1", "type": "proposal", "state": state, "ts": ts,
        "proposal_id": p.proposal_id, "review_id": p.review_id, "store": p.store_id,
        "till": p.till_id, "article_number": p.article_number,
        "article_name": p.article_name, "reason": p.reason, "reason_label": p.reason_label,
        "step_pct": p.step_pct, "clamped": p.clamped, "old_price": p.old_label,
        "new_price": p.new_label, "pct_shown": p.pct_shown,
        "pct_label": p.pct_label_unicode, "ref30": p.ref30_label,
        "margin_pct_new": p.margin_label, "base_price_label": p.base_price_label or "",
        "valid_to": p.valid_to.astimezone(zone).isoformat(),
        "valid_to_label": p.valid_to_label(zone), "headline": p.headline,
        "rationale": p.rationale, "facts_line": p.facts_line, "note": p.note,
        "text_source": p.text_source, "ai_model": p.ai_model, "run_id": run_id,
        "guardrails": p.guardrails}
    if action_id:
        body["action_id"] = action_id
    if state == "approved" and p.decided_at is not None:
        body["decided_at"] = iso_ts(p.decided_at, str(zone))
    if state in END_STATES:
        body["status_reason"] = p.status_reason or ""
    return body


class Emitter:
    """Writes our own events into ``engine.event_outbox`` (the engine relay publishes)."""

    def __init__(self, source: str, zone: ZoneInfo, clock: Callable[[], datetime]):
        self._writer = OutboxWriter("engine")
        self._source = source
        self.zone = zone
        self._clock = clock

    def ts(self) -> str:
        """Technical time with offset (``ts`` of 7.2)."""
        return iso_ts(self._clock(), str(self.zone))

    def _add(self, conn: Conn, aggregate_id: str, topic: str, event_type: str,
             payload: dict[str, Any], delivery_class: str) -> None:
        offset = self._writer.next_offset(conn, aggregate_id)
        self._writer.add(conn, aggregate_id=aggregate_id, aggregate_offset=offset,
                         event_type=event_type, topic=topic, payload_text=compact(payload),
                         delivery_class=delivery_class,
                         user_props={"eventType": event_type, "source": self._source,
                                     "apiVersion": "gpos-v1", "traceId": aggregate_id})

    def review_request(self, conn: Conn, r: ReviewRecord) -> None:
        self._add(conn, r.review_id, topics.review_request(r.store_id, r.till_id, r.review_id),
                  "review.request", review_request(r), "sam_input")

    def review_state(self, conn: Conn, r: ReviewRecord, run_id: str, *,
                     card: dict[str, Any] | None = None, proposal_id: str = "") -> None:
        """Publish the review's current status."""
        self._add(conn, r.review_id,
                  topics.review_state(r.status, r.store_id, r.till_id, r.review_id),
                  f"review.{r.status}",
                  review_payload(r, r.status, run_id, self.ts(), card=card,
                                 proposal_id=proposal_id), "ui")

    def approval_request(self, conn: Conn, p: ProposalRecord) -> None:
        self._add(conn, p.proposal_id,
                  topics.approval_request(p.store_id, p.till_id, p.proposal_id),
                  "approval.request", approval_request(p), "sam_input")

    def proposal_state(self, conn: Conn, p: ProposalRecord, run_id: str, *,
                       state: str = "", action_id: str = "") -> None:
        """Publish the proposal's status (or the signal ``duplicate_request``)."""
        state = state or p.status
        self._add(conn, p.proposal_id,
                  topics.proposal(state, p.store_id, p.till_id, p.proposal_id),
                  f"proposal.{state}",
                  proposal_payload(p, state, run_id, self.ts(), self.zone, action_id=action_id),
                  "ui")
