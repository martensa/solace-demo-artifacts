"""Idempotent OpenMetadata bootstrap for the Solace Event Portal connector.

Creates everything the connector and bridge rely on but never own:

  * `EventPortal` classification + lifecycle tags
    (Draft, Released, Deprecated, Retired, Application)
  * Topic custom properties used by `connector.mappers`
    (CP_DOMAIN_ID, CP_EVENT_VERSION_ID, ...)
  * MessagingService custom property `eventPortalAuditWatermark`
    used by the reconciliation job

Run once after installing OM, and re-run whenever the connector adds a
new custom property. Every step is read-then-create — safe to re-execute.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any, Dict, List, Optional, Tuple

from .property_keys import (
    APP_PIPELINE_SERVICE_NAME,
    CONSUMER_STORAGE_SERVICE_NAME,
    EVENT_API_STORAGE_SERVICE_NAME,
    SCHEMA_DATABASE_NAME,
    SCHEMA_DATABASE_SERVICE_NAME,
    TOPIC_TREE_STORAGE_SERVICE_NAME,
    CP_APP_DOMAIN_ID,
    CP_APP_DOMAIN_NAME,
    CP_APP_ID,
    CP_APP_VERSION_ID,
    CP_CONSUMED_BY,
    CP_CONSUMER_BROKER_TYPE,
    CP_CONSUMER_ID,
    CP_CONSUMER_SUBSCRIPTIONS,
    CP_CONSUMER_TYPE,
    CP_CONTAINS_PII,
    CP_DOMAIN_ID,
    CP_DOMAIN_NAME,
    CP_EP_APP_DOMAIN,
    CP_EP_APPLICATION,
    CP_EP_DOMAIN,
    CP_EP_EVENT,
    CP_EP_SCHEMA,
    CP_EAPP_ID,
    CP_EAPP_PLANS,
    CP_EAPP_VERSION_ID,
    CP_EP_DELETED_AT,
    CP_EP_EAPP,
    CP_EP_EVENT_API,
    CP_EVENT_API_ID,
    CP_EVENT_API_VERSION_ID,
    CP_EVENT_ID,
    CP_EVENT_VERSION_ID,
    CP_IS_LATEST_VERSION,
    CP_MODELED_MESH_IDS,
    CP_PUBLISHED_BY,
    CP_SCHEMA_CONTENT,
    CP_SCHEMA_ID,
    CP_SCHEMA_TYPE,
    CP_SCHEMA_VERSION_ID,
    CP_STATE,
    CP_STATE_CHANGED_AT,
    CP_TOPIC_ADDRESS,
    CP_TOPIC_SEGMENT,
    CP_TOPIC_SEGMENT_DEPTH,
    CP_TOPIC_SEGMENT_PATH,
    PII_CLASSIFICATION,
    PII_TAG_NAME,
)

logger = logging.getLogger(__name__)

# Wave 5 (#62): a dedicated compliance classification so ALDI IT-Sec can
# govern the PII tag independently of the lifecycle EventPortal.* tags.
PII_CLASSIFICATION_DESC = (
    "Compliance + data-protection tags for Solace Event Portal entities."
)


CLASSIFICATION_NAME = "EventPortal"
CLASSIFICATION_DESC = (
    "Lifecycle and provenance tags imported from Solace Event Portal."
)

TAGS: List[Tuple[str, str]] = [
    ("Draft", "Event Portal lifecycle state: Draft"),
    ("Released", "Event Portal lifecycle state: Released"),
    ("Deprecated", "Event Portal lifecycle state: Deprecated"),
    ("Retired", "Event Portal lifecycle state: Retired"),
    ("Application", "Synthetic Topic representing an Event Portal application"),
]

# All custom-property keys used by the connector + bridge.
# `markdown` types render as clickable links in the OM UI -- preferred for
# the user-facing back-links to the Solace Cloud EP designer. The remaining
# `string` props (state, topicAddress, ...) carry textual / lookup info.
TOPIC_CUSTOM_PROPERTIES: List[Tuple[str, str, str]] = [  # (key, type, description)
    (CP_EP_DOMAIN, "markdown", "Link to the originating EP application domain"),
    (CP_EP_EVENT, "markdown", "Link to the EP event + version"),
    (CP_EP_SCHEMA, "markdown", "Link to the EP schema + version (if present)"),
    (CP_TOPIC_ADDRESS, "string", "Reconstructed Solace topic address with vars"),
    (CP_STATE, "string", "Event Portal lifecycle state (Draft, Released, ...)"),
    (CP_STATE_CHANGED_AT, "string", "ISO timestamp of last state change"),
    (
        CP_IS_LATEST_VERSION,
        "string",
        "'true' iff this Topic carries the highest semver of its EP event "
        "(Wave 1 #54). UI default-filter recommendation: "
        "eventPortalIsLatestVersion=true to hide deprecated history.",
    ),
    (
        CP_EP_DELETED_AT,
        "string",
        "ISO-8601 UTC timestamp set by the reconcile drift pass when the "
        "EP event version is no longer visible. Combined with the "
        "EventPortal.Retired tag (Wave 4 #61).",
    ),
    (
        CP_CONTAINS_PII,
        "string",
        "'true' iff a PII signal fired for this Topic (EP CA / tag / "
        "topic-segment / schema x-pii field). Pairs with the "
        "EventPortalCompliance.PII tag (Wave 5 #62).",
    ),
]

# Legacy properties — once registered for backward compatibility but no
# longer populated by current ingests. Removed from OM by
# `om-eventportal-bootstrap --remove-legacy`.
LEGACY_TOPIC_PROPERTIES: List[str] = [
    CP_DOMAIN_ID, CP_DOMAIN_NAME, CP_EVENT_ID, CP_EVENT_VERSION_ID,
    CP_SCHEMA_VERSION_ID, CP_MODELED_MESH_IDS, CP_PUBLISHED_BY, CP_CONSUMED_BY,
]

# OM 1.11 removed Type registration for service-level entities — there is
# no `messagingService` Type to attach custom properties to. The audit
# watermark we used in 0.3.x is dead code anyway: EP Cloud Enterprise
# does not expose an audit feed (Cluster 1.4), so reconcile is full-pull
# (#23) with no watermark needed. Kept the constant + import for backward
# compatibility with downstream code that may still reference it, but the
# bootstrap no longer tries to register a CP that the server rejects.
MESSAGING_SERVICE_CUSTOM_PROPERTIES: List[Tuple[str, str, str]] = []

# Wave 3 (#45): DataProduct CPs for EAPP.
DATAPRODUCT_CUSTOM_PROPERTIES: List[Tuple[str, str, str]] = [
    (CP_EP_EAPP, "markdown", "Link to the EP Event API Product + version"),
    (CP_EAPP_ID, "string", "EP Event API Product id"),
    (CP_EAPP_VERSION_ID, "string", "EP Event API Product version id"),
    (CP_EAPP_PLANS, "markdown", "EAPP plans + Class-of-Service policy table"),
    (
        CP_IS_LATEST_VERSION,
        "string",
        "'true' iff this DataProduct carries the highest semver of its EP "
        "Event API Product (Wave 3 #45).",
    ),
    # eapp_to_data_product_request stamps the EP lifecycle state; register it
    # on `dataProduct` so the create does not 400 with the unknown field.
    (CP_STATE, "string", "Event Portal lifecycle state (Draft, Released, ...)"),
]


# Wave 3 (#44): EventAPI Container custom properties.
CONTAINER_CUSTOM_PROPERTIES: List[Tuple[str, str, str]] = [
    (CP_EP_EVENT_API, "markdown", "Link to the EP Event API + version"),
    (CP_EVENT_API_ID, "string", "EP Event API id (stable)"),
    (CP_EVENT_API_VERSION_ID, "string", "EP Event API version id (per-version)"),
    (
        CP_IS_LATEST_VERSION,
        "string",
        "'true' iff this Container carries the highest semver of its EP "
        "Event API (Wave 3 #44).",
    ),
    # event_api_to_container_request stamps the EP lifecycle state on the
    # Event-API Container too; register it on `container` so the create
    # does not 400 with "Unknown custom field eventPortalState".
    (CP_STATE, "string", "Event Portal lifecycle state (Draft, Released, ...)"),
]


# Wave 3 (#53): Container custom properties for topic-tree segment Containers.
# Registered on the `container` entity type (same as #44/#55 Containers).
TOPIC_TREE_CUSTOM_PROPERTIES: List[Tuple[str, str, str]] = [
    (
        CP_TOPIC_SEGMENT,
        "string",
        "Topic-address segment value (`orders` / `{region}` / ...).",
    ),
    (
        CP_TOPIC_SEGMENT_PATH,
        "string",
        "Full slash-joined path from the topic-tree root to this segment.",
    ),
    (
        CP_TOPIC_SEGMENT_DEPTH,
        "string",
        "1-based depth of this segment within the tree.",
    ),
]


# Wave 3 (#52): Table custom properties for first-class EP Schemas.
# Registered on the `table` entity type since EP Schemas land as OM Tables
# under the synthetic `solace-event-portal-schemas` DatabaseService.
TABLE_CUSTOM_PROPERTIES: List[Tuple[str, str, str]] = [
    (CP_EP_SCHEMA, "markdown", "Link to the EP Schema + version"),
    (CP_SCHEMA_ID, "string", "EP Schema id (stable across versions)"),
    (CP_SCHEMA_VERSION_ID, "string", "EP Schema version id (per-version)"),
    (CP_SCHEMA_TYPE, "string", "Schema format (JSON, AVRO, PROTOBUF, XSD...)"),
    (
        CP_SCHEMA_CONTENT,
        "markdown",
        "Raw schema body rendered as a fenced markdown code block for "
        "in-OM review when field-level parsing was skipped (e.g. XSD).",
    ),
    (CP_STATE, "string", "Event Portal lifecycle state of this schema version"),
    (CP_STATE_CHANGED_AT, "string", "ISO timestamp of last state change"),
    (
        CP_IS_LATEST_VERSION,
        "string",
        "'true' iff this Table carries the highest semver of its EP "
        "Schema (Wave 3 #52).",
    ),
]


# Wave 3 (#55): Consumer-Queue Container custom properties.
# Registered on the same `container` entity type as CONTAINER_CUSTOM_PROPERTIES
# above. ensure_custom_property is idempotent so the loop just adds the
# missing ones — Container.customProperties grows by the union of both.
CONSUMER_CUSTOM_PROPERTIES: List[Tuple[str, str, str]] = [
    (CP_CONSUMER_ID, "string", "EP applicationVersion.consumers[].id (stable)"),
    (
        CP_CONSUMER_TYPE,
        "string",
        "EP consumer type (eventQueue, topicEndpoint, ...). Reflects how the "
        "binding behaves on the Solace broker.",
    ),
    (
        CP_CONSUMER_BROKER_TYPE,
        "string",
        "EP broker type the consumer binds to (solace, kafka, ...).",
    ),
    (
        CP_CONSUMER_SUBSCRIPTIONS,
        "markdown",
        "Subscription patterns table (type | pattern | matched event count) "
        "rendered from EP consumer.subscriptions[] for at-a-glance reading "
        "on the OM Container page.",
    ),
    # consumer_to_container_request links the consuming app + its domain on
    # the Container; register both on `container` so the create does not 400
    # with "Unknown custom field eventPortalApplication".
    (CP_EP_APPLICATION, "markdown", "Link to the EP application + version"),
    (CP_EP_APP_DOMAIN, "markdown", "Link to the EP application domain"),
]


# Pipeline custom properties for EP applications mapped to Pipeline entities.
PIPELINE_CUSTOM_PROPERTIES: List[Tuple[str, str, str]] = [
    (CP_EP_APPLICATION, "markdown", "Link to the EP application + version"),
    (CP_EP_APP_DOMAIN, "markdown", "Link to the EP application domain"),
    (
        CP_IS_LATEST_VERSION,
        "string",
        "'true' iff this Pipeline carries the highest semver of its EP "
        "application (Wave 1 #54).",
    ),
    (
        CP_EP_DELETED_AT,
        "string",
        "ISO-8601 UTC timestamp set by the reconcile drift pass when the "
        "EP application version is no longer visible. Combined with the "
        "EventPortal.Retired tag (Wave 4 #61).",
    ),
    (
        CP_CONTAINS_PII,
        "string",
        "'true' iff a PII signal fired for this application Pipeline "
        "(Wave 5 #62). Pairs with the EventPortalCompliance.PII tag.",
    ),
]

# Legacy Pipeline properties (no longer populated; removable via
# --remove-legacy).
LEGACY_PIPELINE_PROPERTIES: List[str] = [
    CP_APP_ID, CP_APP_VERSION_ID, CP_APP_DOMAIN_ID, CP_APP_DOMAIN_NAME,
]


# ---------------------------------------------------------------- low-level

def _client(om):
    """Return the underlying REST client of an OpenMetadata SDK instance."""
    return om.client


def _get_or_none(om, path: str) -> Optional[Dict[str, Any]]:
    try:
        return _client(om).get(path)
    except Exception as exc:  # 404 is the common case; SDK raises in various ways
        logger.debug("GET %s -> %s", path, exc)
        return None


# ---------------------------------------------------------------- ensure ops

def ensure_classification(om, name: str = CLASSIFICATION_NAME,
                          description: str = CLASSIFICATION_DESC) -> None:
    existing = _get_or_none(om, f"/classifications/name/{name}")
    if existing:
        logger.info("Classification %s already exists", name)
        return
    _client(om).post(
        "/classifications",
        json={"name": name, "description": description},
    )
    logger.info("Created classification %s", name)


def ensure_tag(om, classification: str, name: str, description: str) -> None:
    fqn = f"{classification}.{name}"
    existing = _get_or_none(om, f"/tags/name/{fqn}")
    if existing:
        logger.info("Tag %s already exists", fqn)
        return
    _client(om).post(
        "/tags",
        json={
            "classification": classification,
            "name": name,
            "description": description,
        },
    )
    logger.info("Created tag %s", fqn)


def ensure_storage_service(
    om,
    name: str,
    *,
    display_name: str,
    description: str,
    service_type: str = "CustomStorage",
) -> None:
    """Idempotently create a synthetic StorageService.

    Wave 3 (#44): used to host the EventAPI Containers under
    ``solace-event-portal-event-apis``. Container entities in OM
    require a StorageService as their service field; we pick the
    CustomStorage type so we never collide with a real S3 / ADLS
    storage definition.
    """
    existing = _get_or_none(om, f"/services/storageServices/name/{name}")
    if existing:
        logger.info("StorageService %s already exists", name)
        return
    body = {
        "name": name,
        "displayName": display_name,
        "description": description,
        "serviceType": service_type,
        "connection": {
            "config": {
                "type": service_type,
                "sourcePythonClass": "connector.event_portal_connector.SolaceEventPortalSource",
            }
        },
    }
    try:
        _client(om).post("/services/storageServices", json=body)
        logger.info("Created StorageService %s", name)
    except Exception:
        logger.warning(
            "POST /services/storageServices failed for %s; container emission "
            "may be skipped on older OM versions", name,
        )


def ensure_database_service(
    om,
    name: str,
    *,
    display_name: str,
    description: str,
    service_type: str = "CustomDatabase",
) -> None:
    """Idempotently create a synthetic DatabaseService.

    Wave 3 (#52): used to host the EP Schema Tables under
    ``solace-event-portal-schemas``. Tables in OM require a
    DatabaseService -> Database -> DatabaseSchema -> Table chain; this
    helper handles the root service.
    """
    existing = _get_or_none(om, f"/services/databaseServices/name/{name}")
    if existing:
        logger.info("DatabaseService %s already exists", name)
        return
    body = {
        "name": name,
        "displayName": display_name,
        "description": description,
        "serviceType": service_type,
        "connection": {
            "config": {
                "type": service_type,
                "sourcePythonClass": "connector.event_portal_connector.SolaceEventPortalSource",
            }
        },
    }
    try:
        _client(om).post("/services/databaseServices", json=body)
        logger.info("Created DatabaseService %s", name)
    except Exception:
        logger.warning(
            "POST /services/databaseServices failed for %s; schema Table "
            "emission may be skipped on older OM versions", name,
        )


def ensure_database(
    om,
    name: str,
    *,
    service: str,
    display_name: Optional[str] = None,
    description: str = "",
) -> None:
    """Idempotently create a Database under an existing DatabaseService."""
    fqn = f"{service}.{name}"
    existing = _get_or_none(om, f"/databases/name/{fqn}")
    if existing:
        logger.info("Database %s already exists", fqn)
        return
    body = {
        "name": name,
        "displayName": display_name or name,
        "description": description,
        "service": service,
    }
    try:
        _client(om).post("/databases", json=body)
        logger.info("Created Database %s", fqn)
    except Exception:
        logger.warning(
            "POST /databases failed for %s; schema Table emission may be skipped",
            fqn,
        )


def ensure_messaging_service(
    om,
    name: str = "solace-event-portal",
    description: str = (
        "Solace Event Portal -- the messaging service that owns the Topics "
        "imported from EP event versions."
    ),
) -> None:
    """Idempotently create the CustomMessaging service the connector imports into.

    Topics created by the ingestion workflow reference this service. When the
    connector runs headlessly (external CronJob, not via the OM UI's
    add-service flow) nothing else creates it, so the bulk Topic create fails
    with "messagingService instance for <name> not found". Creating it here
    makes the headless deploy self-sufficient. serviceType CustomMessaging so
    it never collides with a real Kafka / Redpanda service.
    """
    existing = _get_or_none(om, f"/services/messagingServices/name/{name}")
    if existing:
        logger.info("MessagingService %s already exists", name)
        return
    body = {
        "name": name,
        "displayName": "Solace Event Portal",
        "description": description,
        "serviceType": "CustomMessaging",
        "connection": {
            "config": {
                "type": "CustomMessaging",
                "sourcePythonClass": "connector.event_portal_connector.SolaceEventPortalSource",
            }
        },
    }
    try:
        _client(om).post("/services/messagingServices", json=body)
        logger.info("Created MessagingService %s", name)
    except Exception:
        logger.warning(
            "POST /services/messagingServices failed for %s; retrying via PUT "
            "without connection", name,
        )
        body.pop("connection", None)
        _client(om).put("/services/messagingServices", data=json.dumps(body))


def ensure_pipeline_service(
    om,
    name: str = APP_PIPELINE_SERVICE_NAME,
    description: str = "Synthetic service holding EP applications as Pipelines.",
) -> None:
    """Idempotently create the synthetic PipelineService that hosts EP-Apps.

    The OM PipelineService entity is a soft requirement for Pipeline
    creation: every Pipeline must reference an existing service. We pick
    serviceType=Custom so we never collide with a real Airflow/Dagster
    pipeline service.
    """
    existing = _get_or_none(om, f"/services/pipelineServices/name/{name}")
    if existing:
        logger.info("PipelineService %s already exists", name)
        return
    body = {
        "name": name,
        "displayName": "Solace Event Portal Applications",
        "description": description,
        "serviceType": "CustomPipeline",
        "connection": {
            "config": {
                "type": "CustomPipeline",
                "sourcePythonClass": "connector.event_portal_connector.SolaceEventPortalSource",
            }
        },
    }
    try:
        _client(om).post("/services/pipelineServices", json=body)
        logger.info("Created PipelineService %s", name)
    except Exception:
        # Older OM versions reject CustomPipeline service type; fall back
        # to creating it via the "create or update" PUT endpoint without
        # the connection block.
        logger.warning(
            "POST /services/pipelineServices failed; retrying via PUT without connection",
        )
        body.pop("connection", None)
        _client(om).put("/services/pipelineServices", data=json.dumps(body))


def ensure_custom_property(
    om,
    entity_type: str,
    key: str,
    property_type_name: str,
    description: str,
) -> None:
    """Add a custom property to an entity type (idempotent).

    OpenMetadata models custom-property type definitions as `Type` entities.
    To attach a property to e.g. `Topic`:

        1. fetch the `Topic` type: GET /metadata/types/name/topic
        2. fetch the property-type entity (e.g. `string`):
           GET /metadata/types/name/string
        3. PUT /metadata/types/{topicId} with the new property in
           `customProperties`

    The current set of allowed property type names: `string`, `markdown`,
    `integer`, `number`, `date`, `dateTime`, `email`, `enum`, `entityReference`.
    """
    type_entity = _get_or_none(om, f"/metadata/types/name/{entity_type}")
    if not type_entity:
        logger.warning("Entity type %s not found in OM; cannot add %s", entity_type, key)
        return
    type_id = type_entity.get("id")
    existing_props = {p.get("name") for p in (type_entity.get("customProperties") or [])}
    if key in existing_props:
        logger.info("Custom property %s.%s already exists", entity_type, key)
        return

    prop_type = _get_or_none(om, f"/metadata/types/name/{property_type_name}")
    if not prop_type:
        logger.error(
            "Property type %s not registered in OM; cannot add %s.%s",
            property_type_name, entity_type, key,
        )
        return

    body = {
        "name": key,
        "description": description,
        "propertyType": {"id": prop_type["id"], "type": "type"},
    }
    _client(om).put(f"/metadata/types/{type_id}", data=json.dumps(body))
    logger.info("Added custom property %s.%s (%s)", entity_type, key, property_type_name)


def delete_custom_property(
    om, entity_type: str, key: str, host_port: str, jwt: str
) -> bool:
    """Remove a custom property from an OM Type. Idempotent.

    OM 1.6 has no per-property DELETE endpoint. We send a JSON-Patch
    `remove` with explicit `Content-Type: application/json-patch+json`
    (the default ometa client uses `application/json`, which gives 400).
    Refresh the property list before each call so the array index stays
    correct after a previous remove.
    """
    import requests as _requests

    type_entity = _get_or_none(
        om, f"/metadata/types/name/{entity_type}?fields=customProperties"
    )
    if not type_entity:
        logger.warning("Entity type %s not found in OM", entity_type)
        return False
    type_id = type_entity.get("id")
    props = type_entity.get("customProperties") or []
    index = next((i for i, p in enumerate(props) if p.get("name") == key), None)
    if index is None:
        return False
    patch = [{"op": "remove", "path": f"/customProperties/{index}"}]
    base = host_port.rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    headers = {
        "Content-Type": "application/json-patch+json",
        "Accept": "application/json",
        "Authorization": f"Bearer {jwt}",
    }
    url = f"{base}/metadata/types/{type_id}"
    try:
        resp = _requests.patch(url, headers=headers, data=json.dumps(patch), timeout=30)
        resp.raise_for_status()
    except Exception:
        logger.exception("PATCH remove failed for %s.%s -- not fatal", entity_type, key)
        return False
    logger.info("Removed custom property %s.%s", entity_type, key)
    return True


def remove_legacy_properties(om, host_port: str, jwt: str) -> Dict[str, int]:
    """Delete every legacy raw-id custom property from Topic + Pipeline.

    Safe to run multiple times -- missing properties are silently skipped.
    Returns a dict {entity_type: number_removed}.
    """
    removed = {"topic": 0, "pipeline": 0}
    for key in LEGACY_TOPIC_PROPERTIES:
        if delete_custom_property(om, "topic", key, host_port, jwt):
            removed["topic"] += 1
    for key in LEGACY_PIPELINE_PROPERTIES:
        if delete_custom_property(om, "pipeline", key, host_port, jwt):
            removed["pipeline"] += 1
    return removed


# ---------------------------------------------------------------- top-level

# Wave 1 (#43): one OM Classification per EP custom-attribute name.
CA_CLASSIFICATION_PREFIX = "EventPortalCustomAttribute_"


def _ca_classification_name(ca_name: str) -> str:
    """Map an EP CA name to an OM Classification name.

    OM accepts ``[A-Za-z][A-Za-z0-9_]*`` for classifications; sanitise to
    that vocabulary while preserving readability."""
    cleaned = "".join(c if c.isalnum() or c == "_" else "_" for c in (ca_name or "unnamed"))
    if not cleaned or not (cleaned[0].isalpha() or cleaned[0] == "_"):
        cleaned = f"x_{cleaned}"
    return f"{CA_CLASSIFICATION_PREFIX}{cleaned}"


def discover_custom_attribute_classifications(
    om,
    ep_client,
    exclude: Optional[set] = None,
) -> List[str]:
    """Walk EP customAttributeDefinitions and ensure a Classification
    per CA name (idempotent).

    Returns the list of Classification names created/verified. Tag values
    within each Classification are lazy-created later, at ingest time by
    the connector (we cannot pre-enumerate them since EP CAs are
    free-text per Cluster 1.6).

    ``exclude`` is a set of CA NAMES (case-sensitive) to skip --
    typically high-cardinality identity-like attributes
    (e.g. ``acl-principal``) where one-tag-per-value would explode.
    Configured via the workflow `customAttributeTagExclude` option.
    """
    skip = exclude or set()
    out: List[str] = []
    try:
        ca_defs = ep_client.list_custom_attribute_definitions()
    except Exception as exc:
        logger.warning("Failed to list EP CA definitions: %s", exc)
        return out
    for ca in ca_defs:
        ca_name = ca.get("name")
        if not ca_name or ca_name in skip:
            continue
        classification_name = _ca_classification_name(ca_name)
        description = (
            f"Auto-discovered from Solace Event Portal custom attribute "
            f"`{ca_name}` (valueType={ca.get('valueType', '?')}). Tag values "
            f"are lazy-created at ingest time."
        )
        ensure_classification(om, name=classification_name, description=description)
        out.append(classification_name)
    if out:
        logger.info(
            "Discovered %d EP custom-attribute classifications "
            "(skipped %d via customAttributeTagExclude)",
            len(out), len(skip),
        )
    return out


def bootstrap(
    om,
    ep_client=None,
    ca_exclude: Optional[set] = None,
    tenant_prefix: str = "",
    service_name: str = "solace-event-portal",
) -> None:
    """Run the full idempotent bootstrap against an OM instance.

    Pass ``ep_client`` to also auto-discover custom-attribute classifications
    from EP (#43). Without it the CA-tagging feature is dormant (the
    mapper still emits topics, just without CA tags).

    Wave 5 (#41): ``tenant_prefix`` prefixes the five shared synthetic
    services so two EP tenants do not collide. Empty = single-tenant
    (legacy names, unchanged). Run once per tenant with its prefix."""
    from .fqn import apply_tenant_prefix

    app_pipeline_service = apply_tenant_prefix(APP_PIPELINE_SERVICE_NAME, tenant_prefix)
    event_api_service = apply_tenant_prefix(EVENT_API_STORAGE_SERVICE_NAME, tenant_prefix)
    consumer_service = apply_tenant_prefix(CONSUMER_STORAGE_SERVICE_NAME, tenant_prefix)
    topic_tree_service = apply_tenant_prefix(TOPIC_TREE_STORAGE_SERVICE_NAME, tenant_prefix)
    schema_db_service = apply_tenant_prefix(SCHEMA_DATABASE_SERVICE_NAME, tenant_prefix)

    ensure_classification(om)
    for tag_name, tag_desc in TAGS:
        ensure_tag(om, CLASSIFICATION_NAME, tag_name, tag_desc)
    # Wave 5 (#62): compliance classification + PII tag.
    ensure_classification(om, name=PII_CLASSIFICATION, description=PII_CLASSIFICATION_DESC)
    ensure_tag(
        om, PII_CLASSIFICATION, PII_TAG_NAME,
        "Entity carries personally identifiable information (declarative: "
        "EP CA / tag / topic-segment / schema x-pii).",
    )
    for key, ptype, desc in TOPIC_CUSTOM_PROPERTIES:
        ensure_custom_property(om, "topic", key, ptype, desc)
    for key, ptype, desc in MESSAGING_SERVICE_CUSTOM_PROPERTIES:
        ensure_custom_property(om, "messagingService", key, ptype, desc)
    for key, ptype, desc in PIPELINE_CUSTOM_PROPERTIES:
        ensure_custom_property(om, "pipeline", key, ptype, desc)
    for key, ptype, desc in CONTAINER_CUSTOM_PROPERTIES:
        ensure_custom_property(om, "container", key, ptype, desc)
    for key, ptype, desc in CONSUMER_CUSTOM_PROPERTIES:
        ensure_custom_property(om, "container", key, ptype, desc)
    for key, ptype, desc in TOPIC_TREE_CUSTOM_PROPERTIES:
        ensure_custom_property(om, "container", key, ptype, desc)
    for key, ptype, desc in DATAPRODUCT_CUSTOM_PROPERTIES:
        ensure_custom_property(om, "dataProduct", key, ptype, desc)
    for key, ptype, desc in TABLE_CUSTOM_PROPERTIES:
        ensure_custom_property(om, "table", key, ptype, desc)
    # Main MessagingService that owns the imported Topics. Created here so a
    # headless deploy (external CronJob) is self-sufficient -- otherwise the
    # bulk Topic create 400s with "messagingService instance not found".
    ensure_messaging_service(om, name=service_name)
    ensure_pipeline_service(om, name=app_pipeline_service)
    # Wave 3 (#44): synthetic StorageService for EventAPI Containers.
    ensure_storage_service(
        om,
        event_api_service,
        display_name="Solace Event Portal Event APIs",
        description=(
            "Synthetic OM StorageService that holds one Container per EP "
            "Event API + version, with lineage to the topics each API "
            "produces / consumes."
        ),
    )
    # Wave 3 (#55): synthetic StorageService for consumer-queue Containers.
    ensure_storage_service(
        om,
        consumer_service,
        display_name="Solace Event Portal Consumer Queues",
        description=(
            "Synthetic OM StorageService that holds one Container per EP "
            "applicationVersion.consumers[] entry (the Solace queue / "
            "topic-endpoint a consuming app binds to). Lineage edges "
            "Topic -> Container -> Pipeline reflect the in-broker fan-out."
        ),
    )
    # Wave 3 (#53): synthetic StorageService for topic-tree segment Containers.
    ensure_storage_service(
        om,
        topic_tree_service,
        display_name="Solace Event Portal Topic Tree",
        description=(
            "Synthetic OM StorageService materialising the Solace "
            "topic-address namespace as nested Containers. Each segment "
            "(literal or `{variable}`) becomes a Container under its "
            "parent; lineage edges run from the deepest segment Container "
            "to the Topic. Configurable depth via the `topicTreeMaxDepth` "
            "connection option."
        ),
    )
    # Wave 3 (#52): synthetic DatabaseService + Database for first-class
    # EP Schemas (one Table per Schema + version).
    ensure_database_service(
        om,
        schema_db_service,
        display_name="Solace Event Portal Schemas",
        description=(
            "Synthetic OM DatabaseService that promotes EP Schemas to "
            "first-class OM Tables. Each EP Application Domain becomes a "
            "DatabaseSchema; each EP Schema + version becomes a Table "
            "(columns = parsed Avro/JSON/Protobuf fields)."
        ),
    )
    ensure_database(
        om,
        SCHEMA_DATABASE_NAME,
        service=schema_db_service,
        display_name="Schemas",
        description=(
            "Top-level container for per-domain DatabaseSchemas. EP has no "
            "matching concept; this single Database exists only to satisfy "
            "OM's DatabaseService -> Database -> DatabaseSchema -> Table chain."
        ),
    )
    if ep_client is not None:
        discover_custom_attribute_classifications(om, ep_client, exclude=ca_exclude)


# ---------------------------------------------------------------- CLI

def _build_om(host_port: str, jwt_token: str):
    from metadata.generated.schema.entity.services.connections.metadata.openMetadataConnection import (
        OpenMetadataConnection,
    )
    from metadata.generated.schema.security.client.openMetadataJWTClientConfig import (
        OpenMetadataJWTClientConfig,
    )
    from metadata.ingestion.ometa.ometa_api import OpenMetadata

    # OM SDK 1.11+ expects the host_port to include the `/api` path
    # prefix. Operators frequently paste just the OM root URL (e.g.
    # `http://openmetadata:8585`); auto-append `/api` so the bootstrap
    # CLI is forgiving. Trailing slashes are tolerated.
    normalised = host_port.rstrip("/")
    if not normalised.endswith("/api"):
        normalised = f"{normalised}/api"

    return OpenMetadata(
        OpenMetadataConnection(
            hostPort=normalised,
            authProvider="openmetadata",
            securityConfig=OpenMetadataJWTClientConfig(jwtToken=jwt_token),
        )
    )


def main(argv=None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Bootstrap OpenMetadata with EventPortal tags and custom properties"
    )
    parser.add_argument(
        "--host-port",
        default="http://openmetadata-server:8585/api",
        help="OM REST base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--jwt-token",
        required=True,
        help="Ingestion-bot JWT for OM",
    )
    parser.add_argument(
        "--remove-legacy",
        action="store_true",
        help="Delete legacy id-only custom properties from Topic + Pipeline "
        "types after running the regular bootstrap.",
    )
    parser.add_argument(
        "--remove-legacy-only",
        action="store_true",
        help="Skip the create/update bootstrap and only remove legacy props.",
    )
    # Wave 1 (#43): Auto-discover EP custom-attribute definitions and
    # register one OM Classification per CA name so tag values can be
    # populated at ingest time.
    parser.add_argument(
        "--ep-api-url",
        default="https://api.solace.cloud/api/v2",
        help="EP REST base URL (default: %(default)s). Only used when --ep-token "
        "is also given.",
    )
    parser.add_argument(
        "--ep-token",
        default=None,
        help="EP API token for #43 custom-attribute auto-discovery. Without "
        "this flag the CA discovery step is skipped.",
    )
    parser.add_argument(
        "--custom-attribute-exclude",
        default="",
        help="Comma-separated list of EP custom-attribute names to NOT register "
        "as classifications (typically high-cardinality identity attributes "
        "like 'acl-principal' where one-tag-per-value would explode).",
    )
    # Wave 5 (#41): multi-tenant. Prefix the five shared synthetic services
    # so two EP tenants do not collide. Must match the connector workflow's
    # tenantPrefix. Run once per tenant.
    parser.add_argument(
        "--tenant-prefix",
        default="",
        help="Prefix for the shared synthetic services (apps/event-apis/"
        "consumers/topic-tree/schemas). Empty = single-tenant (default).",
    )
    parser.add_argument(
        "--service-name",
        default="solace-event-portal",
        help="Name of the CustomMessaging service that owns the imported "
        "Topics. Must match the ingestion workflow's source.serviceName "
        "(default: %(default)s).",
    )
    args = parser.parse_args(argv)

    ep_client = None
    ca_exclude = {
        s.strip() for s in (args.custom_attribute_exclude or "").split(",") if s.strip()
    }
    if args.ep_token:
        from .event_portal_client import EventPortalClient
        ep_client = EventPortalClient(
            base_url=args.ep_api_url, api_token=args.ep_token,
        )

    om = _build_om(args.host_port, args.jwt_token)
    if not args.remove_legacy_only:
        bootstrap(
            om,
            ep_client=ep_client,
            ca_exclude=ca_exclude or None,
            tenant_prefix=args.tenant_prefix,
            service_name=args.service_name,
        )
    if args.remove_legacy or args.remove_legacy_only:
        removed = remove_legacy_properties(om, args.host_port, args.jwt_token)
        print(
            f"Legacy properties removed: topic={removed['topic']} "
            f"pipeline={removed['pipeline']}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
