"""``assess_event`` and ``raise_basket_review`` on the scratch DB (11.1, 11.2, 7.2)."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any

import pytest
from google.protobuf import any_pb2, descriptor_pool, json_format

from gposdemo.common.bus import MemoryBus
from gposdemo.common.clock import ts_json
from gposdemo.common.descriptors import Types
from gposdemo.common.jsonutil import canonical, compact, sha256_hex
from gposdemo.engine import Engine
from tests.engine.fakes import (
    BANANEN,
    ENTE,
    ESPRESSO,
    KOCHBUCH,
    MILCH,
    Backends,
    FakeClock,
    PosWriter,
    gebit_event,
)
from tests.engine.flow import published

pytestmark = pytest.mark.db


def scan(basket: Any, index: int, number: str, offset: int, clock: FakeClock) -> str:
    return gebit_event("PositionAdded", basket.tx_id, offset, clock(),
                       positionId=basket.positions[index], articleNumber=number,
                       articleId=f"ID{number}", itemCount=1)


def inbox(engine: Engine, tx_id: str) -> list[dict[str, Any]]:
    return engine.service.ctx.db.fetch(
        'select "offset", event_type, store_id, till_id, verdict, payload_sha256, sam_run_id '
        'from engine.event_inbox where tx_id = %s order by "offset"', (tx_id,))


def test_scan_insight_is_published_and_deduplicated(engine: Engine, pos: PosWriter,
                                                    memory_bus: MemoryBus,
                                                    clock: FakeClock) -> None:
    basket = pos.basket([ENTE, BANANEN, MILCH], status="OPEN")
    raw = scan(basket, 0, ENTE, 3, clock)
    result = engine.service.assess_event(raw, "run-1")
    assert (result.verdict, result.event_key, result.event_type) == (
        "scan", f"{basket.tx_id}:3", "PositionAdded")
    assert (result.store, result.till, result.article_number, result.insight_code) == (
        "101", "01", ENTE, "slow_seller")
    assert result.insight_text == ("Ladenhüter: 9 von 35 geplanten Stück verkauft (7 Tage), "
                                   "Reichweite 6,5 Wochen, Bestand 96")
    [message] = memory_bus.messages(f"gpos/v1/insight/scan/101/01/{basket.tx_id}")
    body = message.json()
    assert list(body) == ["schema_version", "type", "ts", "tx_id", "store", "till",
                          "event_key", "position_id", "article_number", "article_name",
                          "code", "severity", "text", "price", "price_source", "run_id"]
    assert (body["type"], body["code"], body["severity"], body["price"],
            body["price_source"], body["article_name"], body["run_id"]) == (
        "insight", "slow_seller", "high", "9,99", "REGULAR", "GEBIT Ente (Quietscheente gelb)",
        "run-1")
    assert message.props["eventType"] == "insight" and not message.persistent
    reordered = compact(dict(reversed(list(json.loads(raw).items()))))
    assert engine.service.assess_event(reordered, "run-2").verdict == "duplicate"
    assert len(memory_bus.messages("gpos/v1/insight/>")) == 1
    [row] = inbox(engine, basket.tx_id)
    assert (row["verdict"], row["payload_sha256"], row["sam_run_id"]) == (
        "scan", sha256_hex(canonical(json.loads(raw))), "run-1")
    stored = engine.service.ctx.db.fetch(
        "select code, facts from engine.insight where tx_id = %s", (basket.tx_id,))
    assert stored[0]["code"] == "slow_seller" and stored[0]["facts"]["sold_7d"] == 9


def test_on_plan_and_price_bound_chips(engine: Engine, pos: PosWriter,
                                       clock: FakeClock) -> None:
    basket = pos.basket([BANANEN, KOCHBUCH], status="OPEN")
    on_plan = engine.service.assess_event(scan(basket, 0, BANANEN, 2, clock))
    bound = engine.service.assess_event(scan(basket, 1, KOCHBUCH, 4, clock))
    assert (on_plan.insight_code, on_plan.insight_text) == ("on_plan",
                                                            "läuft nach Plan (180/180)")
    assert (bound.insight_code, bound.insight_text) == ("excluded", "Gesperrt: Preisbindung")


def test_card_turns_on_customer_behaviour(engine: Engine, pos: PosWriter,
                                          clock: FakeClock) -> None:
    basket = pos.basket([ESPRESSO], status="OPEN", membership_id="M-1001")
    member = engine.service.assess_event(gebit_event(
        "LoyaltyMembershipAssigned", basket.tx_id, 2, clock()))
    assert (member.verdict, member.insight_code, member.insight_text) == (
        "member", "member", "Karte Kaffeepause · Profil-Einwilligung ja")
    result = engine.service.assess_event(scan(basket, 0, ESPRESSO, 4, clock))
    assert result.insight_code == "customer_behaviour"
    assert result.insight_text.startswith("Kundenverhalten: Stammartikel der Karte: zuletzt "
                                          "vor 35 Tagen")
    other = pos.basket([ESPRESSO], status="OPEN", membership_id="M-1003")
    assert engine.service.assess_event(gebit_event(
        "LoyaltyMembershipAssigned", other.tx_id, 2, clock())).insight_text == \
        "Karte Feierabend · Profil-Einwilligung nein"
    assert engine.service.assess_event(scan(other, 0, ESPRESSO, 4, clock)).insight_code == \
        "neutral"


def test_verdicts_ignore_stale_void_close_cancel(engine: Engine, pos: PosWriter,
                                                 clock: FakeClock) -> None:
    basket = pos.basket([ENTE, MILCH], status="OPEN")
    service = engine.service
    assert service.assess_event("not json").verdict == "ignore"
    assert service.assess_event('["list"]').verdict == "ignore"
    probe = service.assess_event('{"@type":"type.googleapis.com/gpos.probe.Probe",'
                                 '"probe":"p1"}')
    assert (probe.verdict, probe.event_type, probe.event_key) == ("ignore", "Probe", "")
    unknown = service.assess_event(gebit_event("PositionAdded", str(uuid.uuid4()), 1, clock()))
    assert (unknown.verdict, unknown.store) == ("ignore", "")
    fiscal = service.assess_event(gebit_event("FiscalTransactionAssigned", basket.tx_id, 5,
                                              clock()))
    assert (fiscal.verdict, fiscal.store) == ("ignore", "101")
    old = gebit_event("PositionAdded", basket.tx_id, 6, clock() - timedelta(seconds=21),
                      positionId=basket.positions[0])
    assert service.assess_event(old).verdict == "stale"
    pos.void(basket, 1)
    void = service.assess_event(gebit_event("ArticlePositionVoided", basket.tx_id, 7, clock(),
                                            positionId=basket.positions[1]))
    assert (void.verdict, void.insight_code, void.insight_text, void.article_number) == (
        "void", "void", "Zeile storniert", MILCH)
    pos.close(basket)
    closed = service.assess_event(gebit_event("PurchaseTransactionClosed", basket.tx_id, 12,
                                              clock()))
    assert (closed.verdict, closed.insight_code, closed.insight_text) == (
        "close", "close", "Bon abgeschlossen")
    other = pos.basket([ENTE], status="OPEN")
    late = gebit_event("PurchaseTransactionClosed", other.tx_id, 9,
                       clock() - timedelta(seconds=301))
    assert service.assess_event(late).verdict == "stale"
    within = gebit_event("PurchaseTransactionClosed", other.tx_id, 10,
                         clock() - timedelta(seconds=100))
    assert service.assess_event(within).verdict == "close"
    cancel = service.assess_event(gebit_event("PurchaseTransactionCancelled", other.tx_id, 11,
                                              clock()))
    assert (cancel.verdict, cancel.insight_code) == ("cancel", "none")
    verdicts = [r["verdict"] for r in inbox(engine, basket.tx_id)]
    assert verdicts == ["ignore", "stale", "void", "close"]


def test_wws_outage_keeps_the_verdict(engine: Engine, pos: PosWriter, stubs: Backends,
                                      clock: FakeClock) -> None:
    basket = pos.basket([ENTE], status="OPEN")
    stubs.wws.unavailable = True
    result = engine.service.assess_event(scan(basket, 0, ENTE, 2, clock))
    assert (result.verdict, result.insight_code, result.insight_text) == (
        "scan", "none", "Analyse nicht verfügbar")


def test_raise_basket_review(engine: Engine, pos: PosWriter, memory_bus: MemoryBus) -> None:
    service = engine.service
    assert service.raise_basket_review("not-a-uuid").status == "unknown_tx"
    assert service.raise_basket_review(str(uuid.uuid4())).status == "unknown_tx"
    open_basket = pos.basket([ENTE], status="OPEN")
    assert service.raise_basket_review(open_basket.tx_id).status == "not_closed"
    basket = pos.basket([ENTE, BANANEN])
    raised = service.raise_basket_review(basket.tx_id, "run-r1")
    assert raised.status == "requested" and raised.tx_id == basket.tx_id
    assert raised.review_id.startswith("GR-270216-") and len(raised.review_id) == 14
    again = service.raise_basket_review(basket.tx_id, "run-r1b")
    assert (again.status, again.review_id) == ("exists", raised.review_id)
    [request] = published(engine, memory_bus, "gpos/v1/review/request/101/01/>")
    assert request == {"schema_version": "1", "review_id": raised.review_id,
                       "tx_id": basket.tx_id, "store": "101", "till": "01"}
    [message] = memory_bus.messages("gpos/v1/review/request/>")
    assert message.app_message_id == f"{raised.review_id}:1"
    assert message.props == {"eventType": "review.request", "source": "gpos-engine",
                             "apiVersion": "gpos-v1", "traceId": raised.review_id}
    [state] = published(engine, memory_bus, "gpos/v1/review/state/requested/101/01/>")
    assert (state["type"], state["state"], state["membership"], state["run_id"]) == (
        "review", "requested", None, "run-r1")
    test_till = pos.basket([ENTE], till="99")
    assert service.raise_basket_review(test_till.tx_id).status == "requested"
    assert published(engine, memory_bus, "gpos/v1/review/request/199/99/>")


@pytest.mark.gebit
def test_real_gebit_position_added(engine: Engine, pos: PosWriter,
                                   gebit_pool: descriptor_pool.DescriptorPool,
                                   clock: FakeClock) -> None:
    """The fields the engine reads exist in purchase-api-2.50.0 (strict parse)."""
    basket = pos.basket([ENTE], status="OPEN")
    event = Types(gebit_pool).event("PositionAdded")
    json_format.ParseDict({
        "header": {"eventTimestamp": ts_json(clock())},
        "metadata": {"offset": "3", "creationTimestamp": ts_json(clock()),
                     "traceId": "kasse-01-7f3a"},
        "purchaseTransactionId": basket.tx_id, "positionId": basket.positions[0],
        "articleId": "ID100001", "articleNumber": ENTE, "itemCount": 1,
        "description": "GEBIT Ente (Quietscheente gelb)"}, event,
        descriptor_pool=gebit_pool)
    packed = any_pb2.Any()
    packed.Pack(event)
    raw = canonical(json_format.MessageToDict(packed, descriptor_pool=gebit_pool))
    result = engine.service.assess_event(raw, "run-gebit")
    assert (result.verdict, result.event_key, result.insight_code) == (
        "scan", f"{basket.tx_id}:3", "slow_seller")
