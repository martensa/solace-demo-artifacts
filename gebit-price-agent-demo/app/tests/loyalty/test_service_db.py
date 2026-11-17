"""gpos-loyalty against the seeded scratch DB (marker ``db``; 4.4, 6.4-6.8, 8.4, 11.7, 13.1).

Every call goes through the real gRPC server or MCP app of ``create(...)``. Tests that
write use the ``restore`` fixture (day reset afterwards).
"""

from __future__ import annotations

import json
import secrets
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import grpc
import pytest
from google.protobuf import json_format
from google.protobuf.message import Message
from starlette.testclient import TestClient

from gposdemo.common import grpcutil, mcputil
from gposdemo.common.bus import MemoryBus
from gposdemo.common.clock import demo_now
from gposdemo.common.config import Settings
from gposdemo.common.db import Db
from gposdemo.loyalty import LoyaltyApp
from tests.loyalty.helpers import D, local, rpc_error, summary

pytestmark = pytest.mark.db

HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
ESPRESSO_WEEKLY = [22, 24, 21, 23, 13, 12, 11, 12]
SEED_PURCHASES = 52  # 12 + 13 + 12 + 15 + 0 (5.7)
MEMBERS = ("M-1001", "M-1002", "M-1003", "M-1004", "M-1005")
BEHAVIOUR_EXAMPLE = (
    '{"membership_id":"M-1001","article_number":"100012","consent_profiling":true,'
    '"member_purchases_8w":2,"member_purchases_12w":4,"days_since_last":35,'
    '"median_interval_days":14,"overdue_factor":2.5,'
    '"cardholder_weekly":[22,24,21,23,13,12,11,12],"cardholder_drop_pct":46.7}')
PROFILE_M1001 = (
    '{"membership_id":"M-1001","persona":"Kaffeepause","segment":"Stammkundin, preisbewusst",'
    '"salutation":"Sie","consent":{"offers":true,"profiling":true},'
    '"tags":["kaffee_tee","molkerei_fruehstueck"],"top_categories_8w":['
    '{"category":"molkerei_fruehstueck","purchases":8,"days_since_last":7},'
    '{"category":"suesswaren_snacks","purchases":4,"days_since_last":14},'
    '{"category":"kaffee_tee","purchases":2,"days_since_last":35}]}')


def _behaviour(client: grpcutil.Client, member: str, article: str) -> Message:
    return client.call("GetPurchaseBehaviour", {"membership_id": member,
                                                "article_number": article})


def _member_fields(msg: Message) -> tuple[int, int, int, int]:
    return (msg.member_purchases_8w, msg.member_purchases_12w, msg.days_since_last,
            msg.median_interval_days)


def _report(client: grpcutil.Client, body: dict[str, Any]) -> None:
    client.call("ReportPurchase", {"header": {"originator": {"identity_id": "pos-sim"}},
                                   "purchase": body})


def _purchase_rows(db: Db, tx_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    head = db.fetch("select member_id, is_seed, visit_id, transaction_type, total_eur "
                    "from loyalty.purchase where purchase_transaction_id = %s", (tx_id,))
    lines = db.fetch("select article_number, category, item_count from loyalty.purchase_line "
                     "where purchase_transaction_id = %s order by position_id", (tx_id,))
    return head, lines


@pytest.fixture
def mcp_http(loyalty_app: LoyaltyApp, telemetry_bus: MemoryBus) -> Iterator[TestClient]:
    telemetry_bus.clear()
    with TestClient(mcputil.http_app(loyalty_app.mcp)) as http:
        yield http


def _tool(http: TestClient, tool: str, arguments: dict[str, str]) -> dict[str, Any]:
    reply = http.post(mcputil.MCP_PATH, headers=HEADERS, json={
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": tool, "arguments": arguments}})
    assert reply.status_code == 200, reply.text
    return reply.json()["result"]


# --------------------------------------------------------------------------- behaviour
def test_kaffeepause_espresso_golden_values(client: grpcutil.Client) -> None:
    """6.8: 2 purchases in [D-56, D-1] (29.12., 12.01.), 4 in 12 weeks, 35 days, 14."""
    msg = _behaviour(client, "M-1001", "100012")
    assert _member_fields(msg) == (2, 4, 35, 14)
    assert msg.consent_profiling
    assert (msg.persona_label, msg.segment_label) == ("Kaffeepause", "Stammkundin, preisbewusst")
    assert list(msg.cardholder_weekly) == ESPRESSO_WEEKLY
    assert (msg.cardholder_drop_pct.scale, msg.cardholder_drop_pct.int_val) == (1, 467)


def test_espresso_without_profiling_consent(client: grpcutil.Client) -> None:
    """S6 / 6.8 M-1003: member fields empty (0 / -1), the anonymous trend stays."""
    msg = _behaviour(client, "M-1003", "100012")
    assert not msg.consent_profiling
    assert _member_fields(msg) == (0, 0, -1, 0)
    assert list(msg.cardholder_weekly) == ESPRESSO_WEEKLY
    assert msg.persona_label == "Feierabend"


def test_familieneinkauf_bought_the_duck_once(client: grpcutil.Client) -> None:
    """6.8 100001 + M-1002: only 1 purchase in 8 weeks (23.01.)."""
    assert _member_fields(_behaviour(client, "M-1002", "100001")) == (1, 1, 24, 0)


def test_cardholder_trend_follows_rule_6_5(client: grpcutil.Client) -> None:
    """Default rule: weekly units x 0.55 half up (Ente: w = 34 36 31 28 22 16 12 9)."""
    msg = _behaviour(client, "M-1004", "100001")
    assert list(msg.cardholder_weekly) == [19, 20, 17, 15, 12, 9, 7, 5]
    assert (msg.cardholder_drop_pct.scale, msg.cardholder_drop_pct.int_val) == (1, 535)


def test_booth_purchase_never_changes_the_signals(client: grpcutil.Client, loyalty_db: Db,
                                                  loyalty_settings: Settings,
                                                  loyalty_app: LoyaltyApp,
                                                  restore: None) -> None:
    """I11: two booth purchases with Espresso (business date D) change nothing."""
    tx_ids = [str(uuid.uuid4()) for _ in range(2)]
    for tx_id in tx_ids:
        _report(client, summary(tx_id, "M-1001", demo_now(loyalty_settings),
                                ["100012", "100017"]))
        assert _member_fields(_behaviour(client, "M-1001", "100012")) == (2, 4, 35, 14)
    head, lines = _purchase_rows(loyalty_db, tx_ids[0])
    assert head == [{"member_id": "M-1001", "is_seed": False, "visit_id": "booth",
                     "transaction_type": "SALE", "total_eur": Decimal("16.98")}]
    assert [ln["article_number"] for ln in lines] == ["100012", "100017"]
    result = loyalty_app.service.reset_demo_state("booth", False, "pytest")
    assert (result.scope, result.purchases_deleted) == ("booth", 2)
    assert _purchase_rows(loyalty_db, tx_ids[0]) == ([], [])


@pytest.mark.parametrize(("day", "hms", "expected"), [
    (D - timedelta(days=57), (23, 59, 59), (0, 1, 57)),
    (D - timedelta(days=56), (0, 0, 0), (1, 1, 56)),
    (D - timedelta(days=85), (23, 59, 59), (0, 0, 85)),
    (D - timedelta(days=84), (0, 0, 0), (0, 1, 84)),
    (D - timedelta(days=1), (23, 59, 59), (1, 1, 1)),
    (D, (0, 0, 0), (0, 0, -1)),
])
def test_window_edges_in_business_time(client: grpcutil.Client, loyalty_settings: Settings,
                                       restore: None, day: date, hms: tuple[int, int, int],
                                       expected: tuple[int, int, int]) -> None:
    """Edges +- 1 day at local midnight: the business date in GPOS_TZ decides, not UTC
    (00:00 in Berlin is 23:00 UTC of the day before). M-1004 never bought Kaffee Crema."""
    assert _member_fields(_behaviour(client, "M-1004", "100013")) == (0, 0, -1, 0)
    closed = local(loyalty_settings, day, *hms)
    _report(client, summary(str(uuid.uuid4()), "M-1004", closed, ["100013"]))
    assert _member_fields(_behaviour(client, "M-1004", "100013"))[:3] == expected


def test_void_reverses_a_reported_sale(client: grpcutil.Client, loyalty_settings: Settings,
                                       restore: None) -> None:
    sale = str(uuid.uuid4())
    _report(client, summary(sale, "M-1004", local(loyalty_settings, D - timedelta(days=10), 11),
                            ["100013"]))
    assert _member_fields(_behaviour(client, "M-1004", "100013"))[:3] == (1, 1, 10)
    _report(client, summary(str(uuid.uuid4()), "M-1004",
                            local(loyalty_settings, D - timedelta(days=9), 11), ["100013"],
                            kind="VOID", referenced=sale))
    assert _member_fields(_behaviour(client, "M-1004", "100013")) == (0, 0, -1, 0)


# --------------------------------------------------------------------------- ReportPurchase
def test_report_is_idempotent_and_stores_lines_only_with_consent(
        client: grpcutil.Client, loyalty_db: Db, loyalty_settings: Settings,
        restore: None) -> None:
    now = demo_now(loyalty_settings)
    kaffeepause, feierabend, anonymous = (str(uuid.uuid4()) for _ in range(3))
    for _ in range(2):
        _report(client, summary(kaffeepause, "M-1001", now, ["100012"]))
    _report(client, summary(feierabend, "M-1003", now, ["100012"]))
    _report(client, summary(anonymous, "", now, ["100012"]))
    assert [len(part) for part in _purchase_rows(loyalty_db, kaffeepause)] == [1, 1]
    head, lines = _purchase_rows(loyalty_db, feierabend)
    assert head[0]["member_id"] == "M-1003" and lines == []  # no profiling consent
    head, lines = _purchase_rows(loyalty_db, anonymous)
    assert head[0]["member_id"] is None and lines == []


def test_report_skips_lines_of_unknown_articles(client: grpcutil.Client, loyalty_db: Db,
                                                loyalty_settings: Settings,
                                                restore: None) -> None:
    tx_id = str(uuid.uuid4())
    body = summary(tx_id, "M-1001", demo_now(loyalty_settings), ["100012", "100017"])
    body["lines"][1]["article_number"] = "999999"
    _report(client, body)
    assert [ln["article_number"] for ln in _purchase_rows(loyalty_db, tx_id)[1]] == ["100012"]


def test_report_for_an_unknown_member(client: grpcutil.Client,
                                      loyalty_settings: Settings) -> None:
    body = summary(str(uuid.uuid4()), "M-9999", demo_now(loyalty_settings), ["100012"])
    err = rpc_error(lambda: _report(client, body))
    assert err.code() == grpc.StatusCode.NOT_FOUND
    assert grpcutil.error_code(err) == "LOY-002"
    assert err.details() == "LOY-002: Mitglied M-9999 unbekannt"


# --------------------------------------------------------------------------- errors
def test_unknown_member_and_article(client: grpcutil.Client) -> None:
    err = rpc_error(lambda: _behaviour(client, "M-9999", "100012"))
    assert (err.code(), grpcutil.error_code(err)) == (grpc.StatusCode.NOT_FOUND, "LOY-002")
    err = rpc_error(lambda: client.call("GetMemberProfile", {"membership_id": "M-9999"}))
    assert (err.code(), grpcutil.error_code(err)) == (grpc.StatusCode.NOT_FOUND, "LOY-002")
    err = rpc_error(lambda: _behaviour(client, "M-1001", "999999"))
    assert err.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert err.details() == "Artikel 999999 unbekannt"


# --------------------------------------------------------------------------- membership
def _resolve(client: grpcutil.Client, card: str) -> dict[str, Any]:
    msg = client.call("ResolveMembership", {
        "membership_identification_value": card,
        "purchase_transaction_id": str(uuid.uuid4()), "location": "Root.DE.999.101.01"})
    return json_format.MessageToDict(msg, preserving_proto_field_name=True)


def test_resolve_membership(client: grpcutil.Client) -> None:
    assert _resolve(client, "CLUB-1001") == {
        "membership_identification_value": "CLUB-1001", "membership_id": "M-1001",
        "program_id": "POINTS-ID", "program_name": "Markt-Bonus",
        "customer_id": "CUST-DEMO-M-1001", "verified": True,
        "status": "MEMBERSHIP_STATUS_ACTIVE",
        "accounts": [{"account_id": "ACC-M-1001-POINTS", "account_type": "POINTS-ACCOUNT-ID",
                      "account_currency_name": "Points", "account_balance": {"scale": 2}}],
        "membership_preferences": [{"key": "digitalReceipt",
                                    "typed_value": {"bool_value": False}}]}
    guest = _resolve(client, "CLUB-GAST")
    assert (guest["membership_id"], guest["anonymous"], guest["status"]) == (
        "M-1005", True, "MEMBERSHIP_STATUS_ACTIVE")
    assert "customer_id" not in guest
    assert _resolve(client, "CLUB-9999") == {"membership_identification_value": "CLUB-9999",
                                             "status": "MEMBERSHIP_STATUS_UNKNOWN"}


def test_blocked_card_is_not_active(client: grpcutil.Client, loyalty_db: Db) -> None:
    loyalty_db.fetch("update loyalty.card set status = 'BLOCKED' where card_value = 'CLUB-1002'")
    try:
        blocked = _resolve(client, "CLUB-1002")
    finally:
        loyalty_db.fetch("update loyalty.card set status = 'ACTIVE' "
                         "where card_value = 'CLUB-1002'")
    assert (blocked["status"], blocked["verified"], blocked["membership_id"]) == (
        "MEMBERSHIP_STATUS_BLOCKED", True, "M-1002")


# --------------------------------------------------------------------------- profile
def test_member_profile_message(client: grpcutil.Client) -> None:
    data = json_format.MessageToDict(
        client.call("GetMemberProfile", {"membership_id": "M-1001"}),
        preserving_proto_field_name=True)
    assert data["history"] == [
        {"category": "molkerei_fruehstueck", "purchases_8w": 8, "days_since_last": 7},
        {"category": "suesswaren_snacks", "purchases_8w": 4, "days_since_last": 14},
        {"category": "kaffee_tee", "purchases_8w": 2, "days_since_last": 35}]
    assert (data["salutation"], data["history_used"]) == ("SALUTATION_FORMAL", True)
    assert data["preference_tags"] == ["kaffee_tee", "molkerei_fruehstueck"]
    assert data["consent"]["changed_at"]["offset"] == 60  # GPOS_TZ, not the DB session zone
    assert data["consent"]["policy_version"] == "2027-01"
    feierabend = client.call("GetMemberProfile", {"membership_id": "M-1003"})
    assert not feierabend.history and not feierabend.history_used
    assert not feierabend.consent.profiling and feierabend.consent.offers


def test_profile_tool_for_every_card_has_no_personal_data(mcp_http: TestClient) -> None:
    texts = {m: _tool(mcp_http, "get_member_profile", {"membership_id": m, "ref": "GR-1"})
             for m in MEMBERS}
    assert texts["M-1001"]["content"][0]["text"] == PROFILE_M1001
    for member, result in texts.items():
        text = result["content"][0]["text"]
        assert result["isError"] is False and "structuredContent" not in result
        assert "CUST-DEMO" not in text and "CLUB-" not in text, member
        assert set(json.loads(text)) == {"membership_id", "persona", "segment", "salutation",
                                         "consent", "tags", "top_categories_8w"}
    guest = json.loads(texts["M-1005"]["content"][0]["text"])
    assert guest["top_categories_8w"] is None and guest["tags"] == []
    family = json.loads(texts["M-1002"]["content"][0]["text"])
    assert family["salutation"] == "du" and len(family["top_categories_8w"]) == 3


# --------------------------------------------------------------------------- MCP + telemetry
def test_behaviour_tool_text_is_the_8_4_example(mcp_http: TestClient,
                                                telemetry_bus: MemoryBus) -> None:
    result = _tool(mcp_http, "get_purchase_behaviour",
                   {"membership_id": "M-1001", "article_number": "100012",
                    "ref": "GR-270216-0007"})
    assert result["content"][0]["text"] == BEHAVIOUR_EXAMPLE
    [event] = telemetry_bus.messages("gpos/v1/telemetry/tool/loyalty/get_purchase_behaviour")
    body = event.json()
    assert (body["caller"], body["ref"], body["ok"]) == ("agent", "GR-270216-0007", True)
    assert body["summary"] == ("100012 · M-1001: 2 Käufe in 8 Wo., zuletzt vor 35 Tagen · "
                               "Kartenkunden 46,7 % seltener")


def test_behaviour_tool_without_consent(mcp_http: TestClient) -> None:
    result = _tool(mcp_http, "get_purchase_behaviour",
                   {"membership_id": "M-1003", "article_number": "100012"})
    data = json.loads(result["content"][0]["text"])
    assert data["consent_profiling"] is False
    assert all(data[k] is None for k in ("member_purchases_8w", "member_purchases_12w",
                                         "days_since_last", "median_interval_days",
                                         "overdue_factor"))
    assert data["cardholder_drop_pct"] == 46.7


def test_unknown_member_reaches_the_agent_as_tool_error(mcp_http: TestClient,
                                                        telemetry_bus: MemoryBus) -> None:
    result = _tool(mcp_http, "get_purchase_behaviour",
                   {"membership_id": "M-9999", "article_number": "100012"})
    assert result["isError"] is True
    assert "Mitglied M-9999 unbekannt" in result["content"][0]["text"]
    [event] = telemetry_bus.messages("gpos/v1/telemetry/tool/loyalty/>")
    assert event.json()["ok"] is False


def test_every_tool_result_fits_the_agent_limit(loyalty_app: LoyaltyApp,
                                                loyalty_db: Db) -> None:
    articles = [r["article_number"] for r in loyalty_db.fetch(
        "select article_number from loyalty.article_ref order by 1")]
    assert len(articles) == 30
    service = loyalty_app.service
    for member in MEMBERS:
        results = [mcputil.text_result(service.get_member_profile(member))]
        results += [mcputil.text_result(service.get_purchase_behaviour(member, a))
                    for a in articles]
        for result in results:
            assert mcputil.within_limits(result, "agent"), mcputil.measure(result)


def test_health_is_ok(mcp_http: TestClient) -> None:
    reply = mcp_http.get("/health")
    assert (reply.status_code, reply.json()) == (200, {"status": "ok", "db": True, "bus": True})


# --------------------------------------------------------------------------- consent + reset
def _consent(client: grpcutil.Client, member: str) -> dict[str, Any]:
    msg = client.call("GetMemberProfile", {"membership_id": member})
    return json_format.MessageToDict(msg.consent, preserving_proto_field_name=True,
                                     always_print_fields_with_no_presence=True)


def _change(client: grpcutil.Client, actor: str, member: str, **flags: Any) -> None:
    client.call("ChangeConsent", {"header": {"originator": {"identity_id": actor}},
                                  "membership_id": member, "consent": flags})


def test_change_consent_and_resets(client: grpcutil.Client, loyalty_db: Db,
                                   restore: None) -> None:
    actor = f"pytest-{secrets.token_hex(3)}"
    seeded = _consent(client, "M-1001")
    assert (seeded["offers"], seeded["profiling"], seeded["policy_version"]) == (
        True, True, "2027-01")
    _change(client, actor, "M-1001", offers=True, profiling=False)
    assert _member_fields(_behaviour(client, "M-1001", "100012")) == (0, 0, -1, 0)
    _change(client, actor, "M-1001", offers=False, profiling=True, policy_version="2027-02")
    changed = _consent(client, "M-1001")
    assert (changed["offers"], changed["profiling"], changed["policy_version"]) == (
        False, True, "2027-02")

    client.call("ResetDemoState", {"header": {"originator": {"identity_id": actor}},
                                   "visit_id": "booth"})
    assert _consent(client, "M-1001")["offers"] is False  # booth keeps consents
    client.call("ResetDemoState", {"header": {"originator": {"identity_id": actor}},
                                   "visit_id": "booth", "full_day_reset": True})
    assert _consent(client, "M-1001") == seeded
    assert _member_fields(_behaviour(client, "M-1001", "100012")) == (2, 4, 35, 14)
    source = loyalty_db.fetch("select source from loyalty.consent where member_id = 'M-1001'")
    assert source == [{"source": "seed"}]
    audit = loyalty_db.fetch("select action, ref from loyalty.audit where actor = %s "
                             "order by id", (actor,))
    assert [(a["action"], a["ref"]) for a in audit] == [
        ("ConsentSeedSnapshot", "M-1001"), ("ChangeConsent", "M-1001"),
        ("ChangeConsent", "M-1001"), ("ResetDemoState", "booth"), ("ResetDemoState", "day")]


def test_change_consent_of_an_unknown_member(client: grpcutil.Client) -> None:
    err = rpc_error(lambda: _change(client, "pytest", "M-9999", offers=True, profiling=True))
    assert (err.code(), grpcutil.error_code(err)) == (grpc.StatusCode.NOT_FOUND, "LOY-002")


def test_resets_never_touch_seed_purchases(loyalty_app: LoyaltyApp, loyalty_db: Db) -> None:
    def seeded() -> int:
        return int(loyalty_db.fetch("select count(*) as n from loyalty.purchase "
                                    "where is_seed")[0]["n"])

    assert seeded() == SEED_PURCHASES
    booth = loyalty_app.service.reset_demo_state("booth", False, "pytest")
    day = loyalty_app.service.reset_demo_state("", True, "pytest")
    assert (booth.scope, day.scope, day.consents_restored) == ("booth", "day", [])
    assert seeded() == SEED_PURCHASES
