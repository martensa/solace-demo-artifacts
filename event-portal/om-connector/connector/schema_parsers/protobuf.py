"""Protocol Buffers (proto3) -> OM SchemaField parser.

Best-effort parser using a small hand-rolled tokenizer rather than
relying on protoc. The use case here is *metadata discovery*, not code
generation -- we want the field names, primitive types, and nesting,
not a fully validated descriptor set. Avoiding the protoc dependency
keeps the ingestion image slim.

If a user's schemas exceed what this parser handles (extensions,
service blocks, oneof inside oneof), the Topic still ingests but with
schemaFields empty -- the full schemaText is preserved.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

from .util import safe_field, sanitize_name

logger = logging.getLogger(__name__)

# Token patterns
_MESSAGE_RE = re.compile(r"message\s+(\w+)\s*\{", re.MULTILINE)
# field:  modifier? type name = number;
_FIELD_RE = re.compile(
    r"^\s*(?:(repeated|optional|required)\s+)?"
    r"(\w+(?:\.\w+)*)\s+(\w+)\s*=\s*\d+\s*(?:\[[^\]]*\])?\s*;",
    re.MULTILINE,
)

_PRIM = {
    "double", "float", "int32", "int64", "uint32", "uint64",
    "sint32", "sint64", "fixed32", "fixed64", "sfixed32", "sfixed64",
    "bool", "string", "bytes",
}


def parse_fields(schema_text: str):
    if not schema_text:
        return []
    text = _strip_comments(schema_text)
    messages = _extract_messages(text)
    if not messages:
        return []
    # First-level fields of the FIRST message in the file. Convention:
    # the EP schema export wraps the event payload in a top-level message.
    top_name = next(iter(messages.keys()))
    return _fields_of(top_name, messages)


def _fields_of(message_name: str, messages):
    body = messages.get(message_name)
    if not body:
        return []
    fields = []
    for modifier, ftype, fname in _FIELD_RE.findall(body):
        ptype = ftype.split(".")[-1]
        if ptype in _PRIM:
            dtype = ptype.upper()
            children = None
        elif ptype in messages:
            dtype = "RECORD"
            children = _fields_of(ptype, messages)
        else:
            dtype = "UNKNOWN"
            children = None
        if modifier == "repeated":
            children = [
                safe_field(name="item", data_type=dtype, description="Array element", children=children)
            ]
            dtype = "ARRAY"
        fields.append(
            safe_field(
                name=sanitize_name(fname),
                data_type=dtype,
                description=f"protobuf {modifier} {ftype}".strip(),
                children=children,
            )
        )
    return fields


def _extract_messages(text: str):
    """Return {message_name: raw_body_text} for every top-level message.

    Handles nested braces by counting depth.
    """
    out = {}
    for m in _MESSAGE_RE.finditer(text):
        name = m.group(1)
        start = m.end()
        depth = 1
        i = start
        while i < len(text) and depth > 0:
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        out[name] = text[start:i - 1]
    return out


def _strip_comments(text: str) -> str:
    # // line comments and /* block comments */
    text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return text
