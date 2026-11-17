"""Schema ``pos`` and the read side of the POS on the seeded scratch DB (marker db).

Tills come from the seed (5.7: ``01`` booth 101, ``98`` probe 199, ``99`` test 199);
baskets are written through ``store`` exactly as the simulator writes them.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from datetime import timedelta
from decimal import Decimal

import pytest

from gposdemo.common.clock import real_now
from gposdemo.common.config import Settings
from gposdemo.common.db import Db
from gposdemo.pos import store
from gposdemo.pos.service import PosService
from gposdemo.pos.store import Basket, Line, Till

pytestmark = pytest.mark.db


@pytest.fixture
def db(pos_db: Db) -> Iterator[Db]:
    """The pos pool on an empty basket table (the seeded tills stay)."""
    pos_db.fetch("truncate pos.basket cascade")
    yield pos_db
    pos_db.fetch("truncate pos.basket cascade")


def put(db: Db, till_id: str, status: str, total: str = "0.00", *, closed_ago: timedelta |
        None = None, lines: tuple[Line, ...] = ()) -> Basket:
    """A basket of ``till_id`` in ``status`` with ``lines``."""
    with db.tx() as conn:
        till = store.till_by_id(conn, till_id)
        assert till is not None
        b = Basket(tx_id=str(uuid.uuid4()), till_id=till.till_id, store_id=till.store_id,
                   location=till.location, status="CREATED")
        store.insert_basket(conn, b)
        for line in lines:
            store.insert_line(conn, b.tx_id, line)
        b.status, b.total = status, Decimal(total)
        b.receipt_number = f"{till.store_id}{till.till_id}270216{store.next_receipt_seq(conn):06d}"
        if closed_ago is not None:
            b.closed_at = real_now() - closed_ago
        store.save_basket(conn, b)
    return b


def line(no: int, number: str, name: str, price: str, *, voided: bool = False) -> Line:
    return Line(position_id=str(uuid.uuid4()), line_no=no, article_number=number,
                article_id=f"ID{number}", name=name, gtin=None, category="kaffee_tee",
                item_count=1, unit_price=Decimal(price), regular_price=Decimal(price),
                price_source="REGULAR", action_id=None, vat_pct=Decimal(7), voided=voided)


@pytest.fixture
def service(make_settings: Callable[..., Settings], db: Db) -> Callable[[str], PosService]:
    return lambda tool_store: PosService(make_settings("pos", GPOS_TOOL_STORE=tool_store), db)


def test_seeded_tills(db: Db) -> None:
    with db.tx() as conn:
        assert store.till_by_location(conn, "Root.DE.999.199.99") == Till(
            "99", "199", "Root.DE.999.199.99", "test", True)
        assert store.till_by_id(conn, "98") == Till("98", "199", "Root.DE.999.199.98", "probe",
                                                    True)
        assert store.till_by_location(conn, "Root.DE.999.101.02") is None
        tool_101, tool_199 = store.tool_till(conn, "101"), store.tool_till(conn, "199")
    assert (tool_101.till_id if tool_101 else None) == "01"
    assert (tool_199.till_id if tool_199 else None) == "99"  # test before probe


def test_get_transaction_searches_every_store(db: Db,
                                             service: Callable[[str], PosService]) -> None:
    probe = put(db, "98", "CLOSED", "16.98", closed_ago=timedelta(0), lines=(
        line(1, "100012", "Espresso Bohnen kräftig", "14.49"),
        line(2, "100004", "Bio-Bananen", "1.99", voided=True),
        line(3, "100017", "Butter-Croissants", "2.49")))
    view = service("101").get_transaction(probe.tx_id, "GR-270216-0001")
    assert (view["till"], view["status"], view["total"]) == ("98", "CLOSED", "16,98")
    assert [(ln["article_number"], ln["price"]) for ln in view["lines"]] == [
        ("100012", "14,49"), ("100017", "2,49")]
    with pytest.raises(LookupError, match="unbekannt"):
        service("101").get_transaction(str(uuid.uuid4()))
    with pytest.raises(LookupError):
        service("101").get_transaction("kein-uuid")


def test_till_status_counts_todays_closed_baskets(db: Db,
                                                  service: Callable[[str], PosService]) -> None:
    put(db, "99", "CLOSED", "13.17", closed_ago=timedelta(seconds=3))
    latest = put(db, "99", "CLOSED", "7.99", closed_ago=timedelta(seconds=1))
    put(db, "99", "CLOSED", "50.00", closed_ago=timedelta(days=2))   # not today
    put(db, "98", "CLOSED", "99.00", closed_ago=timedelta(seconds=1))  # other till
    put(db, "99", "CANCELLED", "3.00")
    open_b = put(db, "99", "OPEN", "1.19")
    assert service("199").get_till_status("GR-1") == {
        "till": "99", "open_tx": open_b.tx_id, "tx_today": 2, "last_closed_tx": latest.tx_id,
        "revenue_today": "21,16"}
    assert service("101").get_till_status() == {
        "till": "01", "open_tx": None, "tx_today": 0, "last_closed_tx": None,
        "revenue_today": "0,00"}


def test_till_state_shows_the_open_basket(db: Db, service: Callable[[str], PosService]) -> None:
    pos = service("101")
    assert pos.till_state("01") == {"till": "01", "store": "101", "open_tx": None}
    b = put(db, "01", "OPEN", "9.99", lines=(
        line(1, "100001", "GEBIT Ente (Quietscheente gelb)", "9.99"),
        line(2, "100010", "Vollmilch 3,5 %", "1.19", voided=True)))
    state = pos.till_state("01")
    assert state["open_tx"]["tx_id"] == b.tx_id and state["open_tx"]["total"] == "9,99"
    assert [ln["description"] for ln in state["open_tx"]["lines"]] == [
        "GEBIT Ente (Quietscheente gelb)"]
    with pytest.raises(KeyError):
        pos.till_state("42")


def test_admin_reset_resets_every_open_basket(db: Db,
                                              service: Callable[[str], PosService]) -> None:
    open_ids = {put(db, till, status).tx_id
                for till, status in (("01", "CREATED"), ("99", "OPEN"), ("98", "IN_PAYMENT"))}
    closed = put(db, "01", "CLOSED", "9.99", closed_ago=timedelta(0))
    outbox = db.fetch("select count(*) as n from pos.event_outbox")
    assert service("101").admin_reset() == {"status": "ok", "reset": 3}
    rows = {r["tx_id"]: r["status"] for r in db.fetch(
        "select tx_id::text as tx_id, status from pos.basket")}
    assert {rows[i] for i in open_ids} == {"RESET"} and rows[closed.tx_id] == "CLOSED"
    assert service("101").admin_reset()["reset"] == 0
    assert db.fetch("select count(*) as n from pos.event_outbox") == outbox  # no events


def test_reset_of_one_till_leaves_the_others(db: Db) -> None:
    mine, other = put(db, "99", "OPEN"), put(db, "01", "OPEN")
    with db.tx() as conn:
        assert store.reset_open(conn, "99") == [mine.tx_id]
        b = store.basket(conn, other.tx_id)
    assert b is not None and b.status == "OPEN"
