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
    AUDIT_WATERMARK_KEY,
    CP_APP_DOMAIN_ID,
    CP_APP_DOMAIN_NAME,
    CP_APP_ID,
    CP_APP_VERSION_ID,
    CP_CONSUMED_BY,
    CP_DOMAIN_ID,
    CP_DOMAIN_NAME,
    CP_EP_APP_DOMAIN,
    CP_EP_APPLICATION,
    CP_EP_DOMAIN,
    CP_EP_EVENT,
    CP_EP_SCHEMA,
    CP_EVENT_ID,
    CP_EVENT_VERSION_ID,
    CP_MODELED_MESH_IDS,
    CP_PUBLISHED_BY,
    CP_SCHEMA_VERSION_ID,
    CP_STATE,
    CP_STATE_CHANGED_AT,
    CP_TOPIC_ADDRESS,
)

logger = logging.getLogger(__name__)


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
# Raw-id properties (CP_DOMAIN_ID etc.) stay registered for backward
# compatibility with existing data; the connector does not set them on new
# ingests anymore.
TOPIC_CUSTOM_PROPERTIES: List[Tuple[str, str, str]] = [  # (key, type, description)
    # New: user-facing markdown links back to the EP designer.
    (CP_EP_DOMAIN, "markdown", "Link to the originating EP application domain"),
    (CP_EP_EVENT, "markdown", "Link to the EP event + version"),
    (CP_EP_SCHEMA, "markdown", "Link to the EP schema + version (if present)"),
    # User-visible textual props.
    (CP_TOPIC_ADDRESS, "string", "Reconstructed Solace topic address with vars"),
    (CP_STATE, "string", "Event Portal lifecycle state (Draft, Released, ...)"),
    (CP_STATE_CHANGED_AT, "string", "ISO timestamp of last state change"),
    # Legacy raw-id props -- kept registered so existing topics keep their
    # values; new ingests no longer populate these.
    (CP_DOMAIN_ID, "string", "(legacy) Event Portal application domain id"),
    (CP_DOMAIN_NAME, "string", "(legacy) Event Portal application domain name"),
    (CP_EVENT_ID, "string", "(legacy) Event Portal event id"),
    (CP_EVENT_VERSION_ID, "string", "(legacy) Event Portal event version id"),
    (CP_SCHEMA_VERSION_ID, "string", "(legacy) Event Portal schema version id"),
    (CP_MODELED_MESH_IDS, "string", "Comma-separated modeled event mesh ids"),
    (CP_PUBLISHED_BY, "string", "(legacy) Application(s) publishing this topic"),
    (CP_CONSUMED_BY, "string", "(legacy) Application(s) consuming this topic"),
]

# Watermark for the audit-based reconciliation job is defined in
# property_keys.py and re-exported above via the import.
MESSAGING_SERVICE_CUSTOM_PROPERTIES: List[Tuple[str, str, str]] = [
    (
        AUDIT_WATERMARK_KEY,
        "string",
        "ISO timestamp of the last successfully reconciled EP audit event",
    ),
]

# Pipeline custom properties for EP applications mapped to Pipeline entities.
PIPELINE_CUSTOM_PROPERTIES: List[Tuple[str, str, str]] = [
    # New markdown back-links.
    (CP_EP_APPLICATION, "markdown", "Link to the EP application + version"),
    (CP_EP_APP_DOMAIN, "markdown", "Link to the EP application domain"),
    # Legacy raw-id props (no longer populated on new ingests).
    (CP_APP_ID, "string", "(legacy) Event Portal application id"),
    (CP_APP_VERSION_ID, "string", "(legacy) Event Portal application version id"),
    (CP_APP_DOMAIN_ID, "string", "(legacy) Event Portal application domain id"),
    (CP_APP_DOMAIN_NAME, "string", "(legacy) Event Portal application domain name"),
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


# ---------------------------------------------------------------- top-level

def bootstrap(om) -> None:
    """Run the full idempotent bootstrap against an OM instance."""
    ensure_classification(om)
    for tag_name, tag_desc in TAGS:
        ensure_tag(om, CLASSIFICATION_NAME, tag_name, tag_desc)
    for key, ptype, desc in TOPIC_CUSTOM_PROPERTIES:
        ensure_custom_property(om, "topic", key, ptype, desc)
    for key, ptype, desc in MESSAGING_SERVICE_CUSTOM_PROPERTIES:
        ensure_custom_property(om, "messagingService", key, ptype, desc)
    for key, ptype, desc in PIPELINE_CUSTOM_PROPERTIES:
        ensure_custom_property(om, "pipeline", key, ptype, desc)
    ensure_pipeline_service(om)


# ---------------------------------------------------------------- CLI

def _build_om(host_port: str, jwt_token: str):
    from metadata.generated.schema.entity.services.connections.metadata.openMetadataConnection import (
        OpenMetadataConnection,
    )
    from metadata.generated.schema.security.client.openMetadataJWTClientConfig import (
        OpenMetadataJWTClientConfig,
    )
    from metadata.ingestion.ometa.ometa_api import OpenMetadata

    return OpenMetadata(
        OpenMetadataConnection(
            hostPort=host_port,
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
    args = parser.parse_args(argv)

    om = _build_om(args.host_port, args.jwt_token)
    bootstrap(om)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
