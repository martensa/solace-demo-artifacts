"""Decimal money and the GEBIT-style ``BDecimal``/``Money`` messages (UC1-BUILD-SPEC 4.3).

``BDecimal`` value = ``int_val * 10^-scale``; in proto3 JSON ``intVal`` is an int64
and therefore a string. Amounts are always ``Decimal``, never ``float``.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

CURRENCY = "EUR"


def to_decimal(value: Decimal | int | str | float) -> Decimal:
    """Exact ``Decimal`` from a ``Decimal``, ``int``, ``str`` or YAML ``float`` (via ``str``)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quantize(value: Decimal, scale: int = 2) -> Decimal:
    """Round half up to ``scale`` places: ``Decimal("7.985")`` -> ``Decimal("7.99")``."""
    return value.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)


def to_bdecimal(value: Decimal, scale: int = 2) -> dict[str, Any]:
    """``Decimal("9.99")`` -> ``{"scale": 2, "intVal": "999"}`` (rounded half up)."""
    int_val = int(quantize(value, scale).scaleb(scale))
    return {"scale": scale, "intVal": str(int_val)}


def from_bdecimal(obj: Mapping[str, Any] | Any) -> Decimal:
    """Inverse of :func:`to_bdecimal` for a proto3 JSON dict or a ``BDecimal`` message.

    Missing fields are proto3 defaults (``0``); ``intVal`` and ``int_val`` are both read.
    """
    if isinstance(obj, Mapping):
        scale = int(obj.get("scale", 0) or 0)
        int_val = int(obj.get("intVal", obj.get("int_val", 0)) or 0)
    else:
        scale, int_val = int(obj.scale), int(obj.int_val)
    return Decimal(int_val).scaleb(-scale)


def to_money(value: Decimal) -> dict[str, Any]:
    """``{"currency": "EUR", "amount": {"scale": 2, "intVal": "999"}}``"""
    return {"currency": CURRENCY, "amount": to_bdecimal(value)}


def from_money(obj: Mapping[str, Any] | Any) -> Decimal:
    """Amount of a ``Money`` dict or message (the currency is always EUR)."""
    amount = obj.get("amount", {}) if isinstance(obj, Mapping) else obj.amount
    return from_bdecimal(amount)
