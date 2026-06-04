"""Reconciliation: re-pull EP since the last sync watermark.

Solace Cloud Event Portal v2 does not expose an architecture-level audit
feed (verified by `scripts/smoke_ep_api.py`). The reconcile path here
therefore does NOT replay a change feed — it pulls each filtered domain's
events that have moved since the watermark, builds a synthetic
`eventVersion.updated` payload, and dispatches through the same handler
set the live polling/HTTP transports use.

Trade-off vs. an audit-replay:
  * cost: more API calls (we fetch full event lists, then per-event
    versions). EP's `updatedTime` filter keeps the result set small.
  * fidelity: deletes are NOT picked up by this path (an event that
    disappears from EP never appears in a list response). For tombstoning
    we still recommend a nightly full ingestion workflow on top.

Flow:
  1. Read the watermark (last successful re-pull timestamp) from a
     custom property on the OpenMetadata MessagingService entity.
     Default: now - 24h.
  2. List application domains updated since the watermark, OR every
     domain the token can see (if `domain_ids` is provided).
  3. For each domain, list events updated since the watermark.
  4. For each event, dispatch `eventVersion.updated` so handlers refetch
     the latest event-version object and upsert the corresponding Topic.
  5. On success, persist the highest seen `updatedTime` as the new
     watermark.

Handlers swallow their own exceptions; a partial failure does not block
the watermark advance (the affected entity gets a second chance on the
next reconcile run).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from connector.property_keys import (
    APP_PIPELINE_SERVICE_NAME,
    AUDIT_WATERMARK_KEY,
    CP_EP_DELETED_AT,
)

from .dispatcher import BridgeContext, Dispatcher

logger = logging.getLogger(__name__)

# Wave 4 (#61): tag applied to OM entities whose EP source disappeared.
RETIRED_TAG_FQN = "EventPortal.Retired"


# ---------------------------------------------------------------- watermark

def _get_messaging_service(om, service_name: str) -> Optional[Dict[str, Any]]:
    try:
        return om.client.get(f"/services/messagingServices/name/{service_name}")
    except Exception as exc:
        logger.debug("Could not fetch MessagingService %s: %s", service_name, exc)
        return None


def read_watermark(
    om, service_name: str, default_lookback: timedelta = timedelta(hours=24)
) -> str:
    svc = _get_messaging_service(om, service_name) or {}
    extension = svc.get("extension") or {}
    wm = extension.get(AUDIT_WATERMARK_KEY)
    if wm:
        return str(wm)
    return (datetime.now(timezone.utc) - default_lookback).isoformat(timespec="seconds")


def write_watermark(om, service_name: str, watermark: str) -> None:
    svc = _get_messaging_service(om, service_name)
    if not svc:
        logger.warning(
            "MessagingService %s not found; cannot persist watermark", service_name
        )
        return
    svc_id = svc.get("id")
    op = "add" if AUDIT_WATERMARK_KEY not in (svc.get("extension") or {}) else "replace"
    patch = [
        {
            "op": op,
            "path": f"/extension/{AUDIT_WATERMARK_KEY}",
            "value": watermark,
        }
    ]
    try:
        om.client.patch(path=f"/services/messagingServices/{svc_id}", data=patch)
        logger.info("Watermark advanced to %s", watermark)
    except Exception:
        logger.exception("Failed to PATCH watermark; will retry next run")


# ---------------------------------------------------------------- replay

def replay_audit_since(
    *,
    ep_client,
    om,
    service_name: str,
    since: Optional[str] = None,
    dispatcher: Optional[Dispatcher] = None,
    domain_ids: Optional[List[str]] = None,
) -> Tuple[int, int, Optional[str]]:
    """Re-pull EP since the watermark and dispatch through bridge handlers.

    The function name is retained for backwards compatibility with the CLI
    surface (`om-eventportal-bridge --reconcile`). Despite the name, the
    implementation does NOT consume an audit feed — see module docstring.

    Args:
        ep_client: EventPortalClient
        om: OpenMetadata SDK
        service_name: OM MessagingService name (carries the watermark)
        since: ISO timestamp; defaults to the watermark on the service
        dispatcher: optional pre-built dispatcher (testing)
        domain_ids: optional restriction to specific EP domain ids

    Returns:
        (events_seen, events_dispatched, new_watermark)
    """
    if dispatcher is None:
        from .handlers import register_defaults
        dispatcher = register_defaults(Dispatcher())
    ctx = BridgeContext(ep_client=ep_client, om=om, service_name=service_name)
    watermark = since or read_watermark(om, service_name)
    logger.info("Reconciliation starting from %s", watermark)

    # 1. domains to walk: explicit list, or every domain visible to the token
    if domain_ids is not None:
        domains: Iterable[Dict[str, Any]] = [
            {"id": did} for did in domain_ids
        ]
    else:
        try:
            domains = ep_client.list_application_domains(since=watermark)
        except Exception:
            logger.exception("list_application_domains failed during reconcile")
            return 0, 0, watermark

    seen = 0
    dispatched = 0
    high_watermark = watermark
    for domain in domains:
        domain_id = domain.get("id")
        if not domain_id:
            continue
        try:
            events = ep_client.list_events(domain_id, since=watermark)
        except Exception:
            logger.exception("list_events(%s) failed", domain_id)
            continue
        for event in events:
            seen += 1
            event_id = event.get("id")
            if not event_id:
                continue
            payload = {
                "eventType": "eventVersion.updated",
                "eventId": event_id,
                # Tell handlers to refetch the latest version
                "data": {"eventId": event_id},
            }
            count = dispatcher.dispatch(ctx, payload)
            if count:
                dispatched += 1
            ts = event.get("updatedTime")
            if ts and ts > high_watermark:
                high_watermark = ts

    if high_watermark != watermark:
        write_watermark(om, service_name, high_watermark)
    logger.info(
        "Reconciliation done: seen=%d dispatched=%d watermark=%s",
        seen, dispatched, high_watermark,
    )
    return seen, dispatched, high_watermark


# ---------------------------------------------------------------- soft-delete


def soft_delete_missing_entities(
    *,
    ep_client,
    om,
    service_name: str,
    auto_purge_after_days: Optional[int] = None,
    now: Optional[datetime] = None,
) -> Dict[str, int]:
    """Wave 4 (#61): mark OM entities whose EP source disappeared.

    Walks every OM Topic under ``service_name`` and every OM Pipeline
    under the synthetic EP-apps PipelineService. For each one whose
    deterministic FQN no longer appears in EP, applies the
    ``EventPortal.Retired`` tag and writes an ISO-8601 ``deletedAt``
    timestamp to the ``eventPortalDeletedAt`` custom property.

    When ``auto_purge_after_days`` is given, entities whose ``deletedAt``
    is older than that many days are hard-deleted afterwards. Default
    ``None`` keeps the soft-tombstone forever (the customer can purge
    via the OM UI when ready).

    Identity model: the OM-side FQN is composed by the connector
    deterministically from EP entity names + versions; see
    ``connector.mappers.topic_fqn`` / ``app_pipeline_fqn``. We rebuild
    the *expected* FQN set from a fresh EP pull, then diff against the
    OM-listed FQN set. Renamed-in-EP entities therefore correctly
    register as both a new arrival and a tombstoned old name -- which
    matches OM's catalog semantics (history is preserved).

    Returns ``{retired: int, purged: int, scanned: int}``.
    """
    from connector.fqn import app_pipeline_fqn, topic_fqn
    now = now or datetime.now(timezone.utc)
    deleted_at = now.isoformat(timespec="seconds")

    # 1. Pull the EP-side authoritative set.
    try:
        domains = ep_client.list_application_domains()
    except Exception:
        logger.exception("Soft-delete pass aborted: cannot list EP domains")
        return {"retired": 0, "purged": 0, "scanned": 0}

    expected_topic_fqns: Set[str] = set()
    expected_pipeline_fqns: Set[str] = set()
    for domain in domains:
        domain_id = domain.get("id")
        if not domain_id:
            continue
        try:
            for event in ep_client.list_events(domain_id):
                ev_name = event.get("name") or ""
                if not ev_name:
                    continue
                try:
                    versions = ep_client.list_event_versions(event["id"])
                except Exception:
                    logger.warning(
                        "list_event_versions(%s) failed during soft-delete",
                        event.get("id"),
                    )
                    continue
                for v in versions or []:
                    if not v:
                        continue
                    expected_topic_fqns.add(
                        topic_fqn(service_name, ev_name, str(v.get("version") or "1.0.0"))
                    )
        except Exception:
            logger.exception("list_events(%s) failed during soft-delete", domain_id)
        try:
            for app in ep_client.list_applications(domain_id):
                app_name = app.get("name") or ""
                if not app_name:
                    continue
                try:
                    versions = ep_client.list_application_versions(app["id"])
                except Exception:
                    logger.warning(
                        "list_application_versions(%s) failed during soft-delete",
                        app.get("id"),
                    )
                    continue
                for v in versions or []:
                    if not v:
                        continue
                    expected_pipeline_fqns.add(
                        app_pipeline_fqn(app_name, str(v.get("version") or "1.0.0"))
                    )
        except Exception:
            logger.exception("list_applications(%s) failed during soft-delete", domain_id)

    # 2. Walk OM-side Topics + Pipelines, diff, and tombstone the missing.
    topics_seen, topics_retired = _tombstone_missing(
        om=om,
        list_path="/topics",
        list_params={"service": service_name, "fields": "tags,extension"},
        expected_fqns=expected_topic_fqns,
        deleted_at=deleted_at,
        entity_kind="topic",
    )
    pipelines_seen, pipelines_retired = _tombstone_missing(
        om=om,
        list_path="/pipelines",
        list_params={
            "service": APP_PIPELINE_SERVICE_NAME, "fields": "tags,extension",
        },
        expected_fqns=expected_pipeline_fqns,
        deleted_at=deleted_at,
        entity_kind="pipeline",
    )

    purged = 0
    if auto_purge_after_days is not None and auto_purge_after_days >= 0:
        cutoff = now - timedelta(days=auto_purge_after_days)
        purged += _hard_delete_aged_tombstones(
            om=om, list_path="/topics",
            list_params={"service": service_name, "fields": "tags,extension"},
            cutoff=cutoff,
        )
        purged += _hard_delete_aged_tombstones(
            om=om, list_path="/pipelines",
            list_params={
                "service": APP_PIPELINE_SERVICE_NAME, "fields": "tags,extension",
            },
            cutoff=cutoff,
        )

    summary = {
        "retired": topics_retired + pipelines_retired,
        "purged": purged,
        "scanned": topics_seen + pipelines_seen,
    }
    logger.info("Soft-delete pass summary: %s", summary)
    return summary


def _iterate_om_paginated(
    om, path: str, params: Dict[str, Any],
) -> Iterable[Dict[str, Any]]:
    """Yield entities from a paginated OM list endpoint.

    OM list endpoints (``/topics``, ``/pipelines``, ...) return:
        {"data": [...], "paging": {"after": "<cursor>"}}
    We chase ``paging.after`` until empty. ``limit`` defaults to 100
    which matches OM's per-call cap.
    """
    after: Optional[str] = None
    while True:
        q = dict(params)
        q.setdefault("limit", 100)
        if after:
            q["after"] = after
        try:
            resp = om.client.get(path=path, data=q)
        except TypeError:
            # The lightweight client in unit tests doesn't accept `data=`.
            try:
                resp = om.client.get(path)
            except Exception:
                logger.warning("OM list %s failed; stopping pagination", path)
                return
        except Exception:
            logger.warning("OM list %s failed; stopping pagination", path)
            return
        for item in (resp or {}).get("data") or []:
            yield item
        after = ((resp or {}).get("paging") or {}).get("after")
        if not after:
            return


def _entity_fqn(entity: Dict[str, Any]) -> Optional[str]:
    fqn = entity.get("fullyQualifiedName")
    if isinstance(fqn, dict):
        return fqn.get("root") or fqn.get("__root__")
    return fqn


def _tag_fqns(entity: Dict[str, Any]) -> Set[str]:
    out: Set[str] = set()
    for t in entity.get("tags") or []:
        tfqn = t.get("tagFQN") if isinstance(t, dict) else None
        if isinstance(tfqn, str):
            out.add(tfqn)
    return out


def _tombstone_missing(
    *,
    om,
    list_path: str,
    list_params: Dict[str, Any],
    expected_fqns: Set[str],
    deleted_at: str,
    entity_kind: str,
) -> Tuple[int, int]:
    """List one OM entity collection and tombstone every entry whose FQN
    is missing from ``expected_fqns`` and not already tombstoned.

    Returns ``(seen, retired)`` so the caller can roll up totals.
    """
    seen = 0
    retired = 0
    for ent in _iterate_om_paginated(om, list_path, list_params):
        seen += 1
        fqn = _entity_fqn(ent)
        if not fqn or fqn in expected_fqns:
            continue
        tags = _tag_fqns(ent)
        if RETIRED_TAG_FQN in tags:
            continue  # already tombstoned -- don't churn
        ent_id = ent.get("id")
        if not ent_id:
            continue
        try:
            _patch_tombstone(
                om=om, entity_kind=entity_kind, entity_id=str(ent_id),
                current_tags=list(ent.get("tags") or []),
                current_extension=dict(ent.get("extension") or {}),
                deleted_at=deleted_at,
            )
            retired += 1
            logger.info(
                "Soft-deleted %s %s (no longer in EP)", entity_kind, fqn,
            )
        except Exception:
            logger.exception(
                "Failed to tombstone %s %s -- will retry next pass",
                entity_kind, fqn,
            )
    return seen, retired


def _patch_tombstone(
    *,
    om,
    entity_kind: str,
    entity_id: str,
    current_tags: List[Dict[str, Any]],
    current_extension: Dict[str, Any],
    deleted_at: str,
) -> None:
    """Send a JSON-Patch that adds the Retired tag + deletedAt CP.

    Uses ``replace`` for ``tags`` + ``extension`` (whole-object) so the
    patch is idempotent and survives re-runs even if the OM server lacks
    deep-merge semantics on JSON-Patch ``add``.
    """
    new_tags = list(current_tags)
    if not any(
        isinstance(t, dict) and t.get("tagFQN") == RETIRED_TAG_FQN
        for t in new_tags
    ):
        new_tags.append({
            "tagFQN": RETIRED_TAG_FQN,
            "labelType": "Automated",
            "state": "Suggested",
            "source": "Classification",
        })
    new_extension = dict(current_extension)
    new_extension[CP_EP_DELETED_AT] = deleted_at
    patch = [
        {"op": "replace", "path": "/tags", "value": new_tags},
        {"op": "replace", "path": "/extension", "value": new_extension},
    ]
    path_segment = {"topic": "topics", "pipeline": "pipelines"}.get(
        entity_kind, f"{entity_kind}s",
    )
    om.client.patch(path=f"/{path_segment}/{entity_id}", data=json.dumps(patch))


def _hard_delete_aged_tombstones(
    *,
    om,
    list_path: str,
    list_params: Dict[str, Any],
    cutoff: datetime,
) -> int:
    """Hard-delete entities whose deletedAt is older than ``cutoff``.

    Wave 4 (#61) opt-in via ``retiredAutoPurgeAfterDays``. Default
    behaviour is to leave tombstoned entities in place forever -- the
    customer keeps full historical audit and prunes manually via the
    OM UI when ready.
    """
    purged = 0
    for ent in _iterate_om_paginated(om, list_path, list_params):
        if RETIRED_TAG_FQN not in _tag_fqns(ent):
            continue
        ext = ent.get("extension") or {}
        ts = ext.get(CP_EP_DELETED_AT)
        if not isinstance(ts, str):
            continue
        try:
            stamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        if stamp > cutoff:
            continue
        ent_id = ent.get("id")
        if not ent_id:
            continue
        try:
            om.client.delete(
                path=f"{list_path}/{ent_id}?hardDelete=true&recursive=true",
            )
            purged += 1
            logger.info(
                "Hard-purged tombstoned %s %s (deletedAt %s past cutoff %s)",
                list_path.lstrip("/"), _entity_fqn(ent), ts, cutoff,
            )
        except Exception:
            logger.exception(
                "Hard-purge failed for %s %s", list_path.lstrip("/"), ent_id,
            )
    return purged
