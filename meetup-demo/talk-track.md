# Talk Track — AI Worker Lifecycle on SAM v2 (Parts 1–2)

Spoken script (English) for the meetup demo, from the opening
through the end of Teamwork. Ops details (full pre-flight,
fallbacks) live in [demo-script.md](demo-script.md); this file
is what you actually say and click. Part 3 (Improvement, Wrap)
follows after the rehearsal.

Conventions: **DO** = click path, **SAY** = spoken line
(shorten freely, keep the bold claims). Slide numbers refer to
`slides/SAM v2 – AI Worker Lifecycle Meetup.pptx`.

Flow note: the AI Builder is kicked off EARLY (right after the
agent roster) so the build runs in the background while you
tour Workflows, Connectors, Entrypoints, Models and Skills —
no dead air waiting for the Builder.

---

## 0. Stage setup (5 min before going live)

Tabs and windows, in the order you will need them:

1. Slides (slide 3 up).
2. `https://sam.solace.lab` logged in as `sam_admin@solace.lab`,
   sidebar on **Agent Management**.
3. Shop page: `meetup-demo/shop/index.html` in a browser tab —
   status LED green (connected to `ws://localhost:8008`).
4. Claude Code window with the SAM MCP server connected
   (`/mcp` shows the entrypoint's tools).
5. Terminal in the repo root (fallback commands).

Quick checks: Retail POS Analyst must NOT exist (delete agent
AND `retail-poslog` connector if present); MongoDB container
up; fresh CLI login (`sam auth login solace-lab --url
https://sam.solace.lab`); model upstreams green:
`cd agent-mesh-deployment/scripts/models && ./apply-models.sh
--probe-only`; Kyverno healthy (`kubectl get pods -n kyverno`
all Running — a crashlooping admission controller silently
blocks every pod change; happens after the Mac switches
networks, see demo-script.md for the 2-minute fix).

---

## 1. Scenario — Slide 3 (0:00–1:30)

**DO**: Open on slide 3 ("Live Demo: Event-Driven Retail Ops").

**SAY**:

> "Let me set the scene. Acme Retail — stores, an online shop,
> and the classic system landscape: customer data in a CRM,
> orders in an OMS, product master data in a PDM — all
> Postgres. And the stores stream every register receipt, the
> POSLOG, over the Solace event mesh into MongoDB. This is a
> real use case — I wrote it up in a blog post on point-of-sale
> analytics; today you'll see it live.
>
> The interesting part is at the top: the online shop publishes
> every order as an event onto the mesh. Most orders succeed.
> Some fail — out of stock, out of season, broken master data.
> And nobody notices until a customer complains.
>
> Today, AI workers notice. A Solace Agent Mesh runs on this
> event mesh — agents that speak to these systems, react to
> events, and work as a team. Everything you'll see runs on
> Kubernetes, on my laptop, against a real Solace broker."

---

## 2. The Lifecycle — Slide 4 (1:30–2:30)

**DO**: Slide 4 ("The demo in the lifecycle").

**SAY**:

> "We treat AI agents like employees, not like scripts. And
> employees have a lifecycle: you **hire** them, you **onboard**
> them with system access, they do **teamwork**, and you
> **measure and improve** them. That lifecycle is the red
> thread of this demo.
>
> Concretely: I'll show you the team we already have, and hire
> a brand-new worker live — an analyst for the store receipts
> in MongoDB. While the platform onboards him, I'll give you a
> tour of his new workplace. Then teamwork: a customer order
> fails in the shop and a team of agents investigates it —
> triggered by the event, no human in the loop. And at the end
> we measure everything: latency, tokens, cost per user,
> quality."

---

## 3. HIRING — the roster and the gap (2:30–3:30)

**DO**: Switch to the SAM tab, sidebar → **Agent Management**.

**SAY**:

> "This is the team we already hired. An **Orchestrator** — the
> team lead, the only agent that delegates to others. Three
> query experts — **CRM**, **OMS**, **PDM** — one per system,
> each bound to its own connector. And two report specialists,
> including the **Order Incident Reporter** — a pure merge
> agent, it has zero tools, its only job is turning specialist
> findings into one incident report. Job descriptions instead
> of prompts, if you like.
>
> Now notice who's **missing**: nobody on this team can see the
> store registers. All that POSLOG data streaming into MongoDB —
> no analyst for it. Let's fix that. Let's hire one, right now."

---

## 4. ONBOARDING kickoff — Build with AI (3:30–4:30)

**DO**: Sidebar → **Builder** → **Build with AI** (Quick
Build). Paste the prompt below and send it. Watch for ~10 s
that it actually starts building (if it asks a clarifying
question instead, answer in one line — it is
non-deterministic). Then leave it running and move on to
section 5.

```text
Create an agent called "Retail POS Analyst".

Role: point-of-sale data analyst for Acme Retail. It answers
questions about in-store POSLOG transactions and compares the
store channel with our online orders.

Document shape of poslog_transactions (one per receipt):
store{store_id, store_name, location{city,state,region}},
register{register_id, cashier_name, shift},
receipt{receipt_number, transaction_type}, customer{customer_id,
customer_type, membership_tier}, payment{method, status},
items[{item_id, sku, name, category{main,sub}, brand, quantity,
unit_price, total_price, cost_price, margin}], totals{...}.

Responsibilities and expectations:
- Query the POSLOG data with MongoDB aggregation pipelines only;
  $unwind "$items" and match on items.sku / items.item_id.
- VOIDED receipts have receipt.transaction_type = "VOID" -
  exclude them from revenue unless asked about voids.
  items.quantity can be fractional (bulk items).
- Save large result sets as artifacts and summarize key findings.
- Explicitly call out data-quality anomalies (sales despite zero
  stock, out-of-season sales, fractional quantities).

System access (create a MongoDB connector "retail-poslog"):
- host: host.docker.internal, port 27017
- database: retail_pos, collection: poslog_transactions
- username: sam_ro, password: sam_ro (authSource retail_pos)

Toolsets: data analysis and artifact tools. Model: general.
```

**SAY** (while pasting and sending):

> "This prompt is a job posting: role, responsibilities,
> expectations — including domain rules like 'voided receipts
> don't count as revenue'. And below that, the onboarding
> package: system access. The Builder will create a **MongoDB
> connector** to the POSLOG database — with a read-only service
> account, not an admin login. Note what I did **not** paste:
> no API key, no model endpoint. The agent gets a model
> **alias**, and credentials live in the connector, scoped
> read-only.
>
> Hiring takes a minute or two — so while HR does the
> paperwork, let me show you around the new colleague's
> workplace."

---

## 5. The workplace tour — while the Builder runs (4:30–7:30)

Keep each stop to two or three sentences. Glance at the
Builder tab between stops; do not comment on it until 6.

### 5.1 Workflows — the standard operating procedure

**DO**: Paste the direct link (the workflow link in the UI is
broken in this build — known bug, use the URL). The app uses
hash routing and matches the workflow's display name:

```text
https://sam.solace.lab/#/agents/workflows/Order%20Incident%20Report
```

Fallback if the display name ever changes — the mesh card name
also works, but it embeds the platform UUID and therefore
changes on every rebuild (current value):

```text
https://sam.solace.lab/#/agents/workflows/workflow_019fad02_c0cd_79df_b36e_86194a999133
```

**SAY**:

> "Workflows are the standard operating procedures of the team.
> This one handles a failed order: three specialists — OMS, PDM,
> POS — investigate **in parallel**, and a fourth agent merges
> their findings into one incident report. Two details worth
> stealing: `fail_fast` is off — if one specialist is missing,
> the report says so transparently instead of failing. And the
> whole thing is YAML in git — I apply it with
> `sam config apply`, same as everything else you see today.
> Notice the POS node: it references the analyst we're hiring
> **right now**."

### 5.2 Connectors (30 s)

**DO**: Sidebar → **Connectors**.

**SAY** (if `retail-poslog` is already visible):

> "Three Postgres connectors — CRM, OMS, PDM. And look at this:
> **retail-poslog** just appeared — the Builder created it a
> moment ago as part of the onboarding. Read-only service
> account, one database, one collection."

**SAY** (if not yet visible):

> "Three Postgres connectors — CRM, OMS, PDM. The fourth one —
> MongoDB for the store receipts — is being created by the
> Builder as we speak; we'll see it in a minute."

### 5.3 Entrypoints (30 s)

**DO**: Sidebar → **Entrypoints**.

**SAY**:

> "Entrypoints are the doors into the mesh — and chat is only
> one of them. `developer-mcp` exposes the whole team as MCP
> tools — my IDE talks to these agents; you'll see that at the
> end. And `shop-events` is an **event-mesh entrypoint**: it
> subscribes to order topics on the broker and triggers agents
> on events. No human in the loop. That's the door the failed
> order will come through in a few minutes."

### 5.4 Models — multi-model by task (1 min)

**DO**: Sidebar → **Models**. Scroll so all nine are visible.

**SAY**:

> "Nine model aliases, three vendors — Anthropic, DeepSeek,
> Qwen — all behind one LiteLLM proxy. The point of the alias:
> an agent binds `workflow` or `expert`, never a vendor, never
> an API key. Swapping the model behind an alias needs no agent
> change and no restart.
>
> And we route by task: the incident report merge runs on
> **Claude Sonnet 5** — the `workflow` alias — while the SQL
> specialists run on Opus. Analysis on **DeepSeek**, code on
> **Qwen**, bulk work on **Haiku**. Every parameter here
> follows the vendor's own guidance — fun fact: the Claude 5
> family doesn't even accept a temperature anymore."

### 5.5 Toolsets and Skills (30 s)

**DO**: Sidebar → **Toolsets**, then **Skills**.

**SAY**:

> "Toolsets are capabilities — data analysis, artifacts, web.
> Skills are **versioned knowledge**: these `retail-*-schema`
> bundles teach the agents each database schema and its traps.
> Training material in git, not prompt spaghetti. When the
> schema changes, we ship a new skill version — we don't
> re-prompt five agents."

---

## 6. ONBOARDING complete — deploy and first task (7:30–9:30)

### 6.1 Review and deploy

**DO**: Back to the **Builder** tab. Point at the generated
system prompt and the connector binding, then **Deploy**.
(Break glass if the Builder failed:
`cd meetup-demo/fallback && sam config apply` — ~20 s, then
continue identically.)

**SAY**:

> "HR is done. Here's the generated worker: my job posting
> turned into a system prompt, the MongoDB connector bound, the
> model alias attached. One important detail happened
> underneath: the platform **introspected the schema** — it
> sampled a hundred documents from the collection, so the agent
> knows the real document shape, not just my description.
> Deploy — contract signed, badge issued. The agent is now a
> live worker on the mesh, discoverable by the Orchestrator
> like every other team member."

### 6.2 First day at work — talk to the data

**DO**: Open **Chat**, select **Retail POS Analyst**, ask:

```text
How often was the Tropical Acai Smoothie Bowl (SMT_ACAI_16OZ)
sold at the registers, and were any of those transactions
voided? Short answer with numbers.
```

Expected (verified): 4 valid sale receipts with 7 units (Miami
stores, `MIA-…` receipt numbers) plus 1 voided receipt, which
it excludes from revenue.

**SAY** (while it runs):

> "First day at work — a real question against the real
> MongoDB. It writes an aggregation pipeline, unwinds the line
> items, filters the voids — exactly the domain rules from the
> job posting."

**SAY** (when the answer lands):

> "Seven units sold across four receipts, one void correctly
> excluded. Keep this number in mind — the registers sell this
> smoothie bowl just fine. Now watch what happens when a
> customer tries to order the same product **online**."

---

## 7. TEAMWORK — real-time retail ops (9:30–15:30)

### 7.1 The shop — orders are events (30 s)

**DO**: Switch to the shop tab. Point at the green status LED.

**SAY**:

> "This is Acme's online shop — and this browser tab is
> connected **directly to the Solace broker** over WebSocket;
> that's what the green light means. Real-time retail ops:
> every order you place here becomes an event on the mesh, on a
> topic like `acmeretail/shop/order/created/...`. No REST
> gateway, no polling — the shop publishes, and anyone entitled
> can react: the OMS, analytics, and since today, our AI team.
> The shop also **subscribes** to the result topics — so
> whatever the agents produce comes back into this page."

### 7.2 The good case — Opus One (1 min)

**DO**: Click **Order** on the Opus One Napa Valley 2019 card
($425). Point at the status card ("published").

**SAY**:

> "A premium order — Opus One, 425 dollars. The event is on the
> mesh; the `shop-events` entrypoint picked it up and asked the
> OMS expert for a quick confirmation. That's the cheap,
> high-volume path: every order gets a sanity check against the
> order history — is the customer known, has the product sold
> before."

**DO**: Wait for the confirmation event to land in the shop
(typically well under a minute; keep talking).

**SAY** (when it lands):

> "There it is, back in the shop as an event: returning
> customer, the product has sold before, order looks good. A
> human never touched that."

### 7.3 The failure — Acai Bowl, 1 min (kick off + narrate)

**DO**: Click **Order** on the Tropical Acai Smoothie Bowl
card. The shop publishes a FAILED order event
(`OUT_OF_STOCK`) — point at the status card.

**SAY**:

> "Now the interesting one. Remember: the registers sell this
> bowl every day — our new analyst just proved it. But the
> online checkout **fails**: out of stock. Classic
> channel-conflict, and normally this dies in a log file.
>
> Not here. The failed-order event just hit the mesh, and the
> entrypoint handed it to the **Orchestrator** with one job:
> investigate. It is now delegating — in parallel — to the OMS
> expert, the PDM expert, and the analyst we hired **eight
> minutes ago**. The Order Incident Reporter will merge their
> findings — on Claude Sonnet 5, while the specialists run on
> Opus. This takes three to four minutes, so let's watch the
> team work."

### 7.4 Watch the team — Activities (2–3 min, while it runs)

**DO**: SAM tab → **Activities** → open the NEWEST task (the
Orchestrator run — event-triggered tasks are attributed to
`sam_admin` via the entrypoint's `defaultUserIdentity`, so they
appear in your list; there is deliberately NO workflow run, the
incident path runs through the Orchestrator). Show the flow
graph building up; click into one delegation branch.

**SAY**:

> "This is the live task graph. The Orchestrator in the middle;
> the parallel delegations fanning out — OMS, PDM, and the new
> POS analyst. Every edge here is an **A2A message over the
> event mesh**, not an in-process call: each of these agents
> could run in a different cluster, a different region, and
> this picture wouldn't change.
>
> [Click a branch] Inside a branch you see the agent's steps:
> the LLM call, the connector query, the answer. Note the
> model per step — the merge runs on Sonnet 5, the specialists
> on Opus. After completion there's a Performance tab — a
> Gantt view of who worked when, which we'll use in the
> improvement part."

Filler lines while waiting (pick as needed):

> "The specialists each check their own system: OMS — has this
> customer or product ordered online before? PDM — what does
> master data say about stock and status? POS — what do the
> registers say? That's the same division of labor you'd give
> three human analysts; it's just seconds instead of a
> meeting."

### 7.5 The incident report lands (1 min)

**DO**: Switch to the shop tab when the incident event
arrives; open/scroll the incident card.

**SAY**:

> "And there's the report — published back onto the mesh, into
> the shop, and to the OMS team. Look at what the team found:
> this is **not actually a stockout** — it's an
> **inventory-modeling mismatch**. 'Made to Order' items carry
> a stock level of zero **by design**; the stores understand
> that and sell this bowl all day, but the online checkout
> reads the zero literally and turns the customer away.
>
> And the detail that makes it hurt: the customer it turned
> away is a **loyal repeat buyer of exactly this item** — the
> stores know them, the webshop rejected them.
>
> So the fix isn't 'order more açaí'. It's one line of checkout
> validation logic — and the report already tells the
> developers **which fields to look at**, and to audit every
> other Made-to-Order SKU for the same trap. From failed order
> to triaged incident: no human in the loop."

Anchor the summary on the three data-stable findings (PDM
stock-0 masking, POS keeps selling, loyal repeat customer) —
severity and exact unit counts vary between runs; the three
findings do not.

### 7.6 Finale — the developer in Claude Code (1.5 min)

**DO**: Switch to the Claude Code window. Briefly show `/mcp`
(the SAM entrypoint and its tools), then send:

```text
Ask the Retail PDM Query Expert: show the product master data
for the Tropical Acai Smoothie Bowl (SMT_ACAI_16OZ) --
stock_level, inventory_status, seasonality and margin. Short
answer.
```

Expected: stock_level 0 and inventory_status "Made to Order" —
the same facts the incident report named as root cause.

**SAY**:

> "Last stop: the developer who has to fix this. They live in
> the IDE — so the same agent team is plugged into Claude Code
> via the **MCP entrypoint** you saw earlier. Same workers,
> same OAuth login, same RBAC — just a different door.
>
> [Answer lands] Stock level zero, status 'Made to Order' —
> the developer verifies the root cause against the same
> specialist the incident workflow used, without leaving the
> IDE. One team, three surfaces: the web UI for the OMS team,
> events for the systems, MCP for the developers."

**Transition to Part 3 (Improvement)**:

> "So the team works. But would you run this in production
> without knowing what it costs, how fast it is, and who uses
> it? Neither would I — let's measure it."

---

## Notes for the rehearsal

- The direct workflow link needs the HASH route (`/#/agents/
  workflows/...`) — without the `#` the app falls back to the
  start page. The display-name variant survives platform
  rebuilds (`display_name` is config-managed); the
  `workflow_<uuid>` variant must be regenerated after every
  rebuild. The page resolves the link against the live agent
  cards, so the workflow must be DEPLOYED for the link to work.
- Builder kickoff: after sending the prompt, confirm for ~10 s
  that it is building before you switch to the tour. If it asks
  clarifying questions, answer in one line. If it errors, run
  the fallback DURING the tour and skip 6.1's review line.
- KNOWN BUILDER FAILURE (hit in rehearsal): a long build
  conversation can die with `Expected toolResult blocks at
  messages.N ... BedrockException`. That means SAM sent a
  malformed history (a tool_use without its toolResult -- SAM
  2.225.14 bug) and the SAME conversation will fail on every
  further message; the proxy's -anthropic/-vertex fallback
  routes are dead, so there is no cushion. Recovery: do NOT
  type into the broken chat. Either start a FRESH Build with
  AI with the same prompt (usually succeeds -- the bug is
  length/state dependent), or break glass with the fallback.
  Before the fresh attempt, check for partial state: delete a
  half-created `retail-poslog` connector and any draft POS
  agent first (Connectors / Agent Management).
- Keep the Builder chat to ONE prompt, no follow-ups. If it
  asks more than one clarifying question, break glass -- every
  extra turn raises the malformed-history risk.
- The Builder's Test engine is BROKEN in 2.225.14 (vendor bug,
  fully diagnosed): its plan generator is killed at a hard 30 s
  while its LLM call needs ~106 s on the Opus tier it insists on
  using -- no configurable surface changes that model. Do not
  touch the Test tab on stage; the first-day test in 6.2 uses
  plain Chat by design.
- The tour is elastic filler: if the Builder is still running
  after 5.5, extend Models (talk vendors/params); if it
  finished early, cut 5.5 short.
- Incident run: 3.5–4 min, ~110k tokens (verified). Never wait
  silently — Activities (7.4) is the designated filler. If the
  run exceeds ~5 min, check Activities for a stuck node and
  keep narrating over the Performance/graph view.
- Shop LED red: broker or port 8008 down — check the solace-1
  container, then reload the page.
- Claude Code MCP: verify the OAuth session BEFORE the demo
  (`/mcp` → tools listed); re-auth takes a browser roundtrip
  you don't want live.
- After the rehearsal, delete the Retail POS Analyst agent AND
  the `retail-poslog` connector again so the live demo starts
  clean (Agent Management → delete; Connectors → delete).
