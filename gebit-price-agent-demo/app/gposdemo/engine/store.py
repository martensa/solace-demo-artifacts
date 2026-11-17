"""SQL of engine and gate: the basket in ``pos`` (read only) and the ``engine`` tables.

Every function takes the caller's connection, so reads and writes share one
transaction; ``lock=True`` adds ``for update`` (row lock until commit).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from ..common.ids import make_id
from .records import PROPOSAL_COLUMNS, REVIEW_COLUMNS, ProposalRecord, ReviewRecord

Conn = psycopg.Connection[Any]


def is_uuid(text: str) -> bool:
    """True for a canonical UUID (``pos.basket.tx_id``)."""
    try:
        return str(uuid.UUID(text)) == text.lower()
    except (ValueError, AttributeError, TypeError):
        return False


def _lock(lock: bool) -> str:
    return " for update" if lock else ""


# ------------------------------------------------------------------ pos (read only)
def basket(conn: Conn, tx_id: str) -> dict[str, Any] | None:
    """``pos.basket`` row: ``tx_id``, ``till_id``, ``store_id``, ``status``, ``membership_id``."""
    if not is_uuid(tx_id):
        return None
    return conn.execute(
        "select tx_id::text as tx_id, till_id, store_id, status, membership_id "
        "from pos.basket where tx_id = %s", (tx_id,)).fetchone()


def basket_lines(conn: Conn, tx_id: str) -> list[dict[str, Any]]:
    """Not voided lines of a basket in scan order."""
    return conn.execute(
        "select position_id::text as position_id, line_no, article_number, name, "
        "unit_price, price_source from pos.basket_line "
        "where tx_id = %s and not voided order by line_no", (tx_id,)).fetchall()


def basket_line(conn: Conn, tx_id: str, position_id: str) -> dict[str, Any] | None:
    """One line by position id (voided lines included)."""
    if not is_uuid(position_id):
        return None
    return conn.execute(
        "select position_id::text as position_id, article_number, name, unit_price, "
        "price_source, voided from pos.basket_line where tx_id = %s and position_id = %s",
        (tx_id, position_id)).fetchone()


# ------------------------------------------------------------------ ids
def next_id(conn: Conn, kind: str, business_date: date) -> str:
    """``GR-YYMMDD-NNNN`` (``kind="review"``) or ``GP-…`` (``kind="proposal"``)."""
    sequence, prefix = {"review": ("engine.review_seq", "GR"),
                        "proposal": ("engine.proposal_seq", "GP")}[kind]
    row = conn.execute("select nextval(%s) as seq", (sequence,)).fetchone()
    assert row is not None
    return make_id(prefix, business_date, int(row["seq"]))


# ------------------------------------------------------------------ reviews
def review(conn: Conn, review_id: str, *, lock: bool = False) -> ReviewRecord | None:
    row = conn.execute(f"select {REVIEW_COLUMNS} from engine.review where review_id = %s"
                       f"{_lock(lock)}", (review_id,)).fetchone()
    return ReviewRecord.from_row(row) if row else None


def review_of_tx(conn: Conn, tx_id: str, *, lock: bool = False) -> ReviewRecord | None:
    row = conn.execute(f"select {REVIEW_COLUMNS} from engine.review where tx_id = %s"
                       f"{_lock(lock)}", (tx_id,)).fetchone()
    return ReviewRecord.from_row(row) if row else None


def latest_review(conn: Conn, store_id: str, till_id: str) -> ReviewRecord | None:
    row = conn.execute(
        f"select {REVIEW_COLUMNS} from engine.review where store_id = %s and till_id = %s "
        "order by created_at desc, review_id desc limit 1", (store_id, till_id)).fetchone()
    return ReviewRecord.from_row(row) if row else None


def set_review(conn: Conn, review_id: str, **columns: Any) -> ReviewRecord:
    """Update columns of one review and return the new row."""
    assignments = ", ".join(f"{name} = %s" for name in columns)
    values = [Jsonb(v) if name in ("lines", "agent_decision") else v
              for name, v in columns.items()]
    row = conn.execute(f"update engine.review set {assignments} where review_id = %s "
                       f"returning {REVIEW_COLUMNS}", (*values, review_id)).fetchone()
    if row is None:
        raise LookupError(f"review {review_id} vanished")
    return ReviewRecord.from_row(row)


# ------------------------------------------------------------------ proposals
def proposal(conn: Conn, proposal_id: str, *, lock: bool = False) -> ProposalRecord | None:
    row = conn.execute(f"select {PROPOSAL_COLUMNS} from engine.proposal where proposal_id = %s"
                       f"{_lock(lock)}", (proposal_id,)).fetchone()
    return ProposalRecord.from_row(row) if row else None


def open_proposal(conn: Conn, store_id: str, till_id: str, *,
                  lock: bool = False) -> ProposalRecord | None:
    row = conn.execute(
        f"select {PROPOSAL_COLUMNS} from engine.proposal where store_id = %s and till_id = %s "
        f"and status in ('ready', 'pending'){_lock(lock)}", (store_id, till_id)).fetchone()
    return ProposalRecord.from_row(row) if row else None


def latest_proposal(conn: Conn, store_id: str, till_id: str) -> ProposalRecord | None:
    row = conn.execute(
        f"select {PROPOSAL_COLUMNS} from engine.proposal where store_id = %s and till_id = %s "
        "order by created_at desc, proposal_id desc limit 1", (store_id, till_id)).fetchone()
    return ProposalRecord.from_row(row) if row else None


def set_proposal(conn: Conn, proposal_id: str, **columns: Any) -> ProposalRecord:
    """Update columns of one proposal and return the new row."""
    assignments = ", ".join(f"{name} = %s" for name in columns)
    row = conn.execute(f"update engine.proposal set {assignments} where proposal_id = %s "
                       f"returning {PROPOSAL_COLUMNS}", (*columns.values(), proposal_id)
                       ).fetchone()
    if row is None:
        raise LookupError(f"proposal {proposal_id} vanished")
    return ProposalRecord.from_row(row)


# ------------------------------------------------------------------ approvals
APPROVAL_COLUMNS = ("proposal_id, run_id, checked_at, apply_calls, first_apply_at, "
                    "last_apply_status, agent_status, outcome, error, sam_error_at, decided_at")


def approval(conn: Conn, proposal_id: str, *, lock: bool = False) -> dict[str, Any] | None:
    return conn.execute(f"select {APPROVAL_COLUMNS} from engine.approval "
                        f"where proposal_id = %s{_lock(lock)}", (proposal_id,)).fetchone()


def set_approval(conn: Conn, proposal_id: str, **columns: Any) -> None:
    assignments = ", ".join(f"{name} = %s" for name in columns)
    conn.execute(f"update engine.approval set {assignments} where proposal_id = %s",
                 (*columns.values(), proposal_id))


def price_change(conn: Conn, proposal_id: str) -> dict[str, Any] | None:
    return conn.execute("select action_id, new_price, applied_at from engine.price_change "
                        "where proposal_id = %s", (proposal_id,)).fetchone()


def audit(conn: Conn, kind: str, ref: str, payload: dict[str, Any], ts: datetime) -> None:
    conn.execute("insert into engine.audit_event (ts, kind, ref, payload) values (%s, %s, %s, %s)",
                 (ts, kind, ref, Jsonb(payload)))


def latest_audit(conn: Conn, kind: str, ref: str) -> dict[str, Any] | None:
    """Payload of the newest audit row of ``kind`` for ``ref`` (read models only)."""
    row = conn.execute("select payload from engine.audit_event where kind = %s and ref = %s "
                       "order by id desc limit 1", (kind, ref)).fetchone()
    return dict(row["payload"]) if row else None
