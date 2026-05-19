"""Tests for the multi-step Test-Connection routine."""
from unittest.mock import MagicMock

from connector.event_portal_client import EventPortalAuthError
from connector.filters import FilterPattern
from connector.test_connection import (
    run_test_connection,
    step_broker_reachable,
    step_ep_api_reachable,
    step_ep_token_valid,
    step_filtered_domains_present,
)


def _client(status_code=200, raise_on_test=None, domains=None):
    """Build a fake EventPortalClient. The real one is requests-heavy; we
    only need session.get + test_connection + list_application_domains."""
    client = MagicMock()
    client.base_url = "https://api.solace.cloud/api/v2"
    client.timeout = 30
    resp = MagicMock(status_code=status_code)
    client.session.get.return_value = resp
    if raise_on_test:
        client.test_connection.side_effect = raise_on_test
    else:
        client.test_connection.return_value = None
    client.list_application_domains.return_value = domains or []
    return client


def test_step_ep_api_reachable_accepts_200_or_401():
    assert step_ep_api_reachable(_client(status_code=200)).passed is True
    assert step_ep_api_reachable(_client(status_code=401)).passed is True


def test_step_ep_api_reachable_fails_on_5xx():
    assert step_ep_api_reachable(_client(status_code=503)).passed is False


def test_step_ep_token_valid_pass():
    assert step_ep_token_valid(_client()).passed is True


def test_step_ep_token_valid_fails_on_auth_error():
    r = step_ep_token_valid(
        _client(raise_on_test=EventPortalAuthError("expired"))
    )
    assert r.passed is False
    assert "expired" in r.message


def test_step_filtered_domains_present_empty_allow_list_is_warned():
    r = step_filtered_domains_present(_client(), FilterPattern.empty())
    assert r.passed is False
    assert "allow-list-only" in r.message


def test_step_filtered_domains_present_matches():
    client = _client(domains=[{"name": "orders"}, {"name": "other"}])
    r = step_filtered_domains_present(
        client, FilterPattern.from_value({"includes": ["orders"]})
    )
    assert r.passed is True
    assert "1 of 2" in r.message


def test_step_filtered_domains_present_filter_matches_nothing():
    client = _client(domains=[{"name": "orders"}, {"name": "other"}])
    r = step_filtered_domains_present(
        client, FilterPattern.from_value({"includes": ["payments"]})
    )
    assert r.passed is False
    assert "none match" in r.message


def test_step_broker_reachable_skipped_when_no_config():
    r = step_broker_reachable(None)
    assert r.passed is True
    assert "skipped" in r.message.lower()


def test_full_report_aggregates_step_results():
    client = _client(
        status_code=200,
        domains=[{"name": "orders"}],
    )
    report = run_test_connection(
        client,
        domain_filter=FilterPattern.from_value({"includes": ["orders"]}),
        broker_config=None,
    )
    assert report.passed is True
    assert len(report.steps) == 4
    assert report.steps[-1].name == "Broker reachable"
    assert "OK" in str(report)


def test_full_report_fails_when_any_step_fails():
    client = _client(
        status_code=503,
        domains=[{"name": "orders"}],
    )
    report = run_test_connection(
        client,
        domain_filter=FilterPattern.from_value({"includes": ["orders"]}),
        broker_config=None,
    )
    assert report.passed is False
    # All four steps still ran (no short-circuit).
    assert len(report.steps) == 4
