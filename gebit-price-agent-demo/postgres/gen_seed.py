#!/usr/bin/env python3
"""Seed generator of DB gpos (UC1-BUILD-SPEC 5.7, data from 6.2-6.5).

Reads data/articles.yaml, seasons.yaml, central_actions.yaml and personas.yaml and
writes three psql files, each one transaction under `set local role`:

    90-seed-wws.sql      truncate + insert of the wws seed tables (stores 101 and 199)
    91-seed-loyalty.sql  truncate + insert of the loyalty seed tables
    92-seed-pos.sql      upsert of the tills 01, 98, 99 (baskets stay)

Deterministic (no randomness, no wall clock): the same YAML and demo date give
byte-identical files. Only stdlib and PyYAML; every YAML number is converted with
Decimal(str(x)) right after yaml.safe_load and never computed as float.

    python3 postgres/gen_seed.py --demo-date 2027-02-16 --out postgres/.generated
"""

import argparse
import sys
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

TZ = ZoneInfo("Europe/Berlin")
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

BOOTH_STORE = "101"
STORES: tuple[str, ...] = (BOOTH_STORE, "199")  # booth and probe/test: identical data

# 6.1: category tag -> label (the VAT per article lives in articles.yaml)
CATEGORIES: dict[str, str] = {
    "obst_gemuese": "Obst & Gemüse",
    "molkerei_fruehstueck": "Molkerei & Frühstück",
    "kaffee_tee": "Kaffee & Tee",
    "suesswaren_snacks": "Süßwaren & Snacks",
    "getraenke": "Getränke",
    "drogerie_haushalt": "Drogerie & Haushalt",
    "spielwaren_geschenke": "Spielwaren & Geschenke",
    "buch": "Bücher",
}
BASE_UNITS = ("g", "ml", "Stück")
VAT_RATES = (Decimal("7"), Decimal("19"))

WEEKS = 8
DAYS_PER_WEEK = 7
# 5.7: weekly units spread over Mon..Sat, Sunday 0 (no row), largest remainder
WEEKDAY_WEIGHTS: tuple[Decimal, ...] = tuple(
    Decimal(w) for w in ("0.14", "0.15", "0.15", "0.16", "0.19", "0.21", "0"))
SUNDAY = 6
HISTORY_DAYS = 90  # 6.3: price history starts at demo date - 90 days

# 6.5: anonymous cardholder statistics
CARDHOLDER_SHARE = Decimal("0.55")
DISTINCT_SHARE = Decimal("0.8")
CARDHOLDER_OVERRIDES: dict[str, tuple[int, ...]] = {
    "100012": (22, 24, 21, 23, 13, 12, 11, 12),
}

# 6.4: seeded purchases
SEED_LOCATION = "Root.DE.999.101.01"
PURCHASE_TIME = time(10, 30)
POLICY_VERSION = "2027-01"
SEED_UUID_NAMESPACE = uuid.NAMESPACE_URL

CENTRAL_ORIGINATOR = "zentrale"
CENT = Decimal("0.01")


class SeedDataError(ValueError):
    """The YAML sources violate the data contract of spec section 6."""


# --------------------------------------------------------------------------- model


@dataclass(frozen=True)
class PriceChange:
    on: date
    old_price: Decimal


@dataclass(frozen=True)
class Delivery:
    expected_on: date
    quantity: int


@dataclass(frozen=True)
class Article:
    number: str
    gtin: str
    name: str
    category: str
    pack: str
    qty: Decimal
    unit: str
    vat: Decimal
    price: Decimal
    cost: Decimal
    plan: Decimal
    weekly: tuple[int, ...]
    stock: int
    listed: date
    season: str | None
    price_bound: bool
    price_change: PriceChange | None
    next_delivery: Delivery | None

    @property
    def article_id(self) -> str:
        return f"ID{self.number}"

    def regular_price_on(self, day: date) -> Decimal:
        """Regular shelf price on a business date (6.4: Espresso 12,99 before 11.01.)."""
        if self.price_change is not None and day < self.price_change.on:
            return self.price_change.old_price
        return self.price


@dataclass(frozen=True)
class Season:
    code: str
    label: str
    start: date
    end: date


@dataclass(frozen=True)
class CentralAction:
    article: str
    price: Decimal
    valid_from: datetime
    valid_to: datetime
    ref30: Decimal
    reason_code: str
    label: str

    @property
    def pct_shown(self) -> int:
        """Reduction against ref30, rounded down (6.7 step 4)."""
        pct = (self.ref30 - self.price) / self.ref30 * 100
        return int(pct.to_integral_value(rounding=ROUND_FLOOR))


@dataclass(frozen=True)
class HistoryRule:
    article: str
    qty: int
    first: date
    every_days: int
    last: date

    def days(self) -> list[date]:
        """Purchase days from `first` every `every_days` while <= `last` (0 = once)."""
        if self.every_days == 0:
            return [self.first]
        step = timedelta(days=self.every_days)
        days: list[date] = []
        day = self.first
        while day <= self.last:
            days.append(day)
            day += step
        return days


@dataclass(frozen=True)
class Member:
    member_id: str
    card: str
    persona: str
    key: str
    segment: str
    salutation: str
    offers: bool
    profiling: bool
    anonymous: bool
    tags: tuple[str, ...]
    history: tuple[HistoryRule, ...]

    @property
    def customer_ref(self) -> str | None:
        return None if self.anonymous else f"CUST-DEMO-{self.member_id}"

    @property
    def card_type(self) -> str:
        return "GUEST" if self.anonymous else "PHYSICAL"

    @property
    def account_id(self) -> str:
        return f"ACC-{self.member_id}-POINTS"


@dataclass(frozen=True)
class Program:
    program_id: str
    name: str
    display: str
    account_type: str
    currency_id: str
    currency_name: str
    base_promotion_id: str
    earn_eur_per_point: Decimal


@dataclass(frozen=True)
class Till:
    till_id: str
    store_id: str
    location: str
    kind: str


TILLS: tuple[Till, ...] = (
    Till("01", "101", "Root.DE.999.101.01", "booth"),
    Till("98", "199", "Root.DE.999.199.98", "probe"),
    Till("99", "199", "Root.DE.999.199.99", "test"),
)


@dataclass(frozen=True)
class Sources:
    articles: tuple[Article, ...]
    seasons: tuple[Season, ...]
    central_actions: tuple[CentralAction, ...]
    program: Program
    tags: dict[str, str]  # tag -> label_de
    members: tuple[Member, ...]

    def article(self, number: str) -> Article:
        for article in self.articles:
            if article.number == number:
                return article
        raise SeedDataError(f"unknown article {number!r}")


# ------------------------------------------------------------------- YAML loading


def _req(obj: Mapping[str, object], key: str, where: str) -> object:
    if key not in obj:
        raise SeedDataError(f"{where}: missing key {key!r}")
    return obj[key]


def _str(obj: Mapping[str, object], key: str, where: str) -> str:
    value = _req(obj, key, where)
    if not isinstance(value, str) or not value:
        raise SeedDataError(f"{where}.{key}: non-empty string expected, got {value!r}")
    return value


def _dec(obj: Mapping[str, object], key: str, where: str) -> Decimal:
    value = _req(obj, key, where)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SeedDataError(f"{where}.{key}: number expected, got {value!r}")
    return Decimal(str(value))


def _int(obj: Mapping[str, object], key: str, where: str) -> int:
    value = _req(obj, key, where)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SeedDataError(f"{where}.{key}: integer expected, got {value!r}")
    return value


def _bool(obj: Mapping[str, object], key: str, where: str) -> bool:
    value = _req(obj, key, where)
    if not isinstance(value, bool):
        raise SeedDataError(f"{where}.{key}: boolean expected, got {value!r}")
    return value


def _date(obj: Mapping[str, object], key: str, where: str) -> date:
    value = _req(obj, key, where)
    if isinstance(value, datetime) or not isinstance(value, date):
        raise SeedDataError(f"{where}.{key}: ISO date expected, got {value!r}")
    return value


def _local_time(obj: Mapping[str, object], key: str, where: str) -> datetime:
    text = _str(obj, key, where)
    try:
        naive = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SeedDataError(f"{where}.{key}: local ISO time expected, got {text!r}") from exc
    if naive.tzinfo is not None:
        raise SeedDataError(f"{where}.{key}: local time without offset expected")
    return naive.replace(tzinfo=TZ)


def _mapping(value: object, where: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SeedDataError(f"{where}: mapping expected, got {type(value).__name__}")
    return value


def _list(value: object, where: str) -> list[object]:
    if not isinstance(value, list):
        raise SeedDataError(f"{where}: list expected, got {type(value).__name__}")
    return value


def _load_yaml(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _parse_article(raw: object, index: int) -> Article:
    where = f"articles[{index}]"
    obj = _mapping(raw, where)
    weekly_raw = _list(_req(obj, "w", where), f"{where}.w")
    if len(weekly_raw) != WEEKS or not all(
            isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in weekly_raw):
        raise SeedDataError(f"{where}.w: {WEEKS} non-negative integers expected")
    change = None
    if "price_change" in obj:
        raw_change = _mapping(obj["price_change"], f"{where}.price_change")
        change = PriceChange(_date(raw_change, "date", f"{where}.price_change"),
                             _dec(raw_change, "from", f"{where}.price_change"))
    delivery = None
    if "next_delivery" in obj:
        raw_delivery = _mapping(obj["next_delivery"], f"{where}.next_delivery")
        delivery = Delivery(_date(raw_delivery, "expected_on", f"{where}.next_delivery"),
                            _int(raw_delivery, "qty", f"{where}.next_delivery"))
    season = _str(obj, "season", where) if "season" in obj else None
    article = Article(
        number=_str(obj, "number", where), gtin=_str(obj, "gtin", where),
        name=_str(obj, "name", where), category=_str(obj, "cat", where),
        pack=_str(obj, "pack", where), qty=_dec(obj, "qty", where),
        unit=_str(obj, "unit", where), vat=_dec(obj, "vat", where),
        price=_dec(obj, "price", where), cost=_dec(obj, "cost", where),
        plan=_dec(obj, "plan", where), weekly=tuple(int(v) for v in weekly_raw),
        stock=_int(obj, "stock", where), listed=_date(obj, "listed", where),
        season=season,
        price_bound=_bool(obj, "price_bound", where) if "price_bound" in obj else False,
        price_change=change, next_delivery=delivery)
    if article.category not in CATEGORIES:
        raise SeedDataError(f"{where}: unknown category {article.category!r}")
    if article.unit not in BASE_UNITS:
        raise SeedDataError(f"{where}: unknown base unit {article.unit!r}")
    if article.vat not in VAT_RATES:
        raise SeedDataError(f"{where}: VAT {article.vat} not in 7/19")
    return article


def _parse_season(raw: object, index: int) -> Season:
    where = f"seasons[{index}]"
    obj = _mapping(raw, where)
    season = Season(_str(obj, "code", where), _str(obj, "label", where),
                    _date(obj, "start", where), _date(obj, "end", where))
    if season.end < season.start:
        raise SeedDataError(f"{where}: end before start")
    return season


def _parse_central_action(raw: object, index: int) -> CentralAction:
    where = f"central_actions[{index}]"
    obj = _mapping(raw, where)
    action = CentralAction(
        article=_str(obj, "article", where), price=_dec(obj, "price", where),
        valid_from=_local_time(obj, "from", where), valid_to=_local_time(obj, "to", where),
        ref30=_dec(obj, "ref30", where), reason_code=_str(obj, "reason_code", where),
        label=_str(obj, "label", where))
    if action.valid_to <= action.valid_from:
        raise SeedDataError(f"{where}: 'to' must be after 'from'")
    return action


def _parse_history(raw: object, where: str) -> HistoryRule:
    obj = _mapping(raw, where)
    rule = HistoryRule(_str(obj, "article", where), _int(obj, "qty", where),
                       _date(obj, "first", where), _int(obj, "every_days", where),
                       _date(obj, "last", where))
    if rule.qty <= 0 or rule.every_days < 0 or rule.last < rule.first:
        raise SeedDataError(f"{where}: qty > 0, every_days >= 0 and last >= first expected")
    return rule


def _parse_member(raw: object, index: int) -> Member:
    where = f"members[{index}]"
    obj = _mapping(raw, where)
    consent = _mapping(_req(obj, "consent", where), f"{where}.consent")
    tags = _list(_req(obj, "tags", where), f"{where}.tags")
    history = _list(_req(obj, "history", where), f"{where}.history")
    salutation = _str(obj, "salutation", where)
    if salutation not in ("FORMAL", "INFORMAL"):
        raise SeedDataError(f"{where}: salutation FORMAL or INFORMAL expected")
    return Member(
        member_id=_str(obj, "id", where), card=_str(obj, "card", where),
        persona=_str(obj, "persona", where), key=_str(obj, "key", where),
        segment=_str(obj, "segment", where), salutation=salutation,
        offers=_bool(consent, "offers", f"{where}.consent"),
        profiling=_bool(consent, "profiling", f"{where}.consent"),
        anonymous=_bool(obj, "anonymous", where) if "anonymous" in obj else False,
        tags=tuple(str(t) for t in tags),
        history=tuple(_parse_history(h, f"{where}.history[{i}]")
                      for i, h in enumerate(history)))


def _parse_program(raw: object) -> Program:
    obj = _mapping(raw, "program")
    return Program(
        program_id=_str(obj, "id", "program"), name=_str(obj, "name", "program"),
        display=_str(obj, "display", "program"),
        account_type=_str(obj, "account_type", "program"),
        currency_id=_str(obj, "currency_id", "program"),
        currency_name=_str(obj, "currency_name", "program"),
        base_promotion_id=_str(obj, "base_promotion_id", "program"),
        earn_eur_per_point=_dec(obj, "earn_eur_per_point", "program"))


def _parse_tags(raw: object) -> dict[str, str]:
    tags: dict[str, str] = {}
    for tag, label in _mapping(raw, "tags").items():
        if label is None:
            if tag not in CATEGORIES:
                raise SeedDataError(f"tags.{tag}: no label and not a category of 6.1")
            label = CATEGORIES[tag]
        if not isinstance(label, str) or not label:
            raise SeedDataError(f"tags.{tag}: label string expected")
        tags[str(tag)] = label
    return tags


def _unique(values: Iterable[str], what: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise SeedDataError(f"duplicate {what} {value!r}")
        seen.add(value)


def _check_references(src: Sources) -> None:
    _unique((a.number for a in src.articles), "article number")
    _unique((a.gtin for a in src.articles), "gtin")
    _unique((s.code for s in src.seasons), "season code")
    _unique((m.member_id for m in src.members), "member id")
    _unique((m.card for m in src.members), "card")
    _unique((m.key for m in src.members), "persona key")
    season_codes = {s.code for s in src.seasons}
    for article in src.articles:
        if article.season is not None and article.season not in season_codes:
            raise SeedDataError(f"article {article.number}: unknown season {article.season!r}")
    for action in src.central_actions:
        src.article(action.article)
    for member in src.members:
        for tag in member.tags:
            if tag not in src.tags:
                raise SeedDataError(f"member {member.member_id}: unknown tag {tag!r}")
        for rule in member.history:
            src.article(rule.article)


def load_sources(data_dir: Path = DEFAULT_DATA_DIR) -> Sources:
    """Load and validate the four seed sources of data_dir (spec 6.2-6.4)."""
    personas = _mapping(_load_yaml(data_dir / "personas.yaml"), "personas.yaml")
    src = Sources(
        articles=tuple(_parse_article(a, i) for i, a in enumerate(
            _list(_load_yaml(data_dir / "articles.yaml"), "articles.yaml"))),
        seasons=tuple(_parse_season(s, i) for i, s in enumerate(
            _list(_load_yaml(data_dir / "seasons.yaml"), "seasons.yaml"))),
        central_actions=tuple(_parse_central_action(c, i) for i, c in enumerate(
            _list(_load_yaml(data_dir / "central_actions.yaml"), "central_actions.yaml"))),
        program=_parse_program(_req(personas, "program", "personas.yaml")),
        tags=_parse_tags(_req(personas, "tags", "personas.yaml")),
        members=tuple(_parse_member(m, i) for i, m in enumerate(
            _list(_req(personas, "members", "personas.yaml"), "personas.members"))))
    _check_references(src)
    return src


# ------------------------------------------------------------------ calculations


def local_midnight(day: date) -> datetime:
    return datetime.combine(day, time(0), TZ)


def history_start(demo_date: date) -> datetime:
    """Start of the seeded price history and of all seeded master data rows."""
    return local_midnight(demo_date - timedelta(days=HISTORY_DAYS))


def week_starts(demo_date: date) -> list[date]:
    """First days of the 8 seven-day windows ending yesterday, oldest first (5.7, 6.5)."""
    first = demo_date - timedelta(days=WEEKS * DAYS_PER_WEEK)
    return [first + timedelta(days=DAYS_PER_WEEK * k) for k in range(WEEKS)]


def split_week(total: int, start: date) -> list[tuple[date, int]]:
    """Spread one weekly sum over the Mon..Sat days of the window starting at `start`.

    Weights 0.14 0.15 0.15 0.16 0.19 0.21 (Mon..Sat), Sunday 0 and without a row;
    largest remainder method, ties go to the earlier weekday. Sums are exact.
    """
    days = [start + timedelta(days=i) for i in range(DAYS_PER_WEEK)]
    quotas = [(day, Decimal(total) * WEEKDAY_WEIGHTS[day.weekday()])
              for day in days if day.weekday() != SUNDAY]
    units = {day: int(quota.to_integral_value(rounding=ROUND_FLOOR)) for day, quota in quotas}
    remainder = total - sum(units.values())
    by_fraction = sorted(quotas, key=lambda dq: (units[dq[0]] - dq[1], dq[0].weekday()))
    for day, _ in by_fraction[:remainder]:
        units[day] += 1
    return [(day, units[day]) for day, _ in quotas]


def daily_units(article: Article, demo_date: date) -> list[tuple[date, int]]:
    rows: list[tuple[date, int]] = []
    for total, start in zip(article.weekly, week_starts(demo_date), strict=True):
        rows.extend(split_week(total, start))
    return rows


def round_half_up(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


def cardholder_week_stats(article: Article) -> list[tuple[int, int]]:
    """(member_purchases, distinct_members) per week, oldest first (6.5)."""
    purchases = CARDHOLDER_OVERRIDES.get(article.number) or tuple(
        round_half_up(Decimal(units) * CARDHOLDER_SHARE) for units in article.weekly)
    return [(p, round_half_up(Decimal(p) * DISTINCT_SHARE)) for p in purchases]


def central_action_id(action: CentralAction, store: str) -> str:
    """PA-SEED-<article> in the booth store; other stores get a '-<store>' suffix."""
    base = f"PA-SEED-{action.article}"
    return base if store == BOOTH_STORE else f"{base}-{store}"


@dataclass(frozen=True)
class PurchaseLine:
    position_id: str
    article: Article
    qty: int
    value: Decimal


@dataclass(frozen=True)
class Purchase:
    tx_id: uuid.UUID
    member: Member
    day: date
    lines: tuple[PurchaseLine, ...]

    @property
    def total(self) -> Decimal:
        return sum((line.value for line in self.lines), Decimal("0.00"))

    @property
    def closed_at(self) -> datetime:
        return datetime.combine(self.day, PURCHASE_TIME, TZ)

    @property
    def receipt_number(self) -> str:
        return f"SEED-{self.member.member_id}-{self.day:%Y%m%d}"


def member_purchases(src: Sources, member: Member, demo_date: date) -> list[Purchase]:
    """One purchase per member and day; entries of the same day become one basket."""
    by_day: dict[date, list[tuple[Article, int]]] = {}
    for rule in member.history:
        article = src.article(rule.article)
        for day in rule.days():
            if day >= demo_date:
                raise SeedDataError(
                    f"member {member.member_id}: purchase {day} not before demo date")
            lines = by_day.setdefault(day, [])
            if any(a.number == article.number for a, _ in lines):
                raise SeedDataError(
                    f"member {member.member_id}: article {article.number} twice on {day}")
            lines.append((article, rule.qty))
    purchases: list[Purchase] = []
    for day in sorted(by_day):
        tx_id = uuid.uuid5(SEED_UUID_NAMESPACE, f"{member.member_id}-{day.isoformat()}")
        purchases.append(Purchase(tx_id, member, day, tuple(
            PurchaseLine(str(uuid.uuid5(SEED_UUID_NAMESPACE, f"{tx_id}-{article.number}")),
                         article, qty, (article.regular_price_on(day) * qty).quantize(CENT))
            for article, qty in by_day[day])))
    return purchases


# ------------------------------------------------------------------------ tables

SqlValue = None | bool | int | str | Decimal | date | datetime | uuid.UUID


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[str, ...]
    rows: tuple[tuple[SqlValue, ...], ...]


def _table(name: str, columns: str, rows: Iterable[tuple[SqlValue, ...]]) -> Table:
    cols = tuple(c.strip() for c in columns.split(","))
    materialized = tuple(rows)
    for row in materialized:
        if len(row) != len(cols):
            raise SeedDataError(f"{name}: row width {len(row)} != {len(cols)} columns")
    return Table(name, cols, materialized)


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT)


def _price_history_rows(src: Sources, article: Article, store: str,
                        demo_date: date) -> list[tuple[SqlValue, ...]]:
    start = history_start(demo_date)
    change = article.price_change
    if change is None:
        rows: list[tuple[SqlValue, ...]] = [
            (article.number, store, start, None, _money(article.price), "REGULAR")]
    else:
        switch = local_midnight(change.on)
        if not start < switch <= local_midnight(demo_date):
            raise SeedDataError(
                f"article {article.number}: price change {change.on} outside the history")
        rows = [(article.number, store, start, switch, _money(change.old_price), "REGULAR"),
                (article.number, store, switch, None, _money(article.price), "REGULAR")]
    for action in src.central_actions:
        if action.article == article.number:
            rows.append((article.number, store, action.valid_from, action.valid_to,
                         _money(action.price), "PROMO"))
    return rows


def wws_tables(src: Sources, demo_date: date) -> list[Table]:
    arts = src.articles
    return [
        _table("wws.season", "season_code, label, start_date, end_date",
               ((s.code, s.label, s.start, s.end) for s in src.seasons)),
        _table("wws.article",
               "article_number, article_id, gtin, name, category, category_label, "
               "pack_label, net_quantity, base_unit, vat_pct, cost_net, price_bound, "
               "season_code, listed_since, sort_order",
               ((a.number, a.article_id, a.gtin, a.name, a.category, CATEGORIES[a.category],
                 a.pack, a.qty, a.unit, a.vat, _money(a.cost), a.price_bound, a.season,
                 a.listed, sort_order) for sort_order, a in enumerate(arts, start=1))),
        _table("wws.article_price", "article_number, store_id, regular_price",
               ((a.number, s, _money(a.price)) for s in STORES for a in arts)),
        _table("wws.price_history",
               "article_number, store_id, valid_from, valid_to, price, kind",
               (row for s in STORES for a in arts
                for row in _price_history_rows(src, a, s, demo_date))),
        _table("wws.price_action",
               "action_id, article_number, store_id, kind, regular_price, action_price, "
               "pct_shown, ref30, valid_from, valid_to, proposal_id, reason_code, "
               "originator, approver, created_at",
               ((central_action_id(c, s), c.article, s, "CENTRAL",
                 _money(src.article(c.article).price), _money(c.price), c.pct_shown,
                 _money(c.ref30), c.valid_from, c.valid_to, None, c.reason_code,
                 CENTRAL_ORIGINATOR, None, c.valid_from)
                for s in STORES for c in src.central_actions)),
        _table("wws.sales_plan", "article_number, store_id, plan_week",
               ((a.number, s, a.plan) for s in STORES for a in arts)),
        _table("wws.sales_daily", "article_number, store_id, day, units",
               ((a.number, s, day, units) for s in STORES for a in arts
                for day, units in daily_units(a, demo_date))),
        _table("wws.stock", "article_number, store_id, on_hand",
               ((a.number, s, a.stock) for s in STORES for a in arts)),
        _table("wws.inbound_delivery",
               "delivery_id, article_number, store_id, expected_on, quantity",
               ((f"DL-{s}-{a.number}-{a.next_delivery.expected_on:%Y%m%d}", a.number, s,
                 a.next_delivery.expected_on, a.next_delivery.quantity)
                for s in STORES for a in arts if a.next_delivery is not None)),
    ]


def loyalty_tables(src: Sources, demo_date: date) -> list[Table]:
    prog = src.program
    seeded_at = history_start(demo_date)
    purchases = [p for m in src.members for p in member_purchases(src, m, demo_date)]
    return [
        _table("loyalty.program",
               "program_id, program_name, display_name, account_type, currency_id, "
               "currency_name, base_promotion_id, earn_eur_per_point",
               [(prog.program_id, prog.name, prog.display, prog.account_type,
                 prog.currency_id, prog.currency_name, prog.base_promotion_id,
                 _money(prog.earn_eur_per_point))]),
        _table("loyalty.article_ref",
               "article_number, article_id, name, category, points_eligible, "
               "coupon_eligible",
               ((a.number, a.article_id, a.name, a.category, not a.price_bound,
                 not a.price_bound) for a in src.articles)),
        _table("loyalty.tag_vocabulary", "tag, label_de", src.tags.items()),
        _table("loyalty.member",
               "member_id, program_id, customer_ref, persona_key, persona_label, "
               "anonymous, salutation, status, is_fictional, created_at, segment_label",
               ((m.member_id, prog.program_id, m.customer_ref, m.key, m.persona,
                 m.anonymous, m.salutation, "ACTIVE", True, seeded_at, m.segment)
                for m in src.members)),
        _table("loyalty.card", "card_value, member_id, card_type, status, issued_at",
               ((m.card, m.member_id, m.card_type, "ACTIVE", seeded_at)
                for m in src.members)),
        _table("loyalty.consent",
               "member_id, offers, profiling, digital_receipt, policy_version, "
               "changed_at, source",
               ((m.member_id, m.offers, m.profiling, False, POLICY_VERSION, seeded_at,
                 "seed") for m in src.members)),
        _table("loyalty.member_tag", "member_id, tag, source, weight",
               ((m.member_id, t, "EXPLICIT", Decimal("1.00"))
                for m in src.members for t in m.tags)),
        _table("loyalty.account",
               "account_id, member_id, program_id, account_type, balance",
               ((m.account_id, m.member_id, prog.program_id, prog.account_type,
                 Decimal("0.00")) for m in src.members)),
        _table("loyalty.purchase",
               "purchase_transaction_id, member_id, receipt_number, location, "
               "transaction_type, closed_at, total_eur, points_earned, is_seed, reported_at",
               ((p.tx_id, p.member.member_id, p.receipt_number, SEED_LOCATION, "SALE",
                 p.closed_at, p.total, Decimal("0.00"), True, p.closed_at)
                for p in purchases)),
        _table("loyalty.purchase_line",
               "purchase_transaction_id, position_id, article_number, category, "
               "item_count, effective_value_eur",
               ((p.tx_id, line.position_id, line.article.number, line.article.category,
                 line.qty, line.value)
                for p in purchases if p.member.profiling for line in p.lines)),
        _table("loyalty.article_week_stats",
               "article_number, week_start, member_purchases, distinct_members",
               ((a.number, start, mp, dm) for a in src.articles
                for start, (mp, dm) in zip(week_starts(demo_date),
                                           cardholder_week_stats(a), strict=True))),
    ]


def pos_tables() -> list[Table]:
    return [_table("pos.till", "till_id, store_id, location, kind, active",
                   ((t.till_id, t.store_id, t.location, t.kind, True) for t in TILLS))]


# --------------------------------------------------------------------- rendering


def sql_literal(value: SqlValue) -> str:
    match value:
        case None:
            return "null"
        case bool():
            return "true" if value else "false"
        case int():
            return str(value)
        case Decimal():
            return format(value, "f")
        case datetime():
            return _quote(value.isoformat(sep=" "))
        case date():
            return _quote(value.isoformat())
        case uuid.UUID():
            return _quote(str(value))
        case str():
            return _quote(value)
    raise TypeError(f"no SQL literal for {type(value).__name__}")


def _quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def render_insert(table: Table, conflict: str = "") -> str:
    rows = ",\n".join("  (" + ", ".join(sql_literal(v) for v in row) + ")"
                      for row in table.rows)
    suffix = f"\n{conflict}" if conflict else ""
    return f"insert into {table.name} ({', '.join(table.columns)}) values\n{rows}{suffix};"


def _render_file(name: str, schema: str, demo_date: date, statements: Sequence[str]) -> str:
    header = (
        f"-- {name}: seed of schema {schema} for demo date {demo_date.isoformat()}.\n"
        "-- Generated by postgres/gen_seed.py (data/*.yaml, tills of spec 5.7); do not edit.\n"
        "-- Idempotent (spec 5.7); run as DB admin after 00..40:\n"
        f"--   psql -X -v ON_ERROR_STOP=1 [-v role_prefix=gpos] -d gpos -f {name}\n"
        "\\encoding UTF8\n"
        "\\if :{?role_prefix}\n\\else\n\\set role_prefix gpos\n\\endif\n"
        f"\\set r_{schema} :role_prefix _{schema}\n\n"
        "begin;\n"
        f"set local role :\"r_{schema}\";\n\n")
    return header + "\n\n".join(statements) + "\n\ncommit;\n"


def _truncate(tables: Iterable[str]) -> str:
    return "truncate " + ", ".join(tables) + " cascade;"


# 5.7: the loyalty seed also empties points_ledger, coupon and offer (UC1 seeds none);
# cascade additionally clears loyalty.membership_assignment (runtime data).
LOYALTY_EMPTY = ("loyalty.points_ledger", "loyalty.coupon", "loyalty.offer")
TILL_UPSERT = ("on conflict (till_id) do update set store_id = excluded.store_id,\n"
               "  location = excluded.location, kind = excluded.kind, "
               "active = excluded.active")


def render_seed(src: Sources, demo_date: date) -> dict[str, str]:
    """File name -> SQL text of the three seed files."""
    wws = wws_tables(src, demo_date)
    loyalty = loyalty_tables(src, demo_date)
    return {
        "90-seed-wws.sql": _render_file(
            "90-seed-wws.sql", "wws", demo_date,
            [_truncate(t.name for t in wws)] + [render_insert(t) for t in wws if t.rows]),
        "91-seed-loyalty.sql": _render_file(
            "91-seed-loyalty.sql", "loyalty", demo_date,
            [_truncate([t.name for t in loyalty] + list(LOYALTY_EMPTY))]
            + [render_insert(t) for t in loyalty if t.rows]),
        "92-seed-pos.sql": _render_file(
            "92-seed-pos.sql", "pos", demo_date,
            [render_insert(t, TILL_UPSERT) for t in pos_tables()]),
    }


# --------------------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the UC1 seed SQL (spec 5.7).")
    parser.add_argument("--demo-date", required=True, type=date.fromisoformat,
                        help="business date D, e.g. 2027-02-16 (GPOS_DEMO_DATE)")
    parser.add_argument("--out", required=True, type=Path, help="output directory")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR,
                        help="directory with the YAML sources (default: data/)")
    args = parser.parse_args(argv)
    try:
        files = render_seed(load_sources(args.data_dir), args.demo_date)
    except SeedDataError as exc:
        print(f"gen_seed: {exc}", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        path = args.out / name
        path.write_text(text, encoding="utf-8")
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
