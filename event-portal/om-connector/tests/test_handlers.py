"""Bridge handler tests (Wave 5 / #41 multi-tenant create-path).

bridge.handlers imports the OM SDK at module load, so these run only where
``metadata`` is installed (the Docker ingestion image / CI). importorskip
keeps the lean local environment green.
"""
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("metadata")

from bridge import handlers  # noqa: E402
from bridge.dispatcher import BridgeContext  # noqa: E402


def _ctx(tenant_prefix=""):
    ctx = BridgeContext(
        ep_client=MagicMock(), om=MagicMock(),
        service_name="t-svc", tenant_prefix=tenant_prefix,
    )
    ctx.ep_client.get_application.return_value = {
        "id": "a1", "name": "OrderService", "applicationDomainId": "d1",
    }
    ctx.ep_client.get_latest_application_version.return_value = {
        "id": "av1", "version": "1.0.0",
    }
    ctx.ep_client.get_application_domain.return_value = {"id": "d1", "name": "orders"}
    return ctx


def test_on_application_upsert_threads_tenant_prefixed_pipeline_service():
    """The webhook/polling create-path must write Pipelines under the same
    tenant-prefixed apps PipelineService the soft-delete pass sweeps."""
    ctx = _ctx(tenant_prefix="t1")
    with patch("connector.mappers.app_to_pipeline_request", return_value=None) as m:
        handlers.on_application_upsert(ctx, {"applicationId": "a1"})
    assert m.called
    assert m.call_args.kwargs["service_name"] == "t1-solace-event-portal-apps"


def test_on_application_upsert_single_tenant_uses_bare_service():
    ctx = _ctx(tenant_prefix="")
    with patch("connector.mappers.app_to_pipeline_request", return_value=None) as m:
        handlers.on_application_upsert(ctx, {"applicationId": "a1"})
    assert m.called
    assert m.call_args.kwargs["service_name"] == "solace-event-portal-apps"
