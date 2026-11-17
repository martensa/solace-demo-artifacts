"""Fixtures of the gpos-pos tests (WP-E, UC1-BUILD-SPEC 13.1).

WWS and loyalty are stub gRPC servers built only from the Showcase protos (the POS
talks to them exactly as to the real services):

* ``StubWws``: ``GetArticle``/``GetEffectivePrice`` from ``data/articles.yaml``;
  ``actions[article_number] = (source, price, action_id)`` overrides the regular price.
* ``StubLoyalty``: ``ResolveMembership`` for the cards of ``data/personas.yaml`` (all
  active), ``CLUB-SPERRE`` blocked, ``CLUB-FEHLER`` answers ``LOY-002``; every other
  card is ``MEMBERSHIP_STATUS_UNKNOWN``. ``ReportPurchase`` requests are recorded.

``pos_app`` runs the real service (``create(settings, bus, db)``) on the seeded scratch
DB with gRPC on a free port and a ``MemoryBus``; it needs the markers ``db`` and
``gebit``. ``Kasse`` drives a till through the GEBIT gRPC API like the BFF does.
"""

from __future__ import annotations

import socket
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import grpc
import pytest
import yaml
from google.protobuf import descriptor_pool, json_format
from google.protobuf.message import Message

from gposdemo.common import grpcutil
from gposdemo.common.bus import MemoryBus, Published
from gposdemo.common.config import Settings
from gposdemo.common.db import Db
from gposdemo.common.descriptors import LOYALTY_SVC, PURCHASE_SVC, WWS_SVC, Types
from gposdemo.common.jsonutil import proto_dict
from gposdemo.common.money import to_bdecimal, to_money
from gposdemo.pos import PosApp, create

DATA = Path(__file__).resolve().parents[3] / "data"
WWS_DT = "de.showcase.wws.v1.datatype"
LOY_DT = "de.showcase.loyalty.v1.datatype"
ACTIVE = "MEMBERSHIP_STATUS_ACTIVE"


def load_articles() -> dict[str, dict[str, Any]]:
    """``data/articles.yaml`` by article number."""
    rows = yaml.safe_load((DATA / "articles.yaml").read_text(encoding="utf-8"))
    return {str(a["number"]): a for a in rows}


def load_cards() -> dict[str, str]:
    """Card -> membership id from ``data/personas.yaml``."""
    doc = yaml.safe_load((DATA / "personas.yaml").read_text(encoding="utf-8"))
    return {m["card"]: m["id"] for m in doc["members"]}


ARTICLES = load_articles()


def article_id(number: str) -> str:
    """GEBIT article id of an article number (``ID100001``)."""
    return f"ID{number}"


class StubWws:
    """``MerchandiseService`` stub: master data and prices of ``data/articles.yaml``."""

    def __init__(self, types: Types):
        self.types = types
        self.by_id = {article_id(n): a for n, a in ARTICLES.items()}
        self.actions: dict[str, tuple[str, Decimal, str]] = {}
        self.price_calls: list[tuple[str, str]] = []

    def GetArticle(self, request: Any, context: grpc.ServicerContext) -> Message:
        art = self.by_id.get(request.article_id)
        if art is None:
            grpcutil.abort(context, grpc.StatusCode.NOT_FOUND, "WWS-001",
                           f"Artikel {request.article_id} unbekannt")
        body = {"articleNumber": str(art["number"]), "articleId": article_id(str(art["number"])),
                "gtin": str(art["gtin"]), "name": art["name"], "category": art["cat"],
                "vatPercent": to_bdecimal(Decimal(str(art["vat"])))}
        return json_format.ParseDict(body, self.types.new(f"{WWS_DT}.Article"))

    def GetEffectivePrice(self, request: Any, context: grpc.ServicerContext) -> Message:
        self.price_calls.append((request.article_number, request.store_id))
        art = ARTICLES.get(request.article_number)
        if art is None:
            grpcutil.abort(context, grpc.StatusCode.NOT_FOUND, "WWS-001", "Artikel unbekannt")
        regular = Decimal(str(art["price"]))
        source, price, action = self.actions.get(request.article_number,
                                                 ("REGULAR", regular, ""))
        body = {"articleNumber": request.article_number, "storeId": request.store_id,
                "price": to_money(price), "regularPrice": to_money(regular),
                "source": f"PRICE_SOURCE_{source}", "actionId": action}
        return json_format.ParseDict(body, self.types.new(f"{WWS_DT}.EffectivePrice"))


class StubLoyalty:
    """``LoyaltyService`` stub: card resolution and recorded purchase reports."""

    def __init__(self, types: Types):
        self.types = types
        self.cards = {card: (mid, ACTIVE) for card, mid in load_cards().items()}
        self.cards["CLUB-SPERRE"] = ("M-1999", "MEMBERSHIP_STATUS_BLOCKED")
        self.resolved: list[dict[str, Any]] = []
        self.reports: list[dict[str, Any]] = []

    def ResolveMembership(self, request: Any, context: grpc.ServicerContext) -> Message:
        self.resolved.append(proto_dict(request))
        value = request.membership_identification_value
        if value == "CLUB-FEHLER":
            grpcutil.abort(context, grpc.StatusCode.NOT_FOUND, "LOY-002", "Mitglied unbekannt")
        mid, status = self.cards.get(value, ("", "MEMBERSHIP_STATUS_UNKNOWN"))
        body = {"membershipIdentificationValue": value, "membershipId": mid,
                "programId": "POINTS-ID", "programName": "POINTS", "verified": bool(mid),
                "status": status}
        return json_format.ParseDict(body, self.types.new(f"{LOY_DT}.MembershipResolution"))

    def ReportPurchase(self, request: Any, context: grpc.ServicerContext) -> Message:
        self.reports.append({"header": proto_dict(request.header),
                             "purchase": proto_dict(request.purchase)})
        return self.types.new("google.protobuf.Empty")


@dataclass
class Stub:
    """A running stub server."""

    impl: Any
    server: grpc.Server

    @property
    def target(self) -> str:
        return f"localhost:{grpcutil.bound_port(self.server)}"


def _serve(pool: descriptor_pool.DescriptorPool, service: str, impl: Any) -> Stub:
    server = grpcutil.serve(pool, service, impl, 0, workers=4)
    server.start()
    return Stub(impl, server)


@pytest.fixture(scope="session")
def showcase_types(showcase_pool: descriptor_pool.DescriptorPool) -> Types:
    return Types(showcase_pool)


@pytest.fixture(scope="session")
def wws_stub(showcase_pool: descriptor_pool.DescriptorPool, showcase_types: Types
             ) -> Iterator[Stub]:
    stub = _serve(showcase_pool, WWS_SVC, StubWws(showcase_types))
    yield stub
    stub.server.stop(0)


@pytest.fixture(scope="session")
def loyalty_stub(showcase_pool: descriptor_pool.DescriptorPool, showcase_types: Types
                 ) -> Iterator[Stub]:
    stub = _serve(showcase_pool, LOYALTY_SVC, StubLoyalty(showcase_types))
    yield stub
    stub.server.stop(0)


def dead_target() -> str:
    """``localhost:<port>`` where nothing listens."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return f"127.0.0.1:{sock.getsockname()[1]}"


@pytest.fixture(scope="session")
def pos_db(scratch_db: Any) -> Iterator[Db]:
    """Pool logged in as the pos role of the seeded scratch DB."""
    db = scratch_db.db("pos", max_size=5)
    yield db
    db.close()


@pytest.fixture(scope="session")
def make_pos_settings(make_settings: Callable[..., Settings], wws_stub: Stub,
                      loyalty_stub: Stub) -> Callable[..., Settings]:
    """Settings of service ``pos`` against the stubs, gRPC on a free port."""

    def make(**env: str) -> Settings:
        base = {"GRPC_PORT": "0", "WWS_GRPC": wws_stub.target,
                "LOYALTY_GRPC": loyalty_stub.target}
        return make_settings("pos", **{**base, **env})

    return make


@pytest.fixture(scope="session")
def pos_bus() -> MemoryBus:
    return MemoryBus()


@pytest.fixture(scope="session")
def pos_app(make_pos_settings: Callable[..., Settings], pos_bus: MemoryBus, pos_db: Db
            ) -> Iterator[PosApp]:
    """The real ``gpos-pos`` (gRPC + relay), MCP not served."""
    app = create(make_pos_settings(), pos_bus, pos_db)
    app.start()
    yield app
    app.stop()


@dataclass
class Kasse:
    """Drives one till through the GEBIT gRPC API (like the BFF facade)."""

    client: grpcutil.Client
    bus: MemoryBus
    location: str
    traces: list[str] = field(default_factory=list)

    def _header(self) -> dict[str, str]:
        trace = f"kasse-99-{uuid.uuid4().hex[:8]}"
        self.traces.append(trace)
        return {"traceId": trace}

    def call(self, method: str, body: dict[str, Any]) -> Message:
        return self.client.call(method, {"header": self._header(), **body})

    def new(self) -> str:
        reply = self.call("CreatePurchaseTransaction", {
            "location": self.location, "employeeId": "booth", "cashdrawerId": "99"})
        return reply.purchase_transaction_id

    def scan(self, tx_id: str, number: str, count: int = 1) -> None:
        self.call("AddArticle", {
            "purchaseTransactionId": tx_id, "articleId": article_id(number), "itemCount": count,
            "capturingInformation": {"inputMethod": "SCANNER", "inputType": "EAN13",
                                     "inputValue": str(ARTICLES[number]["gtin"])}})

    def card(self, tx_id: str, card: str) -> None:
        self.call("AssignLoyaltyMembership", {
            "purchaseTransactionId": tx_id, "membershipIdentificationValue": card,
            "capturingInformation": {"inputMethod": "SCANNER", "inputValue": card}})

    def void(self, tx_id: str, position_id: str) -> None:
        self.call("VoidArticlePosition", {"purchaseTransactionId": tx_id,
                                          "positionId": position_id})

    def start_payment(self, tx_id: str) -> None:
        self.call("StartPaymentProcess", {"purchaseTransactionId": tx_id})

    def cash(self, tx_id: str, euros: str) -> None:
        self.call("CreateCashPayment", {
            "purchaseTransactionId": tx_id, "amount": to_money(Decimal(euros)),
            "clientId": "kasse-99", "clientTransactionId": str(uuid.uuid4())})

    def pay(self, tx_id: str, euros: str) -> None:
        self.start_payment(tx_id)
        self.cash(tx_id, euros)

    def cancel(self, tx_id: str) -> None:
        self.call("CancelPurchaseTransaction", {
            "purchaseTransactionId": tx_id, "cancellationReason": "Kunde verzichtet",
            "cancellationReasonCode": "CUSTOMER"})

    def events(self, tx_id: str, count: int, timeout: float = 5.0) -> list[Published]:
        """The first ``count`` GEBIT events of ``tx_id`` in publish order."""
        found = self.bus.wait_for(f"gebit/rp/purchase/v2/*/*/*/*/*/*/{tx_id}", count, timeout)
        return found[:count]


@pytest.fixture(scope="session")
def pos_client(pos_app: PosApp, gebit_pool: descriptor_pool.DescriptorPool
               ) -> Iterator[grpcutil.Client]:
    client = grpcutil.Client(gebit_pool, PURCHASE_SVC, f"localhost:{pos_app.grpc_port}")
    yield client
    client.close()


@pytest.fixture
def kasse(pos_client: grpcutil.Client, pos_bus: MemoryBus, settings: Settings) -> Kasse:
    """Test till 99 (store 199, never SAM)."""
    return Kasse(pos_client, pos_bus, settings.test_location)
