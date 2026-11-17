"""Price actions of gpos-wws: request, end, reset, expiry (UC1-BUILD-SPEC 4.3, 5.4, 11.7).

* ``RequestPriceChange`` starts a booth action, idempotent per ``proposal_id``: a repeat
  returns the existing ``action_id`` with ``created=False`` and publishes nothing.
  Checks in this order: request complete (``WWS-002``), repeat, action still in the
  future (``WWS-002``), article known (``WWS-001``), not price bound (``WWS-012``),
  expected regular price (``WWS-020``), a real reduction (``WWS-010``), no open action
  (``WWS-011``). Before every request, open actions with ``valid_to < demo_now()`` are
  ended with reason ``expired`` (5.4).
* Booth actions start at business date 00:00 (6.7 step 5): the engine sends that
  ``valid_from``; a request without one gets it here.
* Every change of an action writes ``wws.audit`` and one event to the outbox in the same
  transaction, under the advisory lock of its aggregate; requests (shared) and resets
  (exclusive) also take the store lock, so a reset never misses an action in flight.
* Prices are whole cents up to 999999,99 € (``numeric(8,2)``), else ``WWS-002``.
* Booth actions never touch ``wws.price_history`` (ref30 without booth actions, 5.4),
  ``wws.stock`` or ``wws.sales_daily``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from gposdemo.common.db import Db
from gposdemo.common.fmt import dt_label, eur
from gposdemo.common.ids import make_id

from . import errors, store
from .analytics import ArticleRecord, PriceAction
from .errors import WwsError
from .events import Authorization, PriceEvents

log = logging.getLogger(__name__)

BOOTH = "BOOTH"
ACTION_ID_PREFIX = "PA"
REASON_EXPIRED = "expired"
REASON_RESET = "reset"
REASON_ENDED = "ended"
MAX_PCT_SHOWN = 99
CENT = Decimal("0.01")
MAX_PRICE = Decimal("999999.99")  # numeric(8,2) of wws.price_action (5.4)


@dataclass(frozen=True)
class PriceChangeCommand:
    """``command.RequestPriceChange`` as domain values (amounts ``Decimal``, times aware)."""

    trace_id: str
    originator: Authorization
    approver: Authorization
    article_number: str
    store_id: str
    expected_regular_price: Decimal
    new_price: Decimal
    pct_shown: int
    ref30: Decimal
    valid_from: datetime | None  # None: business date 00:00
    valid_to: datetime
    proposal_id: str
    reason_code: str  # enum name, never REASON_CODE_UNSPECIFIED


@dataclass
class ResetOutcome:
    """Action ids ended (booth) and restored (central) by ``ResetDemoState``."""

    ended: list[str] = field(default_factory=list)
    restored: list[str] = field(default_factory=list)


def valid_price(amount: Decimal) -> bool:
    """A storable shelf price: whole cents, ``0.01 <= amount <= 999999.99`` (the range is
    checked first, so a huge exponent never reaches ``quantize``)."""
    return CENT <= amount <= MAX_PRICE and amount == amount.quantize(CENT)


def validate(cmd: PriceChangeCommand) -> None:
    """Static checks of a request (``WWS-002``); nothing here depends on the database."""
    missing = [name for name, value in (
        ("header.originator", cmd.originator.identity_id),
        ("header.approver", cmd.approver.identity_id), ("article_number", cmd.article_number),
        ("store_id", cmd.store_id), ("proposal_id", cmd.proposal_id)) if not value]
    if missing:
        raise errors.invalid(f"Pflichtfeld fehlt: {', '.join(missing)}")
    for name, amount in (("expected_regular_price", cmd.expected_regular_price),
                         ("new_price", cmd.new_price), ("ref30", cmd.ref30)):
        if not valid_price(amount):
            raise errors.invalid(f"{name}: {amount} ist kein Preis in ganzen Cent "
                                 f"zwischen 0,01 und 999999,99 €")
    if not 0 <= cmd.pct_shown <= MAX_PCT_SHOWN:
        raise errors.invalid(f"pct_shown {cmd.pct_shown} liegt nicht zwischen 0 und 99")
    if cmd.valid_from is not None and cmd.valid_to <= cmd.valid_from:
        raise errors.invalid("valid_to muss nach valid_from liegen")


def check_article(article: ArticleRecord, cmd: PriceChangeCommand) -> None:
    """``WWS-012``, ``WWS-020`` and ``WWS-010`` against the current master data."""
    if article.price_bound:
        raise WwsError(errors.PRICE_BOUND, f"Artikel {article.article_number} ist "
                                           f"preisgebunden")
    if cmd.expected_regular_price != article.regular_price:
        raise WwsError(errors.REGULAR_MISMATCH,
                       f"Erwarteter Regulärpreis {eur(cmd.expected_regular_price)} € passt "
                       f"nicht zum aktuellen {eur(article.regular_price)} €")
    if cmd.new_price >= article.regular_price:
        raise WwsError(errors.NO_REDUCTION,
                       f"Keine Senkung: {eur(cmd.new_price)} € ist nicht kleiner als "
                       f"{eur(article.regular_price)} €")


def _repeat(existing: PriceAction, cmd: PriceChangeCommand) -> str:
    """The action id of an earlier call with the same ``proposal_id``."""
    if (existing.article_number, existing.store_id) != (cmd.article_number, cmd.store_id):
        raise errors.invalid(f"proposal_id {cmd.proposal_id} gehört zur Aktion "
                             f"{existing.action_id} eines anderen Artikels")
    return existing.action_id


def _day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _label(value: datetime, now: datetime) -> str:
    """``"Di 23.02. 20:00"`` in the time zone of the business clock."""
    return dt_label(value.astimezone(now.tzinfo))


class PriceActions:
    """Commands on ``wws.price_action``; ``clock`` is business time (``demo_now``)."""

    def __init__(self, db: Db, events: PriceEvents, clock: Callable[[], datetime]):
        self._db = db
        self._events = events
        self._clock = clock

    def request(self, cmd: PriceChangeCommand) -> tuple[str, bool]:
        """Start a booth action; ``(action_id, created)``."""
        validate(cmd)
        self.expire_due(cmd.trace_id)
        now = self._clock()
        with self._db.tx() as conn:
            store.lock_store(conn, cmd.store_id, exclusive=False)
            store.lock_aggregate(conn, store.aggregate_id(cmd.article_number, cmd.store_id))
            existing = store.action_by_proposal(conn, cmd.proposal_id)
            if existing is not None:
                return _repeat(existing, cmd), False
            if cmd.valid_to <= now:
                raise errors.invalid(f"valid_to {_label(cmd.valid_to, now)} liegt in der "
                                     f"Vergangenheit")
            article = store.article(conn, cmd.store_id, "article_number", cmd.article_number)
            if article is None:
                raise errors.article_unknown(cmd.article_number, cmd.store_id)
            check_article(article, cmd)
            running = store.open_actions(conn, cmd.store_id, cmd.article_number)
            if running:
                raise WwsError(errors.ACTION_RUNNING,
                               f"Für Artikel {cmd.article_number} läuft die Aktion "
                               f"{running[0].action_id} bis "
                               f"{_label(running[0].valid_to, now)}")
            action = PriceAction(
                action_id=make_id(ACTION_ID_PREFIX, now.date(), store.next_action_seq(conn)),
                article_number=cmd.article_number, store_id=cmd.store_id, kind=BOOTH,
                regular_price=article.regular_price, action_price=cmd.new_price,
                pct_shown=cmd.pct_shown, ref30=cmd.ref30,
                valid_from=cmd.valid_from or _day_start(now), valid_to=cmd.valid_to,
                proposal_id=cmd.proposal_id, reason_code=cmd.reason_code,
                originator=cmd.originator.identity_id, approver=cmd.approver.identity_id)
            store.insert_action(conn, action)
            self._events.emit_applied(conn, action, article.name, trace_id=cmd.trace_id,
                                      originator=cmd.originator, approver=cmd.approver)
            store.audit(conn, cmd.approver.identity_id, "price_action.created",
                        action.action_id,
                        {"proposal_id": cmd.proposal_id, "originator": action.originator,
                         "article_number": action.article_number, "store_id": action.store_id,
                         "regular_price": str(action.regular_price),
                         "action_price": str(action.action_price)})
        log.info("price action %s: %s %s %s -> %s", action.action_id, action.article_number,
                 action.store_id, action.regular_price, action.action_price)
        return action.action_id, True

    def end(self, action_id: str, reason: str, trace_id: str) -> bool:
        """End an open action now; ``False`` when it had already ended (idempotent)."""
        if not action_id:
            raise errors.invalid("Pflichtfeld fehlt: action_id")
        with self._db.tx() as conn:
            found = store.action_by_id(conn, action_id)
            if found is None:
                raise WwsError(errors.ACTION_UNKNOWN, f"Preisaktion {action_id} unbekannt")
            store.lock_aggregate(conn, store.aggregate_id(found.article_number, found.store_id))
            ended = store.end_action(conn, action_id, self._clock(), reason or REASON_ENDED)
            if ended is None:
                return False
            self._events.emit_ended(conn, ended, trace_id=trace_id)
            store.audit(conn, "wws", "price_action.ended", action_id,
                        {"reason": ended.end_reason, "trace_id": trace_id})
        return True

    def reset(self, store_id: str, full: bool, trace_id: str) -> ResetOutcome:
        """End every open booth action of the store; ``full`` also restores the central
        actions that are still valid (11.7 step 2). One transaction under the exclusive
        store lock (requests in flight finish first), aggregates locked in sorted order."""
        if not store_id:
            raise errors.invalid("Pflichtfeld fehlt: store_id")
        outcome = ResetOutcome()
        with self._db.tx() as conn:
            store.lock_store(conn, store_id, exclusive=True)
            now = self._clock()
            booth = [a for a in store.open_actions(conn, store_id) if a.kind == BOOTH]
            central = store.restorable_central(conn, store_id, now) if full else []
            for aggregate in sorted({store.aggregate_id(a.article_number, a.store_id)
                                     for a in booth + central}):
                store.lock_aggregate(conn, aggregate)
            for action in booth:
                ended = store.end_action(conn, action.action_id, now, REASON_RESET)
                if ended is not None:
                    self._events.emit_ended(conn, ended, trace_id=trace_id)
                    outcome.ended.append(ended.action_id)
            for action in central:
                self._restore(conn, action, trace_id, outcome)
            store.audit(conn, "wws", "demo.reset", store_id,
                        {"full": full, "trace_id": trace_id, "ended": outcome.ended,
                         "restored": outcome.restored})
        log.info("reset store %s (full=%s): ended %s, restored %s", store_id, full,
                 outcome.ended, outcome.restored)
        return outcome

    def _restore(self, conn: store.Conn, action: PriceAction, trace_id: str,
                 outcome: ResetOutcome) -> None:
        restored = store.reopen_action(conn, action.action_id)
        if restored is None:
            return
        found = store.article(conn, restored.store_id, "article_number",
                              restored.article_number)
        name = found.name if found else restored.article_number
        self._events.emit_applied(conn, restored, name, trace_id=trace_id,
                                  originator=Authorization(restored.originator),
                                  approver=None)
        outcome.restored.append(restored.action_id)

    def expire_due(self, trace_id: str) -> list[str]:
        """End open actions with ``valid_to < demo_now()`` (reason ``expired``, ended at
        ``valid_to``); one transaction per action, so no two aggregate locks are held."""
        now = self._clock()
        with self._db.tx() as conn:
            due = store.due_actions(conn, now)
        expired: list[str] = []
        for action in due:
            with self._db.tx() as conn:
                store.lock_aggregate(conn, store.aggregate_id(action.article_number,
                                                              action.store_id))
                ended = store.end_action(conn, action.action_id, action.valid_to,
                                         REASON_EXPIRED)
                if ended is None:
                    continue
                self._events.emit_ended(conn, ended, trace_id=trace_id)
                store.audit(conn, "wws", "price_action.expired", ended.action_id,
                            {"valid_to": ended.valid_to.isoformat(), "trace_id": trace_id})
                expired.append(ended.action_id)
        return expired
