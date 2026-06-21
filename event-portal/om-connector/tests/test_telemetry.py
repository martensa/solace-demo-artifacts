"""Tests for connector.telemetry (Wave 5 / #63 + #10).

The OTel span tests require opentelemetry (the bridge's optional ``otel``
extra); they importorskip cleanly in the lean ingestion environment. The
no-op behaviour without configuration is asserted regardless.
"""
import pytest

from connector import telemetry


@pytest.fixture(autouse=True)
def _reset_tracing():
    telemetry.shutdown_tracing()
    yield
    telemetry.shutdown_tracing()


def test_span_is_noop_when_unconfigured():
    # Without configure_tracing, span() is a transparent context manager.
    with telemetry.span("anything", action="x") as sp:
        assert sp is None
    assert telemetry.current_trace_context() == (None, None)


def test_configure_tracing_disabled_returns_false():
    assert telemetry.configure_tracing(enabled=False) is False


def test_configure_tracing_records_spans_and_attributes():
    otel = pytest.importorskip("opentelemetry")
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    active = telemetry.configure_tracing(
        enabled=True,
        service_name="test-svc",
        span_processor=SimpleSpanProcessor(exporter),
    )
    assert active is True

    with telemetry.span("bridge.dispatch", action="event.updated", dropped=None):
        tid, sid = telemetry.current_trace_context()
        assert tid is not None and len(tid) == 32
        assert sid is not None and len(sid) == 16

    spans = exporter.get_finished_spans()
    assert [s.name for s in spans] == ["bridge.dispatch"]
    attrs = dict(spans[0].attributes)
    assert attrs["action"] == "event.updated"
    # None-valued attributes are dropped, not serialized as "None".
    assert "dropped" not in attrs
    assert otel is not None


def test_span_marks_error_status_and_reraises():
    pytest.importorskip("opentelemetry")
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )
    from opentelemetry.trace import StatusCode

    exporter = InMemorySpanExporter()
    telemetry.configure_tracing(
        enabled=True, span_processor=SimpleSpanProcessor(exporter)
    )

    with pytest.raises(ValueError):
        with telemetry.span("boom"):
            raise ValueError("kaboom")

    span = exporter.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.ERROR


def test_inc_counter_no_op_without_labels():
    prom = pytest.importorskip("prometheus_client")
    name = "test_telemetry_unique_total"
    before = prom.REGISTRY.get_sample_value(name) or 0.0
    telemetry.inc_counter(name, "unit test counter")
    after = prom.REGISTRY.get_sample_value(name)
    assert after == before + 1.0


def test_record_ep_auth_failure_increments():
    prom = pytest.importorskip("prometheus_client")
    before = prom.REGISTRY.get_sample_value(telemetry.EP_AUTH_FAILURES) or 0.0
    telemetry.record_ep_auth_failure()
    after = prom.REGISTRY.get_sample_value(telemetry.EP_AUTH_FAILURES)
    assert after == before + 1.0
