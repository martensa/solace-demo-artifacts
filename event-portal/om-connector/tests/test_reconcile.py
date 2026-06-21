"""Reconciliation tests (full-pull mode).

Since EP v2 does not expose an audit feed, reconcile now does a
since-watermark scan of domains and events and dispatches
`eventVersion.updated` per event. Tests verify watermark advance,
empty-result no-op, and respecting an explicit `domain_ids` restriction.
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from bridge.dispatcher import Dispatcher
from bridge.reconcile import (
    RETIRED_TAG_FQN,
    replay_audit_since,
    soft_delete_missing_entities,
)
from connector.property_keys import (
    APP_PIPELINE_SERVICE_NAME,
    CP_EP_DELETED_AT,
)


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


# --------------------------------------------------------- Wave 4 (#61)


class _FakeOMClient:
    """Tiny OM REST client double for soft-delete tests.

    ``list_responses`` is keyed by path so different list endpoints can
    return different data sets (``/topics`` vs ``/pipelines``). PATCH and
    DELETE calls are recorded for assertions.
    """

    def __init__(self, list_responses=None):
        self.list_responses = list_responses or {}
        self.patches = []
        self.deletes = []

    def get(self, path, data=None):
        return self.list_responses.get(path, {"data": [], "paging": {}})

    def patch(self, path, data=None):
        # `data` is a JSON-encoded patch string -- decode for assertions.
        if isinstance(data, (str, bytes)):
            try:
                data = json.loads(data)
            except Exception:
                pass
        self.patches.append((path, data))

    def delete(self, path):
        self.deletes.append(path)


def _make_om(client):
    om = MagicMock()
    om.client = client
    return om


def test_soft_delete_tombstones_topics_missing_from_ep():
    """A Topic under the service that no longer matches an EP event-version
    must get the Retired tag + deletedAt CP.

    Note: the connector preserves dots in version segments via
    `quote_if_dotted` so FQNs read like ``solace-ep."OrderCreated_v1.0.0"``.
    """
    ep = MagicMock()
    ep.list_application_domains.return_value = [{"id": "d-1"}]
    ep.list_events.return_value = [{"id": "e-1", "name": "OrderCreated"}]
    ep.list_event_versions.return_value = [{"id": "ev-1", "version": "1.0.0"}]
    ep.list_applications.return_value = []

    client = _FakeOMClient(
        list_responses={
            "/topics": {
                "data": [
                    {
                        "id": "t-alive",
                        "fullyQualifiedName": 'solace-ep."OrderCreated_v1.0.0"',
                        "tags": [],
                        "extension": {},
                    },
                    {
                        "id": "t-zombie",
                        "fullyQualifiedName": 'solace-ep."OrderShipped_v1.0.0"',
                        "tags": [],
                        "extension": {},
                    },
                ],
                "paging": {},
            },
            "/pipelines": {"data": [], "paging": {}},
        }
    )
    summary = soft_delete_missing_entities(
        ep_client=ep, om=_make_om(client), service_name="solace-ep",
    )

    assert summary["scanned"] == 2  # two topics walked
    assert summary["retired"] == 1
    # Patch landed on the zombie Topic, not the alive one.
    assert len(client.patches) == 1
    path, body = client.patches[0]
    assert path == "/topics/t-zombie"
    # PATCH ops include both tags and extension.
    ops_by_path = {op["path"]: op for op in body}
    assert ops_by_path["/tags"]["value"][0]["tagFQN"] == RETIRED_TAG_FQN
    assert CP_EP_DELETED_AT in ops_by_path["/extension"]["value"]


def test_soft_delete_tombstones_pipelines_missing_from_ep():
    """Same drift logic applies to Pipelines under the synthetic
    EP-apps PipelineService."""
    ep = MagicMock()
    ep.list_application_domains.return_value = [{"id": "d-1"}]
    ep.list_events.return_value = []
    ep.list_applications.return_value = [{"id": "a-1", "name": "OrderService"}]
    ep.list_application_versions.return_value = [{"id": "av-1", "version": "1.2.0"}]

    client = _FakeOMClient(
        list_responses={
            "/topics": {"data": [], "paging": {}},
            "/pipelines": {
                "data": [
                    {
                        "id": "p-alive",
                        "fullyQualifiedName": (
                            f'{APP_PIPELINE_SERVICE_NAME}."OrderService_v1.2.0"'
                        ),
                        "tags": [], "extension": {},
                    },
                    {
                        "id": "p-zombie",
                        "fullyQualifiedName": (
                            f'{APP_PIPELINE_SERVICE_NAME}."PaymentService_v1.0.0"'
                        ),
                        "tags": [], "extension": {},
                    },
                ],
                "paging": {},
            },
        }
    )
    summary = soft_delete_missing_entities(
        ep_client=ep, om=_make_om(client), service_name="solace-ep",
    )

    assert summary["retired"] == 1
    assert client.patches[0][0] == "/pipelines/p-zombie"


def test_soft_delete_is_idempotent_skips_already_retired():
    """A Topic already carrying the Retired tag must NOT be re-patched
    every cron run."""
    ep = MagicMock()
    ep.list_application_domains.return_value = [{"id": "d-1"}]
    ep.list_events.return_value = []
    ep.list_applications.return_value = []

    client = _FakeOMClient(
        list_responses={
            "/topics": {
                "data": [{
                    "id": "t-already",
                    "fullyQualifiedName": "solace-ep.OldEvent_v1_0_0",
                    "tags": [{"tagFQN": RETIRED_TAG_FQN}],
                    "extension": {CP_EP_DELETED_AT: "2026-04-01T00:00:00+00:00"},
                }],
                "paging": {},
            },
            "/pipelines": {"data": [], "paging": {}},
        }
    )
    summary = soft_delete_missing_entities(
        ep_client=ep, om=_make_om(client), service_name="solace-ep",
    )
    assert summary["retired"] == 0
    assert client.patches == []


def test_soft_delete_auto_purge_hard_deletes_aged_tombstones():
    """Tombstones older than the cutoff get hard-deleted when the
    operator passes auto_purge_after_days."""
    ep = MagicMock()
    ep.list_application_domains.return_value = []

    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    old_ts = (now - timedelta(days=45)).isoformat(timespec="seconds")
    fresh_ts = (now - timedelta(days=10)).isoformat(timespec="seconds")
    client = _FakeOMClient(
        list_responses={
            "/topics": {
                "data": [
                    {
                        "id": "t-old",
                        "fullyQualifiedName": "svc.OldEvent_v1",
                        "tags": [{"tagFQN": RETIRED_TAG_FQN}],
                        "extension": {CP_EP_DELETED_AT: old_ts},
                    },
                    {
                        "id": "t-fresh",
                        "fullyQualifiedName": "svc.FreshEvent_v1",
                        "tags": [{"tagFQN": RETIRED_TAG_FQN}],
                        "extension": {CP_EP_DELETED_AT: fresh_ts},
                    },
                ],
                "paging": {},
            },
            "/pipelines": {"data": [], "paging": {}},
        }
    )
    summary = soft_delete_missing_entities(
        ep_client=ep, om=_make_om(client),
        service_name="solace-ep",
        auto_purge_after_days=30,
        now=now,
    )
    assert summary["purged"] == 1
    # Only the aged tombstone got the hard-delete call.
    assert any("t-old" in p for p in client.deletes)
    assert not any("t-fresh" in p for p in client.deletes)


def test_soft_delete_pipeline_isolation_uses_tenant_prefix():
    """Wave 5 (#41): a per-tenant bridge must scope its pipeline soft-delete
    to its own prefixed apps PipelineService AND rebuild expected FQNs with
    the same prefix, so it never tombstones another tenant's pipelines."""
    ep = MagicMock()
    ep.list_application_domains.return_value = [{"id": "d-1"}]
    ep.list_events.return_value = []
    ep.list_applications.return_value = [{"id": "a-1", "name": "OrderService"}]
    ep.list_application_versions.return_value = [{"id": "av-1", "version": "1.2.0"}]

    prefixed_service = "t1-" + APP_PIPELINE_SERVICE_NAME
    captured = {}

    class _CapturingOMClient(_FakeOMClient):
        def get(self, path, data=None):
            if path == "/pipelines":
                captured["pipelines_params"] = data
            return super().get(path, data)

    client = _CapturingOMClient(
        list_responses={
            "/topics": {"data": [], "paging": {}},
            "/pipelines": {
                "data": [
                    {
                        "id": "p-alive",
                        "fullyQualifiedName": (
                            f'{prefixed_service}."OrderService_v1.2.0"'
                        ),
                        "tags": [], "extension": {},
                    },
                    {
                        "id": "p-zombie",
                        "fullyQualifiedName": (
                            f'{prefixed_service}."PaymentService_v1.0.0"'
                        ),
                        "tags": [], "extension": {},
                    },
                ],
                "paging": {},
            },
        }
    )
    summary = soft_delete_missing_entities(
        ep_client=ep, om=_make_om(client),
        service_name="t1-solace-ep", tenant_prefix="t1",
    )

    # The pipeline list query was scoped to the prefixed PipelineService.
    assert captured["pipelines_params"]["service"] == prefixed_service
    # Expected FQNs were rebuilt with the prefix, so the alive pipeline is
    # preserved and only the prefixed zombie is tombstoned.
    assert summary["retired"] == 1
    assert client.patches[0][0] == "/pipelines/p-zombie"


def test_soft_delete_aborts_cleanly_when_ep_unreachable():
    """If list_application_domains throws, the function must not blow up
    the cron -- return zeros and log."""
    ep = MagicMock()
    ep.list_application_domains.side_effect = RuntimeError("ep is down")
    client = _FakeOMClient()
    summary = soft_delete_missing_entities(
        ep_client=ep, om=_make_om(client), service_name="solace-ep",
    )
    assert summary == {"retired": 0, "purged": 0, "scanned": 0}
    assert client.patches == []
