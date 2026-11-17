"""MCP server ``gpos-wws-api``: the agent tools of the WWS (UC1-BUILD-SPEC 8.1, 8.4).

Exactly three tools, each ``(article_number, ref)`` with ``str`` parameters and one
compact JSON text content (no ``structuredContent``, no ``outputSchema``, <= 1200 B):
``get_article``, ``get_sales_performance``, ``get_season_info``. No side effects except
the telemetry event ``gpos/v1/telemetry/tool/wws/<tool>`` (``caller`` ``agent``, ``ref``
from the argument). An unknown article answers an error JSON with ``isError``.

The tool list is static: :func:`build_mcp` with ``api=None`` and ``tel=None`` serves
``--dump-tools`` without database, bus or descriptors.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import date
from typing import Annotated, Any, Protocol

from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult, TextContent
from pydantic import Field

from gposdemo.common import mcputil
from gposdemo.common.fmt import date_label
from gposdemo.common.jsonutil import compact
from gposdemo.common.telemetry import Telemetry

from .errors import WwsError

SERVER_NAME = "gpos-wws-api"
INSTRUCTIONS = (
    "Read-only merchandise management API (Warenwirtschaft) of the fictional showcase "
    "store: article master data and price, sales against plan, stock, season. Every tool "
    "answers one compact JSON object; prices are German labels without currency "
    "(\"9,99\" = 9.99 EUR), dates ISO, figures refer to the business date.")

ArticleNumber = Annotated[str, Field(description="Article number, e.g. 100001.")]
Ref = Annotated[str, Field(description="Review id of the caller (e.g. GR-270216-0007), "
                                       "shown on the monitor.")]


class AgentApi(Protocol):
    """The service methods behind the tools (``WwsService``)."""

    def get_article(self, article_number: str, ref: str = "") -> dict[str, Any]: ...

    def get_sales_performance(self, article_number: str, ref: str = "") -> dict[str, Any]: ...

    def get_season_info(self, article_number: str, ref: str = "") -> dict[str, Any]: ...


def error_result(article_number: str, err: WwsError) -> CallToolResult:
    """``{"article_number", "error": <code>, "message": <German text>}`` with ``isError``."""
    body = {"article_number": article_number, "error": err.code, "message": err.text}
    return CallToolResult(content=[TextContent(type="text", text=compact(body))],
                          is_error=True)


def _answer(article_number: str, fetch: Callable[[], dict[str, Any]]) -> CallToolResult:
    try:
        return mcputil.text_result(fetch())
    except WwsError as err:
        return error_result(article_number, err)


def _weeks_label(value: float | None) -> str:
    """``6.5`` -> ``"6,5"``; ``None`` (no sales in 4 weeks) -> ``"–"``."""
    return "–" if value is None else f"{value:.1f}".replace(".", ",")


def _from_iso(text: str) -> str:
    """``"2027-02-14"`` -> ``"14.02."``"""
    return date_label(date.fromisoformat(text))


def article_summary(body: dict[str, Any]) -> str:
    """``"100001: 9,99 € (REGULAR), Bestand 96"``"""
    return (f"{body['article_number']}: {body['price']} € ({body['price_source']}), "
            f"Bestand {body['stock']}")


def sales_summary(body: dict[str, Any]) -> str:
    """``"100001: 9/35 verkauft, Reichweite 6,5 Wo."`` (7.2)"""
    return (f"{body['article_number']}: {body['sold_7d']}/{body['plan_7d']} verkauft, "
            f"Reichweite {_weeks_label(body['weeks_of_supply'])} Wo.")


def season_summary(body: dict[str, Any]) -> str:
    """``"100008: Saison Valentinstag endete am 14.02., Rest 46"``"""
    number = body["article_number"]
    status = body["status"]
    if status == "none":
        return f"{number}: keine Saison"
    end = _from_iso(body["end"])
    if status == "ended":
        return f"{number}: Saison {body['season']} endete am {end}, Rest {body['leftover_units']}"
    if status == "before":
        return (f"{number}: Saison {body['season']} ab {_from_iso(body['start'])}, "
                f"Rest {body['leftover_units']}")
    return (f"{number}: Saison {body['season']} endet am {end} ({body['days_to_end']} Tage), "
            f"Rest {body['leftover_units']}")


def _summary(describe: Callable[[dict[str, Any]], str]
             ) -> Callable[[dict[str, Any], CallToolResult], str]:
    """Telemetry summary from the tool's JSON text; errors as ``"<n>: <message>"``."""

    def summarize(_arguments: dict[str, Any], result: CallToolResult) -> str:
        body = json.loads(mcputil.result_text(result))
        if result.is_error:
            return f"{body['article_number']}: {body['message']}"
        return describe(body)

    return summarize


def _require(api: AgentApi | None) -> AgentApi:
    if api is None:
        raise RuntimeError("gpos-wws-api was built without a service (--dump-tools only)")
    return api


def build_mcp(api: AgentApi | None, tel: Telemetry | None,
              checks: Mapping[str, Callable[[], bool]] | None = None) -> MCPServer:
    """The MCP server with the three agent tools and ``GET /health`` (``checks``)."""
    mcp = mcputil.make_server(SERVER_NAME, INSTRUCTIONS)

    @mcp.tool(structured_output=False)
    @mcputil.telemetry(tel, caller="agent", summary=_summary(article_summary))
    def get_article(article_number: ArticleNumber, ref: Ref = "") -> CallToolResult:
        """Article master data, effective price, ref30, stock, margin."""
        return _answer(article_number, lambda: _require(api).get_article(article_number, ref))

    @mcp.tool(structured_output=False)
    @mcputil.telemetry(tel, caller="agent", summary=_summary(sales_summary))
    def get_sales_performance(article_number: ArticleNumber, ref: Ref = "") -> CallToolResult:
        """Sales against plan and weeks of supply of one article."""
        return _answer(article_number,
                       lambda: _require(api).get_sales_performance(article_number, ref))

    @mcp.tool(structured_output=False)
    @mcputil.telemetry(tel, caller="agent", summary=_summary(season_summary))
    def get_season_info(article_number: ArticleNumber, ref: Ref = "") -> CallToolResult:
        """Season status and leftover stock of one article."""
        return _answer(article_number,
                       lambda: _require(api).get_season_info(article_number, ref))

    mcputil.add_health(mcp, dict(checks or {}))
    return mcp
