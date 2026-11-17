"""Watchdog, R4 errors, reset, HTTP API, MCP wire and relay of engine and gate
(11.7, 11.8, 8.1)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pytest
from mcp_types import CallToolResult
from starlette.testclient import TestClient

from gposdemo.common import mcputil
from gposdemo.common.bus import MemoryBus
from gposdemo.engine import Engine
from gposdemo.engine.gate import Gate
from tests.engine.fakes import BANANEN, ENTE, PRALINEN, FakeClock, PosWriter, gebit_event
from tests.engine.flow import approval_row, approve, checked, prepared, published, staged

pytestmark = pytest.mark.db
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def rpc(client: TestClient, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    reply = client.post(mcputil.MCP_PATH, headers=HEADERS, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": arguments}})
    assert reply.status_code == 200, reply.text
    return reply.json()["result"]


@pytest.fixture
def http(engine: Engine) -> Iterator[TestClient]:
    with TestClient(mcputil.http_app(engine.mcp)) as client:
        yield client


def test_watchdog_timeouts(engine: Engine, pos: PosWriter, memory_bus: MemoryBus,
                           clock: FakeClock) -> None:
    service = engine.service
    requested = service.raise_basket_review(pos.basket([ENTE]).tx_id).review_id
    prepared_review = prepared(engine, pos, [BANANEN, ENTE], till="99")
    ready = staged(engine, prepared(engine, pos, [ENTE], till="98"), ENTE, "slow_seller", "20")
    pending_check = checked(engine, staged(engine, prepared(engine, pos, [PRALINEN]), PRALINEN,
                                           "season_end", "30",
                                           headline="Herzpralinen: Saisonrest"))
    assert service.maintenance.sweep() == {"reviews_requested": 0, "reviews_prepared": 0,
                                           "proposals_ready": 0, "proposals_pending": 0,
                                           "sam_errors": 0}
    clock.advance(61)
    counts = service.maintenance.sweep()
    assert (counts["reviews_requested"], counts["proposals_ready"]) == (1, 1)
    clock.advance(60)
    assert service.maintenance.sweep()["reviews_prepared"] == 0   # 180 s since 12.11.
    clock.advance(30)
    counts = service.maintenance.sweep()
    assert (counts["proposals_pending"], counts["reviews_prepared"]) == (1, 0)
    clock.advance(30)
    assert service.maintenance.sweep()["reviews_prepared"] == 1
    assert (service.review(requested) or {})["error"] == "SAM-Lauf nicht gestartet"
    assert (service.review(prepared_review.review_id) or {})["error"] == \
        "Agent-Zeitüberschreitung"
    assert (service.proposal(ready.proposal_id) or {})["status_reason"] == \
        "Freigabe-Lauf nicht gestartet"
    expired = service.proposal(pending_check.proposal_id) or {}
    assert (expired["state"], expired["approval"]["outcome"]) == ("expired", "expired")
    assert len(published(engine, memory_bus, "gpos/v1/review/state/failed/>")) == 2
    assert published(engine, memory_bus, "gpos/v1/proposal/expired/>")
    outcome = service.record_outcome(pending_check.proposal_id, "run-r4", "", "",
                                     "Tool approval timed out after 2 minutes")
    assert (outcome.outcome, outcome.notify_message) == (
        "expired", f"Keine Antwort binnen 2 Minuten. Ref {pending_check.proposal_id}.")


def test_sam_error_grace_and_timeout(engine: Engine, pos: PosWriter, clock: FakeClock) -> None:
    service = engine.service
    with pytest.raises(ValueError, match="rule"):
        service.sam_error("r1", "101", "01", "x")
    assert service.sam_error("r4", "101", "01", "x")["status"] == "no_pending_proposal"
    check = checked(engine, staged(engine, prepared(engine, pos, [ENTE]), ENTE, "slow_seller",
                                   "20"))
    clock.advance(125)                    # a real HIL timeout ends after the window
    first = service.sam_error("r4", "101", "01", "Tool approval timed out after 2 minutes")
    assert (first["status"], first["proposal_id"]) == ("noted", check.proposal_id)
    clock.advance(2)
    assert service.sam_error("r4", "101", "01", "duplicate errorOutput")["status"] == "noted"
    assert service.maintenance.settle_sam_errors() == 0  # grace of 5 s since the first
    clock.advance(3.5)
    assert service.maintenance.settle_sam_errors() == 1
    proposal = service.proposal(check.proposal_id) or {}
    assert (proposal["state"], proposal["status_reason"]) == ("expired",
                                                              "Keine Antwort binnen 2 Minuten")
    assert proposal["approval"]["sam_error_at"] is not None
    assert service.maintenance.settle_sam_errors() == 0


DENY_TEXT = "Agent reported error: Price approval was denied by store manager"


@pytest.mark.parametrize(("text", "after_s", "state", "reason"), [
    (DENY_TEXT, 6, "rejected", "Abgelehnt in Agent Mesh (Agent meldete einen Fehler)"),
    ("Tool approval timed out after 2 minutes", 125, "expired",
     "Keine Antwort binnen 2 Minuten"),
    ("Tool approval timed out after 2 minutes", 30, "failed", "SAM-Lauf abgebrochen"),
    ("connection refused", 6, "failed", "SAM-Lauf abgebrochen"),
])
def test_sam_error_is_settled_like_record_outcome(engine: Engine, pos: PosWriter,
                                                  clock: FakeClock, text: str,
                                                  after_s: float, state: str,
                                                  reason: str) -> None:
    """11.8: the BFF backstop classifies by decide_outcome with sam_error_at - checked_at."""
    service = engine.service
    check = checked(engine, staged(engine, prepared(engine, pos, [ENTE]), ENTE, "slow_seller",
                                   "20"))
    clock.advance(after_s)
    assert service.sam_error("p4", "101", "01", text)["status"] == "noted"
    clock.advance(6)
    assert service.maintenance.settle_sam_errors() == 1
    proposal = service.proposal(check.proposal_id) or {}
    assert (proposal["state"], proposal["status_reason"]) == (state, reason)
    assert proposal["approval"]["outcome"] == state


def test_record_fail_before_the_grace_wins(engine: Engine, pos: PosWriter,
                                           clock: FakeClock) -> None:
    check = checked(engine, staged(engine, prepared(engine, pos, [ENTE]), ENTE, "slow_seller",
                                   "20"))
    engine.service.sam_error("r4", "101", "01", "node failed")
    assert engine.service.record_outcome(check.proposal_id, "run-r4", "", "",
                                         "node failed").outcome == "failed"
    clock.advance(10)
    assert engine.service.maintenance.settle_sam_errors() == 0
    assert approval_row(engine, check.proposal_id)["outcome"] == "failed"


def test_reset_booth_and_day(engine: Engine, gate: Gate, pos: PosWriter, memory_bus: MemoryBus,
                             clock: FakeClock) -> None:
    service = engine.service
    with pytest.raises(ValueError, match="scope"):
        service.reset("all", "101")
    open_review = service.raise_basket_review(pos.basket([ENTE]).tx_id).review_id
    check = checked(engine, staged(engine, prepared(engine, pos, [PRALINEN]), PRALINEN,
                                   "season_end", "30", headline="Herzpralinen: Saisonrest"))
    other_store = prepared(engine, pos, [ENTE], till="99")
    result = service.reset("booth", "101")
    assert result == {"scope": "booth", "store_id": "101", "reviews_superseded": 1,
                      "proposals_superseded": 1, "truncated": False}
    assert (service.review(open_review) or {})["state"] == "superseded"
    assert (service.review(other_store.review_id) or {})["state"] == "prepared"
    superseded = published(engine, memory_bus, "gpos/v1/proposal/superseded/101/01/>")
    assert superseded[0]["status_reason"] == "Zurückgesetzt"
    assert approve(gate, clock, check).status == "superseded"
    outcome = service.record_outcome(check.proposal_id, "run-r4", "denied", "", "")
    assert (outcome.outcome, outcome.notify_title) == (
        "superseded", "Zurückgesetzt: Herzpralinen Valentin bleibt bei 7,99 €")
    last_id = check.proposal_id
    assert service.reset("day", "101")["truncated"] is True
    assert service.state("101", "01") == {"review": None, "proposal": None,
                                          "counts": {"reviews": 0, "proposals": 0,
                                                     "approved": 0}}
    next_stage = staged(engine, prepared(engine, pos, [ENTE]), ENTE, "slow_seller", "20")
    assert next_stage.proposal_id > last_id  # sequences are never reset


def test_http_api(engine: Engine, http: TestClient, pos: PosWriter) -> None:
    assert http.get("/health").json() == {"status": "ok", "db": True, "bus": True}
    empty = http.get("/api/state").json()
    assert empty["review"] is None and empty["counts"]["proposals"] == 0
    check = checked(engine, staged(engine, prepared(engine, pos, [ENTE]), ENTE, "slow_seller",
                                   "20"))
    state = http.get("/api/state", params={"store": "101", "till": "01"}).json()
    assert (state["proposal"]["proposal_id"], state["proposal"]["state"]) == (
        check.proposal_id, "pending")
    assert state["review"]["state"] == "proposed"
    assert state["review"]["proposal_id"] == check.proposal_id
    assert state["counts"] == {"reviews": 1, "proposals": 1, "approved": 0}
    proposal = http.get(f"/api/proposals/{check.proposal_id}").json()
    assert proposal["approval"]["apply_calls"] == 0 and proposal["approval"]["checked_at"]
    assert proposal["approval"]["first_apply_at"] is None
    assert proposal["proposal_hash"] == check.proposal_hash
    review = http.get(f"/api/reviews/{state['review']['review_id']}").json()
    assert review["agent_input"] and review["decision"]["decision"] == "propose"
    assert http.get("/api/proposals/GP-270216-9999").status_code == 404
    assert http.get("/api/reviews/GR-270216-9999").status_code == 404
    error = http.post("/api/sam-error", json={"rule": "r4", "store": "101", "till": "01",
                                               "error": "Tool approval timed out"})
    assert error.json()["status"] == "noted"
    assert http.post("/api/sam-error", json={"rule": "r9", "store": "101",
                                             "till": "01"}).status_code == 400
    assert http.post("/api/sam-error", content=b"[1]").status_code == 400
    reset = http.post("/api/reset", json={"scope": "booth", "store_id": "101"})
    assert reset.json()["proposals_superseded"] == 1
    assert http.post("/api/reset", json={"scope": "x"}).status_code == 400


def test_booth_tools_over_mcp(engine: Engine, http: TestClient, pos: PosWriter,
                              memory_bus: MemoryBus, clock: FakeClock) -> None:
    basket = pos.basket([ENTE], status="OPEN")
    raw = gebit_event("PositionAdded", basket.tx_id, 2, clock(),
                      positionId=basket.positions[0])
    wire = rpc(http, "assess_event", {"raw": raw, "run_id": "run-mcp"})
    assert wire["content"] == [{"type": "text", "text": "assess_event: scan 100001 slow_seller"}]
    assert wire["structuredContent"]["verdict"] == "scan"
    [telemetry] = memory_bus.messages("gpos/v1/telemetry/tool/engine/assess_event")
    body = telemetry.json()
    assert (body["caller"], body["run_id"], body["ok"], body["summary"]) == (
        "workflow", "run-mcp", True, "assess_event: scan 100001 slow_seller")
    rows = engine.service.ctx.db.fetch("select service, tool, caller, run_id, ok "
                                       "from engine.tool_call")
    assert rows == [{"service": "engine", "tool": "assess_event", "caller": "workflow",
                     "run_id": "run-mcp", "ok": True}]
    probe = rpc(http, "check_proposal", {"proposal_id": "probe-notify-1"})
    assert probe["content"][0]["text"] == "check_proposal: probe"
    note = rpc(http, "note_event", {"event_key": "probe-1", "verdict": "unknown"})
    assert note["structuredContent"] == {"status": "noted", "event_key": "probe-1",
                                         "verdict": "unknown"}
    prep = rpc(http, "prepare_review", {"review_id": "probe-2", "run_id": "run-p3"})
    assert prep["content"][0]["text"] == "prepare_review: no unknown"
    closed = rpc(http, "close_review", {"review_id": "probe-2", "outcome": "unknown",
                                        "rationale": ""})
    assert closed["content"][0]["text"] == "close_review: noted"
    for result in (wire, probe, note, prep, closed):
        full, text = mcputil.measure(CallToolResult.model_validate(result))
        assert full <= 1800 and text <= 1500


def test_gate_over_mcp(engine: Engine, gate: Gate, pos: PosWriter, memory_bus: MemoryBus,
                       clock: FakeClock) -> None:
    check = checked(engine, staged(engine, prepared(engine, pos, [ENTE]), ENTE, "slow_seller",
                                   "20"))
    clock.advance(4)
    with TestClient(mcputil.http_app(gate.mcp)) as client:
        assert client.get("/health").json() == {"status": "ok", "db": True, "bus": True}
        args = {k: getattr(check, k) for k in ("proposal_id", "proposal_hash", "article_name",
                                               "old_price", "new_price", "pct_label",
                                               "reason_label", "valid_to_label")}
        wire = rpc(client, "apply_price", {**args, "run_id": "run-r4", "approved_at": ""})
    action_id = wire["structuredContent"]["action_id"]
    assert wire["content"][0]["text"] == f"apply_price: status=applied action_id={action_id}"
    full, _ = mcputil.measure(CallToolResult.model_validate(wire))
    assert full < 600
    [telemetry] = memory_bus.messages("gpos/v1/telemetry/tool/gate/apply_price")
    body = telemetry.json()
    assert (body["service"], body["caller"], body["ref"], body["run_id"], body["summary"]) == (
        "gate", "agent", check.proposal_id, "run-r4",
        f"{check.proposal_id} applied {action_id}")
    [approved] = published(engine, memory_bus, "gpos/v1/proposal/approved/>")
    assert approved["action_id"] == action_id
    [message] = memory_bus.messages("gpos/v1/proposal/approved/>")
    assert message.props["source"] == "gpos-gate"


def test_threads_publish_the_outbox(engine: Engine, pos: PosWriter,
                                    memory_bus: MemoryBus) -> None:
    engine.start()
    review_id = engine.service.raise_basket_review(pos.basket([ENTE]).tx_id).review_id
    deadline = time.monotonic() + 5
    while not memory_bus.messages(f"gpos/v1/review/request/101/01/{review_id}"):
        assert time.monotonic() < deadline, "relay did not publish within 5 s"
        time.sleep(0.05)
    assert engine.watchdog.is_alive() and engine.relay.is_alive()
    engine.stop()
    assert not engine.watchdog.is_alive() and not engine.relay.is_alive()
