"""Pure WWS analytics against the master data of 6.2 and the golden values of 6.8.

No database: articles come from ``data/articles.yaml``; the weekly sums are booked on
one day per window, which is all the 8 windows of 6.6 look at.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from gposdemo.wws import analytics
from gposdemo.wws.analytics import (ArticleRecord, Delivery, HistoryEntry, PriceAction,
                                    Season)

TZ = ZoneInfo("Europe/Berlin")
D = date(2027, 2, 16)
NOW = datetime(2027, 2, 16, 14, 20, tzinfo=TZ)
SEASONS = {
    "valentinstag": Season("valentinstag", "Valentinstag", date(2027, 1, 18), date(2027, 2, 14)),
    "winter": Season("winter", "Winter", date(2026, 11, 1), date(2027, 2, 28)),
    "ostern": Season("ostern", "Ostern", date(2027, 3, 1), date(2027, 3, 28)),
}
ON_PLAN = [n for n in (f"1000{i:02d}" for i in range(1, 31))
           if n not in ("100001", "100002", "100008", "100009", "100012", "100028")]


def at(day: date, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


def record(a: dict[str, Any], store_id: str = "101") -> ArticleRecord:
    return ArticleRecord(
        article_number=a["number"], article_id=f"ID{a['number']}", gtin=a["gtin"],
        name=a["name"], category=a["cat"], category_label="", pack_label=a["pack"],
        net_quantity=a["qty"], base_unit=a["unit"], vat_pct=a["vat"], cost_net=a["cost"],
        price_bound=bool(a.get("price_bound", False)), season_code=a.get("season", ""),
        listed_since=a["listed"], store_id=store_id, regular_price=a["price"],
        stock_on_hand=a["stock"])


def daily(a: dict[str, Any], today: date = D) -> list[tuple[date, int]]:
    """Each weekly sum on the middle day of its window, plus noise outside [D-56, D-1]."""
    rows = [(start + timedelta(days=3), units)
            for (start, _), units in zip(analytics.week_windows(today), a["w"], strict=True)]
    return rows + [(today - timedelta(days=57), 999), (today, 999)]


def figures(a: dict[str, Any], delivery: Delivery | None = None) -> analytics.SalesFigures:
    return analytics.sales_figures(record(a), a["plan"], daily(a), D, delivery)


def history(*rows: tuple[str, datetime, datetime | None, str]) -> list[HistoryEntry]:
    return [HistoryEntry(Decimal(p), f, t, k) for p, f, t, k in rows]


def booth(article: str = "100001", price: str = "7.99", *, valid_from: datetime = at(D),
          valid_to: datetime = at(D + timedelta(days=7), 20), ended: datetime | None = None
          ) -> PriceAction:
    return PriceAction("PA-270216-0003", article, "101", "BOOTH", Decimal("9.99"),
                       Decimal(price), 20, Decimal("9.99"), valid_from, valid_to,
                       "GP-270216-0003", "REASON_CODE_SLOW_SELLER", "gpos-engine",
                       "role:marktleitung", ended, "reset" if ended else "")


# ----------------------------------------------------------------------- sales windows
def test_week_windows_end_yesterday() -> None:
    windows = analytics.week_windows(D)
    assert len(windows) == 8
    assert windows[0] == (date(2026, 12, 22), date(2026, 12, 28))
    assert windows[-1] == (date(2027, 2, 9), date(2027, 2, 15))
    assert all((end - start).days == 6 for start, end in windows)
    assert all(b[0] - a[1] == timedelta(days=1) for a, b in zip(windows, windows[1:]))


def test_weekly_units_ignore_days_outside_the_window(articles: dict[str, dict]) -> None:
    ente = articles["100001"]
    assert analytics.weekly_units(daily(ente), D) == (34, 36, 31, 28, 22, 16, 12, 9)
    edges = [(date(2026, 12, 22), 1), (date(2027, 2, 15), 2), (date(2026, 12, 21), 50),
             (D, 50)]
    assert analytics.weekly_units(edges, D) == (1, 0, 0, 0, 0, 0, 0, 2)


def test_ente_is_a_falling_slow_seller(articles: dict[str, dict]) -> None:
    f = figures(articles["100001"])
    assert (f.as_of, f.sold_7d, f.plan_7d) == (date(2027, 2, 15), 9, Decimal(35))
    assert f.weekly_units == (34, 36, 31, 28, 22, 16, 12, 9)
    assert f.avg_week_28d == Decimal("14.75")
    assert f.sell_through_7d.quantize(Decimal("0.01")) == Decimal("0.26")
    assert f.sell_through_7d < Decimal("0.3")  # 6.6: strong slow seller -> step 20
    assert f.weeks_of_supply.quantize(Decimal("0.1")) == Decimal("6.5")
    assert f.weeks_of_supply > Decimal("6.0")
    assert (f.stock_on_hand, f.trend, f.listed_days) == (96, "falling", 168)
    assert f.next_delivery is None


def test_pluschhase_is_rising(articles: dict[str, dict]) -> None:
    f = figures(articles["100002"])
    assert (f.sold_7d, f.trend) == (14, "rising")  # avg 13 against 9 (6.8)
    assert f.avg_week_28d == Decimal("11")
    assert f.sell_through_7d.quantize(Decimal("0.01")) == Decimal("0.47")
    assert f.weeks_of_supply.quantize(Decimal("0.1")) == Decimal("8.2")


def test_espresso_without_card_is_inconspicuous(articles: dict[str, dict]) -> None:
    delivery = Delivery(date(2027, 2, 18), 24)
    f = figures(articles["100012"], delivery)
    assert (f.sold_7d, f.trend, f.next_delivery) == (17, "stable", delivery)
    assert f.sell_through_7d.quantize(Decimal("0.01")) == Decimal("0.57")  # >= 0.5


def test_kochbuch_supply(articles: dict[str, dict]) -> None:
    f = figures(articles["100028"])
    assert (f.sold_7d, f.avg_week_28d, f.sell_through_7d) == (0, Decimal(1), Decimal(0))
    assert f.weeks_of_supply == Decimal(14)  # 6.8: Reichweite 14 Wo.


@pytest.mark.parametrize("number", ON_PLAN)
def test_on_plan_articles(articles: dict[str, dict], number: str) -> None:
    f = figures(articles[number])
    assert Decimal("0.95") <= f.sell_through_7d <= Decimal("1.09")  # 6.8
    assert f.trend == "stable"


def test_no_plan_and_no_sales_give_no_ratio(articles: dict[str, dict]) -> None:
    quiet = {**articles["100001"], "w": [0] * 8}
    f = analytics.sales_figures(record(quiet), Decimal(0), daily(quiet), D, None)
    assert (f.sell_through_7d, f.weeks_of_supply, f.trend) == (None, None, "stable")


@pytest.mark.parametrize(("weekly", "expected"), [
    ([0, 0, 0, 0, 20, 20, 23, 23], "rising"),    # 23 >= 1.15 * 20 (edge)
    ([0, 0, 0, 0, 20, 20, 22, 23], "stable"),
    ([0, 0, 0, 0, 20, 20, 17, 17], "falling"),   # 17 <= 0.85 * 20 (edge)
    ([0, 0, 0, 0, 20, 20, 18, 17], "stable"),
    ([0, 0, 0, 0, 0, 0, 1, 0], "rising"),
    ([0] * 8, "stable"),
])
def test_trend_edges(weekly: list[int], expected: str) -> None:
    assert analytics.trend(weekly) == expected


# ----------------------------------------------------------------------------- seasons
def test_season_status() -> None:
    assert analytics.season_status(SEASONS["ostern"], D) == "before"
    assert analytics.season_status(SEASONS["winter"], D) == "running"
    assert analytics.season_status(SEASONS["valentinstag"], D) == "ended"
    assert analytics.season_status(SEASONS["valentinstag"], date(2027, 2, 14)) == "running"
    assert analytics.season_status(SEASONS["ostern"], date(2027, 3, 1)) == "running"


def test_herzpralinen_season_ended(articles: dict[str, dict]) -> None:
    a = articles["100008"]
    f = analytics.season_figures(SEASONS["valentinstag"], D, a["w"], a["stock"])
    assert (f.days_to_end, f.status) == (-2, "ended")
    assert f.avg_day_14d.quantize(Decimal("0.1")) == Decimal("6.4")
    assert (f.projected_units_to_end, f.leftover_units, f.leftover_share) == (0, 46, Decimal(1))


def test_gluehwein_season_running(articles: dict[str, dict]) -> None:
    a = articles["100009"]
    f = analytics.season_figures(SEASONS["winter"], D, a["w"], a["stock"])
    assert (f.days_to_end, f.status, f.projected_units_to_end) == (12, "running", 17)
    assert (f.leftover_units, f.stock_on_hand) == (103, 120)  # 6.8: Rest 103/120
    assert f.leftover_share >= Decimal("0.4")


def test_pluschhase_season_before_easter(articles: dict[str, dict]) -> None:
    a = articles["100002"]
    f = analytics.season_figures(SEASONS["ostern"], D, a["w"], a["stock"])
    assert (f.status, f.days_to_end, f.projected_units_to_end, f.leftover_units) == (
        "before", 40, 74, 16)


def test_season_without_stock_has_no_share() -> None:
    f = analytics.season_figures(SEASONS["winter"], D, [0] * 8, 0)
    assert (f.leftover_units, f.leftover_share) == (0, None)


# ------------------------------------------------------------------------------ prices
ESPRESSO_HISTORY = history(("12.99", at(D - timedelta(days=90)), at(date(2027, 1, 11)), "REGULAR"),
                           ("14.49", at(date(2027, 1, 11)), None, "REGULAR"))
GLUEHWEIN_HISTORY = history(("3.49", at(D - timedelta(days=90)), None, "REGULAR"),
                            ("2.99", at(date(2027, 2, 8), 8), at(date(2027, 2, 21), 20), "PROMO"))


def test_ref30_results_of_6_3() -> None:
    assert analytics.ref30(ESPRESSO_HISTORY, NOW, Decimal("14.49")) == Decimal("14.49")
    assert analytics.ref30(GLUEHWEIN_HISTORY, NOW, Decimal("3.49")) == Decimal("2.99")
    assert analytics.ref30([], NOW, Decimal("9.99")) == Decimal("9.99")


def test_ref30_window_edges() -> None:
    # the 12,99 row ends 2027-01-11 00:00; [t-30d, t] touches it until t = 02-10 00:00
    assert analytics.ref30(ESPRESSO_HISTORY, at(date(2027, 2, 9), 23, 59),
                           Decimal("14.49")) == Decimal("12.99")
    assert analytics.ref30(ESPRESSO_HISTORY, at(date(2027, 2, 10)),
                           Decimal("14.49")) == Decimal("14.49")
    # a row starting after t never counts
    future = history(("1.00", NOW + timedelta(minutes=1), None, "PROMO"))
    assert analytics.ref30(future, NOW, Decimal("3.49")) == Decimal("3.49")


def test_pct_shown_rounds_down() -> None:
    assert analytics.pct_shown(Decimal("9.99"), Decimal("7.99")) == 20
    assert analytics.pct_shown(Decimal("7.99"), Decimal("5.49")) == 31
    assert analytics.pct_shown(Decimal("14.49"), Decimal("12.99")) == 10
    assert analytics.pct_shown(Decimal("3.49"), Decimal("2.99")) == 14
    with pytest.raises(ValueError):
        analytics.pct_shown(Decimal(0), Decimal(1))


def test_margin_of_6_8() -> None:
    assert analytics.margin_pct(Decimal("9.99"), Decimal(19), Decimal("5.20")).quantize(
        Decimal("0.1")) == Decimal("38.1")
    assert analytics.margin_pct(Decimal("7.99"), Decimal(19), Decimal("5.20")).quantize(
        Decimal("0.1")) == Decimal("22.6")
    assert analytics.margin_pct(Decimal("5.49"), Decimal(7), Decimal("3.10")).quantize(
        Decimal("0.1")) == Decimal("39.6")


def test_regular_quote_uses_history_ref30(articles: dict[str, dict]) -> None:
    q = analytics.quote(record(articles["100012"]), [], ESPRESSO_HISTORY, NOW)
    assert (q.price, q.regular_price, q.source, q.action) == (
        Decimal("14.49"), Decimal("14.49"), "REGULAR", None)
    assert (q.ref30, q.pct_shown) == (Decimal("14.49"), 0)


def test_central_action_quote(articles: dict[str, dict]) -> None:
    central = PriceAction("PA-SEED-100009", "100009", "101", "CENTRAL", Decimal("3.49"),
                          Decimal("2.99"), 14, Decimal("3.49"), at(date(2027, 2, 8), 8),
                          at(date(2027, 2, 21), 20), "", "REASON_CODE_CENTRAL_PROMOTION",
                          "zentrale", "")
    q = analytics.quote(record(articles["100009"]), [central], GLUEHWEIN_HISTORY, NOW)
    assert (q.price, q.source, q.action) == (Decimal("2.99"), "CENTRAL_ACTION", central)
    # ref30 is the 30-day low of the history (6.3: Glühwein 2,99 on 16.02.); the shown
    # reduction stays the one the action was started with (14 % against 3,49)
    assert (q.ref30, q.pct_shown) == (Decimal("2.99"), 14)
    after = analytics.quote(record(articles["100009"]), [central], GLUEHWEIN_HISTORY,
                            at(date(2027, 2, 21), 20))
    assert (after.price, after.source) == (Decimal("3.49"), "REGULAR")


def test_booth_action_from_business_date_midnight(articles: dict[str, dict]) -> None:
    ente = record(articles["100001"])
    action = booth()
    cases = {
        at(D): (Decimal("7.99"), "BOOTH_ACTION"),
        at(D) - timedelta(seconds=1): (Decimal("9.99"), "REGULAR"),
        NOW: (Decimal("7.99"), "BOOTH_ACTION"),
        at(date(2027, 2, 23), 19, 59): (Decimal("7.99"), "BOOTH_ACTION"),
        at(date(2027, 2, 23), 20): (Decimal("9.99"), "REGULAR"),  # valid_to exclusive
    }
    for when, expected in cases.items():
        q = analytics.quote(ente, [action], [], when)
        assert (q.price, q.source) == expected, when
    q = analytics.quote(ente, [action], [], NOW)
    assert (q.ref30, q.pct_shown, q.action) == (Decimal("9.99"), 20, action)


def test_expired_or_ended_actions_do_not_count(articles: dict[str, dict]) -> None:
    ente = record(articles["100001"])
    expired = booth(valid_from=at(D - timedelta(days=8)), valid_to=at(D - timedelta(days=1), 20))
    ended = booth(ended=NOW - timedelta(hours=1))
    other_article = booth(article="100004", price="1.49")
    for action in (expired, ended, other_article):
        assert analytics.quote(ente, [action], [], NOW).source == "REGULAR"


def test_last_price_change_of_espresso() -> None:
    change = analytics.last_price_change(ESPRESSO_HISTORY, NOW, TZ)
    assert change == analytics.PriceChange(date(2027, 1, 11), Decimal("12.99"),
                                           Decimal("14.49"))
    assert analytics.last_price_change(ESPRESSO_HISTORY, at(date(2027, 1, 10)), TZ) is None
    assert analytics.last_price_change(GLUEHWEIN_HISTORY, NOW, TZ) is None  # PROMO ignored
