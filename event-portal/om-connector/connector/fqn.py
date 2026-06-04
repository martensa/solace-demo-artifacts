"""Pure FQN-building helpers, importable without ``openmetadata-ingestion``.

The bridge's reconcile + soft-delete paths need to compose deterministic
OM FQNs from EP entity names, but they run in environments where the OM
SDK may not be installed (e.g. a slim bridge image or a unit test). The
mappers in ``connector.mappers`` import the OM SDK at module load --
useless for those callers. This module mirrors the FQN logic with zero
runtime dependencies so anything can use it.

`mappers` re-exports these names for backwards compatibility, so callers
already on ``from connector.mappers import topic_fqn`` keep working.
"""
from __future__ import annotations

import re
from typing import Optional

from .property_keys import APP_PIPELINE_SERVICE_NAME

# OM FQN segment vocabulary. Dots + dashes are kept verbatim (the
# `quote_if_dotted` helper wraps dotted parts in double-quotes); anything
# else outside word chars is replaced by `_` so semver versions like
# `1.0.0` survive intact and get auto-quoted at the FQN boundary.
_INVALID_FQN_CHARS = re.compile(r"[^A-Za-z0-9_\-.]")


def sanitize(name: Optional[str]) -> str:
    """Make ``name`` safe to embed in an OpenMetadata FQN."""
    return _INVALID_FQN_CHARS.sub("_", name or "unnamed")


def build_topic_name(event_name: str, version: str) -> str:
    """Topic entity name = ``<event>_v<version>``, FQN-safe."""
    return sanitize(f"{event_name}_v{version}")


def quote_if_dotted(part: str) -> str:
    """OM treats dots as FQN separators; parts containing a literal dot
    must be quoted (``name.with.dots`` -> ``"name.with.dots"``). Used for
    entity FQNs that include semver versions (1.0.0).
    """
    if "." in part and not (part.startswith('"') and part.endswith('"')):
        return f'"{part}"'
    return part


def topic_fqn(service_name: str, event_name: str, version: str) -> str:
    """FQN of a Topic entity under the EP MessagingService."""
    return f"{service_name}.{quote_if_dotted(build_topic_name(event_name, version))}"


def app_pipeline_name(app_name: str, version: str) -> str:
    """Pipeline entity name = ``<app>_v<version>``, FQN-safe."""
    return sanitize(f"{app_name}_v{version}")


def app_pipeline_fqn(app_name: str, version: str) -> str:
    """FQN of a Pipeline entity standing in for an EP application version.

    Pipelines live under the synthetic PipelineService
    ``solace-event-portal-apps`` (see APP_PIPELINE_SERVICE_NAME).
    """
    return (
        f"{APP_PIPELINE_SERVICE_NAME}."
        f"{quote_if_dotted(app_pipeline_name(app_name, version))}"
    )
