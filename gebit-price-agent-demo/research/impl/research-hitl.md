# SAM 2.542.1: Human-in-the-Loop and Notifications for the price agent

Track: how to build the price-change approval natively in SAM 2.542.1
(lab: chart 2.3.10, namespace `sam-solace-lab`), for the EuroCIS 2027
"Preis- und Aktionsagent mit Freigabe" (POS simulator triggers, several
price triggers, fair UI, Postgres, AKS target).

Method: read-only. Sources are the 2.542.1 docs and authoring skills
shipped with the CLI, the strings of the 2.542.1 CLI binary (which embeds
the same engine, feature catalog, SQL migrations and WebUI bundle as the
pods), the deployed `sam-awe` binary, the shipped pod configs, read-only
`kubectl`/`psql` queries and unauthenticated HTTP GETs. Nothing was
applied, restarted or written on the lab. No live HITL run was possible:
the feature flag is off on the lab (1.6) and the cached `sam` login had
expired (a browser login needs the user's password).

Legend: **VERIFIED** = seen in a source (cited). **INFERRED** = follows
from verified sources but was not executed. **UNKNOWN** = needs the Gate 0
spike (section 5.4). Confidence per fact: section 7.

Path abbreviations:

- `SP` = `<scratchpad>`
- `DOCS` = `SP/review-sam/skills2542/sam-docs/references/documentation`
- `SKILL` = `SP/review-sam/skills2542`
- `STR` = `SP/impl/hitl/sam-cli.strings` (`strings -n 6 ~/.local/bin/sam`,
  CLI 2.542.1; line numbers refer to this dump; Go concatenates many
  literals per line)
- `OAS` = `SP/impl/hitl/api-v2-openapi.yaml` (GET
  `https://sam.solace.lab/api/v2/openapi.yaml`, 200, no auth, 17059 lines)
- `PLAT` = `/etc/sam/configs/gwe/platform.yaml` in the gwe pod

---

## 0. Bottom line

1. **There IS a native approval path for event-triggered runs in
   2.542.1, but it is a flagged feature that is OFF on the lab.** A
   workflow `type: tool` node whose tool carries
   `hil: {require_approval: true}` pauses the run, the notification
   service puts an approval request into the inbox of the run's user,
   and the run resumes (on any AWE pod) when the user approves, or the
   node fails on deny/timeout. It needs
   `SAM_FEATURE_WORKFLOW_HIL_PAUSE_RESUME=true` (release phase
   `controlled_availability`, default `false`), the notification service
   (on by default, running on the lab) and a session database (present).
   With the flag off, a gated tool node FAILS instead of running
   (`workflow_tool_approval_enforcement` is on by default) [VERIFIED
   `STR:674099-674107`, `STR:674180-674198`, `STR:115367`].
2. **Agent-level HITL does not help for event-triggered runs.** Tool
   approval on an agent's tool and `ask_user_question` need an entrypoint
   with `interactive_user_input=true`; the event mesh entrypoint sets it
   false, so tool approval is a fail-safe denial and `ask_user_question`
   errors [VERIFIED `DOCS/concepts/a2a-protocol.md:89`,
   `DOCS/reference/built-in-tools.md:171`]. In WebUI chats both work
   (card in chat plus inbox) [VERIFIED].
3. **Recipient = the run identity** (`defaultUserIdentity` /
   `userIdentityExpression` of the event rule). A run with no user id
   cannot pause (`workflow HIL pause: task has no recipient user id`,
   `STR:2904`). Recommendation: make the run identity the approver
   (`marktleitung@solace.lab`); another user can answer only through the
   REST API with `notify:_:send_others`.
4. **Our own fair UI can approve through the SAM API, but only with a
   human user's session token, never with an API key.** Endpoints:
   `GET /api/v1/notify/inbox`, `POST /api/v1/notify/inbox/{id}/respond`
   with `{"status":"answered","data":{"approved":true}}` [VERIFIED routes
   and WebUI code; body shape for approvals INFERRED]. API keys are
   refused by the notification service and by task submission [VERIFIED
   `DOCS/administering/api-keys.md:89-101`,
   `DOCS/administering/notifications.md:230`]. These routes are not in the
   `/api/v2` OpenAPI spec (management API only) [VERIFIED `OAS`].
5. **Timeouts**: approval timeout per tool entry, default `45m`, no
   documented maximum; on timeout or deny the paused node FAILS (so a
   rejection is a failed run unless handled with `on_exit`) [VERIFIED].
   Whether node/workflow timeouts count during the pause is UNKNOWN.
6. **Recommended**: split propose (agent, LLM) and approve (tool-only,
   gated) into two workflows; native gated `apply_price` tool node as the
   target, `notify_user` tool nodes for insights, the signed decision
   event (DESIGN 6.4) as the fallback that replaces only the approval
   workflow. Gate 0 spike G0-19 (5.4) decides between them.

---

## 1. Which HITL mechanisms exist in 2.542.1

### 1.1 Overview

| Mechanism | Configured where | WebUI chat | Event-mesh-triggered run |
|---|---|---|---|
| A. Tool approval on an agent's tool (`hil:`) | agent `tools:` entry, connector `values.hil`, toolset reserved key `hil` | works: card in chat + inbox, Slack/Teams DM | **fail-safe denial** (no interactive surface) |
| B. `ask_user_question` (`hil_tools`) | agent toolset `hil_tools` (also in `general_agent_tools`) | works: form in chat + inbox (not Slack/Teams for WebUI chats) | **error** |
| C. Workflow HIL pause/resume (gated `type: tool` node) | workflow `tools:` entry `hil:`, or the bound connector's/toolset's gate | prompt goes ONLY to the inbox (no live-task fallback) | **designed for it**, needs feature flag (off on lab) |
| D. Notifications (`notify_user`) | `tools: [{tool_type: builtin-group, group_name: notification_tools}]` | fire-and-forget, inbox/Slack/Teams/webhook/connector | works (fire-and-forget), scope `notify:_:send` |

### 1.2 A. Tool approval (`hil:` block)

Evidence: `SKILL/sam-declarative-config/references/design/agent-design.md:230-321`
(HIL section), `SKILL/sam-declarative-config/references/connector.md:21-146`,
`SKILL/sam-declarative-config/references/toolset.md:289-341`, embedded
schema `STR` around the workflow `tools:` item (shown verbatim by
`grep -n 'entry takes. A gated tool node pauses'` -> `STR:111268`).

- Where it is authored:
  - Agent runtime YAML: `hil:` directly on a `tools:` entry (`builtin`,
    `builtin-group`, `mcp`, `openapi`); multi-tool entries take a
    `hil.tools.<registered name>` sub-map
    (`agent-design.md:275-346`).
  - `kind: connector` (every tool-producing type: mcp, api/openapi,
    sql, slack, document/graph DB, search, knowledge base, event_mesh,
    email): `spec.values.hil: {tools: {<role or tool name>: {...}}}`;
    MCP keys are the registered tool name (incl. `tool_name_prefix`,
    non `[A-Za-z0-9_]` -> `_`); the gate applies to EVERY agent and
    workflow node using the connector (`agent-design.md:257-273,348-373`;
    embedded skill text "A connector's gate applies to every agent that
    uses the connector", `STR:115366`).
  - `kind: toolset` package: reserved config key `hil`, keyed by tool
    name (`toolset.md:289-341`); the platform writes it into the per-tool
    `hil:` block at deploy. OpenAPI v2 confirms:
    `{"hil":{"web_request":{"require_approval":true}}}` (`OAS:6317-6321`).
  - Workflow `tools:` entry: same `hil` block (`STR:111268` schema:
    "A gated tool node pauses for approval and runs only once a human
    approves; where the workflow cannot reach a human it fails").
  - Not honoured: `hil` on skill-bundled tools is silently dropped
    (`agent-design.md:252-255`).
- Fields (`agent-design.md:302-310`): `require_approval` (bool, default
  false), `require_approval_when` (list of rules, OR-ed, operators
  `eq in not_in exists not_exists gt lt gte lte`, dotted `arg` paths,
  missing arg fails OPEN except `exists`/`not_exists`), `approval_message`
  (Go `text/template` over the tool args, `{{.argName}}`), `show_args`
  (default true), `timeout` (duration, default `45m`, no global key).
  A block without `require_approval`/`require_approval_when` gates
  nothing, silently (`agent-design.md:312-314`).
- Card: agent display name, rendered message, args (label + value,
  JSON-schema description as tooltip) (`agent-design.md:471-484`).
- Deny, cancel and timeout return a tool error to the LLM (agent path)
  (`agent-design.md:482-484`).

### 1.3 B. `ask_user_question` (`hil_tools`)

`DOCS/reference/built-in-tools.md:159-171`: 1-4 questions, bounded
choices; returns `status` `answered|cancelled|timed_out` plus `answers`;
default timeout 45 minutes; "interactive agents only; do not attach to
autonomous or workflow agents ... Returns an error on channels that cannot
render an interactive prompt (for example, an Event Mesh entrypoint)".
Toolset id `hil_tools` (`SKILL/sam-declarative-config/references/toolset.md:27`).
Embedded best practice: never put it on workflow nodes or event-driven
agents, they "will block indefinitely" (`STR`, "Field Interaction Rules"
2 and 7; `SKILL/.../design/best-practices.md:313-315`).
Not usable for our event-triggered path.

### 1.4 C. Workflow HIL pause/resume (the native path for events)

Feature catalog in the binary (`STR:674099-674107`, same entry in the
deployed `sam-awe`, see 1.6), summarised in our words:

- `workflow_hil_pause_resume`: off by default and not generally
  available yet. When on, a workflow tool node whose tool returns a
  pending approval pauses the run instead of failing. The request goes
  out through the notification service, the paused run is stored
  durably, and the run continues on any pod once the user answers or
  the request expires. Switched on with
  `SAM_FEATURE_WORKFLOW_HIL_PAUSE_RESUME=true`; when off, the node
  fails as before.
- `workflow_tool_approval_enforcement` (`STR:674180-674198`): on by
  default, same release stage. It applies `hil.require_approval` to
  workflow `type: tool` nodes. When on, a gated tool waits for
  approval where a human can be reached (this needs the pause/resume
  flag) and fails the node otherwise; it never runs unapproved. When
  off, a gated node runs without asking and the dispatch is recorded
  with the approval reason `enforcement_disabled`.

Behaviour matrix (embedded connector skill, `STR:115367-115369`):

| enforcement | pause_resume | gated tool node |
|---|---|---|
| on (default) | off (default, lab today) | node FAILS (`HIL_NO_APPROVAL_ROUTE`) |
| on | on | node PAUSES, prompt via notify, resumes on answer |
| off | any | runs WITHOUT approval (audit `enforcement_disabled`) |

Startup/runtime messages (`STR`): "tools require human approval but this
workflow cannot prompt; nodes calling them will fail. Enable
workflow_hil_pause_resume and configure a session database to allow
approvals" (`STR:4994`); "tool %q requires human approval, but this
workflow cannot request it; enable workflow_hil_pause_resume, configure a
session database, and run the notification service, which is what
delivers the prompt and carries the answer back" (`STR:5649`); "workflow
HIL pause/resume enabled"; "workflow HIL: approval granted; dispatching
tool node"; "workflow HIL: tool not approved; failing the node";
"approval for tool %q timed out"; "tool %q was denied by the user"
(`STR:2148`, `STR:2904`).

Durable store (SQL migration, `STR:14085`): table `workflow_paused`
(`request_id` PK, `execution_id`, `workflow_name`, `node_id`,
`requester_addr` = notify response topic, `recipient_user_id`,
`state_snapshot`, `exec_context` "(UserProps, TaskID, ContextID,
Identity, ...)", `routing`, `status paused|resumed|timed_out|cancelled|failed`,
`expires_at`, ...). Comment: "When a workflow tool node returns a pending
(HIL) result, the executor persists the entire execution here and routes
an input request through the notification service. The user's reply comes
back on the notify response topic; whichever pod receives it claims the
row (first-wins), reconstructs the DAGExecutor from the snapshot, and
resumes - so a paused workflow survives the originating pod's loss."

Notify side (`STR:12430`): table `notify_pending_requests` (`request_id`,
`requester_addr`, `recipient_user_id`, `dedup`, `status
pending|answered|cancelled|timed_out|failed`, `expires_at`). "A gateway
later publishes the user's reply on {ns}/sam/v1/notify/reply/{request_id};
the service looks the row up here and forwards the response to
requester_addr." `PLAT:31-40` (pod config): the notification service is
"the delivery surface for HIL prompts ... Required for workflow HIL
pause/resume, which routes its input prompt solely through this service
(no live-task fallback)."

Error codes (evidence migration, `STR:45966-46016`): `HIL_DENIED`,
`HIL_CANCELLED` (user said no / pressed Cancel), `HIL_RUN_ENDED` (answer
after the run ended), `HIL_NO_APPROVAL_ROUTE` ("only a workflow reports
it, when approvals are on and the deployment has no durable store or
route to ask anyone through"), `HIL_UNREADABLE`, `HIL_UNANSWERABLE`,
`HIL_BACKSTOP`, `HIL_EXIT_HANDLER` (a gated call inside an `on_exit`
handler is refused before dispatch); `HIL_NO_HUMAN_IN_EVAL_RUN`
(`STR:10291`: evaluation runs refuse calls that need a person).

Node-level configuration: there is no HIL field on the node; the gate
lives on the tool (workflow `tools:` entry, connector `values.hil`, or
toolset `hil`) [VERIFIED `sam config schema show workflow --type tool`,
saved as `SP/impl/hitl/schema-wf-tool.md`: fields `id type depends_on when
timeout input retry_strategy tool_name connector tool`].

**Doc contradiction** (to note, not to trust blindly):
`SKILL/sam-declarative-config/references/design/agent-design.md:316-321`
still says a gated workflow tool node "dispatches the tool without
asking" (that is the `enforcement off` behaviour), while
`SKILL/sam-author-agent/references/workflows.md:32` and
`SKILL/sam-declarative-config/references/workflow.md:395-404` say it
"fails instead of running" and the binary catalog says "fails ... or
pauses with pause_resume". The binary is authoritative; the user docs
(`DOCS/using-agent-mesh/notifications.md:80`) confirm "A workflow step
that waits for your approval fails when the request expires", i.e.
workflow steps can wait for approval. The offline 2.542.1 doc pages do
not document the flag itself.

Also seen: `ask_user_question`-style answers from a workflow tool node
(a tool node calling `ask_user_question`) are NOT documented; the
`{{%s.output.answers.%s.choice}}` string belongs to decision nodes. Do not
plan on it.

### 1.5 Behaviour per channel

(a) **Event-mesh-triggered workflow run**

- Gated tool node (C): pauses only with the flag on; recipient = run's
  user id (section 3). INFERRED to work for event runs: nothing in the
  pause path checks `interactive_user_input`; it routes "solely through"
  the notification service, and the only recipient precondition found is
  a user id on the task (`STR:2904`). This is the core Gate 0 question.
- Agent node inside the run with a gated tool (A): the entrypoint's
  `gatewayCapabilities` are forwarded unchanged to peers
  (`DOCS/concepts/a2a-protocol.md:89`), so INFERRED fail-safe denial,
  the agent gets a tool error. Embedded skill text: "HIL only works for
  interactive agents with a connected user. A gated tool called on a
  channel that cannot prompt is **denied**, not auto-approved"
  (`STR:125951`).
- `ask_user_question` (B): error (VERIFIED docs).
- `notify_user` (D): works as a tool node without LLM (docs), scope
  `notify:_:send` on the run identity (DESIGN G0-16).
- Direct agent target (`targetAgent`) with a gated tool: denial
  (VERIFIED `a2a-protocol.md:89`: "MCP, event mesh, and webhook set
  interactive_user_input to false, so those prompts return a clean error
  (or, for tool approval, a fail-safe denial) instead of deadlocking").

(b) **WebUI chat session**

- Agent tool approval and `ask_user_question` work: the request shows in
  the chat AND as an inbox item with "Needs response"; "Agent Mesh accepts
  the first answer it receives, wherever you give it"; tool approvals also
  reach Slack/Teams DMs; a question asked during a WebUI chat goes only to
  the inbox (`DOCS/using-agent-mesh/notifications.md:69-82`;
  `DOCS/administering/notifications.md:36`). Chat answers use
  `POST /api/v1/userInput/respond` with `{taskId, agentName, requestId,
  status: answered|cancelled, data}` (WebUI bundle, `STR:235146`).
- A workflow started from chat that hits a gated tool node: prompt goes
  to the inbox only ("no live-task fallback", `PLAT:37-40`) [INFERRED].
- Scheduled tasks: no human in the loop; `input-required` cannot be
  satisfied (`DOCS/using-agent-mesh/scheduled-tasks.md:108`).

### 1.6 Live lab state (read-only checks, 2026-11-10)

- Deployed `sam-awe` (2.542.1) contains the flag and messages: `grep -a`
  in the pod found `SAM_FEATURE_WORKFLOW_HIL_PAUSE_RESUME=true` (1 hit),
  "workflow HIL pause/resume enabled", "tools require human approval but
  this workflow cannot prompt; nodes calling them will fail"; container
  env has **0** `SAM_FEATURE_*` variables [VERIFIED `kubectl exec ... grep`].
- Shared env ConfigMap `agent-mesh-solace-agent-mesh-env` (envFrom of
  gwe/awe/str) has no `SAM_FEATURE_*` key; `SESSION_SERVICE_TYPE=sql`,
  `WEB_UI_SESSION_SERVICE_TYPE=sql` [VERIFIED].
- awe log since start (211 lines, 3 h): no "workflow HIL" line; session
  store `sql` on `sam-solace-lab_orchestrator` [VERIFIED].
- gwe log: "notify service initialized", "notify inbox enabled", "notify
  HIL router started replyQueue=sam-solace-lab/q/notify/reply", "notify
  service started queue=sam-solace-lab/q/notify/request" [VERIFIED].
- `GET https://sam.solace.lab/api/v1/notify/health` -> 200;
  `GET /api/v1/notify/inbox` without token -> 401 [VERIFIED curl].
- Platform DB: tables `notifications` (`id, user_id, title, body,
  payload, source, status, created_at, read_at, category`),
  `notify_pending_requests` (0 rows), `notify_user_channels`, ...;
  `notifications` has 0 rows. Orchestrator DB has no `workflow_paused`
  table (store never opened) [VERIFIED `psql \d`, read-only].
- Chart: `environmentVariables` renders into the shared env ConfigMap;
  chart comment "SAM_FEATURE_* flags default from the binary's feature
  catalog. Override one for a deployment by setting it here"
  (`~/.local/share/sam/charts/solace-agent-mesh-2.3.10/values.yaml:304-305`).
  So enabling = one line in
  `agent-mesh-deployment/local-k8s-values.yaml` (`environmentVariables`,
  line 200 block) plus `helm upgrade` (owner decision; lab-wide; same
  mechanism on AKS).

---

## 2. Delivery through the notification service, answering, REST

### 2.1 Channels

`DOCS/administering/notifications.md:22-40,103-218`,
`DOCS/using-agent-mesh/notifications.md:18-115`:

- **In-app inbox** (channel type `web`): every notification; the type
  "Tool approvals and agent input requests" cannot be turned off for
  In-App. Requests show a "Needs response" badge; expanding the row opens
  the form; answered/expired requests show "Expired"; marking read does
  not answer.
- **Slack / Teams DM**: via a running Slack/Teams entrypoint after the
  user enables it in Settings; tool approvals are answerable in the DM
  (release note 2.542.1 fixed the card content). Never posted in channels.
- **Webhook** (`notify.directory[].channels[].type: webhook`) and
  **connector** channel: per-user, configured in the platform YAML
  `notify.directory`, read at startup. Webhook URL must NOT resolve to a
  private, loopback or link-local address (so not to an in-cluster
  service), forbidden headers include `Authorization`, 30 s timeout,
  body `generic|slack|teams`. These channels deliver text only; there is
  no reply path from them.
- Answering is possible from: inbox (WebUI), chat (agent path), Slack/Teams
  DM (tool approvals), and the REST API (2.2).

### 2.2 REST endpoints (not in the /api/v2 spec)

`OAS` lists only `/api/v2/platform/*` management routes (agents,
connectors, entrypoints, workflows, models, rbac, apiKeys, evaluations,
...); no notify, no task or HIL routes [VERIFIED path list]. The notify
API is served under `/api/v1/notify` on the WebUI origin, same auth as
the UI (`DOCS/administering/notifications.md:24`). Routes from the binary
(`STR:2477` and route table) and the WebUI client code (`STR:235177`):

| Method and path | Use |
|---|---|
| `GET /api/v1/notify/health` | no auth, 200 when running |
| `GET /api/v1/notify/inbox?pageNumber=1&pageSize=50[&status=unread][&category=...]` | list own inbox |
| `POST /api/v1/notify/inbox/{id}/respond` body `{"status":"answered"\|"cancelled","data":{...}}` | answer an input request (WebUI sends `data = surface context`, `{}` on cancel) |
| `POST /api/v1/notify/inbox/{id}/read`, `/unread`, `POST /api/v1/notify/inbox/read-all[?category=]` | read state |
| `DELETE /api/v1/notify/inbox/{id}`, `DELETE /api/v1/notify/inbox` | delete |
| `GET/PUT /api/v1/notify/preferences`, `/preferences/categories`, `/preferences/matrix` | settings |
| `GET /api/v1/notify/channels`, `POST /api/v1/notify/channels/{type}/confirm`, `/confirm/verify`, `/disable` | Slack/Teams channels |
| `POST /api/v1/notify` | send a notification via REST (to others needs `notify:_:send_others`); input mode via REST: "mode 'input' (HIL) is not supported yet" |
| `POST /api/v1/userInput/respond` | chat-path answer (`taskId, agentName, requestId, status, data`) |
| `POST /api/v1/auth/refresh`, `GET /api/v1/user` | token refresh, identity check |

Inbox item fields used by the WebUI (`STR:235297`): `id`, `requestId`,
`surface` (A2UI form), `promptState` (`pending`/`resolved`), `status`
(`unread`/`read`), `title`, `body`, `category`, `source`, `action`
(`sessionId`/`shareId`/`path`), `label`. The WebUI treats an item as
answerable when `requestId && surface && (promptState=='pending' ||
(status=='unread' && promptState!='resolved'))`.

Tool-approval answer payload: the WebUI summarises an answered approval
as "Denied" when `context.approved === false`, else "Approved"
(`STR:235145`), so the approve body is INFERRED as
`{"status":"answered","data":{"approved":true}}` and deny as
`{"approved":false}` (verify in G0-19 T6 by capturing the WebUI request).
Errors: "this request is no longer awaiting input (already answered,
cancelled, or expired)" (`STR:3617`), "not permitted to act on behalf of
another user".

Broker side (internal, not a contract): topics
`{ns}/sam/v1/notify/request/...`, `.../reply/{request_id}`,
`.../response/...`, `.../deliver/{channel}/...`, `.../presence/...`,
`.../inboxCreated` (gateway signal on every new inbox row) (`STR:2110`).
A read-only subscription to `sam-solace-lab/sam/v1/notify/inboxCreated`
could push "new approval waiting" to our monitor; payload UNKNOWN (T13).
Do NOT publish replies on `notify/reply/...` ourselves: undocumented and
it would bypass SAM's auth.

### 2.3 Auth for our own fair UI

- **API keys cannot be used**: "Agent Mesh refuses a key on every other
  request, including task submission, sessions, projects, prompts,
  scheduled tasks, and the notification service" (403 where WebUI and
  platform share a process, 401 otherwise)
  (`DOCS/administering/api-keys.md:89-101`; `notifications.md:230`;
  message "API keys can only call the Platform configuration API").
  System-user keys are GA, but only for `sam config` / `sam eval` routes.
- What works: a human user's SAM access token (ES256 JWT minted by the
  gwe after OIDC login, `ttl_seconds` 3600 default, idle timeout 4 h,
  `POST /api/v1/auth/refresh`) sent as `Authorization: Bearer`
  (`DOCS/administering/enabling-sso.md:20-35`; `gwe.yaml:51-52`).
- Whether a raw Keycloak access token is accepted as bearer: the v2
  OpenAPI security scheme says "A sign-in access token from your identity
  provider, or an Agent Mesh API key" (`OAS:7509`), and the binary has an
  IdP userinfo path, but it is UNVERIFIED for `/api/v1/notify` (T7).
- `sam api` handles token refresh but its help text says "Do not build
  external system integrations on top of it" - not for the BFF.
- So: **possible** for our UI with a marktleitung session token; the
  cleanest token sources, in order: (1) Keycloak token accepted directly
  (if T7 passes; BFF gets it for the demo user from a dedicated Keycloak
  client), (2) operator logs in once through SAM and the BFF keeps the
  SAM token + refresh token, (3) no custom auth at all: the tablet shows
  SAM's own Notifications page in kiosk mode, logged in as marktleitung.

---

## 3. Recipient and cross-user answering

- The workflow pause addresses the task's user: `workflow_paused.exec_context`
  holds the Identity, `recipient_user_id` "who was asked", and the pause
  fails with "workflow HIL pause: task has no recipient user id" when the
  task has none (`STR:14085`, `STR:2904`). For an event run that user is
  the rule's `userIdentityExpression` result, else `defaultUserIdentity`,
  else the `runAs` system user / built-in default system user
  (`sam config schema show entrypoint --type event_mesh`, saved as
  `SP/impl/hitl/schema-ep-eventmesh.md`). A system user cannot log in,
  so a system-user run identity makes the prompt unanswerable in the UI.
- Today the lab demos run as `power_user@solace.lab` (bsg rule,
  `bsg-trading-desk-demo/mesh/entrypoints/bsg-desk-events.yaml.template:49`).
- **A different user ("Marktleitung") receiving the prompt**: only by
  being the run identity. Recommended: rule `defaultUserIdentity:
  marktleitung@solace.lab` (new Keycloak demo user, group mapped to a role
  with `workflow:*:invoke`, `agent:*:invoke`, `notify:_:send`, tool
  scopes as power_user). Per-store routing possible with
  `userIdentityExpression` on an event field.
- **A different user answering someone else's prompt**: REST only, with
  `notify:_:send_others` ("answering another user's input requests") and
  `notify:_:read_others` to read their inbox
  (`DOCS/administering/notifications.md:220-230`,
  `DOCS/reference/rbac-reference.md:63`). The WebUI inbox shows only the
  caller's own items. The parameter that addresses another user's inbox
  is UNKNOWN (T8). `notify_user`'s `recipient_user_id` is NOT limited by
  `send_others` (warning `notifications.md:216-218`).

---

## 4. Latency and timeouts

- **Approval timeout**: `hil.timeout` per tool entry, default `45m`
  ("fixed", no deployment-wide key), Go duration; no documented maximum
  (`agent-design.md:310`; embedded schema default `"45m"`). Stored as
  `expires_at` in `workflow_paused` and `notify_pending_requests`; swept
  by timeout sweepers (`hilTimeoutSweepLoop`, notify `timeoutSweepLoop`);
  sweep interval UNKNOWN.
- **On timeout**: notify row `timed_out`, inbox shows "Expired"; "A
  workflow step that waits for your approval fails when the request
  expires" (`DOCS/using-agent-mesh/notifications.md:80`); message
  "approval for tool %q timed out"; with `fail_fast: true` the run fails
  and the event rule's `errorOutput` publishes. **On deny**: node fails
  (`HIL_DENIED`, "tool %q was denied by the user"). Answer after the run
  ended: `HIL_RUN_ENDED`, not dispatched.
- **Node and workflow timeouts during the pause**: node default 5 min
  (`SKILL/.../workflow-design.md:657-661`), `workflow_timeout` optional.
  Whether they tick while paused: UNKNOWN (T5). Until then set the gated
  node's `timeout` and `workflow_timeout` above `hil.timeout`.
- **Event-rule acknowledgment**: with `on_completion`, the default
  `timeoutSeconds` is 300; when it elapses the entrypoint applies the
  On-failure action (nack -> redelivery) "and publishes nothing at that
  point. The task keeps running"
  (`DOCS/building/entrypoints/event-mesh/index.md:149,178`). A pause
  longer than the ack timeout would therefore start a SECOND run and a
  second approval request. Use `on_receive` on any rule whose workflow
  can pause, with idempotency in our tools (T12).
- **Latency of the pause/resume path**: not measured. INFERRED small:
  pause = persist snapshot + one broker publish + notify DB insert +
  `inboxCreated` signal; resume = REST -> broker reply -> notify claim ->
  broker response -> AWE claim + DAG reconstruct -> dispatch. Measured
  reference points: tool node 0.02-0.8 s, event start ~22 ms. Target
  for G0-19: pause -> inbox visible <= 2 s p95; click -> tool start
  <= 2 s p95.
- **Restart**: paused rows survive an AWE pod restart and are claimed
  first-wins by any replica (`STR:14085`); answers arriving while an
  instance stops may be lost until the sweeper times them out
  ("workflow HIL: answer arrived while the instance is stopping; it is
  lost unless another replica claims it, otherwise the row times out").
- **Retention**: answered/expired requests and still-pending requests
  older than `retention_days` (30) are deleted hourly
  (`DOCS/administering/notifications.md:97-101`).

---

## 5. Recommended pattern for the price agent

### 5.1 Shape

Two workflows and three event rules on the existing event-mesh
entrypoint (names follow DESIGN.md; sketches, not validated).

1. `gpos-pos-event` (unchanged idea): one run per GEBIT Purchase API
   event, deterministic `assess` tool node evaluates the triggers
   (slow seller, competitor price, overstock, time-of-day, ... all in
   the engine), a `switch`, and only on a decision moment the price
   agent (fast/workflow model, multi-modal input if a shelf photo is
   attached) proposes a change with structured output. A tool node
   `stage_proposal` writes the proposal to Postgres
   (`status=awaiting_approval`, `proposal_hash`, `auto_ok` from the
   policy) and publishes `gpos/v1/proposal/{store}/{proposalId}`. A
   `notify_user` tool node sends the insight ("KI-Einschaetzung") to the
   Marktleitung inbox. Rule: `on_completion` as today (no pause here).
2. `gpos-price-approval` (NEW, tool-only, no LLM): started by the
   proposal event (rule with `on_receive`, run identity
   `marktleitung@solace.lab`). Nodes: `check` (proposal still pending,
   hash ok) -> `apply` (GATED `apply_price`) -> `tell` (`notify_user`
   "Preis aktiv"). `on_exit.on_failure` -> `record` (not gated) writes
   `rejected`/`expired`/`superseded` to Postgres and the monitor. The
   evaluation suite targets `gpos-pos-event`/the agent only, because
   evaluation runs refuse HIL (`HIL_NO_HUMAN_IN_EVAL_RUN`).
3. Fallback (DESIGN 6.4): `gpos-apply-decision`, started by the signed
   tablet decision event; replaces only workflow 2.

Policy-driven gate (shows "HITL where needed" with several triggers):
gate unless the policy explicitly allows automatic application,
fail-closed against missing args.

```yaml
# kind: connector (MCP) for the engine's gRPC-backed tools; sketch
spec:
  type: mcp
  values:
    # server_url, connection_type, manifest: see the MCP track
    hil:
      tools:
        apply_price:              # registered name incl. tool_name_prefix
          require_approval_when:  # OR-ed; missing arg fails open, so
            - arg: auto_ok        # not_exists closes that hole
              not_exists: true
            - arg: auto_ok
              eq: false
          approval_message: >-
            {{.article_name}}: {{.old_price}} EUR -> {{.new_price}} EUR
            ({{.pct}} %), Ausloeser {{.trigger}}. Freigeben?
          show_args: true
          timeout: "5m"
```

```yaml
kind: workflow
name: gpos-price-approval
description: >-
  Applies one staged price proposal after the store manager approves it
  in the SAM inbox (native HITL); records rejections and expiries.
spec:
  appConfig:
    version: 0.1.0
    workflow_timeout: 8m          # > hil.timeout until G0-19 T5 says otherwise
    default_node_timeout: 10s
    fail_fast: true
    input_schema:
      type: object
      required: [proposal_id]
      properties:
        proposal_id: {type: string}
    tools:
      - tool_type: builtin-group
        group_name: notification_tools   # notify_user; scope notify:_:send
    nodes:
      - id: check
        type: tool
        connector: gpos-pricing-tools
        tool: check_proposal
        input:
          proposal_id: "{{workflow.input.proposal_id}}"
          run_id: "{{workflow.run_id}}"
      - id: apply
        type: tool
        connector: gpos-pricing-tools
        tool: apply_price               # gated by the connector's hil
        depends_on: [check]
        timeout: 7m
        input:
          proposal_id: "{{workflow.input.proposal_id}}"
          article_name: "{{check.output.mcp_structured_content.article_name}}"
          old_price: "{{check.output.mcp_structured_content.old_price}}"
          new_price: "{{check.output.mcp_structured_content.new_price}}"
          pct: "{{check.output.mcp_structured_content.pct}}"
          trigger: "{{check.output.mcp_structured_content.trigger}}"
          auto_ok: "{{check.output.mcp_structured_content.auto_ok}}"
          proposal_hash: "{{check.output.mcp_structured_content.proposal_hash}}"
      - id: tell
        type: tool
        tool_name: notify_user
        depends_on: [apply]
        timeout: 4s
        input:
          title: "{{apply.output.mcp_structured_content.notify_title}}"
          message: "{{apply.output.mcp_structured_content.notify_message}}"
          channels: [web]
      - id: record
        type: tool
        connector: gpos-pricing-tools
        tool: record_outcome            # never gated (HIL_EXIT_HANDLER)
        input:
          proposal_id: "{{workflow.input.proposal_id}}"
          status: "{{workflow.status}}"
          error: "{{workflow.error.message}}"
    on_exit:
      on_failure: record
    output_mapping:
      proposal_id: "{{workflow.input.proposal_id}}"
      change_id: "{{apply.output.mcp_structured_content.change_id}}"
```

```yaml
# event rule (in the existing event_mesh entrypoint)
- name: gpos_price_approval
  subscriptions:
    - topic: "gpos/v1/proposal/>"
      qos: 1
  messageFormat: json
  targetWorkflowName: gpos-price-approval
  inputExpression: "input.payload:"
  defaultUserIdentity: marktleitung@solace.lab   # = approver
  acknowledgmentPolicy:
    mode: on_receive                            # a pause must not hit the ack timeout
  successOutput: {enabled: true, topic: "gpos/v1/sam/approval/ok", topicType: static, responseType: structured}
  errorOutput: {enabled: true, topic: "gpos/v1/sam/approval/error", topicType: static, responseType: error}
```

Tool rules (engine side): `apply_price` is idempotent by
`proposal_id` (`UPDATE ... SET status='applied' WHERE status=
'awaiting_approval' AND hash=...`), returns `already_applied`/
`superseded` instead of failing, so the native path and the fallback
can never apply twice. All tool returns are Pydantic models and stay
below 2048 bytes.

Constraints of the native path to accept in the talk track:

- Approve/deny only: the approver cannot edit the percentage on the
  approval card (args are fixed by the proposal). Price options (slot A/B)
  need a second proposal or the fallback tablet UI.
- Deny or timeout = failed run (red in Activities) by design; the
  `on_exit` record turns it into a clean "abgelehnt"/"abgelaufen" on the
  monitor.
- Approval card is text (message + args); images and the "Warum" card
  stay on our monitor/tablet.

### 5.2 Fair UI wiring

- Tablet, native variant (no custom auth): kiosk browser on SAM's
  Notifications page as marktleitung; the visitor taps the request,
  presses Approve. Monitor learns the state from our Postgres/broker
  events (`stage_proposal`, `apply_price`, `record_outcome`), optionally
  the `inboxCreated` signal and the A2A status stream (T13, T14).
- Tablet, custom variant (if T6+T7 pass): BFF lists
  `GET /api/v1/notify/inbox?status=unread` with the marktleitung token,
  filters `requestId && surface && promptState=='pending'`, maps the item
  to our proposal (proposal_id is in the approval message/args), and
  posts `POST /api/v1/notify/inbox/{id}/respond`
  `{"status":"answered","data":{"approved":true|false}}`. Our tablet
  design keeps its look, SAM still does the HITL.
- `notify_user` for insights: tool nodes without LLM (`notify_user`,
  `channels: ["web"]`), or the agent itself when the text is
  model-written; run identity needs `notify:_:send` (approved for
  power_user; add to the marktleitung role too).

### 5.3 Fallback (if native HITL for event runs fails)

Exactly DESIGN 6.4: tablet -> BFF -> HMAC-signed decision event
`gpos/v1/decision/{action}/{store}/{proposalId}` -> rule (on_completion
ok, no pause) -> tool-only `gpos-apply-decision` (verify HMAC, hash,
status; idempotent apply) -> `notify_user` to the Marktleitung inbox. In
that case native SAM HITL is shown in a WebUI chat moment (agent with a
gated `apply_price` tool, card in chat) and named honestly as "in chat
native, at the till via signed decision event".

Hybrid safety net (recommended even when native passes): the host keeps
the signed "Notfall-Freigabe" on the tablet; the idempotent
`apply_price` makes whichever comes first win; the still-pending SAM
request is then answered with `cancelled` by the BFF (if it has a
token) or expires after `hil.timeout` and `record_outcome` writes
`superseded`.

### 5.4 Gate 0 spike G0-19 "Native Workflow-HIL (2.542.1)"

Replaces G0-17 (which asked about an agent with `hil_tools`, the wrong
mechanism). Needs owner approval for the lab writes in P1-P3.

Preparation:

- P1 Flag: `environmentVariables.SAM_FEATURE_WORKFLOW_HIL_PAUSE_RESUME:
  "true"` in `agent-mesh-deployment/local-k8s-values.yaml`,
  `./scripts/start.sh` (helm upgrade, gwe/awe/str restart). Check: awe log
  "workflow HIL pause/resume enabled", no "cannot prompt" warning for
  the spike workflow, `workflow_paused` table appears in the session DB.
  Re-run G0-4 (load) with the flag on.
- P2 Identity: Keycloak user `marktleitung@solace.lab` + role
  (`workflow:*:invoke`, `agent:*:invoke`, `notify:_:send`); user logs in
  once to the WebUI.
- P3 Spike resources under prefix `gpos-spike-hil-`:
  - Phase A (zero code): workflow with `tools: [{tool_type: builtin,
    tool_name: get_current_time, hil: {require_approval: true,
    approval_message: "Spike: Preis 8,67 EUR -> 6,89 EUR freigeben?",
    timeout: "2m"}}, {tool_type: builtin-group, group_name:
    notification_tools}]`, nodes `gate` (tool `get_current_time`) ->
    `tell` (`notify_user`), `on_exit.on_failure` -> `notify_user` with
    `{{workflow.status}}`/`{{workflow.error.message}}`; event rule
    `gpos/spike/hil/>`, `defaultUserIdentity: marktleitung@solace.lab`,
    `on_receive`, outputs to `gpos/spike/hil/ok|err`.
  - Phase B: same with the G0-10 MCP stub tool `apply_price` gated via
    the connector's `values.hil` with `require_approval_when` and a
    templated `approval_message`.

Tests and pass criteria:

| Test | Steps | Pass |
|---|---|---|
| T1 chat baseline | run the spike workflow from a WebUI chat as marktleitung | pauses, inbox item "Needs response", approve -> completes |
| T2 event, approve | 10 events, approve each in the inbox | 10/10 pause; inbox item <= 2 s p95 after gate start; tool start <= 2 s p95 after click; successOutput 10/10; 0 duplicate runs |
| T3 deny | 5 events, deny | node fails `HIL_DENIED`, errorOutput + on_exit 5/5, no hang |
| T4 timeout | `hil.timeout: 1m`, no answer | fails at 1m + sweep delay (record it), inbox "Expired", errorOutput 3/3 |
| T5 timer interplay | node `timeout: 20s`, `hil.timeout: 2m`, approve at 60 s; same with `workflow_timeout: 30s` | document whether the pause counts; a setting for a 5-min window exists |
| T6 REST approve | with marktleitung's SAM token: GET inbox, POST respond approve and deny; capture the WebUI's own request body | both resume/deny correctly; exact `data` shape recorded |
| T7 IdP token | Keycloak access token of marktleitung as Bearer on `GET /api/v1/user` and `/api/v1/notify/inbox` | 200 = BFF auth model (1); 401 = model (2) or (3) |
| T8 cross-user | as sam_admin: list/answer marktleitung's request (try `?userId=` / `?user_id=`); as power_user: same | admin allowed, power_user 403; parameter name recorded |
| T9 restart | pause, owner restarts awe, approve | resumes 3/3 |
| T10 concurrency | 5 parallel events, approve in shuffled order | each run resumes its own node 5/5 |
| T11 agent path (finding) | event-triggered workflow with an agent node whose tool is gated | expected fail-safe denial; record message |
| T12 ack timeout | same rule with `on_completion`, `timeoutSeconds: 30`, approve at 60 s | expected nack + redelivery -> confirms `on_receive` |
| T13 inbox signal | read-only probe subscribed to `sam-solace-lab/sam/v1/notify/>` on VPN sam | payload of `inboxCreated` recorded (user, id?) |
| T14 status stream | probe on `sam-solace-lab/a2a/v1/gateway/status/>` during a pause | signals recorded (node start, `user_input_request`?) for the monitor |

Decision rule:

- **Native GO** if T2, T3, T4, T9 and T10 pass and T5 yields a working
  setting: approval workflow 2 goes native; tablet = SAM inbox (kiosk) or
  custom UI.
- **Custom tablet on SAM API** additionally needs T6 and T7 (or an
  accepted token model 2).
- **Fallback** if T2 fails (`HIL_NO_APPROVAL_ROUTE`, "no recipient user
  id", prompt never in inbox, or resume unreliable): signed decision
  event; native HITL only in a chat moment; report to Solace with the
  T11/T2 evidence.

---

## 6. Open points and risks

- Flag is `controlled_availability` and off by default; the notification
  service is Early Access ("do not use in production"). Ask Solace
  whether it is supported for a public demo on 2.542.1 and AKS.
- Docs disagree on gated tool nodes (1.4); the offline docs do not
  document `workflow_hil_pause_resume` at all.
- Unknown: node/workflow timer during pause, sweep interval, max
  `hil.timeout`, the exact approval `data` shape, cross-user parameter,
  `inboxCreated` payload, whether IdP tokens are accepted as bearer.
- AKS: the same Helm `environmentVariables` line; notify DB = platform DB
  (or `NOTIFY_DATABASE_URL`); webhook channels cannot target private
  addresses; more than one AWE replica is supported by the claim model
  (T9 covers one restart only).
- `sam config apply` on 2.542.1 replaces whole resources: keep the
  connector's `hil` block in the files, or it is removed.

---

## 7. Facts with confidence

| # | Fact | Confidence |
|---|---|---|
| 1 | Gated workflow tool node pauses and resumes via notify when `SAM_FEATURE_WORKFLOW_HIL_PAUSE_RESUME=true` | high (binary catalog, migrations, messages; not executed) |
| 2 | Flag default false, controlled_availability; off on the lab | high (catalog, pod env, no log line, no table) |
| 3 | With enforcement on (default) and pause off, a gated tool node fails, never runs unapproved | high (catalog + workflows.md; one older doc says otherwise) |
| 4 | Native pause works for event_mesh-triggered workflow runs | medium (no capability check found; recipient needs a user id) - G0-19 T2 |
| 5 | Agent-level tool approval in event runs = fail-safe denial; `ask_user_question` errors | high for direct agent targets, medium for agent nodes inside event-triggered workflows |
| 6 | In WebUI chats agent tool approval and `ask_user_question` work, chat + inbox, first answer wins | high (docs) |
| 7 | Prompt recipient = run's user id; no user id -> pause fails | high (schema comment + message) |
| 8 | Another user can answer only via REST with `notify:_:send_others`; UI inbox is per user | high (docs); query parameter unknown |
| 9 | Notify REST routes (`/api/v1/notify/inbox`, `/{id}/respond` with `{status,data}`) | high (route table + WebUI code) |
| 10 | Approval `data` is `{"approved": true\|false}` | medium (WebUI summariser) |
| 11 | API keys cannot call the notification service or submit tasks | high (docs) |
| 12 | Raw Keycloak access token accepted as bearer on `/api/v1/notify` | low (spec wording only) |
| 13 | Notify routes are not in the `/api/v2` OpenAPI spec | high (spec path list) |
| 14 | `hil.timeout` default 45m per entry, no documented max | high |
| 15 | Deny/timeout fail the paused node (run fails with fail_fast) | high (docs + messages) |
| 16 | Node/workflow timeouts tick during the pause | unknown |
| 17 | Paused run survives AWE restart, any replica resumes | medium-high (migration comment, catalog) |
| 18 | `on_completion` ack timeout during a pause causes redelivery and a duplicate run | medium-high (doc semantics, not tested with a pause) |
| 19 | Evaluation runs refuse HIL calls (`HIL_NO_HUMAN_IN_EVAL_RUN`) | medium-high (error-code migration) |
| 20 | Webhook channel cannot target private/in-cluster addresses; no reply path from webhook/connector channels | high (docs) |
| 21 | Enabling = one `environmentVariables` line in the Helm values (lab and AKS) | high (chart comment, shared env ConfigMap) |
| 22 | `inboxCreated` broker signal usable for push to our monitor | low (topic exists, payload unknown) |
