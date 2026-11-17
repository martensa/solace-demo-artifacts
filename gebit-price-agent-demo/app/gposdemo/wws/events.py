"""``PriceChangeApplied`` / ``PriceChangeEnded`` of gpos-wws (UC1-BUILD-SPEC 4.3, 5.1, 7).

Payload = proto3 JSON of ``google.protobuf.Any`` holding the event (``@type``
``type.googleapis.com/de.showcase.wws.v1.event.<Event>``), one line, real umlauts
(``jsonutil.proto_compact``). The event is built strictly against the Showcase pool, so a
wrong field name fails here and never reaches the bus.

* Topic ``showcase/wws/v1/price/{Event}/{country}/{company}/{store}/{articleNumber}``,
  delivery class ``business`` (persistent only with ``GPOS_DELIVERY=persistent``).
* Aggregate ``"<article_number>:<store_id>"``; ``metadata.offset`` from
  ``OutboxWriter.next_offset`` in the same transaction as the business change.
* ``header``/``metadata`` carry technical time (``creationTimestamp`` in whole
  seconds, as in the 7.2 examples); ``validFrom``, ``validTo`` and ``endedAt``
  business time with the offset of ``GPOS_TZ`` (7.2).
* User properties (7.3): ``eventType`` (full proto name), ``source`` ``gpos-wws``,
  ``apiVersion`` ``wws-v1``, ``traceId``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from google.protobuf import any_pb2

from gposdemo.common import topics
from gposdemo.common.clock import offset_ts_json, real_now, ts_json
from gposdemo.common.config import Settings
from gposdemo.common.descriptors import WWS_EVENT_PKG, Types
from gposdemo.common.jsonutil import parse_strict, proto_compact
from gposdemo.common.money import to_money
from gposdemo.common.outbox import OutboxWriter

from .analytics import PriceAction
from .store import Conn, aggregate_id

APPLIED = "PriceChangeApplied"
ENDED = "PriceChangeEnded"
SOURCE = "gpos-wws"
API_VERSION = "wws-v1"
DELIVERY_CLASS = "business"
KIND_ENUM = {"CENTRAL": "PRICE_ACTION_KIND_CENTRAL", "BOOTH": "PRICE_ACTION_KIND_BOOTH"}


@dataclass(frozen=True)
class Authorization:
    """``datatype.AuthorizationInformation``: e.g. ``gpos-engine``, ``role:marktleitung``."""

    identity_id: str
    details: str = ""

    def as_json(self) -> dict[str, str]:
        return {"identity_id": self.identity_id, "details": self.details}


@dataclass(frozen=True)
class WwsEvent:
    """One built event, ready for the outbox."""

    name: str  # PriceChangeApplied | PriceChangeEnded
    aggregate_id: str
    offset: int
    topic: str
    payload_text: str
    props: dict[str, str]

    @property
    def event_type(self) -> str:
        """Full proto name (``eventType`` user property and outbox ``event_type``)."""
        return f"{WWS_EVENT_PKG}.{self.name}"


class PriceEvents:
    """Builds the two price events and adds them to ``wws.event_outbox``."""

    def __init__(self, types: Types, s: Settings,
                 clock: Callable[[], datetime] = real_now):
        self._types = types
        self._country = s.country
        self._company = s.company
        self._zone = ZoneInfo(s.tz)
        self._clock = clock
        self._outbox = OutboxWriter("wws")

    # ------------------------------------------------------------------ build (pure)
    def build_applied(self, action: PriceAction, article_name: str, *, offset: int,
                      trace_id: str, originator: Authorization,
                      approver: Authorization | None) -> WwsEvent:
        """``PriceChangeApplied`` of ``action`` (a booth action or a restored central one)."""
        body: dict[str, Any] = {
            "action_id": action.action_id,
            "article_number": action.article_number,
            "article_name": article_name,
            "store_id": action.store_id,
            "kind": KIND_ENUM[action.kind],
            "regular_price": to_money(action.regular_price),
            "action_price": to_money(action.action_price),
            "pct_shown": action.pct_shown,
            "ref30": to_money(action.ref30),
            "valid_from": offset_ts_json(action.valid_from.astimezone(self._zone)),
            "valid_to": offset_ts_json(action.valid_to.astimezone(self._zone)),
            "proposal_id": action.proposal_id,
            "reason_code": action.reason_code,
            "originator": originator.as_json(),
        }
        if approver is not None:
            body["approver"] = approver.as_json()
        return self._build(APPLIED, action, offset, trace_id, body)

    def build_ended(self, action: PriceAction, *, offset: int, trace_id: str) -> WwsEvent:
        """``PriceChangeEnded`` of an ended ``action`` (reason and time from the row)."""
        if action.ended_at is None:
            raise ValueError(f"action {action.action_id} is not ended")
        body = {
            "action_id": action.action_id,
            "article_number": action.article_number,
            "store_id": action.store_id,
            "reason": action.end_reason,
            "ended_at": offset_ts_json(action.ended_at.astimezone(self._zone)),
        }
        return self._build(ENDED, action, offset, trace_id, body)

    def _build(self, name: str, action: PriceAction, offset: int, trace_id: str,
               body: dict[str, Any]) -> WwsEvent:
        now = self._clock()
        doc = {"header": {"event_timestamp": ts_json(now)},
               "metadata": {"offset": str(offset),
                            "creation_timestamp": ts_json(now.replace(microsecond=0)),
                            "trace_id": trace_id},
               **body}
        msg = parse_strict(doc, self._types.new(f"{WWS_EVENT_PKG}.{name}"), self._types.pool)
        wrapped = any_pb2.Any()
        wrapped.Pack(msg)
        topic = topics.wws_price(name, self._country, self._company, action.store_id,
                                 action.article_number)
        props = {"eventType": f"{WWS_EVENT_PKG}.{name}", "source": SOURCE,
                 "apiVersion": API_VERSION, "traceId": trace_id or action.action_id}
        return WwsEvent(name, aggregate_id(action.article_number, action.store_id), offset,
                        topic, proto_compact(wrapped, self._types.pool), props)

    # ------------------------------------------------------------- emit (transactional)
    def emit_applied(self, conn: Conn, action: PriceAction, article_name: str, *,
                     trace_id: str, originator: Authorization,
                     approver: Authorization | None) -> WwsEvent:
        """Build ``PriceChangeApplied`` with the next offset and add it to the outbox."""
        offset = self._outbox.next_offset(conn, aggregate_id(action.article_number,
                                                             action.store_id))
        event = self.build_applied(action, article_name, offset=offset, trace_id=trace_id,
                                   originator=originator, approver=approver)
        self._add(conn, event)
        return event

    def emit_ended(self, conn: Conn, action: PriceAction, *, trace_id: str) -> WwsEvent:
        """Build ``PriceChangeEnded`` with the next offset and add it to the outbox."""
        offset = self._outbox.next_offset(conn, aggregate_id(action.article_number,
                                                             action.store_id))
        event = self.build_ended(action, offset=offset, trace_id=trace_id)
        self._add(conn, event)
        return event

    def _add(self, conn: Conn, event: WwsEvent) -> None:
        self._outbox.add(conn, aggregate_id=event.aggregate_id, aggregate_offset=event.offset,
                         event_type=event.event_type, topic=event.topic,
                         payload_text=event.payload_text, delivery_class=DELIVERY_CLASS,
                         user_props=event.props)
