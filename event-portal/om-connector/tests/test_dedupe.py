import time

from bridge.dedupe import InMemoryDedupeStore


def test_first_seen_is_false_subsequent_is_true():
    store = InMemoryDedupeStore(max_entries=10, ttl_seconds=60)
    assert store.seen("evt-1") is False
    assert store.seen("evt-1") is True
    assert store.seen("evt-2") is False


def test_empty_id_is_never_seen():
    store = InMemoryDedupeStore()
    assert store.seen("") is False
    assert store.seen("") is False


def test_eviction_drops_oldest():
    store = InMemoryDedupeStore(max_entries=2, ttl_seconds=60)
    store.seen("a")
    store.seen("b")
    store.seen("c")
    # "a" was the oldest insertion and should have been evicted
    assert store.seen("a") is False


def test_ttl_expiry(monkeypatch):
    store = InMemoryDedupeStore(max_entries=10, ttl_seconds=1)
    base = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: base)
    store.seen("evt")
    monkeypatch.setattr(time, "monotonic", lambda: base + 2)
    assert store.seen("evt") is False
