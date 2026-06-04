# CLAUDE.md — Solace Event Portal OpenMetadata Connector

## Mission

A production-ready OpenMetadata ingestion connector that imports
Solace Event Portal metadata as a Messaging Service, with cross-system
lineage (EP -> Kafka / Snowflake / Databricks / SAP) and (planned)
bi-directional sync of governance metadata. Customer anchor: ALDI
Nord (Cloud Enterprise, 2 tenants, EU). Target: v1.0.0 GA in 10
weeks; OM upstream contribution in the following quarter.

EP is the system of record for EDA models (events, schemas,
applications, topic-addresses, pub/sub declarations). OM enriches it
with extended descriptions, classifications, certification, owners,
and cross-system lineage to non-EP entities. Per-field
source-of-truth policy lives in `docs/asset-mapping-spec.md`
(Cluster 5 table).

## Current state (post-Wave 4)

| Wave | Status | Image | Highlights |
|---|---|---|---|
| Wave 0 | shipped | 0.4.0 | OM 1.11 SDK migration, owners/domains plural |
| Wave 1 | shipped | 0.5.0 | Schema-field parsing (#64), all-versions default (#54), Custom Attributes -> Tags (#43) |
| Wave 2 | shipped | 0.6.0 | ServiceSpec split (#66), Linked-Apps lineage (#59), cross-system YAML edges (#50), external-CA fallback (#60) |
| Wave 3 | shipped | 0.7.0 | New entity types: Event API Container (#44), EAPP DataProduct (#45), first-class Schemas (#52), Topic-tree (#53), Consumer-Queue (#55) |
| Wave 4 | shipped | 0.8.0 | userIdToEmailMap (#57), AsyncAPI sourceUrl (#56), Sub-Domain hierarchy (#48), Soft-delete drift pass (#61) |
| Wave 4.5 | deferred | 0.8.5 | #49 OM -> EP write-back (split out of Wave 4) |
| Wave 5 | next | 0.9.0 | Production hardening: multi-tenant (#41), PII (#62), OTel (#63), metrics (#10), structured logging (#11), graceful shutdown (#13), Helm chart (#15), Phase 2 docs (#16), Beat-Kafka (#67) |
| Wave 6 | future | 0.10.0 | OpenMetadata upstream PR prep |
| Wave 7 | future | 1.0.0 | OpenMetadata upstream contribution + GA |

Active image: `registry.solace.lab/openmetadata-ingestion-solace:0.8.0`.
The image is also tagged `:latest`. Tag bumps live in
`openmetadata-deployment/local-k8s-deps-values.yaml`.

## Stack (target for v1.0)

- Python 3.10+ (OM 1.11 dropped 3.9)
- `openmetadata-ingestion >= 1.11.5, < 1.13` (pin upper bound below
  1.13 until 1.13 GA on PyPI; today's latest stable is 1.12.8.9)
- `metadata.parsers.{avro_parser, json_schema_parser, protobuf_parser}` --
  USE OM's built-in schema parsers, don't reimplement
- `requests` + `urllib3` retry adapter for the REST client
- `pyyaml` for AsyncAPI parsing (private-build only; out of scope for
  the upstream contribution)
- `pytest` + `responses` for unit tests (OM upstream uses `responses`)
- `ruff` (line-length=120 to match OM upstream, target-version=py310)
- `opentelemetry-sdk` + `opentelemetry-exporter-otlp` for telemetry
  (Wave 5 / #63)

## Repo layout (current)

```text
connector/
  service_spec.py            DefaultMessagingSpec registration (Wave 2)
  event_portal_client.py     REST client; paginated, retrying, dict returns
  event_portal_connector.py  Top-level Source class
  metadata_source.py         EventPortalMetadataSource (Wave 2)
  lineage_source.py          EventPortalLineageSource (Wave 2)
  mappers.py                 Pure functions: EP payload -> OM Create*Request
  fqn.py                     Pure FQN helpers (Wave 4; no OM SDK dep)
  schema_parsers/            Per-format parser dispatch package (Wave 1)
  asyncapi_parser.py         AsyncAPI v2 -> Topic requests (private build)
  filters.py                 Allow-list filter pattern
  owner_resolver.py          userIdToEmailMap lookup + OM user resolve
  bootstrap.py               Bootstrap classifications, CAs, services
  property_keys.py           Stable constants
  sample_data.py             Live Solace subscribe -> Topic sample data
bridge/
  main.py                    Bridge entrypoint + CLI flags
  config.py                  BridgeSettings (env-var driven)
  dispatcher.py              Event-type -> handler routing
  handlers.py                Bridge event handlers
  forwarder.py               Webhook -> Solace forwarder (private build)
  signature.py               EP webhook HMAC verification
  dedupe.py                  In-memory + Redis dedupe stores
  reconcile.py               Full-pull reconcile + soft-delete (#61)
  transport/polling.py       EP polling-mode (no outbound webhooks)
  writeback.py               (DEFERRED -- Wave 4.5 / #49)
config/
  example-workflow.yaml      Sample `metadata ingest -c` workflow
docs/
  asset-mapping-spec.md       Living mapping spec (per-cluster decisions)
  discovery-closure-summary.md ALDI discovery sign-off envelope
  implementation-plan.md      7-wave delivery plan + Wave 4.5 carve-out
  workshop-demo-script.md     Pilot demo walkthrough
  EP-edition-compatibility.md Per-EP-edition endpoint matrix
  aldi-signoff-memo.md        ALDI sign-off envelope summary
  aldi-discovery-onepager.md  ALDI one-pager (PDF generated alongside)
  demo-seed-data.md           Demo seeding script
  openmetadata-image-flip.md  Helm image flip procedure
scripts/
  build-and-push.sh           Build + push the OM ingestion image
  smoke_ep_api.py             EP-API smoke-test against a live tenant
Dockerfile                    Bakes the connector into openmetadata/ingestion
pyproject.toml
.markdownlint.json
```

## Commands

```bash
# Lint + test (run from event-portal/om-connector)
python -m pytest tests --ignore=tests/test_connector_helpers.py -q
pipx run --spec=ruff ruff check connector tests bridge
npx markdownlint-cli CLAUDE.md README.md docs/

# Build + push the ingestion image (currently 0.8.0 per pyproject.toml)
bash scripts/build-and-push.sh

# Run a one-shot ingestion against a workflow YAML
metadata ingest -c config/example-workflow.yaml

# Bootstrap OM with EP classifications + custom properties + services
om-eventportal-bootstrap --jwt <om-jwt> \
  --host-port http://om-server:8585 \
  --ep-token <ep-token>   # optional, enables CA-discovery (#43)

# Soft-delete drift pass (Wave 4 / #61)
python -m bridge.main --soft-delete-missing
python -m bridge.main --soft-delete-missing --auto-purge-after-days 30

# Smoke-test EP API (keep the leading space so the export does not
# land in shell history)
 export EP_API_TOKEN='...'
python scripts/smoke_ep_api.py
```

## Architecture (current after Wave 4)

The connector ingests EP under a CustomMessaging service named
`solace-event-portal`. Wave 2 split the source into
**EventPortalMetadataSource** (entity emission pass) and
**EventPortalLineageSource** (cross-system + linked-apps edges) via
the OM `ServiceSpec` registry.

Entity coverage delivered through Wave 4:

- **Domain** per EP Application Domain; optional sub-domain hierarchy
  via the `omDomainParentMap` workflow option (#48).
- **Topic** per EP event version under the MessagingService, with
  parsed Avro / JSON-Schema / Protobuf SchemaFields (#64), lifecycle
  tags (`EventPortal.{Draft,Released,Deprecated,Retired,Application}`)
  and the per-version `eventPortalIsLatestVersion` CP (#54).
- **Pipeline** per EP Application version under the synthetic
  `solace-event-portal-apps` PipelineService, with downloadable
  AsyncAPI doc on `Pipeline.sourceUrl` (#56).
- **Container** per EP Event API version under the synthetic
  `solace-event-portal-event-apis` StorageService (#44), per
  applicationVersion.consumers[] entry under
  `solace-event-portal-consumers` (#55), and per topic-address segment
  under `solace-event-portal-topic-tree` (#53, depth-cap via
  `topicTreeMaxDepth`).
- **DataProduct** per EP Event API Product version, with assets[]
  referencing the matching #44 Containers (#45).
- **Table** per EP Schema version under the synthetic
  `solace-event-portal-schemas` CustomDatabase (#52), with one
  DatabaseSchema per EP domain; field-level columns derived from the
  parsed SchemaFields.

Lineage coverage:

- App Pipeline <-> Topic (per produced / consumed eventVersionId).
- Event API Container <-> Topic (per produced / consumed
  eventVersionId on the EP API, #44).
- Consumer Container chain Topic -> Container -> Pipeline (#55).
- Topic-tree segment Container -> Topic at the deepest in-cap segment
  (#53).
- Schema Table -> Topic (per schemaVersionId, #52).
- Pipeline -> Pipeline within EP via the
  inbound/outboundApplicationVersionAssociations (#59).
- Cross-system edges from a YAML mapping (#50) plus external-system
  fallback via EP Custom Attributes (#60).

Drift handling: the bridge's `--soft-delete-missing` pass (#61, Wave 4)
walks OM Topics + Pipelines, diffs FQNs against a fresh EP pull, and
JSON-Patches every zombie with the `EventPortal.Retired` tag plus the
`eventPortalDeletedAt` ISO timestamp. Optional
`--auto-purge-after-days` hard-deletes once the tombstone ages past
the cutoff.

OM -> EP write-back (the original Wave 4 #49) is carved out into
**Wave 4.5** so the high-blast-radius write path can land in its own
image (`0.8.5`) with shadow-deploy. The hook lives in
`bridge/writeback.py` (file not yet present; see
`docs/implementation-plan.md` for the design).

## Coding conventions

- Prefer dict access for Event Portal payloads, not pydantic models.
  The EP API ships new fields frequently; brittle typed models hurt
  more than help.
- Mappers must be pure functions of their inputs (no I/O, no global
  state). The REST client is the only place that touches the network.
- Pure FQN helpers (`sanitize`, `topic_fqn`, `app_pipeline_fqn`, ...)
  live in `connector/fqn.py` -- no OM SDK dependency, so they are
  callable from the slim bridge image. `mappers.py` re-exports the
  same symbols for backwards compatibility.
- Error handling: yield `Either(left=StackTraceError(name=..., ...))`.
  Use a small naming taxonomy so the OM run report groups failures:
  `Topic`, `Schema`, `Lineage`, `Tag`, `DataProduct`, `Container`.
- Use `sanitize()` from `connector.fqn` for FQN segments. OM 1.11
  quotes segments containing `.` automatically via `fqn.quote_name()`;
  prefer that to bespoke quoting.
- Logging: `metadata.utils.logger.ingestion_logger()` (Wave 7
  contribution). Today's `logging.getLogger(__name__)` is fine for
  the private build. **Never `print`** -- OM upstream lints it out.
- For Wave 7 / upstream contribution: every Python file under
  `ingestion/` MUST carry the **Collate Community License 1.0**
  header (copy verbatim from any
  `metadata/ingestion/source/messaging/kafka/*.py`).
- Documentation: Markdown lines <= 80 chars (MD013), URLs in backticks
  or angle brackets (MD034), no HTML (MD033). Config at
  `event-portal/om-connector/.markdownlint.json`.

## OpenMetadata SDK notes (1.11+)

- Import paths: most messaging-relevant types live under
  `metadata.generated.schema.{type.schema, type.basic,
  type.entityReference, api.data.createTopic, api.lineage.addLineage,
  ...}`. The legacy `entity.data.topic` location for SchemaType is
  GONE in 1.11.
- `SchemaType` enum: Avro, Protobuf, JSON, Other, None_, plus newer
  additions. XSD has no enum entry; map to Other.
- `MessageSchema.schemaFields: List[FieldModel]` -- FieldModel is
  recursive with `name`, `dataType` (UPPERCASE primitive),
  `dataTypeDisplay` (free string; use for logical types),
  `children[]`. Populate via the OM parsers in `connector.schema_parsers`.
- `partitions` on `CreateTopicRequest` is required even though
  Solace/EP topics aren't partitioned. Hardcode `1` and document why
  (NATS PR #28153 reviewers flagged this).
- `owners` (plural, `List[EntityReference]`) replaced `owner`. Wave 0
  migration touched 6+ sites.
- `domains` (plural, `List[EntityReference]`) replaced `domain` in OM
  1.9. Wave 0 migration touched 7 sites.
- `LineageDetails.source = LineageSource.Manual` is effectively
  required in 1.11+. Set on every `AddLineageRequest`. Also use
  `LineageDetails.pipeline` reference to attach edges to the
  responsible pipeline (Kafka-Connect pattern).
- Custom-properties JSON-Patch: the ometa SDK sends the wrong
  Content-Type. Use direct `requests.patch()` with
  `Content-Type: application/json-patch+json`.
- Pydantic v2 idioms: `WorkflowSource.model_validate()` (not
  `parse_obj()`), `EntityExtension(root=dict)`,
  `FullyQualifiedEntityName(root=fqn_str)`.

## Event Portal API notes

- Base URL: `https://api.solace.cloud/api/v2`
- Auth: `Authorization: Bearer <token>` from My Account -> Token
  Management. Two tokens planned for v1.0: `ep-token-reader` (used by
  Metadata + Lineage sources) and `ep-token-writer` (Wave 4.5 / #49).
- All resource endpoints live under `/architecture/`.
- Pagination: `pageNumber` + `pageSize` query params; response meta
  carries `meta.pagination.totalPages`. Keep `pageSize <= 100` for
  `*Versions` endpoints.
- Lifecycle state field is `stateId` on v2 endpoints, `state` on v1.
- Topic addresses are reconstructed from
  `deliveryDescriptor.address.addressLevels` -- see
  `extract_topic_address` in `connector/mappers.py`.
- `applicationVersion.consumers[]` is the source-of-truth for
  Consumer-Queue + subscription patterns (#55).
- `applicationVersion.inbound/outboundApplicationVersionAssociations[]`
  is EP's Linked-Apps feature -- directional pointers between EP App
  versions (#59).
- CONFIRMED NOT AVAILABLE in Cloud Enterprise (smoke-tested
  2026-05-27): `/iam/users`, `/iam/teams`, `/admin/users`,
  `/users/{id}`, `/architecture/teams`, `/me`, `/organizations`,
  `/sso/users`, `/missionControl/users`,
  `/architecture/modeledEventMeshes`.
- `/architecture/customAttributeDefinitions` IS available (paginated,
  3 pages on seall). Used for auto-discovery (#43).
- `/architecture/eventApis` + `/architecture/eventApiVersions` IS
  available (Wave 3 / #44).
- `/architecture/eventApiProducts` +
  `/architecture/eventApiProductVersions` IS available (Wave 3 / #45).
- `/architecture/schemas` + `/architecture/schemaVersions` IS
  available (Wave 3 / #52); paginated, `applicationDomainId` singular.
- Use the Event Portal MCP server (if connected) or
  `scripts/smoke_ep_api.py` to fetch live payload shapes when
  uncertain -- never invent field names.

## Customer context (ALDI Nord -- informs all decisions)

- EP: Cloud Enterprise, 2 tenants in 1 EU region.
- OM: Self-Hosted 1.11 (planning 1.13 when GA).
- Operator: ALDI Platform Team.
- Tags: existing classifications in use; EP-CAs mapped as Tags with
  auto-discovery (Wave 1 / #43, default-on).
- Lineage: full EDA E2E expected (SAP -> EP-Pipeline -> Topic ->
  Queue -> EP-Pipeline -> SAP) with cross-system to Kafka / Snowflake
  / Databricks.
- Bi-dir sync: required for governance fields (description,
  classification, tags, certification, owners) -- delivered through
  Wave 4.5 / #49.
- Token rotation: 90d manual (RISK -- automate with Vault in v1.1).
- Secrets: plain K8s for v1.0 (RISK -- Vault in v1.1).
- PII: yes in topic-names, schemas, sample-payloads -- declarative
  via tag / CA / segment / x-pii annotation; hard-block sample-data
  (Wave 5 / #62).
- Network: SaaS-egress only (EP is `api.solace.cloud`, OM is on-prem
  ALDI). Polling-only bridge confirmed.
- Data residency: Europe only.

## What this connector deliberately does NOT do

- Modeled Event Mesh: NOT mapped (Cloud Enterprise 404; closed
  wontfix per Cluster 1.3). The feature flag `emitDataProducts` is
  still wired for higher-tier editions and is default OFF.
- Outbound webhook subscriptions: NOT used (Cloud Enterprise doesn't
  expose outbound webhooks; bridge stays in polling mode forever).
- EP Teams -> OM Teams: BLOCKED (EP exposes no team API). See #58.
- AsyncAPI standalone mode: PRIVATE BUILD ONLY (out of scope for the
  upstream PR; revisit as separate follow-up after v1.0 lands).
- Configure event brokers: read-only on the broker side (we touch
  EP, not the broker SEMP).
- Manage OAuth flows: only Bearer tokens for v1.0.
- Hard-delete on missing-in-EP: soft-delete with the
  `EventPortal.Retired` tag is the default (#61). Hard-delete is
  opt-in via `--auto-purge-after-days N`.

## Living docs (read in this order)

1. `docs/discovery-closure-summary.md` -- what was decided + open
   risks (sign-off envelope)
2. `docs/asset-mapping-spec.md` -- per-cluster mapping rationale
   (changes as discovery answers shift)
3. `docs/implementation-plan.md` -- 7-wave delivery plan + Wave 4.5
   carve-out
4. `docs/EP-edition-compatibility.md` -- per-EP-edition endpoint
   matrix
5. `docs/workshop-demo-script.md` -- pilot demo walkthrough (kept for
   ALDI workshop reference)
6. `README.md` -- public-facing project README

## When in doubt

- For Event Portal payload shapes: use `scripts/smoke_ep_api.py` or
  curl against the live API. Don't guess.
- For OM SDK signatures: read the installed package source under
  `site-packages/metadata/`, not blog posts (SDK churns).
- For OM FQN rules: prefer `metadata.utils.fqn.quote_name()` and the
  per-entity builder in `fqn_build_registry`. Otherwise reuse the
  pure helpers in `connector.fqn`.
- For Wave 7 contribution conventions: mirror PR #28153 (NATS) file
  structure exactly. Apply the Collate license header to every Python
  file under `ingestion/`. Strip every `print`. Run
  `make py_format_check && make generate` locally before pushing.

## Next session pickup

The shortest path back into the codebase from a fresh Claude session:

1. Read this file plus `docs/implementation-plan.md` (Wave 5 is the
   next concrete unit of work; Wave 4.5 / #49 is the only Wave 4
   spillover).
2. Glance at `docs/discovery-closure-summary.md` to remember which
   product decisions are locked in vs still negotiable.
3. Check the project tasks list -- the task IDs in there map to the
   `#NN` references peppered through this document and the
   implementation plan.
4. `git log --oneline -10` shows the Wave 4 closure commits
   (`feat(om-connector): Wave 4 ...` + `fix(openmetadata-deployment):
   bump ingestion image to 0.8.0 (Wave 4)`).
5. Active image tag: `0.8.0`. The
   `openmetadata-deployment/local-k8s-deps-values.yaml` already
   points at it. Run `bash scripts/build-and-push.sh` after any
   `pyproject.toml` version bump.
