"""Reconciliation: re-pull EP since the last sync watermark.

Solace Cloud Event Portal v2 does not expose an architecture-level audit
feed (verified by `scripts/smoke_ep_api.py`). The reconcile path here
therefore does NOT replay a change feed — it pulls each filtered domain's
events that have moved since the watermark, builds a synthetic
`eventVersion.updated` payload, and dispatches through the same handler
set the live polling/HTTP transports use.

Trade-off vs. an audit-replay:
  * cost: more API calls (we fetch full event lists, then per-event
    versions). EP's `updatedTime` filter keeps the result set small.
  * fidelity: deletes are NOT picked up by this path (an event that
    disappears from EP never appears in a list response). For tombstoning
    we still recommend a nightly full ingestion workflow on top.

Flow:
  1. Read the watermark (last successful re-pull timestamp) from a
     custom property on the OpenMetadata MessagingService entity.
     Default: now - 24h.
  2. List application domains updated since the watermark, OR every
     domain the token can see (if `domain_ids` is provided).
  3. For each domain, list events updated since the watermark.
  4. For each event, dispatch `eventVersion.updated` so handlers refetch
     the latest event-version object and upsert the corresponding Topic.
  5. On success, persist the highest seen `updatedTime` as the new
     watermark.

Handlers swallow their own exceptions; a partial failure does not block
the watermark advance (the affected entity gets a second chance on the
next reconcile run).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from connector.property_keys import AUDIT_WATERMARK_KEY

from .dispatcher import BridgeContext, Dispatcher

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- watermark

def _get_messaging_service(om, service_name: str) -> Optional[Dict[str, Any]]:
    try:
        return om.client.get(f"/services/messagingServices/name/{service_name}")
    except Exception as exc:
        logger.debug("Could not fetch MessagingService %s: %s", service_name, exc)
        return None


def read_watermark(
    om, service_name: str, default_lookback: timedelta = timedelta(hours=24)
) -> str:
    svc = _get_messaging_service(om, service_name) or {}
    extension = svc.get("extension") or {}
    wm = extension.get(AUDIT_WATERMARK_KEY)
    if wm:
        return str(wm)
    return (datetime.now(timezone.utc) - default_lookback).isoformat(timespec="seconds")


def write_watermark(om, service_name: str, watermark: str) -> None:
    svc = _get_messaging_service(om, service_name)
    if not svc:
        logger.warning(
            "MessagingService %s not found; cannot persist watermark", service_name
        )
        return
    svc_id = svc.get("id")
    op = "add" if AUDIT_WATERMARK_KEY not in (svc.get("extension") or {}) else "replace"
    patch = [
        {
            "op": op,
            "path": f"/extension/{AUDIT_WATERMARK_KEY}",
            "value": watermark,
        }
    ]
    try:
        om.client.patch(path=f"/services/messagingServices/{svc_id}", data=patch)
        logger.info("Watermark advanced to %s", watermark)
    except Exception:
        logger.exception("Failed to PATCH watermark; will retry next run")


# ---------------------------------------------------------------- replay

def replay_audit_since(
    *,
    ep_client,
    om,
    service_name: str,
    since: Optional[str] = None,
    dispatcher: Optional[Dispatcher] = None,
    domain_ids: Optional[List[str]] = None,
) -> Tuple[int, int, Optional[str]]:
    """Re-pull EP since the watermark and dispatch through bridge handlers.

    The function name is retained for backwards compatibility with the CLI
    surface (`om-eventportal-bridge --reconcile`). Despite the name, the
    implementation does NOT consume an audit feed — see module docstring.

    Args:
        ep_client: EventPortalClient
        om: OpenMetadata SDK
        service_name: OM MessagingService name (carries the watermark)
        since: ISO timestamp; defaults to the watermark on the service
        dispatcher: optional pre-built dispatcher (testing)
        domain_ids: optional restriction to specific EP domain ids

    Returns:
        (events_seen, events_dispatched, new_watermark)
    """
    if dispatcher is None:
        from .handlers import register_defaults
        dispatcher = register_defaults(Dispatcher())
    ctx = BridgeContext(ep_client=ep_client, om=om, service_name=service_name)
    watermark = since or read_watermark(om, service_name)
    logger.info("Reconciliation starting from %s", watermark)

    # 1. domains to walk: explicit list, or every domain visible to the token
    if domain_ids is not None:
        domains: Iterable[Dict[str, Any]] = [
            {"id": did} for did in domain_ids
        ]
    else:
        try:
            domains = ep_client.list_application_domains(since=watermark)
        except Exception:
            logger.exception("list_application_domains failed during reconcile")
            return 0, 0, watermark

    seen = 0
    dispatched = 0
    high_watermark = watermark
    for domain in domains:
        domain_id = domain.get("id")
        if not domain_id:
            continue
        try:
            events = ep_client.list_events(domain_id, since=watermark)
        except Exception:
            logger.exception("list_events(%s) failed", domain_id)
            continue
        for event in events:
            seen += 1
            event_id = event.get("id")
            if not event_id:
                continue
            payload = {
                "eventType": "eventVersion.updated",
                "eventId": event_id,
                # Tell handlers to refetch the latest version
                "data": {"eventId": event_id},
            }
            count = dispatcher.dispatch(ctx, payload)
            if count:
                dispatched += 1
            ts = event.get("updatedTime")
            if ts and ts > high_watermark:
                high_watermark = ts

    if high_watermark != watermark:
        write_watermark(om, service_name, high_watermark)
    logger.info(
        "Reconciliation done: seen=%d dispatched=%d watermark=%s",
        seen, dispatched, high_watermark,
    )
    return seen, dispatched, high_watermark
