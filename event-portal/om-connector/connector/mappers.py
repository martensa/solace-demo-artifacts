"""Translation from Event Portal payloads to OpenMetadata create requests.

Kept in a separate module so it can be unit-tested without spinning up the
ingestion framework. The Event Portal payload shapes are intentionally
treated as dicts (not pydantic models) — the API ships new fields often
and we want to be permissive.

Targets OpenMetadata 1.6+:
  * Application Domain  -> CreateDomainRequest
  * Modeled Event Mesh  -> CreateDataProductRequest (Topics as assets)
  * Event Version       -> CreateTopicRequest
  * Schema (JSON/Avro)  -> Topic.messageSchema
  * Lifecycle state     -> Tag + custom property
  * App publishes/subs  -> AddLineageRequest (Container -> Topic / reverse)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from metadata.generated.schema.api.data.createTopic import CreateTopicRequest
from metadata.generated.schema.entity.data.topic import SchemaType
from metadata.generated.schema.type.schema import (
    FieldName,
    MessageSchema,
    SchemaField,
)
from metadata.generated.schema.type.tagLabel import (
    LabelType,
    State,
    TagLabel,
    TagSource,
)

logger = logging.getLogger(__name__)


# Lifecycle state -> classification tag FQN.
_STATE_TAG: Dict[str, str] = {
    "DRAFT": "EventPortal.Draft",
    "RELEASED": "EventPortal.Released",
    "DEPRECATED": "EventPortal.Deprecated",
    "RETIRED": "EventPortal.Retired",
}

# Event Portal schema content type -> OM SchemaType enum.
_SCHEMA_TYPE_MAP: Dict[str, SchemaType] = {
    "JSON": SchemaType.JSON,
    "AVRO": SchemaType.Avro,
    "XSD": SchemaType.XML,
    "PROTOBUF": SchemaType.Protobuf,
}

_INVALID_FQN_CHARS = re.compile(r"[^A-Za-z0-9_\-.]")

# Re-export for callers that historically imported from connector.mappers.
from .property_keys import (  # noqa: E402,F401  (re-export)
    CP_CONSUMED_BY,
    CP_DOMAIN_ID,
    CP_DOMAIN_NAME,
    CP_EVENT_ID,
    CP_EVENT_VERSION_ID,
    CP_MODELED_MESH_IDS,
    CP_PUBLISHED_BY,
    CP_SCHEMA_VERSION_ID,
    CP_STATE,
    CP_STATE_CHANGED_AT,
    CP_TOPIC_ADDRESS,
)


# --------------------------------------------------------------- name helpers


def sanitize(name: Optional[str]) -> str:
    """Make `name` safe to embed in an OpenMetadata FQN."""
    return _INVALID_FQN_CHARS.sub("_", name or "unnamed")


def build_topic_name(event_name: str, version: str) -> str:
    """Topic entity name = `<event>_v<version>`, FQN-safe."""
    return sanitize(f"{event_name}_v{version}")


def topic_fqn(service_name: str, event_name: str, version: str) -> str:
    return f"{service_name}.{build_topic_name(event_name, version)}"


def domain_fqn(domain_name: str) -> str:
    return sanitize(domain_name)


def data_product_fqn(mesh_name: str) -> str:
    return sanitize(mesh_name)


# ------------------------------------------------------------- topic address


def extract_topic_address(event_version: Dict[str, Any]) -> Optional[str]:
    """Rebuild the topic address from the delivery descriptor.

    Event Portal stores topic addresses as an ordered list of address
    levels — each level is either a literal segment or a named variable.
    We reconstitute the slash-delimited string Solace publishes on:

        orders/{region}/created
    """
    addr = (event_version.get("deliveryDescriptor") or {}).get("address") or {}
    levels = addr.get("addressLevels") or []
    parts: List[str] = []
    for lvl in levels:
        ltype = (lvl.get("addressLevelType") or "").upper()
        name = lvl.get("name") or ""
        if not name:
            continue
        parts.append("{" + name + "}" if ltype == "VARIABLE" else name)
    return "/".join(parts) or None


# --------------------------------------------------------- schema extraction


def parse_schema_fields(content: Optional[str], schema_format: str) -> List[SchemaField]:
    """Dispatch to the per-format parser in `connector.schema_parsers`.

    JSON Schema, Avro, Protobuf, and XSD are all handled with recursive
    field extraction; unknown formats return an empty list (the Topic
    still ingests with the raw schemaText preserved).
    """
    from .schema_parsers import parse_fields as _dispatch
    return _dispatch(schema_format, content or "")


# ---------------------------------------------------------------- builders


def event_to_topic_request(
    *,
    service_name: str,
    domain: Dict[str, Any],
    event: Dict[str, Any],
    event_version: Dict[str, Any],
    schema_payload: Optional[Dict[str, Any]],
    modeled_mesh_ids: Optional[List[str]] = None,
    owner: Any = None,
) -> CreateTopicRequest:
    """Build a CreateTopicRequest from an Event Portal event version.

    `schema_payload`, when present, is `{"version": <schemaVersion>,
    "schema": <schema>}` as returned by EventPortalClient.
    """
    event_name = event.get("name") or "unnamed-event"
    version_str = str(event_version.get("version") or "1.0.0")
    topic_address = extract_topic_address(event_version) or event_name
    state = (
        event_version.get("stateId") or event_version.get("state") or ""
    ).upper()

    description = "\n\n".join(
        p
        for p in [
            event.get("description") or "",
            event_version.get("description") or "",
            f"Source: Solace Event Portal application domain "
            f"`{domain.get('name')}`",
            f"Topic address: `{topic_address}`",
            f"Event Portal version: `{version_str}` (state `{state or 'UNKNOWN'}`)",
        ]
        if p
    )

    message_schema: Optional[MessageSchema] = None
    if schema_payload:
        schema = schema_payload.get("schema") or {}
        schema_version = schema_payload.get("version") or {}
        fmt = (
            schema.get("schemaType")
            or schema.get("contentType")
            or "JSON"
        ).upper()
        om_type = _SCHEMA_TYPE_MAP.get(fmt, SchemaType.Other)
        text = schema_version.get("content")
        fields = parse_schema_fields(text, fmt)
        if text or fields:
            message_schema = MessageSchema(
                schemaType=om_type,
                schemaText=text,
                schemaFields=fields,
            )

    tags: List[TagLabel] = []
    state_tag = _STATE_TAG.get(state)
    if state_tag:
        tags.append(
            TagLabel(
                tagFQN=state_tag,
                labelType=LabelType.Automated,
                state=State.Suggested,
                source=TagSource.Classification,
            )
        )

    extension = {
        CP_DOMAIN_ID: domain.get("id"),
        CP_DOMAIN_NAME: domain.get("name"),
        CP_EVENT_ID: event.get("id"),
        CP_EVENT_VERSION_ID: event_version.get("id"),
        CP_TOPIC_ADDRESS: topic_address,
        CP_STATE: state or None,
        CP_STATE_CHANGED_AT: event_version.get("updatedTime"),
        CP_SCHEMA_VERSION_ID: event_version.get("schemaVersionId"),
        CP_MODELED_MESH_IDS: ",".join(modeled_mesh_ids) if modeled_mesh_ids else None,
    }
    # Strip Nones — OM rejects unknown-typed nulls.
    extension = {k: v for k, v in extension.items() if v is not None}

    request = CreateTopicRequest(
        name=build_topic_name(event_name, version_str),
        displayName=f"{event_name} v{version_str}",
        description=description,
        service=service_name,
        # Solace topics are not partitioned; OM requires the field so fix at 1.
        partitions=1,
        messageSchema=message_schema,
        tags=tags or None,
    )
    # extension is set post-construction so we can drop it cleanly when the
    # target OM version doesn't define the custom-property type yet.
    if extension and hasattr(request, "extension"):
        request.extension = extension
    if owner is not None and hasattr(request, "owner"):
        request.owner = owner
    return request


def domain_to_create_request(domain: Dict[str, Any], owner: Any = None):
    """Build an OM CreateDomainRequest from an EP application domain.

    Imported lazily because the symbol path differs across OM versions
    (1.3 vs 1.6). Falls back to returning a plain dict if unavailable, so
    callers running against an older OM can degrade to tags-only mapping.
    """
    try:
        from metadata.generated.schema.api.domains.createDomain import (
            CreateDomainRequest,
        )
        from metadata.generated.schema.entity.domains.domain import DomainType
    except Exception:  # pragma: no cover - depends on OM version
        logger.warning("OM Domain entity not importable; skipping domain mapping")
        return None

    request = CreateDomainRequest(
        name=sanitize(domain.get("name") or domain.get("id") or "unnamed"),
        displayName=domain.get("name"),
        description=(
            domain.get("description")
            or f"Solace Event Portal application domain `{domain.get('name')}`"
        ),
        domainType=DomainType.Aggregate,
    )
    if owner is not None and hasattr(request, "owner"):
        request.owner = owner
    return request


def modeled_mesh_to_data_product_request(mesh: Dict[str, Any], domain_fqn_: str):
    """Build a CreateDataProductRequest from a Modeled Event Mesh.

    Topics ingested under the mesh's domains are wired up as assets in a
    separate step (see source connector) since we need OM-side FQNs.
    """
    try:
        from metadata.generated.schema.api.domains.createDataProduct import (
            CreateDataProductRequest,
        )
    except Exception:  # pragma: no cover - depends on OM version
        logger.warning(
            "OM DataProduct entity not importable; skipping mesh mapping"
        )
        return None

    return CreateDataProductRequest(
        name=sanitize(mesh.get("name") or mesh.get("id") or "unnamed-mesh"),
        displayName=mesh.get("name"),
        description=(
            mesh.get("description")
            or "Solace Modeled Event Mesh imported from Event Portal."
        ),
        domain=domain_fqn_,
    )


def app_pipeline_name(app_name: str, version: str) -> str:
    return sanitize(f"{app_name}_v{version}")


def app_pipeline_fqn(app_name: str, version: str) -> str:
    """FQN of a Pipeline entity standing in for an EP application version.

    Pipelines live under the synthetic PipelineService
    `solace-event-portal-apps` (see APP_PIPELINE_SERVICE_NAME).
    """
    from .property_keys import APP_PIPELINE_SERVICE_NAME
    return f"{APP_PIPELINE_SERVICE_NAME}.{app_pipeline_name(app_name, version)}"


def app_to_pipeline_request(
    *, domain: Dict[str, Any], app: Dict[str, Any], app_version: Dict[str, Any],
    owner: Any = None,
):
    """Build a CreatePipelineRequest from an EP application version.

    The pipeline carries the EP application as a first-class entity in OM:
      * its produced/consumed event versions become lineage edges from/to
        the Topics in the MessagingService;
      * the application domain is recorded as a custom property + tag;
      * an `EventPortal.Application` classification tag flags this pipeline
        as machine-managed.
    """
    try:
        from metadata.generated.schema.api.data.createPipeline import (
            CreatePipelineRequest,
        )
    except Exception:  # pragma: no cover - depends on OM version
        logger.warning("OM Pipeline SDK not importable; skipping pipeline emit")
        return None

    from .property_keys import (
        APP_PIPELINE_SERVICE_NAME,
        CP_APP_DOMAIN_ID,
        CP_APP_DOMAIN_NAME,
        CP_APP_ID,
        CP_APP_VERSION_ID,
    )

    app_name = app.get("name") or "unknown-app"
    version_str = str(app_version.get("version") or "1.0.0")
    description = "\n\n".join(
        p for p in [
            app.get("description") or "",
            app_version.get("description") or "",
            f"Solace Event Portal application `{app_name}` v{version_str} "
            f"in domain `{domain.get('name')}`.",
        ] if p
    )

    tags = [
        TagLabel(
            tagFQN="EventPortal.Application",
            labelType=LabelType.Automated,
            state=State.Suggested,
            source=TagSource.Classification,
        )
    ]
    extension = {
        CP_APP_ID: app.get("id"),
        CP_APP_VERSION_ID: app_version.get("id"),
        CP_APP_DOMAIN_ID: domain.get("id"),
        CP_APP_DOMAIN_NAME: domain.get("name"),
    }
    extension = {k: v for k, v in extension.items() if v is not None}

    request = CreatePipelineRequest(
        name=app_pipeline_name(app_name, version_str),
        displayName=f"{app_name} v{version_str}",
        description=description,
        service=APP_PIPELINE_SERVICE_NAME,
        tags=tags,
    )
    if extension and hasattr(request, "extension"):
        request.extension = extension
    if owner is not None and hasattr(request, "owner"):
        request.owner = owner
    return request


def app_topic_lineage_request(
    *,
    topic_fqn_: str,
    app: Dict[str, Any],
    app_version: Dict[str, Any],
    direction: str,
):
    """Build an AddLineageRequest between a Pipeline (the EP app) and a Topic.

    `direction == "publishes"` -> pipeline -> topic
    `direction == "consumes"`  -> topic -> pipeline
    """
    try:
        from metadata.generated.schema.api.lineage.addLineage import (
            AddLineageRequest,
        )
        from metadata.generated.schema.type.entityLineage import (
            EntitiesEdge,
            LineageDetails,
        )
        from metadata.generated.schema.type.entityReference import EntityReference
    except Exception:  # pragma: no cover - depends on OM version
        logger.warning("OM Lineage SDK not importable; skipping lineage emit")
        return None

    app_name = app.get("name") or "unknown-app"
    version_str = str(app_version.get("version") or "1.0.0")
    pipeline_fqn = app_pipeline_fqn(app_name, version_str)

    direction = direction.lower()
    if direction == "publishes":
        from_fqn, from_type = pipeline_fqn, "pipeline"
        to_fqn, to_type = topic_fqn_, "topic"
    elif direction == "consumes":
        from_fqn, from_type = topic_fqn_, "topic"
        to_fqn, to_type = pipeline_fqn, "pipeline"
    else:
        raise ValueError(f"Unknown lineage direction: {direction}")

    return AddLineageRequest(
        edge=EntitiesEdge(
            fromEntity=EntityReference(id=None, type=from_type, fullyQualifiedName=from_fqn),
            toEntity=EntityReference(id=None, type=to_type, fullyQualifiedName=to_fqn),
            lineageDetails=LineageDetails(
                description=f"Solace Event Portal: {app_name} {direction}",
            ),
        )
    )
