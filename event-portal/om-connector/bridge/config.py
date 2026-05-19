"""Runtime configuration for the bridge.

Pydantic settings are populated from environment variables (12-factor) and
optionally a `.env` file. Settings are split by concern (Event Portal,
OpenMetadata, transport) so each can be swapped without touching the rest.
"""
from __future__ import annotations

from typing import List, Literal, Optional

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:  # pragma: no cover - older pydantic
    from pydantic import BaseSettings  # type: ignore

    SettingsConfigDict = dict  # type: ignore


class EventPortalSettings(BaseSettings):
    api_url: str = "https://api.solace.cloud/api/v2"
    api_token: str = ""
    webhook_secret: str = ""

    model_config = SettingsConfigDict(env_prefix="EP_", env_file=".env", extra="ignore")


class OpenMetadataSettings(BaseSettings):
    host_port: str = "http://openmetadata-server:8585/api"
    jwt_token: str = ""
    service_name: str = "solace-event-portal"

    model_config = SettingsConfigDict(env_prefix="OM_", env_file=".env", extra="ignore")


class TransportSettings(BaseSettings):
    """Selects how the bridge receives notifications.

    * `http`      - FastAPI endpoint at /webhook/event-portal that applies
                    deltas directly to OpenMetadata.
    * `solace`    - subscribes to a Solace queue (durable) that an upstream
                    forwarder publishes EP webhook payloads onto.
    * `forwarder` - HTTP receiver only; does not call OpenMetadata. Verifies
                    the EP signature and publishes the raw payload onto a
                    Solace topic for a `solace`-mode bridge to consume.
    """

    mode: Literal["http", "solace", "forwarder"] = "http"

    # forwarder
    forwarder_topic_prefix: str = "om/sync/eventportal"

    # http
    bind_host: str = "0.0.0.0"
    bind_port: int = 8080

    # solace
    solace_host: str = "tcp://solace_1:55555"
    solace_vpn: str = "default"
    solace_username: str = "om-bridge"
    solace_password: str = ""
    solace_queue: str = "om/sync/eventportal"

    # dedupe
    dedupe_ttl_seconds: int = 600
    dedupe_max_entries: int = 10_000

    # event-type allowlist (empty = accept all)
    accept_event_types: List[str] = []

    model_config = SettingsConfigDict(env_prefix="BRIDGE_", env_file=".env", extra="ignore")


class BridgeSettings:
    """Bag-of-config so handler functions can take one parameter."""

    def __init__(
        self,
        ep: Optional[EventPortalSettings] = None,
        om: Optional[OpenMetadataSettings] = None,
        transport: Optional[TransportSettings] = None,
    ):
        self.ep = ep or EventPortalSettings()
        self.om = om or OpenMetadataSettings()
        self.transport = transport or TransportSettings()
