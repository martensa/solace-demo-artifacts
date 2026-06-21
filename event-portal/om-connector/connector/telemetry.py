"""Dependency-free observability shim (Wave 5 / #63 + #10).

This module is the single, lower-layer observability surface shared by
both runtime images:

* the **connector** runs *inside* the OpenMetadata ingestion image, which
  must stay lean -- so OpenTelemetry and prometheus_client are NEVER hard
  dependencies here. Every helper degrades to a transparent no-op when the
  optional package is absent.
* the **bridge** is the slim long-running image; it installs the optional
  ``otel`` extra and ``prometheus_client`` and therefore gets real spans
  and counters through the exact same call sites.

Layering rule: the connector may import this module; this module must
import neither the OpenMetadata SDK nor anything under ``bridge`` (so the
ingestion image and the bridge image can both load it). All optional
imports are performed lazily inside the functions, so importing
``connector.telemetry`` is always safe and cheap.
"""
from __future__ import annotations

import contextlib
import logging
from typing import Any, Dict, Iterator, Optional, Tuple

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Tracing (OpenTelemetry, optional)
# --------------------------------------------------------------------------- #

_TRACER: Any = None
_PROVIDER: Any = None


def configure_tracing(
    *,
    enabled: bool,
    endpoint: Optional[str] = None,
    protocol: str = "http/protobuf",
    service_name: str = "om-eventportal-bridge",
    headers: Optional[Dict[str, str]] = None,
    span_processor: Any = None,
) -> bool:
    """Install a global tracer. Returns True if tracing is now active.

    No-op (returns False) when ``enabled`` is False or the OpenTelemetry
    packages are not installed -- in which case :func:`span` stays a
    transparent context manager and :func:`current_trace_context` returns
    ``(None, None)``.

    ``span_processor`` is a test/extension seam: pass a
    ``SimpleSpanProcessor(InMemorySpanExporter())`` to capture spans in a
    unit test without touching the network. Production passes None and an
    OTLP exporter is built from ``endpoint`` + ``protocol``.
    """
    global _TRACER, _PROVIDER
    if not enabled:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning(
            "otel_enabled but opentelemetry is not installed; "
            "tracing disabled. Install with: pip install '.[otel]'"
        )
        return False

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    processor = span_processor
    if processor is None:
        processor = _build_otlp_processor(
            BatchSpanProcessor, endpoint=endpoint, protocol=protocol, headers=headers
        )
    if processor is None:
        return False
    provider.add_span_processor(processor)

    # Bind our tracer to the provider we just built. We also publish it as
    # the global provider so any OTel-instrumented library shares it, but we
    # never rely on the global getter: set_tracer_provider() is a one-shot
    # per process, so reading it back would hand later callers (and tests)
    # the FIRST provider. provider.get_tracer() always returns ours.
    try:
        trace.set_tracer_provider(provider)
    except Exception:  # noqa: BLE001 - already-set is just a warning
        pass
    _PROVIDER = provider
    _TRACER = provider.get_tracer("connector.telemetry")
    logger.info(
        "OpenTelemetry tracing enabled service=%s endpoint=%s protocol=%s",
        service_name, endpoint or "<default>", protocol,
    )
    return True


def _build_otlp_processor(batch_cls, *, endpoint, protocol, headers):
    """Build an OTLP span processor for the requested protocol, or None."""
    try:
        if protocol == "grpc":
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
        else:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
    except ImportError:
        logger.warning(
            "otel_enabled but the OTLP %s exporter is not installed; "
            "tracing disabled. Install with: pip install '.[otel]'",
            protocol,
        )
        return None
    kwargs: Dict[str, Any] = {}
    if endpoint:
        kwargs["endpoint"] = endpoint
    if headers:
        kwargs["headers"] = headers
    return batch_cls(OTLPSpanExporter(**kwargs))


@contextlib.contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """Start a span if tracing is active, else a transparent no-op.

    On exception the span is marked ERROR and the exception recorded; the
    exception always propagates. ``None``-valued attributes are dropped so
    callers can pass optional ids inline.
    """
    if _TRACER is None:
        yield None
        return
    from opentelemetry.trace import Status, StatusCode

    with _TRACER.start_as_current_span(name) as sp:
        for key, value in attributes.items():
            if value is not None:
                sp.set_attribute(key, value)
        try:
            yield sp
        except Exception as exc:  # noqa: BLE001 - re-raised below
            sp.set_status(Status(StatusCode.ERROR, str(exc)))
            sp.record_exception(exc)
            raise


def current_trace_context() -> Tuple[Optional[str], Optional[str]]:
    """Return ``(trace_id_hex, span_id_hex)`` for the active span, or
    ``(None, None)`` when tracing is off or no span is active. Used by the
    bridge JSON log formatter to correlate logs with traces (#11 <-> #63).
    """
    if _TRACER is None:
        return None, None
    try:
        from opentelemetry import trace

        ctx = trace.get_current_span().get_span_context()
        if not ctx or not ctx.is_valid:
            return None, None
        return f"{ctx.trace_id:032x}", f"{ctx.span_id:016x}"
    except Exception:  # noqa: BLE001 - never let telemetry break callers
        return None, None


def shutdown_tracing() -> None:
    """Flush + shut down the tracer provider (graceful shutdown / #13)."""
    global _TRACER, _PROVIDER
    provider, _PROVIDER, _TRACER = _PROVIDER, None, None
    if provider is None:
        return
    try:
        provider.shutdown()
    except Exception:  # noqa: BLE001 - shutdown must never raise
        logger.debug("tracer provider shutdown raised; ignoring", exc_info=True)


# --------------------------------------------------------------------------- #
# Counters (prometheus_client, optional)
# --------------------------------------------------------------------------- #

_COUNTERS: Dict[str, Any] = {}

# Connector-side metric: the EP client lives in the connector layer and may
# not import ``bridge.metrics``, so the one metric it emits is defined here
# and surfaces in the bridge's /metrics exposition via the shared registry.
EP_AUTH_FAILURES = "eventportal_ep_auth_failures_total"
EP_AUTH_FAILURES_DOC = "Event Portal API authentication failures (HTTP 401)."


def record_ep_auth_failure() -> None:
    """Count one EP API 401 (no-op without prometheus_client / #10)."""
    inc_counter(EP_AUTH_FAILURES, EP_AUTH_FAILURES_DOC)


def inc_counter(
    name: str,
    documentation: str,
    amount: float = 1.0,
    labels: Optional[Dict[str, str]] = None,
) -> None:
    """Increment a process-wide prometheus counter (no-op without the dep).

    The counter is lazily created in prometheus_client's default registry
    and cached by name, so the bridge's ``/metrics`` exposition picks it up
    automatically. Label names are fixed on first use; pass the same keys
    every time. ``amount=0`` is a convenient way to pre-register a counter
    at zero so dashboards see it before the first real event.
    """
    counter = _get_counter(name, documentation, tuple(sorted(labels)) if labels else ())
    if counter is None:
        return
    try:
        if labels:
            counter.labels(**labels).inc(amount)
        else:
            counter.inc(amount)
    except Exception:  # noqa: BLE001 - metrics must never break callers
        logger.debug("counter %s inc failed; ignoring", name, exc_info=True)


def _get_counter(name: str, documentation: str, labelnames: Tuple[str, ...]) -> Any:
    cached = _COUNTERS.get(name)
    if cached is not None:
        return cached
    try:
        from prometheus_client import Counter
    except ImportError:
        return None
    counter = Counter(name, documentation, labelnames)
    _COUNTERS[name] = counter
    return counter
