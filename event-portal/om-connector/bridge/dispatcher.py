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

        for handler in handlers:
            try:
                handler(ctx, payload)
            except Exception:
                logger.exception(
                    "Handler %s failed for %s",
                    getattr(handler, "__name__", repr(handler)),
                    event_type,
                )
        return len(handlers)
