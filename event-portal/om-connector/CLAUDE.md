# CLAUDE.md — Solace Event Portal OpenMetadata Connector

## Mission

A custom OpenMetadata ingestion connector that imports Solace Event Portal
metadata as a Messaging Service. Event Portal is the system of record;
this connector reads from it and emits OM entities (Topics, schemas, tags,
lineage). Read-only against Event Portal — never PUT/POST/DELETE on the
Event Portal side.

## Stack

- Python 3.9+
- `openmetadata-ingestion` SDK (the `metadata.ingestion.api.steps.Source`
  base class is what we extend)
- `requests` + `urllib3` retry adapter for the REST client
- `pyyaml` for AsyncAPI parsing
- `pytest` + `responses` for unit tests
- `ruff` for lint

## Repo layout

```
connector/
  event_portal_client.py    REST client; paginated, retrying, dict returns
  event_portal_connector.py Source subclass; the OM ingestion entry point
  mappers.py                Pure functions: Event Portal payload -> CreateTopicRequest
  asyncapi_parser.py        Alt ingestion mode for AsyncAPI 2.x specs
config/
  example-workflow.yaml     Sample `metadata ingest -c` workflow
Dockerfile                  Bakes the connector into openmetadata/ingestion
pyproject.toml
```

## Commands

```bash
# Lint + test
pytest -q && ruff check .

# Build the ingestion image
docker build -t my-org/openmetadata-ingestion-solace:1.6.0 .

# Run a one-shot ingestion against a workflow YAML
metadata ingest -c config/example-workflow.yaml

# Local OpenMetadata stack (assumed in a sibling repo for now)
make -C ../openmetadata-compose up
```

## Architecture in one paragraph

The connector registers as a `CustomMessaging` service. Pass 1 walks Event
Portal application domains, lists events, fetches the latest event version
per event (or every version if `ingestAllVersions=true`), resolves the
schema, and emits a `CreateTopicRequest`. The Topic FQN encodes
`<service>.<domain>.<event>_v<version>`. Pass 2 walks applications and
attaches pub/sub references to topics via custom properties — proper
lineage entities are a later iteration. A separate companion workflow
emits `Topic -> Delta table` lineage by parsing Spark jobs that use
`pubsubplus-connector-spark`; that lives outside this repo.

See README for the full architecture and entity mapping table.

## Coding conventions

- Prefer dict access for Event Portal payloads, not pydantic models. The
  Event Portal API ships new fields frequently and brittle typed models
  hurt more than they help here.
- Mappers must be pure functions of their inputs (no I/O, no global
  state). The REST client is the only place that touches the network.
- Error handling in `_iter` yields `Either(left=StackTraceError(...))` —
  one failure should not abort the whole ingestion run.
- Use `sanitize()` from `mappers.py` for anything that goes into an OM
  FQN. OM is strict about characters allowed in FQNs.
- Logging: `logging.getLogger(__name__)`, never `print`. INFO for
  per-domain counts, DEBUG for per-entity detail.

## OpenMetadata SDK notes

- Import paths are versioned by `metadata.generated.schema.*`. If a class
  isn't where you expect, check `pip show openmetadata-ingestion` for the
  installed version and search the site-packages tree.
- `MessageSchema` requires `schemaType` from the `SchemaType` enum; values
  outside the enum cause silent skips.
- `partitions` is a required field on `CreateTopicRequest` even though
  Solace topics aren't partitioned. We hardcode `1`.
- The `OpenMetadata` client supports a `patch` method for partial updates
  via JSON Patch. The scaffolding's `_patch_topic_with_app` is a
  placeholder — replace with the real signature, which is roughly
  `metadata.patch(entity=Topic, source=existing, destination=updated)`.
- For lineage, use `AddLineage` requests against `/v1/lineage`. Both
  endpoints (fromEntity, toEntity) must already exist before the edge
  request is sent.

## Event Portal API notes

- Base URL: `https://api.solace.cloud/api/v2`
- Auth: `Authorization: Bearer <token>` from My Account -> Token Management
- All resource endpoints live under `/architecture/`
- Pagination: `pageNumber` + `pageSize` query params; response meta carries
  `meta.pagination.totalPages`. Some endpoints (notably *Versions
  endpoints) have caps on page size — keep page_size <= 100.
- Lifecycle state field is `stateId` on v2 endpoints, `state` on v1; the
  connector reads both for forward compatibility.
- Topic addresses are reconstructed from `deliveryDescriptor.address.addressLevels`
  — see `extract_topic_address` in mappers.py.
- Use the Event Portal MCP server (if connected) to fetch live payload
  shapes when uncertain — never invent field names.

## Open TODOs (priority order)

1. Replace the illustrative `_patch_topic_with_app` with the real
   `OpenMetadata.patch` call.
2. Verify pagination envelope assumptions against the real API — some
   endpoints return `nextPageUri` instead of `totalPages`.
3. Recurse into nested JSON Schema `properties` and Avro `fields` so
   nested SchemaFields are emitted (currently top-level only).
4. Add `since` (ISO timestamp) for incremental runs using Event Portal's
   `updatedTime` filter.
5. Pytest fixtures for: one published event, one consumed event, one
   event with no schema, JSON Schema + Avro paths.
6. Migrate pub/sub from custom properties to proper lineage edges with
   synthetic Application peer entities (decide pattern first).
7. AsyncAPI mode: end-to-end test against a real Event Portal AsyncAPI
   export.
8. Companion script for Databricks lineage (out of repo for now).

## What this connector deliberately does NOT do

- Configure event brokers (read-only)
- Write back to Event Portal (read-only)
- Manage authentication beyond Bearer tokens (no OAuth flow)
- Model Event Portal's Modeled Event Mesh as a first-class OM entity (we
  use a custom property instead)
- Emit lineage to Databricks tables (separate companion workflow)

## When in doubt

- For Event Portal payload shapes, use the Event Portal MCP server or
  curl against the live API. Don't guess.
- For OM SDK signatures, read the installed package source, not blog
  posts (the SDK churns).
- For OM FQN rules, look at how the Kafka connector builds them
  (`openmetadata-ingestion/src/metadata/ingestion/source/messaging/kafka/`).
