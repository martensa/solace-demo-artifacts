"""Pure-function helper tests for connector.event_portal_connector.

The helpers tested here do not touch the OM SDK or the EP REST client,
so they run in any environment without ``openmetadata-ingestion``.
"""
from __future__ import annotations

from connector.event_portal_connector import _latest_version_id, _semver_tuple


# --------------------------------------------------------- semver_tuple


def test_semver_tuple_parses_dotted_numeric():
    assert _semver_tuple("1.2.3") == (1, 2, 3)


def test_semver_tuple_handles_leading_or_empty_chunks():
    assert _semver_tuple("") == (0,)
    assert _semver_tuple("v1") == (1,)


def test_semver_tuple_extracts_digits_per_chunk():
    """Non-numeric chars within a chunk are dropped; the surviving
    digits are concatenated. So ``1.0.0-rc1`` -> (1, 0, 1) because
    ``0-rc1`` -> "01" -> 1.

    For our use (picking the 'latest' version) this is deliberate
    simplicity over semver-strict ordering: rc-suffixed builds sort
    above the plain version, which mirrors EP's own admin-UI sort."""
    assert _semver_tuple("1.0.0-rc1") == (1, 0, 1)
    assert _semver_tuple("1.0.0") == (1, 0, 0)
    assert _semver_tuple("1.0.0-rc2") == (1, 0, 2)


def test_semver_tuple_orders_correctly_for_max():
    """The intended use of semver_tuple is to find the highest version
    via plain tuple comparison."""
    assert _semver_tuple("2.0.0") > _semver_tuple("1.999.999")
    assert _semver_tuple("0.10.0") > _semver_tuple("0.9.99")


# ----------------------------------------------------- latest_version_id


def test_latest_version_id_picks_highest_semver():
    versions = [
        {"id": "v1-id", "version": "1.0.0"},
        {"id": "v3-id", "version": "3.0.0"},
        {"id": "v2-id", "version": "2.5.0"},
    ]
    assert _latest_version_id(versions) == "v3-id"


def test_latest_version_id_handles_single_version():
    versions = [{"id": "only", "version": "0.1.0"}]
    assert _latest_version_id(versions) == "only"


def test_latest_version_id_handles_empty_list():
    assert _latest_version_id([]) is None


def test_latest_version_id_skips_none_entries():
    """The EP client returns None when get_latest_*_version 404s; the
    helper must skip those without crashing."""
    versions = [None, {"id": "real", "version": "1.0.0"}, None]
    assert _latest_version_id(versions) == "real"


def test_latest_version_id_missing_version_string_treated_as_zero():
    versions = [
        {"id": "no-ver"},  # no 'version' field
        {"id": "v1", "version": "0.0.1"},
    ]
    assert _latest_version_id(versions) == "v1"
