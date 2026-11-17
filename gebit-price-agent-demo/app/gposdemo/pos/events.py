"""GEBIT purchase events built from the runtime descriptor pool (UC1-BUILD-SPEC 4.2, 7.1, 7.3).

Adapted from ``spikes/grpc-spike/gebitsim/events.py``:

* Payload = proto3 JSON of ``google.protobuf.Any`` (``@type:
  type.googleapis.com/de.gebit.rp.purchase.purchase.v2.event.<Event>``), one line via
  ``jsonutil.proto_compact`` (int64 as string, enum names, real umlauts).
* ``header.eventTimestamp`` and ``metadata.creationTimestamp`` are technical time,
  ``metadata.offset`` counts per transaction from 1, ``metadata.traceId`` is the
  request trace id (left out when the command had none, e.g.
  ``FiscalTransactionAssigned``).
* The body is parsed strictly (``ParseDict``): a wrong field name fails at once.
* Topic ``gebit/rp/purchase/v2/{category}/{Event}/{country}/{company}/{store}/{till}/{txId}``,
  ``category`` = file stem of the event proto without ``_event``.
* User properties ``eventType``, ``purchaseTransactionId``, ``offset``, ``traceId``,
  ``location``, ``apiVersion``, ``source``; the outbox sets the application message
  id ``{txId}:{offset}``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from google.protobuf import any_pb2, descriptor_pool, json_format

from gposdemo.common import topics
from gposdemo.common.clock import real_now, ts_json
from gposdemo.common.descriptors import EVENT_PKG, Types
from gposdemo.common.jsonutil import proto_compact

API_VERSION = "purchase-2.50.0"
SOURCE = "gpos-pos"
STATUS_PREFIX = "PURCHASE_TRANSACTION_STATUS_"


def status_enum(status: str) -> str:
    """``"OPEN"`` -> ``"PURCHASE_TRANSACTION_STATUS_OPEN"``"""
    return STATUS_PREFIX + status


def string_properties(values: Mapping[str, str]) -> list[dict[str, Any]]:
    """GEBIT ``Property`` list with ``typedValue.stringValue`` (empty strings stay)."""
    return [{"key": key, "typedValue": {"stringValue": value}} for key, value in values.items()]


@dataclass(frozen=True)
class GebitEvent:
    """One built event, ready for the outbox."""

    name: str
    event_type: str
    topic: str
    payload: str
    props: dict[str, str]
    offset: int


class EventFactory:
    """Builds GEBIT purchase events of the pool (purchase-api 2.50.0)."""

    def __init__(self, pool: descriptor_pool.DescriptorPool):
        self.pool = pool
        self.types = Types(pool)
        self._categories: dict[str, str] = {}

    def category(self, name: str) -> str:
        """Topic category of an event: ``.../event/basket_event.proto`` -> ``basket``."""
        found = self._categories.get(name)
        if found is None:
            desc = self.pool.FindMessageTypeByName(f"{EVENT_PKG}.{name}")
            found = desc.file.name.rsplit("/", 1)[-1].removesuffix(".proto")
            found = found.removesuffix("_event")
            self._categories[name] = found
        return found

    def build(self, name: str, body: Mapping[str, Any], *, tx_id: str, location: str,
              offset: int, trace_id: str, now: datetime | None = None) -> GebitEvent:
        """Event ``name`` with header, metadata and ``purchaseTransactionId`` plus ``body``."""
        stamp = ts_json(now or real_now())
        metadata: dict[str, Any] = {"offset": str(offset), "creationTimestamp": stamp}
        if trace_id:
            metadata["traceId"] = trace_id
        doc = {"header": {"eventTimestamp": stamp}, "metadata": metadata,
               "purchaseTransactionId": tx_id, **body}
        msg = self.types.event(name)
        json_format.ParseDict(doc, msg, ignore_unknown_fields=False, descriptor_pool=self.pool)
        packed = any_pb2.Any()
        packed.Pack(msg)
        country, company, store, till = topics.parse_location(location)
        event_type = f"{EVENT_PKG}.{name}"
        return GebitEvent(
            name=name, event_type=event_type,
            topic=topics.gebit_event(self.category(name), name, country, company, store, till,
                                     tx_id),
            payload=proto_compact(packed, self.pool),
            props={"eventType": event_type, "purchaseTransactionId": tx_id,
                   "offset": str(offset), "traceId": trace_id, "location": location,
                   "apiVersion": API_VERSION, "source": SOURCE},
            offset=offset)
