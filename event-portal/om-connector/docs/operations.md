# Operations Runbook

Production operations for the Solace Event Portal to OpenMetadata
connector + bridge (Wave 6 / GA). Covers deploy, configuration,
observability, the routine cron jobs, the write-back shadow-deploy
procedure, token rotation, and troubleshooting.

Audience: the ALDI Platform Team running the connector against
Self-Hosted OpenMetadata 1.11 + Solace Cloud Event Portal v2 (EU).

## Components

- **Pull connector** -- a custom OpenMetadata Source baked into the
  ingestion image. Runs on the OM ingestion schedule (Airflow), emits
  entities + lineage, and is the daily reconciliation pass.
- **Bridge** -- the standalone long-running service
  (`registry.solace.lab/om-eventportal-bridge`). Runs in `polling`
  mode against EP, plus the `--soft-delete-missing` / `--reconcile`
  cron jobs and the opt-in `writeback` receiver.

Network: EP is SaaS (`api.solace.cloud`, egress 443); OM is on-prem.
No inbound from EP. OM EntityChangeEvents (write-back) are consumed
locally inside the cluster.

## Prerequisites

1. **OM ingestion-bot JWT** with metadata write permission.
2. **EP reader token** (`ep-token-reader`) -- read scope on the
   target application domains.
3. **EP writer token** (`ep-token-writer`) -- ONLY for write-back
   (#49); separate from the reader, write scope on
   `/architecture/<entity>/{id}`. Not needed unless write-back goes
   live.
4. **One-time OM bootstrap** (idempotent; re-run after every upgrade):

   ```bash
   om-eventportal-bootstrap \
     --host-port "$OM_HOST_PORT" --jwt-token "$OM_JWT" \
     --ep-token "$EP_READER_TOKEN"        # enables CA auto-discovery
   # multi-tenant: run once per tenant with its prefix
   om-eventportal-bootstrap --host-port "$OM_HOST_PORT" \
     --jwt-token "$OM_JWT" --tenant-prefix tenant-b
   ```

## Deploy

### Ingestion image

```bash
bash scripts/build-and-push.sh        # tag from pyproject.toml
```

Point the OM Airflow deployment at the tag via
`openmetadata-deployment/local-k8s-deps-values.yaml`
(`airflow.images.airflow.tag` + `pod_template.tag`).

### Bridge (Helm)

```bash
bash scripts/build-bridge-image.sh
helm install ep-bridge charts/solace-eventportal-bridge \
  --set secret.epApiToken="$EP_READER_TOKEN" \
  --set secret.omJwtToken="$OM_JWT" \
  --set observability.metrics.enabled=true \
  --set observability.logFormat=json \
  --set cron.softDelete.enabled=true \
  --set cron.reconcile.enabled=true
```

For an on-prem OM behind the lab CA, also set `labCaTrust.enabled=true`.
For two tenants, run two releases with distinct
`openMetadata.serviceName` and `openMetadata.tenantPrefix`.

## Configuration reference

Bridge settings are env-var driven (see `bridge/config.py`). Groups:

- `EP_*` -- Event Portal: `EP_API_URL`, `EP_API_TOKEN` (reader),
  `EP_WRITER_TOKEN` (write-back), `EP_WEBHOOK_SECRET`.
- `OM_*` -- OpenMetadata: `OM_HOST_PORT`, `OM_JWT_TOKEN`,
  `OM_SERVICE_NAME`, `OM_TENANT_PREFIX`.
- `BRIDGE_*` -- transport: `BRIDGE_MODE`,
  `BRIDGE_POLLING_INTERVAL_SECONDS`, dedupe, allow-list, solace.
- `BRIDGE_OBS_*` -- observability: `LOG_FORMAT` (`text`|`json`),
  `LOG_LEVEL`, `SHUTDOWN_GRACE_SECONDS`, `METRICS_ENABLED`,
  `METRICS_PORT`, `OTEL_ENABLED`, `OTEL_ENDPOINT`, `OTEL_PROTOCOL`,
  `OTEL_SERVICE_NAME`.
- `BRIDGE_WB_*` -- write-back: `ENABLED`, `DRY_RUN`,
  `OM_WEBHOOK_SECRET`, `OM_WEBHOOK_HEADER`, `QUEUE_MAX`.

Connector workflow options live in the ingestion YAML
(`config/example-workflow.yaml`); the full table is in `README.md`.

## Observability

### Metrics (Prometheus)

Enable with `BRIDGE_OBS_METRICS_ENABLED=true`; the bridge exposes
`/metrics` (polling/solace via a standalone server on
`metrics_port`, http/forwarder/writeback via the FastAPI mount).

Key series + suggested alerts:

- `eventportal_ep_auth_failures_total` -- EP 401s. Alert `> 0` over
  5m (token expired/rotated wrong).
- `eventportal_bridge_poll_ticks_total{outcome="error"}` -- failing
  poll ticks. Alert on a rising rate.
- `eventportal_bridge_dispatch_seconds` -- handler latency histogram.
- `eventportal_bridge_events_seen_total` /
  `_events_dispatched_total` -- throughput.
- `eventportal_bridge_writeback_queue_depth` -- write-back backlog.
  Alert if sustained `> 0` (worker stalled).
- `eventportal_bridge_writeback_ops_total{outcome="error"}` --
  write-back failures.

### Logs + traces

Set `BRIDGE_OBS_LOG_FORMAT=json` for structured logs with a
`correlation_id` per poll tick / event (and `trace_id` when tracing
is on). Set `BRIDGE_OBS_OTEL_ENABLED=true` +
`BRIDGE_OBS_OTEL_ENDPOINT` (or enable the chart's `otelCollector`
sidecar) for OTLP spans. Data residency: keep the OTLP endpoint
in-region (never an external SaaS).

## Routine operations

- **Ingestion** -- the OM workflow runs on its Airflow schedule
  (metadata pass, then the lineage pass).
- **Reconcile** (`--reconcile`) -- catch-up re-pull since the
  watermark; the chart's `cron.reconcile` runs it (default every
  15m).
- **Soft-delete drift** (`--soft-delete-missing`) -- tags
  OM entities missing on EP as `EventPortal.Retired`; the chart's
  `cron.softDelete` runs it (default hourly). Add
  `--auto-purge-after-days N` (`cron.softDelete.autoPurgeAfterDays`)
  to hard-delete aged tombstones; default keeps them forever.

## Write-back go-live (#49, shadow deploy)

Write-back is OFF + dry-run by default. To take it live SAFELY:

1. Provision the separate `ep-token-writer` (write scope).
2. Deploy `BRIDGE_MODE=writeback` with `BRIDGE_WB_ENABLED=true` and
   `BRIDGE_WB_DRY_RUN=true`. Register the OM Alert -> webhook
   destination (`/webhook/openmetadata`) with the shared
   `BRIDGE_WB_OM_WEBHOOK_SECRET`.
3. Watch the dry-run logs (`[writeback dry-run] would set ...`) and
   `eventportal_bridge_writeback_ops_total{outcome="dry_run"}` for
   at least 7 days. Confirm the planned EP custom-attribute writes
   match expectations and that the EP write wire-contract in
   `EventPortalWriter` is correct against the live tenant.
4. Only then set `BRIDGE_WB_DRY_RUN=false` (and ensure
   `EP_WRITER_TOKEN` is set -- the bridge refuses to start live
   without it).

Per-field policy (Cluster 5): `description` -> `epExtendedDescription`,
certification -> `epCertification`, owners -> `epAdditionalOwners`,
external linkage -> `externalSourceOmFqn` / `externalSinkOmFqn`. EP
wins for structural fields; OM wins for governance.

## PII handling (#62)

Configure at least one signal to activate detection: `piiCaName`,
`piiTagNames`, or `piiTopicSegmentPattern`. A flagged Topic/Pipeline
gets the `EventPortalCompliance.PII` tag + `eventPortalContainsPii`
property, and live sample-data is HARD-BLOCKED for it. Detection is
read-only and off until configured.

## Token rotation (90d manual)

Rotate the OM bot JWT, the EP reader token, and (if write-back is
live) the EP writer token on the agreed 90d cadence. Update the K8s
Secret (or the Vault-synced `existingSecret` in v1.1) and restart the
bridge. A wrong/expired token surfaces as
`eventportal_ep_auth_failures_total` rising.

## Troubleshooting

- **EP 401s** -- token expired or wrong scope. Reader token for
  metadata/reconcile/soft-delete; writer token only for live
  write-back. Check `eventportal_ep_auth_failures_total`.
- **Entities wrongly Retired** -- a per-tenant bridge MUST set
  `OM_TENANT_PREFIX` matching the connector's `tenantPrefix`, or it
  diffs the wrong PipelineService. Verify the prefix on both sides.
- **Pod crashloop in polling mode** -- ensure probes are not pointed
  at a non-existent HTTP port; the Helm chart gates them by mode.
- **Write-back not writing** -- expected when `BRIDGE_WB_ENABLED` is
  false or `BRIDGE_WB_DRY_RUN` is true, or the entity is EP-owned
  (structural) only. Live writes also require `EP_WRITER_TOKEN`.

## GA cutover sequence

1. Build + push the `0.9.0` ingestion + bridge images; flip
   `local-k8s-deps-values.yaml` to `0.9.0`.
2. Deploy to ALDI staging (2 tenants, 1 region). Soak 1 week;
   compare OM entity + lineage counts vs expected; resolve drift.
3. Bump `pyproject.toml` to `1.0.0`, rebuild + push the `1.0.0`
   images, tag the release.
4. Production cutover; decommission the pilot CustomMessaging setup.
5. Roll back by pinning the previous image tag in
   `local-k8s-deps-values.yaml` + the Helm `image.tag`; entities are
   additive/idempotent, so a re-ingest on the prior version is safe.
