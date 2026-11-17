"""gpos-wws domain service and its gRPC layer (UC1-BUILD-SPEC 2.3, 2.4, 4.3, 4.5).

``WwsService`` is the Fachobjekt: pure methods that return ``showcase.wws.v1``
messages (gRPC side) or the agent-tool dicts of 8.4 (``get_article``,
``get_sales_performance``, ``get_season_info``, same ``str`` parameters as the MCP
tools). ``MerchandiseImpl`` is the thin gRPC wrapper: one method per RPC of
``MerchandiseService`` that unpacks the request, calls the service and maps a
``WwsError`` to status, ``"<CODE>: <text>"`` and trailing metadata ``gpos-error-code``.

Business time (``demo_now()``) drives prices, validities, sales windows, seasons and
``ref30``; the clock is injectable for tests.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

import grpc
import psycopg
from google.protobuf.message import Message

from gposdemo.common import grpcutil
from gposdemo.common.clock import demo_now, from_ts
from gposdemo.common.config import Settings
from gposdemo.common.db import Db
from gposdemo.common.descriptors import Types
from gposdemo.common.jsonutil import parse_strict
from gposdemo.common.money import from_money

from . import analytics, errors, store, views
from .actions import PriceActions, PriceChangeCommand, ResetOutcome
from .analytics import ArticleRecord, PriceChange, PriceQuote, SalesFigures, SeasonFigures
from .errors import WwsError
from .events import Authorization, PriceEvents

log = logging.getLogger(__name__)

DATATYPE = "de.showcase.wws.v1.datatype."
EMPTY = "google.protobuf.Empty"
HISTORY_DEFAULT_DAYS = 90
HISTORY_MAX_DAYS = 3660  # ten years; keeps ``timedelta`` and the query sane
REASON_UNSPECIFIED = "REASON_CODE_UNSPECIFIED"
CURRENCY = "EUR"

T = TypeVar("T")


class WwsService:
    """Merchandise management of the showcase stores (articles, prices, sales, seasons,
    price actions)."""

    def __init__(self, s: Settings, db: Db, types: Types, *,
                 clock: Callable[[], datetime] | None = None):
        self.settings = s
        self._db = db
        self._types = types
        self._zone = ZoneInfo(s.tz)
        self._clock = clock or (lambda: demo_now(s))
        self.actions = PriceActions(db, PriceEvents(types, s), self._clock)

    def now(self) -> datetime:
        """Business time (``demo_now()`` unless a clock was injected)."""
        return self._clock()

    def _message(self, name: str, doc: dict[str, Any]) -> Message:
        return parse_strict(doc, self._types.new(DATATYPE + name), self._types.pool)

    # ------------------------------------------------------------------ snapshots
    def _article(self, conn: store.Conn, store_id: str, key: str, value: str) -> ArticleRecord:
        if not store_id or not value:
            raise errors.article_unknown(value, store_id)
        found = store.article(conn, store_id, key, value)
        if found is None:
            raise errors.article_unknown(value, store_id)
        return found

    def _price(self, conn: store.Conn, a: ArticleRecord, at: datetime
               ) -> tuple[PriceQuote, PriceChange | None]:
        history = store.price_history(conn, a.store_id, a.article_number).get(
            a.article_number, [])
        actions = store.open_actions(conn, a.store_id, a.article_number)
        return (analytics.quote(a, actions, history, at),
                analytics.last_price_change(history, at, self._zone))

    @staticmethod
    def _daily(conn: store.Conn, a: ArticleRecord, day: date) -> list[tuple[date, int]]:
        """Daily units of the 8 sales windows ``[D-56, D-1]``."""
        first = analytics.week_windows(day)[0][0]
        return store.daily_sales(conn, a.article_number, a.store_id, first,
                                 day - timedelta(days=1))

    def _sales(self, conn: store.Conn, a: ArticleRecord, now: datetime) -> SalesFigures:
        day = now.date()
        return analytics.sales_figures(
            a, store.plan_week(conn, a.article_number, a.store_id), self._daily(conn, a, day),
            day, store.next_delivery(conn, a.article_number, a.store_id, day))

    def _season(self, conn: store.Conn, a: ArticleRecord, now: datetime
                ) -> SeasonFigures | None:
        season = store.season(conn, a.season_code) if a.season_code else None
        if season is None:
            return None
        day = now.date()
        weekly = analytics.weekly_units(self._daily(conn, a, day), day)
        return analytics.season_figures(season, day, weekly, a.stock_on_hand)

    @staticmethod
    def _margin(a: ArticleRecord, q: PriceQuote) -> Decimal:
        return analytics.margin_pct(q.price, a.vat_pct, a.cost_net)

    # ----------------------------------------------------------- queries (gRPC side)
    def list_articles(self, store_id: str, category: str = "") -> Message:
        """``datatype.ArticleList`` of the store at business time, in file order."""
        at = self.now()
        with self._db.tx() as conn:
            found = store.articles(conn, store_id, category)
            history = store.price_history(conn, store_id)
            actions = store.open_actions(conn, store_id)
        docs = []
        for a in found:
            rows = history.get(a.article_number, [])
            q = analytics.quote(a, actions, rows, at)
            change = analytics.last_price_change(rows, at, self._zone)
            docs.append(views.article_doc(a, q, self._margin(a, q), change, self._zone))
        return self._message("ArticleList", {"articles": docs})

    def find_article(self, store_id: str, key: str, value: str) -> Message:
        """``datatype.Article`` by ``article_number``, ``gtin`` or ``article_id``."""
        if key not in store.ARTICLE_KEYS:
            raise errors.invalid("Artikelschlüssel fehlt (article_number, gtin oder "
                                 "article_id)")
        at = self.now()
        with self._db.tx() as conn:
            a = self._article(conn, store_id, key, value)
            q, change = self._price(conn, a, at)
        return self._message("Article", views.article_doc(a, q, self._margin(a, q), change,
                                                          self._zone))

    def effective_price(self, article_number: str, store_id: str,
                        at: datetime | None = None) -> Message:
        """``datatype.EffectivePrice`` at ``at`` (default: business time now)."""
        at = at or self.now()
        with self._db.tx() as conn:
            a = self._article(conn, store_id, "article_number", article_number)
            q, _ = self._price(conn, a, at)
        return self._message("EffectivePrice",
                             views.effective_price_doc(a.article_number, store_id, q,
                                                       self._zone))

    def sales_performance(self, article_number: str, store_id: str) -> Message:
        """``datatype.SalesPerformance`` (windows end yesterday)."""
        now = self.now()
        with self._db.tx() as conn:
            a = self._article(conn, store_id, "article_number", article_number)
            figures = self._sales(conn, a, now)
        return self._message("SalesPerformance",
                             views.sales_doc(a.article_number, store_id, figures))

    def season_info(self, article_number: str, store_id: str) -> Message:
        """``datatype.SeasonInfo``; status ``none`` for a non-seasonal article."""
        now = self.now()
        with self._db.tx() as conn:
            a = self._article(conn, store_id, "article_number", article_number)
            figures = self._season(conn, a, now)
        return self._message("SeasonInfo", views.season_doc(a.article_number, figures))

    def price_history(self, article_number: str, store_id: str, days: int = 0) -> Message:
        """``datatype.PriceHistory`` of the last ``days`` (0 = default 90, at most 3660)
        plus ``ref30``; other values are ``WWS-002``."""
        if not 0 <= days <= HISTORY_MAX_DAYS:
            raise errors.invalid(f"days {days} liegt nicht zwischen 0 (Standard "
                                 f"{HISTORY_DEFAULT_DAYS}) und {HISTORY_MAX_DAYS}")
        at = self.now()
        start = at - timedelta(days=days or HISTORY_DEFAULT_DAYS)
        with self._db.tx() as conn:
            a = self._article(conn, store_id, "article_number", article_number)
            rows = store.price_history(conn, store_id, a.article_number).get(
                a.article_number, [])
        shown = [h for h in rows if h.overlaps(start, at)]
        ref30 = analytics.ref30(rows, at, a.regular_price)
        return self._message("PriceHistory", views.history_doc(a.article_number, store_id,
                                                               shown, ref30, self._zone))

    # ----------------------------------------------------------------------- commands
    def request_price_change(self, cmd: PriceChangeCommand) -> Message:
        """``datatype.PriceActionId``; idempotent per ``proposal_id``."""
        action_id, created = self.actions.request(cmd)
        return self._message("PriceActionId", {"action_id": action_id, "created": created})

    def end_price_change(self, action_id: str, reason: str, trace_id: str) -> bool:
        """End a running action; ``False`` when it had already ended."""
        return self.actions.end(action_id, reason, trace_id)

    def reset_demo_state(self, store_id: str, full: bool, trace_id: str) -> ResetOutcome:
        """End all booth actions of the store; ``full`` also restores central actions."""
        return self.actions.reset(store_id, full, trace_id)

    # ----------------------------------------------------- agent tools (8.4, dicts)
    def get_article(self, article_number: str, ref: str = "") -> dict[str, Any]:
        """Master data, effective price, ``ref30``, stock, margin, last price change of
        the tool store. ``ref`` is the caller's reference (telemetry only)."""
        at = self.now()
        with self._db.tx() as conn:
            a = self._article(conn, self.settings.tool_store, "article_number", article_number)
            q, change = self._price(conn, a, at)
            season = store.season(conn, a.season_code) if a.season_code else None
        return views.agent_article(a, q, self._margin(a, q), change, season, self._zone)

    def get_sales_performance(self, article_number: str, ref: str = "") -> dict[str, Any]:
        """Sales against plan and weeks of supply in the tool store (``ref``: telemetry)."""
        now = self.now()
        with self._db.tx() as conn:
            a = self._article(conn, self.settings.tool_store, "article_number", article_number)
            figures = self._sales(conn, a, now)
        return views.agent_sales(a.article_number, figures)

    def get_season_info(self, article_number: str, ref: str = "") -> dict[str, Any]:
        """Season status and leftover stock in the tool store (``ref``: telemetry)."""
        now = self.now()
        with self._db.tx() as conn:
            a = self._article(conn, self.settings.tool_store, "article_number", article_number)
            figures = self._season(conn, a, now)
        return views.agent_season(a.article_number, figures)


# ---------------------------------------------------------------------------- gRPC
def _auth(msg: Any) -> Authorization:
    return Authorization(msg.identity_id, msg.details)


def _time(request: Message, name: str) -> datetime:
    """Aware time of an ``OffsetTimestamp`` field (``WWS-002`` outside ``datetime``'s range,
    which ``from_ts`` reports as ``ValueError``/``OverflowError``/``OSError``)."""
    try:
        return from_ts(getattr(request, name))
    except (ValueError, OverflowError, OSError) as exc:
        raise errors.invalid(f"{name}: Zeitpunkt außerhalb des gültigen Bereichs") from exc


def _amount(request: Message, name: str) -> Decimal:
    """Amount of a mandatory ``Money`` field (``WWS-002`` when unset or not EUR)."""
    if not request.HasField(name):
        raise errors.invalid(f"Pflichtfeld fehlt: {name}")
    money = getattr(request, name)
    if money.currency != CURRENCY:
        raise errors.invalid(f"{name}: Währung {money.currency or '(leer)'} statt EUR")
    return from_money(money)


def command_from_request(request: Message) -> PriceChangeCommand:
    """``command.RequestPriceChange`` -> :class:`PriceChangeCommand` (``WWS-002`` on gaps)."""
    if not request.HasField("valid_to"):
        raise errors.invalid("Pflichtfeld fehlt: valid_to")
    reason = request.DESCRIPTOR.fields_by_name["reason_code"].enum_type.values_by_number.get(
        request.reason_code)
    if reason is None or reason.name == REASON_UNSPECIFIED:
        raise errors.invalid("Pflichtfeld fehlt: reason_code")
    header = request.header
    return PriceChangeCommand(
        trace_id=header.trace_id,
        originator=_auth(header.originator),
        approver=_auth(header.approver),
        article_number=request.article_number,
        store_id=request.store_id,
        expected_regular_price=_amount(request, "expected_regular_price"),
        new_price=_amount(request, "new_price"),
        pct_shown=request.pct_shown,
        ref30=_amount(request, "ref30"),
        valid_from=_time(request, "valid_from") if request.HasField("valid_from") else None,
        valid_to=_time(request, "valid_to"),
        proposal_id=request.proposal_id,
        reason_code=reason.name,
    )


class MerchandiseImpl:
    """``de.showcase.wws.v1.service.MerchandiseService``: all nine RPCs of 4.3."""

    def __init__(self, service: WwsService, types: Types):
        self._svc = service
        self._types = types

    def _run(self, context: grpc.ServicerContext, call: Callable[[], T]) -> T:
        try:
            return call()
        except WwsError as err:
            grpcutil.abort(context, err.status, err.code, err.text)
        except psycopg.OperationalError:
            log.exception("database unavailable")
            context.abort(grpc.StatusCode.UNAVAILABLE,
                          "Warenwirtschaft: Datenbank nicht erreichbar")

    def _empty(self) -> Message:
        return self._types.new(EMPTY)

    def ListArticles(self, request: Any, context: grpc.ServicerContext) -> Message:
        return self._run(context, lambda: self._svc.list_articles(request.store_id,
                                                                  request.category))

    def GetArticle(self, request: Any, context: grpc.ServicerContext) -> Message:
        key = request.WhichOneof("key") or ""
        value = getattr(request, key) if key else ""
        return self._run(context, lambda: self._svc.find_article(request.store_id, key, value))

    def GetEffectivePrice(self, request: Any, context: grpc.ServicerContext) -> Message:
        return self._run(context, lambda: self._svc.effective_price(
            request.article_number, request.store_id,
            _time(request, "at") if request.HasField("at") else None))

    def GetSalesPerformance(self, request: Any, context: grpc.ServicerContext) -> Message:
        return self._run(context, lambda: self._svc.sales_performance(
            request.article_number, request.store_id))

    def GetSeasonInfo(self, request: Any, context: grpc.ServicerContext) -> Message:
        return self._run(context, lambda: self._svc.season_info(request.article_number,
                                                                request.store_id))

    def GetPriceHistory(self, request: Any, context: grpc.ServicerContext) -> Message:
        return self._run(context, lambda: self._svc.price_history(
            request.article_number, request.store_id, request.days))

    def RequestPriceChange(self, request: Any, context: grpc.ServicerContext) -> Message:
        return self._run(context, lambda: self._svc.request_price_change(
            command_from_request(request)))

    def EndPriceChange(self, request: Any, context: grpc.ServicerContext) -> Message:
        self._run(context, lambda: self._svc.end_price_change(
            request.action_id, request.reason, request.header.trace_id))
        return self._empty()

    def ResetDemoState(self, request: Any, context: grpc.ServicerContext) -> Message:
        self._run(context, lambda: self._svc.reset_demo_state(
            request.store_id, request.full, request.header.trace_id))
        return self._empty()
