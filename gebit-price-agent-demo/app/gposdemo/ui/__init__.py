"""``gpos-ui``: BFF with /kasse, /monitor, POS facade, SSE and reset (UC1-BUILD-SPEC 10).

``create(settings, bus, db)`` follows the service contract of 2.4: ``start()`` (not
blocking: bus subscriptions, counters ticker, first receipt refresh), ``stop()``,
``service`` (:class:`~gposdemo.ui.bff.Bff`), ``app`` (FastAPI) and ``mcp`` (``None``:
the UI has no MCP server). ``run()`` serves the app with uvicorn on ``HTTP_PORT``
(8090). The UI has no database role; ``db`` is accepted for the uniform signature and
must be ``None``.
"""

from __future__ import annotations

import logging
import signal
import threading
from types import FrameType
from typing import Any

import uvicorn

from ..common import log as logsetup
from ..common.bus import Bus, make_bus
from ..common.config import Settings, load_settings
from ..common.db import Db
from ..common.descriptors import load_pool
from ..common.topics import UI_SUBSCRIPTIONS, parse_location
from . import refdata
from .bff import Bff, Gateways, build_app
from .clients import EngineClient, LoyaltyClient, PosAdminClient, WwsClient
from .counters import Counters
from .facade import PosFacade
from .feed import HEARTBEAT_S, Hub

log = logging.getLogger(__name__)

COUNTERS_INTERVAL_S = 0.5  # counters event at most 2/s (10.2)
SHUTDOWN_GRACE_S = 3
BOOTSTRAP_JOIN_S = 5.0


class CountersTicker(threading.Thread):
    """Sends ``counters`` when they changed, at most every 0.5 s."""

    def __init__(self, hub: Hub, interval: float = COUNTERS_INTERVAL_S):
        super().__init__(name="counters", daemon=True)
        self.hub = hub
        self.interval = interval
        self._stop_event = threading.Event()
        self._sent = hub.counters.version

    def flush(self) -> bool:
        """Broadcast the counters if they changed since the last flush."""
        version = self.hub.counters.version
        if version == self._sent:
            return False
        self._sent = version
        self.hub.broadcast("counters", self.hub.counters.to_dict())
        return True

    def run(self) -> None:
        while not self._stop_event.wait(self.interval):
            self.flush()

    def stop(self) -> None:
        self._stop_event.set()


class Service:
    """The running ``gpos-ui`` (2.4 service contract)."""

    mcp: Any = None  # the UI serves no MCP tools

    def __init__(self, settings: Settings, bus: Bus, bff: Bff, heartbeat_s: float):
        self.settings = settings
        self.bus = bus
        self.service = bff
        self.app = build_app(bff, heartbeat_s)
        self.ticker = CountersTicker(bff.hub)
        self.bootstrap = threading.Thread(target=bff.refresh_bon, args=(bff.booth_till,),
                                          name="bon-refresh", daemon=True)

    def start(self) -> None:
        """Subscribe the three UI filters, start the ticker, refresh the booth receipt
        in the background (POS may still be starting)."""
        for topic_filter in UI_SUBSCRIPTIONS:
            self.bus.subscribe(topic_filter, self.service.on_message)
        self.ticker.start()
        self.bootstrap.start()
        log.info("gpos-ui started: %d subscriptions, booth %s/%s", len(UI_SUBSCRIPTIONS),
                 *self.service.hub.booth)

    def stop(self) -> None:
        """End SSE streams, stop the ticker, close the clients (the bus belongs to the
        caller)."""
        self.ticker.stop()
        if self.bootstrap.is_alive():
            self.bootstrap.join(BOOTSTRAP_JOIN_S)
        self.service.hub.close_all()
        self.service.close()


def gateways_from_settings(settings: Settings) -> Gateways:
    """Real clients: GEBIT facade (runtime descriptors), Showcase gRPC, HTTP."""
    showcase = load_pool([settings.showcase_descriptor_set])
    return Gateways(
        facade=PosFacade.from_settings(settings),
        wws=WwsClient(showcase, settings.wws_grpc),
        loyalty=LoyaltyClient(showcase, settings.loyalty_grpc),
        engine=EngineClient(settings.engine_url),
        pos_admin=PosAdminClient(settings.pos_admin_url))


def create(settings: Settings, bus: Bus, db: Db | None = None, *,
           gateways: Gateways | None = None, heartbeat_s: float = HEARTBEAT_S) -> Service:
    """Build the UI service (not started). ``gateways`` replaces the real clients (tests)."""
    if db is not None:
        raise ValueError("gpos-ui has no database role (2.2); pass db=None")
    data = refdata.load(settings.data_dir)
    hub = Hub(settings.booth_location, settings.tz, data,
              Counters(*parse_location(settings.booth_location)[2:]))
    bff = Bff(settings, bus, hub, gateways or gateways_from_settings(settings), data)
    return Service(settings, bus, bff, heartbeat_s)


def _exit_on_sigterm(_signum: int, _frame: FrameType | None) -> None:
    raise SystemExit(0)


def run() -> None:
    """``python -m gposdemo.ui``: serve on ``HTTP_PORT`` until SIGTERM.

    uvicorn re-raises SIGTERM after its graceful shutdown; the handler turns it into
    ``SystemExit`` so that ``stop()`` and the bus close still run.
    """
    settings = load_settings("ui")
    logsetup.configure(settings.log_level, "ui")
    bus = make_bus(settings, "gpos-ui")
    svc = create(settings, bus)
    svc.start()
    signal.signal(signal.SIGTERM, _exit_on_sigterm)
    try:
        uvicorn.run(svc.app, host="0.0.0.0", port=settings.http_port, log_level="warning",
                    proxy_headers=True, timeout_graceful_shutdown=SHUTDOWN_GRACE_S)
    finally:
        svc.stop()
        bus.close()
