"""Schema parsers for Event Portal payload formats.

One module per format. Each module exposes:

    parse_fields(schema_text: str) -> List[SchemaField]

returning a list of OM `SchemaField`s with nested `children` populated
where the source format supports nesting (JSON Schema, Avro records,
Protobuf messages). The public `parse_fields(format, text)` dispatcher
picks the right module by format name.

Lazy imports of the OM SDK keep the module loadable in slim test
environments.
"""
from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)


def parse_fields(schema_format: str, schema_text: str) -> List["SchemaField"]:  # noqa: F821
    """Dispatch to a per-format parser.

    Unknown formats return an empty list rather than raising so the rest
    of the pipeline can still surface the Topic.
    """
    fmt = (schema_format or "").upper()
    if fmt == "JSON":
        from .json_schema import parse_fields as p
        return p(schema_text)
    if fmt == "AVRO":
        from .avro import parse_fields as p
        return p(schema_text)
    if fmt == "PROTOBUF":
        from .protobuf import parse_fields as p
        return p(schema_text)
    if fmt in ("XSD", "XML"):
        from .xsd import parse_fields as p
        return p(schema_text)
    logger.debug("No schema parser registered for format %s", fmt)
    return []
