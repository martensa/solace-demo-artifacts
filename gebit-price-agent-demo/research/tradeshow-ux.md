# EuroCIS showcase "Preis- und Aktionsagent mit Freigabe" - booth experience, UX and hardware

Track report: trade-show booth experience, UX and hardware (web research + expert reasoning).
Written 2026-11-10. Read-only research: nothing in the repo, cluster, broker, databases or SAM
config was changed.

Legend: **[V]** = VERIFIED (source given: file:line, URL or command), **[A]** = ASSUMPTION or
expert judgement (to be confirmed). Prices are rough street prices in EUR (incl. VAT unless
stated) from web listings found today. They are snapshots, not quotes.

---

## 0. Executive summary (the 12 things that matter most)

1. **The hero moment is physical and takes about 30 s.** The visitor scans a real product.
   The agent proposes a markdown. The visitor, handed the tablet as "Marktleitung", taps
   *Freigeben*. The e-paper shelf label flips and the next scan of the same product rings up the
   new price. Everything else on the booth supports this one sequence.
2. **A guided interaction lasts about 3 minutes** (an express version takes 60-90 s). One POS
   station handles at most about 17 guided visitors per hour; at a realistic 40-60 % load that
   is 7-10 per hour, roughly 170-240 over three fair days, plus 2-4 onlookers each [A].
3. **Hide the LLM latency behind the visitor's own actions.** Deterministic signals (sales
   rate, stock, best-before date, active promotions) appear in under 1.5 s. The AI proposal follows
   8-12 s after the hero scan, while the visitor scans the next items. The measured basis: fast-tier
   agent nodes take 5-11 s and tool nodes under 1.5 s on this lab
   [V: bsg-trading-desk-demo/README.md "Measured on the cluster"]. The voucher at checkout must be
   **precomputed during the basket**, so it appears in under 3 s after `PurchaseTransactionClosed`.
4. **SAM's built-in human-in-the-loop cannot be the approval channel.** `ask_user_question` is for
   interactive agents only. It must not be attached to workflow agents, and it returns an error on
   an Event Mesh entrypoint [V: samdocs/reference__built-in-tools.md:171]. `notify_user` is
   fire-and-forget to a web inbox, webhook, Slack or Teams [V: same file:836-847]. So the approval
   tablet is our own one-tap web app that publishes a decision event. The SAM inbox notification
   can be shown as an extra channel.
5. **Messe Duesseldorf forbids your own Wi-Fi access points unless approved.** The exhibitor hotspot
   offers 10 Mbit/s, and devices must support 5 GHz
   [V: <https://www.boot.com/en/Exhibit/WiFi_regulations>, a Messe Duesseldorf fair]. So:
   **wire everything** (USB scanners, Ethernet on all screens, an ESP32 board with Ethernet for the
   label), order a wired Telekom line, and use a 5G router as WAN failover.
6. **ESL: DIY black/white e-paper over MQTT for the hero moment, mirrored on the monitor.** It
   refreshes in 0.4 s partial or about 5 s full
   [V: <https://www.waveshare.com/4.2inch-e-paper.htm>]. A vendor ESL can be added if GEBIT has a
   partner integration and it passes a latency test of under 10 s. OpenEPaperLink tags check in
   every 40 s and typically lag 40-60 s, and its licence is CC BY-NC-SA
   [V: <https://github.com/jjwbruijn/OpenEPaperLink/wiki/Tag-protocol-timing>]. That rules it out.
   Colour e-paper (red) needs 12-20 s per refresh. Avoid it for the hero label.
7. **"AI proposes, rules check, human decides" must be visible on every screen.** Facts from data
   (tool nodes) are shown separately from the AI's judgement. Compliance checks are deterministic
   tick boxes: minimum margin, the 30-day lowest price under PAngV §11
   [V: <https://lxgesetze.de/pangv/11>], no fixed-price goods, no promotion collision. *Anpassen*
   recomputes impact and checks live, and an adjustment that breaks a rule disables *Freigeben*.
8. **Show GEBIT's own semantics.** Line events are drawn as provisional (dashed) until
   `PurchaseTransactionClosed` arrives, then turn solid ("Verkauf final"); a
   `PurchaseTransactionCancelled` greys them out. This is exactly the point the GEBIT developer
   stressed. The voucher maps to GEBIT's native `CheckoutCoupon` with `print_content`
   [V: receipt .../loyalty_datatype.proto:188-255]. The approval maps to the receipt's `Approval`
   record (`approver_id`, `approved_command`, `approved_at`) [V: receipt_datatype.proto:125-126,
   254-264].
9. **UI tech: reuse the proven pattern.** That is one FastAPI + SSE "booth-ui" service with static
   HTML/CSS/vanilla JS views (`/monitor`, `/freigabe`, `/kasse`, `/kunde`, `/etikett`, `/op`) in
   kiosk browsers [V: bsg-trading-desk-demo/app/bsgdemo/ui/server.py:1-20]. Use a 4-6x larger type
   scale than the BSG presenter page, which uses 15-26 px for a laptop at 1 m
   [V: .../ui/static/index.html:14-87]. Only the ESP32 label talks MQTT to the broker directly.
10. **Readability:** on a 65" monitor at 5 m, any text meant for passers-by needs about 78 CSS px or
    more in a 1920x1080 viewport. Prices and KPIs need 200-260 px (rule of thumb 1 inch of letter
    height per 10 ft, computed in section 4.6). A 65" panel beats a 55" one for this layout.
11. **Reliability ladder:** L0 live; L1 "Regel-Modus" (rule-based proposals, labelled) when the LLM
    is slow, unreachable or out of budget; L2 replay of recorded agent outputs on real scans
    (labelled); L3 an attract-loop video. Add a reset barcode card, an auto-reset after each receipt,
    and promotions that end after 2 minutes ("Messe-Zeitraffer"), so the next visitor sees the base
    price again. The lab Mac must never sleep or change networks, because of known Rancher Desktop
    wedges [V: memory notes, section 7.3].
12. **Cost:** at about 2 fast-tier agent calls per guided visit, a 3-day fair costs roughly
    USD 10-25 in LLM tokens [A, using Haiku 4.5 at $1/$5 per MTok (V: claude-api skill model
    table, cached 2026-11-03)]. Running an LLM on every one of the about 11 events per sale would
    multiply that by about 5 and break the 50 USD LiteLLM cap. Trigger the workflow per event, but
    let a switch or tool node drop irrelevant events before any agent runs.

---

## 1. Facts that shape the booth

### 1.1 Fair and venue

- **EuroCIS 2027: 16-18 February 2027, Messe Duesseldorf** [A: aggregators
  <https://tradefest.io/en/event/eurocis>, <https://www.messen.de/de/7614/duesseldorf/eurocis/info>;
  confirm on the official site]. Trade visitors only (B2B). Projected about 13,500 attendees and
  475 exhibitors (tradefest projection) [A]. EuroCIS 2026 ran as part of EuroShop, 22-26 Feb 2026
  [V: <https://www.technologyrecord.com/article/eurocis-2026-showcasing-innovations-that-address-real-challenges-in-retail>].
  That is about 14 weeks from today.
- **The audience is retail IT, store operations and pricing people from retailers, plus integrators
  and competitors [A].** They know POS, ESL and promotions very well, and many ESL vendors exhibit
  at EuroCIS (SoluM showed Newton labels in hall 10 in 2024
  [V: <https://www.solum-group.com/solum/press-release-detail.newton-labels-take-center-stage-at-eurocis-2024>]).
  The differentiator is therefore **not** the ESL. It is the event-driven loop: POS event, then
  agent, then human approval, then price live at the till and on the shelf.
- **Wi-Fi rules (Messe Duesseldorf):** "You are not permitted to set up your own access points".
  The exhibitor business hotspot runs at 10 Mbit/s up and down. Devices must support 5 GHz. The
  standard package covers 10 simultaneous users, upgradeable to 25, 50 or 100
  [V: <https://www.boot.com/en/Exhibit/WiFi_regulations>]. Older order forms show a fee for having
  your own AP approved (EUR 129 + VAT if approved, EUR 49 + VAT if not)
  [V, dated 2017: <https://www.oos.rehacare.de/2017/en/FORM_WLAN>]. A Telekom order form lists a
  symmetric wired line of up to 50 Mbit/s with a 4-port router and a flat rate
  [V, dated 2022: <https://www.eurogin.com/content/dam/Informa/eurogin/2022/pdf/order-forms/B33_Telecom_Wired%20Internet%20access%20options.pdf>].
  Current products and prices are in the fair's Online Order System (OOS), and GEBIT orders as the
  exhibitor [A].
- **Power:** Messe Duesseldorf sells a "cannot be switched off, 24-hour operation" socket as a
  separate product, and orders placed less than 21 days before set-up carried a 35 % surcharge
  [V, dated 2018: <https://oos.eurocis.com/2018/en/BE2200>, <https://oos.drupa.de/en/BE2240F>].
  Plan for booth power to go off at night, so cold-start every morning, or order 24 h power for
  the lab host [A].
- **Lead capture service:** Messe Duesseldorf sold Scan2Lead (badge scanning app, station or
  handheld) through the OOS [V, dated 2018-2019: <https://oos.eurocis.com/2019/en/BE9801>]. Check
  the 2027 offering [A].

### 1.2 Lab and platform facts that constrain UX

- Lab pods running today: `agent-mesh-postgresql-0`, `-seaweedfs-0`, `-awe-`, `-gwe-`, `-str-`,
  all `Running`, age 7d3h [V: `kubectl get pods -n sam-solace-lab`, 2026-11-10].
- Measured on BSG (SAM 2.493.0): desk-assistant reply in 7.4 s; alert to desk note in 14.2 s
  (issuer-specific branch) or 20.3 s (market-wide branch); `enrich` tool node 0.3-1.4 s; analyst
  8.7 s; market context 5.3 s (parallel); communicator 11.1 s; publish < 1 s; about 60k / 92k
  tokens per run [V: bsg-trading-desk-demo/README.md "Measured on the cluster (2026-11-04)"].
- Agent-node progress cannot be shown live over MQTT. SAM's own A2A status events live on VPN
  `sam`, which has no MQTT listener, so BSG shows the agent rows as *inferred*
  [V: bsg-trading-desk-demo/README.md "Decisions" and RUNBOOK.md step 3]. MQTT 1883 serves only
  the `default` VPN [V: memory project_event_mesh.md]. UX consequence: progress steps for tool
  nodes are real, while the agent step shows an elapsed timer ("KI formuliert Vorschlag ... 6 s").
  A backend subscriber over SMF/WebSocket to VPN `sam` could make it real [A, not done in BSG].
- Non-ASCII text in agent output arrived mangled at a solclientjs consumer
  [V: memory project_sam_v2_workflow_events.md "Non-ASCII ..."]. The retail shop page works around
  it with explicit UTF-8 decoding [V: sam-retail-ops-demo/shop/index.html:190-197]. UX consequence:
  agents return **structured fields** (numbers, codes, one short ASCII rationale), and the UI
  renders the German text with umlauts and "6,99 €" from its own templates.
- Only one demo overlay may run on the platform at a time (install.sh refuses otherwise)
  [V: sam-retail-ops-demo/README.md "Install / remove"]. Freeze the lab for the fair.
- SAM HITL: `ask_user_question` is for interactive agents only, not for workflow agents, and it
  errors on an Event Mesh entrypoint [V: samdocs/reference__built-in-tools.md:159-171].
  `notify_user` sends a fire-and-forget notification to web inbox, webhook, Slack or Teams and
  needs `notify:_:send`; posting to another user's inbox needs `notify:_:send_others`
  [V: reference__built-in-tools.md:836-847, reference__rbac-reference.md:62-63]. Whether the
  notification service is deployed in this lab is not verified [A].

### 1.3 GEBIT data points the UI can use

- Sample sale article: `"description": "GEBIT Ente"`, `"articleNumber": "article004"`, total
  8.67 EUR (`intVal 867, scale 2`), 19 % VAT [V: gebit/events/events_simpleSale/03_PositionAdded.json].
  A **rubber duck as the hero product** (and giveaway) fits [A].
- Timing of the integration-test sale: all 11 events within about 1.23 s. The six payment and
  closing events (06-11) fall within **0.15 ms** of each other (eventTimestamp 1793636729.297603086
  to .297757555) [V: python3 -I over the 11 JSON files]. UX consequence: the monitor must queue
  bursts visually (about 250 ms cadence) while showing the true timestamps.
- Events relevant to the stream: `PositionAdded`, `ArticlePositionItemCountChanged`,
  `ArticlePositionVoided`, `ArticlePositionPriceOverridden`, `ArticlePositionPromotionApplied`,
  `PercentageArticlePositionDiscountApplied`, `PurchaseTransactionCancelled`,
  `PurchaseTransactionClosed` and others
  [V: purchase/.../v2/event/purchase_transaction_event.proto, `grep ^message`]. Loyalty:
  `ApplyAnonymousCoupon`, `AssignLoyaltyMembership`, `AssignLoyaltyCoupon` commands;
  `AnonymousCouponApplied`, `LoyaltyMembershipAssigned` events [V: loyalty_command.proto,
  loyalty_event.proto].
- Final receipt (`simpleSale.json`) has `receiptNumber`, `total.value "8.67"`,
  `fiscalTransaction.attributes.DE_QRCode` (TSE data), `loyalty.loyaltyPurchaseResult.checkoutCoupons`
  and `approvals` [V: python3 -I structure dump of simpleSale.json]. `CheckoutCoupon` = {application,
  coupon_id, print_content} with the comment "Checkout coupons generated for the purchase made"
  [V: receipt/.../loyalty_datatype.proto:190-191, 245-255]. `Approval` = {approver_id,
  approved_command, approved_at} [V: receipt_datatype.proto:254-264].

---

## 2. Best practices for interactive tech demos at fairs (applied to this use case)

| Topic | Best practice | Our application |
|---|---|---|
| **First 3-5 s** | Passers-by give a booth about 3 s, and graphics must be taken in during the time it takes to walk about 10 ft [V: Exhibitor magazine via <https://exhibitoronline.com/topics/article.asp?ID=1449>]. Keep it to 10 words or fewer [V: <https://www.alta-graphics.com/alta-blog/tips-to-make-your-trade-show-booth-graphics-get-noticed/>]. | Monitor headline of 7 words or fewer: **"KI schlägt Preise vor. Sie entscheiden."** Motion in the corner of the eye (event dots flowing), plus a physical cue: a shelf with real products and a counter sign **"Scannen Sie ein Produkt"**. |
| **Attract loop** | Something must happen all the time; a small crowd attracts a bigger crowd [V: <https://www.pavegen.com/blog/10-things-your-trade-show-booth-is-missing>]. | After 60 s idle the monitor plays a **replay of the last real decision** (labelled "Rückblick 14:32") and shows live counters ("Heute 143 Scans an diesem Stand"). The customer display shows "Willkommen - scannen Sie ein Produkt aus dem Regal". No sound. |
| **Dwell time** | Hands-on interaction, timed demos, seating or coffee, and staff who start real conversations raise dwell time [V: <https://skyline.com/blog/improve-dwell-time-in-your-trade-show-booth>]. Vendor dwell-time numbers are unverified. | The visitor does the scanning and the approving. A coffee voucher (redeemable at the GEBIT bar) extends dwell into a sales conversation. Scheduled shows ("Live-Demo zur vollen und halben Stunde"). |
| **2-4 min guided interaction** | One clear arc: hook, action, surprise, proof, take-away. | The 3-minute choreography in section 3, plus a 60-90 s express version for crowds. |
| **One hero moment** | One unforgettable, physical, explainable moment. | Tap *Freigeben* → **the shelf label flips** → re-scan → new price at the till. The ESL is mirrored big on the monitor for people at the back. |
| **Readable from 3-5 m** | About 1 inch of letter height per 10 ft [V: <https://www.signs.com/blog/?p=16381>]. | Type scale in section 4.6: at least 78 px on 65" for anything a passer-by should read; prices and KPIs 200-260 px. |
| **Noise** | Hall noise drowns out audio [A]. | Visual feedback only: screen pulses, check marks, the label flip, the scanner's own beep. The host uses a headset mic only for scheduled shows, if the booth has PA [A]. |
| **Staff roles** | Separate attracting, demoing and qualifying roles [A, common practice]. | Host/presenter, approver (staff or visitor), backstage operator, greeter at peak. See 3.2. |
| **Visitor participation** | Let them touch it. | The visitor picks products from the shelf and scans them on a **hands-free presentation scanner**. The visitor plays *Marktleitung* on the tablet. The visitor takes the voucher home on their phone. |
| **Throughput** | Plan capacity, not just experience. | One station: 3:00 interaction + 0:30 handover → at most about 17 per hour; realistic 7-10 per hour; show mode at peak (1 scanner, 1 approver, 4-8 watchers). |
| **Lead capture** | Ask for contact details mid- or post-demo, not up front [V: <https://demoboost.com/interactive-demo-playbook/conferences-shows-demo>]. | QR voucher on the customer display and receipt → phone landing page with an opt-in form; badge scan with the Messe lead app at the wrap step; voucher redemption brings them to the sales lounge. |
| **Crowds** | Switch from 1:1 to 1:n; use the screen as narrator. | Show mode: the host scans, one volunteer approves, the monitor tells the story in numbered steps (1 Scan, 2 KI-Vorschlag, 3 Freigabe, 4 Preis aktiv). A deep-dive corner (laptop with SAM Activities and Grafana) pulls techies out of the queue. |
| **Reset between visitors** | Zero-touch reset, under 30 s. | Auto-reset 25 s after the voucher is shown. The approved promotion runs 2 minutes ("Messe-Zeitraffer"), then the label flips back with "Aktion beendet". A RESET barcode card gives an instant reset; a nightly script reseeds. |

---

## 3. Booth choreography

### 3.1 Layout (demo zone of about 3 m x 3 m inside the GEBIT booth) [A: booth size unknown]

```text
                         back wall (booth graphic: "KI schlägt vor. Sie entscheiden.")
 +------------------------------------------------------------------------------+
 |   [ 65" monitor, landscape, bottom edge ~1.3 m, centre ~1.75 m ]             |
 |                                                                              |
 |   [ Deep-dive corner ]                       [ Shelf: 3 levels, 6-8 products ]|
 |   laptop: SAM Activities,                    hero product at eye level        |
 |   Grafana, operator view /op                 (1.4-1.6 m) with e-paper ESL     |
 |                                              + 7.5" e-paper promo topper      |
 |        [ POS counter, 90-95 cm high, parallel to the aisle ]                 |
 |        host side: cashier touch screen 15.6", receipt printer                |
 |        visitor side: customer display 10-13", hands-free scanner,            |
 |        approval tablet on a stand at the counter end (handed over)           |
 +------------------------------------------------------------------------------+
                                  aisle (visitors approach here)
```

- The monitor hangs high, so heads at the counter do not block it. It faces the aisle. Its bottom
  edge at about 1.3 m is a judgement call [A].
- The shelf stands at the aisle edge: products you can pick up invite a stop.
- The host stands behind the counter facing the visitor. The visitor stands on the aisle side and
  sees the customer display, scanner, tablet and shelf, and turns only the head to see the monitor.

### 3.2 Roles

- **Host/presenter (Gastgeber/in, GEBIT or Solace):** stops people, guides the scan, narrates
  three sentences, hands over the tablet, closes with the voucher and a qualifying question.
- **Approver (Marktleitung):** by default **the visitor** ("Möchten Sie heute Marktleitung sein?").
  A second staff member takes it in show mode or when the visitor declines.
- **Operator (backstage, part-time):** watches `/op` (device health, LLM latency, budget, mode
  L0-L3), resets, switches modes, answers deep technical questions in the deep-dive corner.
- **Greeter/lead catcher (peak hours only):** at the aisle, scans badges, manages the queue,
  invites people to the next show.

Host script, three sentences in German [A]:

1. "Jeder Scan an der Kasse ist ein Ereignis - hier sehen Sie es live."
2. "Die KI erkennt, dass die Ente sich schlecht verkauft, und schlägt eine Aktion vor."
3. "Aber entscheiden tun Sie - mit einem Tipp. Erst dann ändert sich der Preis an Kasse und Regal."

### 3.3 Step-by-step choreography (happy path, target seconds)

Times are from the first contact. The latency targets come from section 7.4.

| # | t (s) | What happens | Who | Screens |
|---|---|---|---|---|
| 0 | idle | Attract mode: replay of the last decision, day counters, "Scannen Sie ein Produkt". The ESL shows the base price. | - | Monitor attract; customer display welcome; ESL base price |
| 1 | 0-10 | Hook: the host invites; the visitor picks 2-3 products from the shelf, including the hero (GEBIT Ente or a best-before item). | Host, visitor | - |
| 2 | 10-15 | First scan: beep. The line appears on the cashier screen and customer display in **under 0.3 s**. On the monitor a dot runs Kasse → Event Mesh, and "Bon geöffnet" plus "Artikel gescannt: Kaffee 4,99 €" appear (dashed = provisional). | Visitor | Kasse, Kunde, Monitor |
| 3 | 15-30 | Hero scan. Within **1.5 s** the monitor shows a deterministic signal card: "Ladenhüter erkannt: 3 verkauft heute, Plan 20 · Bestand 48 · Reichweite 31 Tage". The agent timeline starts: "Absatz geprüft ✓ · Bestand ✓ · Aktionen ✓ · KI formuliert Vorschlag … 3 s". | Visitor | Monitor |
| 4 | 30-45 | The visitor scans the remaining items (this masks the agent time). The proposal arrives **8-12 s after the hero scan** (fallback after 15 s, section 7.5). The monitor shows the big proposal card; the tablet lights up with "Neuer Vorschlag". | Visitor | Monitor, Tablet |
| 5 | 45-65 | Decision: the host hands over the tablet ("Sie sind die Marktleitung"). The visitor reads 3 reasons, the impact and 4 green checks, may try *Anpassen* (e.g. −30 % turns the margin check red and blocks the button), then taps **Freigeben**. | Visitor (approver) | Tablet |
| 6 | 65-75 | **Hero moment:** the monitor shows "Freigegeben von Marktleitung 14:32:05" → "Artikelstamm aktualisiert" → "Etikett aktualisiert". The shelf ESL flips (1-5 s) and the promo topper shows "AKTION −20 %". The host points to the shelf. | Host | Monitor, ESL |
| 7 | 75-90 | Proof: the visitor scans the hero again. The POS rings up **6,99 €** with an "Aktion" badge; the customer display shows "Sie sparen 1,68 €" and "Niedrigster Preis der letzten 30 Tage: 8,67 €". | Visitor | Kasse, Kunde |
| 8 | 90-105 | Pay: the host taps "Bar bezahlen (Demo)". The payment burst is shown at a 250 ms cadence; on `PurchaseTransactionClosed` all lines turn solid: "Verkauf final - Bon 0026". A fan-out animation shows one event reaching 4 consumers: E-Journal, Warenwirtschaft, DWH, KI-Gutschein. | Host | Monitor, Kasse |
| 9 | 105-120 | Voucher (precomputed, shown **under 3 s** after Closed): QR on the customer display and the printed receipt: "Ihr Gutschein für den nächsten Besuch: Espresso an der GEBIT-Bar". The visitor scans it with a phone; the landing page opens. | Visitor | Kunde, phone, printer |
| 10 | 120-180 | Wrap: the host shows the day KPIs ("Heute: 37 Vorschläge, 29 freigegeben, 5 angepasst, 3 abgelehnt"), asks a qualifying question ("Wie laufen Preisänderungen bei Ihnen heute?"), badge scan, handover to sales or the deep-dive corner. Auto-reset 25 s later; the promotion ends after 2 min and the ESL flips back. | Host, greeter | Monitor, ESL |

**Express version (60-90 s, crowds):** the operator pre-scans a basket via a control barcode
("SZENARIO 1"). The host does one live hero scan, the proposal appears, a volunteer approves, the
label flips. Payment and voucher are skipped, or a QR is shown to the whole group.

### 3.4 Scenario variants (rotate to keep repeat visitors and staff fresh)

Pick two primary scenarios for the booth and keep the rest in reserve [A]:

1. **Ladenhüter → Aktion (primary):** the GEBIT Ente sells far below plan with high stock, so the
   proposal is −20 % for the rest of the day. Non-food, so it survives three fair days.
2. **MHD/Abschrift → Markdown (primary):** a dummy pack of yoghurt or salad whose best-before date
   is tomorrow, with 30 units at risk of write-off, so the proposal is −30 % from now. This is the
   most convincing story for grocery retailers. The best-before data is simulated, the pack is a
   dummy.
3. **Warenkorb-Aktion live (reserve):** pasta and tomato sauce in the basket lead to "Parmesan
   −30 % jetzt an der Kasse". This is the live single-article promotion of the owner's idea and
   maps to `ArticlePositionPromotionApplied` [V: event exists] [A: whether the agent may apply it].
4. **Kundenkarte → Gutschein (reserve / add-on):** the visitor scans a fictitious persona card
   ("Familie Müller", "Student Ben"), which maps to `AssignLoyaltyMembership`. The voucher depends
   on the persona. Never use real personal data.
5. **Leitplanke greift (reserve, Q&A):** a fixed-price item (book, Buchpreisbindung). The rule
   check blocks the markdown; the AI may only propose a cross-sell. This shows that the system is
   safe by design.

**Control barcodes** (laminated cards for the host): `RESET`, `SZENARIO 1/2/3`, `MODUS LIVE`,
`MODUS REGEL`, `MODUS REPLAY`, `EXPRESS`. The scanner is already in the host's hand, so no extra UI
is needed. Prefix them (e.g. `##CTL:RESET`) so they never reach the POS as an article [A].

### 3.5 Making booth scans and "slow seller" logic compatible

If every visitor scans the GEBIT Ente, it becomes a bestseller and the story collapses. Therefore
[A]:

- The **sales baseline comes from a simulated store** ("Filiale Düsseldorf-Messe", 4 weeks of
  seeded history and a plan per article). Booth scans add to "heute" but are weighed against the
  plan.
- The **trigger is multi-factor**: sales rate vs plan, stock coverage, best-before, no active
  promotion. It stays true for the hero items all day.
- Promotions end after 2 minutes (Zeitraffer) and the agent is allowed to propose again; the
  monitor counts "Vorschläge heute".

---

## 4. Screen specifications

General rules for all screens [A]: German, "Sie"-form, short verbs ("Erkannt", "Vorgeschlagen",
"Freigegeben", "Aktiv"). German number format "6,99 €". Tabular numerals. Never colour alone:
always icon plus label. Colour code: Scan = blue, Zahlung = green, KI = violet, Mensch/Freigabe =
orange, Regel/Prüfung = teal, Fehler = red. Self-hosted fonts and icons (no CDN at runtime). An
English toggle via the operator view for international visitors.

### 4.1 (a) Booth monitor, 65" landscape, `/monitor`

Purpose: tell the story to someone 5 m away who never touches anything.

Layout (1920x1080 CSS px):

- **Top band (≈ 14 %):** headline "KI schlägt Preise vor. Sie entscheiden." (96-110 px). On the
  right, 4 KPI tiles: "Scans heute 143", "KI-Vorschläge 37", "Freigegeben 29", "Ø Scan →
  Vorschlag 11 s" (numbers 120 px, labels 40 px).
- **Left column (≈ 35 %): "Live an der Kasse".** A receipt-like list, newest on top, 4-6 lines in
  48-56 px: "Artikel gescannt · GEBIT Ente · 8,67 €". Provisional lines are dashed and grey; on
  `PurchaseTransactionClosed` the block turns solid with "✓ Verkauf final". On
  `PurchaseTransactionCancelled` it is struck through: "Bon abgebrochen - nichts verkauft".
- **Centre/right (≈ 65 %): "Was die KI gerade tut".**
  - A **metro-line diagram** (always visible, 6 stations): Kasse → Event Mesh → KI-Agent →
    Marktleitung → Artikelstamm → Regal & Kasse. Every event is a dot that travels along the line
    (600-800 ms); the active station glows. At `PurchaseTransactionClosed` the line fans out to
    E-Journal / Warenwirtschaft / DWH / KI-Gutschein: "Ein Ereignis, viele Abnehmer - ohne
    Punkt-zu-Punkt-Schnittstellen".
  - A **step timeline** under the active proposal: "1 Absatz geprüft ✓ 0,4 s · 2 Bestand ✓ ·
    3 Aktionen ✓ · 4 KI-Vorschlag … 6 s · 5 Prüfregeln ✓ · 6 Wartet auf Freigabe".
  - A **proposal card** (big): "Vorschlag: GEBIT Ente −20 % → 6,99 €" (price 200-240 px); 3 reasons
    in 56 px; impact line "+12 Stück erwartet · Marge 31 % → 18 %"; status chip "Wartet auf
    Freigabe" → "Freigegeben ✓ 14:32 Marktleitung" → "Preis aktiv".
  - An **ESL mirror tile:** a pixel-true rendering of the shelf label that flips at the same time
    as the real one.
- **Bottom ticker (32 px, for techies at 1-2 m):**
  `gebit/pos/v2/purchase/PositionAdded · Workflow-Lauf 3f2a · 4 Knoten · 11,2 s · 18k Tokens · Haiku 4.5`.

Idle/attract (after 60 s without a scan): alternate every 8 s between (1) a big CTA "Scannen Sie
ein Produkt aus dem Regal →" with an arrow to the shelf, (2) a replay of the last decision
(labelled "Rückblick") and (3) the day KPIs.

### 4.2 (b) Approval tablet, 11" landscape, `/freigabe`

Purpose: a credible store-manager decision in 10-20 s, one tap.

- **Header:** "Marktleitung · Freigaben (1 offen)".
- **Card:**
  - Product photo, name, article number; **current price 8,67 € → proposal 6,99 € (−20 %)**;
    validity "heute bis 20:00", shown on the fair as "2 Min (Messe-Zeitraffer)".
  - **Warum** (3 bullets, each with a data-source icon): "Abverkauf heute 3 statt Plan 20
    (Kasse)", "Bestand 48, Reichweite 31 Tage (Bestand)", "Keine laufende Aktion (Aktionen)".
  - **KI-Einschätzung** (separated, violet label): one sentence of 140 characters or fewer, e.g.
    "Rabatt von 20 % bringt laut Abverkaufsmuster ähnlicher Artikel ca. +12 Stück heute."
  - **Wirkung:** expected units, revenue delta, margin after the markdown, write-off avoided (EUR).
  - **Prüfungen** (deterministic, teal, ✓/✗): "Mindestmarge 15 % ✓ (18 %)"; "30-Tage-Tiefstpreis
    8,67 € wird angezeigt ✓ (PAngV §11)"; "Keine Preisbindung ✓"; "Keine Aktionskollision ✓";
    "Max. Rabatt 30 % ✓".
  - **Sicherheit:** "hoch - 4 von 4 Signalen", in plain words, never a fake decimal [A].
- **Actions:**
  - **Freigeben** (full width, ≥ 72 px tall, green/orange).
  - **Anpassen** opens steps −10/−15/−20/−25/−30 % and a duration. Impact and checks are recomputed
    on the tablet without an LLM. A failing check disables *Freigeben* and says why.
  - **Ablehnen** opens reason chips: "Aktion läuft bereits", "Marge zu niedrig", "Ware kommt nach",
    "Sonstiges". The reason is logged and shown on the monitor.
- After tapping: "Freigegeben - wird jetzt an Kasse und Regal verteilt", plus **"Rückgängig"
  (60 s)**, which issues a revert event (no delay before the price applies).
- **Audit footer:** "Vorschlag A-0042 · KI: Preis-Agent (fast) · Daten: Kasse, Bestand, Aktionen
  · Freigabe: Marktleitung (approver_id) · 14:32:05", mirroring GEBIT's `Approval` record
  [V: receipt_datatype.proto:254-264].
- Touch targets of at least 48 px; no keyboard; kiosk; vibration or a screen flash on a new
  proposal (sound is unreliable in the hall).

### 4.3 (c) POS: cashier screen (host side) and customer display (visitor side)

**Cashier screen `/kasse` (15.6" touch, simulator until GEBIT's real POS client takes over):**

- Line items, quantities, totals, and buttons "Bar bezahlen (Demo)", "Menge", "Storno",
  "Bon abbrechen", "Kundenkarte".
- Each line carries a small event chip (`PositionAdded ✓`) so techies see the 1:1 mapping.
- A price-change banner: "Neuer Preis aktiv seit 14:32 (Freigabe Marktleitung)".
- The receipt print uses GEBIT's checkout-coupon print content [A: GEBIT POS printing].

**Customer display `/kunde` (10-13", facing the visitor):**

- The last scanned item, large (price 120-160 px), and the running total.
- On a promotion: "AKTION −20 %", the old price struck through, "Sie sparen 1,68 €", and in a clear,
  legible size "Niedrigster Preis der letzten 30 Tage: 8,67 €". The BGH held that a small-print
  reference price is not enough [V: BGH I ZR 183/24 summary via
  <https://www.otto-schmidt.de/news/wirtschaftsrecht/werbung-mit-preisermassigung-niedrigster-gesamtpreis-der-letzten-30-tage-muss-unmissverstandlich-und-klar-erkennbar-sein-2025-10-09.html>].
- At the end: "Danke! Ihr Gutschein für den nächsten Besuch" with a **QR of at least 4 cm** (high
  contrast, quiet zone) and a short URL.
- Swap: in the GEBIT lab the cashier screen becomes the real GEBIT POS. The customer display stays
  ours unless GEBIT provides one [A].

### 4.4 (d) ESL or simulated shelf label

- **Shelf-edge ESL (4.2" black/white e-paper, 400x300):** product name; price at 40 % or more of
  the label height; unit price (Grundpreis, e.g. "1 Stück" or "100 g = 1,40 €", which PAngV
  requires) [A: content per article]; an inverse "AKTION" banner; "30-Tage-Tiefstpreis 8,67 €" in
  small type; article number and EAN barcode.
- **Promo topper (optional, 7.5" e-paper, 800x480, 2-5 s refresh):** appears on approval with
  "AKTION −20 % · nur heute". A 4.2" label is readable at 1-2 m at most; the topper and the monitor
  mirror carry the moment to the aisle [A].
- **Mirror tile on the monitor** is the always-working fallback and the view for the back row.
- **Simulated label `/etikett`:** the same rendering on a small LCD or old phone in a shelf-edge
  housing. Use it if the e-paper fails; label it "ESL-Simulation" [A].

### 4.5 (e) Visitor phone landing page (public, mobile-first)

- **Must be on the public internet.** Visitors are on mobile data and cannot reach
  `*.solace.lab` [A]. Use a static page (e.g. a GEBIT or Solace web space, or a static host).
- **No backend needed:** the voucher payload sits in the URL **fragment** (`#v=...`, never sent to
  a server): voucher id, value, validity, a 3-step "Ihr Weg durch das Event Mesh" timeline (number
  of events, time to proposal, who approved), with an HMAC signature so the booth can validate on
  redemption [A]. **No personal data in the URL.**
- **Content:** voucher card ("Espresso an der GEBIT-Bar · gültig bis 18.02.2027 · Code
  GBT-7K3Q"); a redeem QR/barcode; "So ist dieser Gutschein entstanden" (scan, KI-Vorschlag,
  Freigabe, Bon final, Gutschein); CTA "Unterlagen anfordern" (opt-in form with consent text) and
  "Termin vereinbaren". No tracking cookies.
- **Redemption closes the loop:** scanning the voucher at the POS fires `ApplyAnonymousCoupon` /
  `AnonymousCouponApplied` [V: those messages exist in loyalty_command/loyalty_event.proto], and
  the monitor shows "Gutschein eingelöst - Kunde kam wieder" ("next visit" in fair time) [A].
- Optional Apple/Google Wallet pass: nice, but it needs signing certificates and issuer accounts,
  so it is out of scope for v1 [A].

### 4.6 Type scale for the booth monitor (computed)

Rule used: about 1 inch of letter height per 10 ft of viewing distance (25.4 mm per 3.05 m)
[V: <https://www.signs.com/blog/?p=16381>; sources vary, this is a moderate one]. Cap height is
taken as about 0.72 em (Inter or a similar sans) [A]. CSS px refer to a 1920x1080 viewport. Panel
heights: 55" = 68.5 cm, 65" = 80.9 cm, 75" = 93.4 cm (16:9 geometry). Computed with python3:

| Panel | mm per CSS px | font-size for 3 m | for 4 m | for 5 m |
|---|---|---|---|---|
| 55" | 0.634 | 56 px | 74 px | 93 px |
| 65" | 0.749 | 47 px | 63 px | 78 px |
| 75" | 0.865 | 41 px | 54 px | 68 px |

Recommended scale on a 65" panel:

- 220-260 px for price and proposal numbers.
- 120 px for KPI numbers.
- 96-110 px for the headline.
- At least 80 px for passer-by text.
- 48-56 px for stream lines (3-3.5 m).
- 32 px for the tech ticker (2 m or less).
- At most 7 words per headline and at most 3 content zones.

---

## 5. Design principles: "AI proposes, human decides", explainability, the event mesh

### 5.1 Principles (anchored in Microsoft's Guidelines for Human-AI Interaction)

Microsoft's 18 guidelines cover four phases: initially, during interaction, when wrong, over time
[V: <https://www.microsoft.com/en-us/research/blog/guidelines-for-human-ai-interaction/>; G1, G15,
G17 and G18 confirmed in search results, the remaining titles are from the CHI 2019 paper by
Amershi et al., quoted from memory [A]].

1. **Nothing reaches the shelf without a visible human tap.** The monitor says it in plain words:
   "Ohne Freigabe kein neuer Preis." Optionally show an autonomy dial: Hinweis / Vorschlag mit
   Freigabe (default) / automatisch innerhalb Leitplanken. This is the governance talking point
   (G17 global controls).
2. **Separate facts from judgement.** Data facts carry data-source icons (Kasse, Bestand,
   Aktionen, Kundenkarte) and come from tool nodes. The AI's judgement is one sentence with a violet
   "KI-Einschätzung" label (G11, make clear why the system did what it did).
3. **Rules are rules, not AI.** Compliance and guardrails are deterministic checklists: minimum
   margin, maximum discount, fixed-price goods, promotion collision, PAngV §11. Under §11, an
   announced price reduction must state the lowest total price of the previous 30 days; individual
   (personalised, non-public) reductions fall under §9 instead
   [V: <https://www.it-recht-kanzlei.de/faq-werbung-preisermaessigungen-gesamtpreis-preisangabenverordnung.html>].
   Legal wording must be reviewed by GEBIT or legal [A].
4. **Impact in EUR and units**, not in model scores (G2: show how well the system can do what it
   does, here as "Sicherheit: hoch - 4 von 4 Signalen").
5. **Adjust, not just yes/no** (G9 efficient correction). The *Anpassen* stepper recomputes impact
   and checks on the spot, and a broken rule blocks the button. Visitors love trying to break it.
6. **Reversible and time-boxed:** "Rückgängig" for 60 s; every promotion has an end. On the booth
   it ends after 2 minutes ("Messe-Zeitraffer").
7. **Who decided, when, on what basis:** an audit line on the tablet, the monitor and in SAM
   Activities, mirroring GEBIT's `Approval` record.
8. **Rejections are visible too.** The day KPIs show "abgelehnt 3" with reasons. A system that is
   never rejected is not believable. Do not claim "die KI lernt daraus" unless feedback is really
   stored and used [A].
9. **Personalisation goes into vouchers, not shelf prices.** Shelf price changes apply to everybody.
   Shopper-specific benefits are coupons (GEBIT `CheckoutCoupon`). The Omnibus directive added a
   disclosure duty for prices personalised by automated decision-making (CRD Art. 6(1)(ea)), so keep
   personalised *prices* out of the demo [V, secondary sources:
   <https://7learnings.com/blog/what-retailers-need-to-know-about-the-new-eu-consumer-protection-directive/>;
   verify the EUR-Lex text].
10. **Honest when degraded:** in Regel-Modus or replay the operator view and a small monitor badge
    say so (G18, notify about changes). If a visitor asks, the host explains [A].
11. **Short AI prose, no anthropomorphism theatre:** "KI analysiert", not "die KI denkt nach und
    fühlt...". At most one sentence on the big screen.

### 5.2 Making the event-driven flow simple

- **Metro-line metaphor** with 6 stations (section 4.1): one direction, one dot per event, stations
  light up. A non-technical visitor understands "it travels from the till to the AI to me to the
  shelf".
- **Event bursts are de-bunched visually** (250 ms cadence) while the true timestamps stay visible.
  GEBIT's payment and closing events arrive within 0.15 ms [V: section 1.3].
- **Provisional vs final** (GEBIT semantics): dashed lines until `PurchaseTransactionClosed`, then
  solid; struck through on `PurchaseTransactionCancelled`.
- **Fan-out at the receipt:** one closed-receipt event goes to 4 consumers (E-Journal,
  Warenwirtschaft, DWH, KI-Gutschein). This mirrors what the GEBIT developer said the receipt is
  used for and is the Solace pitch in one picture.
- **Triage lane** (shows that the owner's per-event idea is cheap and governed): "11 Ereignisse →
  11 Bewertungen → 2 KI-Läufe". Every event starts a workflow; most end in a switch or tool node
  within a second, and only relevant ones wake an agent [A: architecture track to confirm SAM
  per-event overhead].
- **German labels for GEBIT events** (the original name stays in the tech ticker):

| GEBIT event | Monitor label (DE) |
|---|---|
| `PurchaseTransactionCreated` / `Opened` | Bon geöffnet |
| `PositionAdded` | Artikel gescannt: {Name} · {Preis} |
| `ArticlePositionItemCountChanged` | Menge geändert: {n} × {Name} |
| `ArticlePositionVoided` | Artikel storniert: {Name} |
| `ArticlePositionPriceOverridden` | Preis manuell geändert |
| `ArticlePositionPromotionApplied` | Aktion angewendet: {Name} −{x} % |
| `PercentageArticlePositionDiscountApplied` | Rabatt {x} % auf {Name} |
| `PaymentProcessStarted` | Zahlung gestartet |
| `CashPaymentPositionCreated` | Barzahlung {Betrag} |
| `PaymentProcessCompleted` | Zahlung abgeschlossen |
| `PurchaseTransactionClosed` | ✓ Verkauf final - Bon {Nr} |
| `PurchaseTransactionCancelled` | Bon abgebrochen - nichts verkauft |
| price change (to article master, format from GEBIT pending) | Preis im Artikelstamm geändert |
| `AnonymousCouponApplied` | Gutschein eingelöst |
| `LoyaltyMembershipAssigned` | Kundenkarte erkannt: {Persona} |

---

## 6. Hardware BOM

### 6.1 Recommended configuration (all wired)

| Item | Recommendation | Rough price | Source / note |
|---|---|---|---|
| Booth monitor | 65" commercial 4K, 24/7 (e.g. Samsung QM65C) on wall or floor stand; 55" QM55C if the budget is tight | 55": 715-925 € [V: <https://pricespy.ie/product.php?p=12548154>, galaxus]; 65": about 1,100-1,500 € [A]; stand 150-300 € [A]; or rent via the booth builder [A] | Matte commercial panel; 24/7 rated |
| Monitor player | Mini PC (Intel N100 to Core Ultra class), Chromium kiosk, Ethernet | 200-600 € [A] | Keeps the lab Mac out of the display path |
| Lab host | The existing lab MacBook (Rancher Desktop k3s, solace-1, Postgres), wired, static IP, never sleeps | existing | See 7.3 |
| POS: cashier screen | 15.6" USB-C touch monitor on mini PC #2 (Chromium kiosk window 1) | 200-300 € [A] | Plus a small mini PC 200-400 € [A] |
| POS: customer display | 10-13" portable monitor on the same mini PC (kiosk window 2) | 120-200 € [A] | Avoids Android dual-screen API issues |
| POS alternative (authentic look) | Sunmi D3 Pro 15.6" + 10.1" customer display | 499 € net + 180 € net [V: <https://jarltech.com/en/sunmi-d3-pro>] | Driving the 2nd screen from a browser is unverified [A] |
| Scanner (hands-free) | Zebra DS9308 presentation scanner, USB HID; spare: Zebra DS2208 with stand | DS9308 ≈ 305-330 € [V: <https://industry-electronics.com/zebra/ds9308-sr4u2100aze-2d-sr-multi-kit-usb-black-lieske_1539862.htm>]; DS2208 ≈ 94-152 € [V: <https://aio.lv/en/product--zebra-ds2208-sr00007zzww--260140.md>] | Alternatives: Honeywell Genesis XP 7680g, EU RRP about 342 € [V: search result, jarltech]; Datalogic Magellan 1500i, UK special about £195-210 [V: barcodestore/avoira] |
| Approval tablet | iPad (A16) 11" in Guided Access, or an Android tablet with Fully Kiosk PLUS; tablet stand with lock; USB-C Ethernet + PD adapter | iPad ≈ 320-370 € [V: <https://www.macwelt.de/article/2762446/ipad-a16-auf-neuem-tiefstpreis-bei-amazon-369-statt-399-euro.html>]; Fully PLUS 8.90 € per device one-time [V: <https://www.fully-kiosk.com/docs/en/faq/difference>]; stand 100-250 € [A]; adapter about 40 € [A] | Spare tablet recommended |
| ESL (hero) | DIY: Waveshare 4.2" B/W e-paper (V2: partial 0.4 s, fast 1.5 s, full 5 s) on an ESP32 board with Ethernet (e.g. Olimex ESP32-POE-ISO or WT32-ETH01), 3D-printed shelf-edge housing, MQTT subscriber | panel ≈ 26-30 € [V: <https://grobotronics.com/pi-display-e-paper-4.2-400x300-black-white.html?sl=en>]; ESP32-ETH board 15-35 € [A]; housing 10 € [A]; build 2 + 1 spare | Refresh times [V: <https://www.waveshare.com/4.2inch-e-paper.htm>]; do a full refresh after several partial ones [V: <https://www.waveshare.com/wiki/4.2inch_e-Paper_Module_Manual>] |
| Promo topper (optional) | Seeed reTerminal E1001, 7.5" B/W ESP32-S3, 2-5 s refresh (Wi-Fi only, so it needs an approved AP or the Telekom hotspot) | ≈ 78-90 USD [V: <https://openelab.com/products/seeed-studio-reterminal-e1001-epaper>] | Colour E1002 refreshes in 12-20 s; avoid [V: <https://wiki.seeedstudio.com/reterminal_e10xx_main_page/>] |
| Receipt printer (optional, recommended) | Epson TM-m30III (Ethernet), voucher QR on the receipt as take-away | ≈ 270-410 € [V: <https://aio.lv/en/product--epson-c31ck50112--7227429.md>, galaxus]; paper rolls | Mark the receipt "DEMO - kein Kaufbeleg" [A]. Check GEBIT POS printer support [A] |
| Shelf and products | Small 3-level shelf; 6-8 real products with EAN-13 plus dummy packs for perishables; GEBIT Ente with an in-store number (GS1 prefix 20-29) | shelf 100-300 € or from the booth builder [A]; products and dummies 100-200 € [A]; 3x stock (things get taken) | Avoid real books or tobacco except for the guardrail scenario |
| Network | 8-16 port switch; router with WAN failover (Telekom wired primary, 5G secondary, Wi-Fi off unless approved); cables | switch 30-60 € [A]; Teltonika RUTX50 5G ≈ 550-580 € [V: <https://pricespy.ie/product.php?p=7116776>], or a cheaper 5G router [A]; 2 SIMs from different carriers | Wired line from Telekom via the OOS |
| Power | Small UPS for the lab host + switch; power strips; 24 h socket for the host if staying on overnight | UPS 120-200 € [A]; 24 h socket via OOS [V: product exists, price not checked] | |
| Spares and kit | 2nd scanner, 2nd tablet, 2nd ESP32 + panel (pre-flashed), HDMI/USB-C cables, gaffer tape, cable ties, laminated control-barcode cards, persona cards | 300-500 € [A] | |

**Budget bands [A]:**

- **Lean** (55" monitor, laptop drives the display, DS2208, Android tablet, DIY ESL, no printer):
  about 2,000-2,800 €.
- **Recommended** (table above, buy): about 4,500-6,500 €.
- **Premium** (75" monitor, Sunmi POS, two topper displays, vendor ESL kit, booth-builder
  integration): about 8,000-12,000 €.

Monitor rental from the booth builder or AV partner can replace the largest purchase [A].

### 6.2 ESL options in detail

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **Vendor loan** (VusionGroup, Hanshow, Pricer, SoluM via GEBIT's ESL partner) | Real retail hardware, co-marketing, credibility with retailers | Partner-only kits (the SoluM demo kit is "for current partners only" [V: SoluM press release, via search]); vendor base station plus cloud or AIMS server; update latency depends on vendor and radio scheduling [A]; many ESL vendors are in the same hall, so it is no differentiator; lead time | Pursue via GEBIT in parallel. Use it at the fair only if API-to-flip is under 10 s in a test [A]. Pricer claims more than 50,000 updates per hour over IR [V: <https://www.pricer.com/press-release/pricer-esl-platform-breakthrough-quadruples-communication-speed-with-existing-infrastructure>] and LED alerts "within 3-4 sec." [V: <https://www.retailtechnologyshow.com/exhibitor-products/pricer-smarttag-color-stc-> listing]. These are vendor claims |
| **Generic ESL demo kit** (Minew, Zhsunyco and similar) | 299-599 USD with base station [V: Alibaba listings via search] | Proprietary cloud, unknown API latency, import lead time | Not recommended |
| **OpenEPaperLink** (reflashed used SoluM/Hanshow tags + ESP32 AP) | Real ESL hardware look, cheap | Tags check in every 40 s, typical delay 40-60 s [V: wiki Tag-protocol-timing]; CC BY-NC-SA 4.0 licence [V: <https://github.com/jjwbruijn/OpenEPaperLink>]; 802.15.4 radio in a crowded hall | **Reject** for a commercial booth |
| **DIY ESP32 + B/W e-paper, MQTT direct from Solace** | 0.4-5 s refresh; full control; "the label is just another subscriber on the event mesh" (Solace story); works wired | Hand-built; partial refresh ghosting; MQTT 1883 lands on the `default` VPN, not `sam` [V: memory project_event_mesh.md], so the price-change event must be on `default` or bridged | **Primary** |
| **Simulated label** (LCD/phone in a housing + monitor mirror) | Instant, zero risk | Not e-paper | **Fallback and mirror**, always on |

### 6.3 Hardware details that bite at fairs [A unless noted]

- **Scanner keyboard layout:** HID keyboard wedge types the characters. With the scanner set to a
  US layout and the OS set to German, letters (y/z) and symbols change. EAN digits survive.
  Configure the German layout in the scanner, or use ALT+numpad emulation, and test the control
  barcodes and voucher codes with letters.
- **Browser focus:** a keyboard-wedge scanner types into the focused window. The `/kasse` page
  keeps a global keydown buffer (characters under 50 ms apart, ended by Enter) so a scan is caught
  regardless of focus. Alternative: the scanner's USB-CDC (serial) mode with Web Serial in Chrome
  desktop.
- **No Bluetooth scanners:** 2.4 GHz is crowded and regulated at the fair; use corded USB.
- **Phones scanning QR:** a QR of at least 4 cm on the customer display, a short URL, high
  contrast; glare test under hall lighting.
- **E-paper under hall lighting:** fine; no backlight, so put it at eye level. Avoid red/colour
  panels (12-20 s refresh).
- **Theft and wear:** dummies for perishables; 3x stock; cable locks on tablet and scanner.

### 6.4 Fallback per device

| Failure | Fallback (time to switch) |
|---|---|
| Scanner | Spare scanner (10 s); on-screen product tiles on `/kasse` "Artikel antippen", which fire the same events |
| Tablet | Spare tablet (30 s); approval modal on `/kasse` or `/op` |
| ESL | Mirror tile on the monitor (always on); spare ESP32 + panel (2 min); `/etikett` on an LCD |
| Monitor | Spare HDMI; the monitor view on the deep-dive laptop turned to the aisle |
| POS mini PC | Laptop browser with `/kasse` + USB scanner |
| Receipt printer | Skip; the voucher QR is on the customer display |
| Internet | 5G failover (automatic); then L1 Regel-Modus; then L2 replay |
| Lab host (Rancher wedge) | Hot-spare laptop running booth-ui in **standalone replay mode** (embedded event simulator, no broker or SAM), switched in about 2 min; fix the lab in the background |

---

## 7. Reliability at the fair

### 7.1 Network design

- **All wired:** lab host, mini PCs, tablet (USB-C Ethernet + power on a stand), ESP32 with
  Ethernet, printer. One isolated booth LAN with **static IPs identical in rehearsal and at the
  fair** (prevents the Rancher stale-IP wedge, section 7.3).
- **Uplink:** a Telekom wired line ordered via OOS (primary) → router with automatic WAN failover
  to 5G (two SIMs from different carriers). Hall mobile networks congest at peak [A].
- **Own Wi-Fi only if approved** (5 GHz; apply early through the OOS). Otherwise keep the tablet on
  its stand and wired, with a lanyard. Leave Wi-Fi off on the router.
- Traffic is tiny: LLM calls, a few KB per event, SSE. 10 Mbit/s would suffice, but it is a shared
  hotspot dependency [A].

### 7.2 Power

- Booth power often goes off at night [A]. Either order a 24 h socket for the lab host + UPS, or run
  a **clean shutdown every evening and a scripted cold start every morning** (rehearsed: from power
  on to demo-ready in under 15 min).
- A UPS covers short power blips during the day.

### 7.3 The lab host is the single biggest risk [V: memory notes]

Known Rancher Desktop failure modes on this exact lab:

- **Sleep/wake clock wedge:** the container clock jumps decades ahead and TLS breaks
  cluster-wide. Recovery needs `docker container prune` plus `event-mesh-deployment/start.sh`, and
  the prune also deletes stopped broker containers
  [V: memory project_rancher_desktop_clock_wedge.md].
- **Dead port forwards after sleep:** the VM, dockerd and k3s are alive, but nothing on the host
  reaches them. Fix: `rdctl shutdown`, relaunch, `docker start` the compose containers, then about
  3 min until VPN `sam` is up [V: memory project_rd_dead_port_forwards.md].
- **Network change:** the stale `--node-external-ip` makes Kyverno crash-loop, fail-closed, and
  blocks all pod changes [V: memory project_rancher_stale_external_ip.md].
- **Reboot or crash:** a stale `vz.pid` leaves the instance "Broken"
  [V: memory project_rancher_stale_vz_pid.md].
- **DMR dependency:** VPN `sam` went down with "DMR Subscription Sync (v:solace-2)" after solace-2
  exited in one incident [V: memory project_rancher_desktop_clock_wedge.md], while BSG ran with
  solace-2 `Exited (137)` [V: bsg README Gate 0]. Verify the cold-start behaviour with solace-2
  stopped before the fair [A].

Mitigations [A]:

- A **dedicated booth Mac**: lid open, `caffeinate`, no sleep or auto-updates, Do Not Disturb.
- **Never switch its network.** It stays on the booth LAN from the rehearsal in the GEBIT lab
  through the fair, with the same static IP.
- A morning **preflight script** in the style of `sam-retail-ops-demo/preflight.sh` (READY / NOT
  READY), including `kubectl get pods -n kyverno`, VPN `sam` state over SEMP, the spool check, a
  model probe, an LLM latency probe, the budget, and an ESL ping.
- `sam auth login` daily (the CLI token cache expires daily [V: bsg RUNBOOK.md "Before the
  audience arrives"]).
- A hot-spare replay laptop (section 6.4).

### 7.4 Latency budget (what the visitor waits for)

| Segment | Target | Hard limit → action | Basis |
|---|---|---|---|
| Scan → line on cashier and customer display | < 0.3 s | 1 s | local, no SAM on this path [A] |
| Scan → event dot on the monitor | < 0.5 s | 1 s | broker + SSE [A] |
| Hero scan → deterministic signal card | < 1.5 s | 3 s | tool nodes 0.3-1.4 s [V: BSG] |
| Hero scan → AI proposal on tablet and monitor | 8-12 s | **15 s → Regel-Vorschlag** (labelled) | fast agent 5-11 s + overhead [V: BSG node timings] |
| Tap Freigeben → monitor "Freigegeben" | < 0.5 s | 1 s | [A] |
| Tap → price active at POS (next scan) | < 1 s | 2 s | price cache updated by event [A]; GEBIT article-master latency unknown |
| Tap → e-paper visible | 1-5 s | 8 s → mirror tile carries it | Waveshare 0.4 / 1.5 / 5 s [V] |
| `PurchaseTransactionClosed` → voucher QR | < 3 s (precomputed) | 8 s → generic voucher | [A]; architecture track to confirm how the workflow "waits" |
| Workflow timeout | - | 30 s → error event, monitor shows "KI-Antwort verworfen" | BSG uses 90 s, too long for a booth [V: RUNBOOK] |

Rules: never show a bare spinner. Always show steps with elapsed seconds. Keep the visitor busy
(scan the next item) while the agent runs.

### 7.5 Degradation levels (operator switch on `/op` or control barcode)

- **L0 Live:** SAM workflow, real LLM.
- **L1 Regel-Modus:** triggered automatically when proposal latency exceeds 15 s, LiteLLM returns
  429 budget_exceeded, or the internet is down. The proposal comes from deterministic templates
  filled with tool data, and the badge reads "Regel-Vorschlag (KI nicht erreichbar)". Everything
  else stays live.
- **L2 Replay:** real scans and events, with agent outputs taken from a recorded corpus (JSONL of
  real L0 runs per scenario and article, replayed with the original delays). Badge "Wiedergabe".
  Use it when SAM itself is down.
- **L3 Video:** the attract loop is a recorded film of a full run, used if the whole stack is down.
- **Record every L0 run** during rehearsals (events, proposal, timings): that is the L2 corpus.
  Export the runs and logs daily (Loki retention is 7 days [V: memory MEMORY.md "SAM forensics
  sources"]).

### 7.6 Reset

- **Per visitor:** automatic 25 s after the voucher, or by the `RESET` card. It clears the receipt,
  sets the monitor to attract mode and the tablet to empty.
- **Per promotion:** it ends after 2 minutes; the end event flips the ESL back ("Aktion beendet").
- **Per day:** a script reseeds the store history, resets prices to base, clears open transactions,
  checks queue and spool depth, resets the KPI counters (or keeps the day's history), and resets the
  LLM-cost counter view.

### 7.7 LLM budget at the fair

- LiteLLM has a hard 50 USD budget (HTTP 429 budget_exceeded) [V: task context]. Request a
  **dedicated fair key or budget**, e.g. 150 USD for 3 days plus rehearsals, with alerts at 50/75/90 %.
  Show the budget on `/op` [A].
- L1 must trigger on 429 automatically.

### 7.8 Rehearsal checklist

**T-6 weeks:**

- Hardware ordered.
- Messe orders placed via GEBIT before the 21-day surcharge window: wired line, 24 h socket, AP
  approval if needed.
- Text and legal review of the PAngV wording.

**T-3 weeks (GEBIT lab):**

- Full end-to-end with real GEBIT events.
- 20 timed runs per primary scenario; p50/p90 for each latency segment.
- Record the L2 corpus.
- Cold-start drill and hot-spare switch drill.
- 100 consecutive scans without a miss.
- Glare and readability test at 3 m and 5 m.
- Staff walk-through: every role can do every role.

**Set-up day:**

- Booth LAN with the same IPs.
- Test the Telekom line and 5G failover (pull the cable while running).
- Lighting and glare check; scanner reading phone screens.
- 10 runs; test the RESET card and all control cards.
- Check the hall noise (visual feedback sufficient).

**Every morning:**

- Cold start, preflight READY.
- `sam auth login`.
- One warm-up run per scenario (first runs after a start can be slow [V: retail talk-track
  Appendix A item 9 for the Builder; A for workflows]).
- Budget check; ESL full refresh; product stock and dummies in place.

**Every hour:** glance at `/op` (devices, LLM p90, budget, mode).

**Every evening:** export the runs and logs; clean shutdown or confirm the 24 h power; charge the
tablets; restock the shelf.

---

## 8. Recommended UI technology

### 8.1 Architecture of the screens

```text
 POS events (simulator now / GEBIT later) --> Solace broker --> SAM workflows
                                                  |   ^
                                                  v   |  (decisions, price change, voucher)
                                   booth-ui (FastAPI BFF, one container)
            SSE /stream?view=monitor|freigabe|kasse|kunde|etikett|op  +  POST /api/decision ...
                 |            |            |           |            |
             /monitor     /freigabe     /kasse      /kunde       /op        ESP32 ESL <-- MQTT (default VPN)
             (mini PC)    (tablet)      (mini PC)   (2nd display)(laptop)
```

- **One booth-ui service** (FastAPI + SSE + static HTML/CSS/vanilla JS), packaged like
  BSG's `demo-ui` [V: bsg-trading-desk-demo/app/bsgdemo/ui/server.py]. A **normalised view model**
  (ScanEvent, ReceiptState, Signal, Proposal, Decision, PriceChanged, Voucher, Health) is what the
  pages consume. The pages never parse GEBIT protobuf/JSON. An adapter layer in the BFF maps
  "simulated GEBIT JSON (proto3 JSON with @type)" today and "real GEBIT events" later. **That is the
  swap point.**
- **Why a BFF and not browser-to-broker WebSocket:**
  - No broker credentials on kiosk devices. The retail shop page connects with `default/default`
    from the browser [V: sam-retail-ops-demo/shop/index.html:163-174].
  - One place for the L1/L2 switch and the replay injection.
  - One UTF-8 decoding path.
  - SSE auto-reconnects natively.
  - Per-view filtering.
  - Direct broker access remains for the ESP32 label (MQTT), where it makes the Solace point.
- **Why not React/Vite for v1:** five small, mostly read-only views; no build chain; matches the
  verified BSG pattern and its operational knowledge. If a GEBIT front-end developer joins, Vite +
  Preact/React is fine as long as the output is static files served by the BFF (no runtime CDN) [A].
- **Real agent progress (optional):** the BFF additionally subscribes over SMF/WebSocket to VPN
  `sam` A2A status topics, to replace the inferred agent timer with real node events. That is the
  gap BSG left open [A].

### 8.2 Kiosk set-up [A unless noted]

- **Mini PCs:** Chromium `--kiosk --app=<url> --noerrdialogs --disable-session-crashed-bubble
  --disable-features=Translate --overscroll-history-navigation=0`; two windows with
  `--window-position` for the cashier screen and the customer display; autostart; no sleep.
- **Tablet:** iPad Guided Access (auto-lock "never" in the Guided Access options), or Android with
  Fully Kiosk Browser PLUS (kiosk mode is a PLUS feature, 8.90 € one-time per device)
  [V: <https://www.fully-kiosk.com/docs/en/faq/difference>].
- **Screen Wake Lock API** in every page (`navigator.wakeLock.request('screen')`), plus OS
  settings.
- **Heartbeat:** every page reports to `/op`; a page that loses SSE shows a small "Verbindung wird
  wiederhergestellt" badge and reconnects.
- **NTP on all devices;** relative times on screen ("vor 3 s").

### 8.3 Animation and typography

- CSS transforms and the Web Animations API only (GPU-friendly on a mini PC), at 60 fps.
- **Event dot:** 600-800 ms ease-out.
- **Price flip:** the old price slides up and is struck, the new price counts down over 600 ms.
- **Proposal card:** slide in with a glow.
- **"Freigegeben" stamp:** 300 ms scale.
- **Fan-out:** 4 arrows in sequence, 150 ms apart.
- No particle effects, no confetti, no infinite spinners.
- Self-hosted fonts: brand fonts if GEBIT/Solace CI allows, else Inter or Source Sans 3 (OFL)
  [A]; `font-variant-numeric: tabular-nums`; the type scale from 4.6.
- **Dark theme on the monitor** (control-room look, high contrast in a bright hall); **light theme
  on the tablet** (paper-like approval form) [A].

### 8.4 German UI strings (starter glossary) [A]

- Monitor:
  - Headline: "KI schlägt Preise vor. Sie entscheiden."
  - Attract: "Scannen Sie ein Produkt aus dem Regal"
  - Sections: "Live an der Kasse", "Was die KI gerade tut"
  - Rule line: "Ohne Freigabe kein neuer Preis"
- Status:
  - "Erkannt", "KI formuliert Vorschlag", "Wartet auf Freigabe", "Freigegeben", "Preis aktiv",
    "Aktion beendet", "Verkauf final", "Bon abgebrochen - nichts verkauft"
  - Degraded: "Regel-Vorschlag (KI nicht erreichbar)", "Wiedergabe"
- Tablet:
  - Header: "Marktleitung · Freigaben"
  - Sections: "Warum", "KI-Einschätzung", "Wirkung", "Prüfungen"
  - Buttons: "Freigeben", "Anpassen", "Ablehnen", "Rückgängig"
  - Reason chips: "Aktion läuft bereits", "Marge zu niedrig", "Ware kommt nach", "Sonstiges"
- Customer display:
  - "AKTION", "Sie sparen {x} €", "Niedrigster Preis der letzten 30 Tage: {p} €"
  - "Danke! Ihr Gutschein für den nächsten Besuch"
- Phone:
  - "Ihr Gutschein", "So ist dieser Gutschein entstanden", "Unterlagen anfordern",
    "Termin vereinbaren"
- Agents return ASCII ("EUR", "ae") in structured fields; the UI renders "€" and umlauts from its
  own templates (section 1.2).

---

## 9. Throughput and cost model

**Throughput [A]:**

- Cycle: 3:00 interaction + 0:30 handover → at most about 17 guided visitors per hour per station.
- At a realistic 40-60 % load: 7-10 per hour.
- Assuming 8 h per day: 55-80 per day, 165-240 over 3 days, plus 2-4 onlookers each (500-900
  people reached).
- Show mode at peak: one run every 4 min for 4-8 people.
- A second, self-service "Express-Scan" station would raise participation, but it is extra hardware
  and staff; optional.

**LLM cost [A, prices V: claude-api skill model table cached 2026-11-03]:**

- Haiku 4.5: $1 per MTok input / $5 per MTok output.
- Sonnet 5: $2 / $10.
- Opus 5: $5 / $25.
- Haiku 5.5 is listed at $0.10 / $0.50 per MTok. Ask whether LiteLLM can offer it, then measure
  its latency.
- Per agent call, assume about 20k input + 1k output tokens. BSG used about 60k tokens per run with
  3 agents [V]. On Haiku 4.5 that is about $0.025 per call.
- Per guided visit, 2 calls (proposal + voucher text) = about $0.05. 240 visits = about $12;
  400 rehearsal runs = about $10. **Total about $20-25.**
- An LLM on every event (about 11 per sale) would be about $0.28 per visit and about $66 for 240
  visits, which breaks the 50 USD cap. Keep the agent behind a switch or tool node.
- Upstream pricing through LiteLLM may differ by provider.

---

## 10. Timeline to the fair (about 14 weeks) [A]

| When | Milestone |
|---|---|
| W46-47 (Nov) | Wireframes for 6 views + German copy; choose hero products; order hardware; request a vendor ESL loan via GEBIT; GEBIT confirms booth space, hall, staff and CI |
| W48-50 (Dec) | booth-ui v1 against the simulator; DIY ESL prototype over MQTT; first end-to-end on the lab; latency and token measurement; L1 Regel-Modus |
| W51-2 | Internal rehearsals with staff; replay corpus v1; preflight script; landing page live on a public host |
| W3 (mid-Jan) | Messe orders done (wired line, 24 h power, AP approval) before the about 21-day surcharge window [V: 2018 rule]; legal review of the price wording |
| W3-5 | GEBIT lab: switch the adapter to real GEBIT events and the price-change service; dress rehearsal on the booth LAN (same IPs) |
| Set-up (about 14-15 Feb) | Network and failover test, glare, 10 runs, staff briefing |
| 16-18 Feb 2027 | Fair (dates to be confirmed officially) |

---

## 11. Open questions

**For GEBIT:**

1. Booth size, hall and position, opening hours, and staff available for the host and approver
   roles.
2. Can the real GEBIT POS client and hardware run at the booth? Does it have a customer display?
   Which receipt printers does it drive? Does it print `CheckoutCoupon.print_content`?
3. Price change: what are the article-master command and event, and how fast does the POS apply a
   new price (cache, next scan)? Can a promotion carry an end time?
4. Which ESL vendor does GEBIT integrate in customer projects, and can that vendor lend a kit and an
   API account? What is the measured API-to-label latency?
5. Coupons: how is a voucher for the next visit modelled (`CheckoutCoupon`, `ApplyAnonymousCoupon`)?
   Can the booth redeem it?
6. Hero products: is there a physical GEBIT Ente (giveaway)? Are we allowed to use real branded
   products on the shelf?
7. CI and branding rules (GEBIT + Solace co-branding); language mix DE/EN on screens.
8. Legal review of the PAngV §11 display text and the "Messe-Zeitraffer" wording.
9. Lead process: Messe lead app, CRM, consent text; who owns the leads?

**For the owner:**

1. A fair LLM budget and model tier (fast/Haiku 4.5 vs. Haiku 5.5 if available).
2. Is a labelled Regel-Modus or replay acceptable on the booth?
3. A dedicated booth Mac or the lab Mac?
4. Should SAM WebUI inbox notifications (`notify_user`) appear as a second channel, e.g. on the
   deep-dive laptop or a staff phone via Teams?
5. Should the visitor be the approver by default, or always a staff member?

**For Messe Duesseldorf (via GEBIT):**

1. Current wired line products and prices.
2. AP approval (5 GHz channel).
3. 24 h power.
4. Hall lighting at the booth location.
5. The 2027 lead-scanning offering.

---

## 12. Risks (ranked)

1. **Lab host wedges** (sleep, network change, reboot) take the whole demo down → dedicated host,
   fixed booth LAN, rehearsed cold start, hot-spare replay laptop.
2. **Agent latency over 15 s or LLM unavailable/out of budget** at peak → masking choreography,
   precomputed voucher, L1 automatically, a dedicated budget.
3. **Messe Wi-Fi rules and RF congestion** → wired everything, apply early for AP approval, 5G
   failover.
4. **The ESL hero moment is too slow or fails** (vendor or OpenEPaperLink 40-60 s, colour e-paper
   12-20 s) → DIY B/W partial refresh plus a monitor mirror; vendor ESL only after a latency test.
5. **Booth scans distort the slow-seller logic** → simulated store baseline, multi-factor trigger,
   2-minute promotions.
6. **Credibility and legal claims** (PAngV §11 display, "KI lernt", personalised prices) → legal
   review, honest copy, personalisation only in vouchers.
7. **Payment and closing event bursts** (6 events within 0.15 ms) → UI animation queue; SAM
   per-event workflow concurrency to be load-tested by the architecture track.
8. **Mangled non-ASCII in agent output** → structured outputs, UI-side templates.
9. **Platform conflicts** (only one demo overlay at a time) → freeze the lab for the fair.
10. **The GEBIT live switch comes late** → the simulator stays the default; the adapter flag is
    rehearsed in both directions.
11. **Theft and wear of products and devices** → dummies, spares, locks.

---

## Appendix A - Sources

Local (verified by reading or command):

- `bsg-trading-desk-demo/README.md` ("Measured on the cluster", "Decisions", "Gate 0"),
  `RUNBOOK.md`, `app/bsgdemo/ui/server.py:1-20`, `app/bsgdemo/ui/static/index.html:14-87`
- `sam-retail-ops-demo/README.md`, `talk-track.md` Appendix A (lines 873-960),
  `shop/index.html:163-197`
- SAM 2.493.0 docs: `reference__built-in-tools.md:25,40,159-171,836-847`,
  `reference__rbac-reference.md:62-63`, `administering__enabling-rbac.md:27`,
  `reference__env-vars.md:150-152`
- GEBIT: `events_simpleSale/03_PositionAdded.json`, all 11 event timestamps (python3 -I),
  `simpleSale.json` (structure dump), `purchase/.../v2/event/*.proto` and `command/*.proto`
  (message names), `receipt/.../v2/datatype/loyalty_datatype.proto:188-255`,
  `receipt_datatype.proto:125-126,254-264`
- Memory notes: project_sam_v2_workflow_events.md, project_sam_mcp_workflow_tools.md,
  project_event_mesh.md, project_rancher_desktop_clock_wedge.md, project_rd_dead_port_forwards.md,
  project_rancher_stale_external_ip.md, project_rancher_stale_vz_pid.md
- `kubectl get pods -n sam-solace-lab -o wide` (2026-11-10)
- claude-api skill model and pricing table (cached 2026-11-03)

Web:

- EuroCIS dates: <https://tradefest.io/en/event/eurocis>,
  <https://www.messen.de/de/7614/duesseldorf/eurocis/info>,
  <https://www.technologyrecord.com/article/eurocis-2026-showcasing-innovations-that-address-real-challenges-in-retail>
- Messe Duesseldorf Wi-Fi: <https://www.boot.com/en/Exhibit/WiFi_regulations>,
  <https://www.compamed-tradefair.com/en/Exhibit/WiFi_regulations>,
  <https://www.oos.rehacare.de/2017/en/FORM_WLAN>
- Power and OOS: <https://oos.eurocis.com/2018/en/BE2200>, <https://oos.drupa.de/en/BE2240F>
- Lead scanning: <https://oos.eurocis.com/2019/en/BE9801>
- 3-second rule: <https://exhibitoronline.com/topics/article.asp?ID=1449>,
  <https://www.alta-graphics.com/alta-blog/tips-to-make-your-trade-show-booth-graphics-get-noticed/>
- Dwell time: <https://skyline.com/blog/improve-dwell-time-in-your-trade-show-booth>,
  <https://demoboost.com/interactive-demo-playbook/conferences-shows-demo>,
  <https://www.pavegen.com/blog/10-things-your-trade-show-booth-is-missing>
- Letter height: <https://www.signs.com/blog/?p=16381>
- OpenEPaperLink: <https://github.com/jjwbruijn/OpenEPaperLink>,
  <https://github.com/jjwbruijn/OpenEPaperLink/wiki/Tag-protocol-timing>
- Waveshare: <https://www.waveshare.com/4.2inch-e-paper.htm>,
  <https://www.waveshare.com/wiki/4.2inch_e-Paper_Module_Manual>
- Seeed reTerminal: <https://wiki.seeedstudio.com/reterminal_e10xx_main_page/>,
  <https://openelab.com/products/seeed-studio-reterminal-e1001-epaper>
- Pricer: <https://www.pricer.com/press-release/pricer-esl-platform-breakthrough-quadruples-communication-speed-with-existing-infrastructure>
- SoluM: <https://solumesl.com/getnewton>,
  <https://www.solum-group.com/solum/press-release-detail.newton-labels-take-center-stage-at-eurocis-2024>
- Scanners: <https://industry-electronics.com/zebra/ds9308-sr4u2100aze-2d-sr-multi-kit-usb-black-lieske_1539862.htm>,
  <https://aio.lv/en/product--zebra-ds2208-sr00007zzww--260140.md>,
  <https://jarltech.com/en/honeywell-genesis-xp-7680g>
- Displays and POS: <https://pricespy.ie/product.php?p=12548154>,
  <https://jarltech.com/en/sunmi-d3-pro>
- Tablets: <https://www.macwelt.de/article/2762446/ipad-a16-auf-neuem-tiefstpreis-bei-amazon-369-statt-399-euro.html>
- Kiosk browser: <https://www.fully-kiosk.com/docs/en/faq/difference>
- Printer: <https://aio.lv/en/product--epson-c31ck50112--7227429.md>
- 5G router: <https://pricespy.ie/product.php?p=7116776>
- PAngV: <https://lxgesetze.de/pangv/11>,
  <https://www.it-recht-kanzlei.de/faq-werbung-preisermaessigungen-gesamtpreis-preisangabenverordnung.html>,
  <https://www.otto-schmidt.de/news/wirtschaftsrecht/werbung-mit-preisermassigung-niedrigster-gesamtpreis-der-letzten-30-tage-muss-unmissverstandlich-und-klar-erkennbar-sein-2025-10-09.html>
- Omnibus / personalised prices: <https://7learnings.com/blog/what-retailers-need-to-know-about-the-new-eu-consumer-protection-directive/>
- Human-AI guidelines: <https://www.microsoft.com/en-us/research/blog/guidelines-for-human-ai-interaction/>
