# Migration from 0.x

How to move a site from the early pilot (`0.3.x`, CustomMessaging on
OM 1.6-1.7) up to the GA line (`0.9.0` -> `1.0.0`). The connector is
additive + idempotent, so most of the migration is "re-bootstrap, flip
the image, re-ingest" -- but a few defaults changed in ways that change
what appears in OpenMetadata.

## Version map

- `0.3.x` -- pilot baseline (CustomMessaging, OM 1.6-1.7).
- `0.4.x` (Wave 0) -- OM 1.11 SDK migration; Python 3.10+; OM 1.9
  `owner`/`domain` renamed to plural `owners`/`domains`.
- `0.5.x` (Wave 1) -- parsed SchemaFields; EP Custom Attributes as
  Tags (auto-discovered); `ingestAllVersions` default ON.
- `0.6.x` (Wave 2) -- ServiceSpec split (metadata + lineage sources);
  cross-system lineage.
- `0.7.x` (Wave 3) -- new entity types: Event API Container, EAPP
  DataProduct, first-class Schema Tables, Topic-tree, Consumer-Queue.
- `0.8.x` (Wave 4) -- `userIdToEmailMap` owners; soft-delete drift.
- `0.9.x` (Wave 5) -- multi-tenant, PII, observability, Helm chart;
  plus Wave 4.5 OM->EP write-back (flag-off).
- `1.0.0` (Wave 6) -- GA.

## Behavioral changes to expect

- **More Topic/Pipeline entities.** `ingestAllVersions` is ON by
  default since `0.5.0`: one Topic per event version + one Pipeline
  per application version, each tagged with
  `eventPortalIsLatestVersion=true|false`. Filter the OM UI on
  `eventPortalIsLatestVersion=true` to hide history.
- **Filter patterns are default-deny.** Since `0.5.x` an empty
  `*FilterPattern.includes` ingests NOTHING. Set explicit `includes`
  regex lists for domains/events/schemas/applications.
- **New synthetic services.** From `0.7.0`: `solace-event-portal-apps`
  (Pipelines), `-event-apis`, `-consumers`, `-topic-tree`
  (Containers), `-schemas` (Tables). Created by bootstrap.
- **Plural owners/domains.** Any external automation reading the OM
  API must use `owners` / `domains` (not the pre-1.9 singular).
- **Soft-delete.** From `0.8.0`, entities missing on EP are tagged
  `EventPortal.Retired` (not hard-deleted) by the drift cron.

## Migration steps

1. **Platform prerequisites** -- OM Self-Hosted 1.11; the ingestion
   image is Python 3.10+. (Local dev: the connector's mapper / schema
   / lineage tests need the OM SDK and only run inside the image.)
2. **Re-run bootstrap** (idempotent) so the new classifications,
   custom properties, and synthetic services exist:

   ```bash
   om-eventportal-bootstrap --host-port "$OM_HOST_PORT" \
     --jwt-token "$OM_JWT" --ep-token "$EP_READER_TOKEN"
   ```

3. **Set filter patterns** in the workflow YAML (default-deny). Start
   from `config/example-workflow.yaml`.
4. **Flip the ingestion image** tag in
   `openmetadata-deployment/local-k8s-deps-values.yaml`, then run the
   workflow. The first run creates the new entity types + lineage.
5. **Deploy the bridge** via the Helm chart
   (`charts/solace-eventportal-bridge`) for polling + the
   reconcile / soft-delete crons. The bridge is env-var driven; map
   any old `.env` keys to the `EP_*` / `OM_*` / `BRIDGE_*` /
   `BRIDGE_OBS_*` groups (see `docs/operations.md`).
6. **(Optional) opt into the new Wave 5/4.5 features**: multi-tenant
   (`tenantPrefix` + `OM_TENANT_PREFIX`), PII (`piiCaName` /
   `piiTagNames` / `piiTopicSegmentPattern`), observability
   (`BRIDGE_OBS_*`), and OM->EP write-back (`BRIDGE_MODE=writeback`,
   off + dry-run by default -- see the write-back go-live procedure in
   `docs/operations.md`).

## Pilot decommission

Once the new ingestion produces the expected entity + lineage counts,
decommission the old `0.3.x` CustomMessaging pilot service in OM. The
new run reuses the same `solace-event-portal` MessagingService name by
default, so Topics carry over; remove any stale pilot-only services or
duplicated entities created before the synthetic-service layout.

## Rollback

Pin the previous image tag in `local-k8s-deps-values.yaml` (ingestion)
and the Helm `image.tag` (bridge). Entities are additive + idempotent,
so re-ingesting on the prior version is safe; soft-delete tombstones
(tags + `eventPortalDeletedAt`) are inert on older versions.
