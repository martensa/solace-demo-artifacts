# Market and partner research: EuroCIS 2027 showcase "Preis- und Aktionsagent mit Freigabe"

Track: market and partner research (web research, read-only).
Date of research: 2026-11-10. EuroCIS 2027 opens 2027-02-16, i.e. 98 days
(14 weeks) from today.

Conventions used in this report:

- **VERIFIED (page)**: the cited page was fetched and the statement was read
  on it (WebFetch, 2026-11-10).
- **VERIFIED (snippet)**: the statement comes from a search-engine result
  snippet for the cited URL; the page itself was not (or could not be) read in
  full. Treat as good but not airtight.
- **VERIFIED (local)**: read from a local file (file:line).
- **ASSUMPTION**: my inference or estimate; not stated by a source.
- Vendor figures are vendor claims even when VERIFIED (they are verified as
  "the vendor says so", not as independent benchmarks).

No personal names or user details were used in any web search.

---

## 0. Executive summary

1. **EuroCIS 2027** runs 16-18 Feb 2027 at Messe Duesseldorf, motto
   "LEADING. BIGGER. AHEAD.", focus AI, data, checkout, payment, security,
   connected stores. The last standalone edition (2025) was a record: 14,471
   trade visitors from 95-97 countries, ~500 exhibitors from 37 countries,
   54 % of visitors with decision-making competence, 44 % from retail.
   In 2026 EuroCIS was not standalone; it ran inside EuroShop 2026 (4 of 14
   halls; EuroShop total 81,000+ visitors, 1,840 exhibitors).
2. **Dominant themes 2025/2026**: AI everywhere (generative AI moving into
   pricing, forecasting, inventory; first "agentic" framings in 2026),
   self-checkout / smart carts / computer vision for loss prevention, ESL
   evolving from price display to store platform (picking, navigation,
   cameras, retail media), and AI price optimisation tied to ESL execution
   (SOLUM + Competera, Vusion + GK AIR at L&T, Hanshow + Too Good To Go).
3. **GEBIT Solutions** (Berlin, founded 1991, ~35 years) is a POS / retail
   platform vendor whose public references include ALDI SUED, Kaufland (7
   countries), dm-drogerie markt, SPAR (SPAR ICS: 10,000 checkouts in 4
   countries), DEICHMANN, OBI; claims 110,000+ POS systems in 32+ countries.
   GEBIT lists EuroCIS 2027 on its own events page and owns a trade-fair
   attraction, the "Bonshooter" (arcade, 4 screens, 2 handheld scanners,
   60-second scan challenge) - a ready-made source of "visitor scans".
4. **GEBIT and Solace are publicly partnered**: Solace is on GEBIT's
   partner page; GEBIT LinkedIn posts (2026-10-08) state GEBIT already uses
   Solace Event Mesh for real-time retail data integration and is adding
   Solace Agent Mesh on the same foundation. GEBIT also took part in Solace
   Connect Frankfurt 2026. No public evidence of Kafka at GEBIT was found.
5. **Shared references** make the partner story credible: dm (GEBIT POS +
   Solace Event Mesh, 100 million events/day, ~10 ms latency), Schwarz Group
   (Kaufland = GEBIT POS; Schwarz on Solace), EDEKA (Solace event mesh to
   6,000+ stores; EDEKA + GEBOS highly commended at RTIH Awards 2026).
6. **ESL is mainstream in German grocery** (EHI 2025: 91 % of food-retail
   respondents use digital price labelling, but mostly only for price
   display). Lidl (all 3,250 German stores, F&V + promo areas), ALDI SUED
   (~2,000 German stores, Hanshow, ~25 M labels worldwide), Netto, Kaufland
   (F&V and bakery in all German stores). Vusion's cloud base exceeded 375 M
   ESLs at end 2025. Intraday markdowns are practiced in Europe (Albert Heijn:
   sales checked every 15 min, up to 4 cuts/day/item; REMA 1000: up to 100
   price changes/day), while surge pricing is publicly avoided.
7. **AI pricing vendors are going "agentic"** (Revionics multi-agent GA
   2026 on Google ADK; Omnia Agent; GK Agentic; Competera AI assistant), but
   none of the public material shows a per-transaction, event-driven trigger
   from the POS's own event stream plus a visible human approval plus the
   closed loop back to POS and shelf. That combination is the white space.
8. **Regulatory hook that strengthens the "approval" story**: section 11
   PAngV requires stating the lowest price of the last 30 days for any
   advertised price reduction, except for perishables marked down because of
   imminent expiry (if the reason is shown). An agent proposal that checks
   this, and a human who approves it, is a compelling compliance narrative.
9. **Recommended framing**: "markdown and personalised voucher agent
   against food waste, with human approval" rather than "dynamic pricing"
   (consumer advocates in Germany warn about "Flatterpreise"; dm explicitly
   guarantees prices for 4 months).

---

## 1. EuroCIS 2027 and the 2025/2026 recap

### 1.1 EuroCIS 2027 - facts

- **Dates/venue**: 16-18 February 2027, Messe Duesseldorf.
  VERIFIED (page): <https://www.eurocis-tradefair.com/>,
  <https://www.eurocis-tradefair.com/en/visit/what-to-expect/reasons-to-attend>.
  Also listed on GEBIT's events page (16.02.-18.02.2027), VERIFIED (page):
  <https://www.gebit.de/en/company/events>.
- **Motto**: "LEADING. BIGGER. AHEAD." with call to action "GO FOR EUROCIS
  2027". VERIFIED (page): <https://www.eurocis-tradefair.com/>.
- **Focus topics (homepage)**: AI, data, checkout, payment, security,
  connected stores. VERIFIED (page): same URL.
- **Topic clusters (visitor page)**: AI & Data-Driven Retail, Employee
  Empowerment, Future Checkout, Loss Prevention, Future Payment, Retail
  Media. VERIFIED (page):
  <https://www.eurocis-tradefair.com/en/visit/what-to-expect/reasons-to-attend>.
- **Special areas**: start-ups (Start-up Hub), food service, cybersecurity,
  charging infrastructure; stages with expert talks; Guided Innovation
  Tours; awards. VERIFIED (page): homepage and reasons-to-attend page.
- **Featured exhibitor logos (homepage, 2027)**: about 40, including 4POS,
  Bizerba, Axis, Datalogic, Diebold, Epson, Glory, **Hanshow**, HP, Ingenico,
  ITAB, **NCR**, Nexi, **SAP**, Sunmi, snabble, Deutsche Telekom, Verifone,
  Wanzl, Zucchetti. VERIFIED (page): <https://www.eurocis-tradefair.com/>.
- **Halls / opening hours 2027**: not stated yet (interactive hall plan
  linked). In 2025 EuroCIS used Halls 9 and 10, 10:00-18:00 daily.
  VERIFIED (page): 2025 pre-show press release
  <https://www.eurocis-tradefair.com/en/Media_News/Press/Press_material/Press_releases/Smart,_secure,_connected_%E2%80%93_EuroCIS_2025_shows_the_future_of_retail_technology>.
- **Expected size 2027**: no official figure. Third-party listing projects
  ~13,500 attendees and ~475 exhibitors. VERIFIED (snippet):
  <https://tradefest.io/en/event/eurocis>. ASSUMPTION: realistic planning
  basis is the 2025 level, ~14,000-15,000 visitors and ~500 exhibitors over
  3 days, i.e. roughly 4,500-5,000 visitors per day across two to four halls.
- **Ticket price reference (2025)**: online day ticket EUR 28, season EUR 50.
  VERIFIED (page): 2025 pre-show press release (above).

### 1.2 EuroCIS 2025 recap (last standalone edition, 18-20 Feb 2025)

Numbers:

- 14,471 trade visitors (press: "more than 14,000") from 95 resp. 97
  countries; ~500 exhibitors from 37 countries; record edition, fully
  booked, largest in its history. VERIFIED (page):
  <https://lebensmittelpraxis.de/handel-aktuell/43282-handelstechnologie-messe-eurocis-2025-lockt-ueber-14-000-fachbesucher-nach-duesseldorf.html>;
  14,471 VERIFIED (snippet) via eurocis-tradefair.com exhibitor pages.
- KPI page: 54 % of visitors with decision-making competence, 44 % of
  visitors from retail, 94 % recommendation rate, 14,400 sqm net space
  (2024: 475 exhibitors / 41 countries, 14,000 visitors / 89 countries,
  56 % decision makers). VERIFIED (page):
  <https://www.eurocis-tradefair.com/en/exhibit/good-reasons-to-attend-eurocis>.
- 37 % of visitors found new business partners. VERIFIED (snippet), same
  site.

Themes:

- **AI dominated**; generative AI applied across inventory management,
  pricing and sales forecasting; the fair director called generative AI a
  new milestone. Other focus areas: automated checkout systems, **ESL**,
  smart shopping carts, personalised customer engagement, intelligent
  shelves, service robots. New special areas: Cybersecurity Hub and Food
  Service Innovation Hub; 18 start-ups in the Start-up Hub; EHI reta awards.
  VERIFIED (page): Lebensmittelpraxis article above.
- Official 2025 "hot topics": customer centricity, smart stores, AI, smart
  energy management, cybersecurity; co-located XPONENTIAL Europe (robotics).
  VERIFIED (page): 2025 pre-show press release.
- The fair's own AI page lists **dynamic pricing** and predictive analytics
  among AI areas showcased. VERIFIED (snippet):
  <https://www.eurocis-tradefair.com/en/visiting/hot-topics/ai-machine-learning-in-retail>.

Notable showcases 2025 (relevant to our use case):

- **Hanshow** (ESL leader, also on the 2027 logo wall): integration with
  **Too Good To Go** (flashing ESLs flag near-expiry food), an **AI-powered
  discounting module** that adjusts prices by expiry date and demand and
  shows them at the shelf edge, cloud-managed ESLs on its HiLPC network, a
  partnership with MOOS (ESL messages change with real-time stock), Smart
  Cart. VERIFIED (page):
  <https://www.hanshow.com/en/news/hanshow%E2%80%99s-unified-solutions-boost-retail-efficiency-and-customer-experience-at-eurocis-2025>
  (dated 2025-02-19).
- **SOLUM** unveiled a unified platform (ESL, digital signage, IoT, vision
  AI cameras). VERIFIED (snippet):
  <https://retailtimes.co.uk/solum-showcases-the-future-of-retail-display-innovation-at-eurocis-2025>.
- Commentary at the time: AI agents "still in their infancy" at EuroCIS
  2025. VERIFIED (snippet), trade press roundup
  (<https://www.eurocis-tradefair.com/en/Euro_CIS_2025/Artificial_Intelligence_back_from_the_future>).

### 1.3 EuroCIS 2026 = part of EuroShop 2026 (22-26 Feb 2026)

- EuroCIS was integrated into EuroShop 2026 as its own brand, replacing the
  former "Dimension Retail Technology". VERIFIED (page), news of
  2025-05-16: <https://www.euroshop-tradefair.com/en/media-news/news/newsticker/eurocis-goes-euroshop>.
- EuroShop 2026 final numbers: 81,000+ visitors from 141 countries
  (two-thirds from abroad, one in five from outside Europe), 1,840
  exhibitors from 61 nations, roughly on par with 2023. EuroCIS occupied
  **four of 14 halls**. Next dates: EuroCIS 16-18 Feb 2027, EuroShop 18-22
  Feb 2029. VERIFIED (page):
  <https://www.technologyrecord.com/article/euroshop-spotlights-retails-digital-future-at-record-international-gathering>,
  <https://www.diyinternational.com/content/news/2026/02/27/free/euroshop-2026-maintains-visitor-and-exhibitor-numbers.html>.
- Main focus per final report: AI-based applications (efficiency and new
  business models), checkout solutions (incl. self-checkout for larger
  baskets); an exhibitor statement says **ESL has evolved from price display
  to platforms for navigation and process optimisation**. VERIFIED (page):
  diyinternational article above.

Notable 2026 showcases and announcements in our space:

- **Vusion (ex VusionGroup / SES-imagotag)** at EuroShop Hall 6, Booth G41
  with SAP as booth partner: ESLs, real-time pricing, inventory automation,
  EdgeSense. VERIFIED (snippet): <https://www.vusion.com/?p=25392>.
  Days before the fair (2026-02-19), Carrefour and Vusion announced
  digitalisation of all French Carrefour hyper- and supermarkets by 2030,
  with a joint lab covering "agentic commerce". VERIFIED (snippet):
  <https://www.intelligentcio.com/eu/2026/03/05/carrefour-partners-with-vusion-to-scale-ai-powered-smart-store-technology-across-france/>.
- **GK Software** (Hall 6, Booth G42): GK Vision, GK Engage and **GK AIR**
  for price optimisation and personalisation. VERIFIED (snippet):
  <https://www.gk-software.com/us/corporate-news-and-press-releases/en-press-release-20260112-euroshop>.
  GK later launched "GK Agentic" (framework for AI agents in retail
  operations, e.g. building promotions). VERIFIED (snippet):
  <https://e-commerce.news/story/gk-software-launches-retail-ai-framework-gk-agentic>.
- **SOLUM + Competera** (announced 2026-02-27 after strong EuroShop
  interest): Competera AI price recommendations pushed via API to SOLUM's
  Newton ESL infrastructure, implemented automatically across stores. No
  approval step and no feedback loop are described. VERIFIED (page):
  <https://www.solum-group.com/solum/press-release-detail.solum-and-competera-expand-partnership-to-integrate-ai-driven-pricing-solutions-with-real-time-esl-execution-across-europe>.
- **7Learnings** AI dynamic pricing (deployed at GALERIA) named a standout
  by the department-store association IADS. VERIFIED (page):
  <https://www.iads.org/member/books-conferences/euroshop-2026-75ccf>.
- **Hanshow**: Store Digital Twin (NexShelf, Smart Cart). VERIFIED (snippet),
  Simply Wall St news listing (szse-301275).
- **Toshiba**: MxP Vision Kiosk (AI grab-and-go), TCx POS; **Posiflex**:
  AI product recognition at self-checkout. VERIFIED (snippet):
  <https://briefglance.com/articles/toshibas-ai-vision-redefining-retails-future-at-euroshop-2026>,
  <https://www.posiflex.com/news-detail/EuroShop_2026/>.
- **Diebold Nixdorf** presented an AI-at-checkout case with EDEKA.
  VERIFIED (snippet), EuroShop programme search results.
- Trade-press verdict: retail does not need more AI demos, it needs better
  integration. VERIFIED (snippet): EuroShop 2026 roundup
  (<https://www.pulse.bot/retail/news/euroshop-2026-how-ai-is-taking-the-smartification-of-stores-to-the-next-level-c7ad7a48-0936-4d12-b23d-da4b4365394d>).

**EHI reta awards 2026** (19th edition, presented at EuroShop 2026)
- relevant winners. VERIFIED (page):
<https://euro-security.de/en/ehi-honours-innovative-technology-solutions-in-retail>.

- Checkout & Smart Store: **Lengermann & Trieschmann (L&T) with Vusion and
  GK AIR** - smart hang tags for ~20,000 items plus the "Intelligent Price
  Engine" for dynamic pricing (demand trends, inventory, external market
  data); prices update at item level, campaigns synced to online.
  VERIFIED (page):
  <https://retailtechinnovationhub.com/home/2026/2/24/german-fashion-retailer-landt-bags-reta-awards-2026-award-for-work-with-vusion-and-gk-software>.
- AI: **Netto Marken-Discount with Trigo** (computer vision on CCTV detects
  unpaid items at self-checkouts); Albert Czechia with Mettler Toledo (AI
  item recognition for loose goods); Sonae with Sensei (autonomous store).
- Customer Experience: China Resources Vanguard with Hanshow (NFC ESLs as
  interactive touchpoints); Kaufland Foundation with Schwarz Digits /
  Bizerba.
- Employee Empowerment: **Thalia "Minerva"** - recommendation assistant built
  on a multi-agent system with specialised expert agents.

### 1.4 Theme matrix (2025/2026 evidence)

| Theme | Evidence | Strength |
| --- | --- | --- |
| Agentic AI | Thalia multi-agent (reta 2026); GK Agentic; Revionics multi-agent; Carrefour/Vusion "agentic commerce" lab; 2025 still "infancy" | Rising, few live demos |
| Dynamic pricing | L&T + GK AIR (reta 2026); 7Learnings; SOLUM + Competera; Hanshow AI discounting | Strong, mostly engine-to-ESL |
| ESL | EHI 91 %; Vusion/SAP booth; Hanshow, SOLUM, Pricer; ESL as platform | Evergreen, very strong |
| Loyalty / personalisation | GK AIR personalisation; Adjoe gamified loyalty (IADS); Koctas LaaS (reta) | Medium |
| Self-checkout / CV | Netto + Trigo; Toshiba; Posiflex; Diebold + EDEKA | Very strong |
| Retail media | EuroCIS 2027 topic cluster; Vusion Retail Media (VAS) | Medium |

Sources for each row are listed in 1.2 / 1.3 and section 4.

### 1.5 Implications for our showcase

- ASSUMPTION: visitors in 2027 will have seen many "AI price engine pushes to
  ESL" demos. Novelty must come from (a) the live POS event stream, (b) the
  visible agent reasoning, (c) the human approval, (d) the closed loop to
  the next scan and the receipt/voucher.
- ASSUMPTION: 54 % decision makers and 44 % retail visitors means the
  audience values operational realism (finality of transactions, PAngV,
  store staff UX) over flashy AI.

---

## 2. GEBIT Solutions and the GEBIT Retail Platform

### 2.1 Company facts

- GEBIT Solutions GmbH, founded 1991 (35th anniversary posts in Oct/Nov
  2026), locations Berlin, Duesseldorf, Leipzig, Stuttgart and Lisbon;
  ISO/IEC 27001:2022 certified. VERIFIED (page):
  <https://www.gebit.de/en/company/about-gebit>,
  <https://www.gebit.de/en/company/news>.
- Headline numbers on the homepage: 10,000,000+ customers (ASSUMPTION:
  shoppers served, period not stated), 110,000+ POS systems, 32+ countries,
  35+ years. VERIFIED (page): <https://www.gebit.de/en/homepage>.
- Employees: third-party directories disagree (approx. 180 to 500).
  VERIFIED (snippet), e.g. Indeed / LeadIQ listings. Not authoritative.
- Object-oriented development since 1991, Java focus since 1996.
  VERIFIED (snippet): <https://www.gebit.de/en/careers/careers-at-gebit>.
  GEBIT staff regularly speak at Java community events (JUG Saxony Day,
  Java Forum Stuttgart with ~40 colleagues). VERIFIED (page): news page.
- Positioning: "STANDIVIDUAL Solutions" = proven standard platform (GEBIT
  Retail Platform) plus customer-specific development; strong at the
  checkout ("retail performance becomes visible at the checkout").
  VERIFIED (page, sponsored article 2026-07-23):
  <https://www.esmmagazine.com/technology/gebit-solutions-where-retail-performance-becomes-visible-314753>.
- Owns test labs with real retail hardware and a **cloud-based reference
  and demo environment** for omnichannel retail. VERIFIED (page, company
  profile): <https://retail-optimiser.de/en/tag/gebit-en>. This is the
  natural target for the later "switch live" phase.

### 2.2 Products (public)

From <https://www.gebit.de/en/homepage> and solution pages (VERIFIED, page):

- **GEBIT Retail Platform**: modular services in 13 functional areas
  (Business Intelligence, Customer Loyalty, Customer Surveys, Finance,
  Fiscalization, Fraud, Fulfillment, Operations, Pricing, Purchasing,
  Receipt, Store, Workforce Management). Examples: price and promotion
  calculation service with what-if scenarios; managed/self/mobile checkout
  clients and device adapters; centralized **event-based** fraud detection;
  receipt repository and layout service. Adapters for Diebold Nixdorf and
  NCR SCO hardware, loyalty/coupon providers, ZVT, PayPal. "Runs on nearly
  all hardware and in every environment"; Cloud & Managed Operations is a
  development focus. <https://www.gebit.de/en/solutions/gebit-retail-platformr>.
- **Checkout portfolio**: Managed-Checkout, Self-Checkout, Mobile
  Managed-Checkout, Mobile Self-Checkout, Cart-Checkout, Scan & Go.
- **Pricing** (centralised, automated price calculation across channels;
  central and regional pricing; quick basket calculation incl. promotions;
  runs centrally in the cloud or locally; "standard API for other solution
  providers"). <https://www.gebit.de/en/solutions/pricing>.
  The solutions overview states Pricing & Campaign Management is
  "synchronized across all channels in milliseconds".
  <https://www.gebit.de/en/solutions>.
- **Campaign Management** (offers, campaigns, promotions per store / store
  group / chain; time-limited or recurring; stores can run clearance
  campaigns; editor + simulator + calendar; SAP promotion module
  connectivity). <https://www.gebit.de/en/solutions/campaign-management>.
- **Loyalty Management** (points or monetary accounts, coupons, vouchers,
  tiers, multiple programmes; facade for external programmes such as
  Payback or DeutschlandCard; linkable to Campaign Management).
  <https://www.gebit.de/en/solutions/loyalty-management>.
- **Digital Receipt / eReceipt** (real-time digital receipts to the
  smartphone, PDF, cloud hosting, EKaBS standard).
  <https://www.gebit.de/en/solutions/digital-receipt-ereceipt>.
- **Attendant App** (staff app for central monitoring of self-checkouts,
  **remote authorizations** such as age verification; mobile or web
  client). <https://www.gebit.de/en/solutions/attendant-app>.
  ASSUMPTION: in the live phase, the approval click could be placed in the
  Attendant App or Operations Suite instead of a SAM-specific tablet UI -
  ask GEBIT.
- **GEBOS** (InStore operating system; EDA = event-driven automation for
  Linux-based POS systems; EDGE = managed event-driven operating
  environment). <https://www.gebit.de/en/solutions/gebos>.
- **Operations Suite** (real-time monitoring), **Fraud Prevention**.

### 2.3 How the platform emits events (public info only)

- GEBIT describes its STANDIVIDUAL solutions / platform as a **reactive,
  event-based microservice architecture** for distributed, real-time-capable
  omnichannel retail, built as versioned standard products. VERIFIED
  (snippet) for <https://en.gebit.de/> and
  <https://www.gebit.de/en/solutions>; the current page versions no longer
  contain that wording (VERIFIED, page: not found on refetch).
- **Solace**: GEBIT states publicly that it already uses **Solace Event
  Mesh** to connect retail systems for real-time data integration and is
  adding **Solace Agent Mesh** on the same foundation. VERIFIED (page,
  LinkedIn post 2026-10-08):
  <https://www.linkedin.com/feed/update/urn:li:activity:7513923086665224193>.
  Further posts the same day welcome the Solace team and call Solace a
  platform for real-time data integration and agentic AI:
  <https://www.linkedin.com/feed/update/urn:li:activity:7513929448870699008>.
  Solace is listed on GEBIT's partner page (45 partners, logos only).
  VERIFIED (page): <https://www.gebit.de/en/company/partnerships>.
- **dm** (GEBIT POS customer) reports that data exchange between SAP
  merchandise management, in-house store systems, **the Gebit POS solution**
  and Markant's master data pool improved significantly after moving to
  Solace Event Mesh. VERIFIED (page, 2025-12-12):
  <https://retail-optimiser.de/en/dm-is-very-pleased-with-solace/>.
- **Kafka**: no public evidence that GEBIT uses Kafka was found
  (searches for GEBIT + Kafka returned nothing GEBIT-specific).
  ASSUMPTION: internal service-to-service eventing may still use something
  else; ask GEBIT.
- **gRPC + Protobuf** command/event API of the Purchase Service: from the
  GEBIT developer's message and the delivered proto files (outside this
  track; see the protocol-analysis track).
- ESL: no ESL vendor appears among GEBIT's 45 listed partners. VERIFIED
  (page): partnerships page. ASSUMPTION: GEBIT integrates ESL per customer
  project; ask which ESL is available in the demo lab.

### 2.4 Known customers / references (DACH and beyond)

- Homepage reference logos: ALDI SUED, SPAR, DEICHMANN, dm-drogerie markt,
  Kaufland, OBI Baumarkt, Bayer AG. VERIFIED (page):
  <https://www.gebit.de/en/homepage>.
- **Kaufland**: chose GEBIT POS for all 7 countries (DE, CZ, SK, PL, HR,
  BG, RO), reported 2014-10-30. VERIFIED (page):
  <https://www.lebensmittelzeitung.net/tech-logistik/nachrichten/Kaufland-will-mit-Gebit-kassieren-107512>.
- **ALDI SUED**: individual POS software built on the GEBIT POS platform for
  4,400+ stores worldwide. VERIFIED (snippet):
  <https://www.cio.de/article/3669037/aldi-sued-setzt-neue-kassenloesung-ein.html>.
  GEBIT integrated Diebold Nixdorf's AI produce recognition (Vynamic Smart
  Vision) into ALDI SUED's checkout (2023-12-18). VERIFIED (page, excerpt):
  <https://retail-optimiser.de/en/tag/gebit-en>.
- **dm-drogerie markt**: uses the Gebit POS solution (2025). VERIFIED (page):
  dm/Solace article above.
- **DEICHMANN**: mobile checkouts on Zebra handhelds developed by GEBIT,
  2025-02-13. VERIFIED (page, excerpt): retail-optimiser tag page.
- **SPAR ICS** (SPAR Austria group IT): "10,000 checkouts, 4 countries"
  milestone, 2026-09-10. VERIFIED (page): <https://www.gebit.de/en/company/news>.
- **OBI**: POS and merchandise-management references (older, 2012).
  VERIFIED (snippet): <https://ixtenso.com/technology/exhibitors-report-on-new-checkout-counter-orders.html>.
- **EDEKA + GEBOS**: "Highly Commended", Technology Implementation of the
  Year (Rest of World), RTIH Innovation Awards 2026 (London, 2026-11-04).
  VERIFIED (snippet): RTIH shortlist / results pages
  (<https://retailtechinnovationhub.com/home/2026/11/5/morrisons-waitrose-and-dunelm-take-top-honours-at-2026-rtih-innovation-awards-ceremony-in-london>);
  GEBIT's own post 2026-11-05 confirms the award for the GEBOS transformation
  programme. VERIFIED (page): news page.

### 2.5 Trade fair presence and booth assets

- GEBIT lists **EuroCIS 2027** among its upcoming events (with RETAIL NXT
  2026, EHI techdays 2026, IT-Tage 2026). VERIFIED (page):
  <https://www.gebit.de/en/company/events>. Hall/stand not published.
- Previous EuroCIS: a GEBIT events page listed 27.-29.02.2024 (= EuroCIS
  2024) "Halle 10 / Stand E55". VERIFIED (snippet only):
  <https://www.gebit.de/en/company/events-news/2> (page now 404).
- **Bonshooter**: GEBIT's arcade machine for trade-fair stands - four
  screens, two handheld scanners, players have 60 seconds to beat the high
  score by scanning items, "several scans per second without pause"; meant
  to show how reliable a checkout must be; a second machine is planned.
  VERIFIED (page, LinkedIn 2026-09-01):
  <https://de.linkedin.com/posts/gebit-solutions-gmbh_gebit-solutions-innovation-insights-3-warum-activity-7500455041665789952-YIGu>.
  ASSUMPTION: this is the ideal crowd magnet and event source for our
  showcase ("your scans feed the agent"), but it produces bursts of several
  scans per second, which rules out one LLM workflow per scan (see 5.4).

### 2.6 Overlap: GEBIT customers that are also public Solace references

| Retailer | GEBIT | Solace |
| --- | --- | --- |
| dm-drogerie markt | Gebit POS solution (2025) | Event Mesh replaced Tibco EMS; 20,000 clients; ~100 M events/day; ~10 ms latency |
| Schwarz Group (Kaufland, Lidl) | Kaufland POS in 7 countries | Solace PubSub+ for stores, supply chain, merchandise management |
| EDEKA | GEBOS (RTIH HC 2026) | Event mesh streams master data to 6,000+ stores |

Sources: dm <https://retail-optimiser.de/en/dm-is-very-pleased-with-solace/>
(VERIFIED, page); Schwarz
<https://www.casestudies.com/company/solace/case-study/schwarz-group-customer-case-study>
and <https://solace.com/industries/retail> (VERIFIED, page); EDEKA
<https://salestechstar.com/sales-intelligence/german-supermarket-chain-edeka-uses-solace-technology-to-stream-master-data-across-their-stores-and-supply-chain/>
(VERIFIED, page, 2021-11-26).

ASSUMPTION: naming these retailers on booth material needs their consent;
use "trusted by leading DACH retailers" unless cleared.

---

## 3. Solace in retail and Solace Agent Mesh positioning

### 3.1 Public retail references

- **HORNBACH** (2025-09-09): multiple brokers in a poly-cloud setup and in
  physical stores, forming an event mesh; price updates, product
  information and sales data shared as they happen (in-store, omnichannel,
  customer app); 170+ stores in 9 countries, ~25,000 employees, EUR 6.2 bn
  sales. VERIFIED (page):
  <https://solace.com/press-center/hornbach-redefines-retail-innovation-with-solaces-platform/>.
- **dm-drogerie markt** (2025-12-12): Tibco EMS fully replaced; Azure and
  Google Cloud now exchange data event-driven; digital receipt in the dm app
  as a use case; logistics data hub replacing Oracle AQ; ~700 legacy
  connections, 20,000 clients migrated, ~100 million events per day, ~10 ms
  latency vs a 50 ms decision window for box routing; Solace beat 27
  competitors in the 2023 selection; couponing and express pickup named as
  beneficiaries. VERIFIED (page):
  <https://retail-optimiser.de/en/dm-is-very-pleased-with-solace/>.
- **EDEKA**: real-time master data from datacenters to store-floor devices
  and POS, 6,000+ stores. VERIFIED (page), see 2.6.
- **Schwarz Group**: replaced legacy messaging, event-driven microservices
  on a new container platform across geographies, cloud and on-prem.
  VERIFIED (page), see 2.6.
- **Les Mousquetaires (Intermarche)**: real-time pricing updates to
  **digital shelf labels**; daily fruit and vegetable price changes; 450+
  new event-driven flows in two years. VERIFIED (page):
  <https://www.casestudies.com/company/solace/case-study/les-mousquetaires-customer-case-study>
  (source: <https://solace.com/company/customers/les-mousquetaires/>).
- Logos on Solace's retail page also include Menards and Lagardere Travel
  Retail; the page describes streaming price and product updates to POS,
  kiosks, apps and websites. VERIFIED (page): <https://solace.com/industries/retail>.
- Solace at EuroCIS/EuroShop: no evidence of an own booth found.
  ASSUMPTION: EuroCIS 2027 with GEBIT would be Solace's first visible retail
  trade-fair showcase in Duesseldorf in recent years - verify internally.

### 3.2 Recurring use-case patterns (relevant for the swap to live)

- Price distribution HQ -> stores -> POS/ESL/app (HORNBACH, Les
  Mousquetaires).
- Master data streaming to stores (EDEKA, Schwarz).
- POS / digital receipt / couponing events across clouds (dm).
- ASSUMPTION: our showcase's "price change event to the article master
  data service" is exactly the HORNBACH/Les Mousquetaires pattern, so it is
  credible to say "this is how leading retailers already distribute prices;
  we add an agent and an approval in front of it".

### 3.3 Solace Agent Mesh positioning

- Solace pitches Agent Mesh as a platform to take agents from idea to
  production (build, test, deploy, observe, improve) on an **event-driven
  foundation** so agents get a continuous stream of real-time data;
  **built-in human-in-the-loop approvals**; governance, RBAC, audit, token
  spend tracking per agent/model/task; open protocols **A2A and MCP**;
  self-hosted or managed; free for companies under USD 25 M revenue.
  Listed use cases: customer support, predictive maintenance, supply chain
  orchestration, personalised marketing/sales agents, workforce assistants.
  No customers named. VERIFIED (page): <https://solace.com/products/agent-mesh>.
- Solace's retail AI thesis: LLMs lack real-time context, retailers need
  RAG over real-time events and an event mesh ("AI store manager"
  orchestrating store events). VERIFIED (snippet):
  <https://solace.com/blog/retail-event-mesh-eda-ai/>.
- Agent Mesh Enterprise GA: reported around Dec 2025 (AWS re:Invent) and
  May 2026 (press). VERIFIED (snippet):
  <https://www.techedt.com/solace-launches-agent-mesh-enterprise-to-support-real-time-agentic-ai-adoption>,
  <https://futurecio.tech/solace-unveils-agent-mesh-enterprise-to-harness-agentic-ai-solutions/>.
- SAM 2.493.0 docs: human-in-the-loop is an A2A task state
  (`input-required`, `user_input_request` / `user_input_response`).
  VERIFIED (local): `scratchpad/samdocs/concepts__a2a-protocol.md:110,127`.
  Non-interactive triggers (scheduled tasks) reject tasks that enter
  `input-required`. VERIFIED (local):
  `scratchpad/samdocs/using-agent-mesh__scheduled-tasks.md:96`.
  ASSUMPTION: an event-mesh-triggered workflow has the same constraint (no
  user attached), so the one-click approval should be modelled as a
  separate approval event (tablet publishes `approval` -> second workflow
  or tool), not as an in-workflow HIL pause. This is for the architecture
  track to confirm.

### 3.4 Implications

- The joint message is unusually strong and public: "GEBIT POS already
  speaks Solace; Agent Mesh is the AI layer on the same mesh" (VERIFIED by
  GEBIT's own post). Use it as the opening line of the talk track.
- Solace's differentiator vs pricing-engine vendors is not the price model
  but the **real-time, event-driven plumbing plus governed agents plus
  approval**. Do not position SAM as a pricing optimiser.

---

## 4. Dynamic pricing and ESL - state of the art 2025/2026

### 4.1 ESL vendors

- **Vusion** (VusionGroup, ex SES-imagotag; Nanterre): FY2025 adjusted
  revenue EUR 1,527 m (+51 %), VAS revenue EUR 211 m (doubled), order intake
  EUR 1.7 bn; cloud installed base **> 375 million ESLs** at end 2025 (152 M
  end 2024); growth driven by EdgeSense rollout in Walmart supercenters;
  Carrefour is the first large-scale European deployment of EdgeSense +
  VusionCloud + Captana; 2026 guidance +15-20 % revenue. VERIFIED (page):
  FY2025 press release 2026-02-26,
  <https://s203.q4cdn.com/882900163/files/doc_financials/2025/q4/Vusion_PR_FY-2025-Results_vUK.pdf>.
  In Germany: **dm** is the second retailer worldwide after Walmart to adopt
  EdgeSense (20 stores live, 50 more following; LED flashing for in-store
  picking) - but dm guarantees prices for at least four months and has no
  plans for more dynamic pricing. VERIFIED (page, 2025-10-31):
  <https://retail-optimiser.de/en/dm-aims-for-real-time-shelf-insights-with-vusiongroup/>.
  OBI DIY stores are a German Vusion deployment. VERIFIED (snippet).
- **Hanshow** (China, Shenzhen-listed, code 301275; its 2025 review cites
  an IPO milestone, VERIFIED snippet): ALDI SUED's single ESL
  supplier (Nebular 350R-N, 3.5 inch, red/white/black, 9 pages per label,
  radio; manufacturer battery claim 15 years at two price changes per day).
  VERIFIED (page, 2022-12-03):
  <https://retail-optimiser.de/en/aldi-sued-introduces-esls-from-hanshow>.
  HiLPC protocol "over 60,000 pieces/hour/ESL controller", tens of millions
  of devices within a few minutes, used in 30,000+ stores in 50+ countries.
  VERIFIED (page, 2023-02-01):
  <https://iotm2mcouncil.org/iot-library/news/smart-retail-news/hanshow-boosts-esl-to-real-time-performance/>.
  China market share 62 % (2023) per Hanshow. VERIFIED (snippet).
- **Pricer** (Sweden, infrared): historic claim of 50,000+ full ESL updates
  per hour, design goal of a full store update within about one hour
  (2008). VERIFIED (page):
  <https://www.pricer.com/press-release/pricer-esl-platform-breakthrough-quadruples-communication-speed-with-existing-infrastructure>.
  Newer product page claims LED alerts within 3-4 seconds. VERIFIED
  (snippet): <https://www.retailtechnologyshow.com/exhibitor-products/pricer-smarttag-color-stc->.
  Pricer powered Albert Heijn's AI dynamic discounting pilot with Wasteless
  (2019). VERIFIED (page):
  <https://www.pricer.com/news/albert-heijn-combats-food-waste-with-pricer-and-wasteless-through-ai-powered-dynamic-pricing>.
- **SOLUM** (Korea; Newton platform, BLE PHY + proprietary protocol at
  2.4 GHz): ~3,000 labels in ~4 minutes per gateway; Newton Lite claims
  simultaneous display update within 5 seconds over 60 RF channels.
  VERIFIED (snippet), SOLUM industrial presentation 2022 and product pages
  (<https://www.solum-group.com/esl-n-iot/product-lineup/special-esl/newton-x>).
  Partnership with Competera (see 1.3).
- **Displaydata**: historic Kaufland Europe ESL supplier. VERIFIED (snippet):
  <https://www.casestudies.com/company/displaydata/case-study/making-the-most-of-margins-with-one-of-europes-largest-esl-deployments>.

### 4.2 Update latency - what to promise on the booth

- Vendor marketing: prices pushed "in seconds" chain-wide (e.g. StrongPoint
  for Vusion). VERIFIED (snippet):
  <https://www.strongpoint.com/uk/solutions/shopfloor/electronic-shelf-labels-esl-2/>.
- Real-world integration lag can be much longer: one POS-vendor integration
  with Vusion documents an average of ~20 minutes from change to tag.
  VERIFIED (snippet): <https://portal.paladinpos.com/knowledge-base/ses-imagotag/>.
- ASSUMPTION: for a single booth label on a dedicated access point, a few
  seconds to under a minute is realistic; measure it before promising
  anything. The robust booth promise is "the **next scan at the POS** uses
  the new price" (GEBIT's price service is "synchronized in milliseconds"
  per GEBIT), with the ESL as a visual bonus.
- Legal point: shelf price and checkout price must match (consumer
  advocates point to shelf/checkout mismatches as a risk). VERIFIED
  (snippet): Verbraucherzentrale Hamburg
  <https://www.vzhh.de/themen/lebensmittel-ernaehrung/einkaufsfalle-supermarkt/dynamic-pricing-digitale-preisschilder-flatterpreisen>.
  ASSUMPTION: the demo should update POS price and ESL from the same event
  and show both, which turns a risk into a selling point.

### 4.3 ESL adoption in Germany

- **EHI Technologie-Trends im Handel 2025** (CIOs of ~119 retailers in
  DACH, Feb 2025): in food retail **91 % of respondents use digital price
  labelling**; usage is mostly limited to price display, extra functions
  such as flashing are still rarely used. Same study: AI named the top
  trend by **100 %** of respondents (first time ever), **92 %** use AI
  (2023: 69 %), 92 % use or plan digital receipts, IT budgets at a record
  1.98 % of net sales, Seamless Checkout second trend (40 %). Top AI use
  case: forecasting & replenishment (55 %). VERIFIED (page, PDF text
  extracted):
  <https://www.ehi.org/wp-content/uploads/Downloads/Leseproben/Technologie_Trends-2025_Leseprobe_06-03-2025.pdf>.
- **Lidl**: all 3,250 German stores equipped with ESL for fruit and
  vegetables and promotion areas (photo caption, LZ 2024-02-26); displays
  also promote Lidl Plus. VERIFIED (page):
  <https://www.lebensmittelzeitung.net/tech-logistik/nachrichten/electronic-shelf-labels-digitale-regalpreis-etiketten-setzen-sich-durch-176195>,
  <https://www.lebensmittelzeitung.net/tech-logistik/nachrichten/rollouts-bei-discountern-digitale-preisschilder-werden-standard-in-deutschland-175108>.
- **ALDI SUED**: ESL in all ~2,000 German stores (Feb 2024); worldwide
  rollout completed with ~25 million displays (LZ headline). VERIFIED
  (snippet): ALDI SUED newsroom headline and
  <https://www.lebensmittelzeitung.net/tech-logistik/nachrichten/25-mio.-digital-displays-aldi-sued-schliesst-weltweiten-esl-rollout-ab-174488>.
- **Netto Marken-Discount**: completion planned H1 2024. VERIFIED (page):
  LZ 2023-12-15 (above).
- **Kaufland**: ESL in F&V of all German stores for years, extended to all
  in-store bakeries (2025). VERIFIED (snippet): Kaufland press material and
  <https://www.t-online.de/digital/aktuelles/id_100726094/kaufland-digitale-preisschilder-jetzt-auch-in-filial-baeckereien.html>.
- **REWE**: ESL in ~1,500 stores and in all new stores (undated LZ/LP
  items). VERIFIED (snippet), likely outdated.
- **EDEKA**: regional (e.g. Ueltzhoefer region near Heilbronn nearly all
  stores); no group-wide figure. VERIFIED (snippet).

### 4.4 Intraday pricing practice in Europe

- **REMA 1000 (Norway)**: up to 100 price changes per day per store (20 to
  hundreds depending on season); cuts hit 50-300 of up to 5,000 items per
  day, mostly seasonal. **Albert Heijn (NL/BE, ~1,280 stores)**: checks
  sales every 15 minutes, caps each item at four cuts per day, saves about
  250,000 kg of food waste per year; customers needed a paper sticker to
  notice markdowns. **Lidl** outside the US uses ESL for same-day price
  cuts only to reduce food waste; Lidl US has no intraday plans.
  VERIFIED (page, WSJ 2025-07-27 via aggregator):
  <https://www-web.itiger.com/news/2554541749>; PYMNTS summary
  <https://www.pymnts.com/?p=2865300> (Walmart ESL in 400+ of ~4,600 US
  stores).
- **No surge pricing evidence**: a study of 180 M price observations in 114
  US stores (2022-2024) found no demand-based surges after ESL adoption;
  authors note ESL may reduce food waste via expiry discounts. VERIFIED
  (page, 2025-07-22):
  <https://today.ucsd.edu/story/new-research-debunks-fears-of-supermarket-surge-pricing-with-electronic-shelf-labels>.
- **Swiss Coop/Migros**: no dynamic pricing; changes only overnight for
  promotions or permanent changes. VERIFIED (snippet):
  <https://www.srf.ch/news/wirtschaft/digitale-preisschilder-migros-aare-aendert-preise-neu-per-knopfdruck>.

### 4.5 AI pricing vendors (who might be "the competition")

- **Revionics (Aptos)**: multi-agent AI pricing system (alpha at Google
  Cloud Next 2025, GA announced for Google Cloud Next 2026), agents for gap
  detection, financial impact modelling and rules/execution; built with
  Google ADK; real-time price pushes; **no explicit approval step
  described**; no POS/ESL integration named. VERIFIED (page, 2026-04-22):
  <https://revionics.com/blog/revionics-multi-agent-pricing-system-is-now-ga-heres-what-that-means-for-retail>.
- **Omnia Retail** (NL, European focus): "Omnia Agent", positioned as the
  first agentic pricing platform; analysis and surfacing by the agent, the
  user makes the final call. VERIFIED (snippet): <https://www.omniaretail.com/agentic-pricing>.
- **Competera**: Store-Level Optimization and AI Pricing Assistant (Jan
  2025); SOLUM ESL execution (Feb 2026). VERIFIED (snippet):
  <https://www.grocerydive.com/press-release/20250124-retails-first-store-level-pricing-optimization-and-ai-powered-pricing-assi/>.
- **Pricefx**: ML + agent-based + generative AI price recommendations, core
  market B2B. VERIFIED (snippet): vendor comparisons.
- **7Learnings** (Berlin, 2019): Series B EUR 10 M+ (2025, Acton Capital);
  GALERIA reference; vendor-claimed ~10 % profit uplift. VERIFIED
  (snippet): <https://7learnings.com/news/7learnings-secures-e10m-series-b/>.
- **GK AIR (GK Software)**: AI price optimisation and personalisation; L&T
  reta award 2026 with Vusion (see 1.3). GK is #2 in new POS software
  installations behind NCR Voyix (Dec 2024). VERIFIED (page, excerpt):
  <https://retail-optimiser.de/en/tag/gebit-en>.
- Also relevant (not researched in depth): Blue Yonder, SAP (Omnichannel
  Promotion Pricing), RELEX. ASSUMPTION.

### 4.6 Markdown / expiry optimisation

- **Wasteless** (Israel): ML pricing for perishables by expiry, integrable
  into POS and ESL; European partners per FAO observatory include EDEKA
  Rhein-Ruhr, Carrefour, Makro, Hoogvliet, Dia, Iper; METRO/Makro pilots;
  company-reported results e.g. -39 % food waste, +1.2 % margin, Spanish
  test -32.75 % waste / +6.3 % revenue. VERIFIED (snippet):
  <https://agritechobservatory.review.fao.org/en/wasteless>,
  <https://trellis.net/article/new-dynamic-duo-pricing-and-food-waste/>.
- **Afresh** (US, fresh forecasting/ordering): reports 25 % average food
  waste reduction in stores using it; USD 115 M Series B (2022), USD 34 M
  (2026). VERIFIED (snippet):
  <https://www.fooddive.com/news/food-waste-reduction-tech-afresh-funding/629092/>.
- **Hanshow + Too Good To Go** and Hanshow AI discounting (EuroCIS 2025),
  see 1.2.
- **Albert Heijn**: AI discounting since 2019 pilot (Zandvoort), today
  15-minute cadence (see 4.4).

### 4.7 Personalised offers via loyalty apps (Germany)

- **Payback** (2025): 35 M+ people in Germany collect regularly, 18 M app
  users, 700+ partners; new partners EDEKA, Netto, Sparkassen, Galeria; dm
  is an established partner. VERIFIED (page, 2026-02-22):
  <https://retail-news.de/payback-rekordbilanz-nutzer-2025/>.
- **REWE Bonus**: REWE left Payback at the start of 2025 and runs its own
  euro-credit programme in the REWE and PENNY apps (weekly bonus actions,
  coupons, redemption at checkout via app); >11 M users reported by one
  source. VERIFIED (snippet): <https://www.drweb.de/rewe/> and REWE Group
  annual review.
- **Lidl Plus**: 120 M+ users worldwide after the US launch (2026-07-09);
  personalised coupons and instant rewards. VERIFIED (page):
  <https://www.retaildetail.eu/news/food/lidl-plus-reaches-120-million-users-following-global-rollout/>.
  Legal: consumer federation vzbv sued Lidl (April 2025) over insufficient
  disclosure that app discounts are "paid with data"; OLG Stuttgart
  dismissed (6 UKl 2/25), revision to the BGH admitted and filed. VERIFIED
  (snippet): <https://retail-news.de/olg-stuttgart-klage-abgwiesen-lidl-plus-app-vzbv/>.
- **Kaufland Card -> Kaufland Card XTRA** (2026-02-12, app-only, points).
  VERIFIED (snippet):
  <https://www.heidelberg24.de/verbraucher/einkauf-test/discounter-neues-rabatt-programm-kaufland-xtra-card-app-kundenkarte-funktioniert-94168854.html>.
- **dm**: dm app (digital receipt, couponing via Solace-connected systems);
  Payback partner. VERIFIED (page): dm/Solace article; Payback article.
- ASSUMPTION: a "voucher for the next visit issued at PurchaseTransactionClosed"
  maps cleanly onto GEBIT Loyalty Management (vouchers, rule-based issuing)
  and eReceipt - and onto how REWE Bonus / Kaufland Card XTRA work - so it
  is a realistic, not a fantasy, use case.

### 4.8 Regulation and public sentiment (talk-track ammunition)

- **Section 11 PAngV**: whoever must state a total price must, for every
  announced price reduction to consumers, state the lowest total price of
  the last 30 days; exceptions: individual price reductions, and perishable
  or short-shelf-life goods reduced because of imminent spoilage/expiry if
  consumers are informed suitably. VERIFIED (page):
  <https://www.gesetze-im-internet.de/pangv_2022/__11.html>.
  Note: "Sale" and "buy 3 pay 2" style promotions are outside the 30-day
  rule. VERIFIED (snippet): <https://www.it-recht-kanzlei.de/preisagabenpflichten-preisermaessigungen-waren.html>.
- **Receipts**: the federal cabinet approved a draft (2026-09-23) for a
  cash-register obligation from January 2028 for businesses with > EUR
  100,000 turnover; the paper-receipt obligation is to become a digital
  receipt provision obligation (not yet passed by parliament). VERIFIED
  (snippet): Deutsche Handwerks Zeitung, Handwerksblatt
  (<https://www.handwerksblatt.de/betriebsfuehrung/registrierkassenpflicht-ab-2028-soll-kommen>).
  ASSUMPTION: makes "voucher on the digital receipt" timely.
- **EU AI Act**: transparency and traceability demands are raised by
  retailers in the EHI AI study context. VERIFIED (page):
  <https://ixtenso.com/euroshop-2026/artificial-intelligence-from-technological-hype-to-strategic-reality-in-retail.html>.
- **Data integration gap**: in the EHI AI study (38 interviews, ~39,000
  stores in DACH, published 2025-12-02) 67 % rate their data integration as
  poor or relatively poor, only 13 % as good; 16 % see themselves as AI
  pioneers. VERIFIED (page): same ixtenso URL.
- **Consumer sentiment**: German consumer advocates warn of "Flatterpreise"
  and less price transparency with ESL. VERIFIED (snippet): vzhh (above).
  In the US, union-backed polling reports majority opposition to digital
  price tags. VERIFIED (snippet), low-quality source. Retailers (Kroger,
  Lidl US, Tesco, Sainsbury's) publicly disavow surge pricing. VERIFIED
  (page): PYMNTS / WSJ summaries above.

---

## 5. Competitors at EuroCIS and how to differentiate

### 5.1 Competitive map (what others show)

1. **ESL platform vendors with AI add-ons** - Vusion (+SAP; EdgeSense,
   Captana, VusionCloud, retail media; Carrefour agentic-commerce lab),
   Hanshow (AI discounting, TGTG, digital twin), SOLUM (+Competera), Pricer
   (+Wasteless history). Strength: big, tangible ESL walls. Gap: the POS is
   a black box; price recommendations come from a separate engine; approval
   and checkout effect are not shown.
2. **AI pricing engines** - GK AIR, 7Learnings, Revionics, Competera,
   Omnia, Pricefx. Strength: optimisation science, references. Gap: batch
   or near-real-time on aggregated data; no per-transaction trigger from
   POS events; approval mostly implicit ("you make the final call") or
   absent in public material.
3. **POS / checkout vendors with AI** - GK, NCR Voyix, Diebold Nixdorf,
   Toshiba, Posiflex, Extenda, LS Retail. Strength: checkout realism, CV
   for loss prevention. Gap: AI focuses on vision/fraud and staff
   assistants, not on agentic pricing decisions.
4. **Hyperscaler/platform agents** - SAP, Microsoft partners (SAP, Toshiba,
   Zebra at EuroCIS 2026), Google ADK-based solutions. Strength: brand.
   Gap: generic agent frameworks, not wired to the store's live event
   stream. VERIFIED (page) for the Microsoft-partner note:
   <https://www.technologyrecord.com/article/eurocis-2026-showcasing-innovations-that-address-real-challenges-in-retail>.

### 5.2 White space (ASSUMPTION, derived from 5.1)

No public EuroCIS/EuroShop showcase found that combines all of:

- per-event trigger from the **real POS's own event stream** (every scan is
  an event on the mesh),
- **transaction finality semantics** (insights on provisional
  PositionAdded; commitments only after PurchaseTransactionClosed;
  PurchaseTransactionCancelled means not sold),
- an **agent proposal with an explanation** (why this article, why this
  markdown, which rule, 30-day lowest price),
- a **visible human approval** with audit trail,
- the **closed loop**: price-change event -> article master data -> the
  next scan at the POS charges the new price -> optional ESL update ->
  receipt/voucher -> new sales events show the effect.

### 5.3 Differentiation pillars and talk-track lines

1. **"Real POS, real events."** GEBIT's Purchase Service events, the same
   ones that feed e-journal, receipt repository, merchandise management and
   SAP in customer projects; demo simulates them faithfully today and
   switches to GEBIT's demo lab without changing the agent side.
2. **"Already on the mesh."** GEBIT publicly uses Solace Event Mesh; dm,
   EDEKA, Schwarz, HORNBACH run Solace in stores. The agent layer (Solace
   Agent Mesh) sits on that foundation - no new integration project.
3. **"The AI proposes, a human decides."** One-click approval, logged and
   attributable; aligns with AI Act transparency and with retailers' wish
   for control. Competitors either push automatically (SOLUM + Competera,
   Revionics as published) or leave the decision implicit.
4. **"Compliant by design."** The proposal states whether section 11 PAngV
   applies (30-day lowest price) or the perishables exemption is used, and
   updates POS and shelf from the same event so they never diverge.
5. **"Against food waste, not against the customer."** Markdowns on
   near-expiry or slow-moving items and a voucher for the next visit; no
   surge pricing. Matches what Lidl/Albert Heijn actually do and defuses
   the "Flatterpreise" concern.
6. **"Fair-speed AI."** The visitor sees the effect within the visit (next
   scan, next receipt), not in a weekly price run.

### 5.4 Design implications from the research (for the design tracks)

- **Use the Bonshooter as the scan source** (ASSUMPTION, needs GEBIT OK): it
  already draws crowds and generates realistic scan bursts. Because it can
  produce several scans per second, do not run one LLM workflow per scan:
  aggregate deterministically (counts, sell-through vs. stock, expiry,
  active promotions) in a tool node or stream processor and trigger the
  agent only on thresholds or at transaction close. Measured lab latency
  for a 4-node event-triggered workflow is 14-20 s with fast-tier agents
  (given in the task context) and the LiteLLM budget is capped at 50 USD,
  so per-scan LLM calls are neither fast nor affordable (ASSUMPTION).
- **Two time scales on the monitor** (ASSUMPTION): (a) instant, rule-based
  live ticker per scan (milliseconds, no LLM); (b) agent insight/proposal
  every N scans or per closed receipt (15-20 s, LLM), (c) approval and the
  "next scan uses the new price" moment.
- **Approval as an event**, not an in-workflow HIL pause, because
  non-interactive triggers cannot answer `input-required` (see 3.3).
- **Voucher at PurchaseTransactionClosed** is the natural "waits for the
  final closing event" moment and maps to GEBIT Loyalty Management and
  eReceipt in the live phase.
- **ESL optional but valuable**: EHI says ESL extras are rarely used; a
  flashing/LED ESL highlighting the approved markdown shows "beyond price
  display". GEBIT has no ESL partner listed - consider borrowing a label
  and access point from Hanshow, SOLUM, Pricer or Vusion (all at EuroCIS),
  or simulate on screen.

---

## 6. Headline facts for the booth monitor or flyer

Pick 3-5. Each line: suggested wording (DE / EN), then the source.

1. **10.9 Mio. Tonnen Lebensmittel landen in Deutschland jaehrlich im
   Abfall - 129 kg pro Kopf; rund 7 % davon im Handel.**
   EN: Germany wastes 10.9 million tonnes of food a year (129 kg per
   person); about 7 % happens in retail.
   Source: Umweltbundesamt, data year 2023, page updated 2025-10-27,
   <https://umweltbundesamt.de/themen/abfall-ressourcen/abfallwirtschaft/abfallvermeidung/lebensmittelabfaelle>
   (VERIFIED, page). Retail ~762,000 t per Thuenen evaluation (VERIFIED,
   snippet). Target: halve food waste by 2030 (national strategy, SDG
   12.3); EU target -30 % per capita in retail and households by end 2030
   (same UBA page).
2. **91 % der Lebensmittelhaendler setzen elektronische Preisschilder ein -
   meist nur, um Preise anzuzeigen.**
   EN: 91 % of food retailers already use electronic shelf labels - mostly
   just to display prices.
   Source: EHI Technologie-Trends im Handel 2025 (n = 119 CIOs, DACH),
   <https://www.ehi.org/wp-content/uploads/Downloads/Leseproben/Technologie_Trends-2025_Leseprobe_06-03-2025.pdf>
   (VERIFIED, page).
3. **100 % der Handels-CIOs nennen KI als Top-Trend - aber 2 von 3 Haendlern
   bewerten ihre Datenintegration als schlecht.**
   EN: Every retail CIO names AI the top trend - yet two in three retailers
   rate their data integration as poor.
   Sources: EHI Technologie-Trends 2025 (100 %, 92 % use AI) and EHI AI study
   2025 via iXtenso (67 % poor/relatively poor),
   <https://ixtenso.com/euroshop-2026/artificial-intelligence-from-technological-hype-to-strategic-reality-in-retail.html>
   (VERIFIED, page). Good bridge to "event mesh first, then agents".
4. **Alle 15 Minuten: So oft prueft Albert Heijn Abverkaeufe - bis zu 4
   Preissenkungen pro Artikel und Tag, rund 250 Tonnen weniger
   Lebensmittelabfall pro Jahr.**
   EN: Albert Heijn checks sales every 15 minutes and may cut a price up to
   four times a day - saving about 250 tonnes of food waste a year.
   Source: Wall Street Journal, 2025-07-27, via
   <https://www-web.itiger.com/news/2554541749> (VERIFIED, page summary).
   ASSUMPTION: cite "WSJ, July 2025" on the flyer; verify the original
   before print.
5. **Ab dem naechsten Scan: Freigabe am Tablet, neuer Preis an der Kasse -
   in Sekunden statt in der naechsten Preisrunde.**
   EN: Approve on the tablet, the new price applies from the next scan.
   Source: our own measured booth number (ASSUMPTION until measured);
   supported by GEBIT's claim that Pricing & Campaign Management is
   synchronised across channels in milliseconds
   (<https://www.gebit.de/en/solutions>, VERIFIED, page).

Reserve facts:

- REMA 1000 (Norway): up to 100 price changes per store per day (WSJ,
  2025-07-27; VERIFIED, page summary).
- Lidl: ESL in all 3,250 German stores for fruit, vegetables and promotions
  (LZ 2024; VERIFIED, page caption).
- Vusion: more than 375 million electronic shelf labels on its cloud at the
  end of 2025 (FY2025 release; VERIFIED, page).
- dm on Solace: about 100 million events per day at ~10 ms (retail-optimiser
  2025-12-12; VERIFIED, page).
- GEBIT: 110,000+ POS systems in 32+ countries (homepage; VERIFIED, page).
- Pricing lever: a 1 % price improvement lifted operating profit by 11.1 %
  across 2,463 companies (HBR 1992, McKinsey authors; VERIFIED, snippet).
  Old and cross-industry - use only in a talk, not on the flyer.
- 54 % of EuroCIS visitors are decision makers (EuroCIS 2025 KPIs;
  VERIFIED, page) - for internal booth staffing, not for the flyer.

---

## 7. Risks

- **"Dynamic pricing" backlash**: German consumer advocates warn about
  "Flatterpreise"; dm guarantees prices for four months; US union campaigns
  push bans. Mitigation: frame as markdown/anti-waste plus loyalty voucher,
  show PAngV check and human approval.
- **Crowded ESL/pricing field**: Vusion, Hanshow, SOLUM, GK, 7Learnings
  will have larger, flashier booths. Mitigation: differentiate on live POS
  events + approval + closed loop; borrow one ESL rather than compete on
  ESL walls.
- **Latency vs. attention span**: 14-20 s agent workflows are long on a
  trade-fair floor. Mitigation: instant rule-based ticker plus delayed
  agent card; pre-warm; keep agent nodes few and fast-tier.
- **Cost / budget**: LiteLLM hard cap at 50 USD; Bonshooter bursts would
  multiply calls. Mitigation: deterministic aggregation, thresholds,
  per-receipt triggering, caching, a "demo budget meter" internally.
- **Live-switch uncertainty**: GEBIT's price-change event to the article
  master data service is not yet specified; internal eventing (Solace vs
  other) of the Purchase Service is not public; mid-transaction price
  semantics unknown.
- **Reference usage**: retailer names (dm, Kaufland, EDEKA, ALDI SUED) on
  booth material need consent; some are competitors of each other.
- **Privacy for personalised vouchers**: loyalty data use is under legal
  scrutiny (vzbv vs Lidl Plus pending at the BGH). Use pseudonymous demo
  personas, no real visitor data; if visitors scan a QR, keep consent
  explicit.
- **Source quality**: several market numbers come from vendor claims or
  search snippets (marked); verify before printing (especially the WSJ
  numbers and the ALDI SUED 25 M figure).
- **Timeline**: 98 days to opening; Christmas period in between; GEBIT
  demo-lab access and booth logistics (power, network, ESL access point,
  radio regulations on the fair floor) must be clarified early.

---

## 8. Open questions

For GEBIT:

1. Will the showcase run on GEBIT's EuroCIS 2027 stand (hall/stand?), on a
   Solace stand, or jointly? Space, power, network, screens available?
2. Can the Bonshooter (or the planned second machine) feed its scans into
   the Purchase Service / our event stream? What scan rate and article
   catalogue does it use?
3. Which broker carries Purchase Service events internally today (Solace
   Event Mesh as stated publicly, Kafka, other)? Topic naming conventions?
   Can the demo lab publish to a Solace VPN we control?
4. Exact command/event for the price change to the article master data
   service; latency until the POS uses it; does an open transaction keep
   the old price, and what happens to positions already added?
5. Which ESL (vendor, access point) is available in the GEBIT demo lab, if
   any? Is an ESL integration adapter part of the platform?
6. Can GEBIT Loyalty Management / Campaign Management issue a voucher via
   API at PurchaseTransactionClosed, and can it appear on the eReceipt?
7. Should the approval click live in the GEBIT Attendant App / Operations
   Suite for the live phase?
8. Which customer names may be shown (dm, Kaufland, SPAR ICS, EDEKA,
   ALDI SUED, DEICHMANN, OBI)?
9. Is the "event-based microservice architecture" wording still the
   official positioning (it disappeared from the current website)?

For the owner / Solace:

1. Is Solace exhibiting at EuroCIS 2027 at all, or only via GEBIT?
2. Is joint marketing (press release, flyer with both logos) planned and
   approved, building on the Oct 2026 partnership posts?
3. Framing decision: "Markdown and voucher agent against food waste" vs
   "dynamic pricing agent" - recommendation is the former.
4. ESL: borrow from an ESL vendor (Hanshow, SOLUM, Pricer, Vusion) or
   simulate on screen?
5. Budget for LLM usage over three fair days beyond the lab's 50 USD cap?
6. Which headline facts go on the flyer, and who verifies them for print?

---

## 9. Source index (all accessed 2026-11-10)

EuroCIS / EuroShop:

- <https://www.eurocis-tradefair.com/>
- <https://www.eurocis-tradefair.com/en/visit/what-to-expect/reasons-to-attend>
- <https://www.eurocis-tradefair.com/en/exhibit/good-reasons-to-attend-eurocis>
- <https://www.eurocis-tradefair.com/en/Media_News/Press/Press_material/Press_releases/Smart,_secure,_connected_%E2%80%93_EuroCIS_2025_shows_the_future_of_retail_technology>
- <https://www.eurocis-tradefair.com/en/EuroCIS_Newsletter_2025_02_20>
- <https://lebensmittelpraxis.de/handel-aktuell/43282-handelstechnologie-messe-eurocis-2025-lockt-ueber-14-000-fachbesucher-nach-duesseldorf.html>
- <https://www.euroshop-tradefair.com/en/media-news/news/newsticker/eurocis-goes-euroshop>
- <https://www.diyinternational.com/content/news/2026/02/27/free/euroshop-2026-maintains-visitor-and-exhibitor-numbers.html>
- <https://www.technologyrecord.com/article/euroshop-spotlights-retails-digital-future-at-record-international-gathering>
- <https://www.technologyrecord.com/article/eurocis-2026-showcasing-innovations-that-address-real-challenges-in-retail>
- <https://invidis.com/news/2026/02/dusseldorf-2026-euroshop-draws-81000-visitors/>
- <https://euro-security.de/en/ehi-honours-innovative-technology-solutions-in-retail>
- <https://retailtechinnovationhub.com/home/2026/2/24/german-fashion-retailer-landt-bags-reta-awards-2026-award-for-work-with-vusion-and-gk-software>
- <https://www.iads.org/member/books-conferences/euroshop-2026-75ccf>
- <https://ixtenso.com/euroshop-2026/artificial-intelligence-from-technological-hype-to-strategic-reality-in-retail.html>
- <https://www.hanshow.com/en/news/hanshow%E2%80%99s-unified-solutions-boost-retail-efficiency-and-customer-experience-at-eurocis-2025>
- <https://www.solum-group.com/solum/press-release-detail.solum-and-competera-expand-partnership-to-integrate-ai-driven-pricing-solutions-with-real-time-esl-execution-across-europe>
- <https://www.gk-software.com/us/corporate-news-and-press-releases/en-press-release-20260112-euroshop>
- <https://tradefest.io/en/event/eurocis>

GEBIT:

- <https://www.gebit.de/en/homepage>
- <https://www.gebit.de/en/company/about-gebit>
- <https://www.gebit.de/en/company/news>
- <https://www.gebit.de/en/company/events>
- <https://www.gebit.de/en/company/partnerships>
- <https://www.gebit.de/en/solutions>
- <https://www.gebit.de/en/solutions/gebit-retail-platformr>
- <https://www.gebit.de/en/solutions/pricing>
- <https://www.gebit.de/en/solutions/campaign-management>
- <https://www.gebit.de/en/solutions/loyalty-management>
- <https://www.gebit.de/en/solutions/gebos>
- <https://www.gebit.de/en/solutions/attendant-app>
- <https://www.gebit.de/en/solutions/digital-receipt-ereceipt>
- <https://www.linkedin.com/feed/update/urn:li:activity:7513923086665224193>
- <https://www.linkedin.com/feed/update/urn:li:activity:7513929448870699008>
- <https://de.linkedin.com/posts/gebit-solutions-gmbh_gebit-solutions-innovation-insights-3-warum-activity-7500455041665789952-YIGu>
- <https://www.esmmagazine.com/technology/gebit-solutions-where-retail-performance-becomes-visible-314753>
- <https://www.lebensmittelzeitung.net/tech-logistik/nachrichten/Kaufland-will-mit-Gebit-kassieren-107512>
- <https://www.cio.de/article/3669037/aldi-sued-setzt-neue-kassenloesung-ein.html>
- <https://retail-optimiser.de/en/tag/gebit-en>

Solace:

- <https://solace.com/industries/retail>
- <https://solace.com/products/agent-mesh>
- <https://solace.com/press-center/hornbach-redefines-retail-innovation-with-solaces-platform/>
- <https://retail-optimiser.de/en/dm-is-very-pleased-with-solace/>
- <https://www.casestudies.com/company/solace/case-study/les-mousquetaires-customer-case-study>
- <https://www.casestudies.com/company/solace/case-study/schwarz-group-customer-case-study>
- <https://salestechstar.com/sales-intelligence/german-supermarket-chain-edeka-uses-solace-technology-to-stream-master-data-across-their-stores-and-supply-chain/>
- <https://solace.com/blog/retail-event-mesh-eda-ai/>
- Local SAM docs: `scratchpad/samdocs/concepts__a2a-protocol.md:110,127`,
  `scratchpad/samdocs/using-agent-mesh__scheduled-tasks.md:96`

ESL, pricing, food waste, loyalty, regulation:

- <https://www.ehi.org/wp-content/uploads/Downloads/Leseproben/Technologie_Trends-2025_Leseprobe_06-03-2025.pdf>
- <https://s203.q4cdn.com/882900163/files/doc_financials/2025/q4/Vusion_PR_FY-2025-Results_vUK.pdf>
- <https://retail-optimiser.de/en/dm-aims-for-real-time-shelf-insights-with-vusiongroup/>
- <https://retail-optimiser.de/en/aldi-sued-introduces-esls-from-hanshow>
- <https://www.lebensmittelzeitung.net/tech-logistik/nachrichten/electronic-shelf-labels-digitale-regalpreis-etiketten-setzen-sich-durch-176195>
- <https://www.lebensmittelzeitung.net/tech-logistik/nachrichten/rollouts-bei-discountern-digitale-preisschilder-werden-standard-in-deutschland-175108>
- <https://iotm2mcouncil.org/iot-library/news/smart-retail-news/hanshow-boosts-esl-to-real-time-performance/>
- <https://www.pricer.com/press-release/pricer-esl-platform-breakthrough-quadruples-communication-speed-with-existing-infrastructure>
- <https://www.pricer.com/news/albert-heijn-combats-food-waste-with-pricer-and-wasteless-through-ai-powered-dynamic-pricing>
- <https://www-web.itiger.com/news/2554541749>
- <https://www.pymnts.com/?p=2865300>
- <https://today.ucsd.edu/story/new-research-debunks-fears-of-supermarket-surge-pricing-with-electronic-shelf-labels>
- <https://revionics.com/blog/revionics-multi-agent-pricing-system-is-now-ga-heres-what-that-means-for-retail>
- <https://www.omniaretail.com/agentic-pricing>
- <https://agritechobservatory.review.fao.org/en/wasteless>
- <https://www.fooddive.com/news/food-waste-reduction-tech-afresh-funding/629092/>
- <https://retail-news.de/payback-rekordbilanz-nutzer-2025/>
- <https://www.retaildetail.eu/news/food/lidl-plus-reaches-120-million-users-following-global-rollout/>
- <https://retail-news.de/olg-stuttgart-klage-abgwiesen-lidl-plus-app-vzbv/>
- <https://www.gesetze-im-internet.de/pangv_2022/__11.html>
- <https://umweltbundesamt.de/themen/abfall-ressourcen/abfallwirtschaft/abfallvermeidung/lebensmittelabfaelle>
- <https://lebensmittelpraxis.de/handel-aktuell/42331-nachhaltiger-konsum-handel-reduziert-lebensmittelabfaelle-um-ein-viertel.html>
- <https://www.vzhh.de/themen/lebensmittel-ernaehrung/einkaufsfalle-supermarkt/dynamic-pricing-digitale-preisschilder-flatterpreisen>
- <https://www.handwerksblatt.de/betriebsfuehrung/registrierkassenpflicht-ab-2028-soll-kommen>
