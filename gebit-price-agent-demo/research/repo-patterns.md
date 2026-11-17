# Repo patterns and reusable building blocks for the EuroCIS showcase

Track: reusable building blocks in `solace-demo-artifacts` for the GEBIT
showcase "Preis- und Aktionsagent mit Freigabe". Written 2026-11-10,
read-only research (no repo, cluster, broker, DB or SAM change).

Notation: **[V]** = VERIFIED (source given as `file:line`, command or
URL), **[A]** = ASSUMPTION / inference that needs a Gate-0 check.
Repo root below = `<repo root>` (abbreviated `REPO/`).
`BSG/` = `REPO/bsg-trading-desk-demo/`,
`INS/` = `REPO/sam-insurance-ops-demo/`, `RET/` = `REPO/sam-retail-ops-demo/`,
`MFG/` = `REPO/sam-manufacturing-ops-demo/`, `AMD/` =
`REPO/agent-mesh-deployment/`, `EMD/` = `REPO/event-mesh-deployment/`.

---

## 0. Executive summary

1. The BSG trading desk demo is the template to fork. It is the only demo
   verified on SAM 2.493.0 and it already has exactly the shape the
   showcase needs: a simulated source feed (publisher), a deterministic
   state machine that decides *when* to bother an LLM (watcher), an MCP
   tools server with Pydantic return models feeding `type: tool` nodes,
   an event-mesh entrypoint into a tool + agent + switch workflow, a
   FastAPI + SSE presenter page with a human action button, k8s
   manifests with TLS ingress, idempotent install/uninstall/reset, a
   connector-manifest generator and a Grafana dashboard generator.
   [V] `BSG/README.md` "Measured on the cluster (2026-11-04)".
2. Map: POS simulator = `publisher.py`; "Basket/Article watcher" =
   `watcher.py` + `watch_engine.py`; price/promo MCP tools =
   `tools_server.py`; monitor + tablet = `ui/server.py` +
   `ui/static/index.html`; approval = BSG step 4 / insurance "Approve"
   button publishing an action event.
3. The single most important architectural lesson: BSG chose MQTT
   (paho) on VPN `default` because MQTT 1883 only exists there; as a
   consequence the UI could NOT read SAM's own workflow status events
   (VPN `sam`, no MQTT listener) and showed the agent nodes as
   "inferred". [V] `BSG/README.md` "Open decisions A",
   `BSG/RUNBOOK.md:32-42`. This is avoidable without any broker change:
   the older demos (insurance/retail/mfg) speak SMF over WebSocket to
   VPN `sam` (`ws://localhost:8008`, user `default`), and the Python
   SMF API (`solace-pubsubplus`) can do the same server-side
   (`tcp://host.docker.internal:55557` is reachable from pods, probed
   today). [V] `INS/cockpit/index.html:620-640`, kubectl exec probe
   (section 4.4).
4. New, verified today: SAM 2.493.0 publishes per-node workflow
   progress on `sam-solace-lab/a2a/v1/gateway/status/<entrypoint_id>/<taskId>`
   with data parts `workflow_execution_start`,
   `workflow_node_execution_start` (node_id, node_type, sub_task_id),
   `workflow_node_execution_result` (node_id, status) and
   `workflow_execution_result`; `<entrypoint_id>` equals the
   `entrypoint_id` of the event-mesh entrypoint. [V] WebUI DB
   `task_events` / `tasks` (section 4.4). So the new UI can show real,
   per-node timing on stage - the thing BSG could not.
5. Cost is the binding constraint for "a workflow on every scan": one
   fast-tier (Haiku 4.5) agent node costs ~14.4k input tokens even with
   no tools (SAM system prompt overhead), ~30k with one tool call; a
   4-node BSG run is 60k-92k tokens. [V] WebUI DB `tasks` rows. With
   prompt caching that is roughly USD 0.03 per warm run and ~0.07 cold
   [A, list prices], against a hard 50 USD LiteLLM budget. The pattern
   to copy is BSG's: deterministic tool nodes (< 1.5 s, no model) on
   every event, an LLM only behind a switch when a deterministic rule
   fires, and one closing-event run per basket.
6. Recommended stack: Python 3.12, one image / several commands,
   FastAPI + uvicorn + SSE, `mcp[cli]==2.2.0`, pydantic v2, httpx,
   `solace-pubsubplus` (SMF, VPN `sam`) instead of paho-mqtt, Python
   `protobuf` with GEBIT's binary descriptor sets (verified: all 11
   simple-sale events parse strictly without code generation), `grpcio`
   later for the live Purchase Service bridge, Postgres (existing host
   container) for article master / prices / promotions, SQLite only for
   ephemeral window state, vanilla JS pages, kustomize, images in
   `registry.solace.lab`, multi-arch build for the later GEBIT lab.

---

## 1. Reuse map

Verdicts: **COPY** (copy and rename), **ADAPT** (copy, then change the
domain logic), **PATTERN** (re-implement the idea), **SKIP**.

### 1.1 MCP tools server with Pydantic return models -- ADAPT

`BSG/app/bsgdemo/tools_server.py` (463 lines). What it does:

- One MCP server (streamable HTTP, `/mcp` on :8765) that holds every
  deterministic data access of the agents and the workflow, because
  "SAM v2 (Go edition) has no in-process Python tools". [V]
  `tools_server.py:1-7`.
- SDK shim for mcp 1.x / 2.x (`MCPServer` vs `FastMCP`) and DNS
  rebinding protection switched off (otherwise HTTP 421 for the Host
  header SAM sends). [V] `tools_server.py:44-50,97-103,417-427`;
  rationale in `INS/qdrant/mcp-server/server.py` docstring ("SDK note").
- `json_response=True, stateless_http=True`. [V] `tools_server.py:422-425`.
- Tools return **Pydantic models** (`EnrichResult`, `PublishResult`)
  so the SDK emits `structuredContent` and an `outputSchema`; workflow
  nodes read `{{<node>.output.mcp_structured_content.<field>}}`. [V]
  `tools_server.py:204-237`, `BSG/mesh/workflows/bsg-alert-triage.yaml:35-43,135`.
- Lean responses below 2048 bytes; verbose detail behind a `detail`
  flag only the smoke test sets. [V] `tools_server.py:240-250,319-322`.
- "Robustness contract": every failure returns `{error, hint}`, never a
  stack trace. [V] `tools_server.py:26-27,345-352`.
- Confirms side effects against the real state ("confirm against the
  watcher, not against hope"). [V] `tools_server.py:134-146`.
- Publishes `progress` events on the bus for the UI from inside the
  tool (`_progress`). [V] `tools_server.py:92-94,343,353`.
- `--dump-tools` prints `tools/list` without a server so the connector
  manifest can be regenerated from inside the cluster. [V]
  `tools_server.py:430-463`.
- `/health` custom route used by the readiness probe. [V]
  `tools_server.py:406-414`, `BSG/k8s/bsg-tools.yaml:32-34`.

For the showcase: tools such as `get_article_context(article_id)`
(stock, sales velocity, active promotions, margin floor),
`propose_price_change(...)` (writes a PENDING proposal, never a price),
`publish_proposal(...)`, `apply_approved_price(proposal_id)` (only the
approval path calls it), `issue_voucher(basket_id, ...)`,
`report_progress(...)`. Every tool that a `type: tool` node calls must
return a model and stay under 2 KB.

### 1.2 Feed publisher / simulator -- ADAPT

`BSG/app/bsgdemo/publisher.py` (223 lines) + `catalog.py` (84 lines).

- `FeedSim` is pure and clock-driven, so it is unit-testable; the loop
  in `main()` only publishes what `FeedSim` produces. [V]
  `publisher.py:1-15,170-223`.
- Scenarios arrive on a control topic (`bsg/control/scenario`), the
  active scenario state is re-published every second for the UI
  countdown. [V] `publisher.py:177-190,212-216`.
- Deterministic catalogue (no RNG at import time), deliberately invalid
  demo identifiers (`DE000DEMO0001`). [V] `catalog.py:1-6,46-73`.

For the showcase this becomes the **GEBIT POS simulator**: it emits the
Purchase Service event sequence of the developer message
(PurchaseTransactionCreated, PurchaseTransactionOpened, PositionAdded,
FiscalTransactionAssigned, PaymentProcessStarted,
CashPaymentPositionCreated x2, PaymentProcessCompleted,
...InChargingFinancialTransaction, ...InClosing, PurchaseTransactionClosed)
in proto3 JSON (or binary) with the field names of GEBIT's own samples,
plus background "other tills" traffic. Scenarios: `slow_mover`,
`promotion_hit`, `loyalty_customer`, `cancel`, `reset`. The booth
scanner (barcode on a real article) is just another producer of
`AddArticle`-equivalents.

### 1.3 Deterministic watcher -- ADAPT (the core of the swap design)

`BSG/app/bsgdemo/watcher.py` (458 lines) + `watch_engine.py` (237 lines).

- Keeps a 15-minute window in memory and SQLite on an emptyDir, prunes
  by `RETENTION_MINUTES`. [V] `watcher.py:1-23,63-139`.
- Watches with metric/op/threshold/hold/TTL and **debounce: at most one
  alert per watch** so one condition starts exactly one workflow run.
  [V] `watch_engine.py:1-19`, `BSG/README.md` "Assumptions".
- HTTP read API for the tools server (`/recent`, `/stats`, `/watches`,
  `/alerts`, `/issuer-status`). [V] `watcher.py:13-20,220-290`.
- Holds human-decision state (issuer status changed by the action
  event). [V] `watcher.py:322-341`.
- Statistic that isolates the anomaly (`mean_spread_pct_since_alert`)
  computed deterministically, so the LLM never does arithmetic or date
  maths. [V] `watcher.py:190-224`, `BSG/README.md` "Assumptions".

For the showcase this becomes the **basket/sales watcher**: it consumes
the raw GEBIT events, keeps per-`purchaseTransactionId` basket state
(positions are only final after PurchaseTransactionClosed;
PurchaseTransactionCancelled discards them), keeps sales velocity per
article, and emits lean, already-decided **facts** (e.g.
`pos/insight/slow-mover/{article}`, `pos/basket/closed/{tx}`) that
trigger SAM. This is also the place where "the workflow waits for the
closing event" lives: SAM 2.493.0 has no wait/event node type (node
types: agent, decision, loop, map, switch, tool, workflow; [V]
`sam config schema show workflow`), so the waiting must be
deterministic state outside SAM, and the closing fact starts a second,
separate workflow run.

### 1.4 Bus helper and topic helpers -- ADAPT

- `BSG/app/bsgdemo/mqttio.py` (106 lines): `Bus` = one connection, JSON
  publish, dispatch by filter, one bad message never kills the loop,
  env-driven config. [V] `mqttio.py:37-106`. Re-implement the same
  interface on `solace-pubsubplus` (SMF) - see section 5.
- `BSG/app/bsgdemo/topics.py` (66 lines): all topic templates in one
  module plus Solace wildcard matching (`*`, `>`) and SMF-to-MQTT
  conversion. [V] `topics.py:11-66`. With SMF the conversion goes away,
  the template module stays.

### 1.5 CLI + Makefile -- COPY

- `BSG/app/bsgdemo/ctl.py`: publishes control events, run inside the UI
  pod (`kubectl exec deploy/demo-ui -- python -m bsgdemo.ctl ...`) so
  it reuses the pod's broker env/Secret. [V] `ctl.py:1-67`,
  `BSG/Makefile:9`.
- `BSG/Makefile`: `help test build push k8s-up mesh-up demo-up
  demo-reset uninstall scenario-* smoke port-forward status logs urls`;
  `CONTAINER_CLI ?= docker` for Rancher moby vs nerdctl. [V]
  `BSG/Makefile:1-76`.

### 1.6 FastAPI + SSE presenter UI -- ADAPT

`BSG/app/bsgdemo/ui/server.py` (305 lines) + `ui/static/index.html`
(365 lines, vanilla JS, no build step).

- `Hub`: broker messages -> typed UI events (`kind`, `ts`, `data`),
  bounded backlog (`deque(maxlen=300)`), fan-out to per-client
  `asyncio.Queue` with `loop.call_soon_threadsafe`. [V]
  `server.py:78-151`.
- `/api/events` SSE: one `snapshot` event (backlog) on connect, then
  `ev` events, plus a `ticker` snapshot every 0.5 s; headers
  `Cache-Control: no-cache`, `X-Accel-Buffering: no`. [V]
  `server.py:266-291`.
- POST endpoints for each presenter button (`/api/step1`,
  `/api/scenario`, `/api/action`, `/api/reset`); the action endpoint
  publishes the human decision with `by` and `note_ref`. [V]
  `server.py:196-244`.
- `ENTRY_MODE=entrypoint|direct` fallback switch with a visible banner
  when the agent is bypassed. [V] `server.py:8-14,196-212`,
  `BSG/RUNBOOK.md:65-67`.
- `collect_text()` extracts answer text from A2A task JSON. [V]
  `server.py:63-75`.
- Page: header with connection dot and links to Grafana and SAM
  Activities, three columns (live ticker, numbered steps, event
  stream), node list with per-node state and seconds, timer from the
  alert, note box, self-drawn SVG chart from the watcher's data. [V]
  `index.html:100-153,161-198,287-326`.
- German UI, 20 px base font, `de-DE` number formatting. [V]
  `index.html:15,157-158`.

For the showcase: split into a **monitor page** (live scans, agent
proposals, workflow nodes with real timings, "price is now X at the
till / ESL") and a **tablet page** (pending proposals as big cards with
"Freigeben" / "Ablehnen"), both served by the same FastAPI app, plus a
simulated **ESL page**.

### 1.7 solclientjs browser UI -- PATTERN (for operator tools, not tablets)

- `INS/cockpit/index.html` (684 lines) + `INS/cockpit/solclient.js`
  (solclientjs 10.17.1 vendored, [V] `grep version solclient.js`):
  the browser connects itself to `ws://localhost:8008`, VPN `sam`,
  `default/default`, publishes PERSISTENT with per-message ack,
  subscribes the result topic. [V] `INS/cockpit/index.html:290-301,620-670`.
- UTF-8 fix: solclientjs hands binary attachments over as byte strings;
  decode with `TextDecoder` before `JSON.parse` (applied in all three
  older demos). [V] `INS/cockpit/index.html:659-670`,
  `RET/shop/index.html` (same block).
- Robust parsing of the A2A task JSON on `successOutput`
  (`responseType: full`): data part first, depth-first search, JSON in
  text as last resort; ignore results for other ids, late duplicates
  and interim states. [V] `INS/cockpit/index.html:376-475`.
- `INS/tools/fire-claim.js`: the same browser solclient.js used from
  node to fire one event and wait for the result with an exit code
  (preflight dry fire). [V] `fire-claim.js:1-26`.
- Served locally via `.claude/launch.json` (`python3 -m http.server`
  ports 8097-8099). [V] `REPO/.claude/launch.json`.

Limit: `ws://localhost:8008` only works in a browser on the presenter
Mac and puts broker credentials into the page. A tablet or a second
monitor on the booth LAN cannot use it as is. Use it for a
"fire-scan.js"-style rehearsal tool and keep the stage UIs server-side
(FastAPI + SSE).

### 1.8 Kubernetes manifests, ingress, TLS -- COPY

`BSG/k8s/` (all [V]):

- `kustomization.yaml`: namespace, `app.kubernetes.io/part-of` label
  (`includeSelectors: false`), image name `bsg-demo` rewritten to
  `registry.solace.lab/bsg-demo/bsg-demo:0.1.0`. [V] `kustomization.yaml:1-21`.
- `configmap.yaml`: all non-secret config, broker host
  `host.docker.internal` (CoreDNS NodeHosts entry maintained by
  `AMD/scripts/start.sh`). [V] `configmap.yaml:1-23`.
- Secret `bsg-broker` created by `install.sh` from `.env` with
  `--dry-run=client -o yaml | kubectl apply -f -`. [V]
  `BSG/scripts/install.sh:18-23`.
- Hardened pods: `runAsNonRoot`, `runAsUser 10001`,
  `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`,
  `emptyDir` for `/tmp`, small requests/limits,
  `imagePullSecrets: registry-pull-secret`. [V] `bsg-tools.yaml:17-43`.
- Stateful single-instance component: `replicas: 1`,
  `strategy: Recreate`, `fsGroup`, emptyDir `/data` for SQLite. [V]
  `feed-watcher.yaml:6-8,17,40-47`.
- Ingress: `cert-manager.io/cluster-issuer: solace-lab-ca-issuer`,
  `ssl-redirect`, `proxy-buffering: "off"` and
  `proxy-read-timeout: "3600"` for SSE, `ingressClassName: nginx`,
  TLS secret per host. [V] `demo-ui.yaml:50-74`.
- Kyverno policies the manifests must pass (live cluster): 
  `ingress-require-tls`, `cert-restrict-domain` (all dnsNames end in
  `.solace.lab`), `cert-require-ecdsa`, `cert-require-san-no-cn`,
  `cert-max-duration`, `cert-enforce-issuer`,
  `inject-registry-pull-secret`, `sync-registry-pull-secret`,
  `inject-solace-lab-ca-trust-bundle`. [V] `kubectl get clusterpolicy`.
  BSG passed all of them with a server-side dry run. [V]
  `BSG/README.md` Gate 0 item 5.

### 1.9 SAM mesh package -- ADAPT

`BSG/mesh/` (all [V]):

- `manifest.yaml`: `kind: manifest`, target `solace-lab` /
  `https://sam.solace.lab` / `auth.type: oauth`, resources by name. [V]
  `manifest.yaml:12-31`.
- `connectors/bsg-desk-tools.yaml`: `type: mcp`, `subtype: remote`,
  in-cluster `server_url`, `streamable-http`, `auth_type: none`, and a
  generated `manifest:` YAML list with `inputSchema`/`outputSchema`.
  [V] `connectors/bsg-desk-tools.yaml:27-72`.
- `workflows/bsg-alert-triage.yaml`: `input_schema` that declares every
  payload field and no `text`, a `type: tool` node with
  `connector:` + `tool:`, two parallel agent nodes with
  `output_schema_override` and instructions that name the keys, a
  `type: switch` with a cautious `default`, branch-specific agent
  nodes, a closing tool node with `coalesce`, `output_mapping` with
  `coalesce`, `workflow_timeout 90s`, `default_node_timeout 40s`,
  `fail_fast: true`. [V] `bsg-alert-triage.yaml:51-257`.
- `entrypoints/*.yaml.template` rendered by `install.sh` into the
  git-ignored `mesh/.rendered/` (credentials from `.env`, workflow
  target); rule with `targetWorkflowName`, `inputExpression:
  "input.payload:"`, `defaultUserIdentity: power_user@solace.lab`,
  `qos: 1`, `acknowledgmentPolicy: on_completion` with timeout,
  `successOutput`/`errorOutput` topics. Second rule targets an agent
  with `promptTemplate`. [V] `entrypoints/bsg-desk-events.yaml.template:26-85`.
- Agents: `modelProvider: [fast]` for workflow nodes, `[general]` for
  the chat-style assistant, connector wiring, `skills` as card
  advertisements, prompts that forbid the runtime's data tools by name.
  [V] `agents/*.yaml`, e.g. `bsg-quote-analyst.yaml:74-77`.

### 1.10 Install / uninstall / reset / preflight scripts -- COPY + ADAPT

- `BSG/scripts/lib.sh`: sources `AMD/scripts/lib/common.sh`
  (`load_env`, `resolve_sam_cli`, `sam_auth_token`), `sam_login`
  (refreshes the token with a harmless `sam config plan`), `api` (curl
  with bearer, `?pageSize=100` on GETs), `id_of`, `delete_named`,
  `ui_exec`. [V] `lib.sh:1-53`, `AMD/scripts/lib/common.sh:1-74`.
- `BSG/scripts/install.sh k8s|mesh|all`: k8s first (secret, kustomize,
  rollout restart, rollout status), refuses `mesh` before the MCP
  server runs, `sam config apply`, resolves the workflow id, renders
  the entrypoint, applies it, applies the dashboard ConfigMap. Only
  additive, everything named `bsg-*`. [V] `install.sh:1-88`.
- `BSG/scripts/uninstall.sh`: named DELETEs in dependency order
  (entrypoint, workflow, agents incl. retired names, connector),
  dashboard, namespace, `.rendered/`; never `--prune`. [V]
  `uninstall.sh:1-30`.
- `BSG/scripts/reset.sh`: back to start in seconds (scenario reset,
  watches cleared, status normal, UI stream cleared). [V] `reset.sh:1-16`.
- From the insurance demo, worth adding:
  - mutual-exclusion guard against other demo overlays (checks for
    their entrypoints) and stop of conflicting containers. [V]
    `INS/install.sh:171-186`;
  - wait for the gwe log line "persistent receiver started ... <rule>"
    before the first event (events before that are lost). [V]
    `INS/install.sh:412-433`;
  - `preflight.sh` with `ok/warn/fail/step`, auto-fix, model probes,
    store checks, broker WebSocket check, dashboard/datasource/grant
    checks, eval pre-runs and a **dry fire** that must print a result;
    ends READY / NOT READY. [V] `INS/preflight.sh:224-228,290-683`;
  - `demo-links.sh` printing hash-routed SAM UI links by id. [V]
    `INS/demo-links.sh:1-40`.

### 1.11 Connector manifest generator -- COPY

`BSG/scripts/gen_connector_manifest.py` (203 lines): calls
`initialize` + `tools/list` over streamable HTTP (handles SSE framing),
or reads `--tools-json` from the in-cluster `--dump-tools`, prefers the
server's `outputSchema`, falls back to documented schemas, renders a
YAML block list with JSON-flow schemas and rewrites the connector file
in place. [V] `gen_connector_manifest.py:1-203`.

### 1.12 Grafana dashboard generator -- COPY + ADAPT

`BSG/scripts/gen_dashboard.py` (236 lines) ->
`BSG/observability/dashboard-sam-bsg-trading-desk.yaml`:

- Datasource `sam-platform-db` = WebUI DB (`tasks`). [V]
  `gen_dashboard.py:4`, `BSG/README.md` Gate 0 item 6.
- Node recognised by the instruction prefix the workflow sends
  (`NODE_CASE`), because `tasks` only has generated ids. [V]
  `gen_dashboard.py:8-17`.
- Dashboard variable `ep` resolved from the data
  (`SELECT DISTINCT entrypoint_id ... LIKE '%watcher_api%'`), so
  nothing is rendered at install time. [V] `gen_dashboard.py:200-212`.
- Panels: last run duration with 45/60 s thresholds, tokens of the last
  run, runs and failures in range, branch of the last run, node table
  and bar chart, runs table, tokens per agent, "Der Beleg" text. [V]
  `gen_dashboard.py:80-195`.
- ConfigMap in `sam-solace-lab`, label `grafana_dashboard: "1"`,
  annotation `grafana_folder: SAM`. [V] `gen_dashboard.py:216-236`.

For the showcase add panels "Vorschlaege / Freigaben / Ablehnungen",
"Zeit bis Freigabe", "Tokens pro Kassenbon" - most of these come from
the demo's own Postgres, not from `tasks` (second datasource).

### 1.13 Eval sets -- ADAPT

- `INS/eval/`: `manifest.yaml` (datasets + experiments),
  `experiments/ins-triage-decision.yaml` (target = the merge agent,
  `LLM Judge` primary + `Closed QA`, `runsPerExample 1`,
  `maxWorkers 3`), datasets as CSV with one-line JSON prompts that are
  the exact fan-in of the workflow node, expected responses with every
  field of the contract. [V] `INS/eval/manifest.yaml:1-44`,
  `experiments/ins-triage-decision.yaml`, `datasets/ins-triage-decisions.yaml`.
- `RET/eval/experiments/retail-ops-model-benchmark.yaml`: same agent on
  three models via `spec.models[].modelConfigId`. [V].
- Workflows cannot be experiment targets; exercise node agents. Do not
  use `Response Match` for JSON verdicts (punished correct answers:
  3/3 judge vs 1/3 match). [V] `INS/eval/experiments/ins-triage-decision.yaml`
  description, `INS/README.md` "Evaluation experiments".
- Eval cost: ~40 s per judge call, waves of ~4; pre-run, never live on
  stage. [V] `INS/eval/manifest.yaml:12-19`.

For the showcase: one dataset "proposal decisions" (article context
JSON -> expected markdown/promotion proposal within guardrails: margin
floor, max discount, no price below cost) and one guardrail set (prompt
injection in an article description, "set all prices to 0").

### 1.14 Postgres seed pattern -- COPY

- `RET/postgres/seed.sh` / `INS/postgres/seed.sh`: checks the host
  container `postgres` is running, creates the DB if absent, pipes the
  SQL (pg_dump `--clean --if-exists` or hand-written DROP/CREATE) with
  `ON_ERROR_STOP=1`; idempotent; `db:sqlfile` pairs because macOS bash
  3.2 has no associative arrays. [V] `RET/postgres/seed.sh:1-41`.
- Connectors reference credentials inline as `${RETAIL_DB_USERNAME,
  postgres}` (an inline default, no `variables:` block, because a
  manifest default beat the environment on CLI 2.348.22). [V]
  `RET/core/connectors/Retail OMS DB.yaml`, `RET/core/manifest.yaml`
  comment.
- Deterministic seed generators checked in next to the data
  (`random.seed(118)`). [V] `MFG/mongodb/seed/generate-seed.py:1-25`.
- Domain reuse: `retail_pdm.retail_product_master` already has
  `unit_price`, `cost_price`, `barcode`, `stock_level`,
  `margin_percent`, `inventory_status`, `seasonality`,
  `popularity_score`. [V] `RET/postgres/sql/03-retail_pdm.sql:65`. It is
  a US grocery data set (New York stores, USD, [V] POSLOG sample) - use
  the schema idea, not the data, for a German booth assortment.

### 1.15 Smoke test and unit tests -- COPY

- `BSG/scripts/smoke_tools.py`: drives the MCP tools exactly like an
  agent, sniffs the broker, asserts "exactly ONE alert", checks the
  human action and the reset; exit code 0/1; no SAM needed. [V]
  `smoke_tools.py:1-60`.
- `BSG/app/tests/test_core.py`: 22 tests on topic matching, catalogue,
  engine hold/debounce/rearm/TTL, simulator scenarios, store and
  statistics (pure functions, no broker). [V] `test_core.py`,
  `BSG/README.md` "Status".

### 1.16 Shared infrastructure in agent-mesh-deployment -- USE, do not copy

- `AMD/scripts/lib/common.sh` (sourced by every demo). [V].
- `AMD/scripts/models/apply-models.sh` (aliases `fast`, `workflow`,
  `expert`, ... ; run before agents that bind to them). [V]
  `INS/install.sh` step 3.
- `AMD/scripts/observability/grant-grafana-platform-db.sh` and the
  platform-DB datasource, if the dashboard needs the platform DB. [V]
  `INS/install.sh` step 8.
- SAM itself connects to `ws://host.docker.internal:8008`, VPN `sam`,
  `default/default`. [V] `AMD/local-k8s-values.yaml` `broker:` block.

### 1.17 Event mesh: how VPNs and clients are provisioned -- READ ONLY

- `EMD/terraform/broker_solace_1.tf:5-91`: modules `vpn` and `client`
  per VPN; VPN `sam` has `services_enabled = false` plus AMQP 5673 for
  the OTel receiver; client username `default` on every VPN; telemetry
  module on `default` and `sam`. [V].
- `EMD/terraform/modules/vpn/main.tf:59-68`: every MQTT listener is
  tied to `services_enabled` -> VPN `sam` has no MQTT (also no REST
  incoming); SMF and web transport are not toggled by it, which is why
  SAM reaches `sam` over 8008. [V].
- `modules/vpn/main.tf:89-95`: ACL profile `default` allows connect,
  publish and subscribe on every topic. [V].
- `EMD/docker-compose.yaml`: solace-1 publishes 8008 (web), 55557->55555
  (SMF), 1883 (MQTT), 8080 (SEMP), 5672, 9000, ... [V].
- A dedicated client username for the demo would be a new
  `module "client"` block = a broker change; not needed, the existing
  `default` user on VPN `sam` is what all older demos use. [V]/[A].

### 1.18 Not to reuse

- `INS/external-agent/` (v1 SDK agent in another namespace): only
  relevant if GEBIT wants "their own agent outside the platform". SKIP
  for now.
- MongoDB stores and `fallback/` Builder beats of retail/mfg: SKIP (no
  live Builder beat planned; Mongo adds a port-27017 conflict with the
  other demos).
- Qdrant + MCP (`INS/qdrant/`): only if a promotion-rules knowledge base
  is wanted; the host Postgres has no pgvector. The compose pattern
  (external network `solace_net`, named volumes, healthchecks, one-shot
  seed job, pinned image) is the template if needed. [V]
  `INS/qdrant/docker-compose.yaml`.

---

## 2. Conventions to follow

### 2.1 Directory layout

BSG layout (newest, recommended):

```text
<demo>/
  README.md        English; status, measured numbers, decisions, Gate 0
  RUNBOOK.md       show script with measured timings and fallbacks
  Makefile         test build push k8s-up mesh-up demo-up demo-reset ...
  .env.example     placeholders only; .env git-ignored
  .gitignore       .env, mesh/.rendered/, __pycache__/, .pytest_cache/, *.db
  app/             one Python package, Dockerfile, requirements(-dev).txt, tests/
  k8s/             kustomize: namespace, configmap, one file per component
  mesh/            manifest.yaml, connectors/, agents/, workflows/,
                   entrypoints/*.template, .rendered/ (git-ignored)
  observability/   generated dashboard ConfigMap
  scripts/         lib.sh install.sh uninstall.sh reset.sh smoke_*.py gen_*.py
  eval/            (older demos) manifest.yaml datasets/ experiments/
  postgres/        (older demos) seed.sh sql/
  slides/          exactly one deck
```

[V] `BSG/` tree; older demos add `core/`, `eval/`, `postgres/`,
`preflight.sh`, `demo-links.sh`, `talk-track.md`, `slides/`. The repo
CLAUDE.md says demos are top-level directories, self-contained,
layered on `agent-mesh-deployment/` via idempotent install/uninstall.
[V] `REPO/CLAUDE.md` "Project Overview".

### 2.2 Naming

- One short prefix everywhere: SAM resources `bsg-*`, namespace
  `bsg-demo`, topics `bsg/...`, image
  `registry.solace.lab/bsg-demo/bsg-demo:<semver>`, label
  `app.kubernetes.io/part-of: bsg-trading-desk-demo`, dashboard uid
  `sam-bsg-trading-desk`, host `bsg-desk.solace.lab`. [V] BSG files
  above. The uninstall relies on the prefix (named deletes only).
- Suggested for the showcase [A]: prefix `gpos` (or `gebit`), dir
  `gebit-price-agent-demo/`, namespace `gpos-demo`, host
  `gpos.solace.lab` (monitor) + `/tablet` path, workflows
  `gpos-scan-insight`, `gpos-basket-close`, entrypoint `gpos-pos-events`.
- Older demos use display names with spaces for agents ("Claims Triage
  Decision"); BSG uses kebab-case names. Prefer BSG's kebab-case (easier
  in scripts, dashboards, URLs). [V].

### 2.3 Topics

- Lowercase, `/`-separated, domain prefix first, entity ids last so
  wildcards select by entity: `bsg/quotes/{issuer}/{class}/{isin}`,
  `bsg/alerts/{watch_id}`, `bsg/desk/notes/{watch_id}`; control topics
  under `.../control/...`; SAM outputs on fixed `results` / `errors` /
  `replies` topics. [V] `BSG/app/bsgdemo/topics.py:11-28`,
  `BSG/README.md` "Topic layout".
- Older demos: `acmeins/claims/fnol/received/<severity>/<claim_id>`,
  results `acmeins/claims/result/triage`, decisions
  `acmeins/claims/decision/<claim_id>`;
  `acmeretail/shop/order/{created|failed}/...`. [V].
- The SAM namespace prefix `sam-solace-lab/` belongs to SAM; never
  publish under it. [V] `AMD/CLAUDE.md` (namespaceId = broker topic
  prefix).
- For GEBIT, keep two layers [A]: raw source events named after GEBIT
  (`gpos/raw/purchase/v2/{eventType}/{store}/{till}/{txId}`) and lean
  demo facts (`gpos/fact/...`) that SAM subscribes to. The swap to the
  real system then only changes who publishes `gpos/raw/...`.

### 2.4 Identity, RBAC, models

- Every event-mesh rule sets `defaultUserIdentity:
  power_user@solace.lab`; without it event tasks run as the bare
  gateway identity and are invisible in Activities and unattributed in
  chargeback. [V] `BSG/README.md` "Decisions",
  `AMD/CLAUDE.md` "Cluster Dependencies", WebUI DB `tasks.user_id`.
- Installs run as `sam_admin` (`sam auth login solace-lab --url
  https://sam.solace.lab`, browser OIDC; the agent session cannot do
  the login). [V] `AMD/CLAUDE.md` "Start and Stop".
- `fast` (Haiku 4.5) for workflow nodes; `general` for chat; `workflow`
  (Sonnet 5) / `expert` (Opus 5) only where measured necessary. Model
  aliases must be lowercase; Claude 5 models reject
  `temperature/top_p/top_k`. [V] `AMD/CLAUDE.md` "scripts/models".
- `ask_user_question` (HIL) does not work on event-mesh entrypoints or
  workflow agents; `notify_user` (`notification_tools`, YAML-only, scope
  `notify:_:send`) sends fire-and-forget notifications to a user's
  inbox. [V] samdocs `reference__built-in-tools.md:159-171,834-847`.
  The approval click therefore belongs in the demo's tablet UI (as in
  BSG step 4 and the insurance Approve button); `notify_user` can add a
  SAM inbox notification for the owner's "notifications in SAM" idea
  [A, not yet tried in the lab].

### 2.5 Language and documentation

- Docs English, no special characters, markdownlint clean: line length
  80 (not in code blocks/tables), no bare URLs, avoid HTML;
  `npx markdownlint-cli <file>`; config `REPO/.markdownlint.json`. [V]
  `REPO/CLAUDE.md` "Writing Documentation", `.markdownlint.json`.
- UI and agent texts German for a German audience (BSG) - the
  insurance demo is English. [V] `BSG/README.md` "Decisions".
- Agent output ASCII-safe (or decode UTF-8 explicitly in every
  consumer); BSG notes used transliterations like
  "Plausibilitaetspruefung". [V] memory `project_sam_v2_workflow_events.md`,
  `BSG/README.md` measured note texts.
- README/RUNBOOK carry measured numbers with dates, not hopes; a
  "Gate 0" section records what was measured before building. [V] BSG
  README.

### 2.6 Delivery and lab rules

- One slide deck per demo under `slides/`, ASCII file name with " - ",
  format-preserving python-pptx edits, render (soffice + pdftopng) and
  show the renders before committing. [V] memory
  `feedback_one_deck_per_demo.md`.
- Images only from `registry.solace.lab` (offline lab); pull secret
  `registry-pull-secret` is placed by Kyverno. [V] `AMD/CLAUDE.md`,
  `BSG/README.md` Gate 0 item 5.
- CA trust: Kyverno injects the lab CA bundle and sets `SSL_CERT_FILE`
  / `REQUESTS_CA_BUNDLE` - fine for Python/node/curl; JVM services need
  a truststore init container. [V] memory `project_jvm_lab_ca.md`,
  Kyverno policy description.
- Pin every dependency exactly (BSG `requirements.txt`, insurance MCP
  `requirements.txt` with reasons). [V].
- Never `sam config apply --prune` (would delete the Orchestrator and
  other demos). [V] `RET/core/manifest.yaml`, `AMD/CLAUDE.md`.
- `.env` git-ignored, `.env.example` checked in; rendered manifests
  git-ignored. [V] `BSG/.gitignore`, `REPO/.gitignore`.
- Work on master, no feature branches; ask before pushing. [V] memory
  `feedback_master_workflow.md`.
- Lab cleanup safety: never `docker container prune` (solace-2 config
  lives in its writable layer), never `docker volume prune -a`, never
  registry `--delete-untagged`. [V] memory `project_lab_cleanup_safety.md` (index entry
  "Lab cleanup safety").

---

## 3. Pitfalls that cost time, and how the new demo avoids them

Each item: what happened, source, avoidance.

### 3.1 Broker and VPN

1. **MQTT selects the VPN by port; 1883 is VPN `default`, VPN `sam` has
   no MQTT.** BSG's feed and SAM would have sat on two VPNs; BSG moved
   its entrypoint to `default` and lost SAM status visibility. [V]
   memory `project_event_mesh.md`, `BSG/README.md` "Open decisions A".
   Avoid: use SMF (Python `solace-pubsubplus` server-side,
   `tcp://host.docker.internal:55557`) on VPN `sam` with the existing
   `default` client, like the older demos do over WebSocket. No broker
   change. Alternative only if GEBIT insists on MQTT: owner decision A1
   (move 1883 to `sam`).
2. **Events published before the entrypoint receiver is up are lost**
   (no queue yet). [V] `INS/install.sh:412-433`, `AMD/CLAUDE.md`.
   Avoid: install waits for "persistent receiver started", preflight
   does a dry fire.
3. **Stale queues / spool over quota** after v1 removal blocked every
   guaranteed publish on `sam`. [V] memory `project_sam_v2_migration.md`.
   Avoid: the demo creates no durable queues of its own on `sam`
   (entrypoint queues are SAM's); POS raw events can be direct or
   persistent to topics without a queue; preflight checks spool usage
   [A].
4. **Connector tool subscriptions outlive deleted connectors**
   (`q/str/builtin-tools-worker`); harmless but accumulates. [V]
   `AMD/CLAUDE.md`. Avoid: do not re-create connectors in a loop during
   development; regenerate the manifest instead.

### 3.2 Entrypoint -> workflow

5. **Workflow targets ignore `promptTemplate`; without
   `inputExpression` the workflow gets empty input** (and still deploys).
   [V] `BSG/README.md` Gate 0 item 4, samdocs
   `building__entrypoints__event-mesh__cli.md:96-97`. Avoid:
   `inputExpression: "input.payload:"` on every workflow rule.
6. **`input_schema` decides field vs text delivery**: declare every
   field the payload carries and no `text`, or the payload falls back to
   `workflow.input.text`. [V] `bsg-alert-triage.yaml:66-92`, samdocs
   cli.md:97. Avoid: the watcher emits a fixed, lean fact schema that is
   generated from one Pydantic model used both for publishing and for
   the workflow `input_schema`. Do NOT send raw GEBIT events into SAM
   (an undeclared field flips the delivery mode).
7. **Friendly workflow name works as `targetWorkflowName` on 2.493.0**
   (the runtime-name workaround of 2.225/2.348 is no longer needed).
   [V] `BSG/mesh/.rendered/entrypoints/bsg-desk-events.yaml:47` +
   green runs in `tasks`. Keep the `ENTRYPOINT_WORKFLOW_TARGET=runtime`
   escape hatch from `BSG/scripts/install.sh:55-63`.
8. **`successOutput.responseType: structured` publishes `null` for
   workflows** per the docs; use `full` (A2A task JSON with a data part)
   or `custom` with `customExpression: "input.payload:data[0]"`. [V]
   samdocs `building__entrypoints__event-mesh__cli.md:100`;
   `INS/triage/entrypoints/claims-triage.yaml.template` uses `full`.
   BSG uses `structured` on `bsg/desk/results` but its UI relies on the
   tool node's own publish, not on that topic. Avoid: let a closing
   tool node publish the business result (BSG pattern) and use `full`
   for the generic result topic.
9. **`acknowledgmentPolicy: on_completion` + timeout**: an event is
   acked only after the run, a crash redelivers it; if the timeout is
   shorter than the run, the on-failure action applies while the run
   continues. [V] `bsg-desk-events.yaml.template:22-25,50-52`, samdocs
   `building__entrypoints__event-mesh.md:172`. Avoid: timeout >=
   `workflow_timeout`; idempotent tools keyed by transaction id so a
   redelivery cannot apply a price twice.

### 3.3 Workflow authoring (2.493.0)

10. **`output_schema:` on a node declares nothing**; must be
    `output_schema_override` (and the instruction must name the keys);
    otherwise switch cases never match and fall to `default`, and
    `output_mapping` emits the literal `{{...}}`. Silent. [V]
    `bsg-alert-triage.yaml:23-27`, memory `project_sam_v2_workflow_events.md`.
11. **Never tell a schema-bound node agent HOW to format its answer**
    ("only JSON, first char {") - fast-tier agents then answer in plain
    text, the result artifact is empty, node output null. Instructions
    describe content only. [V] memory `project_sam_v2_workflow_events.md`,
    `INS/triage/workflows/claim-triage.yaml` header.
12. **Agents get `create_sqlite_db`, `merge_structured_data`,
    `artifact_search_and_replace_regex`, ... regardless of `toolsets: []`**
    and may corrupt their input with them; forbid them by name. [V]
    `bsg-quote-analyst.yaml:74-77`, memory.
13. **`coalesce` every optional field in `output_mapping`** or one
    missing key kills the run's output. [V]
    `bsg-alert-triage.yaml:247-256`, `INS/README.md` "The scenario".
14. **No decision model in the lab** -> decision nodes unusable; use
    `switch`. [V] `BSG/README.md` Gate 0 item 6.
15. **Deploy phase only fires on a config change**; bump
    `appConfig.version` to force a redeploy. [V] `AMD/CLAUDE.md` last
    gotcha, `bsg-alert-triage.yaml:53`.
16. **Workflows cannot be eval targets**; MCP-exposed workflows return
    only "completed successfully". [V] `INS/README.md`, `AMD/CLAUDE.md`
    `scripts/desktop/`.
17. **No wait/event node**: "wait for the closing event" cannot be a
    workflow step. [V] `sam config schema show workflow` node list.
    Avoid: basket state in the watcher, a second workflow on the
    closing fact. Node-level `when:` exists on every node type and can
    skip expensive agent nodes cheaply. [V] `sam config schema show
    workflow --type tool` (field `when`).

### 3.4 MCP tools in workflows (each cost one deploy cycle on 2026-11-04)

18. **`sam config apply` never triggers MCP tool discovery** -> "has no
    stored tool list" -> workflow refused. Fix: explicit `manifest:` on
    the connector, generated by `gen_connector_manifest.py`. [V] memory
    `project_sam_mcp_workflow_tools.md`, `BSG/README.md` "What the
    first runs added".
19. **`manifest` must be a YAML list**, not a `|` string, although the
    schema says textarea. [V] same.
20. **MCP responses over 2048 bytes become an artifact** and no field
    resolves ("that value has 9 fields"). `tool_config`/`extract_fields`
    are not available for connector-backed tools. Fix: lean responses.
    [V] same. Relevance: GEBIT's `PurchaseTransactionClosed` sample is
    4744 bytes compact JSON, `CashPaymentPositionCreated` 3277, so no
    tool may echo a raw GEBIT event. [V] `wc -c` on the sample files.
21. **Structured content needs a Pydantic model return type**; with
    `dict` the node sees `{mcp_tool_output, message_to_llm, status}`
    ("that value has 3 fields"). [V] same,
    `tools_server.py:204-237`.
22. **Diagnose with the STIM** (`sam api --target solace-lab
    /api/v1/tasks/<taskId>` -> `result_data.mcp_tool_output`) and the
    awe deploy warning "workflow reference could not be verified",
    not with the node error text. [V] memory
    `project_sam_mcp_workflow_tools.md`.
23. **MCP server must be reachable before the workflow is applied**
    (k8s-up before mesh-up), and DNS-rebinding protection off. [V]
    `BSG/scripts/install.sh:32-43`, `INS/qdrant/mcp-server/server.py`
    docstring.
24. **mcp SDK 2.x renamed FastMCP -> MCPServer and moved host/port to
    `run()`**; pin `mcp[cli]==2.2.0`. [V] `BSG/app/requirements.txt`,
    `INS/qdrant/mcp-server/requirements.txt`.

### 3.5 CLI, auth, API

25. **`sam auth login` is a browser flow**; token cached per target name
    (`solace-lab`), ~1 h access token, refresh via any CLI call;
    `sam eval run` needs `SAM_AUTH_TOKEN` exported (401 otherwise). [V]
    `BSG/README.md` Gate 0 item 7, `INS/README.md` evals,
    `AMD/scripts/lib/common.sh:56-73`.
26. **List endpoints paginate** (default 20) -> `?pageSize=100`. [V]
    `BSG/scripts/lib.sh:24`.
27. **REST paths renamed in 2.348.22** (`/platform/gateways` ->
    `/platform/entrypoints`). [V] `AMD/CLAUDE.md`.
28. **Manifest `variables:` default beat env (CLI 2.348.22)** -> inline
    `${VAR, default}`. [V] `RET/core/manifest.yaml` comment.

### 3.6 UI and presentation

29. **UI could not show agent node progress** (VPN choice) and could not
    render the agent's PNG artifact (needs an authenticated artifact
    URL); it drew its own chart from the watcher instead. [V]
    `BSG/README.md` "Open points", `index.html:283-286,310-326`.
    Avoid: SMF on VPN `sam` + status topics (section 4.4); keep charts
    self-drawn from deterministic data.
30. **SSE behind NGINX needs `proxy-buffering: off`** and a long
    read timeout; MCP/agent calls through the SAM ingress 504'd at 60 s
    until timeouts were raised. [V] `BSG/k8s/demo-ui.yaml:50-61`,
    `AMD/local-k8s-values.yaml:120-123` (proxy-read/send-timeout 900).
31. **UTF-8 mangling in solclientjs** without `TextDecoder`. [V]
    `INS/cockpit/index.html:659-670`.
32. **Results for other ids / late duplicates / interim states** must be
    ignored, the clock frozen at the measured time, a failed run shown
    as FAILED. [V] `INS/cockpit/index.html:356-367,432-475,577-588`.
33. **DNS for a new demo host is missing** (`bsg-desk.solace.lab` still
    not in `/etc/hosts` today; line 16 of `/etc/hosts` is malformed,
    two entries on one line). Needs sudo by the owner. [V] `grep
    solace.lab /etc/hosts`. Avoid: plan the hosts entry early; keep the
    `make port-forward` fallback.
34. **Tablets and a second monitor are other devices**: `*.solace.lab`
    resolves only on the Mac (`127.0.0.1` in `/etc/hosts`) and the lab
    CA is not trusted on a tablet [A]. Avoid: serve the tablet page from
    the same FastAPI app; on the booth LAN either a router DNS entry for
    the ingress IP plus the lab CA installed on the tablet, or a plain
    HTTP port-forward bound to the LAN with a shared secret in the URL.
    Never expose the broker or SAM credentials to the tablet.

### 3.7 Lab fragility (critical for a multi-day fair)

35. **Network change of the Mac** (fair WLAN, hotspot) leaves k3s
    advertising a dead `--node-external-ip`; Kyverno (fail-closed)
    then blocks all pod changes. Fix documented (~2 min). [V] memory
    `project_rancher_stale_external_ip.md`. The ingress address today
    is the home LAN IP `192.168.178.54`. [V] `kubectl get ingress`.
    Avoid: fixed booth network/travel router with the same subnet, or
    rehearse the fix; preflight checks `kubectl get endpoints
    kubernetes` vs the Mac IP and Kyverno pods.
36. **Mac sleep/wake** kills Rancher's SSH port forwards (docker.sock
    and all ports dead) or wedges the container clock (TLS errors
    cluster-wide). [V] memory `project_rd_dead_port_forwards.md`,
    `project_rancher_desktop_clock_wedge.md`. Avoid: disable sleep on
    the booth Mac, morning preflight, documented recovery in the RUNBOOK.
37. **amd64 images under emulation are unstable on this Mac** (DB
    designer). [V] memory index `MEMORY.md` entry "DB Designer K8s deploy". Avoid:
    do not run GEBIT's Java microservices locally; connect to GEBIT's
    lab; build our own images multi-arch (arm64 here, amd64 for GEBIT).
38. **Port collisions**: the insurance knowledge MCP server listens on
    host :8765 (compose), Qdrant on 6333/6334, demo mongos on 27017;
    BSG port-forwards 8765/8080/8090. [V] `INS/qdrant/docker-compose.yaml`,
    `BSG/Makefile:59-62`. BSG is still deployed and running today
    (4 pods in `bsg-demo`). [V] `kubectl -n bsg-demo get pods`.
    Avoid: other local ports for port-forwards (e.g. 8190/8180/8865),
    distinct topic prefix; decide whether the installer refuses or
    tolerates BSG/insurance (insurance refuses other overlays,
    `INS/install.sh:171-186`).
39. **Grafana sidecar drops DELETE events** (stale dashboards survive
    ConfigMap removal). [V] memory `project_sam_v2_migration.md` (leak 2).

### 3.8 Cost and timing

40. **Every agent LLM call carries ~14k tokens of platform prompt**:
    measured `bsg-market-context` (no tools) 14,448 input / 13,656
    cached / 587 output; `bsg-quote-analyst` (one chart tool call)
    30,146 / 28,259 / 848; communicator 28,813 / 27,368 / 661 (61,448
    on a cold, retried run). [V] WebUI DB `tasks.token_usage_details`,
    queried today. Estimate with Haiku 4.5 list prices (USD 1 in /
    5 out per MTok [V] claude-api skill model table; cache write 1.25x
    and cache read 0.1x [A]): ~USD 0.025-0.03 per warm 3-agent run,
    ~0.06-0.08 cold. 50 USD shared budget => roughly 700-2,000 runs
    for everything incl. rehearsals and evals [A]. `general` is Opus
    4.8 [A from memory] and the BSG desk assistant used 41k input per
    call [V tasks]. Avoid: tool-only nodes per scan, LLM only behind a
    deterministic trigger and once per closed basket, fast tier, small
    prompts, no chart tool on the critical path.
41. **Latency budget**: tool nodes 0.3-1.4 s, fast agent nodes 5-11 s;
    alert -> note 14.2 s (2 parallel agents + 1) and 20.3 s; insurance
    4-node run 27-33 s. [V] `BSG/README.md` "Measured",
    `INS/README.md`. Avoid: at most one agent hop on the per-scan path
    (target: insight on screen within ~10 s of the scan), parallel
    fan-out, merge-free switch branches.
42. **Concurrency**: one analyst serving two heavy flows timed out in
    the insurance rehearsal. [V] memory `project_ins_ops_demo.md`.
    Avoid [A]: the watcher rate-limits LLM-triggering facts (e.g. max
    one open proposal per article, one in-flight insight per till) and
    a burst test is part of Gate 0.

---

## 4. How the BSG UI visualises live progress, and what it could not do

### 4.1 Data path

```text
broker (VPN default, MQTT 1883)
  bsg/#  --paho-->  demo-ui Hub (Python thread)
                      |  typed events: watch, alert, progress, note,
                      |  reply, error, action, issuer_status, scenario, news
                      v
  asyncio.Queue per browser  --SSE /api/events-->  EventSource in index.html
     snapshot (backlog of 300) once, then ev, plus ticker every 0.5 s
```

[V] `ui/server.py:78-151,266-291`, `index.html:350-362`.

### 4.2 What the page shows

- Step cards 1-4 turning active/done as events arrive. [V]
  `index.html:200-201,256-307`.
- Workflow node list (`enrich`, `analyst`, `context`, `route`,
  `communicator`, `publish`) with kind badge (Tool/Agent/Switch), state
  icon and seconds. [V] `index.html:161-194`.
- A run timer started at the alert and frozen at the note. [V]
  `index.html:195-198,266-271,287-293`.
- Node state sources:
  - `enrich` running at the alert, finished by the tool's own
    `bsg/desk/progress` event; `publish` finished by the publish tool's
    progress event. [V] `index.html:266-282`, `tools_server.py:343,353,386`.
  - `analyst` and `context` set "running" when `enrich` finishes
    (inferred), everything set "done" when the note arrives. [V]
    `index.html:278-280,290`.
  - Errors on `bsg/desk/errors` mark running nodes failed. [V]
    `index.html:303`.
- The note (German, 8 lines), branch, artifact name, run id; the action
  button for the human decision publishes `bsg/desk/actions` and the
  ticker badge turns "in Pruefung". [V] `index.html:293-306,338-339`.
- Self-drawn spread chart from the watcher's `/recent` series. [V]
  `server.py:247-263`, `index.html:310-326`.

### 4.3 What it could not do

- Real per-node start/end of agent nodes: the timings shown for the
  agent rows are the whole run's, not their own (analyst 8.7 s and
  context 5.3 s in parallel, communicator 11.1 s are only visible in
  Grafana). [V] `BSG/RUNBOOK.md:32-42`, commit `cfff94d`.
- The switch decision before the note arrives (branch only known from
  the note). [V] `index.html:289`.
- SAM's A2A status topics: `SAM_STATUS_TOPICS` stays empty because the
  status events are on VPN `sam`, which has no MQTT listener. [V]
  `k8s/configmap.yaml:21-23`, `BSG/README.md` "Open decisions A".
- Rendering the agent's chart artifact (authenticated artifact URL
  needed). [V] `BSG/README.md` "Open points".
- Cancelling running workflow runs from Reset (platform endpoint
  unknown; runs time out after 90 s). [V] `BSG/scripts/reset.sh:5-7`.

### 4.4 What the new demo can do instead (verified today)

- Status events exist and carry node granularity. WebUI DB
  `task_events` for one BSG workflow run (task
  `01a1a7c8-cd2b-...`) on topic
  `sam-solace-lab/a2a/v1/gateway/status/01a1a646-38f1-7172-bd48-5a77f7ea1c2a/<taskId>`:
  `agent_progress_update` 12, `tool_invocation_start` 9, `tool_result` 9,
  `workflow_node_execution_result` 7, `llm_invocation` 7,
  `llm_response` 7, `workflow_node_execution_start` 6,
  `artifact_saved` 5, `artifact_creation_progress` 2,
  `workflow_execution_start` 1, `workflow_execution_result` 1. [V]
  `psql ... SELECT signal_type, count(*) FROM task_events ...`.
- Payload shape (JSON-RPC status-update), e.g. node start:
  `{"result":{"taskId":...,"kind":"status-update","status":{"state":"working","message":{"parts":[{"kind":"data","data":{"type":"workflow_node_execution_start","node_id":"enrich","node_type":"tool","sub_task_id":"...","cases":null,...}}]}},"final":false}}`
  and node result: `{"type":"workflow_node_execution_result","node_id":"enrich","status":"success","output_artifact_ref":{"name":"wf_enrich_output_5c5141ec.json","version":0}}`.
  [V] same query, payload excerpt.
- The `<gatewayID>` in the topic is the event-mesh entrypoint's id
  (`tasks.entrypoint_id = 01a1a646-...`, `trigger_kind = event`,
  `user_id = power_user@solace.lab`). [V] `psql ... FROM tasks`.
- Node sub-tasks additionally appear on
  `sam-solace-lab/a2a/v1/agent/status/workflow_<id>/<subTaskId>`. [V]
  same table.
- Therefore [A, needs a Gate-0 sniff]: a read-only SMF subscriber on
  VPN `sam` with `sam-solace-lab/a2a/v1/gateway/status/<entrypoint_id>/>`
  receives these events live (ACL `default` allows subscribe on every
  topic [V], and Solace delivers persistent messages to matching direct
  subscriptions [A]); install.sh resolves `<entrypoint_id>` via
  `GET /api/v1/platform/entrypoints` and writes it into the UI
  ConfigMap. Correlating a task with the POS transaction: from the
  `workflow_execution_start` data or the tool nodes' own progress
  events that carry the transaction id [A].
- Fallback if live sniffing is not wanted: poll the WebUI DB
  `task_events` read-only (role `grafana_ro` already exists) every
  second [A: latency of the task-log firehose].
- Caution: these are SAM-internal message formats, not a public
  contract; parse defensively and keep the tool-progress events as the
  guaranteed minimum. [A].

---

## 5. Recommended tech stack for the showcase

### 5.1 Services (one image, several commands, like BSG)

- **Python 3.12 (`python:3.12-slim`, glibc)**, one package
  `app/<prefix>demo/`, commands `pos_sim`, `pos_bridge` (later: gRPC to
  GEBIT), `watcher`, `tools_server`, `ui.server`, `ctl`. Justification:
  BSG proved the image, probes, hardening and Kyverno path on this
  cluster; one image keeps build/push/kustomize simple. [V] BSG.
- **FastAPI 0.162 + uvicorn 0.54 + SSE via `StreamingResponse`**,
  pydantic v2, httpx 0.28 - same pins as BSG. [V]
  `BSG/app/requirements.txt`.
- **MCP: `mcp[cli]==2.2.0`**, streamable HTTP, stateless, JSON
  responses, Pydantic return models, `--dump-tools`. [V].
- **Broker client: `solace-pubsubplus`** (Solace Python API, SMF) for
  every server-side component, on VPN `sam`, user `default`, URL
  `tcp://host.docker.internal:55557` from pods (`tcp://localhost:55557`
  on the Mac). Justification: same VPN as SAM (no broker change, no
  VPN split), read access to SAM status topics, persistent publish
  with acks, native `*`/`>` wildcards, user properties for trace/ids.
  [V] port 55557 reachable from a pod (probe today: 55557 open, 8008
  open, 1883 open, 5432 open, 8080 open, 55555 refused); PyPI
  `solace-pubsubplus` 1.12.0 ships `manylinux_2_17_aarch64` and
  `manylinux_2_12_x86_64` wheels (no musllinux aarch64, so not Alpine)
  [V] `https://pypi.org/pypi/solace-pubsubplus/json`; 1.9.0 is
  installed on the Mac [V] `pip3 show`. WebSocket transport from Python
  is [A]; SMF TCP is the safe choice. Keep the `Bus` interface from
  `mqttio.py` so a paho implementation can be swapped in if GEBIT's lab
  only offers MQTT.
- **Protobuf: Python `protobuf` runtime (6.33.x) with GEBIT's binary
  descriptor sets** `purchase-api-2.50.0.pb` (57 files) and
  `receipt-api-2.13.0.pb` (18 files) loaded into a `DescriptorPool`
  (plus `descriptor.proto` and the well-known types), message classes
  via `message_factory.GetMessageClass`, `json_format.ParseDict`
  for proto3 JSON and `SerializeToString` for binary. Verified: all 11
  `events_simpleSale/*.json` parse strictly (unknown fields rejected)
  with no generated code; binary sizes 138-3,273 bytes. [V] probe
  script `scratchpad/repo-scripts/pb_probe.py` run with `python3 -I`.
  Justification: no codegen step in the image, schema-exact round trip,
  the same descriptors validate simulator output and real GEBIT
  events. Decimals arrive as `{scale, intVal}` (e.g. 867 / scale 2 =
  8.67) -> one helper to `decimal.Decimal`. [V] `03_PositionAdded.json`.
  For the live Purchase Service: `grpcio` (1.78 on the Mac [V]) plus
  `grpcio-tools`/`protoc` (protoc 34.1 installed [V]) to generate stubs
  from the `.proto` sources at build time, or dynamic stubs from the
  descriptor pool [A]. Keep GEBIT sources out of the image build
  context except the descriptor files (untrusted vendor data).
- **SAM `messageFormat: protobuf`** exists for event-mesh rules but the
  schema has no descriptor field, so SAM cannot decode GEBIT messages
  by type [V] `sam config schema show entrypoint --type event_mesh`;
  [A] on what it delivers. Keep SAM on lean JSON facts produced by the
  watcher.
- **Persistence**: host Postgres container (Postgres 18,
  `host.docker.internal:5432` reachable from pods [V]) for article
  master, prices, price history, promotions, loyalty, proposals and
  approvals, with an idempotent `seed.sh`; SQLite on emptyDir only for
  the watcher's rolling window (BSG pattern). No pgvector [given].
  A SAM `sql/postgres` connector (read-only user) is optional for a
  chat agent; all writes go through MCP tools that enforce the
  approval state machine.
- **Price change swap point**: an `ArticlePriceChanged`-style event
  (GEBIT "details to follow") emitted by `apply_approved_price` on
  `gpos/raw/article-master/...`; the simulator's till and the ESL page
  subscribe to it; later the bridge forwards it to GEBIT's article
  master service. [A] until GEBIT specifies the contract.

### 5.2 UIs

- **Monitor and tablet: server-rendered static pages from the FastAPI
  app** (vanilla JS, no build step, SSE in, `fetch` POST out), German,
  large type, self-drawn SVG. Justification: works on any device that
  reaches one HTTPS origin, no broker credentials in the browser, BSG
  proved SSE through the ingress. [V] BSG UI.
- **Approval** = POST from the tablet -> UI server publishes
  `gpos/approval/{proposal_id}` with approver and timestamp (BSG
  `/api/action`, insurance `approve()`); the tools server applies the
  price only for an approved proposal id. SAM HIL is not available on
  this path. [V] samdocs `reference__built-in-tools.md:171`.
- **ESL**: a simulated ESL tile page (subscribes to price changes) for
  now; a real ESL vendor API later behind the same event. [A].
- **Rehearsal / dry-fire CLI**: Python `ctl` inside the UI pod (BSG) or
  node + solclient.js (insurance `fire-claim.js`); prefer the Python
  one to keep one language. [V].
- **SAM proof views**: links to SAM Activities and the Grafana dashboard
  in the header (BSG). [V] `index.html:106-110`.

### 5.3 Packaging and operations

- `make build push` to `registry.solace.lab/<prefix>-demo/<prefix>-demo:<ver>`;
  add `docker buildx build --platform linux/arm64,linux/amd64` for the
  GEBIT lab. [V] `BSG/Makefile:21-25`; [A] buildx availability in
  Rancher's moby.
- kustomize overlay per environment later (`k8s/base`, `k8s/lab`,
  `k8s/gebit`) so the broker URL, VPN, POS source (simulator vs bridge)
  and host names are config only. [A].
- `install.sh k8s|mesh|all`, `uninstall.sh`, `reset.sh`,
  `preflight.sh` (with a dry-fire scan and the network/Kyverno checks of
  3.7), `gen_connector_manifest.py`, `gen_dashboard.py`, pytest unit
  tests for simulator, basket state machine and pricing rules, a
  `smoke_tools.py` without SAM. [V] patterns above.

---

## 6. Suggested event/flow skeleton (derived from the patterns)

Not a design decision, a sketch to show how the building blocks fit
[A]:

```text
POS simulator / booth scanner / (later) GEBIT bridge
  -> gpos/raw/purchase/v2/<EventType>/<store>/<till>/<txId>   (proto3 JSON or binary)
watcher (deterministic, Postgres + SQLite window)
  - per tx basket state; drop on PurchaseTransactionCancelled
  - per article sales velocity vs plan, stock, active promotions
  -> gpos/fact/scan/<till>/<txId>          lean, every PositionAdded (UI only)
  -> gpos/fact/insight/<articleId>         only when a rule fires (debounced)
  -> gpos/fact/basket-closed/<txId>        on PurchaseTransactionClosed
SAM entrypoint gpos-pos-events (VPN sam, power_user, inputExpression)
  insight       -> workflow gpos-price-proposal:
                   tool(context) -> agent(fast, proposal) -> tool(publish PENDING)
  basket-closed -> workflow gpos-basket-close:
                   tool(basket summary) -> switch(loyalty?) -> agent(voucher text) -> tool(issue voucher)
tablet: Freigeben -> gpos/approval/<proposalId>
tools server: apply price -> gpos/raw/article-master/price-changed/<articleId>
till simulator and ESL page pick up the new price; monitor shows the whole chain
plus real node timings from sam-solace-lab/a2a/v1/gateway/status/<entrypoint_id>/>
```

---

## 7. Open questions

For GEBIT:

1. Which transport will the demo lab offer for the Purchase Service
   events: gRPC event stream per client, Kafka, Solace, MQTT? (Decides
   whether the bridge is gRPC->SMF or broker-to-broker.)
2. Are events available in binary protobuf, proto3 JSON, or both; is
   `PurchaseTransactionClosed.serializedReceiptContent` always present,
   and in which format?
3. The price change contract for the article master service (command
   or event, fields, validity date, store scope, who confirms) and
   whether an ESL integration exists in the demo lab.
4. Can a POS client in the demo lab subscribe to events of *all* tills,
   or only its own transactions?
5. Network access from the booth Mac to GEBIT's lab (VPN? latency?),
   and whether GEBIT runs amd64 only.

For the owner:

1. VPN decision: SMF on VPN `sam` (recommended, no broker change) or
   MQTT with the 1883 move (A1) or stay on `default` (A2, no SAM
   status in the UI)?
2. Is a live sniff of `sam-solace-lab/a2a/v1/gateway/status/...` for
   the UI acceptable (internal format), or should node progress come
   only from the demo's tool events?
3. LLM budget for the fair days (shared 50 USD cap): accept "LLM only
   on deterministic triggers + basket close", or raise the budget?
4. Booth network: own travel router / fixed subnet to avoid the k3s
   stale-IP wedge; who adds `/etc/hosts` / router DNS entries and the
   lab CA on the tablet?
5. Coexistence: may BSG stay deployed (it keeps publishing quotes on
   VPN `default`), or does the new installer refuse other overlays like
   the insurance demo does?
6. UI language German only, or German with English toggle for
   international visitors?
