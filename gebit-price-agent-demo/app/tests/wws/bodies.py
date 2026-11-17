"""Request bodies (proto3 JSON) shared by the gpos-wws gRPC tests."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from gposdemo.common.clock import offset_ts_json

TZ = ZoneInfo("Europe/Berlin")
D0 = datetime(2027, 2, 16, tzinfo=TZ)  # business date 00:00 = start of a booth action
VALID_TO = datetime(2027, 2, 23, 20, tzinfo=TZ)  # "Di 23.02. 20:00" (6.7 step 5)


def money(value: str) -> dict[str, Any]:
    """``Money`` in EUR from a decimal string."""
    cents = int(Decimal(value) * 100)
    return {"currency": "EUR", "amount": {"scale": 2, "intVal": str(cents)}}


def change(proposal_id: str, *, article: str = "100001", store: str = "199",
           regular: str = "9.99", new: str = "7.99", pct: int = 20, ref30: str = "9.99",
           valid_from: datetime | None = D0, valid_to: datetime = VALID_TO,
           reason: str = "REASON_CODE_SLOW_SELLER") -> dict[str, Any]:
    """A RequestPriceChange as the gate sends it (11.4 step 9); default: S1 Ente."""
    body: dict[str, Any] = {
        "header": {"traceId": proposal_id, "originator": {"identityId": "gpos-engine"},
                   "approver": {"identityId": "role:marktleitung"}},
        "articleNumber": article, "storeId": store, "expectedRegularPrice": money(regular),
        "newPrice": money(new), "pctShown": pct, "ref30": money(ref30),
        "validTo": offset_ts_json(valid_to), "proposalId": proposal_id, "reasonCode": reason}
    if valid_from is not None:
        body["validFrom"] = offset_ts_json(valid_from)
    return body
