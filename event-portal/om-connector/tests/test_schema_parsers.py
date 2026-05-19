"""Schema parser tests.

Run without `openmetadata-ingestion` installed: `safe_field` falls back
to a dict shape with the same keys (name, dataType, description, children),
so assertions are agnostic of whichever representation is in use.
"""
import json

from connector.schema_parsers import parse_fields


# --------------------------------------------------------- helpers


def _name(f):
    return f["name"] if isinstance(f, dict) else f.name.__root__


def _dtype(f):
    return f["dataType"] if isinstance(f, dict) else f.dataType


def _children(f):
    if isinstance(f, dict):
        return f.get("children") or []
    return f.children or []


# --------------------------------------------------------- JSON Schema


def test_json_schema_simple_properties():
    text = json.dumps({
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "qty": {"type": "integer"},
        },
        "required": ["id"],
    })
    fields = parse_fields("JSON", text)
    assert [_name(f) for f in fields] == ["id", "qty"]
    assert [_dtype(f) for f in fields] == ["STRING", "INTEGER"]


def test_json_schema_nested_object_has_children():
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
    [addr] = parse_fields("JSON", text)
    assert _dtype(addr) == "RECORD"
    assert [_name(c) for c in _children(addr)] == ["street", "zip"]


def test_json_schema_array_has_item_child():
    text = json.dumps({
        "type": "object",
        "properties": {
            "tags": {"type": "array", "items": {"type": "string"}},
        },
    })
    [tags] = parse_fields("JSON", text)
    assert _dtype(tags) == "ARRAY"
    [item] = _children(tags)
    assert _dtype(item) == "STRING"


def test_json_schema_resolves_internal_ref():
    text = json.dumps({
        "type": "object",
        "properties": {"customer": {"$ref": "#/definitions/Customer"}},
        "definitions": {
            "Customer": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
            }
        },
    })
    [customer] = parse_fields("JSON", text)
    assert _dtype(customer) == "RECORD"
    assert [_name(c) for c in _children(customer)] == ["id"]


def test_json_schema_handles_nullable_type_list():
    text = json.dumps({
        "type": "object",
        "properties": {"name": {"type": ["string", "null"]}},
    })
    [name] = parse_fields("JSON", text)
    assert _dtype(name) == "STRING"


# --------------------------------------------------------- Avro


def test_avro_record_with_nested_record():
    text = json.dumps({
        "type": "record",
        "name": "Order",
        "fields": [
            {"name": "id", "type": "string"},
            {
                "name": "customer",
                "type": {
                    "type": "record",
                    "name": "Customer",
                    "fields": [{"name": "email", "type": "string"}],
                },
            },
        ],
    })
    fields = parse_fields("AVRO", text)
    assert [_name(f) for f in fields] == ["id", "customer"]
    customer = fields[1]
    assert _dtype(customer) == "RECORD"
    assert [_name(c) for c in _children(customer)] == ["email"]


def test_avro_union_with_null_marks_nullable():
    text = json.dumps({
        "type": "record",
        "name": "Order",
        "fields": [{"name": "shippedAt", "type": ["null", "string"]}],
    })
    [f] = parse_fields("AVRO", text)
    assert _dtype(f) == "STRING"


def test_avro_array_field_has_item_child():
    text = json.dumps({
        "type": "record",
        "name": "Order",
        "fields": [{"name": "lines", "type": {"type": "array", "items": "long"}}],
    })
    [lines] = parse_fields("AVRO", text)
    assert _dtype(lines) == "ARRAY"
    [item] = _children(lines)
    assert _dtype(item) == "LONG"


def test_avro_enum_records_symbols_in_description():
    text = json.dumps({
        "type": "record",
        "name": "Order",
        "fields": [{
            "name": "status",
            "type": {"type": "enum", "name": "Status", "symbols": ["NEW", "DONE"]},
        }],
    })
    [status] = parse_fields("AVRO", text)
    assert _dtype(status) == "ENUM"


# --------------------------------------------------------- Protobuf


def test_protobuf_basic_message_and_repeated():
    text = """
    syntax = "proto3";
    message Order {
      string id = 1;
      int64 qty = 2;
      repeated string tags = 3;
    }
    """
    fields = parse_fields("PROTOBUF", text)
    assert [_name(f) for f in fields] == ["id", "qty", "tags"]
    assert [_dtype(f) for f in fields] == ["STRING", "INT64", "ARRAY"]


def test_protobuf_nested_message():
    text = """
    syntax = "proto3";
    message Order {
      string id = 1;
      Customer customer = 2;
    }
    message Customer {
      string email = 1;
    }
    """
    fields = parse_fields("PROTOBUF", text)
    [_, customer] = fields
    assert _dtype(customer) == "RECORD"
    assert [_name(c) for c in _children(customer)] == ["email"]


# --------------------------------------------------------- XSD


def test_xsd_top_level_element_with_sequence():
    text = """<?xml version="1.0"?>
    <xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
      <xs:element name="Order">
        <xs:complexType>
          <xs:sequence>
            <xs:element name="id" type="xs:string"/>
            <xs:element name="qty" type="xs:int"/>
          </xs:sequence>
        </xs:complexType>
      </xs:element>
    </xs:schema>
    """
    [order] = parse_fields("XSD", text)
    assert _dtype(order) == "RECORD"
    assert [_name(c) for c in _children(order)] == ["id", "qty"]
    assert [_dtype(c) for c in _children(order)] == ["STRING", "INTEGER"]


# --------------------------------------------------------- Format dispatch


def test_unknown_format_returns_empty_list():
    assert parse_fields("ASN1", "doesnt matter") == []


def test_empty_content_returns_empty_list():
    assert parse_fields("JSON", "") == []
