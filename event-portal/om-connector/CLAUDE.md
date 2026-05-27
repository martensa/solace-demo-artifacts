# CLAUDE.md — Solace Event Portal OpenMetadata Connector

## Mission

A production-ready OpenMetadata ingestion connector that imports Solace
Event Portal metadata as a Messaging Service, with cross-system lineage
(EP -> Kafka/Snowflake/Databricks/SAP) and bi-directional sync of
governance metadata (OM-side enrichments flow back to EP as Custom
Attributes). Customer anchor: ALDI Nord (Cloud Enterprise, 2 tenants,
EU). Target: v1.0.0 GA in 10 weeks; OM upstream contribution in the
following quarter.

EP is the system of record for EDA models (events, schemas, applications,
topic-addresses, pub/sub declarations). OM enriches it with extended
descriptions, classifications, certification, owners, and cross-system
lineage to non-EP entities. Per-field source-of-truth policy lives in
`docs/asset-mapping-spec.md` (Cluster 5 table).

## Stack (target for v1.0)

- Python 3.10+ (OM 1.11 dropped 3.9)
- `openmetadata-ingestion >= 1.11.5, < 1.13` (pin upper bound below
  1.13 until 1.13 GA on PyPI; today's latest stable is 1.12.8.9)
- `metadata.parsers.{avro_parser,json_schema_parser,protobuf_parser}` —
  USE OM's built-in schema parsers, don't reimplement
- `requests` + `urllib3` retry adapter for the REST client
- `pyyaml` for AsyncAPI parsing (private-build only — not part of
  upstream contribution)
- `pytest` + `responses` for unit tests (OM upstream uses `responses`)
- `ruff` (line-length=120 to match OM upstream, target-version=py310)
- `opentelemetry-sdk` + `opentelemetry-exporter-otlp` for telemetry
  (Wave 5 / #63)

## Repo layout (target after Wave 2 ServiceSpec split)

```
connector/
  service_spec.py            DefaultMessagingSpec registration
  event_portal_client.py     REST client; paginated, retrying, dict returns
  metadata_source.py         EventPortalMetadataSource — entities pass
  lineage_source.py          EventPortalLineageSource — cross-system edges pass
  mappers.py                 Pure functions: EP payload -> OM Create*Request
  schema_parser.py           Thin dispatcher around metadata.parsers.*
  filters.py                 Allow-list filter pattern
  owner_resolver.py          userIdToEmailMap lookup
  bootstrap.py               Bootstrap classifications, CAs, services
  property_keys.py           Stable constants
bridge/
  main.py                    Bridge entrypoint
  transport/polling.py       EP polling-mode (no webhooks available)
  writeback.py               (Wave 4 / #49) OM -> EP write-back
  reconcile.py               Drift detection + soft-delete (#61)
  handlers.py                Bridge event handlers
config/
  example-workflow.yaml      Sample `metadata ingest -c` workflow
docs/
  asset-mapping-spec.md       Living mapping spec (per-cluster decisions)
  discovery-closure-summary.md ALDI discovery sign-off envelope
  implementation-plan.md      7-wave delivery plan
  workshop-demo-script.md     Pilot demo walkthrough
  EP-edition-compatibility.md Per-EP-edition endpoint matrix
Dockerfile                    Bakes the connector into openmetadata/ingestion
pyproject.toml
```

## Commands

```bash
# Lint + test
pytest -q && ruff check .

# Build the ingestion image (Wave 0 bumps base to 1.11.x)
docker build -t registry.solace.lab/openmetadata-ingestion-solace:0.4.0 .

# Run a one-shot ingestion against a workflow YAML
metadata ingest -c config/example-workflow.yaml

# Bootstrap OM with EP classifications + custom properties
om-eventportal-bootstrap --jwt <om-jwt> --host-port http://om-server:8585

# Smoke-test EP API (set EP_API_TOKEN with leading-space in shell)
 export EP_API_TOKEN='...'
python scripts/smoke_ep_api.py
```

## Architecture in one paragraph (target Wave 6)

The connector registers as a first-class `MessagingService` enum value
(`EventPortal`) — drop the `CustomMessaging` workaround used in the
pilot. Two Source classes wired via `ServiceSpec`:
**EventPortalMetadataSource** emits Domains, Topics (with parsed
SchemaFields), Pipelines (per EP Application), Containers (per EP
consumer-queue, per Event-API, per topic-address segment, per
classified external system), DataProducts (per EAPP), and first-class
Schema entities. **EventPortalLineageSource** runs separately and emits
within-EP Linked-Apps edges (#59), external-system edges via either
naming-classification (#65) or EP CA fallback (#60), and cross-system
edges from a YAML mapping (#50 v1.0) / auto-discovery (v1.1). A
companion **bridge** runs in polling-mode (EP exposes no outbound
webhooks), with an optional **writeback** component that subscribes to
OM EntityChangeEvents and PUTs OM-owned fields back to EP as Custom
Attributes (#49).

## Coding conventions

- Prefer dict access for Event Portal payloads, not pydantic models.
  The EP API ships new fields frequently; brittle typed models hurt
  more than help.
- Mappers must be pure functions of their inputs (no I/O, no global
  state). The REST client is the only place that touches the network.
- Error handling: yield `Either(left=StackTraceError(name=..., ...))`.
  Use a small naming taxonomy so the OM run report groups failures:
  `Topic`, `Schema`, `Lineage`, `Tag`, `DataProduct`, `Container`.
- Use `sanitize()` from `mappers.py` for FQN segments. OM 1.11 quotes
  segments containing `.` automatically via `fqn.quote_name()`; prefer
  that to bespoke quoting.
- Logging: `metadata.utils.logger.ingestion_logger()` (Wave 7
  contribution). Today's `logging.getLogger(__name__)` is fine for
  the private build. **Never `print`** — OM upstream lints it out.
- For Wave 7 / upstream contribution: every Python file under
  `ingestion/` MUST carry the **Collate Community License 1.0**
  header (copy verbatim from any `metadata/ingestion/source/messaging/kafka/*.py`).

## OpenMetadata SDK notes (1.11+)

- Import paths: most messaging-relevant types live under
  `metadata.generated.schema.{type.schema, type.basic, type.entityReference,
   api.data.createTopic, api.lineage.addLineage, ...}`. The legacy
  `entity.data.topic` location for SchemaType is GONE in 1.11.
- `SchemaType` enum: Avro, Protobuf, JSON, Other, None_, plus newer
  additions. XSD has no enum entry; map to Other.
- `MessageSchema.schemaFields: List[FieldModel]` — FieldModel is
  recursive with `name`, `dataType` (UPPERCASE primitive),
  `dataTypeDisplay` (free string — use for logical types),
  `children[]`. Populate via `metadata.parsers.avro_parser.parse_avro_schema`
  / `json_schema_parser.parse_json_schema` / `protobuf_parser.parse_protobuf_schema`.
- `partitions` on `CreateTopicRequest` is required even though
  Solace/EP topics aren't partitioned. Hardcode `1` and document why
  (NATS PR #28153 reviewers flagged this).
- `owners` (plural, List[EntityReference]) replaced `owner`. Wave 0
  migration touches 6+ sites.
- `domains` (plural, List[EntityReference]) replaced `domain` in OM
  1.9. Wave 0 migration touches 7 sites.
- `LineageDetails.source = LineageSource.Manual` is effectively
  required in 1.11+. Set on every AddLineageRequest. Also use
  `LineageDetails.pipeline` reference to attach edges to the
  responsible pipeline (Kafka-Connect pattern).
- Custom-properties JSON-Patch: ometa SDK sends the wrong
  Content-Type. Use direct `requests.patch()` with
  `Content-Type: application/json-patch+json`.
- Pydantic v2 idioms: `WorkflowSource.model_validate()` (not
  `parse_obj()`), `EntityExtension(root=dict)`,
  `FullyQualifiedEntityName(root=fqn_str)`.

## Event Portal API notes

- Base URL: `https://api.solace.cloud/api/v2`
- Auth: `Authorization: Bearer <token>` from My Account -> Token
  Management. **Two tokens needed for v1.0**:
  `ep-token-reader` (used by Metadata + Lineage sources) and
  `ep-token-writer` (used by bridge writeback when #49 is enabled).
- All resource endpoints live under `/architecture/`.
- Pagination: `pageNumber` + `pageSize` query params; response meta
  carries `meta.pagination.totalPages`. Keep `pageSize <= 100` for
  *Versions endpoints.
- Lifecycle state field is `stateId` on v2 endpoints, `state` on v1.
- Topic addresses are reconstructed from
  `deliveryDescriptor.address.addressLevels` — see
  `extract_topic_address` in mappers.py.
- **`applicationVersion.consumers[]`** is the source-of-truth for
  Consumer-Queue + subscription patterns (#55).
- **`applicationVersion.inbound/outboundApplicationVersionAssociations[]`**
  is EP's Linked-Apps feature — directional pointers between EP App
  versions (#59).
- **CONFIRMED NOT AVAILABLE in Cloud Enterprise** (smoke-tested 2026-05-27):
  `/iam/users`, `/iam/teams`, `/admin/users`, `/users/{id}`,
  `/architecture/teams`, `/me`, `/organizations`, `/sso/users`,
  `/missionControl/users`, `/architecture/modeledEventMeshes`.
- `/architecture/customAttributeDefinitions` IS available
  (paginated, 3 pages on seall). Use for auto-discovery (#43).
- Use the Event Portal MCP server (if connected) or
  `scripts/smoke_ep_api.py` to fetch live payload shapes when
  uncertain — never invent field names.

## Customer context (ALDI Nord — informs all decisions)

- EP: Cloud Enterprise, 2 tenants in 1 EU region.
- OM: Self-Hosted 1.11 (planning 1.13 when GA).
- Operator: ALDI Platform Team.
- Tags: existing classifications in use; EP-CAs to be mapped as Tags
  with auto-discovery.
- Lineage: full EDA E2E expected (SAP -> EP-Pipeline -> Topic -> Queue
  -> EP-Pipeline -> SAP) with cross-system to Kafka / Snowflake /
  Databricks.
- Bi-dir sync: required for governance fields (description,
  classification, tags, certification, owners).
- Token rotation: 90d manual (RISK — automate with Vault in v1.1).
- Secrets: plain K8s for v1.0 (RISK — Vault in v1.1).
- PII: yes in topic-names, schemas, sample-payloads — declarative via
  tag/CA/segment/x-pii annotation; hard-block sample-data.
- Network: SaaS-egress only (EP is api.solace.cloud, OM is on-prem
  ALDI). Polling-only bridge confirmed.
- Data residency: Europe only.

## What this connector deliberately does

- Modeled Event Mesh: NOT mapped (Cloud Enterprise 404; closed
  wontfix per Cluster 1.3).
- Webhook subscriptions: NOT used (Cloud Enterprise doesn't expose
  outbound webhooks; bridge stays in polling mode forever).
- EP Teams -> OM Teams: BLOCKED (EP exposes no team API).
- AsyncAPI standalone mode: PRIVATE BUILD ONLY (out of scope for
  upstream PR; revisit as separate follow-up after v1.0 lands).
- Configure event brokers: read-only on the broker side (we touch
  EP, not the broker SEMP).
- Manage OAuth flows: only Bearer tokens for v1.0.
- Hard-delete on missing-in-EP: soft-delete with Retired tag only,
  optional manual purge after N days.

## Living docs (read in this order)

1. `docs/discovery-closure-summary.md` — what was decided + open
   risks (sign-off envelope)
2. `docs/asset-mapping-spec.md` — per-cluster mapping rationale
   (changes as discovery answers shift)
3. `docs/implementation-plan.md` — 7-wave delivery plan
4. `docs/EP-edition-compatibility.md` — per-EP-edition endpoint
   matrix
5. `docs/workshop-demo-script.md` — pilot demo walkthrough (kept for
   ALDI workshop reference)
6. `README.md` — public-facing project README

## When in doubt

- For Event Portal payload shapes: use `scripts/smoke_ep_api.py` or
  curl against the live API. Don't guess.
- For OM SDK signatures: read the installed package source under
  `site-packages/metadata/`, not blog posts (SDK churns).
- For OM FQN rules: use `metadata.utils.fqn.quote_name()` and the
  per-entity builder in `fqn_build_registry`. Don't bespoke-quote.
- For Wave 7 contribution conventions: mirror PR #28153 (NATS) file
  structure exactly. Apply Collate license header to every Python
  file under `ingestion/`. Strip every `print`. Run
  `make py_format_check && make generate` locally before pushing.
