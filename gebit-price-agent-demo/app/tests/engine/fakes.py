"""Test doubles of WP-F: WWS and loyalty answers from ``data/*.yaml`` (via
``postgres/gen_seed.py``), served by real gRPC servers on the Showcase protos.

The engine only talks to WWS and loyalty through ``showcase.wws.v1`` and
``showcase.loyalty.v1``; these stubs answer like the services of WP-C and WP-D for the
fictional master data, so the engine's gRPC clients and converters run for real.
"""

from __future__ import annotations

import importlib.util
import itertools
import statistics
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any
from zoneinfo import ZoneInfo

import grpc
from google.protobuf import descriptor_pool, json_format
from google.protobuf.message import Message

from gposdemo.common.clock import from_ts, offset_ts_json, real_now, ts_json
from gposdemo.common.db import Db
from gposdemo.common.descriptors import LOYALTY_SVC, WWS_SVC, Types
from gposdemo.common.grpcutil import abort, bound_port, serve
from gposdemo.common.jsonutil import canonical
from gposdemo.common.money import from_money, to_bdecimal, to_money
from gposdemo.engine import clients

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data"
GEN_SEED = ROOT / "postgres" / "gen_seed.py"
POLICY_FILE = ROOT / "policy" / "pricing-policy.yaml"
D = date(2027, 2, 16)
ZONE = ZoneInfo("Europe/Berlin")
WWS_DT = "de.showcase.wws.v1.datatype"
LOY_DT = "de.showcase.loyalty.v1.datatype"
EVENT_PREFIX = "type.googleapis.com/de.gebit.rp.purchase.purchase.v2.event."

ENTE, HASE, BANANEN, PRALINEN, GLUEHWEIN, MILCH = (
    "100001", "100002", "100004", "100008", "100009", "100010")
ESPRESSO, CREMA, TOAST, CROISSANTS, WASSER, KOCHBUCH = (
    "100012", "100013", "100016", "100017", "100021", "100028")


def gen_seed() -> ModuleType:
    """``postgres/gen_seed.py`` (a script of WP-B) as a module, loaded once."""
    name = "gpos_gen_seed_engine_tests"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, GEN_SEED)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FakeClock:
    """Injectable technical clock: ``clock()`` -> now; ``advance(seconds)``."""

    def __init__(self) -> None:
        self.now = real_now()

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@dataclass
class BoothAction:
    action_id: str
    number: str
    store: str
    price: Decimal
    valid_from: datetime
    valid_to: datetime
    proposal_id: str


@dataclass
class Showcase:
    """WWS and loyalty view of the fictional data on business date ``D``."""

    src: Any
    demo_date: date = D
    actions: dict[tuple[str, str], BoothAction] = field(default_factory=dict)
    by_proposal: dict[str, BoothAction] = field(default_factory=dict)
    requests: list[dict[str, Any]] = field(default_factory=list)
    fail_request: tuple[grpc.StatusCode, str] | None = None
    seq: int = 0

    def reset(self) -> None:
        self.actions.clear()
        self.by_proposal.clear()
        self.requests.clear()
        self.fail_request = None

    # ------------------------------------------------------------- WWS
    def article(self, number: str) -> Any:
        return self.src.article(number)

    def now(self) -> datetime:
        return datetime.combine(self.demo_date, real_now().astimezone(ZONE).time(), ZONE)

    def central(self, number: str) -> Any | None:
        return next((c for c in self.src.central_actions if c.article == number), None)

    def effective(self, number: str, store: str) -> tuple[Decimal, str, str, datetime | None]:
        """(price, source, action_id, valid_to) at business time now."""
        art, now = self.article(number), self.now()
        booth = self.actions.get((store, number))
        if booth is not None and booth.valid_from <= now < booth.valid_to:
            return booth.price, "BOOTH_ACTION", booth.action_id, booth.valid_to
        central = self.central(number)
        if central is not None and central.valid_from <= now < central.valid_to:
            return central.price, "CENTRAL_ACTION", f"PA-SEED-{number}", central.valid_to
        return art.regular_price_on(self.demo_date), "REGULAR", "", None

    def ref30(self, number: str) -> Decimal:
        art = self.article(number)
        days = [self.demo_date - timedelta(days=i) for i in range(31)]
        prices = [art.regular_price_on(day) for day in days]
        central = self.central(number)
        if central is not None and central.valid_from.date() <= self.demo_date:
            prices.append(central.price)
        return min(prices)

    def article_json(self, number: str, store: str) -> dict[str, Any]:
        art = self.article(number)
        price, source, action_id, valid_to = self.effective(number, store)
        regular = art.regular_price_on(self.demo_date)
        effective: dict[str, Any] = {
            "article_number": number, "store_id": store, "price": to_money(price),
            "regular_price": to_money(regular), "source": f"PRICE_SOURCE_{source}",
            "action_id": action_id, "ref30": to_money(self.ref30(number))}
        if valid_to is not None:
            effective["valid_to"] = offset_ts_json(valid_to)
        body: dict[str, Any] = {
            "article_number": number, "article_id": art.article_id, "gtin": art.gtin,
            "name": art.name, "category": art.category, "pack_label": art.pack,
            "net_quantity": to_bdecimal(art.qty, 3), "base_unit": art.unit,
            "vat_percent": to_bdecimal(art.vat), "cost_net": to_money(art.cost),
            "price_bound": art.price_bound, "season_code": art.season or "",
            "listed_since": art.listed.isoformat(), "price": effective,
            "stock_on_hand": art.stock}
        if art.price_change is not None:
            body["last_price_change"] = {"date": art.price_change.on.isoformat(),
                                         "old_price": to_money(art.price_change.old_price),
                                         "new_price": to_money(art.price)}
        return body

    def sales_json(self, number: str, store: str) -> dict[str, Any]:
        art = self.article(number)
        return {"article_number": number, "store_id": store,
                "as_of": (self.demo_date - timedelta(days=1)).isoformat(),
                "sold_7d": art.weekly[-1], "plan_7d": to_bdecimal(art.plan),
                "weekly_units": list(art.weekly), "stock_on_hand": art.stock,
                "listed_days": (self.demo_date - art.listed).days}

    def season_json(self, number: str) -> dict[str, Any]:
        art = self.article(number)
        season = next((s for s in self.src.seasons if s.code == art.season), None)
        if season is None:
            return {"article_number": number, "status": "none"}
        days = (season.end - self.demo_date).days
        status = ("before" if season.start > self.demo_date
                  else "ended" if days < 0 else "running")
        return {"article_number": number, "season_code": season.code,
                "season_label": season.label, "start_date": season.start.isoformat(),
                "end_date": season.end.isoformat(), "days_to_end": days, "status": status,
                "stock_on_hand": art.stock}

    def request_price_change(self, req: Any) -> dict[str, Any]:
        """``RequestPriceChange`` like WP-C: validation, idempotent per proposal id."""
        body = json_format.MessageToDict(req, preserving_proto_field_name=True)
        self.requests.append(body)
        if self.fail_request is not None:
            raise _Abort(*self.fail_request)
        known = self.by_proposal.get(req.proposal_id)
        if known is not None:
            return {"action_id": known.action_id, "created": False}
        number, store = req.article_number, req.store_id
        art = self.article(number)
        regular = art.regular_price_on(self.demo_date)
        new_price = from_money(req.new_price)
        if from_money(req.expected_regular_price) != regular:
            raise _Abort(grpc.StatusCode.ABORTED, "WWS-020")
        if new_price >= regular:
            raise _Abort(grpc.StatusCode.INVALID_ARGUMENT, "WWS-010")
        if art.price_bound:
            raise _Abort(grpc.StatusCode.FAILED_PRECONDITION, "WWS-012")
        if self.effective(number, store)[1] != "REGULAR":
            raise _Abort(grpc.StatusCode.FAILED_PRECONDITION, "WWS-011")
        self.seq += 1
        action = BoothAction(f"PA-{self.demo_date:%y%m%d}-{self.seq:04d}", number, store,
                             new_price, from_ts(req.valid_from),
                             from_ts(req.valid_to), req.proposal_id)
        self.actions[(store, number)] = action
        self.by_proposal[req.proposal_id] = action
        return {"action_id": action.action_id, "created": True}

    # ------------------------------------------------------------- loyalty
    def member(self, membership_id: str) -> Any | None:
        return next((m for m in self.src.members if m.member_id == membership_id), None)

    def profile_json(self, membership_id: str) -> dict[str, Any] | None:
        m = self.member(membership_id)
        if m is None:
            return None
        return {"membership_id": m.member_id, "persona_label": m.persona,
                "consent": {"offers": m.offers, "profiling": m.profiling,
                            "policy_version": "2027-01"},
                "segment_label": m.segment, "history_used": m.profiling}

    def purchase_days(self, membership_id: str, number: str) -> list[date]:
        m = self.member(membership_id)
        assert m is not None
        days = {d for rule in m.history if rule.article == number for d in rule.days()}
        return sorted(d for d in days if d < self.demo_date)

    def behaviour_json(self, membership_id: str, number: str) -> dict[str, Any] | None:
        m = self.member(membership_id)
        if m is None:
            return None
        weekly = [p for p, _ in gen_seed().cardholder_week_stats(self.article(number))]
        prior, last = sum(weekly[:4]) / 4, sum(weekly[4:]) / 4
        drop = Decimal(str(round((prior - last) / prior * 100, 1))) if prior else Decimal(0)
        body: dict[str, Any] = {"membership_id": m.member_id, "article_number": number,
                                "consent_profiling": m.profiling, "persona_label": m.persona,
                                "segment_label": m.segment, "cardholder_weekly": weekly,
                                "cardholder_drop_pct": to_bdecimal(drop, 1)}
        if not m.profiling:
            return {**body, "days_since_last": -1}
        days = self.purchase_days(membership_id, number)
        d8, d12 = self.demo_date - timedelta(days=56), self.demo_date - timedelta(days=84)
        window = [d for d in days if d >= d12]
        gaps = [(b - a).days for a, b in itertools.pairwise(window)]
        return {**body, "member_purchases_8w": sum(1 for d in days if d >= d8),
                "member_purchases_12w": len(window),
                "days_since_last": (self.demo_date - days[-1]).days if days else -1,
                "median_interval_days": int(statistics.median(gaps)) if gaps else 0}


class _Abort(Exception):
    def __init__(self, code: grpc.StatusCode, error_code: str):
        super().__init__(error_code)
        self.code, self.error_code = code, error_code


def _answer(types: Types, full_name: str, body: dict[str, Any]) -> Message:
    return json_format.ParseDict(body, types.new(full_name))


class FakeWws:
    """``MerchandiseService`` impl (GetArticle, GetSalesPerformance, GetSeasonInfo,
    RequestPriceChange)."""

    def __init__(self, showcase: Showcase, types: Types):
        self.showcase, self.types = showcase, types
        self.unavailable = False

    def _known(self, number: str, context: grpc.ServicerContext) -> None:
        if self.unavailable:
            context.abort(grpc.StatusCode.UNAVAILABLE, "wws down (test)")
        try:
            self.showcase.article(number)
        except ValueError:
            abort(context, grpc.StatusCode.NOT_FOUND, "WWS-001", "Artikel unbekannt")

    def GetArticle(self, request: Any, context: grpc.ServicerContext) -> Message:
        self._known(request.article_number, context)
        return _answer(self.types, f"{WWS_DT}.Article",
                       self.showcase.article_json(request.article_number, request.store_id))

    def GetSalesPerformance(self, request: Any, context: grpc.ServicerContext) -> Message:
        self._known(request.article_number, context)
        return _answer(self.types, f"{WWS_DT}.SalesPerformance",
                       self.showcase.sales_json(request.article_number, request.store_id))

    def GetSeasonInfo(self, request: Any, context: grpc.ServicerContext) -> Message:
        self._known(request.article_number, context)
        return _answer(self.types, f"{WWS_DT}.SeasonInfo",
                       self.showcase.season_json(request.article_number))

    def RequestPriceChange(self, request: Any, context: grpc.ServicerContext) -> Message:
        try:
            body = self.showcase.request_price_change(request)
        except _Abort as err:
            abort(context, err.code, err.error_code, "abgelehnt (Test)")
        return _answer(self.types, f"{WWS_DT}.PriceActionId", body)


class FakeLoyalty:
    """``LoyaltyService`` impl (GetMemberProfile, GetPurchaseBehaviour)."""

    def __init__(self, showcase: Showcase, types: Types):
        self.showcase, self.types = showcase, types

    def GetMemberProfile(self, request: Any, context: grpc.ServicerContext) -> Message:
        body = self.showcase.profile_json(request.membership_id)
        if body is None:
            abort(context, grpc.StatusCode.NOT_FOUND, "LOY-002", "Mitglied unbekannt")
        return _answer(self.types, f"{LOY_DT}.MemberProfile", body)

    def GetPurchaseBehaviour(self, request: Any, context: grpc.ServicerContext) -> Message:
        body = self.showcase.behaviour_json(request.membership_id, request.article_number)
        if body is None:
            abort(context, grpc.StatusCode.NOT_FOUND, "LOY-002", "Mitglied unbekannt")
        return _answer(self.types, f"{LOY_DT}.PurchaseBehaviour", body)


@dataclass
class Backends:
    """Running stub servers and their targets."""

    showcase: Showcase
    wws: FakeWws
    loyalty: FakeLoyalty
    wws_target: str
    loyalty_target: str
    servers: list[grpc.Server]

    def stop(self) -> None:
        for server in self.servers:
            server.stop(0)


def start_backends(pool: descriptor_pool.DescriptorPool, showcase: Showcase) -> Backends:
    types = Types(pool)
    wws, loyalty = FakeWws(showcase, types), FakeLoyalty(showcase, types)
    wws_server = serve(pool, WWS_SVC, wws, 0, workers=4)
    loyalty_server = serve(pool, LOYALTY_SVC, loyalty, 0, workers=4)
    wws_server.start()
    loyalty_server.start()
    return Backends(showcase, wws, loyalty, f"localhost:{bound_port(wws_server)}",
                    f"localhost:{bound_port(loyalty_server)}", [wws_server, loyalty_server])


# ------------------------------------------------------------------ facts (unit tests)
@dataclass(frozen=True)
class Facts:
    article: clients.ArticleFacts
    sales: clients.SalesFacts
    season: clients.SeasonFacts | None
    behaviour: clients.BehaviourFacts | None


def facts(showcase: Showcase, pool: descriptor_pool.DescriptorPool, number: str,
          store: str = "101", membership_id: str | None = None) -> Facts:
    """What the engine's clients make of the stub answers (proto round trip)."""
    types = Types(pool)
    article = clients.article_facts(
        _answer(types, f"{WWS_DT}.Article", showcase.article_json(number, store)), ZONE)
    sales = clients.sales_facts(
        _answer(types, f"{WWS_DT}.SalesPerformance", showcase.sales_json(number, store)))
    season = clients.season_facts(
        _answer(types, f"{WWS_DT}.SeasonInfo", showcase.season_json(number)))
    behaviour = None
    if membership_id is not None:
        body = showcase.behaviour_json(membership_id, number)
        assert body is not None
        behaviour = clients.behaviour_facts(
            _answer(types, f"{LOY_DT}.PurchaseBehaviour", body))
    return Facts(article, sales, season, behaviour)


# ------------------------------------------------------------------ pos baskets
TILLS = {"01": ("101", "Root.DE.999.101.01"), "98": ("199", "Root.DE.999.199.98"),
         "99": ("199", "Root.DE.999.199.99")}


@dataclass
class Basket:
    tx_id: str
    till: str
    store: str
    positions: list[str]


class PosWriter:
    """Writes baskets into ``pos`` as ``gpos-pos`` would (role ``…_pos``)."""

    def __init__(self, db: Db, showcase: Showcase):
        self.db, self.showcase = db, showcase

    def basket(self, numbers: list[str], *, till: str = "01", status: str = "CLOSED",
               membership_id: str | None = None) -> Basket:
        store, location = TILLS[till]
        tx_id = str(uuid.uuid4())
        positions = [str(uuid.uuid4()) for _ in numbers]
        with self.db.tx() as conn:
            conn.execute(
                "insert into pos.basket (tx_id, till_id, store_id, location, status, "
                "membership_id) values (%s, %s, %s, %s, %s, %s)",
                (tx_id, till, store, location, status, membership_id))
            for line_no, (number, position) in enumerate(zip(numbers, positions,
                                                             strict=True), 1):
                art = self.showcase.article(number)
                price, source, action_id, _ = self.showcase.effective(number, store)
                conn.execute(
                    "insert into pos.basket_line (tx_id, position_id, line_no, "
                    "article_number, article_id, name, gtin, category, item_count, "
                    "unit_price, regular_price, price_source, action_id, vat_pct) "
                    "values (%s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s, %s, %s, %s)",
                    (tx_id, position, line_no, number, art.article_id, art.name, art.gtin,
                     art.category, price, art.regular_price_on(self.showcase.demo_date),
                     source, action_id or None, art.vat))
        return Basket(tx_id, till, store, positions)

    def void(self, basket: Basket, index: int) -> None:
        with self.db.tx() as conn:
            conn.execute("update pos.basket_line set voided = true where tx_id = %s and "
                         "position_id = %s", (basket.tx_id, basket.positions[index]))

    def close(self, basket: Basket) -> None:
        with self.db.tx() as conn:
            conn.execute("update pos.basket set status = 'CLOSED' where tx_id = %s",
                         (basket.tx_id,))


def gebit_event(name: str, tx_id: str, offset: int, at: datetime, **body: Any) -> str:
    """A purchase event as SAM delivers it: proto3 JSON of ``Any``, keys sorted (7.3)."""
    return canonical({"@type": EVENT_PREFIX + name, "header": {"eventTimestamp": ts_json(at)},
                      "metadata": {"offset": str(offset), "creationTimestamp": ts_json(at)},
                      "purchaseTransactionId": tx_id, **body})
