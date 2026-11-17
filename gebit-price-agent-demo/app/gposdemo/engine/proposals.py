"""``stage_proposal`` (the engine decides) and ``check_proposal`` (UC1-BUILD-SPEC 11.3,
11.4).

The planner (``gpos-price-planner``, alias ``planning``) chooses the article, the reason
and the words of the KI-Empfehlung; the engine checks that the article is a free
candidate with a confirmed evidence item (step 2b: ``holds`` "yes" from
``note_evidence``), fixes the step (``suggested_step_pct`` of the candidate), checks the
guardrails with fresh WWS data, computes price point, ``ref30``, margin and validity,
and stages the proposal. The stored ``review.agent_decision`` keeps the planner's
decision with ``model`` and the evidence. The partial unique index
``proposal_one_open_per_till`` catches a race after ``prepare_review`` (-> ``deferred``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from ..common.fmt import dt_label, eur
from ..common.jsonutil import sha256_hex
from . import notify, pricing, store, texts, validator
from .clients import ArticleFacts
from .context import Context
from .guardrails import guardrail_rows
from .models import CheckResult, StageResult
from .records import ProposalRecord, ReviewRecord

log = logging.getLogger(__name__)

READY_TIMEOUT_S = 60
PROBE_NOTIFY_PREFIX = "probe-notify-"
INVALID_CANDIDATE = "Agent wählte keinen gültigen Kandidaten"
INVALID_EVIDENCE = "KI-Empfehlung ohne bestätigten Beleg"
INVALID_REASON = "Anlass passt nicht zum Kandidaten"
NO_CONSENT = "Kundenverhalten ohne Profil-Einwilligung"
NOT_PREPARED = "Review nicht vorbereitet"
REASON_CORRECTED = "Anlass korrigiert"
DEFERRED = "Offene Freigabe an dieser Kasse"
UNKNOWN_ARTICLE = "Artikel unbekannt"
MODELS = ("fast", "planning")
DECISION_TEXT_MAX = 400


def model_alias(model: str, ref: str) -> str:
    """``fast``/``planning``, else ``""`` (consumers read ``""`` as ``fast``)."""
    value = (model or "").strip()
    if value in MODELS:
        return value
    if value and "{{" not in value:
        log.warning("%s: model %r is no alias of %s, stored as ''", ref, value, MODELS)
    return ""


def stored_evidence(review: ReviewRecord) -> dict[str, Any] | None:
    """The evidence ``note_evidence`` stored in ``review.agent_decision`` (or ``None``)."""
    evidence = (review.agent_decision or {}).get("evidence")
    return evidence if isinstance(evidence, dict) else None


def evidence_item(evidence: dict[str, Any] | None, article_number: str
                  ) -> dict[str, Any] | None:
    if evidence is None:
        return None
    return next((it for it in evidence.get("items", [])
                 if isinstance(it, dict) and it.get("a") == article_number), None)


def proposal_hash(proposal_id: str, article_number: str, regular: Decimal, new: Decimal,
                  valid_to_iso: str) -> str:
    """First 10 hex characters of ``sha256("<id>|<article>|<regular>|<new>|<valid_to>")``."""
    return sha256_hex(f"{proposal_id}|{article_number}|{regular:.2f}|{new:.2f}|"
                      f"{valid_to_iso}")[:10]


def parse_step(text: str) -> int | None:
    """The agent's ``step_pct`` (``"20"``) as an int; ``None`` when it is no number."""
    try:
        return int(text.strip())
    except (ValueError, AttributeError):
        return None


def block_rule(article: ArticleFacts, max_step: int) -> str:
    """Why fresh WWS data forbids a reduction now (race with a price change)."""
    if article.price_bound:
        return texts.BLOCK_PRICE_BOUND
    if article.price.action_open:
        return texts.action_block(article.price.source, article.price.valid_to)
    return texts.BLOCK_MIN_MARGIN if max_step == 0 else ""


@dataclass(frozen=True)
class Draft:
    """Everything of a proposal except id and hash."""

    review: ReviewRecord
    article: ArticleFacts
    reason: str
    step_requested: int
    step: int
    clamped: bool
    status_reason: str
    option: pricing.StepOption
    valid_from: datetime
    valid_to: datetime
    guardrails: list[dict[str, Any]]
    texts: validator.ProposalTexts
    decision: dict[str, Any]


class Proposals:
    """Implements ``stage_proposal`` and ``check_proposal``."""

    def __init__(self, ctx: Context):
        self.ctx = ctx

    # ------------------------------------------------------------- stage
    def stage(self, review_id: str, article_number: str, reason: str, step_pct: str,
              headline: str, rationale: str, facts_line: str, run_id: str = "",
              model: str = "") -> StageResult:
        article_number, reason = article_number.strip(), reason.strip()
        model = model_alias(model, review_id)
        with self.ctx.db.tx() as conn:
            review = store.review(conn, review_id)
        if review is None or review.status != "prepared":
            return StageResult(status="invalid", article_number=article_number,
                               blocked_rule=NOT_PREPARED)
        evidence = stored_evidence(review)
        raw = {"decision": "propose", "article_number": article_number, "reason": reason,
               "step_pct": step_pct, "headline": headline, "rationale": rationale,
               "facts_line": facts_line}
        stored: dict[str, Any] = {
            **{k: texts.shorten(validator.clean(v), DECISION_TEXT_MAX) for k, v in raw.items()},
            "model": model, **({"evidence": evidence} if evidence else {})}
        line = next((ln for ln in review.lines
                     if ln["article_number"] == article_number and ln["candidate"]), None)
        if line is None or line["blocked"]:
            return self._refuse(review, run_id, "invalid", INVALID_CANDIDATE, article_number,
                                stored)
        item = evidence_item(evidence, article_number)
        if evidence is not None and (item is None or item.get("holds") != "yes"):  # 2b
            return self._refuse(review, run_id, "invalid", INVALID_EVIDENCE, article_number,
                                stored)
        chosen, corrected = self._reason(line, reason)
        if chosen is None:
            return self._refuse(review, run_id, "invalid", INVALID_REASON, article_number,
                                stored)
        if chosen == "customer_behaviour" and not review.membership_id:
            return self._refuse(review, run_id, "invalid", NO_CONSENT, article_number, stored)
        article = self.ctx.wws.article(article_number, review.store_id, review_id)
        if article is None:
            return self._refuse(review, run_id, "blocked", UNKNOWN_ARTICLE, article_number,
                                stored)
        options = pricing.step_options(article.price.regular_price, article.cost_net,
                                       article.vat_percent, self.ctx.policy)
        fresh_max = pricing.max_step(options)
        rule = block_rule(article, fresh_max)
        if rule:
            return self._refuse(review, run_id, "blocked", rule, article_number, stored)
        draft = self._draft(review, line, article, options, chosen, corrected, step_pct,
                            min(int(line["suggested_step_pct"]), fresh_max), raw, stored,
                            str(item.get("numbers", "")) if item else "")
        return self._insert(draft, run_id)

    def _reason(self, line: dict[str, Any], reason: str) -> tuple[str | None, bool]:
        """11.3 step 3: the agent's reason, or the only signal (corrected), or ``None``."""
        signals = list(line["signals"])
        if reason in signals:
            return reason, False
        if len(signals) == 1:
            return signals[0], True
        return None, False

    def _draft(self, review: ReviewRecord, line: dict[str, Any], article: ArticleFacts,
               options: list[pricing.StepOption], reason: str, corrected: bool,
               step_pct: str, step: int, raw: dict[str, str], stored: dict[str, Any],
               evidence_numbers: str) -> Draft:
        requested = parse_step(step_pct)
        notes = [REASON_CORRECTED] if corrected else []
        clamped = requested != step
        if clamped:
            shown = texts.shorten(validator.clean(step_pct), 10) or "–"
            notes.append(f"Stufe korrigiert ({shown} → {step} %)")
        option = pricing.option_for(options, step)
        assert option.price is not None
        regular, ref30 = article.price.regular_price, article.price.ref30
        valid_from, valid_to = pricing.validity(self.ctx.demo_date, self.ctx.policy,
                                                self.ctx.zone)
        rows = guardrail_rows(option, options, regular=regular,
                              price_bound=article.price_bound,
                              action_open=article.price.action_open,
                              valid_to_label=dt_label(valid_to),
                              min_margin_pct=self.ctx.policy.guardrails.min_margin_pct)
        shown = pricing.pct_shown(ref30, option.price)
        checked = validator.proposal_texts(
            raw["headline"], raw["rationale"], raw["facts_line"],
            article_name=article.name, reason=reason, facts=str(line["facts"]),
            allowed_amounts={eur(regular), eur(option.price), eur(ref30)},
            limits=self.ctx.policy.texts,
            allowed_percents=validator.allowed_percents(shown, str(line["facts"]),
                                                        evidence_numbers))
        return Draft(review, article, reason, requested or 0, step, clamped,
                     "; ".join(notes), option, valid_from, valid_to, rows, checked, stored)

    def _insert(self, d: Draft, run_id: str) -> StageResult:
        r, a = d.review, d.article
        new_price = d.option.price
        assert new_price is not None and d.option.margin_pct is not None
        with self.ctx.db.tx() as conn:
            current = store.review(conn, r.review_id, lock=True)
            if current is None or current.status != "prepared":
                return StageResult(status="invalid", article_number=a.article_number,
                                   blocked_rule=NOT_PREPARED)
            if store.open_proposal(conn, r.store_id, r.till_id):
                return self._defer(conn, current, run_id, a.article_number)
            proposal_id = store.next_id(conn, "proposal", self.ctx.demo_date)
            values = (
                proposal_id, r.review_id, r.tx_id, r.store_id, r.till_id, a.article_number,
                a.name, d.reason, d.step_requested, d.step, d.clamped, a.price.regular_price,
                new_price, a.price.ref30, pricing.pct_shown(a.price.ref30, new_price),
                pricing.round_tenth(d.option.margin_pct),
                pricing.base_price_label(new_price, a.net_quantity, a.base_unit) or None,
                d.valid_from, d.valid_to, d.texts.headline, d.texts.rationale,
                d.texts.facts_line,
                pricing.price_note(a.last_price_change, new_price, self.ctx.demo_date),
                d.texts.source, Jsonb(d.guardrails),
                proposal_hash(proposal_id, a.article_number, a.price.regular_price, new_price,
                              d.valid_to.isoformat()),
                d.status_reason or None, run_id or None, self.ctx.clock())
            try:
                with conn.transaction():
                    conn.execute(
                        "insert into engine.proposal (proposal_id, review_id, tx_id, store_id, "
                        "till_id, article_number, article_name, reason, step_requested, "
                        "step_pct, clamped, regular_price, new_price, ref30, pct_shown, "
                        "margin_pct_new, base_price_label, valid_from, valid_to, headline, "
                        "rationale, facts_line, note, text_source, guardrails, proposal_hash, "
                        "status, status_reason, run_id_stage, created_at) values (%s, %s, %s, "
                        "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                        "%s, %s, %s, %s, %s, %s, 'ready', %s, %s, %s)", values)
            except psycopg.errors.UniqueViolation:
                return self._defer(conn, current, run_id, a.article_number)
            # the review first: proposal.ai_model reads review.agent_decision->>'model'
            review = store.set_review(conn, r.review_id, status="proposed",
                                      agent_decision=d.decision, decided_at=self.ctx.clock())
            p = store.proposal(conn, proposal_id)
            assert p is not None
            self.ctx.emitter.proposal_state(conn, p, run_id)
            self.ctx.emitter.approval_request(conn, p)
            self.ctx.emitter.review_state(conn, review, run_id, proposal_id=proposal_id)
        return StageResult(status="ready", proposal_id=p.proposal_id,
                           article_number=p.article_number, article_name=p.article_name,
                           old_price=p.old_label, new_price=p.new_label,
                           pct_label=p.pct_label_ascii, reason_label=p.reason_label,
                           step_pct=p.step_pct, clamped=p.clamped, text_source=p.text_source)

    def _defer(self, conn: store.Conn, review: ReviewRecord, run_id: str,
               article_number: str) -> StageResult:
        updated = store.set_review(conn, review.review_id, status="deferred", error=DEFERRED,
                                   decided_at=self.ctx.clock())
        self.ctx.emitter.review_state(conn, updated, run_id)
        return StageResult(status="deferred", article_number=article_number,
                           blocked_rule=DEFERRED)

    def _refuse(self, review: ReviewRecord, run_id: str, status: str, rule: str,
                article_number: str, stored: dict[str, Any]) -> StageResult:
        """``invalid``/``blocked``: the review ends ``blocked`` with the rule as reason and
        keeps the planner's decision (monitor: "planning empfahl X, Engine blockiert")."""
        with self.ctx.db.tx() as conn:
            current = store.review(conn, review.review_id, lock=True)
            if current is not None and current.status == "prepared":
                updated = store.set_review(conn, review.review_id, status="blocked",
                                           error=rule, agent_decision=stored,
                                           decided_at=self.ctx.clock())
                self.ctx.emitter.review_state(conn, updated, run_id)
        log.info("stage_proposal %s: %s (%s)", review.review_id, status, rule)
        return StageResult(status=status, article_number=article_number, blocked_rule=rule)

    # ------------------------------------------------------------- check
    def check(self, proposal_id: str, run_id: str) -> CheckResult:
        if proposal_id.startswith(PROBE_NOTIFY_PREFIX):
            return CheckResult(status="probe", proposal_id=proposal_id,
                               notify_title=notify.PROBE_TITLE,
                               notify_message=notify.PROBE_MESSAGE)
        with self.ctx.db.tx() as conn:
            p = store.proposal(conn, proposal_id, lock=True)
            if p is None:
                return CheckResult(status="unknown", proposal_id=proposal_id)
            if p.status == "superseded":
                return CheckResult(status="superseded", proposal_id=proposal_id)
            if p.status != "ready":
                return CheckResult(status="decided", proposal_id=proposal_id)
            now = self.ctx.clock()
            if (now - p.created_at).total_seconds() > READY_TIMEOUT_S:
                p = store.set_proposal(conn, proposal_id, status="failed",
                                       status_reason="Freigabe-Lauf zu spät gestartet",
                                       decided_at=now, run_id_approval=run_id or None)
                self.ctx.emitter.proposal_state(conn, p, run_id)
                return CheckResult(status="stale", proposal_id=proposal_id)
            p = store.set_proposal(conn, proposal_id, status="pending", pending_at=now,
                                   run_id_approval=run_id or None)
            conn.execute("insert into engine.approval (proposal_id, run_id, checked_at) "
                         "values (%s, %s, %s) on conflict (proposal_id) do update "
                         "set run_id = excluded.run_id, checked_at = excluded.checked_at",
                         (proposal_id, run_id, now))
            self.ctx.emitter.proposal_state(conn, p, run_id)
        return self.awaiting(p)

    def awaiting(self, p: ProposalRecord) -> CheckResult:
        """``awaiting_approval`` with the labels the approver copies and the summary."""
        title, message = notify.inform(p, self.ctx.zone, self.ctx.policy.guardrails.min_margin_pct)
        return CheckResult(status="awaiting_approval", proposal_id=p.proposal_id,
                           proposal_hash=p.proposal_hash, article_name=p.article_name,
                           old_price=p.old_label, new_price=p.new_label,
                           pct_label=p.pct_label_ascii,
                           reason_label=p.reason_label,
                           valid_to_label=p.valid_to_label(self.ctx.zone),
                           notify_title=title, notify_message=message)
