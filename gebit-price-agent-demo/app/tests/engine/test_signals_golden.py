"""Signals, blocks, steps and prices: every row of the golden values (6.8) on 2027-02-16.

The facts come from ``data/*.yaml`` through the Showcase protos and the engine's own
gRPC converters, so the numbers here are exactly what the engine sees in the lab.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import pytest

from gposdemo.engine import pricing, signals
from gposdemo.engine.policy import Policy
from gposdemo.engine.signals import Assessment
from tests.engine.fakes import (
    CREMA,
    CROISSANTS,
    ENTE,
    ESPRESSO,
    GLUEHWEIN,
    HASE,
    KOCHBUCH,
    PRALINEN,
    D,
    Facts,
)

CANDIDATE_ARTICLES = {ENTE, HASE, PRALINEN, GLUEHWEIN, KOCHBUCH}


def rounded(value: Decimal | None, places: int) -> Decimal:
    """``value`` rounded half even like ``round`` (fails when the metric is missing)."""
    assert value is not None
    return round(value, places)


def assess(get_facts: Callable[..., Facts], policy: Policy, number: str,
           membership_id: str | None = None) -> Assessment:
    f = get_facts(number, membership_id=membership_id)
    return signals.evaluate(f.article, f.sales, f.season, f.behaviour, policy, D)


def options(get_facts: Callable[..., Facts], policy: Policy,
            number: str) -> dict[int, pricing.StepOption]:
    a = get_facts(number).article
    return {o.step: o for o in pricing.step_options(a.price.regular_price, a.cost_net,
                                                    a.vat_percent, policy)}


def test_ente_slow_seller(get_facts: Callable[..., Facts], policy: Policy) -> None:
    a = assess(get_facts, policy, ENTE)
    m = a.metrics
    assert a.signals == ("slow_seller",)
    assert rounded(m.sell_through, 2) == Decimal("0.26")
    assert (m.sold_7d, m.plan_7d, m.avg_week_28d, m.stock) == (9, 35, Decimal("14.75"), 96)
    assert rounded(m.weeks_of_supply, 1) == Decimal("6.5")
    assert (a.max_step_pct, a.suggested_step_pct, a.blocked) == (20, 20, "")
    assert a.facts["slow_seller"] == ("9 von 35 geplanten Stück verkauft (7 Tage), "
                                      "Reichweite 6,5 Wochen, Bestand 96")
    assert (a.insight_code, a.severity) == ("slow_seller", "high")
    assert a.insight_text == ("Ladenhüter: 9 von 35 geplanten Stück verkauft (7 Tage), "
                              "Reichweite 6,5 Wochen, Bestand 96")
    steps = options(get_facts, policy, ENTE)
    assert (steps[20].price, rounded(steps[20].margin_pct, 1), steps[20].allowed) == (
        Decimal("7.99"), Decimal("22.6"), True)
    assert (steps[30].price, rounded(steps[30].margin_pct, 1), steps[30].allowed) == (
        Decimal("6.99"), Decimal("11.5"), False)
    ref30 = get_facts(ENTE).article.price.ref30
    assert ref30 == Decimal("9.99") and pricing.pct_shown(ref30, Decimal("7.99")) == 20


def test_herzpralinen_season_end(get_facts: Callable[..., Facts], policy: Policy) -> None:
    a = assess(get_facts, policy, PRALINEN)
    assert a.signals == ("season_end",)
    assert (a.metrics.days_to_end, a.metrics.stock) == (-2, 46)
    assert (a.max_step_pct, a.suggested_step_pct) == (30, 30)
    assert a.facts["season_end"] == "Saison Valentinstag endete am 14.02., Restbestand 46"
    f = get_facts(PRALINEN).article
    step = options(get_facts, policy, PRALINEN)[30]
    assert step.price == Decimal("5.49") and rounded(step.margin_pct, 1) == Decimal("39.6")
    assert pricing.pct_shown(f.price.ref30, step.price) == 31
    assert f.price.ref30 == Decimal("7.99")
    assert pricing.base_price_label(step.price, f.net_quantity, f.base_unit) == "27,45 €/kg"


def test_espresso_with_kaffeepause(get_facts: Callable[..., Facts], policy: Policy) -> None:
    a = assess(get_facts, policy, ESPRESSO, "M-1001")
    b = get_facts(ESPRESSO, membership_id="M-1001").behaviour
    assert b is not None
    assert (b.member_purchases_8w, b.days_since_last, b.median_interval_days) == (2, 35, 14)
    assert a.signals == ("customer_behaviour",)
    assert a.metrics.overdue_factor == Decimal("2.5")
    assert (a.metrics.prior_weekly, rounded(a.metrics.cardholder_drop_pct, 1)) == (
        Decimal("22.5"), Decimal("46.7"))
    assert (a.max_step_pct, a.suggested_step_pct) == (10, 10)
    assert a.facts["customer_behaviour"] == (
        "Stammartikel der Karte: zuletzt vor 35 Tagen (sonst alle 14 Tage); "
        "Kartenkunden kaufen 47 % seltener")
    f = get_facts(ESPRESSO).article
    steps = options(get_facts, policy, ESPRESSO)
    assert (steps[10].price, rounded(steps[10].margin_pct, 1)) == (Decimal("12.99"),
                                                                 Decimal("26.7"))
    assert (steps[20].price, rounded(steps[20].margin_pct, 1), steps[20].allowed) == (
        Decimal("11.49"), Decimal("17.1"), False)
    assert f.price.ref30 == Decimal("14.49")
    assert pricing.pct_shown(f.price.ref30, Decimal("12.99")) == 10
    assert pricing.base_price_label(Decimal("12.99"), f.net_quantity, f.base_unit) == \
        "12,99 €/kg"
    assert pricing.price_note(f.last_price_change, Decimal("12.99"), D) == \
        "Rücknahme der Preiserhöhung vom 11.01."


def test_espresso_without_card_is_neutral(get_facts: Callable[..., Facts],
                                          policy: Policy) -> None:
    a = assess(get_facts, policy, ESPRESSO)
    assert a.signals == () and not a.candidate
    assert rounded(a.metrics.sell_through, 2) == Decimal("0.57")
    assert (a.insight_code, a.insight_text, a.severity) == ("neutral", "unauffällig", "info")
    assert a.line_facts == "unauffällig (17/30)"


def test_espresso_without_consent(get_facts: Callable[..., Facts], policy: Policy) -> None:
    a = assess(get_facts, policy, ESPRESSO, "M-1003")
    assert a.signals == () and a.insight_code == "neutral"


def test_ente_with_family_card_keeps_slow_seller(get_facts: Callable[..., Facts],
                                                 policy: Policy) -> None:
    behaviour = get_facts(ENTE, membership_id="M-1002").behaviour
    assert behaviour is not None and behaviour.member_purchases_8w == 1
    assert assess(get_facts, policy, ENTE, "M-1002").signals == ("slow_seller",)


def test_pluschhase_rising_slow_seller(get_facts: Callable[..., Facts], policy: Policy) -> None:
    a = assess(get_facts, policy, HASE)
    m = a.metrics
    assert a.signals == ("slow_seller",)  # Ostern starts 01.03.: no season_end
    assert rounded(m.sell_through, 2) == Decimal("0.47") and m.avg_week_28d == Decimal("11")
    assert (m.stock, rounded(m.weeks_of_supply, 1)) == (90, Decimal("8.2"))
    assert m.days_to_end is None
    assert (a.max_step_pct, a.suggested_step_pct, a.blocked) == (30, 10, "")


def test_gluehwein_blocked_by_central_action(get_facts: Callable[..., Facts],
                                             policy: Policy) -> None:
    a = assess(get_facts, policy, GLUEHWEIN)
    assert a.signals == ("season_end", "slow_seller")
    assert (a.metrics.sold_7d, a.metrics.plan_7d, a.metrics.days_to_end) == (9, 30, 12)
    leftover = rounded(a.metrics.leftover_share, 4) * a.metrics.stock
    assert round(leftover) == 103 and a.metrics.stock == 120
    assert a.blocked == "Zentralaktion läuft bis 21.02."
    assert not a.free and a.candidate
    assert (a.insight_code, a.insight_text) == ("action",
                                                "Zentralaktion aktiv bis So 21.02. 20:00")
    price = get_facts(GLUEHWEIN).article.price
    assert (price.price, price.source, price.ref30) == (Decimal("2.99"), "CENTRAL_ACTION",
                                                        Decimal("2.99"))


def test_kochbuch_price_bound(get_facts: Callable[..., Facts], policy: Policy) -> None:
    a = assess(get_facts, policy, KOCHBUCH)
    assert a.signals == ("slow_seller",)
    assert (a.metrics.sold_7d, a.metrics.plan_7d, a.metrics.weeks_of_supply) == (
        0, 4, Decimal("14"))
    assert "Reichweite 14 Wochen" in a.facts["slow_seller"]
    assert a.blocked == "Preisbindung"
    assert (a.insight_code, a.insight_text) == ("excluded", "Gesperrt: Preisbindung")


def test_all_other_articles_on_plan(get_facts: Callable[..., Facts], policy: Policy,
                                    sources: object) -> None:
    others = [a.number for a in sources.articles  # type: ignore[attr-defined]
              if a.number not in CANDIDATE_ARTICLES | {ESPRESSO, PRALINEN}]
    assert len(others) == 24
    for number in others:
        a = assess(get_facts, policy, number)
        assert (a.signals, a.insight_code, a.blocked) == ((), "on_plan", ""), number
        assert Decimal("0.95") <= rounded(a.metrics.sell_through, 2) <= Decimal("1.09"), number
        assert a.line_facts.startswith("läuft nach Plan ("), number
    assert assess(get_facts, policy, CREMA).insight_text == "läuft nach Plan (44/45)"
    # Herzpralinen sell above plan, but the season signal wins
    assert assess(get_facts, policy, PRALINEN).insight_code == "season_end"


def test_croissants_no_action_line(get_facts: Callable[..., Facts], policy: Policy) -> None:
    a = assess(get_facts, policy, CROISSANTS, "M-1001")
    assert not a.candidate and a.line_facts == "läuft nach Plan (71/70)"


@pytest.mark.parametrize(("regular", "step", "expected"), [
    (Decimal("9.99"), 20, Decimal("7.99")), (Decimal("7.99"), 30, Decimal("5.49")),
    (Decimal("14.49"), 10, Decimal("12.99")), (Decimal("12.99"), 30, Decimal("8.99")),
    (Decimal("1.19"), 10, Decimal("0.99")), (Decimal("0.99"), 30, Decimal("0.49")),
    (Decimal("0.49"), 10, None)])
def test_price_points(regular: Decimal, step: int, expected: Decimal | None,
                      policy: Policy) -> None:
    target = pricing.step_target(regular, step)
    assert pricing.price_point(target, policy.guardrails.price_endings_cents) == expected
