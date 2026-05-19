"""XSD (XML Schema) -> OM SchemaField parser.

Pulls top-level `xs:element` declarations and their direct children, using
the standard-library `xml.etree.ElementTree` (no lxml dependency).

We deliberately do NOT resolve `xs:import` / `xs:include` -- the EP API
ships the schema as a self-contained text blob and following external
refs has unbounded cost.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Dict, List

from .util import safe_field, sanitize_name

logger = logging.getLogger(__name__)

_NS = {"xs": "http://www.w3.org/2001/XMLSchema"}


_TYPE_MAP = {
    "string": "STRING",
    "boolean": "BOOLEAN",
    "decimal": "NUMBER",
    "float": "FLOAT",
    "double": "DOUBLE",
    "integer": "INTEGER",
    "int": "INTEGER",
    "long": "LONG",
    "short": "INTEGER",
    "byte": "INTEGER",
    "dateTime": "DATETIME",
    "date": "DATE",
    "time": "TIME",
}


def parse_fields(schema_text: str):
    if not schema_text:
        return []
    try:
        root = ET.fromstring(schema_text)
    except ET.ParseError as exc:
        logger.warning("XSD content is not valid XML: %s", exc)
        return []

    # Index complexType definitions for ref resolution.
    complex_types: Dict[str, ET.Element] = {}
    for ct in root.findall("xs:complexType", _NS):
        name = ct.get("name")
        if name:
            complex_types[name] = ct

    # Top-level elements
    top_elements = root.findall("xs:element", _NS)
    if not top_elements:
        return []

    return [_field_of(el, complex_types) for el in top_elements]


def _field_of(element: ET.Element, complex_types: Dict[str, ET.Element]):
    name = sanitize_name(element.get("name") or element.get("ref") or "field")
    type_ref = element.get("type")
    inline_complex = element.find("xs:complexType", _NS)

    children = None
    if type_ref and ":" in type_ref:
        local = type_ref.split(":")[-1]
        dtype = _TYPE_MAP.get(local, local.upper())
        if local in complex_types:
            children = _children_of_complex(complex_types[local], complex_types)
            dtype = "RECORD"
    elif type_ref:
        if type_ref in complex_types:
            children = _children_of_complex(complex_types[type_ref], complex_types)
            dtype = "RECORD"
        else:
            dtype = _TYPE_MAP.get(type_ref, type_ref.upper())
    elif inline_complex is not None:
        children = _children_of_complex(inline_complex, complex_types)
        dtype = "RECORD"
    else:
        dtype = "STRING"

    description = None
    annotation = element.find("xs:annotation/xs:documentation", _NS)
    if annotation is not None and annotation.text:
        description = annotation.text.strip()
    return safe_field(name=name, data_type=dtype, description=description, children=children)


def _children_of_complex(ct: ET.Element, complex_types: Dict[str, ET.Element]):
    seq = ct.find("xs:sequence", _NS)
    if seq is None:
        seq = ct.find("xs:all", _NS)
    if seq is None:
        seq = ct.find("xs:choice", _NS)
    if seq is None:
        return []
    return [_field_of(el, complex_types) for el in seq.findall("xs:element", _NS)]
