"""Pure merchandise analytics of gpos-wws (UC1-BUILD-SPEC 4.3, 5.4, 6.3, 6.6).

No I/O and no clock: :mod:`.store` reads the rows, the caller passes business time
(``demo_now()``) and the business date ``D``. All figures are unrounded ``Decimal``;
rounding happens only when a figure is written (:mod:`.views`).

* Effective price at business time ``t``: the open action with
  ``valid_from <= t < valid_to``, else the regular price of the store (5.4).
* ``ref30``: lowest price of all ``price_history`` rows overlapping
  ``[t - 30 days, t]`` (6.3, PAngV). The history never holds booth actions, so they
  never count (named demo simplification, 4.3, 10.4).
* Sales windows: 8 windows of 7 days ending yesterday (``[D-56, D-1]``), oldest
  first; the last one is ``sold_7d`` (6.6).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

WEEKS = 8
DAYS_PER_WEEK = 7
REF30_DAYS = 30
RECENT_WEEKS = 4  # avg_week_28d = mean of the last 4 weeks
TREND_RISING = Decimal("1.15")
TREND_FALLING = Decimal("0.85")
HUNDRED = Decimal(100)

SOURCE_REGULAR = "REGULAR"
SOURCE_BY_KIND = {"CENTRAL": "CENTRAL_ACTION", "BOOTH": "BOOTH_ACTION"}


@dataclass(frozen=True)
class ArticleRecord:
    """Master data of one article plus its regular price and stock in one store."""

    article_number: str
    article_id: str
    gtin: str
    name: str
    category: str
    category_label: str
    pack_label: str
    net_quantity: Decimal
    base_unit: str
    vat_pct: Decimal
    cost_net: Decimal
    price_bound: bool
    season_code: str  # "" = no seasonal article
    listed_since: date
    store_id: str
    regular_price: Decimal
    stock_on_hand: int


@dataclass(frozen=True)
class PriceAction:
    """One row of ``wws.price_action`` (times are business time)."""

    action_id: str
    article_number: str
    store_id: str
    kind: str  # CENTRAL | BOOTH
    regular_price: Decimal
    action_price: Decimal
    pct_shown: int
    ref30: Decimal
    valid_from: datetime
    valid_to: datetime
    proposal_id: str  # "" for CENTRAL
    reason_code: str  # enum name, e.g. REASON_CODE_SLOW_SELLER
    originator: str
    approver: str  # "" for CENTRAL
    ended_at: datetime | None = None
    end_reason: str = ""

    @property
    def is_open(self) -> bool:
        """Not ended (5.4: at most one open action per article and store)."""
        return self.ended_at is None

    def effective_at(self, at: datetime) -> bool:
        """Open and ``valid_from <= at < valid_to``."""
        return self.is_open and self.valid_from <= at < self.valid_to

    @property
    def source(self) -> str:
        """``CENTRAL_ACTION`` or ``BOOTH_ACTION``."""
        return SOURCE_BY_KIND[self.kind]


@dataclass(frozen=True)
class HistoryEntry:
    """One row of ``wws.price_history`` (``REGULAR`` or ``PROMO``)."""

    price: Decimal
    valid_from: datetime
    valid_to: datetime | None
    kind: str

    def overlaps(self, start: datetime, end: datetime) -> bool:
        """True when ``[valid_from, valid_to)`` meets the closed window ``[start, end]``."""
        return self.valid_from <= end and (self.valid_to is None or self.valid_to > start)


@dataclass(frozen=True)
class Season:
    """One row of ``wws.season``."""

    code: str
    label: str
    start: date
    end: date


@dataclass(frozen=True)
class Delivery:
    """Next inbound delivery of an article."""

    expected_on: date
    quantity: int


@dataclass(frozen=True)
class PriceQuote:
    """What the POS charges at one business time, with the PAngV reference."""

    price: Decimal
    regular_price: Decimal
    source: str  # REGULAR | CENTRAL_ACTION | BOOTH_ACTION
    action: PriceAction | None
    ref30: Decimal
    pct_shown: int


@dataclass(frozen=True)
class PriceChange:
    """Last change of the regular price (6.7 step 8)."""

    on: date
    old_price: Decimal
    new_price: Decimal


@dataclass(frozen=True)
class SalesFigures:
    """Sales against plan of one article in one store (4.3 ``SalesPerformance``)."""

    as_of: date
    sold_7d: int
    plan_7d: Decimal
    sell_through_7d: Decimal | None  # None without a plan
    weekly_units: tuple[int, ...]
    avg_week_28d: Decimal
    stock_on_hand: int
    weeks_of_supply: Decimal | None  # None without sales in the last 4 weeks
    trend: str
    listed_days: int
    next_delivery: Delivery | None


@dataclass(frozen=True)
class SeasonFigures:
    """Season status of one seasonal article (4.3 ``SeasonInfo``)."""

    season: Season
    days_to_end: int
    status: str  # before | running | ended
    avg_day_14d: Decimal
    projected_units_to_end: int
    stock_on_hand: int
    leftover_units: int
    leftover_share: Decimal | None  # None without stock


def round_half_up(value: Decimal) -> int:
    """Commercial rounding to an integer."""
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


# ----------------------------------------------------------------------------- prices
def ref30(history: Iterable[HistoryEntry], at: datetime, fallback: Decimal) -> Decimal:
    """Lowest price of the rows overlapping ``[at - 30 days, at]``; ``fallback`` (the
    regular price) when no row overlaps."""
    start = at - timedelta(days=REF30_DAYS)
    prices = [h.price for h in history if h.overlaps(start, at)]
    return min(prices) if prices else fallback


def pct_shown(reference: Decimal, price: Decimal) -> int:
    """Shown reduction against ``reference``, rounded down (6.7 step 4)."""
    if reference <= 0:
        raise ValueError("reference price must be positive")
    return int(((reference - price) / reference * HUNDRED).to_integral_value(
        rounding=ROUND_FLOOR))


def effective_action(actions: Iterable[PriceAction], article_number: str,
                     at: datetime) -> PriceAction | None:
    """The open action of ``article_number`` that is effective at ``at``."""
    return next((a for a in actions
                 if a.article_number == article_number and a.effective_at(at)), None)


def quote(article: ArticleRecord, actions: Iterable[PriceAction],
          history: Iterable[HistoryEntry], at: datetime) -> PriceQuote:
    """Effective price at ``at`` (5.4).

    ``ref30`` is always the 30-day low of the history at ``at`` (6.3: Glühwein 2,99 on
    16.02. while its central action runs; booth actions are never in the history).
    ``pct_shown`` is 0 for the regular price, else the reduction the action shows as it
    was approved (central seed 14 % against the 3,49 before the action, 6.3).
    """
    action = effective_action(actions, article.article_number, at)
    low = ref30(history, at, article.regular_price)
    if action is None:
        return PriceQuote(article.regular_price, article.regular_price, SOURCE_REGULAR, None,
                          low, 0)
    return PriceQuote(action.action_price, article.regular_price, action.source, action,
                      low, action.pct_shown)


def margin_pct(price: Decimal, vat_pct: Decimal, cost_net: Decimal) -> Decimal:
    """Net margin in percent at gross ``price``: ``(p/(1+vat) - cost) / (p/(1+vat))``."""
    if price <= 0:
        raise ValueError("price must be positive")
    net = price / (1 + vat_pct / HUNDRED)
    return (net - cost_net) / net * HUNDRED


def last_price_change(history: Iterable[HistoryEntry], at: datetime,
                      tz: tzinfo) -> PriceChange | None:
    """Last change of the regular price that took effect at or before ``at``.

    Consecutive ``REGULAR`` rows with different prices; the date is the business date
    of the newer row's ``valid_from`` in ``tz``.
    """
    regular = sorted((h for h in history if h.kind == "REGULAR" and h.valid_from <= at),
                     key=lambda h: h.valid_from)
    change: PriceChange | None = None
    for older, newer in zip(regular, regular[1:]):
        if newer.price != older.price:
            change = PriceChange(newer.valid_from.astimezone(tz).date(), older.price,
                                 newer.price)
    return change


# ------------------------------------------------------------------------------ sales
def week_windows(today: date) -> list[tuple[date, date]]:
    """The 8 windows ``[start, end]`` of 7 days ending yesterday, oldest first."""
    first = today - timedelta(days=WEEKS * DAYS_PER_WEEK)
    return [(first + timedelta(days=DAYS_PER_WEEK * k),
             first + timedelta(days=DAYS_PER_WEEK * (k + 1) - 1)) for k in range(WEEKS)]


def weekly_units(daily: Iterable[tuple[date, int]], today: date) -> tuple[int, ...]:
    """Units per window of :func:`week_windows`; days outside ``[D-56, D-1]`` are ignored."""
    windows = week_windows(today)
    sums = [0] * WEEKS
    for day, units in daily:
        for k, (start, end) in enumerate(windows):
            if start <= day <= end:
                sums[k] += units
                break
    return tuple(sums)


def trend(weekly: Sequence[int]) -> str:
    """``rising`` if avg(last 2 weeks) >= 1.15 * avg(2 weeks before), ``falling`` if
    <= 0.85 *, else ``stable`` (4.3); equal averages (also 0 and 0) are ``stable``."""
    if len(weekly) < RECENT_WEEKS:
        raise ValueError(f"trend needs {RECENT_WEEKS} weeks, got {len(weekly)}")
    recent = Decimal(weekly[-1] + weekly[-2]) / 2
    prior = Decimal(weekly[-3] + weekly[-4]) / 2
    if recent == prior:
        return "stable"
    if recent >= TREND_RISING * prior:
        return "rising"
    if recent <= TREND_FALLING * prior:
        return "falling"
    return "stable"


def sales_figures(article: ArticleRecord, plan_week: Decimal,
                  daily: Iterable[tuple[date, int]], today: date,
                  next_delivery: Delivery | None) -> SalesFigures:
    """Key figures of 6.6 for one article; ``today`` is the business date ``D``."""
    weekly = weekly_units(daily, today)
    sold = weekly[-1]
    avg_28 = Decimal(sum(weekly[-RECENT_WEEKS:])) / RECENT_WEEKS
    return SalesFigures(
        as_of=today - timedelta(days=1),
        sold_7d=sold,
        plan_7d=plan_week,
        sell_through_7d=Decimal(sold) / plan_week if plan_week > 0 else None,
        weekly_units=weekly,
        avg_week_28d=avg_28,
        stock_on_hand=article.stock_on_hand,
        weeks_of_supply=Decimal(article.stock_on_hand) / avg_28 if avg_28 > 0 else None,
        trend=trend(weekly),
        listed_days=(today - article.listed_since).days,
        next_delivery=next_delivery,
    )


# ----------------------------------------------------------------------------- season
def season_status(season: Season, today: date) -> str:
    """``before`` (D < start), ``ended`` (D > end) or ``running``."""
    if today < season.start:
        return "before"
    if today > season.end:
        return "ended"
    return "running"


def season_figures(season: Season, today: date, weekly: Sequence[int],
                   stock_on_hand: int) -> SeasonFigures:
    """Season status, sales rate of the last 14 days and projected leftover stock.

    ``avg_day_14d = (w7 + w8) / 14``; projected sales until the season end =
    ``avg_day_14d * max(days_to_end, 0)``, rounded half up (0 once the season ended);
    ``leftover = max(stock - projected, 0)``, ``leftover_share = leftover / stock``.
    """
    days_to_end = (season.end - today).days
    avg_day = Decimal(weekly[-1] + weekly[-2]) / (2 * DAYS_PER_WEEK)
    projected = round_half_up(avg_day * max(days_to_end, 0))
    leftover = max(stock_on_hand - projected, 0)
    return SeasonFigures(
        season=season,
        days_to_end=days_to_end,
        status=season_status(season, today),
        avg_day_14d=avg_day,
        projected_units_to_end=projected,
        stock_on_hand=stock_on_hand,
        leftover_units=leftover,
        leftover_share=Decimal(leftover) / stock_on_hand if stock_on_hand > 0 else None,
    )
