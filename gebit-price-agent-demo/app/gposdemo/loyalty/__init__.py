"""gpos-loyalty: loyalty system of the fictional showcase store (UC1-BUILD-SPEC 2.2, 2.4).

* gRPC ``showcase.loyalty.v1`` ``LoyaltyService`` on ``GRPC_PORT`` (50052), the UC1
  subset of 4.4 (``server.py``).
* MCP ``gpos-loyalty-api`` on ``MCP_PORT`` (8772) with the two agent tools of 8.4 and
  ``GET /health`` (``tools.py``).
* Schema ``loyalty`` (role ``gpos_loyalty``); no events and no outbox relay in UC1.

``create(settings, bus, db)`` wires everything without starting it; ``start()``
starts gRPC (non-blocking); ``python -m gposdemo.loyalty`` then serves MCP blocking.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import grpc
from mcp.server.mcpserver import MCPServer

from gposdemo.common import grpcutil, mcputil
from gposdemo.common.bus import Bus
from gposdemo.common.config import Settings
from gposdemo.common.db import Db
from gposdemo.common.descriptors import LOYALTY_SVC, Types, load_pool
from gposdemo.common.telemetry import Telemetry

from .server import LoyaltyGrpc
from .service import LoyaltyService
from .tools import build_mcp

SERVICE = "loyalty"
STOP_GRACE_S = 2.0


@dataclass
class LoyaltyApp:
    """The wired service of 2.4: ``service``, ``impl``, ``mcp`` (not started), ``server``."""

    settings: Settings
    service: LoyaltyService
    impl: LoyaltyGrpc
    mcp: MCPServer
    server: grpc.Server

    @property
    def grpc_port(self) -> int:
        """Port the gRPC server is bound to (useful with ``GRPC_PORT=0``)."""
        return grpcutil.bound_port(self.server)

    def start(self) -> None:
        """Start the gRPC server (non-blocking)."""
        self.server.start()

    def stop(self) -> None:
        """Stop the gRPC server; open calls get :data:`STOP_GRACE_S` to finish."""
        self.server.stop(STOP_GRACE_S).wait()


def _bus_probe(bus: Bus) -> Callable[[], bool]:
    probe = getattr(bus, "healthy", None)
    return probe if callable(probe) else (lambda: True)


def create(settings: Settings, bus: Bus, db: Db) -> LoyaltyApp:
    """Wire gpos-loyalty: service, gRPC impl bound to ``settings.grpc_port`` (not started),
    MCP server with telemetry and ``/health``."""
    pool = load_pool([settings.showcase_descriptor_set])
    service = LoyaltyService(db, settings)
    impl = LoyaltyGrpc(service, Types(pool))
    server = grpcutil.serve(pool, LOYALTY_SVC, impl, settings.grpc_port)
    mcp = build_mcp(service, Telemetry(bus, SERVICE, tz=settings.tz))
    mcputil.add_health(mcp, {"db": db.ping, "bus": _bus_probe(bus)})
    return LoyaltyApp(settings, service, impl, mcp, server)
