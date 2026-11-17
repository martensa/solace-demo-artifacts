"""Typed rows of ``engine.review`` and ``engine.proposal`` (UC1-BUILD-SPEC 5.6)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from ..common.fmt import dt_label, eur, pct_label
from .texts import REASON_LABELS

REVIEW_OPEN = ("requested", "prepared")
PROPOSAL_OPEN = ("ready", "pending")

REVIEW_COLUMNS = ("review_id, tx_id::text as tx_id, store_id, till_id, membership_id, status, "
                  "lines, agent_input, agent_decision, run_id_raise, run_id_review, error, "
                  "created_at, prepared_at, decided_at")
PROPOSAL_COLUMNS = ("proposal_id, review_id, tx_id::text as tx_id, store_id, till_id, "
                    "article_number, article_name, reason, step_requested, step_pct, clamped, "
                    "regular_price, new_price, ref30, pct_shown, margin_pct_new, "
                    "base_price_label, valid_from, valid_to, headline, rationale, facts_line, "
                    "note, text_source, guardrails, proposal_hash, status, status_reason, "
                    "run_id_stage, run_id_approval, created_at, pending_at, decided_at, "
                    # 7.2 ai_model: model alias of the KI-Empfehlung ("" = legacy, read fast);
                    # implicit alias "proposal" works in select … from and update … returning
                    "coalesce((select r.agent_decision->>'model' from engine.review r "
                    "where r.review_id = proposal.review_id), '') as ai_model")


@dataclass(frozen=True)
class ReviewRecord:
    review_id: str
    tx_id: str
    store_id: str
    till_id: str
    membership_id: str | None
    status: str
    lines: list[dict[str, Any]]
    agent_input: str | None
    agent_decision: dict[str, Any] | None
    run_id_raise: str | None
    run_id_review: str | None
    error: str | None
    created_at: datetime
    prepared_at: datetime | None
    decided_at: datetime | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ReviewRecord:
        return cls(**{k: row[k] for k in cls.__dataclass_fields__})

    @property
    def is_open(self) -> bool:
        return self.status in REVIEW_OPEN


@dataclass(frozen=True)
class ProposalRecord:
    proposal_id: str
    review_id: str
    tx_id: str
    store_id: str
    till_id: str
    article_number: str
    article_name: str
    reason: str
    step_requested: int
    step_pct: int
    clamped: bool
    regular_price: Decimal
    new_price: Decimal
    ref30: Decimal
    pct_shown: int
    margin_pct_new: Decimal
    base_price_label: str | None
    valid_from: datetime
    valid_to: datetime
    headline: str
    rationale: str
    facts_line: str
    note: str
    text_source: str
    guardrails: list[dict[str, Any]]
    proposal_hash: str
    status: str
    status_reason: str | None
    run_id_stage: str | None
    run_id_approval: str | None
    created_at: datetime
    pending_at: datetime | None
    decided_at: datetime | None
    ai_model: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ProposalRecord:
        return cls(**{k: row[k] for k in cls.__dataclass_fields__})

    @property
    def is_open(self) -> bool:
        return self.status in PROPOSAL_OPEN

    @property
    def old_label(self) -> str:
        return eur(self.regular_price)

    @property
    def new_label(self) -> str:
        return eur(self.new_price)

    @property
    def ref30_label(self) -> str:
        return eur(self.ref30)

    @property
    def pct_label_ascii(self) -> str:
        """``"-20 %"``: what the approver copies into ``apply_price`` (9.4)."""
        return pct_label(self.pct_shown, ascii_minus=True)

    @property
    def pct_label_unicode(self) -> str:
        """``"−20 %"`` for monitor and notifications."""
        return pct_label(self.pct_shown)

    @property
    def reason_label(self) -> str:
        return REASON_LABELS[self.reason]

    @property
    def margin_label(self) -> str:
        """``"22,6"``"""
        return f"{self.margin_pct_new:.1f}".replace(".", ",")

    @property
    def ending_label(self) -> str:
        """Cent ending of the new price: ``",99"``."""
        return f",{int(self.new_price * 100) % 100:02d}"

    def valid_to_label(self, zone: ZoneInfo) -> str:
        """``"Di 23.02. 20:00"`` (business time in ``GPOS_TZ``)."""
        return dt_label(self.valid_to.astimezone(zone))
