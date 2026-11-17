"""Receipt number and the serialized receipt of closed and cancelled baskets (4.2, 5.3).

``PurchaseTransactionClosed.serializedReceiptContent`` carries a binary
``Any(Receipt)`` of the GEBIT Receipt API 2.13.0 (base64 in JSON) when the receipt
descriptor set is mounted, otherwise it stays empty (``pos.receipt.api_version`` =
``'none'``). The receipt is minimal, as in gebitsim: id, type, status, number,
location, currency and total.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from google.protobuf import any_pb2

from gposdemo.common.descriptors import Types

RECEIPT_TYPE = "de.gebit.rp.receipt.receipt.v2.datatype.Receipt"
RECEIPT_API = "receipt-api-2.13.0"
RECEIPT_VERSION = "2.13.0"
NO_RECEIPT_API = "none"
RECEIPT_FORMAT = "PROTOBUF"


def receipt_number(store_id: str, till_id: str, business_date: date, seq: int) -> str:
    """``<store><till><YYMMDD><seq 6 digits>``: ``("101", "01", 2027-02-16, 42)`` ->
    ``"10101270216000042"`` (business date, sequence ``pos.receipt_seq``)."""
    if seq < 1:
        raise ValueError(f"receipt sequence must be positive, got {seq}")
    return f"{store_id}{till_id}{business_date:%y%m%d}{seq:06d}"


@dataclass(frozen=True)
class SerializedReceipt:
    """Base64 receipt plus the API version stored in ``pos.receipt``."""

    api_version: str
    content_b64: str

    def event_fields(self) -> dict[str, Any]:
        """``serializedReceipt*`` fields of the closing event (none without a receipt)."""
        if not self.content_b64:
            return {}
        return {"serializedReceiptFormat": RECEIPT_FORMAT,
                "serializedReceiptContent": self.content_b64,
                "serializedReceiptVersion": RECEIPT_VERSION}


class ReceiptBuilder:
    """Builds receipts when the receipt descriptor set is part of the GEBIT pool."""

    def __init__(self, types: Types):
        try:
            types.cls(RECEIPT_TYPE)
        except KeyError:
            self._types: Types | None = None
        else:
            self._types = types

    @property
    def available(self) -> bool:
        """True when the Receipt API descriptor is mounted."""
        return self._types is not None

    def build(self, *, tx_id: str, receipt_number: str, location: str, total: Decimal,
              closed: bool) -> SerializedReceipt:
        """Closed (``closed``) or cancelled receipt as base64 ``Any``."""
        if self._types is None:
            return SerializedReceipt(NO_RECEIPT_API, "")
        receipt: Any = self._types.new(RECEIPT_TYPE)
        receipt.receipt_id = tx_id
        receipt.receipt_type = "SALE"
        (receipt.closed_receipt if closed else receipt.canceled_receipt).SetInParent()
        receipt.receipt_number = receipt_number
        receipt.location = location
        receipt.currency = "EUR"
        receipt.total.value = f"{total:.2f}"
        packed = any_pb2.Any()
        packed.Pack(receipt)
        return SerializedReceipt(RECEIPT_API,
                                 base64.b64encode(packed.SerializeToString()).decode("ascii"))
