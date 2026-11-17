"""Answer shapes without database: proto docs parse strictly, agent JSON stays small."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from google.protobuf import json_format
from google.protobuf.descriptor_pool import DescriptorPool

from gposdemo.common import mcputil
from gposdemo.common.clock import from_ts
from gposdemo.common.descriptors import Types
from gposdemo.common.jsonutil import parse_strict
from gposdemo.wws import views
from gposdemo.wws.analytics import (ArticleRecord, Delivery, PriceAction, PriceChange,
                                    PriceQuote, SalesFigures, Season, SeasonFigures)

TZ = ZoneInfo("Europe/Berlin")
DATATYPE = "de.showcase.wws.v1.datatype."
LONG_NAME = "Kochbuch „Regional kochen – Gemüse, Kräuter & Getreide aus Süddeutschland“ XXL"
SEASON = Season("valentinstag_lang", "Valentinstag und Muttertag Sonderedition",
                date(2027, 1, 18), date(2027, 2, 14))


def article(**changes: object) -> ArticleRecord:
    base = dict(article_number="100028", article_id="ID100028", gtin="2099100000285",
                name=LONG_NAME, category="spielwaren_geschenke",
                category_label="Spielwaren & Geschenke", pack_label="6 × 1,5 l Mehrweg",
                net_quantity=Decimal("9000"), base_unit="ml", vat_pct=Decimal("19.00"),
                cost_net=Decimal("15.60"), price_bound=True, season_code=SEASON.code,
                listed_since=date(2026, 3, 1), store_id="199",
                regular_price=Decimal("1234.99"), stock_on_hand=99999)
    return ArticleRecord(**{**base, **changes})


ACTION = PriceAction("PA-SEED-100028-199", "100028", "199", "CENTRAL", Decimal("1234.99"),
                     Decimal("999.99"), 19, Decimal("1234.99"),
                     datetime(2027, 2, 8, 8, tzinfo=TZ), datetime(2027, 2, 21, 20, tzinfo=TZ),
                     "", "REASON_CODE_CENTRAL_PROMOTION", "zentrale", "")
QUOTE = PriceQuote(Decimal("999.99"), Decimal("1234.99"), "CENTRAL_ACTION", ACTION,
                   Decimal("1234.99"), 19)
CHANGE = PriceChange(date(2027, 1, 11), Decimal("1199.99"), Decimal("1234.99"))
SALES = SalesFigures(date(2027, 2, 15), 99999, Decimal("12345.50"), Decimal("8.1004"),
                     (99999,) * 8, Decimal("99999"), 99999, Decimal("1.0001"), "falling",
                     9999, Delivery(date(2027, 2, 18), 99999))
SEASON_FIGURES = SeasonFigures(SEASON, -2000, "ended", Decimal("99999.1234"), 0, 99999,
                               99999, Decimal(1))


@pytest.fixture
def types(showcase_pool: DescriptorPool) -> Types:
    return Types(showcase_pool)


def test_agent_answers_in_the_worst_case_fit_1200_bytes() -> None:
    answers = [
        views.agent_article(article(), QUOTE, Decimal("-5.55"), CHANGE, SEASON, TZ),
        views.agent_sales("100028", SALES),
        views.agent_season("100028", SEASON_FIGURES),
    ]
    for answer in answers:
        _, size = mcputil.measure(mcputil.text_result(answer))
        assert size <= mcputil.AGENT_MAX_TEXT_BYTES, answer


def test_agent_article_with_action() -> None:
    got = views.agent_article(article(), QUOTE, Decimal("12.345"), CHANGE, SEASON, TZ)
    assert got["action"] == {"action_id": "PA-SEED-100028-199", "kind": "CENTRAL",
                             "price": "999,99", "valid_to": "So 21.02. 20:00"}
    assert (got["price"], got["regular_price"], got["ref30"], got["margin_pct"]) == (
        "999,99", "1234,99", "1234,99", 12.3)
    assert got["last_price_change"] == {"date": "2027-01-11", "from": "1199,99",
                                        "to": "1234,99"}


def test_agent_sales_without_plan_or_supply() -> None:
    quiet = SalesFigures(date(2027, 2, 15), 0, Decimal(0), None, (0,) * 8, Decimal(0), 5, None,
                         "stable", 3, None)
    got = views.agent_sales("100004", quiet)
    assert (got["plan_7d"], got["sell_through_7d"], got["weeks_of_supply"]) == (0, None, None)
    assert views.agent_sales("100004", SALES)["plan_7d"] == 12345.5


def test_proto_docs_parse_strictly(types: Types) -> None:
    docs = {
        "Article": views.article_doc(article(), QUOTE, Decimal("-5.55"), CHANGE, TZ),
        "SalesPerformance": views.sales_doc("100028", "199", SALES),
        "SeasonInfo": views.season_doc("100028", SEASON_FIGURES),
        "EffectivePrice": views.effective_price_doc("100028", "199", QUOTE, TZ),
    }
    for name, doc in docs.items():
        parse_strict(doc, types.new(DATATYPE + name), types.pool)
    msg = parse_strict(docs["Article"], types.new(DATATYPE + "Article"), types.pool)
    as_json = json_format.MessageToDict(msg)
    assert as_json["netQuantity"] == {"scale": 3, "intVal": "9000000"}
    assert as_json["marginPercent"] == {"scale": 1, "intVal": "-56"}  # half up: -5.55 -> -5.6
    assert as_json["price"]["validTo"]["offset"] == 60
    assert from_ts(as_json["price"]["validTo"]) == datetime(2027, 2, 21, 20, tzinfo=TZ)


def test_unset_ratios_stay_unset(types: Types) -> None:
    quiet = SalesFigures(date(2027, 2, 15), 0, Decimal(0), None, (0,) * 8, Decimal(0), 5, None,
                         "stable", 3, None)
    msg = parse_strict(views.sales_doc("100004", "199", quiet),
                       types.new(DATATYPE + "SalesPerformance"), types.pool)
    assert not msg.HasField("sell_through_7d") and not msg.HasField("weeks_of_supply")
    assert not msg.HasField("next_delivery")
    regular = PriceQuote(Decimal("9.99"), Decimal("9.99"), "REGULAR", None, Decimal("9.99"), 0)
    price = parse_strict(views.effective_price_doc("100001", "199", regular, TZ),
                         types.new(DATATYPE + "EffectivePrice"), types.pool)
    assert not price.HasField("valid_to") and price.action_id == ""
