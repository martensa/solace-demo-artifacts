"""Shapes of gpos-wws answers (UC1-BUILD-SPEC 4.3, 8.4): pure functions, no I/O.

* ``*_doc``: proto3 JSON (field names as in the proto) of the ``showcase.wws.v1``
  answers; the service parses them strictly into messages.
* ``agent_*``: the compact JSON of the agent tools ``get_article``,
  ``get_sales_performance`` and ``get_season_info`` (8.4 examples): German price labels
  (``"9,99"``), ISO dates, ratios as JSON numbers.

``BDecimal`` scales: money 2, ``net_quantity`` 3, ``vat_percent`` 2, ``margin_percent``
1, ``plan_7d`` and ``avg_week_28d`` 2; the unbounded ratios ``sell_through_7d``,
``weeks_of_supply``, ``avg_day_14d`` and ``leftover_share`` 4, so a caller can apply
thresholds (6.6) without rounding effects. Agent JSON rounds like the 8.4 examples.
"""

from __future__ import annotations

from datetime import datetime, tzinfo
from decimal import Decimal
from typing import Any

from gposdemo.common.clock import offset_ts_json
from gposdemo.common.fmt import dt_label, eur
from gposdemo.common.money import quantize, to_bdecimal, to_money

from .analytics import (ArticleRecord, HistoryEntry, PriceChange, PriceQuote, SalesFigures,
                        Season, SeasonFigures)

RATIO_SCALE = 4
SOURCE_ENUM = {"REGULAR": "PRICE_SOURCE_REGULAR", "CENTRAL_ACTION": "PRICE_SOURCE_CENTRAL_ACTION",
               "BOOTH_ACTION": "PRICE_SOURCE_BOOTH_ACTION"}


def _ots(value: datetime, tz: tzinfo) -> dict[str, Any]:
    return offset_ts_json(value.astimezone(tz))


def _ratio(value: Decimal | None) -> dict[str, Any] | None:
    return None if value is None else to_bdecimal(value, RATIO_SCALE)


def _drop_none(doc: dict[str, Any]) -> dict[str, Any]:
    """Unset optional message fields (``None``) are left out of the proto3 JSON."""
    return {k: v for k, v in doc.items() if v is not None}


def _float(value: Decimal, places: int) -> float:
    """Agent figure rounded half up to ``places`` (``1.0``, ``0.26``, ``6.5``)."""
    return float(quantize(value, places))


def _optional_float(value: Decimal | None, places: int) -> float | None:
    return None if value is None else _float(value, places)


def _count(value: Decimal) -> int | float:
    """A planned quantity: ``35`` for ``35.00``, else two places."""
    rounded = quantize(value, 2)
    return int(rounded) if rounded == rounded.to_integral_value() else float(rounded)


# ------------------------------------------------------------------------ proto3 JSON
def effective_price_doc(article_number: str, store_id: str, q: PriceQuote,
                        tz: tzinfo) -> dict[str, Any]:
    """``datatype.EffectivePrice``."""
    return _drop_none({
        "article_number": article_number,
        "store_id": store_id,
        "price": to_money(q.price),
        "regular_price": to_money(q.regular_price),
        "source": SOURCE_ENUM[q.source],
        "action_id": q.action.action_id if q.action else "",
        "valid_to": _ots(q.action.valid_to, tz) if q.action else None,
        "ref30": to_money(q.ref30),
        "pct_shown": q.pct_shown,
    })


def article_doc(a: ArticleRecord, q: PriceQuote, margin: Decimal, change: PriceChange | None,
                tz: tzinfo) -> dict[str, Any]:
    """``datatype.Article`` with the effective price of the request's store."""
    return _drop_none({
        "article_number": a.article_number,
        "article_id": a.article_id,
        "gtin": a.gtin,
        "name": a.name,
        "category": a.category,
        "category_label": a.category_label,
        "pack_label": a.pack_label,
        "net_quantity": to_bdecimal(a.net_quantity, 3),
        "base_unit": a.base_unit,
        "vat_percent": to_bdecimal(a.vat_pct, 2),
        "cost_net": to_money(a.cost_net),
        "price_bound": a.price_bound,
        "season_code": a.season_code,
        "listed_since": a.listed_since.isoformat(),
        "price": effective_price_doc(a.article_number, a.store_id, q, tz),
        "stock_on_hand": a.stock_on_hand,
        "margin_percent": to_bdecimal(margin, 1),
        "last_price_change": None if change is None else {
            "date": change.on.isoformat(), "old_price": to_money(change.old_price),
            "new_price": to_money(change.new_price)},
    })


def sales_doc(article_number: str, store_id: str, f: SalesFigures) -> dict[str, Any]:
    """``datatype.SalesPerformance``."""
    return _drop_none({
        "article_number": article_number,
        "store_id": store_id,
        "as_of": f.as_of.isoformat(),
        "sold_7d": f.sold_7d,
        "plan_7d": to_bdecimal(f.plan_7d, 2),
        "sell_through_7d": _ratio(f.sell_through_7d),
        "weekly_units": list(f.weekly_units),
        "avg_week_28d": to_bdecimal(f.avg_week_28d, 2),
        "stock_on_hand": f.stock_on_hand,
        "weeks_of_supply": _ratio(f.weeks_of_supply),
        "trend": f.trend,
        "listed_days": f.listed_days,
        "next_delivery": None if f.next_delivery is None else {
            "expected_on": f.next_delivery.expected_on.isoformat(),
            "quantity": f.next_delivery.quantity},
    })


def season_doc(article_number: str, f: SeasonFigures | None) -> dict[str, Any]:
    """``datatype.SeasonInfo``; without a season only ``status`` ``none``."""
    if f is None:
        return {"article_number": article_number, "status": "none"}
    return _drop_none({
        "article_number": article_number,
        "season_code": f.season.code,
        "season_label": f.season.label,
        "start_date": f.season.start.isoformat(),
        "end_date": f.season.end.isoformat(),
        "days_to_end": f.days_to_end,
        "status": f.status,
        "avg_day_14d": _ratio(f.avg_day_14d),
        "projected_units_to_end": f.projected_units_to_end,
        "stock_on_hand": f.stock_on_hand,
        "leftover_units": f.leftover_units,
        "leftover_share": _ratio(f.leftover_share),
    })


def history_doc(article_number: str, store_id: str, entries: list[HistoryEntry],
                ref30: Decimal, tz: tzinfo) -> dict[str, Any]:
    """``datatype.PriceHistory`` (never contains booth actions)."""
    return {
        "article_number": article_number,
        "store_id": store_id,
        "entries": [_drop_none({
            "price": to_money(e.price),
            "valid_from": _ots(e.valid_from, tz),
            "valid_to": _ots(e.valid_to, tz) if e.valid_to else None,
            "kind": e.kind}) for e in entries],
        "ref30": to_money(ref30),
    }


# ------------------------------------------------------------------------- agent JSON
def agent_article(a: ArticleRecord, q: PriceQuote, margin: Decimal,
                  change: PriceChange | None, season: Season | None,
                  tz: tzinfo) -> dict[str, Any]:
    """Text of ``get_article`` (8.4)."""
    action = None if q.action is None else {
        "action_id": q.action.action_id, "kind": q.action.kind,
        "price": eur(q.action.action_price),
        "valid_to": dt_label(q.action.valid_to.astimezone(tz))}
    return {
        "article_number": a.article_number,
        "name": a.name,
        "category": a.category_label,
        "pack": a.pack_label,
        "price": eur(q.price),
        "regular_price": eur(q.regular_price),
        "price_source": q.source,
        "action": action,
        "ref30": eur(q.ref30),
        "margin_pct": _float(margin, 1),
        "stock": a.stock_on_hand,
        "season": season.label if season else None,
        "price_bound": a.price_bound,
        "last_price_change": None if change is None else {
            "date": change.on.isoformat(), "from": eur(change.old_price),
            "to": eur(change.new_price)},
        "listed_since": a.listed_since.isoformat(),
    }


def agent_sales(article_number: str, f: SalesFigures) -> dict[str, Any]:
    """Text of ``get_sales_performance`` (8.4)."""
    return {
        "article_number": article_number,
        "as_of": f.as_of.isoformat(),
        "sold_7d": f.sold_7d,
        "plan_7d": _count(f.plan_7d),
        "sell_through_7d": _optional_float(f.sell_through_7d, 2),
        "weekly_units": list(f.weekly_units),
        "avg_week_28d": _float(f.avg_week_28d, 2),
        "stock": f.stock_on_hand,
        "weeks_of_supply": _optional_float(f.weeks_of_supply, 1),
        "trend": f.trend,
        "next_delivery": None if f.next_delivery is None else {
            "expected_on": f.next_delivery.expected_on.isoformat(),
            "quantity": f.next_delivery.quantity},
    }


def agent_season(article_number: str, f: SeasonFigures | None) -> dict[str, Any]:
    """Text of ``get_season_info`` (8.4); ``{"article_number", "status": "none"}``
    without a season."""
    if f is None:
        return {"article_number": article_number, "status": "none"}
    return {
        "article_number": article_number,
        "season": f.season.label,
        "start": f.season.start.isoformat(),
        "end": f.season.end.isoformat(),
        "days_to_end": f.days_to_end,
        "status": f.status,
        "avg_day_14d": _float(f.avg_day_14d, 1),
        "projected_units_to_end": f.projected_units_to_end,
        "stock": f.stock_on_hand,
        "leftover_units": f.leftover_units,
        "leftover_share": _optional_float(f.leftover_share, 2),
    }
