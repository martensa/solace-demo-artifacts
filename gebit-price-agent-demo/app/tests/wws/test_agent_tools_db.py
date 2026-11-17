"""Agent tools of gpos-wws-api with the real service on the seeded scratch DB (8.4).

The 8.4 examples are compared byte for byte (compact JSON, key order included). The
tools read store ``GPOS_TOOL_STORE`` (199 in tests, same data as 101).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from starlette.testclient import TestClient

from gposdemo.common import mcputil
from gposdemo.common.bus import MemoryBus
from gposdemo.common.jsonutil import compact
from gposdemo.wws import WwsApp

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_wws")]

HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
TOOLS = ("get_article", "get_sales_performance", "get_season_info")

# 8.4, verbatim (line breaks only)
ENTE_ARTICLE = {
    "article_number": "100001", "name": "GEBIT Ente (Quietscheente gelb)",
    "category": "Spielwaren & Geschenke", "pack": "1 Stück", "price": "9,99",
    "regular_price": "9,99", "price_source": "REGULAR", "action": None, "ref30": "9,99",
    "margin_pct": 38.1, "stock": 96, "season": None, "price_bound": False,
    "last_price_change": None, "listed_since": "2026-09-01"}
ENTE_SALES = {
    "article_number": "100001", "as_of": "2027-02-15", "sold_7d": 9, "plan_7d": 35,
    "sell_through_7d": 0.26, "weekly_units": [34, 36, 31, 28, 22, 16, 12, 9],
    "avg_week_28d": 14.75, "stock": 96, "weeks_of_supply": 6.5, "trend": "falling",
    "next_delivery": None}
PRALINEN_SEASON = {
    "article_number": "100008", "season": "Valentinstag", "start": "2027-01-18",
    "end": "2027-02-14", "days_to_end": -2, "status": "ended", "avg_day_14d": 6.4,
    "projected_units_to_end": 0, "stock": 46, "leftover_units": 46, "leftover_share": 1.0}


@pytest.fixture(scope="module")
def http(wws_app: WwsApp) -> Iterator[TestClient]:
    with TestClient(mcputil.http_app(wws_app.mcp)) as client:
        yield client


def call(client: TestClient, tool: str, **arguments: str) -> dict[str, Any]:
    reply = client.post(mcputil.MCP_PATH, headers=HEADERS, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": arguments}})
    assert reply.status_code == 200, reply.text
    return reply.json()["result"]


def text(result: dict[str, Any]) -> str:
    [content] = result["content"]
    return content["text"]


def test_examples_of_8_4_over_mcp(http: TestClient) -> None:
    for tool, number, expected in (("get_article", "100001", ENTE_ARTICLE),
                                   ("get_sales_performance", "100001", ENTE_SALES),
                                   ("get_season_info", "100008", PRALINEN_SEASON)):
        result = call(http, tool, article_number=number, ref="GR-270216-0007")
        assert result["isError"] is False and "structuredContent" not in result
        assert text(result) == compact(expected), tool
    assert text(call(http, "get_season_info", article_number="100001")) == compact(
        {"article_number": "100001", "status": "none"})


def test_service_methods_return_the_same_dicts(wws_app: WwsApp) -> None:
    """2.4: ``service.<tool>(**args)`` is the dict behind the text content."""
    assert wws_app.service.get_article("100001", ref="GR-1") == ENTE_ARTICLE
    assert wws_app.service.get_sales_performance("100001") == ENTE_SALES
    assert wws_app.service.get_season_info("100008") == PRALINEN_SEASON


def test_espresso_article_shows_the_last_price_change(wws_app: WwsApp) -> None:
    espresso = wws_app.service.get_article("100012")
    assert espresso["last_price_change"] == {"date": "2027-01-11", "from": "12,99",
                                             "to": "14,49"}
    assert (espresso["price"], espresso["ref30"], espresso["margin_pct"]) == (
        "14,49", "14,49", 34.3)  # (14,49/1,07 - 8,90) / (14,49/1,07)
    sales = wws_app.service.get_sales_performance("100012")
    assert sales["next_delivery"] == {"expected_on": "2027-02-18", "quantity": 24}


def test_gluehwein_article_shows_the_central_action(wws_app: WwsApp) -> None:
    got = wws_app.service.get_article("100009")
    assert (got["price"], got["regular_price"], got["price_source"]) == (
        "2,99", "3,49", "CENTRAL_ACTION")
    assert got["action"] == {"action_id": "PA-SEED-100009-199", "kind": "CENTRAL",
                             "price": "2,99", "valid_to": "So 21.02. 20:00"}
    assert (got["ref30"], got["season"]) == ("2,99", "Winter")  # 6.3 result on 16.02.
    season = wws_app.service.get_season_info("100009")
    assert (season["status"], season["days_to_end"], season["leftover_units"],
            season["leftover_share"]) == ("running", 12, 103, 0.86)


def test_pluschhase_shows_rising_sales_and_easter(wws_app: WwsApp) -> None:
    sales = wws_app.service.get_sales_performance("100002")
    assert (sales["trend"], sales["sell_through_7d"], sales["weeks_of_supply"]) == (
        "rising", 0.47, 8.2)
    season = wws_app.service.get_season_info("100002")
    assert (season["status"], season["start"]) == ("before", "2027-03-01")
    assert wws_app.service.get_article("100002")["season"] == "Ostern"


def test_unknown_article(http: TestClient) -> None:
    result = call(http, "get_sales_performance", article_number="999999", ref="GR-9")
    assert result["isError"] is True
    assert json.loads(text(result)) == {"article_number": "999999", "error": "WWS-001",
                                        "message": "Artikel 999999 im Laden 199 unbekannt"}


def test_every_answer_is_within_1200_bytes(http: TestClient, articles: dict[str, dict]
                                           ) -> None:
    sizes = []
    for number in articles:
        for tool in TOOLS:
            result = call(http, tool, article_number=number, ref="GR-270216-9999")
            assert result["isError"] is False, (tool, number)
            sizes.append(len(text(result).encode("utf-8")))
    assert max(sizes) <= mcputil.AGENT_MAX_TEXT_BYTES
    assert len(sizes) == 90


def test_telemetry_of_an_agent_call(http: TestClient, wws_bus: MemoryBus) -> None:
    call(http, "get_sales_performance", article_number="100001", ref="GR-270216-0007")
    [event] = wws_bus.messages("gpos/v1/telemetry/tool/wws/get_sales_performance")
    body = event.json()
    assert (body["service"], body["tool"], body["caller"], body["ref"], body["ok"]) == (
        "wws", "get_sales_performance", "agent", "GR-270216-0007", True)
    assert body["summary"] == "100001: 9/35 verkauft, Reichweite 6,5 Wo."  # 7.2
    assert event.persistent is False


def test_health_reports_db_and_bus(http: TestClient) -> None:
    reply = http.get("/health")
    assert (reply.status_code, reply.json()) == (200, {"status": "ok", "db": True, "bus": True})
