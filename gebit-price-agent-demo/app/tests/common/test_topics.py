"""topics: builders for every topic of 7.1 and their subscription boundaries."""

from __future__ import annotations

import pytest

from gposdemo.common import topics
from gposdemo.common.bus import topic_matches

TX = "5b1f0c2e-8d1e-4a43-9a51-0c7a2f0e1b11"


def test_parse_location() -> None:
    assert topics.parse_location("Root.DE.999.101.01") == ("DE", "999", "101", "01")
    assert topics.parse_location("Root.DE.999.199.98") == ("DE", "999", "199", "98")
    for bad in ("DE.999.101.01", "Root.DE.999.101", "Root.DE.999..01", "Root.DE/1.999.101.01"):
        with pytest.raises(ValueError):
            topics.parse_location(bad)


def test_every_topic_of_7_1() -> None:
    assert topics.gebit_event("basket", "PositionAdded", "DE", "999", "101", "01", TX) == (
        f"gebit/rp/purchase/v2/basket/PositionAdded/DE/999/101/01/{TX}")
    assert topics.wws_price("PriceChangeApplied", "DE", "999", "101", "100001") == (
        "showcase/wws/v1/price/PriceChangeApplied/DE/999/101/100001")
    assert topics.insight("101", "01", TX) == f"gpos/v1/insight/scan/101/01/{TX}"
    assert topics.review_request("101", "01", "GR-270216-0007") == (
        "gpos/v1/review/request/101/01/GR-270216-0007")
    assert topics.review_state("prepared", "101", "01", "GR-270216-0007") == (
        "gpos/v1/review/state/prepared/101/01/GR-270216-0007")
    assert topics.proposal("ready", "101", "01", "GP-270216-0003") == (
        "gpos/v1/proposal/ready/101/01/GP-270216-0003")
    assert topics.proposal("duplicate_request", "101", "01", "GP-270216-0003") == (
        "gpos/v1/proposal/duplicate_request/101/01/GP-270216-0003")
    assert topics.approval_request("101", "01", "GP-270216-0003") == (
        "gpos/v1/approval/request/101/01/GP-270216-0003")
    assert topics.telemetry_tool("wws", "get_sales_performance") == (
        "gpos/v1/telemetry/tool/wws/get_sales_performance")
    assert topics.sam_done("r3") == "gpos/v1/sam/done/r3"
    assert topics.sam_error("p4") == "gpos/v1/sam/error/p4"


def test_states_categories_and_rules_are_closed_sets() -> None:
    assert len(topics.REVIEW_STATES) == 10 and len(topics.PROPOSAL_STATES) == 8
    for call in (lambda: topics.review_state("ready", "101", "01", "GR-1"),
                 lambda: topics.proposal("requested", "101", "01", "GP-1"),
                 lambda: topics.gebit_event("purchase", "X", "DE", "999", "101", "01", TX),
                 lambda: topics.wws_price("PriceChanged", "DE", "999", "101", "1"),
                 lambda: topics.sam_done("r2")):
        with pytest.raises(ValueError):
            call()


@pytest.mark.parametrize("level", ["", "a/b", "*", ">", " 01"])
def test_invalid_levels_are_rejected(level: str) -> None:
    with pytest.raises(ValueError):
        topics.insight("101", level, TX)


def test_sam_rule_filters_never_catch_ui_topics() -> None:
    r3 = topics.review_request_filter("101", "01")
    r4 = topics.approval_request_filter("101", "01")
    assert r3 == "gpos/v1/review/request/101/01/>"
    assert r4 == "gpos/v1/approval/request/101/01/>"
    assert topic_matches(r3, topics.review_request("101", "01", "GR-270216-0007"))
    assert topic_matches(r4, topics.approval_request("101", "01", "GP-270216-0003"))
    for state in topics.REVIEW_STATES:
        assert not topic_matches(r3, topics.review_state(state, "101", "01", "GR-270216-0007"))
    for state in topics.PROPOSAL_STATES:
        assert not topic_matches(r4, topics.proposal(state, "101", "01", "GP-270216-0003"))
    # probe till 98 and test till 99 never reach the booth rules
    assert not topic_matches(r3, topics.review_request("199", "98", "GR-270216-0001"))
    assert not topic_matches(r4, topics.approval_request("199", "99", "GP-270216-0001"))


def test_ui_subscriptions_cover_all_published_topics() -> None:
    published = [
        topics.gebit_event("purchase_transaction", "PurchaseTransactionClosed", "DE", "999",
                           "101", "01", TX),
        topics.wws_price("PriceChangeEnded", "DE", "999", "101", "100001"),
        topics.insight("199", "99", TX), topics.telemetry_tool("gate", "apply_price"),
        topics.sam_error("r4"),
    ]
    for topic in published:
        assert any(topic_matches(f, topic) for f in topics.UI_SUBSCRIPTIONS), topic
