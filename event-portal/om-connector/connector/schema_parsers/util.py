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


def safe_field(
    *,
    name: str,
    data_type: str,
    description: Optional[str] = None,
    children: Optional[List[Any]] = None,
):
    """Build an OM `SchemaField` if the SDK is available, else a dict.

    The dict shape mirrors the SDK's serialized form so tests can be run
    against either representation.
    """
    try:
        from metadata.generated.schema.type.schema import FieldName, SchemaField

        return SchemaField(
            name=FieldName(__root__=name),
            dataType=data_type,
            description=description,
            children=children or None,
        )
    except Exception:
        return {
            "name": name,
            "dataType": data_type,
            "description": description,
            "children": children or [],
        }
