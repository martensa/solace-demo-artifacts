"""MCP server ``gpos-price-gate`` (UC1-BUILD-SPEC 8.3): exactly one tool, ``apply_price``.

The connector gates it (``values.hil``, 9.3); the server itself knows no gate but checks
every call against the database (11.4). The tool list is static: ``build_mcp(None,
None)`` serves ``--dump-tools``.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult
from pydantic import Field

from ...common import mcputil
from ...common.telemetry import Telemetry
from ..models import ApplyResult
from .service import GateService

NAME = "gpos-price-gate"
INSTRUCTIONS = ("apply_price is the only price-changing tool of the EuroCIS price agent demo. "
                "Every call needs the store manager's approval in Agent Mesh and is checked "
                "against the staged proposal. Fictional data only.")


def summary(_args: dict[str, Any], result: CallToolResult) -> str:
    """Telemetry summary: ``"GP-270216-0003 applied PA-270216-0003"`` (8.3)."""
    data = result.structured_content or {}
    return " ".join(str(data.get(k) or "") for k in ("proposal_id", "status", "action_id")
                    if data.get(k))


def build_mcp(service: GateService | None, tel: Telemetry | None) -> MCPServer:
    """The gate server; ``service=None`` only for ``--dump-tools``."""
    mcp = mcputil.make_server(NAME, INSTRUCTIONS)

    def svc() -> GateService:
        if service is None:
            raise RuntimeError("tool called on a --dump-tools server")
        return service

    @mcp.tool()
    @mcputil.telemetry(tel, caller="agent", ref_param="proposal_id", summary=summary)
    def apply_price(
        proposal_id: Annotated[str, Field(description="Proposal id, e.g. GP-270216-0003.")],
        proposal_hash: Annotated[str, Field(description="proposal_hash of check_proposal.")],
        article_name: Annotated[str, Field(description="Article name, copied unchanged.")],
        old_price: Annotated[str, Field(description="Old price, e.g. 9,99.")],
        new_price: Annotated[str, Field(description="New price, e.g. 7,99.")],
        pct_label: Annotated[str, Field(description="Reduction label, e.g. -20 %.")],
        reason_label: Annotated[str, Field(description="Reason label, e.g. Ladenhüter.")],
        valid_to_label: Annotated[str, Field(description="Validity, e.g. Di 23.02. 20:00.")],
        run_id: Annotated[str, Field(description="Workflow run id of the approval.")] = "",
        approved_at: Annotated[str, Field(
            description="ISO time of the approval (fallback F2 only, else empty).")] = "",
    ) -> Annotated[CallToolResult, ApplyResult]:
        """Apply one staged price proposal (idempotent per proposal)."""
        r = svc().apply_price(proposal_id, proposal_hash, article_name, old_price, new_price,
                              pct_label, reason_label, valid_to_label, run_id, approved_at)
        return mcputil.structured_result("apply_price", r,
                                         f"status={r.status} action_id={r.action_id}")

    return mcp
