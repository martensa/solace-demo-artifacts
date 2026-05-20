"""Bridge entry point.

Usage:
  # Default: polling mode (works against Solace Cloud EP v2)
  python -m bridge.main

  # HTTP webhook receiver (only if your EP edition supports webhooks)
  BRIDGE_MODE=http python -m bridge.main

  # Solace consumer (when a forwarder publishes EP payloads onto a queue)
  BRIDGE_MODE=solace python -m bridge.main

  # Forwarder: receive EP webhooks, publish raw payload onto Solace
  BRIDGE_MODE=forwarder python -m bridge.main

  # Register the bridge URL with Event Portal (one-shot)
  python -m bridge.main --register-webhook https://bridge.example.com/webhook/event-portal

  # Full-pull reconciliation (catch up after an outage)
  python -m bridge.main --reconcile
  python -m bridge.main --reconcile --since 2026-05-17T00:00:00Z

Settings come from environment variables (see bridge/config.py).
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading

from .config import BridgeSettings
from .dispatcher import Dispatcher
from .handlers import register_defaults

logger = logging.getLogger(__name__)


def _build_ep_client(settings: BridgeSettings):
    from connector.event_portal_client import EventPortalClient

    return EventPortalClient(
        base_url=settings.ep.api_url, api_token=settings.ep.api_token
    )


def _build_om(settings: BridgeSettings):
    from metadata.generated.schema.entity.services.connections.metadata.openMetadataConnection import (
        OpenMetadataConnection,
    )
    from metadata.generated.schema.security.client.openMetadataJWTClientConfig import (
        OpenMetadataJWTClientConfig,
    )
    from metadata.ingestion.ometa.ometa_api import OpenMetadata

    return OpenMetadata(
        OpenMetadataConnection(
            hostPort=settings.om.host_port,
            authProvider="openmetadata",
            securityConfig=OpenMetadataJWTClientConfig(
                jwtToken=settings.om.jwt_token
            ),
        )
    )


def _register_webhook(settings: BridgeSettings, target_url: str) -> int:
    """Register a webhook with EP if the edition supports it.

    Solace Cloud Event Portal v2 has no public webhook-subscription API,
    so this exits non-zero with an explanatory message and a pointer
    to the polling mode (which solves the same use case).
    """
    from connector.event_portal_client import EventPortalNotSupported
    from .handlers import DEFAULT_HANDLERS

    ep = _build_ep_client(settings)
    try:
        sub = ep.create_webhook_subscription(
            name="openmetadata-bridge",
            target_url=target_url,
            secret=settings.ep.webhook_secret,
            event_types=[t for t, _ in DEFAULT_HANDLERS],
        )
    except EventPortalNotSupported as exc:
        print(f"Cannot register webhook: {exc}", file=sys.stderr)
        print(
            "\nWorkaround for Solace Cloud EP v2: run the bridge in "
            "polling mode (BRIDGE_MODE=polling). The same handler set "
            "applies, only the trigger is a periodic poll instead of "
            "an EP push.",
            file=sys.stderr,
        )
        return 2
    print(f"Created webhook subscription: id={sub.get('id')} url={target_url}")
    return 0


def _reconcile(settings: BridgeSettings, since: str = None) -> int:
    from .reconcile import replay_audit_since

    ep_client = _build_ep_client(settings)
    om = _build_om(settings)
    seen, dispatched, watermark = replay_audit_since(
        ep_client=ep_client,
        om=om,
        service_name=settings.om.service_name,
        since=since,
    )
    print(
        f"reconcile: events_seen={seen} dispatched={dispatched} "
        f"watermark_now={watermark}"
    )
    return 0


def main(argv=None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Solace EP -> OpenMetadata bridge")
    parser.add_argument(
        "--register-webhook",
        metavar="URL",
        help="Register the bridge's URL with Event Portal as a webhook target and exit",
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Run full-pull reconciliation once and exit",
    )
    parser.add_argument(
        "--since",
        metavar="ISO_TS",
        help="Override watermark for --reconcile (default: read from OM)",
    )
    args = parser.parse_args(argv)

    settings = BridgeSettings()

    if args.register_webhook:
        return _register_webhook(settings, args.register_webhook)

    if args.reconcile:
        return _reconcile(settings, since=args.since)

    mode = settings.transport.mode

    if mode == "polling":
        return _serve_polling(settings)
    if mode == "http":
        return _serve_http(settings)
    if mode == "forwarder":
        return _serve_forwarder(settings)
    if mode == "solace":
        return _serve_solace(settings)

    logger.error("Unknown BRIDGE_MODE: %s", mode)
    return 1


def _serve_polling(settings: BridgeSettings) -> int:
    from .transport.polling import run_polling_loop

    dispatcher = register_defaults(Dispatcher())
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    run_polling_loop(
        settings=settings,
        dispatcher=dispatcher,
        ep_client=_build_ep_client(settings),
        om=_build_om(settings),
        stop_event=stop,
    )
    return 0


def _serve_http(settings: BridgeSettings) -> int:
    try:
        import uvicorn
    except ImportError:
        logger.error("uvicorn is required: pip install '.[bridge]'")
        return 1
    from .transport.http import build_http_app

    dispatcher = register_defaults(Dispatcher())
    app = build_http_app(
        settings=settings,
        dispatcher=dispatcher,
        ep_client=_build_ep_client(settings),
        om=_build_om(settings),
    )
    uvicorn.run(
        app,
        host=settings.transport.bind_host,
        port=settings.transport.bind_port,
        log_level="info",
    )
    return 0


def _serve_forwarder(settings: BridgeSettings) -> int:
    try:
        import uvicorn
    except ImportError:
        logger.error("uvicorn is required: pip install '.[bridge]'")
        return 1
    from .forwarder import build_forwarder_app

    app = build_forwarder_app(
        settings=settings,
        topic_prefix=settings.transport.forwarder_topic_prefix,
    )
    uvicorn.run(
        app,
        host=settings.transport.bind_host,
        port=settings.transport.bind_port,
        log_level="info",
    )
    return 0


def _serve_solace(settings: BridgeSettings) -> int:
    from .transport.solace import run_solace_consumer

    dispatcher = register_defaults(Dispatcher())
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    run_solace_consumer(
        settings=settings,
        dispatcher=dispatcher,
        ep_client=_build_ep_client(settings),
        om=_build_om(settings),
        stop_event=stop,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
