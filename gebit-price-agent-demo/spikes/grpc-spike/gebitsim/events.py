"""Build GEBIT purchase events from the runtime pool and serialise them.

Wire format = proto3 canonical JSON of google.protobuf.Any (what GEBIT's
sample events are): {"@type": "type.googleapis.com/<full name>", ...}.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from google.protobuf import any_pb2, json_format

from .descriptors import EVENT_PKG, Types

TOPIC_ROOT = "gebit/rp/purchase/v2"


def bd(int_val: int, scale: int = 2) -> dict:
    """datatype.BDecimal as proto3 JSON (int64 -> string; zero omitted on output)."""
    return {"scale": scale, "intVal": str(int_val)}


def money(cents: int, currency: str = "EUR") -> dict:
    return {"currency": currency, "amount": bd(cents)}


def ts(now_ns: int) -> dict:
    """datatype.Timestamp: a GEBIT message, NOT google.protobuf.Timestamp."""
    return {"seconds": str(now_ns // 1_000_000_000), "nanos": now_ns % 1_000_000_000}


def ots(now_ns: int, offset_min: int = 60) -> dict:
    """datatype.OffsetTimestamp {seconds, nanos, offset(minutes)}."""
    return {**ts(now_ns), "offset": offset_min}


def split_tax(gross: int, rate_bp: int) -> tuple[int, int]:
    """gross cents, rate in basis points of percent (1900 = 19.00%) -> (net, tax), half-up."""
    net = (gross * 10000 * 2 + (10000 + rate_bp)) // (2 * (10000 + rate_bp))
    return net, gross - net


@dataclass
class Emitted:
    name: str
    topic: str
    payload: str  # proto3 JSON (Any form)
    props: dict = field(default_factory=dict)
    build_us: float = 0.0


class EventFactory:
    def __init__(self, types: Types):
        self.types = types
        self._topic_cat: dict[str, str] = {}

    def category(self, name: str) -> str:
        # Derived from the descriptor: .../event/basket_event.proto -> "basket"
        c = self._topic_cat.get(name)
        if c is None:
            d = self.types.pool.FindMessageTypeByName(f"{EVENT_PKG}.{name}")
            c = d.file.name.rsplit("/", 1)[1].removesuffix(".proto").removesuffix("_event")
            self._topic_cat[name] = c
        return c

    def build(self, name: str, body: dict, *, tx_id: str, location: str, offset: int,
              trace_id: str | None, now_ns: int | None = None) -> Emitted:
        t0 = time.perf_counter()
        now_ns = now_ns or time.time_ns()
        msg = self.types.event(name)
        doc = {"header": {"eventTimestamp": ts(now_ns)},
               "metadata": {"offset": str(offset), "creationTimestamp": ts(now_ns),
                            **({"traceId": trace_id} if trace_id else {})},
               "purchaseTransactionId": tx_id, **body}
        json_format.ParseDict(doc, msg)  # strict: typo in a field name -> ParseError
        any_msg = any_pb2.Any()
        any_msg.Pack(msg)  # type_url = type.googleapis.com/<full name>
        payload = json_format.MessageToJson(any_msg, descriptor_pool=self.types.pool)
        country, company, store, till = (location.split(".") + ["_"] * 5)[1:5]
        topic = f"{TOPIC_ROOT}/{self.category(name)}/{name}/{country}/{company}/{store}/{till}/{tx_id}"
        props = {"eventType": f"{EVENT_PKG}.{name}", "purchaseTransactionId": tx_id,
                 "offset": offset, "traceId": trace_id or "", "location": location,
                 "apiVersion": "purchase-2.50.0", "applicationMessageId": f"{tx_id}:{offset}"}
        return Emitted(name, topic, payload, props, (time.perf_counter() - t0) * 1e6)


class JsonlSink:
    """Stand-in for the Solace publisher (no broker writes in the spike)."""

    def __init__(self, path: str | None):
        self.fh = open(path, "a", encoding="ascii") if path else None
        self.count = 0

    def publish(self, ev: Emitted) -> None:
        self.count += 1
        if self.fh:
            self.fh.write(json.dumps({"topic": ev.topic, "props": ev.props,
                                      "payload": json.loads(ev.payload)}) + "\n")
            self.fh.flush()
