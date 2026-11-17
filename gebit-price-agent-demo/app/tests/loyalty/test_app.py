"""``create(settings, bus, db)`` wiring of gpos-loyalty without a database (2.3, 2.4, 4.1)."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import grpc
import pytest
from google.protobuf import descriptor_pool
from grpc_health.v1 import health_pb2, health_pb2_grpc
from starlette.testclient import TestClient

from gposdemo.common import grpcutil, mcputil
from gposdemo.common.bus import MemoryBus
from gposdemo.common.config import Settings
from gposdemo.common.db import Db
from gposdemo.common.descriptors import LOYALTY_SVC
from gposdemo.loyalty import LoyaltyApp, create
from tests.loyalty.helpers import rpc_error

UNREACHABLE_DSN = "host=127.0.0.1 port=1 dbname=none user=none connect_timeout=1"
IMPLEMENTED = ("ResolveMembership", "GetMemberProfile", "GetPurchaseBehaviour",
               "ReportPurchase", "ChangeConsent", "ResetDemoState")


@pytest.fixture
def offline_app(make_settings: Callable[..., Settings], memory_bus: MemoryBus
                ) -> Iterator[LoyaltyApp]:
    db = Db(UNREACHABLE_DSN, application_name="ut-loyalty")
    app = create(make_settings("loyalty", GRPC_PORT="0"), memory_bus, db)
    app.start()
    yield app
    app.stop()
    db.close()


@pytest.fixture
def offline_client(offline_app: LoyaltyApp, showcase_pool: descriptor_pool.DescriptorPool
                   ) -> Iterator[grpcutil.Client]:
    c = grpcutil.Client(showcase_pool, LOYALTY_SVC, f"localhost:{offline_app.grpc_port}")
    yield c
    c.close()


def test_impl_has_one_method_per_implemented_rpc(offline_app: LoyaltyApp,
                                                 showcase_pool: descriptor_pool.DescriptorPool
                                                 ) -> None:
    _, implemented = grpcutil.service_handler(showcase_pool, LOYALTY_SVC, offline_app.impl)
    assert sorted(implemented) == sorted(IMPLEMENTED)


def test_grpc_health_and_unimplemented_rpcs(offline_app: LoyaltyApp,
                                            offline_client: grpcutil.Client) -> None:
    stub = health_pb2_grpc.HealthStub(offline_client.channel)
    reply = stub.Check(health_pb2.HealthCheckRequest(service=LOYALTY_SVC), timeout=5)
    assert reply.status == health_pb2.HealthCheckResponse.SERVING
    for method in ("IssueCoupon", "ResolveCoupon", "ListEligibleOffers"):
        err = rpc_error(lambda m=method: offline_client.call(m, {}))
        assert err.code() == grpc.StatusCode.UNIMPLEMENTED


@pytest.mark.parametrize(("method", "body", "text"), [
    ("GetPurchaseBehaviour", {"article_number": "100012"}, "membership_id fehlt"),
    ("GetPurchaseBehaviour", {"membership_id": "M-1001"}, "article_number fehlt"),
    ("GetMemberProfile", {"membership_id": "  "}, "membership_id fehlt"),
    ("ReportPurchase", {"purchase": {"purchase_transaction_id": "not-a-uuid"}},
     "purchase_transaction_id ist keine UUID"),
    ("ReportPurchase", {"purchase": {
        "purchase_transaction_id": "5b1f0c2e-8d1e-4a43-9a51-0c7a2f0e1b11"}},
     "transaction_type muss SALE oder VOID sein"),
    ("ReportPurchase", {"purchase": {
        "purchase_transaction_id": "5b1f0c2e-8d1e-4a43-9a51-0c7a2f0e1b11",
        "transaction_type": "TRANSACTION_TYPE_VOID"}},
     "referenced_purchase_transaction_id fehlt"),
    ("ResetDemoState", {"visit_id": "visit-7"}, 'visit_id muss "booth" sein'),
    # proto3 would read the missing flags as all false and revoke every consent
    ("ChangeConsent", {"membership_id": "M-1001"}, "consent fehlt"),
])
def test_malformed_requests_are_invalid_argument_without_code(
        offline_client: grpcutil.Client, method: str, body: dict[str, object],
        text: str) -> None:
    """Checked before any database access (the DB of this app is unreachable)."""
    err = rpc_error(lambda: offline_client.call(method, body))
    assert err.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert text in err.details()
    assert grpcutil.error_code(err) == ""


def test_health_reports_the_database(offline_app: LoyaltyApp) -> None:
    with TestClient(mcputil.http_app(offline_app.mcp)) as http:
        reply = http.get("/health")
    assert reply.status_code == 503
    assert reply.json() == {"status": "degraded", "db": False, "bus": True}
