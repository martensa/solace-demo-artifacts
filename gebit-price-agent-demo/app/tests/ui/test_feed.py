"""Bus -> SSE conversion (10.2), open receipts and SSE wire format."""

from __future__ import annotations

import json
from typing import Any

import pytest

from gposdemo.common import topics
from gposdemo.common.config import Settings
from gposdemo.ui import feed
from gposdemo.ui.counters import Counters
from gposdemo.ui.refdata import RefData, load

from .conftest import gebit_payload

TX = "5b1f0c2e-8d1e-4a43-9a51-0c7a2f0e1b11"
BOOTH = ("101", "01")
EVENT_TYPE = "type.googleapis.com/de.gebit.rp.purchase.purchase.v2.event."


def gebit_topic(category: str, event: str, store: str = "101", till: str = "01") -> str:
    return topics.gebit_event(category, event, "DE", "999", store, till, TX)


def position_added(offset: int = 3, price_source: str = "REGULAR", base: str = "999",
                   position_id: str = "0d4c-1") -> dict[str, Any]:
    """PositionAdded as our simulator writes it (4.2 example, proto3 JSON)."""
    return {
        "@type": EVENT_TYPE + "PositionAdded",
        "header": {"eventTimestamp": {"seconds": "1794393601", "nanos": 412000000}},
        "metadata": {"offset": str(offset), "creationTimestamp": {"seconds": "1794393601"},
                     "traceId": "kasse-01-7f3a"},
        "purchaseTransactionId": TX, "positionId": position_id,
        "articlePositionType": "ARTICLE_POSITION_TYPE_SALE", "articleId": "ID100001",
        "articleNumber": "100001", "itemCount": 1,
        "description": "GEBIT Ente (Quietscheente gelb)",
        "capturingInformation": {"inputMethod": "SCANNER", "inputType": "EAN13",
                                 "inputValue": "2099100000018"},
        "pricingInformation": {
            "totalSum": {"scale": 2, "intVal": "1198"},
            "articlePositions": [
                {"positionId": "other", "calculatedPositionPrice": {
                    "basePrice": {"scale": 2, "intVal": "199"}}},
                {"positionId": position_id, "calculatedPositionPrice": {
                    "basePrice": {"scale": 2, "intVal": base}}}]},
        "purchaseTransactionStatus": "PURCHASE_TRANSACTION_STATUS_OPEN",
        "extensionProperties": [
            {"key": "showcase.priceSource", "typedValue": {"stringValue": price_source}},
            {"key": "showcase.regularPrice", "typedValue": {"stringValue": "9.99"}},
            {"key": "showcase.actionId", "typedValue": {"stringValue": ""}},
            {"key": "showcase.gtin", "typedValue": {"stringValue": "2099100000018"}}]}


PRICE_APPLIED = {
    "@type": "type.googleapis.com/de.showcase.wws.v1.event.PriceChangeApplied",
    "header": {"eventTimestamp": {"seconds": "1794393700", "nanos": 120000000}},
    "metadata": {"offset": "2", "creationTimestamp": {"seconds": "1794393700"},
                 "traceId": "GP-270216-0003"},
    "actionId": "PA-270216-0003", "articleNumber": "100001",
    "articleName": "GEBIT Ente (Quietscheente gelb)", "storeId": "101",
    "kind": "PRICE_ACTION_KIND_BOOTH",
    "regularPrice": {"currency": "EUR", "amount": {"scale": 2, "intVal": "999"}},
    "actionPrice": {"currency": "EUR", "amount": {"scale": 2, "intVal": "799"}},
    "pctShown": 20, "ref30": {"currency": "EUR", "amount": {"scale": 2, "intVal": "999"}},
    "validFrom": {"seconds": "1802732400", "offset": 60},
    "validTo": {"seconds": "1803409200", "offset": 60},
    "proposalId": "GP-270216-0003", "reasonCode": "REASON_CODE_SLOW_SELLER",
    "originator": {"identityId": "gpos-engine"}, "approver": {"identityId": "role:marktleitung"}}


@pytest.fixture(scope="module")
def data(settings: Settings) -> RefData:
    return load(settings.data_dir)


@pytest.fixture
def hub(settings: Settings, data: RefData) -> feed.Hub:
    return feed.Hub(settings.booth_location, settings.tz, data, Counters(*BOOTH))


def raw(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


# --------------------------------------------------------------------- classify
@pytest.mark.parametrize("topic, kind", [
    (gebit_topic("basket", "PositionAdded"), "pos_event"),
    ("showcase/wws/v1/price/PriceChangeApplied/DE/999/101/100001", "price_change"),
    ("gpos/v1/insight/scan/101/01/" + TX, "insight"),
    ("gpos/v1/review/state/prepared/101/01/GR-270216-0007", "review"),
    ("gpos/v1/proposal/ready/101/01/GP-270216-0003", "proposal"),
    ("gpos/v1/telemetry/tool/wws/get_sales_performance", "tool_call"),
    ("gpos/v1/sam/done/r3", "sam_run"),
    ("gpos/v1/sam/error/p4", "sam_run"),
    ("gpos/v1/review/request/101/01/GR-270216-0007", None),
    ("gpos/v1/approval/request/101/01/GP-270216-0003", None),
])
def test_classify(topic: str, kind: str | None) -> None:
    assert feed.classify(topic) == kind


# --------------------------------------------------------------------- pos_event
def test_pos_event_position_added_booth() -> None:
    data = feed.pos_event(gebit_topic("basket", "PositionAdded"), position_added(), BOOTH)
    assert data == {
        "event": "PositionAdded", "tx_id": TX, "store": "101", "till": "01", "offset": 3,
        "position_id": "0d4c-1", "article_number": "100001",
        "description": "GEBIT Ente (Quietscheente gelb)", "item_count": 1, "price": "9,99",
        "price_source": "REGULAR", "regular_price": "9,99", "action_id": "", "total": "11,98",
        "status": "OPEN", "to_sam": True, "receipt_number": ""}


def test_pos_event_booth_action_price() -> None:
    data = feed.pos_event(gebit_topic("basket", "PositionAdded"),
                          position_added(price_source="BOOTH_ACTION", base="799"), BOOTH)
    assert (data["price"], data["price_source"], data["regular_price"]) == (
        "7,99", "BOOTH_ACTION", "9,99")


@pytest.mark.parametrize("category, event, store, till, to_sam", [
    ("basket", "PositionAdded", "101", "01", True),
    ("basket", "ArticlePositionVoided", "101", "01", True),
    ("loyalty", "LoyaltyMembershipAssigned", "101", "01", True),
    ("purchase_transaction", "PurchaseTransactionClosed", "101", "01", True),
    ("purchase_transaction", "PurchaseTransactionCancelled", "101", "01", True),
    ("fiscal_transaction", "FiscalTransactionAssigned", "101", "01", False),
    ("purchase_transaction", "PurchaseTransactionOpened", "101", "01", False),
    ("basket", "PositionAdded", "199", "99", False),
    ("basket", "PositionAdded", "199", "98", False),
])
def test_to_sam_only_for_the_five_r1_kinds_of_the_booth(category: str, event: str, store: str,
                                                         till: str, to_sam: bool) -> None:
    payload = {"purchaseTransactionId": TX, "metadata": {"offset": "1"}}
    data = feed.pos_event(gebit_topic(category, event, store, till), payload, BOOTH)
    assert data["to_sam"] is to_sam
    assert (data["event"], data["store"], data["till"]) == (event, store, till)
    assert data["total"] == "" and data["price"] == ""


def test_pos_event_closed_status_and_zero_total() -> None:
    payload = {"purchaseTransactionId": TX, "metadata": {"offset": "13"},
               "purchaseTransactionStatus": "PURCHASE_TRANSACTION_STATUS_CLOSED",
               "pricingInformation": {"totalSum": {"scale": 2}}}
    data = feed.pos_event(gebit_topic("purchase_transaction", "PurchaseTransactionClosed"),
                          payload, BOOTH)
    assert (data["status"], data["offset"], data["total"]) == ("CLOSED", 13, "0,00")


def test_loyalty_event_gets_card_persona_and_consent(hub: feed.Hub) -> None:
    payload = gebit_payload("LoyaltyMembershipAssigned", purchaseTransactionId=TX,
                            metadata={"offset": "2"},
                            capturingInformation={"inputValue": "CLUB-1003"})
    kind, data = hub.convert(gebit_topic("loyalty", "LoyaltyMembershipAssigned"), raw(payload))
    assert kind == "pos_event"
    assert (data["card"], data["persona"], data["consent_profiling"]) == (
        "CLUB-1003", "Feierabend", False)


def test_loyalty_event_without_card_uses_the_facade_card(hub: feed.Hub) -> None:
    hub.note_card("01", TX, "CLUB-1001")
    payload = gebit_payload("LoyaltyMembershipAssigned", purchaseTransactionId=TX,
                            metadata={"offset": "2"})
    _, data = hub.convert(gebit_topic("loyalty", "LoyaltyMembershipAssigned"), raw(payload))
    assert (data["card"], data["persona"], data["consent_profiling"]) == (
        "CLUB-1001", "Kaffeepause", True)


# --------------------------------------------------------------------- price_change
def test_price_change_applied_from_the_7_2_example(settings: Settings) -> None:
    topic = "showcase/wws/v1/price/PriceChangeApplied/DE/999/101/100001"
    assert feed.price_change(topic, PRICE_APPLIED, settings.tz) == {
        "event": "PriceChangeApplied", "store": "101", "action_id": "PA-270216-0003",
        "article_number": "100001", "article_name": "GEBIT Ente (Quietscheente gelb)",
        "old": "9,99", "new": "7,99", "pct_shown": 20, "valid_to_label": "Di 23.02. 20:00",
        "proposal_id": "GP-270216-0003", "topic": topic}


def test_price_change_ended(settings: Settings) -> None:
    topic = "showcase/wws/v1/price/PriceChangeEnded/DE/999/101/100001"
    payload = {"actionId": "PA-270216-0003", "articleNumber": "100001", "storeId": "101",
               "reason": "reset", "endedAt": {"seconds": "1802769300", "offset": 60}}
    data = feed.price_change(topic, payload, settings.tz)
    assert (data["event"], data["old"], data["new"], data["valid_to_label"]) == (
        "PriceChangeEnded", "", "", "")


# --------------------------------------------------------------------- sam_run
@pytest.mark.parametrize("payload", [
    {"review_id": "GR-1", "decision": "propose", "proposal_id": "GP-1"},
    {"result": {"review_id": "GR-1", "decision": "propose", "proposal_id": "GP-1"}},
    {"output": {"review_id": "GR-1", "decision": "propose", "proposal_id": "GP-1"}},
    {"result": json.dumps({"review_id": "GR-1", "decision": "propose", "proposal_id": "GP-1"})},
])
def test_sam_done_is_read_tolerantly(payload: dict[str, Any]) -> None:
    data = feed.sam_run("gpos/v1/sam/done/r3", payload)
    assert data == {"rule": "r3", "workflow": "gpos-basket-review", "ok": True, "label": "ok",
                    "output": {"review_id": "GR-1", "decision": "propose",
                               "proposal_id": "GP-1"}}


DENY_ERROR = "Agent reported error: Price approval was denied by store manager"


@pytest.mark.parametrize("rule, error, label", [
    ("r4", "Tool approval timed out after 2 minutes", "Abgelaufen"),
    ("p4", "Tool approval timed out after 2 minutes", "Abgelaufen"),
    ("r4", DENY_ERROR, "Abgelehnt"),
    ("p4", DENY_ERROR, "Abgelehnt"),
    ("r4", "Tool call was denied by the user", "Abgelehnt"),
    ("r4", "Freigabe abgelehnt", "Abgelehnt"),
    ("r4", "Permission denied: connector scope missing", "Fehler"),
    ("r4", "agent declined to call apply_price", "Fehler"),
    ("r4", "approval timed out, treated as denied", "Abgelaufen"),
    ("r4", "workflow was redeployed or stopped during execution", "Fehler"),
])
def test_r4_and_p4_errors_carry_a_provisional_label(rule: str, error: str, label: str) -> None:
    """10.2: the label of an R4/P4 error is provisional (from the text); the monitor
    replaces it by the engine outcome (10.4)."""
    data = feed.sam_run(f"gpos/v1/sam/error/{rule}", {"error": error})
    assert (data["ok"], data["label"], data["error"]) == (False, label, error)
    assert data["provisional"] is True
    assert data["workflow"] == "gpos-price-approval"


@pytest.mark.parametrize("rule, error", [
    ("r3", "agent node timed out"),
    ("r3", DENY_ERROR),
    ("r1", "boom"),
])
def test_other_errors_stay_fehler_without_provisional(rule: str, error: str) -> None:
    data = feed.sam_run(f"gpos/v1/sam/error/{rule}", {"error": error})
    assert (data["ok"], data["label"], data["error"]) == (False, "Fehler", error)
    assert "provisional" not in data
    assert data["workflow"] == {"r1": "gpos-pos-event", "r3": "gpos-basket-review"}[rule]


def test_done_runs_are_never_provisional() -> None:
    data = feed.sam_run("gpos/v1/sam/done/r4", {"status": "applied", "proposal_id": "GP-1"})
    assert (data["ok"], data["label"]) == (True, "ok") and "provisional" not in data


@pytest.mark.parametrize("payload, text", [
    ("plain text error", "plain text error"),
    ({"error": {"message": "Tool approval timed out"}}, "Tool approval timed out"),
    ({"result": {"errorMessage": "denied"}}, "denied"),
    ({"error": "Workflow failed", "detail": "Tool call was denied by the user"},
     "Tool call was denied by the user"),
    ({"status": "failed", "code": 7}, '{"status":"failed","code":7}'),
])
def test_sam_error_text_variants(payload: Any, text: str) -> None:
    assert feed.sam_error_text(payload) == text


@pytest.mark.parametrize("payload", [
    {"error": "Workflow failed", "details": "Tool approval timed out after 2 minutes"},
    {"error": {"code": "NODE_FAILED", "cause": {"message": "Tool approval timed out"}}},
    {"result": {"status": "failed", "errors": ["node approve", "Tool approval timed out"]}},
])
def test_r4_timeout_is_found_in_any_error_shape(payload: dict[str, Any]) -> None:
    """A-22: the errorOutput shape is unverified; "timed out" decides „Abgelaufen“ here and
    the engine classifies the forwarded text itself (11.5/11.8), so it must carry it."""
    data = feed.sam_run("gpos/v1/sam/error/r4", payload)
    assert data["label"] == "Abgelaufen" and data["provisional"] is True
    assert "timed out" in data["error"]


@pytest.mark.parametrize("payload", [
    {"error": "Workflow failed", "details": DENY_ERROR},
    {"error": {"code": "NODE_FAILED", "cause": {"message": DENY_ERROR}}},
    {"result": {"status": "failed", "errors": ["node approve", DENY_ERROR]}},
    DENY_ERROR,
])
def test_r4_denial_is_found_in_any_error_shape(payload: Any) -> None:
    """The denial text (with its approval context) is what the BFF forwards to the
    engine, which decides ``rejected`` only inside the approval window (11.5 R6)."""
    data = feed.sam_run("gpos/v1/sam/error/r4", payload)
    assert (data["label"], data["provisional"]) == ("Abgelehnt", True)
    assert data["error"] == DENY_ERROR


def test_timeout_text_wins_over_a_denial_text() -> None:
    payload = {"error": DENY_ERROR, "details": "Tool approval timed out after 2 minutes"}
    data = feed.sam_run("gpos/v1/sam/error/r4", payload)
    assert data["label"] == "Abgelaufen"
    assert data["error"] == "Tool approval timed out after 2 minutes"


def test_technical_text_anywhere_makes_the_label_fehler() -> None:
    """All texts count for the label: a technical word next to the denial wins."""
    payload = {"error": DENY_ERROR, "details": "connection refused by server"}
    data = feed.sam_run("gpos/v1/sam/error/r4", payload)
    assert data["label"] == "Fehler" and data["provisional"] is True
    assert data["error"] == DENY_ERROR


@pytest.mark.parametrize("payload", [None, "", {}, {"code": 7}])
def test_empty_r4_error_is_fehler(payload: Any) -> None:
    data = feed.sam_run("gpos/v1/sam/error/r4", payload)
    assert (data["label"], data["provisional"]) == ("Fehler", True)


def test_duplicate_request_signal_keeps_state() -> None:
    payload = {"schema_version": "1", "type": "proposal", "state": "approved",
               "proposal_id": "GP-1", "store": "101", "till": "01"}
    data = feed.proposal_event("gpos/v1/proposal/duplicate_request/101/01/GP-1", payload)
    assert data["state"] == "approved" and data["signal"] == "duplicate_request"
    ready = feed.proposal_event("gpos/v1/proposal/ready/101/01/GP-1", payload)
    assert "signal" not in ready


# --------------------------------------------------------------------- receipts
def test_hub_builds_the_open_receipt_from_events(hub: feed.Hub) -> None:
    hub.handle(gebit_topic("purchase_transaction", "PurchaseTransactionCreated"),
               raw(gebit_payload("PurchaseTransactionCreated", purchaseTransactionId=TX,
                                 metadata={"offset": "1"},
                                 purchaseTransactionStatus="PURCHASE_TRANSACTION_STATUS_CREATED")))
    hub.handle(gebit_topic("basket", "PositionAdded"), raw(position_added()))
    hub.handle("gpos/v1/insight/scan/101/01/" + TX, raw({
        "schema_version": "1", "type": "insight", "tx_id": TX, "store": "101", "till": "01",
        "position_id": "0d4c-1", "article_number": "100001", "code": "slow_seller",
        "severity": "high", "text": "Ladenhüter: 9 von 35 geplanten Stück verkauft (7 Tage), "
        "Reichweite 6,5 Wochen"}))
    bon = hub.snapshot("01")["bon"]
    assert bon["tx_id"] == TX and bon["status"] == "OPEN" and bon["total"] == "11,98"
    assert bon["lines"][0]["price"] == "9,99"
    assert bon["lines"][0]["insight"]["code"] == "slow_seller"
    assert [e["event"] for e in bon["events"]] == ["PurchaseTransactionCreated", "PositionAdded"]
    assert bon["events"][1]["to_sam"] is True and bon["events"][0]["to_sam"] is False
    hub.handle(gebit_topic("basket", "ArticlePositionVoided"),
               raw(gebit_payload("ArticlePositionVoided", purchaseTransactionId=TX,
                                 positionId="0d4c-1", metadata={"offset": "4"})))
    assert hub.snapshot("01")["bon"]["lines"][0]["voided"] is True


def test_late_event_does_not_roll_back_status_or_total(hub: feed.Hub) -> None:
    closed = gebit_payload("PurchaseTransactionClosed", purchaseTransactionId=TX,
                           metadata={"offset": "13"},
                           purchaseTransactionStatus="PURCHASE_TRANSACTION_STATUS_CLOSED",
                           pricingInformation={"totalSum": {"scale": 2, "intVal": "1317"}})
    late = gebit_payload("PurchaseTransactionInClosing", purchaseTransactionId=TX,
                         metadata={"offset": "12"},
                         purchaseTransactionStatus="PURCHASE_TRANSACTION_STATUS_IN_CLOSING",
                         pricingInformation={"totalSum": {"scale": 2, "intVal": "999"}})
    hub.handle(gebit_topic("purchase_transaction", "PurchaseTransactionClosed"), raw(closed))
    hub.handle(gebit_topic("purchase_transaction", "PurchaseTransactionInClosing"), raw(late))
    bon = hub.snapshot("01")["bon"]
    assert (bon["status"], bon["total"], bon["last_offset"]) == ("CLOSED", "13,17", 13)
    assert [e["offset"] for e in bon["events"]] == [13, 12]


def test_receipt_from_pos_admin_is_read_tolerantly(data: RefData) -> None:
    bon = feed.bon_from_admin("01", {
        "tx_id": TX, "status": "OPEN", "membership_id": "M-1001", "total": "11.98",
        "lines": [{"position_id": "p-1", "article_number": "100001", "name": "GEBIT Ente",
                   "item_count": 1, "unit_price": "9.99", "price_source": "REGULAR"},
                  {"position_id": "p-2", "article_number": "100004", "description": "Bananen",
                   "quantity": 2, "price": 1.99, "voided": True}]}, data).to_dict()
    assert (bon["card"], bon["persona"], bon["consent_profiling"]) == (
        "CLUB-1001", "Kaffeepause", True)
    assert bon["total"] == "11,98"
    assert [(l["description"], l["item_count"], l["price"], l["voided"]) for l in bon["lines"]] == [
        ("GEBIT Ente", 1, "9,99", False), ("Bananen", 2, "1,99", True)]


def test_probe_on_a_gebit_topic_is_no_till_event(hub: feed.Hub) -> None:
    """9.8: the R1 probe is a ``gpos.probe.Probe`` on the booth's Cancelled topic; it must
    not open a phantom receipt (the till would answer POS-001 to every later action)."""
    probe_topic = topics.gebit_event("purchase_transaction", "PurchaseTransactionCancelled",
                                     "DE", "999", "101", "01", "probe-0b7f6c1e")
    probe = {"@type": "type.googleapis.com/gpos.probe.Probe", "probe": "r1"}
    assert hub.handle(probe_topic, raw(probe)) is None
    assert hub.handle(gebit_topic("basket", "PositionAdded"),
                      raw({"purchaseTransactionId": TX, "metadata": {"offset": "3"}})) is None
    snap = hub.snapshot("01")
    assert snap["bon"] is None and snap["events"] == []
    assert hub.counters.to_dict()["pos_events"] == 0


def test_kasse_reload_keeps_chips_and_band_of_the_same_receipt(hub: feed.Hub) -> None:
    hub.handle(gebit_topic("basket", "PositionAdded"), raw(position_added()))
    hub.handle("gpos/v1/insight/scan/101/01/" + TX, raw({
        "schema_version": "1", "type": "insight", "tx_id": TX, "store": "101", "till": "01",
        "position_id": "0d4c-1", "code": "slow_seller", "severity": "high",
        "text": "Ladenhüter: 9 von 35 geplanten Stück verkauft (7 Tage), Reichweite 6,5 Wochen"}))
    line = {"position_id": "0d4c-1", "article_number": "100001", "description": "GEBIT Ente",
            "item_count": 1, "price": "9,99", "price_source": "REGULAR"}
    hub.load_bon("01", {"open_tx": {"tx_id": TX, "status": "OPEN", "total": "9,99",
                                    "offset": 3, "lines": [line]}})
    bon = hub.snapshot("01")["bon"]
    assert bon["lines"][0]["insight"]["code"] == "slow_seller"
    assert [e["event"] for e in bon["events"]] == ["PositionAdded"]
    hub.load_bon("01", {"open_tx": {"tx_id": "other-tx", "status": "OPEN", "lines": [line]}})
    bon = hub.snapshot("01")["bon"]
    assert bon["lines"][0]["insight"] is None and bon["events"] == []


def test_load_bon_without_open_tx_drops_an_open_receipt(hub: feed.Hub) -> None:
    hub.handle(gebit_topic("basket", "PositionAdded"), raw(position_added()))
    hub.load_bon("01", {"open_tx": None})
    assert hub.snapshot("01")["bon"] is None


def test_load_bon_keeps_a_closed_receipt(hub: feed.Hub) -> None:
    hub.handle(gebit_topic("purchase_transaction", "PurchaseTransactionClosed"), raw(
        gebit_payload("PurchaseTransactionClosed", purchaseTransactionId=TX,
                      metadata={"offset": "13"},
                      purchaseTransactionStatus="PURCHASE_TRANSACTION_STATUS_CLOSED")))
    hub.load_bon("01", {"open_tx": None})
    assert hub.snapshot("01")["bon"]["status"] == "CLOSED"


def test_ring_keeps_the_last_30_events(hub: feed.Hub) -> None:
    for i in range(35):
        hub.handle(f"gpos/v1/telemetry/tool/wws/t{i}", raw({"tool": f"t{i}", "caller": "agent"}))
    events = hub.snapshot("01")["events"]
    assert len(events) == 30
    assert events[0]["data"]["tool"] == "t5" and events[-1]["data"]["tool"] == "t34"
    assert hub.clear() == 30 and hub.snapshot("01")["events"] == []


def test_unreadable_messages_are_dropped(hub: feed.Hub) -> None:
    assert hub.handle("gpos/v1/review/state/prepared/101/01/GR-1", b"not json") is None
    assert hub.handle(gebit_topic("basket", "PositionAdded"), raw(gebit_payload(
        "PositionAdded", metadata={"offset": "x"}))) is None
    assert hub.handle(gebit_topic("basket", "PositionAdded"), raw(gebit_payload(
        "PositionAdded", metadata="3", pricingInformation=[]))) is None
    assert hub.handle("other/topic", raw({})) is None
    assert hub.snapshot("01")["events"] == []


# --------------------------------------------------------------------- SSE wire
def test_sse_message_format() -> None:
    text = feed.sse_message("insight", {"text": "Ladenhüter", "price": "9,99"})
    assert text == 'event: insight\ndata: {"text":"Ladenhüter","price":"9,99"}\n\n'
    assert feed.SSE_RETRY == "retry: 2000\n\n"
    assert feed.SSE_HEARTBEAT == ": hb\n\n"
    assert feed.HEARTBEAT_S == 15.0
