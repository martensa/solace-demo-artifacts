"""Schema-field parser dispatcher.

Wave 1 (#64) replaced the home-grown per-format walkers with thin
delegates to OpenMetadata's built-in parsers under
``metadata.parsers.*``. Upstream's parsers carry years of field-shape
fidelity work (nested records, Avro unions, JSON-Schema ``$ref``
resolution, Debezium ``oneOf`` nullable, Protobuf descriptors) that we
were re-implementing badly.

Public API kept stable for `connector.mappers`:

    parse_fields(schema_format: str, schema_text: str) -> List[FieldModel]

Returns OM ``FieldModel`` objects ready to plug into
``Topic.messageSchema.schemaFields``. Unknown / unparseable schemas
return an empty list so the Topic still ingests with its raw schemaText
preserved.

Beat-Kafka layer (#67 point 5): OM's parsers silently drop Avro
``logicalType`` (decimal/date/timestamp-millis/uuid) and JSON-Schema
``format`` (date-time/uuid/email). We post-process the parsed field
tree against the source schema text to re-attach these as
``dataTypeDisplay`` strings -- a small accuracy win that upstream's
Kafka connector does not have.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------- public dispatch


def parse_fields(schema_format: str, schema_text: str) -> List[Any]:
    """Dispatch to the OM parser for ``schema_format``.

    Recognised formats (case-insensitive): ``JSON``, ``AVRO``,
    ``PROTOBUF``. Anything else (including ``XSD`` / ``XML`` -- OM has no
    parser for those) returns an empty list.

    Any parser exception is logged and swallowed; the caller still gets
    an empty list and the connector keeps emitting the Topic with the
    raw ``schemaText`` attached.
    """
    fmt = (schema_format or "").strip().upper()
    if not schema_text:
        return []

    parsers = {
        "JSON": _parse_json,
        "AVRO": _parse_avro,
        "PROTOBUF": _parse_protobuf,
    }
    fn = parsers.get(fmt)
    if fn is None:
        logger.debug(
            "No OM parser registered for schema format %s; returning []",
            fmt or "(empty)",
        )
        return []

    try:
        fields = fn(schema_text)
    except Exception as exc:  # pragma: no cover - parse failure is non-fatal
        logger.warning(
            "Schema parse failed for format %s: %s; returning [] so the"
            " Topic still ingests with raw schemaText",
            fmt, exc,
        )
        return []

    # Beat-Kafka: rewrite logical types into dataTypeDisplay where OM's
    # parser dropped them. Failures here are also non-fatal -- the parsed
    # tree is still usable without the enrichment.
    try:
        if fmt == "AVRO":
            _enrich_avro_logical_types(fields, schema_text)
        elif fmt == "JSON":
            _enrich_json_schema_format(fields, schema_text)
    except Exception as exc:  # pragma: no cover
        logger.debug(
            "logical-type enrichment failed for %s: %s; continuing", fmt, exc
        )

    return fields


# ------------------------------------------------------- OM parser delegates


def _parse_json(schema_text: str) -> List[Any]:
    from metadata.parsers.json_schema_parser import parse_json_schema

    return parse_json_schema(schema_text) or []


def _parse_avro(schema_text: str) -> List[Any]:
    from metadata.parsers.avro_parser import parse_avro_schema

    return parse_avro_schema(schema_text) or []


_PROTOBUF_MESSAGE_RE = re.compile(r"^\s*message\s+(\w+)\s*\{", re.MULTILINE)


def _parse_protobuf(schema_text: str) -> List[Any]:
    # Protobuf parsing requires the `grpc_tools.protoc` toolchain to be
    # available; OM's parser writes the .proto to /tmp/protobuf_openmetadata/
    # then compiles + reflects. The OM parser config requires a
    # ``schema_name`` matching the message it should reflect on. We
    # auto-detect by scanning the source for the first top-level
    # ``message X { ... }`` declaration; otherwise reflection fails with
    # ``module 'topic_pb2' has no attribute 'Topic'``.
    from metadata.parsers.protobuf_parser import ProtobufParser, ProtobufParserConfig

    match = _PROTOBUF_MESSAGE_RE.search(schema_text)
    schema_name = match.group(1) if match else "Topic"
    config = ProtobufParserConfig(schema_name=schema_name, schema_text=schema_text)
    return ProtobufParser(config=config).parse_protobuf_schema() or []


# ------------------------------------------------- logical type enrichment


_AVRO_LOGICAL_TYPE_DISPLAY: Dict[str, str] = {
    # Logical type name in Avro -> human-readable suffix appended to dataType.
    "decimal": "decimal",
    "date": "date",
    "time-millis": "time-millis",
    "time-micros": "time-micros",
    "timestamp-millis": "timestamp-millis",
    "timestamp-micros": "timestamp-micros",
    "local-timestamp-millis": "local-timestamp-millis",
    "local-timestamp-micros": "local-timestamp-micros",
    "duration": "duration",
    "uuid": "uuid",
}


def _enrich_avro_logical_types(fields: Iterable[Any], schema_text: str) -> None:
    """Walk the Avro source + parsed tree in parallel, copying
    ``logicalType`` into ``dataTypeDisplay``.

    The OM Avro parser preserves field NAMES and ORDER but not the
    underlying `{"type": {...logicalType...}}` annotation; we re-read
    the source JSON to recover it. Names are matched by string equality;
    if the source structure diverges (unions, refs) we silently skip.
    """
    try:
        source = json.loads(schema_text)
    except (json.JSONDecodeError, ValueError):
        return
    name_to_logical = _collect_avro_logical_types(source)
    if name_to_logical:
        _apply_display_by_name(fields, name_to_logical)


def _collect_avro_logical_types(node: Any) -> Dict[str, str]:
    """Walk an Avro schema dict and return ``{field_name: logical_type}``."""
    result: Dict[str, str] = {}

    def visit(n: Any) -> None:
        if isinstance(n, dict):
            # A field entry has a 'name' and a 'type'; the type may be
            # a string, a dict, or a union list.
            if "name" in n and "type" in n:
                logical = _avro_logical_type_of(n.get("type"))
                if logical:
                    result[n["name"]] = logical
            for v in n.values():
                visit(v)
        elif isinstance(n, list):
            for item in n:
                visit(item)

    visit(node)
    return result


def _avro_logical_type_of(type_node: Any) -> Optional[str]:
    """Return the Avro ``logicalType`` string for ``type_node`` if any."""
    if isinstance(type_node, dict):
        lt = type_node.get("logicalType")
        if isinstance(lt, str) and lt in _AVRO_LOGICAL_TYPE_DISPLAY:
            return _AVRO_LOGICAL_TYPE_DISPLAY[lt]
    elif isinstance(type_node, list):
        # Union -- pick the first non-null branch with a logicalType.
        for branch in type_node:
            lt = _avro_logical_type_of(branch)
            if lt:
                return lt
    return None


_JSON_FORMAT_DISPLAY: Dict[str, str] = {
    "date-time": "date-time",
    "date": "date",
    "time": "time",
    "duration": "duration",
    "email": "email",
    "idn-email": "idn-email",
    "hostname": "hostname",
    "ipv4": "ipv4",
    "ipv6": "ipv6",
    "uri": "uri",
    "uri-reference": "uri-reference",
    "uuid": "uuid",
}


def _enrich_json_schema_format(fields: Iterable[Any], schema_text: str) -> None:
    """Walk JSON-Schema source + parsed tree, copying ``format`` annotations
    into ``dataTypeDisplay``."""
    try:
        source = json.loads(schema_text)
    except (json.JSONDecodeError, ValueError):
        return
    name_to_format = _collect_json_schema_formats(source)
    if name_to_format:
        _apply_display_by_name(fields, name_to_format)


def _collect_json_schema_formats(node: Any) -> Dict[str, str]:
    """Walk a JSON-Schema dict and return ``{property_name: format}``."""
    result: Dict[str, str] = {}

    def visit_properties(props: Any) -> None:
        if not isinstance(props, dict):
            return
        for prop_name, prop_def in props.items():
            if not isinstance(prop_def, dict):
                continue
            fmt = prop_def.get("format")
            if isinstance(fmt, str) and fmt in _JSON_FORMAT_DISPLAY:
                result[prop_name] = _JSON_FORMAT_DISPLAY[fmt]
            # Recurse into nested objects + arrays
            if prop_def.get("type") == "object":
                visit_properties(prop_def.get("properties") or {})
            items = prop_def.get("items")
            if isinstance(items, dict):
                visit_properties(items.get("properties") or {})

    if isinstance(node, dict):
        visit_properties(node.get("properties") or {})
        # JSON-Schema can also have `definitions` / `$defs` we want to
        # touch, in case parser inlines them.
        for defs_key in ("definitions", "$defs"):
            defs = node.get(defs_key)
            if isinstance(defs, dict):
                for d in defs.values():
                    if isinstance(d, dict):
                        visit_properties(d.get("properties") or {})
    return result


def _apply_display_by_name(
    fields: Iterable[Any], name_to_display: Dict[str, str]
) -> None:
    """Walk parsed ``FieldModel``s and merge logical-type / format
    annotations into ``dataTypeDisplay``.

    OM's Avro parser pre-fills ``dataTypeDisplay`` with the bare type
    name (e.g. ``"long"``); JSON-Schema's parser leaves it ``None``.
    For Beat-Kafka fidelity we surface the richer logical-type by
    composing ``"{base}<{logical}>"`` (e.g. ``"long<timestamp-millis>"``)
    so OM users immediately see the semantic type next to the wire
    type.
    """
    if not name_to_display:
        return
    stack: List[Any] = list(fields)
    visited = 0
    while stack and visited < 10000:  # safety against pathological cycles
        f = stack.pop()
        visited += 1
        name = _field_name(f)
        if name in name_to_display:
            logical = name_to_display[name]
            existing = getattr(f, "dataTypeDisplay", None)
            if existing and existing != logical:
                new_display = f"{existing}<{logical}>"
            else:
                new_display = logical
            try:
                f.dataTypeDisplay = new_display
            except Exception:  # pragma: no cover
                pass
        children = getattr(f, "children", None) or []
        stack.extend(children)


def _field_name(field: Any) -> str:
    """Extract a ``FieldModel.name`` as a plain string.

    OM 1.11 wraps it in ``FieldName(RootModel)`` exposing ``.root``;
    older SDKs may use ``__root__`` or a plain string.
    """
    n = getattr(field, "name", None)
    if n is None:
        return ""
    return str(getattr(n, "root", getattr(n, "__root__", n)))
