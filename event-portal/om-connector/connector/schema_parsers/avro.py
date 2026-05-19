"""Avro -> OM SchemaField parser.

Handles:
  * Primitive types and complex types (record, enum, array, map, union).
  * Nested records (recursion).
  * Named-type references within the same document.
  * Union types ["null", "T"] -> reported as T with required=false.

Avro logical types (decimal, date, timestamp-millis, uuid, ...) are
reflected as their underlying primitive type but mentioned in the field
description so analysts don't lose the semantic.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .util import safe_field, sanitize_name

logger = logging.getLogger(__name__)


_PRIM_MAP = {
    "null": "NULL",
    "boolean": "BOOLEAN",
    "int": "INTEGER",
    "long": "LONG",
    "float": "FLOAT",
    "double": "DOUBLE",
    "bytes": "BYTES",
    "string": "STRING",
}


def parse_fields(schema_text: str):
    if not schema_text:
        return []
    try:
        body = json.loads(schema_text) if isinstance(schema_text, str) else schema_text
    except (TypeError, ValueError):
        logger.warning("Avro content is not valid JSON")
        return []

    named_types: Dict[str, Dict[str, Any]] = {}
    _collect_named_types(body, named_types)

    if not isinstance(body, dict):
        return []
    if body.get("type") != "record":
        return []
    return [_field(f, named_types) for f in body.get("fields") or []]


def _field(field: Dict[str, Any], named: Dict[str, Dict[str, Any]]):
    name = sanitize_name(field.get("name", "field"))
    dtype, children, suffix = _type_of(field.get("type"), named)
    description_parts: List[str] = []
    if field.get("doc"):
        description_parts.append(field["doc"])
    if suffix:
        description_parts.append(suffix)
    if "default" in field:
        description_parts.append(f"default={field['default']}")
    description = " | ".join(description_parts) or None
    return safe_field(
        name=name,
        data_type=dtype,
        description=description,
        children=children,
    )


def _type_of(t: Any, named: Dict[str, Dict[str, Any]]):
    """Return (dtype, children, suffix). suffix appended to description."""
    if isinstance(t, str):
        prim = _PRIM_MAP.get(t)
        if prim:
            return prim, None, ""
        # Named-type reference
        if t in named:
            return _type_of(named[t], named)
        return t.upper(), None, ""

    if isinstance(t, list):
        non_null = [x for x in t if x != "null"]
        nullable = len(non_null) != len(t)
        if not non_null:
            return "NULL", None, ""
        dtype, children, suffix = _type_of(non_null[0], named)
        if nullable:
            suffix = (suffix + " ").strip() + "(nullable)" if not suffix.endswith("(nullable)") else suffix
        return dtype, children, suffix.strip()

    if isinstance(t, dict):
        kind = t.get("type")
        logical = t.get("logicalType")
        if kind == "record":
            children = [_field(f, named) for f in t.get("fields") or []]
            return "RECORD", children, ""
        if kind == "enum":
            symbols = ", ".join(t.get("symbols") or [])
            return "ENUM", None, f"symbols=[{symbols}]"
        if kind == "array":
            inner_dtype, inner_children, _ = _type_of(t.get("items"), named)
            return "ARRAY", [
                safe_field(
                    name="item",
                    data_type=inner_dtype,
                    description="Array element",
                    children=inner_children,
                )
            ], ""
        if kind == "map":
            inner_dtype, inner_children, _ = _type_of(t.get("values"), named)
            return "MAP", [
                safe_field(
                    name="value",
                    data_type=inner_dtype,
                    description="Map value",
                    children=inner_children,
                )
            ], ""
        if kind == "fixed":
            return "BYTES", None, f"fixed[size={t.get('size')}]"
        # Primitive wrapped in dict -> e.g. {"type":"int","logicalType":"date"}
        prim = _PRIM_MAP.get(str(kind))
        if prim:
            suffix = f"logicalType={logical}" if logical else ""
            return prim, None, suffix
        return "UNKNOWN", None, ""

    return "UNKNOWN", None, ""


def _collect_named_types(node: Any, into: Dict[str, Dict[str, Any]]) -> None:
    """Index `name`-bearing records / enums / fixed for later $ref resolution."""
    if isinstance(node, dict):
        if node.get("type") in ("record", "enum", "fixed") and node.get("name"):
            into[node["name"]] = node
        for v in node.values():
            _collect_named_types(v, into)
    elif isinstance(node, list):
        for item in node:
            _collect_named_types(item, into)
