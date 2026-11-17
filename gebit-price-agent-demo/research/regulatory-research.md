# Regulatory guardrails: price and promotion agent with approval (EuroCIS showcase)

Track: legal and regulatory guardrails for dynamic pricing, ESL, markdowns and
personalised offers in Germany and the EU. Research date: 2026-11-10.

This is not legal advice. It derives demo guardrails from public law,
guidance and case law. Before anything goes live in a retailer's store, the
retailer's counsel (and GEBIT's tax and compliance people) have to sign off.

Legend used throughout:

- **[V]** = VERIFIED in this session, with the source (statute text, court
  decision, official guidance, local file:line, or at least two consistent
  secondary sources).
- **[A]** = ASSUMPTION, interpretation or well-known fact not re-fetched in
  this session. Treat it as a hypothesis to confirm.

---

## 0. Executive summary (what matters for the demo)

1. **The 30-day rule is the single most important legal mechanic and the best
   "compliance as a feature" moment.** Whenever the shelf label, monitor,
   receipt or app *announces* a price reduction (strike-through, "-20 %",
   "Aktion", "Preis-Highlight", "Super-Knüller"), the lowest price applied
   to consumers in the 30 days before the reduction must be shown, and any
   percentage must be calculated against that 30-day price
   (§ 11 Abs. 1 PAngV; ECJ C-330/23 Aldi Süd, 26.09.2024; BGH I ZR 183/24,
   09.10.2025) [V]. A silent price change without a reduction claim is not
   covered (Commission PID guidance, section 1.1) [V]. So the agent needs a
   **per-article price history** and a deterministic **reference-price
   calculator**; if the new price is not below the 30-day lowest price, a
   reduction must not be advertised at all.
2. **Exceptions are narrow and must be machine-checked**: individual
   (personalised) reductions and perishable goods reduced because of
   imminent spoilage *with a visible reason* (§ 11 Abs. 4 PAngV; OLG
   Nürnberg 3 U 2376/24, 05.08.2025: the best-before date on the pack is not
   enough) [V]. Gradual uninterrupted reductions may keep the first
   reference price (§ 11 Abs. 2 PAngV, read narrowly per Commission guidance
   4.3) [V].
3. **The owner's "voucher for the next visit" idea is the legally cleanest
   personalisation pattern.** The Commission's guidance names a "20 % off"
   voucher issued on purchase, valid for the next purchase, as a *real
   personalised price reduction outside Art. 6a* (guidance 2.3) [V]. Best
   practice in DACH retail (Lidl, Billa, Spar apps) is: **uniform shelf
   price for everyone + personalised coupons that only reduce** [V,
   secondary]. Consumer bodies (vzbv 23.10.2025, BEUC) want personalised
   price *increases* banned, while personalised *discounts* are tolerated
   with transparency [V].
4. **Dynamic pricing in a German store is legal (price autonomy), but
   sensitive.** Limits: price clarity and shelf/checkout consistency (§ 1
   Abs. 3, § 10 PAngV), misleading practices (§ 5 UWG, UWG blacklist), price
   gouging on essentials in a shortage (§ 4 WiStG, fine up to 25,000 EUR),
   food below cost for retailers with superior market power (§ 20 Abs. 3
   GWB, spoilage exception) [V]. Public fear of "surge pricing" via ESL is
   real (US: Kroger letter 2024, Seattle grocery surveillance-pricing ban
   Sept 2026, Maryland ban April 2026) even though the first empirical ESL
   study found practically no surge pricing [V]. **Demo stance: markdowns
   only, no increases during opening hours, no customer-specific shelf
   prices.**
5. **EU Digital Fairness Act (DFA): proposal expected tomorrow,
   11.11.2026** (IAPP 22.10.2026; EPRS briefing Oct 2026) [V]. A leaked
   71-page draft (reported 09.11.2026) is a *Regulation* replacing the UCPD
   (which also applies offline) and restricts personalised pricing that
   exploits vulnerabilities; fines up to 6 % of worldwide turnover in
   Commission-led cases [V, press]. At EuroCIS (16-18.02.2027 [V,
   secondary]) the DFA will be a fresh proposal, not law: a perfect talking
   point ("built for the DFA world already").
6. **EU AI Act: a retail pricing/promotion agent is not high-risk** (not in
   Annex III; only credit scoring and life/health-insurance pricing are)
   [A, well-established]. Art. 5 prohibitions apply since 02.02.2025
   (no exploitation of age/disability/socio-economic vulnerabilities; the
   Commission's Art. 5 guidelines use AI differential pricing against
   low-income consumers in insurance as an example) [V]. **Art. 50
   transparency applies since 02.08.2026 and was not postponed** by the
   Digital Omnibus (Reg. (EU) 2026/1744, in force 27.07.2026), which moved
   Annex III high-risk duties to 02.12.2027 [V]. Germany's KI-MIG is in
   force since 29.07.2026 (Bundesnetzagentur = market surveillance) [V].
   Human oversight is legally mandatory only for high-risk systems, so the
   approval step is *voluntary best practice* and should be sold as such.
7. **KassenSichV/TSE**: at a fair with no real sale there is no recordable
   business transaction [A]. The sensitive part is producing documents that
   look like real fiscal receipts. GEBIT's own sample already uses a TSE
   **simulator** (signatures prefixed `++FCC+SIMULATOR++`,
   simpleSale.json:234, :294) and a placeholder VAT ID (`DE123456789`,
   simpleSale.json:36) [V]. Guardrail: demo or training mode
   (`BON_TYP=AVTraining`), "DEMO - kein Kassenbeleg" marking, never a
   productive TSE, no real money, vouchers without monetary value.
8. **Antitrust (brief)**: unilateral pricing with own data is fine; risk is
   a shared pricing tool or vendor platform that pools non-public data of
   competing retailers (hub-and-spoke, Eturas C-74/14; EU Horizontal
   Guidelines 2023) [V, secondary]. GEBIT is a platform vendor for many
   retailers, so **tenant isolation of pricing data** is a selling point.
9. **Architecture consequence**: the LLM agent only *proposes*; a
   deterministic SAM **tool node** (no LLM) evaluates ~30 guardrails, a
   **switch node** routes to auto-OK / human approval / 4-eyes / reject, and
   only the guardrail service may emit the price-change event to GEBIT's
   article master data service. Guardrails run twice (before the approval
   card and again at commit).

---

## 0.1 Context facts that shape the guardrails

- EuroCIS 2027: 16-18 February 2027, Messe Düsseldorf, trade visitors only
  (B2B) [V, secondary: messen.de, tradefest.io]. The PAngV applies to offers
  "von Unternehmern gegenüber Verbrauchern" (§ 1 Abs. 1 PAngV) [V]. At a
  B2B booth with simulated sales, the PAngV is therefore probably not even
  triggered [A]. The demo must still behave *as if in a German store*,
  because that is what the audience (retail IT and compliance people)
  will judge.
- GEBIT sample receipt (local, untrusted data, read only):
  - fiscal block with KassenSichV fields: `DE_SerialNoTSS`,
    `DE_TransactionNo`, `DE_SignatureCounterStart/Finish`,
    `DE_TimestampStart/Finish`, `DE_ProcessType = Kassenbeleg-V1`,
    `DE_ReceiptType` ("BON_TYP") = `Beleg` (simpleSale.json:179-317,
    :261-264) [V]
  - signatures and QR code from a simulator (`++FCC+SIMULATOR++`,
    simpleSale.json:214, :234, :294) [V]; "FCC" is probably a fiscal cloud
    connector [A]
  - `vatNumber: DE123456789` (placeholder, :36), `cashdrawerId:
    PURCHASE_IT_TEST_CASHDRAWER` (:56), employee `ID199901` (:52) [V]
  - position `priceSource: freezePrice` (:125); per the receipt proto,
    `price_source` tells where the unit price came from, which matters
    most when that price takes precedence over master-data prices
    (receipt basket_datatype.proto:272-274) [V]; what `freezePrice`
    means exactly (price frozen at scan time?) is [A], ask GEBIT.
- GEBIT Purchase API (proto, read only):
  - loyalty memberships carry `bool anonymous = 15` (the shopper stays
    anonymous, no known individual customer) and `optional string
    customer_id`, which stays empty for anonymous memberships
    (loyalty_datatype.proto:92-97) [V], which is ideal for data
    minimisation
  - commands `ApplyAnonymousCoupon` (loyalty_command.proto:25),
    `AssignLoyaltyCoupon` (:115), `ApplyPercentageArticlePositionDiscount`
    (basket_command.proto:303), `OverrideArticlePositionPrice` (:282) [V]
  - no "training" mode field anywhere in the purchase or receipt protos
    (grep, 0 hits) [V], so training mode is likely configured in the
    fiscal service or the till [A].
- Event finality (GEBIT developer, via task brief): `PositionAdded` etc. are
  only final after `PurchaseTransactionClosed`; `PurchaseTransactionCancelled`
  means not sold. For guardrails this means: vouchers and any "sold"
  statistics only on `Closed`; the 30-day price history comes from
  *applied prices* (article master / price service), not from receipts.

---

## 1. Preisangabenverordnung (PAngV 2022) and price-reduction case law

### 1.1 Statutory text (gesetze-im-internet.de, PAngV 2022)

- **§ 1 Abs. 1**: scope = goods/services offered by traders *to consumers* [V].
- **§ 1 Abs. 3**: price information must be clearly attributable, "leicht
  erkennbar und deutlich lesbar oder sonst gut wahrnehmbar" and must follow
  "den Grundsätzen von Preisklarheit und Preiswahrheit" [V]. The BGH reads
  § 1 Abs. 3 S. 2 into § 11: the 30-day price must be shown
  "unmissverständlich, klar erkennbar und gut lesbar" (BGH I ZR 183/24) [V].
- **§ 4 (Grundpreis)**: unit price next to total price for goods sold by
  weight, volume, length or area, "unmissverständlich, klar erkennbar und gut
  lesbar"; may be omitted if identical to the total price; exceptions in
  Abs. 3 (under 10 g/ml, vending machines, small direct sellers, ...) [V].
- **§ 5 (unit)**: 1 kg, 1 l, 1 m, 1 m², 1 m³; for loose goods 1 kg or 100 g,
  1 l or 100 ml [V]. **So every markdown must recompute the Grundpreis on
  the ESL.**
- **§ 7 / ECJ C-543/21 (29.06.2023, Pfandbehälter)**: the deposit is stated
  separately, not included in the total price [V for the case via omsels
  aggregator; § 7 content A]. Beverage markdowns must not fold the deposit
  into the reduced price or the percentage.
- **§ 10 (Handel)**: goods that consumers can take themselves must be priced
  with labels on goods or shelves; exception for goods shown during
  promotional demonstrations if the price is stated during the demo and
  before the contract (§ 10 Abs. 6 Nr. 2) [V]. ESLs are a form of shelf
  labelling [A, obvious].
- **§ 11 Preisermäßigungen** [V]:
  - Abs. 1: "bei jeder Bekanntgabe einer Preisermäßigung" state "den
    niedrigsten Gesamtpreis ..., den er innerhalb der letzten 30 Tage vor
    der Anwendung der Preisermäßigung" applied to consumers.
  - Abs. 2: for a gradual, uninterrupted increasing reduction ("schrittweise,
    ohne Unterbrechung ansteigende Preisermäßigung") the lowest price before
    the *first* step may be kept for the whole reduction period.
  - Abs. 3: applies accordingly to traders who only owe the Grundpreis
    (loose goods, § 4 Abs. 2).
  - Abs. 4: does **not** apply to (1) "individuellen Preisermäßigungen" or
    (2) reductions of "schnell verderbliche Waren oder Waren mit kurzer
    Haltbarkeit" when reduced because of imminent spoilage or expiry *and
    this is made recognisable to consumers in a suitable way*.
- Note: the 30-day rule for newly listed goods (less than 30 days on sale)
  is not in § 11 PAngV 2022 as a separate paragraph in the fetched text; the
  Directive leaves it to Member States [A]. For the demo, seed at least 30
  days of history for every article.
- **§ 20 PAngV**: breaches of § 10 Abs. 1-4 and § 11 Abs. 1 (also with
  Abs. 3) are administrative offences under § 3 Abs. 1 S. 1 Nr. 2 WiStG
  1954 [V]; § 3 Abs. 2 WiStG: fine "bis zu fünfundzwanzigtausend Euro" [V].
  For widespread cross-border infringements in a CPC coordinated action,
  § 19 UWG allows up to 4 % of annual turnover (or 2 million EUR) for
  breaches of § 5c UWG [V].
- In parallel, a missing or unclear 30-day price is an omission of material
  information under § 5a Abs. 1, Abs. 2 Nr. 2 and § 5b Abs. 4 UWG
  (BGH I ZR 183/24), so competitors, the Wettbewerbszentrale and consumer
  associations can sue for injunctions [V].

### 1.2 EU layer: Art. 6a Price Indication Directive and Commission guidance

Commission Notice 2021/C 526/02 (OJ C 526, 29.12.2021), read in full text
from the PDF in this session [V]:

- **1.1**: Art. 6a "does not deal with, and does not restrict in any way,
  price fluctuations and price decreases that do not involve a price
  reduction announcement". Vague claims like "sales price", "special offers",
  "Black Friday offers" *are* covered; "best/lowest prices" comparisons with
  other sellers are not (they fall under the UCPD).
- **2.2**: a general reduction announcement (banner, "20 % on everything")
  needs no prior price on the banner itself, but the prior price per item
  must be correct.
- **2.3 (key for personalisation)**: Art. 6a does not apply to continuous
  loyalty programmes (discount cards, points), nor to "real personalised
  price reductions", for example a "20 % off" voucher received on purchase,
  valid for the next purchase until end of month, birthday or sign-up
  reductions, and "reductions applied at the time of the purchase that have
  not been announced in advance". **But** "This weekend 20 % off on
  everything for loyalty members only" or a code available to everyone is
  a public reduction (Art. 6a applies) when the programme is used by many
  or most customers. These offers remain subject to the UCPD.
- **4.1 Perishables**: "fresh food and drinks with short expiry time
  limits"; not seasonal clothing that only "expires" commercially.
- **4.3 Progressive reductions**: the first reference price may be kept only
  when the price is reduced "progressively, without interruptions and
  without increasing the indicated prior price"; successive campaigns with
  intermittent price increases (e.g. "20 % every Sunday") use the general
  rule, i.e. the previous promo price becomes the new 30-day lowest price.

### 1.3 Case law 2024-2026 (Germany/EU)

- **ECJ C-330/23 Aldi Süd, 26.09.2024** (ECLI:EU:C:2024:804): a reduction
  announced as a percentage or a claim highlighting a price advantage
  ("Preis-Highlight") must be calculated on the 30-day prior price; naming
  the 30-day price "as mere information" is not enough [V: curia press
  release p1_4575171, beck-aktuell, otto-schmidt, LG Düsseldorf PM 13/24].
  LG Düsseldorf 38 O 182/22 then granted the injunction [V].
- **BGH 09.10.2025, I ZR 183/24 ("Jacobs Krönung", Netto)**: flyer showed
  4.44 EUR, strike-through 6.99 EUR, "-36 %"; the 30-day best price 4.44 EUR
  only in a footnote at the page bottom; the BGH dismissed Netto's appeal:
  the 30-day price must be shown clearly, legibly and unambiguously; breach
  is also unfair under § 5a UWG [V: ra-plutte.de, datev-magazin, omsels].
- **OLG Düsseldorf 18.12.2025, I-20 U 43/25 (Aldi Süd, energy drink)**:
  0.99 EUR, "UVP 1.29", "-23 %" was treated as a price reduction under § 11
  Abs. 1 because the layout suggested one; revision allowed [V].
  **OLG Köln 15.05.2026, 6 U 92/25 disagrees** (a clearly labelled UVP
  comparison is not a § 11 reduction) [V: omsels aggregator]. Revisions at
  the BGH reportedly pending (I ZR 80/25 and one more) [V, secondary, the
  second file number is uncertain]. **Demo consequence: do not use UVP
  strike-through comparisons at all.**
- **OLG Köln 13.02.2026, 6 UKl 4/25**: a stated percentage must tie to the
  30-day reference price; extra reference prices must be explained and must
  not distract [V: omsels].
- **OLG Köln 27.03.2026, 6 U 77/25**: a reduction followed by a price
  increase disclosed only later in small print is misleading [V: omsels].
- **OLG Karlsruhe 03.03.2026, 14 U 83/25**: "Sie sparen* 33 %" plus
  "SUPER-KNÜLLER" for carrots is a § 11 reduction; the percentage must
  refer to the 30-day lowest price [V: omsels].
- **OLG Nürnberg 05.08.2025, 3 U 2376/24**: perishable exception only if the
  *reason* (imminent spoilage/expiry) is stated clearly; a best-before date
  on the pack front is not enough [V: omsels].
- **BGH 02.07.2026, I ZR 242/25 (Beschluss)**: whether a reduction is
  "announced" depends on public perception; a strike-through price for a
  "Set" in a Christmas sale may signal a reduction [V: omsels].
- **App-only prices**: in a Lidl flyer the lamb price applied only with the
  Lidl Plus app; the normal price was not clear for other shoppers and the
  Grundpreis was missing or calculated from the app price; Lidl changed it
  [V, press: giga.de]. vzbv v. Lidl ("paying with data"): OLG Stuttgart
  23.09.2025, 6 UKl 2/25, held that "price" means money only; revision
  pending at the BGH as I ZR 198/25 [V]; no BGH ruling found as of today [V,
  search].

### 1.4 Shelf price vs checkout price

- Consumer centres: in Germany the shelf label is an *invitatio ad
  offerendum*; the checkout price applies, the customer may refuse the item;
  deliberate mis-pricing is an administrative offence (VZ NRW, VZ
  Niedersachsen) [V]. So a mismatch does not give the customer a legal claim
  to the lower price, but it breaches price truth/clarity (§ 1 Abs. 3, § 10
  PAngV) and may mislead (§ 5 UWG) [A for the UWG qualification].
- The VZ Hamburg sample check of digital price tags (2017) found wrong
  Grundpreise after shrinkflation, missing or illegible Grundpreise, and
  *labels showing a different price than the scanner* [V]. This is exactly
  the failure mode the demo should visibly prevent.
- Practical rule for the demo: **one effective timestamp per price change;
  POS price and ESL price switch together; the agent never raises a price
  for an article already in an open basket.**

### 1.5 Guardrail implications (PAngV)

| Rule | Machine check |
| --- | --- |
| Reference price | `ref30 = min(applied_price, window [t-30d, t))` per article and store |
| Reduction base | displayed % = floor((ref30 - new) / ref30 * 100) |
| No fake reduction | if `new >= ref30` then `advertise_reduction = false` |
| Perishable exception | `perishable && days_to_bbd <= N && reason_text_on_label` |
| Gradual reduction | keep campaign ref only if uninterrupted and never raised |
| Grundpreis | recompute and render for every new price (§ 4, § 5) |
| Deposit | deposit shown separately, excluded from % (§ 7, C-543/21) |
| No UVP comparisons | template has no UVP field |
| Member-only promo | treat as public reduction (ref30 + normal price + Grundpreis for both) |

---

## 2. Dynamic and surge pricing in brick-and-mortar retail with ESL

### 2.1 Legality in Germany

- No statute forbids changing shelf prices during the day; German law starts
  from freedom of contract and price autonomy [V, secondary commentary;
  A as a legal summary].
- Hard limits relevant for an agent:
  - price clarity, truth and shelf/checkout consistency (§ 1 Abs. 3, § 10
    PAngV) [V]
  - § 11 PAngV whenever a reduction is *announced* (section 1) [V]
  - misleading and aggressive practices (§§ 5, 5a, 4a UWG and the UWG
    blacklist annex; e.g. Nr. 5 bait offers without adequate stock and
    Nr. 7 false "only for a very limited time" claims) [A: annex numbers
    from the UCPD blacklist, not re-fetched]
  - **§ 4 WiStG**: demanding unreasonably high prices for goods of essential
    need as a result of restricted competition, abuse of market power or a
    *shortage* ("Mangellage") is an administrative offence, fine up to
    25,000 EUR [V]. Surge pricing on water or bread during a heat wave or
    supply disruption is precisely this risk.
  - **§ 20 Abs. 3 GWB**: companies with superior market power versus small
    and medium competitors may not sell food below cost price
    ("Einstandspreis") unless objectively justified; selling below cost to
    prevent spoilage or imminent unsellability is justified, as is giving
    food to charities [V]. Agent markdowns on food therefore need a cost
    floor with a perishable exception.
  - antitrust (section 6) and GDPR if personal data is used (section 3).
- EU: the Commission has said dynamic pricing may breach the UCPD if the
  price changes after the payment process has started (EPRS briefing
  791529, Oct 2026) [V]. Translated to a store: never change the price of
  an article in an open transaction.

### 2.2 Consumer perception and the debate

- VZ Hamburg (2017): fears of "Preiserhöhung auf Knopfdruck", loss of
  price equality and transparency ("Flatterpreise") [V].
- vzbv (2016, then-chief): digital labels are the precondition for intraday
  changes; customers must not be disadvantaged [V, derstandard.at].
- US 2024-2026: Senators Warren and Casey wrote to Kroger (Aug 2024) about
  ESL plus AI pricing and possible income-based personalisation [V,
  winfuture.de 14.08.2024]. Seattle passed a grocery "surveillance pricing"
  ban (Fair Pricing and Transparency Act, 7-2 vote around 23.09.2026; open
  coupons and senior/veteran discounts remain allowed) [V, trendingtopics.eu
  24.09.2026]. Maryland signed a ban in April 2026 (in force 01.10.2026 per
  one source) [V, secondary]. New York's algorithmic pricing disclosure law
  (2025) requires disclosure when prices are set by algorithms using
  personal data [V, secondary]; the exact label text is [A]. A US union
  survey reported 67-68 % worry about surveillance pricing (campaign
  survey, use with care) [V, secondary].
- Evidence: a 2025 working paper (Stamatopoulos, Sanders, Bray; one US
  grocery chain over five years) found temporary price increases on about
  0.005 % of products per day before ESL, rising by only 0.0006 percentage
  points after ESL, with changes more often in the shopper's favour [V:
  UCSD Rady news 22.07.2025, AP coverage 06/2025]. Whole Foods, Tesco and
  Sainsbury's publicly ruled out surge pricing via ESL [V, AP].
- Interpretation for the booth [A]: visitors will arrive with "AI + ESL =
  surge pricing" in mind. The demo should pre-empt this: **the agent can
  only lower prices**, shows *why*, and a human approves.

### 2.3 EU policy 2025-2026

- Fitness Check of EU consumer law: published 03.10.2024 (SWD(2024)230);
  core directives still relevant but only partly effective online; consumer
  harm estimated at 7.9 billion EUR per year [V, EPRS].
- DFA consultation July-October 2025; industry asked for a "pause and
  reset" (March 2026); EP asked in July 2026 to consider banning dynamic
  pricing at live sports and cultural events [V, EPRS].
- **DFA proposal expected 11.11.2026** (IAPP, 22.10.2026) [V]; EPRS:
  "fourth quarter of 2026", "mid-November" [V]. Leak reported 09.11.2026: a
  71-page draft *Regulation* repealing and replacing the UCPD while keeping
  its core, restricting personalised pricing that exploits vulnerabilities,
  with Commission fines up to 6 % of worldwide turnover via a CPC reform
  [V, newsletter.digitalfairnessact.com]. Further reported details
  ("Article 13" ban on profiling-based personalised pricing harmful to
  minors or vulnerable consumers; dynamic pricing must disclose the number
  of items available at the advertised price) come only from a commercial
  blog summary [A].
- Because the UCPD covers offline commercial practices too, a DFA
  Regulation replacing it would reach physical stores as well [A,
  inference]; the EPRS briefing focuses on digital environments [V].
- **Action item for the team:** re-check the actual DFA text after
  11.11.2026 and before the EuroCIS talk track is frozen.

---

## 3. Personalised pricing, loyalty and GDPR

### 3.1 Consumer-law information duty: online only

- Art. 246a § 1 Abs. 1 S. 1 Nr. 6 EGBGB (implementing Art. 6(1)(ea) CRD):
  "gegebenenfalls den Hinweis, dass der Preis auf der Grundlage einer
  automatisierten Entscheidungsfindung personalisiert wurde"; the duty
  arises via § 312d Abs. 1 BGB, i.e. **only for distance contracts and
  off-premises contracts** [V: gesetze-im-internet.de].
- Art. 246 EGBGB (in-store contracts) has no such item, and Abs. 2 exempts
  everyday transactions performed immediately ("Geschäfte des täglichen
  Lebens") [V: dejure.org].
- So a store has **no statutory duty** to disclose in-store personalisation
  [V/A], but app-based or e-commerce channels do. Transparency is still best
  practice and is what vzbv demands: information *at the moment the price
  is perceived*, including parameters and weights, plus a choice of a
  non-personalised price (vzbv position paper "Verbraucherrecht digital
  fair", 23.10.2025, chapter I.3) [V].

### 3.2 Why "uniform shelf price + personalised coupons" is best practice

- PAngV/PID: personalised vouchers on purchase are outside Art. 6a; member
  campaigns open to most customers are inside (guidance 2.3) [V].
- vzbv (23.10.2025): "Personalisierte Preiserhöhungen sind grundsätzlich zu
  untersagen"; data revealing willingness to pay, including personal or
  situational distress, must not be used for personalised price increases;
  no emotion recognition or mood analysis for price personalisation;
  burden of proof on the trader [V, read from the PDF].
- BEUC (Dec 2025 position, March 2026 checklist): prevent pricing based on
  tracking and/or profiling, *except for price reductions* [V, secondary
  summary of the BEUC checklist].
- Market practice: Billa, Spar, Lidl apps give personalised discounts and
  coupons while shelf prices are equal for all [V, trendingtopics.eu].
- AGG § 19 Abs. 1 Nr. 1: no discrimination by race/ethnic origin, sex,
  religion, disability, age or sexual identity in mass transactions
  ("Massengeschäfte", typically concluded "ohne Ansehen der Person") [V];
  § 20 Abs. 1 Nr. 3 allows "besondere Vorteile" (e.g. senior discounts)
  where there is no interest in equal treatment, but not for race/ethnic
  origin [V]. So persona attributes such as age or sex must never drive a
  price; at most an explicit, generally offered advantage.
- Conclusion for the demo: **the shelf/ESL price is per article and store,
  never per person; personalisation happens only as reductions (voucher at
  checkout for the next visit, or a coupon applied at the till), opt-in,
  explained.**

### 3.3 GDPR for loyalty profiling

- Legal basis: DSK Orientierungshilfe Direktwerbung (Feb 2022), 1.3.2 b):
  automated selection to build detailed profiles, behaviour predictions or
  analyses that produce additional insight is profiling that "nicht mehr auf
  Art. 6 Abs. 1 UAbs. 1 lit. f DSGVO gestützt werden kann" and needs prior
  consent; pointing to the Art. 21 objection right is not enough. Simple
  mailings to all customers or coarse segments (postcode) without extra
  insight can rely on legitimate interest (1.3.2 a) [V, read from the PDF].
- Art. 22 GDPR: decisions based solely on automated processing with legal
  or similarly significant effects are restricted; exceptions include
  explicit consent (Art. 22(2)(c)) with the right to human intervention
  (Art. 22(3)) [A, statute knowledge]. The Article 29 WP / EDPB guidelines
  (WP251rev.01) say differential pricing can have a significant effect if,
  e.g., "prohibitively high prices effectively bar" someone from goods [V,
  secondary quoting the guideline]. A one-off basket voucher is unlikely to
  reach that threshold [A].
- ECJ C-634/21 SCHUFA (07.12.2023): a score can itself be a "decision" if it
  plays a determining role [A, well-established, not re-fetched].
- ECJ C-203/22 Dun & Bradstreet Austria (27.02.2025): Art. 15(1)(h) requires
  a concrete, intelligible explanation of the procedure and principles
  actually applied; a formula alone is not enough [V, secondary]. The
  proposal card's "why" text and the inputs used are exactly that.
- Pseudonymous vs anonymous: ECJ C-413/23 P EDPS v SRB (04.09.2025):
  pseudonymised data remains personal for whoever holds the key but may
  not be personal for a recipient with no realistic means of
  re-identification [V, secondary].
- Data minimisation (Art. 5(1)(c)) and privacy by design (Art. 25) [A,
  statute].
- Employee data in the audit log: approver IDs are personal data of staff;
  in a German store a system able to monitor employee behaviour or
  performance triggers works council co-determination (§ 87 Abs. 1 Nr. 6
  BetrVG) [A, statute knowledge]. Keep approver IDs as role pseudonyms in
  the demo and never build approver performance analytics.

### 3.4 Data minimisation for a trade-show demo with visitors

Recommended design [A, derived]:

- **No personal data at all in the pipeline.** Visitors pick a *persona
  card* (barcode) such as "Kaffee-Fan", "Bio-Familie", "Schnäppchenjäger",
  "Grillabend". The card is shared and reusable, not linked to a person, so
  the data is effectively anonymous; GEBIT supports `anonymous = true`
  loyalty memberships without `customer_id` (loyalty_datatype.proto:92-97)
  [V for the field].
- Never scan trade-fair badges, never ask for name, email or phone number
  in the demo flow. If leads are wanted, use the normal booth lead process
  with its own privacy notice, separate from the demo.
- Persona attributes allowed: preference tags and the current basket only.
  Forbidden: age, sex, family status, health or diet as health data,
  income or socio-economic proxies, location history.
- If a voucher is shown on the visitor's phone via QR code, use a static,
  cookie-free page; anything stored on the device needs consent under
  § 25 TDDDG unless strictly necessary [A, statute knowledge].
- Photos or video of visitors at the booth: signage and consent (GDPR, KUG)
  [A].
- Retention: purge event data after each fair day or after the fair; keep
  only aggregated counters for the talk track.
- A small privacy notice at the booth: "Demo mit fiktiven Personas. Es
  werden keine personenbezogenen Daten verarbeitet."

---

## 4. EU AI Act

### 4.1 Classification of a pricing/promotion agent

- High-risk Annex III lists biometrics, critical infrastructure, education,
  employment, access to essential services (incl. creditworthiness 5(b) and
  **risk assessment and pricing for life and health insurance 5(c)**), law
  enforcement, migration and justice [A for the list, well-established; V
  for 5(c) via multiple secondary sources]. Retail shelf pricing and
  promotions are **not** listed, so the agent is not high-risk [A].
- Caveat: using the same system to evaluate or monitor employees (e.g.
  approver performance) would move toward Annex III point 4 (employment)
  [A]. Avoid.
- **Art. 5 prohibitions (since 02.02.2025)**: manipulative or deceptive
  techniques that materially distort behaviour with significant harm
  (5(1)(a)); exploitation of vulnerabilities due to age, disability or a
  specific social or economic situation (5(1)(b)) [V, Commission Art. 5
  guidelines of 04.02.2025 as summarised by Covington and others]. The
  guidelines' own example: AI-enabled differential pricing in insurance that
  exploits socio-economic situations to charge lower-income consumers more
  [V, secondary]. Guardrail: no vulnerability-based features, no false
  urgency.

### 4.2 Transparency (Art. 50)

- Art. 50(1): providers must design AI systems that interact directly with
  natural persons so that people are informed they are dealing with AI,
  unless obvious; Art. 50(2): machine-readable marking of synthetic content
  by providers of generative systems; Art. 50(4): deployers' duties for
  deepfakes and AI-generated text published to inform the public [A for the
  wording, well-established].
- **Applies since 02.08.2026, not postponed.** Only relief: providers of
  systems placed on the market before 02.08.2026 have until 02.12.2026 for
  the Art. 50(2) marking (new Art. 111(4)) [V: artificialintelligenceact.eu
  Digital Omnibus explorer, usercentrics, technology.org]. Commission
  Art. 50 guidelines reportedly published 20.07.2026 [V, single secondary].
- For the booth: if visitors can ask the agent questions (chat), say so
  ("Sie sprechen mit einem KI-Agenten"). Label every proposal "KI-Vorschlag"
  even where not strictly required.

### 4.3 Human oversight

- Art. 14 human oversight and Art. 26 deployer duties bind only high-risk
  systems [A, well-established]. The approval step is therefore voluntary
  good practice, and GDPR Art. 22(3) (right to human intervention) and the
  "AI does not decide alone" message justify it. Present it as "Human in the
  loop by design, not because the law forces us" [A, messaging].
- Art. 4 AI literacy (since 02.02.2025): the Omnibus restated it as a duty
  to take measures supporting AI literacy proportionate to staff and
  context; Commission and Member States support SMEs [V,
  artificialintelligenceact.eu]. Booth staff and approvers should have a
  short briefing.

### 4.4 Timeline 2024-2028 (as amended)

- 01.08.2024: AI Act in force [A].
- 02.02.2025: Art. 5 prohibitions, Art. 4 AI literacy [A/V].
- 02.08.2025: GPAI obligations, governance, penalties [A].
- 08.07.2026: Digital Omnibus on AI adopted as Reg. (EU) 2026/1744
  (EP vote 16.06.2026, Council 29.06.2026 per secondary sources); OJ
  24.07.2026; in force 27.07.2026 [V].
- 29.07.2026: German KI-MIG in force (BGBl. 2026 I Nr. 223); Bundesnetzagentur
  as central market surveillance and complaints authority, sector
  regulators keep their remit [V, several secondary sources plus
  gesetze-im-internet listing].
- 02.08.2026: Art. 50 transparency and most remaining provisions apply [V].
- 02.12.2026: end of Art. 50(2) grace period for legacy systems; new Art. 5
  prohibitions added by the Omnibus (non-consensual intimate images, CSAM)
  apply [V].
- 16-18.02.2027: EuroCIS (everything above already applicable).
- 02.12.2027: Annex III high-risk obligations (was 02.08.2026) [V].
- 02.08.2028: Annex I (product-embedded) high-risk obligations [V].

---

## 5. KassenSichV / TSE: what is sensitive when simulating a POS at a fair

### 5.1 Legal frame

- § 146a Abs. 1 AO with KassenSichV: electronic recording systems must be
  protected by a BSI-certified technical security device (TSE) [V,
  secondary]. Receipt issuing duty (§ 146a Abs. 2 AO) for each recorded
  business transaction [V, secondary: Belegausgabepflicht per
  "aufzeichnungspflichtigen Geschäftsvorfall"].
- Registration duty (§ 146a Abs. 4 AO): via "Mein ELSTER" since 01.01.2025;
  systems acquired before 01.07.2025 had to be reported by 31.07.2025; new
  systems and decommissionings within one month; rented or leased tills
  count as acquired [V: BMF letter 28.06.2024 via IHK, Bayern
  Finanzamt PDF, PwC].
- DSFinV-K defines the export and receipt types. A training receipt maps to
  `BON_TYP = AVTraining` (fiskaltrust German reference: training flag
  "overrides BON_TYP=AVTraining") [V, secondary]. Whether a training
  booking on a productive till must still be signed by the TSE is [A]
  (vendor behaviour differs; fiskaly integrations reportedly do not report
  training transactions [V, secondary]).
- § 379 AO (Steuergefährdung): issuing factually incorrect receipts or not
  properly protecting a system is an administrative offence [A, statute
  knowledge, not re-fetched].
- Price changes themselves have no KassenSichV dimension; but every
  discount or override in a real sale ends up in the TSE-protected record
  (`ApplyPercentageArticlePositionDiscount`, `OverrideArticlePositionPrice`
  exist in the GEBIT API) [V for the commands; A for the fiscal mapping].

### 5.2 What is legally sensitive at the booth [A, derived]

1. **Real money or goods changing hands.** If anything is actually sold
   (even coffee for coins), that is a business transaction requiring a
   properly fiscalised, registered POS with a productive TSE and receipts.
   Keep the demo strictly free and simulated.
2. **Using a productive TSE** registered to a real store/tax number for
   demo transactions would pollute that taxpayer's fiscal journal and
   DSFinV-K export. Use GEBIT's TSE simulator (already in their sample) or
   a vendor sandbox.
3. **Receipt look-alikes.** A printed receipt with QR code, TSE serial,
   signature counter and a real company's VAT ID looks like a genuine
   fiscal receipt and could be misused as proof of purchase. Mark every
   demo receipt "DEMO / Trainingsbeleg - kein Kassenbeleg i.S.d. § 146a
   AO", use placeholder VAT ID and test location (GEBIT already uses
   `DE123456789`, `Root.DE.999.101.01`), and prefer on-screen receipts.
4. **Vouchers.** A voucher with real monetary value redeemable at a real
   store would bring voucher VAT rules (single/multi-purpose vouchers, § 3
   Abs. 13-15 UStG) and fiscal recording into play [A]. Demo vouchers must
   say "ohne Geldwert, nicht einlösbar" (or be redeemable only for a free
   booth giveaway).
5. **Employee master data** on receipts (`employeeId`): use demo IDs only.
6. In GEBIT's demo lab later: ask whether the till runs in training mode
   (BON_TYP `AVTraining`) and which TSE (simulator vs cloud test TSE) is
   attached; the purchase API protos have no training field (grep), so it
   is a till or fiscal-service setting [A].

---

## 6. Antitrust and algorithmic pricing (brief)

- Unilateral pricing using one's own sales, stock, cost and promo data and
  publicly observable competitor prices is generally lawful [A,
  well-established].
- Risks:
  - **Hub-and-spoke via a shared tool**: competitors using the same pricing
    tool or platform that pools their non-public data or aligns their
    prices. ECJ Eturas C-74/14 (21.01.2016): travel agencies using a common
    booking system that capped discounts; awareness of the system message
    can be presumed but rebutted [A for date; V for the case's role via
    secondary]. The 2023 EU Horizontal Guidelines (OJ 21.07.2023) treat a
    shared algorithmic pricing tool as a possible hub-and-spoke information
    exchange; firms can be liable for anti-competitive effects of their
    algorithms; a tool provider can be liable if it could reasonably
    foresee the conduct [V, secondary: VBB, Chambers; paragraph numbers
    unverified].
  - **Signalling** future prices publicly.
  - **Vertical**: suppliers may fund promotions but may not fix resale
    prices (RPM; Art. 4(a) VBER 2022/720, § 1 GWB) [A].
  - § 20 Abs. 3 GWB below-cost food sales (section 2.1) [V].
- For GEBIT (platform vendor for many retailers): pricing models, features
  and data must be tenant-isolated; no cross-retailer price data; document
  it. That is a credible selling point at EuroCIS [A].

---

## 7. Machine-checkable guardrails (enforced by the workflow)

### 7.1 Where they run (SAM workflow pattern)

- Event-mesh entrypoint (POS events, stock, promo, loyalty) -> workflow.
- **Agent node** (LLM, e.g. `fast` tier) produces a *structured proposal*
  only: `{article_id, store_id, proposal_type: MARKDOWN|PROMO|VOUCHER,
  new_price, valid_from, valid_to, reason_code, rationale_text,
  inputs_used[]}`. It never calls the price service.
- **Tool node "guardrail_check"** (deterministic MCP tool, no LLM;
  < 1.5 s per the BSG measurements) returns
  `{verdict: AUTO_OK|NEEDS_APPROVAL|NEEDS_4_EYES|REJECT|REWRITE,
  rule_results[], computed: {ref30, discount_pct_display, unit_price,
  margin_pct, stock_cover_h}, label_preview}`.
- **Switch node** on `verdict` (declare the field in
  `output_schema_override`, otherwise the switch silently falls through,
  per lab notes) -> approval notification (tablet) or reject card.
- After approval: **tool node "commit_price_change"** re-runs all checks
  with fresh data (prices or stock may have moved), then emits the price
  change event to the article master data service (GEBIT, format TBD), the
  ESL update, and the audit record. Only this tool holds the write path.

### 7.2 Guardrail catalogue

Default parameter values are proposals for the demo; GEBIT/retailer would
set real values.

**A. Price indication (PAngV, UWG)**

- **A01 REF_PRICE_30D** - Store every consumer-applied price per article and
  store with `valid_from/valid_to` (regular and promo). `ref30 = min(price
  applied in [t_apply - 30 d, t_apply))`. Block any reduction announcement
  if `ref30` is unknown. Legal: § 11 Abs. 1 PAngV, Art. 6a PID, C-330/23.
- **A02 DISCOUNT_BASE** - Any displayed %, strike-through, "statt", "Aktion",
  "Preis-Highlight", "Knüller" is computed against `ref30`; display
  `floor()` of the percentage; the strike-through price equals `ref30`.
  Legal: C-330/23, OLG Karlsruhe 14 U 83/25, OLG Köln 6 UKl 4/25.
- **A03 NO_FAKE_REDUCTION** - If `new_price >= ref30`: `advertise_reduction =
  false`; result is either a silent price change (no reduction wording) or
  REJECT. Monitor shows the reason.
- **A04 REF_ALWAYS_RENDERED** - If `advertise_reduction`, the ESL template
  and monitor must render "Niedrigster Preis der letzten 30 Tage: X EUR" in
  the same visual block and legible size (no footnote). Legal: BGH
  I ZR 183/24, § 1 Abs. 3 PAngV.
- **A05 PERISHABLE_EXCEPTION** - Exemption from A01-A04 only if
  `article.perishable = true` AND `days_to_best_before <= 2` (parameter)
  AND label text "Reduziert wegen kurzer Haltbarkeit (MHD dd.mm.)". Legal:
  § 11 Abs. 4 Nr. 2 PAngV, OLG Nürnberg 3 U 2376/24, guidance 4.1.
- **A06 GRADUAL_CAMPAIGN** - A campaign may keep its first `ref30` across
  steps only if each step is lower than the previous and no price increase
  happened in between; otherwise recompute. Legal: § 11 Abs. 2 PAngV,
  guidance 4.3.
- **A07 SUCCESSIVE_PROMOS** - After a promo ends, the promo price stays in
  the history; a new promo within 30 days uses it as `ref30` (this usually
  shrinks the displayable percentage, which the monitor should show).
- **A08 UNIT_PRICE** - Recompute Grundpreis for every new price (1 kg, 1 l,
  1 m, 1 m², 1 m³; loose goods 1 kg/100 g, 1 l/100 ml); block if
  `net_quantity` or unit is missing. Legal: §§ 4, 5 PAngV.
- **A09 DEPOSIT_SEPARATE** - Deposit never included in total price or % and
  shown separately. Legal: § 7 PAngV, C-543/21.
- **A10 NO_UVP_COMPARISON** - Templates have no UVP strike-through.
  Rationale: OLG Düsseldorf 20 U 43/25 vs OLG Köln 6 U 92/25, BGH pending.
- **A11 MEMBER_PROMO_PUBLIC** - Promotions for "all members" or open codes are
  treated as public reductions (A01-A04 apply), and the label shows the
  normal price and Grundpreis for non-members too. Legal: guidance 2.3,
  Lidl lamb flyer case.
- **A12 VALIDITY_TRUTH** - Any "nur heute"/"bis 18 Uhr"/countdown must match
  `valid_to`, which is enforced; the same "last chance" claim must not be
  re-run for the same article the same day. Legal: UWG blacklist (false
  limited-time claim) [A annex number].
- **A13 STOCK_COVERAGE** - Advertised promotions require `stock_on_hand >=
  forecast_demand(valid_from..valid_to)` (or a stated quantity limit).
  Legal: UWG blacklist bait offers [A], reported DFA draft [A].
- **A14 PRICE_CONSISTENCY** - Invariant: for each article and store at any
  time t, `esl_price(t) == pos_price(t)`. Activation sequence: send ESL
  update with `effective_at`; activate POS price only after ESL ack
  (timeout e.g. 10 s) or roll back; drift monitor alarms if a mismatch
  exists longer than e.g. 5 s. Legal: §§ 1 Abs. 3, 10 PAngV; VZ Hamburg
  findings.
- **A15 OPEN_BASKET_PROTECTION** - A price change never increases the price
  of a position already in an open transaction; reductions apply from the
  next scan (as the showcase promises). Legal/guidance: EPRS (no change
  after payment started) [V]; GEBIT `price_source` semantics [A].

**B. Dynamic pricing hygiene**

- **B01 MARKDOWN_ONLY** - The agent may propose reductions and the end of a
  promotion (back to the regular price at the announced `valid_to`) only;
  any proposal above the regular price is REJECT.
- **B02 NO_SURGE_ESSENTIALS** - Block price increases for articles flagged
  `essential` when the trigger is demand spike, stock-out risk or an
  external shortage signal. Legal: § 4 WiStG.
- **B03 MAX_MARKDOWN** - `discount_vs_regular <= 30 %` -> NEEDS_APPROVAL;
  `30-50 %` -> NEEDS_4_EYES (role `store_manager`); `> 50 %` -> REJECT,
  except perishable clearance (A05) up to 70 %.
- **B04 MARGIN_FLOOR** - `new_net_price >= unit_cost_net * (1 + 0.05)`;
  below -> NEEDS_4_EYES, unless perishable clearance.
- **B05 BELOW_COST_FOOD** - For category `food`: `new_price <
  einstandspreis` allowed only with reason `SPOILAGE_RISK` (A05 data).
  Legal: § 20 Abs. 3 GWB (applies to large retailers; enforce always).
- **B06 CHANGE_FREQUENCY** - Max 2 price changes per article per store per
  day, min hold time 60 min (demo: 10 min). Rationale: "Flatterpreise"
  concern (VZ Hamburg), customer trust, ESL battery.
- **B07 NO_INCREASE_OPENING_HOURS** - No price increase while the store is
  open except the scheduled end of an announced promotion.
- **B08 UNIFORM_SHELF_PRICE** - Exactly one active shelf price per article
  and store; the ESL API takes no customer parameter.
- **B09 COOLDOWN_AFTER_REJECT** - Same article and reason not re-proposed for
  30 min after a human rejection (avoids nagging the approver).

**C. Personalisation and data protection**

- **C01 NO_PERSONALISED_SHELF_PRICE** - Price features must not include any
  customer identifier; personalisation only via vouchers/coupons that
  reduce. Rationale: vzbv, BEUC, market practice, DFA direction.
- **C02 VOUCHER_CATALOGUE** - Vouchers only from pre-approved templates
  (e.g. max 10 % or max 2 EUR, min basket 10 EUR, valid 14 days, explicit
  exclusions); in-catalogue -> AUTO_OK, out-of-catalogue -> NEEDS_APPROVAL.
  Conditions printed on the voucher. Rationale: guidance 2.3 (outside
  Art. 6a, but UCPD transparency).
- **C03 VOUCHER_FINALITY** - Issue the voucher only on
  `PurchaseTransactionClosed`; never on `PurchaseTransactionCancelled`;
  idempotent per `receiptId`.
- **C04 FEATURE_ALLOWLIST** - Allowed inputs: current basket lines,
  quantities, totals, active promos, persona preference tags, aggregated
  sales and stock. Forbidden (validator rejects the proposal if referenced
  in `inputs_used`): age, sex, ethnicity, religion, disability, sexual
  identity, health, income or socio-economic proxies, precise location,
  emotion or mood signals. Legal: AGG § 19, AI Act Art. 5(1)(b), GDPR
  Art. 9, vzbv.
- **C05 CONSENT_GATE** - Profile-based personalisation (history across
  visits) only if `membership.anonymous == false` AND `consent_profiling ==
  true`; otherwise basket-only, nothing stored. Legal: DSK OH Werbung 2022
  1.3.2 b), GDPR Art. 6(1)(a).
- **C06 NO_PERSONAL_DATA_INGEST** - Payload validator on the entrypoint:
  `CustomerData.customer_name`, addresses, emails, phone numbers must be
  empty; regex scan for email/phone/IBAN patterns -> drop event and alert.
- **C07 EXPLANATION_STORED** - Every proposal and voucher stores a
  human-readable reason and the list of inputs used, displayable on the
  monitor. Legal: GDPR Art. 13-15, C-203/22.
- **C08 RETENTION** - Demo raw events purged nightly; production: price
  history >= 30 days rolling plus dispute buffer (proposal: 12 months) [A].

**D. AI governance and human oversight**

- **D01 LLM_NO_WRITE** - Only the `commit_price_change` tool can emit price
  events; it requires a signed approval token bound to `proposal_id` and
  hash of the approved payload.
- **D02 APPROVAL_REQUIRED** - Every shelf price change needs a human click in
  the demo; approval cards expire after N minutes (expiry = reject, never
  auto-approve).
- **D03 RECHECK_AT_COMMIT** - All A/B/C rules run again at commit.
- **D04 AI_LABEL** - Every proposal is labelled "KI-Vorschlag (Modell:
  fast)", every executed change "freigegeben von: Rolle Filialleitung".
  Any chat with visitors starts with an AI disclosure. Legal: AI Act Art. 50
  (spirit and, for chat, letter).
- **D05 KILL_SWITCH** - One tap: pause the agent and revert all AI-originated
  prices to regular prices (with ESL + POS consistency, A14).
- **D06 AUDIT_TRAIL** - Append-only record per proposal: triggering event
  IDs (Solace topic + message id), agent output, guardrail results with
  rule versions, approver role pseudonym and timestamp, command sent,
  ESL ack, POS effective time, first receipt using the new price.
- **D07 NO_EMPLOYEE_SCORING** - No analytics on individual approvers. Legal:
  BetrVG § 87 Abs. 1 Nr. 6 [A], AI Act Annex III point 4 [A].
- **D08 NO_DARK_PATTERNS** - No fake scarcity, no fake countdowns, no
  "nur noch 2 Stück" unless true (stock-backed). Legal: UWG, AI Act
  Art. 5(1)(a).

**E. Fiscal and demo integrity**

- **E01 TRAINING_OR_SIMULATOR** - Demo tills only with TSE simulator or test
  TSE; if available, `BON_TYP = AVTraining`.
- **E02 RECEIPT_WATERMARK** - All receipts (screen or print) carry "DEMO -
  kein Kassenbeleg"; placeholder VAT ID and test location.
- **E03 NO_REAL_PAYMENT** - Payment steps simulated; no card terminal in live
  mode at the booth.
- **E04 VOUCHER_NO_CASH_VALUE** - "Demo-Gutschein ohne Geldwert".
- **E05 DEMO_BANNER** - Monitor and tablet show "Simulation, fiktive Daten".

**F. Antitrust**

- **F01 OWN_DATA_ONLY** - Inputs: own sales, stock, cost, promotions, public
  competitor prices; no non-public competitor data; models and features per
  retailer tenant.
- **F02 NO_EXTERNAL_SIGNALLING** - The agent never publishes future price
  intentions outside the retailer.
- **F03 SUPPLIER_INDEPENDENCE** - Supplier-funded promo parameters are inputs,
  never binding resale prices.

### 7.3 Example guardrail configuration (proposal)

```yaml
guardrails:
  version: "2027-02-eurocis-1"
  reference_price:
    window_days: 30
    display_rounding: floor_percent
    require_history: true
  perishable_exception:
    max_days_to_best_before: 2
    label_text: "Reduziert wegen kurzer Haltbarkeit (MHD {bbd})"
  markdown:
    auto_proposal_max_pct: 30
    four_eyes_max_pct: 50
    perishable_max_pct: 70
    margin_floor_pct: 5
    food_below_cost_requires: SPOILAGE_RISK
  frequency:
    max_changes_per_article_per_day: 2
    min_hold_minutes: 10        # demo; production 60+
  direction:
    allow_increase_above_regular: false
    allow_increase_during_opening_hours: false
  consistency:
    esl_ack_timeout_s: 10
    max_mismatch_s: 5
    protect_open_baskets: true
  personalisation:
    shelf_price_personalised: false
    voucher_templates: [NEXT_VISIT_10PCT, COFFEE_2EUR, BIO_5PCT]
    forbidden_features: [age, sex, ethnicity, religion, disability,
                         sexual_identity, health, income, location, emotion]
    profile_requires: {anonymous: false, consent_profiling: true}
  approval:
    required_for: [MARKDOWN, PROMO]
    auto_ok_for: [VOUCHER_IN_CATALOGUE]
    card_expiry_minutes: 5
  fiscal:
    receipt_watermark: "DEMO - kein Kassenbeleg"
    bon_typ: AVTraining
```

### 7.4 Data the guardrail tool needs (demo data stores)

- `price_history(article_id, store_id, price_gross, valid_from, valid_to,
  source: REGULAR|PROMO|MARKDOWN|PERISHABLE, announced_as_reduction bool)`
  seeded with >= 35 days for every demo article (including one article
  whose 30-day low is below the "regular" price, to trigger A03 live).
- `article(article_id, regular_price, unit_cost_net, einstandspreis,
  net_quantity, unit, deposit, category, essential bool, perishable bool,
  best_before)`.
- `stock(article_id, store_id, on_hand, forecast_per_hour)`.
- `voucher_template(...)`, `guardrail_decision(...)`, `audit_event(...)`.
- Postgres on the lab host (no pgvector needed for this).

### 7.5 Signals to request from GEBIT for the live swap

- Price-change event to the article master data service: does it carry
  `reference_price_30d`, `announced_as_reduction`, `reason_code`
  (perishable), `valid_from/valid_to`, `approved_by`, `proposal_id`? If
  not, keep them in the guardrail service and pass a correlation ID.
- Does GEBIT's price service already maintain a 30-day lowest price per
  article (most German retailers had to build this in 2022)? If yes, the
  guardrail should *read* it from GEBIT rather than compute it.
- ESL integration: which vendor/protocol, ack semantics, latency.
- Semantics of `price_source = freezePrice`, and whether a master-data
  price change affects open baskets.
- Training mode and TSE setup in the demo lab.

---

## 8. "Compliance as a feature" moments on the monitor

Each moment is short (2-5 s on screen) and fits the 14-20 s event ->
proposal timing measured on the BSG demo.

1. **The 30-day check (the "aha")** - The agent proposes "Kaffee 500 g:
   -25 % statt 5.99". The guardrail panel animates: "Niedrigster Preis
   letzte 30 Tage: 4.99 (Aktion vom 21.01.)" -> rewrites to "-16 %" against
   4.99, or, if the new price is not below 4.99, "Keine Rabattwerbung
   zulässig: stille Preisanpassung". Caption: "§ 11 PAngV / EuGH Aldi Süd -
   eingebaut, nicht nachgeprüft."
2. **The legally complete ESL preview** - Tablet card shows the ESL mock:
   new price, Grundpreis per kg, "Niedrigster Preis 30 Tage", validity "bis
   18:00", deposit separate; green ticks per rule (A01-A14).
3. **Perishable done right** - Yogurt with best-before tomorrow: label says
   "Reduziert wegen kurzer Haltbarkeit"; caption explains why the 30-day
   price is not needed here and why the reason must be visible.
4. **The blocked proposal** - Demand spike on water (simulated heat wave):
   the agent (or a deliberately "greedy" test prompt) proposes +20 %; the
   guardrail shows REJECT "Preiserhöhung bei Grundbedarf in Mangellage
   (§ 4 WiStG) / keine Erhöhung während Öffnungszeiten". Message: "Die KI
   entscheidet nicht allein - und nicht alles."
5. **One click, one truth** - After approval: "ESL bestätigt 12:04:31.2 ·
   Kasse aktiv 12:04:31.4 · Abweichung 0" then the next visitor scan shows
   the new price on the receipt.
6. **Voucher at checkout, no profile** - On `PurchaseTransactionClosed`: "Ihr
   Gutschein für den nächsten Besuch: 10 % auf Bio-Sortiment. Grundlage:
   nur dieser Warenkorb (anonyme Persona). Kein Profil gespeichert. Der
   Regalpreis bleibt für alle gleich."
7. **Second markdown the same day** - The promo from the morning lowers the
   reference: "Neuer Referenzpreis 3.49 (heutige Aktion) - zulässige
   Rabattangabe nur noch -8 %". Shows the system remembers what consumers
   actually paid.
8. **Audit trail drill-down** - Click a price: chain of Solace event IDs ->
   agent proposal (with "KI-Vorschlag" label) -> 14 guardrail results ->
   approver role -> commit -> ESL ack -> first receipt. "Prüfbar in
   Sekunden."
9. **Kill switch** - "Alle KI-Preise zurücksetzen" reverts consistently.
10. **DFA-ready slide/tile** - "EU Digital Fairness Act (Vorschlag
    11.11.2026): personalisierte Preise unter Druck - unser Design:
    personalisiert wird nur der Rabatt, nie der Regalpreis."

---

## 9. Open points and risks

- DFA text: verify after 11.11.2026; adjust talk track (personalised
  pricing, dynamic-pricing disclosures, reference pricing).
- BGH on UVP comparisons pending; avoid UVP in the demo.
- BGH I ZR 198/25 (Lidl Plus "paying with data") pending; if the BGH treats
  data as consideration, loyalty "free" claims change. Avoid "kostenlos"
  claims for any loyalty element in the demo.
- KassenSichV handling of training bookings is vendor-specific; confirm with
  GEBIT.
- Whether a B2B fair demo triggers PAngV at all is irrelevant for
  credibility; behave as production.
- AI Act Art. 50 guidelines (July 2026) not read in this session; if the
  booth offers a chat, check them.

---

## 10. Sources (all accessed 2026-11-10)

Statutes:

- PAngV § 1, § 4, § 5, § 10, § 11, § 20: `https://www.gesetze-im-internet.de/pangv_2022/`
- WiStG 1954 § 3, § 4: `https://www.gesetze-im-internet.de/wistrg_1954/__3.html`,
  `https://www.gesetze-im-internet.de/wistrg_1954/__4.html`
- UWG § 19: `https://www.gesetze-im-internet.de/uwg_2004/__19.html`
- EGBGB Art. 246a § 1: `https://www.gesetze-im-internet.de/bgbeg/art_246a__1.html`;
  Art. 246: `https://dejure.org/gesetze/EGBGB/246.html`
- AGG § 19, § 20: `https://www.gesetze-im-internet.de/agg/__19.html`,
  `https://www.gesetze-im-internet.de/agg/__20.html`
- GWB § 20: `https://www.gesetze-im-internet.de/gwb/__20.html`

EU guidance and policy:

- Commission Notice 2021/C 526/02 on Art. 6a PID (PDF read in full):
  `https://mpo.gov.cz/assets/en/consumer-protection/information-for-consumers/2023/9/European-Commission-guidelines-_2021_C-526_02_.pdf`
  (EUR-Lex: `https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:52021XC1229(06)`)
- EPRS briefing "Towards a digital fairness act" (Oct 2026):
  `https://eprs.europarl.europa.eu/contents/publications/EPRS/2026/10/EPRS_BRI(2026)791529.html`
- IAPP, 22.10.2026: `https://iapp.org/news/a/a-view-from-brussels-final-countdown-to-the-digital-fairness-act-has-started`
- DFA leak report, 09.11.2026: `https://newsletter.digitalfairnessact.com/p/contexte-publishes-leaked-draft-of-digital-fairness-act`
- BEUC checklist (March 2026): `https://www.beuc.eu/sites/default/files/publications/BEUC-X-2026-019_Checklist_Towards_the_Digital_Fairness_Act.pdf`
- Digital Omnibus on AI (Reg. (EU) 2026/1744): `https://artificialintelligenceact.eu/ai-act-explorer/digital-omnibus/`;
  `https://usercentrics.com/knowledge-hub/eu-ai-act-high-risk-delay-article-50-transparency-consent/`;
  `https://www.technology.org/2026/10/13/eu-ai-act-deadlines-after-the-digital-omnibus-what-applies-from-december-2026-to-august-2028/`
- Commission Art. 5 guidelines (summary): `https://www.insideprivacy.com/artificial-intelligence/european-commission-guidelines-on-prohibited-ai-practices-under-the-eu-artificial-intelligence-act/`
- KI-MIG: `https://www.gesetze-im-internet.de/ki-mig/KI-MIG.pdf`;
  `https://www.advisori.de/blog/ki-mig-ai-act-durchfuehrungsgesetz-unternehmen`

Case law and commentary:

- ECJ C-330/23 press: `https://curia.europa.eu/jcms/jcms/p1_4575171`;
  `https://www.beck-aktuell.de/daily/meldung/detail/eugh-c33023-aldi-sued-irrefuehrende-rabattwerbung`;
  `https://www.lg-duesseldorf.nrw.de/behoerde/presse/pressemitteilungen_2024/13-24_-urteil-im-verfahren-ueber-preisangabenverordnung.pdf`
- BGH I ZR 183/24: `https://www.ra-plutte.de/bgh-unzulaessige-werbung-mit-einer-preisermaessigung/`;
  `https://rewis.io/urteile/urteil/sqe-09-10-2025-i-zr-18324/`
- OLG Düsseldorf 20 U 43/25: `https://www.beck-aktuell.de/heute-im-recht/rechtsprechung/olg-duesseldorf-i20u4325-verbraucherschutz-aldi-sued-rabattwerbung-2025-12-19`
- Case-law aggregator (OLG Köln, Karlsruhe, Nürnberg 2025-2026, BGH I ZR 242/25):
  `https://www.omsels.info/die-verbote-oder-was-darf-ich-nicht/%C2%A7%C2%A7-5a-5b-uwg-informationspflichten/%C2%A7-5a-abs-1-uwg-wesentliche-informationspflichten/preisangabenverordnung-pangv/preisermaessigungen`
- Lidl Plus OLG Stuttgart / BGH I ZR 198/25: `https://www.vzbv.de/urteile/bezahlen-mit-daten-olg-stuttgart-Urteil-lidl`;
  `https://www.beck-aktuell.de/heute-im-recht/rechtsgeschehen/streit-lidl-app-kostenlos-irrefuehrung-bgh-revision-verbraucherzentrale-2025-10-07`
- Lidl app-only flyer price: `https://www.giga.de/tech/lidl-gibt-in-rabatt-streit-nach-und-passt-preise-an-nicht-nur-in-der-app--01JRD1BPM3EJ458NJZMWJ3QKE8`
- ECJ C-203/22: `https://cms.law/en/fra/news-information/cjeu-landmark-ruling-on-the-right-of-access-and-automated-decision-making`
- ECJ C-413/23 P: `https://www.cliffordchance.com/insights/resources/blogs/talking-tech/en/articles/2025/09/pseudonymized-data-after-edps-v-srb.html`
- WP251 pricing example (secondary): `https://wilmerhale.com/en/insights/blogs/wilmerhale-privacy-and-cybersecurity-law/the-article-29-working-party-releases-draft-guidelines-on-profiling-and-automated-decision-making-under-the-gdpr`
- Horizontal Guidelines 2023 algorithms (secondary): `https://chambers.com/articles/algorithmic-alignment-of-prices-the-eu-approach-towards-liability-13`

Consumer bodies and market:

- vzbv position paper 23.10.2025 (PDF read): `https://www.vzbv.de/sites/default/files/2025-10/25-10-23_vzbv_Positionspapier_Verbraucherrecht_digital_fair.pdf`
- DSK Orientierungshilfe Direktwerbung Feb 2022 (PDF read): `https://www.datenschutzkonferenz-online.de/media/oh/OH-Werbung_Februar%202022_final.pdf`
- VZ Hamburg on digital price tags: `https://www.vzhh.de/themen/lebensmittel-ernaehrung/einkaufsfalle-supermarkt/dynamic-pricing-digitale-preisschilder-flatterpreisen`
- VZ Niedersachsen shelf vs checkout: `https://www.verbraucherzentrale-niedersachsen.de/wissen/vertraege-reklamation/kundenrechte/regal-oder-kasse-welcher-preis-gilt-119926`
- UCSD ESL study: `https://rady.ucsd.edu/why/news/2025/07-22-new-research-debunks-fears-of-supermarket-surge-pricing-with-electronic-shelf-labels.html`
- Seattle ban: `https://www.trendingtopics.eu/seattle-bans-grocery-surveillance-pricing/`
- Kroger letter: `https://winfuture.de/news,144514.html`

Fiscal:

- Mitteilungspflicht: `https://www.ihk.de/magdeburg/recht/allgemeine-rechtsauskuenfte-1/wirtschaft-und-recht/elektronische-meldung-von-kassen-systemen--6197104`;
  `https://finanzamt.bayern.de/Informationen/Steuerinfos/Weitere_Themen/Elektronische_Kassensysteme/2024-06-28-mitteilungsverpflichtung-nach-AO.pdf`
- fiskaltrust receipt cases (AVTraining): `https://docs.fiskaltrust.eu/docs/poscreators/middleware-doc/germany/reference-tables/ftreceiptcase`

Local files (GEBIT, untrusted data, read only):

- `.../scratchpad/gebit/simpleSale.json` lines 28, 36, 52, 56, 125, 179-317
- `.../scratchpad/gebit/purchase/de/gebit/rp/purchase/purchase/v2/datatype/loyalty_datatype.proto` lines 73-124
- `.../scratchpad/gebit/purchase/de/gebit/rp/purchase/purchase/v2/command/loyalty_command.proto` lines 25, 115
- `.../scratchpad/gebit/purchase/de/gebit/rp/purchase/purchase/v2/command/basket_command.proto` lines 282, 303
- `.../scratchpad/gebit/receipt/de/gebit/rp/receipt/receipt/v2/datatype/basket_datatype.proto` lines 268-274
