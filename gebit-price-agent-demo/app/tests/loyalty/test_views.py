"""Agent-tool JSON (8.4) and proto mapping (4.4) of gpos-loyalty, without DB or broker."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from google.protobuf import descriptor_pool, json_format
from google.protobuf.message import Message

from gposdemo.common import mcputil
from gposdemo.common.descriptors import Types
from gposdemo.common.jsonutil import compact
from gposdemo.loyalty.behaviour import CategoryFrequency
from gposdemo.loyalty.server import (
    behaviour_json,
    profile_json,
    report_from_message,
    resolution_json,
)
from gposdemo.loyalty.service import (
    Account,
    Consent,
    MemberProfile,
    PurchaseBehaviour,
    Resolution,
    behaviour_view,
    profile_view,
)
from tests.loyalty.helpers import summary

DATATYPE = "de.showcase.loyalty.v1.datatype"
BERLIN = ZoneInfo("Europe/Berlin")
SEEDED_AT = datetime(2026, 11, 18, tzinfo=BERLIN)  # D-90 00:00 (WP-B seed)
# 8.4 example of get_purchase_behaviour, compact as it is sent.
BEHAVIOUR_EXAMPLE = (
    '{"membership_id":"M-1001","article_number":"100012","consent_profiling":true,'
    '"member_purchases_8w":2,"member_purchases_12w":4,"days_since_last":35,'
    '"median_interval_days":14,"overdue_factor":2.5,'
    '"cardholder_weekly":[22,24,21,23,13,12,11,12],"cardholder_drop_pct":46.7}')
PERSONAL_KEYS = {"name", "first_name", "last_name", "age", "birthday", "sex", "gender",
                 "address", "email", "phone", "customer_ref", "customer_id", "card",
                 "card_value"}


def _behaviour(**overrides: Any) -> PurchaseBehaviour:
    values: dict[str, Any] = {
        "membership_id": "M-1001", "article_number": "100012", "consent_profiling": True,
        "persona_label": "Kaffeepause", "segment_label": "Stammkundin, preisbewusst",
        "member_purchases_8w": 2, "member_purchases_12w": 4, "days_since_last": 35,
        "median_interval_days": 14, "cardholder_weekly": [22, 24, 21, 23, 13, 12, 11, 12],
        "cardholder_drop_pct": Decimal("46.7")}
    return PurchaseBehaviour(**{**values, **overrides})


def _profile(profiling: bool = True, history: list[CategoryFrequency] | None = None
             ) -> MemberProfile:
    return MemberProfile(
        membership_id="M-1001", persona_label="Kaffeepause",
        segment_label="Stammkundin, preisbewusst", salutation="FORMAL",
        tags=["kaffee_tee", "molkerei_fruehstueck"],
        consent=Consent(offers=True, profiling=profiling, digital_receipt=False,
                        policy_version="2027-01", changed_at=SEEDED_AT),
        points_balance=Decimal("0.00"),
        history=history if history is not None else [
            CategoryFrequency("molkerei_fruehstueck", 8, 7),
            CategoryFrequency("suesswaren_snacks", 4, 14),
            CategoryFrequency("kaffee_tee", 2, 35)],
        open_coupons=0, history_used=profiling)


def _keys(obj: Any) -> set[str]:
    if isinstance(obj, dict):
        return set(obj) | {k for v in obj.values() for k in _keys(v)}
    if isinstance(obj, list):
        return {k for v in obj for k in _keys(v)}
    return set()


def _parse(pool: descriptor_pool.DescriptorPool, type_name: str, body: dict[str, Any]
           ) -> Message:
    msg = Types(pool).new(type_name)
    return json_format.ParseDict(body, msg, descriptor_pool=pool)


# --------------------------------------------------------------------------- 8.4 views
def test_behaviour_view_is_the_8_4_example() -> None:
    assert compact(behaviour_view(_behaviour())) == BEHAVIOUR_EXAMPLE


def test_behaviour_view_without_consent_has_null_member_fields() -> None:
    view = behaviour_view(_behaviour(consent_profiling=False, member_purchases_8w=0,
                                     member_purchases_12w=0, days_since_last=-1,
                                     median_interval_days=0))
    assert view == {"membership_id": "M-1001", "article_number": "100012",
                    "consent_profiling": False, "member_purchases_8w": None,
                    "member_purchases_12w": None, "days_since_last": None,
                    "median_interval_days": None, "overdue_factor": None,
                    "cardholder_weekly": [22, 24, 21, 23, 13, 12, 11, 12],
                    "cardholder_drop_pct": 46.7}


def test_behaviour_view_never_bought_with_consent() -> None:
    view = behaviour_view(_behaviour(member_purchases_8w=0, member_purchases_12w=0,
                                     days_since_last=-1, median_interval_days=0))
    assert (view["member_purchases_8w"], view["member_purchases_12w"]) == (0, 0)
    assert view["days_since_last"] is None and view["median_interval_days"] is None
    assert view["overdue_factor"] is None


def test_profile_view_shape_and_top_three() -> None:
    history = [CategoryFrequency("molkerei_fruehstueck", 8, 7),
               CategoryFrequency("suesswaren_snacks", 4, 14),
               CategoryFrequency("kaffee_tee", 2, 35),
               CategoryFrequency("getraenke", 1, 40)]
    assert compact(profile_view(_profile(history=history))) == (
        '{"membership_id":"M-1001","persona":"Kaffeepause",'
        '"segment":"Stammkundin, preisbewusst","salutation":"Sie",'
        '"consent":{"offers":true,"profiling":true},'
        '"tags":["kaffee_tee","molkerei_fruehstueck"],"top_categories_8w":['
        '{"category":"molkerei_fruehstueck","purchases":8,"days_since_last":7},'
        '{"category":"suesswaren_snacks","purchases":4,"days_since_last":14},'
        '{"category":"kaffee_tee","purchases":2,"days_since_last":35}]}')


def test_profile_view_without_profiling_consent() -> None:
    view = profile_view(_profile(profiling=False, history=[]))
    assert view["top_categories_8w"] is None
    assert view["consent"] == {"offers": True, "profiling": False}
    assert view["tags"] == ["kaffee_tee", "molkerei_fruehstueck"]


def test_informal_salutation_is_du() -> None:
    profile = _profile().model_copy(update={"salutation": "INFORMAL"})
    assert profile_view(profile)["salutation"] == "du"


def test_views_carry_no_personal_attributes() -> None:
    for view in (behaviour_view(_behaviour()), profile_view(_profile())):
        assert not _keys(view) & PERSONAL_KEYS


def test_views_stay_within_the_agent_limit() -> None:
    tags = ["kaffee_tee", "molkerei_fruehstueck", "obst_gemuese", "suesswaren_snacks",
            "getraenke", "drogerie_haushalt", "spielwaren_geschenke", "buch", "familie",
            "saison"]
    big_profile = _profile().model_copy(update={
        "persona_label": "P" * 60, "segment_label": "S" * 80, "tags": tags,
        "history": [CategoryFrequency("spielwaren_geschenke", 999, 999)] * 8})
    big_behaviour = _behaviour(membership_id="M-" + "9" * 30, article_number="1" * 20,
                               member_purchases_8w=999, member_purchases_12w=999,
                               days_since_last=9999, median_interval_days=1,
                               cardholder_weekly=[99999] * 8,
                               cardholder_drop_pct=Decimal("-99999.9"))
    for view in (profile_view(big_profile), behaviour_view(big_behaviour)):
        result = mcputil.text_result(view)
        assert mcputil.within_limits(result, "agent"), mcputil.measure(result)


# --------------------------------------------------------------------------- proto mapping
def test_behaviour_message(showcase_pool: descriptor_pool.DescriptorPool) -> None:
    msg = _parse(showcase_pool, f"{DATATYPE}.PurchaseBehaviour", behaviour_json(_behaviour()))
    assert json_format.MessageToDict(msg, preserving_proto_field_name=True) == {
        "membership_id": "M-1001", "article_number": "100012", "consent_profiling": True,
        "persona_label": "Kaffeepause", "segment_label": "Stammkundin, preisbewusst",
        "member_purchases_8w": 2, "member_purchases_12w": 4, "days_since_last": 35,
        "median_interval_days": 14, "cardholder_weekly": [22, 24, 21, 23, 13, 12, 11, 12],
        "cardholder_drop_pct": {"scale": 1, "int_val": "467"}}


def test_behaviour_message_without_consent(showcase_pool: descriptor_pool.DescriptorPool
                                           ) -> None:
    b = _behaviour(consent_profiling=False, member_purchases_8w=0, member_purchases_12w=0,
                   days_since_last=-1, median_interval_days=0)
    msg = _parse(showcase_pool, f"{DATATYPE}.PurchaseBehaviour", behaviour_json(b))
    assert (msg.member_purchases_8w, msg.member_purchases_12w, msg.days_since_last,
            msg.median_interval_days) == (0, 0, -1, 0)
    assert list(msg.cardholder_weekly) == [22, 24, 21, 23, 13, 12, 11, 12]


def test_profile_message(showcase_pool: descriptor_pool.DescriptorPool) -> None:
    msg = _parse(showcase_pool, f"{DATATYPE}.MemberProfile", profile_json(_profile()))
    data = json_format.MessageToDict(msg, preserving_proto_field_name=True)
    assert data["salutation"] == "SALUTATION_FORMAL"
    assert data["preference_tags"] == ["kaffee_tee", "molkerei_fruehstueck"]
    assert data["consent"]["changed_at"] == {"seconds": str(int(SEEDED_AT.timestamp())),
                                             "offset": 60}
    assert data["history"][0] == {"category": "molkerei_fruehstueck", "purchases_8w": 8,
                                  "days_since_last": 7}
    assert data["history_used"] is True and data["segment_label"] == "Stammkundin, preisbewusst"
    assert data["points_balance"] == {"scale": 2}  # 0.00: int_val 0 is the default


def _resolution() -> Resolution:
    return Resolution(card_value="CLUB-1001", status="ACTIVE", verified=True,
                      membership_id="M-1001", program_id="POINTS-ID",
                      program_name="Markt-Bonus", customer_id="CUST-DEMO-M-1001",
                      accounts=[Account(account_id="ACC-M-1001-POINTS",
                                        account_type="POINTS-ACCOUNT-ID",
                                        currency_name="Points", balance=Decimal("12.50"))])


def test_resolution_message(showcase_pool: descriptor_pool.DescriptorPool) -> None:
    msg = _parse(showcase_pool, f"{DATATYPE}.MembershipResolution",
                 resolution_json(_resolution()))
    data = json_format.MessageToDict(msg, preserving_proto_field_name=True)
    assert data == {
        "membership_identification_value": "CLUB-1001", "membership_id": "M-1001",
        "program_id": "POINTS-ID", "program_name": "Markt-Bonus",
        "customer_id": "CUST-DEMO-M-1001", "verified": True,
        "status": "MEMBERSHIP_STATUS_ACTIVE",
        "accounts": [{"account_id": "ACC-M-1001-POINTS", "account_type": "POINTS-ACCOUNT-ID",
                      "account_currency_name": "Points",
                      "account_balance": {"scale": 2, "int_val": "1250"}}],
        "membership_preferences": [{"key": "digitalReceipt",
                                    "typed_value": {"bool_value": False}}]}


def test_unknown_card_resolution(showcase_pool: descriptor_pool.DescriptorPool) -> None:
    unknown = Resolution(card_value="CLUB-9999", status="UNKNOWN", verified=False)
    msg = _parse(showcase_pool, f"{DATATYPE}.MembershipResolution", resolution_json(unknown))
    assert json_format.MessageToDict(msg, preserving_proto_field_name=True) == {
        "membership_identification_value": "CLUB-9999", "status": "MEMBERSHIP_STATUS_UNKNOWN"}


def _summary_message(pool: descriptor_pool.DescriptorPool, body: dict[str, Any]) -> Message:
    return _parse(pool, f"{DATATYPE}.PurchaseSummary", body)


def test_report_from_message(showcase_pool: descriptor_pool.DescriptorPool) -> None:
    tx_id = str(uuid.uuid4())
    closed = datetime(2027, 2, 16, 14, 20, 1, tzinfo=BERLIN)
    msg = _summary_message(showcase_pool, summary(tx_id, "M-1001", closed,
                                                  ["100012", "100017"]))
    report = report_from_message(msg)
    assert (report.purchase_transaction_id, report.membership_id) == (tx_id, "M-1001")
    assert (report.transaction_type, report.location) == ("SALE", "Root.DE.999.101.01")
    assert report.closed_at == closed and report.closed_at.utcoffset().total_seconds() == 3600
    assert report.total == Decimal("16.98")
    assert [(ln.article_number, ln.category, ln.item_count, ln.value, ln.effectual)
            for ln in report.lines] == [
        ("100012", "kaffee_tee", 1, Decimal("14.49"), True),
        ("100017", "molkerei_fruehstueck", 1, Decimal("2.49"), True)]


@pytest.mark.parametrize(("flags", "expected"), [
    ((False, False), [True, True]),   # flag unused by the POS: all lines are non-voided
    ((True, False), [True, False]),   # flag used: the false line is voided
])
def test_effectual_flag(showcase_pool: descriptor_pool.DescriptorPool,
                        flags: tuple[bool, bool], expected: list[bool]) -> None:
    body = summary(str(uuid.uuid4()), "M-1001", datetime(2027, 2, 16, 12, tzinfo=BERLIN),
                   ["100012", "100017"])
    for line, flag in zip(body["lines"], flags, strict=True):
        line["effectual"] = flag
    report = report_from_message(_summary_message(showcase_pool, body))
    assert [ln.effectual for ln in report.lines] == expected


def test_report_without_closing_time_and_type(showcase_pool: descriptor_pool.DescriptorPool
                                              ) -> None:
    msg = _summary_message(showcase_pool, {"purchase_transaction_id": "x"})
    report = report_from_message(msg)
    assert report.closed_at is None and report.total == Decimal("0.00")
    assert report.transaction_type == "UNSPECIFIED" and report.membership_id == ""


@pytest.mark.gebit
def test_resolution_maps_onto_gebit_loyalty_membership(
        gebit_pool: descriptor_pool.DescriptorPool) -> None:
    """The POS copies the resolution 1:1 into GEBIT ``LoyaltyMembership`` (4.4): every
    field we send except our ``status`` parses strictly into the GEBIT type."""
    body = resolution_json(_resolution())
    body.pop("status")
    msg = _parse(gebit_pool, "de.gebit.rp.purchase.purchase.v2.datatype.LoyaltyMembership",
                 body)
    assert msg.membership_id == "M-1001" and msg.verified
    assert msg.accounts[0].account_currency_name == "Points"
