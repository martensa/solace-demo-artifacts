"""Helpers of the WP-F db tests: drive engine and gate the way the SAM workflows do."""

from __future__ import annotations

from typing import Any

from gposdemo.common.bus import MemoryBus
from gposdemo.engine import Engine
from gposdemo.engine.gate import Gate
from gposdemo.engine.models import (
    CheckResult,
    EvidenceResult,
    PrepareReviewResult,
    StageResult,
)
from tests.engine.fakes import FakeClock, PosWriter

S1_TEXTS = {"headline": "GEBIT Ente: Abverkauf ankurbeln",
            "rationale": "Nur 9 von 35 geplanten Enten in 7 Tagen verkauft; der Bestand "
                         "reicht 6,5 Wochen.",
            "facts_line": "9/35 verkauft (7 Tage) · Bestand 96 · Reichweite 6,5 Wo."}
# 8.2.2: what the evidence agent (fast) reports for S1, as node note passes it
S1_EVIDENCE = {"article": "100001", "reason": "slow_seller", "holds": "yes",
               "numbers": "trend=falling; sold_7d=9; plan_7d=35; weeks_of_supply=6.5; "
                          "weekly_first=34; weekly_last=9",
               "tools": "get_sales_performance"}
NONE_SLOT = {"article": "none", "reason": "none", "holds": "unknown", "numbers": "none",
             "tools": "none"}


def published(engine: Engine, bus: MemoryBus, topic_filter: str) -> list[dict[str, Any]]:
    """Publish the engine outbox now and return the JSON bodies matching the filter."""
    while engine.relay.drain():
        pass
    return [m.json() for m in bus.messages(topic_filter)]


def prepared(engine: Engine, pos: PosWriter, numbers: list[str], *, till: str = "01",
             membership_id: str | None = None) -> PrepareReviewResult:
    """Closed basket -> raise_basket_review -> prepare_review."""
    basket = pos.basket(numbers, till=till, membership_id=membership_id)
    raised = engine.service.raise_basket_review(basket.tx_id, "run-r1")
    assert raised.status == "requested", raised
    return engine.service.prepare_review(raised.review_id, "run-r3")


def evidenced(engine: Engine, prep: PrepareReviewResult,
              items: list[dict[str, str]] | None = None, *, model: str = "fast",
              tx_status: str = "closed") -> EvidenceResult:
    """``note_evidence`` with the flat slots c1/c2 of node ``note`` (default: S1)."""
    slots = ([S1_EVIDENCE] if items is None else list(items))[:2]
    slots += [NONE_SLOT] * (2 - len(slots))
    args = {f"c{n}_{key}": value for n, slot in enumerate(slots, 1)
            for key, value in slot.items()}
    return engine.service.note_evidence(prep.review_id, model=model, tx_status=tx_status,
                                        run_id="run-r3", **args)


def staged(engine: Engine, prep: PrepareReviewResult, article_number: str, reason: str,
           step_pct: str, **texts: str) -> StageResult:
    return engine.service.stage_proposal(prep.review_id, article_number, reason, step_pct,
                                         run_id="run-r3", model="planning",
                                         **{**S1_TEXTS, **texts})


def checked(engine: Engine, stage: StageResult, run_id: str = "run-r4") -> CheckResult:
    check = engine.service.check_proposal(stage.proposal_id, run_id)
    assert check.status == "awaiting_approval", check
    return check


def card(check: CheckResult, **changes: str) -> dict[str, str]:
    """The ``apply_price`` arguments the approver copies from ``check``."""
    args = {k: getattr(check, k) for k in ("proposal_id", "proposal_hash", "article_name",
                                           "old_price", "new_price", "pct_label",
                                           "reason_label", "valid_to_label")}
    return {**args, "run_id": "run-r4", **changes}


def approve(gate: Gate, clock: FakeClock, check: CheckResult, after_s: float = 4.0,
            **changes: str) -> Any:
    """The store manager answers ``after_s`` seconds after ``check_proposal``."""
    clock.advance(after_s)
    return gate.service.apply_price(**card(check, **changes))


def approval_row(engine: Engine, proposal_id: str) -> dict[str, Any]:
    proposal = engine.service.proposal(proposal_id)
    assert proposal is not None and proposal["approval"] is not None
    return proposal["approval"]
