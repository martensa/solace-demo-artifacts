# BSG Trading Desk Assistant demo

A short multi-agent demo for Boerse Stuttgart architects and market
data people: the same Solace mesh that carries their quote feeds
(MQTT), now with agents on top that act on live events, run in a
predictable SAM workflow, and are observable step by step.

Storyline (four steps, one thread, under 7 minutes) and the show
script: [RUNBOOK.md](RUNBOOK.md).

## Status

Work in progress. Built so far, without access to the lab cluster:

- `app/` -- feed publisher, deterministic watcher, MCP tools server
  and presenter UI (one Python image). 22 unit tests pass, and the
  smoke test of the whole deterministic path passes against the real
  broker `solace-1`, twice: with the components run locally and with
  them running in the cluster. A watch from the tool call, exactly
  one alert 10.3 s after the scenario start, enrichment with three
  data sets, desk note, issuer status, reset.
- `k8s/` -- APPLIED. Namespace `bsg-demo` runs `feed-publisher`,
  `feed-watcher`, `bsg-tools` and `demo-ui`; the quotes of all three
  issuers flow through `solace-1`, the Ingress serves
  `bsg-desk.solace.lab` over TLS from the lab CA, and the `awe` pod
  reaches the MCP server at `bsg-tools.bsg-demo.svc:8765` (checked
  with a real `initialize` call).
- `mesh/` -- APPLIED and RUN. Connector, four agents, the
  `bsg-alert-triage` workflow and the `bsg-desk-events` entrypoint are
  on the platform, and both branches of the switch were verified on
  the cluster (numbers under "Measured").
- `observability/` -- APPLIED. The Grafana dashboard
  `sam-bsg-trading-desk` reads the `tasks` table through the
  `sam-platform-db` datasource.

## Measured on the cluster (2026-11-04)

One full run, from the UI's step 1 to the desk note on the mesh:

- Desk request to watch: the assistant answers in 7.4 s and the watch
  carries the right filter and condition.
- Scenario to alert: 10.4 s, exactly one alert per watch.
- Alert to desk note: **14.2 s** issuer specific, **20.3 s** market
  wide -- against a 60 s budget and a 90 s workflow timeout.
- Inside a run: `enrich` 0.3-1.4 s (a tool node, no model),
  `bsg-quote-analyst` 8.7 s, `bsg-market-context` 5.3 s (those two in
  parallel), `bsg-desk-communicator` 11.1 s, `publish` well under a
  second. About 60k tokens issuer specific, 92k market wide.
- Issuer specific: "Spread 0,80% vs. 15-Min-Mittel 0,25% (Faktor 3,1).
  Beta und Gamma halten mit 0,18% bzw. 0,23% deutlich unter Schwelle
  0,50%" -> Plausibilitaetspruefung empfohlen.
- Market wide: "Beta (0,91 %) und Gamma (0,89 %) zeigen vergleichbar
  erhoehte Spannen ... DAX in letzten 60 s um 3,42 % gefallen,
  High-Impact-News aktiv" -> Marktlage beobachten, keine
  Emittentenmassnahme.

## Architecture

```text
bsg-demo namespace            solace-1, VPN default         sam-solace-lab
feed-publisher --MQTT--> bsg/quotes|reference|news --> feed-watcher
demo-ui --MQTT--> bsg/control/*, bsg/desk/actions --> publisher, watcher
demo-ui --MQTT--> bsg/desk/requests/{id} --> entrypoint --> bsg-desk-assistant
feed-watcher ---> bsg/alerts/{watch_id} --> entrypoint --> bsg-alert-triage
bsg-tools (MCP) <-- tool calls of the agents (connector bsg-desk-tools)
bsg-tools ------> bsg/desk/notes|progress/{watch_id}
demo-ui <-- SSE <-- bsg/# (plus SAM status topics, read only)
```

Components (all in `app/bsgdemo/`, one image, see `app/Dockerfile`):

- `publisher.py` -- three fictional issuers (alpha, beta, gamma),
  five products each in `dax-turbo`, `nasdaq-knockout` and
  `discount-cert`; ISINs `DE000DEMO0001` to `DE000DEMO0015`. Quotes
  every 250-500 ms per product, spreads 0.10-0.30 %, prices as a
  random walk around the reference level. Scenarios on
  `bsg/control/scenario`: `wide_spread`, `market_wide`, `stale`,
  `reset`.
- `watcher.py` + `watch_engine.py` -- deterministic, no LLM. Keeps
  15 minutes in memory and in SQLite (emptyDir), evaluates watches
  (`spread_pct`, `quote_age_s`, `drift_vs_ref_pct`) with hold time,
  TTL and debounce, publishes alerts, tracks the issuer status, and
  serves `/recent`, `/reference`, `/news`, `/watches`, `/alerts`,
  `/issuer-status`, `/stats`.
- `tools_server.py` -- MCP server (streamable HTTP) with
  `watch_feed`, `list_watches`, `stop_watch`, `enrich_alert`,
  `publish_desk_note`, `report_progress`. SAM v2 (Go) has no
  in-process Python tools, so every deterministic data access runs
  here.
- `ui/` -- FastAPI + SSE presenter page (German, large type).
- `ctl.py` -- CLI for the scenario Make targets.

Topic layout (prefix `bsg/`):

- `bsg/quotes/{issuer}/{product_class}/{isin}`
- `bsg/reference/{underlying}`, `bsg/news`
- `bsg/control/scenario`, `bsg/control/scenario/state`,
  `bsg/control/watch`
- `bsg/watches/{watch_id}/{event}`
- `bsg/alerts/{watch_id}`
- `bsg/desk/requests/{id}`, `bsg/desk/replies`
- `bsg/desk/progress/{watch_id}`, `bsg/desk/notes/{watch_id}`,
  `bsg/desk/results`, `bsg/desk/errors`
- `bsg/desk/actions`, `bsg/desk/issuer-status/{issuer}`

## Environment (measured in Gate 0 on 2026-11-04)

- SAM v2 Enterprise, Go edition, 2.493.0 (chart 2.2.30), release
  `agent-mesh` in `sam-solace-lab`. Resources are applied
  declaratively with `sam config apply` (no `sam run` in v2).
- Broker `solace-1` runs in Docker Compose on the host
  (`event-mesh-deployment`), not in the cluster. SAM uses VPN `sam`
  via `ws://host.docker.internal:8008`. The demo was drafted for the
  same VPN over MQTT `host.docker.internal:1883` -- which Gate 0
  showed to be the `default` VPN, not `sam`. See "Open decisions".
- Models: `general` for the desk assistant, `fast` for all workflow
  agents (latency budget below 60 s from alert to note).
- Observability: SAM emits no OTel spans; traces come from the
  broker, and telemetry is configured on both the `default` and the
  `sam` VPN. Token usage per user comes from the `tasks` table of
  the WebUI database, which is what the Grafana datasource
  `sam-platform-db` points at. The existing dashboards have no
  filter variables, hence an own dashboard.

## Decisions and assumptions

Decided with the owner on 2026-11-04:

- Branch node: stop and report if 2.493.0 has none. It has one
  (`type: switch`), so this did not trigger.
- Tool nodes: the version does have them, which removed the premise
  of the original decision. Settled after Gate 0: `enrich` and
  `publish` are `type: tool` nodes on the `bsg-desk-tools`
  connector, so the deterministic steps run with no model in them at
  all, and the agent `bsg-alert-runner` is gone.
- VPN: the demo's feed stays on the `default` VPN of `solace-1`,
  which is the one MQTT 1883 serves, and the SAM entrypoint reads it
  there. The broker is not changed. The cost of that is
  `SAM_STATUS_TOPICS`: SAM's own A2A status events live on the `sam`
  VPN, which has no MQTT listener, so the UI cannot read them and
  the agent nodes between `enrich` and `publish` stay inferred.
- Event-triggered runs are attributed to `power_user@solace.lab`
  (`defaultUserIdentity`). Show the runs in SAM Activities as
  `power_user`. The other demos use the same persona, so the demo
  dashboard filters on the `bsg-` names and the time range as well.
- Documentation in English; UI and desk notes in German.

Assumptions:

- One alert per watch: a watch fires at most once (`max_alerts`
  1) and at most once per product, and the alert lists every
  product of the filter that breaches at that moment. Without this,
  two Alpha DAX turbos would start two workflow runs.
  `scenario reset` re-arms all watches.
- `drift_vs_ref_pct` is the absolute difference between the
  reference level an issuer quotes against and the live reference.
- `enrich_alert` resamples quotes to 5 s per product (about 1,000
  rows for three issuers and one class over 15 minutes) to keep
  the artifacts small.
- The market context verdict uses a fixed rule, two of: the
  underlying's reference moved more than 1 % in the last 60 s, at
  least one high-impact news item in the last 5 minutes, both peer
  issuers above the alert's threshold. Every part of it is a
  comparison of two numbers the enrichment hands over, so both
  branches are reproducible and no model does date arithmetic.
- The figure every comparison rests on is
  `mean_spread_pct_since_alert`: the mean spread over exactly the
  seconds the alert's condition has held. The 60 s mean dilutes a
  10 s anomaly with 50 s of normal quotes, and the 15 minute window
  can still hold the previous run of the same scenario -- so neither
  of those separates an issuer specific anomaly from a market wide
  one.
- The UI draws its own spread chart from the watcher next to the
  agent's chart artifact name; showing the agent's PNG needs an
  authenticated artifact URL (open point).
- Workflow node progress: enrich and publish emit progress events;
  the agent nodes in between are shown as inferred unless SAM's own
  status topics are wired in (`SAM_STATUS_TOPICS`).

## Gate 0 (ran on the lab on 2026-11-04 -- result)

Everything below was measured against the running lab, not assumed.
Sources for the schema items: `sam config schema show workflow`, the
offline documentation (`sam docs`) and the CLI's own authoring
reference (`sam ai-assistance skill install`).

### 1. Cluster and versions -- OK

Context `rancher-desktop`; release `agent-mesh` revision 2 in
`sam-solace-lab`, chart `solace-agent-mesh-2.2.30`, app version
2.493.0; images `solace-agent-mesh:2.493.0` and
`solace-agent-mesh-str:1.76.4`; `sam` CLI 2.493.0. `solace-1` is up;
`solace-2` is `Exited (137)` and this demo does not need it.

### 2. Workflow schema of 2.493.0

- Branch node EXISTS: `type: switch`, with
  `cases: [{condition, node}]` and `default:` (`when` is an alias for
  `condition`, `then` for `node`). Every switch target must list the
  switch node in its `depends_on`, and converging after the branch
  uses the `coalesce` operator. The stop rule of decision 1 therefore
  does not trigger.
- Tool node EXISTS: `type: tool` with `tool_name:`, or
  `connector: <name>` plus `tool: <base name>` for a connector from
  the platform store. This is the premise of decision 2 -- see
  "Open decisions".
- Artifact hand-over: a tool node's output is the tool's structured
  data plus `created_artifact` (the name pinned to the version it
  wrote, e.g. `quotes.csv:1`), `created_artifact_name` and
  `created_artifact_version` -- but only when the call saved exactly
  one artifact. `enrich_alert` saves several, so it has to name its
  data sets in its own structured data, which it does.
- Run id: `{{workflow.run_id}}` and `{{workflow.task_id}}` resolve in
  any node.
- Correction to the drafts: node-level schemas are
  `output_schema_override` and `input_schema_override`. A node
  written with `output_schema:` declares nothing, and every
  `{{node.output.<field>}}` reference then degrades silently -- the
  switch case never matches and falls through to `default`, and
  `output_mapping` returns the literal `{{...}}` text. Unlike
  2.348.22, the node instruction must now also name the keys.

### 3. MCP tool results and artifacts

An MCP response becomes an artifact only above
`mcp_tool_response_save_threshold_bytes` (default 2048), and
`extract_fields` (JMESPath, read back under
`{{node.output.extracted_fields.<key>}}`) rides along with saved
responses only. `tool_config`, and therefore `extract_fields`, is not
available on a connector-backed MCP tool; that needs a `tools:` entry
with `tool_type: mcp` in the workflow itself. The demo does not need
it: `enrich_alert` returns its data set names directly.

### 4. Entrypoint to workflow

An event-mesh rule targets a workflow with `targetWorkflowName`, and
entrypoints resolve the friendly `name:` to the generated
`workflow_<id>` card, so the runtime-name workaround should be
unnecessary (`ENTRYPOINT_WORKFLOW_TARGET=name`, to be confirmed on
the first run). A workflow rule ignores `promptTemplate` and needs
`inputExpression` instead; without it the workflow receives empty
input and the rule still saves and deploys. With an `input_schema`, a
JSON object payload arrives as addressable fields
(`workflow.input.<field>`), which beats the `{"text": ...}` path the
draft assumes -- but the schema must then declare every field the
alert carries and must not also accept `text`, or the payload falls
back to the text form.

### 5. Network, Kyverno, DNS

- Workflows run in the `awe` pod, not `str` as this list previously
  said. From `awe`, `host.docker.internal` resolves to 192.168.5.2
  and TCP 1883, 8008 and 8080 are open. Cross-namespace DNS works and
  `sam-solace-lab` has no NetworkPolicy, so
  `bsg-tools.bsg-demo.svc:8765` will be reachable.
- Kyverno accepts everything in `k8s/`: a server-side dry run of
  `kubectl apply -k k8s` passed for all nine objects, and the policy
  `sync-registry-pull-secret` placed `registry-pull-secret` into the
  namespace on its own. The probe namespace was removed again.
- `registry.solace.lab` answers and `~/.docker/config.json` holds an
  entry for it.
- DNS for `bsg-desk.solace.lab` is MISSING: it does not resolve and
  `/etc/hosts` has no entry for it. Adding one needs sudo; until then
  the demo runs through `make port-forward`. While editing that file:
  its line 16 is malformed -- the `openmetadata.solace.lab` entry and
  the `db-designer` entry sit on one line without a line break.
- BLOCKER: MQTT 1883 belongs to the `default` VPN, not to `sam`. See
  "Open decisions".

### 6. Status topics and the dashboard

- The lab's A2A namespace is `sam-solace-lab`, so the status topics
  are `sam-solace-lab/a2a/v1/gateway/status/<gatewayID>/<taskID>` and
  `sam-solace-lab/a2a/v1/agent/status/<agent>/<subTaskID>`. They live
  on VPN `sam`, which has no MQTT listener (item 5), so
  `SAM_STATUS_TOPICS` can only be filled if option A1 below is taken.
  No workflow run existed yet to sniff.
- The `tasks` table is in the WebUI database `sam-solace-lab_webui`,
  which is what the Grafana datasource `sam-platform-db` points at
  (the datasource `SAM Platform Config DB` is the other one, the
  platform database). Columns available for the dashboard:
  `handler_type`, `handler_name`, `agent_name`, `parent_task_id`,
  `total_input_tokens`, `total_output_tokens`,
  `total_cached_input_tokens`, `token_usage_details`, `start_time`
  and `end_time` (epoch milliseconds), `status`, `error_message`,
  `user_id`, `trigger_kind`, `trigger_source`, `entrypoint_name`.
- The WebUI database is EMPTY after the 2.493.0 upgrade (`tasks`,
  `task_events`, `sessions` and the rest all at zero rows), so the
  chargeback panels of the other demo dashboards stay blank until new
  tasks run. On the platform only `Orchestrator`, `Activity Monitor`
  and the `developer-mcp` gateway are registered.
- Model aliases `fast`, `general` and `workflow` (claude-sonnet-5)
  exist. There is no model of type `decision`, so decision nodes are
  unusable -- `switch` is the branch.

### 7. Needs the owner

`sam auth login` is a browser OIDC flow against `auth.solace.lab`, so
`make mesh-up` cannot run unattended. The CLI caches the token per
`target.name`, which is `solace-lab` here: a login that lands under a
different cache key (`sam auth login sam.solace.lab`) does not help,
and the token lasts an hour.

## What the first runs added to Gate 0

Three things only a run on the cluster could settle, each of which had
cost a deploy cycle:

1. **`sam config apply` never triggers MCP tool discovery.** A
   connector it creates keeps an empty tool list, and the workflow
   create is refused with "connector ... has no stored tool list".
   Discovery does happen per agent registration -- the connector
   record shows `toolCount: 6` under `agentRegistrations` -- but the
   workflow check reads the connector itself. The fix is an explicit
   `manifest:` on the connector, which also pins the tools' schemas.
   The field is a `textarea` in the schema but the runtime wants a
   list: as a `|` block it fails with "'manifest' must be a list of
   tool entries, got string".
2. **An MCP response over 2048 bytes is stored as an artifact** and
   the node's output becomes a digest, at which point no field of the
   response resolves. `enrich_alert` returned 2741 bytes and the
   analyst node failed with "field ... not found in node output; that
   value has 9 fields". The tool now returns a lean summary (1241
   bytes) and hides the data set descriptions behind a `detail` flag
   that only the smoke test sets.
3. **Structured output needs a model return type.** The MCP SDK emits
   `structured_content`, and an `outputSchema` in `tools/list`, only
   for a tool whose return type is a Pydantic model. With a plain
   `dict` the node output is the bare envelope -- `mcp_tool_output`,
   `message_to_llm`, `status` -- which is the "that value has 3
   fields" failure. With a model, the connector reference's
   `{{<node>.output.mcp_structured_content.<field>}}` is exactly
   right.

## Open decisions (Gate 0)

### A. Which VPN carries the demo feed

Measured on `solace-1` over SEMP: VPN `default` has
`serviceMqttPlainTextEnabled: true` on port 1883, while VPN `sam` has
MQTT plain text, TLS, WebSocket and WebSocket-TLS all disabled. MQTT
selects the VPN by port, so a client on
`host.docker.internal:1883` lands on `default` and never on `sam`.
SAM's own eleven clients sit on VPN `sam` over SMF and web transport
(8008), where the VPN comes from the handshake rather than the port.
As drafted, the feed and the entrypoint would sit on two VPNs and
never see each other.

- Option A1 (recommended): move MQTT plain text 1883 from VPN
  `default` to VPN `sam`. Nothing uses MQTT on `default` (zero MQTT
  sessions, only the `trace` client), nothing in the repository
  refers to 1883 except this demo and the event-mesh README, and
  1883 is already published by docker-compose. That is one Terraform
  change in `event-mesh-deployment` plus a live SEMP swap (disable on
  `default` first, then enable on `sam`): no container recreate, no
  change in `app/`, and the demo matches its own design.
- Option A2: leave the broker untouched, run the feed on VPN
  `default`, and point the event-mesh entrypoint and connector at
  `default` as well -- SMF carries the VPN name, so that is config
  only. No infrastructure change at all, but the demo's events no
  longer share a VPN with SAM's A2A traffic, `SAM_STATUS_TOPICS`
  stays empty, and the `bsg/` topics become visible to the Event
  Management Agent on the `default` VPN.

Not recommended: a second MQTT port for VPN `sam`. That needs a new
docker-compose port mapping, so `solace-1` has to be recreated -- and
it keeps no volume, its configuration lives in the container's
writable layer.

### B. Tool nodes instead of the alert runner

Decision 2 was taken on the assumption that 2.493.0 has no tool node.
It has one. Recommendation: make `enrich` and `publish` `type: tool`
nodes against the `bsg-desk-tools` connector and drop the agent
`bsg-alert-runner`, so the deterministic steps run with no LLM in the
loop at all -- faster, and a stronger story on stage. The agent
remains in the git history if the connector path turns out unusable.

Either way one ordering constraint holds: a platform MCP connector
only stores its tool list when it is saved while its MCP server is
reachable, and a workflow whose node names a tool outside that list is
refused. So `k8s-up` has to run before `mesh-up`, which `install.sh`
already does, or the connector needs an inline `manifest`.

## Setup

```bash
cp .env.example .env            # credentials of the default VPN
pip install -r app/requirements-dev.txt
make test                       # unit tests
make k8s-up                     # build, push, deploy bsg-demo
make port-forward               # in a second shell
make smoke                      # deterministic path, no SAM
sam auth login solace-lab       # browser; the CLI cache expires daily
make mesh-up                    # connector, agents, workflow, entrypoint
```

`make mesh-up` refuses to run before `make k8s-up`: a platform MCP
connector only stores its tool list while its server is reachable, and
on 2.493.0 a workflow tool node naming a tool outside that list is
refused at save and at deploy.

Local run without a cluster (any MQTT broker on 1883):

```bash
cd app
MQTT_HOST=127.0.0.1 python -m bsgdemo.watcher &
MQTT_HOST=127.0.0.1 python -m bsgdemo.publisher &
MQTT_HOST=127.0.0.1 WATCHER_URL=http://127.0.0.1:8080 \
  MCP_PORT=8765 python -m bsgdemo.tools_server &
MQTT_HOST=127.0.0.1 WATCHER_URL=http://127.0.0.1:8080 \
  ENTRY_MODE=direct PORT=8090 python -m bsgdemo.ui.server
```

## Removal

`make uninstall` deletes the SAM resources named `bsg-*`
(entrypoint, workflow, agents, connector), the dashboard ConfigMap
and the namespace `bsg-demo`. Nothing else is touched; it never
uses `sam config apply --prune`.

## Open points

- An `/etc/hosts` entry for `bsg-desk.solace.lab` (needs sudo).
  Until then the UI is reachable through `make port-forward` on
  `http://localhost:8090`.
- A rehearsal of the whole show through the UI, rather than through
  the MQTT harness that drove the runs above.
- Cancelling running workflow runs in `make demo-reset` (platform
  API endpoint unknown); today runs end within the 90 s timeout.
- Showing the agent's chart artifact in the UI. The workflow reports
  its name (`spread_<watch_id>.png`) and the UI shows that, but
  rendering the PNG needs an authenticated artifact URL.
- Screenshots of Grafana and SAM Activities for the final report.
- The agent nodes between the two tool nodes stay inferred in the UI,
  because SAM's A2A status events are on the `sam` VPN, which has no
  MQTT listener (decision A).
