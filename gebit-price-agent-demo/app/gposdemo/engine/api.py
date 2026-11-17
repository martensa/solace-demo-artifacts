"""Engine HTTP API on the MCP port via ``custom_route`` (UC1-BUILD-SPEC 11.8).

* ``GET /api/state?store=101&till=01`` -> last review, open or last proposal, counters
* ``GET /api/reviews/{id}``, ``GET /api/proposals/{id}`` (with the ``approval`` row)
* ``POST /api/reset`` ``{"scope": "booth"|"day", "store_id": "101"}``
* ``POST /api/sam-error`` ``{"rule": "r4"|"p4", "store", "till", "error"}``

``GET /health`` comes from ``mcputil.add_health``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import anyio.to_thread
from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..common.topics import parse_location
from .service import EngineService


def _not_found(what: str, ident: str) -> JSONResponse:
    return JSONResponse({"error": f"{what} {ident} unknown"}, status_code=404)


async def _body(request: Request) -> dict[str, Any] | None:
    try:
        body = json.loads(await request.body() or b"{}")
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


async def _run(fn: Callable[[], Any]) -> Any:
    return await anyio.to_thread.run_sync(fn)


def add_api(mcp: MCPServer, service: EngineService) -> None:
    """Register the routes of 11.8 on ``mcp``."""
    _, _, booth_store, booth_till = parse_location(service.ctx.settings.booth_location)

    @mcp.custom_route("/api/state", methods=["GET"])
    async def state(request: Request) -> Response:
        store_id = request.query_params.get("store", booth_store)
        till_id = request.query_params.get("till", booth_till)
        return JSONResponse(await _run(lambda: service.state(store_id, till_id)))

    @mcp.custom_route("/api/reviews/{review_id}", methods=["GET"])
    async def review(request: Request) -> Response:
        review_id = request.path_params["review_id"]
        found = await _run(lambda: service.review(review_id))
        return JSONResponse(found) if found else _not_found("review", review_id)

    @mcp.custom_route("/api/proposals/{proposal_id}", methods=["GET"])
    async def proposal(request: Request) -> Response:
        proposal_id = request.path_params["proposal_id"]
        found = await _run(lambda: service.proposal(proposal_id))
        return JSONResponse(found) if found else _not_found("proposal", proposal_id)

    @mcp.custom_route("/api/reset", methods=["POST"])
    async def reset(request: Request) -> Response:
        body = await _body(request)
        if body is None:
            return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
        scope = str(body.get("scope") or "booth")
        store_id = str(body.get("store_id") or booth_store)
        try:
            return JSONResponse(await _run(lambda: service.reset(scope, store_id)))
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @mcp.custom_route("/api/sam-error", methods=["POST"])
    async def sam_error(request: Request) -> Response:
        body = await _body(request)
        if body is None:
            return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
        args = {k: str(body.get(k) or "") for k in ("rule", "store", "till", "error")}
        if not (args["store"] and args["till"]):
            return JSONResponse({"error": "store and till are required"}, status_code=400)
        try:
            return JSONResponse(await _run(lambda: service.sam_error(**args)))
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
