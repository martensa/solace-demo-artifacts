"""Bus -> SSE: topic classification, event conversion, open receipts, fan-out (10.2).

The bus receiver thread calls :meth:`Hub.handle` for every message of the three
``gpos-ui`` subscriptions; the hub converts it into one SSE event (``pos_event``,
``insight``, ``sam_run``, ``review``, ``tool_call``, ``proposal``, ``price_change``),
updates the open receipt of the till and the counters, keeps the last 30 monitor
events and fans the event out to every connected browser (in-process, one replica).
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

import anyio.to_thread

from ..common import approval_text, topics
from ..common.clock import from_ts
from ..common.fmt import dt_label, eur, parse_price
from ..common.jsonutil import compact
from ..common.money import from_bdecimal, from_money
from .counters import Counters
from .refdata import RefData
from .texts import RUN_LABEL_DENIED, RUN_LABEL_ERROR, RUN_LABEL_EXPIRED, RUN_LABEL_OK

log = logging.getLogger(__name__)

R1_EVENTS = ("PositionAdded", "ArticlePositionVoided", "LoyaltyMembershipAssigned",
             "PurchaseTransactionClosed", "PurchaseTransactionCancelled")
# proto3 JSON of google.protobuf.Any (4.2); the probes of 9.8 publish another @type
GEBIT_EVENT_TYPE = "type.googleapis.com/de.gebit.rp.purchase.purchase.v2.event."
STATUS_PREFIX = "PURCHASE_TRANSACTION_STATUS_"
FINAL_STATUSES = ("CLOSED", "CANCELLED", "RESET")
WORKFLOWS = {"1": "gpos-pos-event", "3": "gpos-basket-review", "4": "gpos-price-approval"}
# rules whose errors may be an approval timeout or denial (name kept: contract tests)
EXPIRY_RULES = ("r4", "p4")
# provisional run label of an R4/P4 error by the text class of approval_text
# (10.2; the final label follows the engine outcome on the monitor, 10.4)
PROVISIONAL_LABELS = {"timeout": RUN_LABEL_EXPIRED, "denied": RUN_LABEL_DENIED}
ERROR_KEYS = ("error", "message", "error_message", "errorMessage", "detail", "details",
              "reason")
ERROR_MAX = 500
RING_SIZE = 30
BAND_SIZE = 12
QUEUE_SIZE = 1000
CARDS_KEPT = 200
HEARTBEAT_S = 15.0
RETRY_MS = 2000
MONITOR_KINDS = ("pos_event", "insight", "sam_run", "review", "tool_call", "proposal",
                 "price_change")

Event = tuple[str, dict[str, Any]]


# --------------------------------------------------------------------- converters
def classify(topic: str) -> str | None:
    """SSE event type of a topic (7.1), ``None`` for topics the monitor ignores."""
    if topic.startswith(f"{topics.GEBIT_ROOT}/"):
        return "pos_event"
    if topic.startswith(f"{topics.WWS_PRICE_ROOT}/"):
        return "price_change"
    prefixes = {"insight/": "insight", "review/state/": "review", "proposal/": "proposal",
                "telemetry/tool/": "tool_call", "sam/done/": "sam_run",
                "sam/error/": "sam_run"}
    for prefix, kind in prefixes.items():
        if topic.startswith(f"{topics.GPOS_ROOT}/{prefix}"):
            return kind
    return None


def price_label(value: Any) -> str:
    """``"9,99"`` from a Decimal, number, ``"9.99"``/``"9,99"`` or a BDecimal dict;
    ``""`` when empty or unreadable."""
    if value is None or value == "":
        return ""
    try:
        if isinstance(value, Mapping):
            return eur(from_bdecimal(value))
        if isinstance(value, str):
            return eur(parse_price(value))
        return eur(Decimal(str(value)))
    except (ValueError, InvalidOperation):
        return ""


def _props(payload: Mapping[str, Any]) -> dict[str, str]:
    """GEBIT ``extensionProperties`` -> ``{key: stringValue}``."""
    out = {}
    for prop in payload.get("extensionProperties") or []:
        if isinstance(prop, Mapping) and prop.get("key"):
            out[str(prop["key"])] = str((prop.get("typedValue") or {}).get("stringValue", ""))
    return out


def _position_price(pricing: Mapping[str, Any], position_id: str) -> str:
    for position in pricing.get("articlePositions") or []:
        if position.get("positionId") == position_id:
            base = (position.get("calculatedPositionPrice") or {}).get("basePrice")
            return price_label(base) if base is not None else ""
    return ""


def is_gebit_event(payload: Mapping[str, Any]) -> bool:
    """A GEBIT purchase event (``@type`` of the event package, 4.2), like 11.1 step 1.

    The R1/P1 probes (9.8) publish ``gpos.probe.Probe`` on a GEBIT topic of the booth or
    probe till; they are no till event and must neither open a receipt nor count.
    """
    return str(payload.get("@type", "")).startswith(GEBIT_EVENT_TYPE)


def pos_event(topic: str, payload: Mapping[str, Any],
              booth: tuple[str, str]) -> dict[str, Any]:
    """``pos_event`` from a GEBIT event (topic levels: ``…/{Event}/{country}/{company}/
    {store}/{till}/{txId}``). ``to_sam`` is true for the five R1 kinds of the booth."""
    levels = topic.split("/")
    event, store, till = levels[5], levels[8], levels[9]
    pricing = payload.get("pricingInformation")
    position_id = str(payload.get("positionId", ""))
    props = _props(payload)
    data: dict[str, Any] = {
        "event": event,
        "tx_id": str(payload.get("purchaseTransactionId") or levels[10]),
        "store": store, "till": till,
        "offset": int((payload.get("metadata") or {}).get("offset", 0) or 0),
        "position_id": position_id,
        "article_number": str(payload.get("articleNumber", "")),
        "description": str(payload.get("description", "")),
        "item_count": int(payload.get("itemCount", 0) or 0),
        "price": _position_price(pricing, position_id) if pricing and position_id else "",
        "price_source": props.get("showcase.priceSource", ""),
        "regular_price": price_label(props.get("showcase.regularPrice", "")),
        "action_id": props.get("showcase.actionId", ""),
        "total": price_label(pricing.get("totalSum") or {}) if pricing is not None else "",
        "status": str(payload.get("purchaseTransactionStatus", "")).removeprefix(STATUS_PREFIX),
        "to_sam": event in R1_EVENTS and (store, till) == booth,
        "receipt_number": str(payload.get("receiptNumber", "")),
    }
    if event == "LoyaltyMembershipAssigned":
        data["card"] = str((payload.get("capturingInformation") or {}).get("inputValue", ""))
    return data


def price_change(topic: str, payload: Mapping[str, Any], tz: str) -> dict[str, Any]:
    """``price_change`` from a WWS ``PriceChangeApplied``/``Ended`` (proto3 JSON)."""
    levels = topic.split("/")
    valid_to = payload.get("validTo")
    return {
        "event": levels[4], "store": levels[7],
        "action_id": str(payload.get("actionId", "")),
        "article_number": str(payload.get("articleNumber") or levels[8]),
        "article_name": str(payload.get("articleName", "")),
        "old": eur(from_money(payload["regularPrice"])) if "regularPrice" in payload else "",
        "new": eur(from_money(payload["actionPrice"])) if "actionPrice" in payload else "",
        "pct_shown": int(payload.get("pctShown", 0) or 0),
        "valid_to_label": dt_label(from_ts(valid_to, tz)) if valid_to else "",
        "proposal_id": str(payload.get("proposalId", "")),
        "topic": topic,
    }


def _json_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def unwrap_sam(payload: Any) -> Any:
    """The SAM object of a ``successOutput``: directly or under ``result``/``output``
    (A-22, read tolerantly)."""
    if isinstance(payload, dict):
        for key in ("result", "output"):
            inner = _json_object(payload.get(key))
            if inner is not None:
                return inner
    return payload


def _texts(value: Any) -> Iterator[str]:
    """Every non-empty string inside an ``errorOutput`` payload, depth first."""
    if isinstance(value, str):
        if value.strip():
            yield value.strip()
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _texts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _texts(item)


def _marked(payload: Any) -> str:
    """The first text naming a timeout, else the first denial text with an approval
    context (``approval_text``), wherever it sits; ``""`` when none."""
    found = list(_texts(payload))
    return (next((t for t in found if approval_text.TIMEOUT.search(t)), "")
            or next((t for t in found if approval_text.is_denial(t)), ""))


def sam_error_text(payload: Any) -> str:
    """Readable error of an ``errorOutput``: a text naming a timeout wherever it sits,
    then a denial text with an approval context (the shape is unverified, A-22; the
    engine classifies the forwarded text itself, 11.5/11.8), else a string or a known
    key, possibly nested."""
    marked = _marked(payload)
    if marked:
        return marked[:ERROR_MAX]
    if isinstance(payload, str):
        return payload.strip()[:ERROR_MAX]
    if isinstance(payload, dict):
        for key in (*ERROR_KEYS, "result", "output"):
            value = payload.get(key)
            text = sam_error_text(value) if isinstance(value, (str, dict)) else ""
            if text:
                return text
        return compact(payload)[:ERROR_MAX] if payload else ""
    return compact(payload)[:ERROR_MAX] if payload is not None else ""


def provisional_label(payload: Any) -> str:
    """Run label of an ``r4``/``p4`` error from all its texts: a timeout text
    „Abgelaufen“, a denial with an approval context „Abgelehnt“, anything else
    „Fehler“ (``approval_text.classify_error``)."""
    kind = approval_text.classify_error(" | ".join(_texts(payload)))
    return PROVISIONAL_LABELS.get(kind, RUN_LABEL_ERROR)


def sam_run(topic: str, payload: Any) -> dict[str, Any]:
    """``sam_run`` from ``gpos/v1/sam/done|error/{rule}``. ``r4``/``p4`` errors carry a
    provisional label from the text (:func:`provisional_label`) and
    ``provisional: true``; the monitor replaces it by the engine outcome (10.4).
    Other errors are „Fehler“."""
    outcome, rule = topic.split("/")[3:5]
    data: dict[str, Any] = {"rule": rule, "workflow": WORKFLOWS.get(rule[1:], ""),
                            "ok": outcome == "done"}
    if data["ok"]:
        data.update(label=RUN_LABEL_OK, output=unwrap_sam(payload))
        return data
    data.update(label=RUN_LABEL_ERROR, error=sam_error_text(payload))
    if rule in EXPIRY_RULES:
        data.update(label=provisional_label(payload), provisional=True)
    return data


def proposal_event(topic: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The 7.2 proposal payload; the topic signal ``duplicate_request`` (state unchanged)
    is added as ``signal``."""
    state = topic.split("/")[3]
    return {**payload, "signal": state} if state in topics.PROPOSAL_SIGNALS else payload


def decode(payload: bytes) -> Any:
    """JSON of a message, or the raw text when it is not JSON."""
    text = payload.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except ValueError:
        return text


# --------------------------------------------------------------------- receipts
@dataclass
class Line:
    """One receipt line of the open receipt."""

    position_id: str
    article_number: str
    description: str
    item_count: int
    price: str
    price_source: str
    regular_price: str = ""
    voided: bool = False
    insight: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"position_id": self.position_id, "article_number": self.article_number,
                "description": self.description, "item_count": self.item_count,
                "price": self.price, "price_source": self.price_source,
                "regular_price": self.regular_price, "voided": self.voided,
                "insight": self.insight}


@dataclass
class Bon:
    """The open (or last) receipt of one till, built from ``pos_event`` and refreshed
    authoritatively from POS ``GET /admin/till/{till}``."""

    tx_id: str
    till: str
    store: str = ""
    status: str = "CREATED"
    receipt_number: str = ""
    total: str = ""
    card: str = ""
    persona: str = ""
    consent_profiling: bool | None = None
    last_offset: int = 0
    lines: dict[str, Line] = field(default_factory=dict)
    band: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=BAND_SIZE))

    def set_card(self, card: str, refdata: RefData) -> None:
        known = refdata.card(card)
        self.card = known.card if known else card
        self.persona = known.persona if known else ""
        self.consent_profiling = known.consent_profiling if known else None

    def apply(self, data: Mapping[str, Any], refdata: RefData) -> None:
        """Update from one ``pos_event``; status and total only from an event that is not
        older than the newest one seen (offsets per transaction, 4.2)."""
        offset = int(data.get("offset") or 0)
        if offset >= self.last_offset:
            self.last_offset = offset
            self.status = str(data.get("status") or self.status)
            self.total = str(data.get("total") or self.total)
        self.store = str(data.get("store") or self.store)
        self.receipt_number = str(data.get("receipt_number") or self.receipt_number)
        self.band.append({"event": data["event"], "offset": data.get("offset", 0),
                          "to_sam": bool(data.get("to_sam"))})
        event, position_id = data["event"], str(data.get("position_id", ""))
        if event == "PositionAdded" and position_id:
            self.lines[position_id] = Line(
                position_id, str(data.get("article_number", "")),
                str(data.get("description", "")), int(data.get("item_count") or 1),
                str(data.get("price", "")), str(data.get("price_source", "")),
                str(data.get("regular_price", "")))
        elif event == "ArticlePositionVoided" and position_id in self.lines:
            self.lines[position_id].voided = True
        elif event == "LoyaltyMembershipAssigned" and data.get("card"):
            self.set_card(str(data["card"]), refdata)

    def keep_live(self, old: Bon) -> None:
        """Keep what only the live events carry (scan-analysis chips, event band) when
        the same receipt is reloaded from POS admin."""
        self.band = old.band
        for position_id, line in self.lines.items():
            previous = old.lines.get(position_id)
            if previous is not None:
                line.insight = previous.insight

    def apply_insight(self, data: Mapping[str, Any]) -> None:
        line = self.lines.get(str(data.get("position_id", "")))
        if line is not None:
            line.insight = {"code": data.get("code", ""), "severity": data.get("severity", ""),
                            "text": data.get("text", "")}

    def to_dict(self) -> dict[str, Any]:
        return {"tx_id": self.tx_id, "till": self.till, "store": self.store,
                "status": self.status, "receipt_number": self.receipt_number,
                "total": self.total, "last_offset": self.last_offset, "card": self.card,
                "persona": self.persona,
                "consent_profiling": self.consent_profiling,
                "lines": [line.to_dict() for line in self.lines.values()],
                "events": list(self.band)}


def _first(obj: Mapping[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if obj.get(key) not in (None, ""):
            return obj[key]
    return default


def bon_from_admin(till: str, open_tx: Mapping[str, Any], refdata: RefData) -> Bon:
    """Receipt from the POS admin answer (``open_tx`` object, field names read
    tolerantly: ``name``/``description``, ``unit_price``/``price``, ...)."""
    bon = Bon(tx_id=str(_first(open_tx, "tx_id", "purchase_transaction_id")), till=till,
              store=str(open_tx.get("store_id", "")),
              status=str(open_tx.get("status", "OPEN")).removeprefix(STATUS_PREFIX),
              receipt_number=str(open_tx.get("receipt_number") or ""),
              total=price_label(open_tx.get("total")),
              last_offset=int(open_tx.get("offset") or 0))
    card = str(_first(open_tx, "card", "membership_card", "membership_id"))
    if card:
        bon.set_card(card, refdata)
    for raw in open_tx.get("lines") or []:
        line = Line(str(raw.get("position_id", "")), str(raw.get("article_number", "")),
                    str(_first(raw, "name", "description")),
                    int(_first(raw, "item_count", "quantity", default=1)),
                    price_label(_first(raw, "unit_price", "price")),
                    str(raw.get("price_source", "")), price_label(raw.get("regular_price")),
                    bool(raw.get("voided", False)))
        bon.lines[line.position_id] = line
    return bon


# --------------------------------------------------------------------- fan-out
class Subscriber:
    """One SSE connection: a bounded queue on the server loop, fed from any thread."""

    def __init__(self, maxsize: int = QUEUE_SIZE):
        self.loop = asyncio.get_running_loop()
        self.queue: asyncio.Queue[Event | None] = asyncio.Queue(maxsize)
        self.closed = False

    def offer(self, item: Event | None) -> None:
        """Hand ``item`` (``None`` = end of stream) to the loop; thread-safe."""
        try:
            self.loop.call_soon_threadsafe(self._put, item)
        except RuntimeError:  # loop already closed
            self.closed = True

    def _put(self, item: Event | None) -> None:
        try:
            self.queue.put_nowait(item)
        except asyncio.QueueFull:
            log.warning("SSE client too slow, closing its stream (it reconnects)")
            self.closed = True


class Hub:
    """State of the monitor and SSE fan-out (one process, one replica)."""

    def __init__(self, booth_location: str, tz: str, refdata: RefData, counters: Counters):
        _, _, store, till = topics.parse_location(booth_location)
        self.booth = (store, till)
        self.tz = tz
        self.refdata = refdata
        self.counters = counters
        self._lock = threading.Lock()
        self._subs: set[Subscriber] = set()
        self._ring: deque[dict[str, Any]] = deque(maxlen=RING_SIZE)
        self._bons: dict[str, Bon] = {}
        self._reviews: dict[str, dict[str, Any]] = {}
        self._proposals: dict[str, dict[str, Any]] = {}
        self._cards_by_tx: dict[str, str] = {}

    # conversion -------------------------------------------------------------
    def convert(self, topic: str, payload: bytes) -> Event | None:
        """SSE event of a bus message (``None``: not for the monitor or unreadable)."""
        kind = classify(topic)
        if kind is None:
            return None
        body = decode(payload)
        if kind == "sam_run":
            return kind, sam_run(topic, body)
        if not isinstance(body, dict):
            log.warning("ignoring non-JSON message on %s", topic)
            return None
        if kind == "pos_event":
            if not is_gebit_event(body):
                log.info("ignoring a non-GEBIT message on %s (probe)", topic)
                return None
            return kind, self._with_card(pos_event(topic, body, self.booth))
        if kind == "price_change":
            return kind, price_change(topic, body, self.tz)
        if kind == "proposal":
            return kind, proposal_event(topic, body)
        return kind, body

    def _with_card(self, data: dict[str, Any]) -> dict[str, Any]:
        """``LoyaltyMembershipAssigned``: card from the event or from the facade call,
        plus persona and consent of the fictional card (6.4)."""
        if data["event"] != "LoyaltyMembershipAssigned":
            return data
        with self._lock:
            card = data.get("card") or self._cards_by_tx.get(data["tx_id"], "")
        known = self.refdata.card(card) if card else None
        return {**data, "card": known.card if known else card,
                "persona": known.persona if known else "",
                "consent_profiling": known.consent_profiling if known else None}

    # state -------------------------------------------------------------------
    def _bon_for(self, till: str, tx_id: str) -> Bon:
        bon = self._bons.get(till)
        if bon is None or bon.tx_id != tx_id:
            bon = Bon(tx_id=tx_id, till=till)
            self._bons[till] = bon
        return bon

    def _update(self, kind: str, data: dict[str, Any]) -> None:
        till = str(data.get("till", ""))
        if kind == "pos_event":
            self._bon_for(till, data["tx_id"]).apply(data, self.refdata)
        elif kind == "insight":
            bon = self._bons.get(till)
            if bon is not None and bon.tx_id == data.get("tx_id"):
                bon.apply_insight(data)
        elif kind == "review":
            self._reviews[till] = data
        elif kind == "proposal" and not data.get("signal"):
            self._proposals[till] = data
        self._ring.append({"event": kind, "data": data})

    def handle(self, topic: str, payload: bytes, _props: dict[str, str] | None = None
               ) -> Event | None:
        """Bus handler: convert, update state and counters, fan out. Never raises."""
        try:
            event = self.convert(topic, payload)
        except (AttributeError, KeyError, IndexError, TypeError, ValueError, InvalidOperation):
            log.warning("cannot convert message on %s", topic, exc_info=True)
            return None
        if event is None:
            return None
        kind, data = event
        with self._lock:
            self._update(kind, data)
        self.counters.on_event(kind, data)
        self.broadcast(kind, data)
        return event

    def note_card(self, till: str, tx_id: str, card: str) -> None:
        """Remember the card the facade assigned (the GEBIT event carries it only in
        ``capturingInformation``, if at all)."""
        with self._lock:
            self._cards_by_tx[tx_id] = card
            while len(self._cards_by_tx) > CARDS_KEPT:
                del self._cards_by_tx[next(iter(self._cards_by_tx))]
            bon = self._bons.get(till)
            if bon is not None and bon.tx_id == tx_id:
                bon.set_card(card, self.refdata)

    def load_bon(self, till: str, admin: Mapping[str, Any]) -> None:
        """Replace the receipt of ``till`` with the POS admin answer (authoritative)."""
        open_tx = admin.get("open_tx")
        with self._lock:
            if isinstance(open_tx, Mapping) and _first(open_tx, "tx_id",
                                                       "purchase_transaction_id"):
                fresh, old = bon_from_admin(till, open_tx, self.refdata), self._bons.get(till)
                if old is not None and old.tx_id == fresh.tx_id:
                    fresh.keep_live(old)
                self._bons[till] = fresh
            elif till in self._bons and self._bons[till].status not in FINAL_STATUSES:
                del self._bons[till]

    def snapshot(self, till: str) -> dict[str, Any]:
        """Receipt, last review/proposal event of ``till`` and the last 30 events."""
        with self._lock:
            bon = self._bons.get(till)
            return {"bon": bon.to_dict() if bon else None,
                    "review": self._reviews.get(till),
                    "proposal_event": self._proposals.get(till),
                    "events": list(self._ring)}

    def clear(self) -> int:
        """Forget receipts, reviews, proposals and the event buffer; return how many
        buffered events were dropped."""
        with self._lock:
            dropped = len(self._ring)
            self._ring.clear()
            self._bons.clear()
            self._reviews.clear()
            self._proposals.clear()
            self._cards_by_tx.clear()
        return dropped

    # fan-out -----------------------------------------------------------------
    def subscribe(self) -> Subscriber:
        """New subscriber on the running loop (call from the request handler)."""
        sub = Subscriber()
        with self._lock:
            self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        with self._lock:
            self._subs.discard(sub)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)

    def broadcast(self, kind: str, data: dict[str, Any]) -> None:
        """Send one event to every subscriber (thread-safe)."""
        with self._lock:
            subs = list(self._subs)
        for sub in subs:
            sub.offer((kind, data))

    def close_all(self) -> None:
        """End every stream (shutdown)."""
        with self._lock:
            subs = list(self._subs)
        for sub in subs:
            sub.closed = True
            sub.offer(None)


# --------------------------------------------------------------------- SSE wire
def sse_message(kind: str, data: Any) -> str:
    """``event: <kind>`` + ``data: <compact JSON>`` + blank line."""
    return f"event: {kind}\ndata: {compact(data)}\n\n"


SSE_RETRY = f"retry: {RETRY_MS}\n\n"
SSE_HEARTBEAT = ": hb\n\n"


async def sse_stream(hub: Hub, sub: Subscriber, hello: Callable[[], dict[str, Any]],
                     heartbeat_s: float = HEARTBEAT_S) -> AsyncIterator[str]:
    """``retry``, ``hello`` (snapshot of ``/api/state``), then every event; a comment
    heartbeat when nothing happened for ``heartbeat_s``. Subscribe before calling, so
    nothing between snapshot and stream is lost."""
    try:
        yield SSE_RETRY
        yield sse_message("hello", await anyio.to_thread.run_sync(hello))
        while not sub.closed:
            try:
                item = await asyncio.wait_for(sub.queue.get(), heartbeat_s)
            except TimeoutError:
                yield SSE_HEARTBEAT
                continue
            if item is None:
                break
            yield sse_message(*item)
    finally:
        hub.unsubscribe(sub)
