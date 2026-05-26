# ALDI Nord — om-connector Production-Discovery

Use this for a focused **90-minute architecture-clarification meeting**
with the ALDI Nord platform / data governance team. Six must-know
clusters. Per cluster: short rationale, the questions, fields to write
the answers into, the default we would ship if no answer comes, and
what the answer concretely changes on Solace's side.

> Anything else (operations / observability / SLOs / multi-environment
> / cross-system lineage / distribution & licensing) is on the
> follow-up list and can be parked for a Block-2 / Block-3 meeting.

---

## Meeting context

| | |
| --- | --- |
| Date | __________________ |
| Solace attendees | __________________ |
| ALDI Nord attendees | __________________ |
| Goal | Lock the data model + identity + security envelope for v1.0 of the Solace EP → OpenMetadata connector. |
| Out of scope today | Rollout plan, operations runbook, lineage to non-Solace systems, distribution model. |
| Pre-read for ALDI | One-page demo recap (see `docs/workshop-demo-script.md`) |

---

## Cluster 1 — EP edition & API capabilities

**Why this matters first**: every other answer depends on what your
EP edition exposes. Cloud v2 (our pilot tenant) does not ship
Modeled-Mesh, Audit-Feed or Webhook-Subscription endpoints; an
on-prem / Insights edition might.

### Questions

| Q | Answer | Source |
| --- | --- | --- |
| 1.1 EP edition & release | _Cloud Enterprise / Insights / Self-Managed_, version _____ | ALDI |
| 1.2 Region(s) / number of EP tenants | _____ tenants in _____ regions | ALDI |
| 1.3 `/architecture/modeledEventMeshes` available? | [ ] yes [ ] no [ ] unknown — test together | Solace verifies |
| 1.4 `/architecture/auditEvents` (architecture-level) available? | [ ] yes [ ] no [ ] unknown | Solace verifies |
| 1.5 Webhook-Subscription CRUD available? | [ ] yes [ ] no [ ] unknown | Solace verifies |
| 1.6 Are EP **Custom Attributes** used? On which entity types? | Domain ___ Event ___ App ___ Schema ___ | ALDI |
| 1.7 Do you use **Event API** + **Event API Product** concepts? | [ ] yes [ ] no [ ] planned | ALDI |
| 1.8 Webhook *signing* — HMAC header name? | _____________ (e.g. `Solace-Signature`) | Solace verifies |

### What this changes on the Solace side

- 1.3 yes → re-enable `emitDataProducts=true` and ship a Modeled-Mesh → OM-DataProduct mapping.
- 1.4 yes → drop the watermark-based reconcile fallback, switch to audit-replay (faster, deletes-aware).
- 1.5 yes → enable `BRIDGE_MODE=http` for sub-second latency, ship a one-shot `--register-webhook` per environment.
- 1.7 yes → add `Container` (Event-API) + `DataProduct` (Event-API-Product) mappings, cross-link to underlying events.

### Default if no answer

Cloud v2 endpoints only, audit-replay disabled, `BRIDGE_MODE=polling`,
no Event-API mapping.

---

## Cluster 2 — OM edition, version & feature-set

**Why**: OM 1.6 ships Data Products, OM ≥ 1.5 ships Sub-Domains, and
the Glossary feature changes the mapping target for EP tags.

### Questions

| Q | Answer | Source |
| --- | --- | --- |
| 2.1 OM edition (Collate Cloud / Self-Hosted) + version | _____ | ALDI |
| 2.2 Domains feature enabled? Sub-Domains hierarchy used? | [ ] flat [ ] hierarchical [ ] not used | ALDI |
| 2.3 Glossary in use? Term-IDs we should map to? | [ ] yes — terms: _________ [ ] no | ALDI |
| 2.4 Tags / Classifications already in use? Which? | _____________________ | ALDI |
| 2.5 Other OM connectors live (Kafka, Snowflake, dbt, Spark, …) | _____________________ | ALDI |
| 2.6 Who operates OM? Solace-managed / ALDI-platform / vendor? | _____________________ | ALDI |
| 2.7 Latest OM upgrade cadence (we need to keep up with breaking SDK changes) | _____________________ | ALDI |

### What this changes

- 2.2 hierarchical → connector emits sub-domains for nested EP-domain structures (if EP supports it).
- 2.3 yes → EP tags → Glossary-Terms instead of plain Classification-Tags.
- 2.5 cross-connectors → opens the door to **cross-system lineage** (Block 3 topic).
- 2.7 → defines our minimum OM-version compatibility matrix.

### Default

OM 1.6.5 Self-Hosted, flat Domains, no Glossary, only the Solace connector active.

---

## Cluster 3 — Asset-mapping completeness

**Why**: this is the heart of "10/10". The Kafka connector maps Topics
+ Schemas + Lineage. We want to match or exceed that for EP.

### Current mapping (what the pilot delivers today)

| EP entity | OM entity | Today |
| --- | --- | --- |
| Application Domain | OM Domain | ✅ |
| Application Version | OM Pipeline (under synthetic PipelineService) | ✅ |
| Event Version | OM Topic | ✅ |
| Schema Version | embedded as `Topic.messageSchema` | ✅ |
| Pub/Sub declarations | OM Lineage edges Pipeline ↔ Topic | ✅ |
| Lifecycle state | Tag `EventPortal.<State>` + Custom Property | ✅ |
| Topic address | Custom Property `eventPortalTopicAddress` | ✅ |
| Back-links to EP UI | Markdown Custom Properties on Topic + Pipeline | ✅ |

### Gap questions

| Q | Answer | Notes |
| --- | --- | --- |
| 3.1 Should **Schemas** be first-class OM entities (e.g. under a synthetic `DatabaseService` "Solace EP Schema Registry") with their own page, versions and lineage? | [ ] keep embedded [ ] promote to first-class [ ] both | Kafka connector promotes them; matches user expectation |
| 3.2 Should **Modeled Event Meshes** become OM **DataProducts**? (depends on 1.3) | [ ] yes [ ] no [ ] later | |
| 3.3 Should **Event-API Products** become OM DataProducts? (depends on 1.7) | [ ] yes [ ] no [ ] later | |
| 3.4 Topic-address hierarchy (`acme/md/customer/*`) → OM Container folder structure? | [ ] flat [ ] folder-by-segment [ ] folder-by-business-domain | |
| 3.5 Should every **Topic version** be a separate OM entity (history), or only the **latest**? | [ ] latest only [ ] all versions [ ] last N | Today: latest only |
| 3.6 EP **Custom Attributes** → which OM target: Custom Properties, Tags or Glossary? | per attribute decision: __________ | Depends on 1.6 |
| 3.7 EP **Categories** (if any) → OM Tags or Glossary? | [ ] tags [ ] glossary [ ] custom property | |
| 3.8 Should **Consumer Subscriptions** (subscribers per topic) become separate OM lineage edges or just stay in `declaredConsumed…Ids`? | [ ] separate entities [ ] lineage only [ ] none | |
| 3.9 **Description aggregation**: EP has descriptions on Domain, Event, EventVersion, Schema, App, AppVersion. Which is the primary, which is appended? | __________ | Today: Event description + EventVersion description concatenated |
| 3.10 **AsyncAPI export** per Application Version — should we attach it as a downloadable artifact to the Pipeline? | [ ] yes [ ] no | OM supports `sourceUrl` field |

### What this changes

- 3.1 promote → adds a new `CustomDatabase`-style service `solace-event-portal-schemas`, schema-per-entity with versions, links from Topics.
- 3.4 hierarchy → uses OM's `Container` entity for the topic-address folder tree, queryable + breadcrumb-navigable.
- 3.5 all versions → already supported via `ingestAllVersions=true`; just a config flip.

### Default

Schemas stay embedded, latest version only, flat topic addresses, no AsyncAPI artifact.

---

## Cluster 4 — Identity, ownership & teams

**Why**: today we set `resolveOwners=false` because EP returns
user-IDs (e.g. `udz8x00uz2o`), not e-mails. For ALDI's RBAC and
self-service "who do I bug about this topic", this needs to be solved.

### Questions

| Q | Answer | Source |
| --- | --- | --- |
| 4.1 Are EP users + OM users the same identity (same Keycloak login)? | [ ] yes [ ] mostly [ ] no | ALDI |
| 4.2 Which Keycloak claim joins them? | [ ] email [ ] preferred_username [ ] sub [ ] other: ___ | ALDI |
| 4.3 Does your EP edition expose user lookup (`/iam/users/{id}` or similar)? | [ ] yes — path: _____ [ ] no [ ] unknown | Solace verifies |
| 4.4 Failing 4.3: are you OK with a **static User-ID → E-Mail map** in connector config? | [ ] yes [ ] no, please find another way | ALDI |
| 4.5 Should **multiple Owners** be supported (Domain-Owner + App-Owner + Topic-Owner)? | [ ] yes [ ] just one [ ] only Domain-Owner | ALDI |
| 4.6 EP Team concept — should it map to **OM Teams**? | [ ] yes — list of EP-teams: ___ [ ] no | ALDI |
| 4.7 Connector service-account in EP — who creates / rotates? Rotation cadence? | __________ days, rotated by __________ | ALDI |
| 4.8 OM ingestion-bot JWT — same question. | __________ | ALDI |

### What this changes

- 4.3 yes → connector resolves user-IDs at runtime, no manual map needed, `resolveOwners=true` becomes default.
- 4.4 yes → ship `userIdToEmailMap` connection option (JSON map), document the maintenance path.
- 4.6 yes → emit OM-Team links instead of (or in addition to) user-Owners.

### Default

Manual `userIdToEmailMap` JSON in connection options, Domain-Owner only, no Team mapping. (Brittle; expect this answer to evolve.)

---

## Cluster 5 — Bi-directionality & source of truth

**Why**: governs whether we ever write *into* EP. Wrong answer here
creates silent drift between systems within months.

### Questions

| Q | Answer | Notes |
| --- | --- | --- |
| 5.1 Is **EP the single source of truth** for event metadata? | [ ] yes [ ] no, OM also enriches | One-way vs. bi-directional architecture |
| 5.2 If 5.1 = no: which fields are owned by OM and should write back to EP? | __________ | e.g. extended description, business glossary, certification |
| 5.3 Conflict resolution if both sides change the same field: | [ ] EP wins [ ] OM wins [ ] last-writer [ ] manual flag | |
| 5.4 Delete handling: event removed in EP — what happens to the OM Topic? | [ ] soft-delete [ ] hard-delete [ ] keep with "Retired" tag [ ] manual | Today: keep (no auto-delete) |
| 5.5 Tag handling: tag added in OM (not present in EP) — does next ingest remove it? | [ ] preserve [ ] overwrite from EP [ ] mark as "OM-added" | Today: preserve (additive merge) |
| 5.6 OM **Certification** of a Topic (e.g. "Tier 1 production data") — should we push that back to EP as a custom attribute? | [ ] yes [ ] no [ ] later | |

### What this changes

- 5.1 no → ship a **reverse-write component** in the bridge (POST/PUT to EP architecture endpoints), with conflict policy from 5.3.
- 5.4 hard-delete → connector watches EP audit/list-diff, soft-deletes OM topics that disappeared.
- 5.6 yes → certification webhook in OM → POST to EP custom-attribute endpoint.

### Default

EP is sole source of truth, OM additive only, no auto-deletes, no
write-back. (Safest; expect 5.6 to become "yes" within 12 months as
trust grows.)

---

## Cluster 6 — Security & compliance

**Why**: ALDI is EU retail. GDPR + audit + secrets are blockers, not
nice-to-haves. Today we have placeholders only.

### Questions

| Q | Answer | Notes |
| --- | --- | --- |
| 6.1 GDPR classification of EP entities — does any topic name / sample payload contain personal data? | __________ | If yes: needs separate review per domain |
| 6.2 Sample-data (live broker messages) — allowed at all? Per-domain decision? | [ ] never [ ] allow-list-only [ ] free-for-all | Today: disabled |
| 6.3 Sample-data retention in OM | __________ days | If enabled at all |
| 6.4 Audit-log target for OM actions (who saw/changed what) | [ ] Splunk [ ] DataDog [ ] Loki [ ] not required | |
| 6.5 mTLS required between Connector ↔ EP? | [ ] yes [ ] no [ ] only between Bridge ↔ OM | |
| 6.6 Secrets-backend | [ ] HashiCorp Vault [ ] AWS-SSM [ ] sealed-K8s-Secrets [ ] plain K8s-Secrets | Today: plain K8s-Secrets |
| 6.7 EP API-Token rotation cadence + automation | every ___ days, automated via ___ | |
| 6.8 OM ingestion-bot JWT rotation cadence + automation | every ___ days, automated via ___ | |
| 6.9 Network isolation — is the OM cluster in the same VPC as EP or external? | __________ | |
| 6.10 Data residency — where can OM-stored EP metadata physically live? | __________ region/country | |

### What this changes

- 6.1 PII present → introduces a `pii: true/false` Custom Property on Topic, blocks sample-data per default for those topics.
- 6.4 SIEM target set → ships an OM audit-exporter sidecar with the right format.
- 6.6 Vault → connector reads tokens via `secret:vault://path/to/key` notation, no plain-text in OM service config.
- 6.10 specific region → constrains where the OM cluster + ingestion containers may run.

### Default

No PII expectation, sample-data globally disabled, plain K8s-Secrets,
no audit-export. (Block 1 for a Production-Pilot, but **not
acceptable for a v1.0 GA release**.)

---

## Decision log (fill during the meeting)

| ID | Topic | Decision | Owner | Due |
| --- | --- | --- | --- | --- |
| D-01 | | | | |
| D-02 | | | | |
| D-03 | | | | |
| D-04 | | | | |
| D-05 | | | | |
| D-06 | | | | |
| D-07 | | | | |
| D-08 | | | | |
| D-09 | | | | |
| D-10 | | | | |

---

## Open follow-ups (Block 2 / Block 3 — schedule separately)

| Topic | Block | Trigger |
| --- | --- | --- |
| Operations & observability (Prometheus, OTel, SLOs, DR) | 2 | when Block-1 architecture is signed off |
| Cross-system lineage (Solace ↔ Kafka ↔ Snowflake ↔ Databricks ↔ BI) | 3 | when other OM connectors are inventoried |
| Distribution / licensing / upstream-PR to OpenMetadata | 3 | when v1.0 scope is locked |
| Multi-environment (Dev / Stage / Prod) + CI/CD pipeline | 2 | parallel to operations cluster |
| Self-service onboarding UI for domain owners | 3 | when role boundaries from Cluster 4 are clear |

---

## What Solace commits to do after the meeting

Within **2 weeks** of receiving Block-1 answers:

- Updated **mapping spec** (Cluster 3) committed as `docs/asset-mapping-spec.md`.
- **Identity-resolution prototype** (Cluster 4) merged + tested against ALDI Keycloak.
- **Security baseline** (Cluster 6) implemented: Vault-backed secrets, audit-export sidecar stub.
- **EP-edition feature matrix** (Cluster 1) ratified with `scripts/smoke_ep_api.py` output as evidence.
- Bumped version to **v1.0.0-rc1**, deployed to ALDI's staging OM.

Within **6 weeks**:

- v1.0.0 GA release in `registry.solace.lab` + ghcr.io.
- ALDI pilot domain in production OM, Plattform-Team sign-off.
- Public design-doc for upstream-contribution discussion (if Block 3 says "yes").

---

*Last updated:* generated _________________  
*Document owner:* Solace, mailto:[your-email@solace.com]
