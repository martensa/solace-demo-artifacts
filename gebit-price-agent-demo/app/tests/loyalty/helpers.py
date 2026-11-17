"""Helpers of the gpos-loyalty tests: business times, POS purchase reports, gRPC errors."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import grpc
import pytest

from gposdemo.common.clock import demo_at, offset_ts_json
from gposdemo.common.config import Settings
from gposdemo.common.money import to_money

D = date(2027, 2, 16)
ARTICLES = {  # number -> (category, price) of the articles the tests report
    "100012": ("kaffee_tee", Decimal("14.49")),
    "100013": ("kaffee_tee", Decimal("6.99")),
    "100017": ("molkerei_fruehstueck", Decimal("2.49")),
}


def local(s: Settings, day: date, hour: int = 0, minute: int = 0, second: int = 0
          ) -> datetime:
    """Business date ``day`` at local time in ``GPOS_TZ``."""
    return demo_at(s, day, hour, minute) + timedelta(seconds=second)


def summary(tx_id: str, member: str, closed_at: datetime, articles: list[str], *,
            kind: str = "SALE", referenced: str = "") -> dict[str, Any]:
    """proto3 JSON of a ``PurchaseSummary`` as the POS reports it (4.4)."""
    lines = [{"position_id": f"pos-{i}", "article_id": f"ID{a}", "article_number": a,
              "category": ARTICLES[a][0], "item_count": 1,
              "effective_value": to_money(ARTICLES[a][1]), "effectual": True}
             for i, a in enumerate(articles, 1)]
    body: dict[str, Any] = {
        "purchase_transaction_id": tx_id, "receipt_number": "R-0001",
        "location": "Root.DE.999.101.01", "transaction_type": f"TRANSACTION_TYPE_{kind}",
        "closed_at": offset_ts_json(closed_at), "lines": lines,
        "total": to_money(sum((ARTICLES[a][1] for a in articles), Decimal("0.00")))}
    if member:
        body["membership_id"] = member
    if referenced:
        body["referenced_purchase_transaction_id"] = referenced
    return body


def rpc_error(fn: Callable[[], Any]) -> grpc.RpcError:
    """The ``RpcError`` that ``fn`` raises (fails the test when it does not raise)."""
    with pytest.raises(grpc.RpcError) as info:
        fn()
    return info.value
