"""SSE ``GET /api/events`` end to end over a real uvicorn server (10.2): retry, hello,
fan-out from the bus thread, heartbeat, throttled counters, reset."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import uvicorn
from google.protobuf import descriptor_pool

from gposdemo.common import topics
from gposdemo.common.bus import MemoryBus
from gposdemo.common.config import Settings
from gposdemo.ui import create

from .conftest import GrpcFake, HttpFake, build_gateways, gebit_payload

TX = "5b1f0c2e-8d1e-4a43-9a51-0c7a2f0e1b11"
HEARTBEAT_S = 0.3


@dataclass
class Live:
    base: str
    bus: MemoryBus
    svc: Any


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def live(settings: Settings, showcase_pool: descriptor_pool.DescriptorPool,
         wws_fake: GrpcFake, loyalty_fake: GrpcFake, engine_fake: HttpFake,
         pos_admin_fake: HttpFake) -> Iterator[Live]:
    bus = MemoryBus()
    svc = create(settings, bus, heartbeat_s=HEARTBEAT_S, gateways=build_gateways(
        settings, showcase_pool, wws_fake, loyalty_fake, engine_fake, pos_admin_fake))
    svc.start()
    svc.bootstrap.join(5)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(svc.app, host="127.0.0.1", port=port,
                                           log_level="warning", timeout_graceful_shutdown=1))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    yield Live(f"http://127.0.0.1:{port}", bus, svc)
    svc.stop()
    server.should_exit = True
    thread.join(10)
    bus.close()


class Reader:
    """Reads one SSE stream in a thread; ``frames`` are (kind, data) or ("comment", text)."""

    def __init__(self, base: str):
        self.frames: list[tuple[str, Any]] = []
        self.raw_start = ""
        self.headers: dict[str, str] = {}
        self._stop = threading.Event()
        self._client = httpx.Client(base_url=base, timeout=httpx.Timeout(10, read=None))
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self._read()
        except httpx.HTTPError:
            if not self._stop.is_set():
                raise

    def _read(self) -> None:
        with self._client.stream("GET", "/api/events") as response:
            self.headers = dict(response.headers)
            kind, data = "", []
            for line in response.iter_lines():
                if self._stop.is_set():
                    return
                if not self.raw_start:
                    self.raw_start = line
                if line.startswith(":"):
                    self.frames.append(("comment", line))
                elif line.startswith("event: "):
                    kind = line[7:]
                elif line.startswith("data: "):
                    data.append(line[6:])
                elif line.startswith("retry: "):
                    self.frames.append(("retry", line[7:]))
                elif not line and kind:
                    self.frames.append((kind, json.loads("\n".join(data))))
                    kind, data = "", []

    def wait(self, predicate: Callable[[tuple[str, Any]], bool], timeout: float = 5.0
             ) -> tuple[str, Any]:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for frame in list(self.frames):
                if predicate(frame):
                    return frame
            time.sleep(0.02)
        raise AssertionError(f"no matching frame in {self.frames}")

    def close(self) -> None:
        self._stop.set()
        self._client.close()


@pytest.fixture
def reader(live: Live) -> Iterator[Reader]:
    r = Reader(live.base)
    yield r
    r.close()


def test_stream_starts_with_retry_then_hello(live: Live, reader: Reader) -> None:
    hello = reader.wait(lambda f: f[0] == "hello")
    assert reader.frames[0] == ("retry", "2000")
    assert reader.headers["content-type"].startswith("text/event-stream")
    assert reader.headers["cache-control"] == "no-cache"
    state = hello[1]
    assert state["booth"] == {"store": "101", "till": "01"}
    assert state["bon"]["tx_id"] == "5b1f0c2e-8d1e-4a43-9a51-0c7a2f0e1b11"
    assert set(state) >= {"bon", "events", "review", "proposal", "counters"}


def test_bus_events_reach_the_browser(live: Live, reader: Reader) -> None:
    reader.wait(lambda f: f[0] == "hello")
    live.bus.publish(topics.gebit_event("basket", "PositionAdded", "DE", "999", "101", "01", TX),
                     json.dumps(gebit_payload(
                         "PositionAdded", purchaseTransactionId=TX, metadata={"offset": "3"},
                         positionId="p-1", articleNumber="100001",
                         description="GEBIT Ente (Quietscheente gelb)")))
    live.bus.publish("gpos/v1/insight/scan/101/01/" + TX, json.dumps(
        {"schema_version": "1", "type": "insight", "tx_id": TX, "store": "101", "till": "01",
         "position_id": "p-1", "code": "slow_seller", "text": "Ladenhüter: 9 von 35"},
        ensure_ascii=False))
    live.bus.publish("gpos/v1/sam/error/r4", json.dumps({"error": "Tool approval timed out"}))
    pos = reader.wait(lambda f: f[0] == "pos_event")[1]
    assert (pos["event"], pos["tx_id"], pos["to_sam"]) == ("PositionAdded", TX, True)
    insight = reader.wait(lambda f: f[0] == "insight")[1]
    assert insight["text"] == "Ladenhüter: 9 von 35"
    run = reader.wait(lambda f: f[0] == "sam_run")[1]
    assert (run["rule"], run["ok"], run["label"]) == ("r4", False, "Abgelaufen")
    assert run["provisional"] is True


def test_heartbeat_comment_when_idle(live: Live, reader: Reader) -> None:
    reader.wait(lambda f: f[0] == "hello")
    assert reader.wait(lambda f: f == ("comment", ": hb"), timeout=3)


def test_counters_are_sent_throttled(live: Live, reader: Reader) -> None:
    reader.wait(lambda f: f[0] == "hello")
    for offset in range(1, 21):
        live.bus.publish(topics.gebit_event("basket", "PositionAdded", "DE", "999", "101", "01",
                                            TX),
                         json.dumps(gebit_payload("PositionAdded", purchaseTransactionId=TX,
                                                  metadata={"offset": str(offset)})))
    last = reader.wait(lambda f: f[0] == "counters" and f[1]["pos_events"] == 20)
    assert last[1]["line"].startswith("20 Kassenereignisse → 0 SAM-Läufe")
    assert last[1]["agent_runs_by_model"] == {"fast": 0, "planning": 0}
    counters = [f for f in reader.frames if f[0] == "counters"]
    assert 1 <= len(counters) <= 3  # 20 changes, at most one event per 0.5 s


def test_reset_is_announced(live: Live, reader: Reader) -> None:
    reader.wait(lambda f: f[0] == "hello")
    response = httpx.post(f"{live.base}/api/demo/reset", json={"scope": "day"}, timeout=10)
    assert response.status_code == 200
    assert reader.wait(lambda f: f[0] == "reset")[1] == {"scope": "day"}
    assert reader.wait(lambda f: f[0] == "counters")[1]["pos_events"] == 0


def test_closing_ends_every_stream(live: Live, reader: Reader) -> None:
    reader.wait(lambda f: f[0] == "hello")
    hub = live.svc.service.hub
    assert hub.subscriber_count == 1
    hub.close_all()
    end = time.monotonic() + 5
    while hub.subscriber_count and time.monotonic() < end:
        time.sleep(0.02)
    assert hub.subscriber_count == 0
