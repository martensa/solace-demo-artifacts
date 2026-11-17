"""JSON forms used on the wire (UC1-BUILD-SPEC 4.1, 7.2, 7.3).

* ``compact``: our own payloads, no spaces, real umlauts, key order kept.
* ``canonical``: what SAM produces (sorted keys); the engine hashes and dedups only this.
* ``proto_compact``: proto3 JSON of a message (``MessageToDict`` defaults: camelCase,
  int64 as string, enum names, ``@type`` for ``Any``), then ``compact``. Never
  ``MessageToJson`` (it indents and escapes umlauts).
* ``parse_strict``: proto3 JSON into a message; unknown fields are an error.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, TypeVar

from google.protobuf import descriptor_pool, json_format
from google.protobuf.message import Message

M = TypeVar("M", bound=Message)


def compact(obj: Any) -> str:
    """``json.dumps`` with ``separators=(",", ":")`` and ``ensure_ascii=False``."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def canonical(obj: Any) -> str:
    """Like :func:`compact` with sorted keys (the form SAM re-serialises to)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def proto_dict(msg: Message, pool: descriptor_pool.DescriptorPool | None = None) -> dict[str, Any]:
    """``MessageToDict`` with the standard options; ``pool`` resolves ``Any`` payloads."""
    return json_format.MessageToDict(msg, descriptor_pool=pool)


def proto_compact(msg: Message, pool: descriptor_pool.DescriptorPool | None = None) -> str:
    """One-line proto3 JSON of ``msg``: ``compact(MessageToDict(msg, descriptor_pool=pool))``."""
    return compact(proto_dict(msg, pool))


def parse_strict(
    data: str | Mapping[str, Any], msg: M, pool: descriptor_pool.DescriptorPool | None = None
) -> M:
    """Fill ``msg`` from proto3 JSON (text or dict); unknown fields raise ``ParseError``."""
    obj = json.loads(data) if isinstance(data, str) else dict(data)
    json_format.ParseDict(obj, msg, ignore_unknown_fields=False, descriptor_pool=pool)
    return msg


def sha256_hex(text: str) -> str:
    """Hex SHA-256 of the UTF-8 bytes of ``text``."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
