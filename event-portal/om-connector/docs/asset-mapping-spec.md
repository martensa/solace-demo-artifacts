# Asset-Mapping Spec — Solace Event Portal -> OpenMetadata

Living document. Updated cluster-by-cluster as ALDI Nord answers the
production-discovery one-pager (`aldi-discovery-onepager.md`). Each
cluster has: decided mapping, alternatives we rejected and why, the
status of the implementation ticket(s), and any open follow-ups.

**Reading order.** Start with the entity-mapping table at the top —
it is the at-a-glance view of every EP construct and where it lands in
OM. The per-cluster sections below explain *why* each mapping was
chosen.

---

## Entity-mapping table (target state for v1.0)

| EP construct | OM target | Mode | Cluster | Ticket |
| --- | --- | --- | --- | --- |
| MessagingService (per EP tenant) | OM MessagingService | 1:1, 2 instances in 1 OM | 1 | #41 |
| Application Domain | OM Domain | 1:1 | 1 (pilot) | shipped |
| Application Version | OM Pipeline (synthetic PipelineService) | latest only by default, all versions opt-in | 1 (pilot) | shipped |
| Event Version | OM Topic | latest only by default | 1 (pilot) | shipped |
| Schema Version | embedded in `Topic.messageSchema` AND first-class Table under CustomDatabase `solace-event-portal-schemas` | both | 1+3 | shipped (embed), #52 (promote) |
| Topic-address path | OM Container tree (folder-by-segment, depth-cap default 3) under StorageService `solace-event-portal-topic-tree` | tree | 3 | #53 |
| All event/app versions | one OM Topic / Pipeline per version (default ON) | per-version | 3 | #54 |
| Consumer Subscription | OM Container under parent EAPP DataProduct + lineage Subscription -> Topic + Subscription -> App | per subscription | 3 | #55 |
| AsyncAPI export | Pipeline.sourceUrl points to EP `/asyncApiSpec` endpoint | per app version | 3 | #56 |
| User identity (EP `createdBy` -> OM owner) | static `userIdToEmailMap` in workflow config (EP exposes no IAM API) | manual map, quarterly sync | 4 | #57 |
| EP Teams | BLOCKED (EP exposes no team API) | parked | 4 | #58 |
| Linked Applications (EP App<->EP App) | OM Pipeline-Pipeline lineage edge via `inbound/outboundApplicationVersionAssociations` | per association | 5 | #59 |
| External-system linkage (SAP, Snowflake, Databricks) | OM lineage edge via EP CA `externalSource/SinkOmFqn` | per CA value | 5 | #60 |
| EP entity deleted | Soft-delete with `EventPortalLifecycle.Retired` tag + `eventPortalDeletedAt` CP; no auto-hard-delete | per entity, reconcile-driven | 5 | #61 |
| PII flag on entity / SchemaField | Tag `EventPortalCompliance.PII` + CP `eventPortalContainsPii=true`; sample-data hard-blocked | per entity / per field | 6 | #62 |
| Audit + telemetry | OTel single exporter -> Collector fan-out to Splunk/DataDog/Loki/Prometheus | per action | 6 | #63 |
| Schema-Field parsing (Avro / JSON / Protobuf) | Recursive parser -> `messageSchema.schemaFields[]` with nested children; FQN per field for column-lineage | per schema version | NEW REQ | #64 |
| App classification (System vs Pipeline) | Heuristic: name regex + Linked-Apps graph; auto-link external systems via OM-search | per app | NEW REQ | #65 |
| Pub/Sub declaration | OM Lineage edge Pipeline <-> Topic | direct edge | 1 (pilot) | shipped |
| Lifecycle state | Classification tag `EventPortal.<State>` + Custom Property | additive | 1 (pilot) | shipped |
| Topic address | Custom Property `eventPortalTopicAddress` | string | 1 (pilot) | shipped |
| EP UI back-link | Markdown Custom Property (Topic + Pipeline) | configurable base URL | 1 (pilot) | shipped |
| Modeled Event Mesh | (not mapped — see Cluster 1) | parked | 1 | #42 closed wontfix |
| EP Tags | Classification `EventPortalTag` + one Tag per value | per value | 1+2 | shipped (pattern), #43 (extend) |
| Custom Attributes | Classification `EventPortalCustomAttribute_<name>` + one Tag per value (exclude list opt-out) | per value | 1+2 | #43 (revised) |
| Event API | OM Container (under MessagingService) + lineage to Events | new | 1 | #44 |
| Event API Product | OM DataProduct | new | 1 | #45 |
| Domain hierarchy | `CreateDomainRequest.parent` via explicit `omDomainParentMap` config | per domain | 2 | #48 |
| Cross-system lineage (Kafka / Snowflake / Databricks) | separate `lineage_workflow.py` with explicit YAML edges; v1.1 auto-discover | sidecar workflow | 2 | #50 |
| OM -> EP write-back (Tags + CAs) | bridge reverse-write to `/architecture/<entity>/{id}` PUT | bridge reverse channel | 2 (leaks 5) | #49 |
| OM SDK version | pinned `>=1.11,<1.14` | build matrix | 2 | #47 |
| Audit feed | n/a (Cloud Enterprise does not expose it) | watermark reconcile only | 1 | n/a |
| Webhook subscriptions | n/a (Cloud Enterprise does not expose it) | polling bridge only | 1 | n/a |

Items below the divider in Cluster 1 are decided. Clusters 2-6 will
extend this table as answers land.

---

## Cluster 1 — EP edition & API capabilities

**ALDI answers received 2026-05-26.**

| Q | Answer | Decision impact |
| --- | --- | --- |
| 1.1 EP edition | Cloud Enterprise | Sets the available endpoint matrix |
| 1.2 Tenants / regions | 2 tenants in 1 region | -> Multi-tenant deploy template |
| 1.3 Modeled Event Mesh | "yes" (per ALDI) but `/architecture/modeledEventMeshes` -> 404 on seall (Cloud Enterprise) | Assumption: ALDI confused MEM with Event API Product. Closing #42 as wontfix; revisit only if ALDI confirms MEM in their UI |
| 1.4 Audit feed | no | No audit-replay; rely on watermark reconcile |
| 1.5 Webhooks | no | `BRIDGE_MODE=polling` only; no `--register-webhook` work |
| 1.6 Custom Attributes used | yes on Domain, Event, App, Schema | Hybrid mapping (see #43) |
| 1.7 Event API + Event API Product | yes | -> #44 (Event API -> OM Container) + #45 (EAPP -> OM DataProduct) |
| 1.8 Webhook signing | n/a | n/a (1.5 = no) |

### 1.1 + 1.2 — Multi-tenant deployment (#41)

**Decision.** 1 OpenMetadata instance hosts **2 MessagingServices**,
one per EP tenant. Each MessagingService has its own connection
config (`organizationId`, API token, ep-console URL, include/exclude
filter pattern). PipelineService is shared (`solace-event-portal-apps`)
but Pipeline FQNs are tenant-prefixed to avoid collision.

**Alternatives rejected.**
- *2 OM instances:* doubles operational cost, defeats the "single
  pane of glass" goal.
- *1 MessagingService with both tenants merged:* loses the per-tenant
  RBAC / certification / filter boundary; entity FQNs would have to
  encode tenant manually.

**Open follow-up.** Naming convention for the two services. Proposal:
`solace-ep-<tenant-slug>` (e.g. `solace-ep-prod`, `solace-ep-dev`).
Locked in Cluster 5 (source-of-truth) once we know if both tenants
are dev/prod or two parallel production environments.

### 1.3 — Modeled Event Mesh (#42 closed wontfix)

**Decision.** No mapping. Closing #42 as not-applicable for ALDI's
Cloud Enterprise edition. The connector's `list_modeled_event_meshes()`
already returns `[]` on 404 so this is a no-op at runtime.

**Reopen trigger.** If ALDI confirms they see a "Modeled Event Mesh"
menu item in their EP UI (vs. confused with Event API Product), we
revisit. Until then the EAPP mapping (#45) covers their use case.

### 1.6 — Custom Attributes -> hybrid mapping (#43)

**Decision.** Hybrid, allow-list driven.

- **Default**: every EP Custom Attribute lands as an OM **Custom
  Property** (string) on the target entity (Topic for Event/Schema
  CAs, Pipeline for App CAs, OM Domain for Domain CAs). The CP name
  is `epCustom_<attributeName>` (camelCase, sanitised).
- **Allow-list override**: workflow config exposes
  `customAttributeAsTag: ["acl-principal", "confidential", ...]`.
  Each listed attribute name is instead mapped to a **Classification**
  (`EventPortalCustomAttribute_<Name>`) with one **Tag** per unique
  value seen during ingestion. Auto-discovered from
  `/architecture/customAttributeDefinitions` -> seeded as empty
  Classifications during `bootstrap` so the UI shows them even before
  the first value lands.

**Why hybrid.** All sampled CAs in seall are `valueType=STRING` with
no `allowedValues` -> free-text. Blind Tag-mapping would explode (e.g.
`acl-principal` with one tag per user ID). But ALDI explicitly asked
for Tags-with-Auto-Discovery, so we keep that capability behind a
config flag for the attributes where Tag semantics actually fit
(low-cardinality, controlled vocabulary).

**Alternatives rejected.**
- *All as Custom Properties:* simple but defeats ALDI's stated goal
  of using CAs for governance filters.
- *All as Tags:* tag explosion on high-cardinality string CAs.

**Implementation notes.** Auto-discovery walks
`/architecture/customAttributeDefinitions` (paginated, ~3 pages on
seall) during `bootstrap` and `--reconcile`. Definitions newly seen
are added to the OM Classification list (always created, even if
allow-list empty -> UI hint for the operator). Tag creation happens
lazily during ingestion as values are observed.

### 1.7 — Event API + Event API Product (#44 + #45)

**Decision.**

- **Event API** -> OM **Container** entity under the
  MessagingService. One Container per EventApi+latest-Version. Lineage
  edges Container -> Topic for each `producedEventVersionId` /
  `consumedEventVersionIds` (direction matters: produced = Container
  -> Topic, consumed = Topic -> Container).
- **Event API Product** -> OM **DataProduct**. One DataProduct per
  EAPP+latest-Version. `assets` list references the underlying Event
  API Containers (`eventApiVersionIds`). Plans
  (`plans[].solaceClassOfServicePolicy`) land as Custom Properties on
  the DataProduct.

**Why Container for Event API.** OM Container is the closest match
for "a stable contract surface bundling multiple events". DataProduct
is reserved for the higher-level marketing surface (EAPP) which
*declares* one or more APIs and is what a consumer subscribes to.

**Alternatives rejected.**
- *Event API as Pipeline:* Pipeline implies execution semantics;
  Event API is a contract, not a runtime.
- *Event API + EAPP both as DataProduct:* loses the two-tier
  distinction (contract vs. product).
- *Event API as a tag on Topic:* loses ability to surface API-level
  description/version/owner in OM UI.

**Open follow-ups.**
- ALDI says 1-10 Event APIs per domain bundled by 2-5 EAPPs. At that
  scale, Container is fine. If volume grows 10x, revisit (Container
  list views get noisy past ~50 per service).
- Plan list flattening: should each Plan be a child entity (Container
  inside Container) or stay as JSON in a Custom Property? Locked when
  we have a real plan example from ALDI.

---

## Cluster 2 — OM edition, version & feature-set

**ALDI answers received 2026-05-26.**

| Q | Answer | Decision impact |
| --- | --- | --- |
| 2.1 OM edition / version | Self-Hosted 1.11, upgrade to 1.13 imminent | -> SDK matrix bump (#47) |
| 2.2 Domains hierarchy | Hierarchical | -> Sub-Domain derivation (#48) |
| 2.3 Glossary | In use but no mapping required (out of scope) | No glossary-mapper |
| 2.4 Existing Tags / Classifications | In use. ALDI wants: EP-Tags -> own OM Classifications, CAs -> Tags, and **OM edits sync back to EP** | Reinforces #43; opens bi-dir sync #49 |
| 2.5 Other OM connectors | Kafka, Snowflake, Databricks. Wants cross-functional lineage. Orient at OM Databricks connector | New cross-system lineage workflow (#50) |
| 2.6 Operator | ALDI Platform Team | Support escalation: ALDI-PT; Solace = product owner |
| 2.7 Upgrade cadence | Not defined | Deferred. Build for current + N-1. Reassess in Cluster 6 |

### 2.1 — SDK compatibility matrix (#47)

**Decision.** Build v1.0 against `openmetadata-ingestion>=1.11.5,<1.13`.
Lower bound = ALDI's current (1.11.14.0 is latest 1.11.x patch);
upper bound = the upcoming 1.13 line (NOT YET RELEASED as of
2026-05-26 — latest stable on PyPI is 1.12.8.9, released
2026-05-13). When 1.13 ships we re-pin to `<1.14` after a probe.

**Verified breaking changes from 1.6 -> 1.11 (release notes).**
- **OM 1.9**: `domain` field renamed to `domains` (List) on every
  entity. `patch_domain()` signature changed. -> 7 call sites in
  `mappers.py` + `event_portal_connector.py` + `bridge/handlers.py`.
- **OM 1.11**: Python 3.9 EOL'd. Minimum Python = 3.10. Airflow 3.x
  is the new default ingestion base image. Elasticsearch 8.x +
  OpenSearch 2.x server required (ALDI Plattform-Team
  responsibility).
- **OM 1.10**: `workflow.print_status()` moved inside `execute()`.
  We don't call it externally; no impact.

**Probable but unverified.** Agent's report claimed `owner -> owners`
(list) migration around 1.10. Not in any release notes we cross-
checked, but plausible. Confirm at build time against
`openmetadata/server:1.11.x`.

**Action items.**
1. Bump `pyproject.toml` `requires-python` to `>=3.10`,
   `target-version = "py310"`, add SDK pin.
2. Bump `Dockerfile` `OM_INGESTION_VERSION` 1.6.5 -> 1.11.14.
3. Patch 7 `domain=` -> `domains=[...]` sites.
4. Migrate Pydantic v1 shims (`parse_obj` -> `model_validate`,
   `__root__` -> `root`).
5. Rebuild Docker, run pytest, smoke-test against an
   `openmetadata/server:1.11.x` instance BEFORE shipping.
6. Add a `tox` matrix entry for 1.11 (and 1.12 once we're stable).

**Risk.** SDK pin `<1.13` doesn't guarantee server compat with
fields added later. ALDI's "1.13 imminent" statement contradicts
PyPI reality — clarify with ALDI whether they meant 1.12 or wait
for 1.13 GA.

### 2.2 — Sub-Domain hierarchy (#48)

**Decision.** EP itself has no native sub-domain field. We support
hierarchy via an **explicit map in workflow config**:

```yaml
sourceConfig:
  config:
    omDomainParentMap:
      "AcmeMasterDataManagement": "Acme"
      "AcmeRetailMasterDataManagement": "Acme.Retail"
```

The mapper sets `CreateDomainRequest.parent` to the resolved parent
FQN. Empty / missing entries -> domain is created flat under the
service root.

**Alternatives rejected.**
- *Naming-convention split (e.g. dot in domain name):* EP domain names
  don't follow a consistent convention at ALDI; would produce wrong
  hierarchies for legacy names.
- *EP Custom Attribute lookup (e.g. CA `parentDomain`):* possible for
  v1.1 once ALDI agrees on a CA name; for v1.0 the explicit map is
  predictable and reviewable.

**Open follow-up.** Do parent OM Domains themselves need a description
/ owner / tags, or are they pure containers? Default: pure containers
auto-created on demand with name only.

### 2.3 — Glossary

Out of scope per ALDI. No mapper. Re-open if ALDI later wants
`epTag -> glossaryTerm` mapping.

### 2.4 — Tags + Classifications + bi-directional sync (revises #43, opens #49)

**Decision part 1 — outbound (EP -> OM).**

- **EP Tags** (the existing `tags[]` array on Event / App / Schema)
  -> dedicated Classification `EventPortalTag` with one Tag per
  EP-tag value. *(Pilot already ships Lifecycle-State this way under
  `EventPortal.<State>`.)*
- **EP Custom Attributes** -> one Classification per CA-name
  (`EventPortalCustomAttribute_<name>`), one Tag per unique value
  seen at ingest time. **Override:** the hybrid-with-CP fallback from
  Cluster 1 is *removed* — ALDI explicitly wants tags. Safeguard:
  workflow-config `customAttributeTagExclude: ["acl-principal"]`
  opts an attribute out if its cardinality is high.

**Decision part 2 — inbound (OM -> EP) (#49).**

ALDI added "Changes in OM should be synced back to EP" — this is
**Cluster 5 territory** but we capture the requirement here. v1.0
scope kept narrow:

| OM change | Sync back to EP? | How |
| --- | --- | --- |
| Tag add/remove on Topic mapped to CA | yes | bridge subscribes to OM webhook -> PUT EP entity custom-attribute value |
| Tag add/remove on Topic mapped to EP-Tag | yes | bridge -> PUT EP entity tags[] |
| Description edit | parked (Cluster 5.2) | needs ALDI sign-off |
| Owner change | parked (Cluster 4 first) | RBAC implications |
| Certification | parked (Cluster 5.6) | |

Conflict policy default: **last-writer-wins with audit log entry**.
Hard policy decision deferred to Cluster 5.3.

**Risk.** Without OM audit-feed subscription (OM has webhooks but the
bridge currently only listens to EP) we add a new failure mode
(silent drift if bridge down). Mitigated by a periodic full-diff
reconcile in the bridge (#23 pattern, reversed direction).

### 2.5 — Cross-system lineage (#50)

**Decision.** New companion workflow `lineage_workflow.py`. v1.0 uses
**explicit YAML mapping**:

```yaml
lineageEdges:
  - from: "solace-ep-prod.AcmeMasterDataManagement.customerCreated_v1"
    to: "kafka-prod.customer-events.customer-created"
    description: "Solace -> Kafka bridge (kafka-connect-solace)"
  - from: "kafka-prod.customer-events.customer-created"
    to: "snowflake-prod.RAW.STG_CUSTOMER_EVENTS"
    description: "Snowpipe streaming ingest"
  - from: "snowflake-prod.RAW.STG_CUSTOMER_EVENTS"
    to: "databricks-prod.silver.customer_events"
    description: "Daily Spark notebook sync"
```

v1.1+ adds **auto-discovery**, mirroring the OM Databricks connector:
parse PySpark / SQL artefacts (`format("solace")`, `format("delta")`)
and emit edges automatically. This needs ALDI to expose their
Databricks workspace + Snowflake metadata — explicit follow-up in
Cluster 3 (asset-completeness).

**Alternatives rejected.**
- *Broker-payload-shape matching:* too fuzzy, false-positive prone.
- *In-band lineage in this connector:* lineage spans OTHER services
  (Snowflake, Databricks); belongs in a sibling workflow that runs
  *after* all source connectors landed their entities.

**Coordinate with #44.** Event API Container is a natural bridging
entity: a single EAPP/Event-API can fan out to many downstream
consumers (Kafka topic, Snowflake table). Cleaner lineage if the
edge anchors on Event API rather than every Topic.

### 2.6 — Operations ownership

ALDI Platform Team operates OM. Solace remains product owner for the
connector + bridge images. Implication: bug fixes ship via image
release, not via support ticket. Distribution path locked in Cluster 6
(when registry / signing model is decided).

### 2.7 — Upgrade cadence

Deferred. v1.0 supports OM 1.11 + 1.13 explicitly (see #47); compat
matrix re-evaluated when ALDI commits to a cadence.

---

## Cluster 3 — Asset-mapping completeness

**ALDI answers received 2026-05-26.**

| Q | Answer | Decision impact |
| --- | --- | --- |
| 3.1 Schemas first-class? | **Promote** (both — keep embedded + first-class) | #52 |
| 3.2 MEM -> DataProduct | No (already decided Cluster 1) | n/a |
| 3.3 EAPP -> DataProduct | Yes (already #45) | n/a |
| 3.4 Topic-address hierarchy | Folder-by-segment, depth-cap 3 (sign-off received) | #53 |
| 3.5 Versions | All-versions (default ON) | #54 |
| 3.6 CAs target | Tags (already Cluster 2.4) | #43 |
| 3.7 EP Categories | Not in use at ALDI | n/a (no mapper) |
| 3.8 Subscriptions | Separate entities (not just lineage) | #55 |
| 3.9 Description aggregation | Event > EventVersion > Schema with markdown dividers | shipped (pattern), extend with Schema block |
| 3.10 AsyncAPI export | Yes (attach to Pipeline) | #56 |

### 3.1 — Schemas as first-class entities (#52)

**Decision.** EP Schemas get promoted to first-class OM entities via
a synthetic CustomDatabase service `solace-event-portal-schemas`,
with one DatabaseSchema per EP-Domain and one Table-equivalent per
EP-Schema+Version. Topic.messageSchema stays embedded for
backward-compat; a new Custom Property
`eventPortalSchemaEntityFqn` cross-links the Topic to the first-class
schema entity (clickable in OM UI).

**Why both, not promote-only.** Embedded `messageSchema` is what most
existing OM views expect (Kafka connector parity). Removing it would
break standard "see the schema of this topic" workflows in OM. The
first-class entity is additive — gives schemas their own page,
description, owner, version history, lineage.

**Lineage.** Schema -> Topic (the schema is upstream of every topic
that carries it). Schema -> Schema for `$ref` references between
schemas (future, if/when EP exposes ref metadata).

### 3.4 — Topic-address hierarchy (#53, RECOMMENDATION)

**Solace recommendation: folder-by-segment with depth cap.** Each
`/` in EP topic-address becomes a Container level. Example:

```
acme/md/customer/created/v1  ->  Container 'acme'
                                 -> 'md'
                                    -> 'customer'  (depth=3 default leaf)
                                       Topic refs hang here
```

Safeguard: `topicAddressContainerDepth` connection option (default
`3`). Past depth-3 the rest of the path stays as `eventPortalTopicAddress`
custom property on the Topic.

**Why folder-by-segment.** Topic patterns ARE the primary navigation
construct EP engineers think in. Container UI gives breadcrumb +
search + per-folder description/owner/RBAC. Three-level cap keeps
the tree shallow.

**Why not folder-by-business-domain.** Redundant — we already map EP
Application Domain -> OM Domain, which serves that purpose.

**Why not flat.** Loses the navigation use case ALDI is asking for.

**Caveat.** OM Container is technically a Storage-service concept
(S3 folders etc.). Re-purposing it for topic hierarchy is a misuse,
but no worse than using Pipeline for EP Apps (already shipped). If
this becomes a friction point with OM upstream we revisit (e.g.
contribute a native MessagingHierarchy entity).

**Confirmed by ALDI 2026-05-26.** Folder-by-segment, depth-cap = 3.

### 3.5 — All versions (#54)

**Decision.** Flip `ingestAllVersions=true` as default. Every event
version becomes its own Topic; every application version becomes its
own Pipeline. Risk: entity count multiplies (100 events * avg-5
versions = 500 Topics). New Custom Property
`eventPortalIsLatestVersion` (bool) drives a default OM search filter
to hide deprecated versions out of the box.

**Open.** Need a small UI guidance doc for ALDI: "default OM Topic
search should filter `lifecycle=current AND eventPortalIsLatestVersion=true`
unless investigating version history".

### 3.7 — EP Categories

Confirmed not in use at ALDI. No mapper. Reopen if a domain
later adopts Categories — would map to OM Tags consistent with
3.6 (CAs -> Tags).

### 3.8 — Consumer subscriptions as entities (#55)

**Decision.** Each EP Subscription becomes its own OM Container
under the parent EAPP DataProduct (or under a synthetic
`solace-event-portal-subscriptions` service). Subscription entity
carries:
- description (consumer rationale, owner-provided)
- owner (consuming-app owner)
- filter pattern (EP subscription wildcard, e.g. `acme/md/customer/>`)
- QoS / SLA (from EAPP plan -> Custom Properties)
- lineage edges Subscription -> Topic (one per matched event) +
  Subscription -> ConsumingApp

**Why Container, not lineage-only.** ALDI explicitly asked for
queryable + RBAC'd subscription objects. Lineage edges aren't
discoverable in OM search; entities are.

**Coordinate with #50.** Subscription is a natural lineage anchor
for cross-system flows: downstream Kafka/Snowflake consumers attach
to Subscription, not directly to Topic.

### 3.9 — Description aggregation

Unanswered (question echoed back). **Default proposal**:

```
[Event description] (primary, top of OM Topic description)

---
**Version notes** (Schema vN):
[EventVersion description]

---
**Schema** ([SchemaName vN.M](EP-link)):
[Schema description]
```

Order: Event > EventVersion > Schema, concatenated with `---`
markdown dividers + bold section headings. Today's pilot already
does Event+EventVersion; adding Schema is a 5-line mapper change.

**Confirmed by ALDI 2026-05-26.** Order locked.

### 3.10 — AsyncAPI export (#56)

**Decision.** Set `Pipeline.sourceUrl` = EP endpoint
`/architecture/applicationVersions/{id}/asyncApiSpec`. v1.0 = direct
EP-endpoint URL (requires EP token in browser). v1.1 = fetch on
ingest + store on shared volume + sourceUrl points to that (no token
needed at view time). Extends to #44 Event API Containers if EP
exposes per-EventApi AsyncAPI.

---

## Cluster 4 — Identity, ownership & teams

**Smoke-test against seall Cloud Enterprise (2026-05-27)** — HARD
constraint discovered before ALDI answers landed:

| Path | Status |
| --- | --- |
| `/iam/users`, `/iam/users/{id}`, `/iam/teams` | 404 |
| `/admin/users`, `/users/{id}`, `/sso/users` | 404 |
| `/missionControl/users`, `/me`, `/organizations` | 404 |
| `/architecture/teams` | 404 |
| Domain payload owner fields | none — only `createdBy`/`changedBy` user-IDs |
| Event payload owner fields | none — only `createdBy`/`changedBy` user-IDs |

**Verdict.** EP Cloud Enterprise v2 has no user-lookup / team-lookup
API surface. Owner resolution at runtime is impossible — only a
static config-driven map works for v1.0.

### Pre-committed decisions (no ALDI input needed)

- **4.3 EP user-lookup endpoint**: NO. Confirmed via 10-path probe.
- **4.4 Static `userIdToEmailMap`**: YES (only viable path). #57
  ships the connection option + mapper integration.
- **4.6 EP Teams -> OM Teams**: BLOCKED. EP exposes no team API.
  #58 parks pending ALDI clarification.

### ALDI answers received 2026-05-27

| Q | Answer | Decision impact |
| --- | --- | --- |
| 4.1 EP-User + OM-User same identity | Yes (same Keycloak login) | Map can use email as cross-system key |
| 4.2 Keycloak claim joining identities | `email` | Map value = email; OM user lookup by email |
| 4.5 Multi-owner support | Yes | #57 mapper assigns `owners=[...]` list; OM 1.11 native |
| 4.7 EP connector-account rotation | 90d MANUAL | Cluster 6 risk: manual = fragile; pursue Vault automation in v1.1 |
| 4.8 OM ingestion-bot JWT rotation | 90d MANUAL | Same risk as 4.7 |

Architecture implication for ALDI: a quarterly process is needed to
keep `userIdToEmailMap` current. Sources of truth: EP UI's
user-listing (manual extract) or — better — a synthetic build step
that reads from ALDI's Keycloak directory and emits the map as a
Kubernetes Secret consumed by the workflow YAML.

**Security note (4.7/4.8)**: Manual 90-day rotation is a known
fragility — high risk of stale tokens silently breaking ingestion
mid-cycle. **v1.0** ships with the manual process documented;
**v1.1** must add Vault-backed rotation (see Cluster 6 #62).
Until then: add a Prometheus alert on EP-401 + OM-401 response
counters (already on #10 backlog) so silent breakage triggers a
page.

---

## Cluster 5 — Bi-directionality & source of truth

**ALDI answers received 2026-05-27**, plus EP-payload smoke-test
2026-05-27 confirmed the real shapes of Linked-Applications +
Consumer-Queue fields.

### Answers + decisions

| Q | Answer | Decision impact |
| --- | --- | --- |
| 5.1 EP = single source of truth? | EP is the leading **Governance Plane for EDA models**, BUT OM enriches AND business apps may pre-exist in OM (SAP etc.). OM changes must reflect back to EP. | Per-field ownership (see scope table below) — neither side wins everything |
| 5.2 What OM owns | Extended description, classification, tags-as-CAs, plus: OM-pre-existing apps must be attachable to EP-Pipelines via EP's Linked-Apps feature | Sharpens #49 + adds #60 (external-system CA convention) |
| 5.3 Conflict policy | Per-field (Solace recommendation) | See scope table; EP wins structural, OM wins governance |
| 5.4 Delete handling | Soft-delete with `Retired` tag (Solace recommendation) | #61 |
| 5.5 OM-only tag on re-ingest | Preserve + import into EP | #49 scope row "tags CA-mapped" |
| 5.6 Certification push-back to EP | Yes | #49 scope row "Certification" |

### Bi-directional sync — per-field scope table (#49)

| Field | OM->EP | EP->OM | Conflict |
| --- | --- | --- | --- |
| Topic-address / Event-name | NO | yes | EP wins always |
| Schema content | NO | yes | EP wins always |
| Pub/Sub declarations | NO | yes | EP wins always |
| Description (base) | append only | yes | additive |
| Description (extended in OM) | YES (CA `epExtendedDescription`) | as CA | OM wins for extended block |
| Tags (mapped from EP tags) | NO | yes | EP wins |
| Tags (CA-mapped, OM-added) | YES (push as CA value) | as CA | OM wins |
| Classification | YES (push as CA) | as CA | OM wins |
| Certification | YES (CA `epCertification`) | as CA | OM wins |
| Owners (added in OM) | YES (CA `epAdditionalOwners`) | createdBy/changedBy | OM wins for additional |
| External-system linkage | YES (CA `externalSourceOmFqn`/`externalSinkOmFqn`) | as CA | OM wins |

**Default (not in table)**: EP wins for structural, OM wins for
governance metadata, last-writer for free-text.

### ALDI's end-to-end EDA lineage vision — implementation map

```
SAP ERP (Source)                  [OM-Table from SAP connector]
  ▼  edge via CA externalSourceOmFqn on EP-App (#60)
EP-Application-Publisher          [OM Pipeline — shipped]
  ▼  declaredProducedEventVersionIds (shipped)
Topic (Event v1) + Schema         [OM Topic — shipped; first-class Schema #52]
  ▼  consumer.subscriptions.value matches Topic.address; attractedEventVersionIds links them
Consumer-Queue                    [OM Container per EP consumer{} — #55 sharpened]
  ▲  part-of (custom property pointing to consumer-Pipeline)
EP-Application-Consumer           [OM Pipeline — shipped]
  ▼  outboundApplicationVersionAssociations (#59) — within-EP Linked Apps
EP-Application-Target             [OM Pipeline — shipped] (or external system via #60)
  ▼  edge via CA externalSinkOmFqn (#60)
SAP ERP (Target)                  [OM-Table from SAP connector]
```

**What EP gives us today (probed against seall):**

- `applicationVersion.inboundApplicationVersionAssociations[]` +
  `outboundApplicationVersionAssociations[]` — shape:
  `{sourceId, destinationId}` between applicationVersions. Direct
  map to OM Pipeline-Pipeline lineage. *(That IS EP's Linked Apps
  feature — it's just not under `/linkedApplications` REST path.)*
- `applicationVersion.consumers[]` — shape:
  `{id, name, consumerType, brokerType, subscriptions: [{value,
  attractedEventVersionIds}]}`. Direct map to OM Container per
  consumer, with subscription patterns as CP and
  attractedEventVersionIds as lineage source-of-truth (EP
  pre-computes pattern-to-event matching — we don't have to).

**What EP does NOT do natively:**

- External-system pointers (no concept of "this app reads from SAP").
  Convention via Custom Attribute `externalSourceOmFqn` /
  `externalSinkOmFqn` on EP Application. Connector reads CA, resolves
  to OM entity by FQN, emits cross-system lineage edge.

### New tickets created from Cluster 5

| # | Title | Scope |
| --- | --- | --- |
| #49 (sharpened) | OM <-> EP bi-dir sync | Per-field scope table above |
| #55 (sharpened) | Consumer-Queue as OM Container | Real EP `consumers[]` shape now codified |
| #59 (new) | Linked Apps (within-EP) lineage | inbound/outboundApplicationVersionAssociations -> OM Pipeline-Pipeline edges |
| #60 (new) | External-system linkage via EP CA | SAP/Snowflake/Databricks attachment via `externalSource/SinkOmFqn` CA |
| #61 (new) | Soft-delete with Retired tag | Mirrors Kafka/Snowflake connector patterns |

### Security implication for Cluster 6

EP service-account token currently scoped **read-only**. Bi-dir sync
needs **write** scope on `/architecture/<entity>/{id}` (for CA value
PUT). ALDI Platform Team must rotate to a write-scoped token before
#49 production deploy. This is a Cluster-6 risk to track.

---

## Cluster 6 — Security & compliance

**ALDI answers received 2026-05-27**.

| Q | Answer | Decision impact |
| --- | --- | --- |
| 6.1 PII present? | Yes — declarative via tag / CA / topic-segment / schema-field annotation | #62 PII detection + sample-data hard-block |
| 6.2 Sample-data allowed? | Allow-list only (status quo) | shipped |
| 6.3 Sample retention | Recommendation requested — see below | configurable, 14d default |
| 6.4 Audit target | OTel (Solace-philosophy aligned) to all backends via OTel Collector fan-out | #63 OTel pipeline (replaces #12) |
| 6.5 mTLS Connector<->EP | TLS yes, no client certs. EP uses Bearer-Token only | status quo; document in security baseline |
| 6.6 Secrets backend | Plain K8s Secrets for v1.0. Vault for v1.1+ | risk-accept for v1.0 |
| 6.7 EP token rotation | 90d manual (locked Cluster 4.7) + **NEW: write-scope needed for #49** | Cluster-6 risk |
| 6.8 OM bot JWT rotation | 90d manual (locked Cluster 4.8) | Cluster-6 risk |
| 6.9 Network isolation | EP is SaaS, OM is on-prem. Polling-only egress from OM to EP. No EP-side webhook delivery possible. | Bridge polling-mode-only; OM-webhooks consumed locally in on-prem cluster |
| 6.10 Data residency | Europe only | EP tenant region check; OM cluster must be EU |

### 6.3 — Sample-data retention recommendation

Reference connector defaults (verified during research):
- Kafka connector: 7 days
- Snowflake connector: 30 days
- Databricks connector: 30 days

**Recommendation**: 14 days default — middle of the spectrum, fits
EU retail GDPR conservative read. Per-domain override via workflow
config `sampleDataRetentionDays: <int>`. PII-tagged topics: 0 days
(never store, only one-shot ad-hoc view if explicitly allowed).

### 6.9 — Network topology implications

EP is `api.solace.cloud` (SaaS in EU region). OM cluster is on-prem
at ALDI. Egress-only flow:

```
ALDI on-prem cluster
  ├─ openmetadata + airflow (KubernetesExecutor)
  ├─ ingestion-bot pod (custom image with our connector)
  │     polls api.solace.cloud (EP) — egress port 443
  │     writes to local OM via internal K8s service
  ├─ bridge pod (polling mode #25)
  │     polls EP for changes — egress port 443
  │     subscribes to OM webhooks — internal K8s service
  │     [v1.1] writes back to EP for OM-owned fields (#49) — egress port 443
  └─ otel-collector pod (Cluster 6.4 #63)
        egress to ALDI's existing log/trace backends
```

**No inbound from EP**. Confirms our polling-mode architecture (#25
already shipped) is the right pattern. Webhook-Reconciler (#14) stays
parked indefinitely until EP exposes outbound webhooks.

### 6.7 — EP token write-scope requirement (NEW)

Bi-dir sync (#49) requires write-scope token on
`/architecture/<entity>/{id}`. Today's token is read-only. ALDI
Platform Team must:
1. Generate a separate write-scoped token in Solace Cloud Console
2. Store separately in K8s Secret `ep-token-writer` (split from
   `ep-token-reader` used by the connector)
3. Bridge uses the writer token; connector + reconcile use the reader
4. Rotate both on 90d manual cadence (Cluster 4.7)
5. **v1.1 risk-mitigation**: Vault-backed dual rotation (#67)

### 6.4 — OTel architecture (#63)

Single OTLP/HTTP exporter from connector + bridge. OTel Collector
deployed alongside (Helm chart includes optional sidecar) fans out
to ALDI's choice of Splunk/DataDog/Loki/Prometheus.

Spans + structured logs enriched with attributes:

| Attribute | Example |
| --- | --- |
| `om.entity.type` | "Topic" |
| `om.entity.fqn` | "solace-ep-prod.AcmeMDM.customerCreated_v1" |
| `ep.entity.id` | "rgty3g9laaa" |
| `ep.entity.type` | "applicationVersion" |
| `actor` | "ingestion-bot" / "user:alice@aldi" |
| `action` | "read" / "write" / "delete" / "blocked-pii" |
| `outcome` | "success" / "4xx" / "5xx" / "skipped" |

Replaces narrower #12. Cross-cuts #11 (structured-log trace_id).

---

## Closed / parked decisions

| ID | Decision | Reason |
| --- | --- | --- |
| #42 | Modeled Event Mesh mapping parked | 404 on seall Cloud Enterprise; ALDI likely confused with EAPP |
| audit-replay | Not implemented | Cloud Enterprise does not expose `/architecture/auditEvents` |
| webhook-subscriptions | Not implemented | Cloud Enterprise does not expose webhook CRUD; bridge stays in polling mode |
