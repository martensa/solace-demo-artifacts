"""Process wiring of ``gpos-gate`` (UC1-BUILD-SPEC 2.3): MCP server ``gpos-price-gate``
in the main thread, no relay (the gate writes ``engine.event_outbox``; the engine
publishes)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

from mcp.server.mcpserver import MCPServer

from ...common import log as gpos_log
from ...common import mcputil
from ...common.bus import Bus, make_bus
from ...common.clock import real_now
from ...common.config import Settings, load_settings
from ...common.db import Db
from ...common.descriptors import load_pool
from ...common.telemetry import Telemetry
from ..app import bus_probe
from ..clients import WwsClient
from ..state import Emitter
from .service import GateService
from .tools import build_mcp

Clock = Callable[[], datetime]


class Gate:
    """``create()`` result: ``service``, ``mcp`` (not started), ``start()``, ``stop()``."""

    def __init__(self, settings: Settings, bus: Bus, db: Db, clock: Clock = real_now):
        self._wws = WwsClient(load_pool([settings.showcase_descriptor_set]), settings.wws_grpc,
                              settings.zone)
        self.service = GateService(settings, db, self._wws,
                                   Emitter("gpos-gate", settings.zone, clock), clock)
        self.mcp: MCPServer = build_mcp(self.service, Telemetry(bus, "gate", db,
                                                                tz=settings.tz))
        mcputil.add_health(self.mcp, {"db": db.ping, "bus": bus_probe(bus)})

    def start(self) -> None:
        """Nothing runs in the background: the gate only answers tool calls."""

    def stop(self) -> None:
        self._wws.close()


def create(settings: Settings, bus: Bus, db: Db, *, clock: Clock = real_now) -> Gate:
    """The gate of 2.4: ``create(settings, bus, db)``; ``clock`` only for tests."""
    return Gate(settings, bus, db, clock)


def run(argv: Sequence[str] | None = None) -> None:
    """``python -m gposdemo.engine.gate [--dump-tools]``"""
    if mcputil.wants_dump_tools(argv):
        mcputil.dump_tools(build_mcp(None, None))
        return
    settings = load_settings("gate")
    gpos_log.configure(settings.log_level, "gate")
    db = Db(settings.dsn, application_name="gpos-gate")
    bus = make_bus(settings, "gpos-gate")
    gate = create(settings, bus, db)
    gate.start()
    try:
        mcputil.run(gate.mcp, settings.mcp_port)
    finally:
        gate.stop()
        bus.close()
        db.close()
