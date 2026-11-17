"""Outbox -> relay -> solace-1 -> subscriber for a WWS price event (markers integration, db).

Direct messages only (lab, finding 20); store 199 and a topic no SAM rule subscribes.
Skips without broker credentials or when solace-1 is unreachable (``solace_settings``).
"""

from __future__ import annotations

import dataclasses
import threading
from typing import Any

import pytest

from gposdemo.common import grpcutil
from gposdemo.common.bus import make_bus
from gposdemo.common.config import Settings
from gposdemo.common.db import Db
from gposdemo.common.descriptors import WWS_SVC
from gposdemo.wws import create

from .bodies import change

pytestmark = [pytest.mark.integration, pytest.mark.db, pytest.mark.usefixtures("clean_wws")]

TOPIC = "showcase/wws/v1/price/PriceChangeApplied/DE/999/199/100001"


def test_price_change_applied_reaches_the_broker(solace_settings: Settings, scratch_db: Any,
                                                 admin_db: Db, showcase_pool: Any) -> None:
    s = dataclasses.replace(solace_settings, service="wws", dsn=scratch_db.dsn("wws"))
    bus = make_bus(s, "gpos-wws-ut")
    received: list[tuple[str, bytes, dict[str, str]]] = []
    arrived = threading.Event()

    def on_message(topic: str, payload: bytes, props: dict[str, str]) -> None:
        received.append((topic, payload, props))
        arrived.set()

    bus.subscribe(TOPIC, on_message)
    db = Db(s.dsn, 3, application_name="ut-wws-int")
    app = create(s, bus, db)
    app.start()
    try:
        client = grpcutil.Client(showcase_pool, WWS_SVC, f"localhost:{app.grpc_port}")
        action_id = client.call_json("RequestPriceChange", change("GP-270216-0990"))["actionId"]
        client.close()
        assert arrived.wait(10.0), "no PriceChangeApplied from solace-1 within 10 s"
    finally:
        app.stop()
        db.close()
        bus.close()
    [row] = admin_db.fetch("select payload_text, published_at from wws.event_outbox")
    mine = [(t, p, props) for t, p, props in received if action_id.encode() in p]
    assert mine, "received messages carry another action id"
    topic, payload, props = mine[0]
    assert topic == TOPIC and row["published_at"] is not None
    assert payload.decode("utf-8") == row["payload_text"]  # bytearray, UTF-8, unchanged
    assert props["eventType"] == "de.showcase.wws.v1.event.PriceChangeApplied"
    assert (props["source"], props["apiVersion"], props["traceId"]) == (
        "gpos-wws", "wws-v1", "GP-270216-0990")
