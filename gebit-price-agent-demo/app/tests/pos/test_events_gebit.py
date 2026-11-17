"""Event, receipt and RPC registration against the runtime GEBIT pool (marker gebit, no DB;
4.2)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from google.protobuf import descriptor_pool, json_format

from gposdemo.common import grpcutil
from gposdemo.common.config import Settings
from gposdemo.common.descriptors import PURCHASE_SVC, Types, load_pool
from gposdemo.pos.events import EventFactory, status_enum, string_properties
from gposdemo.pos.pricing import PricedLine, pricing_information
from gposdemo.pos.receipt import ReceiptBuilder, SerializedReceipt
from gposdemo.pos.sim import Simulator

from .conftest import ARTICLES

pytestmark = pytest.mark.gebit

TX = "5b1f0c2e-8d1e-4a43-9a51-0c7a2f0e1b11"
AT = datetime(2026, 11, 11, 13, 20, 1, 412000, tzinfo=UTC)
CATEGORIES = {
    "PurchaseTransactionCreated": "purchase_transaction", "PositionAdded": "basket",
    "FiscalTransactionAssigned": "fiscal_transaction", "LoyaltyMembershipAssigned": "loyalty",
    "PaymentProcessStarted": "payment_session",
    "PurchaseTransactionInChargingFinancialTransaction": "financial_transaction",
}


@pytest.fixture(scope="module")
def factory(gebit_pool: descriptor_pool.DescriptorPool) -> EventFactory:
    return EventFactory(gebit_pool)


def test_all_106_rpcs_registered_only_the_4_2_subset_implemented(
        gebit_pool: descriptor_pool.DescriptorPool) -> None:
    """4.2: every RPC of the service is registered; only these seven are served, the
    others (GetPurchaseTransaction included) answer UNIMPLEMENTED."""
    _, implemented = grpcutil.service_handler(gebit_pool, PURCHASE_SVC, Simulator)
    assert len(gebit_pool.FindServiceByName(PURCHASE_SVC).methods) == 106
    assert sorted(implemented) == [
        "AddArticle", "AssignLoyaltyMembership", "CancelPurchaseTransaction",
        "CreateCashPayment", "CreatePurchaseTransaction", "StartPaymentProcess",
        "VoidArticlePosition"]


@pytest.mark.parametrize(("event", "category"), sorted(CATEGORIES.items()))
def test_topic_category_from_the_descriptor(factory: EventFactory, event: str,
                                           category: str) -> None:
    assert factory.category(event) == category


def test_position_added_matches_the_4_2_example(factory: EventFactory) -> None:
    ente = ARTICLES["100001"]
    body = {"positionId": "0d4c0000-0000-4000-8000-000000000001",
            "articlePositionType": "ARTICLE_POSITION_TYPE_SALE", "articleId": "ID100001",
            "articleNumber": "100001", "itemCount": 1, "description": ente["name"],
            "capturingInformation": {"inputMethod": "SCANNER", "inputType": "EAN13",
                                     "inputValue": ente["gtin"]},
            "pricingInformation": pricing_information(
                [PricedLine("0d4c0000-0000-4000-8000-000000000001", Decimal("9.99"), 1,
                            Decimal(19))]),
            "purchaseTransactionStatus": status_enum("OPEN"),
            "extensionProperties": string_properties({"showcase.priceSource": "REGULAR",
                                                      "showcase.regularPrice": "9.99"})}
    event = factory.build("PositionAdded", body, tx_id=TX, location="Root.DE.999.101.01",
                          offset=3, trace_id="kasse-01-7f3a", now=AT)
    assert event.topic == f"gebit/rp/purchase/v2/basket/PositionAdded/DE/999/101/01/{TX}"
    assert event.payload.startswith(
        '{"@type":"type.googleapis.com/de.gebit.rp.purchase.purchase.v2.event.PositionAdded",'
        '"header":{"eventTimestamp":{"seconds":"1794403201","nanos":412000000}},'
        '"metadata":{"offset":"3","creationTimestamp":{"seconds":"1794403201",'
        '"nanos":412000000},"traceId":"kasse-01-7f3a"},'
        f'"purchaseTransactionId":"{TX}"')
    assert '"description":"GEBIT Ente (Quietscheente gelb)"' in event.payload
    assert ('"extensionProperties":[{"key":"showcase.priceSource","typedValue":'
            '{"stringValue":"REGULAR"}},{"key":"showcase.regularPrice","typedValue":'
            '{"stringValue":"9.99"}}]') in event.payload
    assert '"totalSum":{"scale":2,"intVal":"999"}' in event.payload
    assert event.props["offset"] == "3" and event.event_type.endswith(".PositionAdded")


def test_empty_string_property_is_kept(factory: EventFactory) -> None:
    event = factory.build("PositionAdded", {
        "extensionProperties": string_properties({"showcase.actionId": ""})},
        tx_id=TX, location="Root.DE.999.199.99", offset=4, trace_id="")
    assert '{"key":"showcase.actionId","typedValue":{"stringValue":""}}' in event.payload
    assert '"traceId"' not in event.payload and event.props["traceId"] == ""


def test_unknown_field_fails_strictly(factory: EventFactory) -> None:
    with pytest.raises(json_format.ParseError):
        factory.build("PurchaseTransactionCreated", {"locationId": "x"}, tx_id=TX,
                      location="Root.DE.999.101.01", offset=1, trace_id="")


def test_umlauts_stay_raw(factory: EventFactory) -> None:
    event = factory.build("PositionAdded", {"description": "Espresso Bohnen kräftig"},
                          tx_id=TX, location="Root.DE.999.101.01", offset=4, trace_id="t")
    assert "kräftig" in event.payload and "\\u" not in event.payload


def test_receipt_only_with_the_receipt_descriptor(gebit_pool: descriptor_pool.DescriptorPool,
                                                  settings: Settings) -> None:
    full = ReceiptBuilder(Types(gebit_pool))
    built = full.build(tx_id=TX, receipt_number="10101270216000042",
                       location="Root.DE.999.101.01", total=Decimal("13.17"), closed=True)
    assert full.available and built.api_version == "receipt-api-2.13.0" and built.content_b64
    purchase_only = load_pool([p for p in settings.gebit_descriptor_sets if "purchase-api" in p])
    bare = ReceiptBuilder(Types(purchase_only))
    assert not bare.available
    assert bare.build(tx_id=TX, receipt_number="1", location="Root.DE.999.101.01",
                      total=Decimal(1), closed=True) == SerializedReceipt("none", "")
