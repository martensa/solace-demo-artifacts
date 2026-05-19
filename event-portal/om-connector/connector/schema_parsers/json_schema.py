"""JSON Schema -> OM SchemaField parser.

Walks `properties` recursively, resolves intra-document `$ref` pointers,
and populates `children` on object and array fields.

Limitations:
  * External `$ref` (other files / URLs) are not fetched.
  * `oneOf` / `anyOf` / `allOf` are unioned into a single field whose
    dataType reflects the first variant. The full schema text is still
    preserved on the Topic, so deeper modelling can be done downstream.
  * `definitions` (Draft-07) and `$defs` (Draft 2019-09+) are both
    searched for $ref resolution.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .util import safe_field, sanitize_name

logger = logging.getLogger(__name__)


# JSON Schema 'type' -> OM SchemaField.dataType label (uppercase)
_TYPE_MAP = {
    "string": "STRING",
    "integer": "INTEGER",
    "number": "NUMBER",
    "boolean": "BOOLEAN",
    "object": "RECORD",
    "array": "ARRAY",
    "null": "NULL",
}


def parse_fields(schema_text: str):
    if not schema_text:
        return []
    try:
        body = json.loads(schema_text) if isinstance(schema_text, str) else schema_text
    except (TypeError, ValueError):
        logger.warning("JSON Schema content is not valid JSON")
        return []
    if not isinstance(body, dict):
        return []
    root_doc = body  # used for $ref resolution
    properties = body.get("properties") or {}
    required = set(body.get("required") or [])
    return [_field(name, body, root_doc, name in required) for name, body in properties.items()]


def _field(name: str, prop: Dict[str, Any], root: Dict[str, Any], required: bool):
    prop = _resolve_ref(prop, root)
    dtype, children = _type_of(prop, root)
    description = prop.get("description")
    if required:
        description = (description or "") + ("" if not description else " ") + "(required)"
    return safe_field(
        name=sanitize_name(name),
        data_type=dtype,
        description=description or None,
        children=children,
    )


def _type_of(prop: Dict[str, Any], root: Dict[str, Any]):
    # Combinators -> union: report the first variant's type for OM,
    # but recurse into its properties so children are visible.
    for combinator in ("oneOf", "anyOf", "allOf"):
        if combinator in prop:
            variants = prop[combinator] or []
            if variants:
                resolved = _resolve_ref(variants[0], root)
                return _type_of(resolved, root)

    t = prop.get("type")
    # `type` can be a list ["string","null"] - pick the first non-null
    if isinstance(t, list):
        non_null = [x for x in t if x != "null"]
        t = non_null[0] if non_null else "null"
    dtype = _TYPE_MAP.get(str(t).lower(), "UNKNOWN")

    children: Optional[List[Any]] = None
    if dtype == "RECORD":
        nested = prop.get("properties") or {}
        nested_required = set(prop.get("required") or [])
        children = [
            _field(n, b, root, n in nested_required) for n, b in nested.items()
        ]
    elif dtype == "ARRAY":
        items = prop.get("items") or {}
        items = _resolve_ref(items, root)
        inner_type, inner_children = _type_of(items, root)
        children = [
            safe_field(
                name="item",
                data_type=inner_type,
                description="Array element",
                children=inner_children,
            )
        ]
    return dtype, children


def _resolve_ref(obj: Any, root: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        return {}
    ref = obj.get("$ref")
    if not ref or not isinstance(ref, str):
        return obj
    if not ref.startswith("#/"):
        # External refs are not followed.
        return obj
    parts = ref.lstrip("#/").split("/")
    cur: Any = root
    for p in parts:
        if not isinstance(cur, dict) or p not in cur:
            return obj
        cur = cur[p]
    return cur if isinstance(cur, dict) else obj
