"""bus: Solace topic matching, MemoryBus, and SolaceBus against the lab broker."""

from __future__ import annotations

import json
import threading
import time
import uuid

import pytest

from gposdemo.common.bus import Bus, MemoryBus, SolaceBus, make_bus, topic_matches
from gposdemo.common.config import Settings


@pytest.mark.parametrize(("flt", "topic", "expected"), [
    ("gpos/v1/>", "gpos/v1/insight/scan/101/01/tx", True),
    ("gpos/v1/>", "gpos/v1", False),
    ("gpos/v1/review/request/101/01/>", "gpos/v1/review/request/101/01/GR-1", True),
    ("gpos/v1/review/request/101/01/>", "gpos/v1/review/state/requested/101/01/GR-1", False),
    ("gpos/v1/review/request/101/01/>", "gpos/v1/review/request/101/01", False),
    ("gebit/rp/purchase/v2/*/PositionAdded/DE/999/101/01/>",
     "gebit/rp/purchase/v2/basket/PositionAdded/DE/999/101/01/tx", True),
    ("gebit/rp/purchase/v2/*/PositionAdded/DE/999/101/01/>",
     "gebit/rp/purchase/v2/basket/PositionAdded/DE/999/199/99/tx", False),
    ("gpos/v1/sam/*/r4", "gpos/v1/sam/error/r4", True),
    ("gpos/v1/sam/*/r4", "gpos/v1/sam/error/r4/x", False),
    ("gpos/v1/sam/done/r*", "gpos/v1/sam/done/r3", True),
    ("gpos/v1/sam/done/r*", "gpos/v1/sam/done/p3", False),
    ("a/>/c", "a/>/c", True),          # '>' not last: literal
    ("a/b*c", "a/bxc", False),         # '*' not at the end of a level: literal
    ("a/b*c", "a/b*c", True),
    ("a/b", "a/b", True),
    ("a/b", "a/b/c", False),
])
def test_topic_matches(flt: str, topic: str, expected: bool) -> None:
    assert topic_matches(flt, topic) is expected


def test_memory_bus_delivers_and_records(memory_bus: MemoryBus) -> None:
    got: list[tuple[str, str, dict[str, str]]] = []
    memory_bus.subscribe("gpos/v1/proposal/*/101/01/>",
                         lambda t, p, props: got.append((t, p.decode(), props)))
    props: dict = {"eventType": "proposal.ready", "offset": 3}  # values become strings
    memory_bus.publish("gpos/v1/proposal/ready/101/01/GP-270216-0003", '{"a":"Glühwein"}',
                       props=props, app_message_id="GP-270216-0003:1")
    memory_bus.publish("gpos/v1/review/state/requested/101/01/GR-1", "{}")
    assert got == [("gpos/v1/proposal/ready/101/01/GP-270216-0003", '{"a":"Glühwein"}',
                    {"eventType": "proposal.ready", "offset": "3"})]
    first = memory_bus.published[0]
    assert first.app_message_id == "GP-270216-0003:1"
    assert first.json() == {"a": "Glühwein"} and first.persistent is False
    assert [m.topic for m in memory_bus.messages("gpos/v1/review/>")] == [
        "gpos/v1/review/state/requested/101/01/GR-1"]
    assert isinstance(memory_bus, Bus)


def test_memory_bus_isolates_failing_handlers(memory_bus: MemoryBus) -> None:
    seen: list[str] = []

    def boom(_t: str, _p: bytes, _props: dict[str, str]) -> None:
        raise RuntimeError("subscriber bug")

    memory_bus.subscribe("x/>", boom)
    memory_bus.subscribe("x/>", lambda t, _p, _props: seen.append(t))
    memory_bus.publish("x/y", "{}")
    assert seen == ["x/y"]
    assert [str(e) for e in memory_bus.errors] == ["subscriber bug"]


def test_memory_bus_rejects_wildcards_and_closed_use(memory_bus: MemoryBus) -> None:
    for bad in ("gpos/v1/>", "gpos/*/x", "", "a//b", "a/"):
        with pytest.raises(ValueError):
            memory_bus.publish(bad, "{}")
    memory_bus.close()
    assert not memory_bus.healthy()
    with pytest.raises(RuntimeError):
        memory_bus.publish("a/b", "{}")


def test_memory_bus_wait_for(memory_bus: MemoryBus) -> None:
    timer = threading.Timer(0.05, lambda: memory_bus.publish("a/b/c", "{}"))
    timer.start()
    assert [m.topic for m in memory_bus.wait_for("a/>", 1, timeout=2)] == ["a/b/c"]
    with pytest.raises(TimeoutError):
        memory_bus.wait_for("a/>", 2, timeout=0.05)
    memory_bus.clear()
    assert memory_bus.published == []


def test_make_bus_memory(settings: Settings) -> None:
    bus = make_bus(settings, "gpos-ut")
    assert isinstance(bus, MemoryBus)


@pytest.mark.integration
def test_solace_bus_direct_roundtrip(solace_settings: Settings) -> None:
    """Direct publish/subscribe on solace-1 (VPN default), payload bytearray, props."""
    run = uuid.uuid4().hex[:10]
    bus = make_bus(solace_settings, "gpos-ut-bus")
    assert isinstance(bus, SolaceBus)
    received: list[tuple[str, bytes, dict[str, str]]] = []
    done = threading.Event()

    def on_message(topic: str, payload: bytes, props: dict[str, str]) -> None:
        received.append((topic, payload, props))
        if len(received) == 2:
            done.set()

    try:
        assert bus.healthy()
        bus.subscribe(f"gpos/v1/ut/{run}/>", on_message)
        bus.subscribe(f"gpos/v1/ut/{run}/>", on_message)  # same filter twice: one delivery
        time.sleep(0.3)
        body = {"text": "Grüße: ä ö ü ß € −20 %", "run": run}
        bus.publish(f"gpos/v1/ut/{run}/a", json.dumps(body, ensure_ascii=False),
                    props={"eventType": "ut", "traceId": run}, app_message_id=f"{run}:1")
        bus.publish(f"gpos/v1/ut/{run}/b/c", "{}")
        bus.publish(f"gpos/v1/other/{run}", "{}")
        assert done.wait(5), f"received {len(received)} of 2"
        time.sleep(0.3)
    finally:
        bus.close()
    assert sorted(t for t, _, _ in received) == [f"gpos/v1/ut/{run}/a", f"gpos/v1/ut/{run}/b/c"]
    _, payload, props = next(r for r in received if r[0].endswith("/a"))
    assert json.loads(payload.decode("utf-8")) == body
    assert props["eventType"] == "ut" and props["traceId"] == run
