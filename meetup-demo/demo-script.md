# Meetup-Demo: AI Worker Lifecycle live auf SAM v2 (20 min)

Grundlage: der Point-of-Sale-Analytics-Use-Case aus dem Blog
([Unleash Revenue Potential][blog]) und den Artefakten in
[solace-sam-demos/sam-retail][repo]. Die POSLOG-Collection
enthält die Original-Transaktionen des Blogs plus die
Demo-Stories im selben Dokument-Schema.

[blog]: https://blog.alexandermartens.de/unleash-revenue-potential-agentic-ais-impact-on-point-of-sale-analytics
[repo]: https://github.com/martensa/solace-sam-demos/tree/master/sam-retail

Rollen im Szenario: **OMS-Team** (SAM WebUI), **Entwickler**
(Claude Code via MCP), **Plattform-Team** (Grafana). Persona-
Choreografie (Passwort = Username): `sam_admin` = Hiring
(Builder + First-Day-Test), `power_user` = Operations (Event-
Läufe via `defaultUserIdentity` + Activities-Beat, eigenes
Browserfenster), `data_engineer` = Developer (Claude Code/MCP).
`viewer` optional für den Security-Beat.

## Timeline

### 00:00–03:00 — Folien 1–4 (Rahmen)

Folie 1 (Lifecycle) → Folie 2 (Plattform auf K8s) → **Folie 3**
(Szenario: Retail Stores streamen POSLOG über das Event Mesh nach
MongoDB; PDM/OMS/CRM in Postgres — die Architektur aus dem Blog-
Use-Case) → kurz Folie 4 (was gleich wo passiert). Kernsatz: „Wir
stellen heute live einen neuen AI-Worker ein, geben ihm Zugriff,
lassen ihn im Team arbeiten — und messen ihn."

### 03:00–08:00 — HIRING + ONBOARDING: AI Builder live

1. SAM UI (`https://sam.solace.lab`, als `power_user`-User) →
   **Builder** → Build with AI → Prompt unten einfügen.
2. Moderation: Rolle/Verantwortung/Erwartungen = **Hiring**;
   Connector (System-Zugriff), Modell-Bindung, Credentials =
   **Onboarding**. MongoDB-Connector ist als *Experimental*
   markiert — ehrlich benennen.
3. Multi-LLM-Beat (2 min): **Models**-Seite zeigen — 9 Aliase:
   die geseedeten `general`/`planning`/`report_gen`/`image_gen`
   (Claude Opus 4.8) plus `workflow` (Sonnet 5), `reasoning`
   (DeepSeek V3.2), `coding` (Qwen3 Coder), `expert` (Opus 5),
   `fast` (Haiku 4.5) — drei Vendors, ein Proxy. Aussage: „Agent
   bindet einen Alias, nie einen Key — Modellwechsel ohne
   Restart. Der Incident-Report läuft auf Sonnet 5, die
   Spezialisten auf Opus 4.8 — gleich in Activities und im
   Token-Dashboard (`by_model`) sichtbar."
4. Security-Beat (1 min): zweites Browserfenster (Inkognito) als
   `viewer`-User: kein Builder-Menü, weniger Agenten sichtbar —
   RBAC via Keycloak-Gruppen.

**Builder-Prompt (copy-paste):**

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

**Fallback (Break glass):** `cd meetup-demo/fallback &&
sam config apply` erstellt Connector + Agent deklarativ.

### 08:00–10:00 — COACHING: Wissen statt Prompt-Spaghetti

1. Builder → Skills: die `retail-*-schema`-Bundles zeigen —
   „interne Weiterbildung": Schema-Wissen + Fallen (Line-Item-
   Dedup!) als versionierte Skills, nicht als Prompttext.
2. POSLOG-Agent: Schema-Introspection erwähnen (Connector sampelt
   100 Dokumente und übergibt dem Agenten das Schema).
3. Kurzer Talk-to-data-Test des NEUEN Agenten (Abfrage 3 unten).

### 10:00–15:00 — TEAMWORK: der Shop-Moment

1. `meetup-demo/shop/index.html` öffnen (Datei im Browser).
   Status-LED grün = verbunden mit `ws://localhost:8008`, VPN
   `sam` — „der Browser publiziert direkt ins Event Mesh."
2. **Opus One bestellen** → created-Event → der **Order
   Confirmation Clerk** (eigener Agent auf `fast`/Haiku, ~7s,
   ~28k Tokens — verifiziert) bestätigt als Response-Event im
   Shop. Sichtbarer Cheap-Tier-Traffic für die Dashboards.
3. **Açaí Bowl bestellen** → failed-Event (OUT_OF_STOCK) →
   Event-Mesh-Entrypoint → **Orchestrator** delegiert parallel an
   OMS + PDM + POS Analyst, „Order Incident Reporter" merged.
   Während er läuft: SAM UI → **Activities** → Task öffnen →
   Flow-Graph live; nach Abschluss **Performance** (Gantt).
   Laufzeit ~2,5–4 min, ~110–135k Tokens — verifiziert. Die
   Event-Tasks laufen via `defaultUserIdentity` als
   `power_user` und erscheinen daher in DESSEN Activities-
   Fenster (Activities ist für alle Rollen eine Pro-User-Sicht;
   ohne das Feld läuft der Task unter der unsichtbaren
   Gateway-Identität — 2026-08-03 in der Probe gefunden und
   gefixt, Attribution live verifiziert).
4. Ergebnis: Incident-Summary als Event im Shop; Artefakt
   `incident-<order_id>.md` in der Session (OMS-Team-Sicht).
5. Persona-Split: Entwickler stellt in **Claude Code** (MCP,
   `/mcp` → sam-lab) dieselbe Frage an die Experten („Zeig mir
   die PDM-Daten zum Açaí Bowl"). Aussage: „Gleiche Worker, drei
   Oberflächen: UI, Claude Code, Events."
6. Optional (Zeitpuffer): Trüffel bestellen → zweiter Incident
   mit anderer Root Cause (out-of-season).

### 15:00–18:00 — IMPROVEMENT: Messen und verbessern

1. Grafana `https://monitoring.solace.lab` → Ordner SAM →
   **SAM Meetup Demo**: dem roten Faden folgen (Gesundheit →
   Geschwindigkeit → Kosten/Chargeback je User → Governance
   „wer nutzt was" → Beweis-Links). Die Demo-Last von eben ist
   live sichtbar (Token-Rate, Latenzen, Audit-Events).
2. Tempo-Drilldown (30 s): Explore → Tempo →
   `sam-solace-lab/a2a`-Spans — jeder A2A-Hop der Demo.
3. Offline-Evals: SAM UI → Evaluations → Experiment
   `meetup-quality` (vorab gelaufen: 12/12, 100 %) → Scores
   zeigen; optional live im Terminal:

   ```bash
   export SAM_AUTH_TOKEN=$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/Library/Application Support/sam/auth/solace-lab.json')))['sam_access_token'])")
   sam eval run meetup-quality --url https://sam.solace.lab --threshold 0.8
   ```

   Laufzeit ~6 min für 6 Beispiele × 2 Evaluatoren. „Exit-Code ≠ 0
   = CI-Gate: Qualität wird Pipeline-Kriterium." Evaluatoren:
   `LLM Judge` + `Factuality` (Seeded; ein „rouge" existiert
   nicht — heuristisch heißt es `Response Match`).

### 18:00–20:00 — Wrap

Folie 4: jede Lifecycle-Phase abhaken (Supervision: work in
progress). Schlusssatz: „Ein Event Mesh, ein Worker-Lifecycle —
Agenten wie Mitarbeitende führen, nicht wie Skripte betreiben."

## Top-5 Talk-to-my-data-Abfragen

1. **CRM (Warm-up):** „Who are our top 10 customers by lifetime
   spend? Show a chart."
2. **OMS+PDM:** „Which products generated revenue, and where are
   margin or inventory critical?" (an den Orchestrator)
3. **Mongo (der neue Worker):** „How often was the Tropical Acai
   Smoothie Bowl sold at the registers although stock is zero —
   and were any transactions voided?" (POSLOG-Dokumente tragen
   `items[]`, `store{}`, `payment.status`)
4. **Mongo+OMS Kanalvergleich:** „Compare Opus One Napa Valley
   2019 revenue: online orders vs. POS registers, by store."
5. **CRM+PDM+Mongo (Orchestrator-Delegation):** „Who bought the
   Shaved Black Truffle outside its season, on which channel,
   and what does that say about our data quality?"

## Die 5 Shop-Produkte (echte Daten-Stories)

| Produkt | Ausgang | Story |
|---|---|---|
| Opus One Napa 2019 ($425) | OK | Top-Umsatz, 67 auf Lager |
| Pike Place Roast ($16.99) | OK | Alltagsprodukt, 187 Bestand |
| Açaí Bowl ($14.99) | FAIL OUT_OF_STOCK | Bestand 0, verkauft sich trotzdem (Status „Made to Order" verdeckt es); Käufer: Tourist ohne Loyalty |
| Black Truffle ($159.99) | FAIL OUT_OF_SEASON | Saison Nov–Mar, Verkauf im Oktober; niedrigste Marge im Katalog (28,1 %) |
| Alpine Trail Mix ($12.99) | FAIL DATA_QUALITY | inventory_status = Markenname „Bulk Bin"; einzige Bruchmengen-Buchung (2.3) |

## Pre-Flight-Checkliste (15 min vor Beginn)

1. `docker ps` — solace-1/2, otel-collector, generator, consumer,
   postgres, retail-pos-mongo laufen.
2. `kubectl get pods -n sam-solace-lab` — alles Running; nach
   frischem Doppel-Restart von gwe+awe: awe einmal einzeln
   restarten (DB-Agenten-Race).
3. `sam auth login solace-lab --url https://sam.solace.lab`
   (power_user/Bootstrap-Admin) — Token für Fallbacks + Evals.
4. Shop öffnen: LED grün; eine Test-Order (Pike Place) feuern,
   Bestätigung abwarten; Event-Log im Shop leeren (Reload).
5. SAM UI eingeloggt (power_user) + Inkognito-Fenster (viewer).
6. Grafana offen: Dashboard „SAM Meetup Demo" + Explore-Tab
   Tempo vorbereitet.
7. Claude Code: `/mcp` → sam-lab authentifiziert.
8. Falls der POSLOG-Agent aus einem früheren Durchlauf existiert:
   im UI löschen (Builder-Demo soll ihn NEU erschaffen);
   Connector `retail-poslog` darf bleiben (Builder-Prompt nutzt
   ihn dann einfach — oder ebenfalls löschen für den vollen
   Onboarding-Moment).
9. Modell-Upstreams gesund (5 Modelle, 1-Token-Probes):
   `cd agent-mesh-deployment/scripts/models && ./apply-models.sh --probe-only`
10. Kyverno gesund: `kubectl get pods -n kyverno` — alles
    Running. Ein crashloopender admission-controller blockiert
    JEDE Pod-Änderung still (tritt nach Mac-Netzwechsel auf;
    Fix siehe „Bekannte Grenzen").
11. Monitoring-Stack gesund: `kubectl get pods -n monitoring` —
    besonders `tempo-0` (OOM bei Block-Kompaktierung meldet sich
    als Exit 137/„Error", nicht als OOMKilled; Limit seit
    2026-08-03 auf 4Gi).
12. Falls str seit der letzten Connector-Anlage/-Änderung neu
    gestartet wurde: Smoke-Test ALLER Connector-Agenten (CRM/
    OMS/PDM/POS + Clerk, je eine kurze Frage). Bei „data source
    offline": Connector-Beschreibung minimal ändern +
    `sam config apply` (Update pusht das Tool-Paket neu).
13. sam-VPN-Spool-Check (die 10-GB-Falle):
   `curl -s -u admin:admin "http://localhost:8080/SEMP/v2/monitor/msgVpns/sam?select=msgSpoolUsage"`
   — unter ~2 GB ist gesund.
14. Notfall-Reihenfolge bei Totalausfall eines Beats: Fallback
    anwenden (`meetup-demo/fallback`), Retail-360-Workflow als
    Ersatzdemo (Folie 4, verifiziert), Grafana läuft immer.

## Rebuild-Abhängigkeiten (nach jedem Plattform-Rebuild prüfen)

1. **Workflow-Kartenname im Event-Entrypoint**: der Entrypoint
   publiziert auf das A2A-Topic des MESH-KARTEN-Namens
   (`workflow_<uuid>`), nicht auf den Config-Namen. Nach einem
   Rebuild neu setzen:

   ```bash
   sam config pull  # oder: /api/v1/platform/workflows -> id
   # entrypoints/shop-events.yaml: targetWorkflowName anpassen
   ```

2. **RBAC**: Event-Mesh-Entrypoints laufen unter einer eigenen
   Gateway-Identität und halten nur die Default-Rollen — deshalb
   trägt `sam_user` jetzt `workflow:*:invoke` (siehe
   `scripts/rbac/rbac/roles/sam_user.yaml`).
3. **MCP-Tool-Namen der Desktop-App** (`scripts/desktop`).

## Bekannte Grenzen (ehrlich moderieren)

- MongoDB-Connector: **Experimental** (2.225.14).
- Workflow-Ergebnisse über MCP tragen nur einen Completion-Status
  — Report-Abruf via Orchestrator-Tool (Claude-Code-Weg).
- Supervision: work in progress, bewusst nicht Teil der Demo.
- RBAC-Grants loggen auf DEBUG — Governance-Dashboard zeigt
  Executions und Denies, nicht die Grants.
- **Builder kann mit „Expected toolResult blocks" sterben**
  (2026-08-03 in der Probe getroffen): SAM 2.225.14 baut bei
  langen Builder-Konversationen eine kaputte History (tool_use
  ohne toolResult) — Bedrock lehnt mit 400 ab, die
  -anthropic/-vertex-Fallbacks des Proxys sind tot, LiteLLM
  retried 3× dieselbe kaputte Anfrage. Die Konversation ist
  danach unbrauchbar: NEUE Build-with-AI-Konversation starten
  (gleicher Prompt) oder Fallback (`meetup-demo/fallback`).
  Vorher Teilzustand aufräumen (retail-poslog-Connector /
  Draft-Agent löschen). Builder-Chat = EIN Prompt, keine
  Follow-ups.
- **Builder-Test-Engine: VENDOR-BUG, nicht behebbar**
  (2026-08-03, vollstaendig diagnostiziert): der Plan-Generator
  (`generate_test_plan`, str-Subprozess) wird vom Aufrufer nach
  HARTEN 30s gekillt (`timeout_seconds`-Default; ignoriert die
  90s aus Solaces eigenem Tool-Manifest). Sein LLM-Call braucht
  auf Opus 4.8 gemessene ~106s — und die Modellwahl ignoriert
  JEDE konfigurierbare Flaeche (Env in str/awe/gwe, DB-Alias
  `planning`, Modell-Binding des ephemeren Test-Agenten; alles
  nacheinander auf Haiku gestellt und per Debug-Log verifiziert:
  der Call blieb auf Opus). Quelle ist das `general`/`report`-
  Tier, das fuer die Demo-Agenten auf Opus bleiben muss.
  Der Test-Tab bleibt aussen vor (Talk Track 6.2 = normaler
  Chat). Bleibende harmlose Aenderungen: DB-Alias `planning` =
  Haiku (nichts bindet es) und ein DB-Trigger
  `ephemeral_agent_default_model` (platform-DB), der ephemeren
  Test-Agenten das `fast`-Binding gibt — ihr CHAT laeuft damit
  auf Haiku (verifiziert). Beides faellt bei stop.sh mit der
  Plattform-DB weg; Re-Erstellung optional.
- **str-Restart verliert ALLE Connector-Tool-Pakete**
  (2026-08-03): Mongo-per-Collection-Tools UND SQL-Connector-
  Tools (`*_sql_query_<uuid>`). Subscription überlebt, Invokes
  scheitern mit „tool not in manifest" (Agent meldet „data
  source offline"). Agent-Redeploy stellt NICHTS wieder her;
  ein Connector-UPDATE (Mini-Änderung an der Beschreibung +
  `sam config apply`) pusht das Paket neu — UUIDs bleiben
  stabil, kein Löschen nötig. Nach jedem str-Restart alle vier
  Connector-Agenten smoken.
- **Nach Netzwechsel des Macs: k3s-API fuer Pods tot**
  (2026-08-03): Rancher Desktop pinnt die Mac-LAN-IP als
  `--node-external-ip` in /etc/conf.d/k3s; nach DHCP-/
  WLAN-Wechsel zeigt der kubernetes-Endpoint auf die tote IP →
  Pod→API "no route to host" → Kyverno crashloopt und blockiert
  als Fail-closed-Webhook ALLE Pod-Aenderungen (rollout restart
  schlaegt fehl, meldet aber "successfully rolled out"!).
  Pre-Flight daher: `kubectl get pods -n kyverno` muss gruen
  sein. Fix ohne Broker-Downtime: IP in /etc/conf.d/k3s per
  `rdctl shell sudo sed` korrigieren, `rc-service k3s restart`,
  Kyverno-Pods loeschen; ein Rancher-Desktop-Neustart schreibt
  die Datei ohnehin neu.
- **Event-Trigger → Workflow ist in 2.225.14 defekt**: mit
  `targetWorkflowName` liefert der Entrypoint eine LEERE A2A-
  Nachricht (per Sniff belegt: `parts[0].text == ""`), der
  Workflow läuft ins Nichts. Deshalb zeigt die Demo den
  Event-Pfad über den **Orchestrator** (`targetAgent`), der
  delegiert — Workflow `order-incident-report` bleibt deployed
  und wird im UI/Activities-Beat gezeigt. Vendor-Gap fürs
  Support-Ticket.
- **Nur der Orchestrator kann delegieren**: ein Standard-Agent
  meldet „peer delegation lives at my level, not theirs".
- **LLM-Budget**: der LiteLLM-Proxy hat ein hartes Kostenlimit
  (`status 429 [budget_exceeded]`). Vor dem Meetup Budget prüfen —
  ohne LLM-Kontingent laufen zwar Events, Workflow und Metriken,
  aber die Agenten antworten nicht.
