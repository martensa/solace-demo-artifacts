"""Results of the workflow tools ``gpos-booth-tools`` and ``gpos-price-gate``
(UC1-BUILD-SPEC 8.2, 8.3). Field names and order are a contract with the workflows:
they read ``{{node.output.mcp_structured_content.<field>}}``."""

from __future__ import annotations

from pydantic import BaseModel


class AssessResult(BaseModel):
    verdict: str          # scan|member|void|close|cancel|ignore|duplicate|stale
    event_key: str        # "<txId>:<offset>"
    event_type: str       # e.g. "PositionAdded"
    tx_id: str = ""
    store: str = ""
    till: str = ""
    article_number: str = ""
    insight_code: str = ""   # 6.6 codes plus member|void|close|none
    insight_text: str = ""   # German, <= 120 chars


class ReviewTriggerResult(BaseModel):
    status: str           # requested|exists|not_booth_or_test|unknown_tx|not_closed
    review_id: str = ""
    tx_id: str = ""


class PrepareReviewResult(BaseModel):
    candidate: str        # yes|no
    review_id: str
    tx_id: str = ""
    membership_id: str = ""
    lines: int = 0
    candidates: int = 0
    reason: str = ""      # has_candidates|no_candidates|only_blocked|deferred|unknown|stale
    agent_input: str = "" # compact JSON, <= 1000 B (8.2.1)


class EvidenceResult(BaseModel):
    status: str           # noted|stale|unknown
    review_id: str
    checked: int = 0      # evidence items kept (<= 2)
    holding: int = 0      # items with holds "yes"
    evidence: str = ""    # compact JSON for the planner, <= 800 B (8.2.2)


class StageResult(BaseModel):
    status: str           # ready|deferred|blocked|invalid
    proposal_id: str = ""
    article_number: str = ""
    article_name: str = ""
    old_price: str = ""   # "9,99"
    new_price: str = ""   # "7,99"
    pct_label: str = ""   # "-20 %" (ASCII hyphen)
    reason_label: str = ""
    step_pct: int = 0     # engine step (= suggested_step_pct)
    clamped: bool = False # true: the agent's step_pct differed and was corrected
    blocked_rule: str = ""
    text_source: str = "" # ai|template (ai = the planner's KI-Empfehlung survived 11.3)


class CheckResult(BaseModel):
    status: str           # awaiting_approval|unknown|stale|superseded|decided|probe
    proposal_id: str
    proposal_hash: str = ""
    article_name: str = ""
    old_price: str = ""
    new_price: str = ""
    pct_label: str = ""
    reason_label: str = ""
    valid_to_label: str = ""
    notify_title: str = ""    # <= 90 chars
    notify_message: str = ""  # <= 600 chars


class OutcomeResult(BaseModel):
    outcome: str          # approved|rejected|expired|failed|superseded|blocked|unknown
    proposal_id: str
    action_id: str = ""
    notify: str = "no"    # yes = texts filled, node tell runs (9.5, 11.6)
    notify_title: str = ""
    notify_message: str = ""


class StatusResult(BaseModel):
    status: str           # noted|closed|unknown
    event_key: str = ""
    verdict: str = ""


class ApplyResult(BaseModel):
    status: str           # applied|already_applied|blocked|superseded|expired|unknown
    proposal_id: str
    action_id: str = ""
    new_price: str = ""
    message: str = ""     # German, <= 160 chars, reason for blocked etc.
