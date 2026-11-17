"""POS facade ``POST /api/pos/{Method}`` -> GEBIT gRPC (10.1, 4.2).

Without marker: whitelist, till check, missing descriptors. Marker ``gebit``: a fake
``PurchaseTransactionService`` from the GEBIT 2.50.0 runtime descriptors checks the
header, ``?till=98|99``, the request bodies and the error mapping.
"""

from __future__ import annotations

import re
import socket
from collections.abc import Callable

import grpc
import pytest

from gposdemo.common.config import Settings
from gposdemo.common.descriptors import PURCHASE_SVC
from gposdemo.common.grpcutil import Client
from gposdemo.ui.facade import ALLOWED_METHODS, PosFacade, split_status

from .conftest import GrpcFake, Ui

TX = "5b1f0c2e-8d1e-4a43-9a51-0c7a2f0e1b11"
TRACE = re.compile(r"^kasse-(01|98|99)-[0-9a-f]{8}$")


def test_whitelist_is_the_seven_commands_of_4_2() -> None:
    assert ALLOWED_METHODS == (
        "CreatePurchaseTransaction", "AddArticle", "VoidArticlePosition",
        "AssignLoyaltyMembership", "StartPaymentProcess", "CreateCashPayment",
        "CancelPurchaseTransaction")


@pytest.mark.parametrize("method", ["GetPurchaseTransaction", "AddCoupon", "Unknown"])
def test_other_methods_answer_404(ui: Ui, method: str) -> None:
    response = ui.client.post(f"/api/pos/{method}", json={})
    assert response.status_code == 404
    assert response.json() == {"ok": False, "code": "BFF-001", "grpc": "",
                               "message": f"Methode nicht erlaubt: {method}"}


def test_unknown_till_is_400(ui: Ui) -> None:
    response = ui.client.post("/api/pos/AddArticle?till=42", json={})
    assert response.status_code == 400 and response.json()["code"] == "BFF-002"


def test_body_must_be_an_object(ui: Ui) -> None:
    response = ui.client.post("/api/pos/AddArticle", content="[1]",
                              headers={"Content-Type": "application/json"})
    assert response.status_code == 400 and response.json()["code"] == "BFF-002"


def test_without_gebit_descriptors_the_facade_is_unavailable(ui: Ui) -> None:
    response = ui.client.post("/api/pos/CreatePurchaseTransaction", json={})
    assert response.status_code == 503
    assert response.json() == {"ok": False, "code": "BFF-003", "grpc": "UNAVAILABLE",
                               "message": "GEBIT_DESCRIPTOR_SETS ist nicht gesetzt"}


def test_from_settings_reports_unloadable_descriptors(make_settings: Callable[..., Settings],
                                                      tmp_path) -> None:
    broken = tmp_path / "broken.pb"
    broken.write_bytes(b"\x00not a descriptor set")
    facade = PosFacade.from_settings(make_settings("ui", GEBIT_DESCRIPTOR_SETS=str(broken)))
    assert not facade.ready
    result = facade.call("AddArticle", {})
    assert result.status == 503 and "nicht ladbar" in result.body["message"]
    facade.close()


@pytest.mark.parametrize("details, trailer, expected", [
    ("POS-002: Transaktion ist CLOSED", "POS-002", ("POS-002", "Transaktion ist CLOSED")),
    ("POS-002: Transaktion ist CLOSED", "", ("POS-002", "Transaktion ist CLOSED")),
    ("connection refused", "", ("", "connection refused")),
    ("LOY-001: Karte unbekannt", "LOY-001", ("LOY-001", "Karte unbekannt")),
])
def test_split_status(details: str, trailer: str, expected: tuple[str, str]) -> None:
    assert split_status(details, trailer) == expected


# --------------------------------------------------------------------- GEBIT
@pytest.fixture
def gebit_ui(make_ui: Callable[..., Ui], make_settings: Callable[..., Settings],
             pos_fake: GrpcFake) -> Ui:
    settings = make_settings("ui", POS_GRPC=pos_fake.target)
    facade = PosFacade.from_settings(settings)
    assert facade.ready
    return make_ui(facade=facade)


@pytest.mark.gebit
@pytest.mark.parametrize("query, till, location", [
    ("", "01", "Root.DE.999.101.01"),
    ("?till=01", "01", "Root.DE.999.101.01"),
    ("?till=98", "98", "Root.DE.999.199.98"),
    ("?till=99", "99", "Root.DE.999.199.99"),
])
def test_create_sets_location_employee_and_drawer(gebit_ui: Ui, pos_fake: GrpcFake,
                                                  query: str, till: str,
                                                  location: str) -> None:
    response = gebit_ui.client.post(f"/api/pos/CreatePurchaseTransaction{query}",
                                    json={"location": "Root.DE.999.666.66",
                                          "header": {"traceId": "client"}})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["result"] == {"purchaseTransactionId": TX}
    assert TRACE.match(body["traceId"]) and body["traceId"].startswith(f"kasse-{till}-")
    assert isinstance(body["ms"], int)
    method, request = pos_fake.impl.requests[-1]
    assert method == "CreatePurchaseTransaction"
    assert request == {"header": {"traceId": body["traceId"]}, "location": location,
                       "employeeId": "booth", "cashdrawerId": till}


@pytest.mark.gebit
def test_add_article_passes_the_command(gebit_ui: Ui, pos_fake: GrpcFake) -> None:
    command = {"purchaseTransactionId": TX, "articleId": "ID100001", "itemCount": 1,
               "capturingInformation": {"inputMethod": "SCANNER", "inputType": "EAN13",
                                        "inputValue": "2099100000018"}}
    response = gebit_ui.client.post("/api/pos/AddArticle", json=command)
    assert response.status_code == 200 and response.json()["result"] == {}
    method, request = pos_fake.impl.requests[-1]
    assert method == "AddArticle"
    assert request == {**command, "header": {"traceId": response.json()["traceId"]}}


@pytest.mark.gebit
def test_cash_payment_amount_is_proto3_json(gebit_ui: Ui, pos_fake: GrpcFake) -> None:
    command = {"purchaseTransactionId": TX, "clientId": "kasse-01",
               "clientTransactionId": "8f9e0b8e-5b8a-4b6f-9d55-6c1c4f3c2a10",
               "amount": {"currency": "EUR", "amount": {"scale": 2, "intVal": "2000"}}}
    assert gebit_ui.client.post("/api/pos/CreateCashPayment", json=command).status_code == 200
    _, request = pos_fake.impl.requests[-1]
    assert request["amount"] == {"currency": "EUR", "amount": {"scale": 2, "intVal": "2000"}}


@pytest.mark.gebit
def test_card_of_the_facade_reaches_the_receipt(gebit_ui: Ui) -> None:
    gebit_ui.client.post("/api/pos/AssignLoyaltyMembership",
                         json={"purchaseTransactionId": TX,
                               "membershipIdentificationValue": "CLUB-1003"})
    bon = gebit_ui.client.get("/api/state").json()["bon"]
    assert (bon["card"], bon["persona"], bon["consent_profiling"]) == (
        "CLUB-1003", "Feierabend", False)



@pytest.mark.gebit
@pytest.mark.parametrize("status, code, http", [
    (grpc.StatusCode.FAILED_PRECONDITION, "POS-002", 409),
    (grpc.StatusCode.NOT_FOUND, "POS-001", 404),
    (grpc.StatusCode.NOT_FOUND, "POS-003", 404),
    (grpc.StatusCode.UNAVAILABLE, "POS-004", 503),
    (grpc.StatusCode.INVALID_ARGUMENT, "LOY-001", 400),
    (grpc.StatusCode.INTERNAL, "POS-999", 502),
])
def test_error_mapping(gebit_ui: Ui, pos_fake: GrpcFake, status: grpc.StatusCode, code: str,
                       http: int) -> None:
    pos_fake.impl.fail["AddArticle"] = (status, code, "Text der Kasse")
    response = gebit_ui.client.post("/api/pos/AddArticle",
                                    json={"purchaseTransactionId": TX, "articleId": "ID1"})
    assert response.status_code == http
    body = response.json()
    assert body == {"ok": False, "code": code, "grpc": status.name,
                    "message": "Text der Kasse", "traceId": body["traceId"]}


@pytest.mark.gebit
def test_unknown_field_is_400(gebit_ui: Ui, pos_fake: GrpcFake) -> None:
    before = len(pos_fake.impl.requests)
    response = gebit_ui.client.post("/api/pos/AddArticle", json={"articleIdd": "ID100001"})
    assert response.status_code == 400
    assert response.json()["code"] == "BFF-002" and "articleIdd" in response.json()["message"]
    assert len(pos_fake.impl.requests) == before


@pytest.mark.gebit
def test_pos_not_reachable_is_503(make_settings: Callable[..., Settings],
                                  gebit_pool) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    settings = make_settings("ui", POS_GRPC=f"127.0.0.1:{port}")
    facade = PosFacade(settings, Client(gebit_pool, PURCHASE_SVC, settings.pos_grpc))
    result = facade.call("StartPaymentProcess", {"purchaseTransactionId": TX})
    assert result.status == 503
    assert (result.body["ok"], result.body["grpc"]) == (False, "UNAVAILABLE")
    assert not facade.healthy()
    facade.close()


@pytest.mark.gebit
def test_health_ok_with_a_serving_pos(gebit_ui: Ui) -> None:
    assert gebit_ui.client.get("/health").json() == {
        "status": "ok", "bus": True, "pos": True, "wws": True, "engine": True}
