"""SQL of gpos-loyalty on schema ``loyalty`` (UC1-BUILD-SPEC 5.5, 5.7).

Every function takes an open connection from ``Db.tx()`` (``dict_row``), so one
service call reads a consistent snapshot in one transaction. The schema is qualified
everywhere. Time bounds are passed in as aware datetimes computed from the business
clock, never SQL ``now()`` (3.2).

Seed restore (``ResetDemoState`` day): ``ChangeConsent`` writes the seeded consent
row to ``loyalty.audit`` (action ``ConsentSeedSnapshot``) before it overwrites it for
the first time; the day reset puts the latest snapshot back. The audit table stays
append-only, and a re-seed needs no extra step.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

Conn = psycopg.Connection[dict[str, Any]]

ACTION_SNAPSHOT = "ConsentSeedSnapshot"
ACTION_CHANGE = "ChangeConsent"
ACTION_RESET = "ResetDemoState"
SOURCE_SEED = "seed"
SOURCE_OPERATOR = "operator"
VISIT_BOOTH = "booth"

# A SALE of the member before the bound that no VOID reverses.
_COUNTED_SALE = """
    p.member_id = %(member)s and p.transaction_type = 'SALE' and p.closed_at < %(before)s
    and not exists (select 1 from loyalty.purchase v
                     where v.transaction_type = 'VOID'
                       and v.referenced_purchase_transaction_id = p.purchase_transaction_id)
"""


@dataclass(frozen=True)
class ConsentRow:
    """``loyalty.consent`` of one member (all false without a row: data protection)."""

    offers: bool
    profiling: bool
    digital_receipt: bool
    policy_version: str
    changed_at: datetime | None
    source: str


NO_CONSENT = ConsentRow(False, False, False, "", None, "")


@dataclass(frozen=True)
class MemberRow:
    """``loyalty.member`` joined with its consent."""

    member_id: str
    program_id: str
    persona_label: str
    segment_label: str
    salutation: str  # FORMAL | INFORMAL
    status: str  # ACTIVE | BLOCKED
    anonymous: bool
    customer_ref: str | None
    consent: ConsentRow


@dataclass(frozen=True)
class CardRow:
    """``loyalty.card``"""

    card_value: str
    member_id: str
    status: str  # ACTIVE | BLOCKED


@dataclass(frozen=True)
class ProgramRow:
    """``loyalty.program`` (the fields the POS needs)."""

    program_id: str
    display_name: str
    currency_name: str


@dataclass(frozen=True)
class AccountRow:
    """``loyalty.account``"""

    account_id: str
    account_type: str
    balance: Decimal


@dataclass(frozen=True)
class NewLine:
    """One effectual receipt line to store (only with profiling consent)."""

    position_id: str
    article_number: str
    category: str
    item_count: int
    value: Decimal


@dataclass(frozen=True)
class NewPurchase:
    """A reported purchase (``ReportPurchase``), runtime data (``is_seed`` false)."""

    tx_id: str
    member_id: str | None
    receipt_number: str
    location: str
    transaction_type: str  # SALE | VOID
    referenced_tx_id: str | None
    closed_at: datetime
    total: Decimal


@dataclass(frozen=True)
class ConsentFlags:
    """New consent flags of ``ChangeConsent``."""

    offers: bool
    profiling: bool
    digital_receipt: bool
    policy_version: str


def _consent(row: dict[str, Any]) -> ConsentRow:
    if row["source"] is None:
        return NO_CONSENT
    return ConsentRow(row["offers"], row["profiling"], row["digital_receipt"],
                      row["policy_version"], row["changed_at"], row["source"])


def find_member(conn: Conn, member_id: str) -> MemberRow | None:
    """The member with its consent, or ``None``."""
    row = conn.execute(
        """select m.member_id, m.program_id, m.persona_label,
                  coalesce(m.segment_label, '') as segment_label, m.salutation, m.status,
                  m.anonymous, m.customer_ref, c.offers, c.profiling, c.digital_receipt,
                  c.policy_version, c.changed_at, c.source
             from loyalty.member m
             left join loyalty.consent c on c.member_id = m.member_id
            where m.member_id = %s""", (member_id,)).fetchone()
    if row is None:
        return None
    return MemberRow(row["member_id"], row["program_id"], row["persona_label"],
                     row["segment_label"], row["salutation"], row["status"], row["anonymous"],
                     row["customer_ref"], _consent(row))


def find_card(conn: Conn, card_value: str) -> CardRow | None:
    """The card with this identification value, or ``None``."""
    row = conn.execute(
        "select card_value, member_id, status from loyalty.card where card_value = %s",
        (card_value,)).fetchone()
    return None if row is None else CardRow(row["card_value"], row["member_id"], row["status"])


def find_program(conn: Conn, program_id: str) -> ProgramRow:
    """The loyalty program (``member.program_id`` is a foreign key, so it exists)."""
    row = conn.execute(
        "select program_id, display_name, currency_name from loyalty.program "
        "where program_id = %s", (program_id,)).fetchone()
    if row is None:
        raise LookupError(f"loyalty program {program_id} missing")
    return ProgramRow(row["program_id"], row["display_name"], row["currency_name"])


def accounts(conn: Conn, member_id: str) -> list[AccountRow]:
    """Accounts of the member, by id."""
    rows = conn.execute(
        "select account_id, account_type, balance from loyalty.account "
        "where member_id = %s order by account_id", (member_id,)).fetchall()
    return [AccountRow(r["account_id"], r["account_type"], r["balance"]) for r in rows]


def tags(conn: Conn, member_id: str) -> list[str]:
    """Preference tags of the member (allowlist only), strongest first, then by name."""
    rows = conn.execute(
        "select tag from loyalty.member_tag where member_id = %s order by weight desc, tag",
        (member_id,)).fetchall()
    return [r["tag"] for r in rows]


def points_balance(conn: Conn, member_id: str) -> Decimal:
    """Sum of the account balances of the member."""
    row = conn.execute(
        "select coalesce(sum(balance), 0) as balance from loyalty.account where member_id = %s",
        (member_id,)).fetchone()
    return Decimal(row["balance"]) if row else Decimal(0)


def open_coupons(conn: Conn, member_id: str) -> int:
    """Number of issued, not yet redeemed coupons of the member."""
    row = conn.execute(
        "select count(*)::int as n from loyalty.coupon "
        "where member_id = %s and status = 'ISSUED'", (member_id,)).fetchone()
    return int(row["n"]) if row else 0


def article_categories(conn: Conn, article_numbers: Sequence[str]) -> dict[str, str]:
    """``article_number -> category`` for the known articles among ``article_numbers``."""
    rows = conn.execute(
        "select article_number, category from loyalty.article_ref "
        "where article_number = any(%s)", (list(article_numbers),)).fetchall()
    return {r["article_number"]: r["category"] for r in rows}


def article_purchases(conn: Conn, member_id: str, article_number: str, before: datetime
                      ) -> list[tuple[str, datetime]]:
    """``(tx_id, closed_at)`` of every counted SALE of the member with the article before
    ``before`` (positive item count)."""
    rows = conn.execute(
        f"""select p.purchase_transaction_id::text as tx_id, p.closed_at
              from loyalty.purchase p
             where {_COUNTED_SALE}
               and exists (select 1 from loyalty.purchase_line l
                            where l.purchase_transaction_id = p.purchase_transaction_id
                              and l.article_number = %(article)s and l.item_count > 0)
             order by p.closed_at""",
        {"member": member_id, "article": article_number, "before": before}).fetchall()
    return [(r["tx_id"], r["closed_at"]) for r in rows]


def category_purchases(conn: Conn, member_id: str, since: datetime, before: datetime
                       ) -> list[tuple[str, datetime, str]]:
    """``(tx_id, closed_at, category)`` of counted SALEs in ``[since, before)``."""
    rows = conn.execute(
        f"""select distinct p.purchase_transaction_id::text as tx_id, p.closed_at, l.category
              from loyalty.purchase p
              join loyalty.purchase_line l
                on l.purchase_transaction_id = p.purchase_transaction_id and l.item_count > 0
             where {_COUNTED_SALE} and p.closed_at >= %(since)s
             order by p.closed_at, l.category""",
        {"member": member_id, "since": since, "before": before}).fetchall()
    return [(r["tx_id"], r["closed_at"], r["category"]) for r in rows]


def cardholder_weeks(conn: Conn, article_number: str, starts: Sequence[date]
                     ) -> dict[date, int]:
    """``week_start -> member_purchases`` of ``loyalty.article_week_stats``."""
    rows = conn.execute(
        "select week_start, member_purchases from loyalty.article_week_stats "
        "where article_number = %s and week_start = any(%s)",
        (article_number, list(starts))).fetchall()
    return {r["week_start"]: int(r["member_purchases"]) for r in rows}


def insert_purchase(conn: Conn, purchase: NewPurchase) -> bool:
    """Insert the purchase header; ``False`` when it was reported before (idempotent)."""
    row = conn.execute(
        """insert into loyalty.purchase
             (purchase_transaction_id, member_id, receipt_number, location, transaction_type,
              referenced_purchase_transaction_id, closed_at, total_eur, points_earned,
              visit_id, is_seed)
           values (%s, %s, %s, %s, %s, %s, %s, %s, 0, %s, false)
           on conflict (purchase_transaction_id) do nothing
           returning purchase_transaction_id""",
        (purchase.tx_id, purchase.member_id, purchase.receipt_number, purchase.location,
         purchase.transaction_type, purchase.referenced_tx_id, purchase.closed_at,
         purchase.total, VISIT_BOOTH)).fetchone()
    return row is not None


def insert_lines(conn: Conn, tx_id: str, lines: Sequence[NewLine]) -> None:
    """Insert the receipt lines of a purchase (a repeated position is kept once)."""
    with conn.cursor() as cur:
        cur.executemany(
            """insert into loyalty.purchase_line
                 (purchase_transaction_id, position_id, article_number, category, item_count,
                  effective_value_eur)
               values (%s, %s, %s, %s, %s, %s)
               on conflict (purchase_transaction_id, position_id) do nothing""",
            [(tx_id, ln.position_id, ln.article_number, ln.category, ln.item_count, ln.value)
             for ln in lines])


def write_audit(conn: Conn, actor: str, action: str, ref: str, payload: dict[str, Any]
                ) -> None:
    """Append one row to ``loyalty.audit``."""
    conn.execute("insert into loyalty.audit (actor, action, ref, payload) "
                 "values (%s, %s, %s, %s)", (actor, action, ref, Jsonb(payload)))


def lock_consent(conn: Conn, member_id: str) -> ConsentRow | None:
    """The consent row of the member, locked for update (``None`` without a row)."""
    row = conn.execute(
        "select offers, profiling, digital_receipt, policy_version, changed_at, source "
        "from loyalty.consent where member_id = %s for update", (member_id,)).fetchone()
    return None if row is None else _consent(row)


def snapshot_payload(consent: ConsentRow) -> dict[str, Any]:
    """The audit payload that restores ``consent`` (``ConsentSeedSnapshot``)."""
    return {"offers": consent.offers, "profiling": consent.profiling,
            "digital_receipt": consent.digital_receipt,
            "policy_version": consent.policy_version,
            "changed_at": consent.changed_at.isoformat() if consent.changed_at else None}


def upsert_consent(conn: Conn, member_id: str, flags: ConsentFlags, changed_at: datetime
                   ) -> ConsentRow:
    """Set the consent of the member (source ``operator``) and return the stored row; an
    empty policy version keeps the stored one."""
    row = conn.execute(
        """insert into loyalty.consent
             (member_id, offers, profiling, digital_receipt, policy_version, changed_at, source)
           values (%(member)s, %(offers)s, %(profiling)s, %(receipt)s, %(policy)s, %(at)s,
                   %(source)s)
           on conflict (member_id) do update set
             offers = excluded.offers, profiling = excluded.profiling,
             digital_receipt = excluded.digital_receipt,
             policy_version = coalesce(nullif(%(policy)s, ''), loyalty.consent.policy_version),
             changed_at = excluded.changed_at, source = excluded.source
           returning offers, profiling, digital_receipt, policy_version, changed_at, source""",
        {"member": member_id, "offers": flags.offers, "profiling": flags.profiling,
         "receipt": flags.digital_receipt, "policy": flags.policy_version, "at": changed_at,
         "source": SOURCE_OPERATOR}).fetchone()
    if row is None:
        raise LookupError(f"consent of {member_id} not written")
    return _consent(row)


def delete_runtime_purchases(conn: Conn) -> int:
    """Delete every purchase with ``is_seed`` false (lines cascade); returns the count."""
    cur = conn.execute("delete from loyalty.purchase where not is_seed")
    return max(cur.rowcount, 0)


def restore_seed_consents(conn: Conn) -> list[str]:
    """Put the latest seed snapshot back for every member whose consent is not seeded."""
    rows = conn.execute(
        f"""with snap as (
              select distinct on (ref) ref as member_id, payload
                from loyalty.audit
               where action = '{ACTION_SNAPSHOT}'
               order by ref, id desc)
            update loyalty.consent c
               set offers = (s.payload->>'offers')::boolean,
                   profiling = (s.payload->>'profiling')::boolean,
                   digital_receipt = (s.payload->>'digital_receipt')::boolean,
                   policy_version = s.payload->>'policy_version',
                   changed_at = coalesce((s.payload->>'changed_at')::timestamptz,
                                         c.changed_at),
                   source = '{SOURCE_SEED}'
              from snap s
             where c.member_id = s.member_id and c.source <> '{SOURCE_SEED}'
            returning c.member_id""").fetchall()
    return sorted(r["member_id"] for r in rows)
