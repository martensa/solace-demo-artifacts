"""REST API of the BFF (10.1) against contract fakes of WWS, Loyalty, engine and POS admin."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable

import pytest

from gposdemo.common import topics
from gposdemo.common.bus import MemoryBus
from gposdemo.common.config import Settings
from gposdemo.ui import create

from .conftest import OPEN_TX, PENDING, Ui, gebit_payload

TX = "5b1f0c2e-8d1e-4a43-9a51-0c7a2f0e1b11"
# anything that would load from the network (the booth runs offline, no CDN)
EXTERNAL_LOAD = re.compile(r"""(?:src|href)\s*=\s*["']?(?:https?:)?//|url\(\s*["']?(?:https?:)?//"""
                           r"""|@import|(?:fetch|EventSource)\(\s*["'](?:https?:)?//""")


def wait_until(predicate: Callable[[], bool], timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


# --------------------------------------------------------------------- pages
def test_root_redirects_to_monitor(ui: Ui) -> None:
    response = ui.client.get("/", follow_redirects=False)
    assert response.status_code == 302 and response.headers["location"] == "/monitor"


def test_pages_are_static_german_and_offline(ui: Ui) -> None:
    assert EXTERNAL_LOAD.search('<script src="https://cdn.example/x.js"></script>')
    for path, script in (("/kasse", "/static/kasse/kasse.js"),
                         ("/monitor", "/static/monitor/monitor.js")):
        response = ui.client.get(path)
        assert response.status_code == 200
        html = response.text
        assert '<html lang="de">' in html and script in html
        assert "/static/shared/texts.js" in html and "/static/shared/common.js" in html
        assert not EXTERNAL_LOAD.search(html)
    for asset in ("/static/kasse/kasse.css", "/static/monitor/monitor.css",
                  "/static/shared/common.css", "/static/shared/common.js",
                  "/static/kasse/kasse.js", "/static/monitor/monitor.js"):
        response = ui.client.get(asset)
        assert response.status_code == 200, asset
        assert response.headers["cache-control"] == "no-cache", asset
        assert not EXTERNAL_LOAD.search(response.text), asset


def test_kasse_reload_reads_the_open_receipt_from_pos_admin(ui: Ui) -> None:
    ui.pos_admin.requests.clear()
    assert ui.client.get("/kasse").status_code == 200
    assert ui.pos_admin.paths("GET") == ["/admin/till/01"]
    bon = ui.client.get("/api/state").json()["bon"]
    assert bon["tx_id"] == OPEN_TX["tx_id"] and bon["total"] == "11,98"
    assert (bon["status"], bon["receipt_number"], bon["last_offset"]) == (
        "OPEN", "10101270216000042", 6)
    assert (bon["card"], bon["persona"], bon["consent_profiling"]) == (
        "CLUB-1001", "Kaffeepause", True)
    assert [(l["description"], l["price"], l["voided"]) for l in bon["lines"]] == [
        ("GEBIT Ente (Quietscheente gelb)", "9,99", False), ("Bio-Bananen", "1,99", False)]
    assert ui.client.get("/kasse?till=99").status_code == 200
    assert ui.pos_admin.paths("GET")[-1] == "/admin/till/99"
    assert ui.client.get("/kasse?till=42").status_code == 400


# --------------------------------------------------------------------- catalog
def test_catalog_from_wws_list_articles(ui: Ui) -> None:
    body = ui.client.get("/api/catalog").json()
    assert body["store"] == "101"
    assert ui.wws.calls[-1] == ("ListArticles", {"storeId": "101"})
    duck = next(a for a in body["articles"] if a["article_number"] == "100001")
    assert duck == {"article_number": "100001", "article_id": "ID100001",
                    "gtin": "2099100000018", "name": "GEBIT Ente (Quietscheente gelb)",
                    "category": "spielwaren_geschenke",
                    "category_label": "Spielwaren & Geschenke", "pack": "1 Stück",
                    "price": "7,99", "regular_price": "9,99", "price_source": "BOOTH_ACTION",
                    "valid_to_label": "Di 23.02. 20:00"}
    bananas = next(a for a in body["articles"] if a["article_number"] == "100004")
    assert (bananas["price"], bananas["price_source"], bananas["valid_to_label"]) == (
        "1,99", "REGULAR", "")
    assert [a["article_number"] for a in body["articles"]] == ["100001", "100004", "100010"]
    assert [c["tag"] for c in body["categories"]] == [
        "obst_gemuese", "molkerei_fruehstueck", "spielwaren_geschenke"]


def test_catalog_is_cached_until_a_price_change(ui: Ui) -> None:
    ui.client.get("/api/catalog")
    ui.client.get("/api/catalog")
    assert sum(1 for c in ui.wws.calls if c[0] == "ListArticles") == 1
    ui.publish("showcase/wws/v1/price/PriceChangeApplied/DE/999/101/100001",
               {"actionId": "PA-1", "articleNumber": "100001", "storeId": "101"})
    ui.client.get("/api/catalog")
    assert sum(1 for c in ui.wws.calls if c[0] == "ListArticles") == 2


PRICE_APPLIED_TOPIC = "showcase/wws/v1/price/PriceChangeApplied/DE/999/101/100001"


def test_catalog_in_flight_across_a_price_change_is_not_cached(ui: Ui) -> None:
    """A ListArticles answer read before PriceChangeApplied must not outlive it."""
    def change_arrives() -> None:
        ui.wws.while_listing = None
        ui.publish(PRICE_APPLIED_TOPIC, {"actionId": "PA-1", "articleNumber": "100001",
                                         "storeId": "101"})

    ui.wws.while_listing = change_arrives
    ui.client.get("/api/catalog")
    ui.client.get("/api/catalog")
    assert sum(1 for c in ui.wws.calls if c[0] == "ListArticles") == 2


def test_catalog_is_invalidated_before_the_pages_hear_of_the_change(ui: Ui) -> None:
    """/kasse reloads the catalog on SSE price_change; the cache must be gone by then."""
    bff = ui.svc.service
    ui.client.get("/api/catalog")
    cached_at_broadcast: list[int] = []
    broadcast = bff.hub.broadcast

    def spy(kind: str, data: dict) -> None:
        if kind == "price_change":
            cached_at_broadcast.append(len(bff._catalogs))
        broadcast(kind, data)

    bff.hub.broadcast = spy  # type: ignore[method-assign]
    ui.publish(PRICE_APPLIED_TOPIC, {"actionId": "PA-1", "articleNumber": "100001",
                                     "storeId": "101"})
    assert cached_at_broadcast == [0]


def test_r1_probe_leaves_the_booth_receipt_alone(ui: Ui) -> None:
    """9.8 step 10: the R1 probe on the booth topic is no till event (no phantom receipt,
    no counter)."""
    ui.publish(topics.gebit_event("purchase_transaction", "PurchaseTransactionCancelled",
                                  "DE", "999", "101", "01", "probe-0b7f6c1e"),
               {"@type": "type.googleapis.com/gpos.probe.Probe", "probe": "r1"})
    state = ui.client.get("/api/state").json()
    assert state["bon"]["tx_id"] == OPEN_TX["tx_id"]
    assert state["counters"]["pos_events"] == 0 and state["events"] == []


def test_catalog_of_the_test_till_uses_store_199(ui: Ui) -> None:
    assert ui.client.get("/api/catalog?till=99").json()["store"] == "199"
    assert ui.wws.calls[-1] == ("ListArticles", {"storeId": "199"})
    assert ui.client.get("/api/catalog?till=07").status_code == 400


# --------------------------------------------------------------------- state
def test_state_combines_receipt_engine_and_counters(ui: Ui) -> None:
    ui.publish(topics.gebit_event("basket", "PositionAdded", "DE", "999", "101", "01", TX),
               gebit_payload("PositionAdded", purchaseTransactionId=TX, metadata={"offset": "3"},
                             positionId="p-9", articleNumber="100001",
                             description="GEBIT Ente (Quietscheente gelb)", itemCount=1,
                             purchaseTransactionStatus="PURCHASE_TRANSACTION_STATUS_OPEN"))
    state = ui.client.get("/api/state").json()
    assert (state["store"], state["till"]) == ("101", "01")
    assert state["booth"] == {"store": "101", "till": "01"}
    assert state["demo_date"] == "2027-02-16" and state["demo_now"].startswith("2027-02-16T")
    assert state["bon"]["tx_id"] == TX
    assert state["proposal"]["proposal_id"] == "GP-270216-0003"
    assert state["proposal"]["state"] == "pending"  # engine "status" mirrored as "state"
    assert state["review"]["state"] == "proposed"
    assert state["engine_ok"] is True and state["engine_counts"]["proposals"] == 1
    assert state["counters"]["pos_events"] == 1
    assert state["counters"]["agent_runs_by_model"] == {"fast": 0, "planning": 0}
    assert "(fast 0, planning 0)" in state["counters"]["line"]
    assert state["events"][-1]["event"] == "pos_event"
    assert ui.engine.requests[-1].params == {"store": "101", "till": "01"}


def test_state_prefers_the_last_review_and_proposal_events(ui: Ui) -> None:
    review = {"schema_version": "1", "type": "review", "state": "prepared",
              "review_id": "GR-270216-0007", "tx_id": TX, "store": "101", "till": "01",
              "candidates": 1, "lines": []}
    proposal = {"schema_version": "1", "type": "proposal", "state": "ready",
                "proposal_id": "GP-270216-0003", "store": "101", "till": "01",
                "old_price": "9,99", "new_price": "7,99"}
    ui.publish("gpos/v1/review/state/prepared/101/01/GR-270216-0007", review)
    ui.publish("gpos/v1/proposal/ready/101/01/GP-270216-0003", proposal)
    state = ui.client.get("/api/state").json()
    assert state["review"] == review
    assert state["proposal_event"] == proposal
    assert state["proposal"]["state"] == "pending"  # the engine is the source of 10.1


def test_state_without_engine(ui: Ui) -> None:
    ui.engine.down = True
    state = ui.client.get("/api/state").json()
    assert state["engine_ok"] is False and state["proposal"] is None
    assert ui.client.get("/api/state?till=55").status_code == 400


# --------------------------------------------------------------------- proposals proxy
def test_proposal_proxy(ui: Ui) -> None:
    response = ui.client.get("/api/proposals/GP-270216-0003")
    assert response.status_code == 200
    body = response.json()
    assert body["approval"]["apply_calls"] == 0 and body["state"] == "pending"
    assert body["approval"]["checked_at"] == PENDING["approval"]["checked_at"]
    assert ui.client.get("/api/proposals/GP-unknown").status_code == 404
    assert ui.client.get("/api/proposals/GP%20x").status_code == 400
    ui.engine.down = True
    assert ui.client.get("/api/proposals/GP-270216-0003").status_code == 503


# --------------------------------------------------------------------- reset
def test_reset_chain_runs_in_order_and_clears_the_bff(ui: Ui) -> None:
    ui.publish(topics.gebit_event("basket", "PositionAdded", "DE", "999", "101", "01", TX),
               gebit_payload("PositionAdded", purchaseTransactionId=TX, metadata={"offset": "3"}))
    assert ui.client.get("/api/state").json()["counters"]["pos_events"] == 1
    response = ui.client.post("/api/demo/reset", json={"scope": "booth"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["scope"] == "booth" and body["store"] == "101"
    assert list(body["steps"]) == ["engine", "wws", "pos", "loyalty", "bff"]
    assert body["steps"]["engine"] == {"ok": True, "reviews": 1, "proposals": 1}
    assert body["steps"]["pos"] == {"ok": True, "status": "ok", "reset": 1}
    assert body["steps"]["bff"]["counters_before"]["pos_events"] == 1
    assert ui.engine.requests[-1].body == {"scope": "booth", "store_id": "101"}
    assert ui.wws.calls[-1] == ("ResetDemoState", {
        "header": {"traceId": "reset-booth", "originator": {"identityId": "gpos-ui"}},
        "storeId": "101"})
    assert ui.loyalty.calls[-1] == ("ResetDemoState", {
        "header": {"traceId": "reset-booth", "originator": {"identityId": "gpos-ui"}},
        "visitId": "booth"})
    assert ui.pos_admin.paths("POST") == ["/admin/reset"]
    state = ui.client.get("/api/state").json()
    assert state["counters"]["pos_events"] == 0 and state["events"] == []
    assert state["counters"]["agent_runs_by_model"] == {"fast": 0, "planning": 0}
    assert state["bon"] is None


def test_reset_day_restores_full_state(ui: Ui) -> None:
    body = ui.client.post("/api/demo/reset", json={"scope": "day"}).json()
    assert body["ok"] is True
    assert ui.engine.requests[-1].body == {"scope": "day", "store_id": "101"}
    assert ui.wws.calls[-1][1]["full"] is True
    assert ui.loyalty.calls[-1][1]["fullDayReset"] is True


def test_reset_reports_a_failed_step_and_goes_on(ui: Ui) -> None:
    ui.wws.fail_reset = True
    response = ui.client.post("/api/demo/reset", json={})
    assert response.status_code == 502
    body = response.json()
    assert body["ok"] is False and body["scope"] == "booth"
    assert body["steps"]["wws"]["ok"] is False and "WWS-099" in body["steps"]["wws"]["error"]
    assert body["steps"]["pos"]["ok"] and body["steps"]["loyalty"]["ok"]


@pytest.mark.parametrize("payload", [{"scope": "all"}, ["booth"], "x"])
def test_reset_rejects_invalid_scope(ui: Ui, payload: object) -> None:
    response = ui.client.post("/api/demo/reset", content=json.dumps(payload),
                              headers={"Content-Type": "application/json"})
    assert response.status_code == 400
    assert ui.engine.paths("POST") == []


# --------------------------------------------------------------------- SAM errors
def test_r4_error_is_forwarded_to_the_engine(ui: Ui) -> None:
    ui.publish("gpos/v1/sam/error/r4", {"error": "Tool approval timed out after 2 minutes"})
    assert wait_until(lambda: "/api/sam-error" in ui.engine.paths("POST"))
    sent = next(r for r in ui.engine.requests if r.path == "/api/sam-error")
    assert sent.body == {"rule": "r4", "store": "101", "till": "01",
                         "error": "Tool approval timed out after 2 minutes"}


def test_p4_error_goes_to_the_probe_till(ui: Ui) -> None:
    ui.publish("gpos/v1/sam/error/p4", "workflow was redeployed or stopped during execution")
    assert wait_until(lambda: "/api/sam-error" in ui.engine.paths("POST"))
    sent = next(r for r in ui.engine.requests if r.path == "/api/sam-error")
    assert sent.body == {"rule": "p4", "store": "199", "till": "98",
                         "error": "workflow was redeployed or stopped during execution"}


def test_other_runs_are_not_forwarded(ui: Ui) -> None:
    ui.publish("gpos/v1/sam/error/r3", {"error": "boom"})
    ui.publish("gpos/v1/sam/error/p1", {"error": "boom"})
    ui.publish("gpos/v1/sam/done/r4", {"proposal_id": "GP-1", "outcome": "approved"})
    time.sleep(0.2)
    assert "/api/sam-error" not in ui.engine.paths("POST")


def test_forward_is_retried(ui: Ui, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("gposdemo.ui.bff.FORWARD_BACKOFF_S", 0.01)
    ui.engine.routes[("POST", "/api/sam-error")] = (503, {"error": "starting"})
    assert ui.svc.service.forward_sam_error("r4", "x") is False
    assert ui.engine.paths("POST").count("/api/sam-error") == 3


# --------------------------------------------------------------------- health
def test_health_without_gebit_descriptors_is_degraded(ui: Ui) -> None:
    body = ui.client.get("/health").json()
    assert body == {"status": "degraded", "bus": True, "pos": False, "wws": True,
                    "engine": True}


def test_health_engine_down(ui: Ui, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("gposdemo.ui.bff.HEALTH_CACHE_S", 0.0)
    ui.engine.down = True
    body = ui.client.get("/health").json()
    assert body["engine"] is False and body["status"] == "degraded"


# --------------------------------------------------------------------- lifecycle
def test_create_refuses_a_db(settings: Settings) -> None:
    with pytest.raises(ValueError, match="no database role"):
        create(settings, MemoryBus(), db=object())  # type: ignore[arg-type]


def test_stop_without_start(settings: Settings, make_ui: Callable[..., Ui]) -> None:
    ui = make_ui()
    svc = create(settings, MemoryBus(), gateways=ui.svc.service.gw)
    svc.stop()
    assert svc.mcp is None and svc.service.hub.subscriber_count == 0


def test_start_subscribes_the_three_ui_filters(ui: Ui) -> None:
    for topic in ("gebit/rp/purchase/v2/basket/PositionAdded/DE/999/101/01/x",
                  "showcase/wws/v1/price/PriceChangeEnded/DE/999/101/100001",
                  "gpos/v1/telemetry/tool/wws/get_article"):
        before = len(ui.client.get("/api/state").json()["events"])
        ui.bus.publish(topic, json.dumps(gebit_payload(
            "PositionAdded", purchaseTransactionId="x", storeId="101", caller="agent",
            tool="get_article")))
        assert len(ui.client.get("/api/state").json()["events"]) == before + 1, topic
