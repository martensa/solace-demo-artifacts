"""Basket review: ``raise_basket_review``, ``prepare_review``, ``note_evidence``,
``close_review`` and the agent input with its overflow rule (UC1-BUILD-SPEC 8.2.1,
8.2.2, 11.2).

``deferred`` is decided before any model call: while the till has an open proposal
(``ready``/``pending``) a new review of that till ends ``deferred`` and is never
resumed (1.2).

``note_evidence`` (no model, 0 tokens) checks the flat output of the evidence agent
(``gpos-pricing-agent``, alias ``fast``) before the planner sees it: only free
candidates of the review, known enums, capped lengths, known agent tool names; it
stores the evidence in ``review.agent_decision`` and publishes ``prepared`` again.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from ..common.jsonutil import compact
from . import signals, store, texts
from .clients import ArticleFacts, MemberFacts
from .context import Context
from .models import EvidenceResult, PrepareReviewResult, ReviewTriggerResult, StatusResult
from .proposals import model_alias
from .policy import Policy
from .records import ReviewRecord
from .signals import Assessment
from .validator import clean

log = logging.getLogger(__name__)

CLOSE_OUTCOMES = ("no_action", "no_candidates", "only_blocked", "deferred", "failed")
LOG_ONLY_OUTCOMES = ("unknown", "stale")
# note_evidence (8.2.2)
AGENT_TOOLS = ("get_transaction", "get_article", "get_sales_performance", "get_season_info",
               "get_purchase_behaviour", "get_member_profile")
HOLDS = ("yes", "no", "unknown")
TX_STATES = ("closed", "not_closed", "unknown")
EVIDENCE_MODELS = ("fast", "planning")
# UC1-32 (16.1 Nr. 41): numbers as long as the evidence agent may write them (9.4). The
# document cap fits two items with 160 ASCII characters each, the two longest article
# names, three tools, "planning"/"not_closed"/"unknown" (measured 755-765 B); only
# beyond that NUMBERS_SHORT applies. Real documents (lab data): S1-S8 221-450 B, the
# largest pair of free candidates 583 B.
EVIDENCE_MAX_BYTES = 800
NUMBERS_MAX = 160
NUMBERS_SHORT = 60
TOOLS_MAX = 3
TOOL_SPLIT = re.compile(r"[,;\s]+")
EMPTY_WORDS = ("none", "-", "null")


@dataclass(frozen=True)
class Slot:
    """One evidence slot (c1/c2) of the evidence agent, as the workflow passes it."""

    article: str = ""
    reason: str = ""
    holds: str = ""
    numbers: str = ""
    tools: str = ""


def slot_value(value: str) -> str:
    """``""`` for an empty, unresolved (``{{…}}``) or "none"/"-"/"null" value."""
    text = (value or "").strip()
    if not text or "{{" in text or text.casefold() in EMPTY_WORDS:
        return ""
    return text


def _evidence_size(doc: dict[str, Any]) -> int:
    return len(compact(doc).encode("utf-8"))


def fit_evidence(doc: dict[str, Any]) -> dict[str, Any]:
    """8.2.2 size cap: first every ``numbers`` to 60 characters, then drop items from
    the end until the compact JSON fits :data:`EVIDENCE_MAX_BYTES`."""
    if _evidence_size(doc) <= EVIDENCE_MAX_BYTES:
        return doc
    for item in doc["items"]:
        item["numbers"] = texts.shorten(item["numbers"], NUMBERS_SHORT)
    while _evidence_size(doc) > EVIDENCE_MAX_BYTES and doc["items"]:
        doc["items"].pop()
    return doc


def evidence_doc(review: ReviewRecord, model: str, tx_status: str,
                 slots: list[Slot]) -> dict[str, Any]:
    """The checked evidence document ``{"model","tx","items":[…]}`` (8.2.2, rules 2-10)."""
    free = {ln["article_number"]: ln for ln in review.lines
            if ln.get("candidate") and not ln.get("blocked")}
    items: list[dict[str, Any]] = []
    for n, slot in enumerate(slots, 1):
        article = slot_value(slot.article)
        line = free.get(article)
        if line is None or any(it["a"] == article for it in items):
            if article:
                log.info("note_evidence %s: slot c%d %r dropped (no free candidate or twice)",
                         review.review_id, n, article)
            continue
        line_signals = [str(sig) for sig in line.get("signals", [])]
        holds = slot_value(slot.holds).casefold()
        holds = holds if holds in HOLDS else "unknown"
        reason = slot_value(slot.reason)
        if reason not in line_signals:
            log.info("note_evidence %s: slot c%d reason %r not a signal of %s",
                     review.review_id, n, reason, article)
            reason, holds = (line_signals[0] if line_signals else "none"), "unknown"
        tools: list[str] = []
        for name in TOOL_SPLIT.split(slot_value(slot.tools)):
            if name in AGENT_TOOLS and name not in tools:
                tools.append(name)
        items.append({"a": article, "name": line["name"], "reason": reason, "holds": holds,
                      "numbers": texts.shorten(clean(slot_value(slot.numbers)), NUMBERS_MAX),
                      "tools": tools[:TOOLS_MAX]})
    tx = slot_value(tx_status).casefold()
    alias = slot_value(model)
    return fit_evidence({"model": alias if alias in EVIDENCE_MODELS else "fast",
                         "tx": tx if tx in TX_STATES else "unknown", "items": items})


@dataclass(frozen=True)
class BasketView:
    """What ``prepare_review`` evaluates: lines (one per article) and the card."""

    assessments: list[Assessment]
    card: dict[str, Any] | None


def card_json(membership_id: str, member: MemberFacts | None) -> dict[str, Any]:
    """``card`` of 8.2.1: ``membership_id``, ``persona``, ``consent_profiling``."""
    if member is None:
        return {"membership_id": membership_id, "persona": "", "consent_profiling": False}
    return {"membership_id": membership_id, "persona": member.persona,
            "consent_profiling": member.consent_profiling}


def line_json(a: Assessment) -> dict[str, Any]:
    """One entry of ``review.lines`` (7.2); steps only for free candidates."""
    line: dict[str, Any] = {"article_number": a.article_number, "name": a.name,
                            "signals": list(a.signals), "candidate": a.candidate,
                            "blocked": a.blocked}
    if a.free:
        line["suggested_step_pct"] = a.suggested_step_pct
        line["max_step_pct"] = a.max_step_pct
    line["facts"] = a.line_facts
    return line


def _size(doc: dict[str, Any]) -> int:
    return len(compact(doc).encode("utf-8"))


def agent_input(review: ReviewRecord, view: BasketView, policy: Policy) -> str:
    """Compact JSON for the pricing agent, <= ``agent_input_max_bytes`` (8.2.1).

    Free candidates by reason priority, then stock value (descending); blocked
    articles only as ``{"name", "why"}``; candidates never carry ``blocked``.
    """
    limits = policy.review
    free = sorted((a for a in view.assessments if a.free),
                  key=lambda a: (policy.priority(a.signals[0]), -a.stock_value))
    doc: dict[str, Any] = {
        "review_id": review.review_id, "tx_id": review.tx_id, "till": review.till_id,
        "card": view.card,
        "candidates": [{"a": a.article_number, "name": a.name, "signals": list(a.signals),
                        "facts": a.line_facts, "suggested_step_pct": a.suggested_step_pct,
                        "max_step_pct": a.max_step_pct}
                       for a in free[:limits.max_candidates_in_agent_input]],
        "blocked": [{"name": a.name, "why": a.blocked} for a in view.assessments
                    if a.candidate and a.blocked][:limits.max_blocked_in_agent_input],
        "no_action": [a.name for a in view.assessments
                      if not a.candidate][:limits.max_no_action_names]}
    return compact(fit(doc, policy))


def fit(doc: dict[str, Any], policy: Policy) -> dict[str, Any]:
    """Overflow rule of 8.2.1, in this order until the JSON fits: (1) every ``facts`` to
    80 characters with "…", (2) drop ``no_action``, (3) drop ``blocked``, (4) drop
    candidates from the end."""
    limit = policy.review.agent_input_max_bytes
    if _size(doc) <= limit:
        return doc
    for candidate in doc["candidates"]:
        candidate["facts"] = texts.shorten(candidate["facts"], policy.review.facts_short_chars)
    for key in ("no_action", "blocked"):
        if _size(doc) <= limit:
            return doc
        doc[key] = []
    while _size(doc) > limit and doc["candidates"]:
        doc["candidates"].pop()
    return doc


class Reviews:
    """Implements ``raise_basket_review``, ``prepare_review`` and ``close_review``."""

    def __init__(self, ctx: Context):
        self.ctx = ctx

    # ------------------------------------------------------------- raise
    def raise_review(self, tx_id: str, run_id: str) -> ReviewTriggerResult:
        with self.ctx.db.tx() as conn:
            bask = store.basket(conn, tx_id)
            if bask is None:
                return ReviewTriggerResult(status="unknown_tx", tx_id=tx_id)
            if not self.ctx.known_till(bask["store_id"], bask["till_id"]):
                return ReviewTriggerResult(status="not_booth_or_test", tx_id=tx_id)
            if bask["status"] != "CLOSED":
                return ReviewTriggerResult(status="not_closed", tx_id=tx_id)
            existing = store.review_of_tx(conn, tx_id)
            if existing is not None:
                return ReviewTriggerResult(status="exists", review_id=existing.review_id,
                                           tx_id=tx_id)
            review_id = store.next_id(conn, "review", self.ctx.demo_date)
            row = conn.execute(
                "insert into engine.review (review_id, tx_id, store_id, till_id, "
                "membership_id, status, run_id_raise, created_at) "
                "values (%s, %s, %s, %s, %s, 'requested', %s, %s) "
                "on conflict (tx_id) do nothing returning review_id",
                (review_id, tx_id, bask["store_id"], bask["till_id"], bask["membership_id"],
                 run_id or None, self.ctx.clock())).fetchone()
            if row is None:  # a parallel run won the race
                existing = store.review_of_tx(conn, tx_id)
                return ReviewTriggerResult(status="exists", tx_id=tx_id,
                                           review_id=existing.review_id if existing else "")
            review = store.review(conn, review_id)
            assert review is not None
            self.ctx.emitter.review_request(conn, review)
            self.ctx.emitter.review_state(conn, review, run_id)
        return ReviewTriggerResult(status="requested", review_id=review_id, tx_id=tx_id)

    # ------------------------------------------------------------- prepare
    def prepare(self, review_id: str, run_id: str) -> PrepareReviewResult:
        with self.ctx.db.tx() as conn:
            review = store.review(conn, review_id)
        if review is None:
            return PrepareReviewResult(candidate="no", review_id=review_id, reason="unknown")
        if review.status != "requested":
            return self._no(review, "stale")
        if self._has_open_proposal(review):
            return self._defer(review, run_id)
        view = self._basket_view(review)
        free = [a for a in view.assessments if a.free]
        if free:
            status, reason = "prepared", "has_candidates"
        elif any(a.candidate for a in view.assessments):
            status, reason = "only_blocked", "only_blocked"
        else:
            status, reason = "no_candidates", "no_candidates"
        lines = [line_json(a) for a in view.assessments]
        text = agent_input(review, view, self.ctx.policy) if free else None
        with self.ctx.db.tx() as conn:
            current = store.review(conn, review_id, lock=True)
            if current is None or current.status != "requested":
                return self._no(review, "stale")
            if store.open_proposal(conn, review.store_id, review.till_id):
                return self._defer_locked(conn, current, run_id)
            now = self.ctx.clock()
            updated = store.set_review(
                conn, review_id, status=status, lines=lines, agent_input=text,
                run_id_review=run_id or None, prepared_at=now,
                decided_at=None if status == "prepared" else now)
            self.ctx.emitter.review_state(conn, updated, run_id, card=view.card)
        return PrepareReviewResult(
            candidate="yes" if free else "no", review_id=review_id, tx_id=review.tx_id,
            membership_id=review.membership_id or "", lines=len(lines), candidates=len(free),
            reason=reason, agent_input=text or "")

    def _no(self, review: ReviewRecord, reason: str) -> PrepareReviewResult:
        return PrepareReviewResult(candidate="no", review_id=review.review_id,
                                   tx_id=review.tx_id, membership_id=review.membership_id or "",
                                   reason=reason)

    def _has_open_proposal(self, review: ReviewRecord) -> bool:
        with self.ctx.db.tx() as conn:
            return store.open_proposal(conn, review.store_id, review.till_id) is not None

    def _defer(self, review: ReviewRecord, run_id: str) -> PrepareReviewResult:
        with self.ctx.db.tx() as conn:
            current = store.review(conn, review.review_id, lock=True)
            if current is None or current.status != "requested":
                return self._no(review, "stale")
            return self._defer_locked(conn, current, run_id)

    def _defer_locked(self, conn: store.Conn, review: ReviewRecord,
                      run_id: str) -> PrepareReviewResult:
        updated = store.set_review(conn, review.review_id, status="deferred",
                                   run_id_review=run_id or None, decided_at=self.ctx.clock(),
                                   error="Offene Freigabe an dieser Kasse")
        self.ctx.emitter.review_state(conn, updated, run_id)
        return self._no(review, "deferred")

    def _basket_view(self, review: ReviewRecord) -> BasketView:
        with self.ctx.db.tx() as conn:
            rows = store.basket_lines(conn, review.tx_id)
        member, card = None, None
        if review.membership_id:
            member = self.ctx.loyalty.profile(review.membership_id, review.review_id)
            card = card_json(review.membership_id, member)
        seen: dict[str, Assessment] = {}
        for row in rows:
            if row["article_number"] not in seen:
                seen[row["article_number"]] = self._assess(review, row, member)
        return BasketView(list(seen.values()), card)

    def _assess(self, review: ReviewRecord, row: dict[str, Any],
                member: MemberFacts | None) -> Assessment:
        number, store_id, trace = row["article_number"], review.store_id, review.review_id
        article: ArticleFacts | None = self.ctx.wws.article(number, store_id, trace)
        sales = self.ctx.wws.sales(number, store_id, trace)
        if article is None or sales is None:
            log.warning("review %s: article %s unknown in WWS", review.review_id, number)
            return Assessment(article_number=number, name=row["name"],
                              insight_text=texts.INSIGHT_UNAVAILABLE,
                              line_facts=texts.INSIGHT_UNAVAILABLE)
        season = self.ctx.wws.season(number, store_id, trace) if article.season_code else None
        behaviour = None
        if member is not None and member.consent_profiling:
            behaviour = self.ctx.loyalty.behaviour(member.membership_id, number, trace)
        return signals.evaluate(article, sales, season, behaviour, self.ctx.policy,
                                self.ctx.demo_date)

    # ------------------------------------------------------------- evidence
    def note_evidence(self, review_id: str, model: str, tx_status: str, slots: list[Slot],
                      run_id: str) -> EvidenceResult:
        """8.2.2: validate, store and publish the evidence of one prepared review."""
        with self.ctx.db.tx() as conn:
            review = store.review(conn, review_id, lock=True)
            if review is None:
                return EvidenceResult(status="unknown", review_id=review_id)
            if review.status != "prepared":
                log.info("note_evidence %s: review is %s", review_id, review.status)
                return EvidenceResult(status="stale", review_id=review_id)
            doc = evidence_doc(review, model, tx_status, slots)
            updated = store.set_review(conn, review_id, agent_decision={"evidence": doc})
            self.ctx.emitter.review_state(conn, updated, run_id)
        return EvidenceResult(status="noted", review_id=review_id, checked=len(doc["items"]),
                              holding=sum(1 for it in doc["items"] if it["holds"] == "yes"),
                              evidence=compact(doc))

    # ------------------------------------------------------------- close
    def close(self, review_id: str, outcome: str, rationale: str, run_id: str,
              model: str = "") -> StatusResult:
        if outcome in LOG_ONLY_OUTCOMES or outcome not in CLOSE_OUTCOMES:
            log.info("close_review %s: outcome %r logged only", review_id, outcome)
            return StatusResult(status="noted", event_key=review_id, verdict=outcome)
        with self.ctx.db.tx() as conn:
            review = store.review(conn, review_id, lock=True)
            if review is None:
                return StatusResult(status="unknown", event_key=review_id, verdict=outcome)
            if not review.is_open:
                return StatusResult(status="closed", event_key=review_id,
                                    verdict=review.status)
            text = texts.shorten(clean(rationale), self.ctx.policy.texts.rationale_max)
            changes: dict[str, Any] = {"status": outcome, "decided_at": self.ctx.clock()}
            if outcome == "no_action":  # keeps the evidence of note_evidence
                changes["agent_decision"] = {**(review.agent_decision or {}),
                                             "decision": "no_action", "rationale": text,
                                             "model": model_alias(model, review_id)}
            elif text:
                changes["error"] = text
            updated = store.set_review(conn, review_id, **changes)
            self.ctx.emitter.review_state(conn, updated, run_id)
        return StatusResult(status="closed", event_key=review_id, verdict=outcome)
