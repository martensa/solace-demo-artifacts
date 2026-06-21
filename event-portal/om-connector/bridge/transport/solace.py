"""Solace consumer transport for the bridge.

Mode: a separate forwarder (or EP itself, if your edition can post to a
broker) publishes EP webhook payloads to a topic on your Solace mesh:

    om/sync/eventportal/<event-type>

The bridge subscribes via a durable queue, dedupes, then dispatches with
the same handler set the HTTP path uses. Benefits:

  * Buffering on OM downtime
  * Replay (within retention)
  * Audit (every change passed through your event mesh)
  * No public ingress required for the bridge

Trade-off: extra hop and an extra dependency (`solace-pubsubplus`).
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Optional

from ..config import BridgeSettings
from ..dedupe import DedupeStore, InMemoryDedupeStore
from ..dispatcher import BridgeContext, Dispatcher

logger = logging.getLogger(__name__)


def run_solace_consumer(
    *,
    settings: BridgeSettings,
    dispatcher: Dispatcher,
    ep_client,
    om,
    dedupe: Optional[DedupeStore] = None,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """Blocking call: connect to Solace, subscribe to the configured queue,
    and dispatch every message. Returns when `stop_event` is set.
    """
    try:
        from solace.messaging.messaging_service import MessagingService
        from solace.messaging.config.transport_security_strategy import TLS
        from solace.messaging.resources.queue import Queue
        from solace.messaging.receiver.message_receiver import MessageHandler
    except ImportError as exc:  # pragma: no cover - optional dep
        raise RuntimeError(
            "solace-pubsubplus is required for the Solace transport. "
            "Install with: pip install '.[bridge-solace]'"
        ) from exc

    dedupe = dedupe or InMemoryDedupeStore(
        max_entries=settings.transport.dedupe_max_entries,
        ttl_seconds=settings.transport.dedupe_ttl_seconds,
    )
    ctx = BridgeContext(
        ep_client=ep_client, om=om, service_name=settings.om.service_name,
        tenant_prefix=settings.om.tenant_prefix,
    )
    stop_event = stop_event or threading.Event()

    broker_props = {
        "solace.messaging.transport.host": settings.transport.solace_host,
        "solace.messaging.service.vpn-name": settings.transport.solace_vpn,
        "solace.messaging.authentication.scheme.basic.username": settings.transport.solace_username,
        "solace.messaging.authentication.scheme.basic.password": settings.transport.solace_password,
    }
    builder = MessagingService.builder().from_properties(broker_props)
    if settings.transport.solace_host.startswith("tcps://"):
        builder = builder.with_transport_security_strategy(
            TLS.create().without_certificate_validation()
        )
    service = builder.build()
    service.connect()

    class _Handler(MessageHandler):
        def on_message(self, message):
            try:
                body = message.get_payload_as_bytes() or b"{}"
                payload = json.loads(body)
            except Exception:
                logger.exception("Could not decode Solace message; acking and skipping")
                receiver.ack(message)
                return

            event_id = (
                payload.get("eventId") or payload.get("id") or payload.get("messageId")
            )
            if dedupe.seen(str(event_id) if event_id else ""):
                receiver.ack(message)
                return
            try:
                handled = dispatcher.dispatch(ctx, payload)
                logger.info(
                    "Solace msg id=%s type=%s handlers=%d",
                    event_id,
                    payload.get("eventType"),
                    handled,
                )
            finally:
                receiver.ack(message)

    receiver = (
        service.create_persistent_message_receiver_builder()
        .build(Queue.durable_exclusive_queue(settings.transport.solace_queue))
    )
    receiver.start()
    receiver.receive_async(_Handler())
    logger.info(
        "Solace consumer attached to queue=%s host=%s",
        settings.transport.solace_queue,
        settings.transport.solace_host,
    )
    try:
        stop_event.wait()
    finally:
        receiver.terminate(grace_period=5)
        service.disconnect()
