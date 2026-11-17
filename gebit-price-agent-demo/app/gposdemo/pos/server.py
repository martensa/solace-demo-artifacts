"""Process assembly of ``gpos-pos`` (UC1-BUILD-SPEC 2.3, 2.4).

``create(settings, bus, db)`` builds everything without starting it: the GEBIT pool
from ``GEBIT_DESCRIPTOR_SETS`` (purchase + receipt, mounted at runtime), the Showcase
pool for the WWS and loyalty clients, the gRPC server (``GRPC_PORT``, ``0`` = free
port), the outbox relay of schema ``pos`` and the MCP server ``gpos-pos-api`` with the
admin routes. ``start()`` starts gRPC and the relay (non-blocking); ``run()`` is the
process entry: create, start, then serve MCP/HTTP on ``MCP_PORT`` until stopped.
"""

from __future__ import annotations

import logging
import signal
from types import FrameType

import grpc
from mcp.server.mcpserver import MCPServer

from gposdemo.common import grpcutil, log, mcputil
from gposdemo.common.bus import Bus, make_bus
from gposdemo.common.config import Settings, load_settings
from gposdemo.common.db import Db
from gposdemo.common.descriptors import PURCHASE_SVC, Types, load_pool
from gposdemo.common.outbox import OutboxRelay
from gposdemo.common.telemetry import Telemetry

from . import admin, tools
from .clients import LoyaltyClient, WwsClient
from .service import PosService
from .sim import Simulator

logger = logging.getLogger(__name__)

SERVICE = "pos"
STOP_GRACE_S = 2.0


def _bus_healthy(bus: Bus) -> bool:
    probe = getattr(bus, "healthy", None)
    return bool(probe()) if callable(probe) else True


class PosApp:
    """The assembled ``gpos-pos`` process: ``service``, ``impl``, ``mcp`` and ``server``."""

    def __init__(self, service: PosService, impl: Simulator, mcp: MCPServer,
                 server: grpc.Server, relay: OutboxRelay, wws: WwsClient,
                 loyalty: LoyaltyClient):
        self.service = service
        self.impl = impl
        self.mcp = mcp
        self.server = server
        self._relay = relay
        self._clients = (wws, loyalty)

    @property
    def grpc_port(self) -> int:
        """Port the gRPC server is bound to."""
        return grpcutil.bound_port(self.server)

    def start(self) -> None:
        """Start gRPC and the outbox relay; returns at once."""
        self._relay.start()
        self.server.start()
        logger.info("gRPC %s on port %d", PURCHASE_SVC, self.grpc_port)

    def stop(self) -> None:
        """Stop gRPC (2 s grace), the relay and the client channels."""
        self.server.stop(STOP_GRACE_S).wait()
        self._relay.stop()
        for client in self._clients:
            client.close()


def create(settings: Settings, bus: Bus, db: Db) -> PosApp:
    """Build the POS process; needs the GEBIT descriptor sets (``ValueError`` without)."""
    if not settings.gebit_descriptor_sets:
        raise ValueError("GEBIT_DESCRIPTOR_SETS is empty: gpos-pos needs the purchase and "
                         "receipt descriptor sets (mounted at runtime)")
    gebit = load_pool(settings.gebit_descriptor_sets)
    showcase = load_pool([settings.showcase_descriptor_set])
    wws = WwsClient(showcase, settings.wws_grpc)
    loyalty = LoyaltyClient(showcase, settings.loyalty_grpc)
    relay = OutboxRelay(db, "pos", bus, settings)
    impl = Simulator(settings, db, Types(gebit), wws, loyalty, relay.kick)
    service = PosService(settings, db)
    mcp = tools.build_mcp(service, Telemetry(bus, SERVICE, tz=settings.tz))
    admin.add_routes(mcp, service, {"db": db.ping, "bus": lambda: _bus_healthy(bus)})
    server = grpcutil.serve(gebit, PURCHASE_SVC, impl, settings.grpc_port)
    return PosApp(service, impl, mcp, server, relay, wws, loyalty)


def _exit_on_sigterm(_signum: int, _frame: FrameType | None) -> None:
    raise SystemExit(0)


def run() -> None:
    """Process entry of ``python -m gposdemo.pos``: blocks until the MCP server ends.

    uvicorn handles SIGTERM itself and raises it again after its graceful shutdown; the
    handler installed here turns that into ``SystemExit``, so gRPC (2 s grace), the
    relay and the connections are stopped in order and the pod exits with 0.
    """
    signal.signal(signal.SIGTERM, _exit_on_sigterm)
    settings = load_settings(SERVICE)
    log.configure(settings.log_level, SERVICE)
    bus = make_bus(settings, "gpos-pos")
    db = Db(settings.dsn, application_name="gpos-pos")
    app = create(settings, bus, db)
    app.start()
    try:
        mcputil.run(app.mcp, settings.mcp_port)
    finally:
        app.stop()
        bus.close()
        db.close()
