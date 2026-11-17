"""WWS events strictly against the own proto and the 7.2 examples (no database)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from google.protobuf import any_pb2, json_format
from google.protobuf.descriptor_pool import DescriptorPool

from gposdemo.common.config import Settings
from gposdemo.common.descriptors import Types
from gposdemo.common.jsonutil import compact, parse_strict
from gposdemo.wws.analytics import PriceAction
from gposdemo.wws.events import Authorization, PriceEvents

TZ = ZoneInfo("Europe/Berlin")
APPLIED_AT = datetime.fromtimestamp(1794393700, UTC) + timedelta(milliseconds=120)
ENDED_AT = datetime.fromtimestamp(1794394900, UTC)

# 7.2, verbatim (line breaks only)
APPLIED_EXAMPLE = {
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
    "originator": {"identityId": "gpos-engine"}, "approver": {"identityId": "role:marktleitung"}}
ENDED_EXAMPLE = {
    "@type": "type.googleapis.com/de.showcase.wws.v1.event.PriceChangeEnded",
    "header": {"eventTimestamp": {"seconds": "1794394900"}},
    "metadata": {"offset": "3", "creationTimestamp": {"seconds": "1794394900"},
                 "traceId": "reset-booth"},
    "actionId": "PA-270216-0003", "articleNumber": "100001", "storeId": "101",
    "reason": "reset", "endedAt": {"seconds": "1802769300", "offset": 60}}


def ente_action(**changes: object) -> PriceAction:
    base = PriceAction(
        action_id="PA-270216-0003", article_number="100001", store_id="101", kind="BOOTH",
        regular_price=Decimal("9.99"), action_price=Decimal("7.99"), pct_shown=20,
        ref30=Decimal("9.99"), valid_from=datetime(2027, 2, 16, tzinfo=TZ),
        valid_to=datetime(2027, 2, 23, 20, tzinfo=TZ), proposal_id="GP-270216-0003",
        reason_code="REASON_CODE_SLOW_SELLER", originator="gpos-engine",
        approver="role:marktleitung")
    return PriceAction(**{**base.__dict__, **changes})


@pytest.fixture
def types(showcase_pool: DescriptorPool) -> Types:
    return Types(showcase_pool)


def events(types: Types, settings: Settings, clock: datetime) -> PriceEvents:
    return PriceEvents(types, settings, lambda: clock)


def reparse(payload: str, types: Types, name: str) -> object:
    """Strict re-parse: Any with ``@type``, then the event without unknown fields."""
    wrapped = parse_strict(payload, any_pb2.Any(), types.pool)
    assert wrapped.type_url == f"type.googleapis.com/de.showcase.wws.v1.event.{name}"
    msg = types.new(f"de.showcase.wws.v1.event.{name}")
    assert wrapped.Unpack(msg)
    return msg


def test_price_change_applied_is_the_7_2_example(types: Types, settings: Settings) -> None:
    event = events(types, settings, APPLIED_AT).build_applied(
        ente_action(), "GEBIT Ente (Quietscheente gelb)", offset=2, trace_id="GP-270216-0003",
        originator=Authorization("gpos-engine"), approver=Authorization("role:marktleitung"))
    assert event.payload_text == compact(APPLIED_EXAMPLE)
    assert "\n" not in event.payload_text and "\\u" not in event.payload_text
    assert event.topic == "showcase/wws/v1/price/PriceChangeApplied/DE/999/101/100001"
    assert (event.aggregate_id, event.offset) == ("100001:101", 2)
    assert event.event_type == "de.showcase.wws.v1.event.PriceChangeApplied"
    assert event.props == {"eventType": "de.showcase.wws.v1.event.PriceChangeApplied",
                           "source": "gpos-wws", "apiVersion": "wws-v1",
                           "traceId": "GP-270216-0003"}
    msg = reparse(event.payload_text, types, "PriceChangeApplied")
    assert json_format.MessageToDict(msg)["actionPrice"]["amount"]["intVal"] == "799"


def test_valid_from_is_business_date_midnight(types: Types, settings: Settings) -> None:
    body = json.loads(events(types, settings, APPLIED_AT).build_applied(
        ente_action(), "x", offset=1, trace_id="", originator=Authorization("gpos-engine"),
        approver=Authorization("role:marktleitung")).payload_text)
    valid_from = datetime.fromtimestamp(int(body["validFrom"]["seconds"]), TZ)
    valid_to = datetime.fromtimestamp(int(body["validTo"]["seconds"]), TZ)
    assert valid_from == datetime(2027, 2, 16, 0, 0, tzinfo=TZ) == datetime.combine(
        settings.demo_date, datetime.min.time(), TZ)
    assert valid_to == datetime(2027, 2, 23, 20, 0, tzinfo=TZ)
    assert "traceId" not in body["metadata"]  # empty trace id is not sent


def test_price_change_ended_is_the_7_2_example(types: Types, settings: Settings) -> None:
    ended = ente_action(ended_at=datetime(2027, 2, 16, 10, 15, tzinfo=TZ), end_reason="reset")
    event = events(types, settings, ENDED_AT).build_ended(ended, offset=3,
                                                          trace_id="reset-booth")
    assert event.payload_text == compact(ENDED_EXAMPLE)
    assert event.topic == "showcase/wws/v1/price/PriceChangeEnded/DE/999/101/100001"
    assert event.props["eventType"] == "de.showcase.wws.v1.event.PriceChangeEnded"
    reparse(event.payload_text, types, "PriceChangeEnded")


def test_ended_event_needs_an_ended_action(types: Types, settings: Settings) -> None:
    with pytest.raises(ValueError, match="not ended"):
        events(types, settings, ENDED_AT).build_ended(ente_action(), offset=1, trace_id="")


def test_restored_central_action_event(types: Types, settings: Settings) -> None:
    central = ente_action(action_id="PA-SEED-100009-199", article_number="100009",
                          store_id="199", kind="CENTRAL", regular_price=Decimal("3.49"),
                          action_price=Decimal("2.99"), pct_shown=14, ref30=Decimal("3.49"),
                          proposal_id="", reason_code="REASON_CODE_CENTRAL_PROMOTION",
                          originator="zentrale", approver="")
    event = events(types, settings, APPLIED_AT).build_applied(
        central, "Glühwein rot", offset=4, trace_id="reset-day",
        originator=Authorization("zentrale"), approver=None)
    body = json.loads(event.payload_text)
    assert (body["kind"], body["originator"], body["articleName"]) == (
        "PRICE_ACTION_KIND_CENTRAL", {"identityId": "zentrale"}, "Glühwein rot")
    assert "approver" not in body and "proposalId" not in body
    assert event.topic == "showcase/wws/v1/price/PriceChangeApplied/DE/999/199/100009"
    reparse(event.payload_text, types, "PriceChangeApplied")


def test_unknown_reason_code_is_rejected(types: Types, settings: Settings) -> None:
    with pytest.raises(json_format.ParseError):
        events(types, settings, APPLIED_AT).build_applied(
            ente_action(reason_code="REASON_CODE_CHEAP"), "x", offset=1, trace_id="",
            originator=Authorization("gpos-engine"), approver=None)
