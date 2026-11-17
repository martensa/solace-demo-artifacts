"""Basket arithmetic of the POS simulator: taxes, GEBIT pricing information, payment.

Pure functions on ``Decimal`` (never ``float``), adapted from
``spikes/grpc-spike/gebitsim/sim.py`` (UC1-BUILD-SPEC 4.2):

* Gross pricing: line gross = effective unit price x item count.
* Tax classes as in gebitsim: ``A`` = 7 %, ``C`` = 19 %. Net per tax class =
  gross / (1 + rate), rounded half up to the cent; tax = gross - net.
* ``pricingInformation`` is proto3 JSON of the GEBIT ``datatype.PricingInformation``;
  ``articlePositions[].calculatedPositionPrice.basePrice`` is the effective unit price.
* Cash payment: the till takes partial payments; once the cash covers the total the
  change is handed back. GEBIT signs change negative (``-1,83``) in the payment
  position and in ``paymentSessionSums.change``; ``balance`` then nets out to zero.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from gposdemo.common.money import quantize, to_bdecimal, to_money

ZERO = Decimal("0.00")
TAX_CLASSES: dict[Decimal, str] = {Decimal(7): "A", Decimal(19): "C"}
PRICING_MODE = "PRICING_MODE_GROSS"
POSITION_TYPE = {"key": "positionType", "typedValue": {"stringValue": "articlePosition"}}


def tax_class(vat_pct: Decimal) -> str:
    """GEBIT tax class of a VAT rate: ``7`` -> ``"A"``, ``19`` -> ``"C"``."""
    try:
        return TAX_CLASSES[vat_pct]
    except KeyError:
        raise ValueError(f"no tax class for VAT {vat_pct} %") from None


def split_tax(gross: Decimal, vat_pct: Decimal) -> tuple[Decimal, Decimal]:
    """``(net, tax)`` of a gross amount: ``split_tax(9.99, 19)`` -> ``(8.39, 1.60)``."""
    net = quantize(gross * 100 / (100 + vat_pct))
    return net, gross - net


@dataclass(frozen=True)
class PricedLine:
    """One effectual basket line as the pricing sees it."""

    position_id: str
    unit_price: Decimal
    item_count: int
    vat_pct: Decimal

    @property
    def gross(self) -> Decimal:
        """Unit price times item count."""
        return quantize(self.unit_price * self.item_count)


def basket_total(lines: Sequence[PricedLine]) -> Decimal:
    """Sum of the line gross values (``0.00`` for an empty basket)."""
    return sum((line.gross for line in lines), ZERO)


def _tax_entry(cls: str, rate: Decimal, gross: Decimal) -> dict[str, Any]:
    net, tax = split_tax(gross, rate)
    return {"taxClass": cls, "taxRate": to_bdecimal(rate), "taxAmount": to_bdecimal(tax),
            "netAmount": to_bdecimal(net), "grossAmount": to_bdecimal(gross)}


def _position(line: PricedLine) -> dict[str, Any]:
    gross = line.gross
    return {"positionId": line.position_id, "calculatedPositionPrice": {
        "basePrice": to_bdecimal(line.unit_price), "baseValue": to_bdecimal(gross),
        "effectiveValue": to_bdecimal(gross),
        "taxes": [_tax_entry(tax_class(line.vat_pct), line.vat_pct, gross)],
        "extensionProperties": [POSITION_TYPE]}}


def pricing_information(lines: Sequence[PricedLine]) -> dict[str, Any]:
    """GEBIT ``PricingInformation`` (proto3 JSON) of the effectual lines.

    Tax sums are grouped by tax class (sorted ``A`` before ``C``); the net total is the
    sum of the per-class net amounts, as on a GEBIT receipt.
    """
    by_class: dict[tuple[str, Decimal], Decimal] = {}
    for line in lines:
        key = (tax_class(line.vat_pct), line.vat_pct)
        by_class[key] = by_class.get(key, ZERO) + line.gross
    tax_sums = [_tax_entry(cls, rate, gross) for (cls, rate), gross in sorted(by_class.items())]
    net_total = sum((split_tax(gross, rate)[0] for (_, rate), gross in by_class.items()), ZERO)
    info: dict[str, Any] = {"totalSum": to_bdecimal(basket_total(lines)),
                            "netTotalSum": to_bdecimal(net_total), "pricingMode": PRICING_MODE}
    if lines:
        info["taxSums"] = tax_sums
        info["articlePositions"] = [_position(line) for line in lines]
    return info


@dataclass(frozen=True)
class Settlement:
    """State of the payment session after one cash payment."""

    paid: Decimal
    change: Decimal
    complete: bool

    @property
    def signed_change(self) -> Decimal:
        """Change as GEBIT writes it (negative = handed back)."""
        return -self.change


def settle(total: Decimal, paid_before: Decimal, amount: Decimal) -> Settlement:
    """Add a cash ``amount``; complete once the cash covers ``total``, change = surplus."""
    if amount <= 0:
        raise ValueError(f"cash amount must be positive, got {amount}")
    paid = paid_before + amount
    if paid < total:
        return Settlement(paid, ZERO, False)
    return Settlement(paid, paid - total, True)


def payment_sums(total: Decimal, paid: Decimal, signed_change: Decimal = ZERO) -> dict[str, Any]:
    """GEBIT ``PaymentSessionSums``: ``balance = total - paid - signed_change``."""
    return {"totalToPay": to_money(total), "totalPaid": to_money(paid),
            "balance": to_money(total - paid - signed_change), "totalCashback": to_money(ZERO),
            "totalRounding": to_money(ZERO), "change": to_money(signed_change)}
