"""Tests for bridge.metrics (Wave 5 / #10).

Requires prometheus_client (the bridge ``bridge`` extra). importorskip keeps
the lean ingestion environment green.
"""
import pytest

prom = pytest.importorskip("prometheus_client")

from bridge import metrics  # noqa: E402


def _count(name, labels=None):
    return prom.REGISTRY.get_sample_value(name, labels) or 0.0


def test_metrics_enabled_when_dep_present():
    assert metrics.enabled() is True


def test_time_dispatch_records_latency_count():
    name = "eventportal_bridge_dispatch_seconds_count"
    labels = {"event_type": "event.updated", "outcome": "ok"}
    before = _count(name, labels)
    with metrics.time_dispatch("event.updated"):
        pass
    assert _count(name, labels) == before + 1


def test_time_dispatch_marks_error_outcome_and_reraises():
    name = "eventportal_bridge_dispatch_seconds_count"
    labels = {"event_type": "event.updated", "outcome": "error"}
    before = _count(name, labels)
    with pytest.raises(RuntimeError):
        with metrics.time_dispatch("event.updated"):
            raise RuntimeError("handler blew up")
    assert _count(name, labels) == before + 1


def test_record_tick_increments_counters():
    ticks_before = _count("eventportal_bridge_poll_ticks_total", {"outcome": "ok"})
    seen_before = _count("eventportal_bridge_events_seen_total")
    disp_before = _count("eventportal_bridge_events_dispatched_total")

    metrics.record_tick("ok", seen=3, dispatched=2)

    assert _count("eventportal_bridge_poll_ticks_total", {"outcome": "ok"}) == (
        ticks_before + 1
    )
    assert _count("eventportal_bridge_events_seen_total") == seen_before + 3
    assert _count("eventportal_bridge_events_dispatched_total") == disp_before + 2


def test_record_ep_auth_failure_increments():
    from connector import telemetry

    before = _count(telemetry.EP_AUTH_FAILURES)
    metrics.record_ep_auth_failure()
    assert _count(telemetry.EP_AUTH_FAILURES) == before + 1


def test_writeback_gauge_registered_at_zero():
    assert _count("eventportal_bridge_writeback_queue_depth") == 0.0


def test_metrics_asgi_app_is_constructable():
    app = metrics.metrics_asgi_app()
    assert app is not None
    assert callable(app)
