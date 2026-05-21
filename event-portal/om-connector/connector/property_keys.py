"""Stable constants shared between the mappers, the bridge, and the
bootstrap CLI.

Lives in its own module so callers (bootstrap, reconcile) can import
without dragging in `openmetadata-ingestion` — useful for slim runtime
environments and lightweight unit tests.
"""

# Topic.extension custom properties (see CreateTopicRequest mapping).
CP_DOMAIN_ID = "eventPortalDomainId"
CP_DOMAIN_NAME = "eventPortalDomainName"
CP_EVENT_ID = "eventPortalEventId"
CP_EVENT_VERSION_ID = "eventPortalEventVersionId"
CP_SCHEMA_VERSION_ID = "eventPortalSchemaVersionId"
CP_TOPIC_ADDRESS = "eventPortalTopicAddress"
CP_STATE = "eventPortalState"
CP_STATE_CHANGED_AT = "eventPortalStateChangedAt"
CP_MODELED_MESH_IDS = "eventPortalModeledMeshIds"
CP_PUBLISHED_BY = "eventPortalPublishedBy"
CP_CONSUMED_BY = "eventPortalConsumedBy"

# Pipeline.extension custom properties (for EP applications mapped as
# Pipeline entities under a synthetic PipelineService).
CP_APP_ID = "eventPortalApplicationId"
CP_APP_VERSION_ID = "eventPortalApplicationVersionId"
CP_APP_DOMAIN_ID = "eventPortalApplicationDomainId"
CP_APP_DOMAIN_NAME = "eventPortalApplicationDomainName"

# Name of the synthetic PipelineService that holds Pipeline entities for
# every EP Application.
APP_PIPELINE_SERVICE_NAME = "solace-event-portal-apps"

# MessagingService.extension property used by the reconciliation job.
AUDIT_WATERMARK_KEY = "eventPortalAuditWatermark"

# --- Human-friendly markdown links to the EP UI (preferred over raw IDs).
# These render in the OM UI as clickable "[Name v1.0.0](https://...)" links
# straight back to the originating Solace Cloud EP entity, so a data
# consumer can jump from OM to EP in one click.

# Topic.extension
CP_EP_DOMAIN = "eventPortalDomain"          # markdown: [DomainName](url)
CP_EP_EVENT = "eventPortalEvent"            # markdown: [EventName vX.Y.Z](url)
CP_EP_SCHEMA = "eventPortalSchema"          # markdown: [SchemaName vX.Y.Z](url) (when present)

# Pipeline.extension
CP_EP_APPLICATION = "eventPortalApplication"          # markdown: [AppName vX.Y.Z](url)
CP_EP_APP_DOMAIN = "eventPortalApplicationDomain"     # markdown: [DomainName](url)

# Default Solace Cloud Console base URL; overridable per service via the
# `epConsoleUrl` connection option.
DEFAULT_EP_CONSOLE_URL = "https://console.solace.cloud"
