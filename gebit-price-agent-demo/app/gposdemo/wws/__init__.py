"""gpos-wws: merchandise management (Warenwirtschaft) of the showcase (WP-C, UC1-BUILD-SPEC 2.2).

One process: gRPC ``de.showcase.wws.v1.service.MerchandiseService`` on ``GRPC_PORT``
(50053, thread pool), MCP server ``gpos-wws-api`` plus ``GET /health`` on ``MCP_PORT``
(8773, main thread), outbox relay of schema ``wws`` as a thread.

``create(settings, bus, db)`` builds everything without starting it (2.4);
``run()`` = ``create``, ``start()``, then the blocking MCP server. ``--dump-tools``
prints ``tools/list`` without touching database, bus or descriptors (8.5).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import grpc
from mcp.server.mcpserver import MCPServer

from gposdemo.common import grpcutil, log, mcputil
from gposdemo.common.bus import Bus, make_bus
from gposdemo.common.config import Settings, load_settings
from gposdemo.common.db import Db
from gposdemo.common.descriptors import WWS_SVC, Types, load_pool
from gposdemo.common.outbox import OutboxRelay
from gposdemo.common.telemetry import Telemetry

from . import tools
from .service import MerchandiseImpl, WwsService

SERVICE = "wws"
CLIENT_NAME = "gpos-wws"
STOP_GRACE_S = 2.0

logger = logging.getLogger(__name__)


def _bus_ok(bus: Bus) -> bool:
    """``healthy()`` of ``SolaceBus``/``MemoryBus``; a bus without it counts as up."""
    probe = getattr(bus, "healthy", None)
    return bool(probe()) if callable(probe) else True


class WwsApp:
    """The running parts of gpos-wws (2.4): ``service``, ``impl``, ``mcp``, gRPC server,
    outbox relay. ``start()`` does not block; ``stop()`` ends gRPC and relay."""

    def __init__(self, s: Settings, service: WwsService, impl: MerchandiseImpl,
                 mcp: MCPServer, grpc_server: grpc.Server, relay: OutboxRelay):
        self.settings = s
        self.service = service
        self.impl = impl
        self.mcp = mcp
        self.grpc_server = grpc_server
        self.relay = relay

    @property
    def grpc_port(self) -> int:
        """Bound gRPC port (``GRPC_PORT``, or the free port chosen for ``0``)."""
        return grpcutil.bound_port(self.grpc_server)

    def start(self) -> None:
        """Start gRPC and the outbox relay."""
        self.grpc_server.start()
        self.relay.start()
        logger.info("gRPC %s on port %d", WWS_SVC, self.grpc_port)

    def stop(self) -> None:
        """Stop gRPC (grace 2 s) and the relay."""
        self.grpc_server.stop(STOP_GRACE_S).wait()
        self.relay.stop()


def create(settings: Settings, bus: Bus, db: Db) -> WwsApp:
    """Build gpos-wws on ``settings`` (descriptor set, ports), ``bus`` and ``db``."""
    pool = load_pool([settings.showcase_descriptor_set])
    types = Types(pool)
    service = WwsService(settings, db, types)
    impl = MerchandiseImpl(service, types)
    telemetry = Telemetry(bus, SERVICE, tz=settings.tz)
    mcp = tools.build_mcp(service, telemetry, {"db": db.ping, "bus": lambda: _bus_ok(bus)})
    server = grpcutil.serve(pool, WWS_SVC, impl, settings.grpc_port)
    relay = OutboxRelay(db, SERVICE, bus, settings)
    return WwsApp(settings, service, impl, mcp, server, relay)


def run(argv: Sequence[str] | None = None) -> None:
    """``python -m gposdemo.wws [--dump-tools]``."""
    if mcputil.wants_dump_tools(argv):
        mcputil.dump_tools(tools.build_mcp(None, None))
        return
    settings = load_settings(SERVICE)
    log.configure(settings.log_level, SERVICE)
    bus = make_bus(settings, CLIENT_NAME)
    db = Db(settings.dsn, application_name=CLIENT_NAME)
    app = create(settings, bus, db)
    app.start()
    try:
        mcputil.run(app.mcp, settings.mcp_port)
    finally:
        app.stop()
        bus.close()
        db.close()
