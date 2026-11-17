"""Domain service of gpos-loyalty (UC1-BUILD-SPEC 2.4, 4.4, 6.4-6.6, 8.4, 11.7).

``LoyaltyService`` has one pure method per use: the gRPC layer (``server.py``) and the
MCP layer (``tools.py``) are thin wrappers. Results are Pydantic models; the two agent
tools return the dict that becomes their compact JSON text content (2.4).

Data protection (guardrails C04, C05): no name, age, sex, address, card value or
customer reference ever leaves through an agent tool; purchase history is read only
with ``consent.profiling``, and receipt lines are stored only with it.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from gposdemo.common.clock import demo_at, demo_now, demo_today
from gposdemo.common.config import Settings
from gposdemo.common.db import Db

from . import behaviour, store
from .behaviour import CategoryFrequency, MemberStats, Purchase

log = logging.getLogger(__name__)

LOY_UNKNOWN_MEMBER = "LOY-002"
TOP_CATEGORIES = 3
DEFAULT_ACTOR = "operator"
SALUTATION_LABELS = {"FORMAL": "Sie", "INFORMAL": "du"}
TRANSACTION_TYPES = ("SALE", "VOID")

MembershipStatus = Literal["ACTIVE", "BLOCKED", "UNKNOWN"]
ResetScope = Literal["booth", "day"]


class LoyaltyError(Exception):
    """A request the service refuses. ``code`` is the 4.5 error code (``""`` when the
    request itself is malformed)."""

    code = ""

    def __init__(self, text: str):
        super().__init__(text)
        self.text = text


class UnknownMember(LoyaltyError):
    """``LOY-002``: no member with this id (gRPC ``NOT_FOUND``)."""

    code = LOY_UNKNOWN_MEMBER


class InvalidRequest(LoyaltyError):
    """Missing or malformed field (gRPC ``INVALID_ARGUMENT``, no 4.5 code)."""


# --------------------------------------------------------------------------- models
class Consent(BaseModel):
    """Consent flags of one membership (``datatype.ConsentFlags``)."""

    offers: bool
    profiling: bool
    digital_receipt: bool
    policy_version: str
    changed_at: datetime | None = None


class Account(BaseModel):
    """Points account (``datatype.LoyaltyAccount``)."""

    account_id: str
    account_type: str
    currency_name: str
    balance: Decimal


class Resolution(BaseModel):
    """Answer to ``ResolveMembership`` (``datatype.MembershipResolution``).

    The POS puts the member on the basket only for status ``ACTIVE``; anything else
    becomes ``LOY-001`` at the POS (4.4).
    """

    card_value: str
    status: MembershipStatus
    verified: bool
    membership_id: str = ""
    program_id: str = ""
    program_name: str = ""
    customer_id: str | None = None
    anonymous: bool = False
    digital_receipt: bool = False
    accounts: list[Account] = []


class MemberProfile(BaseModel):
    """Profile of one fictional card (``datatype.MemberProfile``), no personal attributes."""

    membership_id: str
    persona_label: str
    segment_label: str
    salutation: str  # FORMAL | INFORMAL
    tags: list[str]
    consent: Consent
    points_balance: Decimal
    history: list[CategoryFrequency]  # empty without profiling consent
    open_coupons: int
    history_used: bool


class PurchaseBehaviour(BaseModel):
    """``datatype.PurchaseBehaviour``: member fields are 0 / -1 without profiling consent."""

    membership_id: str
    article_number: str
    consent_profiling: bool
    persona_label: str
    segment_label: str
    member_purchases_8w: int
    member_purchases_12w: int
    days_since_last: int
    median_interval_days: int
    cardholder_weekly: list[int]
    cardholder_drop_pct: Decimal

    @property
    def overdue_factor(self) -> Decimal | None:
        """``days_since_last / median_interval_days`` (two decimals, cut), or ``None``."""
        return behaviour.overdue_factor(self.days_since_last, self.median_interval_days)


class ReportLine(BaseModel):
    """One receipt line of a reported purchase (``datatype.BasketLine``)."""

    position_id: str
    article_number: str
    category: str = ""
    item_count: int
    value: Decimal
    effectual: bool = True


class PurchaseReport(BaseModel):
    """A closed purchase reported by the POS (``datatype.PurchaseSummary``)."""

    purchase_transaction_id: str
    receipt_number: str = ""
    location: str = ""
    transaction_type: str = "SALE"
    closed_at: datetime | None = None  # business time; None = now in business time
    membership_id: str = ""
    lines: list[ReportLine] = []
    total: Decimal = Decimal("0.00")
    referenced_purchase_transaction_id: str = ""


class ReportResult(BaseModel):
    """Outcome of ``ReportPurchase``."""

    stored: bool  # false: reported before (idempotent)
    lines: int = 0


class ConsentChange(BaseModel):
    """New flags of ``ChangeConsent``; an empty policy version keeps the stored one."""

    offers: bool
    profiling: bool
    digital_receipt: bool = False
    policy_version: str = ""


class ResetResult(BaseModel):
    """Outcome of ``ResetDemoState`` (11.7 step 4)."""

    scope: ResetScope
    purchases_deleted: int
    consents_restored: list[str]


# --------------------------------------------------------------------------- views
def _number(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def behaviour_view(b: PurchaseBehaviour) -> dict[str, Any]:
    """Text content of ``get_purchase_behaviour`` (8.4): without profiling consent the
    member fields are ``null``; ``null`` also stands for "never bought" and "unknown
    interval". The anonymous cardholder trend is always there."""
    member: dict[str, Any] = dict.fromkeys(
        ("member_purchases_8w", "member_purchases_12w", "days_since_last",
         "median_interval_days", "overdue_factor"))
    if b.consent_profiling:
        member = {
            "member_purchases_8w": b.member_purchases_8w,
            "member_purchases_12w": b.member_purchases_12w,
            "days_since_last": b.days_since_last if b.days_since_last >= 0 else None,
            "median_interval_days": b.median_interval_days or None,
            "overdue_factor": _number(b.overdue_factor),
        }
    return {"membership_id": b.membership_id, "article_number": b.article_number,
            "consent_profiling": b.consent_profiling, **member,
            "cardholder_weekly": list(b.cardholder_weekly),
            "cardholder_drop_pct": float(b.cardholder_drop_pct)}


def profile_view(p: MemberProfile) -> dict[str, Any]:
    """Text content of ``get_member_profile`` (8.4): persona, segment, form of address,
    consent, tags and (only with profiling consent) the top categories of 8 weeks."""
    top = None
    if p.consent.profiling:
        top = [{"category": c.category, "purchases": c.purchases_8w,
                "days_since_last": c.days_since_last} for c in p.history[:TOP_CATEGORIES]]
    return {"membership_id": p.membership_id, "persona": p.persona_label,
            "segment": p.segment_label,
            "salutation": SALUTATION_LABELS.get(p.salutation, p.salutation),
            "consent": {"offers": p.consent.offers, "profiling": p.consent.profiling},
            "tags": list(p.tags), "top_categories_8w": top}


# --------------------------------------------------------------------------- helpers
def _required(value: str, field: str) -> str:
    text = value.strip()
    if not text:
        raise InvalidRequest(f"{field} fehlt")
    return text


def _uuid(value: str, field: str) -> str:
    try:
        return str(uuid.UUID(_required(value, field)))
    except ValueError as exc:
        raise InvalidRequest(f"{field} ist keine UUID: {value!r}") from exc


def _consent(row: store.ConsentRow, zone: ZoneInfo) -> Consent:
    """Consent with ``changed_at`` in ``GPOS_TZ`` (the DB session may answer in UTC)."""
    changed_at = row.changed_at.astimezone(zone) if row.changed_at else None
    return Consent(offers=row.offers, profiling=row.profiling,
                   digital_receipt=row.digital_receipt, policy_version=row.policy_version,
                   changed_at=changed_at)


class LoyaltyService:
    """Members, consent, profile, purchase behaviour and purchases of the showcase store."""

    def __init__(self, db: Db, settings: Settings):
        self.db = db
        self.settings = settings

    # ----------------------------------------------------------------- clock
    def _today(self) -> date:
        return demo_today(self.settings)

    def _midnight(self, day: date) -> datetime:
        return demo_at(self.settings, day)

    def _purchases(self, rows: Sequence[tuple[str, datetime]]) -> list[Purchase]:
        zone = self.settings.zone
        return [Purchase(tx_id, behaviour.business_day(at, zone)) for tx_id, at in rows]

    # ----------------------------------------------------------------- POS side
    def resolve_membership(self, card_value: str) -> Resolution:
        """Card value -> membership (4.4). Unknown or empty value: status ``UNKNOWN``."""
        value = card_value.strip()
        with self.db.tx() as conn:
            card = store.find_card(conn, value) if value else None
            member = store.find_member(conn, card.member_id) if card else None
            if card is None or member is None:
                return Resolution(card_value=value, status="UNKNOWN", verified=False)
            program = store.find_program(conn, member.program_id)
            accounts = [Account(account_id=a.account_id, account_type=a.account_type,
                                currency_name=program.currency_name, balance=a.balance)
                        for a in store.accounts(conn, member.member_id)]
        active = card.status == "ACTIVE" and member.status == "ACTIVE"
        return Resolution(
            card_value=value, status="ACTIVE" if active else "BLOCKED", verified=True,
            membership_id=member.member_id, program_id=program.program_id,
            program_name=program.display_name, customer_id=member.customer_ref,
            anonymous=member.anonymous, digital_receipt=member.consent.digital_receipt,
            accounts=accounts)

    def report_purchase(self, report: PurchaseReport) -> ReportResult:
        """Store a closed purchase (idempotent per transaction id).

        ``closed_at`` is business time (3.2); lines are stored only for a member with
        profiling consent, only effectual ones, and only for known articles.
        """
        tx_id = _uuid(report.purchase_transaction_id, "purchase_transaction_id")
        if report.transaction_type not in TRANSACTION_TYPES:
            raise InvalidRequest(f"transaction_type muss SALE oder VOID sein, nicht "
                                 f"{report.transaction_type!r}")
        referenced = None
        if report.transaction_type == "VOID":
            referenced = _uuid(report.referenced_purchase_transaction_id,
                               "referenced_purchase_transaction_id")
        member_id = report.membership_id.strip() or None
        closed_at = report.closed_at or demo_now(self.settings)
        with self.db.tx() as conn:
            member = store.find_member(conn, member_id) if member_id else None
            if member_id and member is None:
                raise UnknownMember(f"Mitglied {member_id} unbekannt")
            header = store.NewPurchase(tx_id, member_id, report.receipt_number,
                                       report.location, report.transaction_type, referenced,
                                       closed_at, report.total)
            if not store.insert_purchase(conn, header):
                return ReportResult(stored=False)
            lines: list[store.NewLine] = []
            if member is not None and member.consent.profiling:
                lines = self._lines(conn, tx_id, report.lines)
                store.insert_lines(conn, tx_id, lines)
        return ReportResult(stored=True, lines=len(lines))

    def _lines(self, conn: store.Conn, tx_id: str, lines: Sequence[ReportLine]
               ) -> list[store.NewLine]:
        effectual = [ln for ln in lines if ln.effectual and ln.item_count != 0]
        known = store.article_categories(conn, sorted({ln.article_number for ln in effectual}))
        out: list[store.NewLine] = []
        for ln in effectual:
            category = known.get(ln.article_number)
            if category is None:
                log.warning("purchase %s: article %s unknown to loyalty, line skipped", tx_id,
                            ln.article_number)
                continue
            out.append(store.NewLine(ln.position_id, ln.article_number,
                                     ln.category or category, ln.item_count, ln.value))
        return out

    # ----------------------------------------------------------------- engine / agent side
    def member_profile(self, membership_id: str) -> MemberProfile:
        """Profile of one card; history of 8 weeks only with profiling consent."""
        member_id = _required(membership_id, "membership_id")
        today = self._today()
        zone = self.settings.zone
        with self.db.tx() as conn:
            member = store.find_member(conn, member_id)
            if member is None:
                raise UnknownMember(f"Mitglied {member_id} unbekannt")
            history: list[CategoryFrequency] = []
            if member.consent.profiling:
                rows = store.category_purchases(
                    conn, member_id, self._midnight(behaviour.window_8w(today)[0]),
                    self._midnight(today))
                history = behaviour.category_frequencies(
                    ((Purchase(tx, behaviour.business_day(at, zone)), cat)
                     for tx, at, cat in rows), today)
            return MemberProfile(
                membership_id=member.member_id, persona_label=member.persona_label,
                segment_label=member.segment_label, salutation=member.salutation,
                tags=store.tags(conn, member_id), consent=_consent(member.consent, zone),
                points_balance=store.points_balance(conn, member_id), history=history,
                open_coupons=store.open_coupons(conn, member_id),
                history_used=member.consent.profiling)

    def purchase_behaviour(self, membership_id: str, article_number: str) -> PurchaseBehaviour:
        """Behaviour of one member for one article plus the anonymous cardholder trend (4.4)."""
        member_id = _required(membership_id, "membership_id")
        article = _required(article_number, "article_number")
        today = self._today()
        starts = behaviour.week_starts(today)
        with self.db.tx() as conn:
            member = store.find_member(conn, member_id)
            if member is None:
                raise UnknownMember(f"Mitglied {member_id} unbekannt")
            if not store.article_categories(conn, [article]):
                raise InvalidRequest(f"Artikel {article} unbekannt")
            stats: MemberStats = behaviour.NO_PURCHASES
            if member.consent.profiling:
                rows = store.article_purchases(conn, member_id, article, self._midnight(today))
                stats = behaviour.member_stats(self._purchases(rows), today)
            weekly = behaviour.weekly_series(store.cardholder_weeks(conn, article, starts), today)
        return PurchaseBehaviour(
            membership_id=member.member_id, article_number=article,
            consent_profiling=member.consent.profiling, persona_label=member.persona_label,
            segment_label=member.segment_label, member_purchases_8w=stats.purchases_8w,
            member_purchases_12w=stats.purchases_12w, days_since_last=stats.days_since_last,
            median_interval_days=stats.median_interval_days, cardholder_weekly=weekly,
            cardholder_drop_pct=behaviour.drop_pct(weekly))

    # ----------------------------------------------------------------- operator side
    def change_consent(self, membership_id: str, change: ConsentChange,
                       actor: str = DEFAULT_ACTOR) -> Consent:
        """Set new consent flags (``ChangeConsent``); the seeded row is snapshotted first,
        so a day reset can restore it."""
        member_id = _required(membership_id, "membership_id")
        flags = store.ConsentFlags(change.offers, change.profiling, change.digital_receipt,
                                   change.policy_version.strip())
        changed_at = demo_now(self.settings)
        with self.db.tx() as conn:
            if store.find_member(conn, member_id) is None:
                raise UnknownMember(f"Mitglied {member_id} unbekannt")
            current = store.lock_consent(conn, member_id)
            if current is not None and current.source == store.SOURCE_SEED:
                store.write_audit(conn, actor, store.ACTION_SNAPSHOT, member_id,
                                  store.snapshot_payload(current))
            updated = store.upsert_consent(conn, member_id, flags, changed_at)
            store.write_audit(conn, actor, store.ACTION_CHANGE, member_id,
                              change.model_dump(mode="json"))
        return _consent(updated, self.settings.zone)

    def reset_demo_state(self, visit_id: str, full_day_reset: bool,
                         actor: str = DEFAULT_ACTOR) -> ResetResult:
        """11.7 step 4: ``booth`` deletes every purchase with ``is_seed`` false; ``day``
        (``full_day_reset``) also restores the seeded consents. ``visit_id`` is always
        ``"booth"`` in UC1 (empty is read as ``"booth"``)."""
        if visit_id.strip() not in ("", store.VISIT_BOOTH):
            raise InvalidRequest(f"visit_id muss \"{store.VISIT_BOOTH}\" sein, nicht "
                                 f"{visit_id!r}")
        scope: ResetScope = "day" if full_day_reset else "booth"
        with self.db.tx() as conn:
            deleted = store.delete_runtime_purchases(conn)
            restored = store.restore_seed_consents(conn) if full_day_reset else []
            result = ResetResult(scope=scope, purchases_deleted=deleted,
                                 consents_restored=restored)
            store.write_audit(conn, actor, store.ACTION_RESET, scope,
                              result.model_dump(mode="json"))
        log.info("reset %s: %d purchases deleted, consents restored %s", scope, deleted,
                 restored)
        return result

    # ----------------------------------------------------------------- agent tools (8.4)
    def get_member_profile(self, membership_id: str, ref: str = "") -> dict[str, Any]:
        """Tool ``get_member_profile``: the compact-JSON dict of :func:`profile_view`.

        ``ref`` (the review id) only feeds telemetry in the MCP layer.
        """
        log.debug("get_member_profile %s ref=%s", membership_id, ref)
        return profile_view(self.member_profile(membership_id))

    def get_purchase_behaviour(self, membership_id: str, article_number: str, ref: str = ""
                               ) -> dict[str, Any]:
        """Tool ``get_purchase_behaviour``: the compact-JSON dict of :func:`behaviour_view`."""
        log.debug("get_purchase_behaviour %s %s ref=%s", membership_id, article_number, ref)
        return behaviour_view(self.purchase_behaviour(membership_id, article_number))
