"""MerchandiseService queries over real gRPC on the seeded scratch DB (4.3, 6.8).

Store 199 (test) carries the same data as the booth store 101 (5.7); the central
action of store 199 is ``PA-SEED-100009-199`` (WP-B id rule).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import grpc
import pytest

from gposdemo.common import grpcutil
from gposdemo.common.clock import from_ts, offset_ts_json
from gposdemo.common.money import from_bdecimal, from_money

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_wws")]

TZ = ZoneInfo("Europe/Berlin")


def eur(money: dict[str, Any]) -> Decimal:
    return from_money(money)


def failure(client: grpcutil.Client, method: str, body: dict[str, Any]
            ) -> tuple[grpc.StatusCode, str, str]:
    with pytest.raises(grpc.RpcError) as caught:
        client.call(method, body)
    err = caught.value
    return err.code(), grpcutil.error_code(err), err.details()


def test_list_articles(client: grpcutil.Client, articles: dict[str, dict]) -> None:
    listed = client.call_json("ListArticles", {"storeId": "199"})["articles"]
    assert [a["articleNumber"] for a in listed] == list(articles)  # file order
    by_number = {a["articleNumber"]: a for a in listed}
    for number, src in articles.items():
        got = by_number[number]
        assert (got["articleId"], got["gtin"], got["name"]) == (
            f"ID{number}", src["gtin"], src["name"])
        assert eur(got["price"]["regularPrice"]) == src["price"]
        assert got["stockOnHand"] == src["stock"]
    assert by_number["100009"]["price"]["source"] == "PRICE_SOURCE_CENTRAL_ACTION"
    sources = {a["price"]["source"] for n, a in by_number.items() if n != "100009"}
    assert sources == {"PRICE_SOURCE_REGULAR"}
    coffee = client.call_json("ListArticles", {"storeId": "199", "category": "kaffee_tee"})
    assert [a["articleNumber"] for a in coffee["articles"]] == ["100012", "100013", "100014"]
    assert client.call_json("ListArticles", {"storeId": "555"}) == {}


@pytest.mark.parametrize("key", [{"articleNumber": "100001"}, {"gtin": "2099100000018"},
                                 {"articleId": "ID100001"}])
def test_get_article_by_each_key(client: grpcutil.Client, key: dict[str, str]) -> None:
    got = client.call_json("GetArticle", {"storeId": "199", **key})
    assert got["articleNumber"] == "100001"
    assert got["categoryLabel"] == "Spielwaren & Geschenke"
    assert (got["packLabel"], got["baseUnit"], got["listedSince"]) == ("1 Stück", "Stück",
                                                                         "2026-09-01")
    assert from_bdecimal(got["netQuantity"]) == 1
    assert from_bdecimal(got["vatPercent"]) == 19
    assert eur(got["costNet"]) == Decimal("5.20")
    assert from_bdecimal(got["marginPercent"]) == Decimal("38.1")
    assert got["stockOnHand"] == 96
    assert "seasonCode" not in got and "lastPriceChange" not in got
    assert got.get("priceBound", False) is False


def test_get_article_details(client: grpcutil.Client) -> None:
    espresso = client.call_json("GetArticle", {"storeId": "101", "articleNumber": "100012"})
    assert espresso["lastPriceChange"]["date"] == "2027-01-11"
    assert eur(espresso["lastPriceChange"]["oldPrice"]) == Decimal("12.99")
    assert eur(espresso["lastPriceChange"]["newPrice"]) == Decimal("14.49")
    assert from_bdecimal(espresso["netQuantity"]) == 1000
    hase = client.call_json("GetArticle", {"storeId": "101", "articleNumber": "100002"})
    assert hase["seasonCode"] == "ostern"
    book = client.call_json("GetArticle", {"storeId": "101", "articleNumber": "100028"})
    assert book["priceBound"] is True and book["name"] == "Kochbuch „Regional kochen“"


@pytest.mark.parametrize(("body", "expected"), [
    ({"storeId": "199", "articleNumber": "999999"}, ("WWS-001", grpc.StatusCode.NOT_FOUND)),
    ({"storeId": "555", "articleNumber": "100001"}, ("WWS-001", grpc.StatusCode.NOT_FOUND)),
    ({"storeId": "199", "gtin": "2099100000000"}, ("WWS-001", grpc.StatusCode.NOT_FOUND)),
    ({"storeId": "199"}, ("WWS-002", grpc.StatusCode.INVALID_ARGUMENT)),
])
def test_get_article_errors(client: grpcutil.Client, body: dict[str, str],
                            expected: tuple[str, grpc.StatusCode]) -> None:
    status, code, details = failure(client, "GetArticle", body)
    assert (code, status) == expected
    assert details.startswith(f"{code}: ")


def test_effective_price_regular(client: grpcutil.Client) -> None:
    got = client.call_json("GetEffectivePrice", {"articleNumber": "100001", "storeId": "199"})
    assert got["source"] == "PRICE_SOURCE_REGULAR"
    assert eur(got["price"]) == eur(got["regularPrice"]) == eur(got["ref30"]) == Decimal("9.99")
    assert "actionId" not in got and "validTo" not in got and "pctShown" not in got


@pytest.mark.parametrize(("store", "action_id"), [("101", "PA-SEED-100009"),
                                                  ("199", "PA-SEED-100009-199")])
def test_effective_price_central_action(client: grpcutil.Client, store: str,
                                        action_id: str) -> None:
    got = client.call_json("GetEffectivePrice", {"articleNumber": "100009", "storeId": store})
    assert (got["source"], got["actionId"], got["pctShown"]) == (
        "PRICE_SOURCE_CENTRAL_ACTION", action_id, 14)
    # ref30 = 30-day low of the history, the 6.3 result for Glühwein on 16.02.; the
    # shown 14 % is the seeded action's (against 3,49 before it started)
    assert (eur(got["price"]), eur(got["regularPrice"]), eur(got["ref30"])) == (
        Decimal("2.99"), Decimal("3.49"), Decimal("2.99"))
    assert from_ts(got["validTo"]) == datetime(2027, 2, 21, 20, tzinfo=TZ)
    assert got["validTo"]["offset"] == 60


@pytest.mark.parametrize(("article", "expected"), [
    ("100001", "9.99"), ("100008", "7.99"), ("100012", "14.49"), ("100009", "2.99")])
@pytest.mark.parametrize("store", ["101", "199"])
def test_ref30_results_of_6_3_on_every_read_path(client: grpcutil.Client, wws_app: Any,
                                                  article: str, expected: str,
                                                  store: str) -> None:
    """6.3: ``ref30`` on 16.02.2027 is Ente 9,99, Pralinen 7,99, Espresso 14,49 (raise 36
    days ago), Glühwein 2,99; every API that carries ``ref30`` says the same."""
    key = {"articleNumber": article, "storeId": store}
    paths = {
        "GetEffectivePrice": eur(client.call_json("GetEffectivePrice", key)["ref30"]),
        "GetArticle": eur(client.call_json("GetArticle", key)["price"]["ref30"]),
        "GetPriceHistory": eur(client.call_json("GetPriceHistory", key)["ref30"]),
    }
    assert paths == dict.fromkeys(paths, Decimal(expected))
    if store == wws_app.settings.tool_store:
        assert wws_app.service.get_article(article)["ref30"] == expected.replace(".", ",")


def test_effective_price_at_a_given_time(client: grpcutil.Client) -> None:
    def price(article: str, when: datetime) -> dict[str, Any]:
        return client.call_json("GetEffectivePrice", {
            "articleNumber": article, "storeId": "199", "at": offset_ts_json(when)})

    before = price("100009", datetime(2027, 2, 8, 7, 59, tzinfo=TZ))
    assert (before["source"], eur(before["price"])) == ("PRICE_SOURCE_REGULAR", Decimal("3.49"))
    after = price("100009", datetime(2027, 2, 21, 20, 0, tzinfo=TZ))
    assert after["source"] == "PRICE_SOURCE_REGULAR"  # valid_to is exclusive
    # Espresso: the 12,99 row leaves the 30-day window at 2027-02-10 00:00
    assert eur(price("100012", datetime(2027, 2, 9, 23, 59, tzinfo=TZ))["ref30"]) == Decimal(
        "12.99")
    assert eur(price("100012", datetime(2027, 2, 10, 0, 0, tzinfo=TZ))["ref30"]) == Decimal(
        "14.49")


def test_sales_performance_ente(client: grpcutil.Client) -> None:
    got = client.call_json("GetSalesPerformance", {"articleNumber": "100001", "storeId": "199"})
    assert (got["asOf"], got["sold7d"], got["weeklyUnits"]) == (
        "2027-02-15", 9, [34, 36, 31, 28, 22, 16, 12, 9])
    assert from_bdecimal(got["plan7d"]) == 35
    assert from_bdecimal(got["sellThrough7d"]) == Decimal("0.2571")
    assert from_bdecimal(got["avgWeek28d"]) == Decimal("14.75")
    assert from_bdecimal(got["weeksOfSupply"]) == Decimal("6.5085")
    assert (got["stockOnHand"], got["trend"], got["listedDays"]) == (96, "falling", 168)
    assert "nextDelivery" not in got


def test_sales_performance_trends_and_delivery(client: grpcutil.Client) -> None:
    hase = client.call_json("GetSalesPerformance", {"articleNumber": "100002", "storeId": "101"})
    assert (hase["trend"], hase["sold7d"]) == ("rising", 14)
    espresso = client.call_json("GetSalesPerformance",
                                {"articleNumber": "100012", "storeId": "101"})
    assert espresso["nextDelivery"] == {"expectedOn": "2027-02-18", "quantity": 24}
    assert espresso["trend"] == "stable"


def test_season_info(client: grpcutil.Client) -> None:
    pralinen = client.call_json("GetSeasonInfo", {"articleNumber": "100008", "storeId": "199"})
    assert (pralinen["seasonCode"], pralinen["seasonLabel"], pralinen["status"]) == (
        "valentinstag", "Valentinstag", "ended")
    assert (pralinen["startDate"], pralinen["endDate"], pralinen["daysToEnd"]) == (
        "2027-01-18", "2027-02-14", -2)
    assert from_bdecimal(pralinen["leftoverShare"]) == 1
    assert (pralinen["stockOnHand"], pralinen["leftoverUnits"]) == (46, 46)
    assert pralinen.get("projectedUnitsToEnd", 0) == 0
    hase = client.call_json("GetSeasonInfo", {"articleNumber": "100002", "storeId": "199"})
    assert (hase["status"], hase["daysToEnd"]) == ("before", 40)
    gluehwein = client.call_json("GetSeasonInfo", {"articleNumber": "100009", "storeId": "199"})
    assert (gluehwein["status"], gluehwein["daysToEnd"], gluehwein["leftoverUnits"]) == (
        "running", 12, 103)
    assert client.call_json("GetSeasonInfo", {"articleNumber": "100001", "storeId": "199"}) == {
        "articleNumber": "100001", "status": "none"}


def test_price_history(client: grpcutil.Client) -> None:
    espresso = client.call_json("GetPriceHistory", {"articleNumber": "100012", "storeId": "199"})
    entries = espresso["entries"]
    assert [(eur(e["price"]), e["kind"]) for e in entries] == [
        (Decimal("12.99"), "REGULAR"), (Decimal("14.49"), "REGULAR")]
    assert from_ts(entries[0]["validTo"]) == from_ts(entries[1]["validFrom"]) == datetime(
        2027, 1, 11, tzinfo=TZ)
    assert "validTo" not in entries[1]
    assert eur(espresso["ref30"]) == Decimal("14.49")
    gluehwein = client.call_json("GetPriceHistory", {"articleNumber": "100009", "storeId": "199"})
    assert [e["kind"] for e in gluehwein["entries"]] == ["REGULAR", "PROMO"]
    assert eur(gluehwein["ref30"]) == Decimal("2.99")  # 6.3
    short = client.call_json("GetPriceHistory", {"articleNumber": "100012", "storeId": "199",
                                                 "days": 30})
    assert [eur(e["price"]) for e in short["entries"]] == [Decimal("14.49")]


@pytest.mark.parametrize("days", [-1, 3661, 2147483647])
def test_price_history_days_out_of_range_is_wws_002(client: grpcutil.Client, days: int
                                                    ) -> None:
    """``days`` 0 means 90 (4.3); a negative or absurd span is refused instead of an
    UNKNOWN from a ``timedelta`` overflow."""
    status, code, details = failure(client, "GetPriceHistory", {
        "articleNumber": "100012", "storeId": "199", "days": days})
    assert (code, status) == ("WWS-002", grpc.StatusCode.INVALID_ARGUMENT)
    assert details == f"WWS-002: days {days} liegt nicht zwischen 0 (Standard 90) und 3660"


def test_every_rpc_of_4_3_is_implemented(client: grpcutil.Client) -> None:
    """Every RPC of 4.3 is implemented (none answers UNIMPLEMENTED)."""
    for method in ("ListArticles", "GetArticle", "GetEffectivePrice", "GetSalesPerformance",
                   "GetSeasonInfo", "GetPriceHistory", "RequestPriceChange", "EndPriceChange",
                   "ResetDemoState"):
        try:
            client.call(method, {})
        except grpc.RpcError as err:
            assert err.code() != grpc.StatusCode.UNIMPLEMENTED, method


def test_business_date_of_the_figures(client: grpcutil.Client) -> None:
    got = client.call_json("GetSalesPerformance", {"articleNumber": "100004", "storeId": "199"})
    assert date.fromisoformat(got["asOf"]) == date(2027, 2, 15)
