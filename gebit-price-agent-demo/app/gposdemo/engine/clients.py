"""gRPC clients of engine and gate for ``showcase.wws.v1`` and ``showcase.loyalty.v1``.

The engine never reads the WWS or loyalty schemas; it asks the services through their
protos (UC1-BUILD-SPEC 2.2, 4.3, 4.4) and turns the answers into small frozen facts.
``NOT_FOUND`` becomes ``None``; every other ``grpc.RpcError`` propagates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import grpc
from google.protobuf import descriptor_pool
from google.protobuf.message import Message

from ..common.clock import from_ts, offset_ts_json
from ..common.descriptors import LOYALTY_SVC, WWS_SVC
from ..common.grpcutil import Client
from ..common.money import from_bdecimal, from_money, to_money
from .pricing import PriceChange

QUERY_TIMEOUT_S = 3.0
COMMAND_TIMEOUT_S = 5.0
ORIGINATOR = "gpos-engine"
APPROVER = "role:marktleitung"
REASON_CODES = {"slow_seller": "REASON_CODE_SLOW_SELLER",
                "season_end": "REASON_CODE_SEASON_END",
                "customer_behaviour": "REASON_CODE_CUSTOMER_BEHAVIOUR"}


@dataclass(frozen=True)
class EffectivePrice:
    """What the till charges now (business time) and the open action, if any."""

    price: Decimal
    regular_price: Decimal
    source: str              # REGULAR | CENTRAL_ACTION | BOOTH_ACTION
    action_id: str
    valid_to: datetime | None
    ref30: Decimal

    @property
    def action_open(self) -> bool:
        return self.source != "REGULAR"


@dataclass(frozen=True)
class ArticleFacts:
    article_number: str
    name: str
    net_quantity: Decimal
    base_unit: str
    vat_percent: Decimal
    cost_net: Decimal
    price_bound: bool
    season_code: str
    listed_since: date | None
    stock: int
    price: EffectivePrice
    last_price_change: PriceChange | None


@dataclass(frozen=True)
class SalesFacts:
    sold_7d: int
    plan_7d: Decimal
    weekly_units: tuple[int, ...]   # 8 values, oldest week first


@dataclass(frozen=True)
class SeasonFacts:
    code: str
    label: str
    start: date
    end: date


@dataclass(frozen=True)
class BehaviourFacts:
    consent_profiling: bool
    member_purchases_8w: int
    days_since_last: int
    median_interval_days: int
    cardholder_weekly: tuple[int, ...]


@dataclass(frozen=True)
class MemberFacts:
    membership_id: str
    persona: str
    consent_profiling: bool


@dataclass(frozen=True)
class PriceChangeRequest:
    """``RequestPriceChange`` of one approved proposal (the gate's only write)."""

    proposal_id: str
    article_number: str
    store_id: str
    expected_regular_price: Decimal
    new_price: Decimal
    pct_shown: int
    ref30: Decimal
    valid_from: datetime
    valid_to: datetime
    reason: str


def enum_name(msg: Message, field: str, prefix: str = "") -> str:
    """Name of an enum field value without ``prefix`` (``""`` for unknown numbers)."""
    descriptor = msg.DESCRIPTOR.fields_by_name[field].enum_type
    value = descriptor.values_by_number.get(getattr(msg, field))
    return value.name.removeprefix(prefix) if value is not None else ""


def _iso_date(text: str) -> date | None:
    return date.fromisoformat(text) if text else None


def _not_found(err: grpc.RpcError) -> bool:
    return isinstance(err, grpc.Call) and err.code() == grpc.StatusCode.NOT_FOUND


def effective_price(msg: Any, zone: ZoneInfo) -> EffectivePrice:
    """``datatype.EffectivePrice`` -> :class:`EffectivePrice` (``valid_to`` in ``zone``)."""
    valid_to = from_ts(msg.valid_to).astimezone(zone) if msg.HasField("valid_to") else None
    return EffectivePrice(
        price=from_money(msg.price), regular_price=from_money(msg.regular_price),
        source=enum_name(msg, "source", "PRICE_SOURCE_") or "REGULAR",
        action_id=msg.action_id, valid_to=valid_to, ref30=from_money(msg.ref30))


def article_facts(msg: Any, zone: ZoneInfo) -> ArticleFacts:
    """``datatype.Article`` -> :class:`ArticleFacts` (business times in ``zone``)."""
    change = None
    if msg.HasField("last_price_change"):
        pc = msg.last_price_change
        change = PriceChange(date.fromisoformat(pc.date), from_money(pc.old_price),
                             from_money(pc.new_price))
    return ArticleFacts(
        article_number=msg.article_number, name=msg.name,
        net_quantity=from_bdecimal(msg.net_quantity), base_unit=msg.base_unit,
        vat_percent=from_bdecimal(msg.vat_percent), cost_net=from_money(msg.cost_net),
        price_bound=msg.price_bound, season_code=msg.season_code,
        listed_since=_iso_date(msg.listed_since), stock=msg.stock_on_hand,
        price=effective_price(msg.price, zone), last_price_change=change)


def sales_facts(msg: Any) -> SalesFacts:
    """``datatype.SalesPerformance`` -> :class:`SalesFacts`."""
    return SalesFacts(sold_7d=msg.sold_7d, plan_7d=from_bdecimal(msg.plan_7d),
                      weekly_units=tuple(msg.weekly_units))


def season_facts(msg: Any) -> SeasonFacts | None:
    """``datatype.SeasonInfo`` -> :class:`SeasonFacts`; ``None`` for status ``none``."""
    if not msg.season_code or msg.status == "none":
        return None
    start, end = _iso_date(msg.start_date), _iso_date(msg.end_date)
    if start is None or end is None:
        return None
    return SeasonFacts(msg.season_code, msg.season_label, start, end)


def behaviour_facts(msg: Any) -> BehaviourFacts:
    """``datatype.PurchaseBehaviour`` -> :class:`BehaviourFacts`."""
    return BehaviourFacts(
        consent_profiling=msg.consent_profiling, member_purchases_8w=msg.member_purchases_8w,
        days_since_last=msg.days_since_last, median_interval_days=msg.median_interval_days,
        cardholder_weekly=tuple(msg.cardholder_weekly))


class WwsClient:
    """``MerchandiseService`` of ``gpos-wws``; business times are read and sent in ``zone``
    (``GPOS_TZ``)."""

    def __init__(self, pool: descriptor_pool.DescriptorPool, target: str, zone: ZoneInfo):
        self._client = Client(pool, WWS_SVC, target)
        self._zone = zone

    def article(self, number: str, store: str, trace_id: str = "") -> ArticleFacts | None:
        """``GetArticle`` by article number (effective price at business time)."""
        try:
            msg = self._client.call("GetArticle", {"traceId": trace_id, "storeId": store,
                                                   "articleNumber": number},
                                    timeout=QUERY_TIMEOUT_S)
        except grpc.RpcError as err:
            if _not_found(err):
                return None
            raise
        return article_facts(msg, self._zone)

    def sales(self, number: str, store: str, trace_id: str = "") -> SalesFacts | None:
        """``GetSalesPerformance``."""
        try:
            msg = self._client.call("GetSalesPerformance",
                                    {"traceId": trace_id, "storeId": store,
                                     "articleNumber": number}, timeout=QUERY_TIMEOUT_S)
        except grpc.RpcError as err:
            if _not_found(err):
                return None
            raise
        return sales_facts(msg)

    def season(self, number: str, store: str, trace_id: str = "") -> SeasonFacts | None:
        """``GetSeasonInfo``; ``None`` without a seasonal assignment."""
        try:
            msg = self._client.call("GetSeasonInfo", {"traceId": trace_id, "storeId": store,
                                                      "articleNumber": number},
                                    timeout=QUERY_TIMEOUT_S)
        except grpc.RpcError as err:
            if _not_found(err):
                return None
            raise
        return season_facts(msg)

    def request_price_change(self, req: PriceChangeRequest) -> tuple[str, bool]:
        """``RequestPriceChange`` (idempotent per proposal id) -> ``(action_id, created)``."""
        body = {
            "header": {"traceId": req.proposal_id, "originator": {"identityId": ORIGINATOR},
                       "approver": {"identityId": APPROVER}},
            "articleNumber": req.article_number, "storeId": req.store_id,
            "expectedRegularPrice": to_money(req.expected_regular_price),
            "newPrice": to_money(req.new_price), "pctShown": req.pct_shown,
            "ref30": to_money(req.ref30),
            "validFrom": offset_ts_json(req.valid_from.astimezone(self._zone)),
            "validTo": offset_ts_json(req.valid_to.astimezone(self._zone)),
            "proposalId": req.proposal_id,
            "reasonCode": REASON_CODES[req.reason]}
        msg: Any = self._client.call("RequestPriceChange", body, timeout=COMMAND_TIMEOUT_S)
        return msg.action_id, msg.created

    def close(self) -> None:
        self._client.close()


class LoyaltyClient:
    """``LoyaltyService`` of ``gpos-loyalty`` (profile and purchase behaviour)."""

    def __init__(self, pool: descriptor_pool.DescriptorPool, target: str):
        self._client = Client(pool, LOYALTY_SVC, target)

    def profile(self, membership_id: str, trace_id: str = "") -> MemberFacts | None:
        """``GetMemberProfile`` -> persona and profiling consent."""
        try:
            msg: Any = self._client.call("GetMemberProfile", {"traceId": trace_id,
                                                              "membershipId": membership_id},
                                         timeout=QUERY_TIMEOUT_S)
        except grpc.RpcError as err:
            if _not_found(err):
                return None
            raise
        return MemberFacts(msg.membership_id or membership_id, msg.persona_label,
                           msg.consent.profiling)

    def behaviour(self, membership_id: str, number: str,
                  trace_id: str = "") -> BehaviourFacts | None:
        """``GetPurchaseBehaviour`` of one member for one article."""
        try:
            msg = self._client.call("GetPurchaseBehaviour",
                                    {"traceId": trace_id, "membershipId": membership_id,
                                     "articleNumber": number}, timeout=QUERY_TIMEOUT_S)
        except grpc.RpcError as err:
            if _not_found(err):
                return None
            raise
        return behaviour_facts(msg)

    def close(self) -> None:
        self._client.close()
