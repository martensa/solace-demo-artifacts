"""MCP server ``gpos-booth-tools`` (UC1-BUILD-SPEC 8.2): nine workflow tools, each a thin
``mcputil`` wrapper around the ``EngineService`` method of the same name.

Parameter order is the same in tool and service (5.1); new optional parameters are
appended after ``run_id``; the tools call the service with keyword arguments only.
The tool list is static: ``build_mcp(None, None)`` serves ``--dump-tools`` without DB,
bus or descriptors.
"""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult
from pydantic import Field

from ..common import mcputil
from ..common.telemetry import Telemetry
from .models import (
    AssessResult,
    CheckResult,
    EvidenceResult,
    OutcomeResult,
    PrepareReviewResult,
    ReviewTriggerResult,
    StageResult,
    StatusResult,
)
from .service import EngineService

NAME = "gpos-booth-tools"
INSTRUCTIONS = ("Deterministic workflow tools of the EuroCIS price agent (engine): ingest and "
                "analyse POS events, raise and prepare basket reviews, stage, check and record "
                "price proposals. Never changes a price. Fictional data only.")

RunId = Annotated[str, Field(description="Workflow run id of the calling SAM run.")]
ReviewId = Annotated[str, Field(description="Review id, e.g. GR-270216-0007.")]
ProposalId = Annotated[str, Field(description="Proposal id, e.g. GP-270216-0003.")]
Model = Annotated[str, Field(
    description="Model alias of the agent that wrote the recommendation (planning).")]
SlotArticle = Annotated[str, Field(description="Candidate article number (a), or none.")]
SlotReason = Annotated[str, Field(
    description="slow_seller|season_end|customer_behaviour|none")]
SlotHolds = Annotated[str, Field(description="yes|no|unknown")]
SlotNumbers = Annotated[str, Field(description="key=value pairs from the API results.")]
SlotTools = Annotated[str, Field(description="Agent tools called for this candidate.")]


def _head_prepare(r: PrepareReviewResult) -> str:
    if r.candidate == "yes":
        return f"yes {r.candidates} candidate{'' if r.candidates == 1 else 's'}"
    return f"no {r.reason}"


def _head_evidence(r: EvidenceResult) -> str:
    return f"noted {r.holding}/{r.checked}" if r.status == "noted" else r.status


def build_mcp(service: EngineService | None, tel: Telemetry | None) -> MCPServer:
    """The booth-tools server; ``service=None`` only for ``--dump-tools``."""
    mcp = mcputil.make_server(NAME, INSTRUCTIONS)

    def svc() -> EngineService:
        if service is None:
            raise RuntimeError("tool called on a --dump-tools server")
        return service

    @mcp.tool()
    @mcputil.telemetry(tel, caller="workflow", ref_param="event_key")
    def assess_event(
        raw: Annotated[str, Field(description="Raw GEBIT purchase event (proto3 JSON).")],
        run_id: RunId = "",
    ) -> Annotated[CallToolResult, AssessResult]:
        """Ingest one raw GEBIT POS event idempotently and analyse it (no model)."""
        r = svc().assess_event(raw=raw, run_id=run_id)
        head = " ".join(p for p in (r.verdict, r.article_number, r.insight_code) if p)
        return mcputil.structured_result("assess_event", r, head)

    @mcp.tool()
    @mcputil.telemetry(tel, caller="workflow", ref_param="tx_id")
    def raise_basket_review(
        tx_id: Annotated[str, Field(description="purchaseTransactionId of a closed basket.")],
        run_id: RunId = "",
    ) -> Annotated[CallToolResult, ReviewTriggerResult]:
        """Raise the basket review of one closed transaction (once per transaction)."""
        r = svc().raise_basket_review(tx_id=tx_id, run_id=run_id)
        return mcputil.structured_result("raise_basket_review", r,
                                         f"{r.status} {r.review_id}")

    @mcp.tool()
    @mcputil.telemetry(tel, caller="workflow", ref_param="event_key")
    def note_event(
        event_key: Annotated[str, Field(description="event_key from assess_event or an id.")],
        verdict: Annotated[str, Field(description="Verdict or status to record.")],
        run_id: RunId = "",
    ) -> Annotated[CallToolResult, StatusResult]:
        """Record an event or run that needs no further action."""
        r = svc().note_event(event_key=event_key, verdict=verdict, run_id=run_id)
        return mcputil.structured_result("note_event", r, r.status)

    @mcp.tool()
    @mcputil.telemetry(tel, caller="workflow", ref_param="review_id")
    def prepare_review(review_id: ReviewId,
                       run_id: RunId = "") -> Annotated[CallToolResult, PrepareReviewResult]:
        """Prepare a basket review: signals, guardrails and the pricing agent's input."""
        r = svc().prepare_review(review_id=review_id, run_id=run_id)
        return mcputil.structured_result("prepare_review", r, _head_prepare(r))

    @mcp.tool()
    @mcputil.telemetry(tel, caller="workflow", ref_param="review_id")
    def note_evidence(
        review_id: ReviewId,
        model: Annotated[str, Field(
            description="Model alias of the agent that gathered the evidence (fast).")] = "",
        tx_status: Annotated[str, Field(description="closed|not_closed|unknown")] = "",
        c1_article: SlotArticle = "",
        c1_reason: SlotReason = "",
        c1_holds: SlotHolds = "",
        c1_numbers: SlotNumbers = "",
        c1_tools: SlotTools = "",
        c2_article: SlotArticle = "",
        c2_reason: SlotReason = "",
        c2_holds: SlotHolds = "",
        c2_numbers: SlotNumbers = "",
        c2_tools: SlotTools = "",
        run_id: RunId = "",
    ) -> Annotated[CallToolResult, EvidenceResult]:
        """Record the evidence of the pricing agent for one prepared review (validated by the engine; no model, never a price)."""  # noqa: E501
        r = svc().note_evidence(
            review_id=review_id, model=model, tx_status=tx_status, c1_article=c1_article,
            c1_reason=c1_reason, c1_holds=c1_holds, c1_numbers=c1_numbers,
            c1_tools=c1_tools, c2_article=c2_article, c2_reason=c2_reason,
            c2_holds=c2_holds, c2_numbers=c2_numbers, c2_tools=c2_tools, run_id=run_id)
        return mcputil.structured_result("note_evidence", r, _head_evidence(r))

    @mcp.tool()
    @mcputil.telemetry(tel, caller="workflow", ref_param="review_id")
    def stage_proposal(
        review_id: ReviewId,
        article_number: Annotated[str, Field(description="Chosen candidate (a).")],
        reason: Annotated[str, Field(description="slow_seller|season_end|customer_behaviour")],
        step_pct: Annotated[str, Field(description="Agent's step, e.g. \"20\".")],
        headline: Annotated[str, Field(description="German headline, <= 70 characters.")],
        rationale: Annotated[str, Field(description="German rationale, <= 240 characters.")],
        facts_line: Annotated[str, Field(description="German key numbers, <= 120 chars.")],
        run_id: RunId = "",
        model: Model = "",
    ) -> Annotated[CallToolResult, StageResult]:
        """Stage the agent's choice as a proposal; the engine fixes step and price."""
        r = svc().stage_proposal(review_id=review_id, article_number=article_number,
                                 reason=reason, step_pct=step_pct, headline=headline,
                                 rationale=rationale, facts_line=facts_line, run_id=run_id,
                                 model=model)
        return mcputil.structured_result("stage_proposal", r,
                                         f"{r.status} {r.proposal_id or r.blocked_rule}")

    @mcp.tool()
    @mcputil.telemetry(tel, caller="workflow", ref_param="review_id")
    def close_review(
        review_id: ReviewId,
        outcome: Annotated[str, Field(
            description="no_action|no_candidates|only_blocked|deferred|failed|unknown|stale")],
        rationale: Annotated[str, Field(description="Agent rationale or SAM error.")],
        run_id: RunId = "",
        model: Model = "",
    ) -> Annotated[CallToolResult, StatusResult]:
        """Close a basket review without a proposal."""
        r = svc().close_review(review_id=review_id, outcome=outcome, rationale=rationale,
                               run_id=run_id, model=model)
        return mcputil.structured_result("close_review", r,
                                         r.verdict if r.status == "closed" else r.status)

    @mcp.tool()
    @mcputil.telemetry(tel, caller="workflow", ref_param="proposal_id")
    def check_proposal(proposal_id: ProposalId,
                       run_id: RunId = "") -> Annotated[CallToolResult, CheckResult]:
        """Check a staged proposal before approval; returns the summary texts."""
        r = svc().check_proposal(proposal_id=proposal_id, run_id=run_id)
        return mcputil.structured_result("check_proposal", r, r.status)

    @mcp.tool()
    @mcputil.telemetry(tel, caller="workflow", ref_param="proposal_id")
    def record_outcome(
        proposal_id: ProposalId,
        run_id: RunId = "",
        agent_status: Annotated[str, Field(description="Approver's status.")] = "",
        action_id: Annotated[str, Field(description="Approver's action_id.")] = "",
        error: Annotated[str, Field(description="SAM error message (on_exit).")] = "",
        approved_at: Annotated[str, Field(
            description="F2 only: time returned by the gated time tool (ISO 8601).")] = "",
        tool_message: Annotated[str, Field(
            description="Message of the gated tool result as the approver copied it "
                        "(SAM's text on a denial or timeout).")] = "",
    ) -> Annotated[CallToolResult, OutcomeResult]:
        """Record the approval outcome from the database; returns the outcome texts."""
        r = svc().record_outcome(proposal_id=proposal_id, run_id=run_id,
                                 agent_status=agent_status, action_id=action_id, error=error,
                                 approved_at=approved_at, tool_message=tool_message)
        return mcputil.structured_result("record_outcome", r, r.outcome)

    return mcp
