"""FastAPI receiver for Event Portal webhooks.

Path: POST /webhook/event-portal
  * verifies HMAC signature against `BRIDGE.ep.webhook_secret`
  * dedupes on `eventId`
  * dispatches to the registered handlers

Returns 200 on accept (including duplicates and unknown event types) so
Event Portal does not enter a retry loop for cases the bridge intentionally
ignores. Returns 401 on signature mismatch.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

try:
    from fastapi import FastAPI, HTTPException, Request, Response
except ImportError as exc:  # pragma: no cover - optional dep
    raise RuntimeError(
        "fastapi is required to run the bridge HTTP transport. "
        "Install with: pip install '.[bridge]'"
    ) from exc

from ..config import BridgeSettings
from ..dedupe import DedupeStore, InMemoryDedupeStore
from ..dispatcher import BridgeContext, Dispatcher
from ..signature import SignatureError, verify

logger = logging.getLogger(__name__)


def build_http_app(
    *,
    settings: BridgeSettings,
    dispatcher: Dispatcher,
    ep_client,
    om,
    dedupe: DedupeStore = None,
) -> "FastAPI":
    dedupe = dedupe or InMemoryDedupeStore(
        max_entries=settings.transport.dedupe_max_entries,
        ttl_seconds=settings.transport.dedupe_ttl_seconds,
    )
    ctx = BridgeContext(
        ep_client=ep_client, om=om, service_name=settings.om.service_name
    )

    app = FastAPI(title="om-eventportal-bridge", version="0.1.0")

    @app.get("/healthz")
    def healthz() -> Dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> Dict[str, Any]:
        return {
            "status": "ok",
            "known_event_types": sorted(dispatcher.known_event_types()),
        }

    @app.post("/webhook/event-portal")
    async def receive(request: Request) -> Response:
        body = await request.body()
        try:
            verify(
                body=body,
                headers=dict(request.headers),
                secret=settings.ep.webhook_secret,
            )
        except SignatureError as exc:
            logger.warning("Rejected webhook: %s", exc)
            raise HTTPException(status_code=401, detail=str(exc))

        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Payload must be a JSON object")

        event_id = (
            payload.get("eventId")
            or payload.get("id")
            or payload.get("messageId")
        )
        if dedupe.seen(str(event_id) if event_id else ""):
            logger.debug("Duplicate webhook id %s; skipping", event_id)
            return Response(status_code=200)

        accept = set(settings.transport.accept_event_types or [])
        event_type = payload.get("eventType") or payload.get("type") or ""
        if accept and event_type not in accept:
            logger.debug("Ignored event type %s (allowlist filter)", event_type)
            return Response(status_code=200)

        handled = dispatcher.dispatch(ctx, payload)
        logger.info(
            "Webhook id=%s type=%s handlers=%d", event_id, event_type, handled
        )
        return Response(status_code=200)

    return app
