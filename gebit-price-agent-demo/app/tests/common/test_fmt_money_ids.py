"""fmt, money, ids: German labels, BDecimal <-> Decimal, id format (2.4, 4.3, 5.6)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from google.protobuf.descriptor_pool import DescriptorPool

from gposdemo.common import fmt, ids, money
from gposdemo.common.descriptors import Types
from gposdemo.common.jsonutil import parse_strict


@pytest.mark.parametrize(("value", "label"), [
    ("9.99", "9,99"), ("7.99", "7,99"), ("5.49", "5,49"), ("12.99", "12,99"),
    ("84.12", "84,12"), ("7", "7,00"), ("7.985", "7,99"), ("7.984", "7,98"),
    ("1234.5", "1234,50"), ("0", "0,00"),
])
def test_eur(value: str, label: str) -> None:
    assert fmt.eur(Decimal(value)) == label


@pytest.mark.parametrize(("pct", "ascii_minus", "label"), [
    (20, False, "−20 %"), (31, False, "−31 %"), (10, True, "-10 %"),
    (0, False, "0 %"), (-5, False, "+5 %"),
])
def test_pct_label(pct: int, ascii_minus: bool, label: str) -> None:
    assert fmt.pct_label(pct, ascii_minus) == label


def test_dt_and_date_labels() -> None:
    berlin = ZoneInfo("Europe/Berlin")
    assert fmt.dt_label(datetime(2027, 2, 23, 20, 0, tzinfo=berlin)) == "Di 23.02. 20:00"
    assert fmt.dt_label(datetime(2027, 2, 21, 9, 5, tzinfo=berlin)) == "So 21.02. 09:05"
    assert fmt.date_label(date(2027, 2, 14)) == "14.02."
    assert fmt.date_label(date(2027, 1, 11)) == "11.01."


@pytest.mark.parametrize(("text", "value"), [
    ("7,99", "7.99"), ("7.99", "7.99"), (" 9,99 € ", "9.99"), ("5,4", "5.40"),
    ("12", "12.00"), ("14,49EUR", "14.49"),
])
def test_parse_price(text: str, value: str) -> None:
    assert fmt.parse_price(text) == Decimal(value)


@pytest.mark.parametrize("text", ["", "abc", "7,999", "1.234,56", "7,99,1", "€"])
def test_parse_price_rejects(text: str) -> None:
    with pytest.raises(ValueError):
        fmt.parse_price(text)


def test_price_labels_roundtrip() -> None:
    for cents in range(1, 20001, 7):
        value = Decimal(cents).scaleb(-2)
        assert fmt.parse_price(fmt.eur(value)) == value


def test_bdecimal_and_money() -> None:
    assert money.to_bdecimal(Decimal("9.99")) == {"scale": 2, "intVal": "999"}
    assert money.to_bdecimal(Decimal("22.6"), 1) == {"scale": 1, "intVal": "226"}
    assert money.to_bdecimal(Decimal("0.265")) == {"scale": 2, "intVal": "27"}  # half up
    assert money.to_money(Decimal("7.99")) == {
        "currency": "EUR", "amount": {"scale": 2, "intVal": "799"}}
    assert money.from_bdecimal({"scale": 2, "intVal": "1449"}) == Decimal("14.49")
    assert money.from_bdecimal({"scale": 2, "int_val": 549}) == Decimal("5.49")
    assert money.from_bdecimal({}) == Decimal(0)
    assert money.from_money({"currency": "EUR", "amount": {"scale": 2, "intVal": "999"}}) \
        == Decimal("9.99")


def test_bdecimal_message_roundtrip(showcase_pool: DescriptorPool) -> None:
    types = Types(showcase_pool)
    msg = parse_strict(money.to_money(Decimal("27.45")),
                       types.new("de.showcase.wws.v1.datatype.Money"))
    assert (msg.amount.scale, msg.amount.int_val, msg.currency) == (2, 2745, "EUR")
    assert money.from_money(msg) == Decimal("27.45")


def test_decimal_helpers_never_go_through_float_rounding() -> None:
    assert money.to_decimal(0.1) == Decimal("0.1")
    assert money.to_decimal("14.49") == Decimal("14.49")
    assert money.quantize(Decimal("11.505")) == Decimal("11.51")
    assert money.quantize(Decimal("22.55"), 1) == Decimal("22.6")


def test_ids() -> None:
    assert ids.make_id("GP", date(2027, 2, 16), 3) == "GP-270216-0003"
    assert ids.make_id("GR", date(2027, 2, 16), 7) == "GR-270216-0007"
    assert ids.make_id("PA", date(2027, 2, 16), 12345) == "PA-270216-12345"
    with pytest.raises(ValueError):
        ids.make_id("gp", date(2027, 2, 16), 1)
    with pytest.raises(ValueError):
        ids.make_id("GP", date(2027, 2, 16), 0)
