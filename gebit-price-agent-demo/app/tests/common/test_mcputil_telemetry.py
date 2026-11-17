"""mcputil and telemetry: result shapes, size limits, telemetry wrapper, health, dump (8.1)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Annotated, Any

import pytest
from mcp_types import CallToolResult, TextContent
from pydantic import BaseModel, Field
from starlette.testclient import TestClient

from gposdemo.common import mcputil
from gposdemo.common.bus import MemoryBus
from gposdemo.common.jsonutil import compact
from gposdemo.common.telemetry import Telemetry, shorten

RUN_ID = "gdk-task-0123abcd"  # short: never trips the sk- hygiene pattern
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


class StatusResult(BaseModel):
    """8.2 StatusResult (fields in this order)."""

    status: str
    event_key: str = ""
    verdict: str = ""


class FillResult(BaseModel):
    status: str
    filler: str = ""


def _server(bus: MemoryBus, health: dict[str, Any] | None = None) -> Any:
    mcp = mcputil.make_server("gpos-ut-tools", "WP-A test server. Fictional data only.")
    tel = Telemetry(bus, "engine")

    @mcp.tool()
    @mcputil.telemetry(tel, caller="workflow", ref_param="event_key")
    def note_event(
        event_key: Annotated[str, Field(description="event_key from assess_event.")],
        verdict: Annotated[str, Field(description="verdict from assess_event.")],
        run_id: Annotated[str, Field(description="Workflow run id.")] = "",
    ) -> Annotated[CallToolResult, StatusResult]:
        """Record an event that needs no action."""
        result = StatusResult(status="noted", event_key=event_key, verdict=verdict)
        return mcputil.structured_result("note_event", result, "noted")

    @mcp.tool(structured_output=False)
    @mcputil.telemetry(tel, caller="agent",
                       summary=lambda args, _r: f"{args['article_number']}: 9/35 verkauft")
    def get_sales_performance(
        article_number: Annotated[str, Field(description="Article number, e.g. 100001.")],
        ref: Annotated[str, Field(description="Review id for the monitor.")] = "",
    ) -> CallToolResult:
        """Sales against plan of one article (agent tool)."""
        if article_number == "boom":
            raise ValueError("Artikel unbekannt")
        return mcputil.text_result({"article_number": article_number, "sold_7d": 9,
                                    "name": "Herzpralinen Valentin"})

    @mcp.tool()
    def size_probe(size: int) -> Annotated[CallToolResult, FillResult]:
        """Result with a filler of ``size`` characters."""
        return mcputil.structured_result("size_probe", FillResult(status="ok", filler="x" * size),
                                         "ok")

    mcputil.add_health(mcp, health or {"db": lambda: True, "bus": lambda: True})
    return mcp


@pytest.fixture
def mcp_and_bus(memory_bus: MemoryBus) -> tuple[Any, MemoryBus]:
    return _server(memory_bus), memory_bus


@pytest.fixture
def http(mcp_and_bus: tuple[Any, MemoryBus]) -> Iterator[TestClient]:
    with TestClient(mcputil.http_app(mcp_and_bus[0])) as client:
        yield client


def _rpc(client: TestClient, method: str, params: dict[str, Any]) -> dict[str, Any]:
    reply = client.post(mcputil.MCP_PATH, headers=HEADERS,
                        json={"jsonrpc": "2.0", "id": 7, "method": method, "params": params})
    assert reply.status_code == 200, reply.text
    return reply.json()["result"]


def test_measure_counts_the_g0_01_envelope() -> None:
    result = mcputil.structured_result("note_event", StatusResult(status="noted"), "noted")
    expected = ('{"content":[{"type":"text","text":"note_event: noted"}],'
                '"structuredContent":{"status":"noted","event_key":"","verdict":""},'
                '"isError":false,"resultType":"complete"}')
    assert mcputil.measure(result) == (len(expected), len("note_event: noted"))


def test_structured_result_shape() -> None:
    result = mcputil.structured_result(
        "assess_event", StatusResult(status="noted", event_key="tx:3"), "scan 100001\nslow_seller")
    assert [c.text for c in result.content] == ["assess_event: scan 100001 slow_seller"]
    assert result.structured_content == {"status": "noted", "event_key": "tx:3", "verdict": ""}


def test_text_result_shape() -> None:
    result = mcputil.text_result({"name": "Glühwein rot", "price": "4,99"})
    assert result.structured_content is None
    assert [c.text for c in result.content] == ['{"name":"Glühwein rot","price":"4,99"}']
    assert mcputil.result_text(result) == '{"name":"Glühwein rot","price":"4,99"}'


def test_measure_equals_the_wire_result(http: TestClient) -> None:
    for tool, args in (("note_event", {"event_key": "5b1f:3", "verdict": "ignore",
                                       "run_id": RUN_ID}),
                       ("get_sales_performance", {"article_number": "100008", "ref": "GR-1"})):
        wire = _rpc(http, "tools/call", {"name": tool, "arguments": args})
        assert wire["isError"] is False and "resultType" not in wire  # legacy protocol
        full, text = mcputil.measure(CallToolResult.model_validate(wire))
        assert full == len(compact({**wire, "resultType": "complete"}).encode("utf-8"))
        assert text == len("".join(c["text"] for c in wire["content"]).encode("utf-8"))


def test_size_limits() -> None:
    def probe(size: int) -> CallToolResult:
        return mcputil.structured_result("size_probe", FillResult(status="ok", filler="x" * size),
                                         "ok")

    base, _ = mcputil.measure(probe(0))
    assert mcputil.within_limits(probe(1800 - base), "workflow")
    assert not mcputil.within_limits(probe(1801 - base), "workflow")
    long_text = CallToolResult(content=[TextContent(type="text", text="ü" * 751)])
    assert mcputil.measure(long_text)[1] == 1502
    assert not mcputil.within_limits(long_text, "workflow")
    agent_ok = mcputil.text_result({"t": "x" * (1200 - len('{"t":""}'))})
    assert mcputil.measure(agent_ok)[1] == 1200 and mcputil.within_limits(agent_ok, "agent")
    assert not mcputil.within_limits(mcputil.text_result({"t": "x" * 1200}), "agent")


def test_oversized_results_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    mcputil.text_result({"t": "x" * 1300})
    assert "too big for a agent tool" in caplog.text


def test_tools_list_schemas(mcp_and_bus: tuple[Any, MemoryBus]) -> None:
    tools = {t["name"]: t for t in mcputil.tools_list(mcp_and_bus[0])}
    note = tools["note_event"]
    assert note["description"] == "Record an event that needs no action."
    assert list(note["inputSchema"]["properties"]) == ["event_key", "verdict", "run_id"]
    assert note["inputSchema"]["required"] == ["event_key", "verdict"]
    assert all(p["type"] == "string" for p in note["inputSchema"]["properties"].values())
    assert list(note["outputSchema"]["properties"]) == ["status", "event_key", "verdict"]
    agent = tools["get_sales_performance"]
    assert "outputSchema" not in agent  # 8.1: agent tools without outputSchema
    assert list(agent["inputSchema"]["properties"]) == ["article_number", "ref"]


def test_dump_tools_prints_the_list(mcp_and_bus: tuple[Any, MemoryBus],
                                    capsys: pytest.CaptureFixture[str]) -> None:
    mcputil.dump_tools(mcp_and_bus[0])
    printed = json.loads(capsys.readouterr().out)
    assert [t["name"] for t in printed] == ["note_event", "get_sales_performance", "size_probe"]
    assert mcputil.wants_dump_tools(["--dump-tools"])
    assert not mcputil.wants_dump_tools([])


def test_telemetry_of_a_workflow_tool(http: TestClient, mcp_and_bus: tuple[Any, MemoryBus]
                                      ) -> None:
    bus = mcp_and_bus[1]
    wire = _rpc(http, "tools/call", {"name": "note_event", "arguments": {
        "event_key": "5b1f:3", "verdict": "ignore", "run_id": RUN_ID}})
    assert wire["structuredContent"] == {"status": "noted", "event_key": "5b1f:3",
                                         "verdict": "ignore"}
    [event] = bus.messages("gpos/v1/telemetry/tool/engine/note_event")
    body = event.json()
    assert list(body) == ["schema_version", "type", "ts", "service", "tool", "caller", "ref",
                          "run_id", "ms", "ok", "summary"]
    assert (body["schema_version"], body["type"], body["caller"]) == ("1", "tool_call", "workflow")
    assert (body["ref"], body["run_id"], body["ok"]) == ("5b1f:3", RUN_ID, True)
    assert body["summary"] == "note_event: noted"
    assert isinstance(body["ms"], int) and body["ms"] >= 0
    assert event.props == {"eventType": "tool_call", "source": "gpos-engine",
                           "apiVersion": "gpos-v1", "traceId": "5b1f:3"}
    assert event.persistent is False


def test_telemetry_of_agent_tool_and_failure(http: TestClient,
                                             mcp_and_bus: tuple[Any, MemoryBus]) -> None:
    bus = mcp_and_bus[1]
    ok = _rpc(http, "tools/call", {"name": "get_sales_performance",
                                   "arguments": {"article_number": "100008", "ref": "GR-1"}})
    assert "structuredContent" not in ok and len(ok["content"]) == 1
    failed = _rpc(http, "tools/call", {"name": "get_sales_performance",
                                       "arguments": {"article_number": "boom"}})
    assert failed["isError"] is True
    first, second = (m.json() for m in bus.messages("gpos/v1/telemetry/tool/engine/>"))
    assert (first["caller"], first["ref"], first["ok"]) == ("agent", "GR-1", True)
    assert first["summary"] == "100008: 9/35 verkauft"
    assert (second["ok"], second["ref"]) == (False, "")
    assert second["summary"] == "ValueError: Artikel unbekannt"


def test_telemetry_never_breaks_the_tool() -> None:
    class DeadBus(MemoryBus):
        def publish(self, *args: Any, **kwargs: Any) -> None:
            raise ConnectionError("broker down")

    tel = Telemetry(DeadBus(), "wws")
    tel.tool_call("get_article", "agent", "", "GR-1", 3, True, "ok")  # must not raise

    @mcputil.telemetry(tel, caller="agent")
    def get_article(article_number: str, ref: str = "") -> CallToolResult:
        return mcputil.text_result({"article_number": article_number})

    assert mcputil.result_text(get_article("100001")) == '{"article_number":"100001"}'


def test_telemetry_none_returns_the_function_unchanged() -> None:
    def tool(x: str) -> CallToolResult:
        return mcputil.text_result({"x": x})

    assert mcputil.telemetry(None, caller="agent")(tool) is tool


def test_summary_is_one_line_of_at_most_120_chars() -> None:
    assert shorten("a\nb  c") == "a b c"
    cut = shorten("x" * 200)
    assert len(cut) == 120 and cut.endswith("…")


def test_health_route(memory_bus: MemoryBus) -> None:
    good = _server(memory_bus)
    with TestClient(mcputil.http_app(good)) as client:
        reply = client.get("/health")
    assert (reply.status_code, reply.json()) == (200, {"status": "ok", "db": True, "bus": True})

    def broken() -> bool:
        raise OSError("db down")

    bad = _server(memory_bus, {"db": broken, "bus": lambda: True})
    with TestClient(mcputil.http_app(bad)) as client:
        reply = client.get("/health")
    assert (reply.status_code, reply.json()) == (503, {"status": "degraded", "db": False,
                                                       "bus": True})
