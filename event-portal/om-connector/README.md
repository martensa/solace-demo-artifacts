# OpenMetadata Solace Event Portal Connector + Webhook Bridge

Two cooperating components that govern an Event Portal estate from
OpenMetadata:

- **Pull connector** (`connector/`) — a custom OpenMetadata Source.
  Ingests application domains as **Data Domains**, events as **Topics**
  (with schema, lifecycle state, topic address, modeled-mesh membership),
  modeled event meshes as **Data Products**, and emits real
  **lineage edges** between applications and topics. Runs on the standard
  ingestion schedule and also serves as the daily reconciliation pass.
- **Webhook bridge** (`bridge/`) — a small FastAPI / Solace consumer
  service. Subscribes to Event Portal change webhooks, verifies the HMAC
  signature, dedupes, and pushes the deltas into OpenMetadata through
  the same mappers the pull connector uses. Two transports ship out of
  the box:
  - **HTTP**: Event Portal posts directly to the bridge.
  - **Solace**: an upstream forwarder publishes EP payloads onto a
    Solace queue; the bridge consumes from the queue. Resilient, replay-
    able, and uses your existing mesh as the audit trail.

## Architecture

```text
Event Portal v2 ─┐
   REST API      ├─► EventPortalClient ─► Pull connector ─► ometa SDK ─► OpenMetadata
   Webhooks      │                                          (also: reconcile)   ▲
   Audit feed   ─┤                                                              │
                 │   ┌──────────────────────┐  HTTP                             │
                 ├──►│ bridge (HTTP)        ├────────────────────────────────────┤
                 │   └──────────────────────┘                                    │
                 │                                                               │
                 │       ┌─────────────────────┐ publish   ┌────────────────────┐│
                 └──────►│ bridge (forwarder)  ├──────────►│ bridge (Solace)    ├┘
                         └─────────────────────┘  queue    └────────────────────┘
```

All three roles are the same image (`Dockerfile.bridge`); pick the role
with `BRIDGE_MODE=http|solace|forwarder`.

## Mapping

| Event Portal                     | OpenMetadata (1.6+)                                              |
| -------------------------------- | ---------------------------------------------------------------- |
| Application Domain               | `Domain` entity (+ owner from EP, resolved to OM user)           |
| Modeled Event Mesh               | `DataProduct` entity                                             |
| Event Version                    | `Topic` (+ owner)                                                |
| Topic Address                    | `Topic.description` + `eventPortalTopicAddress`                  |
| Schema (JSON / Avro / Proto/XSD) | `Topic.messageSchema` with recursive `schemaFields`              |
| Lifecycle state                  | Tag (`EventPortal.Draft`/`Released`/...) + Custom Property       |
| Application Version              | `Pipeline` entity under PipelineService `solace-event-portal-apps` |
| Application publishes Y          | Lineage edge: Pipeline → Topic                                   |
| Application consumes Y           | Lineage edge: Topic → Pipeline                                   |
| Modeled mesh membership          | Custom property `eventPortalModeledMeshIds`                      |
| Live messages (opt-in)           | `Topic.sampleData` (via Solace SMF subscribe)                    |

Custom property keys are stable contract — see
[connector/property_keys.py](connector/property_keys.py).

### Compatibility

| Connector | OpenMetadata | Notes                                                  |
| --------- | ------------ | ------------------------------------------------------ |
| 0.3.x     | 1.6 – 1.7    | Pipeline-Entity mapping requires OM >= 1.5             |
| 0.2.x     | 1.6          | Pre-Pipeline: apps modeled as synthetic Topics         |
| 0.1.x     | 1.5 – 1.6    | Initial scaffolding, no filter patterns                |

### Migration from 0.2.x → 0.3.x

EP applications are now `Pipeline` entities, not synthetic Topics. After
upgrading:

1. `om-eventportal-bootstrap …` — creates the new `solace-event-portal-apps`
   PipelineService and the Pipeline custom properties.
2. Run the ingestion workflow once with the new release.
3. Manually soft-delete the old synthetic Topics in OM (Topics named
   `app_*_v*` under your Messaging service). They're orphans now —
   their lineage was migrated to the new Pipeline entities.

## One-time: bootstrap OpenMetadata

Before the first ingest or webhook delivery, register the EventPortal
classification + tags and the custom-property definitions the connector
relies on. The script is idempotent — safe to re-run after every
deployment.

```bash
# from a container with `openmetadata-ingestion` installed (e.g. the
# custom ingestion image you build below, or the bridge image)
om-eventportal-bootstrap --host-port http://openmetadata-server:8585/api \
                         --jwt-token "$OM_INGESTION_BOT_TOKEN"
```

Creates:
- Classification `EventPortal` with tags `Draft`, `Released`,
  `Deprecated`, `Retired`, `Application`.
- All `eventPortal*` custom properties on `Topic` (see
  [connector/property_keys.py](connector/property_keys.py)).
- `eventPortalAuditWatermark` custom property on `MessagingService`
  (used by the reconciliation job).

## Install — pull connector

Bake into a custom `openmetadata-ingestion` image:

```bash
docker build -t my-org/openmetadata-ingestion-solace:1.6.0 .
# Reference in your OM deployment, e.g. docker-compose:
#   ingestion:
#     image: my-org/openmetadata-ingestion-solace:1.6.0
```

Or install into an existing Python ingestion env:

```bash
pip install -e .
```

## Configure — pull connector

1. In Event Portal, generate an API token with `read` permission on the
   target application domains.
2. In OpenMetadata: **Settings → Services → Messaging → Add New Service →
   Custom Messaging**.
3. Set:
   - **Source Python Class Name** —
     `connector.event_portal_connector.SolaceEventPortalSource`
   - **Connection Options** — see table below.

| Option                     | Default                              | Description                                                                                 |
| -------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------- |
| `apiUrl`                   | `https://api.solace.cloud/api/v2`    | Event Portal REST base                                                                      |
| `apiToken`                 | *(required)*                         | Bearer token. Use `secret:<name>` to pull from OM secrets.                                  |
| `mode`                     | `rest_api`                           | `rest_api` or `asyncapi`                                                                    |
| `domainFilterPattern`      | `{}` (default-deny)                  | JSON `{includes:[regex...], excludes:[regex...]}`. Allow-list-only: empty includes -> none. |
| `eventFilterPattern`       | `{}` (default-deny)                  | Same shape; filters event names within matched domains.                                     |
| `schemaFilterPattern`      | `{}` (default-deny)                  | Same shape; controls which schemas are attached to Topics.                                  |
| `applicationFilterPattern` | `{}` (default-deny)                  | Same shape; controls which apps become Pipelines + lineage.                                 |
| `includeLineage`           | `true`                               | Emit App ↔ Topic lineage edges                                                              |
| `ingestAllVersions`        | `false`                              | Emit a Topic / Pipeline per version (otherwise latest only)                                 |
| `emitDomains`              | `true`                               | Emit OM `Domain` per EP application domain                                                  |
| `emitDataProducts`         | `true`                               | Emit OM `DataProduct` per modeled event mesh                                                |
| `resolveOwners`            | `true`                               | Resolve EP owner e-mails to OM users (Keycloak identity)                                    |
| `since`                    | *(empty)*                            | ISO timestamp for incremental runs                                                          |
| `sampleDataEnabled`        | `false`                              | If true, subscribe to broker and capture last N messages per Topic                          |
| `brokerHost`               | *(empty)*                            | Solace broker URL (`tcp://`, `tcps://`, `ws://`, `wss://`)                                  |
| `brokerVpn`                | `default`                            | Solace VPN                                                                                  |
| `brokerUsername`           | *(empty)*                            | Broker auth user                                                                            |
| `brokerPassword`           | *(empty)*                            | Broker auth password                                                                        |

See [`config/example-workflow.yaml`](config/example-workflow.yaml) for a
full ingestion workflow definition.

## Install — webhook bridge

```bash
docker build -f Dockerfile.bridge -t my-org/om-eventportal-bridge:0.1.0 .
```

Or install in a venv:

```bash
pip install '.[bridge]'             # HTTP only
pip install '.[bridge,bridge-solace]'  # also Solace transport
```

## Configure — webhook bridge

Copy [`config/bridge.example.env`](config/bridge.example.env) to `.env`
and fill in. Then either:

```bash
# HTTP mode — bridge listens on :8080 for EP webhook posts
python -m bridge.main

# Solace mode — bridge subscribes to the configured queue
BRIDGE_MODE=solace python -m bridge.main
```

### Registering the webhook with Event Portal

Once the bridge is reachable from EP (HTTP mode only), register the
subscription with one command:

```bash
python -m bridge.main --register-webhook https://bridge.example.com/webhook/event-portal
```

The command creates a webhook subscription, scoping to the event types
the bridge knows about (`event.*`, `eventVersion.*`, `schema.*`,
`application.*`, `applicationDomain.*`).

### Picking a transport

- **`http`** — simplest. EP posts directly to the bridge; the bridge
  applies the delta to OpenMetadata. Requires a public (or
  VPN-reachable) HTTPS endpoint. Loses webhook payloads if the bridge
  or OM is down longer than EP's retry window.
- **`forwarder` + `solace`** — run two bridge containers: a
  `forwarder` (publicly reachable; verifies the signature and republishes
  the raw payload onto `om/sync/eventportal/<eventType>`) and a `solace`
  consumer (subscribes to a durable queue, applies to OM). Persistent
  queues absorb OM downtime; every EP change is auditable on your mesh.
  Trade-off: extra hop + extra container.

You can run `http` and `solace` consumers at once for belt-and-braces;
the dedupe cache prevents double application as long as `eventId` is
stable across transports.

### Reconciliation

Two complementary mechanisms:

1. **Audit replay** (`--reconcile`) — the bridge reads the EP audit
   feed since its persisted watermark, replays each change through the
   live handler set, and advances the watermark on success. Cheap; run
   it whenever the bridge has been offline.

   ```bash
   om-eventportal-bridge --reconcile                          # since last run
   om-eventportal-bridge --reconcile --since 2026-05-17T00:00:00Z
   ```

   The watermark is stored as a custom property
   (`eventPortalAuditWatermark`) on the `MessagingService` entity — that
   property is created by the bootstrap script.

2. **Full pull** — the standard ingestion workflow remains the
   authoritative reconciliation pass. Schedule it daily with
   `since=<yesterday>` to overwrite anything the bridge missed.

## Lineage to Databricks

Lineage between Solace Topics and Databricks Delta tables is not emitted
by this connector — that bridge runs at runtime through the
`pubsubplus-connector-spark` Spark Structured Streaming connector, which
OM cannot see directly.

The recommended pattern is a small companion workflow that:

1. Lists Databricks notebooks / jobs that import
   `solacecoe.connectors.spark`.
2. Parses the `host`, `vpn`, and queue / topic subscription from the
   Spark options to resolve the Event Portal Topic FQN.
3. Reads the `writeStream` sink to resolve the Delta table FQN.
4. Calls OM's `/v1/lineage` API to add the edge.

A reference implementation lives at
`scripts/emit_databricks_lineage.py` *(planned — not in this
scaffolding)*.

## Limitations and roadmap

- **Applications as entities.** OM has no `Application` entity yet, so
  apps are modeled as a synthetic Topic tagged
  `EventPortal.Application`. Switch to `CreateApplicationRequest` once
  OM ships first-class support.
- **Multi-version ingestion** (`ingestAllVersions`) is implemented for
  events but not yet for applications.
- **Event Portal webhook payload schema** is verified against EP Cloud;
  on-prem editions may emit slightly different `eventType` strings. The
  bridge's `DEFAULT_HANDLERS` table is the one place to extend.
- **HA dedupe**: the in-memory dedupe store is single-replica only. For
  multi-replica deployments swap in `RedisDedupeStore`
  (see [`bridge/dedupe.py`](bridge/dedupe.py)).

## Development

```bash
pip install -e '.[dev,bridge]'
pytest                       # signature + dispatcher + dedupe tests
pytest tests/test_mappers.py # skipped unless openmetadata-ingestion installed
```
