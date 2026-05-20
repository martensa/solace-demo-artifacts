"""Polling transport — the bridge mode for EP editions without webhooks.

Solace Cloud Event Portal v2 has no public webhook-subscription API
(verified by `scripts/smoke_ep_api.py`). This transport restores a
near-realtime sync by polling the EP REST API every N seconds for events
modified since a watermark, then dispatching through the same handlers
the HTTP / Solace transports use.

Defaults are tuned for the workshop demo: 10-second interval keeps the
"change visible in OM" promise tight enough for a live audience, while
keeping the request volume against EP modest (one list-domains call +
one list-events call per included domain per tick).

The dispatcher is exactly the one `register_defaults()` builds for the
HTTP transport, so any change you make to a handler affects all four
modes consistently.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Iterable, Optional

from ..config import BridgeSettings
from ..dedupe import DedupeStore, InMemoryDedupeStore
from ..dispatcher import BridgeContext, Dispatcher
from ..reconcile import read_watermark, write_watermark

logger = logging.getLogger(__name__)


def run_polling_loop(
    *,
    settings: BridgeSettings,
    dispatcher: Dispatcher,
    ep_client,
    om,
    dedupe: Optional[DedupeStore] = None,
    stop_event: Optional[threading.Event] = None,
    sleep_fn=time.sleep,
) -> None:
    """Run the polling loop until `stop_event` is set.

    Args:
        settings:  bridge settings (uses transport.polling_interval_seconds
                   and transport.polling_domain_ids)
        dispatcher: pre-built dispatcher (use register_defaults())
        ep_client: EventPortalClient
        om: OpenMetadata SDK
        dedupe: optional dedupe store. Default: in-memory.
        stop_event: optional event to break the loop cleanly. Default:
                    a fresh Event() that is never set (loop runs forever).
        sleep_fn: injectable for unit tests.
    """
    dedupe = dedupe or InMemoryDedupeStore(
        max_entries=settings.transport.dedupe_max_entries,
        ttl_seconds=settings.transport.dedupe_ttl_seconds,
    )
    ctx = BridgeContext(
        ep_client=ep_client, om=om, service_name=settings.om.service_name
    )
    stop_event = stop_event or threading.Event()
    interval = max(1, settings.transport.polling_interval_seconds)
    domain_ids = settings.transport.polling_domain_ids or None

    logger.info(
        "Polling loop started interval=%ds domain_ids=%s",
        interval, domain_ids or "<all>",
    )

    while not stop_event.is_set():
        try:
            seen, dispatched, _ = _tick(ctx, ep_client, om, dispatcher, dedupe,
                                        settings.om.service_name, domain_ids)
            if seen:
                logger.info("Poll tick: seen=%d dispatched=%d", seen, dispatched)
        except Exception:
            logger.exception("Polling tick failed; will retry next interval")
        # interruptible sleep so SIGTERM doesn't wait the full interval
        for _ in range(interval):
            if stop_event.is_set():
                break
            sleep_fn(1)


def _tick(
    ctx: BridgeContext,
    ep_client,
    om,
    dispatcher: Dispatcher,
    dedupe: DedupeStore,
    service_name: str,
    domain_ids: Optional[Iterable[str]],
):
    watermark = read_watermark(om, service_name)
    if domain_ids is not None:
        domains: Iterable[Dict[str, Any]] = [{"id": d} for d in domain_ids]
    else:
        domains = ep_client.list_application_domains(since=watermark)

    seen = 0
    dispatched = 0
    high_watermark = watermark
    for domain in domains:
        did = domain.get("id")
        if not did:
            continue
        try:
            events = ep_client.list_events(did, since=watermark)
        except Exception:
            logger.exception("list_events(%s) failed", did)
            continue
        for event in events:
            seen += 1
            event_id = event.get("id")
            if not event_id:
                continue
            # Dedupe on (event_id, updatedTime) so the same logical event
            # within one tick window is only dispatched once.
            ts = event.get("updatedTime") or ""
            dedupe_key = f"{event_id}:{ts}"
            if dedupe.seen(dedupe_key):
                continue
            payload = {
                "eventType": "eventVersion.updated",
                "eventId": event_id,
                "data": {"eventId": event_id},
            }
            count = dispatcher.dispatch(ctx, payload)
            if count:
                dispatched += 1
            if ts and ts > high_watermark:
                high_watermark = ts

    if high_watermark != watermark:
        write_watermark(om, service_name, high_watermark)
    return seen, dispatched, high_watermark
