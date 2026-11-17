"""Guardrail list of a proposal (UC1-BUILD-SPEC 6.7 step 7, example 7.2).

Always every row with ``ok`` true/false, plus one info row per blocked step above the
chosen one (``"−30 % gesperrt"`` with ``"Marge 11,5 %"``).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..common.fmt import pct_label
from .pricing import StepOption, round_tenth
from .texts import de_num


def percent(value: Decimal) -> str:
    """``Decimal("22.55")`` -> ``"22,6 %"``"""
    return f"{round_tenth(value):f} %".replace(".", ",")


def guardrail_rows(chosen: StepOption, options: list[StepOption], *, regular: Decimal,
                   price_bound: bool, action_open: bool, valid_to_label: str,
                   min_margin_pct: Decimal) -> list[dict[str, Any]]:
    """The 6.7 list for the chosen step (its price and margin must be set)."""
    if chosen.price is None or chosen.margin_pct is None:
        raise ValueError(f"step {chosen.step} has no price point")
    ending = int(chosen.price * 100) % 100
    rows: list[dict[str, Any]] = [
        {"rule": "Nur Senkung", "ok": chosen.price < regular},
        {"rule": f"Mindestmarge {de_num(min_margin_pct)} %",
         "ok": chosen.margin_pct >= min_margin_pct, "value": percent(chosen.margin_pct)},
        {"rule": "Keine laufende Aktion", "ok": not action_open},
        {"rule": "Nicht preisgebunden", "ok": not price_bound},
        {"rule": f"Preispunkt ,{ending:02d}", "ok": True},
        {"rule": f"Befristet bis {valid_to_label}", "ok": True},
        {"rule": "Ein offener Vorschlag je Kasse", "ok": True},
    ]
    for option in options:
        if option.step > chosen.step and not option.allowed:
            value = (f"Marge {percent(option.margin_pct)}" if option.margin_pct is not None
                     else "kein Preispunkt")
            rows.append({"rule": f"{pct_label(option.step)} gesperrt", "ok": False,
                         "value": value, "info": True})
    return rows
