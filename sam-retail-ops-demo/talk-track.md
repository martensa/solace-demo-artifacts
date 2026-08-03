# Event-Driven Retail Operations — Live Demo Script

The complete 20-minute demo script for Solace Agent Mesh v2:
what to say, what to click, and how to recover. This file is
the single source of truth — pre-flight, fallbacks and known
limits live in the appendices at the end.

Conventions: **DO** = click path, **SAY** = spoken line
(shorten freely, keep the bold claims). Slide numbers refer to
`slides/SAM v2 – AI Worker Lifecycle Meetup.pptx` (slides 3
and 4 are used). All verified numbers are from live runs on
2026-08-03.

Flow note: the AI Builder is kicked off EARLY (right after the
agent roster) so the build runs in the background during the
platform tour — no dead air waiting for the Builder.

---

## Personas and RBAC — who is logged in when

All demo users live in Keycloak (`solace-lab` realm, password =
username); their groups map to SAM RBAC roles via claim
mappings, so what each window may see and do is enforced by the
platform, not by discipline. Order of appearance:

| # | User | Where | Role (scopes) | Beats |
|---|------|-------|---------------|-------|
| 1 | `sam_admin` | Browser A | bootstrap admin (full) | Tour (3, 5), Builder (4, 6.1), first-day test (6.2), Evals (8.5) |
| 2 | `power_user` | Browser B | ops: invoke agents/workflows, manage connectors, builder read-only | Activities (7.4); the event-triggered runs are attributed to it (`defaultUserIdentity`) |
| 3 | `data_engineer` | Claude Code | invoke agents/workflows, read/create connectors | MCP finale (7.6) |
| 4 | `viewer` (optional) | Incognito | chat only | Security aside: no Builder menu, fewer agents |

Evals note: stay on `sam_admin` for 8.5 — evaluation management
(datasets, evaluators, experiments) is not part of the demo
roles' scope set. Nice framing when asked: hiring, quality
gates and audits are management concerns; operating and using
the workers is delegated.

---

## Timing at a glance (20:00 total)

| Section | Window | Content |
|---|---|---|
| 1 | 0:00–1:30 | Scenario (slide 3) |
| 2 | 1:30–2:30 | Lifecycle (slide 4) |
| 3 | 2:30–3:30 | Hiring: the roster and the gap |
| 4 | 3:30–4:30 | Onboarding kickoff: Build with AI |
| 5 | 4:30–7:30 | Workplace tour (while the Builder runs) |
| 6 | 7:30–9:30 | Deploy + first-day test |
| 7 | 9:30–16:00 | Teamwork: shop → incident → Claude Code |
| 8 | 16:00–18:45 | Improvement: dashboard, traces, evals |
| 9 | 18:45–20:00 | Wrap (slide 4) |

Overrun plan — cut in this order, none of them break the story:
(1) 5.4 Toolsets/Skills, (2) 8.1's health glance to 10
seconds, (3) the Datasets/Evaluators detour in 8.5, (4) 7.6
down to a single question and one closing sentence.

---

## 0. Stage setup (see Appendix A for the full pre-flight)

Tabs and windows, in the order you will need them:

1. Slides (slide 3 up).
2. Browser window A: `https://sam.solace.lab` logged in as
   `sam_admin@solace.lab`, sidebar on **Agent Management**.
3. Browser window B (separate profile/incognito):
   `https://sam.solace.lab` logged in as `power_user` /
   `power_user`, sidebar on **Activities**. Used only in 7.4 —
   Activities is a PER-USER view (admins included), and the
   incident tasks are attributed to power_user.
4. Shop page: `sam-retail-ops-demo/shop/index.html` in a
   browser tab — status LED green (connected to
   `ws://localhost:8008`).
5. Claude Code window with the SAM MCP server connected AND
   authenticated as `data_engineer` / `data_engineer` (`/mcp`
   shows the entrypoint's tools). The developer persona runs
   under this user on purpose: its role carries
   `agent:*:invoke`, and the governance dashboard later shows
   the IDE queries under `data_engineer@solace.lab` — do the
   OAuth roundtrip BEFORE the demo, never on stage.
6. Grafana tab 1: `https://monitoring.solace.lab` logged in,
   folder **SAM** → dashboard **SAM Retail Ops Demo** open
   (10 s refresh, time range "Last 1 hour" — widen it if your
   last incident run is older).
7. Grafana tab 2: **Explore → Tempo** with the search
   `sam-solace-lab/a2a` already executed and one trace OPEN —
   8.3 is then a single tab switch, no live typing.
8. Terminal in the repo root (fallback commands ready).

Optional cold open (zero risk, strong hook): before slide 3,
show a finished incident report from rehearsal traffic
(screenshot is fine) and say: "Four minutes after a customer
hit an out-of-stock error, this root-cause report existed. No
human wrote it. The next twenty minutes show you the workforce
that did."

---

## 1. Scenario — slide 3 (0:00–1:30)

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
> One naming thing up front, because there are two meshes
> tonight: the **event mesh** is the broker network moving the
> events — think Kafka topics plus dynamic routing across
> brokers. The **agent mesh** is the AI-worker platform living
> on top of it. When I say 'the mesh', I mean the event mesh —
> the wires.
>
> The interesting part is at the top: the online shop publishes
> every order as an event onto the mesh. Most orders succeed.
> Some fail — out of stock, out of season, broken master data.
> And nobody notices until a customer complains.
>
> Today, AI workers notice — before anyone files a ticket.
> Everything you'll see runs on Kubernetes, on my laptop,
> against a real Solace broker."

---

## 2. The lifecycle — slide 4 (1:30–2:30)

**DO**: Slide 4 ("The demo in the lifecycle").

**SAY**:

> "We treat AI agents like employees, not like scripts. And
> employees have a lifecycle: you **hire** them, you **onboard**
> them with system access, they do **teamwork**, and you
> **measure and improve** them. That lifecycle is the red
> thread of this demo.
>
> Concretely, in the next eighteen minutes: I'll show you the
> team we already have and hire a brand-new worker live — an
> analyst for the store receipts in MongoDB. While the platform
> onboards him, I'll give you a tour of his new workplace. Then
> teamwork: a customer order fails in the shop and a team of
> agents investigates it, triggered by the event itself. And at
> the end we measure everything: latency, tokens, cost per
> user, quality."

---

## 3. HIRING — the roster and the gap (2:30–3:30)

**DO**: Switch to browser window A (`sam_admin`), sidebar →
**Agent Management**. (You verified the POS analyst and the
`retail-poslog` connector are absent during pre-flight —
Appendix A item 5; Agent Management is the source of truth.)

**SAY**:

> "This is the team we already hired — and note that I'm
> logged in as the **admin**, the hiring manager; remember WHO
> does what, it will show up on a bill later. An
> **Orchestrator** — the team lead, the only agent that
> delegates to others. Three query experts — **CRM**, **OMS**,
> **PDM** — one per system, each bound to its own connector. A
> confirmation clerk for routine work, and two report
> specialists, including the **Order Incident Reporter** — a
> pure merge agent: zero tools, its only job is turning
> specialist findings into one incident report. Job
> descriptions instead of prompts, if you like.
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

**Break glass** (Builder fails or stalls — see Appendix C for
the failure signature): run this in the terminal — it creates
the identical connector + agent declaratively in ~20 s
(requires the pre-flight `sam auth login`), then continue at
6.2:

```bash
cd ~/Documents/GitHub/solace-demo-artifacts/sam-retail-ops-demo/fallback && sam config apply
```

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

Toolsets: data analysis and artifact tools. Model: reasoning.
```

**SAY** (while pasting and sending):

> "This prompt is a job posting: role, responsibilities,
> expectations — including domain rules like 'voided receipts
> don't count as revenue'. And below that, the onboarding
> package: system access. The Builder will create a **MongoDB
> connector** to the POSLOG database — with a read-only service
> account, not an admin login. Note what I did **not** paste:
> no API key, no model endpoint. The agent gets a model
> **alias** — and deliberately the `reasoning` tier: an analyst
> doing data work gets the cost-efficient DeepSeek model, not
> the premium tier. Credentials live in the connector, scoped
> read-only.
>
> Hiring takes a minute or two — so while HR does the
> paperwork, let me show you around the new colleague's
> workplace."

---

## 5. The workplace tour — while the Builder runs (4:30–7:30)

Keep each stop to two or three sentences. Glance at the
Builder tab between stops; do not comment on it until 6. The
tour is elastic filler: extend 5.3 if the Builder is slow, cut
5.4 if it finished early.

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

### 5.2 Connectors, Entrypoints (30 s each)

**DO**: Sidebar → **Connectors**, then **Entrypoints**.

**SAY** (Connectors — adapt to what the screen shows):

> "Three Postgres connectors — CRM, OMS, PDM. And look at this:
> **retail-poslog** just appeared — the Builder created it a
> moment ago as part of the onboarding. Read-only service
> account, one database, one collection."

**SAY** (Entrypoints):

> "Entrypoints are the doors into the mesh — and chat is only
> one of them. `developer-mcp` exposes the whole team as MCP
> tools — my IDE talks to these agents; you'll see that at the
> end. And `shop-events` subscribes to order topics on the
> broker and triggers agents on events. That's the door the
> failed order will come through in a few minutes."

### 5.3 Models — multi-model by task (1 min)

**DO**: Sidebar → **Models**. Scroll so all nine are visible.

**SAY**:

> "Nine model aliases, three vendors — Anthropic, DeepSeek,
> Qwen — all behind one LiteLLM proxy. The point of the alias:
> an agent binds `workflow` or `fast`, never a vendor, never an
> API key. Swapping the model behind an alias needs no agent
> change and no restart.
>
> And we route by task: routine order confirmations run on
> **Haiku**, the analyst we're hiring runs on **DeepSeek**, the
> incident report merge on **Sonnet 5**, and the heavy
> orchestration on **Opus**. You'll see all four in the
> dashboards later — and every parameter here follows the
> vendor's own guidance. Fun fact: the Claude 5 family doesn't
> even accept a temperature anymore."

### 5.4 Toolsets and Skills (30 s — first cut on overrun)

**DO**: Sidebar → **Toolsets**, then **Skills**.

**SAY**:

> "Toolsets are capabilities — data analysis, artifacts, web.
> Skills are **versioned knowledge**: these `retail-*-schema`
> bundles teach the agents each database schema and its traps.
> Training material in git, not prompt spaghetti."

---

## 6. ONBOARDING complete — deploy and first task (7:30–9:30)

### 6.1 Review and deploy

**DO**: Back to the **Builder** tab. Point at the generated
system prompt and the connector binding, then **Deploy**.

**SAY**:

> "HR is done. Here's the generated worker: my job posting
> turned into a system prompt, the MongoDB connector bound, the
> model alias attached. One important detail happened
> underneath: the platform **introspected the schema** — it
> sampled a hundred documents from the collection, so the agent
> knows the real document shape, not just my description.
> Deploy — contract signed, badge issued."

(If the deploy spinner lingers:)

> "While the badge prints — the agent is registering itself on
> the mesh right now, which is why the Orchestrator will find
> it without any wiring from me."

### 6.2 First day at work — talk to the data

**DO**: Still in window A (`sam_admin` — the hiring manager
checks their new hire personally): open **Chat**, select
**Retail POS Analyst**, and ask:

```text
How often was the Tropical Acai Smoothie Bowl (SMT_ACAI_16OZ)
sold at the registers, and were any of those transactions
voided? Short answer with numbers.
```

Expected (verified, ~21 s on DeepSeek): 5 receipts in total —
4 valid sales plus 1 void, 7 units overall (Miami stores,
`MIA-…` receipt numbers); the void is excluded from revenue.
Exact phrasing varies per run; the receipt/void/unit counts do
not.

**SAY** (while it runs):

> "First day at work — a real question against the real
> MongoDB. It writes an aggregation pipeline, unwinds the line
> items, filters the voids — exactly the domain rules from the
> job posting. And it's answering on **DeepSeek** — remember,
> we hired this analyst onto the cost-efficient reasoning
> tier."

**SAY** (when the answer lands):

> "Four clean register sales, one void correctly excluded.
> Keep that in mind — the registers sell this smoothie bowl
> just fine. Now watch what happens when a customer tries to
> order the same product **online**."

---

## 7. TEAMWORK — real-time retail ops (9:30–16:00)

### 7.1 The shop — orders are events (30 s)

**DO**: Switch to the shop tab. Point at the green status LED.

**SAY**:

> "This is Acme's online shop — and this browser tab is
> connected **directly to the Solace broker** over WebSocket;
> that's what the green light means. On Kafka, that's a REST
> proxy you build and run — here the browser is a first-class
> event client. Every order becomes an event on a topic like
> `acmeretail/shop/order/created/...`, and the shop also
> **subscribes** to the result topics — whatever the agents
> produce comes back into this page."

### 7.2 The good case — Opus One (45 s)

**DO**: Click **Order** on the Opus One Napa Valley 2019 card
($425).

**SAY** (one sentence — the confirmation lands in ~7 s; let
its arrival interrupt you, that interruption IS the beat):

> "A premium order — 425 dollars — and the **Order
> Confirmation Clerk**, a deliberately small worker on the
> Haiku fast tier, is already checking it—"

**SAY** (as it lands):

> "—and there it is. Seven seconds: returning customer, the
> product has sold before, order looks good. That cost about
> **three cents**, because routine, high-volume work runs on
> the cheap tier. No human touched it."

### 7.3 The failure — Acai Bowl (45 s, kick off + narrate)

**DO**: Click **Order** on the Tropical Acai Smoothie Bowl
card. The shop publishes a FAILED order event
(`OUT_OF_STOCK`) — point at the status card.

**SAY**:

> "Now the interesting one. Remember: the registers sell this
> bowl every day — our new analyst just proved it. But the
> online checkout **fails**: out of stock. Classic channel
> conflict, and normally this dies in a log file.
>
> Not here. The failed-order event just hit the mesh, and the
> entrypoint handed it to the **Orchestrator** with one job:
> investigate. It is now delegating — in parallel — to the OMS
> expert, the PDM expert, and the analyst we hired **a few
> minutes ago**. This takes two-and-a-half to four minutes, so
> let's watch the team work."

### 7.4 Watch the team — Activities (up to 3 min, elastic)

**DO**: Switch to browser window B (`power_user`) →
**Activities** → open the NEWEST task (the Orchestrator run —
event-triggered tasks are attributed to `power_user` via the
entrypoint's `defaultUserIdentity`, so they appear in THIS
window, not in the admin's; Activities is per-user for
everyone. There is deliberately NO workflow run — the incident
path runs through the Orchestrator, see Appendix C). Show the
flow graph building up; click into one delegation branch.

**SAY**:

> "Notice I switched users: this is the **operations view** —
> the event-triggered runs belong to the power user, not to the
> admin. This is the live task graph. The Orchestrator in the
> middle; the parallel delegations fanning out — OMS, PDM, and
> the new POS analyst. Every edge here is an **A2A message** —
> agent-to-agent, the protocol the agents speak — and it
> travels as an ordinary event over the broker, not an
> in-process call. No bespoke RPC layer, no service registry:
> each of these agents could run in a different cluster and
> this picture wouldn't change. And hold one thought: every one
> of these edges is being **traced inside the broker** — I'll
> show you in a minute.
>
> [Click a branch] Inside a branch you see the agent's steps:
> the LLM call, the connector query, the answer. Look at the
> model per step — the merge runs on Sonnet 5, the SQL
> specialists on Opus, and the POS branch on DeepSeek. Three
> models in one investigation, each where it earns its keep."

Filler beats while waiting (priority order, drop from the
bottom; fast run = beat 1 only):

1. Narrate branches as they complete: "OMS just came back —
   one specialist done; the merge starts when all three
   report."
2. "The specialists each check their own system — the same
   division of labor you'd give three human analysts; it's
   just seconds instead of a meeting."
3. Preview the **Performance** tab: "after completion there's
   a Gantt view of who worked when — we use it in reviews."

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
> to triaged incident: **no human in the loop**."

Anchor the summary on the three data-stable findings (PDM
stock-0 masking, POS keeps selling, loyal repeat customer) —
severity and exact unit counts vary between runs; the three
findings do not.

### 7.6 Finale — the developer in Claude Code (1 min hard cap)

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

> "Last stop: the developer who has to fix this — logged in as
> the **data engineer**, allowed to invoke agents, nothing
> more. Same team, plugged into the IDE via the MCP entrypoint.
> [Answer lands] Stock level zero, 'Made to Order' — the
> developer verifies the root cause against the same specialist
> the incident team used, without leaving the IDE. One team,
> three doors: the web UI, events, MCP."

---

## 8. IMPROVEMENT — measure the workforce (16:00–18:45)

The whole section lives in ONE Grafana dashboard with a guided
top-to-bottom flow — scroll, don't click around. Your
rehearsal and demo traffic is real data here.

### 8.1 Health and speed — rows 1–2 (45 s)

**DO**: Switch to Grafana tab 1 (dashboard **SAM Retail Ops
Demo**). One glance at row 1, then scroll to row 2 ("Request
duration p50/p95", "LLM latency p95 by model").

**SAY**:

> "Last lifecycle stage: improvement — and the first rule is:
> measure. Same Prometheus, same Grafana your ops team already
> uses. Row one: all three runtime components up, broker
> connected, our demo traffic visible. Row two is the one I
> like: **LLM latency per model**. Remember we route by task?
> Here you SEE that decision — Haiku answers in seconds,
> DeepSeek and Sonnet 5 mid-range, Opus takes its time on the
> hard work. Model routing isn't ideology — it's a latency and
> cost curve you can watch."

### 8.2 Cost, chargeback and audit — rows 3–4 (1 min)

**DO**: Scroll to row 3 ("Token rate by model/type" and the
table "Token chargeback by user"), then glance at row 4.

**SAY**:

> "The question every CFO asks: what does this cost — and WHO
> is spending it? Left: token rate per model, from the runtime
> metrics. Right: the chargeback table — from the **platform
> database**, per task, per user. Not an estimate.
>
> Look at the names: **power_user** — operations, the
> event-triggered incident runs, the biggest block.
> **sam_admin** — the hiring manager: Builder and first-day
> test. **data_engineer** — the IDE queries. Three personas,
> three budgets. And row four underneath is the audit stream:
> every tool execution with its user identity — every MongoDB
> query our new analyst ran today is in there, attributed,
> next to auth failures and RBAC denies."

### 8.3 The proof — Tempo (45 s)

**DO**: Switch to Grafana tab 2 (the pre-opened trace — no
live typing).

**SAY**:

> "And if you don't believe dashboards: raw telemetry. **No SDK
> in the agents produced this — the broker emitted it.** On
> Kafka, tracing message flows means instrumenting every
> client; here the event mesh itself is traced. The root span
> is the broker **receiving** a publish — the producing pod's
> identity is in the attributes — and every child span is one
> **delivery** to a subscriber queue, each with its own
> latency. The incident investigation you just watched exists
> here as hard distributed-tracing evidence, in the same Tempo
> your other services trace into."

### 8.4 (reserved — audit content merged into 8.2)

### 8.5 Quality — offline evals (1:15)

**DO**: Back to browser window A (`sam_admin` — evaluation
management needs admin scopes, see the RBAC table) →
**Evaluations**. One sentence each on **Datasets** and
**Evaluators** (cut this detour on overrun), then open
**Experiments** → **retail-ops-model-benchmark** → the latest
run group with the three per-model runs.

**SAY**:

> "Quality is the hard metric — so we treat it like software:
> **experiments validate that agents respond consistently and
> safely** — you coach the agent into the right behaviour
> BEFORE you ship, and you catch regressions whenever a
> prompt, a model or a tool changes. Datasets are versioned
> question sets with expected answers; evaluators are the
> judges — eleven ship out of the box, from LLM judges to
> heuristic matchers.
>
> This experiment ran the **same agent, same six questions,
> same two judges — under three different models**. Fair
> warning: six questions is a smoke suite, not a paper — the
> **method** is the point. And the method delivered: **Haiku,
> the cheapest model in the house, scores identically to
> Sonnet 5** — and a nose ahead of our Opus production tier on
> factuality. For routine CRM questions, the premium model
> buys you nothing — measured, not guessed. Rerun it on new
> data next month and you get quality as a **trend line per
> model**. And since the CLI run has a threshold and an exit
> code, it's a **CI gate**: if quality drops, the pipeline
> goes red before your users notice."

(If someone asks, offer to run the gate live during Q&A —
commands in Appendix D. Never start it inside the talk.)

Measured reference (2026-08-03 pre-runs, Factuality / LLM
Judge): Haiku 0.83/0.88 — Sonnet 5 0.83/0.88 — Opus 4.8
(production gate) 0.79/0.88, 11 of 12 checks passed — DeepSeek
V3.2 0.79/0.75, all runs passing overall. Benchmark runs
execute in parallel and share the runtime, so per-run durations
are not comparable latency numbers — use the dashboard's
LLM-latency panel for that.

---

## 9. WRAP — the lifecycle, closed (18:45–20:00)

**DO**: Bridge over the window switch, back to the slides —
slide 4 (the lifecycle mapping).

**SAY**:

> "Health, speed, cost, audit, quality — that's the whole
> improvement stage. Let's step back and close the loop.
>
> **Hiring**: you saw the roster, and a job posting turned
> into a worker. **Onboarding**: the Builder wired it to
> MongoDB with scoped credentials, and it answered its first
> question two minutes later. **Teamwork**: a customer order
> failed, and a team of agents — including the one we hired
> during this talk — investigated it end to end, triggered by
> the event, and told the developers which line of code to
> fix. **Improvement**: everything measured — health, speed,
> cost per person, audit trail, and a quality gate in CI.
>
> The point is not that agents can answer questions. The point
> is that you can run them like a **workforce**: hired,
> onboarded, collaborating over an event mesh, and accountable
> — with **no human in the loop** on the routine path. That's
> what an event-driven agent platform buys you.
>
> Everything you saw — the shop, the agents, the dashboards,
> the eval suite — is on my GitHub, and the retail use case is
> written up on my blog. Thank you — questions?"

---

## Appendix A — Pre-flight checklist (15 min before going live)

1. `docker ps` — solace-1/2, otel-collector, generator,
   consumer, postgres, pgadmin, retail-pos-mongo all running
   (postgres/pgadmin are host containers and stay Exited after
   a reboot — `docker start postgres pgadmin`).
2. `kubectl get pods -n sam-solace-lab` — all Running. Rule:
   after a simultaneous gwe+awe restart, restart awe once more
   AFTER gwe is ready (DB-agent loading race).
3. Fresh CLI login (needed for fallbacks and evals):
   `sam auth login solace-lab --url https://sam.solace.lab`
   (as `sam_admin`).
4. Windows and tabs per section 0 (A: sam_admin, B:
   power_user, shop, Claude Code as data_engineer with `/mcp`
   verified, two Grafana tabs incl. the pre-opened trace).
5. Retail POS Analyst AND `retail-poslog` connector absent
   (Agent Management / Connectors → delete if present; a plain
   `./install.sh` leaves exactly this clean state).
6. Model upstreams green:
   `cd agent-mesh-deployment/scripts/models && ./apply-models.sh --probe-only`
7. Kyverno healthy: `kubectl get pods -n kyverno` all Running —
   a crashlooping admission controller silently blocks EVERY
   pod change (typical after the Mac switches networks; fix in
   Appendix C).
8. Monitoring healthy: `kubectl get pods -n monitoring` —
   especially `tempo-0` (an OOM during block compaction shows
   as exit 137 / "Error", NOT OOMKilled; limit is 4Gi since
   2026-08-03).
9. If str restarted since the last connector change: smoke-test
   ALL connector agents (CRM/OMS/PDM/POS + Clerk, one short
   question each). On "data source offline": touch the
   connector description + `sam config apply` (the update
   re-pushes the tool package; an agent redeploy does NOT).
10. sam-VPN spool check (the 10-GB trap) — healthy is under
    ~2 GB:

    ```bash
    curl -s -u admin:admin "http://localhost:8080/SEMP/v2/monitor/msgVpns/sam?select=msgSpoolUsage"
    ```

11. Shop smoke test: fire one Pike Place test order, wait for
    the Clerk confirmation event (~7 s), then reload the page
    to clear the event log for a clean stage.
12. Eval pre-runs exist (Experiments → both experiments show a
    completed run). If not (fresh platform): run them now,
    ~15 min total — commands in Appendix D.
13. Grafana time range covers your latest incident run
    (default "Last 1 hour").
14. Escalation ladder for a TOTAL beat failure: (1) apply the
    fallback (`sam-retail-ops-demo/fallback`, ~20 s); (2) show
    the verified Retail-360 workflow as the replacement demo
    (slide 4); (3) Grafana always runs — the Improvement part
    is failure-proof.

Setup from scratch (fresh platform): run the base one-click
deployment in `agent-mesh-deployment/` (Keycloak scripts,
`load-images.sh`, `start.sh`, `sam auth login`,
`apply-rbac.sh`), then `./install.sh` in this directory — it
layers the demo idempotently (data stores, retail core,
models, mesh overlay, eval package, dashboard).
`./uninstall.sh` removes the demo again and leaves the base
platform reusable for other demos.

## Appendix B — Extra queries and product stories

Backup "talk to my data" queries (all verified against the
data; use for Q&A or buffer time):

1. CRM warm-up: "Who are our top 10 customers by lifetime
   spend? Show a chart."
2. OMS+PDM (to the Orchestrator): "Which products generated
   revenue, and where are margin or inventory critical?"
3. Mongo+OMS channel comparison: "Compare Opus One Napa Valley
   2019 revenue: online orders vs. POS registers, by store."
4. CRM+PDM+Mongo (Orchestrator delegation): "Who bought the
   Shaved Black Truffle outside its season, on which channel,
   and what does that say about our data quality?"

The five shop products (real data stories):

| Product | Outcome | Story |
|---|---|---|
| Opus One Napa 2019 ($425) | OK | top revenue, 67 in stock |
| Pike Place Roast ($16.99) | OK | everyday item, 187 in stock |
| Acai Bowl ($14.99) | FAIL OUT_OF_STOCK | stock 0 masked by "Made to Order"; buyer is a tourist without loyalty card |
| Black Truffle ($159.99) | FAIL OUT_OF_SEASON | season Nov–Mar, sold in October; lowest margin in the catalog (28.1%) |
| Alpine Trail Mix ($12.99) | FAIL DATA_QUALITY | inventory_status holds the brand name "Bulk Bin"; only fractional-quantity booking (2.3) |

The truffle order is the optional second incident (different
root cause) if you have buffer time in section 7.

References for the wrap: blog
`https://blog.alexandermartens.de/unleash-revenue-potential-agentic-ais-impact-on-point-of-sale-analytics`,
repo `https://github.com/martensa/solace-sam-demos/tree/master/sam-retail`.
The `poslog_transactions` collection holds the blog's original
receipts plus the demo stories in the same document schema.

## Appendix C — Known limits and recovery (moderate honestly)

- **Builder can die with "Expected toolResult blocks at
  messages.N"** (BedrockException): SAM 2.225.14 assembles a
  malformed history on long Builder conversations; the
  conversation is poisoned — do NOT keep typing. Start a FRESH
  Build with AI with the same prompt, or break glass (section
  4). Keep the Builder chat to ONE prompt; if it asks more
  than one clarifying question, break glass.
- **Never open the Builder's Test tab on stage**: its plan
  generator is killed at a hard 30 s while its LLM call needs
  ~106 s on the Opus tier it insists on using — no configurable
  surface changes that model (vendor ticket filed). If asked:
  "known issue in this build; filed upstream."
- **Event-trigger → workflow is defective in 2.225.14**: with
  `targetWorkflowName` the entrypoint delivers an EMPTY A2A
  message (sniff-verified). That is WHY the incident path runs
  through the Orchestrator (`targetAgent`) and why Activities
  shows a task, not a workflow run. The workflow stays deployed
  for the 5.1 explanation.
- **An STR restart loses ALL connector tool packages** (Mongo
  per-collection AND `*_sql_query_*` tools): agents report
  "data source offline", str logs "tool not in manifest".
  Recovery: minimal edit to the connector description +
  `sam config apply`; an agent redeploy does NOT help.
- **Event tasks need `defaultUserIdentity`**: without it they
  run under the gateway identity and are INVISIBLE in
  Activities (per-user view, admins included). The shop-events
  rules attribute to `power_user`.
- **After the Mac switches networks, the k3s API dies for
  pods**: Rancher Desktop pins the Mac LAN IP as
  `--node-external-ip` in `/etc/conf.d/k3s`; after a Wi-Fi/DHCP
  change the kubernetes endpoint points at a dead IP, Kyverno
  crashloops and its fail-closed webhook blocks every pod
  change — `rollout restart` even reports success without
  restarting anything. Fix (~2 min, no broker downtime):
  `rdctl shell sudo sed -i "s/OLD_IP/NEW_IP/" /etc/conf.d/k3s`,
  then `rdctl shell sudo rc-service k3s restart`, then delete
  the kyverno pods and re-check.
- **LLM budget**: the LiteLLM proxy enforces a hard cost limit
  (HTTP 429 `budget_exceeded`). Check headroom before the
  event; an incident run costs ~110–135k tokens.
- **Timing facts**: incident run 2.5–4 min. If it exceeds
  ~5 min, check Activities for a stuck node and keep narrating
  over the graph/Performance view.

## Appendix D — Commands

Fallback (POS analyst + connector, ~20 s):

```bash
cd ~/Documents/GitHub/solace-demo-artifacts/sam-retail-ops-demo/fallback && sam config apply
```

Eval runs (pre-run before the event; quality ~5 min, benchmark
~10 min):

```bash
export SAM_AUTH_TOKEN=$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/Library/Application Support/sam/auth/solace-lab.json')))['sam_access_token'])")
```

```bash
sam eval run retail-ops-quality --url https://sam.solace.lab --threshold 0.8
```

```bash
sam eval run retail-ops-model-benchmark --url https://sam.solace.lab
```

Demo install / removal on top of a running base platform:

```bash
cd ~/Documents/GitHub/solace-demo-artifacts/sam-retail-ops-demo && ./install.sh
```

```bash
cd ~/Documents/GitHub/solace-demo-artifacts/sam-retail-ops-demo && ./uninstall.sh --dry-run
```

## Appendix E — Q&A preparation (the three hardest questions)

1. **"A one-line SQL check would find stock_level=0 in
   milliseconds. Why is this an AI problem?"** — "That rule is
   obvious in hindsight — someone has to FIND the failure mode
   first, across four systems. The team does open-ended
   root-cause analysis for failures nobody has codified yet —
   and its own report proposes exactly that deterministic
   check. AI finds the rule; the rule then runs for free."
2. **"What does a Solace event mesh buy me over Kafka +
   Temporal + an agent framework?"** — "The mesh already
   carries the business events — the shop order that triggered
   everything. Agents are just more subscribers; no new
   integration layer. On top you get durable per-agent queues
   with backpressure, location transparency, and broker-side
   tracing for free — the pieces you would otherwise build."
3. **"110k tokens and 3 minutes per incident — how does that
   scale?"** — "Tiering is the point: the high-volume path is
   the 7-second Haiku clerk at cents. The deep investigation is
   a triage team for NOVEL failures, not a per-order hot path —
   in production you dedupe upstream on the mesh (topic
   filters, correlation) so one root cause triggers one
   investigation, not thousands."
