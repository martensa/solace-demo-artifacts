from unittest.mock import MagicMock

from bridge.dispatcher import BridgeContext, Dispatcher


def test_dispatch_invokes_registered_handler():
    dispatcher = Dispatcher()
    h = MagicMock()
    dispatcher.register("event.updated", h)

    ctx = BridgeContext(ep_client=MagicMock(), om=MagicMock(), service_name="svc")
    count = dispatcher.dispatch(ctx, {"eventType": "event.updated", "eventId": "1"})

    assert count == 1
    h.assert_called_once_with(ctx, {"eventType": "event.updated", "eventId": "1"})


def test_dispatch_returns_zero_for_unknown_event_type():
    dispatcher = Dispatcher()
    ctx = BridgeContext(ep_client=MagicMock(), om=MagicMock(), service_name="svc")
    assert dispatcher.dispatch(ctx, {"eventType": "something.else"}) == 0


def test_dispatch_swallows_handler_errors():
    dispatcher = Dispatcher()
    bad = MagicMock(side_effect=RuntimeError("boom"))
    good = MagicMock()
    dispatcher.register("event.updated", bad)
    dispatcher.register("event.updated", good)

    ctx = BridgeContext(ep_client=MagicMock(), om=MagicMock(), service_name="svc")
    dispatcher.dispatch(ctx, {"eventType": "event.updated"})

    # Both handlers were attempted; bad failing did not stop good.
    bad.assert_called_once()
    good.assert_called_once()


def test_payload_without_event_type_is_noop():
    dispatcher = Dispatcher()
    h = MagicMock()
    dispatcher.register("event.updated", h)

    ctx = BridgeContext(ep_client=MagicMock(), om=MagicMock(), service_name="svc")
    assert dispatcher.dispatch(ctx, {"eventId": "x"}) == 0
    h.assert_not_called()


def test_bridge_context_tenant_prefix_defaults_empty():
    """Wave 5 (#41): BridgeContext carries the tenant prefix so handlers
    can thread the prefixed apps PipelineService; default is single-tenant."""
    ctx = BridgeContext(ep_client=MagicMock(), om=MagicMock(), service_name="svc")
    assert ctx.tenant_prefix == ""
    ctx2 = BridgeContext(
        ep_client=MagicMock(), om=MagicMock(), service_name="svc",
        tenant_prefix="t1",
    )
    assert ctx2.tenant_prefix == "t1"
