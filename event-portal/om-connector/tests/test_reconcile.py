"""Reconciliation tests.

Cover the pure-Python parts (audit -> payload mapping, ordering) without
needing an OM/EP backend.
"""
from unittest.mock import MagicMock

from bridge.dispatcher import BridgeContext, Dispatcher
from bridge.reconcile import audit_event_to_payload, replay_audit_since


def test_audit_event_create_event():
    audit = {
        "id": "a-1",
        "resourceType": "Event",
        "action": "CREATED",
        "resourceId": "e-1",
        "createdTime": "2026-05-01T10:00:00Z",
    }
    p = audit_event_to_payload(audit)
    assert p["eventType"] == "event.created"
    assert p["eventId"] == "a-1"
    assert p["resourceId"] == "e-1"


def test_audit_event_update_event_version():
    audit = {
        "id": "a-2",
        "resourceType": "EventVersion",
        "action": "UPDATE",
        "resourceId": "ev-2",
        "eventId": "e-2",
        "eventVersionId": "ev-2",
        "createdTime": "2026-05-01T10:05:00Z",
    }
    p = audit_event_to_payload(audit)
    assert p["eventType"] == "eventVersion.updated"
    assert p["eventVersionId"] == "ev-2"
    assert p["eventId"] == "e-2"


def test_audit_event_unknown_resource_returns_none():
    assert audit_event_to_payload({"resourceType": "Foo", "action": "UPDATE"}) is None


def test_audit_event_unknown_action_returns_none():
    assert audit_event_to_payload({"resourceType": "Event", "action": "FOO"}) is None


def test_replay_advances_watermark_and_dispatches_in_order():
    ep = MagicMock()
    # Returned out of order to verify replay sorts by createdTime.
    ep.list_audit_events.return_value = [
        {
            "id": "a-2", "resourceType": "Event", "action": "UPDATED",
            "resourceId": "e-2", "createdTime": "2026-05-01T10:05:00Z",
        },
        {
            "id": "a-1", "resourceType": "Event", "action": "CREATED",
            "resourceId": "e-1", "createdTime": "2026-05-01T10:00:00Z",
        },
    ]
    om = MagicMock()
    om.client.get.return_value = {"id": "svc-id", "extension": {}}

    dispatcher = Dispatcher()
    seen_ids = []

    def handler(ctx, payload):
        seen_ids.append(payload["resourceId"])

    dispatcher.register("event.created", handler)
    dispatcher.register("event.updated", handler)

    seen, dispatched, watermark = replay_audit_since(
        ep_client=ep, om=om, service_name="solace-ep",
        since="2026-05-01T09:00:00Z", dispatcher=dispatcher,
    )

    assert seen == 2
    assert dispatched == 2
    assert seen_ids == ["e-1", "e-2"]
    assert watermark == "2026-05-01T10:05:00Z"
    # Watermark patched onto MessagingService extension.
    om.client.patch.assert_called_once()


def test_replay_no_events_returns_unchanged_watermark():
    ep = MagicMock()
    ep.list_audit_events.return_value = []
    om = MagicMock()
    om.client.get.return_value = {"id": "svc-id", "extension": {}}

    # Pass an explicit empty dispatcher so the test doesn't import
    # bridge.handlers (which requires openmetadata-ingestion).
    seen, dispatched, watermark = replay_audit_since(
        ep_client=ep, om=om, service_name="solace-ep",
        since="2026-05-01T09:00:00Z", dispatcher=Dispatcher(),
    )
    assert (seen, dispatched, watermark) == (0, 0, "2026-05-01T09:00:00Z")
    om.client.patch.assert_not_called()
