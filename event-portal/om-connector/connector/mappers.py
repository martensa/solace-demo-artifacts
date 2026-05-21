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

# OM 1.6+ renamings inside metadata.generated.schema.type.schema:
#   SchemaType: moved here from entity.data.topic
#   MessageSchema -> Topic    (we re-alias for readability)
#   SchemaField   -> FieldModel
#   FieldName: unchanged, but pydantic v2 uses .root instead of .__root__
try:
    from metadata.generated.schema.type.schema import (
        FieldName,
        FieldModel as SchemaField,
        SchemaType,
        Topic as MessageSchema,
    )
except ImportError:  # pragma: no cover - legacy fallback
    from metadata.generated.schema.entity.data.topic import SchemaType  # OM <= 1.5
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
# Solace Cloud EP v2 returns `stateId` as a numeric string ("1"/"2"/...)
# referencing GET /architecture/states. Older EP editions surfaced the
# state name on `state` directly, so we accept both vocabularies.
_STATE_TAG: Dict[str, str] = {
    # Numeric IDs from /architecture/states (verified 2026-05).
    "1": "EventPortal.Draft",
    "2": "EventPortal.Released",
    "3": "EventPortal.Deprecated",
    "4": "EventPortal.Retired",
    # Name-based fallback for legacy editions.
    "DRAFT": "EventPortal.Draft",
    "RELEASED": "EventPortal.Released",
    "DEPRECATED": "EventPortal.Deprecated",
    "RETIRED": "EventPortal.Retired",
}

# Event Portal schema content type -> OM SchemaType enum.
_SCHEMA_TYPE_MAP: Dict[str, SchemaType] = {
    "JSON": SchemaType.JSON,
    "AVRO": SchemaType.Avro,
    # OM 1.6+ collapsed XML/XSD into the generic `Other` bucket.
    "XSD": SchemaType.Other,
    "XML": SchemaType.Other,
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


def _quote_if_dotted(part: str) -> str:
    """OM treats dots as FQN separators; parts containing a literal dot
    must be quoted (`name.with.dots` -> `"name.with.dots"`). Used for
    entity FQNs that include semver versions (1.0.0)."""
    if "." in part and not (part.startswith('"') and part.endswith('"')):
        return f'"{part}"'
    return part


def topic_fqn(service_name: str, event_name: str, version: str) -> str:
    return f"{service_name}.{_quote_if_dotted(build_topic_name(event_name, version))}"


def _as_extension(data: Dict[str, Any]):
    """Wrap a dict in the OM `EntityExtension` RootModel if available.

    OM 1.6+ uses pydantic v2; setting a raw dict on `Topic.extension`
    breaks `model_dump_json()` with "'dict' object has no attribute 'root'".
    Try the EntityExtension wrapper, fall back to the raw dict for older
    OM versions / slim test envs.
    """
    if not data:
        return None
    try:
        from metadata.generated.schema.type.basic import EntityExtension

        return EntityExtension(root=data)
    except Exception:
        return data


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
    # Solace Cloud EP returns stateId as a numeric string ("1".."4");
    # legacy editions returned the uppercase name on `state`. Look up
    # the tag map by either. Description prints the human-readable name.
    raw_state = str(
        event_version.get("stateId") or event_version.get("state") or ""
    )
    state_key = raw_state.upper()
    state_human = {
        "1": "Draft", "2": "Released", "3": "Deprecated", "4": "Retired",
    }.get(raw_state, state_key.title() or "UNKNOWN")

    description = "\n\n".join(
        p
        for p in [
            event.get("description") or "",
            event_version.get("description") or "",
            f"Source: Solace Event Portal application domain "
            f"`{domain.get('name')}`",
            f"Topic address: `{topic_address}`",
            f"Event Portal version: `{version_str}` (state `{state_human}`)",
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
    # Try numeric ID first (Solace Cloud), fall back to uppercase name.
    state_tag = _STATE_TAG.get(raw_state) or _STATE_TAG.get(state_key)
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
        CP_STATE: state_human if state_human != "UNKNOWN" else None,
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
        request.extension = _as_extension(extension)
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
    return f"{APP_PIPELINE_SERVICE_NAME}.{_quote_if_dotted(app_pipeline_name(app_name, version))}"


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
        request.extension = _as_extension(extension)
    if owner is not None and hasattr(request, "owner"):
        request.owner = owner
    return request


def app_topic_lineage_request(
    *,
    topic_id: str,
    pipeline_id: str,
    app: Dict[str, Any],
    direction: str,
):
    """Build an AddLineageRequest between a Pipeline (the EP app) and a Topic.

    OM 1.6+ requires resolved entity IDs on both ends of the edge --
    FQN alone results in "1 validation error for EntityReference". The
    connector resolves IDs via `OpenMetadata.get_by_name(...)` before
    calling this builder.

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

    direction = direction.lower()
    if direction == "publishes":
        from_id, from_type = pipeline_id, "pipeline"
        to_id, to_type = topic_id, "topic"
    elif direction == "consumes":
        from_id, from_type = topic_id, "topic"
        to_id, to_type = pipeline_id, "pipeline"
    else:
        raise ValueError(f"Unknown lineage direction: {direction}")

    return AddLineageRequest(
        edge=EntitiesEdge(
            fromEntity=EntityReference(id=from_id, type=from_type),
            toEntity=EntityReference(id=to_id, type=to_type),
            lineageDetails=LineageDetails(
                description=f"Solace Event Portal: {app_name} {direction}",
            ),
        )
    )
