# Discovery-Closure-Summary — Solace EP -> OpenMetadata Connector

**Customer**: ALDI Nord (Platform Team + IT-Sec)
**Discovery period**: 2026-05-26 / 2026-05-27 (sprint)
**Method**: 6-cluster structured discovery, each cluster smoke-tested
against ALDI's reference tenant `seall` (Cloud
Enterprise) before answers were locked in `asset-mapping-spec.md`.
**Outcome**: All 6 clusters answered + 2 additional ALDI requirements
captured + 25 implementation tickets (#41-65) ready for prioritisation.

This document is the **signed-off architecture envelope** that the
v1.0 production-ready connector will implement.

---

## Executive summary

Three findings shape the entire delivery plan:

1. **EP Cloud Enterprise has zero IAM/team APIs** (10-path smoke test).
   Identity resolution must use a static `userIdToEmailMap` curated
   by ALDI Platform Team; OM-Teams from EP is impossible in v1.0.

2. **EP Linked-Apps + Consumer-Queue ARE in the REST payload** but on
   the `applicationVersion` resource (not under `/linkedApplications`).
   This unblocks ALDI's full E2E lineage vision
   (SAP -> EP-Pipeline -> Topic -> Queue -> EP-Pipeline -> SAP) without
   any EP-side write-back for the core lineage.

3. **OM jump 1.6.5 -> 1.11 is structurally invasive** but mechanical
   (Python 3.10+, Airflow 3.x, `domain` -> `domains` rename across 7
   sites, Pydantic-v2-only). Must be the first wave of work — every
   other ticket assumes the new SDK.

Plus two ALDI-volunteered scope expansions that elevate the
deliverable from "nice EP connector" to "Databricks-grade enterprise
connector":

- **Schema-field parsing** with column-level granularity (#64)
- **Dynamic System-vs-Pipeline classification** of EP Apps with
  auto-link to OM-pre-existing entities (#65)

---

## Cluster-by-cluster decisions (signed)

See `docs/asset-mapping-spec.md` for full per-cluster rationale. This
table is the at-a-glance signoff record.

### Cluster 1 — EP edition + API capabilities

| Item | Decision | Ticket |
| --- | --- | --- |
| EP edition | Cloud Enterprise, 2 tenants in 1 region | #41 |
| Modeled Event Mesh | Not applicable (seall 404) | #42 closed wontfix |
| Audit feed | Not exposed -> watermark reconcile | (shipped #23) |
| Webhooks | Not exposed -> polling-only bridge | (shipped #25) |
| Custom Attributes | Auto-discover + map to OM Tags | #43 |
| Event API | OM Container per EventApi+Version + lineage to Topics | #44 |
| Event API Product | OM DataProduct per EAPP+Version | #45 |

### Cluster 2 — OM edition + feature-set

| Item | Decision | Ticket |
| --- | --- | --- |
| SDK target | OM 1.11.x (latest 1.11.14), upper bound `<1.13` until 1.13 GA | #47 |
| Domain hierarchy | Explicit `omDomainParentMap` in workflow config | #48 |
| Glossary | Not in scope | n/a |
| Bi-directional sync | OM->EP for governance fields only (per-field table) | #49 |
| Cross-system lineage | YAML edges v1.0; auto-discover v1.1 (Databricks-style) | #50 |
| OM operator | ALDI Platform Team | n/a |

### Cluster 3 — Asset-mapping completeness

| Item | Decision | Ticket |
| --- | --- | --- |
| First-class Schemas | Promoted + still embedded | #52 |
| Topic-address tree | Folder-by-segment, depth-cap 3 (configurable) | #53 |
| Versions | All-versions default ON | #54 |
| Consumer-Queue | Container per EP `consumers[]` entry | #55 |
| AsyncAPI export | `Pipeline.sourceUrl` to EP endpoint | #56 |
| EP Categories | Not in use at ALDI | n/a |
| Description aggregation | Event > EventVersion > Schema with markdown dividers | (extend shipped mapper) |

### Cluster 4 — Identity / Ownership / Teams

| Item | Decision | Ticket |
| --- | --- | --- |
| EP user-lookup API | NOT EXPOSED (proved via 10-path probe) | n/a |
| `userIdToEmailMap` | Required, manual curation by ALDI | #57 |
| EP teams | BLOCKED (no team API) | #58 parked |
| Multi-owner | Yes (OM 1.11 native `owners` list) | (folded into #57) |
| Token rotation | 90d manual; Vault automation in v1.1 | #67 |

### Cluster 5 — Bi-directionality + source-of-truth

| Item | Decision | Ticket |
| --- | --- | --- |
| EP-leading model | Yes for EDA; OM enriches; bi-dir for governance | #49 sharpened |
| Linked-Apps (EP App<->EP App) | OM Pipeline<->Pipeline lineage edge | #59 |
| External-system linkage | EP CA `externalSource/SinkOmFqn` v1.0 + auto-naming-classification v1.1 | #60, #65 |
| Delete handling | Soft-delete with `Retired` tag | #61 |
| Tag preservation | OM-only tags preserved AND pushed to EP as CA values | #49 |
| Certification push-back | Yes (write to EP CA) | #49 |

### Cluster 6 — Security + compliance

| Item | Decision | Ticket |
| --- | --- | --- |
| PII | Declarative via tag/CA/topic-segment/schema-field; sample-data hard-block | #62 |
| Sample-data | Allow-list only (shipped); 14d default retention | (config tweak) |
| Audit + telemetry | OTel via Collector fan-out | #63 |
| TLS | Required; certificate-auth not in scope | (shipped) |
| Secrets | Plain K8s for v1.0; Vault for v1.1+ | #67 |
| Network topology | SaaS egress only; polling-only bridge | (shipped) |
| Data residency | EU only | infra requirement |

### Additional ALDI requirements (post-cluster-discovery)

| Item | Decision | Ticket |
| --- | --- | --- |
| Schema-field parsing | Recursive Avro/JSON/Protobuf -> `SchemaField[]` with nesting | #64 |
| App-classification (System vs Pipeline) | Naming-regex + Linked-Apps graph + auto-link OM search | #65 |

---

## Open risks + mitigations

| Risk | Severity | Mitigation |
| --- | --- | --- |
| 90d manual token rotation → silent breakage | HIGH | Prometheus alert on EP-401 / OM-401 (#10); Vault automation v1.1 (#67) |
| EP-token write-scope leak (Bi-dir #49) | HIGH | Split read/write tokens; reduce write-scope to specific CA paths; Vault rotation |
| OM 1.11 SDK migration breaks pilot (#47) | MEDIUM | Test against `openmetadata/server:1.11.x` before shipping; staged release |
| Static `userIdToEmailMap` drift | MEDIUM | Quarterly extract script (synthesise from ALDI Keycloak); WARN log on lookup miss |
| Linked-App auto-classification false positives (#65) | MEDIUM | Default OFF; dry-run mode; require explicit allow-list |
| OM Container-for-Topic-Tree misuse (#53) | LOW | Accept; revisit if/when OM ships native MessagingHierarchy |
| OM 1.13 not yet released | LOW | Pin `<1.13`; bump after GA + probe |
| EP API field deprecations between Cloud releases | LOW | Defensive dict-access (already convention); CI smoke-test against live tenant |

---

## Roadmap (waves)

Detailed wave breakdown in `docs/implementation-plan.md`. Summary:

| Wave | Theme | Tickets | Weeks | Image |
| --- | --- | --- | --- | --- |
| 0 | SDK foundation | #47, #51, #66 scaffold | 1 | 0.4.0 |
| 1 | Core mapping + schema-fields | #43, #54, #64 | 1 | 0.5.0 |
| 2 | Lineage + cross-system | #50, #59, #60, #65, #66 | 2 | 0.6.0 |
| 3 | New entity types | #44, #45, #52, #53, #55 | 1 | 0.7.0 |
| 4 | Identity + bi-dir | #48, #49, #56, #57, #58, #61 | 1 | 0.8.0 |
| 5 | Production hardening | #10, #11, #13, #15, #16, #41, #62, #63, #67 | 2 | 0.9.0 |
| 6 | GA + ALDI cutover | — | 1 | 1.0.0 |
| 7 | OM upstream contribution | — | post-GA (Q3) | upstream |

### Strategic deltas vs Kafka connector (where we exceed upstream)

Identified via Kafka-deep-dive research (#67):

1. Native Application / Producer / Consumer modelling (Kafka relies on KafkaConnect)
2. Native Domain support (Topic.domains; Kafka never sets it)
3. Lifecycle state -> OM Tags (Kafka emits zero tags)
4. Version semantics (Kafka flattens to latest silently)
5. Logical-type fidelity in dataTypeDisplay (Kafka drops them)
6. First-class Schema entity (Kafka embeds only)
7. $ref graph resolution (Kafka string-concatenates)

These become the leading bullets of the upstream PR description.

### Architecture decisions from Databricks-connector research

- **Split into separate Source-classes via ServiceSpec** (#66):
  MetadataSource + LineageSource as today's monolith won't scale to
  the lineage + bi-dir complexity. Mirrors Databricks's
  `DefaultDatabaseSpec(metadata_source_class=..., lineage_source_class=...)`.

- **Cross-system lineage via `crossSystemServiceFqns` config + ES-FQN search**
  (mirror Databricks `crossDatabaseServiceNames`). Not regex; metadata-driven.

- **Multi-step test-connection** with per-step green/red UI feedback
  (already partial in #8; align naming taxonomy with Databricks).

- **Standardised `Either(left=StackTraceError(name=...))` taxonomy** —
  group failures in OM run report by name=`Topic`/`Schema`/`Lineage`/`Tag`.

---

## Decision log

DECIDED (binding for v1.0):

- All cluster items in tables above
- OM SDK target = 1.11.x; upper bound `<1.13` (revisit at 1.13 GA)
- Python 3.10+ minimum (driven by OM 1.11)
- Polling-only bridge (no EP webhook subscription)
- Static `userIdToEmailMap` manually curated
- Plain K8s Secrets for v1.0 (Vault v1.1)
- Soft-delete with Retired tag (no auto-hard-delete)

PARKED (revisit):

- #42 Modeled Event Mesh (reopen if ALDI confirms MEM in their UI)
- #58 EP Teams mapping (until EP exposes team API OR ALDI commits to external source-of-truth)
- Webhook-Reconciler #14 (until EP exposes outbound webhooks)
- AsyncAPI v1.1 fetch-and-store (vs v1.0 sourceUrl-link)

DEFERRED to v1.1+:

- Vault-backed secret rotation (#67)
- Cross-system lineage auto-discovery (vs YAML edges in v1.0)
- AsyncAPI fetch-store on shared volume
- OM upstream contribution (after v1.0 stable in ALDI prod)

---

## Next steps (Solace internal)

1. **Today**: Final implementation plan + ALDI sign-off on this document
2. **Week 1**: Execute Wave 0 (#47 SDK migration)
3. **Week 2-3**: Wave 1 (Cluster-1 mappings)
4. **Week 4-6**: Waves 2-4 (asset completeness + lineage + identity)
5. **Week 7-8**: Wave 5 (production hardening)
6. **Week 9-10**: v1.0.0-rc1 -> staging at ALDI
7. **Week 11-12**: v1.0.0 GA -> ALDI production cutover
8. **Q3 2026**: v1.1 (Vault, auto-lineage); start OM upstream PR

---

*Last updated:* 2026-05-27
*Authors:* Solace
*Sign-off pending:* ALDI Platform Team + IT-Sec
