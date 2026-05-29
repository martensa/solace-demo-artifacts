"""AsyncAPI 2.x → OpenMetadata CreateTopicRequest mapping.

This is the second ingestion mode: instead of walking Event Portal's
proprietary REST API, parse an AsyncAPI document (which Event Portal can
also export per application version, or which may live in Git as the
contract source of truth).

The mapping is intentionally lossy in the same way as `mappers.py`:
top-level message payload fields become SchemaFields; lifecycle state and
modeled event mesh aren't available in plain AsyncAPI so we skip them.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Optional

import yaml

from metadata.generated.schema.api.data.createTopic import CreateTopicRequest

# OM 1.6+ renamed MessageSchema -> Topic and SchemaField -> FieldModel.
# Alias on import so call sites stay readable.
try:
    from metadata.generated.schema.type.schema import (
        FieldModel as SchemaField,
        SchemaType,
        Topic as MessageSchema,
    )
except ImportError:  # pragma: no cover - legacy fallback
    from metadata.generated.schema.entity.data.topic import SchemaType  # OM <= 1.5
    from metadata.generated.schema.type.schema import (
        MessageSchema,
        SchemaField,
    )

from .mappers import parse_schema_fields, sanitize

logger = logging.getLogger(__name__)


def parse_asyncapi(content: str) -> Dict[str, Any]:
    """Accept either JSON or YAML AsyncAPI content."""
    content = content.strip()
    if content.startswith("{"):
        return json.loads(content)
    return yaml.safe_load(content)


def asyncapi_to_topic_requests(
    *,
    service_name: str,
    spec: Dict[str, Any],
    domain_hint: Optional[str] = None,
) -> Iterable[CreateTopicRequest]:
    """Yield one CreateTopicRequest per channel in the AsyncAPI document."""
    info = spec.get("info") or {}
    title = info.get("title") or "asyncapi"
    spec_version = info.get("version") or "1.0.0"
    channels = spec.get("channels") or {}
    components = spec.get("components") or {}
    messages_by_ref = components.get("messages") or {}
    schemas_by_ref = components.get("schemas") or {}

    for channel_name, channel in channels.items():
        for op_kind in ("publish", "subscribe"):
            op = channel.get(op_kind)
            if not op:
                continue
            message = _resolve_ref(op.get("message"), messages_by_ref)
            if not message:
                continue
            payload = _resolve_ref(message.get("payload"), schemas_by_ref)
            schema_text = (
                json.dumps(payload, indent=2) if isinstance(payload, dict) else None
            )
            fields: List[SchemaField] = (
                parse_schema_fields(schema_text, "JSON") if schema_text else []
            )

            topic_name = sanitize(f"{title}_{channel_name}_v{spec_version}")
            description = "\n\n".join(
                p
                for p in [
                    f"AsyncAPI title: `{title}` v`{spec_version}`",
                    f"Channel: `{channel_name}` ({op_kind})",
                    f"Application domain (hint): `{domain_hint}`"
                    if domain_hint
                    else "",
                    op.get("summary") or "",
                    op.get("description") or "",
                ]
                if p
            )

            yield CreateTopicRequest(
                name=topic_name,
                displayName=f"{title} · {channel_name} ({op_kind})",
                description=description,
                service=service_name,
                partitions=1,
                messageSchema=MessageSchema(
                    schemaType=SchemaType.JSON,
                    schemaText=schema_text,
                    schemaFields=fields,
                )
                if schema_text or fields
                else None,
            )


def _resolve_ref(
    obj: Any,
    components: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Resolve a `$ref` pointer one level. AsyncAPI refs in EP exports are
    typically `#/components/messages/Foo` or `#/components/schemas/Bar`."""
    if not isinstance(obj, dict):
        return None
    ref = obj.get("$ref")
    if not ref:
        return obj
    # Expect refs like "#/components/messages/Foo"
    parts = ref.lstrip("#/").split("/")
    if len(parts) < 3:
        return obj
    key = parts[-1]
    return components.get(key) or obj
