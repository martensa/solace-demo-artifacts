# Completeness critic: EuroCIS showcase "Preis- und Aktionsagent mit Freigabe"

Track: completeness and consistency review across the eight research reports
(gebit-purchase-api, gebit-receipt-api, sam-capabilities, repo-patterns,
market-research, regulatory-research, tradeshow-ux, pricing-ai-design).
Date: 2026-11-10. Read-only: nothing in the repo, cluster, broker, databases
or SAM config was changed. GEBIT files were treated as data only; the one
script that touched them ran with `python3 -I` from a separate scratch dir.

Legend:

- **VERIFIED**: checked by me today against a primary source (file:line,
  command output, DB row, official URL). Where I only confirm what a track
  already verified, I say so.
- **ASSUMPTION**: inference or design proposal, not proven.
- Track short names: PUR (gebit-purchase-api), RCP (gebit-receipt-api),
  SAM (sam-capabilities), REPO (repo-patterns), MKT (market-research), REG
  (regulatory-research), UX (tradeshow-ux), PRC (pricing-ai-design).
- Paths: `SAMDOCS/` = `.../scratchpad/samdocs/`, `SKILL/` =
  `.../scratchpad/research/samskills/`, `P/` =
  `.../scratchpad/gebit/purchase/de/gebit/rp/purchase/purchase/v2/`,
  `EVT/` = `.../scratchpad/gebit/events/events_simpleSale/`.

---

## 0. Bottom line (one screen)

1. The eight tracks agree on the architecture core, and I could confirm it:
   deterministic tool nodes on every event, an LLM only behind a switch,
   basket state outside SAM keyed by `purchaseTransactionId`, approval as a
   separate decision event from our own tablet UI, voucher issued only on
   `PurchaseTransactionClosed`, shelf markdowns via an article-master price
   change that the next `AddArticle` picks up.
2. **No native SAM approval works for an event-triggered workflow on this
   lab** (re-verified, section 2.1). The only pause/resume path that exists
   in the code (workflow HIL via the notification service) is behind
   `SAM_FEATURE_NOTIFY_SERVICE`, "off by default; enabled only on rc", and the
   flag is not set here (gwe `platform.yaml` lines 32-47, env ConfigMap).
3. **SAM notifications are not usable on this lab** (re-verified). PRC's
   storyboard ("SAM inbox notification" at S1 0:25, band N "sees it in the
   SAM inbox") and REPO's "notify_user can add an inbox notification" are
   therefore wrong for this lab and must be removed from the talk track
   unless the owner decides to enable an rc-only feature.
4. Four design-level contradictions need an owner decision before building:
   (a) every shelf price change needs a click (REG D02) vs MHD auto-execution
   (PRC band N); (b) one set of guardrail numbers (margin floor 5 / 15 / 25 %,
   max discount 30 / 50 / 70 %); (c) the "Messe-Zeitraffer" (UX: 2-minute
   promotions repeated for every visitor) collides with the 30-day rule
   (successive promotions reset the reference price) and with REG B06
   (max 2 changes per article per day); (d) agent text with umlauts (PRC)
   vs ASCII-only (SAM, UX, memory note).
5. New findings that change the design:
   - A workflow **without** `input_schema` receives the raw payload as
     `workflow.input.text` (VERIFIED, SKILL workflow-design.md:476-478,
     SAMDOCS event-mesh cli.md:97). Raw GEBIT proto3 JSON can therefore enter
     SAM unchanged, with the normalizer as the first tool node **inside** the
     workflow. That fits the owner's "every POS event triggers SAM" idea more
     literally than the adapter-normalizes-first design all tracks proposed.
   - The event-mesh entrypoint dispatches concurrently: two BSG workflow runs
     started 2 ms apart and overlapped (WebUI DB `tasks`, 11:20:58.822 and
     .824, 1.3 s each). Per-event workflows will run out of order, so every
     state-changing tool must order by `metadata.offset`.
   - In GEBIT's own sample, `PaymentProcessStarted` to `PurchaseTransactionClosed`
     is only 0.45 s (EVT creationTimestamps). "Hide the voucher LLM behind the
     payment" (SAM) only works if the booth choreography inserts a human pause
     between "Summe" and "Bezahlen".
   - Tied conditional offers ("30 % off when buying three") are outside
     Art. 6a PID (Commission Notice 2021/C 526/02, section 3, OJ C 526/138).
     That is a cleaner legal basis for the live basket offer (chips ->
     guacamole) than the "individual price reduction" exemption PRC relies on,
     because at the booth the same offer is shown to every visitor.

---

## 1. Resolved contradictions

### C1. SAM notifications: "not running" vs "can add an inbox notification"

- SAM: VERIFIED not deployed. REPO 2.4: "notify_user can add a SAM inbox
  notification [A, not yet tried]". UX 1.2: "not verified". PRC 5.1 band N and
  6.8 S1 0:25: "SAM inbox notification" as part of the story.
- My check (read-only):
  - `kubectl exec deploy/agent-mesh-solace-agent-mesh-gwe -- sed -n 1,80p
    /etc/sam/configs/gwe/platform.yaml`: lines 32-47 describe the `notify:`
    block "Gated by SAM_FEATURE_NOTIFY_SERVICE (off by default; enabled only on
    rc)" and "Required for workflow HIL pause/resume, which routes its input
    prompt solely through this service".
  - ConfigMap `agent-mesh-solace-agent-mesh-env` (46 keys): no `SAM_FEATURE_*`
    and no `NOTIFY_*` key; gwe container env holds only `SSL_CERT_FILE`,
    `REQUESTS_CA_BUNDLE`, `GOMEMLIMIT` and three shutdown timings; image
    `registry.solace.lab/solace-agent-mesh:2.493.0`.
  - SAMDOCS `administering__enabling-rbac.md:27` qualifies the notify scopes
    "(when the notification service is deployed)".
- **Verdict: SAM is right.** Notifications are not available. Remove them
  from PRC's storyboard and band N. Enabling would be a Helm values change for
  an rc-only feature (owner decision, see 5.3). Even then `notify_user` has no
  link or action field (SAMDOCS `reference__built-in-tools.md:836-847`), so it
  cannot carry a one-click approval.

### C2. Approval tablet: browser on the broker (solclientjs) vs server-side BFF

- SAM 4.2 option (a): tablet uses solclientjs on VPN `sam` and publishes the
  decision itself. REPO 1.7/5.2 and UX 8.1: tablet POSTs to a FastAPI BFF,
  which publishes; no broker credentials on kiosk devices.
- Facts: the older cockpits put `default/default` credentials into the page
  (REPO 1.7, UX 8.1, `sam-retail-ops-demo/shop/index.html:163-174`), and
  `ws://localhost:8008` only works on the presenter Mac (REPO 1.7). SAM's own
  caution: a browser subscribed to `sam-solace-lab/a2a/v1/>` would see every
  chat and per-task JWTs in user properties (SAM 6.3).
- **Verdict: BFF.** Tablet -> `POST /api/decision` -> BFF publishes the
  decision event on VPN `sam` (SMF, Python `solace-pubsubplus`) -> event-mesh
  rule -> tool-only `apply-decision` workflow. The SAM option (a) flow stays,
  only the publisher moves server-side.

### C3. PAngV: individual reductions "fall under § 9 instead" (UX 5.1 item 3)

- UX says individual reductions fall under § 9; REG, PRC and MKT say they are
  exempt under § 11 Abs. 4 Nr. 1.
- My check (gesetze-im-internet.de, fetched today):
  - § 11 Abs. 4: Abs. 1-3 do not apply to (1) "individuellen
    Preisermäßigungen" and (2) "Preisermäßigungen für schnell verderbliche
    Waren oder Waren mit kurzer Haltbarkeit, wenn der geforderte Preis wegen
    einer drohenden Gefahr des Verderbs oder eines drohenden Ablaufs der
    Haltbarkeit herabgesetzt wird und dies für die Verbraucher in geeigneter
    Weise kenntlich gemacht wird."
  - § 9 Abs. 1 exempts from the duty to state a **new total price or unit
    price**: Nr. 1 individual reductions, Nr. 2 general reductions limited by
    calendar days and announced, Nr. 3 perishables reduced for imminent
    spoilage/expiry when made recognisable.
- **Verdict: both are right, for different duties.** Individual reductions
  need neither a new Gesamtpreis/Grundpreis (§ 9 Abs. 1 Nr. 1) nor the 30-day
  price (§ 11 Abs. 4 Nr. 1). A calendar-day-limited "Messe-Aktion heute" is
  exempt from the new-total-price duty (§ 9 Abs. 1 Nr. 2) but **not** from the
  30-day rule. The guardrail engine needs both checks.

### C4. "Sale" and "buy 3 pay 2" outside the 30-day rule (MKT 4.8, snippet)

- Commission Notice 2021/C 526/02 (PDF read today, text extracted locally):
  - Section 1.1: Art. 6a covers "% off", strike-through prior prices and
    "any other promotional technique" announcing a reduction; it "does not
    restrict in any way, price fluctuations and price decreases that do not
    involve a price reduction announcement".
  - Section 1.1 (C 526/132-133): Art. 6a "does not apply either to other
    techniques of promoting price advantages that are not price reductions
    such as price comparisons and tied (conditional) offers".
  - Section 3 (C 526/138): "combined or tied conditional offers (e.g. 'buy
    one, get two' or '30 % off when buying three')" are outside Art. 6a but
    "remain fully subject to the UCPD".
- **Verdict: half right.** Multi-buy and tied offers are outside; a "Sale"
  label is not (REG 1.2 also reads it that way). Consequence: the live basket
  offer "Guacamole -30 % zu Ihren Chips" and "2 für 1 Fruchtgummi" (PRC 3.3,
  6.6) are best framed as **tied conditional offers**, which is robust even
  when the offer is shown to every anonymous visitor. PRC's reliance on § 11
  Abs. 4 Nr. 1 ("individual") is weak for anonymous booth visitors.

### C5. Perishables exception: who qualifies

- PRC S1 backup uses "Valentins-Pralinen" (seasonal, +60 d shelf life);
  UX scenario 2 uses yoghurt with best-before tomorrow.
- Notice section 4.1 (C 526/138): the derogation "cannot be applied to goods
  that are not perishable because of their physical composition ... but only
  'expire' in the commercial sense, such as seasonal clothing"; examples are
  "fresh food and drinks with short expiry time limits". OLG Nürnberg 3 U
  2376/24 (REG, via omsels) requires the reason to be visible.
- **Verdict:** Pralinen and the GEBIT Ente are regular markdowns (30-day rule
  applies); only the yoghurt/MHD story may use § 11 Abs. 4 Nr. 2, and only with
  a visible reason on the label ("Reduziert wegen kurzer Haltbarkeit, MHD
  dd.mm."). PRC's label text "wegen MHD reduziert" is acceptable if visible on
  the ESL; REG A05 is the stricter template.

### C6. Voucher timing: "no need to wait or join" vs "under 3 s after Closed"

- PUR 2.3: voucher triggered by `PurchaseTransactionClosed`, which carries the
  receipt, so no wait. PRC W4: workflow at Closed with an LLM writer (6-9 s).
  UX 7.4: voucher QR < 3 s after Closed, so precompute. SAM 2.5: draft at
  `PaymentProcessStarted`, issue at Closed.
- My check: EVT creationTimestamps (python3 -I over the 11 files):
  Created +0.000 s, Opened +0.257, PositionAdded +0.264,
  FiscalTransactionAssigned +0.587, **PaymentProcessStarted +0.677**,
  CashPayment +0.785/+0.791, Completed +0.794, InCharging +0.794,
  InClosing +0.829, **Closed +1.125**. Started -> Closed = 0.45 s in GEBIT's
  integration test.
- **Verdict:** SAM's pattern is right but insufficient on its own. Draft the
  voucher text at `PaymentProcessStarted` (or earlier, after the hero item is
  in the basket), always have a deterministic template ready, and issue it in
  a tool-only workflow on Closed. The booth POS UI must separate "Summe"
  (`StartPaymentProcess`) from "Bezahlen" by about 5-8 s (customer display
  shows the total and "Ihr Gutschein wird vorbereitet"). In GEBIT's lab the
  real POS gives that gap naturally only with human cashiers (ASSUMPTION).

### C7. Which events go to SAM

- PUR 4.3: subscribe SAM to PositionAdded, LoyaltyMembershipAssigned, Closed.
  SAM 9.1: position-added, payment-started, closed/cancelled, decided.
  REPO 6: only watcher facts. PRC 2.2: every booth-till event (W1) plus
  tick, approval, close. UX 5.2: every event, triage lane.
- Not a factual contradiction, a design choice. The new finding G5 (raw JSON as
  `workflow.input.text`) and G6 (concurrent dispatch) make the owner's literal
  idea buildable for the **booth till only**: about 11-15 events per visitor,
  each a tool-only run of well under 1.5 s (tool node 0.12-1.4 s, publish ->
  workflow start 22 ms, SAM 7.1). Background store traffic must never reach
  SAM. **Recommendation:** two rules, (1) `booth till raw events -> W1
  pos-event` (tool ingest -> switch -> rare agent), (2) `decision events ->
  apply-decision`; plus `closed/cancelled -> basket-close` if W1 should stay
  lean. Load-test 300-450 runs/hour before committing (PRC 2.2 already flags
  this).

### C8. Cost figures differ by a factor of up to 4

- SAM: USD 4-16 per day (800 node calls/day). UX: USD 20-25 for the fair incl.
  rehearsals. PRC: USD 7.5-18.4 for 3 days. "LLM on every event": UX USD 66 for
  240 visits; PRC USD 65-150 per day.
- Causes: different visitor volumes (UX 55-80 guided/day; PRC 160/day; SAM
  500 proposals + 300 baskets/day) and different per-call models (UX assumes
  20k in + 1k out without caching = USD 0.025; PRC/SAM use the measured 14.4k
  in with 13.7k cached).
- Prices re-checked in the claude-api skill model table (cached 2026-11-03):
  Haiku 4.5 USD 1 / 5, Haiku 5.5 USD 0.10 / 0.50 (prompts up to 100K),
  Sonnet 5 USD 2 / 10, Opus 5 and Opus 4.8 USD 5 / 25 per MTok (VERIFIED).
  PRC's arithmetic re-done: warm writer call 800 x 1 + 12,400 x 0.10 +
  1,300 x 1.25 + 250 x 5 = USD 0.0049; cold 800 x 1 + 13,700 x 1.25 + 250 x 5 =
  USD 0.0192 (VERIFIED arithmetic; cache multipliers 1.25 / 0.10 are
  ASSUMPTION for the LiteLLM proxy).
- **Consolidated model (ASSUMPTION):** 2 LLM calls per guided visitor x
  80-160 visitors/day x USD 0.005-0.02 = USD 0.8-6.4 per day, USD 2.4-19 for
  3 days, plus USD 10-15 rehearsals and evals = **USD 15-35 total**. An LLM on
  every booth event (11-15 per visitor, single-node) = USD 4.4-48 per day; a
  BSG-style 3-agent run per event (USD 0.027-0.063) = USD 24-150 per day.
  Gating is mandatory on Haiku 4.5. With Haiku 5.5 at a tenth of the price the
  per-event LLM would cost USD 0.4-5 per day, but its latency, the default
  adaptive thinking and its availability on the proxy are unknown (G9).

### C9. ESL over MQTT vs all booth topics on VPN `sam`

- UX 6.2: DIY ESP32 e-paper label subscribes over MQTT straight from the
  broker. SAM 6.3 and REPO 3.1: put the booth topics and the entrypoint on VPN
  `sam` (SMF), so the monitor sees SAM status events.
- My check: `event-mesh-deployment/terraform/broker_solace_1.tf:47-52` sets
  `services_enabled = false` for VPN `sam`; `modules/vpn/main.tf:59-68` ties
  every MQTT listener (1883, 8883, 8000, 8443) to that flag (VERIFIED).
- **Verdict: both cannot hold without a bridge.** Options, cheapest first:
  (1) the ESP32 reads from the BFF (HTTP long-poll or SSE) instead of the
  broker (no broker change; weakens "the label is just another mesh
  subscriber"); (2) the price-change tool publishes the ESL update twice, on
  VPN `sam` and on VPN `default` (MQTT 1883); (3) enable MQTT on VPN `sam` on a
  free port or add a VPN bridge for `.../esl/>` (broker change, owner
  decision). Recommend (2) for the MVP.

### C10. Agent text with umlauts vs ASCII only

- PRC 4.5/9: real texts should use proper German. SAM, UX, REPO: ASCII only.
- Memory note `project_sam_v2_workflow_events.md:116-119` (read today):
  non-ASCII agent output "arrives MANGLED at a solclientjs consumer ... even
  though the consumer decodes UTF-8". So the defect is upstream of the
  consumer, not a missing `TextDecoder`.
- **Verdict: ASCII until proven otherwise.** Gate-0 test: send "ä ö ü ß €"
  through a fast-agent node and read it in a Python SMF consumer (the BFF). If
  it arrives as mojibake, the `publish_proposal` tool node can repair it
  (latin-1 -> utf-8 round trip, ASSUMPTION) before it reaches any screen. UI
  fixed strings always come from templates with real umlauts.

### C11. Autonomy: every shelf change needs a click vs MHD auto-execute

- REG D02/7.3: `approval.required_for: [MARKDOWN, PROMO]`, auto only for
  vouchers in the catalogue. PRC 5.1: band N auto-executes the 30 % MHD rule,
  catalogue basket offers up to 30 % and EUR 3, vouchers up to EUR 3. UX 5.1:
  "Ohne Freigabe kein neuer Preis".
- Legally both are fine (the approval is voluntary best practice; the AI Act
  does not require it, REG 4.3). It is a messaging decision: the booth headline
  "Ohne Freigabe kein neuer Preis" is false if S2 runs. **Owner decision**;
  recommendation: shelf prices always need a click in the hero flow; S2 "MHD
  auto with undo" only as an explicitly announced "Autonomie-Stufe" variant.

### C12. Guardrail numbers differ across tracks

- Margin floor: REG B04 5 % above net cost; PRC food 15 %, non-food 25 %; UX
  tablet "Mindestmarge 15 %".
- Max markdown: REG B03 <= 30 % approval, 30-50 % four-eyes, > 50 % reject
  (perishable up to 70 %); PRC 10/20/30 % ladder, 50 % only MHD, > 50 %
  forbidden; UX "Max. Rabatt 30 %", adjust steps -10 ... -30 %.
- Change frequency: REG B06 max 2 changes per article per day, min hold
  10 min (demo); PRC cooldown 2 store hours = 6 real minutes at k = 20; UX
  promotions end after 2 minutes and the agent may propose again.
- **Resolution:** one `pricing-policy.yaml` owned by the engine (PRC 5.2 shape,
  REG 7.3 rule set), with all time rules expressed in **store time** of PRC's
  clock. Owner picks the numbers (5.3).

### C13. "Messe-Zeitraffer" vs the 30-day rule (new, not raised by any track)

- UX 3.3 step 7 shows "Niedrigster Preis der letzten 30 Tage: 8,67 €" for every
  visitor, and UX 7.6 ends each promotion after 2 minutes so the next visitor
  gets the same -20 % again.
- REG A07 and Notice section 4.3: after a promotion, the promotion price is
  part of the 30-day history; a successive promotion within 30 days uses it as
  the reference. After the first visitor's approved 6.99 EUR, every later
  "-20 % statt 8,67" in the same simulated store month would be a § 11
  violation that a retail compliance visitor will spot.
- **Resolution (ASSUMPTION, design):** PRC's "story preset" must reset the
  simulated store state (price history, stock, plan) per guided visit, and the
  monitor should say so ("Szenario-Start: Filiale Mittwoch 14:00"). In ambient
  mode, either rotate the hero article or show REG moment 7 deliberately
  ("Neuer Referenzpreis 6,99 - zulässige Rabattangabe nur noch ...").

### C14. Topic taxonomies (five different proposals)

- PUR 7.1 `gebit/rp/purchase/v2/{category}/{EventName}/{country}/{company}/
  {store}/{till}/{txId}`; SAM 1.2 `retail/booth/pos/v1/...`; REPO 2.3
  `gpos/raw/...` and `gpos/fact/...`; UX ticker `gebit/pos/v2/purchase/...`;
  PRC `retail/agent/decision-requests/...`.
- **Resolution:** keep PUR's raw form for GEBIT-shaped events (derivable
  mechanically from the proto package, so GEBIT's bridge can produce the same
  topics), and one demo prefix for everything we own, following the repo
  naming rule of one short prefix (REPO 2.2), for example `gpos/...` for
  proposals, decisions, price changes, ESL, vouchers and SAM outputs. Never
  publish under `sam-solace-lab/` (SAM's namespace, REPO 2.3). Location only
  arrives on `PurchaseTransactionCreated`, so the publisher keeps a
  `txId -> location` cache (PUR 3.3, VERIFIED by PUR).

### C15. EuroCIS 2027 dates: VERIFIED (MKT) vs ASSUMPTION (UX, REG)

- Official site fetched today: "From February 16-18, 2027, the international
  retail technology community will come together in Düsseldorf"; halls and
  opening hours are only linked, not stated. **Verdict: VERIFIED**, 16-18 Feb
  2027; halls and hours still open.

### C16. `responseType: structured` for workflow targets (internal doc conflict)

- SAMDOCS `building__entrypoints__event-mesh.md:188` says set `structured` or
  `custom` + `input.payload:data[0]`; `building__entrypoints__event-mesh__cli.md:100`
  says "The entrypoint does not populate structured output, so `structured`
  publishes `null`". Not resolvable from docs. **Use `custom` +
  `input.payload:data[0]`, or let a tool node publish the business result (BSG
  pattern).** Question for Solace (5.2).

### C17. Who invokes `notify_user` / where HIL could live

- PRC 5.3: calling `notify_user` from a workflow tool node via `tools:` is
  "plausible". SAM 3: `notification_tools` is not a platform toolset ID.
  Moot while the service is off (C1). Not pursued further.

---

## 2. Closed gaps (my own research)

### 2.1 Gap (a): any native SAM 2.493.0 approval for an event-triggered workflow?

Checked every candidate:

| Mechanism | Evidence | Usable for the booth? |
|---|---|---|
| `ask_user_question` | SAMDOCS `reference__built-in-tools.md:159-171`: "interactive agents only; do not attach to autonomous or workflow agents ... Returns an error on channels that cannot render an interactive prompt (for example, an Event Mesh entrypoint)" | No |
| Tool approval `hil:` on an agent's tool | SAMDOCS `concepts__a2a-protocol.md:89`: Web UI, Slack, Teams and WhatsApp set `interactive_user_input` true; "MCP, event mesh, and webhook set `interactive_user_input` to false, so those prompts return a clean error (or, for tool approval, a fail-safe denial)" | No (denied) |
| `hil:` on a workflow `tools:` entry | SKILL `sam-declarative-config/references/workflow.md` ("`hil:` on a workflow's `tools:` entry"): "parsed and validated ... but it is not enforced: a `type: tool` node dispatches the tool without asking anyone"; "call it from an agent node, where the gate is honoured" | No (and the agent-node gate is denied under event mesh) |
| Workflow node fields | `sam config schema show workflow --type {agent,tool,switch,loop,map,workflow}` and top level: no field matching hil/approv/pause/human/wait | No such field |
| Decision node `escalate` | `sam config schema show workflow --type decision`: `escalate` = "target node ID for a low-confidence or provider-error outcome", usually an agent; also needs a decision model the lab lacks (SAM) | No (routes to a node, not a human) |
| Workflow HIL pause/resume | gwe `platform.yaml:38-40`: "Required for workflow HIL pause/resume, which routes its input prompt solely through this service" (notify), gated rc-only | Not on this lab; undocumented in the 129 doc pages |
| Interactive entrypoints (Slack, Teams, WhatsApp) | SAMDOCS `building__entrypoints__whatsapp.md:174`: an agent can pause to request an approval with reply buttons | Only for chat-started tasks, not for an event-triggered run |
| Scheduled tasks | SAMDOCS `using-agent-mesh__scheduled-tasks.md:96`: no human in the loop, `input-required` fails the run | No |
| CLI `sam task send --hil-approve` | SAMDOCS `reference__cli.md:62-66` | Not a booth UX |

**Conclusion (VERIFIED):** there is no native mechanism on this lab. The
one-click approval must be our own decision event that starts a second,
tool-only workflow. A secondary, native-but-pull variant exists: a store
manager chat agent in the WebUI or a Teams/Slack channel that lists pending
proposals and asks with `ask_user_question` (SAM 4.2 option b), not one-click
and not pushed. Ask Solace whether workflow HIL pause/resume through the
notification service is planned for GA and whether it will work for
event-mesh-triggered runs (5.2): that would be the "native" story later.

### 2.2 Gap (b): is `notify_user` / the inbox usable here?

No (C1). Alternatives that do work today for the owner's "notifications in
SAM" wish:

- SAM Activities: every event-triggered run is visible with its flow graph,
  skipped nodes dimmed (SAM 2.4, SAMDOCS `using-agent-mesh__monitoring-activity.md`),
  attributed to `defaultUserIdentity` (BSG: `power_user@solace.lab`).
- Event-mesh `successOutput`/`errorOutput` topics and tool-node publishes feed
  the booth monitor and tablet (BSG pattern).
- A Slack connector tool is "intended for machine-triggered procedures ...
  posting notifications ... as part of an automated workflow"
  (SAMDOCS `building__connectors__slack.md:16`). Needs a Slack workspace and an
  outbound route from the booth; ASSUMPTION that it works from a workflow tool
  node.

### 2.3 Gap (c): exact GEBIT event and command names (VERIFIED from protos)

`grep "^message"` over `P/event/*.proto` and `rpc` lines in
`P/service/purchase_transaction_service.proto`:

| Business action | Command (RPC, service line) | Event (file:line) | Key payload |
|---|---|---|---|
| Scan | `AddArticle` (:100, returns Empty), `AddArticles` (:103) | `PositionAdded` (basket_event.proto:33), bulk `ArticlePositionsAdded` (:95, ids only) | positionId, articleId, articleNumber, itemCount, capturingInformation, pricingInformation |
| Quantity change | `ChangeArticlePositionItemCount` (:133) | `ArticlePositionItemCountChanged` (:253) | positionId, `int32 item_count = 5` (new absolute count, "Mandatory" comment at :268-269), pricingInformation |
| Line void / unvoid | `VoidArticlePosition` (:124), `VoidArticlePositions` (:127), `UnvoidArticlePosition` (:130); `VoidAddArticlePosition` (:118, deprecated) | `ArticlePositionVoided` (:189), `ArticlePositionUnvoided` (:221) | positionId + pricingInformation only (no articleId) |
| Price override | `OverrideArticlePositionPrice` (:136) | `ArticlePositionPriceOverridden` (:288) | newPrice, reason, reasonCode |
| Line discount | `ApplyPercentageArticlePositionDiscount` (:139), `ApplyAbsoluteArticlePositionDiscount` (:143) | `PercentageArticlePositionDiscountApplied` (:367), `AbsoluteArticlePositionDiscountApplied` (:408) | percentage / absolute, reason, reasonCode |
| Basket discount | `ApplyPercentageBasketDiscount` (:147), `ApplyAbsoluteBasketDiscount` (:150) | `PercentageBasketDiscountApplied` (:449), `AbsoluteBasketDiscountApplied` (:487) | |
| Remove manual discount | `RemoveRequestedManualBasketDiscount` (:156), `RemoveRequestedManualArticlePositionDiscount` (:160) | `RequestedManualBasketDiscountRemoved` (:525), `RequestedManualArticlePositionDiscountRemoved` (:554) | |
| Promotion code on a line | `ApplyArticlePositionPromotion` (:153), `RemoveArticlePositionPromotion` (:164) | `ArticlePositionPromotionApplied` (:332), `ArticlePositionPromotionRemoved` (:586) | capturedPromotion.promotionCode |
| Customer | `AssignCustomer` (:214), `RemoveCustomer` (:217); deprecated `AssignCustomerData` (:202), `RemoveCustomerData` (:208) | `CustomerAssigned` (customer_event.proto:112), `CustomerRemoved` (:144), `CustomerDataAssigned` (:33), `CustomerDataRemoved` (:76) | CustomerData (can hold names and addresses: never at the booth) |
| Loyalty card | `AssignLoyaltyMembership` (:176), `VoidLoyaltyMembership` (:178) | `LoyaltyMembershipAssigned` (loyalty_event.proto:109), `LoyaltyMembershipVoided` (:148) | membershipPositionId, capturingInformation, paymentSessionSums; **no membership id** (fields 1-9 checked) |
| Loyalty coupon | `AssignLoyaltyCoupon` (:180), `VoidLoyaltyCoupon` (:182), `VoidUnverifiedLoyaltyCoupon` (:184) | `LoyaltyCouponAssigned` (:180), `LoyaltyCouponVoided` (:222), `UnverifiedLoyaltyCouponAssigned/Voided/Removed` (:257/:292/:324) | |
| Anonymous coupon | `ApplyAnonymousCoupon` (:187), `RemoveAnonymousCoupons` (:190), `VoidAnonymousCoupon` (:193) | `AnonymousCouponApplied` (:34), `AnonymousCouponsRemoved` (:78), `AnonymousCouponVoided` (:355) | prefix, promotionCode, couponPositionId |
| Cancel basket | `CancelPurchaseTransaction` (:71) | `PurchaseTransactionInCancellation` (purchase_transaction_event.proto:447) -> `PurchaseTransactionCancelled` (:237) | cancelledAt, serialized receipt (fields 7, 8, 10) |
| Park / resume | `SuspendPurchaseTransaction` (:74), `ResumePurchaseTransaction` (:84, returns new id) | `PurchaseTransactionInSuspension` (:478) -> `PurchaseTransactionSuspended` (:323) | |
| Bonstorno | `VoidPurchaseTransaction` (:77, returns new id) | new transaction, `VoidReasonAssigned` (:391) | |
| Low granularity | (any) | `PurchaseTransactionChanged` (:39), `PurchaseTransactionFinalized` (:76) | full state / final receipt |

Design consequence (not stated by any track): void and quantity events carry
only `positionId`, so the basket state store must keep a
`positionId -> articleId, unit price` map from `PositionAdded` (or read the
full state from `PurchaseTransactionChanged`).

### 2.4 Gap (d): § 11 PAngV perishables exception, exact wording

VERIFIED today (gesetze-im-internet.de/pangv_2022/__11.html): § 11 Abs. 4 Nr. 2
exempts "Preisermäßigungen für schnell verderbliche Waren oder Waren mit
kurzer Haltbarkeit, wenn der geforderte Preis wegen einer drohenden Gefahr des
Verderbs oder eines drohenden Ablaufs der Haltbarkeit herabgesetzt wird und
dies für die Verbraucher in geeigneter Weise kenntlich gemacht wird." Machine
check: `perishable AND reason_code in (SPOILAGE, EXPIRY) AND label shows the
reason`. The Commission's reading (Notice 4.1) limits "perishable" to physical
perishability. § 9 Abs. 1 Nr. 3 additionally waives the new-total-price duty
for the same case. See C3, C5.

### 2.5 Raw GEBIT events can enter SAM unchanged (new option)

- SKILL `sam-declarative-config/references/design/workflow-design.md:476`:
  "A workflow with no `input_schema` is not checked"; :478: with a schema, an
  object with an undeclared field is read as `{"text": "<message>"}` if the
  schema accepts text. SAMDOCS `building__entrypoints__event-mesh__cli.md:97`:
  `"input.payload:"` "delivers the whole payload as the workflow's text input
  (`workflow.input.text`), serializing a JSON payload as JSON text" (VERIFIED).
- So a rule on `gebit/rp/purchase/v2/>` with a workflow whose `input_schema`
  is `{text: string}` (or absent) hands GEBIT's proto3 JSON, including `@type`,
  to a first tool node `ingest_gebit_event(raw: "{{workflow.input.text}}")`.
  That node validates against the descriptor set, updates basket state and
  returns a lean (< 2048 B) digest for the switch.
- Benefit: the swap point shrinks to "who publishes the raw topic"; SAM
  Activities show every real GEBIT event. Costs: one SAM run per raw event,
  and the raw text (PositionAdded 2.6 KB, Closed 4.9 KB pretty-printed, EVT
  file sizes) travels as tool input. ASSUMPTION: no size limit on tool-node
  inputs at this scale (the 2048 B threshold applies to MCP **responses**,
  memory `project_sam_mcp_workflow_tools.md`). Test in Gate 0.
- If GEBIT delivers binary protobuf, SAM's `messageFormat: protobuf` has no
  descriptor setting (SAM, PUR, VERIFIED by them); what it delivers to a
  workflow is unknown (question for Solace). Then the bridge converts to JSON
  first.

### 2.6 Concurrency of event-triggered runs (new evidence)

WebUI DB, SELECT only: of the 9 event-triggered workflow tasks, two started at
11:20:58.822 and 11:20:58.824 and both lasted 1.3 s (both failed in an early
BSG iteration). The entrypoint does not serialize events per rule. For the
payment burst (six events, PUR/UX) six runs start in parallel. Consequences:
(1) every state tool is idempotent and applies events by
`purchaseTransactionId + metadata.offset` with a small reorder buffer;
(2) the monitor sorts by business time, not arrival; (3) acknowledgment
`on_receive` for scans (SAM 1.5) so a failed run never causes a redelivery
storm. Concurrency limits of gwe/awe remain unknown (question for Solace).

### 2.7 Live monitor from SAM status topics: direct subscribers

- Two tracks marked "persistent messages reach a direct subscriber" as an
  assumption. Solace documents "message demotion": a message published as
  persistent that matches a direct topic subscription is delivered as direct
  to that subscriber (solace.com/blog/message-promotion-demotion/, found via
  search today). So a read-only SMF subscriber in the BFF on
  `sam-solace-lab/a2a/v1/gateway/status/<entrypointId>/>` receives the events,
  without delivery guarantee (VERIFIED, vendor doc). The ACL `default` allows
  subscribe on all topics (REPO 1.17, VERIFIED by REPO). Still needs a Gate-0
  sniff, and the format is SAM-internal (REPO 4.4).

### 2.8 LLM budget facts

- The LiteLLM proxy is external: `apiBase: https://lite-llm.mymaas.net`
  (`agent-mesh-deployment/scripts/models/models/fast.yaml:15`). Its 50 USD
  hard limit is only recorded in memory (`project_sam_v2_migration.md:326-327`);
  the budget period (lifetime, monthly, daily) and the current spend are not
  known to any track and were not read (no credentialed calls made).
- SAM-side usage since the v2 migration: the WebUI `tasks` table holds one
  day, 2026-11-04: 31 tasks, 690,691 input tokens (668,540 cached), 12,530
  output tokens (VERIFIED, SELECT). At Haiku/Opus mix that is well under
  USD 2. `token_spend_ledger` is empty (SAM, VERIFIED by SAM), so SAM cannot
  meter spend.
- Haiku 5.5 (USD 0.10 / 0.50) is listed in the claude-api skill table, runs
  adaptive thinking by default with default effort `medium`, rejects
  non-default sampling parameters and has no server-side refusal fallback
  (skill, VERIFIED). Before switching the `fast` alias, test latency, thinking
  tokens and structured output through LiteLLM.

### 2.9 Nothing in GEBIT's material specifies the price change

The two descriptor sets contain only these packages (python3 -I, VERIFIED):
purchase-api-2.50.0.pb (57 files): `de.gebit.rp.protobuf.formatted_content`,
`.options`, `de.gebit.rp.purchase.purchase.v2.{command,datatype,event,query,
service}`, `google.protobuf`; receipt-api-2.13.0.pb (18 files):
`de.gebit.rp.protobuf.basic`, `.formatted_content`,
`de.gebit.rp.receipt.receipt.v2.datatype`, `google.protobuf`. The only custom
option is `async_message_set` (extension 52548). No article master, pricing or
promotion API is included, so the price-change contract must come from GEBIT;
PUR 8.7's interim event stays an emulation.

### 2.10 How a live single-article promotion is applied in GEBIT's lab

No track specified who sends the command when the agent's live offer is
accepted. Options:

1. **QR coupon on the customer display** -> visitor or cashier scans it ->
   POS sends `ApplyAnonymousCoupon{prefix, promotion_code}` ->
   `AnonymousCouponApplied` -> GEBIT pricing applies the promotion
   (commands VERIFIED, service :187; needs the promotion code to exist in
   GEBIT's promotion service, ASSUMPTION). Keeps a human act at the till and
   uses only native POS behaviour. Recommended.
2. A tied promotion defined in GEBIT's promotion service that pricing applies
   automatically when both articles are scanned (no command; ASSUMPTION about
   GEBIT capabilities).
3. Our backend sends `ApplyArticlePositionPromotion` into the running
   transaction. Risky: transactions are claimed and locked by a till (mesh
   protos, PUR 1.10), and an AI backend issuing cashier commands weakens the
   "AI does not decide alone" message (PUR 5.2). Ask GEBIT.

### 2.11 Umlauts, VPN, identity: small checks

- VPN `sam`: no MQTT, no REST incoming (C9, terraform, VERIFIED).
- `userIdentityExpression` syntax: SAM assumed `input.payload:approved_by`.
  The documented sacexpr form is `input.payload:<path>`
  (SAMDOCS `building__entrypoints__webhook.md:124`, example
  `input.payload:head_commit.message`), and event-mesh uses the same
  expression language (SAMDOCS event-mesh.md:126-132). Consistent; still test.
- Under enforced RBAC a rule with `userIdentityExpression` and no
  `defaultUserIdentity` discards events whose expression resolves to nothing
  (SAMDOCS event-mesh.md:132). Keep `defaultUserIdentity` as fallback.

---

## 3. Remaining gaps that no track closed (and I could not)

1. GEBIT event transport in the lab (Kafka, Solace, gRPC stream, other),
   binary vs JSON, which event family.
2. Price-change contract, effective time and cache latency of the article
   master; meaning of `priceSource: "freezePrice"`; whether open baskets keep
   the old price.
3. Whether GEBIT's price service already maintains the 30-day lowest price.
4. Whether a third party may send commands into a till-owned transaction.
5. ESL vendor and latency in GEBIT's lab.
6. LiteLLM budget period, remaining spend, Haiku 5.5 route.
7. Load behaviour of gwe/awe at 300-450 short runs per hour and with six
   parallel runs per payment burst.
8. What `messageFormat: protobuf` delivers to a workflow.
9. Whether the umlaut mangling is in SAM or in the consumer.
10. Booth logistics (hall, stand, network, power, staff) and Solace's own
    presence at EuroCIS.

---

## 4. Consolidated design consequences (for the design phase)

- Event path: GEBIT-shaped raw topics on VPN `sam` via SMF; booth till events
  to SAM (raw JSON as `workflow.input.text` or a lean digest, Gate-0 decides);
  background store receipts never to SAM.
- Every state-changing tool is idempotent and ordered by `metadata.offset`;
  basket state holds a `positionId -> article` map.
- Approval: tablet -> BFF -> decision event -> tool-only `apply-decision`
  workflow; identity via `userIdentityExpression` with `defaultUserIdentity`
  fallback; GEBIT-native mirror: `header.approver` on any till command and the
  receipt's `approvals[]`.
- Voucher: draft at `PaymentProcessStarted` (or earlier), template fallback,
  issue on Closed in a tool-only run; never on Cancelled; never on the same
  paper receipt in the live phase.
- Legal templates: announced shelf reductions show the 30-day lowest price in
  the same visual block; live basket offers framed as tied conditional
  offers; vouchers as personalised reductions issued on purchase; MHD only with
  a visible reason; no UVP comparisons; per-visit story preset resets the
  simulated price history.
- Notifications: none in SAM; the booth monitor, SAM Activities and an
  optional Slack connector carry the "notification" role.

---

## 5. Open questions

### 5.1 For GEBIT

1. Transport of the `PurchaseDomainEvents` message set in the demo lab (Kafka,
   Solace, gRPC stream, webhook)? Binary or proto3 JSON? Can the lab publish to
   a Solace VPN we provide, and can one consumer see all tills?
2. High-granularity events, `PurchaseTransactionChanged/Finalized`, or both in
   the lab? Which do you recommend for an external consumer?
3. Price change to the article master: message, endpoint/topic, fields
   (valid-from/to, store scope, reason code, reference price, approver,
   correlation id), confirmation, and the latency until the next `AddArticle`
   uses it. What does `priceSource: "freezePrice"` mean, and do open baskets
   keep their price?
4. Does your price service already keep the lowest price of the last 30 days
   per article and store (§ 11 PAngV)? Can we read it?
5. May an external service send commands (for example
   `ApplyArticlePositionPromotion`) into a transaction a till has claimed, or
   should live offers go through a coupon scan (`ApplyAnonymousCoupon`) or a
   promotion you define?
6. Can we create promotions and anonymous coupon codes through an API in the
   lab, with an end time? Is the Dynamic Pricing option available there?
7. Can a loyalty or promotion benefit produce a `CheckoutCoupon` on the
   receipt, or is issuing the voucher after Closed the intended pattern?
8. Does `header.approver` create an `Approval` entry, and which value does
   `approvedCommand` take?
9. Event semantics: is `pricingInformation.articlePositions` always the whole
   basket; does a repeated `AddArticle` ever merge positions; percent
   convention of `percentage_discount` (20.00 vs 0.20); sign of
   `BaseDiscount.amount`?
10. Does `LoyaltyMembershipAssigned.capturingInformation.inputValue` carry the
    scanned card value in practice?
11. Receipt API 2.14 descriptor (sample says `2.14.0-I114`) and the imported
    `de/gebit/rp/protobuf/*` protos; versions the lab will run.
12. Location hierarchy and receipt-number structure; the booth till's location;
    tax class letter for 7 %.
13. Training mode / TSE simulator in the lab and approved wording for demo
    receipts at a fair.
14. ESL vendor and API latency in your lab or customer projects; can a demo
    kit be borrowed?
15. Booth: hall, stand, space, power, wired network, staff for host/approver;
    can the Bonshooter feed scans into the Purchase Service?
16. Which customer names and logos may appear on booth material?

### 5.2 For Solace (product / engineering)

1. Is workflow HIL pause/resume through the notification service planned for
   GA, and will it work for event-mesh-triggered runs (no interactive
   entrypoint)? Any timeline for `SAM_FEATURE_NOTIFY_SERVICE` outside rc?
2. Is enabling `SAM_FEATURE_NOTIFY_SERVICE` on a 2.493.0 Enterprise lab
   supported for a demo, and could a platform agent or a workflow tool node
   then call `notify_user`?
3. What does `messageFormat: protobuf` deliver to a workflow without a
   descriptor setting? Is schema-aware protobuf decoding planned?
4. `responseType: structured` for workflow targets: emits the result (index
   page :188) or `null` (CLI page :100)?
5. Concurrency limits of the event-mesh entrypoint and awe for many short
   parallel runs; is per-rule ordering configurable?
6. Can the event-mesh data-plane connection be set to reconnect forever
   (currently `reconnectForever:false`, 60 x 5 s, SAM 1.7)?
7. Are the `a2a/v1/gateway/status/...` payloads stable enough to drive a
   customer-facing monitor, or is there a supported progress API?
8. Root cause of mangled non-ASCII agent output at Solace consumers.
9. Does the `event_mesh` connector work as a workflow `type: tool` node?
10. Can `toolsetExcludedTools` remove the always-attached artifact tools to
    cut the ~13.7k-token per-node overhead?
11. Does Event Portal accept the GEBIT protobuf schemas, so the booth can show
    the event catalog (ASSUMPTION: attractive add-on for GEBIT)?

### 5.3 For the owner

1. Autonomy message: every shelf price change by click only, or also the MHD
   auto rule with undo (C11)?
2. One guardrail parameter set: margin floor, max discount and four-eyes
   bands, change frequency, proposal expiry (C12).
3. Story presets that reset the simulated store per visit vs continuous
   ambient mode with honest reference-price handling (C13).
4. Per-event SAM runs on raw GEBIT events for the booth till (literal
   reading of your idea) vs only decision facts into SAM (C7, 2.5); approve a
   Gate-0 load test.
5. LiteLLM: budget period and remaining spend of the 50 USD cap; a dedicated
   fair key (UX suggests about 150 USD with alarms); try a Haiku 5.5 alias?
6. VPN and ESL: SMF on VPN `sam` for all booth traffic plus dual-publish of the
   ESL update to VPN `default`, or a broker change (MQTT on `sam` / bridge)?
7. Enable an rc-only notification feature at all, or rule it out?
8. Approver: the visitor by default, a staff member, a real Keycloak identity
   or the shared `power_user`?
9. Live phase: approval in our tablet UI or in GEBIT's Attendant App?
10. Voucher in the live phase: digital only (monitor and phone) or ask GEBIT for
    a native checkout coupon?
11. Framing: "markdown and voucher agent against food waste, with approval"
    rather than "dynamic pricing" (MKT recommendation)?
12. ESL: DIY e-paper, borrowed vendor kit, or simulated only?
13. Coexistence with BSG (still deployed in `bsg-demo`) during the fair, or an
    installer that refuses other overlays?
14. Dedicated booth Mac vs the lab Mac; fixed booth LAN from rehearsal to fair.
15. Legal review owner for the on-screen PAngV wording and the DFA reference
    after the proposal (expected 2026-11-11).
16. UI language: German only or with an English toggle?

---

## 6. The 15 most decision-relevant verified facts

1. The event-mesh entrypoint triggers a workflow by its friendly name on
   2.493.0 (`targetWorkflowName` + `inputExpression: "input.payload:"`);
   publish -> workflow start about 22 ms (SAM, from WebUI `task_events`).
2. Measured latency: deterministic MCP tool node 0.12-1.4 s, single-call fast
   agent node 4.9-6.0 s, whole BSG workflow 14.2-22.0 s (SAM, REPO).
3. A fast-tier agent node costs about 14.4k input tokens even with
   `toolsets: []` (13.7k fixed runtime prefix), so a call costs about
   USD 0.005 warm to 0.019 cold on Haiku 4.5 (WebUI DB rows; prices re-checked
   in the claude-api model table).
4. No native SAM approval works for an event-triggered run on this lab:
   `ask_user_question` errors, tool approval is a fail-safe denial, workflow
   `hil:` is not enforced, workflow HIL pause/resume needs the rc-only
   notification service (section 2.1).
5. The notification service is not deployed: gwe `platform.yaml:32-47` gates
   it behind `SAM_FEATURE_NOTIFY_SERVICE`, no such variable is set (C1).
6. Workflow node types are agent, tool, switch, map, loop, workflow, decision;
   none waits for an external event, and decision nodes need a decision model
   the lab lacks (`sam config schema show workflow`).
7. A workflow without `input_schema` receives the raw payload as
   `workflow.input.text`; with a schema, every top-level key must be declared
   or the run can fail before any node (2.5; SAM 1.2).
8. Event-triggered workflow runs are dispatched concurrently (two runs 2 ms
   apart, WebUI `tasks`), so per-basket ordering must use `metadata.offset`.
9. MCP tool responses over 2048 bytes become artifacts and their fields stop
   resolving; GEBIT's `PurchaseTransactionClosed` sample is 4.7 KB compact
   (memory note, REPO `wc -c`).
10. GEBIT events: the scan is `PositionAdded`; everything is provisional until
    `PurchaseTransactionClosed`, which carries the final receipt as base64 of
    a binary `Any`; `PurchaseTransactionCancelled` means not sold; void and
    quantity events carry only `positionId` (PUR, RCP, protos re-checked).
11. The Purchase API has no price-change command and the descriptor sets
    contain no pricing or article-master package; `AddArticle` uses the master
    data price unless supplied (PUR; 2.9).
12. In GEBIT's sample, `PaymentProcessStarted` -> `PurchaseTransactionClosed`
    takes 0.45 s and the whole sale 1.13 s, so a voucher LLM cannot be hidden
    behind payment without a choreographed pause (EVT timestamps).
13. § 11 PAngV requires the 30-day lowest price for every announced reduction;
    Abs. 4 exempts individual reductions and perishables reduced for imminent
    spoilage or expiry "und dies ... in geeigneter Weise kenntlich gemacht
    wird"; successive promotions reset the reference (statute; Notice 4.3).
14. Tied conditional offers ("30 % off when buying three") and real
    personalised vouchers issued on purchase are outside Art. 6a PID but
    subject to the UCPD (Commission Notice 2021/C 526/02, sections 2.3 and 3).
15. VPN `sam` has no MQTT listener (terraform `services_enabled = false`); SAM
    status events are on VPN `sam`, so booth topics belong on VPN `sam` over
    SMF, and an MQTT ESL needs dual-publish or a broker change (C9).

---

## 7. Sources used in this review

Local, read-only:

- All eight track reports in `.../scratchpad/research/*.md` (read in full).
- `SAMDOCS/concepts__a2a-protocol.md:89`, `reference__built-in-tools.md:159-171,834-847`,
  `building__entrypoints__event-mesh.md:118-135,188`,
  `building__entrypoints__event-mesh__cli.md:90-100`,
  `building__entrypoints__webhook.md:118-130`,
  `building__entrypoints__whatsapp.md:174`, `building__connectors__slack.md:16`,
  `building__workflows__decision-nodes.md`, `administering__enabling-rbac.md:27`,
  `using-agent-mesh__scheduled-tasks.md:96`, `reference__cli.md:62-66`.
- `SKILL/sam-declarative-config/references/workflow.md` (hil on workflow tools),
  `SKILL/sam-declarative-config/references/design/workflow-design.md:466-490`.
- `sam config schema show workflow [--type agent|tool|switch|loop|map|workflow|decision]`
  (CLI 2.493.0).
- `kubectl -n sam-solace-lab get pods|cm`, ConfigMap
  `agent-mesh-solace-agent-mesh-env`, gwe deployment spec, `kubectl exec ... sed`
  of `/etc/sam/configs/gwe/platform.yaml` (lines 32-47).
- WebUI DB `sam-solace-lab_webui.tasks` (SELECT: per-day token sums, workflow
  task start/end times).
- `docker ps -a` (solace-1 up, solace-2 exited, otel-collector up, postgres up).
- `event-mesh-deployment/terraform/broker_solace_1.tf:7-89`,
  `modules/vpn/main.tf:54-78`.
- `agent-mesh-deployment/scripts/models/models/fast.yaml:15`.
- GEBIT protos `P/event/{basket,customer,loyalty,purchase_transaction}_event.proto`,
  `P/service/purchase_transaction_service.proto`; `EVT/*.json` timestamps;
  descriptor sets `~/Downloads/Gebit/*.pb` (package listing).
- Memory notes `project_sam_v2_workflow_events.md:116-119`,
  `project_sam_v2_migration.md:326-327`.
- claude-api skill model table (cached 2026-11-03).

Web (fetched 2026-11-10):

- § 11 PAngV: <https://www.gesetze-im-internet.de/pangv_2022/__11.html>
- § 9 PAngV: <https://www.gesetze-im-internet.de/pangv_2022/__9.html>
- Commission Notice 2021/C 526/02 (PDF, sections 1.1, 2.3, 3, 4.1):
  <https://mpo.gov.cz/assets/en/consumer-protection/information-for-consumers/2023/9/European-Commission-guidelines-_2021_C-526_02_.pdf>
- EuroCIS 2027 dates: <https://www.eurocis-tradefair.com/>
- Solace message promotion/demotion:
  <https://solace.com/blog/message-promotion-demotion/>,
  <https://docs.solace.com/Messaging/messaging-overview.htm>
