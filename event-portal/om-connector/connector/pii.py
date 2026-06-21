"""Pure PII-signal detection (Wave 5 / #62).

The connector flags an entity as PII-bearing when ANY of four declarative
signals fire:

1. an EP Custom Attribute whose *name* is in the configured PII CA set
   (matched by name, never by free-text value -- EP CA values are
   unconstrained, so value-matching would be unreliable);
2. an EP/OM tag in the configured PII tag set;
3. the topic address matches an operator-supplied regex;
4. a schema field annotated ``x-pii: true`` (JSON Schema) or carrying an
   ``x-pii`` marker (Avro field property or ``doc``).

This module has ZERO OpenMetadata-SDK dependency so the detection logic
is unit-testable everywhere and reusable from the slim bridge. The OM
``TagLabel`` rendering + ``FieldModel`` annotation live in
``connector.mappers`` / ``connector.schema_parsers`` respectively; this
module only decides *whether* PII is present and *which fields*.

PII detection is read-only on the EP side; registering a ``pii`` CA
definition back into EP needs an EP write path (reserved for Wave 4.5 /
#49) and is intentionally out of scope here.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable, List, Optional, Set

logger = logging.getLogger(__name__)

# Marker key looked up on schema fields. JSON-Schema uses it as a boolean
# property extension; Avro fields may carry it as a custom property or
# mention it in their ``doc`` string.
PII_ANNOTATION_KEY = "x-pii"


def topic_address_is_pii(topic_address: Optional[str], pattern: Optional[str]) -> bool:
    """True if ``topic_address`` matches the operator's PII regex.

    A blank pattern disables this signal. A malformed pattern is logged
    once and treated as no-match (never raises -- a bad config must not
    abort ingestion, and must not silently tag everything as PII).
    """
    if not topic_address or not pattern:
        return False
    try:
        return re.search(pattern, topic_address) is not None
    except re.error:
        logger.warning("Invalid piiTopicSegmentPattern %r; ignoring", pattern)
        return False


def _norm(values: Optional[Iterable[str]]) -> Set[str]:
    return {v for v in (values or []) if v}


def names_intersect(
    present: Optional[Iterable[str]], configured: Optional[Iterable[str]]
) -> bool:
    """True if any configured name is present (case-sensitive set test)."""
    conf = _norm(configured)
    if not conf:
        return False
    return bool(_norm(present) & conf)


def schema_text_pii_fields(
    schema_text: Optional[str], schema_type: Optional[str]
) -> Set[str]:
    """Return the set of field names flagged ``x-pii`` in a schema body.

    Supports JSON Schema (``properties.<name>.x-pii: true``, recursive)
    and Avro (``fields[].x-pii`` / ``fields[].doc`` containing the
    marker). Unknown / unparseable schemas yield an empty set -- never
    raises, so a malformed schema downgrades to "no field-level PII"
    rather than breaking ingestion.
    """
    if not schema_text:
        return set()
    stype = (schema_type or "").strip().lower()
    try:
        doc = json.loads(schema_text)
    except (ValueError, TypeError):
        return set()
    if not isinstance(doc, dict):
        return set()
    if stype.startswith("avro"):
        return _avro_pii_fields(doc)
    # Default to JSON-Schema shape (also a sane fallback for "json").
    found: Set[str] = set()
    _json_schema_pii_fields(doc, found)
    return found


def _is_pii_flag(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1", "pii")
    return False


def _json_schema_pii_fields(node: Any, found: Set[str]) -> None:
    if not isinstance(node, dict):
        return
    props = node.get("properties")
    if isinstance(props, dict):
        for name, sub in props.items():
            if isinstance(sub, dict) and _is_pii_flag(sub.get(PII_ANNOTATION_KEY)):
                found.add(name)
            _json_schema_pii_fields(sub, found)
    # Recurse into the common composition / nesting keywords.
    for key in ("items", "additionalProperties"):
        _json_schema_pii_fields(node.get(key), found)
    for key in ("allOf", "anyOf", "oneOf"):
        for sub in node.get(key) or []:
            _json_schema_pii_fields(sub, found)
    defs = node.get("$defs") or node.get("definitions")
    if isinstance(defs, dict):
        for sub in defs.values():
            _json_schema_pii_fields(sub, found)


def _avro_pii_fields(node: Any) -> Set[str]:
    found: Set[str] = set()
    _avro_walk(node, found)
    return found


def _avro_walk(node: Any, found: Set[str]) -> None:
    if isinstance(node, list):
        for sub in node:
            _avro_walk(sub, found)
        return
    if not isinstance(node, dict):
        return
    for field in node.get("fields") or []:
        if not isinstance(field, dict):
            continue
        name = field.get("name")
        doc = field.get("doc")
        if name and (
            _is_pii_flag(field.get(PII_ANNOTATION_KEY))
            or (isinstance(doc, str) and PII_ANNOTATION_KEY in doc.lower())
        ):
            found.add(name)
        # Recurse into nested record types (field["type"] may be a dict
        # or a union list of dicts).
        _avro_walk(field.get("type"), found)


def has_pii_signal(
    *,
    present_ca_names: Optional[Iterable[str]] = None,
    pii_ca_names: Optional[Iterable[str]] = None,
    present_tag_names: Optional[Iterable[str]] = None,
    pii_tag_names: Optional[Iterable[str]] = None,
    topic_address: Optional[str] = None,
    topic_pattern: Optional[str] = None,
    schema_text: Optional[str] = None,
    schema_type: Optional[str] = None,
) -> bool:
    """Combine the four declarative PII signals into a single boolean."""
    return (
        names_intersect(present_ca_names, pii_ca_names)
        or names_intersect(present_tag_names, pii_tag_names)
        or topic_address_is_pii(topic_address, topic_pattern)
        or bool(schema_text_pii_fields(schema_text, schema_type))
    )


def should_sample(
    sample_data_enabled: bool, has_address: bool, contains_pii: bool
) -> bool:
    """Whether a topic may be buffered for live sample-data collection.

    The security-critical gate (#62): a PII-bearing topic is NEVER sampled,
    regardless of the other flags. Kept pure + unit-tested so an accidental
    inversion of the hard-block is caught immediately.
    """
    return bool(sample_data_enabled and has_address and not contains_pii)


def parse_pii_ca_names(raw: Any) -> List[str]:
    """Normalise the ``piiCaName`` option (single value, comma string, or
    list) into a list of CA names."""
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(v).strip() for v in raw if str(v).strip()]
    return [s.strip() for s in str(raw).split(",") if s.strip()]


def parse_pii_tag_names(raw: Any) -> List[str]:
    """Normalise the ``piiTagNames`` option into a list of tag names/FQNs."""
    return parse_pii_ca_names(raw)
