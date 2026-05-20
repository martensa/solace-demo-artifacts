"""Reconciliation tests (full-pull mode).

Since EP v2 does not expose an audit feed, reconcile now does a
since-watermark scan of domains and events and dispatches
`eventVersion.updated` per event. Tests verify watermark advance,
empty-result no-op, and respecting an explicit `domain_ids` restriction.
"""
from unittest.mock import MagicMock

from bridge.dispatcher import Dispatcher
from bridge.reconcile import replay_audit_since


def test_replay_dispatches_event_updated_per_event_and_advances_watermark():
    ep = MagicMock()
    ep.list_application_domains.return_value = [
        {"id": "d-1", "name": "orders", "updatedTime": "2026-05-01T09:00:00Z"},
    ]
    ep.list_events.return_value = [
        {"id": "e-1", "name": "OrderCreated", "updatedTime": "2026-05-01T10:00:00Z"},
        {"id": "e-2", "name": "OrderShipped", "updatedTime": "2026-05-01T10:05:00Z"},
    ]
    om = MagicMock()
    om.client.get.return_value = {"id": "svc-id", "extension": {}}

    dispatcher = Dispatcher()
    seen_payloads = []

    def handler(ctx, payload):
        seen_payloads.append(payload)

    dispatcher.register("eventVersion.updated", handler)

    seen, dispatched, watermark = replay_audit_since(
        ep_client=ep, om=om, service_name="solace-ep",
        since="2026-05-01T09:00:00Z", dispatcher=dispatcher,
    )

    assert seen == 2
    assert dispatched == 2
    assert {p["eventId"] for p in seen_payloads} == {"e-1", "e-2"}
    assert watermark == "2026-05-01T10:05:00Z"
    om.client.patch.assert_called_once()


def test_replay_respects_explicit_domain_ids_and_skips_list_domains():
    ep = MagicMock()
    ep.list_events.return_value = [
        {"id": "e-1", "updatedTime": "2026-05-01T10:00:00Z"},
    ]
    om = MagicMock()
    om.client.get.return_value = {"id": "svc-id", "extension": {}}

    dispatcher = Dispatcher()
    dispatcher.register("eventVersion.updated", lambda ctx, p: None)

    seen, dispatched, _ = replay_audit_since(
        ep_client=ep, om=om, service_name="solace-ep",
        since="2026-05-01T09:00:00Z", dispatcher=dispatcher,
        domain_ids=["d-1", "d-2"],
    )

    # list_application_domains should NOT have been called.
    ep.list_application_domains.assert_not_called()
    # list_events called once per supplied domain id.
    assert ep.list_events.call_count == 2
    assert seen == 2  # one event per domain
    assert dispatched == 2


def test_replay_no_events_returns_unchanged_watermark():
    ep = MagicMock()
    ep.list_application_domains.return_value = []
    om = MagicMock()
    om.client.get.return_value = {"id": "svc-id", "extension": {}}

    seen, dispatched, watermark = replay_audit_since(
        ep_client=ep, om=om, service_name="solace-ep",
        since="2026-05-01T09:00:00Z", dispatcher=Dispatcher(),
    )
    assert (seen, dispatched, watermark) == (0, 0, "2026-05-01T09:00:00Z")
    om.client.patch.assert_not_called()


def test_replay_swallows_list_events_failure_per_domain():
    """One failing domain shouldn't abort the whole reconciliation."""
    ep = MagicMock()
    ep.list_events.side_effect = [
        RuntimeError("boom"),
        [{"id": "e-2", "updatedTime": "2026-05-01T10:00:00Z"}],
    ]
    om = MagicMock()
    om.client.get.return_value = {"id": "svc-id", "extension": {}}

    dispatcher = Dispatcher()
    dispatcher.register("eventVersion.updated", lambda ctx, p: None)

    seen, dispatched, watermark = replay_audit_since(
        ep_client=ep, om=om, service_name="solace-ep",
        since="2026-05-01T09:00:00Z", dispatcher=dispatcher,
        domain_ids=["d-bad", "d-good"],
    )

    # The good domain still produced an event.
    assert seen == 1
    assert dispatched == 1
    assert watermark == "2026-05-01T10:00:00Z"
