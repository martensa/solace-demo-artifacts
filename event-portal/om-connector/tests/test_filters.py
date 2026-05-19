import pytest

from connector.filters import (
    FilterParseError,
    FilterPattern,
    parse_filter_options,
)


# ----------------------------------------------------- default-deny semantics


def test_empty_pattern_matches_nothing():
    p = FilterPattern.empty()
    assert p.is_empty_allow_list is True
    assert p.match("anything") is False
    assert p.match("") is False
    assert p.match(None) is False


def test_no_includes_means_no_match_even_with_excludes():
    p = FilterPattern.from_value({"excludes": [".*"]})
    assert p.match("orders") is False


# ----------------------------------------------------- include / exclude


def test_includes_only():
    p = FilterPattern.from_value({"includes": ["orders\\..*"]})
    assert p.match("orders.created") is True
    assert p.match("orders.shipped") is True
    assert p.match("billing.created") is False


def test_excludes_take_precedence_over_includes():
    p = FilterPattern.from_value(
        {"includes": ["orders\\..*"], "excludes": [".*\\.internal"]}
    )
    assert p.match("orders.created") is True
    assert p.match("orders.internal") is False


def test_multiple_includes_are_ored():
    p = FilterPattern.from_value({"includes": ["orders\\..*", "billing\\..*"]})
    assert p.match("orders.x") is True
    assert p.match("billing.y") is True
    assert p.match("inventory.z") is False


# ----------------------------------------------------- input formats


def test_from_value_accepts_json_string():
    p = FilterPattern.from_value('{"includes":["foo"]}')
    assert p.match("foobar") is True


def test_from_value_accepts_legacy_comma_separated_includes():
    p = FilterPattern.from_value("orders,billing")
    assert p.match("orders") is True
    assert p.match("billing") is True
    assert p.match("foo") is False


def test_from_value_accepts_filter_pattern_instance_passthrough():
    base = FilterPattern.from_value({"includes": ["x"]})
    assert FilterPattern.from_value(base) is base


def test_invalid_regex_raises():
    with pytest.raises(FilterParseError):
        FilterPattern.from_value({"includes": ["("]})  # unclosed group


def test_invalid_json_raises():
    with pytest.raises(FilterParseError):
        FilterPattern.from_value("{not-json")


def test_non_object_json_raises():
    with pytest.raises(FilterParseError):
        FilterPattern.from_value("[1,2]")


# ----------------------------------------------------- parse_filter_options


def test_parse_filter_options_returns_all_known_keys_with_defaults():
    out = parse_filter_options({})
    assert set(out.keys()) == {
        "domainFilterPattern",
        "eventFilterPattern",
        "schemaFilterPattern",
        "applicationFilterPattern",
    }
    for fp in out.values():
        assert fp.is_empty_allow_list is True


def test_parse_filter_options_picks_up_configured_pattern():
    out = parse_filter_options(
        {"domainFilterPattern": {"includes": ["orders"]}}
    )
    assert out["domainFilterPattern"].match("orders-domain") is True
    assert out["eventFilterPattern"].is_empty_allow_list is True


def test_filter_method_returns_matching_subset():
    p = FilterPattern.from_value({"includes": ["a", "b"]})
    assert p.filter(["a1", "b2", "c3"]) == ["a1", "b2"]
