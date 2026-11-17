"""SQL access of gpos-wws to schema ``wws`` (UC1-BUILD-SPEC 5.4).

Every function takes a connection from ``Db.tx()`` (``dict_row``) and runs inside the
caller's transaction. The service never writes ``wws.stock`` or ``wws.sales_daily``:
booth sales leave the key figures on their seed state all day (5.4).

Row locks: price actions of one aggregate (``"<article_number>:<store_id>"``) are
changed only under :func:`lock_aggregate`, the advisory lock that
``OutboxWriter.next_offset`` takes for the same aggregate.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from .analytics import ArticleRecord, Delivery, HistoryEntry, PriceAction, Season

Conn = psycopg.Connection[Any]

ARTICLE_KEYS = ("article_number", "gtin", "article_id")
SCHEMA = "wws"

_ARTICLE_SELECT = """
select a.article_number, a.article_id, a.gtin, a.name, a.category, a.category_label,
       a.pack_label, a.net_quantity, a.base_unit, a.vat_pct, a.cost_net, a.price_bound,
       coalesce(a.season_code, '') as season_code, a.listed_since,
       p.store_id, p.regular_price, coalesce(s.on_hand, 0) as stock_on_hand
  from wws.article a
  join wws.article_price p on p.article_number = a.article_number and p.store_id = %(store)s
  left join wws.stock s on s.article_number = a.article_number and s.store_id = %(store)s
"""
_ACTION_COLUMNS = (
    "action_id, article_number, store_id, kind, regular_price, action_price, pct_shown, "
    "ref30, valid_from, valid_to, coalesce(proposal_id, '') as proposal_id, reason_code, "
    "originator, coalesce(approver, '') as approver, ended_at, "
    "coalesce(end_reason, '') as end_reason")


def aggregate_id(article_number: str, store_id: str) -> str:
    """Outbox aggregate of a price action: ``"<article_number>:<store_id>"`` (5.1)."""
    return f"{article_number}:{store_id}"


def lock_aggregate(conn: Conn, aggregate: str) -> None:
    """``pg_advisory_xact_lock`` on ``wws:<aggregate>`` until the transaction ends."""
    conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"{SCHEMA}:{aggregate}",))


def lock_store(conn: Conn, store_id: str, *, exclusive: bool) -> None:
    """Store-wide advisory lock ``wws:store:<store_id>`` until the transaction ends.

    ``RequestPriceChange`` takes it shared (requests of one store still run side by
    side), ``ResetDemoState`` exclusive: a reset waits for requests in flight and sees
    the actions they commit, and no request inserts behind its back. Always taken
    before any aggregate lock, so the two lock kinds never form a cycle.
    """
    function = "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
    conn.execute(f"select {function}(hashtext(%s))", (f"{SCHEMA}:store:{store_id}",))


# --------------------------------------------------------------------------- articles
def _article(row: Mapping[str, Any]) -> ArticleRecord:
    return ArticleRecord(**row)


def articles(conn: Conn, store_id: str, category: str = "") -> list[ArticleRecord]:
    """All articles priced in ``store_id`` in file order, optionally of one category."""
    query = _ARTICLE_SELECT + (" where a.category = %(category)s" if category else "")
    rows = conn.execute(query + " order by a.sort_order",
                        {"store": store_id, "category": category}).fetchall()
    return [_article(r) for r in rows]


def article(conn: Conn, store_id: str, key: str, value: str) -> ArticleRecord | None:
    """One article by ``article_number``, ``gtin`` or ``article_id`` in ``store_id``."""
    if key not in ARTICLE_KEYS:
        raise ValueError(f"unknown article key {key!r}")
    query = sql.SQL(_ARTICLE_SELECT + " where {} = %(value)s").format(
        sql.Identifier("a", key))
    row = conn.execute(query, {"store": store_id, "value": value}).fetchone()
    return _article(row) if row else None


def season(conn: Conn, code: str) -> Season | None:
    """The season ``code`` (``None`` for an unknown or empty code)."""
    row = conn.execute(
        'select season_code as code, label, start_date as "start", end_date as "end" '
        "from wws.season where season_code = %s", (code,)).fetchone()
    return Season(**row) if row else None


def price_history(conn: Conn, store_id: str,
                  article_number: str = "") -> dict[str, list[HistoryEntry]]:
    """History rows of the store (or one article), per article, oldest first."""
    query = ("select article_number, price, valid_from, valid_to, kind "
             "from wws.price_history where store_id = %(store)s"
             + (" and article_number = %(article)s" if article_number else "")
             + " order by article_number, valid_from")
    out: dict[str, list[HistoryEntry]] = {}
    for row in conn.execute(query, {"store": store_id, "article": article_number}):
        number = row.pop("article_number")
        out.setdefault(number, []).append(HistoryEntry(**row))
    return out


# ------------------------------------------------------------------------------ sales
def daily_sales(conn: Conn, article_number: str, store_id: str, first: date,
                last: date) -> list[tuple[date, int]]:
    """``(day, units)`` of ``wws.sales_daily`` in ``[first, last]``."""
    rows = conn.execute(
        "select day, units from wws.sales_daily where article_number = %s "
        "and store_id = %s and day between %s and %s order by day",
        (article_number, store_id, first, last)).fetchall()
    return [(r["day"], r["units"]) for r in rows]


def plan_week(conn: Conn, article_number: str, store_id: str) -> Decimal:
    """Planned units per week (0 without a plan row)."""
    row = conn.execute(
        "select plan_week from wws.sales_plan where article_number = %s and store_id = %s",
        (article_number, store_id)).fetchone()
    return row["plan_week"] if row else Decimal(0)


def next_delivery(conn: Conn, article_number: str, store_id: str,
                  from_day: date) -> Delivery | None:
    """Earliest inbound delivery expected on or after ``from_day``."""
    row = conn.execute(
        "select expected_on, quantity from wws.inbound_delivery where article_number = %s "
        "and store_id = %s and expected_on >= %s order by expected_on limit 1",
        (article_number, store_id, from_day)).fetchone()
    return Delivery(**row) if row else None


# ----------------------------------------------------------------------------- actions
def _action(row: Mapping[str, Any]) -> PriceAction:
    return PriceAction(**row)


def _actions(conn: Conn, where: str, params: Mapping[str, Any]) -> list[PriceAction]:
    rows = conn.execute(f"select {_ACTION_COLUMNS} from wws.price_action where {where} "
                        "order by article_number, valid_from", params).fetchall()
    return [_action(r) for r in rows]


def open_actions(conn: Conn, store_id: str, article_number: str = "") -> list[PriceAction]:
    """Actions of the store (or one article) that are not ended."""
    where = "store_id = %(store)s and ended_at is null"
    if article_number:
        where += " and article_number = %(article)s"
    return _actions(conn, where, {"store": store_id, "article": article_number})


def action_by_id(conn: Conn, action_id: str) -> PriceAction | None:
    """The action ``action_id`` (open or ended)."""
    found = _actions(conn, "action_id = %(id)s", {"id": action_id})
    return found[0] if found else None


def action_by_proposal(conn: Conn, proposal_id: str) -> PriceAction | None:
    """The booth action created for ``proposal_id`` (idempotency key, 4.3)."""
    found = _actions(conn, "proposal_id = %(proposal)s", {"proposal": proposal_id})
    return found[0] if found else None


def due_actions(conn: Conn, now: datetime) -> list[PriceAction]:
    """Open actions of all stores with ``valid_to < now`` (to be marked expired, 5.4)."""
    return _actions(conn, "ended_at is null and valid_to < %(now)s", {"now": now})


def restorable_central(conn: Conn, store_id: str, now: datetime) -> list[PriceAction]:
    """Ended central actions of the store that are still valid after ``now``."""
    return _actions(conn, "store_id = %(store)s and kind = 'CENTRAL' and ended_at is not "
                          "null and valid_to > %(now)s", {"store": store_id, "now": now})


def next_action_seq(conn: Conn) -> int:
    """``nextval('wws.action_seq')`` for ``PA-YYMMDD-NNNN``."""
    return int(conn.execute("select nextval('wws.action_seq') as seq").fetchone()["seq"])


def insert_action(conn: Conn, action: PriceAction) -> None:
    """Insert a new open action."""
    conn.execute(
        "insert into wws.price_action (action_id, article_number, store_id, kind, "
        "regular_price, action_price, pct_shown, ref30, valid_from, valid_to, proposal_id, "
        "reason_code, originator, approver) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
        "%s, %s, %s, %s)",
        (action.action_id, action.article_number, action.store_id, action.kind,
         action.regular_price, action.action_price, action.pct_shown, action.ref30,
         action.valid_from, action.valid_to, action.proposal_id or None, action.reason_code,
         action.originator, action.approver or None))


def end_action(conn: Conn, action_id: str, ended_at: datetime, reason: str) -> PriceAction | None:
    """End the action if it is still open; the ended row, or ``None`` if it was not open."""
    row = conn.execute(
        f"update wws.price_action set ended_at = %s, end_reason = %s "
        f"where action_id = %s and ended_at is null returning {_ACTION_COLUMNS}",
        (ended_at, reason, action_id)).fetchone()
    return _action(row) if row else None


def reopen_action(conn: Conn, action_id: str) -> PriceAction | None:
    """Reopen an ended action unless another action of its article and store is open."""
    row = conn.execute(
        f"update wws.price_action pa set ended_at = null, end_reason = null "
        f"where pa.action_id = %s and pa.ended_at is not null and not exists ("
        f"select 1 from wws.price_action o where o.article_number = pa.article_number "
        f"and o.store_id = pa.store_id and o.ended_at is null) returning {_ACTION_COLUMNS}",
        (action_id,)).fetchone()
    return _action(row) if row else None


def audit(conn: Conn, actor: str, action: str, ref: str, payload: Mapping[str, Any]) -> None:
    """One row of ``wws.audit``."""
    conn.execute("insert into wws.audit (actor, action, ref, payload) values (%s, %s, %s, %s)",
                 (actor, action, ref or None, Jsonb(dict(payload))))
