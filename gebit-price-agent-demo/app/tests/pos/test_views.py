"""Agent and admin views of a basket, size budget of get_transaction (8.4, 11.8; no marker)."""

from __future__ import annotations

from decimal import Decimal

from gposdemo.common.jsonutil import compact
from gposdemo.common.mcputil import AGENT_MAX_TEXT_BYTES, text_result
from gposdemo.pos.service import MAX_LINES, open_tx_view, short_name, transaction_view
from gposdemo.pos.store import Basket, Line
from gposdemo.pos.tools import till_summary, transaction_summary

TX = "5b1f0c2e-8d1e-4a43-9a51-0c7a2f0e1b11"
LONG_NAME = "Bio-Fruchtjoghurt Erdbeere-Rhabarber cremig gerührt Großpackung"  # 63 chars


def basket(**kw: object) -> Basket:
    values: dict[str, object] = {
        "tx_id": TX, "till_id": "01", "store_id": "101", "location": "Root.DE.999.101.01",
        "status": "CLOSED", "receipt_number": "10101270216000042", "membership_id": "M-1001",
        "total": Decimal("16.98"), "last_offset": 13}
    return Basket(**{**values, **kw})  # type: ignore[arg-type]


def line(no: int, name: str = "Espresso Bohnen kräftig", price: str = "14.49",
         source: str = "REGULAR", voided: bool = False, count: int = 1) -> Line:
    return Line(position_id=f"00000000-0000-4000-8000-{no:012d}", line_no=no,
                article_number=f"1000{no:02d}", article_id=f"ID1000{no:02d}", name=name,
                gtin="2099100000124", category="kaffee_tee", item_count=count,
                unit_price=Decimal(price), regular_price=Decimal("14.49"), price_source=source,
                action_id="PA-270216-0003" if source == "BOOTH_ACTION" else None,
                vat_pct=Decimal(7), voided=voided)


def size(view: dict[str, object]) -> int:
    return len(compact(view).encode("utf-8"))


def test_transaction_view_s3_shape() -> None:
    view = transaction_view(basket(), [line(12), line(17, "Butter-Croissants", "2.49")])
    assert view == {
        "tx_id": TX, "till": "01", "status": "CLOSED", "receipt": "10101270216000042",
        "membership_id": "M-1001", "total": "16,98",
        "lines": [{"article_number": "100012", "name": "Espresso Bohnen kräftig", "qty": 1,
                   "price": "14,49", "source": "REGULAR"},
                  {"article_number": "100017", "name": "Butter-Croissants", "qty": 1,
                   "price": "2,49", "source": "REGULAR"}]}
    assert "kräftig" in text_result(view).content[0].text  # umlauts stay raw


def test_voided_lines_are_not_shown() -> None:
    view = transaction_view(basket(membership_id=None, receipt_number=None),
                            [line(1), line(2, voided=True), line(3)])
    assert [ln["article_number"] for ln in view["lines"]] == ["100001", "100003"]
    assert view["membership_id"] is None and view["receipt"] is None
    assert "more" not in view


def test_at_most_eight_lines_then_more() -> None:
    view = transaction_view(basket(), [line(n) for n in range(1, 13)])
    assert len(view["lines"]) == MAX_LINES == 8
    assert view["more"] == 4


def test_max_case_eight_long_lines_fits_1200_bytes() -> None:
    lines = [line(n, LONG_NAME, "999.99", "CENTRAL_ACTION", count=99) for n in range(1, 9)]
    view = transaction_view(basket(status="IN_PAYMENT", total=Decimal("9999.99")), lines)
    assert len(view["lines"]) == 8 and "more" not in view
    assert view["lines"][0]["name"] == short_name(LONG_NAME)
    assert len(view["lines"][0]["name"]) == 32 and view["lines"][0]["name"].endswith("…")
    assert size(view) <= AGENT_MAX_TEXT_BYTES


def test_oversized_lines_move_into_more() -> None:
    umlauts = "Ä" * 39  # 2 bytes each after the cut
    lines = [line(n, umlauts + "Ü" * 20, "999.99", "CENTRAL_ACTION", count=99)
             for n in range(1, 13)]
    view = transaction_view(basket(), lines)
    assert size(view) <= AGENT_MAX_TEXT_BYTES
    assert len(view["lines"]) < 8
    assert len(view["lines"]) + view["more"] == 12


def test_open_tx_view_for_the_bff() -> None:
    view = open_tx_view(basket(status="OPEN", total=Decimal("7.99"), last_offset=5),
                        [line(1, "GEBIT Ente (Quietscheente gelb)", "7.99", "BOOTH_ACTION"),
                         line(2, voided=True)])
    assert (view["tx_id"], view["till"], view["store_id"], view["status"]) == (
        TX, "01", "101", "OPEN")
    assert (view["total"], view["offset"], view["membership_id"]) == ("7,99", 5, "M-1001")
    [only] = view["lines"]
    assert only == {"position_id": "00000000-0000-4000-8000-000000000001", "line_no": 1,
                    "article_number": "100001", "article_id": "ID100001",
                    "description": "GEBIT Ente (Quietscheente gelb)", "gtin": "2099100000124",
                    "item_count": 1, "price": "7,99", "regular_price": "14,49",
                    "price_source": "BOOTH_ACTION", "action_id": "PA-270216-0003"}


def test_telemetry_summaries_are_german_one_liners() -> None:
    tx = text_result(transaction_view(basket(), [line(n) for n in range(1, 11)]))
    assert transaction_summary({}, tx) == "Bon 5b1f0c2e: 10 Zeilen, 16,98 €, Karte M-1001"
    till = text_result({"till": "01", "open_tx": None, "tx_today": 7, "last_closed_tx": TX,
                        "revenue_today": "84,12"})
    assert till_summary({}, till) == "Kasse 01: 7 Bons heute, 84,12 €, kein offener Bon"
