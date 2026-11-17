"""gRPC clients of the POS simulator for WWS and loyalty (UC1-BUILD-SPEC 4.3, 4.4).

Both talk to the Showcase pool (never merged with the GEBIT pool, 4.1).

* WWS: ``GetArticle`` (master data by ``article_id``) and ``GetEffectivePrice`` (the
  price the till charges, business time = WWS ``demo_now()``). ``NOT_FOUND`` ->
  ``POS-003``; any other failure or an answer without a usable price -> ``POS-004``.
* Loyalty: ``ResolveMembership`` (``MEMBERSHIP_STATUS_ACTIVE`` or ``LOY-001``; an error
  code of the loyalty service is passed through) and ``ReportPurchase`` (best effort,
  2 s timeout; any failure is logged, never raised).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import grpc
from google.protobuf import descriptor_pool

from gposdemo.common.descriptors import LOYALTY_SVC, WWS_SVC
from gposdemo.common.grpcutil import Client, error_code
from gposdemo.common.money import from_bdecimal, from_money

from .errors import PosError, backend_unavailable, unknown_article

log = logging.getLogger(__name__)

WWS_TIMEOUT_S = 3.0
LOYALTY_TIMEOUT_S = 3.0
REPORT_TIMEOUT_S = 2.0
PRICE_SOURCES = ("REGULAR", "CENTRAL_ACTION", "BOOTH_ACTION")
ACTIVE = "MEMBERSHIP_STATUS_ACTIVE"
ORIGINATOR = {"identityId": "gpos-pos"}


@dataclass(frozen=True)
class ArticleInfo:
    """Master data the till needs for a basket line."""

    article_number: str
    article_id: str
    name: str
    gtin: str
    category: str
    vat_pct: Decimal


@dataclass(frozen=True)
class EffectivePrice:
    """What the till charges now, and why."""

    price: Decimal
    regular_price: Decimal
    source: str
    action_id: str


def _details(err: grpc.RpcError) -> str:
    return (err.details() if isinstance(err, grpc.Call) else "") or str(err)


class WwsClient:
    """``MerchandiseService`` of ``gpos-wws``."""

    def __init__(self, pool: descriptor_pool.DescriptorPool, target: str,
                 timeout: float = WWS_TIMEOUT_S):
        self._client = Client(pool, WWS_SVC, target)
        self._timeout = timeout

    def _call(self, method: str, body: Mapping[str, Any], key: str) -> dict[str, Any]:
        try:
            return self._client.call_json(method, body, self._timeout)
        except grpc.RpcError as err:
            if err.code() == grpc.StatusCode.NOT_FOUND:
                raise unknown_article(key) from err
            raise backend_unavailable("WWS", _details(err)) from err

    def article(self, store_id: str, article_id: str, trace_id: str) -> ArticleInfo:
        """``GetArticle`` by GEBIT ``article_id`` (e.g. ``ID100001``)."""
        data = self._call("GetArticle", {"traceId": trace_id, "storeId": store_id,
                                         "articleId": article_id}, article_id)
        number = data.get("articleNumber", "")
        if not number or not data.get("name") or "vatPercent" not in data:
            raise backend_unavailable("WWS", f"unvollständiger Artikel {article_id}")
        return ArticleInfo(article_number=number, article_id=data.get("articleId", article_id),
                           name=data["name"], gtin=data.get("gtin", ""),
                           category=data.get("category", ""),
                           vat_pct=from_bdecimal(data["vatPercent"]))

    def effective_price(self, store_id: str, article_number: str, trace_id: str
                        ) -> EffectivePrice:
        """``GetEffectivePrice`` at the WWS business time."""
        data = self._call("GetEffectivePrice", {"traceId": trace_id,
                                                "articleNumber": article_number,
                                                "storeId": store_id}, article_number)
        source = str(data.get("source", "")).removeprefix("PRICE_SOURCE_")
        price = from_money(data.get("price", {}))
        regular = from_money(data.get("regularPrice", {}))
        if source not in PRICE_SOURCES or price <= 0 or regular <= 0:
            raise backend_unavailable("WWS", f"kein gültiger Preis für {article_number}")
        return EffectivePrice(price=price, regular_price=regular, source=source,
                              action_id=data.get("actionId", ""))

    def close(self) -> None:
        """Close the channel."""
        self._client.close()


class LoyaltyClient:
    """``LoyaltyService`` of ``gpos-loyalty``."""

    def __init__(self, pool: descriptor_pool.DescriptorPool, target: str,
                 timeout: float = LOYALTY_TIMEOUT_S):
        self._client = Client(pool, LOYALTY_SVC, target)
        self._timeout = timeout

    def resolve(self, card: str, tx_id: str, location: str,
                capturing: Mapping[str, Any] | None, trace_id: str) -> str:
        """Membership id of an active card; ``LOY-001`` otherwise."""
        body: dict[str, Any] = {"traceId": trace_id, "membershipIdentificationValue": card,
                                "purchaseTransactionId": tx_id, "location": location}
        if capturing:
            body["capturingInformation"] = dict(capturing)
        try:
            data = self._client.call_json("ResolveMembership", body, self._timeout)
        except grpc.RpcError as err:
            code = error_code(err)
            if code:
                text = _details(err).removeprefix(f"{code}: ")
                raise PosError(err.code(), code, text) from err
            raise backend_unavailable("Loyalty", _details(err)) from err
        membership_id = data.get("membershipId", "")
        if data.get("status") != ACTIVE or not membership_id:
            raise PosError(grpc.StatusCode.INVALID_ARGUMENT, "LOY-001",
                           f"Karte {card} unbekannt oder gesperrt")
        return membership_id

    def report_purchase(self, purchase: Mapping[str, Any], trace_id: str) -> bool:
        """``ReportPurchase``; best effort: any failure is logged and returns False.

        The basket is committed ``CLOSED`` before this call (4.4), so no failure here
        (RPC error, closed channel, unserialisable body) may turn the payment into an
        error for the till.
        """
        body = {"header": {"traceId": trace_id, "originator": ORIGINATOR},
                "purchase": dict(purchase)}
        tx_id = purchase.get("purchaseTransactionId")
        try:
            self._client.call("ReportPurchase", body, REPORT_TIMEOUT_S)
        except grpc.RpcError as err:
            log.warning("ReportPurchase %s failed: %s", tx_id, _details(err))
            return False
        except Exception:  # noqa: BLE001 - best effort: the payment is committed already
            log.warning("ReportPurchase %s failed", tx_id, exc_info=True)
            return False
        return True

    def close(self) -> None:
        """Close the channel."""
        self._client.close()
