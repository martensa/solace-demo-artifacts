"""Event-type dispatch for webhook payloads.

Maps an EP `eventType` to one or more handler callables. Handlers receive
the parsed payload plus a `BridgeContext` exposing the EP client and the
OpenMetadata SDK; their job is to resolve the affected objects and apply
the delta. They never mutate global state — keeps the dispatcher trivially
unit-testable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List

from connector import telemetry

from . import metrics
from .logging_setup import get_correlation_id, reset_correlation_id, set_correlation_id

logger = logging.getLogger(__name__)


@dataclass
class BridgeContext:
    """Everything a handler needs to fulfill an event."""

    ep_client: Any  # EventPortalClient
    om: Any  # OpenMetadata SDK
    service_name: str


HandlerFn = Callable[[BridgeContext, Dict[str, Any]], None]


class Dispatcher:
    def __init__(self):
        self._handlers: Dict[str, List[HandlerFn]] = {}

    def register(self, event_type: str, handler: HandlerFn) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def known_event_types(self) -> Iterable[str]:
        return self._handlers.keys()

    def dispatch(
        self,
        ctx: BridgeContext,
        payload: Dict[str, Any],
    ) -> int:
        """Run every registered handler for the payload's event type.

        Returns the number of handlers invoked. Unknown event types are
        logged at debug and counted as 0 — the webhook still 200s so EP
        doesn't enter a retry loop for events the bridge doesn't care about.
        """
        event_type = (payload.get("eventType") or payload.get("type") or "").strip()
        if not event_type:
            logger.debug("Webhook payload missing eventType: %s", payload)
            return 0

        handlers = self._handlers.get(event_type, [])
        if not handlers:
            logger.debug("No handler registered for event type %s", event_type)
            return 0

        # One correlation id per dispatched event so all handler logs for
        # the same event line up (the polling/HTTP transports may set a
        # coarser id; mint a per-event one only when none is bound).
        token = set_correlation_id() if get_correlation_id() == "-" else None
        ep_entity_id = payload.get("eventId") or payload.get("id")
        try:
            for handler in handlers:
                handler_name = getattr(handler, "__name__", repr(handler))
                # Let a handler error propagate through the span + latency
                # timer (so both record outcome=error), then catch it here
                # so one failing handler never blocks the others.
                try:
                    with metrics.time_dispatch(event_type), telemetry.span(
                        "bridge.dispatch",
                        action=event_type,
                        handler=handler_name,
                        **{"ep.entity.id": ep_entity_id},
                    ):
                        handler(ctx, payload)
                except Exception:
                    logger.exception(
                        "Handler %s failed for %s", handler_name, event_type
                    )
        finally:
            if token is not None:
                reset_correlation_id(token)
        return len(handlers)
