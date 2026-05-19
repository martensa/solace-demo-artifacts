# ALDI Workshop — Demo Script

**Duration**: ~30 min (24 min demo + Q&A)
**Goal**: Show that Solace Event Portal metadata flows into OpenMetadata
automatically, with governance and resilience that the customer's
existing stack (Solace + EP + OM) does not have today.

---

## Demo arc at a glance

| Act | Title         | Time | Show-stopper? |
| --- | ------------- | ---- | ------------- |
| 1   | The Why       | 3 min | no            |
| 2   | Pull-Ingest   | 5 min | **YES** — backbone |
| 3   | Live Webhook  | 4 min | **YES** — wow moment |
| 4   | Governance    | 3 min | no            |
| 5   | Resilience    | 4 min | no            |
| 6   | Sample-Data (optional) | 3 min | no |
| —   | Wrap-up + Q&A | 5 min | —             |

If any act after 3 fails live, skip to wrap-up. Acts 1-3 must work.

---

## Pre-demo checklist (run 30 min before the workshop)

```bash
# 1. OpenMetadata reachable
curl -fsSL https://openmetadata.solace.lab/api/v1/system/version | jq .version

# 2. Custom ingestion image is the one OM uses
kubectl -n openmetadata-solace-lab get deploy openmetadata \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
#   -> expected: registry.solace.lab/openmetadata-ingestion-solace:<tag>

# 3. Bootstrap was run (Classification + Tags + CPs + PipelineService)
curl -fsSL -H "Authorization: Bearer $OM_INGESTION_BOT_TOKEN" \
  https://openmetadata.solace.lab/api/v1/classifications/name/EventPortal \
  | jq .name
#   -> expected: "EventPortal"

# 4. Bridge running, healthcheck green
curl -fsSL https://bridge.solace.lab/healthz
#   -> {"status":"ok"}

# 5. Bridge has its EP webhook subscription registered
om-eventportal-bridge --register-webhook https://bridge.solace.lab/webhook/event-portal
#   idempotent — re-run is safe

# 6. EP demo domain `aldi-orders-demo` exists with 3 events + 2 apps
#    (see docs/demo-seed-data.md for the exact content to stage)

# 7. Browser tabs prepared:
#    - OM:  https://openmetadata.solace.lab/services/messagingServices/solace-event-portal
#    - EP:  https://console.solace.cloud/event-portal/designer
#    - Term: kubectl -n openmetadata-solace-lab logs -f deploy/solace-eventportal-bridge

# 8. One ALDI-internal counter-example domain `aldi-internal-test` exists in EP
#    (used in Act 4 to demonstrate the filter dropping it).
```

If any of these eight fails, fix or remove the corresponding act from
the demo before going live.

---

## Act 1 — The Why (3 min)

**Slide / whiteboard**: three islands

```
   [Solace Broker]   [Event Portal]   [OpenMetadata]
       runtime          contracts        catalog
         |                 |                |
         +-----------------+----------------+
                  no shared truth
```

Talking points:

- ALDI today: brokers move events, EP holds the contracts, OM catalogs
  data assets. **Three sources of truth, zero cross-references.**
- A data engineer can't ask OM "who consumes `orders/created`?"
- A platform engineer can't ask EP "is anyone outside our domain using
  this event?"
- The Solace EP ↔ OM Connector closes the loop **without doubling the
  governance effort**. EP stays the contract owner. OM is just a mirror
  with lineage to the rest of the data estate.

Transition: "Let's see it work."

---

## Act 2 — Pull-Ingest (5 min) — backbone

Step-by-step:

1. **Open OM UI**, navigate to
   *Services → Messaging → solace-event-portal*. Show: zero topics yet
   (or a "Last run failed" if you haven't run the workflow on the day).
2. **Show the workflow config** — open the ingestion in OM's UI, point
   at `domainFilterPattern.includes: ["^aldi-orders-demo$"]`.
   > "Allow-list only. We **opt in** which domains land in OM. ALDI's
   > entire EP catalog isn't dumped — only what we explicitly govern."
3. **Click "Run Now"**. Switch to OM Logs view briefly so the audience
   sees it's not pre-recorded.
4. **After ~15-20 s, refresh the service page**:
   - `Domain aldi-orders-demo` created
   - 3 Topics: `OrderCreated_v1.0.0`, `OrderShipped_v1.0.0`,
     `OrderCancelled_v1.0.0` — each with:
     - Topic address: `aldi/orders/{region}/created` etc. (variable!)
     - `EventPortal.Released` tag
     - `messageSchema` populated with nested fields (open one schema —
       show `customer.address.zip` resolves through `$ref`)
5. **Switch to the Pipelines tab**: `order-processor_v1.0.0` and
   `inventory-service_v1.0.0` under the synthetic PipelineService
   `solace-event-portal-apps`.
6. **Click on the Lineage tab** of `OrderCreated_v1.0.0`:
   > "OM didn't guess. EP knows that `order-processor` consumes
   > `OrderCreated` and publishes the next two. The connector turned
   > those declarations into first-class lineage edges."

**Closing line**: "One click, all the metadata from EP, in OM. No
copy-paste."

**Backup plan**: pre-recorded GIF of the same flow in
`docs/recordings/act2-pull.gif`. Pre-stage in a browser tab so you can
swipe to it if the live run hangs.

---

## Act 3 — Live Webhook (4 min) — wow moment

Step-by-step:

1. **Side-by-side layout**: EP UI on the left, OM UI on the right, terminal
   tailing `kubectl logs -f deploy/solace-eventportal-bridge` at the
   bottom.
2. In **EP UI**, open `OrderShipped` event, change the description to:
   `Updated live during ALDI workshop at HH:MM` (use the current time
   so the audience knows it's fresh).
3. Click **Save** in EP.
4. **Look at the terminal**: bridge logs print
   `Webhook id=... type=eventVersion.updated handlers=1`. The audience
   sees the event come in.
5. **Refresh the OM topic page**: description is updated.
   The clock-on-screen shows it took ~2 seconds.

**Closing line**: "No polling, no waiting for the next workflow run.
EP signs the webhook, the bridge verifies the HMAC, dedupes, applies."

**Backup plan**: if the EP webhook isn't reaching the bridge,
fall back to `om-eventportal-bridge --reconcile` and show the same
update arriving through the audit replay path
(takes ~5 s but still the same outcome). Frame it as a feature:
> "Even if the webhook missed delivery, we have a cheap catch-up
> mechanism."

---

## Act 4 — Governance via filter pattern (3 min)

Step-by-step:

1. Switch to the **EP UI** and show that there's another domain in the
   account: `aldi-internal-test`. Point at the events in it (any 1-2
   are fine; just need to look real).
2. **Back to OM**, show the connection options of the workflow:
   ```yaml
   domainFilterPattern:
     includes: ["^aldi-orders-demo$"]
     excludes: [".*-internal.*", ".*-test$"]
   ```
3. **Click "Run Now"** again.
4. After it completes, show that `aldi-internal-test` is **NOT** in OM.
   Open the workflow logs and grep for the filter message:
   `Domain aldi-internal-test ... blocked by domainFilterPattern`.

**Talking points**:
- "Allow-list only is the default. Empty `includes` -> nothing flows.
  Governance teams set what's curated."
- "Same filter shape on events, schemas, applications.
  All four work independently."

**Backup plan**: if EP doesn't have a second domain, walk the audience
through the YAML and explain the policy. No live demo needed.

---

## Act 5 — Resilience: reconcile after outage (4 min)

Step-by-step:

1. **Show the bridge running**: `kubectl get pods | grep bridge`.
2. **Stop it**:
   ```bash
   kubectl -n openmetadata-solace-lab \
     scale deploy solace-eventportal-bridge --replicas=0
   ```
3. **In EP**, change `OrderCreated` description to
   `Modified while bridge was offline at HH:MM`.
4. **Show OM** still has the old description (refresh to prove it).
5. **Restart the bridge**:
   ```bash
   kubectl scale deploy solace-eventportal-bridge --replicas=1
   kubectl wait --for=condition=ready pod -l app=solace-eventportal-bridge
   ```
6. **Run reconciliation**:
   ```bash
   kubectl exec deploy/solace-eventportal-bridge -- \
     om-eventportal-bridge --reconcile
   #   reconcile: audit_events_seen=N dispatched=N watermark_now=...
   ```
7. **Refresh OM**: description is updated, watermark is persisted on
   the MessagingService extension.

**Talking points**:
- "Webhooks are best-effort. The audit replay is the fallback."
- "Watermark is persisted on the MessagingService — survives bridge
  restarts and even bridge re-deploys."
- "In production we'd schedule the full pull workflow as a nightly
  reconciliation on top — defense in depth."

**Backup plan**: if `--reconcile` fails (EP audit endpoint quirks,
empty audit list), trigger a normal workflow re-run instead. Same
outcome from the audience's perspective.

---

## Act 6 — Sample Data (optional, 3 min)

Only show this act if Acts 1-5 stayed inside their time budget.

Step-by-step:

1. In the workflow config, point at `sampleDataEnabled: true` and the
   broker connection (host, vpn, credentials).
2. Trigger a re-run.
3. In OM, open `OrderCreated_v1.0.0`, switch to **Sample Data** tab —
   show 3-5 actual JSON payloads collected live from the broker
   during ingestion.
4. **Talking point**: "These are real messages, sampled with a
   bounded-memory subscriber. Not stored anywhere outside OM —
   ingestion is the only consumer."

**Backup plan**: skip the act if broker subscription fails. Sample-data
is a bonus, not a requirement.

---

## Wrap-up + Q&A (5 min)

**Recap slide**:

```
What we showed:        What it gives ALDI:
  Pull-ingest             one-click metadata sync
  Live webhook            seconds, not nightly
  Filter pattern          opt-in governance
  Reconcile               outage-proof
  (Sample-data)           contracts + reality
```

**Forward-looking** (don't go too deep — the customer set their pace):

- **Operational hardening** (Phase 2): Prometheus metrics, OpenTelemetry
  traces, Redis-backed dedupe for multi-replica HA, native Helm chart.
- **Distribution** (Phase 3): PyPI package, ghcr.io image, GitHub Actions CI.
- **Upstream** (optional): contribute a native `MessagingServiceType.Solace`
  to the OpenMetadata project so this is a first-class connector rather
  than a custom one.

**Q&A talking points** (in case the customer asks):

| Question | Answer |
| --- | --- |
| Can we sync OM tags BACK to EP? | Not yet; reverse-metadata is a v0.4 roadmap item. |
| What about Confluent Schema Registry? | EP already understands JSON Schema / Avro / Protobuf / XSD; the connector parses them all recursively. Confluent SR can be a second source if needed. |
| What about Kafka topics? | OM has a native Kafka connector. This one is for Solace. They coexist as two MessagingServices. |
| How does owner-sync handle SSO? | OM resolves the EP owner e-mail against OM users (Keycloak identity). LRU+TTL cache, negative caching for unknowns. |
| Multi-tenant EP accounts? | One MessagingService per account today. Multi-account is a small extension. |
| Cost on OM side? | One ingestion workflow run per night (~5 min CPU). Bridge: <100m CPU idle. Negligible. |
| Security of the webhook? | HMAC-SHA256 signed payloads, secret rotated via Kubernetes Secret. TLS-only ingress with cert-manager. |
| What if EP changes its API? | Connector is schema-free against EP (returns dicts), so additive changes don't break us. Removed fields surface as warnings in logs, not crashes. |

---

## Post-demo cleanup (5 min, off-screen)

```bash
# Reset description so the demo room is clean for the next session
# (only do this if you re-run the workshop)
om-eventportal-bridge --reconcile

# If you staged demo data on EP just for the workshop, optionally:
# - Delete aldi-orders-demo / aldi-internal-test domains
# - Remove the webhook subscription:
om-eventportal-bridge --register-webhook ""  # not yet implemented; delete via EP UI for now
```

---

## What we still need to build for this demo

This script assumes the following exist by demo time. They don't yet
and we ship them today (see `docs/demo-prep-plan.md`):

1. **Custom ingestion image** `registry.solace.lab/openmetadata-ingestion-solace:0.3.0`
   built and rolled out into the lab OM.
2. **Bootstrap CLI** run against the lab OM (Classification + CPs +
   PipelineService).
3. **Bridge** deployed as a single-replica Deployment with Ingress
   `bridge.solace.lab`.
4. **EP demo content**: `aldi-orders-demo` (3 events + 2 apps + schemas)
   and `aldi-internal-test` (1 event, used in Act 4).
5. **EP webhook subscription** registered to the bridge URL.
6. **Smoke-test results** against the live EP API to catch any
   endpoint-path or payload-shape surprises.
7. **Dry-run** of acts 1-3 end-to-end at least once, ideally with a
   stopwatch.
