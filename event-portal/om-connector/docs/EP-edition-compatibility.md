# Event Portal edition compatibility

Smoke-tested 2026-05-20 against Solace Cloud Event Portal v2
(`https://api.solace.cloud/api/v2`) with an Enterprise org token.

## Endpoint matrix

| Connector feature                | EP endpoint                                | Cloud v2 | Notes |
| -------------------------------- | ------------------------------------------ | -------- | ----- |
| Application Domain ingest        | `/architecture/applicationDomains`         | ✅       | All expected fields present |
| Event ingest                     | `/architecture/events`                     | ✅       | + `numberOfVersions`, `endOfLifeDate`, `stats`, `customAttributes` |
| Event Version ingest             | `/architecture/eventVersions`              | ✅       | `deliveryDescriptor.address.addressLevels` populated as expected |
| Schema + SchemaVersion ingest    | `/architecture/schemas` + `schemaVersions` | ✅       | `content` field carries the schema text |
| Application + App Version ingest | `/architecture/applications` + Versions    | ✅       | `declaredProducedEventVersionIds` / `declaredConsumedEventVersionIds` populated |
| Event API ingest (#44)           | `/architecture/eventApis` + Versions       | ⚠️ assumed | Endpoint confirmed available; the `producedEventVersionIds` / `consumedEventVersionIds` field names are ASSUMED (note: the App path uses the `declared*` prefix). Guarded with `or []` -> no crash, but verify against a live tenant before trusting the Event-API lineage. |
| Event API Product ingest (#45)   | `/architecture/eventApiProducts` + Versions | ⚠️ assumed | Endpoint available; `plans[]` / asset refs assumed; verify field names. |
| AsyncAPI export                  | `applicationVersions/{id}/asyncApi`        | ✅       | JSON + 2.5.0 working |
| Modeled Event Mesh → DataProduct | `/architecture/modeledEventMeshes`         | ❌ 404   | Endpoint missing in this edition. Connector tolerates with empty list; `emitDataProducts` is OFF by default. |
| Audit-based reconcile            | `/architecture/auditEvents`                | ❌ 404   | The `/architecture/audits` endpoint exists but is broker/mesh-scoped (requires `eventBrokerId`). Reconcile rebuilt as full-pull since watermark. |
| Incremental `updatedTime` filter | `?updatedTime=gte:<since>` query param      | ⚠️ assumed | The client sends a server-side `updatedTime=gte:` filter for incremental pulls. Whether EP v2 honours it is UNVERIFIED (and "full pull" elsewhere in this doc implies it may not). If silently ignored it over-fetches (safe) but the watermark semantics assume it works -- verify, else fall back to client-side filtering. |
| Webhook subscription CRUD        | `/architecture/eventPortalWebhooks`        | ❌ 404   | No public webhook API. Bridge runs in `polling` mode instead. `--register-webhook` raises `EventPortalNotSupported` with a clear message. |
| Owner e-mail on `createdBy`      | (none)                                     | ❌       | `createdBy` is a user-id (e.g. `udz8x00uz2o`); no `/users/{id}` lookup found. `resolveOwners` is OFF by default. |

## Implications for the workshop demo

- **Acts 1, 2, 4 (Pull + Filter)**: unaffected. All critical endpoints
  work, schema parsing handles JSON Schema `$ref` and nested objects,
  Pipeline-as-App mapping, lineage edges, lifecycle tags.
- **Act 3 (Realtime)**: runs as **polling-mode bridge** with a
  10-second tick. The same handler set applies; only the trigger is a
  periodic GET instead of an EP-initiated POST. Once Solace ships a
  webhook API we flip `BRIDGE_MODE=http` — no other code change.
- **Act 5 (Reconcile)**: `om-eventportal-bridge --reconcile` does a
  watermark-anchored full pull, NOT an audit replay. Same UX, same
  outcome.

## How to validate against your own EP edition

```bash
EP_API_TOKEN=... python scripts/smoke_ep_api.py
```

Critical pass / optional skip. If the optional ones (`modeledEventMeshes`,
`auditEvents`, `eventPortalWebhooks`) come back **200 with usable
data**, you can flip the corresponding defaults in
`config/aldi-workshop-workflow.yaml` (`emitDataProducts: "true"`) and
`k8s/01-configmap.yaml` (`BRIDGE_MODE: "http"`).

## Beta compatibility status (audit 2026-06-22)

A full static audit of every EP API endpoint + payload field the
connector + bridge use, cross-checked against this matrix and
adversarially verified, concluded:

- **READ / ingestion path: EP v2-ready.** All resource calls use the
  confirmed `/architecture/*` v2 shapes, correct singular/plural query
  params, `meta.pagination.totalPages`, and `data` envelopes. Edition
  gaps (Modeled Event Mesh) are 404-guarded; every lineage lookup is
  `or []` + cache-skip guarded, so an unverified field name degrades to
  "no edge", never a crash.
- **One correctness bug found + fixed**: `_latest()` ranked EP v2's
  NUMERIC `stateId` ("1".."4") against string state names, so
  latest-version selection ignored lifecycle state (a higher-semver
  Draft could beat a Released version) in non-all-versions ingestion
  and in every bridge poll/handler update. Fixed in
  `connector/event_portal_client.py` (numeric stateId ranking) with a
  regression test (`tests/test_ep_client.py`).
- **Verify-before-trust (guarded, non-crashing) for GA**: the Event
  API version field names (`producedEventVersionIds` vs the App path's
  `declared*` prefix) and the server-side `updatedTime=gte:` filter.
  Smoke-test both against the live tenant.
- **Write-back (#49): flag-off, contract unverified.** The EP v2 wire
  shape for writing custom-attribute / governance values back to an
  entity is isolated in `EventPortalWriter` and must be verified under
  shadow deploy before enabling live writes. It ships dry-run + off.

**Beta-readiness: the read/ingestion path is EP v2-compatible (with the
`_latest` fix in); the two field/filter contracts are smoke-test-before-
trust; write-back stays disabled until its wire shape is confirmed.**
