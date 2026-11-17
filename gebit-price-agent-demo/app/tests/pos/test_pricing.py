"""Basket, tax and payment arithmetic of the POS (13.1 tests/pos, no marker)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from gposdemo.common.money import from_bdecimal, from_money
from gposdemo.pos.pricing import (PricedLine, basket_total, payment_sums, pricing_information,
                                  settle, split_tax, tax_class)

D = Decimal
ENTE = PricedLine("p-ente", D("9.99"), 1, D(19))
BANANEN = PricedLine("p-bananen", D("1.99"), 1, D(7))
MILCH = PricedLine("p-milch", D("1.19"), 1, D(7))
S1 = [ENTE, BANANEN, MILCH]


def test_tax_classes_as_in_gebitsim() -> None:
    assert tax_class(D(7)) == "A"
    assert tax_class(D("19.00")) == "C"  # WWS sends BDecimal 19.00
    with pytest.raises(ValueError, match="no tax class"):
        tax_class(D(16))


@pytest.mark.parametrize(("gross", "rate", "net", "tax"), [
    ("9.99", 19, "8.39", "1.60"),     # GEBIT Ente
    ("1.99", 7, "1.86", "0.13"),      # Bio-Bananen
    ("1.19", 7, "1.11", "0.08"),      # Vollmilch
    ("3.18", 7, "2.97", "0.21"),      # class A of S1
    ("14.49", 7, "13.54", "0.95"),    # Espresso
])
def test_split_tax_half_up(gross: str, rate: int, net: str, tax: str) -> None:
    assert split_tax(D(gross), D(rate)) == (D(net), D(tax))


def test_s1_total_and_tax_split() -> None:
    info = pricing_information(S1)
    assert basket_total(S1) == D("13.17")
    assert from_bdecimal(info["totalSum"]) == D("13.17")
    assert from_bdecimal(info["netTotalSum"]) == D("11.36")  # 2.97 (A) + 8.39 (C)
    assert info["pricingMode"] == "PRICING_MODE_GROSS"
    a, c = info["taxSums"]
    assert (a["taxClass"], from_bdecimal(a["taxRate"]), from_bdecimal(a["grossAmount"]),
            from_bdecimal(a["netAmount"]), from_bdecimal(a["taxAmount"])) == (
        "A", D(7), D("3.18"), D("2.97"), D("0.21"))
    assert (c["taxClass"], from_bdecimal(c["grossAmount"]), from_bdecimal(c["taxAmount"])) == (
        "C", D("9.99"), D("1.60"))
    assert a["taxRate"] == {"scale": 2, "intVal": "700"}


def test_article_positions_carry_the_effective_unit_price() -> None:
    lines = [PricedLine("p-ente", D("7.99"), 1, D(19)), PricedLine("p-milch", D("1.19"), 3, D(7))]
    positions = pricing_information(lines)["articlePositions"]
    assert [p["positionId"] for p in positions] == ["p-ente", "p-milch"]
    ente, milch = (p["calculatedPositionPrice"] for p in positions)
    assert from_bdecimal(ente["basePrice"]) == D("7.99")
    assert from_bdecimal(milch["basePrice"]) == D("1.19")
    assert from_bdecimal(milch["baseValue"]) == D("3.57")
    assert from_bdecimal(milch["effectiveValue"]) == D("3.57")
    assert milch["taxes"][0]["taxClass"] == "A"
    assert from_bdecimal(milch["taxes"][0]["netAmount"]) == D("3.34")


def test_empty_basket_has_no_tax_sums() -> None:
    info = pricing_information([])
    assert "taxSums" not in info and "articlePositions" not in info
    assert from_bdecimal(info["totalSum"]) == D(0)


def test_cash_with_change_s1() -> None:
    result = settle(D("13.17"), D(0), D("15.00"))
    assert (result.complete, result.paid, result.change, result.signed_change) == (
        True, D("15.00"), D("1.83"), D("-1.83"))
    sums = payment_sums(D("13.17"), result.paid, result.signed_change)
    assert from_money(sums["totalToPay"]) == D("13.17")
    assert from_money(sums["totalPaid"]) == D("15.00")
    assert from_money(sums["change"]) == D("-1.83")
    assert from_money(sums["balance"]) == D(0)
    assert sums["change"]["currency"] == "EUR"


def test_partial_cash_then_exact_rest() -> None:
    first = settle(D("13.17"), D(0), D("10.00"))
    assert (first.complete, first.change) == (False, D(0))
    assert from_money(payment_sums(D("13.17"), first.paid)["balance"]) == D("3.17")
    second = settle(D("13.17"), first.paid, D("3.17"))
    assert (second.complete, second.paid, second.change) == (True, D("13.17"), D(0))


def test_cash_amount_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        settle(D("13.17"), D(0), D(0))
