"""HTTP routes of ``gpos-pos`` next to ``/mcp`` on port 8771 (UC1-BUILD-SPEC 8.1, 11.7, 11.8).

* ``GET /health`` -> ``{"status": "ok", "db": true, "bus": true}`` (503 when degraded)
* ``POST /admin/reset`` -> open baskets ``RESET`` without GEBIT events:
  ``{"status": "ok", "reset": n}``
* ``GET /admin/till/{till}`` -> ``{"till": "01", "store": "101", "open_tx": {...} | null}``;
  404 for an unknown till

Blocking DB work runs in a worker thread, never on the event loop.
"""

from __future__ import annotations

from collections.abc import Callable

import anyio.to_thread
from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from gposdemo.common import mcputil

from .service import PosService


def add_routes(mcp: MCPServer, service: PosService, health: dict[str, Callable[[], bool]]
               ) -> None:
    """Register health and the two admin routes on the MCP server."""
    mcputil.add_health(mcp, health)

    @mcp.custom_route("/admin/reset", methods=["POST"])
    async def admin_reset(_request: Request) -> Response:
        return JSONResponse(await anyio.to_thread.run_sync(service.admin_reset))

    @mcp.custom_route("/admin/till/{till}", methods=["GET"])
    async def admin_till(request: Request) -> Response:
        till = request.path_params["till"]
        try:
            state = await anyio.to_thread.run_sync(service.till_state, till)
        except KeyError:
            return JSONResponse({"error": f"Kasse {till} unbekannt"}, status_code=404)
        return JSONResponse(state)
