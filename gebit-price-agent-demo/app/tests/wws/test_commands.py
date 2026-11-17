"""RequestPriceChange parsing and the static checks of 4.3/4.5 (no database)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import grpc
import psycopg
import pytest
from google.protobuf import json_format
from google.protobuf.descriptor_pool import DescriptorPool

from gposdemo.common.descriptors import Types
from gposdemo.wws import errors
from gposdemo.wws.actions import PriceChangeCommand, check_article, validate
from gposdemo.wws.analytics import ArticleRecord
from gposdemo.wws.errors import WwsError
from gposdemo.wws.events import Authorization
from gposdemo.wws.service import MerchandiseImpl, command_from_request

TZ = ZoneInfo("Europe/Berlin")
REQUEST = "de.showcase.wws.v1.command.RequestPriceChange"


def money(cents: int, currency: str = "EUR") -> dict[str, Any]:
    return {"currency": currency, "amount": {"scale": 2, "intVal": str(cents)}}


def body(**changes: Any) -> dict[str, Any]:
    """The request the gate sends for S1 (11.4 step 9)."""
    base: dict[str, Any] = {
        "header": {"traceId": "GP-270216-0003", "originator": {"identityId": "gpos-engine"},
                   "approver": {"identityId": "role:marktleitung"}},
        "articleNumber": "100001", "storeId": "101",
        "expectedRegularPrice": money(999), "newPrice": money(799), "pctShown": 20,
        "ref30": money(999), "validFrom": {"seconds": "1802732400", "offset": 60},
        "validTo": {"seconds": "1803409200", "offset": 60},
        "proposalId": "GP-270216-0003", "reasonCode": "REASON_CODE_SLOW_SELLER"}
    for key, value in changes.items():
        if value is None:
            base.pop(key)
        else:
            base[key] = value
    return base


@pytest.fixture
def request_of(showcase_pool: DescriptorPool) -> Any:
    types = Types(showcase_pool)

    def make(doc: dict[str, Any]) -> Any:
        return json_format.ParseDict(doc, types.new(REQUEST))

    return make


def ente(**changes: Any) -> ArticleRecord:
    base = dict(article_number="100001", article_id="ID100001", gtin="2099100000018",
                name="GEBIT Ente (Quietscheente gelb)", category="spielwaren_geschenke",
                category_label="Spielwaren & Geschenke", pack_label="1 Stück",
                net_quantity=Decimal(1), base_unit="Stück", vat_pct=Decimal(19),
                cost_net=Decimal("5.20"), price_bound=False, season_code="",
                listed_since=date(2026, 9, 1), store_id="101", regular_price=Decimal("9.99"),
                stock_on_hand=96)
    return ArticleRecord(**{**base, **changes})


def code_of(fn: Any, *args: Any) -> str:
    with pytest.raises(WwsError) as caught:
        fn(*args)
    return caught.value.code


def test_command_of_the_s1_request(request_of: Any) -> None:
    cmd = command_from_request(request_of(body()))
    assert (cmd.trace_id, cmd.originator.identity_id, cmd.approver.identity_id) == (
        "GP-270216-0003", "gpos-engine", "role:marktleitung")
    assert (cmd.article_number, cmd.store_id, cmd.proposal_id) == ("100001", "101",
                                                                   "GP-270216-0003")
    assert (cmd.expected_regular_price, cmd.new_price, cmd.ref30, cmd.pct_shown) == (
        Decimal("9.99"), Decimal("7.99"), Decimal("9.99"), 20)
    assert cmd.valid_from == datetime(2027, 2, 16, tzinfo=TZ)
    assert cmd.valid_to == datetime(2027, 2, 23, 20, tzinfo=TZ)
    assert cmd.reason_code == "REASON_CODE_SLOW_SELLER"
    validate(cmd)
    check_article(ente(), cmd)


def test_missing_valid_from_means_business_date_start(request_of: Any) -> None:
    assert command_from_request(request_of(body(validFrom=None))).valid_from is None


@pytest.mark.parametrize("field", ["validTo", "newPrice", "ref30", "expectedRegularPrice",
                                   "reasonCode"])
def test_missing_mandatory_fields_are_wws_002(request_of: Any, field: str) -> None:
    assert code_of(command_from_request, request_of(body(**{field: None}))) == "WWS-002"


def test_foreign_currency_is_wws_002(request_of: Any) -> None:
    assert code_of(command_from_request,
                   request_of(body(newPrice=money(799, "USD")))) == "WWS-002"


@pytest.mark.parametrize("changes", [
    {"header": {"traceId": "t", "originator": {"identityId": "gpos-engine"}}},
    {"header": {"traceId": "t", "approver": {"identityId": "role:marktleitung"}}},
    {"proposalId": None}, {"articleNumber": None}, {"storeId": None},
    {"pctShown": 100}, {"pctShown": -1}, {"newPrice": money(0)},
    {"validTo": {"seconds": "1802732400", "offset": 60}},
])
def test_static_checks_are_wws_002(request_of: Any, changes: dict[str, Any]) -> None:
    cmd = command_from_request(request_of(body(**changes)))
    err = pytest.raises(WwsError, validate, cmd).value
    assert (err.code, err.status) == ("WWS-002", grpc.StatusCode.INVALID_ARGUMENT)


@pytest.mark.parametrize(("field", "amount"), [
    ("newPrice", {"scale": 3, "intVal": "7995"}),          # 7,995: not a whole cent
    ("ref30", {"scale": 2, "intVal": "100000000"}),        # 1 000 000,00 > numeric(8,2)
    ("expectedRegularPrice", {"scale": -30, "intVal": "1"}),  # 1E+30, no quantize overflow
    ("newPrice", {"scale": 2, "intVal": "-1"}),
])
def test_prices_outside_numeric_8_2_are_wws_002(request_of: Any, field: str,
                                                amount: dict[str, Any]) -> None:
    """A price the column ``numeric(8,2)`` cannot store exactly is refused before the
    database (it used to surface as gRPC UNKNOWN with the raw constraint error)."""
    cmd = command_from_request(request_of(body(**{field: {"currency": "EUR",
                                                          "amount": amount}})))
    err = pytest.raises(WwsError, validate, cmd).value
    assert (err.code, err.status) == ("WWS-002", grpc.StatusCode.INVALID_ARGUMENT)
    assert "ganzen Cent zwischen 0,01 und 999999,99 €" in err.text


def test_prices_in_whole_cents_with_another_scale_pass(request_of: Any) -> None:
    """``9,990`` (scale 3) is exactly 9,99 €: accepted, compared numerically."""
    cmd = command_from_request(request_of(body(
        expectedRegularPrice={"currency": "EUR", "amount": {"scale": 3, "intVal": "9990"}})))
    validate(cmd)
    check_article(ente(), cmd)
    assert cmd.expected_regular_price == Decimal("9.99")


def test_article_checks_and_their_status(request_of: Any) -> None:
    cmd = command_from_request(request_of(body()))
    cases = {
        "WWS-012": (ente(price_bound=True), cmd),
        "WWS-020": (ente(regular_price=Decimal("10.99")), cmd),
        "WWS-010": (ente(), command_from_request(request_of(body(newPrice=money(999))))),
    }
    for code, (article, command) in cases.items():
        err = pytest.raises(WwsError, check_article, article, command).value
        assert err.code == code
        assert err.status == errors.STATUS[code]
    assert errors.STATUS["WWS-010"] == grpc.StatusCode.INVALID_ARGUMENT
    assert errors.STATUS["WWS-011"] == grpc.StatusCode.FAILED_PRECONDITION
    assert errors.STATUS["WWS-012"] == grpc.StatusCode.FAILED_PRECONDITION
    assert errors.STATUS["WWS-020"] == grpc.StatusCode.ABORTED
    assert errors.STATUS["WWS-001"] == grpc.StatusCode.NOT_FOUND


def test_error_texts_are_german() -> None:
    err = errors.article_unknown("999999", "199")
    assert str(err) == "WWS-001: Artikel 999999 im Laden 199 unbekannt"
    cmd = PriceChangeCommand(
        trace_id="t", originator=Authorization("gpos-engine"),
        approver=Authorization("role:marktleitung"), article_number="100001",
        store_id="101", expected_regular_price=Decimal("9.99"), new_price=Decimal("7.99"),
        pct_shown=20, ref30=Decimal("9.99"), valid_from=None,
        valid_to=datetime(2027, 2, 23, 20, tzinfo=TZ), proposal_id="GP-1",
        reason_code="REASON_CODE_SLOW_SELLER")
    mismatch = pytest.raises(WwsError, check_article, ente(regular_price=Decimal("10.99")),
                             cmd).value
    assert mismatch.text == "Erwarteter Regulärpreis 9,99 € passt nicht zum aktuellen 10,99 €"
    bound = pytest.raises(WwsError, check_article, ente(price_bound=True), cmd).value
    assert bound.text == "Artikel 100001 ist preisgebunden"


# ------------------------------------------------------------------ gRPC error mapping
class Aborted(Exception):
    """What ``context.abort`` raises in grpcio."""


class FakeContext:
    def __init__(self) -> None:
        self.trailing: tuple[tuple[str, str], ...] = ()
        self.aborted: tuple[grpc.StatusCode, str] | None = None

    def set_trailing_metadata(self, metadata: tuple[tuple[str, str], ...]) -> None:
        self.trailing = metadata

    def abort(self, code: grpc.StatusCode, details: str) -> None:
        self.aborted = (code, details)
        raise Aborted(details)


class FailingService:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def sales_performance(self, article_number: str, store_id: str) -> None:
        raise self.exc

    def effective_price(self, article_number: str, store_id: str, at: Any) -> None:
        raise self.exc


def test_wws_error_becomes_status_message_and_trailer(showcase_pool: DescriptorPool) -> None:
    types = Types(showcase_pool)
    impl = MerchandiseImpl(FailingService(errors.article_unknown("999999", "199")), types)
    ctx = FakeContext()
    with pytest.raises(Aborted):
        impl.GetSalesPerformance(types.new("de.showcase.wws.v1.query.GetSalesPerformance",
                                           article_number="999999", store_id="199"), ctx)
    assert ctx.aborted == (grpc.StatusCode.NOT_FOUND,
                           "WWS-001: Artikel 999999 im Laden 199 unbekannt")
    assert ctx.trailing == (("gpos-error-code", "WWS-001"),)


YEAR_10000 = {"seconds": "253402300800", "offset": 60}  # beyond datetime: ValueError


@pytest.mark.parametrize("field", ["validTo", "validFrom"])
def test_times_out_of_range_are_wws_002(request_of: Any, field: str) -> None:
    err = pytest.raises(WwsError, command_from_request,
                        request_of(body(**{field: YEAR_10000}))).value
    assert (err.code, err.text) == ("WWS-002",
                                    f"{'valid_to' if field == 'validTo' else 'valid_from'}: "
                                    f"Zeitpunkt außerhalb des gültigen Bereichs")


def test_effective_price_at_out_of_range_is_wws_002(showcase_pool: DescriptorPool) -> None:
    """Formerly an UNKNOWN: ``from_ts`` ran outside the error mapping of the RPC."""
    types = Types(showcase_pool)
    impl = MerchandiseImpl(FailingService(AssertionError("service must not be called")),
                           types)
    ctx = FakeContext()
    request = json_format.ParseDict(
        {"articleNumber": "100001", "storeId": "199", "at": YEAR_10000},
        types.new("de.showcase.wws.v1.query.GetEffectivePrice"))
    with pytest.raises(Aborted):
        impl.GetEffectivePrice(request, ctx)
    assert ctx.aborted == (grpc.StatusCode.INVALID_ARGUMENT,
                           "WWS-002: at: Zeitpunkt außerhalb des gültigen Bereichs")
    assert ctx.trailing == (("gpos-error-code", "WWS-002"),)


def test_database_outage_is_unavailable(showcase_pool: DescriptorPool) -> None:
    types = Types(showcase_pool)
    impl = MerchandiseImpl(FailingService(psycopg.OperationalError("down")), types)
    ctx = FakeContext()
    with pytest.raises(Aborted):
        impl.GetSalesPerformance(types.new("de.showcase.wws.v1.query.GetSalesPerformance"), ctx)
    assert ctx.aborted == (grpc.StatusCode.UNAVAILABLE,
                           "Warenwirtschaft: Datenbank nicht erreichbar")
