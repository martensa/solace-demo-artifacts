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
    api_token: str = ""          # read scope (ep-token-reader)
    webhook_secret: str = ""
    # Wave 4.5 (#49): SEPARATE write-scoped token (ep-token-writer). Only
    # the write-back path uses it; metadata + reconcile use api_token.
    # Empty => write-back cannot write (stays in dry-run / refuses).
    writer_token: str = ""

    model_config = SettingsConfigDict(env_prefix="EP_", env_file=".env", extra="ignore")


class OpenMetadataSettings(BaseSettings):
    host_port: str = "http://openmetadata-server:8585/api"
    jwt_token: str = ""
    service_name: str = "solace-event-portal"
    # Wave 5 (#41): must match the connector's tenantPrefix so the
    # soft-delete pass diffs the prefixed apps PipelineService for THIS
    # tenant only. Empty = single-tenant (legacy, unchanged).
    tenant_prefix: str = ""

    model_config = SettingsConfigDict(env_prefix="OM_", env_file=".env", extra="ignore")


class TransportSettings(BaseSettings):
    """Selects how the bridge receives notifications.

    * `polling`   - bridge polls EP every N seconds for changed events
                    since the watermark. Default for Solace Cloud EP v2
                    (which does not expose a webhook subscription API).
    * `http`      - FastAPI endpoint at /webhook/event-portal that applies
                    deltas directly to OpenMetadata. Use this when your EP
                    edition supports webhooks and you have configured one
                    pointing at the bridge URL (Solace Cloud v2: no).
    * `solace`    - subscribes to a Solace queue (durable) that an upstream
                    forwarder publishes EP webhook payloads onto.
    * `forwarder` - HTTP receiver only; does not call OpenMetadata. Verifies
                    the EP signature and publishes the raw payload onto a
                    Solace topic for a `solace`-mode bridge to consume.
    """

    mode: Literal["polling", "http", "solace", "forwarder", "writeback"] = "polling"

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

    # polling
    polling_interval_seconds: int = 10
    # restrict polling to specific domain ids; empty = every domain the
    # token can see (intentionally NOT the connector's filter pattern —
    # the bridge does not parse OM filters; pre-restrict here.)
    polling_domain_ids: List[str] = []

    # dedupe
    dedupe_ttl_seconds: int = 600
    dedupe_max_entries: int = 10_000

    # event-type allowlist (empty = accept all)
    accept_event_types: List[str] = []

    model_config = SettingsConfigDict(env_prefix="BRIDGE_", env_file=".env", extra="ignore")


class ObservabilitySettings(BaseSettings):
    """Production-hardening knobs (Wave 5): logging, metrics, tracing,
    graceful shutdown. All env vars share the ``BRIDGE_OBS_`` prefix.

    Defaults are conservative so the bridge behaves exactly like 0.8.0
    out of the box: text logs, no metrics server, no tracing. Operators
    opt in via the Helm chart (#15).
    """

    # #11 structured logging
    log_format: Literal["text", "json"] = "text"
    log_level: str = "INFO"

    # #13 graceful shutdown
    shutdown_grace_seconds: int = 10

    # #10 Prometheus metrics
    metrics_enabled: bool = False
    metrics_port: int = 9100

    # #63 OpenTelemetry tracing
    otel_enabled: bool = False
    otel_endpoint: str = ""  # e.g. http://otel-collector:4318 (empty = SDK default)
    otel_protocol: Literal["http/protobuf", "grpc"] = "http/protobuf"
    otel_service_name: str = "om-eventportal-bridge"

    model_config = SettingsConfigDict(
        env_prefix="BRIDGE_OBS_", env_file=".env", extra="ignore"
    )


class WritebackSettings(BaseSettings):
    """OM -> EP governance write-back (Wave 4.5 / #49). High blast radius,
    so it is OFF by default and DRY-RUN by default even when enabled --
    operators must explicitly opt into live EP writes after a shadow
    deploy. All env vars share the ``BRIDGE_WB_`` prefix.
    """

    # Master switch. When false, the OM webhook receiver still 200s but
    # nothing is enqueued/applied.
    enabled: bool = False
    # When true (default), planned EP writes are logged + counted but NOT
    # sent to EP. Flip to false only after the shadow-deploy drift cron is
    # green (plan exit criterion).
    dry_run: bool = True
    # HMAC secret OM signs its EntityChangeEvent webhook with (Alerts ->
    # destination). Verified via bridge.signature.verify.
    om_webhook_secret: str = ""
    om_webhook_header: str = "X-OM-Signature"
    # Worker drain bound used by graceful shutdown (#13) + the queue cap.
    queue_max: int = 10000

    model_config = SettingsConfigDict(
        env_prefix="BRIDGE_WB_", env_file=".env", extra="ignore"
    )


class BridgeSettings:
    """Bag-of-config so handler functions can take one parameter."""

    def __init__(
        self,
        ep: Optional[EventPortalSettings] = None,
        om: Optional[OpenMetadataSettings] = None,
        transport: Optional[TransportSettings] = None,
        obs: Optional[ObservabilitySettings] = None,
        writeback: Optional[WritebackSettings] = None,
    ):
        self.ep = ep or EventPortalSettings()
        self.om = om or OpenMetadataSettings()
        self.transport = transport or TransportSettings()
        self.obs = obs or ObservabilitySettings()
        self.writeback = writeback or WritebackSettings()
