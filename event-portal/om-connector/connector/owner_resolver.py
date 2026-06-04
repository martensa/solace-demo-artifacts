"""Map Event Portal owners to OpenMetadata users via e-mail.

Event Portal exposes a `createdBy` (and sometimes `owner`) field on domains
/ events / applications. Cloud Enterprise returns user IDs (e.g.
``udz8x00uz2o``) on these fields, NOT e-mails — there is no public
``/users/{id}`` endpoint to resolve them (smoke-tested 2026-05).

Wave 4 (#57): static ``userIdToEmailMap`` connection option closes the
gap. Resolution order:

  1. EP entity payload  ->  see if any field carries an e-mail directly
     (older editions, or ``ownerEmail`` if set).
  2. EP entity carries a user-ID  ->  look up the mapped e-mail in the
     static ``userIdToEmailMap``. Operator must populate this map at
     workflow-config time; auto-discovery is blocked by the missing EP
     ``/users/{id}`` endpoint.
  3. OM GET /users/name/<email-local-part> OR /users/email/<email>
     (newer OM versions support both; we try both and accept the first
     hit).
  4. Build an `EntityReference(type=user, id=<found id>)` for use as
     ``owners`` on a CreateXRequest.

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
        user_id_to_email: Optional[Dict[str, str]] = None,
        cache_size: int = 1024,
        cache_ttl_seconds: int = 600,
        miss_ttl_seconds: int = 60,
    ):
        self._om = om
        # Wave 4 (#57): static map populated from the workflow option
        # ``userIdToEmailMap``. Empty dict means "no translation table",
        # which is fine for older EP editions whose payloads carry an
        # e-mail directly.
        self._user_id_to_email: Dict[str, str] = dict(user_id_to_email or {})
        self._unmapped_logged: set = set()
        self._cache: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self._cache_size = cache_size
        self._hit_ttl = cache_ttl_seconds
        self._miss_ttl = miss_ttl_seconds
        self._lock = threading.Lock()

    # ----------------------------------------------------------- public API

    def resolve_owner(self, ep_entity: Dict[str, Any]):
        """Pick the best e-mail off an EP entity and resolve it to an OM user.

        Looks at, in order: ``ownerEmail``, ``owner``, ``createdBy``,
        ``changedBy``. When the field is an EP user-ID (no ``@``), look it
        up in ``userIdToEmailMap`` first. Returns an OM ``EntityReference``
        or ``None`` if no user could be matched.
        """
        email = _extract_email(ep_entity)
        if not email:
            user_id = _extract_user_id(ep_entity)
            if user_id:
                email = self._user_id_to_email.get(user_id)
                if not email:
                    # Log unmapped user IDs once each so operators know
                    # which entries to add to userIdToEmailMap.
                    if user_id not in self._unmapped_logged:
                        self._unmapped_logged.add(user_id)
                        logger.warning(
                            "EP user-ID %s has no entry in userIdToEmailMap; "
                            "owner will be left blank. Add the mapping to "
                            "the workflow connectionOptions to resolve.",
                            user_id,
                        )
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
    """Find an e-mail directly on the EP payload (no map lookup)."""
    for key in ("ownerEmail", "owner", "createdBy", "changedBy"):
        v = ep_entity.get(key)
        if isinstance(v, str) and "@" in v:
            return v.strip()
        if isinstance(v, dict):
            mail = v.get("email") or v.get("username")
            if isinstance(mail, str) and "@" in mail:
                return mail.strip()
    return None


def _extract_user_id(ep_entity: Dict[str, Any]) -> Optional[str]:
    """Find an EP user-ID on the payload (no e-mail).

    EP v2 Cloud Enterprise returns user IDs as plain strings (no ``@``)
    on ``createdBy`` / ``changedBy``. Resolution to e-mail goes through
    the static ``userIdToEmailMap``.
    """
    for key in ("owner", "createdBy", "changedBy"):
        v = ep_entity.get(key)
        if isinstance(v, str):
            sv = v.strip()
            if sv and "@" not in sv:
                return sv
        elif isinstance(v, dict):
            sub = v.get("id") or v.get("userId") or v.get("sub")
            if isinstance(sub, str) and sub.strip() and "@" not in sub:
                return sub.strip()
    return None


def parse_user_id_map(raw: Any) -> Dict[str, str]:
    """Coerce a workflow-config value to a ``{user_id: email}`` dict.

    Accepts either:
      * a YAML / pydantic dict already (most common), or
      * a comma-separated string ``id1:email1,id2:email2`` (operator
        convenience when stashing the map in a single env var).

    Wave 4 (#57). Silently drops blank / malformed entries so a stray
    trailing comma doesn't break the whole map.
    """
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {
            str(k).strip(): str(v).strip()
            for k, v in raw.items()
            if k and v and isinstance(v, str) and "@" in v
        }
    if isinstance(raw, str):
        out: Dict[str, str] = {}
        for pair in raw.split(","):
            if ":" not in pair:
                continue
            k, _, v = pair.partition(":")
            k = k.strip()
            v = v.strip()
            if k and v and "@" in v:
                out[k] = v
        return out
    return {}


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
