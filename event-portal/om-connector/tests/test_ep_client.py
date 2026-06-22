"""EventPortalClient helper tests.

connector.event_portal_client has no OM-SDK dependency, so the pure
helpers run locally. Focus: `_latest()` lifecycle-aware version ranking
against EP v2's NUMERIC stateId (regression for the compat-audit bug
where numeric stateIds fell through to the default rank)."""
from connector.event_portal_client import _latest


def test_latest_none_and_empty():
    assert _latest([]) is None


def test_latest_released_beats_higher_semver_draft_v2_numeric():
    # EP v2 numeric stateId: "1"=Draft, "2"=Released. A Released 1.0.0 must
    # outrank a Draft 2.0.0 -- lifecycle state wins over raw semver.
    versions = [
        {"id": "released", "version": "1.0.0", "stateId": "2"},
        {"id": "draft", "version": "2.0.0", "stateId": "1"},
    ]
    assert _latest(versions)["id"] == "released"


def test_latest_among_released_picks_highest_semver():
    versions = [
        {"id": "v1", "version": "1.0.0", "stateId": "2"},
        {"id": "v2", "version": "1.3.0", "stateId": "2"},
        {"id": "v1_1", "version": "1.1.0", "stateId": "2"},
    ]
    assert _latest(versions)["id"] == "v2"


def test_latest_deprecated_and_retired_rank_below_draft_numeric():
    versions = [
        {"id": "retired", "version": "9.0.0", "stateId": "4"},
        {"id": "deprecated", "version": "8.0.0", "stateId": "3"},
        {"id": "draft", "version": "1.0.0", "stateId": "1"},
    ]
    assert _latest(versions)["id"] == "draft"


def test_latest_legacy_string_state_still_ranks():
    # Older EP editions send the state name instead of a numeric id.
    versions = [
        {"id": "rel", "version": "1.0.0", "state": "RELEASED"},
        {"id": "drf", "version": "2.0.0", "state": "draft"},
    ]
    assert _latest(versions)["id"] == "rel"
