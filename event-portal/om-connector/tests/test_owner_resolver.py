import time

import pytest

from connector.owner_resolver import OwnerResolver


class _FakeClient:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        if path in self.responses:
            return self.responses[path]
        raise RuntimeError(f"404 {path}")


class _FakeOM:
    def __init__(self, client):
        self.client = client


def test_resolves_email_via_email_endpoint():
    client = _FakeClient(
        responses={
            "/users/email/alice@example.org": {
                "id": "u-1", "name": "alice", "displayName": "Alice",
            }
        }
    )
    r = OwnerResolver(_FakeOM(client))
    ref = r.resolve_by_email("alice@example.org")
    assert ref is not None
    assert (ref["id"] if isinstance(ref, dict) else ref.id) == "u-1"
    assert (ref["type"] if isinstance(ref, dict) else ref.type) == "user"


def test_falls_back_to_name_endpoint_when_email_misses():
    client = _FakeClient(
        responses={"/users/name/bob": {"id": "u-2", "name": "bob"}}
    )
    r = OwnerResolver(_FakeOM(client))
    ref = r.resolve_by_email("bob@example.org")
    assert ref is not None
    assert "/users/email/bob@example.org" in client.calls
    assert "/users/name/bob" in client.calls


def test_negative_result_is_cached():
    client = _FakeClient(responses={})
    r = OwnerResolver(_FakeOM(client), miss_ttl_seconds=60)
    assert r.resolve_by_email("ghost@example.org") is None
    n = len(client.calls)
    # second call must not hit OM again
    assert r.resolve_by_email("ghost@example.org") is None
    assert len(client.calls) == n


def test_positive_result_is_cached():
    client = _FakeClient(
        responses={"/users/email/alice@example.org": {"id": "u-1", "name": "alice"}}
    )
    r = OwnerResolver(_FakeOM(client))
    r.resolve_by_email("alice@example.org")
    n = len(client.calls)
    r.resolve_by_email("alice@example.org")
    assert len(client.calls) == n


def test_resolve_owner_picks_email_from_ep_entity_shapes():
    client = _FakeClient(
        responses={"/users/email/alice@example.org": {"id": "u-1", "name": "alice"}}
    )
    r = OwnerResolver(_FakeOM(client))
    # ownerEmail wins over createdBy
    ref = r.resolve_owner({
        "ownerEmail": "alice@example.org",
        "createdBy": "carol@example.org",
    })
    assert ref is not None
    assert "/users/email/alice@example.org" in client.calls


def test_resolve_owner_returns_none_when_no_email_field():
    client = _FakeClient(responses={})
    r = OwnerResolver(_FakeOM(client))
    assert r.resolve_owner({"name": "orders-domain"}) is None
    assert client.calls == []


def test_cache_ttl_expires(monkeypatch):
    base = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: base[0])
    client = _FakeClient(responses={})
    r = OwnerResolver(_FakeOM(client), miss_ttl_seconds=1)
    r.resolve_by_email("ghost@example.org")
    n = len(client.calls)
    base[0] += 5
    r.resolve_by_email("ghost@example.org")
    assert len(client.calls) > n
