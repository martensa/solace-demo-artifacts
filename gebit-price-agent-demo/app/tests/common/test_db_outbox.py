"""db and outbox against a scratch Postgres DB (marker db; 5.1, 13.1 next_offset)."""

from __future__ import annotations

import threading
import time
from typing import Any

import psycopg
import pytest

from gposdemo.common.bus import MemoryBus
from gposdemo.common.config import Settings
from gposdemo.common.db import Db
from gposdemo.common.outbox import OutboxRelay, OutboxWriter

pytestmark = pytest.mark.db


def test_tx_commits_and_rolls_back(ut_db: Db) -> None:
    writer = OutboxWriter("ut")
    with ut_db.tx() as conn:
        writer.add(conn, aggregate_id="A", aggregate_offset=1, event_type="t", topic="a/b",
                   payload_text="{}", delivery_class="ui")
    with pytest.raises(RuntimeError), ut_db.tx() as conn:
        writer.add(conn, aggregate_id="A", aggregate_offset=2, event_type="t", topic="a/b",
                   payload_text="{}", delivery_class="ui")
        raise RuntimeError("abort")
    rows = ut_db.fetch("select aggregate_id, aggregate_offset, app_message_id, user_props "
                       "from ut.event_outbox order by id")
    assert rows == [{"aggregate_id": "A", "aggregate_offset": 1, "app_message_id": "A:1",
                     "user_props": {}}]
    assert ut_db.ping()
    assert ut_db.fetch("select 1 where false") == []


def test_add_validates(ut_db: Db) -> None:
    writer = OutboxWriter("ut")
    with ut_db.tx() as conn:
        with pytest.raises(ValueError):
            writer.add(conn, aggregate_id="A", aggregate_offset=1, event_type="t", topic="a",
                       payload_text="{}", delivery_class="gold")
        with pytest.raises(ValueError):
            writer.add(conn, aggregate_id="A", aggregate_offset=0, event_type="t", topic="a",
                       payload_text="{}", delivery_class="ui")


def test_unique_offset_per_aggregate(ut_db: Db) -> None:
    writer = OutboxWriter("ut")
    with ut_db.tx() as conn:
        writer.add(conn, aggregate_id="A", aggregate_offset=1, event_type="t", topic="a",
                   payload_text="{}", delivery_class="ui")
    with pytest.raises(psycopg.errors.UniqueViolation), ut_db.tx() as conn:
        writer.add(conn, aggregate_id="A", aggregate_offset=1, event_type="t", topic="a",
                   payload_text="{}", delivery_class="ui")


def test_next_offset_two_connections_wait_for_each_other(ut_db: Db) -> None:
    """The advisory lock serialises two writers of one aggregate (engine and gate)."""
    writer = OutboxWriter("ut")
    holding = threading.Event()
    result: dict[str, Any] = {}

    def first() -> None:
        with ut_db.tx() as conn:
            offset = writer.next_offset(conn, "GP-270216-0003")
            writer.add(conn, aggregate_id="GP-270216-0003", aggregate_offset=offset,
                       event_type="proposal.ready", topic="a", payload_text="{}",
                       delivery_class="ui")
            holding.set()
            time.sleep(0.5)
            result["first"] = offset

    thread = threading.Thread(target=first)
    thread.start()
    assert holding.wait(5)
    started = time.perf_counter()
    with ut_db.tx() as conn:
        second = writer.next_offset(conn, "GP-270216-0003")
        waited = time.perf_counter() - started
        writer.add(conn, aggregate_id="GP-270216-0003", aggregate_offset=second,
                   event_type="proposal.pending", topic="a", payload_text="{}",
                   delivery_class="ui")
    thread.join(5)
    assert (result["first"], second) == (1, 2)
    assert waited >= 0.3
    with ut_db.tx() as conn:  # other aggregates are independent
        assert writer.next_offset(conn, "GP-270216-0004") == 1


def test_next_offset_never_duplicates_under_contention(ut_db: Db) -> None:
    writer = OutboxWriter("ut")
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(15):
                with ut_db.tx() as conn:
                    offset = writer.next_offset(conn, "100001:101")
                    writer.add(conn, aggregate_id="100001:101", aggregate_offset=offset,
                               event_type="x", topic="a", payload_text="{}",
                               delivery_class="business")
        except BaseException as exc:  # noqa: BLE001 - collected for the assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert errors == []
    offsets = [r["aggregate_offset"] for r in ut_db.fetch(
        "select aggregate_offset from ut.event_outbox order by aggregate_offset")]
    assert offsets == list(range(1, 46))


def _add(db: Db, aggregate: str, offset: int, delivery_class: str, topic: str,
         payload: str = "{}") -> None:
    props: dict = {"eventType": "ev", "offset": offset}  # values become strings
    with db.tx() as conn:
        OutboxWriter("ut").add(conn, aggregate_id=aggregate, aggregate_offset=offset,
                               event_type="ev", topic=topic, payload_text=payload,
                               delivery_class=delivery_class, user_props=props)


def test_relay_drains_in_id_order_with_props(ut_db: Db, memory_bus: MemoryBus,
                                             make_settings: Any) -> None:
    _add(ut_db, "tx-1", 1, "sam_input", "gebit/x/1", '{"t":"Grüße"}')
    _add(ut_db, "tx-1", 2, "ui", "gpos/x/2")
    _add(ut_db, "tx-2", 1, "business", "gpos/x/3")
    relay = OutboxRelay(ut_db, "ut", memory_bus, make_settings("engine",
                                                               GPOS_DELIVERY="persistent"))
    assert relay.drain() == 3
    assert relay.drain() == 0
    sent = memory_bus.published
    assert [(m.topic, m.app_message_id, m.persistent) for m in sent] == [
        ("gebit/x/1", "tx-1:1", True), ("gpos/x/2", "tx-1:2", False),
        ("gpos/x/3", "tx-2:1", True)]
    assert sent[0].text() == '{"t":"Grüße"}'
    assert sent[0].props == {"eventType": "ev", "offset": "1"}
    assert ut_db.fetch("select count(*) as n from ut.event_outbox "
                       "where published_at is null") == [{"n": 0}]


def test_relay_keeps_failed_rows_and_order(ut_db: Db, settings: Settings) -> None:
    class FlakyBus(MemoryBus):
        def __init__(self) -> None:
            super().__init__()
            self.down = True

        def publish(self, topic: str, payload: str, **kw: Any) -> None:
            if self.down and topic.endswith("/2"):
                raise ConnectionError("broker down")
            super().publish(topic, payload, **kw)

    bus = FlakyBus()
    for i in (1, 2, 3):
        _add(ut_db, "tx-9", i, "ui", f"gpos/x/{i}")
    relay = OutboxRelay(ut_db, "ut", bus, settings)
    assert relay.drain() == 1
    assert [m.topic for m in bus.published] == ["gpos/x/1"]
    bus.down = False
    assert relay.drain() == 2
    assert [m.topic for m in bus.published] == ["gpos/x/1", "gpos/x/2", "gpos/x/3"]


def test_relay_thread_wakes_on_notify(ut_scratch: Any, settings: Settings) -> None:
    db = ut_scratch.db("ut", max_size=3)
    bus = MemoryBus()
    relay = OutboxRelay(db, "ut", bus, settings)
    try:
        db.fetch("truncate ut.event_outbox restart identity")
        relay.start()
        time.sleep(0.3)  # LISTEN is up
        started = time.perf_counter()
        _add(db, "tx-5", 1, "ui", "gpos/x/notify")
        assert [m.topic for m in bus.wait_for("gpos/x/>", 1, timeout=3)] == ["gpos/x/notify"]
        assert time.perf_counter() - started < 0.9  # NOTIFY, not the 1 s poll
        relay.kick()
    finally:
        relay.stop()
        db.close()
    assert not relay.is_alive()


def test_listen_calls_back_and_close_stops_it(ut_scratch: Any) -> None:
    db = ut_scratch.db("ut", max_size=2)
    calls = threading.Event()
    thread = db.listen("ut_custom", calls.set)
    time.sleep(0.3)
    db.fetch("select pg_notify('ut_custom', '')")
    assert calls.wait(3)
    db.close()
    thread.join(3)
    assert not thread.is_alive()


def test_pool_bounds_connections(ut_scratch: Any) -> None:
    db = ut_scratch.db("ut", max_size=1)
    inside = threading.Event()
    release = threading.Event()
    order: list[str] = []

    def hold() -> None:
        with db.tx():
            inside.set()
            release.wait(5)
            order.append("first")

    thread = threading.Thread(target=hold)
    thread.start()
    assert inside.wait(5)
    timer = threading.Timer(0.3, release.set)
    timer.start()
    db.fetch("select 1")  # blocks until the only connection is back
    order.append("second")
    thread.join(5)
    db.close()
    assert order == ["first", "second"]


def test_broken_connection_is_discarded(ut_scratch: Any) -> None:
    db = ut_scratch.db("ut", max_size=1)
    with db.tx() as conn:
        pid = conn.execute("select pg_backend_pid() as pid").fetchone()["pid"]
    admin = ut_scratch.admin_db()
    admin.fetch("select pg_terminate_backend(%s)", (pid,))
    admin.close()
    with pytest.raises(psycopg.OperationalError):
        db.fetch("select 1")
    assert db.fetch("select 2 as two") == [{"two": 2}]
    db.close()
