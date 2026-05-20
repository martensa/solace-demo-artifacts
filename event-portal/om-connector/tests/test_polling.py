"""Polling-mode tests.

We never actually sleep — the loop runs one tick by injecting a stop_event
that gets set immediately after the first tick.
"""
import threading
from unittest.mock import MagicMock

from bridge.config import (
    BridgeSettings,
    EventPortalSettings,
    OpenMetadataSettings,
    TransportSettings,
)
from bridge.dedupe import InMemoryDedupeStore
from bridge.dispatcher import Dispatcher
from bridge.transport.polling import run_polling_loop


def _settings(interval=10, domain_ids=None):
    return BridgeSettings(
        ep=EventPortalSettings(),
        om=OpenMetadataSettings(),
        transport=TransportSettings(
            mode="polling",
            polling_interval_seconds=interval,
            polling_domain_ids=domain_ids or [],
        ),
    )


def test_polling_one_tick_dispatches_each_new_event():
    ep = MagicMock()
    ep.list_application_domains.return_value = [
        {"id": "d-1", "updatedTime": "2026-05-01T09:00:00Z"},
    ]
    ep.list_events.return_value = [
        {"id": "e-1", "updatedTime": "2026-05-01T10:00:00Z"},
        {"id": "e-2", "updatedTime": "2026-05-01T10:01:00Z"},
    ]
    om = MagicMock()
    # Explicit early watermark so the event timestamps in this test
    # are actually "newer" under ISO-8601 lexicographic comparison.
    om.client.get.return_value = {
        "id": "svc-id",
        "extension": {"eventPortalAuditWatermark": "2026-04-01T00:00:00Z"},
    }

    dispatcher = Dispatcher()
    payloads = []
    dispatcher.register("eventVersion.updated", lambda c, p: payloads.append(p))

    # Stop after the first tick. The interval-sleep is replaced with a
    # function that sets the stop_event so the for-loop exits immediately.
    stop = threading.Event()
    sleeps = [0]

    def fake_sleep(_seconds):
        sleeps[0] += 1
        stop.set()

    run_polling_loop(
        settings=_settings(),
        dispatcher=dispatcher,
        ep_client=ep, om=om,
        dedupe=InMemoryDedupeStore(),
        stop_event=stop,
        sleep_fn=fake_sleep,
    )

    assert {p["eventId"] for p in payloads} == {"e-1", "e-2"}
    om.client.patch.assert_called_once()  # watermark advanced once


def test_polling_dedupes_same_event_with_unchanged_updatedTime():
    ep = MagicMock()
    ep.list_application_domains.return_value = [
        {"id": "d-1", "updatedTime": "2026-05-01T09:00:00Z"},
    ]
    ep.list_events.return_value = [
        {"id": "e-1", "updatedTime": "2026-05-01T10:00:00Z"},
    ]
    om = MagicMock()
    # Explicit early watermark so the event timestamps in this test
    # are actually "newer" under ISO-8601 lexicographic comparison.
    om.client.get.return_value = {
        "id": "svc-id",
        "extension": {"eventPortalAuditWatermark": "2026-04-01T00:00:00Z"},
    }

    dispatcher = Dispatcher()
    payloads = []
    dispatcher.register("eventVersion.updated", lambda c, p: payloads.append(p))

    dedupe = InMemoryDedupeStore()
    stop = threading.Event()
    ticks = [0]

    def fake_sleep(_seconds):
        ticks[0] += 1
        if ticks[0] >= 2:  # let the loop run two tick-sleeps before stop
            stop.set()

    # Two ticks at the same data shape — second one must be deduped.
    run_polling_loop(
        settings=_settings(interval=1),
        dispatcher=dispatcher,
        ep_client=ep, om=om,
        dedupe=dedupe,
        stop_event=stop,
        sleep_fn=fake_sleep,
    )

    # Even after multiple ticks, the (eventId, updatedTime) dedupe key
    # blocks a second dispatch.
    assert len(payloads) == 1


def test_polling_with_explicit_domain_ids_skips_list_domains():
    ep = MagicMock()
    ep.list_events.return_value = [
        {"id": "e-1", "updatedTime": "2026-05-01T10:00:00Z"},
    ]
    om = MagicMock()
    # Explicit early watermark so the event timestamps in this test
    # are actually "newer" under ISO-8601 lexicographic comparison.
    om.client.get.return_value = {
        "id": "svc-id",
        "extension": {"eventPortalAuditWatermark": "2026-04-01T00:00:00Z"},
    }

    dispatcher = Dispatcher()
    dispatcher.register("eventVersion.updated", lambda c, p: None)

    stop = threading.Event()
    run_polling_loop(
        settings=_settings(domain_ids=["d-1"]),
        dispatcher=dispatcher,
        ep_client=ep, om=om,
        dedupe=InMemoryDedupeStore(),
        stop_event=stop,
        sleep_fn=lambda _s: stop.set(),
    )

    ep.list_application_domains.assert_not_called()
    ep.list_events.assert_called_once()
    # Positional arg 0 should be the supplied domain id.
    assert ep.list_events.call_args.args[0] == "d-1"
