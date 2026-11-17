"""MCP server conventions of all gpos-demo services (UC1-BUILD-SPEC 8.1, G0-01).

* mcp 2.2.0 ``MCPServer``, streamable HTTP on path ``/mcp``, ``json_response=True``,
  ``stateless_http=True``, DNS-rebinding protection off.
* Workflow tools (connectors ``gpos-booth-tools``, ``gpos-price-gate``) return
  ``Annotated[CallToolResult, Model]`` built by :func:`structured_result`:
  ``structuredContent`` = model plus ONE one-line text ``"<tool>: <short status>"``.
  Limits: whole result (compact JSON) <= 1800 B, text <= 1500 B.
* Agent tools (``gpos-wws-api``, ``gpos-loyalty-api``, ``gpos-pos-api``) are registered
  with ``@mcp.tool(structured_output=False)`` and return :func:`text_result`: exactly
  one text content with compact JSON, no ``structuredContent``, no ``outputSchema``.
  Limit: text <= 1200 B.
* Every tool is wrapped with :func:`telemetry` (below ``@mcp.tool``); every server has
  ``GET /health`` (:func:`add_health`) and ``--dump-tools`` (:func:`dump_tools`).

Typical use inside a service module::

    mcp = mcputil.make_server("gpos-wws-api", INSTRUCTIONS)

    @mcp.tool(structured_output=False)
    @mcputil.telemetry(tel, caller="agent", summary=sales_summary)
    def get_sales_performance(article_number: str, ref: str = "") -> CallToolResult:
        return mcputil.text_result(service.get_sales_performance(article_number, ref))
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import logging
import sys
import time
from collections.abc import Callable, Sequence
from typing import Any, Literal, TypeVar

import anyio.to_thread
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import CallToolResult, TextContent
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .jsonutil import compact
from .telemetry import Telemetry, shorten

log = logging.getLogger(__name__)

MCP_PATH = "/mcp"
MCP_HOST = "0.0.0.0"
WORKFLOW_MAX_BYTES = 1800
WORKFLOW_MAX_TEXT_BYTES = 1500
AGENT_MAX_TEXT_BYTES = 1200
DUMP_TOOLS_FLAG = "--dump-tools"

ToolKind = Literal["workflow", "agent"]
F = TypeVar("F", bound=Callable[..., CallToolResult])
Summary = Callable[[dict[str, Any], CallToolResult], str]


def make_server(name: str, instructions: str) -> MCPServer:
    """``MCPServer`` named like its SAM connector (e.g. ``gpos-booth-tools``)."""
    return MCPServer(name=name, instructions=instructions)


def _transport_options() -> dict[str, Any]:
    """The streamable-HTTP options of 8.1 (G0-01), shared by :func:`run` and :func:`http_app`."""
    return {"streamable_http_path": MCP_PATH, "json_response": True, "stateless_http": True,
            "transport_security": TransportSecuritySettings(
                enable_dns_rebinding_protection=False)}


def run(mcp: MCPServer, port: int) -> None:
    """Serve ``mcp`` (tools on ``/mcp`` plus custom routes) on ``0.0.0.0:port``; blocks."""
    log.info("MCP %s on http://%s:%d%s", mcp.name, MCP_HOST, port, MCP_PATH)
    mcp.run(transport="streamable-http", host=MCP_HOST, port=port, **_transport_options())


def http_app(mcp: MCPServer) -> Starlette:
    """The ASGI app :func:`run` serves (same options), e.g. for an in-process test client."""
    return mcp.streamable_http_app(host=MCP_HOST, **_transport_options())


def measure(result: CallToolResult) -> tuple[int, int]:
    """``(full bytes, text bytes)`` with the G0-01 definition of the 8.1 limit.

    ``full`` = the whole result as JSON-RPC ``result`` object, compact UTF-8, with
    ``content`` + ``structuredContent`` + ``isError`` + ``resultType`` (the server adds
    ``isError``; ``resultType`` only for newer protocol versions, counted anyway, so
    the measure is an upper bound). ``text`` = UTF-8 bytes of all text contents.
    """
    data = result.model_dump(mode="json", by_alias=True, exclude_none=True)
    data.setdefault("isError", False)
    data.setdefault("resultType", "complete")
    full = len(compact(data).encode("utf-8"))
    text = sum(len(c.text.encode("utf-8")) for c in result.content if isinstance(c, TextContent))
    return full, text


def within_limits(result: CallToolResult, kind: ToolKind) -> bool:
    """True when ``result`` respects the 8.1 size limits of a ``kind`` tool."""
    full, text = measure(result)
    if kind == "workflow":
        return full <= WORKFLOW_MAX_BYTES and text <= WORKFLOW_MAX_TEXT_BYTES
    return text <= AGENT_MAX_TEXT_BYTES


def _warn_if_too_big(tool: str, result: CallToolResult, kind: ToolKind) -> None:
    if not within_limits(result, kind):
        full, text = measure(result)
        log.warning("%s result too big for a %s tool: %d B total, %d B text", tool, kind,
                    full, text)


def structured_result(tool: str, model: BaseModel, head: str) -> CallToolResult:
    """Workflow-tool result: ``structuredContent`` = ``model``, text ``"<tool>: <head>"``.

    ``head`` is flattened to one line. A result over the 8.1 limits is logged as a
    warning (the unit tests of each package assert the limits).
    """
    result = CallToolResult(
        content=[TextContent(type="text", text=f"{tool}: {' '.join(head.split())}")],
        structured_content=model.model_dump(mode="json"))
    _warn_if_too_big(tool, result, "workflow")
    return result


def text_result(obj: dict[str, Any]) -> CallToolResult:
    """Agent-tool result: exactly one text content with compact JSON, nothing else."""
    result = CallToolResult(content=[TextContent(type="text", text=compact(obj))])
    _warn_if_too_big("agent tool", result, "agent")
    return result


def result_text(result: CallToolResult) -> str:
    """All text contents of ``result`` joined (agent tools: the compact JSON)."""
    return "".join(c.text for c in result.content if isinstance(c, TextContent))


def _default_summary(_arguments: dict[str, Any], result: CallToolResult) -> str:
    return result_text(result)


def telemetry(tel: Telemetry | None, *, caller: str, ref_param: str = "ref",
              summary: Summary | None = None) -> Callable[[F], F]:
    """Decorator: publish one telemetry event after every call of a sync tool function.

    ``ms`` is the duration, ``ok`` is false when the tool raised or returned
    ``isError``; ``run_id`` and ``ref`` come from the call arguments (``ref_param``
    names the argument used as ``ref``, e.g. ``"review_id"`` for a workflow tool);
    ``summary(arguments, result)`` writes the German summary (default: the text content,
    which for workflow tools is ``"<tool>: <status>"``). ``tel=None`` (``--dump-tools``)
    returns the function unchanged. The signature is preserved, so MCP sees the same
    parameters and return annotation. Telemetry failures never reach the caller.
    """

    def decorate(fn: F) -> F:
        if tel is None:
            return fn
        if inspect.iscoroutinefunction(fn):
            raise TypeError(f"{fn.__name__}: telemetry wraps sync tool functions only")
        signature = inspect.signature(fn)
        describe = summary or _default_summary

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> CallToolResult:
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            arguments = dict(bound.arguments)
            run_id = str(arguments.get("run_id", "") or "")
            ref = str(arguments.get(ref_param, "") or "")
            started = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                ms = round((time.perf_counter() - started) * 1000)
                tel.tool_call(fn.__name__, caller, run_id, ref, ms, False,
                              shorten(f"{type(exc).__name__}: {exc}"))
                raise
            ms = round((time.perf_counter() - started) * 1000)
            try:
                text = describe(arguments, result)
            except Exception:  # noqa: BLE001 - a broken summary must not break the tool
                log.warning("summary of %s failed", fn.__name__, exc_info=True)
                text = result_text(result)
            tel.tool_call(fn.__name__, caller, run_id, ref, ms, not result.is_error, text)
            return result

        return wrapper  # type: ignore[return-value]

    return decorate


def add_health(mcp: MCPServer, checks: dict[str, Callable[[], bool]]) -> None:
    """``GET /health`` -> ``{"status": "ok", "db": true, "bus": true}`` (8.1).

    ``checks`` maps a key (``"db"``, ``"bus"``) to a blocking probe; probes run in a
    worker thread. Any false or failing probe answers ``"status": "degraded"`` with
    HTTP 503, so the readiness probe takes the pod out of service.
    """

    def evaluate() -> dict[str, bool]:
        out: dict[str, bool] = {}
        for key, probe in checks.items():
            try:
                out[key] = bool(probe())
            except Exception:  # noqa: BLE001 - a failing probe is a false probe
                out[key] = False
        return out

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> Response:
        results = await anyio.to_thread.run_sync(evaluate)
        healthy = all(results.values())
        return JSONResponse({"status": "ok" if healthy else "degraded", **results},
                            status_code=200 if healthy else 503)


def tools_list(mcp: MCPServer) -> list[dict[str, Any]]:
    """``tools/list`` as plain dicts: ``name``, ``description``, ``inputSchema`` and,
    only when present, ``outputSchema`` (the format ``gen_connector_manifest.py`` reads).
    """

    async def collect() -> list[dict[str, Any]]:
        out = []
        for tool in await mcp.list_tools():
            data = tool.model_dump(by_alias=True, exclude_none=True)
            entry = {"name": data["name"], "description": data.get("description") or "",
                     "inputSchema": data.get("inputSchema") or {"type": "object"}}
            if data.get("outputSchema"):
                entry["outputSchema"] = data["outputSchema"]
            out.append(entry)
        return out

    return asyncio.run(collect())


def dump_tools(mcp: MCPServer) -> None:
    """Print :func:`tools_list` as JSON to stdout (``--dump-tools``, 8.5)."""
    print(json.dumps(tools_list(mcp), ensure_ascii=False, indent=1))


def wants_dump_tools(argv: Sequence[str] | None = None) -> bool:
    """True when the command line (default ``sys.argv``) asks for ``--dump-tools``."""
    return DUMP_TOOLS_FLAG in (sys.argv[1:] if argv is None else argv)
