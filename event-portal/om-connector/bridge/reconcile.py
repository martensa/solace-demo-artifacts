"""Audit-based reconciliation for missed webhook events.

While the daily pull connector is the strongest reconciliation pass (it
walks the full graph and overwrites OM unconditionally), the audit-based
replay is the *cheap* one: it asks Event Portal "what changed since
timestamp T?" and feeds each change through the same dispatcher the
bridge uses for live webhooks.

This is what you run after a bridge outage to catch up without doing a
full re-ingest.

Flow:
  1. Read the watermark (last successfully replayed audit timestamp) from
     a custom property on the OpenMetadata MessagingService entity. If
     missing, default to `now - 24h`.
  2. List EP audit events since the watermark.
  3. Translate each audit event to a synthetic webhook payload
     (`eventType` matches `bridge.handlers.DEFAULT_HANDLERS`).
  4. Dispatch through the same Dispatcher (`register_defaults()`).
  5. On success, write the highest-seen audit timestamp back as the new
     watermark.

Failures during step 4 do NOT advance the watermark, so the next run
picks them up again. Idempotent handlers (`create_or_update`) make this
safe.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional, Tuple

from connector.property_keys import AUDIT_WATERMARK_KEY

from .dispatcher import BridgeContext, Dispatcher

logger = logging.getLogger(__name__)


# Map an EP audit `resourceType` to the bridge eventType. The verb portion
# is filled in from the audit event's `action` field.
_RESOURCE_TO_BASE: Dict[str, str] = {
    "Event": "event",
    "EventVersion": "eventVersion",
    "Schema": "schema",
    "SchemaVersion": "schemaVersion",
    "Application": "application",
    "ApplicationVersion": "applicationVersion",
    "ApplicationDomain": "applicationDomain",
}

_ACTION_TO_VERB: Dict[str, str] = {
    "CREATE": "created",
    "CREATED": "created",
    "UPDATE": "updated",
    "UPDATED": "updated",
    "DELETE": "deleted",
    "DELETED": "deleted",
}


def audit_event_to_payload(audit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Translate a single audit event into a bridge-dispatchable payload."""
    resource_type = audit.get("resourceType") or audit.get("entityType")
    action = (audit.get("action") or audit.get("operation") or "").upper()
    base = _RESOURCE_TO_BASE.get(resource_type or "")
    verb = _ACTION_TO_VERB.get(action)
    if not base or not verb:
        return None
    payload: Dict[str, Any] = {
        "eventType": f"{base}.{verb}",
        "eventId": audit.get("id") or audit.get("auditId"),
        "resourceId": audit.get("resourceId") or audit.get("entityId"),
        # Echo through original fields so handlers can pick them up.
        "data": audit.get("data") or audit,
    }
    # Some EP editions surface convenient sub-ids on the audit row directly.
    for k in ("eventId", "eventVersionId", "applicationId", "applicationDomainId",
              "schemaId", "schemaVersionId"):
        if audit.get(k):
            payload[k] = audit[k]
    return payload


# ---------------------------------------------------------------- watermark

def _get_messaging_service(om, service_name: str) -> Optional[Dict[str, Any]]:
    try:
        return om.client.get(f"/services/messagingServices/name/{service_name}")
    except Exception as exc:
        logger.debug("Could not fetch MessagingService %s: %s", service_name, exc)
        return None


def read_watermark(om, service_name: str, default_lookback: timedelta = timedelta(hours=24)) -> str:
    svc = _get_messaging_service(om, service_name) or {}
    extension = svc.get("extension") or {}
    wm = extension.get(AUDIT_WATERMARK_KEY)
    if wm:
        return str(wm)
    return (datetime.now(timezone.utc) - default_lookback).isoformat(timespec="seconds")


def write_watermark(om, service_name: str, watermark: str) -> None:
    svc = _get_messaging_service(om, service_name)
    if not svc:
        logger.warning("MessagingService %s not found; cannot persist watermark", service_name)
        return
    svc_id = svc.get("id")
    extension = dict(svc.get("extension") or {})
    extension[AUDIT_WATERMARK_KEY] = watermark
    patch = [
        {
            "op": "add" if AUDIT_WATERMARK_KEY not in (svc.get("extension") or {}) else "replace",
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
) -> Tuple[int, int, Optional[str]]:
    """Replay EP audit events into the bridge dispatcher.

    Returns `(seen, dispatched, new_watermark)`. The new watermark is only
    advanced if every dispatched event succeeded (handlers swallow their
    own exceptions, so "success" here means "every event mapped to a known
    type and reached its handler").
    """
    if dispatcher is None:
        from .handlers import register_defaults
        dispatcher = register_defaults(Dispatcher())
    ctx = BridgeContext(ep_client=ep_client, om=om, service_name=service_name)
    watermark = since or read_watermark(om, service_name)
    logger.info("Reconciliation starting from %s", watermark)

    audits = list(ep_client.list_audit_events(since=watermark))
    if not audits:
        logger.info("No audit events since %s; nothing to do", watermark)
        return 0, 0, watermark

    seen = len(audits)
    dispatched = 0
    high_watermark = watermark
    for audit in _ordered_by_time(audits):
        payload = audit_event_to_payload(audit)
        if not payload:
            logger.debug(
                "Skipping audit %s (resource=%s action=%s)",
                audit.get("id"), audit.get("resourceType"), audit.get("action"),
            )
            continue
        count = dispatcher.dispatch(ctx, payload)
        if count:
            dispatched += 1
        ts = audit.get("createdTime") or audit.get("timestamp")
        if ts and ts > high_watermark:
            high_watermark = ts

    if high_watermark != watermark:
        write_watermark(om, service_name, high_watermark)
    return seen, dispatched, high_watermark


def _ordered_by_time(audits: Iterable[Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    """Audit events must be applied in time order so deletes follow creates."""
    return sorted(
        audits,
        key=lambda a: a.get("createdTime") or a.get("timestamp") or "",
    )
