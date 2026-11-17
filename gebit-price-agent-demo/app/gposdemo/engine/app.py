"""Process wiring of ``gpos-engine`` (UC1-BUILD-SPEC 2.3, 2.4): MCP server
``gpos-booth-tools`` plus the HTTP API in the main thread, outbox relay and watchdog
as threads."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import datetime

from mcp.server.mcpserver import MCPServer

from ..common import log as gpos_log
from ..common import mcputil
from ..common.bus import Bus, make_bus
from ..common.clock import real_now
from ..common.config import Settings, load_settings
from ..common.db import Db
from ..common.descriptors import load_pool
from ..common.outbox import OutboxRelay
from ..common.telemetry import Telemetry
from .api import add_api
from .clients import LoyaltyClient, WwsClient
from .context import Context
from .policy import load_policy
from .service import EngineService
from .state import Emitter
from .tools import build_mcp
from .watchdog import Watchdog

log = logging.getLogger(__name__)

Clock = Callable[[], datetime]


def bus_probe(bus: Bus) -> Callable[[], bool]:
    """``/health`` probe of a bus (``healthy()`` of ``SolaceBus``/``MemoryBus``)."""
    healthy = getattr(bus, "healthy", None)
    return healthy if callable(healthy) else (lambda: True)


class Engine:
    """``create()`` result: ``service``, ``mcp`` (not started), ``start()``, ``stop()``."""

    def __init__(self, settings: Settings, bus: Bus, db: Db, clock: Clock = real_now):
        pool = load_pool([settings.showcase_descriptor_set])
        self._wws = WwsClient(pool, settings.wws_grpc, settings.zone)
        self._loyalty = LoyaltyClient(pool, settings.loyalty_grpc)
        ctx = Context(settings=settings, db=db, bus=bus, wws=self._wws, loyalty=self._loyalty,
                      policy=load_policy(settings.policy_file),
                      emitter=Emitter("gpos-engine", settings.zone, clock), clock=clock)
        self.service = EngineService(ctx, on_sam_error=self._settle_later)
        self.relay = OutboxRelay(db, "engine", bus, settings)
        self.watchdog = Watchdog(self.service.maintenance)
        self.mcp: MCPServer = build_mcp(self.service, Telemetry(bus, "engine", db,
                                                                tz=settings.tz))
        add_api(self.mcp, self.service)
        mcputil.add_health(self.mcp, {"db": db.ping, "bus": bus_probe(bus)})

    def _settle_later(self) -> None:
        if self.watchdog.is_alive():
            self.watchdog.settle_later()

    def start(self) -> None:
        """Start relay and watchdog (non-blocking)."""
        self.relay.start()
        self.watchdog.start()

    def stop(self) -> None:
        """Stop the threads and close the gRPC channels."""
        self.watchdog.stop()
        self.relay.stop()
        self._wws.close()
        self._loyalty.close()


def create(settings: Settings, bus: Bus, db: Db, *, clock: Clock = real_now) -> Engine:
    """The engine of 2.4: ``create(settings, bus, db)``; ``clock`` only for tests."""
    return Engine(settings, bus, db, clock)


def run(argv: Sequence[str] | None = None) -> None:
    """``python -m gposdemo.engine [--dump-tools]``"""
    if mcputil.wants_dump_tools(argv):
        mcputil.dump_tools(build_mcp(None, None))
        return
    settings = load_settings("engine")
    gpos_log.configure(settings.log_level, "engine")
    db = Db(settings.dsn, application_name="gpos-engine")
    bus = make_bus(settings, "gpos-engine")
    engine = create(settings, bus, db)
    engine.start()
    try:
        mcputil.run(engine.mcp, settings.mcp_port)
    finally:
        engine.stop()
        bus.close()
        db.close()
