"""Deterministic signals, blocks and steps of one article (UC1-BUILD-SPEC 6.6, 6.7).

All figures are recomputed from the raw WWS and loyalty answers (weekly units, plan,
stock, dates), so the thresholds of the policy always see exact ``Decimal`` values:

* ``sell_through`` = ``sold_7d / plan_7d``; ``avg_week_28d`` = mean of the last 4 weeks;
  ``weeks_of_supply`` = stock / ``avg_week_28d``; ``listed_days`` = D - listed;
  ``avg_day_14d`` = (last 2 weeks) / 14; ``days_to_end`` = season end - D.
* Cardholder drop = mean of the last 4 weeks against the 4 weeks before, in percent.

Blocks (price-bound, open action, no allowed step) apply to candidates only; the scan
insight shows price-bound and open actions for every article.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from . import pricing, texts
from .clients import ArticleFacts, BehaviourFacts, SalesFacts, SeasonFacts
from .policy import Policy

SEVERITY = {"slow_seller": "high", "season_end": "high", "customer_behaviour": "high",
            "excluded": "blocked", "action": "blocked", "on_plan": "ok", "neutral": "info"}
WITHIN_DAYS = 7  # policy key suggested_step.season_end.within_7_days


@dataclass(frozen=True)
class Metrics:
    """Figures behind the signals (stored in ``engine.insight.facts``)."""

    sold_7d: int = 0
    plan_7d: Decimal = Decimal(0)
    sell_through: Decimal | None = None
    avg_week_28d: Decimal | None = None
    weeks_of_supply: Decimal | None = None
    stock: int = 0
    listed_days: int = 0
    days_to_end: int | None = None
    leftover_share: Decimal | None = None
    overdue_factor: Decimal | None = None
    cardholder_drop_pct: Decimal | None = None
    prior_weekly: Decimal | None = None

    def as_json(self) -> dict[str, Any]:
        """JSON-safe view (Decimals as strings, rounded to 4 places)."""
        out: dict[str, Any] = {}
        for key, value in self.__dict__.items():
            if isinstance(value, Decimal):
                out[key] = f"{value.quantize(Decimal('0.0001')).normalize():f}"
            else:
                out[key] = value
        return out


@dataclass(frozen=True)
class Assessment:
    """Result of :func:`evaluate` for one article."""

    article_number: str
    name: str
    signals: tuple[str, ...] = ()
    facts: dict[str, str] = field(default_factory=dict)
    blocked: str = ""
    max_step_pct: int = 0
    suggested_step_pct: int = 0
    insight_code: str = "neutral"
    insight_text: str = texts.NEUTRAL
    line_facts: str = texts.NEUTRAL
    stock_value: Decimal = Decimal(0)
    metrics: Metrics = field(default_factory=Metrics)

    @property
    def candidate(self) -> bool:
        """At least one signal fired (blocked candidates stay candidates)."""
        return bool(self.signals)

    @property
    def free(self) -> bool:
        """Candidate without block: may go to the agent."""
        return self.candidate and not self.blocked

    @property
    def severity(self) -> str:
        return SEVERITY.get(self.insight_code, "info")


def _mean(values: tuple[int, ...]) -> Decimal | None:
    return Decimal(sum(values)) / len(values) if values else None


def _metrics(article: ArticleFacts, sales: SalesFacts, demo_date: date) -> Metrics:
    plan = sales.plan_7d
    avg = _mean(sales.weekly_units[-4:])
    listed = (demo_date - article.listed_since).days if article.listed_since else 0
    return Metrics(
        sold_7d=sales.sold_7d, plan_7d=plan,
        sell_through=Decimal(sales.sold_7d) / plan if plan > 0 else None,
        avg_week_28d=avg,
        weeks_of_supply=Decimal(article.stock) / avg if avg else None,
        stock=article.stock, listed_days=listed)


def _slow_seller(m: Metrics, policy: Policy) -> int:
    """Suggested step when ``slow_seller`` fires, else 0."""
    rule = policy.slow_seller
    if m.sell_through is None or m.sell_through >= rule.max_sell_through:
        return 0
    covered = m.weeks_of_supply is None or m.weeks_of_supply > rule.min_weeks_of_supply
    if not covered or m.stock <= 0 or m.listed_days < rule.min_listed_days:
        return 0
    strong = m.sell_through < rule.strong_sell_through
    return policy.steps.slow_seller_strong if strong else policy.steps.slow_seller_default


def _season_end(m: Metrics, season: SeasonFacts | None, weekly: tuple[int, ...],
                demo_date: date, policy: Policy) -> tuple[int, Metrics]:
    """Suggested step when ``season_end`` fires (else 0) and the metrics with season data."""
    if season is None or season.start > demo_date:
        return 0, m
    days = (season.end - demo_date).days
    m = _replace(m, days_to_end=days)
    if days < 0:
        return (policy.steps.season_end_ended if m.stock > 0 else 0), m
    if days > policy.season_end.window_days or m.stock <= 0:
        return 0, m
    avg_day = Decimal(sum(weekly[-2:])) / 14
    share = (Decimal(m.stock) - avg_day * days) / m.stock
    m = _replace(m, leftover_share=share)
    if share < policy.season_end.min_leftover_share:
        return 0, m
    if days <= WITHIN_DAYS:
        return policy.steps.season_end_within_7_days, m
    return policy.steps.season_end_default, m


def _customer_behaviour(m: Metrics, behaviour: BehaviourFacts | None,
                        policy: Policy) -> tuple[int, Metrics]:
    """Suggested step when ``customer_behaviour`` fires (else 0) and the metrics."""
    rule = policy.customer_behaviour
    if behaviour is None or not behaviour.consent_profiling:
        return 0, m
    weekly = behaviour.cardholder_weekly
    if len(weekly) < 8 or sum(weekly[-8:-4]) <= 0:
        return 0, m
    prior, last = Decimal(sum(weekly[-8:-4])) / 4, Decimal(sum(weekly[-4:])) / 4
    drop = (prior - last) / prior * 100
    m = _replace(m, prior_weekly=prior, cardholder_drop_pct=drop)
    if behaviour.median_interval_days <= 0 or behaviour.days_since_last < 0:
        return 0, m
    factor = Decimal(behaviour.days_since_last) / behaviour.median_interval_days
    m = _replace(m, overdue_factor=factor)
    fires = (behaviour.member_purchases_8w >= rule.min_member_buys_8w
             and factor >= rule.min_overdue_factor and prior >= rule.min_prior_weekly
             and drop >= rule.min_cardholder_drop_pct)
    return (policy.steps.customer_behaviour if fires else 0), m


def _replace(m: Metrics, **changes: Any) -> Metrics:
    return Metrics(**{**m.__dict__, **changes})


def _facts(signal: str, m: Metrics, season: SeasonFacts | None,
           behaviour: BehaviourFacts | None) -> str:
    if signal == "slow_seller":
        return texts.slow_seller_facts(m.sold_7d, m.plan_7d, m.weeks_of_supply, m.stock)
    if signal == "season_end" and season is not None and m.days_to_end is not None:
        return texts.season_end_facts(season.label, season.end, m.days_to_end, m.stock)
    if signal == "customer_behaviour" and behaviour is not None:
        return texts.customer_behaviour_facts(behaviour.days_since_last,
                                              behaviour.median_interval_days,
                                              m.cardholder_drop_pct or Decimal(0))
    raise ValueError(f"no facts for signal {signal}")


def _block(article: ArticleFacts, max_step: int) -> str:
    if article.price_bound:
        return texts.BLOCK_PRICE_BOUND
    if article.price.action_open:
        return texts.action_block(article.price.source, article.price.valid_to)
    if max_step == 0:
        return texts.BLOCK_MIN_MARGIN
    return ""


def _insight(article: ArticleFacts, signals: tuple[str, ...], facts: dict[str, str],
             m: Metrics, policy: Policy) -> tuple[str, str]:
    if article.price_bound:
        return "excluded", texts.INSIGHT_EXCLUDED
    if article.price.action_open:
        return "action", texts.action_insight(article.price.source, article.price.valid_to)
    if signals:
        return signals[0], texts.signal_insight(signals[0], facts[signals[0]])
    if m.sell_through is not None and m.sell_through >= policy.on_plan_min_sell_through:
        return "on_plan", texts.on_plan_facts(m.sold_7d, m.plan_7d)
    return "neutral", texts.NEUTRAL


def evaluate(article: ArticleFacts, sales: SalesFacts, season: SeasonFacts | None,
             behaviour: BehaviourFacts | None, policy: Policy,
             demo_date: date) -> Assessment:
    """Signals, facts, blocks, steps and scan insight of one article on business date
    ``demo_date``. ``behaviour`` is ``None`` without a card at the basket."""
    m = _metrics(article, sales, demo_date)
    steps: dict[str, int] = {}
    if step := _slow_seller(m, policy):
        steps["slow_seller"] = step
    step, m = _season_end(m, season, sales.weekly_units, demo_date, policy)
    if step:
        steps["season_end"] = step
    step, m = _customer_behaviour(m, behaviour, policy)
    if step:
        steps["customer_behaviour"] = step
    signals = tuple(sorted(steps, key=policy.priority))
    facts = {s: _facts(s, m, season, behaviour) for s in signals}
    options = pricing.step_options(article.price.regular_price, article.cost_net,
                                   article.vat_percent, policy)
    max_step = pricing.max_step(options)
    suggested = min(steps[signals[0]], max_step) if signals else 0
    code, insight = _insight(article, signals, facts, m, policy)
    if signals:
        line_facts = "; ".join(facts[s] for s in signals)
    elif code == "on_plan":
        line_facts = insight
    else:
        line_facts = texts.neutral_facts(m.sold_7d, m.plan_7d)
    return Assessment(
        article_number=article.article_number, name=article.name, signals=signals,
        facts=facts, blocked=_block(article, max_step) if signals else "",
        max_step_pct=max_step, suggested_step_pct=suggested, insight_code=code,
        insight_text=insight, line_facts=line_facts,
        stock_value=article.cost_net * article.stock, metrics=m)
