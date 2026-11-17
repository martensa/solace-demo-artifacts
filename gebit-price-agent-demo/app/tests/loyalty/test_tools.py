"""MCP server ``gpos-loyalty-api`` (8.1, 8.4, 9.3): tool list, wire shape, telemetry."""

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
from gposdemo.loyalty.service import UnknownMember
from gposdemo.loyalty.tools import (
    PROFILE_DESCRIPTION,
    SERVER_NAME,
    behaviour_summary,
    build_mcp,
    profile_summary,
)

APP_DIR = Path(__file__).resolve().parents[2]
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
REF = "GR-270216-0007"
BEHAVIOUR = {"membership_id": "M-1001", "article_number": "100012", "consent_profiling": True,
             "member_purchases_8w": 2, "member_purchases_12w": 4, "days_since_last": 35,
             "median_interval_days": 14, "overdue_factor": 2.5,
             "cardholder_weekly": [22, 24, 21, 23, 13, 12, 11, 12],
             "cardholder_drop_pct": 46.7}
PROFILE = {"membership_id": "M-1003", "persona": "Feierabend", "segment": "Spontaneinkauf",
           "salutation": "Sie", "consent": {"offers": True, "profiling": False},
           "tags": ["getraenke"], "top_categories_8w": None}


class FakeApi:
    """Stands in for ``LoyaltyService``; records the calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def get_member_profile(self, membership_id: str, ref: str = "") -> dict[str, Any]:
        self.calls.append(("get_member_profile", (membership_id, ref)))
        if membership_id == "M-0000":
            raise UnknownMember("Mitglied M-0000 unbekannt")
        return PROFILE

    def get_purchase_behaviour(self, membership_id: str, article_number: str, ref: str = ""
                               ) -> dict[str, Any]:
        self.calls.append(("get_purchase_behaviour", (membership_id, article_number, ref)))
        return BEHAVIOUR


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.fixture
def http(api: FakeApi, memory_bus: MemoryBus) -> Iterator[TestClient]:
    mcp = build_mcp(api, Telemetry(memory_bus, "loyalty"))
    with TestClient(mcputil.http_app(mcp)) as client:
        yield client


def _call(client: TestClient, tool: str, arguments: dict[str, str]) -> dict[str, Any]:
    reply = client.post(mcputil.MCP_PATH, headers=HEADERS, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": arguments}})
    assert reply.status_code == 200, reply.text
    return reply.json()["result"]


def test_exactly_the_two_tools_of_8_4() -> None:
    mcp = build_mcp(None, None)
    assert mcp.name == SERVER_NAME == "gpos-loyalty-api"
    tools = {t["name"]: t for t in mcputil.tools_list(mcp)}
    assert list(tools) == ["get_member_profile", "get_purchase_behaviour"]
    for tool in tools.values():
        assert "outputSchema" not in tool  # agent tools: text only (8.1)
        props = tool["inputSchema"]["properties"]
        assert all(p["type"] == "string" for p in props.values())
        assert props["ref"]["default"] == ""
    assert tools["get_member_profile"]["description"] == PROFILE_DESCRIPTION == (
        "Profile of one fictional loyalty card (no personal attributes).")
    assert list(tools["get_member_profile"]["inputSchema"]["properties"]) == [
        "membership_id", "ref"]
    assert tools["get_member_profile"]["inputSchema"]["required"] == ["membership_id"]
    assert list(tools["get_purchase_behaviour"]["inputSchema"]["properties"]) == [
        "membership_id", "article_number", "ref"]
    assert tools["get_purchase_behaviour"]["inputSchema"]["required"] == [
        "membership_id", "article_number"]


def test_dump_tools_needs_no_db_bus_or_descriptors() -> None:
    """``--dump-tools`` with an empty environment (no DSN, broker or descriptor set)."""
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""),
           "SHOWCASE_DESCRIPTOR_SET": "/nonexistent/showcase.pb",
           "GPOS_DSN": "postgresql://nobody@127.0.0.1:1/none"}
    proc = subprocess.run([sys.executable, "-m", "gposdemo.loyalty", "--dump-tools"],
                          cwd=APP_DIR, env=env, capture_output=True, text=True, timeout=60,
                          check=False)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == mcputil.tools_list(build_mcp(None, None))


def test_served_tool_list_equals_the_dump(api: FakeApi, memory_bus: MemoryBus) -> None:
    """8.5: the manifests come from ``--dump-tools``, ``check_manifests.py`` compares them
    with the running server; the telemetry wrapper must not change the tool list."""
    served = build_mcp(api, Telemetry(memory_bus, "loyalty"))
    assert mcputil.tools_list(served) == mcputil.tools_list(build_mcp(None, None))


def test_purchase_behaviour_on_the_wire(http: TestClient, api: FakeApi,
                                        memory_bus: MemoryBus) -> None:
    result = _call(http, "get_purchase_behaviour",
                   {"membership_id": "M-1001", "article_number": "100012", "ref": REF})
    assert result["isError"] is False and "structuredContent" not in result
    [content] = result["content"]
    assert content["type"] == "text"
    assert content["text"] == json.dumps(BEHAVIOUR, separators=(",", ":"), ensure_ascii=False)
    assert api.calls == [("get_purchase_behaviour", ("M-1001", "100012", REF))]
    [event] = memory_bus.messages("gpos/v1/telemetry/tool/loyalty/get_purchase_behaviour")
    body = event.json()
    assert (body["service"], body["tool"], body["caller"], body["ref"], body["ok"]) == (
        "loyalty", "get_purchase_behaviour", "agent", REF, True)
    assert body["summary"] == ("100012 · M-1001: 2 Käufe in 8 Wo., zuletzt vor 35 Tagen · "
                               "Kartenkunden 46,7 % seltener")
    assert event.props["source"] == "gpos-loyalty" and event.props["traceId"] == REF


def test_member_profile_on_the_wire(http: TestClient, memory_bus: MemoryBus) -> None:
    result = _call(http, "get_member_profile", {"membership_id": "M-1003", "ref": REF})
    assert json.loads(result["content"][0]["text"]) == PROFILE
    [event] = memory_bus.messages("gpos/v1/telemetry/tool/loyalty/get_member_profile")
    assert event.json()["summary"] == "M-1003 Feierabend · keine Profil-Einwilligung"


def test_unknown_member_is_a_tool_error(http: TestClient, memory_bus: MemoryBus) -> None:
    result = _call(http, "get_member_profile", {"membership_id": "M-0000"})
    assert result["isError"] is True
    assert "Mitglied M-0000 unbekannt" in result["content"][0]["text"]
    [event] = memory_bus.messages("gpos/v1/telemetry/tool/loyalty/>")
    assert event.json()["ok"] is False


def test_dump_only_server_refuses_calls() -> None:
    with TestClient(mcputil.http_app(build_mcp(None, None))) as client:
        result = _call(client, "get_member_profile", {"membership_id": "M-1001"})
    assert result["isError"] is True


@pytest.mark.parametrize(("data", "text"), [
    ({**BEHAVIOUR, "consent_profiling": False, "member_purchases_8w": None,
      "days_since_last": None},
     "100012 · M-1001: keine Profil-Einwilligung · Kartenkunden 46,7 % seltener"),
    ({**BEHAVIOUR, "member_purchases_8w": 0, "days_since_last": None,
      "cardholder_drop_pct": -20.0},
     "100012 · M-1001: 0 Käufe in 8 Wo., nie gekauft · Kartenkunden 20,0 % häufiger"),
    ({**BEHAVIOUR, "cardholder_drop_pct": 0.0},
     "100012 · M-1001: 2 Käufe in 8 Wo., zuletzt vor 35 Tagen · Kartenkunden unverändert"),
    ({**BEHAVIOUR, "member_purchases_8w": 1, "days_since_last": 1},
     "100012 · M-1001: 1 Kauf in 8 Wo., zuletzt vor 1 Tag · Kartenkunden 46,7 % seltener"),
])
def test_behaviour_summaries(data: dict[str, Any], text: str) -> None:
    result = mcputil.text_result(data)
    assert behaviour_summary({}, result) == text
    assert len(text) <= 120


def test_profile_summary_with_consent() -> None:
    data = {**PROFILE, "membership_id": "M-1001", "persona": "Kaffeepause",
            "consent": {"offers": True, "profiling": True},
            "top_categories_8w": [{"category": "kaffee_tee", "purchases": 2,
                                   "days_since_last": 35}]}
    assert profile_summary({}, mcputil.text_result(data)) == (
        "M-1001 Kaffeepause · Profil-Einwilligung ja · 1 Kategorie")
