"""Purchase-behaviour arithmetic (4.4, 6.4-6.6, 6.8): windows, edges, median, trend."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from gposdemo.loyalty.behaviour import (
    NO_PURCHASES,
    CategoryFrequency,
    MemberStats,
    Purchase,
    business_day,
    category_frequencies,
    drop_pct,
    median_interval,
    member_stats,
    overdue_factor,
    week_starts,
    weekly_series,
)
from tests.loyalty.helpers import D

BERLIN = ZoneInfo("Europe/Berlin")
# Kaffeepause (M-1001) buys Espresso every second Tuesday (6.4).
ESPRESSO_DAYS = (date(2026, 12, 1), date(2026, 12, 15), date(2026, 12, 29),
                 date(2027, 1, 12))
CARDHOLDER_ESPRESSO = [22, 24, 21, 23, 13, 12, 11, 12]  # override 6.5


def _purchases(days: tuple[date, ...] | list[date], prefix: str = "tx") -> list[Purchase]:
    return [Purchase(f"{prefix}-{day.isoformat()}", day) for day in days]


def _every(first: date, step: int, last: date) -> list[date]:
    days, day = [], first
    while day <= last:
        days.append(day)
        day += timedelta(days=step)
    return days


def test_kaffeepause_espresso_golden_values() -> None:
    stats = member_stats(_purchases(ESPRESSO_DAYS), D)
    assert stats == MemberStats(purchases_8w=2, purchases_12w=4, days_since_last=35,
                                median_interval_days=14)
    assert stats.overdue_factor == Decimal("2.50")


@pytest.mark.parametrize("shift", [-1, 1])
def test_golden_values_hold_one_day_either_side(shift: int) -> None:
    """Every window edge is 7 days away from a purchase (6.4): D +- 1 keeps 2 / 4 / 14."""
    stats = member_stats(_purchases(ESPRESSO_DAYS), D + timedelta(days=shift))
    assert (stats.purchases_8w, stats.purchases_12w, stats.median_interval_days) == (2, 4, 14)
    assert stats.days_since_last == 35 + shift


@pytest.mark.parametrize(("days_before_d", "in_8w", "in_12w"), [
    (1, 1, 1),    # D-1: last day of both windows
    (56, 1, 1),   # D-56: first day of the 8-week window
    (57, 0, 1),   # D-57: one day too early for 8 weeks
    (84, 0, 1),   # D-84: first day of the 12-week window
    (85, 0, 0),   # D-85: outside both windows
])
def test_window_edges_are_inclusive(days_before_d: int, in_8w: int, in_12w: int) -> None:
    stats = member_stats(_purchases([D - timedelta(days=days_before_d)]), D)
    assert (stats.purchases_8w, stats.purchases_12w) == (in_8w, in_12w)
    assert stats.days_since_last == days_before_d  # the last purchase counts without window
    assert stats.median_interval_days == 0


@pytest.mark.parametrize("days_after_d", [0, 1])
def test_purchases_on_or_after_the_business_date_never_count(days_after_d: int) -> None:
    booth = Purchase("booth", D + timedelta(days=days_after_d))
    assert member_stats(_purchases(ESPRESSO_DAYS) + [booth], D) == member_stats(
        _purchases(ESPRESSO_DAYS), D)
    assert member_stats([booth], D) == NO_PURCHASES


def test_two_purchases_on_one_day_count_twice_but_one_interval_day() -> None:
    day = D - timedelta(days=10)
    stats = member_stats([Purchase("a", day), Purchase("b", day)], D)
    assert (stats.purchases_8w, stats.median_interval_days) == (2, 0)


@pytest.mark.parametrize(("days", "median"), [
    (ESPRESSO_DAYS, 14),
    ((date(2027, 1, 1), date(2027, 1, 8), date(2027, 1, 22)), 11),  # gaps 7, 14 -> 10.5
    ((date(2027, 1, 1), date(2027, 1, 8), date(2027, 1, 15), date(2027, 1, 29)), 7),
    ((date(2027, 1, 1),), 0),
    ((), 0),
])
def test_median_interval(days: tuple[date, ...], median: int) -> None:
    assert median_interval(days) == median


def test_median_uses_only_the_12_week_window() -> None:
    outside = [D - timedelta(days=100), D - timedelta(days=86)]
    stats = member_stats(_purchases([*outside, D - timedelta(days=50)]), D)
    assert (stats.purchases_12w, stats.median_interval_days) == (1, 0)


@pytest.mark.parametrize(("days_since_last", "median", "factor"), [
    (35, 14, Decimal("2.50")),
    (21, 14, Decimal("1.50")),
    (20, 14, Decimal("1.42")),  # 1.428... is cut, never rounded up over a threshold
    (-1, 14, None),
    (5, 0, None),
])
def test_overdue_factor(days_since_last: int, median: int, factor: Decimal | None) -> None:
    assert overdue_factor(days_since_last, median) == factor


def test_week_starts_are_the_8_windows_ending_yesterday() -> None:
    starts = week_starts(D)
    assert starts[0] == D - timedelta(days=56) == date(2026, 12, 22)
    assert starts[-1] + timedelta(days=6) == D - timedelta(days=1)
    assert [(b - a).days for a, b in zip(starts, starts[1:], strict=False)] == [7] * 7


def test_weekly_series_fills_missing_weeks_with_zero() -> None:
    starts = week_starts(D)
    by_week = dict(zip(starts, CARDHOLDER_ESPRESSO, strict=True))
    assert weekly_series(by_week, D) == CARDHOLDER_ESPRESSO
    del by_week[starts[2]]
    by_week[date(2026, 1, 1)] = 99  # not one of the 8 windows
    assert weekly_series(by_week, D) == [22, 24, 0, 23, 13, 12, 11, 12]


@pytest.mark.parametrize(("weekly", "drop"), [
    (CARDHOLDER_ESPRESSO, Decimal("46.7")),        # 22.5 -> 12.0 (6.5)
    ([10, 10, 10, 10, 12, 12, 12, 12], Decimal("-20.0")),
    ([0, 0, 0, 0, 3, 4, 5, 6], Decimal("0.0")),
    ([19, 21, 20, 22, 18, 20, 21, 19], Decimal("4.9")),  # 20.5 -> 19.5
])
def test_cardholder_drop_pct(weekly: list[int], drop: Decimal) -> None:
    assert drop_pct(weekly) == drop


def test_cardholder_drop_needs_eight_weeks() -> None:
    with pytest.raises(ValueError, match="8 weekly values"):
        drop_pct([1, 2, 3])


def test_business_day_uses_the_local_date() -> None:
    late_utc = datetime(2026, 12, 21, 23, 30, tzinfo=UTC)  # 00:30 in Berlin
    assert business_day(late_utc, BERLIN) == date(2026, 12, 22)
    with pytest.raises(ValueError, match="aware"):
        business_day(datetime(2026, 12, 22, 10, 30), BERLIN)


def test_category_frequencies_of_kaffeepause() -> None:
    """M-1001 history of 6.4: Espresso, Croissants + Vollmilch weekly, Cantuccini
    biweekly."""
    rows: list[tuple[Purchase, str]] = []
    by_day: dict[date, set[str]] = {}
    for day in ESPRESSO_DAYS:
        by_day.setdefault(day, set()).add("kaffee_tee")
    for day in _every(date(2026, 11, 24), 7, date(2027, 2, 9)):
        by_day.setdefault(day, set()).add("molkerei_fruehstueck")
    for day in _every(date(2026, 11, 24), 14, date(2027, 2, 2)):
        by_day.setdefault(day, set()).add("suesswaren_snacks")
    for day, categories in by_day.items():
        rows += [(Purchase(f"tx-{day}", day), cat) for cat in sorted(categories)]
    assert category_frequencies(rows, D) == [
        CategoryFrequency("molkerei_fruehstueck", 8, 7),
        CategoryFrequency("suesswaren_snacks", 4, 14),
        CategoryFrequency("kaffee_tee", 2, 35),
    ]


def test_category_frequencies_ignore_purchases_outside_the_8_weeks() -> None:
    rows = [(Purchase("old", D - timedelta(days=57)), "getraenke"),
            (Purchase("booth", D), "getraenke"),
            (Purchase("a", D - timedelta(days=3)), "buch"),
            (Purchase("b", D - timedelta(days=9)), "buch"),
            (Purchase("c", D - timedelta(days=2)), "obst_gemuese"),
            (Purchase("d", D - timedelta(days=30)), "obst_gemuese")]
    assert category_frequencies(rows, D) == [CategoryFrequency("obst_gemuese", 2, 2),
                                             CategoryFrequency("buch", 2, 3)]
