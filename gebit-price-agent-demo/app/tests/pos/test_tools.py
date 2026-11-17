"""MCP server gpos-pos-api, --dump-tools and the admin routes (8.1, 8.4, 8.5, 11.8; no marker).

A fake service stands in for the DB-backed ``PosService`` (the DB path is covered in
``test_store_db.py``); the HTTP layer is exercised in-process over ``/mcp``.
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
from gposdemo.pos import admin, tools

APP_DIR = Path(__file__).resolve().parents[2]
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
TX = "5b1f0c2e-8d1e-4a43-9a51-0c7a2f0e1b11"
TX_VIEW = {"tx_id": TX, "till": "01", "status": "CLOSED", "receipt": "10101270216000042",
           "membership_id": "M-1001", "total": "16,98",
           "lines": [{"article_number": "100012", "name": "Espresso Bohnen kräftig", "qty": 1,
                      "price": "14,49", "source": "REGULAR"}]}
TILL_VIEW = {"till": "01", "open_tx": None, "tx_today": 7, "last_closed_tx": TX,
             "revenue_today": "84,12"}


class FakeService:
    """Answers like ``PosService`` without a DB."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def get_transaction(self, tx_id: str, ref: str = "") -> dict[str, Any]:
        self.calls.append(("get_transaction", (tx_id, ref)))
        if tx_id != TX:
            raise LookupError(f"Transaktion {tx_id} unbekannt")
        return TX_VIEW

    def get_till_status(self, ref: str = "") -> dict[str, Any]:
        self.calls.append(("get_till_status", (ref,)))
        return TILL_VIEW

    def till_state(self, till: str) -> dict[str, Any]:
        if till != "01":
            raise KeyError(till)
        return {"till": "01", "store": "101", "open_tx": None}

    def admin_reset(self) -> dict[str, Any]:
        return {"status": "ok", "reset": 2}


@pytest.fixture
def fake() -> FakeService:
    return FakeService()


@pytest.fixture
def http(fake: FakeService, memory_bus: MemoryBus) -> Iterator[TestClient]:
    mcp = tools.build_mcp(fake, Telemetry(memory_bus, "pos"))  # type: ignore[arg-type]
    admin.add_routes(mcp, fake, {"db": lambda: True, "bus": lambda: True})  # type: ignore[arg-type]
    with TestClient(mcputil.http_app(mcp)) as client:
        yield client


def _call(client: TestClient, name: str, arguments: dict[str, str]) -> dict[str, Any]:
    reply = client.post(mcputil.MCP_PATH, headers=HEADERS, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments}})
    assert reply.status_code == 200, reply.text
    return reply.json()["result"]


def test_dump_tools_runs_without_gebit_db_and_bus(tmp_path: Path) -> None:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path), "PYTHONPATH": str(APP_DIR),
           "GEBIT_DESCRIPTOR_SETS": str(tmp_path / "missing.pb"), "GPOS_DSN": "",
           "SOLACE_HOST": "tcp://127.0.0.1:1"}
    proc = subprocess.run([sys.executable, "-m", "gposdemo.pos", "--dump-tools"], env=env,
                          cwd=tmp_path, capture_output=True, text=True, timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr
    listed = {t["name"]: t for t in json.loads(proc.stdout)}
    assert list(listed) == ["get_transaction", "get_till_status"]
    tx = listed["get_transaction"]
    assert tx["description"] == "One POS transaction with lines, prices and membership."
    assert list(tx["inputSchema"]["properties"]) == ["tx_id", "ref"]
    assert tx["inputSchema"]["required"] == ["tx_id"]
    assert list(listed["get_till_status"]["inputSchema"]["properties"]) == ["ref"]
    for tool in listed.values():
        assert "outputSchema" not in tool  # 8.1: agent tools carry no output schema
        assert all(p["type"] == "string" for p in tool["inputSchema"]["properties"].values())


def test_get_transaction_is_one_compact_text(http: TestClient, fake: FakeService,
                                             memory_bus: MemoryBus) -> None:
    result = _call(http, "get_transaction", {"tx_id": TX, "ref": "GR-270216-0007"})
    assert "structuredContent" not in result and result["isError"] is False
    [content] = result["content"]
    assert content["text"] == json.dumps(TX_VIEW, separators=(",", ":"), ensure_ascii=False)
    assert fake.calls == [("get_transaction", (TX, "GR-270216-0007"))]
    [event] = memory_bus.messages("gpos/v1/telemetry/tool/pos/get_transaction")
    body = event.json()
    assert (body["service"], body["caller"], body["ref"], body["ok"]) == (
        "pos", "agent", "GR-270216-0007", True)
    assert body["summary"] == "Bon 5b1f0c2e: 1 Zeilen, 16,98 €, Karte M-1001"


def test_get_till_status(http: TestClient, memory_bus: MemoryBus) -> None:
    result = _call(http, "get_till_status", {"ref": "GR-270216-0008"})
    assert json.loads(result["content"][0]["text"]) == TILL_VIEW
    [event] = memory_bus.messages("gpos/v1/telemetry/tool/pos/get_till_status")
    assert event.json()["summary"] == "Kasse 01: 7 Bons heute, 84,12 €, kein offener Bon"


def test_unknown_transaction_is_a_tool_error(http: TestClient, memory_bus: MemoryBus) -> None:
    result = _call(http, "get_transaction", {"tx_id": "nope"})
    assert result["isError"] is True
    assert "unbekannt" in result["content"][0]["text"]
    [event] = memory_bus.messages("gpos/v1/telemetry/tool/pos/get_transaction")
    assert event.json()["ok"] is False


def test_admin_routes(http: TestClient) -> None:
    assert http.post("/admin/reset").json() == {"status": "ok", "reset": 2}
    assert http.get("/admin/till/01").json() == {"till": "01", "store": "101", "open_tx": None}
    missing = http.get("/admin/till/42")
    assert missing.status_code == 404
    assert http.get("/health").json() == {"status": "ok", "db": True, "bus": True}


def test_tools_without_service_refuse_to_run() -> None:
    mcp = tools.build_mcp(None, None)
    assert [t["name"] for t in mcputil.tools_list(mcp)] == ["get_transaction",
                                                             "get_till_status"]
    with TestClient(mcputil.http_app(mcp)) as client:
        assert _call(client, "get_till_status", {})["isError"] is True
