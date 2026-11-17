"""Fakes of the services the BFF talks to, strictly over their contracts.

* WWS and Loyalty: real gRPC servers (``grpcutil.serve`` on port 0) built from the
  Showcase descriptor set, with recording fake implementations (4.3, 4.4).
* Engine HTTP API (11.8) and POS admin (11.8): ``httpx.MockTransport`` handlers that
  answer like the contract and record every request.
* GEBIT POS (4.2): a gRPC server from the GEBIT descriptor sets (tests marked
  ``gebit`` only).

Test data is the fictional master data of the spec (GEBIT Ente 9,99 / 7,99, ...).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

import grpc
import httpx
import pytest
from fastapi.testclient import TestClient
from google.protobuf import descriptor_pool, json_format

from gposdemo.common.bus import MemoryBus
from gposdemo.common.clock import demo_at, offset_ts_json
from gposdemo.common.config import Settings
from gposdemo.common.descriptors import LOYALTY_SVC, PURCHASE_SVC, WWS_SVC, Types
from gposdemo.common.grpcutil import abort, bound_port, serve
from gposdemo.common.money import to_money
from gposdemo.ui import Service, create
from gposdemo.ui.bff import Gateways
from gposdemo.ui.clients import EngineClient, LoyaltyClient, PosAdminClient, WwsClient
from gposdemo.ui.facade import PosFacade


# --------------------------------------------------------------------- test data
GEBIT_EVENT_TYPE = "type.googleapis.com/de.gebit.rp.purchase.purchase.v2.event."


def gebit_payload(event: str, **fields: Any) -> dict[str, Any]:
    """A GEBIT event as ``gpos-pos`` publishes it: proto3 JSON of ``Any`` (4.2)."""
    return {"@type": GEBIT_EVENT_TYPE + event, **fields}


def wws_article(number: str, gtin: str, name: str, category: str, label: str, pack: str,
                price: str, *, regular: str | None = None,
                source: str = "PRICE_SOURCE_REGULAR", action_id: str = "",
                valid_to: dict[str, Any] | None = None) -> dict[str, Any]:
    """A ``datatype.Article`` as proto3 JSON (what ``ListArticles`` returns)."""
    effective = {"articleNumber": number, "storeId": "101", "price": to_money(Decimal(price)),
                 "regularPrice": to_money(Decimal(regular or price)), "source": source}
    if action_id:
        effective["actionId"] = action_id
    if valid_to:
        effective["validTo"] = valid_to
    return {"articleNumber": number, "articleId": f"ID{number}", "gtin": gtin, "name": name,
            "category": category, "categoryLabel": label, "packLabel": pack,
            "price": effective}


@pytest.fixture(scope="session")
def booth_valid_to(settings: Settings) -> dict[str, Any]:
    """Valid-to of a booth action: Di 23.02. 20:00 (6.7)."""
    return offset_ts_json(demo_at(settings, date(2027, 2, 23), 20))


@pytest.fixture
def articles(booth_valid_to: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        wws_article("100004", "2099100000049", "Bio-Bananen", "obst_gemuese",
                    "Obst & Gemüse", "1 kg", "1.99"),
        wws_article("100001", "2099100000018", "GEBIT Ente (Quietscheente gelb)",
                    "spielwaren_geschenke", "Spielwaren & Geschenke", "1 Stück", "7.99",
                    regular="9.99", source="PRICE_SOURCE_BOOTH_ACTION",
                    action_id="PA-270216-0003", valid_to=booth_valid_to),
        wws_article("100010", "2099100000100", "Vollmilch 3,5 %", "molkerei_fruehstueck",
                    "Molkerei & Frühstück", "1 l", "1.19"),
    ]


# --------------------------------------------------------------------- gRPC fakes
class FakeWws:
    """``MerchandiseService``: ``ListArticles`` and ``ResetDemoState`` (recording)."""

    def __init__(self, pool: descriptor_pool.DescriptorPool, articles: list[dict[str, Any]]):
        self.types = Types(pool)
        self.articles = articles
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_reset = False
        self.while_listing: Callable[[], None] | None = None  # runs inside ListArticles

    def _record(self, name: str, request: Any) -> None:
        self.calls.append((name, json_format.MessageToDict(request)))

    def ListArticles(self, request: Any, context: grpc.ServicerContext) -> Any:
        self._record("ListArticles", request)
        if self.while_listing is not None:
            self.while_listing()
        reply = self.types.new("de.showcase.wws.v1.datatype.ArticleList")
        json_format.ParseDict({"articles": self.articles}, reply)
        return reply

    def ResetDemoState(self, request: Any, context: grpc.ServicerContext) -> Any:
        self._record("ResetDemoState", request)
        if self.fail_reset:
            abort(context, grpc.StatusCode.UNAVAILABLE, "WWS-099", "test failure")
        return self.types.new("google.protobuf.Empty")


class FakeLoyalty:
    """``LoyaltyService``: ``ResetDemoState`` (recording)."""

    def __init__(self, pool: descriptor_pool.DescriptorPool):
        self.types = Types(pool)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def ResetDemoState(self, request: Any, context: grpc.ServicerContext) -> Any:
        self.calls.append(("ResetDemoState", json_format.MessageToDict(request)))
        return self.types.new("google.protobuf.Empty")


@dataclass
class GrpcFake:
    impl: Any
    server: grpc.Server
    target: str


def start_fake(pool: descriptor_pool.DescriptorPool, service: str, impl: Any) -> GrpcFake:
    server = serve(pool, service, impl, 0, workers=4)
    server.start()
    return GrpcFake(impl, server, f"127.0.0.1:{bound_port(server)}")


@pytest.fixture
def wws_fake(showcase_pool: descriptor_pool.DescriptorPool,
             articles: list[dict[str, Any]]) -> Iterator[GrpcFake]:
    fake = start_fake(showcase_pool, WWS_SVC, FakeWws(showcase_pool, articles))
    yield fake
    fake.server.stop(0)


@pytest.fixture
def loyalty_fake(showcase_pool: descriptor_pool.DescriptorPool) -> Iterator[GrpcFake]:
    fake = start_fake(showcase_pool, LOYALTY_SVC, FakeLoyalty(showcase_pool))
    yield fake
    fake.server.stop(0)


# --------------------------------------------------------------------- HTTP fakes
@dataclass
class Recorded:
    method: str
    path: str
    params: dict[str, str]
    body: Any


@dataclass
class HttpFake:
    """Base of the HTTP fakes: routes ``(method, path) -> (status, json)``."""

    routes: dict[tuple[str, str], tuple[int, Any]] = field(default_factory=dict)
    requests: list[Recorded] = field(default_factory=list)
    down: bool = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        body = json.loads(request.content) if request.content else None
        self.requests.append(Recorded(request.method, request.url.path,
                                      dict(request.url.params), body))
        status, answer = self.routes.get((request.method, request.url.path),
                                         (404, {"error": "not found"}))
        return httpx.Response(status, json=answer)

    def paths(self, method: str | None = None) -> list[str]:
        return [r.path for r in self.requests if method is None or r.method == method]


PENDING = {"proposal_id": "GP-270216-0003", "status": "pending", "review_id": "GR-270216-0007",
           "approval": {"apply_calls": 0, "checked_at": "2027-02-16T10:00:01+01:00",
                        "first_apply_at": None}}


@pytest.fixture
def engine_fake() -> HttpFake:
    return HttpFake(routes={
        ("GET", "/health"): (200, {"status": "ok", "db": True, "bus": True}),
        ("GET", "/api/state"): (200, {"review": {"review_id": "GR-270216-0007",
                                                 "status": "proposed"},
                                      "proposal": PENDING,
                                      "counts": {"reviews": 1, "proposals": 1, "approved": 0}}),
        ("GET", "/api/proposals/GP-270216-0003"): (200, PENDING),
        ("POST", "/api/reset"): (200, {"reviews": 1, "proposals": 1}),
        ("POST", "/api/sam-error"): (200, {"ok": True}),
    })


# GET /admin/till/01 as gpos-pos answers it (WP-E: German price labels, effectual lines)
OPEN_TX = {"tx_id": "5b1f0c2e-8d1e-4a43-9a51-0c7a2f0e1b11", "till": "01", "store_id": "101",
           "status": "OPEN", "receipt_number": "10101270216000042", "membership_id": "M-1001",
           "total": "11,98", "offset": 6,
           "lines": [{"position_id": "p-1", "line_no": 1, "article_number": "100001",
                      "article_id": "ID100001", "description": "GEBIT Ente (Quietscheente gelb)",
                      "gtin": "2099100000018", "item_count": 1, "price": "9,99",
                      "regular_price": "9,99", "price_source": "REGULAR", "action_id": ""},
                     {"position_id": "p-2", "line_no": 2, "article_number": "100004",
                      "article_id": "ID100004", "description": "Bio-Bananen",
                      "gtin": "2099100000049", "item_count": 1, "price": "1,99",
                      "regular_price": "1,99", "price_source": "REGULAR", "action_id": ""}]}


@pytest.fixture
def pos_admin_fake() -> HttpFake:
    return HttpFake(routes={
        ("GET", "/admin/till/01"): (200, {"open_tx": OPEN_TX}),
        ("GET", "/admin/till/99"): (200, {"open_tx": None}),
        ("POST", "/admin/reset"): (200, {"status": "ok", "reset": 1}),
    })


# --------------------------------------------------------------------- the service
@dataclass
class Ui:
    """A started ``gpos-ui`` with its fakes."""

    svc: Service
    bus: MemoryBus
    client: TestClient
    wws: FakeWws
    loyalty: FakeLoyalty
    engine: HttpFake
    pos_admin: HttpFake

    def publish(self, topic: str, payload: dict[str, Any] | str) -> None:
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        self.bus.publish(topic, text)


def build_gateways(settings: Settings, showcase_pool: descriptor_pool.DescriptorPool,
                   wws: GrpcFake, loyalty: GrpcFake, engine: HttpFake, pos_admin: HttpFake,
                   facade: PosFacade | None = None) -> Gateways:
    return Gateways(
        facade=facade or PosFacade(settings, None, "GEBIT_DESCRIPTOR_SETS ist nicht gesetzt"),
        wws=WwsClient(showcase_pool, wws.target),
        loyalty=LoyaltyClient(showcase_pool, loyalty.target),
        engine=EngineClient("http://engine.test", transport=httpx.MockTransport(engine)),
        pos_admin=PosAdminClient("http://pos.test", transport=httpx.MockTransport(pos_admin)))


@pytest.fixture
def make_ui(settings: Settings, showcase_pool: descriptor_pool.DescriptorPool,
            wws_fake: GrpcFake, loyalty_fake: GrpcFake, engine_fake: HttpFake,
            pos_admin_fake: HttpFake) -> Iterator[Callable[..., Ui]]:
    """``make_ui(facade=None)``: a started UI on a MemoryBus with all fakes."""
    started: list[Ui] = []

    def make(facade: PosFacade | None = None) -> Ui:
        bus = MemoryBus()
        gateways = build_gateways(settings, showcase_pool, wws_fake, loyalty_fake,
                                  engine_fake, pos_admin_fake, facade)
        svc = create(settings, bus, gateways=gateways)
        svc.start()
        svc.bootstrap.join(5)
        ui = Ui(svc, bus, TestClient(svc.app), wws_fake.impl, loyalty_fake.impl, engine_fake,
                pos_admin_fake)
        started.append(ui)
        return ui

    yield make
    for ui in started:
        ui.client.close()
        ui.svc.stop()
        ui.bus.close()


@pytest.fixture
def ui(make_ui: Callable[..., Ui]) -> Ui:
    return make_ui()


# --------------------------------------------------------------------- GEBIT POS fake
class FakePos:
    """``PurchaseTransactionService`` (GEBIT 2.50.0 runtime descriptors): records the
    requests and answers like 4.2; ``fail`` maps a method to (status, code, text)."""

    def __init__(self, pool: descriptor_pool.DescriptorPool):
        self.types = Types(pool)
        self.pool = pool
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.fail: dict[str, tuple[grpc.StatusCode, str, str]] = {}

    def _handle(self, name: str, request: Any, context: grpc.ServicerContext) -> None:
        self.requests.append((name, json_format.MessageToDict(request,
                                                              descriptor_pool=self.pool)))
        if name in self.fail:
            status, code, text = self.fail[name]
            abort(context, status, code, text)

    def CreatePurchaseTransaction(self, request: Any, context: grpc.ServicerContext) -> Any:
        self._handle("CreatePurchaseTransaction", request, context)
        return self.types.new("de.gebit.rp.purchase.purchase.v2.datatype.PurchaseTransactionId",
                              purchase_transaction_id="5b1f0c2e-8d1e-4a43-9a51-0c7a2f0e1b11")

    def _empty(self, name: str, request: Any, context: grpc.ServicerContext) -> Any:
        self._handle(name, request, context)
        return self.types.new("google.protobuf.Empty")

    def AddArticle(self, request: Any, context: grpc.ServicerContext) -> Any:
        return self._empty("AddArticle", request, context)

    def AssignLoyaltyMembership(self, request: Any, context: grpc.ServicerContext) -> Any:
        return self._empty("AssignLoyaltyMembership", request, context)

    def CreateCashPayment(self, request: Any, context: grpc.ServicerContext) -> Any:
        return self._empty("CreateCashPayment", request, context)


@pytest.fixture
def pos_fake(gebit_pool: descriptor_pool.DescriptorPool) -> Iterator[GrpcFake]:
    fake = start_fake(gebit_pool, PURCHASE_SVC, FakePos(gebit_pool))
    yield fake
    fake.server.stop(0)
