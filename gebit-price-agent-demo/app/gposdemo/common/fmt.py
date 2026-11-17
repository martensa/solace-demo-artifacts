"""German display formats for prices, percentages and dates (UC1-BUILD-SPEC 2.4).

``eur`` writes no thousands separator: every label must round-trip through
``parse_price`` (the gate compares price labels, 11.4 step 7).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

MINUS = "\u2212"  # typographic minus, "−20 %"
WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")

_PRICE = re.compile(r"^(-?\d+)(?:[.,](\d{1,2}))?$")
_CENT = Decimal("0.01")


def eur(value: Decimal) -> str:
    """Price label without currency: ``Decimal("9.99")`` -> ``"9,99"`` (half up)."""
    return f"{value.quantize(_CENT, rounding=ROUND_HALF_UP):f}".replace(".", ",")


def pct_label(pct: int, ascii_minus: bool = False) -> str:
    """Reduction label: ``20`` -> ``"−20 %"`` (U+2212) or ``"-20 %"`` with ``ascii_minus``.

    A positive ``pct`` is a reduction; ``0`` is ``"0 %"`` and a negative value an
    increase (``"+5 %"``).
    """
    if pct == 0:
        return "0 %"
    if pct < 0:
        return f"+{-pct} %"
    return f"{'-' if ascii_minus else MINUS}{pct} %"


def dt_label(value: datetime) -> str:
    """``"Di 23.02. 20:00"`` in the time zone of ``value`` (pass business time)."""
    return f"{WEEKDAYS[value.weekday()]} {value:%d.%m.} {value:%H:%M}"


def date_label(value: date) -> str:
    """``"14.02."``"""
    return f"{value:%d.%m.}"


def parse_price(text: str) -> Decimal:
    """``"7,99"`` | ``"7.99"`` | ``"7,99 €"`` -> ``Decimal("7.99")`` (two places).

    Raises ``ValueError`` for anything else (thousands separators included).
    """
    cleaned = text.strip().removesuffix("€").removesuffix("EUR").strip()
    match = _PRICE.match(cleaned)
    if not match:
        raise ValueError(f"not a price: {text!r}")
    whole, cents = match.group(1), match.group(2) or "0"
    return Decimal(f"{whole}.{cents}").quantize(_CENT)
