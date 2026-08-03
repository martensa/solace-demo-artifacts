# Talk Track — AI Worker Lifecycle on SAM v2 (Part 1)

Spoken script (English) for the meetup demo, from the opening
through the end of Onboarding. Ops details (pre-flight checks,
fallbacks, timings) live in [demo-script.md](demo-script.md);
this file is what you actually say and click. Part 2 (Teamwork,
Improvement, Wrap) follows after the rehearsal of Part 1.

Conventions: **DO** = click path, **SAY** = spoken line
(shorten freely, keep the bold claims). Slide numbers refer to
`slides/SAM v2 – AI Worker Lifecycle Meetup.pptx`.

---

## 0. Before you start (2 min before going live)

- Log in at `https://sam.solace.lab` as `sam_admin@solace.lab`
  and leave the tab open.
- Verify the Retail POS Analyst does NOT exist (Agent
  Management) — it gets hired live. If it exists, delete it.
- MongoDB container up (`docker ps | grep mongo`), model
  upstreams green:
  `cd agent-mesh-deployment/scripts/models && ./apply-models.sh
  --probe-only`.
- Keep this file open on the second screen for the Builder
  prompt and the test query.

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
> Concretely, in the next fifteen minutes: I'll show you the
> team we already have — that's Hiring. I'll onboard a brand-new
> worker live, with the AI Builder — an analyst for the store
> receipts in MongoDB. Then teamwork: a customer order fails in
> the shop and a team of agents investigates it — triggered by
> the event, no human in the loop. And at the end we measure
> everything: latency, tokens, cost per user, quality."

---

## 3. HIRING — the team on the platform (2:30–5:30)

Login is already done (`sam_admin`). This whole section is a
guided tour; keep each stop to two or three sentences.

### 3.1 Agent Management — the roster

**DO**: Sidebar → **Agent Management**.

**SAY**:

> "This is the team we already hired. An **Orchestrator** — the
> team lead, the only agent that delegates to others. Three
> query experts — **CRM**, **OMS**, **PDM** — one per system,
> each bound to its own connector. And two report specialists,
> including the **Order Incident Reporter** — a pure merge
> agent, it has zero tools, its only job is turning specialist
> findings into one incident report. Job descriptions instead
> of prompts, if you like."

### 3.2 Workflows — the standard operating procedure

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
> `sam config apply`, same as everything else you'll see today."

### 3.3 Connectors, Entrypoints (30 s each)

**DO**: Sidebar → **Connectors**, then **Entrypoints**.

**SAY** (Connectors):

> "Three Postgres connectors — CRM, OMS, PDM. Notice what's
> missing: nothing talks to the MongoDB with the store receipts
> yet. That's the gap we'll close in a minute."

**SAY** (Entrypoints):

> "Entrypoints are the doors into the mesh — and chat is only
> one of them. `developer-mcp` exposes the whole team as MCP
> tools — my IDE talks to these agents. And `shop-events` is an
> **event-mesh entrypoint**: it subscribes to order topics on
> the broker and triggers agents on events. No human in the
> loop. That's the door the failed order will come through
> later."

### 3.4 Models — multi-model by task

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
> **Qwen**, bulk work on **Haiku**. You'll see the different
> models per step later in the observability part, and every
> parameter here follows the vendor's own guidance — fun fact:
> the Claude 5 family doesn't even accept a temperature
> anymore."

### 3.5 Toolsets and Skills (30 s)

**DO**: Sidebar → **Toolsets**, then **Skills**.

**SAY**:

> "Toolsets are capabilities — data analysis, artifacts, web.
> Skills are **versioned knowledge**: these `retail-*-schema`
> bundles teach the agents each database schema and its traps.
> That's training material in git, not prompt spaghetti. When
> the schema changes, we ship a new skill version — we don't
> re-prompt five agents."

---

## 4. ONBOARDING — hire the POS Analyst live (5:30–9:30)

### 4.1 Build with AI

**DO**: Sidebar → **Builder** → **Build with AI** (Quick
Build). Paste the prompt below, send it, and narrate while it
builds. (Break glass if the Builder misbehaves:
`cd meetup-demo/fallback && sam config apply` — then continue
at 4.3.)

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

**SAY** (while pasting):

> "Now we hire. This prompt is a job posting: role,
> responsibilities, expectations — including domain rules like
> 'voided receipts don't count as revenue'. And below that, the
> onboarding package: system access. The Builder will create a
> **MongoDB connector** to the POSLOG database — with a
> read-only service account, not an admin login."

**SAY** (while it builds — pick what fits the pace):

> "Watch what the platform does with it: it creates the
> connector, then **introspects the schema** — it samples a
> hundred documents from the collection so the agent knows the
> real document shape, not just my description. The MongoDB
> connector is marked *experimental*, so this is honestly the
> riskiest click of the demo — which is why the whole thing
> also exists as YAML in the repo. If the Builder has a bad
> day, one `sam config apply` hires the same worker in twenty
> seconds.
>
> Note what I did **not** paste anywhere: no API key, no model
> endpoint. The agent gets the `general` model **alias**, and
> credentials live in the connector, scoped read-only. That's
> the difference between onboarding an employee and hardcoding
> a script."

### 4.2 Deploy

**DO**: When the Builder finishes, review the generated agent
(point at the system prompt and the connector binding), then
**Deploy**.

**SAY**:

> "Contract signed, badge issued. The agent is now a live
> worker on the mesh — discoverable by the Orchestrator like
> every other team member. Total hiring time: about two
> minutes."

### 4.3 First day at work — talk to the data

**DO**: Open **Chat**, select **Retail POS Analyst**, and ask:

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
> excluded. Keep this number in mind — the register sells this
> smoothie bowl just fine. Later, a customer will try to order
> the same product **online** — and that order will fail. Our
> new analyst is about to earn their salary."

**Transition to Part 2 (Teamwork)**:

> "So: hired, onboarded, first task done. Now let's see the
> team work together — without me asking anything."

---

## Notes for the rehearsal

- The direct workflow link needs the HASH route (`/#/agents/
  workflows/...`) — without the `#` the app falls back to the
  start page. The display-name variant survives platform
  rebuilds (`display_name` is config-managed); the
  `workflow_<uuid>` variant must be regenerated after every
  rebuild. The page resolves the link against the live agent
  cards, so the workflow must be DEPLOYED for the link to work.
- If the Builder asks clarifying questions instead of building,
  answer briefly or restart with the same prompt — it is
  non-deterministic. The fallback needs ~20 s.
- Builder + deploy + test together budget ~4 minutes. If the
  Builder takes longer than ~2:30, start the fallback in the
  terminal while narrating — do not wait silently.
- After the rehearsal, delete the Retail POS Analyst agent AND
  the `retail-poslog` connector again so the live demo starts
  clean (Agent Management → delete; Connectors → delete).
