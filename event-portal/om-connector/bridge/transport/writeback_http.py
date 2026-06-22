"""FastAPI receiver for OpenMetadata EntityChangeEvents (Wave 4.5 / #49).

OM Alerts post change events to ``POST /webhook/openmetadata`` (consumed
locally in the on-prem cluster -- never inbound from EP, per Cluster 6.9).
Each event is signature-verified, then enqueued onto the
``WritebackProcessor`` which maps OM-owned governance fields to EP custom
attributes and writes them back (dry-run by default).

Returns 200 on accept (including ignored events) so OM does not retry for
cases the bridge intentionally drops.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

try:
    from fastapi import FastAPI, HTTPException, Request, Response
except ImportError as exc:  # pragma: no cover - optional dep
    raise RuntimeError(
        "fastapi is required to run the bridge write-back receiver. "
        "Install with: pip install '.[bridge]'"
    ) from exc

from .. import metrics
from ..config import BridgeSettings
from ..signature import SignatureError, verify
from ..writeback import WritebackProcessor

logger = logging.getLogger(__name__)


def build_writeback_app(
    *,
    settings: BridgeSettings,
    processor: WritebackProcessor,
) -> "FastAPI":
    app = FastAPI(title="om-eventportal-writeback", version="0.1.0")

    if settings.obs.metrics_enabled:
        asgi = metrics.metrics_asgi_app()
        if asgi is not None:
            app.mount("/metrics", asgi)

    @app.get("/healthz")
    def healthz() -> Dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> Dict[str, Any]:
        return {
            "status": "ok",
            "writeback_enabled": settings.writeback.enabled,
            "dry_run": settings.writeback.dry_run,
        }

    @app.post("/webhook/openmetadata")
    async def receive(request: Request) -> Response:
        body = await request.body()
        # OM signs the webhook with an HMAC; verify with the configured
        # secret + header. Reuses the EP webhook verifier.
        try:
            verify(
                body=body,
                headers=dict(request.headers),
                secret=settings.writeback.om_webhook_secret,
                header_candidates=(settings.writeback.om_webhook_header,),
            )
        except SignatureError as exc:
            logger.warning("Rejected OM webhook: %s", exc)
            raise HTTPException(status_code=401, detail=str(exc))

        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")

        # OM may send a single change event or a batch.
        events = payload if isinstance(payload, list) else [payload]
        accepted = 0
        for event in events:
            if isinstance(event, dict) and processor.enqueue(event):
                accepted += 1
        logger.info(
            "OM webhook: received=%d enqueued=%d (enabled=%s dry_run=%s)",
            len(events), accepted,
            settings.writeback.enabled, settings.writeback.dry_run,
        )
        return Response(status_code=200)

    return app
