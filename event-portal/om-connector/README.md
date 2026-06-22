# OpenMetadata Solace Event Portal Connector

Two cooperating components that govern a Solace Event Portal estate
from OpenMetadata:

- **Pull connector** (`connector/`) — a custom OpenMetadata Source
  that ingests EP application domains, events, applications, schemas,
  Event APIs, Event API Products, consumer queues, and the
  topic-address hierarchy. Emits real lineage edges and lifecycle
  tags. Runs on the standard ingestion schedule and also serves as
  the daily reconciliation pass.
- **Webhook bridge** (`bridge/`) — a small FastAPI / Solace consumer
  service. Today's Solace Cloud Event Portal does not expose outbound
  webhooks, so the bridge runs in **polling mode** against the same
  REST API as the pull connector. The bridge also runs the
  soft-delete drift pass.

**Status: Beta.** The `0.9.0` line (Waves 0-5 + the flag-off Wave 4.5
write-back) is the Beta release; this is the current scope. The
formerly-planned v1.0 GA / prod-cutover and OpenMetadata upstream
contribution are out of scope.

Current image:
`registry.solace.lab/openmetadata-ingestion-solace:0.9.0`.

See `CLAUDE.md` for the per-wave status grid and the architectural
overview. See `docs/implementation-plan.md` for the delivery record
and `docs/operations.md` for running the Beta.

## Why this connector

Event Portal is the system of record for event-driven architecture.
This connector is purpose-built for it rather than retrofitting the
generic Kafka messaging connector, and it exceeds that connector on
seven axes (the `#67` Beat-Kafka list):

1. **Application modelling** — native Producer / Consumer / Application
   entities; the Kafka connector leans on KafkaConnect.
2. **Domain** — sets `Topic.domains` natively; the Kafka connector
   never sets it.
3. **Lifecycle** — EP states become OM Tags
   (`EventPortal.{Draft,Released,Deprecated,Retired}`); the Kafka
   connector emits zero tags.
4. **Versions** — one Topic / Pipeline per version
   (`ingestAllVersions` default on); the Kafka connector flattens to
   latest silently.
5. **Logical types** — Avro / JSON-Schema logical types preserved in
   `dataTypeDisplay`; the Kafka connector drops them.
6. **Schemas** — first-class Schema / Table entity; the Kafka
   connector only embeds the schema in the Topic.
7. **Refs** — `$ref` graph resolution across schemas; the Kafka
   connector string-concatenates.

## Compatibility

| Connector | OpenMetadata SDK | Notes |
|---|---|---|
| 0.9.x | 1.11 | Wave 5: production hardening (multi-tenant, PII, observability, Helm) |
| 0.8.x | 1.11 | Wave 4: Identity + Soft-delete drift pass |
| 0.7.x | 1.11 | Wave 3: new entity types (Event API, EAPP, Schemas, Tree, Consumer) |
| 0.6.x | 1.11 | Wave 2: ServiceSpec split + cross-system lineage |
| 0.5.x | 1.11 | Wave 1: parsed SchemaFields + CA-to-Tag + all-versions default |
| 0.4.x | 1.11 | Wave 0: SDK migration baseline |
| 0.3.x | 1.6 - 1.7 | Pilot: pre-Wave-0 baseline (CustomMessaging) |

## Mapping (current as of image 0.8.0)

| Event Portal | OpenMetadata entity | Service |
|---|---|---|
| Application Domain | `Domain` | (root); optional sub-domain via `omDomainParentMap` |
| Application Version | `Pipeline` | `solace-event-portal-apps` (CustomPipeline) |
| Event Version | `Topic` | the configured MessagingService |
| Schema Version | `Table` (columns from parsed fields) | `solace-event-portal-schemas` (CustomDatabase) |
| Event API Version | `Container` | `solace-event-portal-event-apis` (CustomStorage) |
| Event API Product Version | `DataProduct` with `assets[]` | (root) |
| `consumers[]` entry | `Container` | `solace-event-portal-consumers` (CustomStorage) |
| Topic-address segment | nested `Container` chain | `solace-event-portal-topic-tree` (CustomStorage) |
| Lifecycle state | `EventPortal.{Draft,Released,Deprecated,Retired,Application}` tag | (classification) |
| EP Custom Attribute | `EventPortalCustomAttribute_<name>.<value>` tag | (classification, auto-discovered) |
| Modeled Event Mesh | `DataProduct` (when edition supports it) | feature-flag `emitDataProducts`, default OFF |

Lineage edges:

- Pipeline (App) to / from Topic per
  `declaredProduced` / `declaredConsumed` event-version IDs.
- Container (Event API) to / from Topic per
  `producedEventVersionIds` / `consumedEventVersionIds`.
- Topic to Container (Consumer Queue) per
  `attractedEventVersionId`; Container to Pipeline for the owning
  consuming app.
- Container (Topic-tree leaf segment) to Topic at the deepest
  in-cap segment.
- Table (Schema) to Topic per `schemaVersionId`.
- Pipeline to Pipeline within EP via
  `inbound/outboundApplicationVersionAssociations` (EP Linked Apps).
- Cross-system edges from a YAML mapping (`lineageEdges` option) +
  external-system fallback via EP Custom Attributes
  (`externalSourceOmFqn` / `externalSinkOmFqn`).

Custom property keys are stable contract; see
`connector/property_keys.py`.

## One-time: bootstrap OpenMetadata

Before the first ingestion or bridge run, register the EventPortal
classification + tags, all custom-property definitions, and the
synthetic services the connector relies on. Idempotent; safe to
re-run after every deployment.

```bash
om-eventportal-bootstrap \
  --host-port http://openmetadata-server:8585/api \
  --jwt-token "$OM_INGESTION_BOT_TOKEN" \
  --ep-token "$EP_API_TOKEN"   # optional: enables CA auto-discovery
```

Bootstrap creates:

- Classification `EventPortal` with tags `Draft`, `Released`,
  `Deprecated`, `Retired`, `Application`.
- All `eventPortal*` custom properties on `Topic`, `Pipeline`,
  `Container`, `DataProduct`, and `Table` types.
- Synthetic services:
  `solace-event-portal-apps` (PipelineService / CustomPipeline),
  `solace-event-portal-event-apis` (StorageService / CustomStorage),
  `solace-event-portal-consumers` (StorageService),
  `solace-event-portal-topic-tree` (StorageService),
  `solace-event-portal-schemas` (DatabaseService / CustomDatabase)
  with a single `schemas` Database underneath.
- When `--ep-token` is supplied: one `EventPortalCustomAttribute_*`
  Classification per EP custom-attribute definition found via
  `/architecture/customAttributeDefinitions`.

## Install: pull connector

Bake into a custom `openmetadata-ingestion` image:

```bash
bash scripts/build-and-push.sh
# Builds + pushes
#   registry.solace.lab/openmetadata-ingestion-solace:<pyproject version>
# and (latest tag).
```

The OM Airflow deployment then points at that tag via
`openmetadata-deployment/local-k8s-deps-values.yaml`
(`airflow.images.airflow.tag` + `airflow.images.pod_template.tag`).

Or install into an existing Python ingestion env:

```bash
pip install -e .
```

## Configure: pull connector

1. In Event Portal, generate an API token with read permission on
   the target application domains.
2. In OpenMetadata: Settings -> Services -> Messaging -> Add New
   Service -> Custom Messaging.
3. Set:

   - **Source Python Class Name**
     `connector.event_portal_connector.SolaceEventPortalSource`
   - **Connection Options**: see table below.

Connection options (most users only set `apiUrl`, `apiToken`, and
the four `*FilterPattern` options):

| Option | Default | Description |
|---|---|---|
| `apiUrl` | `https://api.solace.cloud/api/v2` | EP REST base URL |
| `apiToken` | *(required)* | Bearer token. Use `secret:<name>` to pull from OM secrets. |
| `domainFilterPattern` | `{}` (default-deny) | JSON `{includes:[regex...], excludes:[regex...]}`. Empty includes => zero domains ingested. |
| `eventFilterPattern` | `{}` (default-deny) | Same shape; filters event names. |
| `schemaFilterPattern` | `{}` (default-deny) | Same shape; filters schemas attached to Topics + emitted as Tables. |
| `applicationFilterPattern` | `{}` (default-deny) | Same shape; filters apps that become Pipelines. |
| `includeLineage` | `true` | Emit App <-> Topic + container lineage edges |
| `ingestAllVersions` | `true` | Emit one Topic / Pipeline per version (Wave 1 flipped on). |
| `emitDomains` | `true` | Emit OM `Domain` per EP application domain |
| `emitDataProducts` | `false` | Emit `DataProduct` per modeled event mesh (Cloud Enterprise: 404 since the endpoint is missing). |
| `emitEventApis` | `true` | Emit Containers + lineage for EP Event APIs (Wave 3 / `#44`) |
| `emitEventApiProducts` | `true` | Emit DataProducts for EP Event API Products (Wave 3 / `#45`) |
| `emitSchemas` | `true` | Promote EP Schemas to first-class Tables (Wave 3 / `#52`) |
| `emitTopicTree` | `true` | Materialise topic-address tree as Containers (Wave 3 / `#53`) |
| `topicTreeMaxDepth` | `3` | Depth cap for the topic-tree Containers |
| `emitConsumers` | `true` | Emit Container per `consumers[]` entry (Wave 3 / `#55`) |
| `resolveOwners` | `true` | Resolve EP owner IDs to OM users (Wave 4 / `#57`) |
| `userIdToEmailMap` | `{}` | Static EP-user-ID to email map; dict OR `id1:email1,id2:email2`. |
| `omDomainParentMap` | `{}` | Static EP-domain-name to OM Domain FQN map for sub-domain hierarchy (Wave 4 / `#48`). |
| `customAttributeTagExclude` | `""` | Comma-separated EP CA names to skip during auto-discovery. |
| `tenantPrefix` | `""` | Multi-tenant: prefix for the shared synthetic services so two EP tenants do not collide (Wave 5 / `#41`). Empty = single-tenant. |
| `piiCaName` | `""` | PII signal: EP Custom Attribute name(s) that mark an entity PII (Wave 5 / `#62`). Single value, comma list, or list. |
| `piiTagNames` | `""` | PII signal: EP/OM tag name(s) that mark an entity PII. |
| `piiTopicSegmentPattern` | `""` | PII signal: regex over the topic address that marks a Topic PII. |
| `asyncApiVersion` | `2.5.0` | AsyncAPI spec version in the Pipeline `sourceUrl` |
| `asyncApiFormat` | `json` | AsyncAPI doc format in the Pipeline `sourceUrl` |
| `epConsoleUrl` | `https://console.solace.cloud` | Base URL for the markdown back-links to the EP UI |
| `since` | *(empty)* | ISO timestamp for incremental runs |
| `sampleDataEnabled` | `false` | Subscribe to broker and capture last N messages per Topic |
| `brokerHost` | *(empty)* | Solace broker URL (`tcp://`, `tcps://`, `ws://`, `wss://`) |
| `brokerVpn` | `default` | Solace VPN |
| `brokerUsername` | *(empty)* | Broker auth user |
| `brokerPassword` | *(empty)* | Broker auth password |

See `config/example-workflow.yaml` for a full workflow definition.

## Install: webhook bridge

```bash
# Convenience wrapper (tags from pyproject.toml, pushes to the registry):
bash scripts/build-bridge-image.sh
# Or directly:
docker build -f Dockerfile.bridge -t my-org/om-eventportal-bridge:0.9.0 .
```

Or install in a venv:

```bash
pip install '.[bridge]'                # HTTP + polling only
pip install '.[bridge,bridge-solace]'  # also Solace transport
```

## Configure: webhook bridge

Copy `config/bridge.example.env` to `.env` and fill in. Then start
the bridge:

```bash
# Polling mode (default; works against Solace Cloud EP v2)
python -m bridge.main

# HTTP webhook receiver (only if your EP edition supports outbound
# webhooks; Solace Cloud Enterprise does NOT)
BRIDGE_MODE=http python -m bridge.main

# Solace consumer (when a forwarder publishes EP payloads onto a queue)
BRIDGE_MODE=solace python -m bridge.main

# Forwarder: receive EP webhooks, publish raw payload onto Solace
BRIDGE_MODE=forwarder python -m bridge.main
```

CLI sub-commands:

```bash
# One-shot full-pull reconciliation (catch up after an outage)
python -m bridge.main --reconcile
python -m bridge.main --reconcile --since 2026-05-17T00:00:00Z

# Soft-delete drift pass: tag OM entities missing on EP as Retired
# (Wave 4 / #61). Idempotent; safe to run on a cron.
python -m bridge.main --soft-delete-missing
python -m bridge.main --soft-delete-missing --auto-purge-after-days 30

# Register the bridge URL with EP as a webhook target (one-shot;
# noop on EP editions without outbound webhooks)
python -m bridge.main \
  --register-webhook https://bridge.example.com/webhook/event-portal
```

### Polling vs webhook vs Solace transport

- **`polling`** (default) — bridge polls the EP REST API on an
  interval. The only transport that works against Solace Cloud EP
  today. Same idempotent handler set as the other transports.
- **`http`** — EP posts directly to the bridge; the bridge applies
  the delta to OpenMetadata. Requires outbound EP webhooks (not
  available on Solace Cloud Enterprise as of 2026-05).
- **`forwarder` + `solace`** — run two bridge containers: a
  `forwarder` (verifies the signature and republishes the raw
  payload onto `om/sync/eventportal/<eventType>`) and a `solace`
  consumer. Persistent queues absorb OM downtime; every EP change
  is auditable on your mesh.

You can run `http` and `solace` consumers at once for
belt-and-braces; the dedupe cache prevents double application as
long as `eventId` is stable across transports.

### Reconciliation strategy

Three complementary mechanisms:

1. **Full pull** — the standard ingestion workflow scheduled daily
   with `since=<yesterday>` overwrites anything the bridge missed
   between polls.
2. **`--reconcile`** — re-pulls since the watermark stored as
   `eventPortalAuditWatermark` on the MessagingService.
3. **`--soft-delete-missing`** — drift-diff against EP, tags
   missing OM entities with `EventPortal.Retired` and
   `eventPortalDeletedAt` (Wave 4 / `#61`). Optional
   `--auto-purge-after-days N` hard-deletes once the tombstone
   ages past the cutoff.

## Cross-system lineage to Kafka / Snowflake / Databricks

Wave 2 wired two paths:

1. **YAML-driven** — declare cross-system edges in the workflow
   YAML via the `lineageEdges` option (see
   `docs/asset-mapping-spec.md` Cluster 2.5 for the shape). The
   `EventPortalLineageSource` resolves both FQNs via OM and emits
   one `AddLineageRequest` each.
2. **EP CA fallback** — when no auto-link hit, set the
   `externalSourceOmFqn` / `externalSinkOmFqn` custom attributes on
   the originating EP entity. The bridge looks them up in OM and
   emits the edge.

Databricks Spark Structured Streaming via
`pubsubplus-connector-spark` is still not auto-discoverable from
OM; the recommended companion is a small workflow that introspects
the Databricks job for the Solace topic + Delta table, then calls
OM's `/v1/lineage` API. Reference implementation tracked in the
implementation plan.

## Production hardening (Wave 5)

### Multi-tenant deployment (`#41`)

Two EP tenants can share one OpenMetadata instance. Each tenant runs
its own ingestion workflow with a distinct `serviceName` (isolates the
MessagingService + every Topic FQN) and a distinct `tenantPrefix`
(isolates the five shared synthetic services). Bootstrap once per
tenant with the matching prefix:

```bash
om-eventportal-bootstrap --host-port "$OM_HOST_PORT" \
  --jwt-token "$OM_INGESTION_BOT_TOKEN" --tenant-prefix tenant-b
```

An empty prefix is byte-identical to single-tenant, so the existing
deployment is unaffected. See `config/example-workflow-tenant-b.yaml`.
Known boundary: OM Domains + DataProducts are global (not under a
service), so two tenants sharing an EP domain name co-locate there by
design.

### PII handling (`#62`)

A Topic / Pipeline is flagged PII when any declarative signal fires:
an EP Custom Attribute name (`piiCaName`), an EP/OM tag (`piiTagNames`),
a topic-address regex (`piiTopicSegmentPattern`), or a schema field
annotated `x-pii`. A flagged entity gets the `EventPortalCompliance.PII`
tag + the `eventPortalContainsPii` custom property, x-pii columns get a
`[PII]` marker, and the live sample-data subscribe is HARD-BLOCKED for
that Topic (PII payloads are never captured). Detection is read-only
against EP and off until at least one signal is configured. Bootstrap
creates the `EventPortalCompliance` classification + `PII` tag.

### Observability (`#11` / `#63` / `#10` / `#13`)

Bridge-process knobs, all `BRIDGE_OBS_*` env (see `bridge/config.py`):

- `BRIDGE_OBS_LOG_FORMAT=json` — structured JSON logs with a
  per-tick / per-event `correlation_id` (and `trace_id` when tracing
  is on).
- `BRIDGE_OBS_OTEL_ENABLED=true` (+ `BRIDGE_OBS_OTEL_ENDPOINT`) —
  OpenTelemetry spans on the poll tick + each dispatch, OTLP/HTTP.
- `BRIDGE_OBS_METRICS_ENABLED=true` (+ `BRIDGE_OBS_METRICS_PORT`) —
  Prometheus `/metrics` (dispatch latency, poll ticks, events
  seen / dispatched, EP 401s).
- `BRIDGE_OBS_SHUTDOWN_GRACE_SECONDS` — SIGTERM drains the current
  tick + flushes dedupe before exit.

The connector-in-ingestion path is unchanged: these are opt-in extras
with no-op fallbacks, so OM's own run report and logging are untouched.

### Helm chart (`#15`)

`charts/solace-eventportal-bridge` packages the bridge image with the
surfaces above. Build + push the image, then install:

```bash
bash scripts/build-bridge-image.sh
helm install ep-bridge charts/solace-eventportal-bridge \
  --set secret.epApiToken="$EP_API_TOKEN" \
  --set secret.omJwtToken="$OM_JWT_TOKEN" \
  --set observability.metrics.enabled=true \
  --set cron.softDelete.enabled=true
```

Probes are mode-gated (polling has no HTTP server, so it never
crashloops); set `secret.existingSecret` to use a Vault-synced Secret
instead of chart-managed token values. See `values.yaml` for the full
surface (OTel sidecar, lab CA mount, CronJob schedules).

## Operating in production

- `docs/operations.md` -- the production runbook: deploy, the full
  configuration reference, metrics to scrape + alert on, the routine
  cron jobs, the write-back shadow-deploy go-live procedure, token
  rotation, troubleshooting, and the Beta release sequence.

## Development

```bash
# Lint
pipx run --spec=ruff ruff check connector tests bridge

# Tests (3 skipped locally because openmetadata-ingestion is only
# present inside the built image)
python -m pytest tests --ignore=tests/test_connector_helpers.py -q

# Markdown lint
npx --yes markdownlint-cli CLAUDE.md README.md docs/
```

See `CLAUDE.md` for the full coding conventions and the
"continue in another session" pickup checklist.

## Limitations and roadmap

- **EP Teams to OM Teams** — BLOCKED. EP v2 Cloud Enterprise
  exposes no team API (smoke-tested 2026-05-27). Tracked as
  ticket `#58`.
- **OM to EP write-back** — IMPLEMENTED (Wave 4.5 / `#49`), OFF +
  dry-run by default. `BRIDGE_MODE=writeback` receives OM
  EntityChangeEvents and pushes OM-owned governance fields back as EP
  custom attributes per the Cluster 5 per-field policy. Live writes need
  `BRIDGE_WB_ENABLED=true` + `BRIDGE_WB_DRY_RUN=false` + the separate
  `EP_WRITER_TOKEN`; the exact EP write contract must be verified under
  shadow deploy first.
- **Modeled Event Mesh** — Cloud Enterprise returns 404 for
  `/architecture/modeledEventMeshes` (Cluster 1.3); feature flag
  `emitDataProducts` stays default OFF.
- **PII detection / OTel telemetry / multi-tenant / Helm chart** —
  SHIPPED in Wave 5 / image `0.9.0` (see "Production hardening" above).
- **v1.0 GA + ALDI prod cutover, and the OpenMetadata upstream
  contribution** — DROPPED / out of scope. The `0.9.0` line is the
  Beta; the roadmap ends here.

Full delivery record: `docs/implementation-plan.md`.
