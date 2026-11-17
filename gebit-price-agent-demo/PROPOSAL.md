# EuroCIS 2027: Preis- und Aktionsagent mit Freigabe

Recherche, Analyse und Vorschlag für einen ersten Entwurf. Showcase
von GEBIT und Solace auf der EuroCIS, Messe Düsseldorf,
16.–18.02.2027.

- Stand: 10.11.2026. Lab: Solace Agent Mesh 2.542.1 (seit heute).
- Dieses Dokument ist die Entscheidungsvorlage. Die vollständige
  Spezifikation (Choreografie im Sekundentakt, YAML, DDL, Topics,
  MCP-Tools, Plan, Stückliste) steht in [DESIGN.md](DESIGN.md).
- Markierungen: **[V]** in der Recherche belegt, **[A]** Annahme,
  **[G0]** wird im Gate 0 (11.–20.11.2026) gemessen.
- Veröffentlichung: GEBIT hat schriftlich zugestimmt (vom Owner am
  17.11.2026 bestätigt): API-Details in eigenen Dokumenten und eigenem
  Code dürfen veröffentlicht werden. GEBIT-Dateien (Deskriptor-Sets,
  API-Doku, Beispielereignisse, Mail) kommen nie ins Repo. Die
  Rechercheberichte, die drei Entwürfe und die Jury-Bewertungen liegen
  in `research/`.

---

## Auf einen Blick

**Die Empfehlung:** ein Showcase, eine Geschichte, ein Held –
**„Ein Tipp. Neuer Preis.“**

1. Ein Besucher scannt die GEBIT Ente. Die Kasse zeigt die Zeile in
   0,3 s, der Monitor nach 0,5 s den roten Regel-Chip „Ladenhüter:
   5 statt 15 verkauft“ und nach 1,5 s den Vorschlag mit Zahlen.
2. Ein zweiter Scan (Espresso) überbrückt die KI. Nach 6–9 s steht
   ihre Begründung da: „-20 %, weil am Freitag 24 weitere Enten
   kommen“.
3. Der Besucher wechselt die Seite und ist jetzt Marktleitung. Wer
   -30 % probiert, sieht die Mindestmarge rot, und Freigeben sperrt.
4. Ein Tipp auf **Freigeben**: Etikett, Topper und Monitor kippen in
   unter 6 s auf 6,89 € statt 8,67 €, mit der 30-Tage-Zeile.
5. Die erste Ente wird storniert und neu gescannt: Sie kostet jetzt
   6,89 €. Nach „Bar (Demo)“ steht „Verkauf final“ da, nach
   höchstens 2 s gibt es den Gutschein-QR, und der Besucher nimmt die
   Ente mit.

**Warum das trägt:**

- Express in 75 s, geführt in 3 Minuten. Nirgends wartet ein
  Besucher länger als etwa 5 s ohne sichtbaren Fortschritt.
- Die Idee „ein SAM-Workflow bei jedem Kassenereignis“ wird wörtlich
  umgesetzt und bleibt bezahlbar. Der Monitor zählt es mit:
  „13 Kassenereignisse → 13 SAM-Läufe → 1 KI-Aufruf“.
- „Die KI entscheidet nicht allein“ ist wörtlich wahr. Kein
  Regalpreis sinkt ohne Tipp; nur der beschriftete Reset zwischen zwei
  Besuchen stellt 8,67 € wieder her. Die Freigabe ist ein signiertes
  Ereignis, das einen Workflow ganz ohne KI startet.
- Neu seit dem Lab-Update auf SAM 2.542.1: Der
  Benachrichtigungsdienst läuft. Jeder Vorschlag kann zusätzlich in
  der SAM-Inbox der Laufidentität `power_user` landen, gezeigt in der
  Tiefenecke (nach Test G0-16 und einer RBAC-Ergänzung).
- GEBIT ist heute komplett simuliert, aber im echten GEBIT-Vertrag:
  Purchase API 2.50.0 mit echten Ereignisnamen. Ins GEBIT-Labor
  wechseln wir per Konfiguration plus eine Adapter-Komponente; den
  Preis-Rückweg muss GEBIT noch festlegen (unser v0-Vorschlag), bis
  dahin bleibt der Preis im Simulator.
- Compliance by design: 30-Tage-Tiefstpreis, abgerundete
  Prozentangaben, MHD-Grund auf dem Etikett, keine Personendaten,
  „DEMO – kein Kassenbeleg“.

**Rahmen:**

- Aufwand: etwa 85 Personentage auf Solace-Seite (plus etwa 6 für
  Versand, Aufbau und Abbau), dazu 10–15 bei
  GEBIT. Mit zwei Entwicklern passt das bis zum Freeze am 05.02.2027;
  G1 und G2 sind knapp, der Puffer liegt nach den Feiertagen.
- Host und Hardware: Der Host auf der Messe ist eine bereitgestellte
  Cloud-Instanz, der Stand hängt per WireGuard-Tunnel daran.
  Kassenhardware, Monitore und die übrige Standtechnik sind vorhanden;
  bestellt wird nur, was nach der Inventur fehlt.
- LLM-Kosten für die ganze Messe inklusive Proben: etwa 15–35 USD.
- Nächste Schritte: bis 13.11. die Inventur der Standtechnik, die
  Details der Cloud-Instanz und die Fragen an GEBIT; bis 20.11. der
  LiteLLM-Messe-Key; zum Start von Gate 0 (11.–20.11.2026) die zwei
  freigegebenen Lab-Änderungen.

---

## 1. Auftrag und Vorgehen

### 1.1 Auftrag

Gemeinsam mit GEBIT entsteht für die EuroCIS 2027 ein Showcase
„Preis- und Aktionsagent mit Freigabe“. Die Wünsche:

- POS-Abverkauf, Bestand, Aktionen und Loyalty als Auslöser.
- Auf dem Monitor erkennt ein Agent Ladenhüter, Kaufverhalten oder
  Aktionen und schlägt eine Abschrift oder Aktion vor.
- Ein Mitarbeiter gibt mit einem Klick frei. Ab dem nächsten Scan
  gilt der neue Preis, optional auch auf einem elektronischen
  Preisschild (ESL).
- Plattform: Solace Agent Mesh im lokalen Cluster und die POS der
  GEBIT Retail Platform. Loyalty und weitere Systeme liegen in einer
  Datenbank (Postgres, eine Vektor-DB nur wenn sinnvoll).
- Heute gibt es keinen POS- oder API-Zugang. Alles wird simuliert;
  später wird im GEBIT-Demo-Labor live geschaltet.
- Ideen: jeden Scan live verfolgen; ein SAM-Workflow pro Ereignis;
  Erkenntnisse und Vorschläge als Benachrichtigung in SAM; menschliche
  Freigabe, wo nötig; Live-Aktionen pro Artikel; beim Bezahlen auf
  den finalen Bon warten und einen Gutschein ausgeben.
- Maßstab: verständlich, nachvollziehbar, ohne lange Wartezeiten,
  einfach, aber überzeugend.

### 1.2 Vorgehen

1. **Recherche in acht Strängen:** GEBIT Purchase API, GEBIT Receipt
   API, Fähigkeiten von SAM im Lab, Muster aus diesem Repo (vor allem
   das BSG-Demo), Markt, Recht, Messe-UX und Preis-KI. Ein
   Vollständigkeitskritiker hat Widersprüche zwischen den Strängen
   aufgelöst und Lücken benannt.
2. **Drei unabhängige Entwürfe:** A „Besuchererlebnis zuerst“,
   B „GEBIT-Vertrag zuerst“, C „Agentische Tiefe“. Drei Jurys haben
   sie bewertet: Stand und Besucher, Technik, Fachlichkeit und Recht.
3. **Synthese:** A ist das Rückgrat, dazu kommen gezielt Ideen aus B
   und C, und alle Jury-Korrekturen sind eingearbeitet. Danach folgte
   der Abgleich mit dem Lab-Update auf SAM 2.542.1 vom selben Tag.
4. **Gegenprüfung:** Vier unabhängige Prüfer haben das Ergebnis aus
   vier Blickwinkeln angegriffen, jeweils mit einem Gegenprüfer
   (Abschnitt 9).

Grundlagen waren unter anderem GEBITs Descriptor-Sets und die elf
Beispielereignisse eines einfachen Verkaufs, die SAM-Doku und das
Konfigurationsschema der CLI 2.542.1, die laufende Lab-Installation,
die Messungen aus dem BSG-Demo sowie Primärquellen zu PAngV,
Rechtsprechung und Markt. Die Quellen stehen in DESIGN.md.

---

## 2. Recherche: Was wir herausgefunden haben

### 2.1 GEBIT Purchase API 2.50.0

- Befehle laufen synchron per gRPC, Ereignisse asynchron als
  Protobuf. Die API hat 106 Methoden (102 Befehle, 4 Abfragen) und
  114 Ereignisse, 110 davon gehören zu `PurchaseDomainEvents`. Der
  Transport der Ereignisse ist nicht dokumentiert; das ist Frage 1 an
  GEBIT [V].
- Neben den feingranularen Ereignissen gibt es grobgranulare
  (`PurchaseTransactionChanged`, `PurchaseTransactionFinalized`).
  Welche Familie das Labor sendet, ist Teil von Frage 1 [V].
- Ein Scan ist `AddArticle` → `PositionAdded`. `AddArticle` gibt
  nichts zurück; die `positionId` kommt erst mit dem Ereignis.
  Storno- und Mengenereignisse tragen nur die `positionId`, deshalb
  hält die Engine eine Zuordnung `positionId → Artikel` [V].
- **Finalität:** Alle Ereignisse sind vorläufig, bis
  `PurchaseTransactionClosed` kommt. Dieses Ereignis trägt den ganzen
  Bon. `PurchaseTransactionCancelled` heißt: nichts verkauft. Im
  Beispiel liegen 0,45 s zwischen `PaymentProcessStarted` und
  `Closed`, der ganze Verkauf dauert 1,12 s [V].
- **Kein Befehl für den Regalpreis:** Ohne
  `supplied_price_information` kommt der Preis aus dem Artikelstamm
  (der Beispiel-Bon zeigt `priceSource: freezePrice`, Bedeutung offen).
  Es gibt nur zeilenbezogene Kassierbefehle wie
  `OverrideArticlePositionPrice`. Eine befristete Aktion gehört in den
  Promotion-Service, der Bon zeigt sie als `positionDiscounts`. Den
  Rückweg vom Agenten zum Preis muss GEBIT noch definieren; wir
  schlagen einen v0-Vertrag als AsyncAPI vor [V].
- **Nützliche Haken:**
  - `extensionProperties` laufen bis in Ereignis und Bon, also kann
    die Vorschlags-ID mitlaufen.
  - `header.approver` und `approvals[]` im Bon bilden Freigaben von
    Kassenbefehlen ab (ob automatisch, ist eine Frage an GEBIT). Die
    Regalpreis-Freigabe ist kein Kassenbefehl und steht dort nicht.
  - `AddArticle.supplied_price_information` erlaubt einen Preis von
    außen.
  - `ApplyAnonymousCoupon` löst Gutscheine ein.
  - Der Bon hat einen Platz für Gutscheine
    (`loyaltyPurchaseResult.checkoutCoupons[]`), aber keine API, die
    ihn füllt. Der Gutschein wird deshalb digital [V].
- Den Ort (`Root.DE.999.101.01`) tragen nur `Created`, `Recovered`,
  die Mesh-Ereignisse, manche Zahlungsereignisse (`clientId`, im
  Beispiel nur die Wechselgeldzeile) und der Bon in `Closed`, nicht
  aber `PositionAdded` und die meisten anderen. Deshalb hält `gpos-pos`
  einen Cache `txId → Ort`. Geldbeträge sind `BDecimal`, im Bon
  `Decimal`. Der Beispiel-Bon hat Version 2.14.0-I114, die Doku
  2.13.0. Die Fiskaldaten im Beispiel stammen aus einem Simulator [V].
- Missverständnisse vermieden: Die „action“-Protos sind
  Abschlussaktionen, keine Werbeaktionen. Die „mesh“-Protos
  beschreiben ein Kassen-Mesh, nicht das Solace Event Mesh [V].

### 2.2 Solace Agent Mesh im Lab

- Der Event-Mesh-Entrypoint startet Workflows per Namen, etwa 22 ms
  nach dem Publish. Läufe starten nebenläufig (zwei Läufe lagen 2 ms
  auseinander), deshalb ordnet die Engine nach `offset` [V].
- Knotentypen: agent, tool, switch, map, loop, workflow und decision.
  Ein decision-Knoten braucht ein Decision-Modell, das das Lab nicht
  hat. Es gibt **keinen Warte-Knoten und keinen Freigabe-Knoten** [V].
- **Gemessen:** Ein Tool-Knoten braucht 0,12–1,4 s, ein Agentenknoten
  auf dem fast-Modell 4,9–6 s. Der BSG-Workflow mit mehreren Agenten
  braucht 14–22 s (auf 2.542.1: 18,9–23,1 s). Deshalb darf der
  Heldenpfad höchstens einen Agentenaufruf enthalten [V].
- MCP-Regeln: eine explizite `manifest:`-Liste; Antworten über
  2048 Byte werden zu Artefakten; strukturierte Felder gibt es nur mit
  Pydantic-Rückgaben [V].
- **Freigabe:** `ask_user_question` liefert auf Event-Mesh-Kanälen
  einen Fehler und gehört laut Doku nicht an Workflow-Agenten.
  Tool-Freigaben enden in ereignisgetriggerten Läufen als Ablehnung.
  Eine native Ein-Klick-Freigabe am Stand gibt es also nicht [V].
- **Neu in 2.542.1 (seit heute im Lab):**
  - Der Benachrichtigungsdienst (Early Access) läuft: Inbox in der
    SAM-UI; Teams oder Slack bräuchten einen eigenen Entrypoint, den
    das Lab nicht hat. Das gwe-Log bestätigt den Start.
  - `notify_user` schickt ohne Rückfrage eine Nachricht; ein
    Tool-Knoten darf es ohne LLM aufrufen. Die Laufidentität braucht
    dafür den Scope `notify:_:send`, den im Lab keine Rolle außer
    `sam_manager` hält. Erst mit einer RBAC-Ergänzung
    (Owner-Entscheidung) kommen Vorschläge in die Inbox.
  - Workflow-HIL (Pause und Fortsetzen) läuft laut Konfiguration über
    diesen Dienst, ist aber nicht dokumentiert und hat kein Feld im
    Workflow-Schema. Das misst G0-17, und es ist eine Frage an
    Solace.
  - SAM erfasst jetzt Kosten je Modellaufruf und setzt Monatsbudgets
    durch, allerdings nur für Modelle mit Preisen; im Lab sind alle
    Modelle noch ohne Preis.
  - Der feste Prompt-Präfix ist kürzer: gemessen rund 1.760 Token
    (Release Notes: 3.200).
  - `sam config apply` entfernt jetzt Einstellungen, die nur in der
    UI gesetzt wurden (auch dort eingegebene Secrets); vor dem ersten
    Apply `sam config pull` oder alles in die Dateien übernehmen [V].
- Bekannte Fallen aus dem Lab [V]:
  - Text mit Umlauten aus Agenten kommt verstümmelt an; bis zum
    Gegenbeweis bleibt der Agententext ASCII.
  - Die Datenebene gibt nach etwa 5 Minuten Brokerausfall auf.
  - gwe und awe nie gleichzeitig neu starten.
  - Alte Queues füllen den Spool.
- Broker: VPN `sam` hat keinen MQTT-Listener, MQTT 1883 gibt es nur
  auf VPN `default`. Die Etiketten bekommen deshalb einen
  Doppelpublish [V].
- **LLM:** Der LiteLLM-Proxy hat eine harte Grenze von 50 USD. Das
  fast-Modell ist Haiku 4.5; ein Aufruf kostet etwa 0,005 USD warm und
  0,02 USD kalt. Ein LLM auf jedem Ereignis würde etwa 4–48 USD pro
  Messetag kosten, drei Agenten pro Ereignis wie im BSG-Demo
  24–150 USD. Gating ist also Pflicht [V].

### 2.3 Markt und Partner

- 91 % der Lebensmittelhändler nutzen elektronische Preisschilder,
  meist nur zur Anzeige (EHI 2025) [V]. Unser Unterschied ist der
  geschlossene Kreis vom Kassenereignis zurück an Kasse und Regal.
- In Deutschland landen 10,9 Mio. Tonnen Lebensmittel im Abfall,
  rund 7 % davon im Handel (Umweltbundesamt, Datenjahr 2023) [V].
  Albert Heijn prüft Abverkäufe alle 15 Minuten und senkt bis zu
  viermal am Tag (WSJ, Juli 2025; Original vor Druck prüfen).
- „Dynamic Pricing“ ist in Deutschland negativ besetzt
  („Flatterpreise“). Deshalb das Framing: **Abschriften gegen
  Ladenhüter und Lebensmittelverschwendung, mit Freigabe**. Nur
  Senkungen, ein Regalpreis für alle.
- GEBIT sitzt in Berlin, gibt es seit 1991 und nennt Referenzen wie
  ALDI SÜD, Kaufland, dm, SPAR, DEICHMANN und OBI. Öffentlich
  bekannt: GEBIT nutzt Solace Event Mesh und ergänzt Agent Mesh;
  Solace steht auf GEBITs Partnerseite [V]. Kundennamen kommen nur
  mit GEBITs Freigabe auf Standmaterial.
- Termin: EuroCIS 2027, 16.–18.02.2027 in Düsseldorf [V].

### 2.4 Recht (Kurzfassung, juristische Prüfung bis G4 nötig)

- **§ 11 PAngV:** Bei jeder angekündigten Preisermäßigung muss der
  niedrigste Preis der letzten 30 Tage dabeistehen. Die Prozentangabe
  bezieht sich auf diesen Preis (EuGH C-330/23). Der 30-Tage-Preis
  selbst muss klar erkennbar und gut lesbar sein, eine Fußnote reicht
  nicht (BGH I ZR 183/24) [V]. Wir setzen ihn in denselben Block, auch
  auf dem Monitor.
- **Verderbliche Ware:** Die Ausnahme in § 11 Abs. 4 Nr. 2 greift nur
  bei drohendem Verderb oder Ablauf, und der Grund muss sichtbar sein
  (OLG Nürnberg 3 U 2376/24). Deshalb reduzieren wir nur die
  betroffene Charge [V].
- **Wiederholte Aktionen** senken den Referenzpreis. Deshalb gibt es
  einen Reset pro Besuch statt alle zwei Minuten eine Messeaktion [V].
- Gebundene Angebote („beim Kauf von …“) liegen außerhalb von
  Art. 6a. Gutscheine beim Kauf sind personalisierte Rabatte. Der
  Regalpreis ist für alle gleich [V].
- **§ 20 Abs. 3 GWB:** Händler mit überlegener Marktmacht dürfen
  Lebensmittel nur mit sachlicher Rechtfertigung unter Einstand
  verkaufen, etwa gegen drohenden Verderb oder Unverkäuflichkeit [V].
  Wir wenden die Regel immer an; die Zweitfreigabe ist unsere Policy,
  am Stand gesperrt.
- **EU AI Act:** Ein Preisagent im Handel steht nicht in Anhang III,
  ist also kein Hochrisiko-System [A]. Art. 50 (Transparenz) gilt seit
  02.08.2026 [V]; ohne Chat verlangt er für unsere Vorschlagstexte
  vermutlich keine Kennzeichnung, wir kennzeichnen trotzdem jeden
  KI-Text. Art. 5 (verbotene Praktiken) berührt uns nicht, weil keine
  Personen- oder Verletzlichkeitsmerkmale einfließen [A]. Die Freigabe
  ist freiwillige gute Praxis.
- Fiskal: nur Simulation, „DEMO – kein Kassenbeleg“, kein Fiskal-QR;
  ohne echten Verkauf entsteht vermutlich kein aufzeichnungspflichtiger
  Geschäftsvorfall [A]. Datenschutz: keine Personendaten; die
  öffentliche Handy-Seite braucht Impressum und Datenschutzerklärung.
  Betriebsverfassung (BetrVG § 87 Abs. 1 Nr. 6): Freigebende nur als
  Rolle, keine Auswertung je Person [A].
- Digital Fairness Act: Der Vorschlag wird am 11.11.2026 erwartet und
  wird vor der Messe geprüft. Am B2B-Stand greift die PAngV
  vermutlich nicht; wir zeigen es „so wie in einer deutschen
  Filiale“ [A].

### 2.5 Messe-UX

- Passanten entscheiden aus 3–5 m Entfernung in etwa 10 s. Daraus
  folgen: Headline mit höchstens sieben Wörtern, höchstens drei
  Zonen, Preise in 220–260 px, Text ab 80 px [V].
- Eine Geschichte, ein Heldenmoment, etwas Physisches: die Ente in
  der Hand und das kippende Etikett. Für die Schlange gibt es eine
  Express-Version; realistisch sind 20–25 Hands-on-Besucher pro
  Stunde in der Schlange, über den Tag planen wir 100–160 [A].
- Die LLM-Wartezeit wird überbrückt: deterministische Karte in 1,5 s,
  zweiter Scan, Rollenwechsel, Vorlage nach 12 s [V].
- Eigene Access Points sind in der Halle ohne Genehmigung verboten,
  also ist alles kabelgebunden. E-Paper braucht für einen Teilrefresh
  0,4 s, für einen vollen etwa 5 s. Reale Herstellerintegrationen
  brauchen Sekunden bis etwa 20 Minuten; verbindlich ist der nächste
  Scan [V].

---

## 3. Analyse

### 3.1 Die Wünsche: erfüllt, ehrlich ersetzt oder bewusst gestrichen

| Wunsch | So im Vorschlag | Status |
|---|---|---|
| Jeden Scan live verfolgen | Monitor und Kundendisplay lesen die Rohereignisse direkt (< 0,5 s) | erfüllt |
| SAM-Workflow bei jedem POS-Ereignis | Jedes Ereignis der Standkasse startet `gpos-pos-event`; 0 Token außer im Heldenmoment | erfüllt, wenn der Lasttest G0-4 besteht; Hintergrundkassen nie |
| Erkenntnisse und Vorschläge als Benachrichtigung in SAM | Tablet und Monitor in Echtzeit; zusätzlich per `notify_user` in die SAM-Inbox (2.542.1) | erfüllt nach G0-16 und einer RBAC-Ergänzung; die Inbox von `power_user` informiert, freigegeben wird am Tablet |
| Menschliche Freigabe, wo nötig | Tablet → signiertes Entscheidungsereignis → reiner Tool-Workflow | ehrlich ersetzt; SAM hat keine native Freigabe für Event-Läufe |
| Live-Aktionen pro Artikel | Freigegebene „Aktion -20 % bis Fr.“ ab dem nächsten Scan, an Regal und Kasse | erfüllt |
| Kaufverhalten des Kunden | Der Gutschein folgt dem Korb („Weil eine Ente im Korb lag …“); Kombi-Angebot nur als Reserve | leichteste Form, ohne Profil |
| Beim Bezahlen auf den finalen Bon warten, dann Gutschein | Die Engine hält den Korb; `Closed` startet einen eigenen Lauf, Gutschein in ≤ 2 s; `Cancelled` → nichts | ehrlich ersetzt (kein Warte-Knoten), wirkt wie gewünscht |
| Loyalty und andere Systeme in einer DB | Postgres `gpos`: Stammdaten, Presets, Historie, Gutscheinkatalog | erfüllt; eine Vektor-DB bringt hier nichts |
| Optional ESL | DIY-E-Paper kabelgebunden, Topper, Spiegelkachel auf dem Monitor | erfüllt |
| Später live im GEBIT-Labor | Simulator im GEBIT-Vertrag, Adapter und Overlay | vorbereitet (G3) |

Bewusst gestrichen: Personas und Kundenkarten, ein Chat-Agent, ein
KI-Text im Zahlungspfad, automatische Preisänderungen ohne Klick,
„Rückgängig“ nach der Freigabe und Preiserhöhungen.

### 3.2 Fünf Spannungen und wie wir sie auflösen

1. **KI-Latenz gegen Messetakt.** Ein Agentenaufruf dauert 5–6 s,
   bis zum fertigen Text vergehen 6–9 s. Deshalb kommt die
   deterministische Karte mit Zahlen in 1,5 s, es
   gibt genau einen KI-Aufruf pro Besuch, ein zweiter Scan überbrückt
   die Zeit, nach 12 s greift eine beschriftete Vorlage, und im
   Zahlungspfad gibt es keine KI.
2. **Workflow pro Ereignis gegen Kosten und Last.** Der erste Knoten
   ist ein deterministisches Tool, danach entscheidet eine Weiche. Nur
   der Heldenmoment weckt den Agenten. So kommen pro Besuch etwa 13
   Läufe auf einen KI-Aufruf. Der Lasttest G0-4 belegt 450 Läufe pro
   Stunde, sonst greift der Rückfall auf Schlüsselereignisse.
3. **„Die KI entscheidet nicht allein“ ohne native Freigabe.** Die
   Freigabe ist ein eigenes Ereignis mit HMAC auf den Hash des
   Vorschlags. Beim Ausführen prüft das Tool die Leitplanken mit
   frischem Zustand neu. Läuft ein Vorschlag ab, ändert sich nichts.
4. **Wiederholte Demo gegen die 30-Tage-Regel.** Jeder Besuch ist ein
   frischer simulierter Nachmittag (Reset pro Besuch, Chip
   „Simulierte Filiale“). Das Etikett zeigt beim Reset „Neue Runde –
   Simulation“, nie eine unerklärte Preiserhöhung.
5. **Simulation gegen Glaubwürdigkeit.** Der Simulator spricht GEBITs
   Vertrag (Descriptor-Sets, echte Ereignisnamen), eine
   Vertragsprüfung zählt mit („100 % gültig“), und die Badges sind
   ehrlich. Wir sagen nie „echte Daten“ oder „live auf GEBIT“.

Zusätzlich der Einwand „Die KI ist nur Dekoration“: Die KI liest eine
Freitext-Filialnotiz („Lieferavis: Freitag nach Ladenschluss kommen
24 weitere Enten“)
und begründet damit sichtbar ihre Wahl. In der Tiefenebene T3 rät sie
mit Begründung sogar von der Aktion ab, die die Regeln empfehlen.

### 3.3 Drei Entwürfe im Vergleich

| Entwurf | Idee | Stand | Technik | Fach | Summe |
|---|---|---|---|---|---|
| **A Besuchererlebnis zuerst** | eine Heldensequenz, schlanker Fußabdruck, Watchdogs | 86,5 | 82 | 71 | **239,5** |
| B GEBIT-Vertrag zuerst | gRPC-Simulator aus GEBITs Deskriptoren, Ports, Vertragsprüfung | 68 | 74 | 77 | 219 |
| C Agentische Tiefe | Autonomiestufen, KI-Beleg, Evaluationen, Red-Team | 68 | 60 | 81 | 209 |

- **Warum A:** Nur A besteht den 10-Sekunden-Test, hat die kleinste
  Fehlerfläche (3 Deployments, 2 Workflows, 1 Agent) und ruft im
  Zahlungspfad keine KI. B überfrachtet den Besuch, C ist fachlich am
  stärksten, auf dem Stand aber zu komplex.
- **Aus B übernommen:** gRPC-Simulator mit Gateway (gleicher
  Befehlsweg für Simulator und GEBIT), Preis-Port mit v0-Vertrag und
  Rückfallkette, Vertragsprüfung, Kustomize-Overlays, kabelgebundener
  7,5"-Topper, Hintergrundkassen als Bild für „SAM hört nur die
  Standkasse“, am Stand einlösbarer Gutschein.
- **Aus C übernommen:** Headline „KI schlägt vor. Regeln prüfen. Sie
  entscheiden.“, KI-Beleg, HMAC-Token, Storno der ersten Ente vor dem
  Neuscan, Tiefenebene (Preisbindung, Referenzpreis-Falle, Agent
  überlisten), ein Evaluations-Experiment als Regressionsschranke,
  Rollout-Pfad als Folie.
- **Neu in der Synthese:** Preispunkt 6,89 € mit exakt „-20 %“,
  Ausführung als befristete Aktion über den Promotion-Weg, Gültigkeit
  gleich Wirkungshorizont, chargengenaue MHD-Abschrift, Freitextnotiz
  als sichtbarer Mehrwert der KI, servergerenderte Etiketten-Bitmaps
  (das Euro-Zeichen fehlt in ISO-8859-1).

---

## 4. Der Vorschlag

### 4.1 Architektur

```text
 Stand-LAN (kabelgebunden, WireGuard-Tunnel zur Cloud-Instanz)
   Scanner -> /kasse   Tablet /freigabe   Monitor /monitor   ESP32-Etiketten
                     \        |              /                  ^ MQTT (VPN default)
                      v       v             v                   |
 Cloud       gpos-ui (BFF, SSE) <-> gpos-engine (Zustand, Regeln, MCP) -> Postgres gpos
                      ^                 ^  MCP-Tools
                      |                 |
             gpos-pos (Kassensimulator, GEBIT-Vertrag) --Ereignisse--> solace-1 VPN sam
                                                                          |
             SAM 2.542.1: Entrypoint gpos-booth-events (2 Regeln) --------+
                          Workflows gpos-pos-event, gpos-apply-decision
                          Agent gpos-pricing-writer (fast) -> LiteLLM
```

- **`gpos-pos`:** Kassensimulator mit gRPC-Teilmenge aus GEBITs
  Deskriptoren; Ereignisse als GEBIT-proto3-JSON; Hintergrundkassen;
  später der Adapter zum GEBIT-Labor.
- **`gpos-engine`:** deterministischer Filialkern mit Korbzustand,
  Finalität, Signalen, Preisstufen, Leitplanken, Vorschlägen,
  Gutscheinen, Watchdogs und Etiketten-Rendering; stellt sechs
  MCP-Tools für SAM bereit.
- **`gpos-ui`:** BFF mit SSE und den Seiten `/monitor`, `/freigabe`,
  `/kasse`, `/kunde`, `/etikett` und `/op`. Er signiert Entscheidungen;
  der Browser bekommt keine Broker-Zugangsdaten.
- **SAM:** ein Event-Mesh-Entrypoint mit zwei Regeln (Rohereignisse
  der Standkasse; Entscheidungen), zwei Workflows, ein Agent auf dem
  fast-Modell, ein MCP-Connector mit generiertem Manifest.
- **Host:** Auf der Messe läuft alles auf einer bereitgestellten
  Cloud-Instanz mit demselben Stack wie im Lab (k3s, SAM 2.542.1,
  Broker, Postgres). Der Router am Stand hält einen WireGuard-Tunnel
  dorthin, über Kabel und 5G. Fällt beides aus, übernimmt das
  Lab-MacBook am Stand als lokaler Notbetrieb (DESIGN.md 4.8).

### 4.2 Wer macht was

| Schritt | Wer | Label am Monitor |
|---|---|---|
| Ereignis aufnehmen, Korb, Finalität | Engine (SAM-Tool) | Kasse / Regel |
| Ladenhüter erkennen, Preisstufen und Rohertrag rechnen, Leitplanken prüfen | Engine (SAM-Tool) | Regel |
| Stufe A oder B wählen, Filialnotiz lesen, Begründung schreiben | Agent `gpos-pricing-writer` | KI |
| KI-Text prüfen (Zahlen, Länge, Stufe) | Engine (SAM-Tool) | Regel |
| Freigeben, anpassen, ablehnen | Besucher als Marktleitung | Mensch |
| Erneut prüfen, Aktion setzen, Etiketten, Gutschein | Engine über SAM-Tool-Knoten | Regel |

Die KI ändert nie den Auslöser, nie die Zahlen und nie die Route. Sie
wählt zwischen vorgeprüften Optionen und schreibt die Begründung.

### 4.3 Ein Lauf pro Kassenereignis

```text
gpos-pos-event:
  assess (Tool) --> route (Weiche)
                      |-- propose --> write (Agent, fast) --> publish (Tool) [--> notify, G0-16]
                      |-- close   --> voucher (Tool)
                      |-- cancel  --> discard (Tool)
                      '-- default --> done (Tool, zählt nur)

gpos-apply-decision:
  apply (Tool: Token prüfen, Leitplanken neu prüfen, Aktion setzen, Audit)
```

- Ein normales Ereignis kostet zwei Tool-Knoten und 0 Token.
- Watchdogs in der Engine (4 s Entwurf, 12 s Text, 3 s Ausführung
  und Gutschein) übernehmen beschriftet, wenn SAM zu langsam ist.
  Kommt das SAM-Ergebnis später doch, wird es als Duplikat verworfen.
- Die Degradationsleiter ist immer beschriftet: L0 live, L1 Text aus
  Vorlage, L2 Direktmodus ohne SAM, L3 lokaler Notbetrieb, L4 Aufzeichnung.

### 4.4 Die Zahlen des Helden

| Stufe | Preis | Absatz bis Fr. | Rohertrag | Marge | Ergebnis |
|---|---|---|---|---|---|
| keine | 8,67 € | 25,5 | 44,5 € | 39,6 % | Basis |
| -10 % | 7,79 € | 31,6 | 49,5 € | 32,8 % | Stufe B |
| **-20 %** | **6,89 €** | **40,4** | **53,3 €** | **24,0 %** | **Stufe A, empfohlen** |
| -30 % | 5,99 € | 42 (ausverkauft) | 26,6 € | 12,6 % | gesperrt: Mindestmarge 20 % |

- 6,89 € liegen 20,5 % unter dem 30-Tage-Tiefstpreis von 8,67 €.
  Angezeigt wird abgerundet „-20 %“; wir versprechen nie mehr Rabatt,
  als wahr ist.
- Die Ausführung ist eine befristete Aktion „bis Fr. 19.02., 20:00“.
  Das ist genau der Horizont der Wirkungsrechnung.
- Ersatzheld S2 „MHD-Retter“ für Lebensmittelbesucher: eine Charge
  Bio-Joghurt mit MHD heute, 1,49 € → 1,04 € (-30 %), Etikett
  „Reduziert wegen kurzer Haltbarkeit“, keine 30-Tage-Zeile, ebenfalls
  nur mit Klick.

### 4.5 Leitplanken (ein Parametersatz, als Code)

- Nur Senkungen, ein Regalpreis für alle, keine Personendaten.
- Mindestmarge netto 20 % bei Non-Food und 12 % bei Lebensmitteln;
  mit einem Klick bis 30 %, darüber nur mit Zweitfreigabe (am Stand
  gesperrt).
- Ein Vorschlag verfällt nach 120 s und ändert dann nichts.
  Höchstens zwei Änderungen pro Artikel und Tag.
- Ausgeschlossen sind Alkohol, Tabak, Pfand und preisgebundene Bücher;
  läuft schon eine Aktion, gibt es keinen Vorschlag.
- Gutschein nur bei `Closed`, nie bei `Cancelled`, einer pro Bon, nur
  aus dem Katalog, höchstens 30 % oder 2 €, ohne Geldwert.

### 4.6 Der Weg ins GEBIT-Labor

- Der Adapter ist `gpos-pos` im Modus `gebit`, mit zwei Ports:
  Ereignis-Eingang und Preis-Ausgang. Alles andere ändert sich nur
  per Konfiguration (Kustomize-Overlay `gebit-lab`).
- Der Preis-Rückweg hat eine feste Reihenfolge:
  1. GEBIT-Promotion-Service.
  2. Befristeter Artikelstammpreis.
  3. `supplied_price_information` über unseren Kassen-Client.
  4. Der Simulator bleibt.
- G3-Abnahme: Freigabe → nächster `AddArticle` mit neuem Preis in
  höchstens 5 s, sonst bleibt der Simulator.
- Messe-Standard ist der Simulator mit Badge. „GEBIT-Labor live“ gibt
  es nur mit lokalem GEBIT-Stack oder bestandenem Dauertest; fällt
  die Verbindung aus, wechselt die Engine zwischen zwei Besuchen
  automatisch zurück.

---

## 5. Erster Entwurf und Plan

### 5.1 Erster Entwurf (Ziel G1, 04.12.2026)

Läuft auf dem Lab mit SAM 2.542.1, ganz ohne GEBIT-Zugang:

- Kassensimulator mit GEBIT-Ereignissen inklusive Bon in `Closed`,
  Engine mit allen sechs MCP-Tools und Watchdogs, beide Workflows,
  Agent, Connector und Entrypoint mit `install.sh` und
  `uninstall.sh`.
- Die Seiten `/kasse`, `/kunde`, `/freigabe`, `/monitor` (funktional)
  und `/etikett` als Spiegel; Reset und Steuerkarten.
- Postgres-Schema und Seed; Tests für die Szenarien und für jedes
  erzeugte Ereignis gegen GEBITs Deskriptoren.
- Abnahme: 20 Besuche in Folge ohne Eingriff, Karte p95 < 1,5 s,
  KI-Text p90 ≤ 9 s, Tipp → Aktion aktiv p95 ≤ 2 s, Gutschein p95
  ≤ 2 s, 0 Token in Läufen ohne Heldenmoment.

### 5.2 Gate 0 (11.–20.11.2026)

Vor dem Bau messen wir, was das Konzept trägt (Details in DESIGN.md
13.2):

- **G0-1:** Apply des ganzen Pakets unter Spike-Namen mit je einem
  Testlauf; `sam config plan` allein prüft die Struktur nicht.
- **G0-2, G0-3:** rohes GEBIT-JSON als `workflow.input.text`; die
  Weiche fällt bei fehlenden Feldern in den Default.
- **G0-4:** Last mit 450 Läufen pro Stunde und Bursts von 7
  parallelen Läufen.
- **G0-5:** Latenz und Kosten des Agenten auf 2.542.1.
- **G0-6:** Umlaute auf dem Agentenpfad.
- **G0-7, G0-8:** Demotion für direkte Abonnenten, Status-Topics,
  SMF aus Pods, MQTT-Doppelpublish und ein ESP32-Prototyp.
- **G0-9 bis G0-14:** Queue-Optionen, MCP-Stub, LiteLLM-Budget,
  HMAC, Kiosk mit SSE und Descriptor-Round-Trip.
- **G0-15:** die Owner-Entscheidungen aus Abschnitt 6 festhalten.
- **G0-16 (neu):** `notify_user` als Tool-Knoten ohne LLM in die
  SAM-Inbox, nach der RBAC-Ergänzung für `notify:_:send`.
- **G0-17 (neu):** Workflow-HIL auf 2.542.1, nur als Befund.
- **G0-18 (neu):** Cloud-Instanz: Rundlaufzeit vom Stand über Kabel
  und 5G, WireGuard-Tunnel mit ESP32-MQTT und SSE.
- Voraussetzung: Die Inventur der vorhandenen Standtechnik liegt bis
  13.11. vor; bestellt wird nur, was fehlt (für G0-8 voraussichtlich
  ein ESP32 mit E-Paper-Panels, falls keine Etiketten da sind).

### 5.3 Gates bis zur Messe

| Gate | Zeitraum | Kern |
|---|---|---|
| G0 Spikes | 11.–20.11.2026 | Messungen, Entscheidungen, Fragen an GEBIT am 13.11. |
| G1 Vertikaler Schnitt | 23.11.–04.12.2026 | erster Entwurf Ende-zu-Ende |
| G2 Stand-komplett | 07.–18.12.2026 | Etiketten und Topper, S2, finale Layouts, Watchdogs, Preflight, Cloud-Instanz mit Tunnel, 10-Sekunden-Test mit Passanten |
| Feiertage | 21.12.2026–06.01.2027 | Firmware, Texte, Deck, Messebestellungen vorbereiten |
| G3 GEBIT-Labor | 07.–22.01.2027 | Adapter, echte GEBIT-Ereignisse, Notbetrieb-Drill, Dauertest, Messebestellungen bis 15.01. |
| G4 Generalprobe | 25.01.–05.02.2027 | 100 Läufe, juristische Freigabe, Freeze am 05.02. |
| G5 Messe | Aufbau 14.–15.02., Messe 16.–18.02.2027 | Preflight jeden Morgen READY |

### 5.4 Aufwand, Hardware, Kosten

- **Aufwand:** 85 Personentage auf Solace-Seite, davon 14 für die
  Oberflächen, 10 für die Engine, 7 für den Simulator und 6 für den
  GEBIT-Adapter. Auf GEBIT-Seite 10–15 Tage für Transport,
  Preisvertrag, Labor, Rechtstexte und Enten. Mit einem Entwickler
  passt es nicht; dann gilt die Streichliste (DESIGN.md 13.5).
- **Hardware:** Kassenhardware, Monitore und die übrige Standtechnik
  sind vorhanden. Die Stückliste in DESIGN.md 10.1 dient als
  Prüfliste für die Inventur: 65"-Monitor, Kassenplatz mit
  Kundendisplay, Freihand-Scanner, Tablet mit Ersatz, drei
  E-Paper-Anzeigen auf ESP32 mit PoE, Router mit 5G-Failover und USV.
  Fehlte alles, wären es etwa 5.800–7.000 €; anfallen werden nur die
  Lücken. Die Cloud-Instanz stellen wir bereit. Giveaways kommen aus
  GEBITs Budget.
- **LLM:** etwa 15–35 USD für die ganze Messe inklusive Proben und
  Evaluation. Dafür ein eigener Messe-Key mit 100 USD und Alarmen,
  zusätzlich ein SAM-Budget für die Laufidentität (wirkt nur, wenn
  die Modellpreise gesetzt sind).

---

## 6. Entscheidungen

### 6.1 Entschieden am 10.11.2026

1. **Autonomie:** Jede Regalpreisänderung nur per Klick, auch beim
   MHD-Retter; eine MHD-Automatik zeigen wir nur als Folie.
2. **Heldenpreis:** 6,89 € als befristete Aktion über den
   Promotion-Weg mit genau „-20 %“.
3. **Reset pro Besuch** statt Dauerbetrieb, wegen der 30-Tage-Regel.
4. **Ein SAM-Lauf pro Ereignis der Standkasse**, wenn G0-4 besteht;
   die Hintergrundkassen erreichen SAM nie.
5. **Messe-Modus:** Simulator mit ehrlichem Badge als Standard;
   GEBIT-Labor live nur mit lokalem Stack oder bestandenem
   Dauertest.
6. **Framing:** „Abschriften gegen Ladenhüter und
   Lebensmittelverschwendung, mit Freigabe“, nicht „Dynamic
   Pricing“.
7. **Host:** eine von uns bereitgestellte Cloud-Instanz statt eines
   Rechners am Stand; das Lab-MacBook steht als lokaler Notbetrieb
   bereit (DESIGN.md 4.8).
8. **Hardware:** Kassenhardware, Monitore und die übrige
   Standtechnik sind vorhanden; Inventur bis 13.11., bestellt wird
   nur, was fehlt.
9. **Lab-Änderungen:** Die Laufidentität bekommt den Scope
   `notify:_:send` (für die SAM-Inbox), und die Modelle `fast` und
   `workflow` bekommen Preise (für Budgets und Kostenseite). Beides
   setzen wir zum Start von Gate 0 um.
10. **Code-Ort:** lokal in `gebit-price-agent-demo/`, von Git
    ausgenommen, bis GEBIT schriftlich zustimmt. Nachtrag: Die
    Zustimmung liegt vor (vom Owner am 17.11.2026 bestätigt); das
    Verzeichnis liegt seitdem im öffentlichen Repo.

### 6.2 Noch offen

1. **LLM-Budget:** eigener Messe-Key mit 100 USD, Alarme bei 50 und
   80 %, bis 20.11. beantragen. Haiku 5.5 nur nach einem Test.
2. **Cloud-Instanz im Detail** (bis 13.11.): Anbieter und Region, VM
   oder verwaltetes Kubernetes, Größe, Betrieb, Zugang, Kosten und
   Termin (spätestens 07.12.2026).
3. **Juristische Prüfung** der Bildschirmtexte durch GEBITs
   Rechtsabteilung oder eine Kanzlei, bis G4.

Dazu kommen kleinere Punkte mit Empfehlung als Arbeitsstand
(Leitplanken-Zahlen, Choreografie, Queue, Etiketten-Hardware,
Giveaways, UI-Sprache, Handy-Seite und mehr) in DESIGN.md 14.2.

---

## 7. Fragen an GEBIT und Solace

### 7.1 An GEBIT (bis 13.11. verschicken; 1–5 blockieren G3)

1. Wie kommen die `PurchaseDomainEvents` im Demo-Labor an (Solace,
   Kafka, gRPC-Stream), binär oder als JSON? Kann das Labor auf einen
   von uns gestellten Solace-VPN publizieren? Sind die feingranularen
   Ereignisse aktiv, die grobgranularen `PurchaseTransactionChanged`
   und `-Finalized` oder beide?
2. Kann der Promotion-Service eine befristete Aktion mit festem
   Preis per API anlegen und beenden? Wie schnell gilt sie beim
   nächsten `AddArticle`?
3. Wie sieht der Artikelstamm-Weg aus (Nachricht, Felder,
   Bestätigung, Latenz)? Was bedeutet `freezePrice`, und werden
   offene Körbe neu bepreist?
4. Führt Ihr Preisservice den 30-Tage-Tiefstpreis, und können wir
   ihn lesen?
5. Chargengenaue MHD-Abschrift: Die API kennt Rabattsticker
   (`captured_promotion`) und Preise aus dem Barcode
   (`supplied_price_information`). Welchen Weg nutzen Ihre Kunden,
   lässt sich ein Sticker auf eine Charge begrenzen, oder braucht es
   einen eigenen Chargenartikel?

Dazu zwölf weitere Fragen (Stand, POS-Client, Artikelstamm, Enten, Coupons,
`approver`, Bon-Semantik, Deskriptoren, ESL, Logos, Recht) in
DESIGN.md 14.3.

### 7.2 An Solace (Produkt und Engineering)

1. Wie verhält sich der Event-Mesh-Entrypoint bei vielen kurzen,
   parallelen Läufen, und lässt sich die Reihenfolge pro Regel
   steuern?
2. Welcher Freigabeweg in Workflows ist für ereignisgetriggerte Läufe
   empfohlen?
3. Ist der Rohtext-Pfad `workflow.input.text` ohne `input_schema` ein
   unterstützter Vertrag für JSON bis 6 KB?
4. Was ist die Ursache der verstümmelten Umlaute in Agententexten?
5. Kann die Datenebene des Entrypoints unbegrenzt neu verbinden?

Sieben weitere Fragen stehen in DESIGN.md 14.4.

---

## 8. Risiken (die sechs größten)

| Risiko | Gegenmaßnahme |
|---|---|
| Uplink oder Cloud-Instanz fällt aus, Kasse und Monitor stehen | Kabel plus 5G-Failover, WireGuard mit automatischem Wiederaufbau, Preflight misst den Tunnel, lokaler Notbetrieb in ≤ 3 min |
| Läufe pro Ereignis überlasten SAM im Zahlungsburst | Lasttest G0-4, idempotente Tools, Engine hält die Ordnung, Watchdogs, Rückfall auf Schlüsselereignisse |
| KI-Text zu langsam oder Budget erschöpft | Karte in 1,5 s, ein Aufruf pro Besuch, Vorlage, eigener Key, Schutzschalter bei 80 % |
| GEBITs Preisweg oder Transport kommt spät | Simulator bleibt Standard, Nahtstellen isoliert, Antwortfrist 04.12. |
| Besucher verstehen die Geschichte nicht | 10-Sekunden-Test in G2, vier Stationen, Ente zum Anfassen, drei Host-Sätze |
| Fachbesucher greifen die Compliance an | Reset pro Besuch, vollständige Etiketten, abgerundete Prozente, „DEMO – kein Kassenbeleg“, juristische Freigabe in G4 |

---

## 9. Gegenprüfung

Vier Prüfer haben beide Dokumente angegriffen (SAM-Technik, GEBIT-API,
Stand und Zahlen, Recht und Konsistenz), jeder gefolgt von einem
Gegenprüfer, der jeden Befund zu widerlegen versuchte. Ergebnis:
57 Befunde, keiner widerlegt; 29 voll bestätigt, 28 teilweise (dort
wurde die Korrektur angepasst). Davon 2 Blocker, 26 schwer, 29 leicht.
Alle sind eingearbeitet; eine zweite Prüfung hat danach die
Einarbeitung kontrolliert.

**Bestätigt ohne Änderung:**

- Diese Rechnungen: Heldentabelle, MHD-Tabelle, Poisson-Wert,
  Prozentangaben, Ersparnis, Bonsumme, Grundpreise, Stückliste,
  Personentage, LLM-Kosten, Jury-Summen und alle Wochentage.
- Alle 31 GEBIT-Befehls-, Ereignis- und Feldnamen existieren in den
  Protos; die Ereignisfolge eines Besuchs passt zum Beispiel.
- Die übrigen YAML-Felder entsprechen dem Schema 2.542.1; die Latenzen
  gelten auch auf 2.542.1 (Tool-Knoten 0,02–0,81 s, Agent mit einem
  Aufruf 4,5–5,6 s); die Express-Version passt in 75 s.
- Die Rechtslogik zu § 9/§ 11 PAngV, MHD-Ausnahme, Art. 6a, Reset pro
  Besuch und BuchPrG ist korrekt wiedergegeben.

**Wichtigste Korrekturen:**

- **Blocker behoben:** Schema, Nutzlast und Tool-Signatur der
  Freigabe passten nicht zusammen; jede Freigabe wäre im Watchdog
  gelandet. Optionale Felder sind jetzt nullbar, das Tool hat
  Standardwerte, G0-12 prüft beide Fälle.
- **Blocker behoben:** DESIGN.md enthält mehr GEBIT-Details als
  dieses Papier, hatte aber keinen Vertraulichkeitshinweis. Jetzt
  steht er im Kopf; das Verzeichnis ist lokal von Git ausgenommen,
  und Frage 13 an GEBIT klärt, was in das öffentliche Repo darf.
- SAM: G0-1 prüft per Apply und Testlauf, denn `sam config plan`
  validiert die Struktur nicht. `notify_user` braucht einen
  `builtin-group`-Eintrag und den Scope `notify:_:send` (RBAC). Die
  gwe-Logzeile für „Entrypoint bereit“ ist auf 2.542.1 eine andere.
  SAM-Budgets wirken erst mit Modellpreisen. Messwerte und
  Eval-Dateilayout sind korrigiert.
- GEBIT: grobgranulare Ereignisse als Frage 1, nur wirksame
  Bonpositionen zählen, Freigabe-Spiegel nur als Ausblick,
  Ortsebenen als Annahme, neue Frage zum Artikelstamm im Labor, keine
  generierten Stubs im Image, Feldbelegung wie in GEBITs Beispielen.
- Stand: kein Bonabbruch vor Vorschlagsablauf, schärfere
  Latenzschwellen, Planungszahl 100–160 pro Tag, Lieferavis „nach
  Ladenschluss“, technische Fristen in echten Sekunden,
  Hardware-Termin vor Gate 0, Reset im geführten Besuch per
  Steuerkarte.
- Recht: 30-Tage-Zeile auch auf dem Monitor, Reset als ausdrückliche
  Ausnahme, Vorbehalt beim Preis-Rückweg, GWB und BGH genauer, AI Act
  und Fiskal als Annahmen markiert, Impressum und Datenschutzerklärung
  für die Handy-Seite, Vertraulichkeitshinweis in DESIGN.md.
