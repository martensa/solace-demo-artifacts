"""Golden values of UC1-BUILD-SPEC 6.8, recomputed in Python straight from data/*.yaml.

The reference below implements the formulas of 6.3 (ref30), 6.5 (cardholder trend),
6.6 (signals, steps) and 6.7 (price points, margin, pct_shown, base price, note)
independently of postgres/gen_seed.py. If a YAML edit moves a hero number of the demo,
these tests name it.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

import pytest

D = date(2027, 2, 16)
TZ = ZoneInfo("Europe/Berlin")
NOW = datetime.combine(D, time(12, 0), TZ)  # any business time of the demo day
STEPS = (10, 20, 30)
ENDINGS = (99, 89, 79, 49)
MIN_MARGIN = Decimal(20)
CARDHOLDER_OVERRIDE = {"100012": [22, 24, 21, 23, 13, 12, 11, 12]}


def dec(value: Any) -> Decimal:
    return Decimal(str(value))


def q(value: Decimal, places: str) -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


# ------------------------------------------------------------ 6.7 price formulas


def price_point(regular: Decimal, step: int) -> Decimal:
    target_cents = int((regular * (100 - step)).to_integral_value(rounding=ROUND_FLOOR))
    euros = target_cents // 100
    while True:
        for ending in ENDINGS:
            if euros * 100 + ending <= target_cents:
                return Decimal(euros * 100 + ending) / 100
        euros -= 1


def margin_pct(price: Decimal, article: dict[str, Any]) -> Decimal:
    net = price / (1 + dec(article["vat"]) / 100)
    return (net - dec(article["cost"])) / net * 100


def max_step(article: dict[str, Any]) -> int:
    regular = dec(article["price"])
    allowed = [s for s in STEPS if margin_pct(price_point(regular, s), article) >= MIN_MARGIN]
    return max(allowed, default=0)


def pct_shown(ref30: Decimal, price: Decimal) -> int:
    return int(((ref30 - price) / ref30 * 100).to_integral_value(rounding=ROUND_FLOOR))


def base_price(price: Decimal, article: dict[str, Any]) -> str:
    unit = {"g": "kg", "ml": "l"}[article["unit"]]
    return f"{q(price * 1000 / dec(article['qty']), '0.01')} €/{unit}"


# ------------------------------------------------------------- 6.3 ref30 model


def price_rows(article: dict[str, Any],
               actions: list[dict[str, Any]]) -> list[tuple[datetime, datetime | None, Decimal]]:
    start = datetime.combine(D - timedelta(days=90), time(0), TZ)
    change = article.get("price_change")
    if change:
        switch = datetime.combine(change["date"], time(0), TZ)
        rows = [(start, switch, dec(change["from"])), (switch, None, dec(article["price"]))]
    else:
        rows = [(start, None, dec(article["price"]))]
    for action in actions:
        if action["article"] == article["number"]:
            rows.append((datetime.fromisoformat(action["from"]).replace(tzinfo=TZ),
                         datetime.fromisoformat(action["to"]).replace(tzinfo=TZ),
                         dec(action["price"])))
    return rows


def ref30(article: dict[str, Any], actions: list[dict[str, Any]],
          at: datetime = NOW) -> Decimal:
    window_start = at - timedelta(days=30)
    return min(price for valid_from, valid_to, price in price_rows(article, actions)
               if valid_from <= at and (valid_to is None or valid_to > window_start))


def open_action(article: dict[str, Any], actions: list[dict[str, Any]]) -> dict[str, Any] | None:
    for action in actions:
        if (action["article"] == article["number"]
                and datetime.fromisoformat(action["from"]).replace(tzinfo=TZ) <= NOW
                < datetime.fromisoformat(action["to"]).replace(tzinfo=TZ)):
            return action
    return None


# -------------------------------------------------------- 6.6 article signals


@dataclass(frozen=True)
class Perf:
    sold_7d: int
    plan: int
    sell_through: Decimal
    avg_week_28d: Decimal
    stock: int
    weeks_of_supply: Decimal
    trend: str
    listed_days: int
    avg_day_14d: Decimal


def perf(article: dict[str, Any]) -> Perf:
    w = article["w"]
    avg28 = Decimal(sum(w[4:8])) / 4
    recent, prior = Decimal(w[6] + w[7]) / 2, Decimal(w[4] + w[5]) / 2
    trend = ("rising" if recent >= dec("1.15") * prior
             else "falling" if recent <= dec("0.85") * prior else "stable")
    return Perf(w[7], article["plan"], Decimal(w[7]) / article["plan"], avg28,
                article["stock"], article["stock"] / avg28, trend,
                (D - article["listed"]).days, Decimal(w[6] + w[7]) / 14)


def season_of(article: dict[str, Any], seasons: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((s for s in seasons if s["code"] == article.get("season")), None)


def slow_seller(p: Perf) -> bool:
    return p.sell_through < dec("0.5") and p.weeks_of_supply > dec("6.0") and p.listed_days >= 28


def leftover(p: Perf, season: dict[str, Any]) -> Decimal:
    return p.stock - p.avg_day_14d * max((season["end"] - D).days, 0)


def season_end(p: Perf, season: dict[str, Any] | None) -> bool:
    if season is None or season["start"] > D:
        return False
    days_to_end = (season["end"] - D).days
    if days_to_end < 0:
        return p.stock > 0
    return days_to_end <= 14 and leftover(p, season) / p.stock >= dec("0.4")


def suggested_step(reason: str, p: Perf, season: dict[str, Any] | None) -> int:
    if reason == "season_end":
        assert season is not None
        days_to_end = (season["end"] - D).days
        return 30 if days_to_end < 0 else 20 if days_to_end <= 7 else 10
    if reason == "slow_seller":
        return 20 if p.sell_through < dec("0.3") else 10
    return 10


# ------------------------------------------------------ 6.4-6.6 card behaviour


def member_days(member: dict[str, Any], number: str) -> list[date]:
    days: set[date] = set()
    for rule in member["history"]:
        if rule["article"] != number:
            continue
        day = rule["first"]
        while day <= rule["last"]:
            days.add(day)
            if rule["every_days"] == 0:
                break
            day += timedelta(days=rule["every_days"])
    return sorted(days)


@dataclass(frozen=True)
class Behaviour:
    buys_8w: int
    buys_12w: int
    days_since_last: int
    median_interval: int
    overdue_factor: Decimal
    prior_weekly: Decimal
    recent_weekly: Decimal
    drop_pct: Decimal | None  # None without cardholder purchases in the prior 4 weeks


def cardholder_weekly(article: dict[str, Any]) -> list[int]:
    return CARDHOLDER_OVERRIDE.get(article["number"]) or [
        int(q(Decimal(units) * dec("0.55"), "1")) for units in article["w"]]


def behaviour(member: dict[str, Any], article: dict[str, Any]) -> Behaviour:
    days = [d for d in member_days(member, article["number"]) if d < D]
    in_12w = [d for d in days if D - timedelta(days=84) <= d <= D - timedelta(days=1)]
    gaps = [(b - a).days for a, b in zip(in_12w, in_12w[1:])]
    weekly = cardholder_weekly(article)
    prior, recent = Decimal(sum(weekly[:4])) / 4, Decimal(sum(weekly[4:])) / 4
    since = (D - days[-1]).days if days else -1
    interval = int(median(gaps)) if gaps else 0
    return Behaviour(
        buys_8w=sum(1 for d in days if D - timedelta(days=56) <= d <= D - timedelta(days=1)),
        buys_12w=len(in_12w), days_since_last=since, median_interval=interval,
        overdue_factor=Decimal(since) / interval if interval else Decimal(0),
        prior_weekly=prior, recent_weekly=recent,
        drop_pct=(prior - recent) / prior * 100 if prior else None)


def customer_behaviour(member: dict[str, Any] | None, article: dict[str, Any]) -> bool:
    if member is None or not member["consent"]["profiling"]:
        return False
    b = behaviour(member, article)
    return (b.buys_8w >= 2 and b.overdue_factor >= dec("1.5") and b.prior_weekly >= 5
            and b.drop_pct is not None and b.drop_pct >= 30)


# ----------------------------------------------------------- review of a basket


@dataclass(frozen=True)
class Line:
    number: str
    signals: tuple[str, ...]
    blocked: str
    candidate: bool
    insight: str


PRIORITY = ("season_end", "slow_seller", "customer_behaviour")


class Reference:
    def __init__(self, articles: list[dict[str, Any]], seasons: list[dict[str, Any]],
                 actions: list[dict[str, Any]], personas: dict[str, Any]) -> None:
        self.articles = {a["number"]: a for a in articles}
        self.by_gtin = {a["gtin"]: a for a in articles}
        self.seasons, self.actions = seasons, actions
        self.cards = {m["card"]: m for m in personas["members"]}

    def line(self, number: str, member: dict[str, Any] | None) -> Line:
        article = self.articles[number]
        p, season = perf(article), season_of(article, self.seasons)
        flags = {"season_end": season_end(p, season), "slow_seller": slow_seller(p),
                 "customer_behaviour": customer_behaviour(member, article)}
        signals = tuple(s for s in PRIORITY if flags[s])
        blocked = ("Preisbindung" if article.get("price_bound")
                   else "Aktion läuft" if open_action(article, self.actions)
                   else "Mindestmarge" if max_step(article) == 0 else "")
        insight = ("excluded" if article.get("price_bound")
                   else "action" if open_action(article, self.actions)
                   else signals[0] if signals
                   else "on_plan" if p.sell_through >= dec("0.8") else "neutral")
        return Line(number, signals, blocked, bool(signals) and not blocked, insight)

    def review(self, scenario: dict[str, Any]) -> list[Line]:
        member = None
        numbers: list[str] = []
        for step in scenario["steps"]:
            if step["op"] == "card":
                member = self.cards[step["value"]]
            elif step["op"] == "scan":
                numbers.append(self.by_gtin[step["value"]]["number"])
        return [self.line(n, member) for n in numbers]


@pytest.fixture(scope="module")
def ref(articles: list[dict[str, Any]], seasons: list[dict[str, Any]],
        central_actions: list[dict[str, Any]], personas: dict[str, Any]) -> Reference:
    return Reference(articles, seasons, central_actions, personas)


@pytest.fixture(scope="module")
def kaffeepause(personas: dict[str, Any]) -> dict[str, Any]:
    return personas["members"][0]


# ======================================================================== 6.8


def test_price_point_examples() -> None:
    assert price_point(dec("9.99"), 20) == dec("7.99")
    assert price_point(dec("7.99"), 30) == dec("5.49")
    assert price_point(dec("14.49"), 10) == dec("12.99")
    assert price_point(dec("1.19"), 30) == dec("0.79")


def test_s1_ente(ref: Reference, articles_by_number: dict[str, dict[str, Any]],
                 central_actions: list[dict[str, Any]]) -> None:
    ente = articles_by_number["100001"]
    p = perf(ente)
    assert (p.sold_7d, p.plan, q(p.sell_through, "0.01")) == (9, 35, dec("0.26"))
    assert (p.avg_week_28d, p.stock, q(p.weeks_of_supply, "0.1")) == (
        dec("14.75"), 96, dec("6.5"))
    assert p.trend == "falling"
    assert ref.line("100001", None).signals == ("slow_seller",)
    assert (max_step(ente), suggested_step("slow_seller", p, None)) == (20, 20)
    new = price_point(dec("9.99"), 20)
    assert (new, pct_shown(ref30(ente, central_actions), new)) == (dec("7.99"), 20)
    assert q(margin_pct(new, ente), "0.1") == dec("22.6")
    blocked = price_point(dec("9.99"), 30)
    assert (blocked, q(margin_pct(blocked, ente), "0.1")) == (dec("6.99"), dec("11.5"))
    assert ref30(ente, central_actions) == dec("9.99")
    assert q(margin_pct(dec("9.99"), ente), "0.1") == dec("38.1")  # get_article, 8.4


def test_s2_herzpralinen(ref: Reference, articles_by_number: dict[str, dict[str, Any]],
                         seasons: list[dict[str, Any]],
                         central_actions: list[dict[str, Any]]) -> None:
    pralinen = articles_by_number["100008"]
    p, season = perf(pralinen), season_of(pralinen, seasons)
    assert season is not None and season["end"] == date(2027, 2, 14)
    assert ((season["end"] - D).days, p.stock) == (-2, 46)
    assert ref.line("100008", None).signals == ("season_end",)
    assert (max_step(pralinen), suggested_step("season_end", p, season)) == (30, 30)
    new = price_point(dec("7.99"), 30)
    assert (new, pct_shown(ref30(pralinen, central_actions), new)) == (dec("5.49"), 31)
    assert q(margin_pct(new, pralinen), "0.1") == dec("39.6")
    assert base_price(new, pralinen) == "27.45 €/kg"
    assert ref30(pralinen, central_actions) == dec("7.99")
    assert q(p.avg_day_14d, "0.1") == dec("6.4")  # get_season_info example, 8.4


def test_s3_espresso_with_kaffeepause(ref: Reference, kaffeepause: dict[str, Any],
                                      articles_by_number: dict[str, dict[str, Any]],
                                      central_actions: list[dict[str, Any]]) -> None:
    espresso = articles_by_number["100012"]
    assert member_days(kaffeepause, "100012") == [
        date(2026, 12, 1), date(2026, 12, 15), date(2026, 12, 29), date(2027, 1, 12)]
    b = behaviour(kaffeepause, espresso)
    assert (b.buys_8w, b.buys_12w, b.days_since_last, b.median_interval) == (2, 4, 35, 14)
    assert b.overdue_factor == dec("2.5")
    assert b.drop_pct is not None
    assert (b.prior_weekly, b.recent_weekly, q(b.drop_pct, "0.1")) == (
        dec("22.5"), dec("12.0"), dec("46.7"))
    assert ref.line("100012", kaffeepause).signals == ("customer_behaviour",)
    assert max_step(espresso) == 10
    new = price_point(dec("14.49"), 10)
    assert (new, pct_shown(ref30(espresso, central_actions), new)) == (dec("12.99"), 10)
    assert q(margin_pct(new, espresso), "0.1") == dec("26.7")
    blocked = price_point(dec("14.49"), 20)
    assert (blocked, q(margin_pct(blocked, espresso), "0.1")) == (dec("11.49"), dec("17.1"))
    assert ref30(espresso, central_actions) == dec("14.49")
    assert base_price(new, espresso) == "12.99 €/kg"


def test_s3_espresso_window_edges_are_seven_days_from_a_purchase(
        kaffeepause: dict[str, Any]) -> None:
    days = member_days(kaffeepause, "100012")
    for edge in (D - timedelta(days=56), D - timedelta(days=84)):
        assert min(abs((d - edge).days) for d in days) == 7
        assert edge not in days


def test_s3_note_rollback_of_the_price_increase(
        articles_by_number: dict[str, dict[str, Any]]) -> None:
    espresso = articles_by_number["100012"]
    change = espresso["price_change"]
    old, current = dec(change["from"]), dec(espresso["price"])
    assert (D - change["date"]).days == 36 <= 90 and current > old
    assert price_point(current, 10) >= old
    assert f"Rücknahme der Preiserhöhung vom {change['date']:%d.%m.}" == (
        "Rücknahme der Preiserhöhung vom 11.01.")


def test_espresso_without_card_is_neutral(ref: Reference,
                                          articles_by_number: dict[str, dict[str, Any]]) -> None:
    p = perf(articles_by_number["100012"])
    assert (p.sold_7d, p.plan, q(p.sell_through, "0.01")) == (17, 30, dec("0.57"))
    line = ref.line("100012", None)
    assert (line.signals, line.candidate, line.insight) == ((), False, "neutral")


def test_s8_pluschhase(ref: Reference, articles_by_number: dict[str, dict[str, Any]],
                       seasons: list[dict[str, Any]]) -> None:
    hase = articles_by_number["100002"]
    p, season = perf(hase), season_of(hase, seasons)
    assert hase["w"][0] == 4 and hase["w"][-1] == 14
    assert (p.sold_7d, p.plan, q(p.sell_through, "0.01")) == (14, 30, dec("0.47"))
    assert (p.avg_week_28d, p.stock, q(p.weeks_of_supply, "0.1")) == (
        dec("11.0"), 90, dec("8.2"))
    assert p.trend == "rising"
    assert (Decimal(hase["w"][6] + hase["w"][7]) / 2, Decimal(hase["w"][4] + hase["w"][5]) / 2
            ) == (13, 9)
    assert season is not None and season["start"] == date(2027, 3, 1) > D  # status before
    assert ref.line("100002", None).signals == ("slow_seller",)
    assert (max_step(hase), suggested_step("slow_seller", p, season)) == (30, 10)


def test_gluehwein_blocked_by_central_action(ref: Reference,
                                             articles_by_number: dict[str, dict[str, Any]],
                                             seasons: list[dict[str, Any]],
                                             central_actions: list[dict[str, Any]]) -> None:
    gluehwein = articles_by_number["100009"]
    p, season = perf(gluehwein), season_of(gluehwein, seasons)
    assert (p.sold_7d, p.plan) == (9, 30)
    assert season is not None and (season["end"] - D).days == 12
    assert (int(q(leftover(p, season), "1")), p.stock) == (103, 120)
    line = ref.line("100009", None)
    assert (line.signals, line.blocked, line.candidate) == (
        ("season_end", "slow_seller"), "Aktion läuft", False)
    action = open_action(gluehwein, central_actions)
    assert action is not None and action["to"] == "2027-02-21T20:00"
    assert ref30(gluehwein, central_actions) == dec("2.99")
    assert pct_shown(dec(action["ref30"]), dec(action["price"])) == 14
    at_start = datetime.fromisoformat(action["from"]).replace(tzinfo=TZ)
    assert ref30(gluehwein, [], at_start) == dec(action["ref30"])


def test_kochbuch_blocked_by_price_binding(ref: Reference,
                                           articles_by_number: dict[str, dict[str, Any]]) -> None:
    p = perf(articles_by_number["100028"])
    assert (p.sold_7d, p.plan, q(p.weeks_of_supply, "0.1")) == (0, 4, dec("14.0"))
    line = ref.line("100028", None)
    assert (line.signals, line.blocked, line.insight) == (
        ("slow_seller",), "Preisbindung", "excluded")


def test_all_other_articles_on_plan(ref: Reference, articles: list[dict[str, Any]]) -> None:
    signalled = {"100001", "100002", "100008", "100009", "100012", "100028"}
    others = [a for a in articles if a["number"] not in signalled]
    assert len(others) == 24
    for article in others:
        line, p = ref.line(article["number"], None), perf(article)
        assert (line.signals, line.insight) == ((), "on_plan"), article["number"]
        assert dec("0.95") <= p.sell_through <= dec("1.09"), article["number"]


def test_m1003_without_profiling_consent(ref: Reference, personas: dict[str, Any]) -> None:
    feierabend = personas["members"][2]
    assert feierabend["consent"]["profiling"] is False
    assert ref.line("100012", feierabend).signals == ()


def test_m1002_ente_only_one_purchase(ref: Reference, personas: dict[str, Any],
                                      articles_by_number: dict[str, dict[str, Any]]) -> None:
    familie = personas["members"][1]
    assert behaviour(familie, articles_by_number["100001"]).buys_8w == 1
    assert ref.line("100001", familie).signals == ("slow_seller",)


def test_only_kaffeepause_espresso_fires_customer_behaviour(
        personas: dict[str, Any], articles: list[dict[str, Any]]) -> None:
    fired = [(m["id"], a["number"]) for m in personas["members"] for a in articles
             if member_days(m, a["number"]) and customer_behaviour(m, a)]
    assert fired == [("M-1001", "100012")]


EXPECTED_REVIEWS = {
    # scenario -> (free candidates in priority order, blocked articles)
    "S1": (["100001"], []),
    "S2": (["100008"], []),
    "S3": (["100012"], []),
    "S4": ([], []),
    "S5": ([], ["100009", "100028"]),
    "S6": ([], []),
    "S7": (["100008", "100001"], []),
    "S8": (["100002"], []),
}


@pytest.mark.parametrize("scenario_id", sorted(EXPECTED_REVIEWS))
def test_scenario_reviews(ref: Reference, scenarios: list[dict[str, Any]],
                          scenario_id: str) -> None:
    scenario = next(s for s in scenarios if s["id"] == scenario_id)
    lines = ref.review(scenario)
    candidates = sorted((ln for ln in lines if ln.candidate),
                        key=lambda ln: PRIORITY.index(ln.signals[0]))
    blocked = [ln.number for ln in lines if ln.signals and ln.blocked]
    assert ([ln.number for ln in candidates], blocked) == EXPECTED_REVIEWS[scenario_id]


def test_s4_all_lines_on_plan(ref: Reference, scenarios: list[dict[str, Any]]) -> None:
    s4 = next(s for s in scenarios if s["id"] == "S4")
    assert [ln.insight for ln in ref.review(s4)] == ["on_plan"] * 3


def test_min_margin_articles_carry_no_signal(ref: Reference,
                                             articles: list[dict[str, Any]]) -> None:
    """Vollmilch (S1, S8) and Butter have max_step 0 but never become candidates."""
    zero = [a["number"] for a in articles if max_step(a) == 0]
    assert zero == ["100010", "100011"]
    assert all(ref.line(n, None).signals == () for n in zero)
