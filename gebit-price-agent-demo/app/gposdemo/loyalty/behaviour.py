"""Pure purchase-behaviour arithmetic of gpos-loyalty (UC1-BUILD-SPEC 4.4, 5.5, 6.4-6.6).

Every window is counted in business dates (``D`` = ``GPOS_DEMO_DATE``) and ends
yesterday, both edges inclusive: 8 weeks = ``[D-56, D-1]``, 12 weeks = ``[D-84, D-1]``.
A purchase with business date ``D`` (every booth purchase) never counts, also not
for ``days_since_last``. The business date of a purchase is the date of
``purchase.closed_at`` in ``GPOS_TZ``.

No I/O here: the store delivers rows, this module turns them into numbers.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from gposdemo.common.clock import in_window, past_window

DAYS_8W = 56
DAYS_12W = 84
WEEKS = 8
DAYS_PER_WEEK = 7
HALF = WEEKS // 2

_ONE_DECIMAL = Decimal("0.1")
_TWO_DECIMALS = Decimal("0.01")


@dataclass(frozen=True)
class Purchase:
    """One purchase (transaction) with its business date."""

    tx_id: str
    day: date


@dataclass(frozen=True)
class MemberStats:
    """Purchases of one article by one member (4.4 member fields)."""

    purchases_8w: int
    purchases_12w: int
    days_since_last: int  # -1 = never bought before D
    median_interval_days: int  # 0 = unknown (fewer than two purchase days)

    @property
    def overdue_factor(self) -> Decimal | None:
        """``days_since_last / median_interval_days``; ``None`` when either is unknown."""
        return overdue_factor(self.days_since_last, self.median_interval_days)


NO_PURCHASES = MemberStats(purchases_8w=0, purchases_12w=0, days_since_last=-1,
                           median_interval_days=0)


@dataclass(frozen=True)
class CategoryFrequency:
    """Purchases with one category in the 8-week window (profile history)."""

    category: str
    purchases_8w: int
    days_since_last: int


def business_day(closed_at: datetime, zone: ZoneInfo) -> date:
    """Business date of an aware timestamp in ``zone`` (``GPOS_TZ``)."""
    if closed_at.tzinfo is None:
        raise ValueError("closed_at needs an aware datetime")
    return closed_at.astimezone(zone).date()


def window_8w(today: date) -> tuple[date, date]:
    """``[D-56, D-1]``"""
    return past_window(today, DAYS_8W)


def window_12w(today: date) -> tuple[date, date]:
    """``[D-84, D-1]``"""
    return past_window(today, DAYS_12W)


def _count(purchases: Iterable[Purchase], window: tuple[date, date]) -> int:
    return len({p.tx_id for p in purchases if in_window(p.day, window)})


def median_interval(days: Iterable[date]) -> int:
    """Median of the gaps between distinct purchase days, rounded half up; 0 below two days."""
    ordered = sorted(set(days))
    if len(ordered) < 2:
        return 0
    gaps = [(later - earlier).days for earlier, later in zip(ordered, ordered[1:], strict=False)]
    median = Decimal(str(statistics.median(gaps)))
    return int(median.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def member_stats(purchases: Sequence[Purchase], today: date) -> MemberStats:
    """4.4 member fields from all purchases of the article by the member.

    Purchases on or after ``today`` are ignored completely.
    """
    before = [p for p in purchases if p.day < today]
    if not before:
        return NO_PURCHASES
    last = max(p.day for p in before)
    in_12w = [p.day for p in before if in_window(p.day, window_12w(today))]
    return MemberStats(
        purchases_8w=_count(before, window_8w(today)),
        purchases_12w=_count(before, window_12w(today)),
        days_since_last=(today - last).days,
        median_interval_days=median_interval(in_12w),
    )


def overdue_factor(days_since_last: int, median_interval_days: int) -> Decimal | None:
    """``days_since_last / median_interval_days``, cut (not rounded) to two decimals.

    Cutting keeps every threshold with at most two decimals exact: the agent rule
    "at least 1.5" holds for the shown value exactly when it holds for the true one.
    """
    if days_since_last < 0 or median_interval_days <= 0:
        return None
    ratio = Decimal(days_since_last) / Decimal(median_interval_days)
    return ratio.quantize(_TWO_DECIMALS, rounding=ROUND_DOWN)


def week_starts(today: date) -> list[date]:
    """First days of the 8 seven-day windows that end yesterday: ``D-56 + 7(k-1)`` (6.5)."""
    first = today - timedelta(days=DAYS_8W)
    return [first + timedelta(days=DAYS_PER_WEEK * k) for k in range(WEEKS)]


def weekly_series(by_week_start: Mapping[date, int], today: date) -> list[int]:
    """Cardholder purchases per week, 8 values, oldest first; a missing week counts 0."""
    return [int(by_week_start.get(start, 0)) for start in week_starts(today)]


def drop_pct(weekly: Sequence[int]) -> Decimal:
    """Drop of the last 4 weeks against the 4 weeks before, percent, one decimal half up.

    Negative = rise; ``0.0`` when the earlier 4 weeks have no purchases.
    ``[22, 24, 21, 23, 13, 12, 11, 12]`` -> ``46.7`` (6.5).
    """
    if len(weekly) != WEEKS:
        raise ValueError(f"need {WEEKS} weekly values, got {len(weekly)}")
    prior = Decimal(sum(weekly[:HALF])) / HALF
    recent = Decimal(sum(weekly[HALF:])) / HALF
    if prior == 0:
        return Decimal("0.0")
    return ((prior - recent) / prior * 100).quantize(_ONE_DECIMAL, rounding=ROUND_HALF_UP)


def category_frequencies(rows: Iterable[tuple[Purchase, str]], today: date
                         ) -> list[CategoryFrequency]:
    """Purchases per category in ``[D-56, D-1]``, most purchases first.

    Ties: more recent first, then category name. ``days_since_last`` counts from the
    last purchase with the category inside the window.
    """
    window = window_8w(today)
    days: dict[str, dict[str, date]] = {}
    for purchase, category in rows:
        if in_window(purchase.day, window):
            days.setdefault(category, {})[purchase.tx_id] = purchase.day
    found = [CategoryFrequency(category, len(by_tx), (today - max(by_tx.values())).days)
             for category, by_tx in days.items()]
    return sorted(found, key=lambda c: (-c.purchases_8w, c.days_since_last, c.category))
