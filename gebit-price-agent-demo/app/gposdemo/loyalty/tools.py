"""MCP server ``gpos-loyalty-api`` (UC1-BUILD-SPEC 8.1, 8.4, connector 9.3).

Exactly two agent tools, read-only, each a thin wrapper around ``LoyaltyService``:

* ``get_member_profile(membership_id, ref)``
* ``get_purchase_behaviour(membership_id, article_number, ref)``

Agent-tool shape: one text content with compact JSON (<= 1200 B), no
``structuredContent``, no ``outputSchema``. Every call publishes
``gpos/v1/telemetry/tool/loyalty/<tool>`` (``caller`` ``agent``, ``ref`` from the
argument) with a German summary. The tool list is static: ``build_mcp(None, None)``
serves ``--dump-tools`` without DB, bus or descriptors.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Annotated, Any, Protocol

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult
from pydantic import Field

from gposdemo.common import mcputil
from gposdemo.common.telemetry import Telemetry

from .service import LoyaltyError

SERVER_NAME = "gpos-loyalty-api"
INSTRUCTIONS = ("Read-only loyalty API of the fictional showcase store: member profile, "
                "consent and purchase behaviour of one card, anonymous cardholder trends. "
                "Fictional data only; no personal attributes.")
PROFILE_DESCRIPTION = "Profile of one fictional loyalty card (no personal attributes)."
BEHAVIOUR_DESCRIPTION = ("Purchase behaviour of one fictional loyalty card for one article "
                         "(member fields only with profiling consent) plus the anonymous "
                         "cardholder trend.")

MembershipId = Annotated[str, Field(description="Membership id of the card, e.g. M-1001.")]
ArticleNumber = Annotated[str, Field(description="Article number, e.g. 100012.")]
Ref = Annotated[str, Field(description="review_id of the basket review (for the monitor).")]


class AgentTools(Protocol):
    """What the tools call (``LoyaltyService`` implements it)."""

    def get_member_profile(self, membership_id: str, ref: str = "") -> dict[str, Any]: ...

    def get_purchase_behaviour(self, membership_id: str, article_number: str, ref: str = ""
                               ) -> dict[str, Any]: ...


def _payload(result: CallToolResult) -> dict[str, Any]:
    data = json.loads(mcputil.result_text(result))
    if not isinstance(data, dict):
        raise ValueError("tool text is not a JSON object")
    return data


def _drop_text(drop: float) -> str:
    """``46.7`` -> ``"Kartenkunden 46,7 % seltener"`` (negative = more often)."""
    if drop == 0:
        return "Kartenkunden unverändert"
    word = "seltener" if drop > 0 else "häufiger"
    return f"Kartenkunden {abs(drop):.1f} % {word}".replace(".", ",")


def _count(n: int, one: str, many: str) -> str:
    """``1`` -> ``"1 Kauf"``, ``2`` -> ``"2 Käufe"``."""
    return f"{n} {one if n == 1 else many}"


def profile_summary(_arguments: dict[str, Any], result: CallToolResult) -> str:
    """Telemetry summary: ``"M-1001 Kaffeepause · Profil-Einwilligung ja · 3 Kategorien"``."""
    data = _payload(result)
    head = f"{data['membership_id']} {data['persona']}"
    if not data["consent"]["profiling"]:
        return f"{head} · keine Profil-Einwilligung"
    categories = _count(len(data["top_categories_8w"]), "Kategorie", "Kategorien")
    return f"{head} · Profil-Einwilligung ja · {categories}"


def behaviour_summary(_arguments: dict[str, Any], result: CallToolResult) -> str:
    """Telemetry summary: ``"100012 · M-1001: 2 Käufe in 8 Wo., zuletzt vor 35 Tagen ·
    Kartenkunden 46,7 % seltener"``."""
    data = _payload(result)
    head = f"{data['article_number']} · {data['membership_id']}"
    trend = _drop_text(data["cardholder_drop_pct"])
    if not data["consent_profiling"]:
        return f"{head}: keine Profil-Einwilligung · {trend}"
    days = data["days_since_last"]
    last = f"zuletzt vor {_count(days, 'Tag', 'Tagen')}" if days is not None else "nie gekauft"
    buys = _count(data["member_purchases_8w"], "Kauf", "Käufe")
    return f"{head}: {buys} in 8 Wo., {last} · {trend}"


def _service(api: AgentTools | None) -> AgentTools:
    if api is None:
        raise RuntimeError("this server only lists tools (--dump-tools)")
    return api


def _answer(call: Callable[[], dict[str, Any]]) -> CallToolResult:
    """Text result of ``call()``; a refused request reaches the agent as a tool error
    with the German reason (``ToolError``), anything else stays a server-side crash."""
    try:
        return mcputil.text_result(call())
    except LoyaltyError as err:
        raise ToolError(err.text) from err


def build_mcp(api: AgentTools | None, tel: Telemetry | None) -> MCPServer:
    """``gpos-loyalty-api`` with both tools (not started). ``api=None`` and ``tel=None``
    give the static tool list for ``--dump-tools``."""
    mcp = mcputil.make_server(SERVER_NAME, INSTRUCTIONS)

    @mcp.tool(description=PROFILE_DESCRIPTION, structured_output=False)
    @mcputil.telemetry(tel, caller="agent", summary=profile_summary)
    def get_member_profile(membership_id: MembershipId, ref: Ref = "") -> CallToolResult:
        return _answer(lambda: _service(api).get_member_profile(membership_id, ref))

    @mcp.tool(description=BEHAVIOUR_DESCRIPTION, structured_output=False)
    @mcputil.telemetry(tel, caller="agent", summary=behaviour_summary)
    def get_purchase_behaviour(membership_id: MembershipId, article_number: ArticleNumber,
                               ref: Ref = "") -> CallToolResult:
        return _answer(lambda: _service(api).get_purchase_behaviour(
            membership_id, article_number, ref))

    return mcp
