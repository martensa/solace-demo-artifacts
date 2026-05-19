"""Map Event Portal owners to OpenMetadata users via e-mail.

Event Portal exposes a `createdBy` (and sometimes `owner`) field on domains
/ events / applications. With Keycloak as the IdP for both EP and OM, the
e-mail is the cleanest 1:1 join key.

Resolution:
  1. EP-Domain/Event/App  ->  owner e-mail (or fallback to createdBy if
     EP returns a Keycloak sub there)
  2. OM GET /users/name/<email-local-part> OR /users/email/<email>
     (newer OM versions support both; we try both and accept the first hit)
  3. Build an `EntityReference(type=user, id=<found id>)` for use as
     `owner` on a CreateXRequest.

Cached via an LRU+TTL store to keep the call volume sane. Misses are
cached too (negative caching) so we don't re-query OM on every Topic for
the same unknown user.

Lazy import of the OM SDK so this module is importable from the bridge
without `openmetadata-ingestion` installed.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# Sentinel used in the cache to remember "we looked and there's no match".
_MISS = object()


class OwnerResolver:
    """Resolve EP owner e-mails to OM `EntityReference` (type=user)."""

    def __init__(
        self,
        om,
        *,
        cache_size: int = 1024,
        cache_ttl_seconds: int = 600,
        miss_ttl_seconds: int = 60,
    ):
        self._om = om
        self._cache: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self._cache_size = cache_size
        self._hit_ttl = cache_ttl_seconds
        self._miss_ttl = miss_ttl_seconds
        self._lock = threading.Lock()

    # ----------------------------------------------------------- public API

    def resolve_owner(self, ep_entity: Dict[str, Any]):
        """Pick the best e-mail off an EP entity and resolve it to an OM user.

        Looks at, in order: `ownerEmail`, `owner`, `createdBy`. Returns an
        OM `EntityReference` or None if no user could be matched.
        """
        email = _extract_email(ep_entity)
        if not email:
            return None
        return self.resolve_by_email(email)

    def resolve_by_email(self, email: str):
        if not email:
            return None
        cached = self._lookup(email)
        if cached is _MISS:
            return None
        if cached is not None:
            return cached
        ref = self._query_om(email)
        self._store(email, ref if ref is not None else _MISS)
        return ref

    # ------------------------------------------------------------- internals

    def _query_om(self, email: str):
        """Try the documented OM endpoints; return EntityReference or None."""
        local = email.split("@", 1)[0]
        for path in (
            f"/users/email/{email}",
            f"/users/name/{local}",
        ):
            try:
                user = self._om.client.get(path)
            except Exception as exc:
                logger.debug("OM lookup %s failed: %s", path, exc)
                continue
            if user and user.get("id"):
                return _to_entity_reference(user)
        logger.info("No OM user matched e-mail %s", email)
        return None

    def _lookup(self, email: str):
        with self._lock:
            entry = self._cache.get(email)
            if not entry:
                return None
            stamp, value = entry
            ttl = self._miss_ttl if value is _MISS else self._hit_ttl
            if time.monotonic() - stamp > ttl:
                del self._cache[email]
                return None
            self._cache.move_to_end(email)
            return value

    def _store(self, email: str, value: Any) -> None:
        with self._lock:
            self._cache[email] = (time.monotonic(), value)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)


# ---------------------------------------------------------------- helpers


def _extract_email(ep_entity: Dict[str, Any]) -> Optional[str]:
    for key in ("ownerEmail", "owner", "createdBy"):
        v = ep_entity.get(key)
        if isinstance(v, str) and "@" in v:
            return v.strip()
        if isinstance(v, dict):
            mail = v.get("email") or v.get("username")
            if isinstance(mail, str) and "@" in mail:
                return mail.strip()
    return None


def _to_entity_reference(user: Dict[str, Any]):
    """Build an OM EntityReference, falling back to a plain dict if the SDK
    cannot be imported (e.g. in slim test environments)."""
    try:
        from metadata.generated.schema.type.entityReference import EntityReference

        return EntityReference(
            id=user["id"],
            type="user",
            name=user.get("name"),
            displayName=user.get("displayName"),
        )
    except Exception:
        return {
            "id": user["id"],
            "type": "user",
            "name": user.get("name"),
            "displayName": user.get("displayName"),
        }
