"""TTL-bounded dedupe cache for webhook event ids.

Event Portal webhooks are at-least-once; the bridge maintains a small
in-memory cache of the last N event ids and skips replays. For a single
replica this is sufficient; for HA the cache should be replaced with Redis
(see `RedisDedupeStore` skeleton below — not wired by default).
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Protocol


class DedupeStore(Protocol):
    def seen(self, event_id: str) -> bool: ...

    def flush(self) -> int:
        """Persist any in-flight state on graceful shutdown (#13).

        Returns the number of entries the store was holding. For stores
        that are already durable (Redis) or have nothing to persist
        (in-memory recency cache) this is a reporting no-op.
        """
        ...


class InMemoryDedupeStore:
    def __init__(self, max_entries: int = 10_000, ttl_seconds: int = 600):
        self._max = max_entries
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._cache: "OrderedDict[str, float]" = OrderedDict()

    def seen(self, event_id: str) -> bool:
        """Return True if `event_id` has been seen recently.

        First call for an id returns False AND records the id; subsequent
        calls within the TTL return True. Entries expire lazily on access.
        """
        if not event_id:
            return False
        now = time.monotonic()
        with self._lock:
            self._expire_locked(now)
            if event_id in self._cache:
                # Refresh recency so an actively replayed id stays cached.
                self._cache.move_to_end(event_id)
                return True
            self._cache[event_id] = now
            self._evict_locked()
            return False

    def _expire_locked(self, now: float) -> None:
        cutoff = now - self._ttl
        while self._cache:
            key, stamp = next(iter(self._cache.items()))
            if stamp >= cutoff:
                return
            self._cache.popitem(last=False)

    def _evict_locked(self) -> None:
        while len(self._cache) > self._max:
            self._cache.popitem(last=False)

    def flush(self) -> int:
        """No durable state to write; report the live entry count (#13)."""
        with self._lock:
            return len(self._cache)


class RedisDedupeStore:  # pragma: no cover - opt-in
    """Production-mode dedupe backed by Redis SETEX.

    Drop-in replacement for InMemoryDedupeStore in HA deployments. Not
    instantiated by default to keep the bridge dependency-light.
    """

    def __init__(self, redis_client, key_prefix: str = "om-bridge:dedupe:", ttl_seconds: int = 600):
        self._redis = redis_client
        self._prefix = key_prefix
        self._ttl = ttl_seconds

    def seen(self, event_id: str) -> bool:
        if not event_id:
            return False
        key = self._prefix + event_id
        # SET key 1 NX EX ttl  -> returns truthy if the key was actually set.
        created = self._redis.set(key, b"1", nx=True, ex=self._ttl)
        return not bool(created)

    def flush(self) -> int:
        """Redis is already durable; nothing to persist on shutdown (#13)."""
        return 0
