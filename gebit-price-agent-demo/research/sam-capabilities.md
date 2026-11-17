# SAM 2.493.0 capabilities for the EuroCIS "Preis- und Aktionsagent mit Freigabe" showcase

Track: Solace Agent Mesh 2.493.0 (Go stack, chart 2.2.30) on the lab, verified
against the offline docs, the CLI schema, the CLI's own authoring skill suite,
the memory notes, the BSG demo and live (read-only) cluster/broker/DB state on
2026-11-10.

Legend: **VERIFIED** = seen in a source (file:line, command output, DB row,
log line). **ASSUMPTION** = inferred, not run on this lab. **CONTRADICTION** =
two official sources disagree.

Abbreviations: `DOCS` = `/private/tmp/.../scratchpad/samdocs/`,
`SKILL` = `/private/tmp/.../scratchpad/research/samskills/` (written by
`sam ai-assistance skill install --to <dir>`, version 2.493.0 - the CLI's
authoritative authoring guide), `BSG` = `bsg-trading-desk-demo/` in the repo.

---

## 0. Executive answer (one screen)

1. **Event -> workflow works on 2.493.0 with the friendly name.** BSG's rendered
   entrypoint uses `targetWorkflowName: bsg-alert-triage` +
   `inputExpression: "input.payload:"` and ran green on both branches
   (VERIFIED: `BSG/mesh/.rendered/entrypoints/bsg-desk-events.yaml:47-48`,
   commit 2757f11, 31 event-triggered tasks in the WebUI DB `tasks` table, all
   `trigger_kind=event`, `user_id=power_user@solace.lab`). The 2.225/2.348
   runtime-name workaround is no longer needed.
2. **Latency floor**: broker publish -> workflow start ~20 ms; a deterministic
   MCP tool node 0.1-1.4 s; a fast-tier (Haiku 4.5) single-LLM-call agent node
   4.9-6.0 s; agent nodes that wander into tool calls 8-12 s (VERIFIED from
   `task_events`/`tasks`, see section 7). A per-scan workflow whose
   "nothing interesting" path is tool node + switch costs **0 tokens and
   < 1.5 s**.
3. **There is no wait/await-event node.** Node types are exactly agent, tool,
   switch, map, loop, workflow, decision (VERIFIED `sam config schema show
   workflow`). The recommended pattern is **correlation outside SAM + one
   workflow per business event** (PositionAdded -> insight; PaymentProcessStarted
   -> prepare voucher; PurchaseTransactionClosed/Cancelled -> issue/discard).
   A `loop` + `delay` + polling tool node can technically "wait" inside one
   run, but it keeps runs open; use only for showmanship.
4. **Notifications are NOT usable on this lab.** `notify_user` needs the
   notification service, which is gated by `SAM_FEATURE_NOTIFY_SERVICE`
   ("off by default; enabled only on rc") and is not running: no `notify`
   component in the gwe startup log, no `q/notify/...` queue on VPN `sam`, no
   `notify_goose_version` migration, frontend flag `notify_service` default
   false (VERIFIED, section 3). `notify_user` also has no link/action field and
   `notification_tools` is not a platform toolset ID (cannot be attached to a
   platform agent).
5. **SAM's own human-in-the-loop does not work from event-triggered runs.**
   `ask_user_question` and tool approval (`hil:`) need an entrypoint with
   `interactive_user_input=true` (WebUI, Slack, Teams, WhatsApp). Event mesh,
   webhook and MCP set it false: `ask_user_question` errors, tool approval is
   a fail-safe **denial**; `hil:` on workflow tool nodes is parsed but never
   enforced (VERIFIED `DOCS/concepts__a2a-protocol.md:89`,
   `DOCS/reference__built-in-tools.md:171`,
   `SKILL/sam-declarative-config/references/workflow.md:395-403`).
   **Realistic one-click approval = custom tablet UI publishing a decision
   event on the broker that triggers a tool-only SAM workflow** (option a).
6. **Live monitor**: every event-triggered workflow run publishes its whole
   lifecycle on `sam-solace-lab/a2a/v1/gateway/status/<eventMeshGatewayId>/<taskId>`
   on VPN `sam` (workflow/node start+result, LLM calls, tool calls, progress
   text, artifacts; VERIFIED 68 events for one BSG run). A browser monitor on
   VPN `sam` (solclientjs, `ws://<host>:8008`, as the insurance/retail/mfg
   cockpits already do) can render real node progress - which BSG could not,
   because its feed lived on VPN `default`. **Put the booth topics on VPN `sam`.**
7. **Cost**: a fast-tier agent node costs ~14-30k input tokens (13-14k of them
   are the runtime's fixed system prompt + tool schemas even with
   `toolsets: []`) and 0.3-1k output tokens -> roughly USD 0.005-0.025 per node
   on Haiku 4.5. One agent node per "interesting" scan plus one per basket
   keeps a show day well under USD 20 - but the LiteLLM hard cap is USD 50 total.

---

## 1. Event-mesh entrypoint

### 1.1 Schema (VERIFIED `sam config schema show entrypoint --type event_mesh`)

`spec.values`: `broker_url` (tcp/tcps/ws/wss), `broker_vpn`, `broker_username`,
`broker_password` (secret, never inherited), `tls_skip_verify` ("false"/"true"),
`event_rules` (>=1), `systemPurpose` (<=4000, stamped on every task as
`system_purpose`), `responseFormat` (<=4000).

Per rule (`event_rules[]`):

| Field | Notes |
|---|---|
| `name` | unique, letters/digits/`_`/`-` |
| `subscriptions` | `[{topic, qos}]`, `*` / `>` wildcards, qos default 1; XOR `existingQueueName` |
| `existingQueueName` | bind consume-only to a pre-provisioned queue (CLI-only; UI then refuses edit) |
| `messageFormat` | `json` (default), `text`, `xml`, `raw_bytes`, `protobuf`, `structured` |
| `payloadEncoding` | default `utf-8` |
| `targetAgent` XOR `targetWorkflowName` | neither = Orchestrator |
| `promptTemplate` | agent targets only (`{payload}`, `{topic}`, `{payload.a.b}`) |
| `responseFormat` | agent targets only, appended literally |
| `inputExpression` | workflow targets; **required in practice**, else empty input |
| `defaultUserIdentity` / `userIdentityExpression` | RBAC + audit attribution |
| `runAs` | system user when no per-message identity resolves |
| `forwardContext` | map key -> sacexpr against the inbound message, readable in outputs as `user_data.forward_context:<key>` |
| `structuredInvocation` | agent targets only; workflows apply their own schema |
| `acknowledgmentPolicy` | `{mode, timeoutSeconds, onFailure{action, nackOutcome}}` or string shorthand |
| `successOutput` / `errorOutput` | `{enabled, topic, topicType static|dynamic, responseType text|full|structured|error|custom, customExpression}` |
| `artifactProcessing` | extract artifacts from the message |

### 1.2 Topics, rules and protobuf

- One durable queue per rule is provisioned **on the data-plane broker**:
  `<ns>/q/eventmesh/<gatewayID>/<ruleName>` (VERIFIED
  `DOCS/administering__event-driven-mesh.md:78`, and SEMP GET on solace-1:
  `sam-solace-lab/q/eventmesh/01a1a646-.../bsg_alerts` and `.../bsg_desk_requests`
  on VPN `default`, non-exclusive, `maxRedeliveryCount 0` = unlimited).
- **`messageFormat: protobuf` exists, but the schema has no field for a
  descriptor/message type** (VERIFIED: no such field in the schema output).
  ASSUMPTION: without a descriptor the entrypoint cannot turn GEBIT protobuf
  into addressable fields. Recommendation: a thin **GEBIT adapter** (the swap
  point) that decodes the Purchase-Service protobuf events (or receives the
  gRPC event stream), converts to compact JSON and publishes booth topics. The
  simulator publishes the same JSON today; in GEBIT's lab only the adapter's
  input side changes.
- GEBIT proto3-JSON has an `@type` key and money as `{scale, intVal:"867"}`
  (VERIFIED `gebit/events/events_simpleSale/03_PositionAdded.json`). With a
  workflow `input_schema`, a JSON object is read as fields only if every
  top-level key is declared and `text` is not accepted; an undeclared key such
  as `@type` makes it fall back to `{"text": ...}` and, if the schema rejects
  that, **the run fails before any node** (VERIFIED
  `DOCS/building__entrypoints__event-mesh__cli.md:97`). Normalize in the
  adapter (`event_type`, `transaction_id`, `article_id`, `price_eur: 8.67`)
  rather than declaring proto3-JSON shapes in SAM.

Proposed booth topic taxonomy (ASSUMPTION, design proposal):

```text
retail/booth/pos/v1/{storeId}/{posId}/{eventType}/{transactionId}
   eventType: position-added | position-voided | payment-started |
              transaction-closed | transaction-cancelled
retail/booth/proposal/v1/{state}/{proposalId}      state: proposed|decided|applied
retail/booth/masterdata/v1/price-changed/{articleId}   (to "article master data")
retail/booth/esl/v1/{articleId}
retail/booth/voucher/v1/{state}/{transactionId}
retail/booth/sam/v1/{results|errors}               (entrypoint outputs)
```

### 1.3 Target and input (VERIFIED)

- `targetWorkflowName` takes the workflow's config `name:`; entrypoints resolve
  it to the generated `workflow_<uuid_with_underscores>` card
  (`SKILL/.../workflow.md:176-183`). Measured: BSG with
  `ENTRYPOINT_WORKFLOW_TARGET=name` ran green
  (`BSG/.env:3`, `BSG/scripts/install.sh:59-63`, rendered file line 47).
- `promptTemplate` is ignored for workflow targets; `inputExpression:
  "input.payload:"` delivers the payload (`DOCS/...event-mesh.md:120`,
  CLI page line 97). The UI cannot set `inputExpression` - a UI-created
  workflow rule gets empty input (`DOCS/...event-mesh.md:86-88`). Use YAML.
- `input_schema` behaviour: JSON object -> `workflow.input.<field>`, unless the
  schema also accepts `text` and the object fails the schema or carries an
  undeclared field -> `workflow.input.text`. Schema-rejected input fails with
  `Input validation failed: ...` before any node
  (`SKILL/.../design/workflow-design.md:474-480`). BSG declares every alert
  field and no `text` (`BSG/mesh/workflows/bsg-alert-triage.yaml:66-92`).
- VERIFIED from `task_events`: `workflow_execution_start` carries the full
  `workflow_input` object - useful for the monitor to map `taskId` ->
  `transaction_id`.

### 1.4 Identity (VERIFIED)

- `defaultUserIdentity` attributes the task (RBAC, audit, Activities,
  chargeback). BSG uses `power_user@solace.lab`; all 31 tasks carry it.
- `userIdentityExpression` (sacexpr, e.g. `input.payload:approved_by` -
  ASSUMPTION on exact path syntax, doc example is
  `input.user_properties.requester`) wins over `defaultUserIdentity`. If set
  without a default and it resolves to nothing, the event is rejected to
  `errorOutput` (code -32003). A `system:`-prefixed identity in a message is
  rejected (`DOCS/...event-mesh.md:126-132`).
- `runAs`: names a `systemUser` (kind exists, `rbac/system-users/`), else the
  built-in `system:default` which can invoke anything without
  `required_scopes`. Naming a system user removes default roles from the
  picture (`SKILL/.../entrypoint.md:74-128`).
- Lab RBAC (VERIFIED platform DB): default role = `sam_user`
  (`agent:*:invoke, workflow:*:invoke`); `power_user` role adds
  `connector:*:*`, `deployment:_:read`, `tool:_:read`, `agent_builder:*:read`.
  Any identity string therefore can at least invoke workflows and agents.

### 1.5 Acknowledgment (VERIFIED docs + SEMP)

- `on_receive` (default) acks on receipt; `on_completion` holds the ack until
  the target completes (`timeoutSeconds` default 300) and applies
  `onFailure.action` (`nack` default / `ack`) on an RPC error, failed publish,
  timeout or un-submittable event. A **published** failed workflow run is
  acked, never redelivered. `nackOutcome rejected|failed` is "intended" to pick
  drop vs redeliver, but "the runtime currently nacks the same way for both"
  (`SKILL/sam-entrypoints/references/event-mesh-entrypoint.md`, Acknowledgment).
- The provisioned queues have unlimited redelivery (SEMP:
  `maxRedeliveryCount 0`). Memory: 2.225.14 produced 190k redeliveries on a
  mis-targeted rule. **Recommendation for scan events: `on_receive`** (a lost
  insight is harmless, a redelivery storm is not). For approval events,
  `on_completion` with `onFailure: {action: ack}` is defensible, or
  `on_receive` plus an idempotent tool.

### 1.6 Outputs (VERIFIED docs, one CONTRADICTION)

- Success output gets the run result; failed/rejected/cancelled workflow runs
  go to `errorOutput` (code -32603) if enabled, else to success. Enable
  `errorOutput` on every workflow rule (`DOCS/...event-mesh.md:153-190`).
- **CONTRADICTION**: `responseType: structured` for a workflow target "emits
  the workflow result" (`DOCS/building__entrypoints__event-mesh.md:181`,
  `SKILL/sam-entrypoints/references/event-mesh-entrypoint.md`) versus "the
  entrypoint does not populate structured output, so `structured` publishes
  `null`" (`DOCS/building__entrypoints__event-mesh__cli.md:100`). Both agree
  on `responseType: custom` + `customExpression: "input.payload:data[0]"`.
  BSG used `structured` but never depended on it (its UI reads the note the
  `publish` tool node writes). **Use `custom` + `input.payload:data[0]`, or
  better, publish business results from a deterministic tool node.**
- Dynamic topics: `topicType: dynamic` expands `{{text://...}}` blocks;
  `user_data.forward_context:<key>` is "the only way to put an inbound field
  into the reply topic" (SKILL event-mesh ref). Not run on this lab.

```yaml
# per rule (docs-based; dynamic topic not yet run on this lab)
forwardContext:
  txn: "input.payload:transaction_id"
successOutput:
  enabled: true
  topicType: dynamic
  topic: "retail/booth/sam/v1/results/{{text://user_data.forward_context:txn}}"
  responseType: custom
  customExpression: "input.payload:data[0]"
errorOutput:
  enabled: true
  topic: "retail/booth/sam/v1/errors"
  topicType: static
  responseType: error
```

### 1.7 Known bugs / traps on this lab

| Item | Status |
|---|---|
| promptTemplate not rendered for workflow targets (DATAGO-148462) | By design now: use `inputExpression` (docs) |
| Gateway published to `request/<NAME>` instead of `workflow_<id>` (2.225/2.348) | FIXED on 2.493.0 (BSG green with friendly name) |
| Events published before the receiver is up are lost (memory 2.348.22) | Persistent queue exists after first deploy; ASSUMPTION it only bites on first deploy / queue re-create |
| Data-plane connection: `reconnectForever:false, reconnectRetries:60, reconnectDelay:5s` | VERIFIED gwe log 2026-11-04T11:59:16 (`logger_name: eventmesh, broker: dataplane`). After ~5 min broker outage the entrypoint stops retrying -> redeploy entrypoint. Control plane uses `reconnectForever:true`. |
| Event mesh entrypoint runs inside the **gwe** pod | VERIFIED (gwe log "event mesh adapter started", handlers 2) |
| Non-ASCII mangled at a solclientjs consumer | Memory; decode the binary attachment as UTF-8 in the UI, or keep agent text ASCII |
| Restart race gwe+awe -> empty card registry | Memory; restart awe alone afterwards |

Full rule example for the showcase is in section 9.

---

## 2. Workflows

### 2.1 Node types (VERIFIED `sam config schema show workflow [--type X]`)

Common: `id`, `type`, `depends_on`, `when`, `timeout`, `input`, `retry_strategy`.

| Type | Specific fields | Notes |
|---|---|---|
| `agent` | `agent_name`, `instruction`, `input_schema_override`, `output_schema_override` | plain `output_schema:` on a node declares NOTHING (memory, BSG) |
| `tool` | `tool_name` or `connector` + `tool` | no LLM; **never retried**; `hil:` not enforced |
| `switch` | `cases: [{condition, node}]` (`when`/`then` aliases), `default` | targets must list the switch in `depends_on`; converge with `coalesce` |
| `map` | `items`, `node`, `max_items` (default 100), `concurrency_limit` | body reads `{{_map_item}}`, `{{_map_index}}` |
| `loop` | `node`, `condition` (required), `max_iterations` (default 100), `delay` | body runs at least once; `{{_loop_iteration}}` |
| `workflow` | `workflow_name`, `instruction` | nested; child has its own `run_id` |
| `decision` | `questions`, `route_on`, `routes`, `min_confidence`, `escalate`, ... | needs a model with `modelType: decision`; the lab has none (VERIFIED `model_configurations.model_type` all `chat`) -> unusable |

Workflow level (`spec.appConfig`): `input_schema` (enforced), `output_schema`
(published, NOT checked), `nodes`, `output_mapping` (required), `skills`
(needed for the card), `tools`, `connectors`, `toolsets`, `workflow_timeout`,
`default_node_timeout`, `fail_fast` (default true), `max_call_depth`,
`retry_strategy`, `on_exit` (`always`, `on_success`, `on_failure`,
`on_cancel`), `decision`. Body MUST sit under `spec.appConfig`; keys beside it
are silently dropped (`SKILL/.../workflow.md:11-28`).

Undocumented hint: the `workflow_node_execution_start` signal carries fields
`wait_for`, `join_strategy`, `join_n`, `parallel_group_id` (VERIFIED in
`task_events` payload) - not in the CLI schema; do not rely on them.

### 2.2 Data flow rules that bite (VERIFIED SKILL `sam-author-agent/references/data-flow.md`)

- `{{workflow.input.x}}`, `{{node.output}}`, `{{node.output.f}}`,
  `{{workflow.run_id}}`, `{{workflow.task_id}}`.
- An agent node guarantees only fields declared in `output_schema_override`
  AND named in the instruction (2.493.0 rule; inverted vs 2.348.22).
- Missing field on a node that ran = hard node error ("that value has N
  fields"). In `when:`/switch/loop conditions an unresolved reference = not
  matched (switch falls to `default`, loop stops `condition_unresolved`). In
  `output_mapping` it stays as literal `{{...}}` in a "successful" run.
- Helpers are keys, not functions: `coalesce: [...]`, `concat: [...]`. No
  arithmetic, no regex, no projection. `"{{coalesce(a,b)}}"` silently resolves
  to nothing.
- Node input is handed to the agent as a JSON file part and **inlined into the
  prompt when small** ("The full content is inlined below ... no tool call is
  needed", VERIFIED `task_events` for BSG nodes: 1941 and 2044 bytes inlined).

### 2.3 Timeouts, fail_fast, retry (VERIFIED `SKILL/.../design/workflow-design.md:540-663`)

- Timeout priority: node `timeout` > `default_node_timeout` > 5 min built-in.
  `workflow_timeout` caps the run. BSG: `workflow_timeout: "90s"`,
  `default_node_timeout: "40s"`, tool nodes `"20s"`.
- `retry_strategy: {limit, retry_policy: OnFailure|OnError|Always, backoff:
  {duration, factor, max_duration}}` on agent/workflow/switch/loop/map nodes.
  Written as `retry:` it is silently ignored. **Tool nodes never retry**
  (`:559`); tools inside a retried map/loop are re-invoked -> make tools
  idempotent.
- `fail_fast: false` keeps other branches running; then guard
  `output_mapping` with `coalesce` fallbacks.

### 2.4 Cheap/fast when nothing interesting happens

Pattern (switch + no-op end), proven shape from BSG (switch on a tool-node
field works when the field is declared by the MCP tool's `outputSchema`):

```yaml
nodes:
  - id: gate                       # deterministic, no LLM, ~0.1-1.4 s
    type: tool
    connector: booth-tools
    tool: evaluate_scan
    timeout: "10s"
    input:
      transaction_id: "{{workflow.input.transaction_id}}"
      article_id: "{{workflow.input.article_id}}"
      price_eur: "{{workflow.input.price_eur}}"
  - id: route
    type: switch
    depends_on: [gate]
    cases:
      - condition: "'{{gate.output.mcp_structured_content.verdict}}' == 'propose'"
        node: propose
    default: skip                   # unresolved field also lands here
  - id: skip                        # visible "no action" node, ~100 ms
    type: tool
    connector: booth-tools
    tool: record_scan
    depends_on: [route]
    input:
      transaction_id: "{{workflow.input.transaction_id}}"
      verdict: "{{gate.output.mcp_structured_content.verdict}}"
```

Measured cost of such a path: 0 LLM tokens; the BSG `enrich` tool node took
121 ms in the latest run (`task_events` 18:18:37.272 -> .393), 0.3-1.4 s
across runs (`BSG/README.md:45`). The Activities flow graph draws skipped
nodes dimmed and labelled "skipped" (`DOCS/using-agent-mesh__monitoring-activity.md`),
which is a nice "the AI looked and decided not to act" visual.

`when:` on a node is the alternative gate (skips the node); unresolved fields
in `when:` also mean "skip".

### 2.5 Can a workflow WAIT for a later external event?

- **No dedicated wait/receive/await node** (VERIFIED schema: 7 node types).
- **Workflow HIL pause/resume** exists in the code base but is gated: the
  shipped `/etc/sam/configs/gwe/platform.yaml:31-46` says the notification
  service is "Required for workflow HIL pause/resume, which routes its input
  prompt solely through this service", gated by `SAM_FEATURE_NOTIFY_SERVICE`
  "(off by default; enabled only on rc)". Undocumented in the 129 offline doc
  pages, flag off on the lab -> **not usable** (VERIFIED config text; feature
  itself not seen).
- **Technically possible: loop + delay + polling tool node**
  (`SKILL/.../design/workflow-design.md:261-293`, "Use when: ... polling"):

```yaml
  - id: wait_close
    type: loop
    depends_on: [propose]
    node: poll_basket
    condition: "'{{poll_basket.output.mcp_structured_content.state}}' == 'open'"
    max_iterations: 60
    delay: "2s"
  - id: poll_basket
    type: tool
    connector: booth-tools
    tool: get_basket_state
    input:
      transaction_id: "{{workflow.input.transaction_id}}"
```

  No tokens, but the run stays open for the whole basket (needs a large
  `workflow_timeout`, with `on_completion` it also holds the broker ack), an
  unresolved field stops the loop early, and concurrency/awe resource limits
  are unknown (ASSUMPTION). Acceptable only as an optional visual for one POS.
- **Recommended pattern (event-driven, no open runs)**:
  - The adapter/simulator (or the booth MCP tool server) is the **basket state
    store** keyed by `purchaseTransactionId`: positions, shown proposals,
    pending voucher, status open/closed/cancelled.
  - `scan-insight` workflow per `position-added` event: provisional insight /
    live single-article promotion (GEBIT: positions are final only after
    `PurchaseTransactionClosed`).
  - `basket-voucher` workflow per `payment-started`
    (`PaymentProcessStarted` arrives seconds before Closed): one agent node
    drafts the next-visit voucher, a tool node **stages** it as pending. This
    hides the ~5-6 s LLM time behind the payment.
  - `basket-close` workflow per `transaction-closed` / `transaction-cancelled`:
    tool-only switch: issue the staged voucher on Closed (receipt is final),
    discard it on Cancelled. Sub-second.
  - Correlation key = `transaction_id` in every payload; the monitor joins on
    it (and on SAM `taskId` via `workflow_execution_start.workflow_input`).

---

## 3. Notifications (`notify_user`)

VERIFIED from docs:

- `notify_user` (group `notification_tools`, "YAML-only" tool, not in the
  toolset picker) - params `message` (req), `title`, `recipient_user_id`
  (default current user; other users "may require additional permissions"),
  `channels` (e.g. `["web","webhook"]`; default all of the recipient's
  configured channels). Fire-and-forget, returns `request_id`
  (`DOCS/reference__built-in-tools.md:40, 834-847`).
- Channels: web inbox, webhook, Slack connector, Slack/Teams entrypoint;
  recipients turn channels on themselves in the Notifications inbox UI
  (`DOCS/reference__env-vars.md:150`; platform.yaml comment "Recipient channels
  are user-managed via the Notifications inbox/preferences UI").
- Scopes: `notify:_:send` (own inbox, documented as "default user grant"),
  `notify:_:send_others`, `notify:_:read_others`
  (`DOCS/reference__rbac-reference.md:62-63`); a `tool:*:*` wildcard does not
  cover it (`DOCS/administering__enabling-rbac.md:32`). On the lab only
  `sam_manager` holds `notify:*:*`; `sam_user`/`power_user` do not (VERIFIED
  `rbac_role_scopes`).
- **No link/action/button field** on `notify_user` (VERIFIED parameter table).
  A URL could only be text inside `message` (ASSUMPTION whether the inbox
  renders it clickable).

VERIFIED on the lab: **not deployed/active**.

- gwe initialised 7 components (metrics_flush, extensions, control, platform,
  gateway, proxy, leader) - no notify service (gwe log 2026-11-04T11:58:12).
- Migrations logged: `platform_goose_version` 119, `evidence_goose_version` 26,
  `gateway_goose_version` 66 - no `notify_goose_version`.
- Broker VPN `sam` queues include `q/schedule/request`, `q/gdk/*`,
  `q/platform/*`, `q/eval/trigger`, `q/str/*` - **no `q/notify/*`** (SEMP GET).
- No `SAM_FEATURE_*` in any pod env; `helm get values -a` shows
  `environmentVariables: {NO_PROXY, SAM_OBSERVABILITY_ENABLED}` only.
- WebUI bundle gates the inbox behind OpenFeature flag `notify_service`
  (default `false`) and calls `/api/v1/notify/{inbox,channels,preferences/*}`.
- Platform toolset IDs (`SKILL/.../toolset.md:19-29`) do not include
  `notification_tools`, and the agent kind forbids `tools` in
  `additionalConfigurations` -> a platform-deployed agent cannot get
  `notify_user` even with the service on (ASSUMPTION, doc-based).

Conclusion: do not build the showcase on SAM notifications. Enabling would mean
`environmentVariables.SAM_FEATURE_NOTIFY_SERVICE: "true"` in the chart values
(cluster change, owner decision) for a feature the shipped config calls
rc-only. The booth's "notification" is the monitor/tablet UI fed by broker
topics.

---

## 4. Human in the loop

### 4.1 What SAM offers (VERIFIED docs)

| Mechanism | Works where | Fails where |
|---|---|---|
| `ask_user_question` (`hil_tools`) - 1-4 questions, header <=12 chars, 0-4 options, 45 min default timeout, returns answered/cancelled/timed_out | interactive agents in WebUI/Slack/Teams/WhatsApp chats | "interactive agents only; do not attach to autonomous or workflow agents ... Returns an error on channels that cannot render an interactive prompt (for example, an Event Mesh entrypoint)" (`DOCS/reference__built-in-tools.md:159-171`); "Fails if every question is text-only" |
| Tool approval `hil: {require_approval, require_approval_when, approval_message, show_args, timeout(45m)}` on a tool/connector | agent tool calls with an interactive entrypoint (approval card in the WebUI) | event mesh, webhook, MCP: `interactive_user_input=false` -> "a fail-safe denial" (`DOCS/concepts__a2a-protocol.md:89`); scheduled tasks reject `input-required` immediately (`DOCS/using-agent-mesh__scheduled-tasks.md:96`); workflow `type: tool` nodes dispatch without asking (`SKILL/.../workflow.md:395-403`) |
| CLI `sam task send --hil-approve/--hil-deny/--hil-respond/--hil-auto-approve` | CLI-started tasks | not a booth UX (`DOCS/reference__cli.md:62-66`) |
| A2A `input-required` state, `user_input_request`/`user_input_response` signals | interactive gateways | same as above |
| Approval/decision node | none exists; `decision` node is a classifier model, not a human step | - |

No repo demo has ever exercised HIL, scheduling or notify (VERIFIED grep:
no `hil_tools`, `ask_user_question`, `require_approval`, `schedule_task`,
`notify_user` anywhere). Memory: vendor ticket 2 lists "ask_user_question
cannot do a single question" (2.225.14) - re-test before relying on it.

### 4.2 Options for one-click approval from a tablet

| Option | Flow | Latency | Robustness | Verdict |
|---|---|---|---|---|
| **(a) Custom tablet UI -> decision event -> SAM workflow** | tablet (solclientjs on VPN `sam`) publishes `retail/booth/proposal/v1/decided/{proposalId}` `{decision, approved_by, ...}` -> event rule (identity from `approved_by` or `power_user`) -> tool-only workflow `apply-decision` -> MCP tool publishes `price-changed` + ESL update; simulator applies at next scan | broker ~ms + workflow start ~20 ms + 1-2 tool nodes 0.1-1.4 s each -> **~0.3-2 s** (ASSUMPTION built from measured parts) | No login on the tablet, no LLM in the path, deterministic, idempotent tool, works offline from LLM budget. Same pattern as the insurance cockpit "Approve" (`sam-insurance-ops-demo/cockpit/index.html:589-603`) but there nothing consumed the decision | **Recommended** |
| (b) WebUI chat with an interactive approval agent (`ask_user_question` + optionally `hil:` on `apply_price_change`) | someone opens SAM WebUI on the tablet, Keycloak login, asks "offene Vorschlaege?", agent lists via MCP, renders options, approves | 2 agent turns 5-15 s each + login; cannot be pushed (no notifications) | Not one-click; LLM budget; session handling; untested on lab | Secondary "store manager assistant" demo only |
| (c) Webhook entrypoint | tablet POSTs `https://sam.solace.lab/gw/<slug>/approve` (token or HMAC) -> 202 + taskId -> workflow | dispatch sub-second; **async, result never returned** (`DOCS/building__entrypoints__webhook.md:14`) | Runs as a system user (no per-user identity, Activities only with `activity:*:read`, `:35,78`), token lives in browser JS, a typo'd target still returns 202 | Fallback if the tablet cannot reach broker WS 8008 |
| (d) Tablet calls `POST /api/v1/message:send` (memory) | needs an OIDC access token (1 h) | fast | Token handling on a kiosk device | Not recommended |
| (e) MCP entrypoint (`/gw/dev/`) | OAuth MCP client | n/a | Overkill | No |

Governance talking point for (a): the agent only **proposes**; a deterministic
tool enforces the guardrails (max discount, min margin, validity window) when
publishing the proposal and again when applying it; the approving human is the
identity on the `apply-decision` run in SAM Activities.

---

## 5. Connectors, webhook, MCP rules, scheduling

### 5.1 Event-mesh connector (VERIFIED `DOCS/building__connectors__event-mesh__cli.md`)

- `type: event_mesh`, `subtype: solace`; `broker_url` must be **SMF**
  (`tcp://` / `tcps://`), plus vpn/user/password (never inherited).
- `operations[]`: `tool_name`, `tool_description`, `topic` (with
  `{property}` placeholders), `wait_for_response` (request/reply vs
  fire-and-forget), `payload_format` json|yaml|text, `qos`, `request_expiry_ms`,
  `reply_mode`, `input_schema` with `x-solace-payload-path` and
  `x-solace-context-expression`.
- Gives agents a publish tool without MCP. Binding it to a workflow `tool`
  node: the docs only spell out conditions for OpenAPI and MCP connectors;
  `tool:` "selects one of a multi-tool connector's tools by un-suffixed base
  name". ASSUMPTION it works for event_mesh - verify with `sam config plan`
  before building on it. On this lab SMF from the awe pod would be
  `tcp://host.docker.internal:55557` (port mapping 55557->55555 VERIFIED
  `docker ps`; reachability from awe NOT tested - BSG only tested 1883, 8008,
  8080).
- Recommendation: keep publishing in the booth MCP tool server (as BSG's
  `publish_desk_note`); it already handles idempotency and guardrails.

### 5.2 Webhook entrypoint (VERIFIED schema + docs)

`routePath` (path params `{id}` -> `user_data.path:id`), `method`,
`authMode token|hmac`, `authToken`/`hmacSecret`, `authTokenLocation
bearer|header|query`, `targetType agent|workflow`, `targetWorkflowName`,
`inputExpression` (required, e.g. `"template:Order {{user_data.path:id}}:
{{json://input.payload:}}"`), `runAs`, `maxBodyBytes`. Mounted at
`/gw/<slug>/...` (slug opt-in at creation, immutable). Async 202, sessionless,
system-user identity.

### 5.3 MCP connector rules (VERIFIED memory + BSG + SKILL)

1. `sam config apply` never triggers tool discovery -> give the connector an
   explicit `manifest:` (YAML **list**, not a `|` string; mutually exclusive
   with `tool_name`/`allow_list`/`deny_list`). Regenerate with
   `BSG/scripts/gen_connector_manifest.py`.
2. MCP responses > `mcp_tool_response_save_threshold_bytes` (2048) become an
   artifact; no field resolves ("that value has 9 fields"). Keep
   workflow-facing responses < 2 KB (BSG: 2741 -> 1241 bytes behind a
   `detail` flag). `extract_fields`/`tool_config` only on an inline
   `tools: - tool_type: mcp` entry, not on a connector-backed tool.
3. Structured content only for tools whose return type is a **Pydantic
   model**; then read `{{node.output.mcp_structured_content.<field>}}`; with
   `-> dict` the output is the bare envelope ("that value has 3 fields").
4. MCP server must be reachable before the workflow is applied; deploy k8s
   part first (`BSG/scripts/install.sh:37-42`).
5. Diagnose with the run's STIM (`sam api /api/v1/tasks/<taskId>`) and the awe
   "workflow reference could not be verified" warning.

### 5.4 Scheduled tasks (VERIFIED `DOCS/using-agent-mesh__scheduled-tasks.md`, built-in tools)

- Experimental. Held by the WebUI entrypoint (`schedulerEnabled` true in
  `/api/v1/config`, `q/schedule/request` on VPN `sam`, `scheduled_tasks`
  table empty).
- Types: cron (5-field POSIX, no seconds), interval (**min 60 s**), one-time.
  Target agent or workflow; a workflow with an `input_schema` gets a JSON
  object (form enforces it). Missed fires within 10 min run once; a fire while
  the previous run is still running is **Skipped**; auto-pause after 10
  consecutive failures; default timeout 3600 s.
- Runs under the creator's identity; any `input-required`/`auth-required`
  state fails the run.
- Created per user in the UI ("Schedules"), or by an agent with
  `toolsets: [scheduling_tools]` (`schedule_task(target_name, target_type,
  schedule_type, schedule, message, timezone, timeout_seconds)`). There is no
  `scheduledTask` declarative kind (VERIFIED `sam config schema list`), so it
  is not part of `sam config apply` - install.sh would need the UI or an
  agent call (ASSUMPTION: or an undocumented REST endpoint).
- Showcase use: "Abverkaufs-Check" every 15 min -> workflow
  `slow-mover-review` (tool node computes sell-through vs plan; agent node
  proposes 1-3 markdowns). Fine for a trade show day; no need for seconds.

---

## 6. Live progress for a custom monitor UI

### 6.1 What is on the broker (VERIFIED)

Topic conventions (`DOCS/concepts__a2a-protocol.md:62-75`), namespace
`sam-solace-lab`, all on **VPN `sam`**:

| Topic | Content |
|---|---|
| `sam-solace-lab/a2a/v1/agent/request/<workflow_card>` | the dispatched request (entrypoint -> workflow) |
| `sam-solace-lab/a2a/v1/gateway/status/<gatewayID>/<taskID>` | **all** status-update events of the run, including sub-agent LLM/tool events |
| `sam-solace-lab/a2a/v1/gateway/response/<gatewayID>/<taskID>` | final A2A task (state, `parts[0].data` = workflow output, metadata incl. `duration_seconds`) |
| `sam-solace-lab/a2a/v1/agent/status/<delegatingAgent>/<subTaskID>` | peer delegation status (not used by workflow nodes here) |

Measured timeline of one BSG run (`task_events`, task `01a1a7c8-cd2b-...`,
68 events): `request` 18:18:37.241 -> `workflow_execution_start` .246 ->
`workflow_node_execution_start` (node_id `enrich`, node_type `tool`,
tool_name `enrich_alert`) -> `tool_invocation_start` / `tool_result` ->
`workflow_node_execution_result` (status `success`, `output_artifact_ref`) ->
two parallel agent nodes (`parallel_group_id`), each with `llm_invocation`,
`agent_progress_update` (free text such as "I will apply the decision rule
literally..."), `llm_response`, `tool_invocation_start` ... ->
`workflow_execution_result` (`workflow_output`) 18:18:59.286 -> `response`
.287. Signal list (`DOCS/concepts__a2a-protocol.md:101-111`): llm_invocation,
llm_response, thinking_content, agent_progress_update, tool_invocation_start,
tool_result, artifact_creation_progress, artifact_saved,
structured_invocation_request/result, workflow_execution_start/result,
workflow_node_execution_start/result, workflow_map_progress,
user_input_request/response, authentication_required.

Payload shape (VERIFIED):

```json
{"jsonrpc":"2.0","id":"<taskId>","result":{"taskId":"<taskId>","kind":"status-update",
 "status":{"state":"working","message":{"parts":[{"kind":"data","data":{
   "type":"workflow_node_execution_start","node_id":"analyst","node_type":"agent",
   "agent_name":"bsg-quote-analyst","sub_task_id":"...","depends_on":["enrich"],
   "parallel_group_id":"...","tool_name":null}}]}},"final":false}}
```

### 6.2 How BSG approached it

BSG's feed and entrypoint data plane are on VPN `default` because MQTT 1883
belongs to `default`; VPN `sam` has every MQTT listener disabled (memory,
`BSG/README.md:335-368`). The UI is MQTT-only, so `SAM_STATUS_TOPICS` stayed
empty (`BSG/k8s/configmap.yaml:23`) and the agent rows between the two tool
nodes were "inferred"; the tool nodes reported progress themselves via
`report_progress`/`publish_desk_note` (`BSG/RUNBOOK.md:33-42`).

### 6.3 Recommendation for the booth monitor

- Use **one solclientjs session on VPN `sam`** (`ws://<laptop>:8008`,
  `default/default` like the insurance/retail/mfg cockpits:
  `sam-insurance-ops-demo/cockpit/index.html:624-641`). Put the booth's own
  topics on VPN `sam` too, and the entrypoint's data plane on `sam`
  (`broker_url: ws://host.docker.internal:8008`, `broker_vpn: sam`). Then one
  session sees POS events, proposals, decisions **and** real SAM node progress.
  The POS simulator / GEBIT adapter publishes via SMF or WebSocket (Python
  `solace-pubsubplus` or solclientjs), not MQTT.
- Subscribe narrowly (ASSUMPTION that direct subscribers receive these
  guaranteed messages - standard Solace behaviour, not tested here):
  - `sam-solace-lab/a2a/v1/gateway/status/<eventMeshGatewayId>/>`
  - `sam-solace-lab/a2a/v1/gateway/response/<eventMeshGatewayId>/>`
  - `retail/booth/>`
  Do not subscribe to `sam-solace-lab/a2a/v1/>` in a browser: it shows every
  chat in the mesh and the per-task JWT in user properties.
- The gateway ID is the entrypoint's platform UUID (BSG:
  `01a1a646-38f1-7172-bd48-5a77f7ea1c2a`, also the queue name
  `q/gdk/gateway/01a1a646-...` on VPN `sam`); it changes when the entrypoint
  is recreated -> render it into the UI config at install time (like BSG's
  ID resolution via `/api/v1/platform/entrypoints`).
- Map `taskId` -> basket via `workflow_execution_start.workflow_input`.
- Show per node: start/end times, node type, agent/tool name, the
  `agent_progress_update` text ("Ich pruefe Abverkauf und Bestand ...") as the
  "AI thinking" ticker.
- Decode the binary attachment as UTF-8 (`TextDecoder`) to avoid the mangled
  umlauts seen before; or keep agent output ASCII.

---

## 7. Latency and cost

### 7.1 Measured on this lab (VERIFIED WebUI DB `tasks`, `task_events`, 2026-11-04)

| Step | Duration | Source |
|---|---|---|
| alert published (`triggered_at` 18:18:37.224) -> A2A request | 17 ms | task_events |
| request -> `workflow_execution_start` | 5 ms | task_events |
| MCP tool node (enrich) | 0.12 s (0.3-1.4 s across runs) | task_events, BSG README |
| fast agent, 1 LLM call, no tool (`bsg-market-context`) | 4.9 / 5.2 / 5.3 / 5.3 / 6.0 s | tasks (5 runs) |
| fast agent, 2 LLM calls + chart tool (`bsg-quote-analyst`) | 8.7-10.1 s | tasks |
| fast agent that wandered into load_artifact/jmespath (`bsg-desk-communicator`) | 4.3-11.8 s | tasks, task_events (3 tool calls, 4 LLM calls in the 11.8 s run) |
| whole 6-node workflow | 14.2-22.0 s | tasks |
| entrypoint -> `general` agent (Opus 4.8) one turn | 6.7-8.4 s | tasks |

Tokens per node (fast = `openai/claude-haiku-4-5-20251001`, `max_tokens 16384`,
VERIFIED `model_configurations`):

| Node | input | of which cached | output |
|---|---|---|---|
| market-context (toolsets `[]`, 1 call) | 14,446-14,458 | 13,654-13,661 (all cache **writes**) | 529-635 |
| quote-analyst (data_analysis, chart) | 30,080-30,149 | ~28,200 | 783-962 |
| desk-communicator | 14,189-61,448 | up to 58,539 (9,396 writes) | 277-804 |
| desk-assistant on `general` (Opus 4.8) | ~41,500 | ~41,500 (21,239 writes) | 310-346 |

Key observation: **~13.6k tokens are the fixed per-agent overhead** (runtime
system prompt + always-attached artifact/data tool schemas) even with
`toolsets: []`. BSG run totals: ~60k tokens issuer specific, ~92k market wide
(`BSG/README.md:44-48`).

### 7.2 Cost estimate (prices: Haiku 4.5 USD 1 / 5 per MTok input/output, Sonnet 5 USD 2 / 10, Opus 5 and Opus 4.8 USD 5 / 25 - claude-api skill model table cached 2026-11-03; cache write 1.25x / read 0.1x = standard multipliers, ASSUMPTION for the LiteLLM proxy's billing)

- Single-call fast node, cold cache: 13.7k write x 1.25 + 0.8k x 1 + 0.55k
  output x 5 -> **~USD 0.02**; warm cache (runs within 5 min): ~USD 0.005.
- 3-agent BSG run on fast: ~USD 0.05-0.07.
- One Opus 4.8 (`general`) turn: ~USD 0.15 -> never put `general`/`expert`
  in the per-event path.
- Booth day guess (ASSUMPTION): 500 proposals x 1 node + 300 baskets x 1 voucher
  node -> 800 node calls x USD 0.005-0.02 = **USD 4-16/day**, plus rehearsals.
  LiteLLM hard cap USD 50 (memory) is the real limit; get it raised for the
  show.
- SAM's own budget kind (`kind: budget`) exists, but `model_configurations`
  has `price_input/price_output/price_cache_*` = NULL and `token_spend_ledger`
  has 0 rows (VERIFIED) -> SAM budgets cannot meter spend until model prices
  are set.

### 7.3 Tips to stay fast and cheap

1. Deterministic first: one MCP tool node decides "interesting or not"
   (thresholds, cooldown per article, max N proposals/min); the LLM only runs
   when there is something to say. No-op path = 0 tokens.
2. One agent node per user-visible moment (proposal, voucher). Do not chain
   analyst -> communicator; let one fast agent return the structured proposal
   (`headline`, `rationale_de`, `action`, `discount_pct`, ...).
3. Hand the agent pre-computed facts (sell-through %, stock days, margin,
   loyalty tier, active promos) < ~2 KB so the input is inlined, in EUR
   decimals, never `{scale,intVal}`.
4. System prompt: "Call no tool." plus forbid the auto-attached tools by name
   (`load_artifact`, `create_sqlite_db`, `merge_structured_data`,
   `transform_data_with_jmespath`, `artifact_search_and_replace_regex`,
   `append_to_artifact`). The communicator without that rule spent 3 extra
   round trips (~6 s). `toolsetExcludedTools` exists in the agent schema -
   ASSUMPTION whether it can drop the always-attached tools; test.
5. Declare `output_schema_override` keys AND name them in the instruction;
   never tell the node HOW to format (memory: breaks structured invocation).
6. Keep system prompt and tools stable (prompt caching); the per-run time
   stamp goes in the user turn already ("[Current time: ...]").
7. `supportsStreaming: false` for agents behind event mesh
   (`SKILL/.../design/best-practices.md:315`).
8. Fast tier only; `max_tokens` 16384 is fine (output is short).
9. Parallelise independent nodes; tool nodes for every deterministic step
   (publish, apply, issue).
10. ASCII-only agent output or UTF-8-safe UI decoding.

---

## 8. RBAC / identity and what can break

### 8.1 RBAC needed (VERIFIED)

- Invoking a deployed workflow needs `workflow:<dashed-uuid>:invoke` or
  `workflow:*:invoke`; `agent:*:invoke` does NOT cover workflows; a
  `workflow:<name>:invoke` grant does nothing
  (`DOCS/reference__rbac-reference.md:92-107`, `SKILL/.../workflow.md:187-189`).
  Memory: workflow callers also needed `agent:*:invoke` for the agent nodes.
- Lab: default role `sam_user` = `agent:*:invoke, workflow:*:invoke`, so
  `defaultUserIdentity: power_user@solace.lab` (or any identity string)
  can run the booth workflows. A scoped alternative:

```yaml
kind: systemUser
name: booth-pos
spec:
  roleNames: [booth_invoke]
---
kind: rbacRole
name: booth_invoke
spec:
  scopes: ["workflow:*:invoke", "agent:*:invoke"]
```
  and `runAs: booth-pos` on the rules (no `defaultUserIdentity`). Then runs
  are visible in Activities only with `activity:*:read`
  (sam_manager/superadmin) - for the booth keep `power_user@solace.lab` and
  log in as `power_user`, as BSG decided.
- `notify:_:send` would be needed for `notify_user` (moot, service off).

### 8.2 Showcase breakers (checklist)

1. **LiteLLM USD 50 hard cap** (429 `budget_exceeded`) - all agent nodes fail;
   deterministic paths keep working. Rate-limit LLM calls in the gate tool.
2. **Event-mesh data-plane reconnect gives up after ~5 min** of broker outage
   (`reconnectForever:false`, 60 x 5 s, VERIFIED log) - after a broker
   restart, redeploy the entrypoint and check `runtimeStatus`.
3. **Redelivery loops**: eventmesh queues have unlimited redelivery; with
   `on_completion` + `nack`, an un-submittable event cycles. Use `on_receive`
   for scans.
4. **input_schema mismatch** (undeclared `@type` etc.) fails runs before any
   node - normalize in the adapter.
5. **MCP traps** (manifest, 2048 B, Pydantic) - section 5.3.
6. **Unresolved switch field** silently goes to `default` - test both branches.
7. **ask_user_question / hil in event-triggered paths** -> error / denial.
8. **Notification service off** - no SAM inbox.
9. **Decision nodes unusable** (no decision-type model).
10. **sam CLI token lasts 1 h**; `install.sh` needs a browser login
    (`sam auth login solace-lab`); currently expired (VERIFIED
    `sam auth list`, so no platform API GETs were possible for this report).
11. **gwe+awe concurrent restart** -> empty card registry (memory); restart awe
    alone afterwards.
12. **Rancher Desktop sleep/wake** (clock wedge, dead port forwards, stale vz
    pid) - disable sleep on the booth laptop; memory has the recovery steps.
13. **Spool over quota on VPN `sam`** (memory: stale queues blocked every
    publish) - check spool before the show; firehose queues capped at 1 GB.
14. **Fast-tier agents patch their input with artifact tools** (memory) -
    prompt ban.
15. **Non-ASCII mangling** in solclientjs consumers.
16. **Booth network**: tablet/monitor reach `ws://<laptop-ip>:8008`; the
    laptop's 127.0.0.1:8080 is currently a kubectl port-forward (solace-1 SEMP
    reachable only via the LAN IP) - fix port usage before the show.
17. Unknown concurrency limits of the entrypoint and awe for overlapping runs
    (ASSUMPTION: fine at booth volume; load-test 10 parallel scans).

---

## 9. Reference config for the showcase (real 2.493.0 schema, untested)

### 9.1 Entrypoint

```yaml
kind: entrypoint
name: booth-pos-events
description: >-
  EuroCIS booth: POS events from the GEBIT adapter (or the simulator) start
  the price-and-promotion workflows; tablet decisions start apply-decision.
spec:
  type: event_mesh
  deploy: true
  values:
    broker_url: "ws://host.docker.internal:8008"
    broker_vpn: "sam"                      # same VPN as SAM -> monitor sees status topics
    broker_username: "default"
    broker_password: ${BOOTH_BROKER_PASSWORD}
    tls_skip_verify: "false"
    systemPurpose: "EuroCIS booth demo. German, ASCII only, short."
    event_rules:
      - name: pos_position_added
        subscriptions:
          - topic: "retail/booth/pos/v1/*/*/position-added/>"
            qos: 1
        messageFormat: json
        targetWorkflowName: scan-insight
        inputExpression: "input.payload:"
        defaultUserIdentity: power_user@solace.lab
        acknowledgmentPolicy: on_receive
        successOutput: {enabled: false, topic: "retail/booth/sam/v1/results"}
        errorOutput:
          enabled: true
          topic: "retail/booth/sam/v1/errors"
          topicType: static
          responseType: error
      - name: pos_payment_started
        subscriptions:
          - topic: "retail/booth/pos/v1/*/*/payment-started/>"
        messageFormat: json
        targetWorkflowName: basket-voucher
        inputExpression: "input.payload:"
        defaultUserIdentity: power_user@solace.lab
        acknowledgmentPolicy: on_receive
        errorOutput: {enabled: true, topic: "retail/booth/sam/v1/errors", responseType: error}
      - name: pos_transaction_final
        subscriptions:
          - topic: "retail/booth/pos/v1/*/*/transaction-closed/>"
          - topic: "retail/booth/pos/v1/*/*/transaction-cancelled/>"
        messageFormat: json
        targetWorkflowName: basket-close
        inputExpression: "input.payload:"
        defaultUserIdentity: power_user@solace.lab
        acknowledgmentPolicy:
          mode: on_completion
          timeoutSeconds: 30
          onFailure: {action: ack}
        errorOutput: {enabled: true, topic: "retail/booth/sam/v1/errors", responseType: error}
      - name: proposal_decided
        subscriptions:
          - topic: "retail/booth/proposal/v1/decided/>"
        messageFormat: json
        targetWorkflowName: apply-decision
        inputExpression: "input.payload:"
        userIdentityExpression: "input.payload:approved_by"   # ASSUMPTION on path syntax
        defaultUserIdentity: power_user@solace.lab
        acknowledgmentPolicy:
          mode: on_completion
          timeoutSeconds: 30
          onFailure: {action: ack}
        errorOutput: {enabled: true, topic: "retail/booth/sam/v1/errors", responseType: error}
```

### 9.2 Workflow `scan-insight` (one LLM node only when needed)

```yaml
kind: workflow
name: scan-insight
description: >-
  Per scanned article: deterministic check of sell-through, stock, active
  promotions and loyalty; only when something is worth saying, one fast agent
  drafts a markdown or promotion proposal for human approval.
spec:
  appConfig:
    version: "1.0.0"
    workflow_timeout: "30s"
    default_node_timeout: "20s"
    fail_fast: true
    skills:
      - id: scan_insight
        name: Scan insight
        description: Turn one POS scan into an optional price or promotion proposal.
    input_schema:
      type: object
      required: [transaction_id, article_id]
      properties:
        event_type: {type: string}
        store_id: {type: string}
        pos_id: {type: string}
        transaction_id: {type: string}
        position_id: {type: string}
        article_id: {type: string}
        article_number: {type: string}
        description: {type: string}
        item_count: {type: number}
        price_eur: {type: number}
        loyalty_id: {type: [string, "null"]}
        occurred_at: {type: string}
    nodes:
      - id: gate
        type: tool
        connector: booth-tools
        tool: evaluate_scan            # Pydantic return, < 2 KB
        timeout: "10s"
        input:
          transaction_id: "{{workflow.input.transaction_id}}"
          article_id: "{{workflow.input.article_id}}"
          price_eur: "{{workflow.input.price_eur}}"
          loyalty_id: "{{workflow.input.loyalty_id}}"
      - id: route
        type: switch
        depends_on: [gate]
        cases:
          - condition: "'{{gate.output.mcp_structured_content.verdict}}' == 'propose'"
            node: propose
        default: skip
      - id: propose
        type: agent
        agent_name: booth-pricing-agent   # fast tier, toolsets: [], "call no tool"
        depends_on: [route]
        timeout: "15s"
        instruction: >-
          Draft one proposal for this article from the facts. Return exactly
          these keys: action, discount_pct, new_price_eur, headline_de,
          rationale_de, valid_minutes.
        input:
          scan: "{{workflow.input}}"
          facts: "{{gate.output.mcp_structured_content.facts}}"
        output_schema_override:
          type: object
          required: [action, discount_pct, new_price_eur, headline_de, rationale_de, valid_minutes]
          properties:
            action: {type: string, enum: [markdown, promotion, bundle]}
            discount_pct: {type: number}
            new_price_eur: {type: number}
            headline_de: {type: string}
            rationale_de: {type: string}
            valid_minutes: {type: integer}
      - id: publish
        type: tool
        connector: booth-tools
        tool: publish_proposal          # re-checks guardrails, publishes proposal/v1/proposed
        depends_on: [propose]
        input:
          transaction_id: "{{workflow.input.transaction_id}}"
          article_id: "{{workflow.input.article_id}}"
          proposal: "{{propose.output}}"
          workflow_run_id: "{{workflow.run_id}}"
      - id: skip
        type: tool
        connector: booth-tools
        tool: record_scan
        depends_on: [route]
        input:
          transaction_id: "{{workflow.input.transaction_id}}"
          article_id: "{{workflow.input.article_id}}"
    output_mapping:
      verdict: "{{gate.output.mcp_structured_content.verdict}}"
      proposal_id:
        coalesce:
          - "{{publish.output.mcp_structured_content.proposal_id}}"
          - "none"
```

### 9.3 Workflow `apply-decision` (tool-only, sub-second)

```yaml
kind: workflow
name: apply-decision
description: >-
  Applies a human decision from the tablet: on approve, publishes the price
  change for the article master data service and the ESL update; no model.
spec:
  appConfig:
    version: "1.0.0"
    workflow_timeout: "20s"
    skills:
      - id: apply_decision
        name: Apply decision
        description: Apply an approved or rejected proposal.
    input_schema:
      type: object
      required: [proposal_id, decision]
      properties:
        proposal_id: {type: string}
        decision: {type: string, enum: [approve, reject]}
        approved_by: {type: string}
        decided_at: {type: string}
    nodes:
      - id: apply
        type: tool
        connector: booth-tools
        tool: apply_decision            # idempotent; publishes masterdata/v1/price-changed
        timeout: "10s"
        input:
          proposal_id: "{{workflow.input.proposal_id}}"
          decision: "{{workflow.input.decision}}"
          approved_by: "{{workflow.input.approved_by}}"
          workflow_run_id: "{{workflow.run_id}}"
    output_mapping:
      status: "{{apply.output.mcp_structured_content.status}}"
```

`basket-voucher` (tool `basket_summary` -> fast agent `booth-voucher-agent` ->
tool `stage_voucher`) and `basket-close` (tool `finalize_basket` with
`event_type` closed|cancelled; no model) follow the same shapes.

### 9.4 Booth agent (fast, autonomous, no tools)

```yaml
kind: agent
name: booth-pricing-agent
description: >-
  Drafts one markdown or promotion proposal for a scanned article from
  pre-computed facts; a human approves it on the tablet.
spec:
  type: standard
  modelProvider: [fast]
  toolsets: []
  additionalConfigurations:
    supportsStreaming: false
  skills:
    - id: price_proposal
      name: Price proposal
      description: One structured markdown or promotion proposal.
  inputModes: [text]
  outputModes: [text]
  systemPrompt: |
    You operate autonomously behind an event trigger. Do not ask questions.
    Use only the facts you are given; do not recompute them.
    Call no tool. Never call load_artifact, create_sqlite_db,
    merge_structured_data, transform_data_with_jmespath,
    artifact_search_and_replace_regex or append_to_artifact.
    Stay inside facts.max_discount_pct and facts.min_margin_pct.
    German, ASCII only (ae, oe, ue, ss), at most 2 sentences in rationale_de.
```

---

## 10. Sources consulted

- Offline docs: `building__entrypoints__event-mesh.md`,
  `building__entrypoints__event-mesh__cli.md`, `building__entrypoints__webhook.md`,
  `building__workflows__cli.md`, `building__connectors__event-mesh__cli.md`,
  `reference__built-in-tools.md`, `reference__rbac-reference.md`,
  `reference__env-vars.md`, `reference__helm-values.md`, `reference__cli.md`,
  `concepts__a2a-protocol.md`, `administering__event-driven-mesh.md`,
  `administering__enabling-rbac.md`, `using-agent-mesh__scheduled-tasks.md`,
  `using-agent-mesh__monitoring-activity.md`.
- CLI: `sam config schema show entrypoint --type event_mesh`, `... workflow`,
  `... workflow --type {agent,tool,switch,map,loop,workflow,decision}`,
  `... agent`, `sam config schema list`, `sam auth list`.
- CLI skill suite (`sam ai-assistance skill install --to SKILL`):
  `sam-declarative-config/references/{workflow,entrypoint,connector,toolset}.md`,
  `design/{workflow-design,agent-design,efficiency,best-practices}.md`,
  `sam-author-agent/references/{workflows,data-flow,builtin-tools}.md`,
  `sam-entrypoints/references/event-mesh-entrypoint.md`,
  `sam-connectors/references/catalog.md`.
- Cluster (read-only): `kubectl get pods/deploy/svc/cm`, gwe/awe config files
  in the pods, gwe logs, `helm get values -a agent-mesh`, WebUI frontend
  bundle, `/api/v1/config`.
- Databases (SELECT only): `sam-solace-lab_webui.tasks`, `.task_events`,
  `.scheduled_tasks`; `sam-solace-lab_platform.rbac_*`,
  `.model_configurations`, `.budgets`, `.token_spend_ledger`, `.users`.
- Broker (SEMP GET only): queues on VPN `default` and `sam` of solace-1.
- Repo: `bsg-trading-desk-demo/` (README, RUNBOOK, mesh/, scripts/,
  .rendered/), insurance/retail/mfg cockpit broker settings.
- Memory notes: project_sam_v2_workflow_events, project_sam_mcp_workflow_tools,
  project_sam_v2_migration, project_event_mesh.
