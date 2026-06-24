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

import logging
from typing import Any, Dict, List, Optional

from metadata.generated.schema.api.data.createTopic import CreateTopicRequest

# OM 1.6+ renamings inside metadata.generated.schema.type.schema:
#   SchemaType: moved here from entity.data.topic
#   MessageSchema -> Topic    (we re-alias for readability)
#   SchemaField   -> FieldModel
#   FieldName: unchanged, but pydantic v2 uses .root instead of .__root__
# OM 1.6+ consolidated the schema-related types under `metadata.generated.schema.type.schema`
# (1.5 had them split across `entity.data.topic` for SchemaType). We target OM 1.11
# (ALDI) so the legacy import path is no longer in play; the fallback was dropped in
# Wave 0 as part of #47.
from metadata.generated.schema.type.schema import (
    FieldModel as SchemaField,
    SchemaType,
    Topic as MessageSchema,
)
from metadata.generated.schema.type.tagLabel import (
    LabelType,
    State,
    TagLabel,
    TagSource,
)

# Wave 1 cleanup: these were originally late-imports below `topic_fqn`,
# which tripped ruff's E402 (Module-level import not at top of file).
# They are pure-Python with no side effects so moving them up is safe.
from dataclasses import dataclass

from .property_keys import (
    DEFAULT_EP_APPLICATION_PATH,
    DEFAULT_EP_APPLICATION_VERSION_PATH,
    DEFAULT_EP_CONSOLE_URL,
    DEFAULT_EP_DOMAIN_PATH,
    DEFAULT_EP_EVENT_PATH,
    DEFAULT_EP_EVENT_VERSION_PATH,
    DEFAULT_EP_SCHEMA_PATH,
    DEFAULT_EP_SCHEMA_VERSION_PATH,
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

# EP's own schema vocabulary -> the canonical format keys used by
# _SCHEMA_TYPE_MAP and schema_parsers.parse_fields. EP returns
# schemaType="jsonSchema" / contentType="json" (not "JSON"), which would
# upper-case to "JSONSCHEMA", miss both maps, and fall back to
# SchemaType.Other with zero parsed fields. Normalise before lookup.
_EP_SCHEMA_FORMAT_ALIASES: Dict[str, str] = {
    "JSONSCHEMA": "JSON",
    "JSON": "JSON",
    "AVRO": "AVRO",
    "PROTOBUF": "PROTOBUF",
    "PROTO": "PROTOBUF",
    "XSD": "XSD",
    "XML": "XML",
    "DTD": "XML",
}


def _normalize_schema_format(raw: Optional[str]) -> str:
    """Map an EP schemaType/contentType value to a canonical format string.

    Empty / unknown -> "JSON" (EP's predominant format and the connector's
    historical default). Keeps the parser dispatch + SchemaType lookup working
    against EP's real vocabulary (jsonSchema, avro, protobuf, ...).
    """
    key = (raw or "").strip().upper()
    if not key:
        return "JSON"
    return _EP_SCHEMA_FORMAT_ALIASES.get(key, key)

# Re-export for callers that historically imported from connector.mappers.
from .property_keys import (  # noqa: E402,F401  (re-export)
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
    CP_EVENT_ID,
    CP_EVENT_VERSION_ID,
    CP_IS_LATEST_VERSION,
    CP_MODELED_MESH_IDS,
    CP_PUBLISHED_BY,
    CP_SCHEMA_VERSION_ID,
    CP_STATE,
    CP_STATE_CHANGED_AT,
    CP_TOPIC_ADDRESS,
    PII_TAG_FQN,
)


# --------------------------------------------------------------- name helpers


# FQN helpers moved to `.fqn` (pure module, no OM SDK dependency) so
# the bridge's reconcile + soft-delete paths can use them. Re-exported
# here for backwards compatibility with existing imports.
from .fqn import (  # noqa: F401, E402
    build_topic_name,
    quote_if_dotted as _quote_if_dotted,
    sanitize,
    topic_fqn,
)


def pii_tag() -> TagLabel:
    """The ``EventPortalCompliance.PII`` TagLabel applied when a PII signal
    fires (Wave 5 / #62). Pure -- the boolean decision is made upstream in
    the connector via ``connector.pii.has_pii_signal``; the mapper only
    renders the tag it is told to attach."""
    return TagLabel(
        tagFQN=PII_TAG_FQN,
        labelType=LabelType.Automated,
        state=State.Suggested,
        source=TagSource.Classification,
    )


# --------------------------------------------------- EP UI deep-links

@dataclass
class EpUrls:
    """Bundle of EP-console URL components used to build markdown
    back-links on Topics and Pipelines. Each path is a `str.format`
    template with named placeholders. The Solace Cloud Console SPA
    expects the human-readable domain name as a `domainName=...` query
    parameter in addition to the id-based path, so every helper takes
    the domain name as a second argument.
    """
    base: str = DEFAULT_EP_CONSOLE_URL
    domain_path: str = DEFAULT_EP_DOMAIN_PATH
    event_path: str = DEFAULT_EP_EVENT_PATH
    event_version_path: str = DEFAULT_EP_EVENT_VERSION_PATH
    schema_path: str = DEFAULT_EP_SCHEMA_PATH
    schema_version_path: str = DEFAULT_EP_SCHEMA_VERSION_PATH
    application_path: str = DEFAULT_EP_APPLICATION_PATH
    application_version_path: str = DEFAULT_EP_APPLICATION_VERSION_PATH
    # Wave 4 (#56): EP REST API base URL (e.g. https://api.solace.cloud/api/v2)
    # used to build downloadable AsyncAPI document URLs that land on
    # Pipeline.sourceUrl. Defaults to None -- when unset the AsyncAPI link
    # is simply not emitted (the OM Pipeline still ingests).
    api_url: Optional[str] = None
    # Default AsyncAPI version + format echoed back to OM. Override via
    # workflow option `asyncApiVersion` / `asyncApiFormat` if needed.
    async_api_version: str = "2.5.0"
    async_api_format: str = "json"

    def _resolve(self, tmpl: str, **kw) -> Optional[str]:
        from urllib.parse import quote
        # URL-encode every value to handle domain names with spaces,
        # ampersands, etc. (e.g. "Acme Retail - MDM").
        encoded = {k: quote(str(v), safe="") for k, v in kw.items()}
        try:
            return self.base.rstrip("/") + tmpl.format(**encoded)
        except (KeyError, IndexError):
            return None

    def domain(self, domain_id, domain_name):
        if not (domain_id and domain_name):
            return None
        return self._resolve(
            self.domain_path,
            domain_id=domain_id, domain_name=domain_name,
        )

    def event(self, domain_id, domain_name, event_id):
        if not (domain_id and domain_name and event_id):
            return None
        return self._resolve(
            self.event_path,
            domain_id=domain_id, domain_name=domain_name, event_id=event_id,
        )

    def event_version(self, domain_id, domain_name, event_id, event_version_id):
        if not (domain_id and domain_name and event_id and event_version_id):
            return None
        return self._resolve(
            self.event_version_path,
            domain_id=domain_id, domain_name=domain_name,
            event_id=event_id, event_version_id=event_version_id,
        )

    def schema(self, domain_id, domain_name, schema_id):
        if not (domain_id and domain_name and schema_id):
            return None
        return self._resolve(
            self.schema_path,
            domain_id=domain_id, domain_name=domain_name, schema_id=schema_id,
        )

    def schema_version(self, domain_id, domain_name, schema_id, sv_id):
        if not (domain_id and domain_name and schema_id and sv_id):
            return None
        return self._resolve(
            self.schema_version_path,
            domain_id=domain_id, domain_name=domain_name,
            schema_id=schema_id, schema_version_id=sv_id,
        )

    def application(self, domain_id, domain_name, application_id):
        if not (domain_id and domain_name and application_id):
            return None
        return self._resolve(
            self.application_path,
            domain_id=domain_id, domain_name=domain_name,
            application_id=application_id,
        )

    def async_api(self, app_version_id: Optional[str]) -> Optional[str]:
        """Return the downloadable EP AsyncAPI document URL for an
        applicationVersion. Wave 4 (#56). Returns ``None`` when
        ``api_url`` is unset or the version id is missing.
        """
        if not (self.api_url and app_version_id):
            return None
        from urllib.parse import quote
        return (
            f"{self.api_url.rstrip('/')}/architecture/applicationVersions/"
            f"{quote(str(app_version_id), safe='')}/asyncApi"
            f"?asyncApiVersion={quote(self.async_api_version, safe='')}"
            f"&format={quote(self.async_api_format, safe='')}"
        )

    def application_version(self, domain_id, domain_name, application_id, av_id):
        if not (domain_id and domain_name and application_id and av_id):
            return None
        return self._resolve(
            self.application_version_path,
            domain_id=domain_id, domain_name=domain_name,
            application_id=application_id, application_version_id=av_id,
        )


def _md_link(label: Optional[str], url: Optional[str]) -> Optional[str]:
    """Build a `[label](url)` markdown link; return None if either is empty.

    Labels with literal ']' or '[' are escaped so OM's renderer doesn't
    truncate them.
    """
    if not label or not url:
        return None
    safe = str(label).replace("[", "\\[").replace("]", "\\]")
    return f"[{safe}]({url})"


def _domain_ref(domain_name: Optional[str]):
    """Build the FullyQualifiedEntityName OM expects on `Topic.domain` /
    `Pipeline.domain`. Must be a RootModel instance (passing a plain
    string makes the metadata-rest sink crash with
    "'str' object has no attribute 'root'")."""
    if not domain_name:
        return None
    fqn = _quote_if_dotted(sanitize(domain_name))
    try:
        from metadata.generated.schema.type.basic import FullyQualifiedEntityName
        return FullyQualifiedEntityName(root=fqn)
    except Exception:  # pragma: no cover - slim envs
        return fqn


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


def _as_source_url(url: str):
    """Wrap a URL in the OM ``SourceUrl`` RootModel if available.

    OM 1.11+ uses pydantic v2. Assigning a raw ``str`` to
    ``Pipeline.sourceUrl`` *post-construction* (which bypasses field
    validation/coercion) makes ``model_dump_json()`` raise "'str' object
    has no attribute 'root'" on OM 1.13. Wrap it explicitly; fall back to
    the raw str for older OM / slim test envs.
    """
    if not url:
        return None
    try:
        from metadata.generated.schema.type.basic import SourceUrl

        return SourceUrl(root=url)
    except Exception:
        return url


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


def parse_schema_fields(
    content: Optional[str], schema_format: str, *, mark_pii: bool = False
) -> List[SchemaField]:
    """Dispatch to the per-format parser in `connector.schema_parsers`.

    JSON Schema, Avro, Protobuf, and XSD are all handled with recursive
    field extraction; unknown formats return an empty list (the Topic
    still ingests with the raw schemaText preserved). ``mark_pii`` (#62)
    is the connector's PII opt-in -- only then are x-pii fields marked.
    """
    from .schema_parsers import parse_fields as _dispatch
    return _dispatch(schema_format, content or "", mark_pii=mark_pii)


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
    ep_urls: Optional[EpUrls] = None,
    attach_to_domain: bool = True,
    is_latest_version: Optional[bool] = None,
    custom_attribute_tags: Optional[List[TagLabel]] = None,
    contains_pii: bool = False,
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
        fmt = _normalize_schema_format(
            schema.get("schemaType") or schema.get("contentType")
        )
        om_type = _SCHEMA_TYPE_MAP.get(fmt, SchemaType.Other)
        text = schema_version.get("content")
        # Wave 5 (#62): mark x-pii fields only when this Topic is flagged
        # PII (contains_pii implies the PII opt-in is on + a signal fired).
        fields = parse_schema_fields(text, fmt, mark_pii=contains_pii)
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
    # Wave 1 (#43): merge auto-discovered EP custom-attribute -> OM Tag
    # bindings produced by the connector for the event entity.
    if custom_attribute_tags:
        tags.extend(custom_attribute_tags)
    # Wave 5 (#62): PII compliance tag when the connector detected a signal.
    if contains_pii:
        tags.append(pii_tag())

    # User-facing markdown links back to the EP designer. Labels carry
    # the human-readable name (+ version), URL embeds the id.
    domain_id = domain.get("id")
    event_id = event.get("id")
    event_version_id = event_version.get("id")
    sv = (schema_payload or {}).get("version") or {}
    schema = (schema_payload or {}).get("schema") or {}
    schema_id = schema.get("id")
    schema_name = schema.get("name")
    sv_id = sv.get("id")
    sv_version = sv.get("version")

    urls = ep_urls or EpUrls()
    domain_name = domain.get("name")
    extension = {
        CP_EP_DOMAIN: _md_link(domain_name, urls.domain(domain_id, domain_name)),
        CP_EP_EVENT: _md_link(
            f"{event_name} v{version_str}",
            urls.event_version(domain_id, domain_name, event_id, event_version_id),
        ),
        CP_EP_SCHEMA: _md_link(
            f"{schema_name} v{sv_version}" if schema_name and sv_version else schema_name,
            urls.schema_version(domain_id, domain_name, schema_id, sv_id),
        ),
        CP_TOPIC_ADDRESS: topic_address,
        CP_STATE: state_human if state_human != "UNKNOWN" else None,
        CP_STATE_CHANGED_AT: event_version.get("updatedTime"),
        # Wave 1 (#54): mark whether this is the highest semver of the
        # event. With ingestAllVersions=true (now the default) the OM UI
        # can default-filter to is-latest=true and hide deprecated
        # historical versions without losing them from the catalog.
        CP_IS_LATEST_VERSION: (
            "true" if is_latest_version else "false"
        ) if is_latest_version is not None else None,
        # Wave 5 (#62): PII flag mirrors the EventPortalCompliance.PII tag.
        CP_CONTAINS_PII: "true" if contains_pii else None,
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
    if attach_to_domain:
        dref = _domain_ref(domain.get("name"))
        if dref is not None:
            # OM 1.9+ renamed `domain` -> `domains` (List[EntityReference]).
            # Prefer the new field; fall back to the legacy singular for
            # backward-compat testing against older OM SDKs.
            if hasattr(request, "domains"):
                request.domains = [dref]
            elif hasattr(request, "domain"):
                request.domain = dref
    if owner is not None and hasattr(request, "owner"):
        request.owner = owner
    return request


def domain_to_create_request(
    domain: Dict[str, Any],
    owner: Any = None,
    *,
    parent_fqn: Optional[str] = None,
):
    """Build an OM CreateDomainRequest from an EP application domain.

    Imported lazily because the symbol path differs across OM versions
    (1.3 vs 1.6). Falls back to returning a plain dict if unavailable, so
    callers running against an older OM can degrade to tags-only mapping.

    Wave 4 (#48): ``parent_fqn`` -- when given, set as the new Domain's
    parent so OM renders a hierarchy (parent → child) in the Domain
    tree. Pass a fully-qualified Domain name; the connector resolves
    EP-domain → parent FQN via the workflow option ``omDomainParentMap``.
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
    # Wave 4 (#48): attach to a pre-existing OM Domain (sub-domain shape).
    # OM 1.11 CreateDomainRequest.parent accepts a fullyQualifiedName
    # string directly; pre-1.11 wanted an EntityReference. Try string
    # first, fall back to EntityReference for back-compat.
    if parent_fqn and hasattr(request, "parent"):
        try:
            request.parent = parent_fqn
        except Exception:
            try:
                from metadata.generated.schema.type.entityReference import (
                    EntityReference,
                )
                request.parent = EntityReference(
                    fullyQualifiedName=parent_fqn, type="domain",
                )
            except Exception:  # pragma: no cover - SDK divergence
                pass
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

    # OM 1.9+ renamed the constructor kwarg `domain` -> `domains` (List).
    # Try the new shape first; fall back to the legacy singular if we are
    # running against an older SDK in a regression test.
    base_kwargs = dict(
        name=sanitize(mesh.get("name") or mesh.get("id") or "unnamed-mesh"),
        displayName=mesh.get("name"),
        description=(
            mesh.get("description")
            or "Solace Modeled Event Mesh imported from Event Portal."
        ),
    )
    try:
        return CreateDataProductRequest(**base_kwargs, domains=[domain_fqn_])
    except TypeError:  # pragma: no cover - pre-1.9 SDK fallback
        return CreateDataProductRequest(**base_kwargs, domain=domain_fqn_)


# app_pipeline_name + app_pipeline_fqn live in `.fqn`; re-exported below.


# --------------------------------------------------------- Event API (#44)


def event_api_to_container_request(
    *,
    event_api: Dict[str, Any],
    event_api_version: Dict[str, Any],
    domain: Dict[str, Any],
    ep_urls: Optional[EpUrls] = None,
    is_latest_version: Optional[bool] = None,
    service_name: Optional[str] = None,
):
    """Build a CreateContainerRequest from an EP Event API + version.

    Wave 3 (#44). Container lives under the synthetic StorageService
    ``solace-event-portal-event-apis`` so OM's Container UI can show
    the API contract -- description, owner, lifecycle, version
    history, EP UI back-link -- alongside the actual lineage edges
    to the topics the API produces / consumes (emitted separately).

    Returns ``None`` when the OM SDK does not expose Container types
    (very old environments), so the connector keeps emitting other
    entities.
    """
    try:
        from metadata.generated.schema.api.data.createContainer import (
            CreateContainerRequest,
        )
    except Exception:  # pragma: no cover - depends on OM version
        logger.warning("OM Container entity not importable; skipping Event API")
        return None

    from .property_keys import (
        CP_EP_EVENT_API,
        CP_EVENT_API_ID,
        CP_EVENT_API_VERSION_ID,
        CP_IS_LATEST_VERSION,
        CP_STATE,
        EVENT_API_STORAGE_SERVICE_NAME,
    )

    service = service_name or EVENT_API_STORAGE_SERVICE_NAME
    name = event_api.get("name") or "unnamed-event-api"
    version_str = str(event_api_version.get("version") or "1.0.0")
    state_id = str(event_api_version.get("stateId") or "")
    state_human = (
        _STATE_TAG.get(state_id, "EventPortal.Unknown").split(".", 1)[-1]
    )

    description = "\n\n".join(
        p for p in [
            event_api.get("description") or "",
            event_api_version.get("description") or "",
            f"Solace Event Portal Event API `{name}` v{version_str} in domain "
            f"`{domain.get('name')}` (state `{state_human}`).",
        ] if p
    )

    domain_id = domain.get("id")
    domain_name = domain.get("name")
    event_api_id = event_api.get("id")
    event_api_version_id = event_api_version.get("id")
    urls = ep_urls or EpUrls()
    # EP doesn't have a dedicated event-api designer URL template, fall back
    # to the domain graph page.
    api_url = urls.domain(domain_id, domain_name)

    extension = {
        CP_EP_EVENT_API: _md_link(f"{name} v{version_str}", api_url),
        CP_EVENT_API_ID: event_api_id,
        CP_EVENT_API_VERSION_ID: event_api_version_id,
        CP_STATE: state_human if state_human != "Unknown" else None,
        CP_IS_LATEST_VERSION: (
            "true" if is_latest_version else "false"
        ) if is_latest_version is not None else None,
    }
    extension = {k: v for k, v in extension.items() if v is not None}

    request = CreateContainerRequest(
        name=sanitize(f"{name}_v{version_str}"),
        displayName=f"{name} v{version_str}",
        description=description or None,
        service=service,
    )
    if extension and hasattr(request, "extension"):
        request.extension = _as_extension(extension)
    if hasattr(request, "domains"):
        dref = _domain_ref(domain_name)
        if dref is not None:
            request.domains = [dref]
    return request


def event_api_container_fqn(
    event_api_name: str, version: str, service_name: Optional[str] = None
) -> str:
    """FQN of the EventAPI Container under the synthetic StorageService."""
    from .property_keys import EVENT_API_STORAGE_SERVICE_NAME
    service = service_name or EVENT_API_STORAGE_SERVICE_NAME
    inner = sanitize(f"{event_api_name}_v{version}")
    return f"{service}.{_quote_if_dotted(inner)}"


# --------------------------------------------------------- EAPP (#45)


def eapp_to_data_product_request(
    *,
    eapp: Dict[str, Any],
    eapp_version: Dict[str, Any],
    domain: Dict[str, Any],
    container_asset_refs: Optional[List[Any]] = None,
    ep_urls: Optional[EpUrls] = None,
    is_latest_version: Optional[bool] = None,
):
    """Build a CreateDataProductRequest from an EP Event API Product version.

    Wave 3 (#45). The EAPP is the consumer-facing "product surface"
    bundling one or more Event APIs (see ``docs/asset-mapping-spec.md``
    Cluster 1.7). Asset references point at the EventAPI Container
    entities created by #44; OM 1.11+ DataProduct natively supports
    that via the ``assets`` field.

    ``plans[].solaceClassOfServicePolicy`` lands as a markdown table in
    a Custom Property so analysts see QoS / SLA at-a-glance on the
    DataProduct page without drilling back into EP.
    """
    try:
        from metadata.generated.schema.api.domains.createDataProduct import (
            CreateDataProductRequest,
        )
    except Exception:  # pragma: no cover
        logger.warning("OM DataProduct entity not importable; skipping EAPP")
        return None

    from .property_keys import (
        CP_EAPP_ID,
        CP_EAPP_PLANS,
        CP_EAPP_VERSION_ID,
        CP_EP_EAPP,
        CP_IS_LATEST_VERSION,
        CP_STATE,
    )

    name = eapp.get("name") or "unnamed-eapp"
    version_str = str(eapp_version.get("version") or "1.0.0")
    state_id = str(eapp_version.get("stateId") or "")
    state_human = (
        _STATE_TAG.get(state_id, "EventPortal.Unknown").split(".", 1)[-1]
    )
    domain_id = domain.get("id")
    domain_name = domain.get("name")
    urls = ep_urls or EpUrls()
    eapp_url = urls.domain(domain_id, domain_name)

    description = "\n\n".join(
        p for p in [
            eapp.get("description") or "",
            eapp_version.get("description") or "",
            f"Solace Event Portal Event API Product `{name}` v{version_str} "
            f"in domain `{domain_name}` (state `{state_human}`).",
        ] if p
    )

    plans_md = _render_eapp_plans_markdown(eapp_version.get("plans") or [])

    extension = {
        CP_EP_EAPP: _md_link(f"{name} v{version_str}", eapp_url),
        CP_EAPP_ID: eapp.get("id"),
        CP_EAPP_VERSION_ID: eapp_version.get("id"),
        CP_EAPP_PLANS: plans_md,
        CP_STATE: state_human if state_human != "Unknown" else None,
        CP_IS_LATEST_VERSION: (
            "true" if is_latest_version else "false"
        ) if is_latest_version is not None else None,
    }
    extension = {k: v for k, v in extension.items() if v is not None}

    base_kwargs = dict(
        name=sanitize(f"{name}_v{version_str}"),
        displayName=f"{name} v{version_str}",
        description=description or None,
    )
    if container_asset_refs:
        # OM 1.13 soft-deprecated CreateDataProductRequest.assets in favour
        # of the bulk PUT /v1/dataProducts/{name}/assets/add API. The inline
        # field is still ACCEPTED across 1.11-1.13, so this keeps working.
        # FOLLOW-UP: migrate to the bulkAssets endpoint before a future OM
        # release enforces the deprecation.
        base_kwargs["assets"] = container_asset_refs

    try:
        request = CreateDataProductRequest(
            **base_kwargs, domains=[domain_fqn(domain_name)]
        )
    except TypeError:  # pragma: no cover - pre-1.9 SDK
        request = CreateDataProductRequest(
            **base_kwargs, domain=domain_fqn(domain_name)
        )
    if extension and hasattr(request, "extension"):
        request.extension = _as_extension(extension)
    return request


# --------------------------------------------------------- Consumer Queue (#55)


def consumer_to_container_request(
    *,
    consumer: Dict[str, Any],
    app: Dict[str, Any],
    app_version: Dict[str, Any],
    domain: Dict[str, Any],
    service_name: Optional[str] = None,
):
    """Build a CreateContainerRequest for one EP applicationVersion.consumers[]
    entry.

    Wave 3 (#55). The Container represents the Solace queue (or
    topic-endpoint) the application binds to consume events. Lineage
    Topic -> Container (for each ``attractedEventVersionId`` the queue's
    subscription patterns match) + Container -> Pipeline (the consuming
    app's pipeline) is emitted by the connector separately.
    """
    try:
        from metadata.generated.schema.api.data.createContainer import (
            CreateContainerRequest,
        )
    except Exception:  # pragma: no cover
        logger.warning("OM Container entity not importable; skipping consumer")
        return None
    from .property_keys import CONSUMER_STORAGE_SERVICE_NAME

    service = service_name or CONSUMER_STORAGE_SERVICE_NAME
    name = consumer.get("name") or "unnamed-consumer"
    consumer_type = consumer.get("consumerType") or "eventQueue"
    broker_type = consumer.get("brokerType") or "solace"
    app_name = app.get("name") or "unknown-app"
    app_version_str = str(app_version.get("version") or "1.0.0")

    subs = consumer.get("subscriptions") or []
    patterns_md = _render_consumer_patterns_markdown(subs)

    description = (
        f"Solace Event Portal consumer queue `{name}` "
        f"({consumer_type}, broker {broker_type}) bound to application "
        f"`{app_name}` v{app_version_str} in domain `{domain.get('name')}`."
    )

    extension = {
        CP_CONSUMER_ID: consumer.get("id"),
        CP_CONSUMER_TYPE: consumer_type,
        CP_CONSUMER_BROKER_TYPE: broker_type,
        CP_CONSUMER_SUBSCRIPTIONS: patterns_md,
        CP_EP_APPLICATION: app_name,
        CP_EP_APP_DOMAIN: domain.get("name"),
    }
    extension = {k: v for k, v in extension.items() if v is not None}

    request = CreateContainerRequest(
        name=sanitize(f"{app_name}_{name}"),
        displayName=name,
        description=description,
        service=service,
    )
    if extension and hasattr(request, "extension"):
        request.extension = _as_extension(extension)
    return request


def _render_consumer_patterns_markdown(subscriptions: List[Dict[str, Any]]) -> Optional[str]:
    if not subscriptions:
        return None
    rows = ["| Type | Pattern | Matched Events |", "| --- | --- | --- |"]
    for s in subscriptions:
        kind = s.get("subscriptionType") or "?"
        value = (s.get("value") or "").replace("|", "/")
        matched = len(s.get("attractedEventVersionIds") or [])
        rows.append(f"| {kind} | `{value}` | {matched} |")
    return "\n".join(rows)


def consumer_container_fqn(
    app_name: str, consumer_name: str, service_name: Optional[str] = None
) -> str:
    """FQN of the Consumer Container under the synthetic StorageService.

    Mirrors how `consumer_to_container_request` builds the Container name:
    sanitized ``{app}_{consumer}`` under ``solace-event-portal-consumers``.
    """
    from .property_keys import CONSUMER_STORAGE_SERVICE_NAME
    service = service_name or CONSUMER_STORAGE_SERVICE_NAME
    inner = sanitize(f"{app_name}_{consumer_name}")
    return f"{service}.{_quote_if_dotted(inner)}"


# --------------------------------------------------------- Schemas (#52)


def domain_database_schema_fqn(
    domain_name: str, service_name: Optional[str] = None
) -> str:
    """FQN of the DatabaseSchema standing in for an EP Application Domain.

    Lives under ``solace-event-portal-schemas.schemas.<domain>`` so a
    user navigating in the OM 'Databases' panel can drill from
    Solace Event Portal Schemas -> schemas -> <domain> -> <SchemaName_vX>.
    """
    from .property_keys import SCHEMA_DATABASE_NAME, SCHEMA_DATABASE_SERVICE_NAME
    service = service_name or SCHEMA_DATABASE_SERVICE_NAME
    inner = sanitize(domain_name)
    return f"{service}.{SCHEMA_DATABASE_NAME}.{_quote_if_dotted(inner)}"


def schema_table_fqn(
    domain_name: str, schema_name: str, version: str,
    service_name: Optional[str] = None,
) -> str:
    """FQN of a Schema Table under the synthetic DatabaseSchema."""
    inner = sanitize(f"{schema_name}_v{version}")
    parent = domain_database_schema_fqn(domain_name, service_name=service_name)
    return f"{parent}.{_quote_if_dotted(inner)}"


def domain_to_database_schema_request(
    domain: Dict[str, Any], service_name: Optional[str] = None
):
    """Build a CreateDatabaseSchemaRequest for an EP Application Domain.

    Wave 3 (#52). One DatabaseSchema per EP domain hosts the per-Schema
    Table entities below it. The bootstrap creates the parent DatabaseService
    + Database lazily; this request just adds the per-domain bucket.
    """
    try:
        from metadata.generated.schema.api.data.createDatabaseSchema import (
            CreateDatabaseSchemaRequest,
        )
    except Exception:  # pragma: no cover
        logger.warning("OM DatabaseSchema entity not importable; skipping")
        return None
    from .property_keys import SCHEMA_DATABASE_NAME, SCHEMA_DATABASE_SERVICE_NAME
    service = service_name or SCHEMA_DATABASE_SERVICE_NAME
    domain_name = domain.get("name") or domain.get("id") or "unknown-domain"
    description = (
        f"Solace Event Portal application domain `{domain_name}`. "
        f"Hosts one OM Table per EP Schema + version for this domain."
    )
    return CreateDatabaseSchemaRequest(
        name=sanitize(domain_name),
        displayName=domain_name,
        description=description,
        database=f"{service}.{SCHEMA_DATABASE_NAME}",
    )


def schema_version_to_table_request(
    *,
    schema: Dict[str, Any],
    schema_version: Dict[str, Any],
    domain: Dict[str, Any],
    ep_urls: Optional["EpUrls"] = None,
    is_latest_version: Optional[bool] = None,
    service_name: Optional[str] = None,
    mark_pii: bool = False,
):
    """Build a CreateTableRequest representing one EP Schema + version.

    Wave 3 (#52). Promotes EP Schemas from a Topic sub-property to
    first-class OM entities. Schema fields are converted to Table columns
    (recursive STRUCT for records), the raw schemaText is also preserved as
    a markdown CP for human review when the parser declines (e.g. XSD).
    Lineage Table -> Topic for each consuming Topic is emitted by the
    connector separately.
    """
    try:
        from metadata.generated.schema.api.data.createTable import (
            CreateTableRequest,
        )
    except Exception:  # pragma: no cover
        logger.warning("OM Table entity not importable; skipping schema")
        return None
    from .property_keys import (
        CP_SCHEMA_CONTENT,
        CP_SCHEMA_ID,
        CP_SCHEMA_TYPE,
    )

    schema_name = schema.get("name") or schema.get("id") or "unknown-schema"
    version_str = str(schema_version.get("version") or "1.0.0")
    fmt = _normalize_schema_format(
        schema.get("schemaType") or schema.get("contentType")
    )
    text = schema_version.get("content") or ""

    columns = _build_table_columns_from_text(fmt, text, mark_pii=mark_pii)

    raw_state = (
        str(schema_version.get("stateId") or "").strip()
        or str(schema_version.get("state") or "").strip()
    )
    state_human = _STATE_HUMAN.get(raw_state) or _STATE_HUMAN.get(
        raw_state.upper()
    ) or "Unknown"

    description = "\n\n".join(
        p for p in (
            schema.get("description") or "",
            f"Solace Event Portal schema `{schema_name}` v{version_str} "
            f"(state `{state_human}`).",
        ) if p
    )

    urls = ep_urls or EpUrls()
    domain_id = domain.get("id")
    domain_name = domain.get("name")
    schema_id = schema.get("id")
    sv_id = schema_version.get("id")

    extension: Dict[str, Any] = {
        CP_EP_SCHEMA: _md_link(
            f"{schema_name} v{version_str}",
            urls.schema_version(domain_id, domain_name, schema_id, sv_id),
        ),
        CP_SCHEMA_ID: schema_id,
        CP_SCHEMA_VERSION_ID: sv_id,
        CP_SCHEMA_TYPE: fmt,
        CP_STATE: state_human if state_human != "Unknown" else None,
        CP_STATE_CHANGED_AT: schema_version.get("updatedTime"),
        CP_SCHEMA_CONTENT: _wrap_schema_text_markdown(text, fmt) if text else None,
    }
    if is_latest_version is not None:
        extension[CP_IS_LATEST_VERSION] = "true" if is_latest_version else "false"
    extension = {k: v for k, v in extension.items() if v is not None}

    request = CreateTableRequest(
        name=sanitize(f"{schema_name}_v{version_str}"),
        displayName=f"{schema_name} v{version_str}",
        description=description or None,
        databaseSchema=domain_database_schema_fqn(
            domain_name or "unknown-domain", service_name=service_name
        ),
        columns=columns,
    )
    if extension and hasattr(request, "extension"):
        request.extension = _as_extension(extension)
    return request


def _wrap_schema_text_markdown(text: str, fmt: str) -> str:
    """Wrap raw schema text in a markdown fenced code block."""
    lang = {"JSON": "json", "AVRO": "json", "PROTOBUF": "protobuf"}.get(fmt, "")
    # Trim very long bodies so the OM custom-property editor stays usable.
    snippet = text if len(text) < 8000 else text[:8000] + "\n... (truncated)"
    return f"```{lang}\n{snippet}\n```"


def _build_table_columns_from_text(
    fmt: str, schema_text: str, *, mark_pii: bool = False
) -> List[Any]:
    """Parse a schema payload to SchemaField[], then convert to Column[].

    Returns ``[]`` on parse failure or unsupported format (XSD/XML) -- the
    Table still ingests with its name + raw schema content in the
    `eventPortalSchemaContent` CP, just without per-column breakdown.
    """
    try:
        from .schema_parsers import parse_fields
    except Exception:  # pragma: no cover
        return []
    fields = parse_fields(fmt, schema_text, mark_pii=mark_pii)
    if not fields:
        # Provide a sentinel single-column table so OM still shows the
        # schema as a tangible entity (TableType requires at least 1 col
        # on some OM versions; a single 'rawSchema' col is the cheapest
        # fallback).
        return _sentinel_raw_schema_column()
    cols = []
    for f in fields:
        col = _field_model_to_column(f)
        if col is not None:
            cols.append(col)
    if not cols:
        return _sentinel_raw_schema_column()
    return cols


def _sentinel_raw_schema_column() -> List[Any]:
    try:
        from metadata.generated.schema.entity.data.table import (
            Column,
            DataType,
        )
    except Exception:  # pragma: no cover
        return []
    try:
        return [
            Column(
                name="rawSchema",
                dataType=DataType.STRING,
                dataTypeDisplay="raw schema (unparsed)",
                description=(
                    "Schema body is preserved in the eventPortalSchemaContent "
                    "custom property. Field-level parsing was skipped (format "
                    "not supported or parse error)."
                ),
            )
        ]
    except Exception:  # pragma: no cover
        return []


# Map an OM SchemaField.dataType string to a Table Column DataType enum
# member. Defaults to UNKNOWN for anything we don't recognise.
_FIELD_TO_COLUMN_DATA_TYPE: Dict[str, str] = {
    "STRING": "STRING",
    "INT": "INT",
    "LONG": "BIGINT",
    "BIGINT": "BIGINT",
    "FLOAT": "FLOAT",
    "DOUBLE": "DOUBLE",
    "BOOLEAN": "BOOLEAN",
    "BYTES": "BINARY",
    "BINARY": "BINARY",
    "ENUM": "ENUM",
    "ARRAY": "ARRAY",
    "MAP": "MAP",
    "RECORD": "STRUCT",
    "STRUCT": "STRUCT",
    "UNION": "UNION",
    "NULL": "NULL",
    "DATE": "DATE",
    "TIME": "TIME",
    "TIMESTAMP": "TIMESTAMP",
    "DECIMAL": "DECIMAL",
    "UUID": "UUID",
}


def _field_model_to_column(field: Any):
    """Recursively translate one OM SchemaField (FieldModel) to a Table Column."""
    try:
        from metadata.generated.schema.entity.data.table import (
            Column,
            DataType,
        )
    except Exception:  # pragma: no cover
        return None
    name = _field_name(field)
    if not name:
        return None
    # SchemaField.dataType is itself an enum on the schema-side; we read
    # its string form and look up the equivalent table-side enum.
    raw_dt = getattr(field, "dataType", None)
    dt_str = str(getattr(raw_dt, "value", raw_dt) or "").upper()
    target = _FIELD_TO_COLUMN_DATA_TYPE.get(dt_str, "UNKNOWN")
    try:
        col_data_type = getattr(DataType, target)
    except Exception:
        col_data_type = DataType.UNKNOWN
    children_raw = getattr(field, "children", None) or []
    children = []
    for c in children_raw:
        cc = _field_model_to_column(c)
        if cc is not None:
            children.append(cc)
    try:
        return Column(
            name=name,
            dataType=col_data_type,
            dataTypeDisplay=getattr(field, "dataTypeDisplay", None),
            description=getattr(field, "description", None),
            children=children or None,
        )
    except Exception:  # pragma: no cover
        return None


def _field_name(field: Any) -> str:
    """Mirror of `schema_parsers._field_name` -- unwrap RootModel name."""
    n = getattr(field, "name", None)
    if n is None:
        return ""
    return str(getattr(n, "root", getattr(n, "__root__", n)))


# --------------------------------------------------------- Topic-tree (#53)


def topic_segment_to_container_request(
    *,
    segment: str,
    depth: int,
    segment_path: List[str],
    parent_fqn: Optional[str] = None,
    service_name: Optional[str] = None,
):
    """Build a CreateContainerRequest for one topic-address segment.

    Wave 3 (#53). The full topic-address tree is materialised as nested
    OM Containers under the synthetic StorageService
    ``solace-event-portal-topic-tree``. Variable segments
    (``{region}``, ``{orderId}``) are kept verbatim in the displayName,
    but sanitised to ``_region_`` in the Container name so the OM FQN
    stays valid.

    ``segment_path`` is the full chain leading to this segment
    (e.g. ``["orders", "{region}", "created"]`` for the leaf of
    ``orders/{region}/created``). ``depth`` mirrors len(segment_path)
    for symmetry.
    """
    try:
        from metadata.generated.schema.api.data.createContainer import (
            CreateContainerRequest,
        )
    except Exception:  # pragma: no cover
        logger.warning("OM Container entity not importable; skipping segment")
        return None
    from .property_keys import (
        CP_TOPIC_SEGMENT,
        CP_TOPIC_SEGMENT_DEPTH,
        CP_TOPIC_SEGMENT_PATH,
        TOPIC_TREE_STORAGE_SERVICE_NAME,
    )

    service = service_name or TOPIC_TREE_STORAGE_SERVICE_NAME
    name = sanitize(_variable_to_safe_name(segment))
    full_path = "/".join(segment_path)
    description = (
        f"Solace topic-address segment `{segment}` at depth {depth} "
        f"(full path: `{full_path}`). Auto-materialised from the Event "
        f"Portal topic-address hierarchy."
    )
    extension = {
        CP_TOPIC_SEGMENT: segment,
        CP_TOPIC_SEGMENT_PATH: full_path,
        CP_TOPIC_SEGMENT_DEPTH: str(depth),
    }
    extension = {k: v for k, v in extension.items() if v is not None}

    request = CreateContainerRequest(
        name=name,
        displayName=segment,
        description=description,
        service=service,
    )
    if parent_fqn and hasattr(request, "parent"):
        try:
            from metadata.generated.schema.type.entityReference import (
                EntityReference,
            )
            request.parent = EntityReference(
                fullyQualifiedName=parent_fqn, type="container",
            )
        except Exception:  # pragma: no cover
            pass
    if extension and hasattr(request, "extension"):
        request.extension = _as_extension(extension)
    return request


def topic_segment_container_fqn(
    segment_path: List[str], service_name: Optional[str] = None
) -> str:
    """FQN of a topic-tree segment Container under the synthetic StorageService.

    The FQN composes one quoted segment per level so '.' inside a topic
    name (rare but legal in Solace) does not collide with the OM FQN
    separator.
    """
    from .property_keys import TOPIC_TREE_STORAGE_SERVICE_NAME
    parts = [service_name or TOPIC_TREE_STORAGE_SERVICE_NAME]
    for seg in segment_path:
        parts.append(_quote_if_dotted(sanitize(_variable_to_safe_name(seg))))
    return ".".join(parts)


def _variable_to_safe_name(segment: str) -> str:
    """Translate ``{region}`` -> ``_region_`` so the name is a valid identifier."""
    if not segment:
        return "_"
    if segment.startswith("{") and segment.endswith("}"):
        return f"_{segment[1:-1]}_"
    return segment


# Lowercase / id-based EP state values mapped back to the human-readable
# tag suffix. Used by the schema mapper since EP returns numeric state IDs.
_STATE_HUMAN: Dict[str, str] = {
    "1": "Draft",
    "2": "Released",
    "3": "Deprecated",
    "4": "Retired",
    "DRAFT": "Draft",
    "RELEASED": "Released",
    "DEPRECATED": "Deprecated",
    "RETIRED": "Retired",
}


def _render_eapp_plans_markdown(plans: List[Dict[str, Any]]) -> Optional[str]:
    """Render EAPP version ``plans[]`` as a small markdown table for the
    DataProduct.extension custom property."""
    if not plans:
        return None
    rows = ["| Plan | Class of Service | Description |", "| --- | --- | --- |"]
    for p in plans:
        pname = p.get("name") or "?"
        cos = p.get("solaceClassOfServicePolicy") or {}
        cos_kind = cos.get("classOfService") or cos.get("queueType") or "-"
        desc = (p.get("description") or "").replace("|", "/")[:120]
        rows.append(f"| {pname} | {cos_kind} | {desc} |")
    return "\n".join(rows)


# app_pipeline_fqn moved to `.fqn`; re-export below for back-compat.
from .fqn import app_pipeline_fqn, app_pipeline_name  # noqa: F401,E402


def app_to_pipeline_request(
    *, domain: Dict[str, Any], app: Dict[str, Any], app_version: Dict[str, Any],
    owner: Any = None,
    ep_urls: Optional[EpUrls] = None,
    attach_to_domain: bool = True,
    is_latest_version: Optional[bool] = None,
    custom_attribute_tags: Optional[List[TagLabel]] = None,
    service_name: Optional[str] = None,
    contains_pii: bool = False,
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
    )

    service = service_name or APP_PIPELINE_SERVICE_NAME
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
    # Wave 1 (#43): merge auto-discovered EP CA tags from connector.
    if custom_attribute_tags:
        tags.extend(custom_attribute_tags)
    # Wave 5 (#62): PII compliance tag when the connector detected a signal.
    if contains_pii:
        tags.append(pii_tag())
    domain_id = domain.get("id")
    domain_name = domain.get("name")
    app_id = app.get("id")
    app_version_id = app_version.get("id")
    urls = ep_urls or EpUrls()
    extension = {
        CP_EP_APPLICATION: _md_link(
            f"{app_name} v{version_str}",
            urls.application_version(domain_id, domain_name, app_id, app_version_id),
        ),
        CP_EP_APP_DOMAIN: _md_link(domain_name, urls.domain(domain_id, domain_name)),
        # Wave 1 (#54): see event_to_topic_request for rationale.
        CP_IS_LATEST_VERSION: (
            "true" if is_latest_version else "false"
        ) if is_latest_version is not None else None,
        # Wave 5 (#62): PII flag mirrors the EventPortalCompliance.PII tag.
        CP_CONTAINS_PII: "true" if contains_pii else None,
    }
    extension = {k: v for k, v in extension.items() if v is not None}

    request = CreatePipelineRequest(
        name=app_pipeline_name(app_name, version_str),
        displayName=f"{app_name} v{version_str}",
        description=description,
        service=service,
        tags=tags,
    )
    # Wave 4 (#56): sourceUrl points OM users at the downloadable EP
    # AsyncAPI document for this application version. The endpoint
    # requires a valid EP bearer token; OM still renders it as a
    # clickable "source" link on the Pipeline page.
    async_api_url = urls.async_api(app_version_id)
    if async_api_url and hasattr(request, "sourceUrl"):
        request.sourceUrl = _as_source_url(async_api_url)
    if extension and hasattr(request, "extension"):
        request.extension = _as_extension(extension)
    if attach_to_domain:
        dref = _domain_ref(domain.get("name"))
        if dref is not None:
            # OM 1.9+ rename: domain -> domains (List). See event_to_topic_request.
            if hasattr(request, "domains"):
                request.domains = [dref]
            elif hasattr(request, "domain"):
                request.domain = dref
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

    # OM 1.11+ effectively requires LineageDetails.source so the run-report UI
    # can group edges by origin. Tag every edge we emit as Manual (we are the
    # explicit caller, not a query-history parser).
    lineage_source = None
    try:
        from metadata.generated.schema.type.entityLineage import LineageSource
        lineage_source = LineageSource.Manual
    except Exception:  # pragma: no cover - pre-1.11 SDK without the enum
        pass

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

    details_kwargs = {
        "description": f"Solace Event Portal: {app_name} {direction}",
    }
    if lineage_source is not None:
        details_kwargs["source"] = lineage_source

    return AddLineageRequest(
        edge=EntitiesEdge(
            fromEntity=EntityReference(id=from_id, type=from_type),
            toEntity=EntityReference(id=to_id, type=to_type),
            lineageDetails=LineageDetails(**details_kwargs),
        )
    )


def pipeline_to_pipeline_lineage_request(
    *,
    source_pipeline_id: str,
    dest_pipeline_id: str,
    source_app_name: str = "",
    dest_app_name: str = "",
):
    """Build an AddLineageRequest between two Pipelines.

    Wave 2 (#59): emitted from EP's
    ``inboundApplicationVersionAssociations`` /
    ``outboundApplicationVersionAssociations`` on each EP application
    version. The "linked applications" graph is the closest analogue to
    a producer / consumer chain Event Portal exposes for non-event
    couplings (file drops, REST calls, shared databases, etc.).
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
        logger.warning(
            "OM Lineage SDK not importable; skipping linked-app lineage emit"
        )
        return None

    lineage_source = None
    try:
        from metadata.generated.schema.type.entityLineage import LineageSource
        lineage_source = LineageSource.Manual
    except Exception:  # pragma: no cover - pre-1.11 SDK without the enum
        pass

    label = " -> ".join(
        x for x in [source_app_name, dest_app_name] if x
    ) or "EP linked applications"
    details_kwargs = {
        "description": f"Solace Event Portal Linked Applications: {label}",
    }
    if lineage_source is not None:
        details_kwargs["source"] = lineage_source

    return AddLineageRequest(
        edge=EntitiesEdge(
            fromEntity=EntityReference(id=source_pipeline_id, type="pipeline"),
            toEntity=EntityReference(id=dest_pipeline_id, type="pipeline"),
            lineageDetails=LineageDetails(**details_kwargs),
        )
    )
