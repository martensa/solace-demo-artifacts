# Solace EP -> OpenMetadata Connector — Production v1.0 Implementation Plan

**Status**: Draft for ALDI sign-off
**Last updated**: 2026-05-27
**Companion docs**: `discovery-closure-summary.md`, `asset-mapping-spec.md`

This plan turns the 25 prioritised tickets (#41-67) from discovery into 7
sequential **waves** of 1-2 weeks each. Each wave has a clear acceptance
goal, a ticket bundle, and a defined exit criterion. No wave is started
until the prior wave's exit criterion is met.

Total: ~10 weeks from kick-off to v1.0.0 GA. Plus Wave 7 (OM upstream
contribution) is post-GA and time-boxed to one quarter.

---

## Principles

- **No big-bang refactors.** Each wave ships a usable image to ALDI staging.
- **Tests-first for new mappers.** Every new entity-type mapper gets a
  pytest fixture before code.
- **Read-only against EP by default.** Bi-directional write-back (#49)
  ships separately in Wave 4, behind an explicit feature flag, with
  audit-log + drift-report from day 1.
- **Mirror Databricks discipline** for cross-system lineage: real
  metadata + graph + ES-FQN-search; regex is a fallback layer, not the
  primary mechanism.
- **Mirror Kafka's SDK conventions** but exceed Kafka on the 7 axes
  identified in #67 (Application/Domain/Lifecycle/Versions/LogicalTypes/
  Schemas/Refs).
- **Beat Kafka where EP gives us richer raw data**, don't ship gaps just
  because Kafka has them.

---

## Wave 0 — Foundation (Week 1)

**Goal**: connector code base runs cleanly against OM 1.11 SDK with the
same observable behaviour as today's pilot. No new features; just
mechanical migration + tested baseline.

**Tickets**: #47 (SDK 1.11), #51 (bridge handler bug), partial #66
(scaffold ServiceSpec, no behaviour change).

**Concrete work**:

1. Bump `pyproject.toml`: `requires-python = ">=3.10"`,
   `target-version = "py310"`, add SDK pin
   `openmetadata-ingestion>=1.11.5,<1.13`.
2. Bump `Dockerfile`: `OM_INGESTION_VERSION` 1.6.5 -> 1.11.14.
   `scripts/build-and-push.sh` mirrors. Smoke-build locally before
   pushing to `registry.solace.lab`.
3. Apply OM 1.9 `domain -> domains` rename across the 7 sites
   (`mappers.py:453,604`; `event_portal_connector.py:358,446`;
   `bridge/handlers.py:79,172`; `mappers.py:512`).
4. Pydantic-v2 cleanup: `WorkflowSource.parse_obj() -> .model_validate()`
   at `event_portal_connector.py:162`. Drop `__root__` fallback at
   `:170-179`. Drop legacy `MessageSchema/SchemaField` fallback at
   `mappers.py:36-43`.
5. Add `LineageDetails.source = LineageSource.Manual` everywhere
   AddLineageRequest is built (`mappers.py:631-660` etc.) — 1.11+
   convention.
6. Fix #51 bridge handler signature mismatch incidentally.
7. Scaffold (no behaviour change yet) `connector/service_spec.py` with
   `DefaultMessagingSpec(metadata_source_class=EventPortalMetadataSource,
   lineage_source_class=None_yet)` — just establishes the import path.
8. Run full pytest + ruff. Fix anything that breaks. NO new tests yet.
9. Smoke-test against an `openmetadata/server:1.11.x` instance.
   ALDI Platform Team confirms server is 1.11.x (Cluster 2.1) — coordinate.
10. Build `0.4.0` image. Push to `registry.solace.lab`. Verify the
    AcmeMDM ingestion pilot still produces identical OM output.

**Exit criterion**: pilot ingestion produces same OM entities as today,
but on top of OM 1.11 SDK. Image `0.4.0` deployed to ALDI staging.

---

## Wave 1 — Core mapping cleanup (Week 2)

**Goal**: schema-field-parsing live + CAs as Tags + all-versions default.
The user-visible "data is now actually navigable" wave.

**Tickets**: #64 (schema-field parsing), #43 (CAs -> Tags),
#54 (all-versions default ON).

**Concrete work**:

1. New `connector/schema_parser.py`:
   - Imports `metadata.parsers.avro_parser.parse_avro_schema`,
     `metadata.parsers.json_schema_parser.parse_json_schema`,
     `metadata.parsers.protobuf_parser.parse_protobuf_schema`.
   - Dispatcher: `parse(schema_text, schema_type) -> List[FieldModel]`.
   - Beat-Kafka layer: preserve avro `logicalType` (decimal/date/timestamp-millis)
     + json-schema `format` (date-time/uuid) in `dataTypeDisplay` post-parse.
   - Graceful fallback: on parse exception, log WARN + return
     top-level-only field list (today's behaviour). Never break ingestion.
2. `mappers.py.event_to_topic_request()`: replace today's top-level-only
   schema fields with `messageSchema.schemaFields = parser.parse(text, st)`.
3. Test fixtures: nested Avro record, JSON Schema with `$ref`, Debezium
   oneOf nullable, Avro union, Avro logical types decimal/date/timestamp.
4. #43 — Custom Attributes -> Tags:
   - `connector/bootstrap.py`: walk `/architecture/customAttributeDefinitions`
     (paginated), create OM Classification `EventPortalCustomAttribute_<name>`
     for each (skip names in workflow-config `customAttributeTagExclude`).
   - `mappers.py`: walk entity.customAttributes at ingestion; for each
     value, ensure Tag exists (lazy-create), apply to entity.
5. #54 — flip `ingestAllVersions` default to `true` in
   `config/example-workflow.yaml`. Add CP `eventPortalIsLatestVersion`
   (bool) in `mappers.py`. Document the OM-UI search filter in README.
6. Tests for #43 + #54.

**Exit criterion**: AcmeMDM ingest produces:
- Topics with nested SchemaFields (verify in OM UI — fields tree expands)
- All event versions as separate Topics (with `eventPortalIsLatestVersion`)
- Tags from each CA value (e.g. `EventPortalCustomAttribute_DataRetention.7days`)
- ALDI Platform Team sign-off on field-tree depth + tag explosion safety.
- Image `0.5.0` to staging.

---

## Wave 2 — Lineage + Cross-system (Week 3-4)

**Goal**: EDA lineage end-to-end (SAP -> Pipeline -> Topic -> Queue ->
Pipeline -> SAP), incl. cross-system edges to OM-pre-existing entities.

**Tickets**: #66 (ServiceSpec split), #59 (within-EP Linked Apps),
#60 (external CA fallback), #65 (dynamic classification),
#50 (cross-system YAML edges).

**Concrete work**:

1. #66 — Split `connector/event_portal_connector.py` into:
   - `EventPortalMetadataSource` (today's main flow)
   - `EventPortalLineageSource` (lineage-only — runs after metadata)
   - Register via `service_spec.py` `DefaultMessagingSpec`.
   - Two workflow YAMLs: `metadata-workflow.yaml` (hourly cron),
     `lineage-workflow.yaml` (daily cron, depends on metadata).
2. #59 — within-EP Linked Apps:
   - `mappers.py.app_to_linked_app_lineage_requests()` reads
     `inbound/outboundApplicationVersionAssociations` from
     applicationVersion payload, emits `Pipeline -> Pipeline`
     AddLineageRequests with `LineageDetails(source=LineageSource.Manual,
     description='EP Linked Application')`.
   - Lives in `EventPortalLineageSource` (Wave 2 dependency).
3. #65 — Dynamic classification (Databricks pattern):
   - Layer 1: read EP `applicationType` + linked-apps graph topology.
   - Layer 2: optional `appClassification.namePatterns` regex
     (ALDI-style — opt-in, default empty).
   - Layer 3: optional `appClassification.sourceSystemAppIds` /
     `sinkSystemAppIds` allow-list (manual override).
   - For classified system-apps, model as OM Container under
     `solace-event-portal-external-systems` StorageService instead of
     Pipeline.
   - `appClassification.dryRun: true` default — log classifications
     without writing.
4. #65 cross-system resolution:
   - For each system-app: `metadata.es_search_from_fqn` across
     `crossSystemServiceFqns` config services. Auto-link on 1-hit;
     skip + log on 0-or-N-hits.
5. #60 — external CA fallback:
   - When #65 auto-link finds 0 hits, look for EP CA
     `externalSourceOmFqn` / `externalSinkOmFqn`.
   - If set, look up OM entity by FQN and emit cross-system edge.
   - Bootstrap: optional `--register-ep-external-links` CLI registers
     the two CA definitions in EP via `/architecture/customAttributeDefinitions`.
6. #50 — cross-system YAML edges:
   - New `connector/lineage_workflow.py` (orchestrated via #66
     LineageSource).
   - Read `lineageEdges` list from workflow YAML (see
     `asset-mapping-spec.md` Cluster 2.5 for shape).
   - For each: resolve `from`/`to` FQNs via OM, emit AddLineageRequest.
   - Skip + WARN log on missing endpoints (allows out-of-order ingest).
7. Tests covering all of above.

**Exit criterion**: ALDI's reference E2E lineage flows through OM:
- SAP-source-system OM Container -> EP-publisher Pipeline
- EP-publisher Pipeline -> Topic
- Topic -> Consumer-Queue (Container) — Wave 3 dep, mock for now
- Consumer-Queue -> EP-consumer Pipeline — Wave 3 dep, mock
- EP-consumer Pipeline -> SAP-sink-system OM Container
- Image `0.6.0` to staging.

---

## Wave 3 — New entity types (Week 5)

**Goal**: complete the EP-to-OM type map. After this wave the OM UI
shows everything EP has.

**Tickets**: #44 (Event API -> Container), #45 (EAPP -> DataProduct),
#52 (first-class Schemas), #53 (Topic-address tree),
#55 (Consumer-Queue Container).

**Concrete work**:

1. #44 — Event API mapping:
   - New mapper `event_api_to_container_request()`.
   - Container under MessagingService root.
   - Custom Properties: eventPortalEventApiId, eventPortalEventApiVersionId.
   - Lineage Container <-> Topic (one edge per
     producedEventVersionIds + consumedEventVersionIds).
2. #45 — EAPP mapping:
   - New mapper `eapp_to_data_product_request()`.
   - DataProduct under MessagingService.
   - `assets: [EntityReference(...EventAPI containers)]` (1.11 native).
   - `plans[].solaceClassOfServicePolicy` -> CP `eventPortalPlans` (markdown table).
3. #52 — First-class Schemas:
   - New synthetic CustomDatabase service `solace-event-portal-schemas`.
   - DatabaseSchema per EP-Domain.
   - Table-equivalent per EP-Schema+Version with the parsed `Columns`
     from #64 parser as the body.
   - Topic CP `eventPortalSchemaEntityFqn` cross-links back.
   - Lineage Schema -> Topic.
4. #53 — Topic-address Container tree:
   - New synthetic StorageService `solace-event-portal-topic-tree`.
   - Walk topic addresses split by `/`. Create Container per segment
     up to `topicAddressContainerDepth` config (default 3).
   - Topic ref hangs at the deepest configured Container.
   - Topic CP `eventPortalTopicAddress` keeps the full string for search.
5. #55 — Consumer-Queue (Container per `consumers[]` entry):
   - New synthetic StorageService `solace-event-portal-consumers`.
   - Container per EP consumer with subscription patterns + brokerType + queue name as CPs.
   - Lineage Topic -> Container (one edge per attractedEventVersionId).
   - Lineage Container -> Pipeline (the owning consuming app).
6. Tests for all new mappers + fixtures.

**Exit criterion**: ALDI's "data product catalog" view in OM matches
EP's coverage 1:1. Image `0.7.0` to staging.

---

## Wave 4 — Identity + Soft-delete (Week 6)

**Goal**: owners resolve to humans. Drift-detection catches deletes
on the EP side and tombstones the matching OM entity.

**Tickets**: #57 (userIdToEmailMap), #56 (AsyncAPI sourceUrl),
#48 (Sub-Domain hierarchy), #61 (soft-delete with Retired tag),
#58 (EP Teams parked).

**Deferred to Wave 4.5 / 5**: #49 (OM -> EP bi-directional write-back).
This is the largest single chunk in the original Wave 4 scope
(~500-800 lines: new bridge/writeback.py, EP CA bootstrap, separate
ep-token-writer K8s Secret, drift-diff cron, EntityChangeEvent
webhook subscriber). It rides on Cluster 5 (Bi-Dir Sync) and is
gated by Cluster 4 (Identity) which Wave 4 has now closed. Sliced
out so the Identity + Soft-delete shipment lands at 0.8.0 without
the write-back risk surface.

**Concrete work**:

1. #57 — userIdToEmailMap:
   - New workflow-config option (str -> str map).
   - `connector/owner_resolver.py`: lookup `email = map[user_id]`, then
     `metadata.get_by_name(User, fqn=email)`, then set `owners=[ref]`
     (list — OM 1.11 native).
   - WARN log on miss, never error.
   - Flip `resolveOwners` default to `true`.
2. #56 — AsyncAPI sourceUrl:
   - `mappers.py.app_to_pipeline_request()` sets `sourceUrl =
     ep_console_url + asyncapi_endpoint_for(app_version_id)`.
3. #48 — Sub-Domain hierarchy:
   - New workflow-config option `omDomainParentMap: {domainName: parentFqn}`.
   - `mappers.py.domain_to_create_request()` resolves parent FQN, sets
     `CreateDomainRequest.parent`.
4. #61 — Soft-delete with Retired tag:
   - Extend reconcile (#23) to detect missing-in-EP entities.
   - Apply tag `EventPortal.Retired` + CP `eventPortalDeletedAt`.
   - Optional `--auto-purge-after-days` for hard-delete (default null).
5. #58 — Document parked.
6. Tests.

**Exit criterion**: OM users see human owners (via the static
userIdToEmailMap). Topics + Pipelines for events / apps deleted on
the EP side get the `EventPortal.Retired` tag within one
``--soft-delete-missing`` cron tick. Image `0.8.0` to staging.

### Deferred — Wave 4.5: #49 OM -> EP write-back

Sliced into a dedicated wave so the high-blast-radius write path
gets its own image and shadow-deploy. Concrete work when picked up:
- New `bridge/writeback.py` — subscribes to OM EntityChangeEvents
  via OM webhook subscription (registered idempotently on startup).
- For each change, applies the per-field policy table (see
  `asset-mapping-spec.md` Cluster 5).
- PUT EP `/architecture/<entity>/{id}` for CA values:
  epExtendedDescription, epCertification, epAdditionalOwners,
  externalSourceOmFqn, externalSinkOmFqn.
- Bootstrap: registers required EP CA definitions if missing.
- **Two separate K8s Secrets**: `ep-token-reader` (used by
  metadata/lineage sources) + `ep-token-writer` (used only by
  bridge/writeback). ALDI rotates both 90d manual.
- Daily drift-diff cron compares OM vs EP for OM-wins fields,
  reports via OTel (alert if drift > threshold).
- Feature-flagged: `writebackEnabled: false` default.
- Target image: `0.8.5` (separate from Wave 4's `0.8.0`).

---

## Wave 5 — Production hardening (Week 7-8)

**Goal**: enterprise-grade observability + secrets + multi-tenant + PII.

**Tickets**: #41 (multi-tenant), #62 (PII), #63 (OTel),
#10 (Prometheus metrics), #11 (structured logging),
#13 (graceful shutdown), #15 (Helm chart),
#16 (Phase 2 docs), #67 (Beat-Kafka docs).

**Concrete work**:

1. #41 — Multi-tenant: two `MessagingService` instances in 1 OM, two
   sets of workflow YAMLs, shared `solace-event-portal-apps`
   PipelineService with tenant-prefixed Pipeline FQNs to avoid
   collision.
2. #62 — PII:
   - Bootstrap registers `pii` CA-definition in EP if missing.
   - Mapper: at ingestion, if any PII source signals (CA / tag /
     topic-segment / schema-field x-pii annotation) -> add Tag
     `EventPortalCompliance.PII` + CP `eventPortalContainsPii=true`.
   - Sample-data subscribe (#2 already shipped): hard-block when
     target Topic has the PII tag.
   - Field-level: extend #64 parser to annotate FieldModel with PII tag
     based on `x-pii: true` annotation in JSON-Schema or Avro doc.
3. #63 — OTel: refactor today's logging to OpenTelemetry spans + logs
   via OTLP/HTTP. Spans tagged with om.entity.type/fqn, ep.entity.id,
   actor, action, outcome. Helm chart bundles optional OTel Collector
   sidecar.
4. #10 — Prometheus `/metrics` endpoint in bridge (req latency, EP/OM
   401 counters, write-back queue depth).
5. #11 — Structured JSON logging with trace_id correlation (cross-cut
   with #63).
6. #13 — Graceful shutdown: SIGTERM drains write-back queue + flushes
   dedupe + closes EP/OM connections.
7. #15 — `charts/solace-eventportal-bridge` Helm chart.
8. #16 — Phase 2 README + compat matrix update.
9. #67 — README "Why this connector" section with Beat-Kafka list.

**Exit criterion**: ALDI IT-Sec sign-off on PII handling. Prometheus
dashboards live. Image `0.9.0` to staging.

---

## Wave 6 — GA + ALDI cutover (Week 9-10)

**Goal**: v1.0.0 GA to ALDI production.

**Work**:

1. v1.0.0-rc1 -> ALDI staging (2 tenants in 1 region).
2. Soak test 1 week. Compare OM entity-count + lineage-edge-count vs
   expected. Resolve any drift.
3. Documentation: README full rewrite. `docs/operations.md` runbook.
   `docs/migration-from-0.x.md` for sites that ran the pilot.
4. v1.0.0 GA tag. Push images. ALDI production cutover.
5. Decommission custom-messaging-service pilot setup.
6. Capture lessons-learned for Wave 7.

**Exit criterion**: ALDI prod runs v1.0.0 for 30 days without major
incident. Then trigger Wave 7.

---

## Wave 7 — OM upstream contribution (Q3 2026, post-GA)

**Goal**: ship Event Portal as a first-class native messaging connector
in `openmetadata-ingestion` PyPI + `openmetadata/ingestion` Docker image,
replacing our `registry.solace.lab` private image for OSS users.

**Reference**: PR #28153 (NATS JetStream) is the structural template;
PR #25021 (PubSub) added the `yield_topic_lineage` extension point we
will use.

### License + identity setup

- Repo root: Apache-2.0; `ingestion/` subdir: **Collate Community
  License 1.0**. Every new Python file under `ingestion/` MUST carry
  the Collate license header (10-line block copied verbatim from
  `ingestion/src/metadata/ingestion/source/messaging/kafka/metadata.py`).
- No CLA bot. Acceptance is implicit via PR submission with correct
  headers. Introduce in Slack `#contributor` first.
- Author named on the PR = Solace; ALDI optionally credited as
  reference customer in PR description (boosts review velocity).

### File layout (14 new + 4 modify)

**JSON schema** (handwritten):
- `openmetadata-spec/src/main/resources/json/schema/entity/services/connections/messaging/eventPortalConnection.json`
- Modify `openmetadata-spec/src/main/resources/json/schema/entity/services/messagingService.json` —
  add `"EventPortal"` to `definitions.messagingServiceType.enum` +
  `javaEnums` + `oneOf` entry

**Python source** (new package, 5 files):
- `ingestion/src/metadata/ingestion/source/messaging/eventportal/__init__.py`
- `.../eventportal/connection.py` — `get_connection` +
  `test_connection_steps`; lift today's `connector/event_portal_client.py`
- `.../eventportal/metadata.py` — `EventPortalSource(MessagingServiceSource)`;
  implements `get_topic_list`, `yield_topic`, `yield_topic_lineage`
- `.../eventportal/models.py` — dataclasses for EP payload shapes
- `.../eventportal/service_spec.py` —
  `ServiceSpec = BaseSpec(metadata_source_class=EventPortalSource)`

**Test connection definition** (1 new):
- `openmetadata-service/src/main/resources/json/data/testConnections/messaging/eventPortal.json`
  steps: ListDomains, ListEvents, ListApplications, ListSchemas,
  ListVersions, ListCustomAttributes

**Workflow example** (1 new):
- `ingestion/src/metadata/examples/workflows/eventportal.yaml`

**Tests** (6 new):
- `ingestion/tests/unit/source/messaging/test_eventportal.py` —
  `responses`-library mocks; matrix: published event, consumed event,
  no-schema, JSON-Schema path, Avro path, EAPP-DataProduct path
- `ingestion/tests/integration/eventportal/__init__.py`
- `.../integration/eventportal/conftest.py`
- `.../integration/eventportal/test_metadata.py`
- `.../integration/eventportal/populate_eventportal.py`
- (Solace Cloud is not dockerizable — `responses` mocks only)

**UI assets** (4 new + edits):
- `openmetadata-ui/src/main/resources/ui/public/locales/en-US/Messaging/EventPortal.md`
- `openmetadata-ui/src/main/resources/ui/src/assets/img/service-icon-eventportal.png`
- Modify `.../ui/src/utils/MessagingServiceUtils.ts` — add lazy
  loader entry in `messagingSchemaLoaders` map
- Modify `.../ui/src/utils/ServiceIconUtils.ts` — register icon

**Auto-regenerated** (~13 files): must run TS codegen locally
(`cd openmetadata-ui/src/main/resources/ui && ./json2ts-generate-all.sh`)
because the GH-Actions bot can't push back to forks.

**Setup** (1 modify):
- `ingestion/setup.py` — add `"eventportal": set()` to `plugins` dict
  around line 332 (no new deps; `requests` already in
  `base_requirements`).

**CI labels** (1 modify):
- `.github/scripts/label_connector.py` RULES list — add
  `connector:eventportal`.

### Pre-contribution refactor checklist (must do before PR)

- [ ] **Drop the `CustomMessaging` registration** — we become a
      first-class `MessagingServiceType.EventPortal` enum value.
- [ ] **Replace `print` with `metadata.utils.logger.ingestion_logger()`**
      across all migrated files (T20 ruff rule + NATS reviewer
      enforced this explicitly).
- [ ] **Resolve `_patch_topic_with_app` TODO** — use real
      `metadata.patch(entity=Topic, source=..., destination=...)`.
      Placeholder code will be rejected.
- [ ] **Don't fake `partitions`** — Solace topics aren't partitioned.
      Keep `partitions=1` (hardcode) AND document the rationale in
      `EventPortal.md` (NATS reviewer flagged this as smell).
- [ ] **Run `make generate`** to produce pydantic v2 models from the
      hand-written JSON schema. Commit the generated tree under
      `ingestion/src/metadata/generated/`.
- [ ] **Ruff clean** (line-length=120, target=py310, all rule
      families enabled — see Agent 3 report).
- [ ] **AsyncAPI mode parking** — does NOT fit upstream pattern;
      leave it as a follow-up PR (keep `asyncapi_parser.py` in our
      private repo).

### 14-step contribution sequence

1. **Slack intro** in `open-metadata/OpenMetadata` `#contributor`
2. **Tracking issue** titled "Add Solace Event Portal messaging
   connector" using the Connector dropdown
3. **Fork + branch** `feat/messaging-eventportal`
4. **Hand-write** `eventPortalConnection.json` (use
   `kafkaConnection.json` as template)
5. **Diff** `messagingService.json` to register the enum
6. **`make generate`** -> regenerated pydantic models committed
7. **Port code**: split today's `event_portal_connector.py` into
   `connection.py` + `metadata.py`; port `mappers.py` + client; apply
   Collate header to every file; strip every `print`
8. **Add** `service_spec.py` + workflow YAML + test-connection JSON
9. **Write** unit tests with `responses` mocks
10. **Write** integration tests with `responses` mocks
11. **Add** UI assets (locale Markdown, icon, lazy loader, service
    icon util, label rule)
12. **TS codegen locally** and commit regenerated files
13. **Lint + test**:
    `make install install_test install_dev && make generate &&
    make py_format_check && pytest ingestion/tests/unit/source/messaging/test_eventportal.py`
14. **Open PR** against `main`, link the issue, request
    `safe to test` label in PR description + Slack ping. Lead the PR
    description with the Beat-Kafka 7-point list (#67).

### Reviewer-expected feedback themes (pre-empt)

From NATS PR #28153 review history:
- No prints
- TS codegen not pushed from fork -> regenerate locally + push
- `connection.py` mutable-module-level state will be flagged by
  `gitar-bot` -> use proper class scoping
- `partitions` semantics — pre-empt by documenting

**Exit criterion**: PR merged into OM main. Next OM release ships
EventPortal as native enum. Drop `registry.solace.lab/openmetadata-
ingestion-solace` image on customer documentation (point to
`docker.getcollate.io/openmetadata/ingestion:<version>`).

---

## Cross-wave concerns

- **Versioning**: bump minor for each wave (`0.4.0` Wave 0, `0.5.0` Wave 1,
  ..., `0.9.0` Wave 5, `1.0.0` Wave 6).
- **Branching**: stay on master per repo convention; tag at each wave exit.
- **CI**: pytest + ruff after every wave; add tox matrix for 1.11 + 1.12 at Wave 0.
- **Communication**: weekly demo to ALDI Platform Team at end of each wave;
  show new entities live in staging OM UI.

---

## Open questions for ALDI sign-off

1. Wave 0 timing — ALDI's OM cluster currently at 1.11.x (Cluster 2.1
   confirmed). Verify exact patch version, schedule staging-side SDK
   bump alongside our 0.4.0 image.
2. Wave 4 #49 — confirm scope (Tags/Description/Cert/Owner/External-link)
   matches expectations. EP write-token approval (security topic).
3. Wave 5 #62 — list of source-signal patterns for PII detection
   (CA name? Tag name pattern? Topic-segment pattern?).
4. Wave 7 — does ALDI want to be named in the upstream PR as the
   reference customer? Helps the PR land faster.
