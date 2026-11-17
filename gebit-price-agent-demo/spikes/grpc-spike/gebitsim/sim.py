"""Minimal PurchaseTransactionService behaviour (in-memory; Postgres later).

Command -> event sequences follow the GEBIT simpleSale sample
(research/gebit-purchase-api.md section 4.3).
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

import grpc
from google.protobuf import any_pb2

from .events import EventFactory, bd, money, ots, split_tax

D = "de.gebit.rp.purchase.purchase.v2.datatype"
ST = "PURCHASE_TRANSACTION_STATUS_"

# articleId -> (articleNumber, description, gross cents, taxClass, rate bp)
CATALOG = {
    "IDarticle004": ("article004", "GEBIT Ente", 867, "C", 1900),
    "IDbanana01": ("banana01", "Bio Bananen 1 kg", 199, "A", 700),
    "IDcoffee01": ("coffee01", "Kaffee Crema 1 kg", 1499, "A", 700),
}


@dataclass
class Position:
    position_id: str
    article_id: str
    article_number: str
    description: str
    item_count: int
    unit_gross: int
    tax_class: str
    rate_bp: int

    @property
    def gross(self) -> int:
        return self.unit_gross * self.item_count


@dataclass
class Basket:
    tx_id: str
    location: str
    employee_id: str
    cashdrawer_id: str
    currency: str = "EUR"
    status: str = "CREATED"
    offset: int = 0
    receipt_number: str = ""
    created_ns: int = 0
    opened_ns: int = 0
    positions: list[Position] = field(default_factory=list)
    paid: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def next_offset(self) -> int:
        self.offset += 1
        return self.offset


class Simulator:
    def __init__(self, types, sink):
        self.types = types
        self.ev = EventFactory(types)
        self.sink = sink
        self.baskets: dict[str, Basket] = {}
        self.receipt_seq = 0
        self.lock = threading.Lock()

    # ---------- helpers ----------
    def pricing(self, b: Basket) -> dict:
        total = sum(p.gross for p in b.positions)
        by_class: dict[tuple[str, int], int] = {}
        for p in b.positions:
            by_class[(p.tax_class, p.rate_bp)] = by_class.get((p.tax_class, p.rate_bp), 0) + p.gross
        tax_sums, net_total = [], 0
        for (cls, rate), gross in sorted(by_class.items()):
            net, tax = split_tax(gross, rate)
            net_total += net
            tax_sums.append({"taxClass": cls, "taxRate": bd(rate), "taxAmount": bd(tax),
                             "netAmount": bd(net), "grossAmount": bd(gross)})
        positions = []
        for p in b.positions:
            net, tax = split_tax(p.gross, p.rate_bp)
            positions.append({"positionId": p.position_id, "calculatedPositionPrice": {
                "basePrice": bd(p.unit_gross), "baseValue": bd(p.gross), "effectiveValue": bd(p.gross),
                "taxes": [{"taxClass": p.tax_class, "taxRate": bd(p.rate_bp), "taxAmount": bd(tax),
                           "netAmount": bd(net), "grossAmount": bd(p.gross)}],
                "extensionProperties": [{"key": "positionType",
                                         "typedValue": {"stringValue": "articlePosition"}}]}})
        out = {"totalSum": bd(total), "netTotalSum": bd(net_total), "pricingMode": "PRICING_MODE_GROSS"}
        if tax_sums:
            out["taxSums"] = tax_sums
            out["articlePositions"] = positions
        return out

    def sums(self, b: Basket, change: int = 0) -> dict:
        """change is signed like GEBIT's (-133 = 1.33 EUR handed back); balance nets it out."""
        total = sum(p.gross for p in b.positions)
        return {"totalToPay": money(total), "totalPaid": money(b.paid), "balance": money(total - b.paid - change),
                "totalCashback": money(0), "totalRounding": money(0), "change": money(change)}

    def emit(self, b: Basket, name: str, body: dict, trace_id: str | None):
        e = self.ev.build(name, body, tx_id=b.tx_id, location=b.location,
                          offset=b.next_offset(), trace_id=trace_id)
        self.sink.publish(e)
        return e

    def basket(self, tx_id: str, context) -> Basket:
        b = self.baskets.get(tx_id)
        if b is None:
            context.abort(grpc.StatusCode.NOT_FOUND, f"purchase transaction {tx_id} not found")
        return b

    # ---------- RPCs (request = dynamic message from the pool) ----------
    def CreatePurchaseTransaction(self, req, context):
        now = time.time_ns()
        b = Basket(str(uuid.uuid4()), req.location or "Root.DE.999.101.01", req.employee_id,
                   req.cashdrawer_id, created_ns=now)
        with self.lock:
            self.baskets[b.tx_id] = b
        with b.lock:
            self.emit(b, "PurchaseTransactionCreated", {
                "location": b.location, "currency": b.currency, "createdAt": ots(now),
                "purchaseTransactionStatus": ST + "CREATED", "employeeId": b.employee_id,
                "cashdrawerId": b.cashdrawer_id, "pricingInformation": self.pricing(b)},
                req.header.trace_id)
        return self.types.new(f"{D}.PurchaseTransactionId", purchase_transaction_id=b.tx_id)

    def AddArticle(self, req, context):
        b = self.basket(req.purchase_transaction_id, context)
        art = CATALOG.get(req.article_id)
        if art is None:
            context.abort(grpc.StatusCode.NOT_FOUND, f"article {req.article_id} unknown")
        with b.lock:
            if b.status not in ("CREATED", "OPEN"):
                context.abort(grpc.StatusCode.FAILED_PRECONDITION, f"status {b.status}")
            trace = req.header.trace_id
            if b.status == "CREATED":
                b.status, b.opened_ns = "OPEN", time.time_ns()
                with self.lock:
                    self.receipt_seq += 1
                b.receipt_number = f"10276999101010026110200{self.receipt_seq:07d}"
                self.emit(b, "PurchaseTransactionOpened", {
                    "openedAt": ots(b.opened_ns), "purchaseTransactionStatus": ST + "OPEN",
                    "receiptNumber": b.receipt_number}, trace)
            p = Position(str(uuid.uuid4()), req.article_id, art[0], art[1], req.item_count or 1,
                         art[2], art[3], art[4])
            b.positions.append(p)
            body = {"positionId": p.position_id, "articlePositionType": "ARTICLE_POSITION_TYPE_SALE",
                    "articleId": p.article_id, "articleNumber": p.article_number,
                    "itemCount": p.item_count, "description": p.description,
                    "pricingInformation": self.pricing(b), "createdAt": ots(time.time_ns()),
                    "purchaseTransactionStatus": ST + "OPEN"}
            if req.HasField("capturing_information"):
                body["capturingInformation"] = {"inputMethod": req.capturing_information.input_method,
                                                "inputValue": req.capturing_information.input_value}
            self.emit(b, "PositionAdded", body, trace)
            if len(b.positions) == 1:  # GEBIT: async fiscal start after first position, no traceId
                self.emit(b, "FiscalTransactionAssigned", {
                    "purchaseTransactionStatus": ST + "OPEN", "fiscalTransactionId": str(uuid.uuid4())}, None)
        return self.types.new("google.protobuf.Empty")

    def StartPaymentProcess(self, req, context):
        b = self.basket(req.purchase_transaction_id, context)
        with b.lock:
            if b.status != "OPEN" or not b.positions:
                context.abort(grpc.StatusCode.FAILED_PRECONDITION, f"status {b.status}")
            b.status = "IN_PAYMENT"
            self.emit(b, "PaymentProcessStarted", {
                "purchaseTransactionStatus": ST + "IN_PAYMENT", "paymentSessionSums": self.sums(b),
                "pricingInformation": self.pricing(b)}, req.header.trace_id)
        return self.types.new("google.protobuf.Empty")

    def CreateCashPayment(self, req, context):
        b = self.basket(req.purchase_transaction_id, context)
        with b.lock:
            if b.status != "IN_PAYMENT":
                context.abort(grpc.StatusCode.FAILED_PRECONDITION, f"status {b.status}")
            a = req.amount.amount
            cents = a.int_val * 10 ** (2 - a.scale) if a.scale <= 2 else a.int_val // 10 ** (a.scale - 2)
            trace = req.header.trace_id
            b.paid += cents
            total = sum(p.gross for p in b.positions)
            pay_id = str(uuid.uuid4())
            self.emit(b, "CashPaymentPositionCreated", {
                "purchaseTransactionStatus": ST + "IN_PAYMENT", "pricingInformation": self.pricing(b),
                "paymentPositionId": pay_id, "clientId": req.client_id,
                "clientTransactionId": req.client_transaction_id,
                "amount": {"currency": req.amount.currency or b.currency,
                           "amount": {"scale": a.scale, "intVal": str(a.int_val)}},
                "paymentSessionSums": self.sums(b), "paymentType": "PAYMENT_TYPE_PAYMENT",
                "paymentTransactionType": "PAYMENT_TRANSACTION_TYPE_PAYMENT",
                "createdAt": ots(time.time_ns())}, trace)
            if b.paid < total:
                return self.types.new("google.protobuf.Empty")
            change = total - b.paid  # <= 0
            if change:
                chg_id = str(uuid.uuid4())
                self.emit(b, "CashPaymentPositionCreated", {
                    "purchaseTransactionStatus": ST + "IN_PAYMENT", "paymentPositionId": chg_id,
                    "clientId": b.location, "clientTransactionId": chg_id,
                    "amount": money(change), "paymentSessionSums": self.sums(b, change),
                    "paymentType": "PAYMENT_TYPE_CHANGE",
                    "paymentTransactionType": "PAYMENT_TRANSACTION_TYPE_CHANGE",
                    "createdAt": ots(time.time_ns())}, trace)
            self.emit(b, "PaymentProcessCompleted", {
                "purchaseTransactionStatus": ST + "IN_PAYMENT",
                "paymentSessionSums": self.sums(b, change)}, trace)
            self.emit(b, "PurchaseTransactionInChargingFinancialTransaction",
                      {"purchaseTransactionStatus": ST + "IN_CHARGING_FINANCIAL_TRANSACTION"}, trace)
            self.emit(b, "PurchaseTransactionInClosing", {"purchaseTransactionStatus": ST + "IN_CLOSING"}, trace)
            b.status = "CLOSED"
            receipt = self.receipt_any(b, "closed_receipt")
            self.emit(b, "PurchaseTransactionClosed", {
                "closedAt": ots(time.time_ns()), "purchaseTransactionStatus": ST + "CLOSED",
                "serializedReceiptFormat": "PROTOBUF", "serializedReceiptContent": receipt,
                "serializedReceiptVersion": "2.13.0-sim"}, trace)
        return self.types.new("google.protobuf.Empty")

    def CancelPurchaseTransaction(self, req, context):
        b = self.basket(req.purchase_transaction_id, context)
        with b.lock:
            if b.status in ("CLOSED", "CANCELLED"):
                context.abort(grpc.StatusCode.FAILED_PRECONDITION, f"status {b.status}")
            trace = req.header.trace_id
            self.emit(b, "PurchaseTransactionInCancellation", {
                "purchaseTransactionStatus": ST + "IN_CANCELLATION", "pricingInformation": self.pricing(b),
                "cancellationReason": req.cancellation_reason,
                "cancellationReasonCode": req.cancellation_reason_code}, trace)
            b.status = "CANCELLED"
            self.emit(b, "PurchaseTransactionCancelled", {
                "purchaseTransactionStatus": ST + "CANCELLED", "pricingInformation": self.pricing(b),
                "cancelledAt": ots(time.time_ns()), "serializedReceiptFormat": "PROTOBUF",
                "serializedReceiptContent": self.receipt_any(b, "canceled_receipt"),
                "serializedReceiptVersion": "2.13.0-sim"}, trace)
        return self.types.new("google.protobuf.Empty")

    # ---------- receipt (receipt-api descriptor, same pool) ----------
    def receipt_any(self, b: Basket, status_field: str) -> str:
        """Minimal Receipt packed as binary Any, base64 for the JSON bytes field."""
        import base64
        R = "de.gebit.rp.receipt.receipt.v2.datatype.Receipt"
        try:
            r = self.types.new(R)
        except KeyError:  # receipt descriptor set not mounted
            return ""
        total = sum(p.gross for p in b.positions)
        r.receipt_id = b.tx_id
        r.receipt_type = "SALE"
        getattr(r, status_field).SetInParent()  # oneof receipt_status
        r.receipt_number = b.receipt_number
        r.location = b.location
        r.currency = b.currency
        r.total.value = f"{total / 100:.2f}"  # receipt API: basic.Decimal{value: string}
        a = any_pb2.Any()
        a.Pack(r)
        return base64.b64encode(a.SerializeToString()).decode()
