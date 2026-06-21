"""Default handler set for Event Portal change webhooks.

Each handler:
  1. extracts the resource ID(s) from the webhook payload
  2. asks Event Portal for the canonical, up-to-date object graph
  3. runs the shared `connector.mappers` to build OM create requests
  4. applies the result through `OpenMetadata.create_or_update` or
     `delete_entity`

Handlers are registered with the dispatcher in `register_defaults()`.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from metadata.generated.schema.entity.data.topic import Topic

from connector.mappers import (
    domain_to_create_request,
    event_to_topic_request,
    topic_fqn,
)

from .dispatcher import BridgeContext, Dispatcher

logger = logging.getLogger(__name__)


# -------------------------------------------------------------- event handlers


def on_event_upsert(ctx: BridgeContext, payload: Dict[str, Any]) -> None:
    """Triggered by `event.created` / `event.updated` / `eventVersion.updated`.

    Refetches the event + latest version + schema, then create_or_updates
    the corresponding Topic.
    """
    event_id = _pick(payload, "eventId", "id", "resourceId")
    event_version_id = _pick(payload, "eventVersionId")
    if not event_id and not event_version_id:
        logger.debug("event-upsert payload had no usable id: %s", payload)
        return

    version: Optional[Dict[str, Any]] = None
    if event_version_id:
        version = ctx.ep_client.get_event_version(event_version_id)
        if version and not event_id:
            event_id = version.get("eventId")
    if not event_id:
        return

    event = ctx.ep_client.get_event(event_id)
    if not event:
        logger.warning("Event %s not found in EP; skipping", event_id)
        return

    if not version:
        version = ctx.ep_client.get_latest_event_version(event_id)
        if not version:
            logger.warning("Event %s has no versions; skipping", event_id)
            return

    domain = ctx.ep_client.get_application_domain(event.get("applicationDomainId"))
    if not domain:
        logger.warning("Event %s has no resolvable domain; skipping", event_id)
        return

    schema_payload = None
    schema_version_id = version.get("schemaVersionId")
    if schema_version_id:
        sv = ctx.ep_client.get_schema_version(schema_version_id)
        sid = (sv or {}).get("schemaId")
        schema = ctx.ep_client.get_schema(sid) if sid else None
        schema_payload = {"version": sv, "schema": schema}

    request = event_to_topic_request(
        service_name=ctx.service_name,
        domain=domain,
        event=event,
        event_version=version,
        schema_payload=schema_payload,
    )
    ctx.om.create_or_update(data=request)
    logger.info(
        "Upserted Topic %s (event_version_id=%s)",
        topic_fqn(
            ctx.service_name,
            event.get("name") or "unnamed",
            str(version.get("version") or "1.0.0"),
        ),
        version.get("id"),
    )


def on_event_delete(ctx: BridgeContext, payload: Dict[str, Any]) -> None:
    """Triggered by `event.deleted` / `eventVersion.deleted`.

    Soft-deletes the Topic. We accept either the resource id (for the EP
    object) or the topic FQN (for replay tests).
    """
    fqn = payload.get("topicFqn")
    if not fqn:
        # Without the version we cannot rebuild the FQN; fall back to a
        # best-effort delete-by-name based on the event name in the payload.
        ev_name = payload.get("eventName") or payload.get("name")
        version = payload.get("version") or payload.get("eventVersion")
        if ev_name and version:
            fqn = topic_fqn(ctx.service_name, ev_name, str(version))
    if not fqn:
        logger.debug("event-delete payload missing fqn hints: %s", payload)
        return
    entity = ctx.om.get_by_name(entity=Topic, fqn=fqn)
    if not entity:
        return
    ctx.om.delete(entity=Topic, entity_id=entity.id, recursive=False, hard_delete=False)
    logger.info("Soft-deleted Topic %s", fqn)


def on_schema_upsert(ctx: BridgeContext, payload: Dict[str, Any]) -> None:
    """Triggered by `schema.updated` / `schemaVersion.updated`.

    A schema change can affect many events. Find every event version that
    references the schema version, then reuse `on_event_upsert` to refresh
    each Topic.
    """
    schema_version_id = _pick(payload, "schemaVersionId", "resourceId", "id")
    if not schema_version_id:
        return

    # No direct "events using schema version" endpoint exists, so this is
    # best-effort: ask EP for the schema version, then for events filtered
    # by `schemaVersionIds` (newer EP editions expose this filter; older
    # ones require a full domain walk - acceptable for a webhook hot path).
    sv = ctx.ep_client.get_schema_version(schema_version_id)
    if not sv:
        return
    schema_id = sv.get("schemaId")
    schema = ctx.ep_client.get_schema(schema_id) if schema_id else None
    domain_id = (schema or {}).get("applicationDomainId")
    if not domain_id:
        return
    for event in ctx.ep_client.list_events(domain_id):
        on_event_upsert(ctx, {"eventId": event["id"]})


def _entity_id_str(entity: Any) -> Optional[str]:
    """Extract an OM entity's id as a string regardless of SDK shape.

    OM 1.6+ wraps UUID-typed fields in `RootModel(root=UUID)`; older SDKs
    exposed the raw UUID. Either way we want a plain string suitable for
    `EntityReference(id=...)`.
    """
    if entity is None:
        return None
    raw_id = getattr(entity, "id", None)
    if raw_id is None:
        return None
    return str(getattr(raw_id, "root", raw_id))


def on_application_upsert(ctx: BridgeContext, payload: Dict[str, Any]) -> None:
    """Triggered by `application.*` / `applicationVersion.*`.

    Recomputes lineage edges for the affected application. We do not patch
    Topics here; their messageSchema and tags don't depend on the app.
    """
    app_id = _pick(payload, "applicationId", "resourceId", "id")
    if not app_id:
        return
    app = ctx.ep_client.get_application(app_id)
    if not app:
        return
    version = ctx.ep_client.get_latest_application_version(app_id)
    if not version:
        return

    from connector.mappers import (
        app_to_pipeline_request,
        app_topic_lineage_request,
    )

    domain = ctx.ep_client.get_application_domain(app.get("applicationDomainId"))
    if not domain:
        return
    # Wave 5 (#41): write under the same tenant-prefixed apps PipelineService
    # the metadata pass + soft-delete use, so the bridge's incremental
    # upserts don't create duplicate Pipelines under the bare service name.
    from connector.fqn import apply_tenant_prefix
    from connector.property_keys import APP_PIPELINE_SERVICE_NAME

    app_service = apply_tenant_prefix(APP_PIPELINE_SERVICE_NAME, ctx.tenant_prefix)
    pipeline_request = app_to_pipeline_request(
        domain=domain, app=app, app_version=version, service_name=app_service,
    )
    if pipeline_request is None:
        return
    pipeline_entity = ctx.om.create_or_update(data=pipeline_request)
    pipeline_id = _entity_id_str(pipeline_entity)
    if pipeline_id is None:
        logger.warning(
            "bridge on_application_upsert: pipeline create_or_update returned no id"
            " for app %s; skipping lineage emit", app.get("name"),
        )
        return

    for ev_id in version.get("declaredProducedEventVersionIds") or []:
        ev_version = ctx.ep_client.get_event_version(ev_id)
        if not ev_version:
            continue
        event = ctx.ep_client.get_event(ev_version.get("eventId"))
        if not event:
            continue
        fqn = topic_fqn(
            ctx.service_name,
            event.get("name") or "unnamed",
            str(ev_version.get("version") or "1.0.0"),
        )
        topic_entity = ctx.om.get_by_name(entity=Topic, fqn=fqn)
        topic_id = _entity_id_str(topic_entity)
        if topic_id is None:
            logger.warning(
                "bridge on_application_upsert: topic %s not in OM yet,"
                " skipping lineage edge (will retry on next event)",
                fqn,
            )
            continue
        req = app_topic_lineage_request(
            topic_id=topic_id,
            pipeline_id=pipeline_id,
            app=app,
            direction="publishes",
        )
        if req is not None:
            ctx.om.add_lineage(data=req)


def on_domain_upsert(ctx: BridgeContext, payload: Dict[str, Any]) -> None:
    """Triggered by `applicationDomain.*`.

    Refreshes the corresponding OM Domain entity. The bridge does not own
    Topic-to-Domain assignments here - those flow through `on_event_upsert`.
    """
    domain_id = _pick(payload, "applicationDomainId", "resourceId", "id")
    if not domain_id:
        return
    domain = ctx.ep_client.get_application_domain(domain_id)
    if not domain:
        return
    req = domain_to_create_request(domain)
    if req is not None:
        ctx.om.create_or_update(data=req)


# -------------------------------------------------------------- registration


# Maps Event Portal eventType strings -> handler. Adjust as the bridge
# learns about additional event types from your EP edition.
DEFAULT_HANDLERS = [
    ("event.created", on_event_upsert),
    ("event.updated", on_event_upsert),
    ("event.deleted", on_event_delete),
    ("eventVersion.created", on_event_upsert),
    ("eventVersion.updated", on_event_upsert),
    ("eventVersion.deleted", on_event_delete),
    ("schema.updated", on_schema_upsert),
    ("schemaVersion.updated", on_schema_upsert),
    ("application.created", on_application_upsert),
    ("application.updated", on_application_upsert),
    ("applicationVersion.created", on_application_upsert),
    ("applicationVersion.updated", on_application_upsert),
    ("applicationDomain.created", on_domain_upsert),
    ("applicationDomain.updated", on_domain_upsert),
]


def register_defaults(dispatcher: Dispatcher) -> Dispatcher:
    for event_type, handler in DEFAULT_HANDLERS:
        dispatcher.register(event_type, handler)
    return dispatcher


# ---------------------------------------------------------------- utilities


def _pick(payload: Dict[str, Any], *keys: str) -> Optional[str]:
    """First non-empty value among the candidate keys, walking `data` too.

    EP webhook payloads wrap the actual resource in `data` for some event
    types; we look there as a fallback.
    """
    for k in keys:
        if payload.get(k):
            return str(payload[k])
    data = payload.get("data") or {}
    if isinstance(data, dict):
        for k in keys:
            if data.get(k):
                return str(data[k])
    return None
