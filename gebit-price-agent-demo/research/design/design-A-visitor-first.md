# Design A - "Besuchererlebnis zuerst"

EuroCIS 2027 showcase (16-18 Feb 2027, Messe Duesseldorf) by GEBIT
Solutions and Solace: **Preis- und Aktionsagent mit Freigabe**.

Angle: optimise for the visitor. One unmistakable hero moment, a story a
passer-by gets in 10 seconds from 5 m, few moving parts, a strong attract
loop, high throughput, and robustness on the fair floor. The architecture is
as lean as it can be while staying honest about what is AI and what is rule.

Written 2026-11-10 (about 14 weeks before the fair, Christmas included).
Based on the eight research tracks and the completeness critic in
`.../scratchpad/research/`. Where the tracks disagree, the critic's verdicts
are applied. Markers: **[V]** verified in the research (source there),
**[A]** assumption or design choice that a gate must confirm.

Short names used below: `engine` (deterministic store core plus MCP tool
server), `pos` (POS adapter: simulator now, GEBIT bridge later), `ui` (BFF
plus all screens), `gpos` (demo prefix for SAM resources, topics, namespace).

---

## 0. The design on one screen

1. **Hero moment (one, physical):** the visitor scans the **GEBIT Ente**
   (rubber duck). Within about 8 s the monitor and the tablet show
   "Ladenhueter erkannt - Vorschlag: -20 % -> 6,93 EUR". The visitor, playing
   *Marktleitung*, taps **Freigeben**. The **shelf label flips** from 8,67 to
   6,93 and the **next scan of the same duck rings up 6,93** - on the same
   receipt as the first duck at 8,67. Then the visitor pays, the receipt
   turns "final", a voucher QR appears, and the visitor keeps the duck.
2. **The 10-second story** (monitor headline and step strip, readable at
   5 m): "KI schlaegt vor. Sie geben frei." and four stations
   `1 Scan -> 2 KI-Vorschlag -> 3 Freigabe -> 4 Neuer Preis`.
3. **Exactly one AI moment per visit.** A fast-tier agent picks one of two
   pre-checked options and writes the two-sentence reason. Everything else
   (signals, numbers, guardrails, price change, voucher) is deterministic
   code, and the screens label it so: violet "KI", teal "Regel", orange
   "Mensch", blue "Kasse".
4. **SAM sees every booth-till event** (the owner's idea, taken literally):
   each GEBIT event of the booth till starts one run of the workflow
   `gpos-pos-event` (12 per visit, plus 1 `gpos-apply-decision` run for the
   tap); 12 of the 13 runs use tool nodes only, take well under 1.5 s and
   cost 0 tokens. The monitor counts it:
   "13 Ereignisse -> 13 SAM-Laeufe -> 1 KI-Aufruf".
5. **Approval** is our own decision event (tablet -> BFF -> broker ->
   tool-only workflow `gpos-apply-decision`), because SAM 2.493.0 has no
   native approval for event-triggered runs and no notification service on
   this lab [V].
6. **Lean footprint:** 3 pods from one image (`gpos-pos`, `gpos-engine`,
   `gpos-ui`) in namespace `gpos-demo`, 1 SAM entrypoint with 2 rules,
   2 workflows, 1 agent, 1 MCP connector, Postgres database `gpos`,
   solace-1 VPN `sam` over SMF, plus one DIY e-paper shelf label on MQTT.
7. **Robust by construction:** SAM is the primary path, and the engine holds
   watchdogs (4 s / 12 s / 3 s) that finish any step SAM did not finish, with
   a visible badge. The visitor never waits more than about 12 s for anything.
8. **Cost:** about 1 LLM call per visitor, USD 0.005-0.019 each, about
   USD 13-29 for the whole fair including rehearsals and evals.
9. **Effort:** about 88 person-days on the Solace side plus about 10-15 on
   the GEBIT side, in six gates (G0 on 20 Nov 2026 to G5 at the fair, freeze 5 Feb 2027).

---

## 1. Core message, framing, three messages

### 1.1 Kernbotschaft (one sentence)

> **"Jeder Scan ist ein Ereignis im Event Mesh: Die KI erkennt den
> Ladenhueter und schlaegt eine Aktion vor, ein Mensch gibt mit einem Tipp
> frei - und schon der naechste Scan kostet weniger, an Kasse und Regal."**

(EN: Every scan is an event on the mesh: the AI spots the slow seller and
proposes a promotion, a person approves with one tap, and the very next scan
costs less, at the till and on the shelf.)

### 1.2 Title and framing

- Showcase title: **"Ein Tipp. Neuer Preis."**
- Subtitle: "Der Preis- und Aktionsagent mit Freigabe - GEBIT Retail Platform
  und Solace Agent Mesh".
- Monitor headline (5 words): **"KI schlaegt vor. Sie geben frei."**
- Counter sign at the shelf (5 m hook): **"Diese Ente verkauft sich
  schlecht. Scannen Sie sie."** and below it "...und nehmen Sie sie mit."
- Framing: **markdowns against slow movers and food waste, with human
  approval** - not "dynamic pricing". Only price reductions, never
  increases; one shelf price for everyone (market research recommends this
  framing; German consumer groups warn about "Flatterpreise" [V]).

### 1.3 The three messages

| For | Message (booth wording) | Proof the visitor sees |
|---|---|---|
| **GEBIT** | "Die GEBIT Retail Platform liefert jedes Kassenereignis in Echtzeit. Darauf arbeiten KI-Agenten ohne neues Integrationsprojekt, und der freigegebene Preis gilt ab dem naechsten Scan." | Real GEBIT event names on the ticker; lines dashed until `PurchaseTransactionClosed`; same duck, two prices on one receipt (price frozen at scan, new price from the next `AddArticle`) |
| **Solace** | "Ein Ereignis, viele Abnehmer. Agenten haengen am selben Strom wie Kasse, Etikett und Statistik - ein deterministischer Workflow entscheidet, wann KI ueberhaupt noetig ist." | "13 Ereignisse -> 13 SAM-Laeufe -> 1 KI-Aufruf"; fan-out of the closing event to three real consumers; SAM Activities graph on the deep-dive laptop |
| **Visitor** | "Die KI entscheidet nicht allein: Sie schlaegt vor, Regeln pruefen, Sie geben frei - und sehen das Ergebnis in Sekunden im Regal und an der Kasse." | The tap; the red check when they try -30 %; the label flip; the 6,93 at the next scan; the duck in their hand |

---

## 2. Storyline and booth choreography

### 2.1 Roles

- **Host** (GEBIT or Solace, always present): invites, hands over the duck
  and the tablet, speaks at most three sentences, taps "Summe" and
  "Bar (Demo)" on the cashier screen, closes with a qualifying question.
- **Approver = the visitor** ("Moechten Sie heute Marktleitung sein?"). In
  show mode a volunteer from the crowd, or a second staff member.
- **Operator** (part-time, deep-dive corner): watches `/op`, switches modes,
  answers technical questions with SAM Activities and Grafana. Not needed for
  a single run.
- **Greeter** (peak hours only): queue, badge scan with the Messe lead app,
  "naechste Live-Runde in 2 Minuten".

Host script (three sentences, German):

1. "Jeder Scan an dieser Kasse ist ein Ereignis - da oben sehen Sie es live."
2. "Die KI hat gemerkt, dass sich die Ente schlecht verkauft, und schlaegt
   eine Aktion vor."
3. "Aber entscheiden tun Sie. Erst nach Ihrem Tipp aendert sich der Preis -
   an der Kasse und im Regal."

### 2.2 Attract loop (no visitor at the till)

| Screen | Content (loop) |
|---|---|
| Monitor | Every 8 s: (a) giant duck photo + "Scannen Sie die Ente." with an arrow to the shelf; (b) "Rueckblick 14:32" - replay of the last real approval (labelled); (c) day counters "Heute 143 Scans - 37 Vorschlaege - 29 freigegeben - 3 abgelehnt". A slow stream of dots from "andere Kassen der Filiale" runs along the bottom the whole time (background tills, real events). |
| Customer display | "Willkommen! Scannen Sie die Ente aus dem Regal." |
| Shelf label (ESL) | Regular price "GEBIT Ente 8,67 EUR". |
| Tablet | Dark, "Marktleitung - keine offenen Vorschlaege". |
| Physical | Shelf at the aisle edge with a basin of ducks, counter sign, hands-free scanner pointing up. No sound. |

### 2.3 Guided version (about 3:00)

Times are from the first scan. "Monitor" means the 65" screen. Each row is
one choreography step; latency targets come from section 11.

| # | t (s) | Visitor / host | Monitor | Tablet | Kasse / Kunde | ESL |
|---|---|---|---|---|---|---|
| 0 | -15 | Host: "Moechten Sie heute Marktleitung sein?" Visitor takes a duck and one other item (espresso) from the shelf. | Attract | dark | Welcome | 8,67 |
| 1 | 0 | Visitor scans the espresso. | Step 1 glows. "Bon geoeffnet" + line "Espresso Bohnen 500 g - 7,99 EUR" (dashed = vorlaeufig) + teal chip "laeuft nach Plan" (< 0.5 s). Scenario chip top right: "Simulierte Filiale - Mittwoch 14:00 - Zeitraffer 20x". | dark | line appears (< 0.3 s) | 8,67 |
| 2 | 8 | Visitor scans the duck. | Line "GEBIT Ente - 8,67 EUR" + **red chip "Ladenhueter: 21 statt 60 verkauft"** (< 0.5 s). At +1.5 s the proposal card slides in with the numbers (teal "Regel-Engine: 3 Stufen geprueft"), step 2 glows, timer "KI formuliert ... 4 s". | "1 neuer Vorschlag" (card with numbers, text pending) | line | 8,67 |
| 3 | 15 | Host sentence 2. | AI text types in (violet "KI-Einschaetzung"), at +6-9 s after the scan. | Card complete, "Freigeben" enabled | | |
| 4 | 20-45 | Host hands over the tablet: "Sie sind die Marktleitung." Visitor reads, may tap **Anpassen -30 %** -> red "Mindestmarge 20 % unterschritten (13,6 %)", "Freigeben" disabled; back to -20 % -> all green; taps **Freigeben**. | Mirrors the tablet: stepper value, check colours. Step 3 glows on the tap. | "Freigegeben - wird an Kasse und Regal verteilt" | | |
| 5 | 45-52 | **Hero moment.** Host points at the shelf. | Stamp "Freigegeben 14:32 - Marktleitung" (< 0.3 s) -> "Artikelstamm aktualisiert" -> "Etikett aktualisiert" -> step 4 glows: "8,67 EUR -> 6,93 EUR" at 240 px. ESL mirror tile flips together with the real label. | | banner on cashier screen "Neuer Preis aktiv seit 14:32" | **flips to 6,93, "AKTION -20 %", 30-day line** (1-5 s) |
| 6 | 55 | Visitor scans the duck again. | Second duck line "6,93 EUR - AKTION". Host: "Was schon im Korb lag, behaelt seinen Preis - ab dem naechsten Scan gilt der neue." | | Customer display: "AKTION -20 %", ~~8,67~~ **6,93 EUR**, "Sie sparen 1,74 EUR", "Niedrigster Preis der letzten 30 Tage: 8,67 EUR" in the same block | 6,93 |
| 7 | 65 | Host taps "Summe", then "Bar (Demo)". | "Zahlung gestartet" ... burst shown at 250 ms cadence ... **all lines turn solid: "Verkauf final - Bon 0042"**. Fan-out: one arrow each to "Abverkaufsstatistik", "SAM-Workflow Gutschein", "Monitor" (real consumers) and greyed "in Projekten: E-Journal, Warenwirtschaft, SAP". Counter "Verkauft heute 23 / Plan 62" ticks (only final sales count). | | total, then "Danke!" | |
| 8 | 68 | | Voucher card: "Ihr Gutschein fuer den naechsten Einkauf: -30 % auf Schaumbad Lavendel" (teal "Regel: passt zu Ihrer Ente"), < 2 s after Closed. | | Customer display: QR (>= 4 cm) + short URL | |
| 9 | 75 | Visitor scans the QR with the phone; host hands over the duck: "Die gehoert Ihnen." | "Danke, Marktleitung!" | | | |
| 10 | 80-180 | Guided extras (pick by audience): (a) deep-dive laptop: SAM Activities run graph of the duck scan (assess -> route -> KI-Agent -> publish; skipped nodes dimmed) and the 12 other runs; (b) Q&A: "Und wenn ich ablehne?"; (c) the yoghurt variant for grocery people (section 3); qualifying question "Wie laufen Preisaenderungen bei Ihnen heute?", badge scan. | Day counters; tech ticker | | | |
| R | +20 after QR | Auto-reset (or host scans the RESET card). | "Neue Runde - Filiale Mittwoch 14:00", back to attract | cleared | Welcome | **back to 8,67** (full refresh 5 s) |

### 2.4 Express version (60-75 s, for crowds and queues)

| t (s) | Step |
|---|---|
| 0 | Visitor scans only the duck (host has it in hand). |
| 1.5 | Proposal card with numbers on monitor and tablet. |
| 8 | AI text arrives; host: "Die KI schlaegt -20 % vor. Sie entscheiden." |
| 12-18 | Visitor taps **Freigeben** (no Anpassen). |
| 18-23 | Label flips; monitor "8,67 -> 6,93". |
| 25 | Re-scan: 6,93 at the till. |
| 30 | Host: "Summe", "Bar (Demo)" -> "Verkauf final". |
| 32 | Voucher QR; visitor keeps the duck. |
| 50-75 | Phone scan, one sentence, next visitor. Auto-reset 20 s after the QR. |

**Show mode** (4-8 watchers): the host scans, one volunteer approves, the
monitor narrates with the four numbered stations. One run every 3-4 min at
the half and full hour ("Live-Demo zur vollen und halben Stunde").

### 2.5 Reset between visitors

- Trigger: 20 s after the voucher QR, or the `RESET` control card, or an
  open basket idle for 90 s (then the till cancels it: monitor "Bon
  abgebrochen - nichts verkauft, kein Gutschein").
- Effect (engine, < 8 s, ESL refresh dominates): cancel any open
  transaction, end the active promotion, restore the scenario preset (price
  8,67, price history, "21 von 60", stock 140), clear the tablet, ESL full
  refresh to 8,67, monitor to attract. The day counters keep counting.
- A new visit starts at the first `PurchaseTransactionCreated` after a
  reset; the engine applies the preset then (zero-touch).
- Why reset per visit: after a first visitor's approved 6,93, a second
  "-20 % statt 8,67" in the same simulated month would break the 30-day rule
  (critic C13). Each visit is a fresh simulated store afternoon, and the
  monitor says so ("Simulierte Filiale - Mittwoch 14:00").

### 2.6 Throughput

- Guided: 3:00 + 0:30 handover -> at most 17 per hour; realistic 8-12 per
  hour at 50-70 % load.
- Express: about 75 s + 15 s -> up to 40 per hour in theory; realistic
  20-25 per hour in a queue.
- Planning number: 100-160 hands-on visitors per fair day (8 h), plus 2-4
  watchers each.
- One till only. Two parallel tills would double the hardware and break the
  "one story" monitor; not recommended for v1.

---

## 3. Scenarios

### 3.1 S1 "Die Ente schwimmt nicht" (default, all day)

Deterministic trigger (all must hold; computed by `engine`, section 8):

- `sold_today / planned_so_far < 0.60` and Poisson `P(X <= sold | planned) < 0.05`
  with `planned_so_far >= 10`.
- Days of supply above target (`stock / (velocity x 12 h)` = 3.3 d vs 2.0 d).
- No active promotion on the article, no open proposal in this visit, not
  excluded (alcohol, deposit, price-bound).

Preset data (applied at every visit start):

| Field | Value |
|---|---|
| Article | `article004` / `IDarticle004` "GEBIT Ente" (GEBIT's own test article [V]) |
| Price / VAT / cost | 8,67 EUR gross, 19 % (tax class C [V]), net 7,29; cost net 4,40 |
| Stock | 140 |
| Plan today | 120 (60 by 14:00 store time) |
| Sold today by 14:00 | 21 (closed receipts only) -> Poisson p = 5.7e-9 |
| Velocity | 3.5 per store hour vs plan 10 |
| Price history | 8,67 for the last 60 days except a -20 % week 6 weeks ago (outside the 30-day window) -> `lowest_price_30d` = 8,67 |
| Elasticity | -1.67 (from that promo week: -20 % price gave +45 % units) |
| Horizon | 24 selling hours (sell-out by Saturday), leftover weight 0.6 |

Engine result (computed today with the formula of section 8):

| Step | Price | Units by horizon | Leftover | Gross profit | Margin | Verdict |
|---|---|---|---|---|---|---|
| none | 8,67 | 84 | 56 | 94.6 | 39.6 % | baseline |
| -10 % | 7,80 | 100 | 40 | 110.9 (+16.4) | 32.9 % | slot B |
| **-20 %** | **6,93** | **122** | **18** | **126.6 (+32.0)** | **24.4 %** | **slot A (recommended)** |
| -30 % | 6,06 | 140 | 0 | 96.9 (+2.4) | 13.6 % | blocked: margin floor 20 % |
| -40 % | 5,20 | 140 | 0 | -4.2 | -0.7 % | blocked: max 30 %, margin |

The line for the audience: "30 % wuerde alles abverkaufen, aber die Marge
faellt unter die Untergrenze. 20 % bringt den hoechsten Rohertrag." The
visitor can prove it on the tablet by trying -30 %.

Promotion prices are the exact percentage rounded down to the cent
(6,93 = -20.07 %), so the shelf can honestly say "-20 %" against the 30-day
lowest price. A classic 6,99 would be only -19.4 % and would have to be
shown as "-19 %" (section 8.1). The demo uses GEBIT's own sample price
8,67 [V] on purpose.

### 3.2 S2 "MHD-Retter" (variant for grocery visitors, host card "SZENARIO 2")

- Article `article010` "Bio-Joghurt Erdbeere 500 g" (dummy pack), 1,49 EUR,
  7 %, cost net 0,78, stock 18, best-before **today** (store date), 6 selling
  hours left, velocity 1.5 per hour -> 9 cups would be thrown away.
- Perishable objective: first zero projected waste, then gross profit
  (lexicographic, "bei MHD-Ware zaehlt zuerst: nichts wegwerfen"):

| Step | Price | Sold | Waste | GP | Margin | Verdict |
|---|---|---|---|---|---|---|
| none | 1,49 | 9 | 9 | -1.51 | 44 % | baseline |
| -20 % | 1,19 | 15.8 | 2.2 | 3.52 | 29.9 % | slot B (still waste) |
| **-30 %** | **1,04** | **18** | **0** | **3.46** | **19.7 %** | **slot A** |
| -50 % | 0,75 | 18 | 0 | -1.42 | -11 % | blocked: below net cost |

- Compliance moment: the label says "Reduziert wegen kurzer Haltbarkeit
  (MHD 17.02.)" and shows **no** 30-day line, because § 11 Abs. 4 Nr. 2
  PAngV exempts perishables reduced for imminent expiry when the reason is
  visible [V]. The tablet check reads "MHD-Ausnahme: Grund sichtbar".
- Still needs the click (C11 decision below: "Ohne Freigabe kein neuer
  Preis" holds for both scenarios).
- In S2 the duck sells at plan (preset), so there is exactly one proposal
  per visit.

### 3.3 Secondary moments that need no extra build

- **Aktionskollision:** "Fruchtgummi Baeren 200 g" has an active "-15 % bis
  Sonntag" promotion in the preset. Scanning it shows the teal chip "Aktion
  laeuft bereits - kein Vorschlag". Shows rules without any LLM.
- **Ablehnen:** the visitor taps "Ablehnen" and a reason chip ("Ware kommt
  nach"). Monitor: "Abgelehnt von Marktleitung - kein neuer Preis". The
  story continues to payment and voucher. "Auch Nein ist Steuerung."
- **Verfall:** a proposal not decided within 120 s expires: "Vorschlag
  verfallen - Preis bleibt" (fail-safe, never auto-approve).
- **Bon abgebrochen** (Q&A): host taps "Bon abbrechen" ->
  `PurchaseTransactionCancelled` -> lines struck through, "nichts verkauft,
  kein Gutschein". This is GEBIT's finality rule in one picture.

### 3.4 Why the triggers are reliable

- The hero's sales baseline is a **preset of a simulated store**, not the
  booth scans, so the duck stays a slow seller all day although every
  visitor scans it (tradeshow track 3.5).
- Background tills (`02`-`05`) publish closed receipts of the other articles
  only (never the hero in S1, never the yoghurt in S2), about one every 4 s,
  for ambient motion. They never reach SAM.
- The visitor's own duck counts only after `PurchaseTransactionClosed`
  ("21 -> 23 verkauft"), which makes the finality rule visible.

### 3.5 Cut from v1 (reserve list, and why)

| Idea | Why cut for the visitor | Where it could return |
|---|---|---|
| Live basket offer ("Guacamole -30 % zu Ihren Chips") | A second proposal per visit doubles the cognitive load and the LLM calls | Phase 3 reserve scenario, framed as a tied conditional offer (outside Art. 6a, critic C4) |
| Loyalty persona cards | Needs cards, explanation, privacy talk; adds 30 s | Phase 3 for repeat visitors |
| LLM-written voucher text | Invisible value, extra latency at the payment burst (0.45 s gap [V]) | Optional flag `VOUCHER_TEXT_AI` after G3 |
| Auto-executed MHD rule ("Autonomie-Stufe") | Contradicts the headline "Ohne Freigabe kein neuer Preis" | Talk-track slide only |
| "Rueckgaengig" 60 s undo | Extra path and states; reset already covers it | Phase 3 |
| SAM chat assistant for the store manager | Not one-click, cannot be pushed, LLM cost | Deep-dive extra if time permits |
| Receipt printer | The duck and the phone QR are the take-away; fiscal look-alike risk | Optional, "DEMO - kein Kassenbeleg" |
| Bonshooter feed | Bursts of several scans per second; GEBIT approval needed | Phase 3: feeds background tills only, never SAM |
| Vendor ESL kit | Latency unknown (one Vusion integration averages ~20 min [V]); every ESL vendor is in the hall | Only if a loan passes a < 10 s test |

---

## 4. Architecture

### 4.1 Picture

```text
 booth LAN (wired, router travels with the Mac)                    public internet
 ------------------------------------------------                  ---------------
 [scanner]-USB->[POS mini PC: /kasse + /kunde]--HTTPS--+            [landing page,
 [tablet /freigabe]--------------------------HTTPS-----+             static, fragment
 [monitor mini PC /monitor]------------------HTTPS-----+             payload only]
 [deep-dive laptop /op, SAM UI, Grafana]-----HTTPS-----+                   ^
 [ESP32 e-paper ESL]--MQTT 1883 (VPN default)---+      |                   | phone
                                                |      v                   |
 booth Mac (Rancher Desktop k3s + host docker)  |   gpos-ui (BFF, SSE)  visitor
   host docker: solace-1 ------------------------+   |  ^ POST /api/...
     VPN sam (SMF 55557, WS 8008)  <-----------------+  | SSE
     VPN default (MQTT 1883) for the ESL only        |  |
   host docker: postgres (db gpos)                   v  |
   k3s ns gpos-demo:                           gpos-pos (simulator | bridge)
     gpos-pos  --raw GEBIT proto3 JSON--> gebit/rp/purchase/v2/... (VPN sam)
     gpos-engine (state, rules, MCP :8765) <--subscribes raw + gpos/v1/...
     gpos-ui
   k3s ns sam-solace-lab:
     gwe: entrypoint gpos-booth-events --(rule 1: booth till raw)--> gpos-pos-event
                                       --(rule 2: decisions)--------> gpos-apply-decision
     awe: workflows -> MCP connector gpos-booth-tools -> gpos-engine:8765
     agent gpos-pricing-writer (fast tier, LiteLLM)
```

### 4.2 Components

| Component | Responsibility | Runs where | Tech |
|---|---|---|---|
| `gpos-pos` | POS adapter with GEBIT method names (`CreatePurchaseTransaction`, `AddArticle`, `ChangeArticlePositionItemCount`, `VoidArticlePosition`, `StartPaymentProcess`, `CreateCashPayment`, `CancelPurchaseTransaction`, `ApplyAnonymousCoupon`). **Mode `sim`:** emits GEBIT proto3 JSON built from GEBIT's descriptor sets (`purchase-api-2.50.0.pb`, `receipt-api-2.13.0.pb`), including the binary receipt in `PurchaseTransactionClosed`; pricing stub (article master + promotions) read at `AddArticle`; background tills. **Mode `bridge`:** forwards commands to GEBIT's gRPC service and relays GEBIT's events to the same topics. | k3s `gpos-demo`, 1 replica | Python 3.12, `protobuf` 6.33 with `DescriptorPool` (no codegen; all 11 GEBIT samples parse strictly [V]), `solace-pubsubplus` (SMF), FastAPI for commands, later `grpcio` |
| `gpos-engine` | The deterministic store core. Subscribes to the raw topics directly (ordered by `metadata.offset`, dedup `txId:offset`). Basket state with `positionId -> article` map; finality; scenario presets and store clock; signals; markdown candidates; guardrails; proposals; price-change requests; ESL updates; vouchers; audit; KPIs; watchdogs (section 12). Exposes the MCP tools SAM calls and an HTTP API for the UI. | k3s `gpos-demo`, 1 replica, `Recreate` | Python 3.12, FastAPI, `mcp[cli]==2.2.0` (streamable HTTP, stateless, JSON, Pydantic returns, `--dump-tools`), `psycopg` 3, `solace-pubsubplus` (VPN `sam`) + `paho-mqtt` (VPN `default`, ESL only) |
| `gpos-ui` | BFF: one SSE stream per view, typed view model (Scan, Insight, Proposal, Decision, PriceChange, Voucher, SamRun, Health); POST endpoints for scan, payment, decision, control; publishes decisions to the broker; serves all static pages; device tokens. Reads SAM status topics read-only (phase 2). | k3s `gpos-demo`, ingress `gpos.solace.lab` (TLS, lab CA) | Python 3.12, FastAPI + uvicorn, SSE, vanilla JS/CSS, self-hosted Inter |
| SAM entrypoint `gpos-booth-events` | Rule 1: every booth-till raw event -> `gpos-pos-event`. Rule 2: decision events -> `gpos-apply-decision`. | k3s `sam-solace-lab` (gwe) | SAM 2.493.0 declarative YAML |
| SAM workflows + agent | `gpos-pos-event` (tool -> switch -> rare agent), `gpos-apply-decision` (tool only), agent `gpos-pricing-writer` (fast). | awe | YAML |
| MCP connector `gpos-booth-tools` | Points at `http://gpos-engine.gpos-demo.svc:8765/mcp`, explicit generated `manifest:` list. | platform | YAML + `gen_connector_manifest.py` (BSG) |
| Broker | solace-1, VPN `sam` for everything (SMF 55557 from pods [V], WS 8008 for SAM), VPN `default` MQTT 1883 only for the ESL dual-publish. | host docker | existing, no broker change |
| Postgres | Database `gpos`: master data, presets, price history, runtime state, audit, KPIs. | host docker `postgres` | existing container, idempotent `seed.sh` |
| ESL | 4.2" black/white e-paper on an Ethernet ESP32, subscribes `gpos/v1/esl/...` on VPN `default` (MQTT), renders from fields with its own font. | shelf | ESP32-POE-ISO, GxEPD2, PubSubClient |
| Landing page | Static mobile page; voucher and "how it happened" from the URL fragment; no backend, no cookies. | public static host (GEBIT or Solace web space) | HTML/CSS/JS |
| Grafana dashboard | Proposals, approvals, latency, tokens (phase 2). | existing Grafana | generated ConfigMap (BSG `gen_dashboard.py`) |

Packaging follows BSG: one image `registry.solace.lab/gpos-demo/gpos-demo:<semver>`
with three commands, kustomize manifests, hardened pods, `install.sh
k8s|mesh|all`, `uninstall.sh`, `reset.sh`, `preflight.sh`, repo directory
`gebit-price-agent-demo/` (prefix `gpos`). Multi-arch build (arm64 for the
Mac, amd64 for GEBIT) from G3.

### 4.3 What is AI and what is rule (shown on screens, said by the host)

| Step | Who | Label |
|---|---|---|
| Ingest event, basket state, finality, voids | engine (code) | Kasse / Regel |
| Slow-seller signal, Poisson test, days of supply | engine | Regel |
| Candidate steps, price points, gross profit | engine | Regel |
| Guardrails (margin, max discount, 30-day price, collisions) | engine | Regel |
| **Pick slot A or B and write headline + reason** | **agent `gpos-pricing-writer`** | **KI** |
| Validate the AI text (numbers, length, slot) | engine | Regel |
| Approve / adjust / reject | visitor | Mensch |
| Re-check, price change, ESL, voucher | engine via SAM tool nodes | Regel |
| Orchestration of every step | SAM workflows | (SAM badge) |

### 4.4 Swap seams for the GEBIT live connection

| Seam | Today (simulated) | GEBIT lab / later | What changes | What stays |
|---|---|---|---|---|
| S1 Event source | `gpos-pos` mode `sim` publishes proto3 JSON on `gebit/rp/purchase/v2/...` | `gpos-pos` mode `bridge` (or GEBIT publishes to our VPN directly, or a Kafka/other-to-Solace bridge) | Producer of the raw topics; binary -> JSON conversion with the same descriptor set if GEBIT sends binary | Topics, payload shape, engine, SAM rules, UI |
| S2 POS commands | `/kasse` -> BFF -> `gpos-pos` HTTP with GEBIT method names | Either the bridge calls GEBIT gRPC `PurchaseTransactionService`, or the **real GEBIT POS client** replaces `/kasse` (then `/kasse` is display only) | Backend of the command adapter | Command names, scan capture, customer display |
| S3 Price change | `price-change` request -> pricing stub in `gpos-pos` -> `price-changed` confirmation | `PriceChangePort` in the bridge maps to GEBIT's article-master contract (not yet specified [V]) | Port implementation, effective-time semantics | Proposal/decision/guardrail flow; confirmation event drives ESL |
| S4 30-day lowest price | engine computes from `price_history` | read from GEBIT's price service if it keeps it (question) | Data source of `ref30` | Display rules |
| S5 ESL | DIY e-paper via MQTT | Vendor ESL via GEBIT's integration, if a test shows < 10 s | Subscriber of `gpos/v1/esl/...` | Event, mirror tile |
| S6 Location / till | `Root.DE.999.101.01` (GEBIT sample [V]) | Lab location | Install-time variable `BOOTH_TILL_TOPIC` in rule 1 | Workflow |
| S7 Voucher redemption | `ApplyAnonymousCoupon` in the simulator | Promotion code created in GEBIT's promotion service | Code provisioning | QR, landing page |
| S8 Approval UI | our tablet | optionally GEBIT Attendant App publishing the same decision event | Publisher of `gpos/v1/decision/...` | `gpos-apply-decision` |

Invariant: SAM resources, the engine and all screens do not change at the
swap. Rehearse the switch in both directions (`POS_MODE=sim|bridge`).

---

## 5. Event and topic model

### 5.1 VPN, transport, format

- **VPN `sam`, SMF** for all booth traffic: same VPN as SAM, so SAM status
  events are visible; no broker change; SMF from pods via
  `tcp://host.docker.internal:55557` [V]. The entrypoint data plane uses
  `ws://host.docker.internal:8008` like SAM itself [V].
- **VPN `default`, MQTT 1883** only for the ESL: the engine dual-publishes
  each ESL update there (VPN `sam` has no MQTT listener [V]; critic C9
  option 2).
- Raw events: GEBIT proto3 canonical JSON with `@type`, validated against
  the descriptor set before publishing. Published **persistent** with ack;
  direct subscribers (engine, BFF) get them demoted [V vendor doc], the
  entrypoint queue spools them.
- Own events: compact JSON, `schema_version`, ASCII-only strings,
  decimals as JSON numbers, ISO timestamps with offset. Free text with
  umlauts never travels in our events; screens render German text from
  templates and fields.

### 5.2 Raw GEBIT-shaped topics (derived from the proto package, PUR 7.1)

```text
gebit/rp/purchase/v2/{category}/{EventName}/{country}/{company}/{store}/{till}/{txId}
  category  = proto file stem: purchase_transaction | basket | payment_session |
              fiscal_transaction | loyalty | ...
  booth till = DE/999/101/01, background tills = DE/999/101/02..05
```

User properties: `eventType`, `purchaseTransactionId`, `offset`, `traceId`,
`location`, `apiVersion=purchase-2.50.0`. Application message id
`{txId}:{offset}`. The `pos` keeps the `txId -> location` cache (only
`PurchaseTransactionCreated` carries `location` [V]).

Events of one guided visit (all on the booth till, all reach SAM):

| # | GEBIT event | Verdict of `assess_event` | Visible as |
|---|---|---|---|
| 1 | `PurchaseTransactionCreated` | `none` (engine applies the preset) | "Bon geoeffnet" |
| 2 | `PurchaseTransactionOpened` | `none` | receipt number |
| 3 | `PositionAdded` (espresso) | `none` + insight "laeuft nach Plan" | line + chip |
| 4 | `FiscalTransactionAssigned` | `none` | ticker only ("TSE: Simulation") |
| 5 | `PositionAdded` (duck) | **`propose`** | line + red chip + proposal card |
| 6 | `PositionAdded` (duck, 6,93) | `none` + insight "Aktion aktiv" | line with AKTION |
| 7 | `PaymentProcessStarted` | `none` | "Zahlung gestartet" |
| 8 | `CashPaymentPositionCreated` (exact amount, no change line) | `none` | "Bar 23,59 EUR" |
| 9 | `PaymentProcessCompleted` | `none` | |
| 10 | `PurchaseTransactionInChargingFinancialTransaction` | `none` | |
| 11 | `PurchaseTransactionInClosing` | `none` | |
| 12 | `PurchaseTransactionClosed` | **`close`** | "Verkauf final", voucher |
| (alt) | `PurchaseTransactionCancelled` | **`cancel`** | "nichts verkauft" |

Plus one decision event -> one `gpos-apply-decision` run. About 13 SAM runs
and 1 LLM call per visit. Background tills publish only
`PurchaseTransactionClosed` and never match rule 1.

### 5.3 Own topics (`gpos/v1/...`, never under `sam-solace-lab/`)

| Topic | Producer | Consumers | Payload (key fields) |
|---|---|---|---|
| `gpos/v1/insight/{store}/{till}/{txId}/{offset}` | engine | ui | `article_number`, `kind` (on_plan, slow_seller, promo_active, excluded), `text_key`, numbers |
| `gpos/v1/proposal/{state}/{store}/{articleNumber}/{proposalId}` (state: draft, ready, expired) | engine (from SAM tool calls or watchdog) | ui | full proposal record (5.4) |
| `gpos/v1/decision/{action}/{store}/{proposalId}` (action: approve, reject) | ui (BFF) | SAM rule 2, engine watchdog | decision record (5.4) |
| `gpos/v1/masterdata/price-change/{store}/{articleNumber}` | engine (`apply_decision`) | pos (stub or bridge) | request: old, new, ref30, kind, valid_from/to, proposal_id, approver_role |
| `gpos/v1/masterdata/price-changed/{store}/{articleNumber}` | pos | engine, ui | confirmation with `effective_at` |
| `gpos/v1/esl/{store}/{articleNumber}` | engine (on `price-changed` and on reset) | ESP32 (MQTT, VPN default), ui mirror (VPN sam) | fields only (5.4) |
| `gpos/v1/esl-ack/{store}/{articleNumber}` | ESP32 (MQTT) | engine, ui | `seq`, `rendered_at` |
| `gpos/v1/voucher/{state}/{store}/{txId}` (state: issued, discarded) | engine (`issue_voucher`, `discard_basket`) | ui | code, text_key, valid_until, landing-page fragment |
| `gpos/v1/samrun/{txId}/{offset}` | engine (inside every tool call) | ui | `run_id`, `verdict`, `node`, `ms` (counts "SAM-Laeufe") |
| `gpos/v1/sam/errors` | SAM entrypoint `errorOutput` | ui, op | error |
| `gpos/v1/control/{cmd}` (cmd: reset, scenario, mode) | ui (control cards, `/op`) | engine, pos | command |
| `gpos/v1/health/{component}` | all components every 5 s | ui (`/op`) | status, versions, lag |
| `sam-solace-lab/a2a/v1/gateway/status/<entrypointId>/>` | SAM (read only) | ui (phase 2) | real node progress [V format, internal] |

### 5.4 Payload sketches

Proposal (`ready`), about 1.2 KB:

```json
{"schema_version": "gpos.proposal.v1", "proposal_id": "prp-0216-0042",
 "visit_id": "v-0216-0042", "state": "ready", "kind": "MARKDOWN",
 "article": {"number": "article004", "id": "IDarticle004", "name": "GEBIT Ente"},
 "current_price": 8.67, "ref30": 8.67,
 "facts": {"sold_today": 21, "plan_so_far": 60, "stock": 140,
           "days_of_supply": 3.3, "target_days": 2.0, "poisson_p": 5.7e-9},
 "slots": {"A": {"pct": 20, "price": 6.93, "units_delta": 38, "gp_delta": 32.0, "margin_pct": 24.4},
           "B": {"pct": 10, "price": 7.80, "units_delta": 16, "gp_delta": 16.4, "margin_pct": 32.9}},
 "blocked": [{"pct": 30, "rule": "MARGIN_FLOOR", "value": 13.6, "limit": 20}],
 "chosen_slot": "A",
 "checks": [{"id": "MARGIN_FLOOR", "ok": true, "value": 24.4, "limit": 20},
            {"id": "MAX_DISCOUNT", "ok": true, "value": 20, "limit": 30},
            {"id": "REF30_SHOWN", "ok": true, "value": 8.67},
            {"id": "NO_PROMO_COLLISION", "ok": true}],
 "ai": {"headline": "GEBIT Ente: -20 % fuer den Rest des Tages",
        "rationale": "Heute 21 statt 60 verkauft, 140 Stueck reichen 3,3 Tage. -20 % bringt rund 38 Stueck und 32 EUR Rohertrag mehr; -30 % unterschreitet die Mindestmarge.",
        "source": "llm", "model": "fast", "ms": 5830},
 "valid_until_store": "20:00", "expires_at": "2027-02-16T14:34:05+01:00",
 "sam_run_id": "wfr-...", "trace_id": "v-0216-0042"}
```

Decision (from the BFF):

```json
{"schema_version": "gpos.decision.v1", "decision_id": "dec-0216-0042",
 "proposal_id": "prp-0216-0042", "action": "approve", "slot": "A", "pct": 20,
 "reason_code": null, "approver_role": "Marktleitung", "approver_ref": "tablet-01",
 "decided_at": "2027-02-16T14:32:05.120+01:00", "trace_id": "v-0216-0042"}
```

ESL update (ASCII fields; the firmware composes the German text):

```json
{"a": "article004", "name": "GEBIT Ente", "mode": "PROMO", "price": "6,93",
 "old": "8,67", "pct": 20, "ref30": "8,67", "mhd": null, "unit_line": null,
 "seq": 117}
```

### 5.5 Ordering and idempotency

- Dedup key everywhere: `purchaseTransactionId:offset` (raw), `proposal_id`
  (decisions, price changes), `receipt_id` (vouchers). Every state-changing
  tool is idempotent and returns the stored result on a repeat.
- The engine applies raw events in `offset` order with a 1 s reorder buffer
  per transaction; a gap older than 1 s is logged and skipped.
- Event-triggered SAM runs start concurrently (two runs 2 ms apart [V]), so
  `assess_event` never relies on arrival order: it ingests its raw text
  idempotently and reads the decision the engine stored for that offset.
- Stale guard: `assess_event` returns `stale` for events older than 20 s
  (backlog after a SAM outage must not produce late proposals).
- Visual order: the monitor sorts by `metadata.creationTimestamp` and
  de-bunches bursts at a 250 ms cadence while showing true times.
- Ack policy: rule 1 `on_receive` (a lost insight is harmless, a
  redelivery storm is not [V]); rule 2 `on_completion`, 20 s,
  `onFailure: ack` (the engine watchdog covers failures).

---

## 6. SAM resources

### 6.1 Entrypoint `gpos-booth-events`

```yaml
kind: entrypoint
name: gpos-booth-events
description: >-
  EuroCIS booth: every GEBIT Purchase Service event of the booth till starts
  gpos-pos-event; tablet decisions start gpos-apply-decision.
spec:
  type: event_mesh
  deploy: true
  values:
    broker_url: "ws://host.docker.internal:8008"
    broker_vpn: "sam"
    broker_username: "default"
    broker_password: ${GPOS_BROKER_PASSWORD}
    tls_skip_verify: "false"
    systemPurpose: "EuroCIS booth demo. German, ASCII only, short."
    event_rules:
      - name: booth_pos_events
        subscriptions:
          - topic: "${BOOTH_TILL_TOPIC}"   # gebit/rp/purchase/v2/*/*/DE/999/101/01/>
            qos: 1
        messageFormat: json
        targetWorkflowName: gpos-pos-event
        inputExpression: "input.payload:"   # no input_schema -> workflow.input.text
        defaultUserIdentity: power_user@solace.lab
        acknowledgmentPolicy: on_receive
        errorOutput:
          enabled: true
          topic: "gpos/v1/sam/errors"
          topicType: static
          responseType: error
      - name: booth_decisions
        subscriptions:
          - topic: "gpos/v1/decision/>"
            qos: 1
        messageFormat: json
        targetWorkflowName: gpos-apply-decision
        inputExpression: "input.payload:"
        defaultUserIdentity: power_user@solace.lab
        acknowledgmentPolicy:
          mode: on_completion
          timeoutSeconds: 20
          onFailure: {action: ack}
        errorOutput:
          enabled: true
          topic: "gpos/v1/sam/errors"
          topicType: static
          responseType: error
```

Business results are published by tool nodes (BSG pattern), so no
`successOutput` is needed (avoids the `structured` contradiction, C16).
`install.sh` renders the template and waits for the gwe log line "persistent
receiver started" for both rules before the first event [V pattern].

### 6.2 Workflow `gpos-pos-event` (one run per raw booth event)

Node graph:

```text
assess (tool) -> route (switch)
                  |-- verdict == propose --> write (agent, fast) --> publish (tool)
                  |-- verdict == close   --> voucher (tool)
                  |-- verdict == cancel  --> discard (tool)
                  '-- default            --> done (tool, no-op note)
```

```yaml
kind: workflow
name: gpos-pos-event
description: >-
  One run per GEBIT POS event of the booth till: a deterministic tool node
  ingests and classifies it; only a decision moment wakes the pricing
  writer; a closing event issues the voucher; a cancel discards the basket.
spec:
  appConfig:
    version: "0.1.0"
    workflow_timeout: "25s"
    default_node_timeout: "6s"
    fail_fast: true
    skills:
      - id: gpos_pos_event
        name: GEBIT POS event
        description: Classify one POS event and act on decision moments.
    # Deliberately no input_schema: the raw proto3 JSON (with @type) arrives
    # as workflow.input.text [V critic 2.5]. Gate 0 confirms; fallback is a
    # digest topic with a declared schema.
    nodes:
      - id: assess
        type: tool
        connector: gpos-booth-tools
        tool: assess_event
        timeout: "5s"
        input:
          raw: "{{workflow.input.text}}"
          run_id: "{{workflow.run_id}}"
      - id: route
        type: switch
        depends_on: [assess]
        cases:
          - condition: "'{{assess.output.mcp_structured_content.verdict}}' == 'propose'"
            node: write
          - condition: "'{{assess.output.mcp_structured_content.verdict}}' == 'close'"
            node: voucher
          - condition: "'{{assess.output.mcp_structured_content.verdict}}' == 'cancel'"
            node: discard
        default: done
      - id: write
        type: agent
        agent_name: gpos-pricing-writer
        depends_on: [route]
        timeout: "12s"
        instruction: >-
          Choose the slot for this markdown proposal and explain it for the
          store manager. Return exactly these keys: slot, headline, rationale.
        input:
          proposal: "{{assess.output.mcp_structured_content.writer_input}}"
        output_schema_override:
          type: object
          required: [slot, headline, rationale]
          properties:
            slot: {type: string, enum: [A, B, none]}
            headline: {type: string}
            rationale: {type: string}
      - id: publish
        type: tool
        connector: gpos-booth-tools
        tool: publish_proposal
        depends_on: [write]
        input:
          proposal_id: "{{assess.output.mcp_structured_content.proposal_id}}"
          slot: "{{write.output.slot}}"
          headline: "{{write.output.headline}}"
          rationale: "{{write.output.rationale}}"
          run_id: "{{workflow.run_id}}"
      - id: voucher
        type: tool
        connector: gpos-booth-tools
        tool: issue_voucher
        depends_on: [route]
        input:
          tx_id: "{{assess.output.mcp_structured_content.tx_id}}"
          run_id: "{{workflow.run_id}}"
      - id: discard
        type: tool
        connector: gpos-booth-tools
        tool: discard_basket
        depends_on: [route]
        input:
          tx_id: "{{assess.output.mcp_structured_content.tx_id}}"
          run_id: "{{workflow.run_id}}"
      - id: done
        type: tool
        connector: gpos-booth-tools
        tool: note_event
        depends_on: [route]
        input:
          event_key: "{{assess.output.mcp_structured_content.event_key}}"
          verdict: "{{assess.output.mcp_structured_content.verdict}}"
          run_id: "{{workflow.run_id}}"
    output_mapping:
      verdict: "{{assess.output.mcp_structured_content.verdict}}"
      event_key: "{{assess.output.mcp_structured_content.event_key}}"
      proposal_id:
        coalesce:
          - "{{publish.output.mcp_structured_content.proposal_id}}"
          - "none"
      voucher_id:
        coalesce:
          - "{{voucher.output.mcp_structured_content.voucher_id}}"
          - "none"
```

### 6.3 Workflow `gpos-apply-decision` (tool only, sub-second)

```yaml
kind: workflow
name: gpos-apply-decision
description: >-
  Applies a human decision from the booth tablet: re-checks the guardrails,
  requests the price change at the article master and records the audit.
  No model in this workflow.
spec:
  appConfig:
    version: "0.1.0"
    workflow_timeout: "15s"
    skills:
      - id: gpos_apply_decision
        name: Apply decision
        description: Apply an approved or rejected price proposal.
    input_schema:            # every key the BFF sends, no `text`
      type: object
      required: [proposal_id, action]
      properties:
        schema_version: {type: string}
        decision_id: {type: string}
        proposal_id: {type: string}
        action: {type: string, enum: [approve, reject]}
        slot: {type: [string, "null"]}
        pct: {type: [number, "null"]}
        reason_code: {type: [string, "null"]}
        approver_role: {type: string}
        approver_ref: {type: string}
        decided_at: {type: string}
        trace_id: {type: string}
    nodes:
      - id: apply
        type: tool
        connector: gpos-booth-tools
        tool: apply_decision
        timeout: "8s"
        input:
          proposal_id: "{{workflow.input.proposal_id}}"
          decision_id: "{{workflow.input.decision_id}}"
          action: "{{workflow.input.action}}"
          pct: "{{workflow.input.pct}}"
          reason_code: "{{workflow.input.reason_code}}"
          approver_role: "{{workflow.input.approver_role}}"
          approver_ref: "{{workflow.input.approver_ref}}"
          decided_at: "{{workflow.input.decided_at}}"
          run_id: "{{workflow.run_id}}"
    output_mapping:
      status: "{{apply.output.mcp_structured_content.status}}"
```

### 6.4 Agent `gpos-pricing-writer`

```yaml
kind: agent
name: gpos-pricing-writer
description: >-
  Picks one of the pre-checked markdown slots and writes a short German
  rationale for the store manager. Never computes or invents numbers.
spec:
  type: standard
  modelProvider: [fast]          # Haiku 4.5 via LiteLLM
  toolsets: []
  additionalConfigurations:
    supportsStreaming: false
  skills:
    - id: price_proposal_text
      name: Price proposal text
      description: Slot choice and German rationale for one markdown proposal.
  inputModes: [text]
  outputModes: [text]
  systemPrompt: |
    You write price proposal texts for a German supermarket in a trade fair
    demo. You run autonomously behind an event trigger; never ask a question.
    Every number, price, percentage and article name comes from the input;
    never invent or recompute one. Call no tool. Never call load_artifact,
    create_sqlite_db, merge_structured_data, transform_data_with_jmespath,
    artifact_search_and_replace_regex or append_to_artifact.
    slot: the input's "recommended" slot unless another slot fits the facts
    clearly better; "none" only if every slot is blocked.
    headline: German, at most 70 characters, names the article and the
    percentage.
    rationale: German, at most two sentences and 220 characters: why now
    (sales against plan, stock), why this depth, and why not the deeper
    step if the input lists it as blocked.
    Write German in ASCII: ae, oe, ue, ss, EUR.
```

Writer input (built by `assess_event`, about 0.8 KB, inlined into the
prompt):

```json
{"article": "GEBIT Ente", "kind": "markdown",
 "facts": {"sold_today": 21, "plan_so_far": 60, "stock": 140,
           "days_of_supply": 3.3, "target_days": 2.0, "ref30_eur": 8.67},
 "slots": {"A": {"pct": 20, "price_eur": 6.93, "units_delta": 38, "gp_delta_eur": 32.0},
           "B": {"pct": 10, "price_eur": 7.80, "units_delta": 16, "gp_delta_eur": 16.4}},
 "blocked": [{"pct": 30, "rule": "Mindestmarge 20 %", "margin_pct": 13.6}],
 "recommended": "A"}
```

### 6.5 MCP connector `gpos-booth-tools` and tool list

Connector: `type: mcp`, `subtype: remote`, `server_url:
http://gpos-engine.gpos-demo.svc:8765/mcp`, `streamable-http`, `auth_type:
none`, explicit generated `manifest:` YAML list (memory/BSG rules [V]). All
tools return Pydantic models below 2048 bytes [V threshold] and never echo a
raw GEBIT event.

| Tool | Called by | Does | Returns (structured) |
|---|---|---|---|
| `assess_event(raw, run_id)` | `gpos-pos-event.assess` | Parse proto3 JSON, ingest idempotently, publish `samrun`; on the hero scan create the draft proposal (slots, checks) and publish `proposal/draft` | `verdict` (none, propose, close, cancel, stale, duplicate), `event_key`, `tx_id`, `event_type`, `proposal_id`, `writer_input` |
| `publish_proposal(proposal_id, slot, headline, rationale, run_id)` | `publish` | Validate the AI output (section 8.4), fall back to the template on failure, publish `proposal/ready` | `proposal_id`, `text_source` (llm, template), `status` |
| `apply_decision(proposal_id, decision_id, action, pct, reason_code, approver_role, approver_ref, decided_at, run_id)` | `gpos-apply-decision.apply` | Idempotent; re-run all guardrails with fresh state; on approve publish `masterdata/price-change`; record decision and audit | `status` (applied, rejected, blocked, expired, duplicate), `change_id`, `new_price` |
| `issue_voucher(tx_id, run_id)` | `voucher` | Only if the basket is CLOSED; idempotent per receipt; pick the catalogue template by rule; publish `voucher/issued` | `voucher_id`, `code`, `template` |
| `discard_basket(tx_id, run_id)` | `discard` | Mark the basket cancelled; never a voucher; publish `voucher/discarded` | `status` |
| `note_event(event_key, verdict, run_id)` | `done` | Count the SAM run, nothing else | `status` |

### 6.6 How the owner's wishes are fulfilled or honestly replaced

| Wish | How it is fulfilled | Honest note |
|---|---|---|
| Follow each scan live | Monitor and customer display read the raw events directly from the broker (< 0.5 s) | Not via SAM, on purpose: the visitor never waits for a workflow to see a scan |
| A SAM workflow on every single POS event | Rule 1 starts `gpos-pos-event` for every booth-till event (about 13 per visit); the monitor counts them; SAM Activities shows each run with skipped nodes dimmed | Load-tested at Gate 0 (450 runs/h, 7 parallel). Fallback: subscribe only `PositionAdded`, `PaymentProcessStarted`, `Closed`, `Cancelled` |
| First insights and proposals as notifications in SAM | SAM tool nodes push the insight chips and the proposal to the tablet and the monitor (that is the "notification"); every run is in SAM Activities | SAM's notification service is rc-only and off on this lab, and `notify_user` has no action field [V]. Revisit if Solace confirms GA |
| Human approval where necessary | Tablet -> decision event -> tool-only `gpos-apply-decision` | No native SAM approval works for event-triggered runs [V]; this is the only one-click path |
| Live promotions per article | The approved "Aktion -20 %" on the scanned article, active from the next scan, on shelf and till | Basket-tied offers kept in reserve |
| At payment, the workflow waits for the closing event, then a voucher | There is no wait node [V]. The engine holds the basket per `purchaseTransactionId`; the `Closed` event starts its own run, whose switch issues the voucher; `Cancelled` discards | The "waiting" is the engine's state, which is the robust event-driven pattern |

---

## 7. Data model and demo dataset

### 7.1 Postgres (database `gpos`, host container, `seed.sh` idempotent)

Master and preset data (seeded):

```sql
article(article_number text primary key, article_id text, gtin text,
        name text, category text, food boolean, perishable boolean,
        vat numeric(4,2), regular_price numeric(8,2), cost_net numeric(8,2),
        unit text, net_qty numeric(8,3), unit_price_basis text,
        shelf_slot text, image text, excluded_reason text);
scenario(scenario_id text primary key, name text, store_time_start time,
         time_factor int, hero_article text, params jsonb);
scenario_article(scenario_id text, article_number text, plan_today int,
                 sold_until_start int, stock int, velocity_per_h numeric,
                 elasticity numeric, horizon_h int, leftover_weight numeric,
                 best_before_offset_days int, active_promo jsonb,
                 primary key (scenario_id, article_number));
price_history(article_number text, store_id text, price numeric(8,2),
              valid_from timestamptz, valid_to timestamptz,
              kind text,          -- REGULAR | PROMO | MARKDOWN | PERISHABLE
              announced boolean);
sales_daily(article_number text, store_id text, day date, units int,
            avg_price numeric(8,2));            -- 8 weeks, for the chart and eval
voucher_template(code text primary key, rule text, priority int,
                 text_key text, valid_days int);
```

Runtime state (reset per visit where noted):

```sql
visit(visit_id text primary key, scenario_id text, started_at timestamptz,
      ended_at timestamptz, outcome text);              -- kept
basket(tx_id uuid primary key, visit_id text, till text, status text,
       receipt_number text, opened_at timestamptz, closed_at timestamptz,
       total numeric(10,2), last_offset bigint);         -- kept
basket_line(tx_id uuid, position_id uuid, article_number text,
            unit_price numeric(8,2), item_count int, voided boolean,
            price_source text, primary key (tx_id, position_id));
event_log(tx_id uuid, "offset" bigint, event_type text, received_at timestamptz,
          via_sam boolean, sam_run_id text, verdict text,
          primary key (tx_id, "offset"));                -- kept, purged nightly
proposal(proposal_id text primary key, visit_id text, article_number text,
         kind text, status text, slots jsonb, blocked jsonb, checks jsonb,
         chosen_slot text, final_pct numeric, new_price numeric(8,2),
         ref30 numeric(8,2), ai jsonb, text_source text, via text,
         created_at timestamptz, ready_at timestamptz, decided_at timestamptz,
         applied_at timestamptz, expires_at timestamptz, sam_run_id text);
decision(decision_id text primary key, proposal_id text, action text,
         pct numeric, reason_code text, approver_role text, approver_ref text,
         decided_at timestamptz, via text);
active_price(article_number text, store_id text, price numeric(8,2),
             kind text, valid_from timestamptz, valid_to timestamptz,
             proposal_id text, primary key (article_number, store_id));
                                                   -- the "article master" stub
price_change(change_id text primary key, proposal_id text, article_number text,
             old_price numeric, new_price numeric, ref30 numeric,
             requested_at timestamptz, effective_at timestamptz,
             esl_ack_at timestamptz, first_scan_at timestamptz);
voucher(voucher_id text primary key, tx_id uuid unique, code text,
        template text, issued_at timestamptz, redeemed_at timestamptz, via text);
audit_event(id bigserial primary key, ts timestamptz, kind text, ref text,
            payload jsonb);                       -- append-only, kept
kpi_day(day date primary key, scans int, sam_runs int, llm_calls int,
        proposals int, approved int, adjusted int, rejected int, expired int,
        vouchers int, fallbacks int);
```

No vector store; Qdrant is not needed.

### 7.2 Assortment (8 articles, one 1.2 m shelf)

Article numbers follow GEBIT's convention (`articleNNN`, `IDarticleNNN`
[V]). GTINs are in-store EANs from the GS1 restricted range (prefix 20-29),
printed on stickers. No deposit, no alcohol, no age restriction at the booth
(they would add `PositionAdded` companions or an age check [A]).

| No | Article | Cat. | VAT | Price | Cost net | Stock | Role |
|---|---|---|---|---|---|---|---|
| 004 | **GEBIT Ente** (rubber duck, physical, giveaway) | Non-Food | 19 | **8,67** | 4,40 | 140 | **S1 hero** |
| 010 | **Bio-Joghurt Erdbeere 500 g** (dummy) | Molkerei, perishable | 7 | 1,49 | 0,78 | 18 | **S2 hero** (MHD today in S2, +5 d in S1) |
| 005 | Schaumbad Lavendel 500 ml | Drogerie | 19 | 2,95 | 0,95 | 36 | voucher target (Ente -> Schaumbad) |
| 007 | Espresso Bohnen 500 g | Kaffee | 7 | 7,99 | 4,20 | 30 | "laeuft nach Plan" |
| 008 | Cantuccini 200 g | Gebaeck | 7 | 2,29 | 0,95 | 32 | voucher target (Espresso -> Cantuccini) |
| 011 | Knusper-Muesli 750 g | Fruehstueck | 7 | 3,99 | 1,85 | 20 | voucher target (Joghurt -> Muesli) |
| 019 | Fruchtgummi Baeren 200 g | Suesswaren | 7 | 1,29 | 0,45 | 60 | active promo -15 % ("Aktionskollision") |
| 025 | GEBIT Mehrweg-Einkaufstasche | Non-Food | 19 | 1,50 | 0,60 | 50 | ambient, "laeuft nach Plan" |

Voucher catalogue (rule-based, issued only on `PurchaseTransactionClosed`,
one per receipt, first matching rule wins, "Demo-Gutschein ohne Geldwert"):

| Prio | Code | Rule (this basket only) | Text on the customer display |
|---|---|---|---|
| 1 | `VCH-SCHAUMBAD-30` | basket contains the duck (affinity Ente -> Schaumbad) | "-30 % auf Schaumbad Lavendel beim naechsten Einkauf, 14 Tage gueltig" |
| 2 | `VCH-MUESLI-20` | basket contains the yoghurt | "-20 % auf Knusper-Muesli beim naechsten Einkauf" |
| 3 | `VCH-CANTUCCINI-20` | basket contains espresso | "-20 % auf Cantuccini beim naechsten Einkauf" |
| 4 | `VCH-WELCOME-10` | otherwise, total >= 5 EUR | "10 % auf Ihren naechsten Einkauf ab 10 EUR, max. 2 EUR" |

Physical stock at the booth: 3 x the expected draw for dummies; ducks per
GEBIT's giveaway budget (planning: 400 per day). The 7 % tax class letter
comes from GEBIT (sample shows only C = 19 % [V]).

### 7.3 History shapes (seed, 8 weeks, deterministic `random.seed`)

- Daily units = `plan x weekday factor x shape x LogNormal(0, 0.15)`,
  Poisson-rounded; weekday factors Mon 0.85 ... Sat 1.35, Sun closed.
- Ente: stable, then -4 % per week in the last 3 weeks; one promo week at
  -20 % six weeks back with +45 % units (gives the elasticity and stays
  outside the 30-day window).
- Joghurt: stable; Fruchtgummi: current promo since 3 days; all others
  stable.
- Price history 60 days for every article (`lowest_price_30d` source).
- Hourly plan curve (store hours 08-20): 0.05, 0.06, 0.08, 0.09, 0.11, 0.10,
  0.07, 0.07, 0.09, 0.11, 0.10, 0.07 (sum 1.00; 0.49 of the day passed at
  14:00).

### 7.4 Personas

None in v1 (cut, section 3.5). The visitor is anonymous; no personal data is
captured, stored or shown. Lead capture happens outside our system (Messe
lead app badge scan by the greeter, CTA links on the landing page).

### 7.5 Store clock and time compression

- `store_time = 14:00 + 20 x (now - visit_start)`, so a 3-minute visit is one
  store hour; the plan-so-far grows from 60 to about 70 during a long visit.
- Idle: clock frozen at 14:00, background tills keep emitting receipts of
  non-hero articles (motion without changing the hero's numbers).
- Monitor chip at all times: "Simulierte Filiale - Mittwoch 14:00 -
  Zeitraffer 20x". The promotion validity is "heute bis 20:00" in store
  time; reset ends it anyway.

### 7.6 Scenario preset (file `data/scenarios.yaml`, loaded into Postgres)

```yaml
scenarios:
  - id: S1
    name: "Die Ente schwimmt nicht"
    store_time_start: "14:00"
    time_factor: 20
    hero: article004
    articles:
      article004: {plan_today: 120, sold_until_start: 21, stock: 140,
                   velocity_per_h: 3.5, elasticity: -1.67, horizon_h: 24,
                   leftover_weight: 0.6}
      article010: {plan_today: 30, sold_until_start: 15, stock: 18,
                   best_before_offset_days: 5}
      article019: {active_promo: {pct: 15, until: "Sonntag"}}
  - id: S2
    name: "MHD-Retter"
    store_time_start: "14:00"
    time_factor: 20
    hero: article010
    articles:
      article010: {plan_today: 30, sold_until_start: 9, stock: 18,
                   velocity_per_h: 1.5, elasticity: -2.5, horizon_h: 6,
                   leftover_weight: 1.0, best_before_offset_days: 0}
      article004: {plan_today: 120, sold_until_start: 58, stock: 140}
      article019: {active_promo: {pct: 15, until: "Sonntag"}}
```

---

## 8. Decision logic, autonomy, guardrails

### 8.1 Signals (deterministic, engine)

- `planned_so_far = plan_today x sum(curve up to store hour)`.
- `STR = sold_today / planned_so_far`; Poisson `p = P(X <= sold | lambda = planned_so_far)`.
- `days_of_supply = stock / (velocity_per_h x 12)`.
- Demand at price `p`: `q(p) = min(stock, velocity x (p / p0)^eps x H)`.
- `GP(d) = (p_net(d) - cost_net) x q(d) - w x cost_net x leftover(d)`.
- Price points: a promotion price is the exact step percentage **rounded
  down** to the cent (8,67 x 0.8 = 6,936 -> 6,93), so the displayed
  percentage, computed against `lowest_price_30d` and floored, is never
  overstated (guardrail A02). A ,99 price point would display -19 % and
  confuse the story.
- Objective: non-perishable = max GP; perishable = zero projected waste
  first, then max GP.
- `lowest_price_30d = min(applied prices in the 30 days before now)`.

### 8.2 One parameter set (`policy/pricing-policy.yaml`)

```yaml
version: "2027.02-eurocis-A"
direction:
  markdown_only: true                 # never a price increase (B01, B07)
  uniform_shelf_price: true           # no customer input to prices (C01)
trigger:
  str_below: 0.60
  poisson_p_below: 0.05
  min_planned_so_far: 10
  days_of_supply_above_target: true
markdown:
  steps_pct: [10, 20, 30, 40]         # engine evaluates; tablet stepper offers the same
  max_one_click_pct: 30               # above: "braucht Zweitfreigabe" -> blocked at the booth
  perishable_max_pct: 50
  margin_floor_net_pct: {non_food: 20, food: 12, perishable_mhd: 0}  # MHD: never below net cost
  price_rounding: floor_cent          # displayed % never overstated (A02)
  max_changes_per_article_per_store_day: 2
  one_proposal_per_visit: true
  proposal_expiry_s: 120              # expiry = no change (D02)
pangv:
  ref_window_days: 30
  require_ref_for_announced_reduction: true      # A01-A04
  display_pct_basis: ref30                       # floor() of the percentage
  ref_line: "Niedrigster Preis der letzten 30 Tage: {ref30}"
  perishable_exception:                           # A05, critic C5
    max_days_to_best_before: 2
    label: "Reduziert wegen kurzer Haltbarkeit (MHD {bbd})"
  no_uvp_comparison: true
exclusions:
  categories: [alcohol, tobacco, deposit, price_bound]
  active_promo_collision: block
approval:
  required_for: [MARKDOWN, MHD_MARKDOWN]          # every shelf price, both scenarios
  recheck_at_commit: true                         # D03
  approver_role: "Marktleitung"
voucher:
  only_on: PurchaseTransactionClosed              # C03
  never_on: PurchaseTransactionCancelled
  per_receipt: 1
  catalogue_only: true                            # C02
  max_value: {pct: 30, eur: 2.00}
  validity_days: 14
  no_cash_value: true                             # E04
llm:
  calls_per_proposal: 1
  in_flight_per_till: 1
  agent_timeout_s: 12
  budget_breaker_pct: 80                          # then template text only
privacy:
  drop_customer_data: true                        # C06: names, addresses never ingested
fiscal:
  receipt_watermark: "DEMO - kein Kassenbeleg"
  tse: "Simulation"
```

### 8.3 Autonomy policy (one rule for the booth)

- **The AI proposes, rules check, a human decides.** No shelf price changes
  without a tap - true for both scenarios, so "Ohne Freigabe kein neuer
  Preis" is literally true on the booth (critic C11; the MHD auto rule stays
  a talk-track variant).
- The route (approval required, blocked, expired) is computed by the engine
  from the action parameters **after** the LLM answered; the LLM never sees
  or sets it.
- Automatic actions without a click: insights (silent), vouchers from the
  catalogue issued on `Closed` (personalised reductions issued on purchase,
  outside Art. 6a [V]), resets.
- Forbidden (never generated): price increases, personalised shelf prices,
  promotions on excluded categories, below-cost prices outside the MHD path,
  any change of fiscal or payment data.

### 8.4 Validator for the AI text (`publish_proposal`, milliseconds)

1. `slot` in {A, B, none}; if it differs from `recommended`, accept only if
   that slot is not blocked; else use `recommended` and flag.
2. Every number in headline and rationale (regex `\d+([.,]\d+)?`) must occur
   in the writer input (prices, percentages, units, euros) or be the slot's
   percentage.
3. The article name must appear; no other article name from the assortment.
4. Lengths: headline <= 70, rationale <= 220 characters, at most 2
   sentences; banned phrases ("nur jetzt", "letzte Chance", "garantiert"),
   no URLs.
5. On any failure: template text, `text_source=template`, small badge
   "Text aus Vorlage", reason logged (becomes an eval row).

Template (also the L1 text): headline "{name}: -{pct} % fuer den Rest des
Tages"; rationale "Heute {sold} statt {plan} verkauft, Bestand reicht
{dos} Tage. -{pct} % bringt rund {units} Stueck mehr; -{blocked_pct} %
unterschreitet die Mindestmarge."

### 8.5 Compliance moments on the booth (each 2-5 s, no extra step)

1. **30-day line** on the ESL and the customer display, same visual block,
   legible size: "Niedrigster Preis der letzten 30 Tage: 8,67 EUR" (§ 11 Abs. 1
   PAngV, BGH I ZR 183/24 [V]). Tablet check "PAngV § 11 ok".
2. **Margin floor and max discount** turn red live when the visitor tries
   -30 % or -40 % on the tablet; "Freigeben" disables and says why.
3. **MHD exception** (S2): reason on the label, no 30-day line, check
   "MHD-Ausnahme: Grund sichtbar" (§ 11 Abs. 4 Nr. 2).
4. **Finality**: dashed lines until `Closed`; voucher only after `Closed`;
   "Bon abgebrochen - kein Gutschein" on cancel.
5. **Fiscal honesty**: customer display footer "DEMO - kein Kassenbeleg -
   TSE: Simulation"; no fiscal QR is ever shown.
6. **No profile**: voucher card says "Grundlage: nur dieser Bon. Kein Profil
   gespeichert. Regalpreis fuer alle gleich."
7. **Honest percentage**: the displayed "-20 %" is computed against the
   30-day lowest price and floored; the price is rounded down so it is never
   overstated (C-330/23 Aldi Sued, A02 [V]). Good answer for the compliance
   visitor who asks "why 6,93 and not 6,99?".
8. **AI label**: every AI sentence carries "KI-Vorschlag (Modell: fast)"; every
   applied change "freigegeben von: Marktleitung" (AI Act Art. 50 spirit).

Legal wording review by GEBIT/legal before G4 (owner decision 14.2).

---

## 9. User interfaces

General rules: German, Sie-form, short verbs ("Erkannt", "Vorgeschlagen",
"Freigegeben", "Aktiv"); German number format "6,93 EUR" rendered as
"6,93 €"; tabular numerals; never colour alone (icon + label). Colour tokens:
Kasse blue `#3B82F6`, KI violet `#8B5CF6`, Regel teal `#14B8A6`, Mensch orange
`#F59E0B`, Zahlung/final green `#22C55E`, Fehler red `#EF4444`. Font: Inter
(OFL), self-hosted, no CDN. Monitor dark (control-room look), tablet light
(paper form). All text with umlauts and the euro sign comes from UI
templates; agent text is ASCII and shown on the tablet and as one sentence
on the monitor. English toggle for the whole booth via `/op` (phase 2;
in EN mode the rationale uses the template text).

Tech: `gpos-ui` FastAPI serves static HTML/CSS/vanilla JS; one SSE stream
per view (`/api/stream?view=...`, snapshot + events, auto-reconnect);
Web Animations API only; Screen Wake Lock; heartbeat to `/op`; device token
per kiosk (header), no broker credentials in any browser.

### 9.1 Booth monitor `/monitor` (65", 1920x1080 CSS px, viewed at 3-5 m)

Type scale (65", from the tradeshow track's computation [V]): price numbers
220-260 px, step strip 72 px, headline 100 px, passer-by text >= 80 px,
receipt lines 52 px, tech ticker 30 px. At most three content zones, at most
7 words per headline.

```text
+--------------------------------------------------------------------------------+
| KI schlaegt vor. Sie geben frei.        [Simulierte Filiale - Mi 14:00 - 20x]  |
| (1 Scan) --> (2 KI-Vorschlag) --> (3 Freigabe) --> (4 Neuer Preis)   <- glows  |
+---------------------------+----------------------------------------------------+
| LIVE AN DER KASSE         |  [duck photo]  GEBIT Ente                          |
| Bon 0042  (vorlaeufig)    |  8,67 €  -->  6,93 €            (240 px)           |
| - - Espresso 7,99 €  [ok] |  [red] Ladenhueter: 21 statt 60 verkauft            |
| - - GEBIT Ente 8,67 € [!] |  [violet KI] "-20 % bringt rund 38 Stueck mehr..." |
| - - GEBIT Ente 6,93 € AKT |  [teal] Marge 24 % ok - Max 30 % ok - 30-Tage ok   |
| Summe 23,59 €             |  [orange] Freigegeben 14:32 - Marktleitung          |
|                           |  [ESL mirror tile: exact label rendering]          |
+---------------------------+----------------------------------------------------+
| ticker: PositionAdded .../DE/999/101/01 - SAM-Lauf 0,4 s - 0 Tokens |          |
| Heute: 13 Ereignisse -> 13 SAM-Laeufe -> 1 KI-Aufruf  - Scans 143 - frei 29    |
+--------------------------------------------------------------------------------+
```

States: attract (section 2.2); visit (above); "Verkauf final" (lines solid,
green check, fan-out animation, voucher card replaces the proposal card);
"Bon abgebrochen" (lines struck through); degraded badge in the top right
("Text aus Vorlage", "Direktmodus", "Wiedergabe").

### 9.2 Approval tablet `/freigabe` (11" landscape, light)

- Header: "Marktleitung - Freigaben (1 offen)".
- Card (fills the screen):
  - Duck photo, "GEBIT Ente - article004".
  - **"8,67 € -> 6,93 € (-20 %)"** (96 px), "gueltig heute bis 20:00".
  - "Warum" - three facts with source icons: "Heute 21 statt 60 verkauft
    (Kasse)", "Bestand 140 - reicht 3,3 Tage (Bestand)", "Keine laufende
    Aktion (Aktionen)".
  - "KI-Einschaetzung" (violet): the rationale.
  - "Wirkung": "+38 Stueck bis Samstag - +32 € Rohertrag - Marge 24 %".
  - "Pruefregeln" (teal): Mindestmarge 20 % - Max. Rabatt 30 % - 30-Tage-
    Tiefstpreis wird angezeigt (PAngV § 11) - keine Aktionskollision.
- Buttons: **Freigeben** (full width, 88 px, orange), **Anpassen** (stepper
  -10 / -20 / -30 / -40 %, recomputes impact and checks locally from the
  slot table the engine sent; a red check disables Freigeben and says why),
  **Ablehnen** (reason chips "Aktion laeuft bereits", "Marge zu niedrig",
  "Ware kommt nach", "Sonstiges").
- Before the AI text arrives: numbers and checks shown, "KI formuliert
  Begruendung ..." with elapsed seconds; Freigeben enabled when the text
  arrives or after the 12 s fallback.
- After the tap: "Freigegeben - wird an Kasse und Regal verteilt", then
  "Preis aktiv 14:32:06".
- Audit footer: "Vorschlag prp-0042 - KI: gpos-pricing-writer (fast) -
  Daten: Kasse, Bestand, Aktionen - Freigabe: Marktleitung (tablet-01) -
  14:32:05".
- Kiosk: iPad Guided Access, touch targets >= 56 px, screen flash on a new
  proposal (no sound).

### 9.3 POS: cashier screen `/kasse` and customer display `/kunde`

- `/kasse` (15.6" touch, host side): line list with event chips
  (`PositionAdded ok`), total; buttons "Summe", "Bar (Demo)", "Zeile
  stornieren", "Bon abbrechen"; product tiles as scanner fallback ("Artikel
  antippen" fires the same `AddArticle`); banner "Neuer Preis aktiv seit
  14:32 (Freigabe Marktleitung)". Global keydown buffer (characters < 50 ms
  apart, Enter-terminated) catches scans regardless of focus; control
  barcodes `##CTL:RESET`, `##CTL:S1`, `##CTL:S2`, `##CTL:EXPRESS`,
  `##CTL:MODE-DIRECT` never reach the POS as articles.
- `/kunde` (13", visitor side): last item large (price 140 px), running
  total; on a promotion "AKTION -20 %", old price struck, new price, "Sie
  sparen 1,74 €", "Niedrigster Preis der letzten 30 Tage: 8,67 €" in the
  same block; at the end "Danke! Ihr Gutschein fuer den naechsten Einkauf"
  with a QR >= 4 cm and a short URL; footer "DEMO - kein Kassenbeleg".
- In the GEBIT lab the real GEBIT POS client may replace `/kasse`; `/kunde`
  stays ours unless GEBIT brings a customer display.

### 9.4 Shelf label (ESL) and `/etikett`

- 4.2" black/white e-paper (400x300), partial refresh 0.4 s, full 5 s [V]:
  name; price at >= 40 % of the label height; inverse banner "AKTION -20 %"
  or "Reduziert wegen kurzer Haltbarkeit (MHD 17.02.)"; line "Niedrigster
  Preis der letzten 30 Tage: 8,67 €" (non-perishable promo only); Grundpreis
  where required (yoghurt "1 kg = 2,08 €" at 1,04); article number. Full
  refresh on every reset (avoids ghosting).
- The firmware renders text from fields with a Latin-1 font (umlauts, euro),
  acks each `seq` on `gpos/v1/esl-ack/...`.
- `/etikett`: pixel-identical rendering on a small LCD in a shelf housing
  (fallback, labelled "ESL-Simulation") and as the mirror tile on the
  monitor (always on, for the back row).

### 9.5 Visitor phone page (public, static)

- URL `https://<public-host>/ente#v=<base64url JSON>`; the fragment never
  reaches a server. Payload: voucher code, text key, validity, and "your
  path" numbers (events, SAM runs, AI calls, seconds to proposal, approved
  at). No personal data, no cookies, no tracking.
- Content: voucher card "-30 % auf Schaumbad Lavendel - Demo-Gutschein ohne
  Geldwert"; "So ist Ihr Gutschein entstanden" (5 steps: Scan - KI-Vorschlag
  - Ihre Freigabe - Bon final - Gutschein) with the real numbers of the visit;
  CTAs "Gespraech vereinbaren" (GEBIT and Solace contact pages), "Mehr ueber
  Solace Agent Mesh", "Mehr ueber die GEBIT Retail Platform".

### 9.6 Operator `/op` (deep-dive laptop)

Device heartbeats (monitor, tablet, POS, ESL ack age), component health
(pos, engine, ui, broker VPN `sam`, entrypoint receivers, MCP), mode switch
L0/L1/L2 and scenario S1/S2, reset, last 20 runs with verdict and ms, LLM
p50/p90 and today's calls, budget estimate, last errors, links to SAM
Activities and Grafana, EN toggle (phase 2).

---

## 10. Hardware, booth BOM, network

### 10.1 BOM (rough street prices incl. VAT, from the tradeshow track [V] where given)

| Item | Choice | Qty | Price |
|---|---|---|---|
| Booth monitor | 65" commercial 24/7 panel (e.g. Samsung QM65C) + floor stand, or rent from the booth builder | 1 | 1,100-1,500 € + 150-300 € (or rental) |
| Monitor player | Mini PC (N100 class), Chromium kiosk, Ethernet | 1 | 200-400 € |
| POS station | Mini PC + 15.6" USB-C touch (cashier) + 13" portable display (customer) | 1 set | 200-400 € + 200-300 € + 120-200 € |
| Scanner | Zebra DS9308 hands-free, USB HID (German layout set); spare DS2208 with stand | 1 + 1 | ~320 € + ~120 € |
| Approval tablet | iPad 11" (A16) in Guided Access, lockable stand, USB-C Ethernet + PD adapter; spare iPad | 2 | ~350 € each + 150 € stand + 40 € adapter |
| ESL | Waveshare 4.2" B/W e-paper + Olimex ESP32-POE-ISO + 3D-printed shelf-edge housing; 1 spare pre-flashed | 2 | ~30 € + ~30 € + 10 € each |
| `/etikett` fallback | 5-7" HDMI/USB LCD in a shelf housing (or an old phone) | 1 | ~60 € |
| Shelf + products | 3-level shelf (1.2 m), duck basin, 8 articles (dummies for the yoghurt), stickers with in-store EANs | 1 | 150-300 € + 150 € |
| Giveaway | GEBIT rubber ducks (branded; GEBIT to confirm availability) | ~1,200 | ~0.60-1.20 € each |
| Network | Router with automatic WAN failover (wired Telekom primary, 5G secondary, Wi-Fi off), e.g. Teltonika RUTX50; 16-port switch; cables; 2 SIMs | 1 | ~570 € + 50 € + 50 € |
| Power | UPS for Mac + switch + router; power strips | 1 | 150-200 € |
| Booth host | Existing lab MacBook (Rancher Desktop k3s, solace-1, Postgres), lid open, `caffeinate` | 1 | existing |
| Hot spare | Second laptop with the standalone stack (section 12.3) | 1 | existing |
| Spares and kit | HDMI/USB-C cables, gaffer tape, laminated control cards, cable locks | - | 200-300 € |
| Messe services (via GEBIT OOS) | Wired internet line, 24 h socket for the host, (no own AP) | - | per OOS price list |

Budget band: about **4,500-6,500 €** bought (or about 3,000 € with a rented
monitor), plus the ducks. No receipt printer in v1.

### 10.2 Network

```text
 Messe wired line (Telekom) --+                    +-- 5G (SIM A/B)
                              v                    v
                      [router RUTX50, 192.168.50.1, Wi-Fi off, DNS overrides]
                              |  gpos.solace.lab -> 192.168.50.10
                      [16-port switch]
        +---------+---------+-------+---------+----------+-----------+
     Mac .10   monitor .21  POS .22  tablet .23 laptop .24  ESP32 .31 (+ spare .32)
   (k3s, broker,  (kiosk)  (kiosk)  (USB-C Eth) (/op)      (MQTT -> .10:1883)
    postgres)
```

- Everything wired; Messe Duesseldorf forbids own access points unless
  approved [V]. The tablet sits on a stand with USB-C Ethernet + power.
- **The booth router travels with the Mac**: from G2 the lab Mac lives
  behind this router with the same static IP at home, in the GEBIT lab and
  at the fair. This avoids the k3s stale-external-IP wedge [V memory].
- Kiosk devices trust the lab CA (one-time profile/cert install) and resolve
  `gpos.solace.lab` through the router. Uplink needed only for LiteLLM
  (`lite-llm.mymaas.net` [V]) and the public landing page.

---

## 11. Latency budget and LLM cost

### 11.1 Latency per step (what the visitor waits for)

Measured bases [V]: publish -> workflow start ~22 ms; MCP tool node
0.12-1.4 s; single-call fast agent node 4.9-6.0 s.

| Segment | Target | Hard limit -> action |
|---|---|---|
| Scan -> line on `/kasse` and `/kunde` | < 0.3 s | 1 s (local path, no SAM) |
| Scan -> line + insight chip on the monitor | < 0.5 s | 1 s |
| Hero scan -> proposal card with numbers (draft) | < 1.5 s | 4 s -> engine watchdog publishes the draft itself, badge "Direktmodus" |
| Hero scan -> AI text on tablet and monitor | 6-9 s | 12 s -> template text, badge "Text aus Vorlage" |
| Tap Freigeben -> "Freigegeben" on the monitor | < 0.3 s | BFF shows it optimistically |
| Tap -> `apply_decision` done | < 1.5 s | 3 s -> engine applies directly |
| Tap -> price active in the stub (`price-changed`) | < 2 s | 3 s |
| Tap -> e-paper shows the new price | 2-6 s | 10 s -> mirror tile carries the moment, alarm on `/op` |
| Re-scan -> new price at the till | < 0.3 s | 1 s |
| `PurchaseTransactionClosed` -> voucher QR | < 2 s | 3 s -> engine issues directly |
| Reset | < 8 s | 15 s |
| Workflow timeouts | `gpos-pos-event` 25 s, agent node 12 s, tool nodes 5-8 s; `gpos-apply-decision` 15 s | errorOutput -> `/op` |

GEBIT lab: the article-master latency is unknown; G3 must measure "approval
-> next `AddArticle` returns the new price" and accept at most 5 s.

### 11.2 LLM cost

Per call (measured token profile of a single-turn fast node: ~14.4k input,
of which ~13.7k cached prefix; our output ~250 tokens; Haiku 4.5 USD 1 / 5
per MTok [V]): **USD 0.0049 warm, 0.0192 cold, 0.0158 if the proxy ignores
caching**.

| Item | Calls | USD |
|---|---|---|
| Fair, 3 days x 100-160 hands-on visitors, 1 call each (repeat scans do not re-propose) | 300-480 | 1.5-9.2 |
| Preflight and warm-up (5 per morning) | 15 | 0.1-0.3 |
| Rehearsals G1-G4 (about 600 runs) | 600 | 3-11.5 |
| Nightly eval from G3 (8 rows x 3 runs + judge, ~USD 0.6 per night x 14) | - | ~8 |
| **Total** | | **about USD 13-29** |

- Per-event SAM runs without an agent cost 0 tokens.
- Compare: an LLM on every booth event would be 13x the calls (USD 20-120
  for the fair), and a BSG-style 3-agent run per event USD 0.027-0.063 each
  - gating is mandatory [V critic C8].
- The 50 USD LiteLLM cap is a hard limit whose period and current spend are
  unknown [V]. Request a dedicated fair key with 100 USD and alarms at 50 /
  80 %; the engine estimates spend from `tasks` token rows and trips the 80 %
  breaker (template texts) itself.

---

## 12. Reliability

### 12.1 Degradation ladder (automatic where possible, always labelled)

| Level | Trigger (detected by) | What runs | Visitor sees |
|---|---|---|---|
| **L0 Live** | normal | SAM workflows + agent | full story |
| **L1 Text aus Vorlage** | agent > 12 s, LiteLLM 429/5xx, budget breaker 80 %, internet down (engine watchdog per proposal; 2 consecutive -> sticky for 10 min) | SAM workflows, template text | identical story, small badge "Text aus Vorlage" |
| **L2 Direktmodus** | no `assess_event` for a hero scan within 4 s, no `apply_decision` within 3 s, no voucher within 3 s (watchdogs); or operator switch / `##CTL:MODE-DIRECT` | engine does every step itself with the template text | identical story, badge "Direktmodus"; SAM counters pause |
| **L3 Hot spare** | booth Mac or k3s/broker down (preflight or `/op` red > 60 s) | spare laptop: docker compose with Solace PubSub+ Standard, Postgres, `gpos-pos`, `gpos-engine`, `gpos-ui` in `MODE=direct`; router DNS `gpos.solace.lab` -> spare; ESL via mirror and `/etikett` only | same screens, badge "Notbetrieb"; about 2 min to switch |
| **L4 Video** | everything down | attract-loop film of a full run on the monitor player | "Aufzeichnung" |

Watchdogs are idempotent: if SAM finishes late, the result is ignored
(`duplicate`). Every L0 run during rehearsals is recorded (events,
proposal, timings) for regression and for the L4 film.

### 12.2 Device fallbacks

| Failure | Fallback (time) |
|---|---|
| Scanner | spare DS2208 (10 s) or product tiles on `/kasse` |
| Tablet | spare iPad (30 s) or the approval card on `/kasse` |
| ESL | mirror tile always on; `/etikett` LCD; spare ESP32 (2 min) |
| Monitor player | `/monitor` on the deep-dive laptop turned to the aisle |
| POS mini PC | `/kasse` on the laptop + USB scanner |
| Internet | 5G failover (automatic); then L1 |
| LiteLLM budget | L1 (automatic) |
| Booth Mac wedge (sleep clock wedge, dead port forwards, stale IP, stale vz.pid [V memory]) | L3 spare, fix in the background with the documented recovery |

### 12.3 Lab host hardening

- Dedicated for the fair from G4: no sleep (`caffeinate`, energy settings),
  no OS or Rancher updates, Do Not Disturb, lid open, UPS, 24 h socket
  ordered (otherwise a rehearsed cold start each morning, power-on to READY
  in < 15 min).
- Never changes networks after G2 (travel router).
- Only `gpos` installed on the platform from G4 (uninstall BSG and other
  overlays; the installer refuses to start if their entrypoints exist).
- Daily: `sam auth login` (token expires daily [V]), export the day's runs
  and logs (Loki keeps 7 days [V]).

### 12.4 Preflight (`scripts/preflight.sh`, READY / NOT READY, < 3 min)

1. Host clock year and NTP sanity; Mac IP = k8s `kubernetes` endpoint;
   Kyverno pods running.
2. solace-1 up; VPN `sam` operational (SEMP GET), spool usage < 50 %;
   VPN `default` MQTT 1883 reachable.
3. Pods `gpos-pos`, `gpos-engine`, `gpos-ui` ready; Postgres `gpos`
   reachable; preset S1 loaded.
4. SAM: `gpos-booth-events` deployed, gwe log shows both persistent
   receivers; workflows and agent deployed; MCP `tools/list` from the awe pod.
5. Model probe: one fast call through LiteLLM < 8 s; budget headroom shown.
6. **Dry fire**: scripted visit on the booth till (S1): Created, espresso,
   duck -> draft < 4 s, ready < 12 s with `text_source=llm`; approve via
   the BFF -> `price-changed` < 3 s -> ESL ack < 10 s; re-scan at 6,93; pay ->
   voucher < 3 s; reset < 15 s. Prints all segment times.
7. Devices: heartbeats from monitor, tablet, POS, ESL within 10 s.
8. Ends with READY or the first failing step and its fix.

### 12.5 Daily routine

Morning: power/cold start, `sam auth login`, preflight READY, one warm-up
run per scenario (warms the prompt cache), ESL full refresh, shelf restock.
Hourly: glance at `/op`. Evening: export runs and logs, reset KPIs (or keep
the day), restock, charge tablets, shutdown or confirm 24 h power.

---

## 13. First draft scope, build plan, effort, acceptance

### 13.1 First local draft (target G1, 4 Dec 2026) must contain

- `gpos-pos` sim: command subset (Created, AddArticle, StartPayment,
  CashPayment exact, Cancel); proto3 JSON from GEBIT descriptors including
  the binary receipt in `Closed`; pricing stub; background tills (closed
  receipts only).
- `gpos-engine`: ingest with offset ordering and dedup, basket state,
  finality, S1 preset, signals, slots, guardrails, proposals, decision
  apply, price change, voucher, audit, KPIs, all three watchdogs; MCP tools
  (6) with Pydantic returns < 2 KB; HTTP API for the UI.
- SAM: connector with generated manifest, agent, both workflows, entrypoint
  with both rules, install/uninstall scripts.
- `gpos-ui`: `/kasse` (with keyboard-wedge capture and tiles), `/kunde`,
  `/freigabe`, `/monitor` (functional layout, final type scale not yet),
  `/etikett`; reset and control cards.
- Postgres schema + seed (8 articles, 8-week history, price history).
- Tests: engine golden scenarios (S1 slots, blocked 30 %, no proposal on
  plan, collision, voucher only on Closed, cancel -> no voucher, idempotency,
  out-of-order offsets), descriptor round trip of every emitted event.

Later (not in the first draft): ESP32 ESL, S2, phone page, `/op` polish,
attract loop, final copy, SAM status sniff, Grafana, eval suite, hot spare,
GEBIT bridge, EN toggle, voucher redemption scan.

### 13.2 Phases and gates

| Gate | Window | Content | Acceptance criteria |
|---|---|---|---|
| **G0 Spikes and decisions** | 11-20 Nov 2026 (KW 46-47) | (a) Raw GEBIT JSON as `workflow.input.text` into a tool node (2.6-4.9 KB); (b) switch default to a no-op tool node; (c) load: 450 tool-only runs/h for 30 min plus 7 parallel runs per payment burst; (d) agent latency with ~0.8 KB input, 250 output tokens; (e) umlaut path agent -> tool -> Python SMF consumer; (f) persistent publish reaches the entrypoint queue and a direct subscriber; (g) SMF from pods to 55557, MQTT dual publish; (h) LiteLLM budget period/spend and a fair key requested; (i) owner decisions of section 14.2 | (a)-(b) pass 20/20; (c) p95 run duration < 2 s, 0 failed runs, no awe/gwe restart; (d) p50 <= 6.5 s, p90 <= 9 s over 20 calls; (e) result documented, ASCII rule kept or lifted; (f)-(g) pass; decisions recorded in README "Decisions" |
| **G1 Vertical slice on the lab** | 23 Nov - 4 Dec (KW 48-49) | First local draft (13.1) running end to end on the lab with the simulator | 20 consecutive S1 visits without manual intervention; scan -> line < 0.5 s p95; hero scan -> AI text p90 <= 10 s; tap -> price active <= 2 s; Closed -> voucher <= 2 s; reset <= 10 s; 0 tokens on non-hero runs (checked in `tasks`); engine tests green |
| **G2 Booth-complete MVP** | 7-18 Dec (KW 50-51) | ESP32 ESL, S2, final monitor/tablet/kunde layouts and type scale, attract loop, `/op`, L1/L2 watchdogs, preflight, phone page on a public host, hardware delivered and on the travel router, German copy v1, legal review started | ESL flip <= 6 s p90 over 50 flips; L1 and L2 forced 10x each without a visible hang (> 12 s); preflight READY from cold in < 15 min; readability check at 5 m (headline, price, step strip) passed by 3 non-team people; 10-second test: 4 of 5 passers-by can say what happened |
| Holiday buffer | 21 Dec - 6 Jan | low intensity: firmware polish, copy, deck, eval rows, Messe orders prepared with GEBIT | GEBIT answers to the five blocking questions (14.3 items 1-5) received by 8 Jan, else G3 runs on the simulator only |
| **G3 GEBIT lab integration and reliability** | 7-22 Jan 2027 (KW 1-3) | `gpos-pos` bridge (transport per GEBIT), price-change port, location config, run on real GEBIT events in GEBIT's lab with the travel router; L3 hot spare; SAM status sniff on the monitor; Grafana; eval suite nightly; 2 h soak; Messe orders placed by 15 Jan (21-day surcharge window [V 2018 rule]) | 20 visits on real GEBIT events with identical screens; approval -> next `AddArticle` new price <= 5 s; bridge switch sim <-> lab in < 5 min both ways; soak: 0 failed runs, cost per call <= USD 0.01 blended; hot-spare switch drill <= 3 min; eval >= 0.9, no wrong slot |
| **G4 Dress rehearsal and freeze** | 25 Jan - 5 Feb (KW 4-5) | 3 rehearsal days with booth staff (all roles), express and show modes, 100 runs, legal sign-off of on-screen wording, freeze of code, policy, data and lab on 5 Feb | 100 runs, >= 98 % without any fallback, 100 % without a visible hang; every staff member did host and operator once; legal sign-off documented; frozen version tagged |
| **G5 Setup and fair** | ship 12 Feb, setup 14-15 Feb, fair 16-18 Feb | network and failover test (pull the cable), glare check, 10 runs, staff briefing; daily routine | preflight READY each morning by opening; L3 never needed (target) |

### 13.3 Effort (person-days, Solace side unless noted)

| Work package | PD |
|---|---|
| G0 spikes and measurements | 4 |
| `gpos-pos` simulator (descriptors, receipt, pricing stub, background) | 5 |
| `gpos-engine` (state, signals, policy, guardrails, proposals, apply, voucher, watchdogs, KPIs) | 9 |
| MCP tools, connector manifest, agent, workflows, entrypoint, install/uninstall/reset | 5 |
| `gpos-ui` BFF and views (monitor 5, tablet 3, kasse/kunde 3, etikett 1, op 2, attract 1) | 15 |
| ESP32 ESL firmware, fonts, housing, ack | 4 |
| Postgres schema, seed generator, scenarios | 3 |
| Phone landing page | 1.5 |
| Preflight, runbook, README, talk track, one slide deck | 5 |
| Tests (engine golden, round trip, smoke without SAM), eval set, soak | 6 |
| Grafana dashboard and SAM status sniff | 3 |
| Hot spare standalone stack | 3 |
| GEBIT bridge and price-change port (Solace side) | 6 |
| Hardware procurement, network, kiosk setup | 4 |
| Rehearsals and staff training (excl. fair days) | 6 |
| Buffer (about 10 %) | 8 |
| **Total Solace side** | **about 88** |
| GEBIT side: event transport into Solace, price-change contract and lab support, legal wording, ducks, booth logistics | 10-15 |
| Fair days (staff, not build) | 3 days x 3-4 people |

With two builders from G0 to G4 (about 50 working days each after holidays)
the plan fits with the buffer; with one builder, cut Grafana, the status
sniff, the hot spare and S2 first (about 15 PD).

---

## 14. Risks, open decisions, questions

### 14.1 Risks (ranked) and mitigations

| # | Risk | Mitigation |
|---|---|---|
| 1 | Booth Mac wedges (sleep, network change, reboot) take everything down | Dedicated host, travel router from G2, no sleep, UPS + 24 h power, preflight, L3 hot spare (2 min) |
| 2 | Per-event SAM runs overload gwe/awe at bursts (7 runs within 1 s), or run out of order | G0 load test; stateless idempotent tools; engine is the ordered state owner; fallback rule with key events only; watchdogs |
| 3 | AI text > 12 s or LiteLLM budget exhausted | Draft card with numbers at < 1.5 s; one call per visit; template fallback; dedicated key; 80 % breaker |
| 4 | GEBIT price-change contract or event transport comes late or is slow (cache) | Simulator stays the default; swap seams S1-S3 isolated; ask by 11 Dec; G3 acceptance "<= 5 s or stay simulated"; fallback for the live phase: apply the Aktion as a GEBIT promotion code if their API allows |
| 5 | ESL flip slow or fails | DIY B/W partial refresh, mirror tile always on, spare board, vendor ESL only after a < 10 s test |
| 6 | Visitors do not get the story | 10-second test at G2; four numbered stations; physical duck; host's three sentences |
| 7 | Legal/credibility attack by retail compliance people (30-day line, MHD reason, fiscal look-alikes) | Per-visit preset, legally complete label templates, "DEMO - kein Kassenbeleg", no fiscal QR, legal sign-off at G4 |
| 8 | Umlaut mangling in the agent path | ASCII agent output, UI templates, G0 test |
| 9 | Hall network (no own Wi-Fi, congestion) | Everything wired, 5G failover, uplink needed only for LiteLLM |
| 10 | Platform conflicts with other demos | Only `gpos` installed from G4, installer guard |
| 11 | Duck theft / stock-out | 400 per day, restock routine; the hero is in the data, the physical duck is a prop |

### 14.2 Open decisions (with recommendation)

| # | Decision | Recommendation |
|---|---|---|
| 1 | Every shelf change by click, or an MHD auto rule (C11) | **Click for both scenarios**; auto rule only on a slide |
| 2 | Guardrail numbers (C12) | **The set in 8.2**: floors 20 / 12 / 0 % (non-food / food / MHD), one-click max 30 %, MHD max 50 %, expiry 120 s, max 2 changes per article per store day |
| 3 | Per-visit preset vs ambient continuity (C13) | **Per-visit preset**, labelled "Simulierte Filiale - Mittwoch 14:00" |
| 4 | Raw GEBIT events into SAM per event vs digest only (C7, 2.5) | **Raw events of the booth till, every event**, if G0 passes; else key events; background never |
| 5 | LiteLLM budget | **Dedicated fair key, 100 USD**, alarms 50/80 %; Haiku 5.5 only after a G0 latency test |
| 6 | ESL transport (C9) | **Dual-publish to VPN `default` MQTT**; no broker change |
| 7 | Enable rc-only SAM notifications | **No** for the fair; ask Solace about GA |
| 8 | Approver identity | **The visitor as "Marktleitung (tablet-01)"**, run identity `power_user@solace.lab`; no Keycloak user on the tablet |
| 9 | Live phase approval UI | **Our tablet**; GEBIT Attendant App only if it can publish the same decision event |
| 10 | Voucher in the live phase | **Digital (customer display QR + phone)**; native `CheckoutCoupon` only if GEBIT offers it |
| 11 | Framing | **"Markdown gegen Ladenhueter und Lebensmittelverschwendung, mit Freigabe"** |
| 12 | ESL hardware | **DIY e-paper** + mirror; vendor loan in parallel via GEBIT |
| 13 | Coexistence with BSG | **Uninstall other overlays from G4**; installer guard |
| 14 | Booth host | **Lab Mac dedicated from G4** + hot-spare laptop; a second full SAM host only if budget allows (+4 PD) |
| 15 | Legal review owner | **GEBIT legal or a retained lawyer**, by G4; DFA reference after the 11 Nov 2026 proposal |
| 16 | UI language | **German**, EN toggle in phase 2 |
| 17 | Kiosk access | **TLS via ingress + lab CA on the kiosk devices + router DNS**; fallback a LAN-bound HTTP port |
| 18 | Physical giveaway | **The duck** (needs GEBIT budget and branding) |

### 14.3 Questions for GEBIT (by 11 Dec 2026; items 1-5 block G3)

1. Event transport of the `PurchaseDomainEvents` in the demo lab (Solace,
   Kafka, gRPC, other), binary or proto3 JSON, all tills visible to one
   consumer? Can the lab publish to a Solace VPN we provide?
2. Price change to the article master: message, endpoint, fields
   (valid from/to, store scope, reason, reference price, approver,
   correlation id), confirmation, latency until the next `AddArticle` uses
   it; meaning of `priceSource: freezePrice`; do open baskets keep the old
   price (our "same duck, two prices" moment depends on it)?
3. Does your price service keep the 30-day lowest price per article and
   store? Can we read it?
4. Booth: hall, stand size, power (24 h socket), wired line, staff for host
   and greeter, opening hours; may we bring our router and devices?
5. Can the real GEBIT POS client and a customer display run at the booth,
   or should our `/kasse` stay?
6. Branded rubber ducks: availability, quantity, branding rules.
7. ESL vendor in your projects; can a kit be borrowed; measured API-to-label
   latency?
8. Can we create a promotion and an anonymous coupon code via API in the
   lab (for redemption of the booth voucher)?
9. Approved wording for demo receipts and TSE simulation at a fair; tax
   class letter for 7 %; booth till location.
10. Which customer names and logos may appear on booth material?
11. Legal review of the on-screen PAngV wording.

### 14.4 Questions for Solace (product / engineering)

1. Concurrency limits of the event-mesh entrypoint and awe for many short
   parallel runs; can per-rule ordering be configured?
2. Workflow HIL pause/resume via the notification service: GA timeline, and
   will it work for event-mesh-triggered runs?
3. Is the raw `workflow.input.text` path (no `input_schema`) a supported
   contract for large JSON payloads?
4. Can the event-mesh data plane reconnect forever (today 60 x 5 s [V])?
5. Are the `a2a/v1/gateway/status/...` payloads stable enough for a
   customer-facing monitor?
6. Root cause of mangled non-ASCII agent output at Solace consumers.
7. Can `toolsetExcludedTools` drop the always-attached artifact tools to cut
   the ~13.7k-token prefix?
8. Is Solace exhibiting at EuroCIS 2027 or only through GEBIT; joint
   marketing approved?
9. Could Event Portal show the GEBIT event catalogue on the deep-dive
   laptop (add-on)?
