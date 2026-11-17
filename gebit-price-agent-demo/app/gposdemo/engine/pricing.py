"""Price computation of the engine (UC1-BUILD-SPEC 6.7).

1. step price ``target`` = ``regular * (100 - step) / 100``, truncated to cents;
2. price point = largest price <= ``target`` ending in ,99 ,89 ,79 or ,49;
3. net margin = ``(p / (1 + vat) - cost) / (p / (1 + vat))``; a step is allowed with
   at least ``min_margin_pct``; ``max_step_pct`` = largest allowed step, else 0;
4. ``pct_shown`` = ``(ref30 - p) / ref30 * 100`` rounded down (PAngV);
5. valid from business date 00:00 to business date + ``action_days`` at 20:00;
6. base price per kg (``g``) or per l (``ml``), none for ``Stück``;
8. note "Rücknahme der Preiserhöhung vom …" (see :func:`price_note`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from ..common.fmt import date_label, eur
from .policy import Policy

CENT = Decimal("0.01")
TENTH = Decimal("0.1")
HUNDRED = Decimal(100)
NOTE_MAX_DAYS = 90
BASE_UNITS = {"g": ("kg", Decimal(1000)), "ml": ("l", Decimal(1000))}


@dataclass(frozen=True)
class StepOption:
    """One discount step of an article: price point and net margin (``None``: no point)."""

    step: int
    price: Decimal | None
    margin_pct: Decimal | None
    allowed: bool


@dataclass(frozen=True)
class PriceChange:
    """Last regular price change of an article (WWS ``last_price_change``)."""

    on: date
    old_price: Decimal
    new_price: Decimal


def step_target(regular: Decimal, step: int) -> Decimal:
    """``regular * (100 - step) / 100`` truncated to cents."""
    return (regular * (HUNDRED - step) / HUNDRED).quantize(CENT, rounding=ROUND_DOWN)


def price_point(target: Decimal, endings_cents: tuple[int, ...]) -> Decimal | None:
    """Largest price <= ``target`` whose cents are one of ``endings_cents`` (euro downwards)."""
    endings = sorted(endings_cents, reverse=True)
    euros = int(target.to_integral_value(rounding=ROUND_FLOOR))
    for euro in range(euros, -1, -1):
        for cents in endings:
            candidate = Decimal(euro) + Decimal(cents) / HUNDRED
            if candidate <= target:
                return candidate
    return None


def margin_pct(price: Decimal, cost_net: Decimal, vat_percent: Decimal) -> Decimal:
    """Net margin in percent at gross ``price`` (unrounded)."""
    net = price / (1 + vat_percent / HUNDRED)
    return (net - cost_net) / net * HUNDRED


def round_tenth(value: Decimal) -> Decimal:
    """One decimal place, half up (margin display, ``numeric(5,1)``)."""
    return value.quantize(TENTH, rounding=ROUND_HALF_UP)


def step_options(regular: Decimal, cost_net: Decimal, vat_percent: Decimal,
                 policy: Policy) -> list[StepOption]:
    """All steps of the policy with their price point and margin."""
    out = []
    for step in policy.guardrails.steps_pct:
        point = price_point(step_target(regular, step), policy.guardrails.price_endings_cents)
        if point is None or point <= 0:
            out.append(StepOption(step, None, None, False))
            continue
        margin = margin_pct(point, cost_net, vat_percent)
        allowed = point < regular and margin >= policy.guardrails.min_margin_pct
        out.append(StepOption(step, point, margin, allowed))
    return out


def max_step(options: list[StepOption]) -> int:
    """Largest allowed step, 0 when none is allowed."""
    return max((o.step for o in options if o.allowed), default=0)


def option_for(options: list[StepOption], step: int) -> StepOption:
    """The option of ``step`` (``KeyError`` if the policy has no such step)."""
    for option in options:
        if option.step == step:
            return option
    raise KeyError(f"no step {step}")


def pct_shown(ref30: Decimal, price: Decimal) -> int:
    """Reduction against ``ref30`` in percent, rounded down; 0 when not lower."""
    if ref30 <= 0 or price >= ref30:
        return 0
    return int(((ref30 - price) / ref30 * HUNDRED).to_integral_value(rounding=ROUND_FLOOR))


def base_price_label(price: Decimal, net_quantity: Decimal, base_unit: str) -> str:
    """``"27,45 €/kg"`` for 5,49 € / 200 g; ``""`` for ``Stück`` (PAngV, 6.7 step 6)."""
    unit = BASE_UNITS.get(base_unit)
    if unit is None or net_quantity <= 0:
        return ""
    label, per = unit
    return f"{eur(price * per / net_quantity)} €/{label}"


def validity(demo_date: date, policy: Policy, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """``(valid_from, valid_to)``: business date 00:00 to ``+action_days`` at the end time."""
    valid_from = datetime(demo_date.year, demo_date.month, demo_date.day, tzinfo=zone)
    end_day = demo_date + timedelta(days=policy.guardrails.action_days)
    end = policy.guardrails.action_end_time
    valid_to = datetime(end_day.year, end_day.month, end_day.day, end.hour, end.minute,
                        tzinfo=zone)
    return valid_from, valid_to


def price_note(change: PriceChange | None, new_price: Decimal, demo_date: date) -> str:
    """6.7 step 8: last regular change at most 90 days back, an increase, and the new
    price is not below the price before it -> ``"Rücknahme der Preiserhöhung vom 11.01."``."""
    if change is None:
        return ""
    recent = timedelta(0) <= demo_date - change.on <= timedelta(days=NOTE_MAX_DAYS)
    if recent and change.new_price > change.old_price and new_price >= change.old_price:
        return f"Rücknahme der Preiserhöhung vom {date_label(change.on)}"
    return ""
