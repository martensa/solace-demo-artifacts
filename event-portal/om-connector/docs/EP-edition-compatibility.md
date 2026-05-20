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
| AsyncAPI export                  | `applicationVersions/{id}/asyncApi`        | ✅       | JSON + 2.5.0 working |
| Modeled Event Mesh → DataProduct | `/architecture/modeledEventMeshes`         | ❌ 404   | Endpoint missing in this edition. Connector tolerates with empty list; `emitDataProducts` is OFF by default. |
| Audit-based reconcile            | `/architecture/auditEvents`                | ❌ 404   | The `/architecture/audits` endpoint exists but is broker/mesh-scoped (requires `eventBrokerId`). Reconcile rebuilt as full-pull since watermark. |
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
