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
# Wave 1 (#54): "true" iff this Topic/Pipeline carries the highest
# semver among the EP event/application versions ingested in this run.
# Set on every per-version OM entity so the OM UI can default-filter
# `eventPortalIsLatestVersion=true` and avoid drowning users in
# deprecated version entities.
CP_IS_LATEST_VERSION = "eventPortalIsLatestVersion"

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
# `epConsoleUrl` connection option (e.g. https://solace-sso.solace.cloud).
DEFAULT_EP_CONSOLE_URL = "https://console.solace.cloud"

# URL path templates relative to `epConsoleUrl`. Each template uses
# str.format with named placeholders. Overridable per service via the
# `ep<Entity>UrlTemplate` connection options if Solace changes its routes.
# Verified against the live Solace Cloud Console (2026-05): the SPA
# router actually uses /domains/<id>/<kind>/<id> with selectedId +
# selectedVersionId query params, and the domain landing page is the
# graph view (not the settings view).
DEFAULT_EP_DOMAIN_PATH = (
    "/ep/designer/domains/{domain_id}/graph"
    "?domainName={domain_name}"
)
DEFAULT_EP_EVENT_PATH = (
    "/ep/designer/domains/{domain_id}/events/{event_id}"
    "?domainName={domain_name}&selectedId={event_id}"
)
DEFAULT_EP_EVENT_VERSION_PATH = (
    "/ep/designer/domains/{domain_id}/events/{event_id}"
    "?domainName={domain_name}&selectedId={event_id}"
    "&selectedVersionId={event_version_id}"
)
DEFAULT_EP_SCHEMA_PATH = (
    "/ep/designer/domains/{domain_id}/schemas/{schema_id}"
    "?domainName={domain_name}&selectedId={schema_id}"
)
DEFAULT_EP_SCHEMA_VERSION_PATH = (
    "/ep/designer/domains/{domain_id}/schemas/{schema_id}"
    "?domainName={domain_name}&selectedId={schema_id}"
    "&selectedVersionId={schema_version_id}"
)
DEFAULT_EP_APPLICATION_PATH = (
    "/ep/designer/domains/{domain_id}/applications/{application_id}"
    "?domainName={domain_name}&selectedId={application_id}"
)
DEFAULT_EP_APPLICATION_VERSION_PATH = (
    "/ep/designer/domains/{domain_id}/applications/{application_id}"
    "?domainName={domain_name}&selectedId={application_id}"
    "&selectedVersionId={application_version_id}"
)
