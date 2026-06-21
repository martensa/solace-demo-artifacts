"""Structured logging for the bridge process (Wave 5 / #11).

The bridge is the slim standalone image and *owns* its root logger, so it
is the right place to install a JSON formatter and a per-tick / per-request
correlation id. The connector running inside the OpenMetadata ingestion
image deliberately does NOT call any of this -- the OM workflow engine owns
that root logger and a competing JSON formatter would corrupt the OM run
report. Keep #11 scoped to the bridge and the standalone CLIs.

No third-party dependency: the JSON formatter is hand-rolled (stdlib only)
so the connector core deps stay lean and these helpers import on any
Python the bridge runs on. When OpenTelemetry tracing is active (#63) the
JSON records also carry ``trace_id`` / ``span_id`` so logs and traces
correlate.
"""
from __future__ import annotations

import contextvars
import json
import logging
import sys
import uuid
from typing import Optional

# Set per poll-tick, per webhook request, or per CLI invocation. Threaded
# automatically through every log record by CorrelationIdFilter.
correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default="-"
)

_STD_RECORD_FIELDS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)


def new_correlation_id() -> str:
    """A short, unique id suitable for one tick / request / invocation."""
    return uuid.uuid4().hex[:12]


def set_correlation_id(value: Optional[str] = None) -> contextvars.Token:
    """Bind a correlation id to the current context.

    Returns the contextvars Token so the caller can ``reset`` it once the
    tick / request / invocation finishes.
    """
    return correlation_id.set(value or new_correlation_id())


def reset_correlation_id(token: contextvars.Token) -> None:
    """Restore the correlation id bound before ``set_correlation_id``."""
    correlation_id.reset(token)


def get_correlation_id() -> str:
    return correlation_id.get()


class CorrelationIdFilter(logging.Filter):
    """Inject the active correlation id onto every record as
    ``record.correlation_id`` (default ``-`` when none is bound)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id.get()
        return True


class JsonFormatter(logging.Formatter):
    """Render a LogRecord as a single-line JSON object.

    Fields: timestamp (ISO-8601 UTC), level, logger, message,
    correlation_id, plus trace_id/span_id when an OTel span is active and
    any structured ``extra=`` keys the caller attached. Exceptions are
    rendered into an ``exception`` string.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", correlation_id.get()),
        }
        trace_id, span_id = _trace_context()
        if trace_id:
            payload["trace_id"] = trace_id
            payload["span_id"] = span_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _STD_RECORD_FIELDS and key not in payload:
                payload[key] = value
        return json.dumps(payload, default=str, ensure_ascii=False)


def _trace_context():
    """Best-effort OTel trace context; never raises, never a hard dep."""
    try:
        from connector.telemetry import current_trace_context

        return current_trace_context()
    except Exception:  # noqa: BLE001 - logging must survive a broken shim
        return None, None


_TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s [%(correlation_id)s] :: %(message)s"


def configure_logging(fmt: str = "text", level: str = "INFO") -> None:
    """Configure the root logger for the bridge process.

    ``fmt`` is ``"text"`` (legacy human format, now with the correlation id)
    or ``"json"`` (one JSON object per line for log shippers). Replaces any
    pre-existing handlers so a second call is idempotent.
    """
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.addFilter(CorrelationIdFilter())
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(_TEXT_FORMAT))

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
