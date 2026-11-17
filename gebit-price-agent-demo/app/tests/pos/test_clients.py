"""WWS and loyalty clients against stub gRPC servers from the Showcase protos (no marker)."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import grpc
import pytest
from google.protobuf import descriptor_pool

from gposdemo.pos.clients import ArticleInfo, EffectivePrice, LoyaltyClient, WwsClient
from gposdemo.pos.errors import PosError

from .conftest import Stub, dead_target


@pytest.fixture
def wws(showcase_pool: descriptor_pool.DescriptorPool, wws_stub: Stub) -> Iterator[WwsClient]:
    client = WwsClient(showcase_pool, wws_stub.target)
    yield client
    client.close()
    wws_stub.impl.actions.clear()


@pytest.fixture
def loyalty(showcase_pool: descriptor_pool.DescriptorPool, loyalty_stub: Stub
            ) -> Iterator[LoyaltyClient]:
    client = LoyaltyClient(showcase_pool, loyalty_stub.target)
    yield client
    client.close()


def test_article_master_data(wws: WwsClient) -> None:
    assert wws.article("199", "ID100012", "t-1") == ArticleInfo(
        article_number="100012", article_id="ID100012", name="Espresso Bohnen kräftig",
        gtin="2099100000124", category="kaffee_tee", vat_pct=Decimal("7.00"))


def test_regular_and_booth_price(wws: WwsClient, wws_stub: Stub) -> None:
    assert wws.effective_price("101", "100001", "t-2") == EffectivePrice(
        price=Decimal("9.99"), regular_price=Decimal("9.99"), source="REGULAR", action_id="")
    wws_stub.impl.actions["100001"] = ("BOOTH_ACTION", Decimal("7.99"), "PA-270216-0003")
    assert wws.effective_price("101", "100001", "t-3") == EffectivePrice(
        price=Decimal("7.99"), regular_price=Decimal("9.99"), source="BOOTH_ACTION",
        action_id="PA-270216-0003")
    assert wws_stub.impl.price_calls[-1] == ("100001", "101")


def test_unknown_article_is_pos_003(wws: WwsClient) -> None:
    with pytest.raises(PosError) as caught:
        wws.article("101", "ID999999", "t-4")
    assert (caught.value.code, caught.value.status) == ("POS-003", grpc.StatusCode.NOT_FOUND)


def test_unusable_price_is_pos_004(wws: WwsClient, wws_stub: Stub) -> None:
    wws_stub.impl.actions["100004"] = ("UNSPECIFIED", Decimal("1.99"), "")
    with pytest.raises(PosError) as caught:
        wws.effective_price("101", "100004", "t-5")
    assert caught.value.code == "POS-004"


def test_unreachable_wws_is_pos_004(showcase_pool: descriptor_pool.DescriptorPool) -> None:
    client = WwsClient(showcase_pool, dead_target(), timeout=1.0)
    try:
        with pytest.raises(PosError) as caught:
            client.article("101", "ID100001", "t-6")
    finally:
        client.close()
    assert (caught.value.code, caught.value.status) == ("POS-004", grpc.StatusCode.UNAVAILABLE)
    assert caught.value.text.startswith("WWS nicht erreichbar")


def test_active_card_resolves_to_the_membership(loyalty: LoyaltyClient,
                                                loyalty_stub: Stub) -> None:
    capturing = {"inputMethod": "SCANNER", "inputValue": "CLUB-1001"}
    assert loyalty.resolve("CLUB-1001", "tx-1", "Root.DE.999.101.01", capturing, "t-7") == "M-1001"
    sent = loyalty_stub.impl.resolved[-1]
    assert sent == {"traceId": "t-7", "membershipIdentificationValue": "CLUB-1001",
                    "purchaseTransactionId": "tx-1", "location": "Root.DE.999.101.01",
                    "capturingInformation": capturing}


@pytest.mark.parametrize("card", ["CLUB-0000", "CLUB-SPERRE"])
def test_unknown_or_blocked_card_is_loy_001(loyalty: LoyaltyClient, card: str) -> None:
    with pytest.raises(PosError) as caught:
        loyalty.resolve(card, "tx-2", "Root.DE.999.101.01", None, "t-8")
    assert (caught.value.code, caught.value.status) == ("LOY-001",
                                                        grpc.StatusCode.INVALID_ARGUMENT)


def test_loyalty_error_code_is_passed_through(loyalty: LoyaltyClient) -> None:
    with pytest.raises(PosError) as caught:
        loyalty.resolve("CLUB-FEHLER", "tx-3", "Root.DE.999.101.01", None, "t-9")
    err = caught.value
    assert (err.code, err.status, err.text) == ("LOY-002", grpc.StatusCode.NOT_FOUND,
                                                "Mitglied unbekannt")


def test_unreachable_loyalty_is_pos_004(showcase_pool: descriptor_pool.DescriptorPool) -> None:
    client = LoyaltyClient(showcase_pool, dead_target(), timeout=1.0)
    try:
        with pytest.raises(PosError) as caught:
            client.resolve("CLUB-1001", "tx-4", "Root.DE.999.101.01", None, "t-10")
        assert caught.value.code == "POS-004"
        assert client.report_purchase({"purchaseTransactionId": "tx-4"}, "t-11") is False
    finally:
        client.close()


def test_report_purchase_never_raises(showcase_pool: descriptor_pool.DescriptorPool,
                                      loyalty_stub: Stub) -> None:
    """4.4 best effort: the basket is CLOSED already, so no failure may reach the till."""
    client = LoyaltyClient(showcase_pool, loyalty_stub.target)
    before = len(loyalty_stub.impl.reports)
    assert client.report_purchase({"purchaseTransactionId": "tx-6", "noSuchField": 1},
                                  "t-13") is False  # body the proto rejects
    client.close()
    assert client.report_purchase({"purchaseTransactionId": "tx-7"}, "t-14") is False  # closed
    assert len(loyalty_stub.impl.reports) == before


def test_report_purchase_header_and_body(loyalty: LoyaltyClient, loyalty_stub: Stub) -> None:
    purchase = {"purchaseTransactionId": "tx-5", "receiptNumber": "19999270216000001",
                "location": "Root.DE.999.199.99", "transactionType": "TRANSACTION_TYPE_SALE",
                "membershipId": "M-1001"}
    assert loyalty.report_purchase(purchase, "t-12") is True
    report = loyalty_stub.impl.reports[-1]
    assert report["header"] == {"traceId": "t-12", "originator": {"identityId": "gpos-pos"}}
    assert report["purchase"] == purchase
