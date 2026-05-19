"""HTTP -> Solace forwarder.

Sits in front of Event Portal and turns every webhook POST into a
persistent Solace message on:

    om/sync/eventportal/<eventType>

The actual bridge then consumes from a durable queue subscribed to
`om/sync/eventportal/>`. This gives you:

  * buffering / replay if OM is down
  * an audit trail of every EP change on your event mesh
  * a clean network boundary - only the forwarder needs public ingress

The forwarder does NOT call OpenMetadata. It only verifies the EP
signature (so a poisoned payload never reaches the broker) and publishes
the raw body. The bridge re-validates on the consumer side as needed.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, Optional

try:
    from fastapi import FastAPI, HTTPException, Request, Response
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "fastapi is required: pip install '.[bridge]'"
    ) from exc

from .config import BridgeSettings
from .signature import SignatureError, verify

logger = logging.getLogger(__name__)

DEFAULT_TOPIC_PREFIX = "om/sync/eventportal"


# ---------------------------------------------------------------- publisher


class SolacePublisher:
    """Thin wrapper around the Solace messaging API.

    Lazily connects on first publish so the forwarder can boot even when
    the broker is briefly unreachable. Reconnects are handled by the
    underlying client.
    """

    def __init__(self, settings: BridgeSettings):
        self._settings = settings
        self._lock = threading.Lock()
        self._service = None
        self._publisher = None

    def _ensure_connected(self) -> None:
        if self._publisher is not None:
            return
        with self._lock:
            if self._publisher is not None:
                return
            try:
                from solace.messaging.messaging_service import MessagingService
                from solace.messaging.config.transport_security_strategy import TLS
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "solace-pubsubplus is required: pip install '.[bridge-solace]'"
                ) from exc

            ts = self._settings.transport
            broker_props = {
                "solace.messaging.transport.host": ts.solace_host,
                "solace.messaging.service.vpn-name": ts.solace_vpn,
                "solace.messaging.authentication.scheme.basic.username":
                    ts.solace_username,
                "solace.messaging.authentication.scheme.basic.password":
                    ts.solace_password,
            }
            builder = MessagingService.builder().from_properties(broker_props)
            if ts.solace_host.startswith("tcps://"):
                builder = builder.with_transport_security_strategy(
                    TLS.create().without_certificate_validation()
                )
            self._service = builder.build()
            self._service.connect()
            self._publisher = (
                self._service.create_persistent_message_publisher_builder()
                .build()
            )
            self._publisher.start()
            logger.info(
                "Solace publisher connected host=%s vpn=%s",
                ts.solace_host, ts.solace_vpn,
            )

    def publish(self, topic: str, body: bytes, properties: Dict[str, str]) -> None:
        self._ensure_connected()
        from solace.messaging.resources.topic import Topic
        from solace.messaging.publisher.outbound_message import (
            OutboundMessageBuilder,
        )

        builder = OutboundMessageBuilder()
        for k, v in (properties or {}).items():
            if v is None:
                continue
            builder.with_property(k, str(v))
        message = builder.build(bytearray(body))
        self._publisher.publish(message, Topic.of(topic))

    def close(self) -> None:
        if self._publisher:
            try:
                self._publisher.terminate(grace_period=5)
            except Exception:
                logger.exception("Publisher terminate failed")
        if self._service:
            try:
                self._service.disconnect()
            except Exception:
                logger.exception("Service disconnect failed")


# ---------------------------------------------------------------- app

def build_forwarder_app(
    *,
    settings: BridgeSettings,
    publisher: Optional[SolacePublisher] = None,
    topic_prefix: str = DEFAULT_TOPIC_PREFIX,
) -> "FastAPI":
    pub = publisher or SolacePublisher(settings)
    app = FastAPI(title="om-eventportal-forwarder", version="0.1.0")

    @app.get("/healthz")
    def healthz() -> Dict[str, str]:
        return {"status": "ok"}

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
            logger.warning("Rejected forward (bad signature): %s", exc)
            raise HTTPException(status_code=401, detail=str(exc))

        try:
            payload: Dict[str, Any] = json.loads(body or b"{}")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Payload must be a JSON object")

        event_type = (payload.get("eventType") or payload.get("type") or "unknown")
        topic = f"{topic_prefix}/{_sanitize_topic_segment(event_type)}"
        event_id = (
            payload.get("eventId") or payload.get("id") or payload.get("messageId") or ""
        )
        pub.publish(
            topic=topic,
            body=body,
            properties={
                "eventType": event_type,
                "eventId": event_id,
                "sourceSystem": "eventportal",
            },
        )
        logger.info(
            "Forwarded id=%s type=%s -> %s", event_id, event_type, topic
        )
        return Response(status_code=200)

    @app.on_event("shutdown")
    def shutdown() -> None:
        pub.close()

    return app


def _sanitize_topic_segment(s: str) -> str:
    """Solace topics use `/` as the separator; reject anything that would
    break the hierarchy and fold whitespace."""
    return (s or "unknown").replace("/", "_").replace(" ", "_").strip() or "unknown"
