"""GEBIT ``PurchaseTransactionService`` behaviour on schema ``pos`` (UC1-BUILD-SPEC 4.2).

``Simulator`` is the gRPC ``impl`` (one method per implemented RPC, name = RPC); the
generic server answers every other RPC of the 106 with ``UNIMPLEMENTED``. Adapted from
``spikes/grpc-spike/gebitsim/sim.py``, with the in-memory state replaced by ``pos``:

* A command reads the basket, calls WWS or loyalty outside any lock, then locks the
  basket row, checks the status again and writes lines, payments, receipt, basket and
  outbox rows in one transaction. Offsets continue ``pos.basket.last_offset``.
* After the commit the outbox relay is kicked (events reach the bus within
  milliseconds) and, after ``PurchaseTransactionClosed`` with a member,
  ``ReportPurchase`` is sent (best effort, business time).
* Status rules: :data:`ALLOWED`. ``AssignLoyaltyMembership`` also works in ``CREATED``
  (card before the first scan) and changes no status. A new transaction on a till
  resets that till's older open basket to ``RESET`` without events, so a till has at
  most one open basket.
* Business timestamps in event bodies (``createdAt``, ``openedAt``, ``closedAt``, ...)
  are business time ``demo_now()``; header and metadata are technical time.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

import grpc
from google.protobuf.message import Message

from gposdemo.common import grpcutil
from gposdemo.common.clock import demo_now, offset_ts_json, real_now
from gposdemo.common.config import Settings
from gposdemo.common.db import Db
from gposdemo.common.descriptors import Types
from gposdemo.common.jsonutil import proto_dict
from gposdemo.common.money import from_bdecimal, quantize, to_money
from gposdemo.common.outbox import OutboxWriter

from . import store
from .clients import ArticleInfo, EffectivePrice, LoyaltyClient, WwsClient
from .errors import (PosError, already_voided, invalid_argument, nothing_to_pay,
                     unknown_article, unknown_transaction, wrong_status)
from .events import EventFactory, status_enum, string_properties
from .pricing import (PricedLine, basket_total, payment_sums, pricing_information, settle)
from .receipt import ReceiptBuilder, receipt_number
from .store import Basket, Line

log = logging.getLogger(__name__)

DATATYPE_PKG = "de.gebit.rp.purchase.purchase.v2.datatype"
EMPTY = "google.protobuf.Empty"
DELIVERY_CLASS = "sam_input"
CURRENCY = "EUR"

ALLOWED: dict[str, tuple[str, ...]] = {
    "AddArticle": ("CREATED", "OPEN"),
    "AssignLoyaltyMembership": ("CREATED", "OPEN"),
    "VoidArticlePosition": ("OPEN",),
    "StartPaymentProcess": ("OPEN",),
    "CreateCashPayment": ("IN_PAYMENT",),
    "CancelPurchaseTransaction": ("CREATED", "OPEN", "IN_PAYMENT"),
}


def require_status(command: str, status: str) -> None:
    """Raise ``POS-002`` unless ``command`` is allowed in ``status`` (:data:`ALLOWED`)."""
    allowed = ALLOWED[command]
    if status not in allowed:
        raise wrong_status(command, status, allowed)


def priced(lines: Sequence[Line]) -> list[PricedLine]:
    """Pricing view of the effectual lines (``store.lines`` leaves voided ones out)."""
    return [PricedLine(ln.position_id, ln.unit_price, ln.item_count, ln.vat_pct)
            for ln in lines]


def cash_amount(amount: Any) -> Decimal:
    """Amount of a GEBIT ``Money`` request field: EUR, positive, at most two places."""
    if amount.currency not in ("", CURRENCY):
        raise invalid_argument(f"Währung {amount.currency} nicht unterstützt")
    value = from_bdecimal(amount.amount)
    if value <= 0 or quantize(value) != value:
        raise invalid_argument(f"ungültiger Betrag {value}")
    return quantize(value)


class _Batch:
    """Events of one basket inside one DB transaction (offsets from ``last_offset``)."""

    def __init__(self, conn: store.Conn, factory: EventFactory, outbox: OutboxWriter,
                 basket: Basket):
        self._conn = conn
        self._factory = factory
        self._outbox = outbox
        self._basket = basket

    def emit(self, name: str, body: dict[str, Any], trace_id: str) -> None:
        b = self._basket
        b.last_offset += 1
        event = self._factory.build(name, body, tx_id=b.tx_id, location=b.location,
                                    offset=b.last_offset, trace_id=trace_id)
        self._outbox.add(self._conn, aggregate_id=b.tx_id, aggregate_offset=event.offset,
                         event_type=event.event_type, topic=event.topic,
                         payload_text=event.payload, delivery_class=DELIVERY_CLASS,
                         user_props=event.props)


class Simulator:
    """gRPC implementation of the used subset of the GEBIT Purchase API 2.50.0."""

    def __init__(self, settings: Settings, db: Db, types: Types, wws: WwsClient,
                 loyalty: LoyaltyClient, on_commit: Callable[[], None]):
        self._s = settings
        self._db = db
        self._types = types
        self._factory = EventFactory(types.pool)
        self._receipts = ReceiptBuilder(types)
        self._outbox = OutboxWriter("pos")
        self._wws = wws
        self._loyalty = loyalty
        self._on_commit = on_commit

    # ------------------------------------------------------------------ plumbing
    def _rpc(self, context: grpc.ServicerContext, command: Callable[[], Message]) -> Message:
        try:
            return command()
        except PosError as err:
            log.info("%s", err)
            grpcutil.abort(context, err.status, err.code, err.text)
        except Exception:
            log.exception("POS command failed")
            context.abort(grpc.StatusCode.INTERNAL, "interner Fehler des Kassensimulators")

    def _empty(self) -> Message:
        return self._types.new(EMPTY)

    def _now(self) -> datetime:
        return demo_now(self._s)

    def _read(self, tx_id: str, command: str) -> Basket:
        """Pre-check outside the lock (before calling WWS or loyalty)."""
        with self._db.tx() as conn:
            b = store.basket(conn, tx_id)
        if b is None:
            raise unknown_transaction(tx_id)
        require_status(command, b.status)
        return b

    def _locked(self, conn: store.Conn, tx_id: str, command: str) -> Basket:
        b = store.basket(conn, tx_id, lock=True)
        if b is None:
            raise unknown_transaction(tx_id)
        require_status(command, b.status)
        return b

    def _batch(self, conn: store.Conn, b: Basket) -> _Batch:
        return _Batch(conn, self._factory, self._outbox, b)

    # ------------------------------------------------------------------ RPCs
    def CreatePurchaseTransaction(self, request: Any, context: grpc.ServicerContext) -> Message:
        return self._rpc(context, lambda: self._create(request))

    def AddArticle(self, request: Any, context: grpc.ServicerContext) -> Message:
        return self._rpc(context, lambda: self._add_article(request))

    def VoidArticlePosition(self, request: Any, context: grpc.ServicerContext) -> Message:
        return self._rpc(context, lambda: self._void(request))

    def AssignLoyaltyMembership(self, request: Any, context: grpc.ServicerContext) -> Message:
        return self._rpc(context, lambda: self._assign_membership(request))

    def StartPaymentProcess(self, request: Any, context: grpc.ServicerContext) -> Message:
        return self._rpc(context, lambda: self._start_payment(request))

    def CreateCashPayment(self, request: Any, context: grpc.ServicerContext) -> Message:
        return self._rpc(context, lambda: self._cash_payment(request))

    def CancelPurchaseTransaction(self, request: Any, context: grpc.ServicerContext) -> Message:
        return self._rpc(context, lambda: self._cancel(request))

    # ------------------------------------------------------------------ commands
    def _create(self, req: Any) -> Message:
        trace = req.header.trace_id
        with self._db.tx() as conn:
            till = store.till_by_location(conn, req.location, lock=True)
            if till is None or not till.active:
                raise invalid_argument(f"keine aktive Kasse für Ort {req.location!r}")
            superseded = store.reset_open(conn, till.till_id)
            b = Basket(tx_id=str(uuid.uuid4()), till_id=till.till_id, store_id=till.store_id,
                       location=till.location, status="CREATED", employee_id=req.employee_id,
                       cashdrawer_id=req.cashdrawer_id)
            store.insert_basket(conn, b)
            self._batch(conn, b).emit("PurchaseTransactionCreated", {
                "location": b.location, "currency": CURRENCY,
                "createdAt": offset_ts_json(self._now()),
                "purchaseTransactionStatus": status_enum("CREATED"),
                "employeeId": req.employee_id, "cashdrawerId": req.cashdrawer_id,
                "pricingInformation": pricing_information([])}, trace)
            store.save_basket(conn, b)
        if superseded:
            log.info("till %s: open baskets %s reset by the new transaction", till.till_id,
                     superseded)
        self._on_commit()
        return self._types.new(f"{DATATYPE_PKG}.PurchaseTransactionId",
                               purchase_transaction_id=b.tx_id)

    def _lookup(self, b: Basket, article_id: str, trace: str) -> tuple[ArticleInfo,
                                                                       EffectivePrice]:
        if not article_id:
            raise unknown_article("(leer)")
        article = self._wws.article(b.store_id, article_id, trace)
        return article, self._wws.effective_price(b.store_id, article.article_number, trace)

    def _add_article(self, req: Any) -> Message:
        trace = req.header.trace_id
        count = req.item_count or 1
        if count < 1:
            raise invalid_argument(f"ungültige Menge {req.item_count}")
        pre = self._read(req.purchase_transaction_id, "AddArticle")
        article, price = self._lookup(pre, req.article_id, trace)
        capturing = (proto_dict(req.capturing_information)
                     if req.HasField("capturing_information") else None)
        with self._db.tx() as conn:
            b = self._locked(conn, pre.tx_id, "AddArticle")
            batch = self._batch(conn, b)
            if b.status == "CREATED":
                self._open(conn, b, batch, trace)
            line = Line(position_id=str(uuid.uuid4()), line_no=store.next_line_no(conn, b.tx_id),
                        article_number=article.article_number, article_id=article.article_id,
                        name=article.name, gtin=article.gtin or None, category=article.category,
                        item_count=count, unit_price=price.price,
                        regular_price=price.regular_price, price_source=price.source,
                        action_id=price.action_id or None, vat_pct=article.vat_pct)
            store.insert_line(conn, b.tx_id, line)
            effectual = priced(store.lines(conn, b.tx_id))
            b.total = basket_total(effectual)
            batch.emit("PositionAdded", self._position_added(line, effectual, capturing), trace)
            if line.line_no == 1:  # GEBIT: async fiscal start after the first position
                batch.emit("FiscalTransactionAssigned", {
                    "purchaseTransactionStatus": status_enum("OPEN"),
                    "fiscalTransactionId": str(uuid.uuid4())}, "")
            store.save_basket(conn, b)
        self._on_commit()
        return self._empty()

    def _open(self, conn: store.Conn, b: Basket, batch: _Batch, trace: str) -> None:
        b.status = "OPEN"
        b.opened_at = real_now()
        b.receipt_number = receipt_number(b.store_id, b.till_id, self._s.demo_date,
                                          store.next_receipt_seq(conn))
        batch.emit("PurchaseTransactionOpened", {
            "openedAt": offset_ts_json(self._now()),
            "purchaseTransactionStatus": status_enum("OPEN"),
            "receiptNumber": b.receipt_number}, trace)

    def _position_added(self, line: Line, effectual: list[PricedLine],
                        capturing: dict[str, Any] | None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "positionId": line.position_id, "articlePositionType": "ARTICLE_POSITION_TYPE_SALE",
            "articleId": line.article_id, "articleNumber": line.article_number,
            "itemCount": line.item_count, "description": line.name,
            "pricingInformation": pricing_information(effectual),
            "createdAt": offset_ts_json(self._now()),
            "purchaseTransactionStatus": status_enum("OPEN"),
            "extensionProperties": string_properties({
                "showcase.priceSource": line.price_source,
                "showcase.regularPrice": f"{line.regular_price:.2f}",
                "showcase.actionId": line.action_id or "",
                "showcase.gtin": line.gtin or ""})}
        if capturing:
            body["capturingInformation"] = capturing
        return body

    def _void(self, req: Any) -> Message:
        trace = req.header.trace_id
        with self._db.tx() as conn:
            b = self._locked(conn, req.purchase_transaction_id, "VoidArticlePosition")
            line = store.find_line(conn, b.tx_id, req.position_id)
            if line is None:
                raise invalid_argument(f"Position {req.position_id!r} gehört nicht zum Bon")
            if line.voided:
                raise already_voided(line.position_id)
            store.void_line(conn, b.tx_id, line.position_id)
            effectual = priced(store.lines(conn, b.tx_id))
            b.total = basket_total(effectual)
            self._batch(conn, b).emit("ArticlePositionVoided", {
                "positionId": line.position_id,
                "pricingInformation": pricing_information(effectual),
                "purchaseTransactionStatus": status_enum(b.status)}, trace)
            store.save_basket(conn, b)
        self._on_commit()
        return self._empty()

    def _assign_membership(self, req: Any) -> Message:
        trace = req.header.trace_id
        card = req.membership_identification_value.strip()
        if not card:
            raise invalid_argument("keine Kartennummer")
        capturing = (proto_dict(req.capturing_information)
                     if req.HasField("capturing_information") else None)
        pre = self._read(req.purchase_transaction_id, "AssignLoyaltyMembership")
        membership_id = self._loyalty.resolve(card, pre.tx_id, pre.location, capturing, trace)
        with self._db.tx() as conn:
            b = self._locked(conn, pre.tx_id, "AssignLoyaltyMembership")
            b.membership_id = membership_id
            b.membership_position_id = str(uuid.uuid4())
            body: dict[str, Any] = {
                "pricingInformation": pricing_information(priced(store.lines(conn, b.tx_id))),
                "purchaseTransactionStatus": status_enum(b.status),
                "membershipPositionId": b.membership_position_id}
            if capturing:
                body["capturingInformation"] = capturing
            self._batch(conn, b).emit("LoyaltyMembershipAssigned", body, trace)
            store.save_basket(conn, b)
        self._on_commit()
        return self._empty()

    def _start_payment(self, req: Any) -> Message:
        trace = req.header.trace_id
        with self._db.tx() as conn:
            b = self._locked(conn, req.purchase_transaction_id, "StartPaymentProcess")
            effectual = priced(store.lines(conn, b.tx_id))
            if not effectual:
                raise nothing_to_pay()
            b.status = "IN_PAYMENT"
            self._batch(conn, b).emit("PaymentProcessStarted", {
                "purchaseTransactionStatus": status_enum("IN_PAYMENT"),
                "paymentSessionSums": payment_sums(b.total, b.paid),
                "pricingInformation": pricing_information(effectual)}, trace)
            store.save_basket(conn, b)
        self._on_commit()
        return self._empty()

    def _cash_payment(self, req: Any) -> Message:
        trace = req.header.trace_id
        amount = cash_amount(req.amount)
        with self._db.tx() as conn:
            b = self._locked(conn, req.purchase_transaction_id, "CreateCashPayment")
            lines = store.lines(conn, b.tx_id)
            effectual = priced(lines)
            result = settle(b.total, b.paid, amount)
            b.paid = result.paid
            batch = self._batch(conn, b)
            payment_id = str(uuid.uuid4())
            store.insert_payment(conn, b.tx_id, payment_id, "CASH", amount)
            batch.emit("CashPaymentPositionCreated", {
                "purchaseTransactionStatus": status_enum("IN_PAYMENT"),
                "pricingInformation": pricing_information(effectual),
                "paymentPositionId": payment_id, "clientId": req.client_id,
                "clientTransactionId": req.client_transaction_id, "amount": to_money(amount),
                "paymentSessionSums": payment_sums(b.total, b.paid),
                "paymentType": "PAYMENT_TYPE_PAYMENT",
                "paymentTransactionType": "PAYMENT_TRANSACTION_TYPE_PAYMENT",
                "createdAt": offset_ts_json(self._now())}, trace)
            closed_at = (self._close(conn, b, batch, result.signed_change, trace)
                         if result.complete else None)
            store.save_basket(conn, b)
        self._on_commit()
        if closed_at is not None and b.membership_id:
            self._report(b, lines, closed_at, trace)
        return self._empty()

    def _close(self, conn: store.Conn, b: Basket, batch: _Batch, signed_change: Decimal,
               trace: str) -> datetime:
        """Change, payment completion and the closing events; returns ``closedAt``."""
        payment_ids = store.payment_ids(conn, b.tx_id)
        if signed_change:
            change_id = str(uuid.uuid4())
            store.insert_payment(conn, b.tx_id, change_id, "CHANGE", signed_change)
            payment_ids.append(change_id)
            batch.emit("CashPaymentPositionCreated", {
                "purchaseTransactionStatus": status_enum("IN_PAYMENT"),
                "paymentPositionId": change_id, "clientId": b.location,
                "clientTransactionId": change_id, "amount": to_money(signed_change),
                "paymentSessionSums": payment_sums(b.total, b.paid, signed_change),
                "paymentType": "PAYMENT_TYPE_CHANGE",
                "paymentTransactionType": "PAYMENT_TRANSACTION_TYPE_CHANGE",
                "createdAt": offset_ts_json(self._now())}, trace)
        batch.emit("PaymentProcessCompleted", {
            "purchaseTransactionStatus": status_enum("IN_PAYMENT"),
            "paymentSessionSums": payment_sums(b.total, b.paid, signed_change),
            "paymentPositionIds": payment_ids}, trace)
        for name, status in (("PurchaseTransactionInChargingFinancialTransaction",
                              "IN_CHARGING_FINANCIAL_TRANSACTION"),
                             ("PurchaseTransactionInClosing", "IN_CLOSING")):
            batch.emit(name, {"purchaseTransactionStatus": status_enum(status)}, trace)
        b.status = "CLOSED"
        b.closed_at = real_now()
        closed_at = self._now()
        receipt = self._receipts.build(tx_id=b.tx_id, receipt_number=b.receipt_number or "",
                                       location=b.location, total=b.total, closed=True)
        store.insert_receipt(conn, b.tx_id, b.receipt_number or "", receipt.api_version,
                             receipt.content_b64)
        batch.emit("PurchaseTransactionClosed", {
            "closedAt": offset_ts_json(closed_at),
            "purchaseTransactionStatus": status_enum("CLOSED"), **receipt.event_fields()}, trace)
        return closed_at

    def _report(self, b: Basket, effectual: Sequence[Line], closed_at: datetime,
                trace: str) -> None:
        """``ReportPurchase`` of a member's closed basket (business time, effectual lines)."""
        self._loyalty.report_purchase({
            "purchaseTransactionId": b.tx_id, "receiptNumber": b.receipt_number or "",
            "location": b.location, "transactionType": "TRANSACTION_TYPE_SALE",
            "closedAt": offset_ts_json(closed_at), "membershipId": b.membership_id,
            "lines": [{"positionId": ln.position_id, "articleId": ln.article_id,
                       "articleNumber": ln.article_number, "category": ln.category,
                       "itemCount": ln.item_count,
                       "effectiveValue": to_money(ln.unit_price * ln.item_count),
                       "effectual": True, "promotionActive": ln.price_source != "REGULAR"}
                      for ln in effectual],
            "total": to_money(b.total)}, trace)

    def _cancel(self, req: Any) -> Message:
        trace = req.header.trace_id
        with self._db.tx() as conn:
            b = self._locked(conn, req.purchase_transaction_id, "CancelPurchaseTransaction")
            pricing = pricing_information(priced(store.lines(conn, b.tx_id)))
            batch = self._batch(conn, b)
            batch.emit("PurchaseTransactionInCancellation", {
                "purchaseTransactionStatus": status_enum("IN_CANCELLATION"),
                "pricingInformation": pricing, "cancellationReason": req.cancellation_reason,
                "cancellationReasonCode": req.cancellation_reason_code}, trace)
            b.status = "CANCELLED"
            receipt = self._receipts.build(tx_id=b.tx_id, receipt_number=b.receipt_number or "",
                                           location=b.location, total=b.total, closed=False)
            store.insert_receipt(conn, b.tx_id, b.receipt_number or "", receipt.api_version,
                                 receipt.content_b64)
            batch.emit("PurchaseTransactionCancelled", {
                "purchaseTransactionStatus": status_enum("CANCELLED"),
                "pricingInformation": pricing, "cancelledAt": offset_ts_json(self._now()),
                **receipt.event_fields()}, trace)
            store.save_basket(conn, b)
        self._on_commit()
        return self._empty()
