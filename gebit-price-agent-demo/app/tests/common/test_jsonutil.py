"""jsonutil: compact/canonical JSON and proto3 JSON of our own events (4.1, 7.2, 7.3)."""

from __future__ import annotations

import json
from datetime import date

import pytest
from google.protobuf import any_pb2, json_format
from google.protobuf.descriptor_pool import DescriptorPool

from gposdemo.common import clock, jsonutil
from gposdemo.common.config import Settings
from gposdemo.common.descriptors import Types

# 7.2 example payloads (proto3 JSON of our own proto)
APPLIED = {
    "@type": "type.googleapis.com/de.showcase.wws.v1.event.PriceChangeApplied",
    "header": {"eventTimestamp": {"seconds": "1794393700", "nanos": 120000000}},
    "metadata": {"offset": "2", "creationTimestamp": {"seconds": "1794393700"},
                 "traceId": "GP-270216-0003"},
    "actionId": "PA-270216-0003", "articleNumber": "100001",
    "articleName": "GEBIT Ente (Quietscheente gelb)", "storeId": "101",
    "kind": "PRICE_ACTION_KIND_BOOTH",
    "regularPrice": {"currency": "EUR", "amount": {"scale": 2, "intVal": "999"}},
    "actionPrice": {"currency": "EUR", "amount": {"scale": 2, "intVal": "799"}},
    "pctShown": 20, "ref30": {"currency": "EUR", "amount": {"scale": 2, "intVal": "999"}},
    "validFrom": {"seconds": "1802732400", "offset": 60},
    "validTo": {"seconds": "1803409200", "offset": 60},
    "proposalId": "GP-270216-0003", "reasonCode": "REASON_CODE_SLOW_SELLER",
    "originator": {"identityId": "gpos-engine"}, "approver": {"identityId": "role:marktleitung"},
}
ENDED = {
    "@type": "type.googleapis.com/de.showcase.wws.v1.event.PriceChangeEnded",
    "header": {"eventTimestamp": {"seconds": "1794394900"}},
    "metadata": {"offset": "3", "creationTimestamp": {"seconds": "1794394900"},
                 "traceId": "reset-booth"},
    "actionId": "PA-270216-0003", "articleNumber": "100001", "storeId": "101",
    "reason": "reset", "endedAt": {"seconds": "1802769300", "offset": 60},
}


def test_compact_and_canonical() -> None:
    obj = {"b": 1, "a": {"ä": "Glühwein €"}}
    assert jsonutil.compact(obj) == '{"b":1,"a":{"ä":"Glühwein €"}}'
    assert jsonutil.canonical(obj) == '{"a":{"ä":"Glühwein €"},"b":1}'
    assert jsonutil.sha256_hex("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


@pytest.mark.parametrize("example", [APPLIED, ENDED])
def test_examples_of_7_2_parse_strictly_and_serialise_unchanged(
        showcase_pool: DescriptorPool, example: dict) -> None:
    msg = jsonutil.parse_strict(example, any_pb2.Any(), showcase_pool)
    text = jsonutil.proto_compact(msg, showcase_pool)
    assert json.loads(text) == example
    assert "\n" not in text and ": " not in text and ", " not in text
    assert text == jsonutil.compact(json_format.MessageToDict(msg, descriptor_pool=showcase_pool))


def test_proto_compact_keeps_umlauts_raw_and_int64_as_string(showcase_pool: DescriptorPool) -> None:
    types = Types(showcase_pool)
    msg = types.new("de.showcase.wws.v1.datatype.Article", article_number="100009",
                    name="Glühwein rot", stock_on_hand=12)
    jsonutil.parse_strict({"netQuantity": {"scale": 3, "intVal": "1000"}}, msg)
    text = jsonutil.proto_compact(msg)
    assert "Glühwein rot" in text and "\\u" not in text
    assert '"intVal":"1000"' in text
    assert '"stockOnHand":12' in text


def test_parse_strict_rejects_unknown_fields(showcase_pool: DescriptorPool) -> None:
    types = Types(showcase_pool)
    with pytest.raises(json_format.ParseError):
        jsonutil.parse_strict('{"articleNumber":"100001","foo":1}',
                              types.new("de.showcase.wws.v1.datatype.Article"))


def test_example_epochs_match_the_demo_date(settings: Settings) -> None:
    applied_from = clock.from_ts(APPLIED["validFrom"])
    applied_to = clock.from_ts(APPLIED["validTo"])
    ended_at = clock.from_ts(ENDED["endedAt"])
    assert applied_from == clock.demo_at(settings, settings.demo_date)
    assert applied_to == clock.demo_at(settings, date(2027, 2, 23), 20)
    assert ended_at.date() == settings.demo_date
