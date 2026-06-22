# Solace EP to OpenMetadata Connector: Delivery Plan (Beta)

**Status**: feature-complete for the **Beta**. Waves 0-5 + Wave 4.5
(`#49` write-back, flag-off) are code-complete on the `0.9.0` line.
The roadmap ends here: the former Wave 6 (v1.0 GA + ALDI prod cutover)
and Wave 7 (OpenMetadata upstream contribution) are **dropped / out of
scope**. Remaining work is the operational Beta release -- build +
push the `0.9.0` images and flip the
`local-k8s-deps-values.yaml` tag (see `docs/operations.md`).

**Last updated**: 2026-06-22 (Beta scope; Waves 6-7 dropped).

**Companion doc**: `asset-mapping-spec.md`.

This plan turns the prioritised tickets from discovery into sequential
**waves** of 1-2 weeks each. Each wave has a clear acceptance goal,
a ticket bundle, and a defined exit criterion. No wave is started
until the prior wave's exit criterion is met.

Scope: Waves 0-5 + Wave 4.5 deliver the Beta. The originally-planned
Wave 6 (GA + prod cutover) and Wave 7 (OM upstream contribution) have
been dropped; their sections were removed from this plan.

---

## Wave status overview

| Wave | Status | Image | Headline |
|---|---|---|---|
| 0 | shipped | 0.4.0 | OM 1.11 SDK migration |
| 1 | shipped | 0.5.0 | Schema-field parsing + CAs to Tags + all-versions |
| 2 | shipped | 0.6.0 | ServiceSpec split + Linked-Apps + cross-system |
| 3 | shipped | 0.7.0 | New entity types (Event API / EAPP / Schemas / Tree / Consumer) |
| 4 | shipped | 0.8.0 | Identity (userIdToEmailMap) + Soft-delete drift pass |
| 4.5 | code-complete | flag-off | OM to EP write-back (`#49`); off + dry-run by default |
| 5 | shipped | 0.9.0 | Production hardening (multi-tenant, PII, OTel, metrics, logging, shutdown, Helm) |

Waves 6 (GA + prod cutover) and 7 (OM upstream contribution) were
dropped -- the `0.9.0` line is the Beta. See `docs/operations.md` for
the operational Beta release + run procedures.

The active deployment tag lives in
`openmetadata-deployment/local-k8s-deps-values.yaml`. Bump
`pyproject.toml` first, then `bash scripts/build-and-push.sh`,
then update the helm values, then commit.

---

## Principles

- **No big-bang refactors.** Each wave ships a usable image to ALDI
  staging.
- **Tests-first for new mappers.** Every new entity-type mapper gets
  a pytest fixture before code.
- **Read-only against EP by default.** Bi-directional write-back
  (ticket `#49`) ships separately in Wave 4.5, behind an explicit
  feature flag, with audit-log + drift-report from day one.
- **Mirror Databricks discipline** for cross-system lineage: real
  metadata + graph + ES-FQN-search; regex is a fallback layer, not
  the primary mechanism.
- **Mirror Kafka's SDK conventions** but exceed Kafka on the seven
  axes identified in ticket `#67` (Application / Domain / Lifecycle /
  Versions / LogicalTypes / Schemas / Refs).
- **Beat Kafka where EP gives us richer raw data**, do not ship gaps
  just because Kafka has them.

---

## Wave 0 (Week 1, SHIPPED at image 0.4.0)

**Goal**: connector code base runs cleanly against OM 1.11 SDK with
the same observable behaviour as today's pilot. No new features;
just mechanical migration + tested baseline.

**Tickets**: `#47` (SDK 1.11), `#51` (bridge handler bug), partial
`#66` (scaffold ServiceSpec, no behaviour change).

**Concrete work**:

1. Bump `pyproject.toml`: `requires-python = ">=3.10"`,
   `target-version = "py310"`, add SDK pin
   `openmetadata-ingestion>=1.11.5,<1.13`.
2. Bump `Dockerfile`: `OM_INGESTION_VERSION` 1.6.5 to 1.11.14.
   `scripts/build-and-push.sh` mirrors. Smoke-build locally before
   pushing to `registry.solace.lab`.
3. Apply OM 1.9 `domain` to `domains` rename across the 7 sites
   (`mappers.py`, `event_portal_connector.py`, `bridge/handlers.py`).
4. Pydantic-v2 cleanup: `WorkflowSource.parse_obj()` to
   `.model_validate()`. Drop legacy `__root__` fallback. Drop legacy
   `MessageSchema/SchemaField` fallback in `mappers.py`.
5. Add `LineageDetails.source = LineageSource.Manual` everywhere
   `AddLineageRequest` is built. OM 1.11+ convention.
6. Fix `#51` bridge handler signature mismatch incidentally.
7. Scaffold (no behaviour change yet) `connector/service_spec.py`.
8. Run full pytest + ruff. Fix anything that breaks. NO new tests.
9. Smoke-test against an `openmetadata/server:1.11.x` instance.
10. Build `0.4.0` image. Push to `registry.solace.lab`. Verify the
    AcmeMDM ingestion pilot still produces identical OM output.

**Exit criterion met**: pilot ingestion produces same OM entities
as before, but on top of OM 1.11 SDK. Image `0.4.0` deployed.

---

## Wave 1 (Week 2, SHIPPED at image 0.5.0)

**Goal**: schema-field-parsing live + CAs as Tags + all-versions
default. The user-visible "data is now actually navigable" wave.

**Tickets**: `#64` (schema-field parsing), `#43` (CAs to Tags),
`#54` (all-versions default ON).

**Concrete work**:

1. New `connector/schema_parsers/` package:

   - Imports `metadata.parsers.avro_parser.parse_avro_schema`,
     `metadata.parsers.json_schema_parser.parse_json_schema`,
     `metadata.parsers.protobuf_parser.parse_protobuf_schema`.
   - Dispatcher: `parse(schema_text, schema_type)` returns
     `List[FieldModel]`.
   - Beat-Kafka layer: preserve Avro `logicalType`
     (decimal / date / timestamp-millis) + JSON-Schema `format`
     (date-time / uuid) in `dataTypeDisplay` post-parse.
   - Graceful fallback: on parse exception, log WARN + return
     top-level-only field list. Never break ingestion.

2. `mappers.py.event_to_topic_request()`: replace today's
   top-level-only schema fields with
   `messageSchema.schemaFields = parser.parse(text, st)`.
3. Test fixtures: nested Avro record, JSON Schema with `$ref`,
   Debezium oneOf nullable, Avro union, Avro logical types decimal,
   date, timestamp.
4. Ticket `#43` (Custom Attributes to Tags):

   - `connector/bootstrap.py`: walk
     `/architecture/customAttributeDefinitions` (paginated), create
     OM Classification `EventPortalCustomAttribute_<name>` for each
     (skip names in workflow-config `customAttributeTagExclude`).
   - `mappers.py`: walk `entity.customAttributes` at ingestion; for
     each value, ensure Tag exists (lazy-create), apply to entity.

5. Ticket `#54`: flip `ingestAllVersions` default to `true` in
   `config/example-workflow.yaml`. Add CP `eventPortalIsLatestVersion`
   (bool) in `mappers.py`. Document the OM-UI search filter in
   `README.md`.
6. Tests for `#43` + `#54`.

**Exit criterion met**: AcmeMDM ingest produces:

- Topics with nested SchemaFields (verify in OM UI; fields tree
  expands).
- All event versions as separate Topics (with
  `eventPortalIsLatestVersion`).
- Tags from each CA value (e.g.
  `EventPortalCustomAttribute_DataRetention.7days`).
- Image `0.5.0` deployed.

---

## Wave 2 (Week 3-4, SHIPPED at image 0.6.0)

**Goal**: EDA lineage end-to-end (SAP to Pipeline to Topic to Queue
to Pipeline to SAP), incl. cross-system edges to OM-pre-existing
entities.

**Tickets**: `#66` (ServiceSpec split), `#59` (within-EP Linked
Apps), `#60` (external CA fallback), `#65` (dynamic classification,
parked-pending), `#50` (cross-system YAML edges).

**Concrete work**:

1. Ticket `#66`: split `connector/event_portal_connector.py` into:

   - `EventPortalMetadataSource` (today's main flow).
   - `EventPortalLineageSource` (lineage-only; runs after metadata).
   - Register via `service_spec.py` `DefaultMessagingSpec`.
   - Two workflow YAMLs: `metadata-workflow.yaml` (hourly cron),
     `lineage-workflow.yaml` (daily cron, depends on metadata).

2. Ticket `#59` within-EP Linked Apps:

   - `mappers.py.pipeline_to_pipeline_lineage_request()` reads
     `inbound/outboundApplicationVersionAssociations` from
     `applicationVersion` payload, emits Pipeline to Pipeline
     `AddLineageRequest`s.
   - Lives in `EventPortalLineageSource`.

3. Ticket `#65` dynamic classification (DEFERRED, opt-in):

   - Layer 1: read EP `applicationType` + linked-apps graph
     topology.
   - Layer 2: optional `appClassification.namePatterns` regex.
   - Layer 3: optional `appClassification.sourceSystemAppIds` /
     `sinkSystemAppIds` allow-list (manual override).
   - Status as of Wave 2: scaffold present; reactivation deferred
     to Wave 5 once Beat-Kafka prep starts.

4. Ticket `#65` cross-system resolution:

   - For each system-app: `metadata.es_search_from_fqn` across
     `crossSystemServiceFqns` config services.

5. Ticket `#60` external CA fallback:

   - When `#65` auto-link finds 0 hits, look for EP CA
     `externalSourceOmFqn` / `externalSinkOmFqn`.
   - Bootstrap: optional CLI registers the two CA definitions in EP.

6. Ticket `#50` cross-system YAML edges:

   - New `connector/lineage_workflow.py` (orchestrated via `#66`
     `LineageSource`).
   - Read `lineageEdges` list from workflow YAML (see
     `asset-mapping-spec.md` Cluster 2.5).
   - For each: resolve `from` / `to` FQNs via OM, emit
     `AddLineageRequest`.

7. Tests covering all of above.

**Exit criterion met**: image `0.6.0` deployed; lineage edges
visible in OM UI for the reference E2E flow.

---

## Wave 3 (Week 5, SHIPPED at image 0.7.0)

**Goal**: complete the EP-to-OM type map. After this wave the OM UI
shows everything EP has.

**Tickets**: `#44` (Event API to Container), `#45` (EAPP to
DataProduct), `#52` (first-class Schemas), `#53` (Topic-address
tree), `#55` (Consumer-Queue Container).

**Concrete work**:

1. Ticket `#44` Event API mapping:

   - New mapper `event_api_to_container_request()`.
   - Container under the synthetic StorageService
     `solace-event-portal-event-apis`.
   - Custom Properties: `eventPortalEventApiId`,
     `eventPortalEventApiVersionId`.
   - Lineage Container to/from Topic (one edge per
     `producedEventVersionIds` + `consumedEventVersionIds`).

2. Ticket `#45` EAPP mapping:

   - New mapper `eapp_to_data_product_request()`.
   - DataProduct with native `assets[]` referencing the `#44`
     EventAPI Containers.
   - `plans[].solaceClassOfServicePolicy` -> CP `eventPortalPlans`
     (markdown table).

3. Ticket `#52` first-class Schemas:

   - New synthetic CustomDatabase service
     `solace-event-portal-schemas`.
   - One DatabaseSchema per EP Application Domain.
   - One Table per EP Schema + Version with the parsed Columns from
     the `#64` parser as the body.
   - Lineage Schema Table to Topic per `schemaVersionId`.

4. Ticket `#53` Topic-address Container tree:

   - New synthetic StorageService `solace-event-portal-topic-tree`.
   - Walk topic addresses split by `/`. Create Container per segment
     up to `topicTreeMaxDepth` config (default 3).
   - Variable segments (`{region}`) sanitised to `_region_` in the
     Container name, kept verbatim in displayName.
   - Lineage Container (deepest in-cap segment) to Topic.

5. Ticket `#55` Consumer-Queue (Container per `consumers[]`):

   - New synthetic StorageService `solace-event-portal-consumers`.
   - Container per EP consumer with subscription patterns +
     `brokerType` + queue name as CPs.
   - Lineage Topic to Container (one edge per
     `attractedEventVersionId`).
   - Lineage Container to Pipeline (the owning consuming app).

6. Tests for all new mappers + fixtures.

**Exit criterion met**: ALDI's "data product catalog" view in OM
matches EP's coverage 1:1. Image `0.7.0` deployed.

---

## Wave 4 (Week 6, SHIPPED at image 0.8.0)

**Goal**: owners resolve to humans. Drift-detection catches deletes
on the EP side and tombstones the matching OM entity.

**Tickets shipped**: `#57` (userIdToEmailMap), `#56` (AsyncAPI
sourceUrl), `#48` (Sub-Domain hierarchy), `#61` (soft-delete with
Retired tag), `#58` (EP Teams documented as parked).

**Deferred to Wave 4.5**: `#49` (OM to EP bi-directional
write-back). Sliced out so the high-blast-radius write path lands in
its own image (`0.8.5`) with shadow-deploy. See "Wave 4.5" below.

**Concrete work**:

1. Ticket `#57` userIdToEmailMap:

   - New workflow-config option (str to str map; accepts both dict
     and `id1:email1,id2:email2` comma-string forms).
   - `connector/owner_resolver.py`: lookup `email = map[user_id]`,
     then `metadata.get_by_name(User, fqn=email)`, then set
     `owners=[ref]` (list; OM 1.11 native).
   - WARN log on miss (once per unmapped ID), never error.
   - Flip `resolveOwners` default to `true` now that misses degrade
     gracefully.

2. Ticket `#56` AsyncAPI sourceUrl:

   - `EpUrls` gains `api_url` + `async_api(app_version_id)` helper.
   - `mappers.py.app_to_pipeline_request()` sets
     `Pipeline.sourceUrl` to the downloadable EP AsyncAPI doc
     `api/v2/architecture/applicationVersions/{id}/asyncApi`.
   - Without `api_url` the Pipeline ingests without `sourceUrl`
     (clean no-op rather than broken link).

3. Ticket `#48` Sub-Domain hierarchy:

   - New workflow-config option
     `omDomainParentMap: {epDomainName: omParentFqn}`.
   - `mappers.py.domain_to_create_request()` resolves the parent
     FQN, sets `CreateDomainRequest.parent`.

4. Ticket `#61` Soft-delete with Retired tag:

   - Extend reconcile (ticket `#23`) to detect missing-in-EP
     entities via deterministic FQN diff.
   - Apply tag `EventPortal.Retired` + CP `eventPortalDeletedAt`
     (ISO-8601 UTC) via JSON-Patch.
   - New `connector/fqn.py` module: pure FQN helpers, no OM SDK
     dependency, so the slim bridge image can use them.
   - New `bridge/main.py` flags `--soft-delete-missing` and
     `--auto-purge-after-days N`. Default behaviour is
     forever-tombstone; hard-delete is opt-in.

5. Ticket `#58` EP Teams: documented as parked. EP v2 Cloud
   Enterprise exposes no team API (smoke-tested 2026-05-27); revisit
   when Solace ships one.
6. Tests for all of the above.

**Exit criterion met**: OM users see human owners (via the static
`userIdToEmailMap`). Topics + Pipelines for events / apps deleted
on the EP side get the `EventPortal.Retired` tag within one
`--soft-delete-missing` cron tick. Image `0.8.0` deployed.

---

## Wave 4.5 (CODE-COMPLETE, flag-off; ships in the next image)

**Goal**: OM to EP write-back for governance fields. Sliced out of
Wave 4 so the write path lands behind its own image + shadow-deploy
without slowing down the identity + soft-delete improvements.

**Closure note**: implemented in `bridge/writeback.py` (pure Cluster 5
per-field policy + `WritebackProcessor` queue/worker/drain),
`EventPortalWriter` (separate write-scoped token), and the
`BRIDGE_MODE=writeback` OM-EntityChangeEvent receiver. OFF
(`BRIDGE_WB_ENABLED=false`) + DRY-RUN (`BRIDGE_WB_DRY_RUN=true`) by
default; live writes require both flags flipped + `EP_WRITER_TOKEN`.
The EP write wire-contract is isolated in `EventPortalWriter` and must
be verified under shadow deploy (the drift cron #4 below) before going
live. Adversarial diff review caught + fixed a drain deadlock, a
double-metrics exposition, and stale lifecycle docstrings.

**Tickets**: `#49` only.

**Concrete work** (when picked up):

1. New `bridge/writeback.py`:

   - Subscribes to OM EntityChangeEvents via OM webhook subscription
     (registered idempotently on startup).
   - For each change, applies the per-field policy table (see
     `asset-mapping-spec.md` Cluster 5).
   - PUT EP `/architecture/<entity>/{id}` for CA values:
     `epExtendedDescription`, `epCertification`,
     `epAdditionalOwners`, `externalSourceOmFqn`,
     `externalSinkOmFqn`.

2. Bootstrap: registers required EP CA definitions if missing.
3. **Two separate K8s Secrets**: `ep-token-reader` (used by
   metadata + lineage sources) and `ep-token-writer` (used only by
   bridge writeback). ALDI rotates both 90d manual.
4. Daily drift-diff cron: compares OM vs EP for OM-wins fields,
   reports via OTel (alert if drift exceeds threshold).
5. Feature-flagged: `writebackEnabled: false` default.
6. Target image: `0.8.5` (separate from Wave 4's `0.8.0`).

**Exit criterion**: adding a tag in OM (e.g.
`EventPortalCertification.Tier1`) appears as EP CA on the matching
entity within 5 minutes. Drift cron green for 7 days under shadow
deploy before enabling on prod.

---

## Wave 5 (Week 7-8, SHIPPED at image 0.9.0)

**Goal**: enterprise-grade observability + secrets + multi-tenant +
PII.

**Closure note**: delivered in four slices (commits on master):
observability + lifecycle foundation (#11/#13/#10/#63), then
multi-tenant (#41), PII (#62), Helm chart (#15), and these docs
(#16/#67). Each non-locally-testable diff was verified by an
adversarial multi-agent review before commit. `dynamic classification`
(#65) stays parked. The bridge write-back queue-depth metric (#10) is
registered at 0 until Wave 4.5 / #49 ships the queue.

**Tickets**: `#41` (multi-tenant), `#62` (PII), `#63` (OTel),
`#10` (Prometheus metrics), `#11` (structured logging), `#13`
(graceful shutdown), `#15` (Helm chart), `#16` (Phase 2 docs),
`#67` (Beat-Kafka docs).

**Concrete work**:

1. Ticket `#41` multi-tenant: two `MessagingService` instances in
   one OM, two sets of workflow YAMLs, shared
   `solace-event-portal-apps` PipelineService with tenant-prefixed
   Pipeline FQNs to avoid collision.
2. Ticket `#62` PII:

   - Bootstrap registers `pii` CA-definition in EP if missing.
   - Mapper: at ingestion, if any PII source signals (CA / tag /
     topic-segment / schema-field `x-pii` annotation) add Tag
     `EventPortalCompliance.PII` + CP
     `eventPortalContainsPii=true`.
   - Sample-data subscribe (ticket `#2` already shipped):
     hard-block when target Topic has the PII tag.
   - Field-level: extend `#64` parser to annotate FieldModel with
     PII tag based on `x-pii: true` annotation in JSON-Schema or
     Avro `doc`.

3. Ticket `#63` OTel: refactor today's logging to OpenTelemetry
   spans + logs via OTLP/HTTP. Spans tagged with
   `om.entity.type/fqn`, `ep.entity.id`, actor, action, outcome.
   Helm chart bundles optional OTel Collector sidecar.
4. Ticket `#10` Prometheus `/metrics` endpoint in bridge (req
   latency, EP/OM 401 counters, write-back queue depth).
5. Ticket `#11` Structured JSON logging with trace_id correlation
   (cross-cut with `#63`).
6. Ticket `#13` Graceful shutdown: SIGTERM drains write-back queue,
   flushes dedupe, and closes EP/OM connections.
7. Ticket `#15` `charts/solace-eventportal-bridge` Helm chart.
8. Ticket `#16` Phase 2 README + compat matrix update.
9. Ticket `#67` README "Why this connector" section with Beat-Kafka
   list.

**Exit criterion**: ALDI IT-Sec sign-off on PII handling.
Prometheus dashboards live. Image `0.9.0` deployed.

---

## Cross-wave concerns

- **Versioning**: bump minor for each wave (`0.4.0` Wave 0,
  `0.5.0` Wave 1, ..., `0.9.0` Wave 5 = the Beta). Wave 4.5 rides the
  `0.9.0` line as a flag-off feature.
- **Branching**: stay on master per repo convention; tag at each
  wave exit.
- **CI**: pytest + ruff after every wave; add tox matrix for
  1.11 + 1.12 at Wave 0.
- **Communication**: weekly demo to ALDI Platform Team at end of
  each wave; show new entities live in staging OM UI.

---

## Open questions for ALDI sign-off

1. Wave 0 timing -- ALDI's OM cluster currently at 1.11.x
   (Cluster 2.1 confirmed). Verify exact patch version, schedule
   staging-side SDK bump alongside our `0.4.0` image. (RESOLVED.)
2. Wave 4.5 / ticket `#49` -- confirm scope (Tags / Description /
   Cert / Owner / External-link) matches expectations. EP
   write-token approval (security topic).
3. Wave 5 / ticket `#62` -- list of source-signal patterns for PII
   detection (CA name? Tag name pattern? Topic-segment pattern?).
