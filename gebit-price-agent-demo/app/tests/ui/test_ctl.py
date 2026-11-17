"""``python -m gposdemo.ui.ctl``: probes (9.7, 9.8), tools-list (8.5), reset, state."""

from __future__ import annotations

import argparse
import json
import threading
from collections.abc import Callable, Iterator
from typing import Annotated, Any

import httpx
import pytest
from mcp_types import CallToolResult
from pydantic import BaseModel, Field
from starlette.testclient import TestClient

from gposdemo.common import mcputil, topics
from gposdemo.common.bus import MemoryBus
from gposdemo.common.config import Settings
from gposdemo.ui import ctl

UUID = "0b7f6c1e-1111-4a43-9a51-0c7a2f0e1b11"


@pytest.fixture
def ui_settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings("ui")


# --------------------------------------------------------------------- probe payloads
def test_p1_probe_is_a_non_gebit_cancel_on_the_probe_till(ui_settings: Settings) -> None:
    probe = ctl.build_probe("p1", ui_settings, UUID)
    assert probe.rule == "p1"
    assert probe.topic == ("gebit/rp/purchase/v2/purchase_transaction/"
                           f"PurchaseTransactionCancelled/DE/999/199/98/probe-{UUID}")
    assert probe.payload == {"@type": "type.googleapis.com/gpos.probe.Probe", "probe": "p1"}
    assert probe.expect == {"verdict": "ignore"}
    assert probe.props["eventType"] == "gpos.probe.Probe"


def test_r1_probe_uses_the_booth_till(ui_settings: Settings) -> None:
    probe = ctl.build_probe("r1", ui_settings, UUID)
    assert "/PurchaseTransactionCancelled/DE/999/101/01/probe-" in probe.topic
    assert probe.payload["probe"] == "r1"


def test_p3_and_r3_probes(ui_settings: Settings) -> None:
    p3 = ctl.build_probe("p3", ui_settings, UUID)
    assert p3.topic == f"gpos/v1/review/request/199/98/probe-{UUID}"
    assert p3.payload == {"schema_version": "1", "review_id": f"probe-{UUID}"}
    assert p3.expect == {"review_id": f"probe-{UUID}", "decision": "unknown"}
    assert ctl.build_probe("r3", ui_settings, UUID).topic.startswith(
        "gpos/v1/review/request/101/01/probe-")


def test_p4_probe(ui_settings: Settings) -> None:
    p4 = ctl.build_probe("p4", ui_settings, UUID)
    assert p4.topic == f"gpos/v1/approval/request/199/98/probe-{UUID}"
    assert p4.payload == {"schema_version": "1", "proposal_id": f"probe-{UUID}"}
    assert p4.expect == {"proposal_id": f"probe-{UUID}", "outcome": "unknown"}


def test_notify_probe_is_the_login_check_of_9_7(ui_settings: Settings) -> None:
    probe = ctl.build_probe("notify", ui_settings, UUID)
    assert probe.rule == "p4"
    assert probe.topic == f"gpos/v1/approval/request/199/98/probe-notify-{UUID}"
    assert probe.payload == {"schema_version": "1", "proposal_id": f"probe-notify-{UUID}"}
    assert probe.expect == {"proposal_id": f"probe-notify-{UUID}", "outcome": "probe"}


def test_sam_inputs_carry_exactly_the_7_2_keys(ui_settings: Settings) -> None:
    assert set(ctl.build_probe("r3", ui_settings).payload) == {"schema_version", "review_id"}
    assert set(ctl.build_probe("r4", ui_settings).payload) == {"schema_version", "proposal_id"}


def test_unknown_probe(ui_settings: Settings) -> None:
    with pytest.raises(ValueError):
        ctl.build_probe("p2", ui_settings)


# --------------------------------------------------------------------- probe runs
class FakeSam:
    """Answers a probe like SAM: on the input topic -> done/error of the rule. A review
    run (r3/p3) first calls ``close_review`` ``close_reviews`` times, whose engine
    telemetry (7.2, ``ref`` = review id) is published before the done output."""

    def __init__(self, bus: MemoryBus, rule: str, answer: Callable[[dict[str, Any]], Any],
                 outcome: str = "done", close_reviews: int = 1):
        self.bus, self.rule, self.answer, self.outcome = bus, rule, answer, outcome
        self.close_reviews = close_reviews
        self.seen: list[tuple[str, dict[str, str]]] = []
        bus.subscribe("gebit/rp/purchase/v2/>", self.on_input)
        bus.subscribe("gpos/v1/review/request/>", self.on_input)
        bus.subscribe("gpos/v1/approval/request/>", self.on_input)

    def on_input(self, topic: str, payload: bytes, props: dict[str, str]) -> None:
        self.seen.append((topic, props))
        request = json.loads(payload)
        if self.rule[1:] == "3":
            for _ in range(self.close_reviews):
                self.bus.publish(topics.telemetry_tool("engine", "close_review"), json.dumps(
                    {"schema_version": "1", "type": "tool_call", "service": "engine",
                     "tool": "close_review", "caller": "workflow",
                     "ref": request["review_id"], "run_id": "run-1", "ms": 3, "ok": True,
                     "summary": "close_review: unknown"}))
        body = self.answer(request)
        topic_out = (topics.sam_done if self.outcome == "done" else topics.sam_error)(self.rule)
        # SAM answers on its own thread, after the run
        threading.Timer(0.05, self.bus.publish, (topic_out, json.dumps(body))).start()


def test_p3_probe_passes_on_matching_done(ui_settings: Settings, memory_bus: MemoryBus) -> None:
    sam = FakeSam(memory_bus, "p3", lambda p: {"review_id": p["review_id"],
                                                "decision": "unknown", "proposal_id": "none"})
    result = ctl.run_probe(memory_bus, ctl.build_probe("p3", ui_settings), timeout=3,
                           tool_grace=0.1)
    assert result.passed, result.detail
    assert '"decision":"unknown"' in result.detail and "close_review 1x" in result.detail
    assert sam.seen[0][1]["source"] == "gpos-ui"
    assert result.line("p3").startswith("probe p3: PASS in ")


@pytest.mark.parametrize("name", ["p3", "r3"])
@pytest.mark.parametrize("calls", [0, 2])
def test_review_probe_needs_exactly_one_close_review(ui_settings: Settings,
                                                     memory_bus: MemoryBus, name: str,
                                                     calls: int) -> None:
    """9.8 step 6 / 9.5 hard rule 6: ``conclude`` must not run after ``skip``; a second
    (or a missing) close_review fails the probe although done carries ``unknown``."""
    FakeSam(memory_bus, name, lambda p: {"review_id": p["review_id"], "decision": "unknown",
                                         "proposal_id": "none"}, close_reviews=calls)
    result = ctl.run_probe(memory_bus, ctl.build_probe(name, ui_settings), timeout=3,
                           tool_grace=0.1)
    assert not result.passed
    assert f"close_review {calls}x, expected exactly 1" in result.detail


def test_close_review_of_another_run_is_not_counted(ui_settings: Settings,
                                                    memory_bus: MemoryBus) -> None:
    FakeSam(memory_bus, "p3", lambda p: {"review_id": p["review_id"], "decision": "unknown",
                                         "proposal_id": "none"})
    memory_bus.publish(topics.telemetry_tool("engine", "close_review"), json.dumps(
        {"service": "engine", "tool": "close_review", "ref": "GR-270216-0007"}))
    assert ctl.run_probe(memory_bus, ctl.build_probe("p3", ui_settings), timeout=3,
                         tool_grace=0.1).passed


def test_done_is_read_under_result(ui_settings: Settings, memory_bus: MemoryBus) -> None:
    FakeSam(memory_bus, "p4", lambda p: {"result": {"proposal_id": p["proposal_id"],
                                                    "outcome": "unknown"}})
    assert ctl.run_probe(memory_bus, ctl.build_probe("p4", ui_settings), timeout=3).passed


def test_r1_probe_passes_on_ignore(ui_settings: Settings, memory_bus: MemoryBus) -> None:
    sam = FakeSam(memory_bus, "r1", lambda _p: {"verdict": "ignore", "event_key": "",
                                                "insight": "", "review_id": "none"})
    assert ctl.run_probe(memory_bus, ctl.build_probe("r1", ui_settings), timeout=3).passed
    assert sam.seen[0][1]["eventType"] == "gpos.probe.Probe"


def test_wrong_outcome_times_out(ui_settings: Settings, memory_bus: MemoryBus) -> None:
    FakeSam(memory_bus, "p4", lambda p: {"proposal_id": p["proposal_id"], "outcome": "decided"})
    result = ctl.run_probe(memory_bus, ctl.build_probe("p4", ui_settings), timeout=0.4)
    assert not result.passed
    assert "no done/p4" in result.detail and '"outcome":"unknown"' in result.detail


@pytest.mark.parametrize("error", [
    {"error": "permission denied: notify:_:send"},
    {"error": "Workflow failed", "details": {"missing_scope": "notify:_:send"}},
])
def test_notify_without_login_fails_with_the_hint(ui_settings: Settings,
                                                  memory_bus: MemoryBus,
                                                  error: dict[str, Any]) -> None:
    FakeSam(memory_bus, "p4", lambda _p: error, outcome="error")
    result = ctl.run_probe(memory_bus, ctl.build_probe("notify", ui_settings), timeout=3)
    assert not result.passed
    assert "einmal in der SAM-WebUI als marktleitung anmelden" in result.detail


def test_error_naming_the_probe_fails_at_once(ui_settings: Settings,
                                              memory_bus: MemoryBus) -> None:
    FakeSam(memory_bus, "p3", lambda p: {"error": f"run for {p['review_id']} failed"},
            outcome="error")
    result = ctl.run_probe(memory_bus, ctl.build_probe("p3", ui_settings), timeout=3)
    assert not result.passed and "failed" in result.detail and result.seconds < 2


def test_foreign_error_is_only_a_note(ui_settings: Settings, memory_bus: MemoryBus) -> None:
    FakeSam(memory_bus, "p3", lambda _p: {"error": "another run failed"}, outcome="error")
    result = ctl.run_probe(memory_bus, ctl.build_probe("p3", ui_settings), timeout=0.4)
    assert not result.passed
    assert result.notes and "another run failed" in result.notes[0]


def test_cmd_probe_exit_codes(ui_settings: Settings, capsys: pytest.CaptureFixture[str]) -> None:
    bus = MemoryBus()
    FakeSam(bus, "p4", lambda p: {"proposal_id": p["proposal_id"], "outcome": "probe"})
    args = argparse.Namespace(name="notify", timeout=3)
    assert ctl.cmd_probe(args, ui_settings, lambda _s: bus) == 0
    assert capsys.readouterr().out.startswith("probe notify: PASS")

    def broken(_s: Settings) -> MemoryBus:
        raise ConnectionError("broker down")

    assert ctl.cmd_probe(args, ui_settings, broken) == 1
    assert "FAIL (broker not reachable" in capsys.readouterr().out


# --------------------------------------------------------------------- tools-list
def test_mcp_urls_follow_the_settings(make_settings: Callable[..., Settings]) -> None:
    cluster = make_settings("ui")
    assert {svc: ctl.mcp_base_url(cluster, svc) for svc in ctl.MCP_SERVICES} == {
        "pos": "http://gpos-pos:8771", "wws": "http://gpos-wws:8773",
        "loyalty": "http://gpos-loyalty:8772", "engine": "http://gpos-engine:8765",
        "gate": "http://gpos-gate:8766"}
    local = make_settings("ui", ENGINE_URL="http://127.0.0.1:8765",
                          WWS_GRPC="127.0.0.1:50053", POS_ADMIN_URL="http://127.0.0.1:8771")
    assert ctl.mcp_base_url(local, "gate") == "http://127.0.0.1:8766"
    assert ctl.mcp_base_url(local, "wws") == "http://127.0.0.1:8773"
    fqdn = make_settings("ui", ENGINE_URL="http://gpos-engine.gpos-demo.svc:8765")
    assert ctl.mcp_base_url(fqdn, "gate") == "http://gpos-gate.gpos-demo.svc:8766"


class Status(BaseModel):
    status: str


def mcp_server() -> Any:
    mcp = mcputil.make_server("gpos-ut-ctl", "ctl test server. Fictional data only.")

    @mcp.tool()
    def note_event(event_key: Annotated[str, Field(description="Key.")],
                   run_id: str = "") -> Annotated[CallToolResult, Status]:
        """Record an event that needs no action."""
        return mcputil.structured_result("note_event", Status(status="noted"), "noted")

    @mcp.tool(structured_output=False)
    def get_article(article_number: Annotated[str, Field(description="Number.")],
                    ref: str = "") -> CallToolResult:
        """Master data of one article (agent tool)."""
        return mcputil.text_result({"article_number": article_number})

    return mcp


@pytest.fixture
def mcp_http() -> Iterator[TestClient]:
    with TestClient(mcputil.http_app(mcp_server())) as client:
        yield client


def test_tools_list_is_the_live_tools_list(mcp_http: TestClient) -> None:
    tools = ctl.McpClient(mcp_http, "http://testserver").tools()
    by_name = {t["name"]: t for t in tools}
    assert set(by_name) == {"note_event", "get_article"}
    assert "outputSchema" in by_name["note_event"]
    assert "outputSchema" not in by_name["get_article"]
    assert by_name["get_article"]["inputSchema"]["required"] == ["article_number"]


def test_cmd_tools_list_prints_json(mcp_http: TestClient, ui_settings: Settings,
                                    capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(service="engine", url="http://testserver")
    assert ctl.cmd_tools_list(args, ui_settings, mcp_http) == 0
    printed = json.loads(capsys.readouterr().out)
    assert isinstance(printed, list) and {t["name"] for t in printed} == {"note_event",
                                                                          "get_article"}


# --------------------------------------------------------------------- reset / state
def bff_transport(calls: list[tuple[str, str, Any]], ok: bool = True) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, str(request.url), body))
        if request.url.path == "/api/demo/reset":
            return httpx.Response(200 if ok else 502, json={"ok": ok, "scope": body["scope"]})
        return httpx.Response(200, json={"store": "101", "till": "01"})

    return httpx.MockTransport(handler)


def test_cmd_reset_posts_to_the_local_bff(ui_settings: Settings,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[tuple[str, str, Any]] = []
    with httpx.Client(transport=bff_transport(calls)) as http:
        args = argparse.Namespace(scope="day", bff=None)
        assert ctl.cmd_reset(args, ui_settings, http) == 0
    assert calls == [("POST", "http://127.0.0.1:8090/api/demo/reset", {"scope": "day"})]
    assert json.loads(capsys.readouterr().out) == {"ok": True, "scope": "day"}
    with httpx.Client(transport=bff_transport(calls, ok=False)) as http:
        assert ctl.cmd_reset(argparse.Namespace(scope="booth", bff=None), ui_settings,
                             http) == 1


def test_cmd_state(ui_settings: Settings, capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[tuple[str, str, Any]] = []
    with httpx.Client(transport=bff_transport(calls)) as http:
        assert ctl.cmd_state(argparse.Namespace(bff="http://bff.test"), ui_settings, http) == 0
    assert calls[0][:2] == ("GET", "http://bff.test/api/state")
    assert json.loads(capsys.readouterr().out)["till"] == "01"


def test_parser_choices() -> None:
    parser = ctl.parser()
    assert parser.parse_args(["probe", "notify"]).name == "notify"
    assert parser.parse_args(["tools-list", "gate"]).service == "gate"
    assert parser.parse_args(["reset"]).scope == "booth"
    with pytest.raises(SystemExit):
        parser.parse_args(["probe", "r2"])
    with pytest.raises(SystemExit):
        parser.parse_args(["tools-list", "ui"])
