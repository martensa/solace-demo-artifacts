"""``assess_event``: idempotent intake of one raw GEBIT event from SAM R1 (UC1-BUILD-SPEC
11.1).

1. Parse ``raw``; no object or no GEBIT purchase event ``@type`` -> ``ignore``.
2. Canonical JSON (sorted keys) -> SHA-256; ``txId``/``offset``; store and till from
   ``pos.basket`` (not resolvable -> ``ignore``).
3. Insert into ``engine.event_inbox``; conflict -> ``duplicate`` (no insight, no action).
4. Age from ``header.eventTimestamp`` against technical time: ``Closed`` older than
   ``CLOSE_MAX_AGE_SECONDS``, any other kind older than ``STALE_SECONDS`` -> ``stale``.
5. Verdict per event kind; scans get the 6.6 insight, a card its profile insight.
6. Store the insight and publish ``gpos/v1/insight/scan/…`` straight to the bus (Direct).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import grpc
from psycopg.types.json import Jsonb

from ..common import topics
from ..common.fmt import eur
from ..common.jsonutil import canonical, compact, sha256_hex
from ..common.telemetry import shorten
from . import signals, store, texts
from .context import Context
from .models import AssessResult

log = logging.getLogger(__name__)

EVENT_PREFIX = "type.googleapis.com/de.gebit.rp.purchase.purchase.v2.event."
VERDICTS = {"PositionAdded": "scan", "ArticlePositionVoided": "void",
            "LoyaltyMembershipAssigned": "member", "PurchaseTransactionClosed": "close",
            "PurchaseTransactionCancelled": "cancel"}


@dataclass(frozen=True)
class ParsedEvent:
    event_type: str
    tx_id: str
    offset: int
    event_ts: datetime | None
    sha256: str
    body: dict[str, Any]

    @property
    def event_key(self) -> str:
        return f"{self.tx_id}:{self.offset}"


@dataclass(frozen=True)
class Line:
    """The basket line an event refers to (``pos.basket_line``)."""

    position_id: str = ""
    article_number: str = ""
    article_name: str = ""
    price: str = ""
    price_source: str = ""


@dataclass(frozen=True)
class Insight:
    code: str
    text: str
    severity: str = "info"
    line: Line = field(default_factory=Line)
    facts: dict[str, Any] | None = None


def _timestamp(obj: Any) -> datetime | None:
    if not isinstance(obj, dict) or "seconds" not in obj:
        return None
    try:
        seconds, nanos = int(obj["seconds"]), int(obj.get("nanos", 0) or 0)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(seconds, UTC) + timedelta(microseconds=nanos // 1000)


def parse_event(raw: str) -> ParsedEvent | str:
    """The event, or the ``event_type`` (possibly ``""``) of an event to ignore."""
    try:
        body = json.loads(raw)
    except (TypeError, ValueError):
        return ""
    if not isinstance(body, dict):
        return ""
    type_url = body.get("@type")
    if not isinstance(type_url, str) or not type_url.startswith(EVENT_PREFIX):
        return type_url.rsplit(".", 1)[-1] if isinstance(type_url, str) else ""
    event_type = type_url.removeprefix(EVENT_PREFIX)
    tx_id = body.get("purchaseTransactionId")
    try:
        offset = int(str((body.get("metadata") or {}).get("offset")))
    except (TypeError, ValueError):
        return event_type
    if not isinstance(tx_id, str) or not store.is_uuid(tx_id) or offset < 1:
        return event_type
    return ParsedEvent(event_type, tx_id, offset,
                       _timestamp((body.get("header") or {}).get("eventTimestamp")),
                       sha256_hex(canonical(body)), body)


class Ingest:
    """Implements ``assess_event``."""

    def __init__(self, ctx: Context):
        self.ctx = ctx

    def assess(self, raw: str, run_id: str) -> AssessResult:
        parsed = parse_event(raw)
        if isinstance(parsed, str):
            return AssessResult(verdict="ignore", event_key="", event_type=parsed,
                                insight_code="none")
        with self.ctx.db.tx() as conn:
            bask = store.basket(conn, parsed.tx_id)
            if bask is None:
                return self._result(parsed, "ignore", None)
            verdict = self._verdict(parsed)
            inserted = conn.execute(
                "insert into engine.event_inbox (tx_id, \"offset\", event_type, store_id, "
                "till_id, event_ts, received_at, sam_run_id, verdict, payload_sha256) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) on conflict do nothing "
                "returning tx_id", (parsed.tx_id, parsed.offset, parsed.event_type,
                                    bask["store_id"], bask["till_id"], parsed.event_ts,
                                    self.ctx.clock(), run_id or None, verdict,
                                    parsed.sha256)).fetchone()
        if inserted is None:
            return self._result(parsed, "duplicate", bask)
        if verdict == "cancel":
            self._supersede_review(parsed.tx_id, run_id)
        insight = self._insight(verdict, parsed, bask)
        if insight is not None:
            self._store_and_publish(insight, parsed, bask, run_id)
        return self._result(parsed, verdict, bask, insight)

    # ------------------------------------------------------------- verdict
    def _verdict(self, parsed: ParsedEvent) -> str:
        verdict = VERDICTS.get(parsed.event_type, "ignore")
        if verdict == "ignore" or parsed.event_ts is None:
            return verdict
        s = self.ctx.settings
        limit = s.close_max_age_seconds if verdict == "close" else s.stale_seconds
        age = (self.ctx.clock() - parsed.event_ts).total_seconds()
        return "stale" if age > limit else verdict

    def _result(self, parsed: ParsedEvent, verdict: str, bask: dict[str, Any] | None,
                insight: Insight | None = None) -> AssessResult:
        code, text = "none", ""
        if insight is not None:
            code, text = insight.code, insight.text
        elif verdict == "close":
            code, text = "close", texts.INSIGHT_CLOSE
        elif verdict == "cancel":
            text = texts.INSIGHT_CANCEL
        return AssessResult(
            verdict=verdict, event_key=parsed.event_key, event_type=parsed.event_type,
            tx_id=parsed.tx_id, store=bask["store_id"] if bask else "",
            till=bask["till_id"] if bask else "",
            article_number=insight.line.article_number if insight else "",
            insight_code=code, insight_text=shorten(text, texts.INSIGHT_MAX))

    # ------------------------------------------------------------- insights
    def _insight(self, verdict: str, parsed: ParsedEvent,
                 bask: dict[str, Any]) -> Insight | None:
        if verdict == "scan":
            return self._scan_insight(parsed, bask)
        if verdict == "void":
            return Insight("void", texts.INSIGHT_VOID, line=self._line(parsed, bask))
        if verdict == "member":
            return self._member_insight(bask)
        return None

    def _line(self, parsed: ParsedEvent, bask: dict[str, Any]) -> Line:
        """The line from ``pos`` (authoritative); the event's own fields as fallback."""
        position_id = str(parsed.body.get("positionId") or "")
        with self.ctx.db.tx() as conn:
            row = store.basket_line(conn, bask["tx_id"], position_id)
        if row is None:
            return Line(position_id, str(parsed.body.get("articleNumber") or ""),
                        str(parsed.body.get("description") or ""))
        return Line(position_id, row["article_number"], row["name"], eur(row["unit_price"]),
                    row["price_source"])

    def _scan_insight(self, parsed: ParsedEvent, bask: dict[str, Any]) -> Insight:
        line = self._line(parsed, bask)
        number, store_id = line.article_number, bask["store_id"]
        try:
            article = self.ctx.wws.article(number, store_id, parsed.event_key)
            sales = self.ctx.wws.sales(number, store_id, parsed.event_key)
            if article is None or sales is None:
                return Insight("none", texts.INSIGHT_UNAVAILABLE, line=line)
            season = (self.ctx.wws.season(number, store_id, parsed.event_key)
                      if article.season_code else None)
            behaviour = (self.ctx.loyalty.behaviour(bask["membership_id"], number,
                                                    parsed.event_key)
                         if bask["membership_id"] else None)
        except grpc.RpcError as err:
            log.warning("scan insight %s: %s", parsed.event_key, err)
            return Insight("none", texts.INSIGHT_UNAVAILABLE, line=line)
        result = signals.evaluate(article, sales, season, behaviour, self.ctx.policy,
                                  self.ctx.demo_date)
        return Insight(result.insight_code, result.insight_text, result.severity, line,
                       result.metrics.as_json())

    def _member_insight(self, bask: dict[str, Any]) -> Insight:
        membership_id = bask["membership_id"] or ""
        try:
            member = self.ctx.loyalty.profile(membership_id) if membership_id else None
        except grpc.RpcError as err:
            log.warning("member insight %s: %s", membership_id, err)
            member = None
        if member is None:
            return Insight("member", texts.INSIGHT_UNAVAILABLE)
        return Insight("member", texts.member_insight(member.persona, member.consent_profiling),
                       facts={"membership_id": member.membership_id,
                              "persona": member.persona,
                              "consent_profiling": member.consent_profiling})

    def _store_and_publish(self, insight: Insight, parsed: ParsedEvent,
                           bask: dict[str, Any], run_id: str) -> None:
        with self.ctx.db.tx() as conn:
            conn.execute(
                "insert into engine.insight (tx_id, store_id, till_id, position_id, "
                "article_number, code, text, facts, sam_run_id, created_at) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (parsed.tx_id, bask["store_id"], bask["till_id"],
                 insight.line.position_id or None, insight.line.article_number or None,
                 insight.code, insight.text,
                 Jsonb(insight.facts or {}), run_id or None, self.ctx.clock()))
        payload = {
            "schema_version": "1", "type": "insight", "ts": self.ctx.emitter.ts(),
            "tx_id": parsed.tx_id, "store": bask["store_id"], "till": bask["till_id"],
            "event_key": parsed.event_key, "position_id": insight.line.position_id,
            "article_number": insight.line.article_number,
            "article_name": insight.line.article_name, "code": insight.code,
            "severity": insight.severity, "text": insight.text, "price": insight.line.price,
            "price_source": insight.line.price_source, "run_id": run_id}
        try:
            self.ctx.bus.publish(
                topics.insight(bask["store_id"], bask["till_id"], parsed.tx_id),
                compact(payload),
                props={"eventType": "insight", "source": "gpos-engine",
                       "apiVersion": "gpos-v1", "traceId": parsed.event_key})
        except Exception:  # noqa: BLE001 - the insight is stored; the chip may be missed
            log.warning("insight publish %s failed", parsed.event_key, exc_info=True)

    def _supersede_review(self, tx_id: str, run_id: str) -> None:
        with self.ctx.db.tx() as conn:
            review = store.review_of_tx(conn, tx_id, lock=True)
            if review is None or not review.is_open:
                return
            review = store.set_review(conn, review.review_id, status="superseded",
                                      decided_at=self.ctx.clock(),
                                      error="Bon abgebrochen")
            self.ctx.emitter.review_state(conn, review, run_id)
