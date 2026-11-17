"""Read side of the POS simulator: agent tools and admin views (UC1-BUILD-SPEC 2.4, 8.4, 11.8).

``PosService`` is the service object of 2.4: pure methods returning dicts, wrapped by
the MCP tools (``tools.py``) and the admin routes (``admin.py``).

* ``get_transaction(tx_id, ref)``: one transaction of any store (probe till 98 too),
  effectual lines in scan order, at most 8, then ``"more": n``; the compact JSON stays
  within the 1200 B of an agent tool (names are cut at 32 characters, and lines move
  into ``more`` until it fits).
* ``get_till_status(ref)``: the till of ``GPOS_TOOL_STORE`` (booth before test before
  probe): open transaction, closed transactions and revenue of the local day.
* ``till_state(till)``: the open basket of a till for the BFF (``GET /admin/till/{till}``),
  field names as in the SSE ``pos_event``.
* ``admin_reset()``: every open basket -> ``RESET`` without GEBIT events (11.7 step 3).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from zoneinfo import ZoneInfo

from gposdemo.common.clock import real_now
from gposdemo.common.config import Settings
from gposdemo.common.db import Db
from gposdemo.common.fmt import eur
from gposdemo.common.jsonutil import compact
from gposdemo.common.mcputil import AGENT_MAX_TEXT_BYTES

from . import store
from .store import Basket, Line

MAX_LINES = 8
NAME_MAX = 32  # longest master-data name: 31 ("GEBIT Ente (Quietscheente gelb)")


def short_name(name: str) -> str:
    """At most :data:`NAME_MAX` characters, cut with ``…``."""
    return name if len(name) <= NAME_MAX else name[: NAME_MAX - 1] + "…"


def _agent_line(line: Line) -> dict[str, Any]:
    return {"article_number": line.article_number, "name": short_name(line.name),
            "qty": line.item_count, "price": eur(line.unit_price), "source": line.price_source}


def _size(view: dict[str, Any]) -> int:
    return len(compact(view).encode("utf-8"))


def transaction_view(b: Basket, lines: Sequence[Line]) -> dict[str, Any]:
    """Agent view of one transaction (8.4), at most 8 lines and 1200 B."""
    head = {"tx_id": b.tx_id, "till": b.till_id, "status": b.status,
            "receipt": b.receipt_number, "membership_id": b.membership_id,
            "total": eur(b.total)}
    rows = [_agent_line(line) for line in lines if not line.voided]
    shown = min(len(rows), MAX_LINES)
    while True:
        view = {**head, "lines": rows[:shown]}
        if shown < len(rows):
            view["more"] = len(rows) - shown
        if shown == 0 or _size(view) <= AGENT_MAX_TEXT_BYTES:
            return view
        shown -= 1


def open_tx_view(b: Basket, lines: Sequence[Line]) -> dict[str, Any]:
    """Open basket for the BFF: status, card, total, last offset and effectual lines."""
    return {"tx_id": b.tx_id, "till": b.till_id, "store_id": b.store_id, "status": b.status,
            "receipt_number": b.receipt_number, "membership_id": b.membership_id,
            "total": eur(b.total), "offset": b.last_offset,
            "lines": [{"position_id": ln.position_id, "line_no": ln.line_no,
                       "article_number": ln.article_number, "article_id": ln.article_id,
                       "description": ln.name, "gtin": ln.gtin or "",
                       "item_count": ln.item_count, "price": eur(ln.unit_price),
                       "regular_price": eur(ln.regular_price), "price_source": ln.price_source,
                       "action_id": ln.action_id or ""}
                      for ln in lines if not ln.voided]}


class PosService:
    """Pure read and admin methods of ``gpos-pos``."""

    def __init__(self, settings: Settings, db: Db):
        self._s = settings
        self._db = db

    def get_transaction(self, tx_id: str, ref: str = "") -> dict[str, Any]:
        """Agent tool ``get_transaction``; ``LookupError`` for an unknown ``tx_id``."""
        with self._db.tx() as conn:
            b = store.basket(conn, tx_id)
            if b is None:
                raise LookupError(f"Transaktion {tx_id} unbekannt")
            return transaction_view(b, store.lines(conn, b.tx_id))

    def get_till_status(self, ref: str = "") -> dict[str, Any]:
        """Agent tool ``get_till_status`` for the till of ``GPOS_TOOL_STORE``."""
        today = real_now().astimezone(ZoneInfo(self._s.tz)).date()
        with self._db.tx() as conn:
            till = store.tool_till(conn, self._s.tool_store)
            if till is None:
                raise LookupError(f"keine Kasse in Laden {self._s.tool_store}")
            open_b = store.open_basket(conn, till.till_id)
            count, revenue = store.closed_today(conn, till.till_id, self._s.tz, today)
            last = store.last_closed(conn, till.till_id)
        return {"till": till.till_id, "open_tx": open_b.tx_id if open_b else None,
                "tx_today": count, "last_closed_tx": last, "revenue_today": eur(revenue)}

    def till_state(self, till: str) -> dict[str, Any]:
        """Open basket of ``till`` (``"open_tx": null`` without); ``KeyError`` if unknown."""
        with self._db.tx() as conn:
            t = store.till_by_id(conn, till)
            if t is None:
                raise KeyError(till)
            b = store.open_basket(conn, t.till_id)
            view = open_tx_view(b, store.lines(conn, b.tx_id)) if b else None
        return {"till": t.till_id, "store": t.store_id, "open_tx": view}

    def admin_reset(self) -> dict[str, Any]:
        """Every open basket -> ``RESET`` (no GEBIT events, nothing reaches SAM)."""
        with self._db.tx() as conn:
            ids = store.reset_open(conn)
        return {"status": "ok", "reset": len(ids)}
