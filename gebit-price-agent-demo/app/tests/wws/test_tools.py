"""MCP server gpos-wws-api: tool list, --dump-tools, result shape, telemetry (8.1, 8.4).

A stub stands in for the service here; ``test_service_db.py`` runs the real one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from gposdemo.common import mcputil
from gposdemo.common.bus import MemoryBus
from gposdemo.common.telemetry import Telemetry
from gposdemo.wws import errors, tools

APP_DIR = Path(__file__).resolve().parents[2]
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
# 8.4 examples (the stub answers them)
ENTE_SALES = {"article_number": "100001", "as_of": "2027-02-15", "sold_7d": 9, "plan_7d": 35,
              "sell_through_7d": 0.26, "weekly_units": [34, 36, 31, 28, 22, 16, 12, 9],
              "avg_week_28d": 14.75, "stock": 96, "weeks_of_supply": 6.5, "trend": "falling",
              "next_delivery": None}
PRALINEN_SEASON = {"article_number": "100008", "season": "Valentinstag", "start": "2027-01-18",
                   "end": "2027-02-14", "days_to_end": -2, "status": "ended",
                   "avg_day_14d": 6.4, "projected_units_to_end": 0, "stock": 46,
                   "leftover_units": 46, "leftover_share": 1.0}


class StubApi:
    """Answers like the service for 100001/100008; everything else is unknown."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def _known(self, tool: str, number: str, ref: str) -> None:
        self.calls.append((tool, number, ref))
        if number not in ("100001", "100008"):
            raise errors.article_unknown(number, "199")

    def get_article(self, article_number: str, ref: str = "") -> dict[str, Any]:
        self._known("get_article", article_number, ref)
        return {"article_number": article_number, "price": "9,99", "price_source": "REGULAR",
                "stock": 96}

    def get_sales_performance(self, article_number: str, ref: str = "") -> dict[str, Any]:
        self._known("get_sales_performance", article_number, ref)
        return ENTE_SALES

    def get_season_info(self, article_number: str, ref: str = "") -> dict[str, Any]:
        self._known("get_season_info", article_number, ref)
        if article_number == "100001":
            return {"article_number": "100001", "status": "none"}
        return PRALINEN_SEASON


@pytest.fixture
def stub() -> StubApi:
    return StubApi()


@pytest.fixture
def http(stub: StubApi, memory_bus: MemoryBus) -> Iterator[TestClient]:
    mcp = tools.build_mcp(stub, Telemetry(memory_bus, "wws"),
                          {"db": lambda: True, "bus": lambda: True})
    with TestClient(mcputil.http_app(mcp)) as client:
        yield client


def call(client: TestClient, tool: str, **arguments: str) -> dict[str, Any]:
    reply = client.post(mcputil.MCP_PATH, headers=HEADERS, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": arguments}})
    assert reply.status_code == 200, reply.text
    return reply.json()["result"]


def test_exactly_the_three_tools_of_8_4() -> None:
    listed = mcputil.tools_list(tools.build_mcp(None, None))
    assert [t["name"] for t in listed] == ["get_article", "get_sales_performance",
                                           "get_season_info"]
    assert [t["description"] for t in listed] == [
        "Article master data, effective price, ref30, stock, margin.",
        "Sales against plan and weeks of supply of one article.",
        "Season status and leftover stock of one article."]
    for tool in listed:
        assert "outputSchema" not in tool  # 8.1: agent tools without outputSchema
        schema = tool["inputSchema"]
        assert list(schema["properties"]) == ["article_number", "ref"]
        assert {p["type"] for p in schema["properties"].values()} == {"string"}
        assert schema["required"] == ["article_number"]
        assert schema["properties"]["ref"]["default"] == ""


def test_dump_tools_needs_no_database_bus_or_descriptors() -> None:
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(APP_DIR),
           "SHOWCASE_DESCRIPTOR_SET": "/nonexistent/showcase.pb",
           "GPOS_DSN": "postgresql://nobody@127.0.0.1:1/none", "GPOS_BUS": "solace",
           "SOLACE_HOST": "tcp://127.0.0.1:1"}
    proc = subprocess.run([sys.executable, "-m", "gposdemo.wws", "--dump-tools"],
                          capture_output=True, text=True, env=env, timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == mcputil.tools_list(tools.build_mcp(None, None))


def test_tool_answers_one_compact_json_text(http: TestClient, stub: StubApi) -> None:
    result = call(http, "get_sales_performance", article_number="100001",
                  ref="GR-270216-0007")
    assert result["isError"] is False
    assert "structuredContent" not in result
    [content] = result["content"]
    assert content["type"] == "text"
    assert content["text"] == json.dumps(ENTE_SALES, separators=(",", ":"))
    assert stub.calls == [("get_sales_performance", "100001", "GR-270216-0007")]


def test_ref_is_optional(http: TestClient, stub: StubApi) -> None:
    call(http, "get_article", article_number="100001")
    assert stub.calls == [("get_article", "100001", "")]


def test_unknown_article_is_an_error_json(http: TestClient) -> None:
    result = call(http, "get_article", article_number="999999", ref="GR-1")
    assert result["isError"] is True
    assert json.loads(result["content"][0]["text"]) == {
        "article_number": "999999", "error": "WWS-001",
        "message": "Artikel 999999 im Laden 199 unbekannt"}


def test_telemetry_per_call(http: TestClient, memory_bus: MemoryBus) -> None:
    call(http, "get_sales_performance", article_number="100001", ref="GR-270216-0007")
    call(http, "get_season_info", article_number="100008", ref="GR-270216-0007")
    call(http, "get_season_info", article_number="100001")
    call(http, "get_article", article_number="100001", ref="GR-2")
    call(http, "get_article", article_number="999999", ref="GR-3")
    sent = memory_bus.messages("gpos/v1/telemetry/tool/wws/>")
    assert [m.topic.rsplit("/", 1)[1] for m in sent] == [
        "get_sales_performance", "get_season_info", "get_season_info", "get_article",
        "get_article"]
    bodies = [m.json() for m in sent]
    assert all(b["service"] == "wws" and b["caller"] == "agent" and b["run_id"] == ""
               for b in bodies)
    assert [(b["ref"], b["ok"]) for b in bodies] == [
        ("GR-270216-0007", True), ("GR-270216-0007", True), ("", True), ("GR-2", True),
        ("GR-3", False)]
    assert [b["summary"] for b in bodies] == [
        "100001: 9/35 verkauft, Reichweite 6,5 Wo.",  # 7.2 example
        "100008: Saison Valentinstag endete am 14.02., Rest 46",
        "100001: keine Saison",
        "100001: 9,99 € (REGULAR), Bestand 96",
        "999999: Artikel 999999 im Laden 199 unbekannt"]
    assert all(m.props["source"] == "gpos-wws" for m in sent)


@pytest.mark.parametrize(("body", "expected"), [
    ({**PRALINEN_SEASON, "status": "running", "end": "2027-02-28", "days_to_end": 12,
      "leftover_units": 103}, "100008: Saison Valentinstag endet am 28.02. (12 Tage), Rest 103"),
    ({**PRALINEN_SEASON, "status": "before", "start": "2027-03-01", "leftover_units": 16},
     "100008: Saison Valentinstag ab 01.03., Rest 16"),
])
def test_season_summaries(body: dict[str, Any], expected: str) -> None:
    assert tools.season_summary(body) == expected


def test_sales_summary_without_supply_figure() -> None:
    assert tools.sales_summary({**ENTE_SALES, "weeks_of_supply": None}) == (
        "100001: 9/35 verkauft, Reichweite – Wo.")


def test_health(stub: StubApi) -> None:
    good = tools.build_mcp(stub, None, {"db": lambda: True, "bus": lambda: True})
    with TestClient(mcputil.http_app(good)) as client:
        reply = client.get("/health")
    assert (reply.status_code, reply.json()) == (200, {"status": "ok", "db": True, "bus": True})
    bad = tools.build_mcp(stub, None, {"db": lambda: False, "bus": lambda: True})
    with TestClient(mcputil.http_app(bad)) as client:
        reply = client.get("/health")
    assert (reply.status_code, reply.json()) == (503, {"status": "degraded", "db": False,
                                                       "bus": True})


def test_tool_without_service_refuses() -> None:
    mcp = tools.build_mcp(None, None)
    with TestClient(mcputil.http_app(mcp)) as client:
        result = call(client, "get_article", article_number="100001")
    assert result["isError"] is True
    assert result["content"][0]["text"] == "Error executing tool get_article"
