"""MCP server ``gpos-pos-api``: read-only agent tools of the till (UC1-BUILD-SPEC 8.1, 8.4).

Agent tools: ``structured_output=False``, one compact JSON text content, no
``outputSchema``, text <= 1200 B. Every call publishes telemetry
``gpos/v1/telemetry/tool/pos/<tool>`` (caller ``agent``, ``ref`` from the argument).
An unknown transaction or till is a ``ToolError``: the agent gets ``isError`` with
the German text (any other exception stays a generic crash message). The tool
definitions are static: :func:`build_mcp` with ``service=None`` and ``tel=None`` serves
``--dump-tools`` without DB, bus or GEBIT descriptors.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult
from pydantic import Field

from gposdemo.common import mcputil
from gposdemo.common.telemetry import Telemetry

from .service import PosService

SERVER_NAME = "gpos-pos-api"
INSTRUCTIONS = ("Read-only POS API of the booth till (simulator of the GEBIT Purchase API "
                "2.50): one transaction with lines and prices, till status. Fictional data.")
GET_TRANSACTION = "One POS transaction with lines, prices and membership."
GET_TILL_STATUS = ("Status of the booth till: open transaction, number and revenue of the "
                   "transactions closed today.")


def _payload(result: CallToolResult) -> dict[str, Any]:
    return json.loads(mcputil.result_text(result))


def transaction_summary(_arguments: dict[str, Any], result: CallToolResult) -> str:
    """``"Bon 5b1f0c2e: 3 Zeilen, 16,98 €, Karte M-1001"``"""
    data = _payload(result)
    lines = len(data["lines"]) + int(data.get("more", 0))
    card = f", Karte {data['membership_id']}" if data.get("membership_id") else ""
    return f"Bon {data['tx_id'][:8]}: {lines} Zeilen, {data['total']} €{card}"


def till_summary(_arguments: dict[str, Any], result: CallToolResult) -> str:
    """``"Kasse 01: 7 Bons heute, 84,12 €, kein offener Bon"``"""
    data = _payload(result)
    state = "Bon offen" if data["open_tx"] else "kein offener Bon"
    return (f"Kasse {data['till']}: {data['tx_today']} Bons heute, "
            f"{data['revenue_today']} €, {state}")


def _service(service: PosService | None) -> PosService:
    if service is None:
        raise RuntimeError("gpos-pos-api runs without a service (--dump-tools only)")
    return service


def _answer(read: Callable[[], dict[str, Any]]) -> CallToolResult:
    try:
        return mcputil.text_result(read())
    except LookupError as exc:
        raise ToolError(str(exc)) from exc


def build_mcp(service: PosService | None, tel: Telemetry | None) -> MCPServer:
    """The MCP server with both tools (not started; ``admin.py`` adds the HTTP routes)."""
    mcp = mcputil.make_server(SERVER_NAME, INSTRUCTIONS)

    @mcp.tool(structured_output=False, description=GET_TRANSACTION)
    @mcputil.telemetry(tel, caller="agent", summary=transaction_summary)
    def get_transaction(
        tx_id: Annotated[str, Field(description="Purchase transaction id (tx_id of the "
                                                "review input).")],
        ref: Annotated[str, Field(description="Review id (review_id) for the monitor.")] = "",
    ) -> CallToolResult:
        return _answer(lambda: _service(service).get_transaction(tx_id, ref))

    @mcp.tool(structured_output=False, description=GET_TILL_STATUS)
    @mcputil.telemetry(tel, caller="agent", summary=till_summary)
    def get_till_status(
        ref: Annotated[str, Field(description="Review id (review_id) for the monitor.")] = "",
    ) -> CallToolResult:
        return _answer(lambda: _service(service).get_till_status(ref))

    return mcp
