"""SQL of the POS simulator on schema ``pos`` (UC1-BUILD-SPEC 5.3).

Every function takes a connection of ``Db.tx()`` (``dict_row``), so the caller decides
the transaction: commands lock the basket row (``for update``) and write lines,
payments, receipt, basket and outbox rows in one transaction. ``pos.basket`` timestamps
are technical time; the engine reads ``pos.till``, ``pos.basket`` and
``pos.basket_line`` (select grant), so their meaning is part of the contract:
``basket_line.unit_price`` = effective price at the scan, ``voided`` lines do not count.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, fields
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg

Conn = psycopg.Connection[dict[str, Any]]

OPEN_STATES = ("CREATED", "OPEN", "IN_PAYMENT")
TOOL_TILL_ORDER = ("booth", "test", "probe")


def canonical_uuid(value: str) -> str | None:
    """Canonical text of a UUID, or ``None`` when ``value`` is not one."""
    try:
        return str(uuid.UUID(value.strip()))
    except (ValueError, AttributeError):
        return None


@dataclass(frozen=True)
class Till:
    """One row of ``pos.till`` (``01`` booth 101, ``98`` probe 199, ``99`` test 199)."""

    till_id: str
    store_id: str
    location: str
    kind: str
    active: bool


@dataclass
class Basket:
    """One row of ``pos.basket``; commands change it and :func:`save_basket` writes it."""

    tx_id: str
    till_id: str
    store_id: str
    location: str
    status: str
    receipt_number: str | None = None
    membership_id: str | None = None
    membership_position_id: str | None = None
    employee_id: str | None = None
    cashdrawer_id: str | None = None
    total: Decimal = Decimal("0.00")
    paid: Decimal = Decimal("0.00")
    last_offset: int = 0
    opened_at: datetime | None = None
    closed_at: datetime | None = None


@dataclass(frozen=True)
class Line:
    """One row of ``pos.basket_line``."""

    position_id: str
    line_no: int
    article_number: str
    article_id: str
    name: str
    gtin: str | None
    category: str
    item_count: int
    unit_price: Decimal
    regular_price: Decimal
    price_source: str
    action_id: str | None
    vat_pct: Decimal
    voided: bool = False


_TILL_COLS = "till_id, store_id, location, kind, active"
_BASKET_COLS = ("tx_id::text as tx_id, till_id, store_id, location, status, receipt_number, "
                "membership_id, membership_position_id::text as membership_position_id, "
                "employee_id, cashdrawer_id, total, paid, last_offset, opened_at, closed_at")
_LINE_COLS = ("position_id::text as position_id, line_no, article_number, article_id, name, "
              "gtin, category, item_count, unit_price, regular_price, price_source, action_id, "
              "vat_pct, voided")


def _till(row: dict[str, Any] | None) -> Till | None:
    return Till(**row) if row else None


def _basket(row: dict[str, Any] | None) -> Basket | None:
    return Basket(**row) if row else None


# ------------------------------------------------------------------------- tills
def till_by_location(conn: Conn, location: str, *, lock: bool = False) -> Till | None:
    """Till of a GEBIT location; ``lock`` serialises commands of the same till."""
    sql = f"select {_TILL_COLS} from pos.till where location = %s"
    return _till(conn.execute(sql + (" for update" if lock else ""), (location,)).fetchone())


def till_by_id(conn: Conn, till_id: str) -> Till | None:
    """Till ``01``, ``98`` or ``99``."""
    return _till(conn.execute(f"select {_TILL_COLS} from pos.till where till_id = %s",
                              (till_id,)).fetchone())


def tool_till(conn: Conn, store_id: str) -> Till | None:
    """The till the agent tools report for a store: booth before test before probe."""
    row = conn.execute(
        f"select {_TILL_COLS} from pos.till where store_id = %s and active "
        "order by array_position(%s::text[], kind), till_id limit 1",
        (store_id, list(TOOL_TILL_ORDER))).fetchone()
    return _till(row)


# ------------------------------------------------------------------------- baskets
def basket(conn: Conn, tx_id: str, *, lock: bool = False) -> Basket | None:
    """The basket of ``tx_id`` (``None`` for unknown or malformed ids)."""
    key = canonical_uuid(tx_id)
    if key is None:
        return None
    sql = f"select {_BASKET_COLS} from pos.basket where tx_id = %s"
    return _basket(conn.execute(sql + (" for update" if lock else ""), (key,)).fetchone())


def open_basket(conn: Conn, till_id: str) -> Basket | None:
    """Newest basket of the till in ``CREATED``, ``OPEN`` or ``IN_PAYMENT``."""
    row = conn.execute(
        f"select {_BASKET_COLS} from pos.basket where till_id = %s and status = any(%s) "
        "order by created_at desc limit 1", (till_id, list(OPEN_STATES))).fetchone()
    return _basket(row)


def insert_basket(conn: Conn, b: Basket) -> None:
    """New basket (status ``CREATED``, offset 0)."""
    conn.execute(
        "insert into pos.basket (tx_id, till_id, store_id, location, status, employee_id, "
        "cashdrawer_id) values (%s, %s, %s, %s, %s, %s, %s)",
        (b.tx_id, b.till_id, b.store_id, b.location, b.status, b.employee_id or None,
         b.cashdrawer_id or None))


def save_basket(conn: Conn, b: Basket) -> None:
    """Write the mutable columns of ``b``."""
    conn.execute(
        "update pos.basket set status = %s, receipt_number = %s, membership_id = %s, "
        "membership_position_id = %s, total = %s, paid = %s, last_offset = %s, "
        "opened_at = %s, closed_at = %s where tx_id = %s",
        (b.status, b.receipt_number, b.membership_id, b.membership_position_id, b.total,
         b.paid, b.last_offset, b.opened_at, b.closed_at, b.tx_id))


def reset_open(conn: Conn, till_id: str | None = None) -> list[str]:
    """Open baskets (of one till, or of all) -> ``RESET``, without events; their ids."""
    sql = "update pos.basket set status = 'RESET' where status = any(%s)"
    params: list[Any] = [list(OPEN_STATES)]
    if till_id is not None:
        sql += " and till_id = %s"
        params.append(till_id)
    rows = conn.execute(sql + " returning tx_id::text as tx_id", params).fetchall()
    return [r["tx_id"] for r in rows]


def next_receipt_seq(conn: Conn) -> int:
    """Next value of ``pos.receipt_seq``."""
    return int(conn.execute("select nextval('pos.receipt_seq') as seq").fetchone()["seq"])


# ------------------------------------------------------------------------- lines
def lines(conn: Conn, tx_id: str) -> list[Line]:
    """Effectual (not voided) lines of a basket in scan order."""
    rows = conn.execute(f"select {_LINE_COLS} from pos.basket_line where tx_id = %s "
                        "and not voided order by line_no", (tx_id,)).fetchall()
    return [Line(**r) for r in rows]


def next_line_no(conn: Conn, tx_id: str) -> int:
    """``max(line_no) + 1`` (call under the basket lock)."""
    row = conn.execute("select coalesce(max(line_no), 0) + 1 as next from pos.basket_line "
                       "where tx_id = %s", (tx_id,)).fetchone()
    return int(row["next"])


def insert_line(conn: Conn, tx_id: str, line: Line) -> None:
    """Add a scanned line."""
    names = [f.name for f in fields(Line)]
    conn.execute(
        f"insert into pos.basket_line (tx_id, {', '.join(names)}) "
        f"values (%s, {', '.join(['%s'] * len(names))})",
        (tx_id, *(getattr(line, n) for n in names)))


def find_line(conn: Conn, tx_id: str, position_id: str) -> Line | None:
    """A line of the basket by position id (also voided ones)."""
    key = canonical_uuid(position_id)
    if key is None:
        return None
    row = conn.execute(f"select {_LINE_COLS} from pos.basket_line where tx_id = %s and "
                       "position_id = %s", (tx_id, key)).fetchone()
    return Line(**row) if row else None


def void_line(conn: Conn, tx_id: str, position_id: str) -> None:
    """Mark a line voided."""
    conn.execute("update pos.basket_line set voided = true where tx_id = %s and "
                 "position_id = %s", (tx_id, position_id))


# ------------------------------------------------------------------------- payment, receipt
def insert_payment(conn: Conn, tx_id: str, payment_id: str, kind: str, amount: Decimal) -> None:
    """Payment row: ``CASH`` (positive) or ``CHANGE`` (negative, as GEBIT signs it)."""
    conn.execute("insert into pos.payment (payment_id, tx_id, kind, amount) "
                 "values (%s, %s, %s, %s)", (payment_id, tx_id, kind, amount))


def payment_ids(conn: Conn, tx_id: str) -> list[str]:
    """Ids of the cash payments of a basket, oldest first."""
    rows = conn.execute("select payment_id::text as payment_id from pos.payment "
                        "where tx_id = %s and kind = 'CASH' order by created_at, payment_id",
                        (tx_id,)).fetchall()
    return [r["payment_id"] for r in rows]


def insert_receipt(conn: Conn, tx_id: str, receipt_number: str, api_version: str,
                   content_b64: str) -> None:
    """The serialized receipt of a closed or cancelled basket."""
    conn.execute("insert into pos.receipt (tx_id, receipt_number, api_version, receipt_b64) "
                 "values (%s, %s, %s, %s)", (tx_id, receipt_number, api_version, content_b64))


# ------------------------------------------------------------------------- reporting
def closed_today(conn: Conn, till_id: str, tz: str, day: date) -> tuple[int, Decimal]:
    """``(count, revenue)`` of the baskets the till closed on ``day`` (local date in ``tz``)."""
    row = conn.execute(
        "select count(*) as n, coalesce(sum(total), 0) as revenue from pos.basket "
        "where till_id = %s and status = 'CLOSED' and (closed_at at time zone %s)::date = %s",
        (till_id, tz, day)).fetchone()
    return int(row["n"]), Decimal(row["revenue"])


def last_closed(conn: Conn, till_id: str) -> str | None:
    """``tx_id`` of the till's most recently closed basket."""
    row = conn.execute("select tx_id::text as tx_id from pos.basket where till_id = %s and "
                       "status = 'CLOSED' order by closed_at desc limit 1", (till_id,)).fetchone()
    return row["tx_id"] if row else None
