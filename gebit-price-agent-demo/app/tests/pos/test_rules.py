"""Status rules, error codes, cash amounts and receipt numbers (13.1 tests/pos, no marker)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import grpc
import pytest

from gposdemo.pos import errors
from gposdemo.pos.errors import PosError
from gposdemo.pos.receipt import RECEIPT_VERSION, SerializedReceipt, receipt_number
from gposdemo.pos.sim import ALLOWED, cash_amount, require_status

STATES = ("CREATED", "OPEN", "IN_PAYMENT", "CLOSED", "CANCELLED", "RESET")
EXPECTED = {  # 4.2: command -> states it is allowed in
    "AddArticle": {"CREATED", "OPEN"},
    "AssignLoyaltyMembership": {"CREATED", "OPEN"},  # card before the first scan (S3, S6)
    "VoidArticlePosition": {"OPEN"},
    "StartPaymentProcess": {"OPEN"},
    "CreateCashPayment": {"IN_PAYMENT"},
    "CancelPurchaseTransaction": {"CREATED", "OPEN", "IN_PAYMENT"},
}


@pytest.mark.parametrize("command", sorted(EXPECTED))
@pytest.mark.parametrize("status", STATES)
def test_status_rules(command: str, status: str) -> None:
    if status in EXPECTED[command]:
        require_status(command, status)
        return
    with pytest.raises(PosError) as caught:
        require_status(command, status)
    err = caught.value
    assert (err.code, err.status) == ("POS-002", grpc.StatusCode.FAILED_PRECONDITION)
    assert command in err.text and status in err.text


def test_rule_table_covers_exactly_the_mutating_rpcs() -> None:
    assert {k: set(v) for k, v in ALLOWED.items()} == EXPECTED


@pytest.mark.parametrize(("factory", "args", "code", "status"), [
    (errors.unknown_transaction, ("tx",), "POS-001", grpc.StatusCode.NOT_FOUND),
    (errors.already_voided, ("pos",), "POS-002", grpc.StatusCode.FAILED_PRECONDITION),
    (errors.nothing_to_pay, (), "POS-002", grpc.StatusCode.FAILED_PRECONDITION),
    (errors.unknown_article, ("ID1",), "POS-003", grpc.StatusCode.NOT_FOUND),
    (errors.backend_unavailable, ("WWS", "down"), "POS-004", grpc.StatusCode.UNAVAILABLE),
    (errors.invalid_argument, ("x",), "POS-005", grpc.StatusCode.INVALID_ARGUMENT),
])
def test_error_codes_of_4_5(factory: object, args: tuple[str, ...], code: str,
                            status: grpc.StatusCode) -> None:
    err = factory(*args)  # type: ignore[operator]
    assert (err.code, err.status) == (code, status)
    assert str(err).startswith(f"{code}: ")


def _money(currency: str, scale: int, int_val: int) -> SimpleNamespace:
    return SimpleNamespace(currency=currency, amount=SimpleNamespace(scale=scale,
                                                                     int_val=int_val))


def test_cash_amount_accepts_eur_and_empty_currency() -> None:
    assert cash_amount(_money("EUR", 2, 2000)) == Decimal("20.00")
    assert cash_amount(_money("", 0, 15)) == Decimal("15.00")


@pytest.mark.parametrize("money", [
    _money("USD", 2, 2000), _money("EUR", 2, 0), _money("EUR", 2, -500),
    _money("EUR", 3, 19999),  # 19.999: no cent amount
])
def test_cash_amount_rejects_invalid_amounts(money: SimpleNamespace) -> None:
    with pytest.raises(PosError) as caught:
        cash_amount(money)
    assert caught.value.code == "POS-005"


def test_receipt_number_format() -> None:
    assert receipt_number("101", "01", date(2027, 2, 16), 42) == "10101270216000042"
    assert receipt_number("199", "99", date(2027, 2, 16), 1) == "19999270216000001"
    with pytest.raises(ValueError):
        receipt_number("101", "01", date(2027, 2, 16), 0)


def test_receipt_event_fields() -> None:
    assert SerializedReceipt("none", "").event_fields() == {}
    assert SerializedReceipt("receipt-api-2.13.0", "AAA=").event_fields() == {
        "serializedReceiptFormat": "PROTOBUF", "serializedReceiptContent": "AAA=",
        "serializedReceiptVersion": RECEIPT_VERSION}
