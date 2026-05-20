"""Helpers shared between the format-specific parsers.

The OM SDK is imported lazily because the parser modules must remain
loadable in slim test environments. Tests assert structural shape
(name / data_type / description / children) so behaviour is verifiable
without `openmetadata-ingestion` installed.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional

_INVALID_FIELD_NAME = re.compile(r"[^A-Za-z0-9_]")


def sanitize_name(name: Optional[str]) -> str:
    """Make `name` safe for OM SchemaField.FieldName."""
    base = (name or "field").strip() or "field"
    return _INVALID_FIELD_NAME.sub("_", base)


# OM data-type vocabulary used when the SDK is available
# (metadata.generated.schema.type.schema.DataTypeTopic). Anything we
# can't map cleanly degrades to UNKNOWN -- still a valid enum value.
_DATA_TYPE_ALIASES = {
    "STRING": "STRING",
    "STR": "STRING",
    "INT": "INT",
    "INTEGER": "INT",
    "LONG": "LONG",
    "BIGINT": "LONG",
    "FLOAT": "FLOAT",
    "DOUBLE": "DOUBLE",
    "NUMBER": "DOUBLE",
    "BOOL": "BOOLEAN",
    "BOOLEAN": "BOOLEAN",
    "BYTES": "BYTES",
    "DATE": "DATE",
    "TIME": "TIME",
    "TIMESTAMP": "TIMESTAMP",
    "TIMESTAMPZ": "TIMESTAMPZ",
    "ARRAY": "ARRAY",
    "MAP": "MAP",
    "ENUM": "ENUM",
    "UNION": "UNION",
    "FIXED": "FIXED",
    "RECORD": "RECORD",
    "OBJECT": "RECORD",
    "NULL": "NULL",
}


def _coerce_data_type(label: str):
    """Map a free-form type label to OM's DataTypeTopic enum.

    Returns the enum value if the SDK is available, otherwise the
    uppercased string label (for tests in slim environments).
    """
    key = (label or "UNKNOWN").upper()
    canonical = _DATA_TYPE_ALIASES.get(key, "UNKNOWN")
    try:
        from metadata.generated.schema.type.schema import DataTypeTopic

        return DataTypeTopic(canonical)
    except Exception:
        return canonical


def safe_field(
    *,
    name: str,
    data_type: str,
    description: Optional[str] = None,
    children: Optional[List[Any]] = None,
):
    """Build an OM `FieldModel` if the SDK is available, else a dict.

    `FieldModel` is what OM 1.6+ calls what used to be `SchemaField`.
    The dict fallback mirrors the SDK's serialized form so tests can be
    run against either representation.
    """
    try:
        from metadata.generated.schema.type.schema import FieldModel, FieldName

        return FieldModel(
            name=FieldName(root=name),
            dataType=_coerce_data_type(data_type),
            description=description,
            children=children or None,
        )
    except Exception:
        return {
            "name": name,
            "dataType": (data_type or "UNKNOWN").upper(),
            "description": description,
            "children": children or [],
        }
