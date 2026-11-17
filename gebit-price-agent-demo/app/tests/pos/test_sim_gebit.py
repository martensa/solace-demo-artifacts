"""The GEBIT Purchase API simulator end to end (markers db, gebit; 13.1 tests/pos, 4.2).

Real ``gpos-pos`` (gRPC, outbox relay, ``MemoryBus``) on the seeded scratch DB, WWS
and loyalty as stub servers from the Showcase protos, till 99 (store 199). Every event
is parsed back strictly against ``purchase-api-2.50.0.pb`` and must re-serialise to
the very same line.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import grpc
import pytest
from google.protobuf import any_pb2, descriptor_pool, json_format
from google.protobuf.message import Message
from grpc_health.v1 import health_pb2, health_pb2_grpc

from gposdemo.common import grpcutil
from gposdemo.common.bus import MemoryBus, Published
from gposdemo.common.clock import from_ts, real_now
from gposdemo.common.db import Db
from gposdemo.common.descriptors import EVENT_PKG, PURCHASE_SVC, Types
from gposdemo.common.jsonutil import proto_compact
from gposdemo.common.mcputil import AGENT_MAX_TEXT_BYTES
from gposdemo.common.money import from_bdecimal, from_money
from gposdemo.pos import PosApp, create
from gposdemo.pos.receipt import RECEIPT_TYPE

from .conftest import Kasse, Stub, dead_target

pytestmark = [pytest.mark.db, pytest.mark.gebit]

DEMO_DATE = date(2027, 2, 16)
CATEGORY = {
    "PurchaseTransactionCreated": "purchase_transaction",
    "PurchaseTransactionOpened": "purchase_transaction",
    "PositionAdded": "basket",
    "FiscalTransactionAssigned": "fiscal_transaction",
    "ArticlePositionVoided": "basket",
    "LoyaltyMembershipAssigned": "loyalty",
    "PaymentProcessStarted": "payment_session",
    "CashPaymentPositionCreated": "payment_session",
    "PaymentProcessCompleted": "payment_session",
    "PurchaseTransactionInChargingFinancialTransaction": "financial_transaction",
    "PurchaseTransactionInClosing": "purchase_transaction",
    "PurchaseTransactionClosed": "purchase_transaction",
    "PurchaseTransactionInCancellation": "purchase_transaction",
    "PurchaseTransactionCancelled": "purchase_transaction",
}
S1_EVENTS = [
    "PurchaseTransactionCreated", "PurchaseTransactionOpened", "PositionAdded",
    "FiscalTransactionAssigned", "PositionAdded", "PositionAdded", "PaymentProcessStarted",
    "CashPaymentPositionCreated", "CashPaymentPositionCreated", "PaymentProcessCompleted",
    "PurchaseTransactionInChargingFinancialTransaction", "PurchaseTransactionInClosing",
    "PurchaseTransactionClosed"]


def name(event: Published) -> str:
    return event.props["eventType"].removeprefix(f"{EVENT_PKG}.")


def reparse(pool: descriptor_pool.DescriptorPool, event: Published) -> Message:
    """Strict parse of the payload (unknown fields fail) and identical re-serialisation."""
    packed = any_pb2.Any()
    json_format.Parse(event.text(), packed, ignore_unknown_fields=False, descriptor_pool=pool)
    msg = Types(pool).cls(packed.type_url.removeprefix("type.googleapis.com/"))()
    assert packed.Unpack(msg)
    assert proto_compact(packed, pool) == event.text()
    return msg


def ext(event: Published) -> dict[str, str]:
    return {p["key"]: p["typedValue"]["stringValue"] for p in event.json()["extensionProperties"]}


def error_of(call: Any) -> tuple[grpc.StatusCode, str]:
    with pytest.raises(grpc.RpcError) as caught:
        call()
    return caught.value.code(), grpcutil.error_code(caught.value)


def basket_row(db: Db, tx_id: str) -> dict[str, Any]:
    [row] = db.fetch("select status, total, paid, receipt_number, membership_id, last_offset "
                     "from pos.basket where tx_id = %s", (tx_id,))
    return row


@pytest.fixture
def booth_action(wws_stub: Stub) -> Iterator[None]:
    """WWS reports the approved booth action of S1 for the Ente (S1b)."""
    wws_stub.impl.actions["100001"] = ("BOOTH_ACTION", Decimal("7.99"), "PA-270216-0003")
    yield
    wws_stub.impl.actions.clear()


def test_s1_event_sequence(kasse: Kasse, gebit_pool: descriptor_pool.DescriptorPool,
                           pos_db: Db) -> None:
    tx = kasse.new()
    for number in ("100001", "100004", "100010"):
        kasse.scan(tx, number)
    kasse.pay(tx, "15.00")
    events = kasse.events(tx, 13)
    assert [name(e) for e in events] == S1_EVENTS
    assert [int(e.props["offset"]) for e in events] == list(range(1, 14))
    for offset, event in enumerate(events, start=1):
        msg = reparse(gebit_pool, event)
        body = event.json()
        assert body["metadata"]["offset"] == str(offset)
        assert event.topic == (f"gebit/rp/purchase/v2/{CATEGORY[name(event)]}/{name(event)}"
                               f"/DE/999/199/99/{tx}")
        assert event.app_message_id == f"{tx}:{offset}"
        assert event.props == {
            "eventType": f"{EVENT_PKG}.{name(event)}", "purchaseTransactionId": tx,
            "offset": str(offset), "traceId": body["metadata"].get("traceId", ""),
            "location": "Root.DE.999.199.99", "apiVersion": "purchase-2.50.0",
            "source": "gpos-pos"}
        assert msg.purchase_transaction_id == tx
        assert "\n" not in event.text() and event.persistent is False
    fiscal = events[3]
    assert "traceId" not in fiscal.json()["metadata"] and fiscal.props["traceId"] == ""
    assert {e.props["traceId"] for e in events[4:6]} <= set(kasse.traces)
    closed = events[-1].json()
    assert closed["purchaseTransactionStatus"] == "PURCHASE_TRANSACTION_STATUS_CLOSED"
    change, completed = events[8].json(), events[9].json()
    assert change["paymentType"] == "PAYMENT_TYPE_CHANGE"
    assert from_money(change["amount"]) == Decimal("-1.83")
    assert from_money(completed["paymentSessionSums"]["balance"]) == Decimal(0)
    assert len(completed["paymentPositionIds"]) == 2
    row = basket_row(pos_db, tx)
    assert (row["status"], row["total"], row["paid"], row["last_offset"]) == (
        "CLOSED", Decimal("13.17"), Decimal("15.00"), 13)
    payments = pos_db.fetch("select kind, amount from pos.payment where tx_id = %s "
                            "order by amount desc", (tx,))
    assert payments == [{"kind": "CASH", "amount": Decimal("15.00")},
                        {"kind": "CHANGE", "amount": Decimal("-1.83")}]


def test_card_void_cancel_events_reparse_on_their_topics(
        kasse: Kasse, gebit_pool: descriptor_pool.DescriptorPool) -> None:
    """The event kinds S1 does not produce: strict re-parse, offsets and topics (the R1
    subscriptions of 9.6 match loyalty/LoyaltyMembershipAssigned, basket/Article-
    PositionVoided and purchase_transaction/PurchaseTransactionCancelled)."""
    tx = kasse.new()
    kasse.card(tx, "CLUB-1002")
    kasse.scan(tx, "100001")
    added = kasse.events(tx, 4)[3].json()
    kasse.void(tx, added["positionId"])
    kasse.cancel(tx)
    events = kasse.events(tx, 8)
    assert [name(e) for e in events] == [
        "PurchaseTransactionCreated", "LoyaltyMembershipAssigned", "PurchaseTransactionOpened",
        "PositionAdded", "FiscalTransactionAssigned", "ArticlePositionVoided",
        "PurchaseTransactionInCancellation", "PurchaseTransactionCancelled"]
    for offset, event in enumerate(events, start=1):
        reparse(gebit_pool, event)
        assert event.json()["metadata"]["offset"] == str(offset)
        assert event.app_message_id == f"{tx}:{offset}"
        assert event.topic == (f"gebit/rp/purchase/v2/{CATEGORY[name(event)]}/{name(event)}"
                               f"/DE/999/199/99/{tx}")
    assert events[1].topic.startswith("gebit/rp/purchase/v2/loyalty/LoyaltyMembershipAssigned/")
    assert events[5].topic.startswith("gebit/rp/purchase/v2/basket/ArticlePositionVoided/")
    assert events[7].topic.startswith(
        "gebit/rp/purchase/v2/purchase_transaction/PurchaseTransactionCancelled/")


def test_parallel_scans_keep_one_opening_and_gapless_offsets(kasse: Kasse, pos_db: Db) -> None:
    """Races: six scans of one fresh basket at once open it once, assign one fiscal
    transaction and hand out offsets 1..9 and line numbers 1..6 without gaps."""
    tx = kasse.new()
    numbers = ("100001", "100004", "100010", "100012", "100013", "100017")
    with ThreadPoolExecutor(len(numbers)) as workers:
        list(workers.map(lambda number: kasse.scan(tx, number), numbers))
    events = kasse.events(tx, 9)
    assert [name(e) for e in events[:4]] == [
        "PurchaseTransactionCreated", "PurchaseTransactionOpened", "PositionAdded",
        "FiscalTransactionAssigned"]
    assert [name(e) for e in events[4:]] == ["PositionAdded"] * 5
    assert [int(e.json()["metadata"]["offset"]) for e in events] == list(range(1, 10))
    assert sorted(e.json()["articleNumber"] for e in events if name(e) == "PositionAdded") == \
        sorted(numbers)
    assert from_bdecimal(events[-1].json()["pricingInformation"]["totalSum"]) == Decimal("37.14")
    rows = pos_db.fetch("select line_no from pos.basket_line where tx_id = %s order by line_no",
                        (tx,))
    assert [r["line_no"] for r in rows] == [1, 2, 3, 4, 5, 6]
    row = basket_row(pos_db, tx)
    assert (row["status"], row["total"], row["last_offset"]) == ("OPEN", Decimal("37.14"), 9)


def test_timestamps_technical_header_business_body(kasse: Kasse) -> None:
    tx = kasse.new()
    [created] = kasse.events(tx, 1)
    body = created.json()
    header = from_ts(body["header"]["eventTimestamp"])
    assert abs(real_now() - header) < timedelta(seconds=30)
    assert body["metadata"]["creationTimestamp"] == body["header"]["eventTimestamp"]
    business = from_ts(body["createdAt"])
    assert business.date() == DEMO_DATE and body["createdAt"]["offset"] == 60
    assert body["location"] == "Root.DE.999.199.99" and body["currency"] == "EUR"
    assert body["employeeId"] == "booth" and body["cashdrawerId"] == "99"
    assert body["purchaseTransactionStatus"] == "PURCHASE_TRANSACTION_STATUS_CREATED"


def test_closed_event_carries_the_receipt(kasse: Kasse, gebit_pool: descriptor_pool.DescriptorPool,
                                          pos_db: Db) -> None:
    tx = kasse.new()
    kasse.scan(tx, "100012")
    kasse.pay(tx, "14.49")  # exact: no change position
    events = kasse.events(tx, 10)
    assert [name(e) for e in events][-6:] == [
        "PaymentProcessStarted", "CashPaymentPositionCreated", "PaymentProcessCompleted",
        "PurchaseTransactionInChargingFinancialTransaction", "PurchaseTransactionInClosing",
        "PurchaseTransactionClosed"]
    opened, closed = events[1].json(), events[-1].json()
    assert closed["serializedReceiptFormat"] == "PROTOBUF"
    assert closed["serializedReceiptVersion"] == "2.13.0"
    assert from_ts(closed["closedAt"]).date() == DEMO_DATE
    packed = any_pb2.Any()
    packed.ParseFromString(base64.b64decode(closed["serializedReceiptContent"]))
    receipt: Any = Types(gebit_pool).cls(RECEIPT_TYPE)()
    assert packed.Unpack(receipt)
    assert (receipt.receipt_id, receipt.receipt_number, receipt.total.value) == (
        tx, opened["receiptNumber"], "14.49")
    assert receipt.WhichOneof("receipt_status") == "closed_receipt"
    assert opened["receiptNumber"].startswith("19999270216")
    [row] = pos_db.fetch("select receipt_number, api_version from pos.receipt where tx_id = %s",
                         (tx,))
    assert row == {"receipt_number": opened["receiptNumber"], "api_version": "receipt-api-2.13.0"}


def test_s3_card_before_the_first_scan(kasse: Kasse, loyalty_stub: Stub, pos_db: Db) -> None:
    tx = kasse.new()
    kasse.card(tx, "CLUB-1001")
    assert basket_row(pos_db, tx)["status"] == "CREATED"  # the card opens nothing
    kasse.scan(tx, "100012")
    kasse.scan(tx, "100017")
    first = kasse.events(tx, 5)
    assert [(name(e), int(e.props["offset"])) for e in first] == [
        ("PurchaseTransactionCreated", 1), ("LoyaltyMembershipAssigned", 2),
        ("PurchaseTransactionOpened", 3), ("PositionAdded", 4), ("FiscalTransactionAssigned", 5)]
    card = first[1].json()
    assert card["purchaseTransactionStatus"] == "PURCHASE_TRANSACTION_STATUS_CREATED"
    assert card["capturingInformation"] == {"inputMethod": "SCANNER", "inputValue": "CLUB-1001"}
    assert card["membershipPositionId"]
    assert loyalty_stub.impl.resolved[-1]["purchaseTransactionId"] == tx
    assert basket_row(pos_db, tx)["membership_id"] == "M-1001"

    reports_before = len(loyalty_stub.impl.reports)
    kasse.pay(tx, "20.00")
    kasse.events(tx, 13)
    assert len(loyalty_stub.impl.reports) == reports_before + 1  # sent before the reply
    report = loyalty_stub.impl.reports[-1]
    assert report["header"] == {"traceId": kasse.traces[-1],
                                "originator": {"identityId": "gpos-pos"}}
    purchase = report["purchase"]
    assert (purchase["purchaseTransactionId"], purchase["membershipId"],
            purchase["transactionType"], purchase["location"]) == (
        tx, "M-1001", "TRANSACTION_TYPE_SALE", "Root.DE.999.199.99")
    closed_at = from_ts(purchase["closedAt"])
    assert closed_at.date() == DEMO_DATE and purchase["closedAt"]["offset"] == 60  # business
    assert from_money(purchase["total"]) == Decimal("16.98")
    assert [(ln["articleNumber"], ln["category"], ln["itemCount"], from_money(ln["effectiveValue"]),
             ln["effectual"]) for ln in purchase["lines"]] == [
        ("100012", "kaffee_tee", 1, Decimal("14.49"), True),
        ("100017", "molkerei_fruehstueck", 1, Decimal("2.49"), True)]
    assert purchase["receiptNumber"] == basket_row(pos_db, tx)["receipt_number"]


def test_purchase_without_card_is_not_reported(kasse: Kasse, loyalty_stub: Stub) -> None:
    before = len(loyalty_stub.impl.reports)
    tx = kasse.new()
    kasse.scan(tx, "100004")
    kasse.pay(tx, "5.00")
    kasse.events(tx, 10)
    assert len(loyalty_stub.impl.reports) == before


def test_position_added_regular_price(kasse: Kasse, pos_db: Db) -> None:
    tx = kasse.new()
    kasse.scan(tx, "100001")
    added = kasse.events(tx, 3)[2]
    body = added.json()
    assert ext(added) == {"showcase.priceSource": "REGULAR", "showcase.regularPrice": "9.99",
                          "showcase.actionId": "", "showcase.gtin": "2099100000018"}
    assert (body["articleId"], body["articleNumber"], body["itemCount"], body["description"]) == (
        "ID100001", "100001", 1, "GEBIT Ente (Quietscheente gelb)")
    assert body["articlePositionType"] == "ARTICLE_POSITION_TYPE_SALE"
    assert body["capturingInformation"] == {"inputMethod": "SCANNER", "inputType": "EAN13",
                                            "inputValue": "2099100000018"}
    [position] = body["pricingInformation"]["articlePositions"]
    assert position["positionId"] == body["positionId"]
    assert from_bdecimal(position["calculatedPositionPrice"]["basePrice"]) == Decimal("9.99")
    assert body["pricingInformation"]["taxSums"][0]["taxClass"] == "C"


def test_s1b_booth_action_price(kasse: Kasse, booth_action: None, wws_stub: Stub,
                                pos_db: Db) -> None:
    tx = kasse.new()
    kasse.scan(tx, "100001")
    added = kasse.events(tx, 3)[2]
    assert ext(added) == {"showcase.priceSource": "BOOTH_ACTION", "showcase.regularPrice": "9.99",
                          "showcase.actionId": "PA-270216-0003", "showcase.gtin": "2099100000018"}
    position = added.json()["pricingInformation"]["articlePositions"][0]
    assert from_bdecimal(position["calculatedPositionPrice"]["basePrice"]) == Decimal("7.99")
    assert wws_stub.impl.price_calls[-1] == ("100001", "199")
    [row] = pos_db.fetch("select unit_price, regular_price, price_source, action_id, category, "
                         "vat_pct from pos.basket_line where tx_id = %s", (tx,))
    assert row == {"unit_price": Decimal("7.99"), "regular_price": Decimal("9.99"),
                   "price_source": "BOOTH_ACTION", "action_id": "PA-270216-0003",
                   "category": "spielwaren_geschenke", "vat_pct": Decimal("19.00")}


def test_void_and_partial_payment(kasse: Kasse, pos_db: Db) -> None:
    tx = kasse.new()
    kasse.scan(tx, "100001")
    kasse.scan(tx, "100010", count=2)
    milk = kasse.events(tx, 5)[4].json()
    assert from_bdecimal(milk["pricingInformation"]["totalSum"]) == Decimal("12.37")
    kasse.void(tx, milk["positionId"])
    voided = kasse.events(tx, 6)[5]
    assert name(voided) == "ArticlePositionVoided"
    assert voided.json()["positionId"] == milk["positionId"]
    assert from_bdecimal(voided.json()["pricingInformation"]["totalSum"]) == Decimal("9.99")
    assert error_of(lambda: kasse.void(tx, milk["positionId"])) == (
        grpc.StatusCode.FAILED_PRECONDITION, "POS-002")
    kasse.start_payment(tx)
    kasse.cash(tx, "5.00")
    partial = kasse.events(tx, 8)[7].json()
    assert from_money(partial["paymentSessionSums"]["balance"]) == Decimal("4.99")
    assert basket_row(pos_db, tx)["status"] == "IN_PAYMENT"
    kasse.cash(tx, "4.99")
    events = kasse.events(tx, 13)
    assert [name(e) for e in events[8:]] == [
        "CashPaymentPositionCreated", "PaymentProcessCompleted",
        "PurchaseTransactionInChargingFinancialTransaction", "PurchaseTransactionInClosing",
        "PurchaseTransactionClosed"]
    row = basket_row(pos_db, tx)
    assert (row["status"], row["total"], row["paid"]) == ("CLOSED", Decimal("9.99"),
                                                          Decimal("9.99"))


def test_cancel(kasse: Kasse, pos_db: Db) -> None:
    tx = kasse.new()
    kasse.scan(tx, "100013")
    kasse.cancel(tx)
    events = kasse.events(tx, 6)
    assert [name(e) for e in events[4:]] == ["PurchaseTransactionInCancellation",
                                             "PurchaseTransactionCancelled"]
    cancelling, cancelled = events[4].json(), events[5].json()
    assert cancelling["cancellationReason"] == "Kunde verzichtet"
    assert cancelling["cancellationReasonCode"] == "CUSTOMER"
    assert cancelled["purchaseTransactionStatus"] == "PURCHASE_TRANSACTION_STATUS_CANCELLED"
    assert cancelled["serializedReceiptContent"]
    assert basket_row(pos_db, tx)["status"] == "CANCELLED"
    assert error_of(lambda: kasse.scan(tx, "100001")) == (grpc.StatusCode.FAILED_PRECONDITION,
                                                           "POS-002")


def test_new_transaction_resets_the_open_basket_of_the_till(kasse: Kasse, pos_db: Db,
                                                            pos_bus: MemoryBus) -> None:
    first = kasse.new()
    kasse.scan(first, "100004")
    kasse.events(first, 4)
    second = kasse.new()
    kasse.events(second, 1)
    assert basket_row(pos_db, first)["status"] == "RESET"
    assert basket_row(pos_db, second)["status"] == "CREATED"
    assert len([m for m in pos_bus.published
                if m.props.get("purchaseTransactionId") == first]) == 4  # no reset event


def test_error_codes(kasse: Kasse, pos_client: grpcutil.Client) -> None:
    unknown = "00000000-0000-4000-8000-000000000000"
    assert error_of(lambda: kasse.scan(unknown, "100001")) == (grpc.StatusCode.NOT_FOUND,
                                                               "POS-001")
    tx = kasse.new()
    assert error_of(lambda: kasse.call("AddArticle", {
        "purchaseTransactionId": tx, "articleId": "ID999999"})) == (grpc.StatusCode.NOT_FOUND,
                                                                    "POS-003")
    assert error_of(lambda: kasse.call("AddArticle", {
        "purchaseTransactionId": tx, "articleId": "ID100001", "itemCount": -1})) == (
        grpc.StatusCode.INVALID_ARGUMENT, "POS-005")
    assert error_of(lambda: kasse.card(tx, "CLUB-0000")) == (grpc.StatusCode.INVALID_ARGUMENT,
                                                             "LOY-001")
    assert error_of(lambda: kasse.start_payment(tx)) == (grpc.StatusCode.FAILED_PRECONDITION,
                                                         "POS-002")  # CREATED, no line
    kasse.scan(tx, "100001")
    kasse.start_payment(tx)
    assert error_of(lambda: kasse.card(tx, "CLUB-1001")) == (
        grpc.StatusCode.FAILED_PRECONDITION, "POS-002")
    assert error_of(lambda: kasse.cash(tx, "0.00")) == (grpc.StatusCode.INVALID_ARGUMENT,
                                                        "POS-005")
    assert error_of(lambda: kasse.call("CreatePurchaseTransaction", {
        "location": "Root.DE.999.101.07"})) == (grpc.StatusCode.INVALID_ARGUMENT, "POS-005")
    with pytest.raises(grpc.RpcError) as caught:
        pos_client.call("GetPurchaseTransaction", {"purchaseTransactionId": tx})
    assert caught.value.code() == grpc.StatusCode.UNIMPLEMENTED
    with pytest.raises(grpc.RpcError) as rejected:
        kasse.scan(unknown, "100001")
    assert rejected.value.details().startswith("POS-001: ")


def test_unreachable_wws_is_pos_004(make_pos_settings: Any, pos_db: Db,
                                    gebit_pool: descriptor_pool.DescriptorPool) -> None:
    app = create(make_pos_settings(WWS_GRPC=dead_target()), MemoryBus(), pos_db)
    app.start()
    client = grpcutil.Client(gebit_pool, PURCHASE_SVC, f"localhost:{app.grpc_port}")
    try:
        kasse = Kasse(client, MemoryBus(), "Root.DE.999.199.99")
        tx = kasse.new()
        assert error_of(lambda: kasse.scan(tx, "100001")) == (grpc.StatusCode.UNAVAILABLE,
                                                              "POS-004")
        row = basket_row(pos_db, tx)
        assert (row["status"], row["last_offset"]) == ("CREATED", 1)
    finally:
        client.close()
        app.stop()


def test_get_transaction_of_a_long_receipt(kasse: Kasse, pos_app: PosApp) -> None:
    tx = kasse.new()
    numbers = ("100001", "100002", "100004", "100008", "100009", "100010", "100011",
               "100012", "100013")
    for number in numbers:
        kasse.scan(tx, number)
    view = pos_app.service.get_transaction(tx, "GR-270216-0009")
    assert len(view["lines"]) == 8 and view["more"] == 1
    assert [ln["article_number"] for ln in view["lines"]] == list(numbers[:8])
    assert len(json.dumps(view, separators=(",", ":"), ensure_ascii=False).encode()) <= \
        AGENT_MAX_TEXT_BYTES
    assert view["till"] == "99" and view["status"] == "OPEN"


def test_admin_reset_and_till_state(kasse: Kasse, pos_app: PosApp, pos_db: Db,
                                    pos_bus: MemoryBus) -> None:
    tx = kasse.new()
    kasse.scan(tx, "100001")
    events = kasse.events(tx, 4)
    state = pos_app.service.till_state("99")
    assert state["store"] == "199" and state["open_tx"]["tx_id"] == tx
    assert state["open_tx"]["offset"] == 4
    assert state["open_tx"]["lines"][0]["position_id"] == events[2].json()["positionId"]
    published = len(pos_bus.published)
    assert pos_app.service.admin_reset()["reset"] >= 1
    assert basket_row(pos_db, tx)["status"] == "RESET"
    assert pos_app.service.till_state("99")["open_tx"] is None
    assert len(pos_bus.published) == published  # the reset reaches nobody
    assert error_of(lambda: kasse.scan(tx, "100004")) == (grpc.StatusCode.FAILED_PRECONDITION,
                                                           "POS-002")


def test_grpc_health_serving(pos_app: PosApp) -> None:
    with grpc.insecure_channel(f"localhost:{pos_app.grpc_port}") as channel:
        stub = health_pb2_grpc.HealthStub(channel)
        reply = stub.Check(health_pb2.HealthCheckRequest(service=PURCHASE_SVC), timeout=5)
    assert reply.status == health_pb2.HealthCheckResponse.SERVING
