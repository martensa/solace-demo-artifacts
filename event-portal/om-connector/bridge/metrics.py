"""Prometheus metrics for the bridge (Wave 5 / #10).

Metric definitions live here (bridge layer, where prometheus_client is
installed). The connector layer never imports this module; the one
connector-side metric (EP 401s) is published through
:func:`connector.telemetry.inc_counter`, which writes to the same default
registry, so it shows up in this exposition automatically.

Everything degrades to a transparent no-op when prometheus_client is not
installed, so ``bridge.dispatcher`` / ``bridge.transport.polling`` can call
the ``observe_*`` helpers unconditionally and the lean test environment
(no prometheus) still imports and runs them.

Exposition has two shapes:
* polling / solace modes have no HTTP server, so :func:`start_metrics_server`
  starts prometheus_client's own tiny WSGI server on ``metrics_port``.
* http / forwarder modes already run FastAPI, so :func:`metrics_asgi_app`
  is mounted at ``/metrics`` on the existing app.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Optional

from connector import telemetry

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter, Gauge, Histogram

    _ENABLED = True

    DISPATCH_LATENCY = Histogram(
        "eventportal_bridge_dispatch_seconds",
        "Handler dispatch latency per event type.",
        labelnames=("event_type", "outcome"),
    )
    POLL_TICKS = Counter(
        "eventportal_bridge_poll_ticks_total",
        "Polling-loop ticks by outcome.",
        labelnames=("outcome",),
    )
    EVENTS_SEEN = Counter(
        "eventportal_bridge_events_seen_total",
        "Event Portal change events seen during polling.",
    )
    EVENTS_DISPATCHED = Counter(
        "eventportal_bridge_events_dispatched_total",
        "Event Portal change events dispatched to at least one handler.",
    )
    # Wave 4.5 / #49: OM->EP write-back queue depth + outcomes.
    WRITEBACK_QUEUE_DEPTH = Gauge(
        "eventportal_bridge_writeback_queue_depth",
        "Pending OM->EP write-back operations on the bridge queue.",
    )
    WRITEBACK_QUEUE_DEPTH.set(0)
    WRITEBACK_OPS = Counter(
        "eventportal_bridge_writeback_ops_total",
        "OM->EP write-back operations by outcome.",
        labelnames=("outcome",),
    )
except ImportError:  # pragma: no cover - exercised only without the dep
    _ENABLED = False
    DISPATCH_LATENCY = POLL_TICKS = EVENTS_SEEN = None
    EVENTS_DISPATCHED = WRITEBACK_QUEUE_DEPTH = WRITEBACK_OPS = None


def enabled() -> bool:
    return _ENABLED


@contextmanager
def time_dispatch(event_type: str):
    """Time one handler dispatch and record latency + outcome.

    Yields a one-element list so the caller can mark the outcome; defaults
    to ``ok`` and flips to ``error`` if the block raises.
    """
    outcome = ["ok"]
    start = time.perf_counter()
    try:
        yield outcome
    except Exception:
        outcome[0] = "error"
        raise
    finally:
        if _ENABLED:
            DISPATCH_LATENCY.labels(
                event_type=event_type or "<none>", outcome=outcome[0]
            ).observe(time.perf_counter() - start)


def record_tick(outcome: str, seen: int = 0, dispatched: int = 0) -> None:
    if not _ENABLED:
        return
    POLL_TICKS.labels(outcome=outcome).inc()
    if seen:
        EVENTS_SEEN.inc(seen)
    if dispatched:
        EVENTS_DISPATCHED.inc(dispatched)


def set_writeback_queue_depth(depth: int) -> None:
    """Set the OM->EP write-back queue-depth gauge (#49)."""
    if _ENABLED:
        WRITEBACK_QUEUE_DEPTH.set(depth)


def record_writeback(outcome: str) -> None:
    """Count one write-back op: applied | dry_run | error | dropped (#49)."""
    if _ENABLED:
        WRITEBACK_OPS.labels(outcome=outcome).inc()


def record_ep_auth_failure() -> None:
    """Increment the EP 401 counter (no-op without prometheus_client)."""
    telemetry.record_ep_auth_failure()


def _preregister_shared_counters() -> None:
    """Touch connector-side counters at 0 so they appear in the first scrape."""
    telemetry.inc_counter(
        telemetry.EP_AUTH_FAILURES, telemetry.EP_AUTH_FAILURES_DOC, amount=0
    )


def start_metrics_server(port: int, addr: str = "0.0.0.0") -> bool:
    """Start a standalone /metrics WSGI server (polling / solace modes)."""
    if not _ENABLED:
        logger.warning(
            "metrics_enabled but prometheus_client is not installed; "
            "/metrics disabled. Install with: pip install '.[bridge]'"
        )
        return False
    _preregister_shared_counters()
    from prometheus_client import start_http_server

    start_http_server(port, addr=addr)
    logger.info("Prometheus metrics server listening on %s:%d", addr, port)
    return True


def metrics_asgi_app() -> Optional[Any]:
    """Return an ASGI app to mount at /metrics (http / forwarder modes)."""
    if not _ENABLED:
        return None
    _preregister_shared_counters()
    from prometheus_client import make_asgi_app

    return make_asgi_app()
