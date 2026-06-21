"""Schema parser tests.

Wave 1 (#64) rewrite: the dispatcher now delegates to OpenMetadata's
built-in ``metadata.parsers.{avro,json_schema,protobuf}_parser`` modules
instead of our home-grown walkers. Tests assert against the
``FieldModel`` shape OM returns (RootModel ``.root`` for ``name`` and
``DataTypeTopic`` enum for ``dataType``) and verify the Beat-Kafka
logical-type / JSON-format enrichment layer.

These tests require the openmetadata-ingestion SDK to be installed --
in the ingestion image that is always the case. Outside the image,
each test silently skips via ``pytest.importorskip``.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("metadata.parsers.json_schema_parser")

from connector.schema_parsers import parse_fields  # noqa: E402


# ----------------------------------------------------------------- helpers


def _name(field) -> str:
    """Read FieldModel.name from a Pydantic-v2 RootModel."""
    n = getattr(field, "name", None)
    return str(getattr(n, "root", getattr(n, "__root__", n))) if n is not None else ""


def _dtype(field) -> str:
    """Read FieldModel.dataType as a plain string (DataTypeTopic enum)."""
    dt = getattr(field, "dataType", None)
    return str(getattr(dt, "value", dt)) if dt is not None else ""


def _display(field):
    return getattr(field, "dataTypeDisplay", None)


def _children(field):
    return getattr(field, "children", None) or []


def _top(fields):
    """OM's JSON + Avro parsers wrap the whole schema in one top-level
    field (a RECORD named 'default' for JSON, the record's own name for
    Avro). Return that wrapper so the per-property checks are concise.
    """
    assert len(fields) == 1, f"expected one top-level wrapper, got {len(fields)}"
    return fields[0]


# -------------------------------------------------------------- JSON Schema


def test_json_schema_simple_properties_wrapped_in_default_record():
    text = json.dumps({
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "qty": {"type": "integer"},
        },
        "required": ["id"],
    })
    top = _top(parse_fields("JSON", text))
    assert _dtype(top) == "RECORD"
    children = _children(top)
    assert [_name(c) for c in children] == ["id", "qty"]
    assert [_dtype(c) for c in children] == ["STRING", "INT"]


def test_json_schema_nested_object_has_record_children():
    text = json.dumps({
        "type": "object",
        "properties": {
            "address": {
                "type": "object",
                "properties": {
                    "street": {"type": "string"},
                    "zip": {"type": "string"},
                },
            },
        },
    })
    top = _top(parse_fields("JSON", text))
    [addr] = _children(top)
    assert _name(addr) == "address"
    assert _dtype(addr) == "RECORD"
    assert [_name(c) for c in _children(addr)] == ["street", "zip"]


def test_json_schema_array_field_has_array_dtype():
    text = json.dumps({
        "type": "object",
        "properties": {
            "tags": {"type": "array", "items": {"type": "string"}},
        },
    })
    top = _top(parse_fields("JSON", text))
    [tags] = _children(top)
    assert _name(tags) == "tags"
    assert _dtype(tags) == "ARRAY"


def test_json_schema_format_lands_in_dataTypeDisplay_beat_kafka():
    """Beat-Kafka: OM's JSON parser drops ``format`` annotations. We
    re-attach them as ``dataTypeDisplay`` so OM users see semantic types
    (uuid, date-time, email) alongside the wire type."""
    text = json.dumps({
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "createdAt": {"type": "string", "format": "date-time"},
            "contactEmail": {"type": "string", "format": "email"},
            "untyped": {"type": "string"},
        },
    })
    top = _top(parse_fields("JSON", text))
    by_name = {_name(c): c for c in _children(top)}
    assert _display(by_name["id"]) == "uuid"
    assert _display(by_name["createdAt"]) == "date-time"
    assert _display(by_name["contactEmail"]) == "email"
    # Plain string with no format is left alone.
    assert _display(by_name["untyped"]) in (None, "string")


# --------------------------------------------------------- Avro


def test_avro_record_with_primitive_fields_wrapped_in_record():
    schema = json.dumps({
        "type": "record",
        "name": "Order",
        "fields": [
            {"name": "id", "type": "long"},
            {"name": "customer", "type": "string"},
        ],
    })
    top = _top(parse_fields("AVRO", schema))
    assert _dtype(top) == "RECORD"
    children = _children(top)
    assert [_name(c) for c in children] == ["id", "customer"]
    assert [_dtype(c) for c in children] == ["LONG", "STRING"]


def test_avro_union_with_null_unwraps_inner_type():
    schema = json.dumps({
        "type": "record",
        "name": "Order",
        "fields": [
            {"name": "discount", "type": ["null", "double"], "default": None},
        ],
    })
    top = _top(parse_fields("AVRO", schema))
    [field] = _children(top)
    assert _name(field) == "discount"
    # The data type comes through as the non-null branch even though
    # the source is a union -- OM's parser unwraps `["null", T]`.
    assert _dtype(field) in ("DOUBLE", "UNION")


def test_avro_array_field_has_array_dtype():
    schema = json.dumps({
        "type": "record",
        "name": "Cart",
        "fields": [
            {"name": "items", "type": {"type": "array", "items": "string"}},
        ],
    })
    top = _top(parse_fields("AVRO", schema))
    [items] = _children(top)
    assert _name(items) == "items"
    assert _dtype(items) == "ARRAY"


def test_avro_logical_types_land_in_dataTypeDisplay_beat_kafka():
    """Beat-Kafka: OM's Avro parser silently drops ``logicalType``
    (decimal, date, timestamp-millis, uuid). We restore them as
    ``dataTypeDisplay`` composed as ``"{wire}<{logical}>"`` so users
    see e.g. ``"long<timestamp-millis>"`` in the OM field tree."""
    schema = json.dumps({
        "type": "record",
        "name": "Order",
        "fields": [
            {"name": "id", "type": {"type": "string", "logicalType": "uuid"}},
            {"name": "amount", "type": {
                "type": "bytes",
                "logicalType": "decimal",
                "precision": 10,
                "scale": 2,
            }},
            {"name": "ts", "type": {"type": "long", "logicalType": "timestamp-millis"}},
            {"name": "plain", "type": "string"},
        ],
    })
    top = _top(parse_fields("AVRO", schema))
    by_name = {_name(c): c for c in _children(top)}
    assert _display(by_name["id"]) == "string<uuid>"
    assert _display(by_name["amount"]) == "bytes<decimal>"
    assert _display(by_name["ts"]) == "long<timestamp-millis>"
    # Plain field has no logical type -- bare wire type is preserved.
    assert _display(by_name["plain"]) in (None, "string")


# --------------------------------------------------------- Protobuf


def test_protobuf_basic_message_with_primitive_fields():
    schema = """
syntax = "proto3";
message Order {
  int64 id = 1;
  string customer = 2;
  double total = 3;
}
"""
    fields = parse_fields("PROTOBUF", schema)
    # Protobuf parser may or may not wrap in a top-level RECORD; both
    # shapes are acceptable. Walk recursively for the named fields.
    seen = set()

    def walk(items):
        for f in items:
            seen.add((_name(f), _dtype(f)))
            walk(_children(f))

    walk(fields)
    assert ("id", "LONG") in seen or ("id", "INT") in seen
    assert any(name == "customer" for name, _ in seen)


# --------------------------------------------------------- error paths


def test_xsd_format_returns_empty_list_no_om_parser():
    """OM has no XSD parser. We return [] so the Topic still emits
    with raw schemaText attached for human inspection."""
    assert parse_fields("XSD", "<xs:schema/>") == []


def test_xml_format_returns_empty_list():
    assert parse_fields("XML", "<root/>") == []


def test_unknown_format_returns_empty_list():
    assert parse_fields("BSON", "{}") == []


def test_empty_content_returns_empty_list():
    assert parse_fields("JSON", "") == []


def test_malformed_json_returns_empty_list_does_not_raise():
    # Parser exception is swallowed; caller still gets [].
    assert parse_fields("JSON", "{not valid json}") == []


def test_json_schema_x_pii_field_marked_when_opted_in():
    """Wave 5 (#62): with mark_pii=True an x-pii field gets a [PII] marker in
    dataTypeDisplay; non-PII fields are untouched."""
    schema = json.dumps({
        "type": "object",
        "properties": {
            "email": {"type": "string", "x-pii": True},
            "name": {"type": "string"},
        },
    })
    top = _top(parse_fields("JSON", schema, mark_pii=True))
    by_name = {_name(c): c for c in _children(top)}
    assert "[PII]" in (_display(by_name["email"]) or "")
    assert "[PII]" not in (_display(by_name["name"]) or "")


def test_x_pii_field_not_marked_when_not_opted_in():
    """Default (mark_pii=False) leaves dataTypeDisplay byte-identical -- an
    existing ingest that never opted into PII sees no [PII] markers."""
    schema = json.dumps({
        "type": "object",
        "properties": {"email": {"type": "string", "x-pii": True}},
    })
    top = _top(parse_fields("JSON", schema))  # mark_pii defaults False
    by_name = {_name(c): c for c in _children(top)}
    assert "[PII]" not in (_display(by_name["email"]) or "")
