# Runbook UC1 „Preisvorschlag nach Kassenabschluss“

Betriebshandbuch für Lab und Messestand (EuroCIS 2027, GEBIT + Solace).
Verbindlich ist `UC1-BUILD-SPEC.md`; Aufbau und Befehle stehen in
`README.md`. Alle Befehle laufen im Demo-Verzeichnis auf dem Mac.

Kernsatz für Monitor und Gespräch: „KI schlägt vor. Regeln prüfen.
Mensch entscheidet.“

## Rollen

- Operator: Mac mit `sam`-Login als `sam_admin`, führt Reset, Wächter,
  Probes und Abnahme aus.
- Marktleitung: SAM-WebUI als `marktleitung@solace.lab`, gibt Vorschläge
  unter „Notifications“ frei („Approve“) oder lehnt ab („Deny“).
- Standpersonal: `/kasse` (Tablet/Laptop) und `/monitor` (Kiosk).

## Vor jedem Messetag

1. Lab läuft: `make status` (sechs Pods `Ready`),
   `scripts/broker.sh r1-show` (genau ein gwe-Flow auf `gpos-booth-r1`).
2. `scripts/reset.sh --scope day --preflight`: Reset-Kette, offene
   `gpos`-Freigabeanfragen abgebrochen, verwaiste Queues gelistet,
   Anmeldeprüfung (Benachrichtigung „gpos Preflight: Benachrichtigung
   ok“ im Posteingang der Marktleitung).
3. Scheitert die Anmeldeprüfung: einmal in der SAM-WebUI als
   `marktleitung` anmelden, dann Schritt 2 wiederholen.
4. `make smoke` muss `READY` melden (Kasse 99, löst nie SAM aus).
5. Inbox-Wächter in einem eigenen Terminal starten: `make demo-watch`
   (läuft den ganzen Tag; e2e-Läufe nur ohne Wächter).
6. Monitor und Kasse öffnen: `make urls`. Uhr im Monitor-Fuß zeigt das
   Fachdatum Di 16.02.2027.
7. Probeläufe auf Kasse 98 nur vor Messebeginn (sie legen Karten in den
   Posteingang der Marktleitung).

## Szenarien (Karten auf `/kasse`)

Alle Erwartungen gelten ab einem Reset.

- S1 Ladenhüter: Vorschlag GEBIT Ente 9,99 → 7,99 € (−20 %), −30 %
  gesperrt (Marge 11,5 %). Hauptdemo, Ablauf unten.
- S2 Saisonende: Herzpralinen 7,99 → 5,49 € (−31 %), Saison endete am
  14.02.
- S3 Kundenverhalten: Karte „Kaffeepause“, Espresso 14,49 → 12,99 €
  (−10 %), Hinweis „Rücknahme der Preiserhöhung vom 11.01.“. Der
  Belege-Agent fragt drei APIs: Kasse (`get_transaction`),
  Warenwirtschaft (`get_article`) und Loyalty
  (`get_purchase_behaviour`); Zeitachse „… prüft Belege über 3
  API-Abfragen“ (seit UC1-31, Spezifikation 15.6).
- S4 Alles im Plan: kein Kandidat, Review ohne KI.
- S5 Leitplanke: Glühwein (Zentralaktion) und Kochbuch
  (Preisbindung) gesperrt, Review ohne KI.
- S6 Ohne Einwilligung: Karte „Feierabend“, Espresso kein Kandidat.
- S7 Zwei Kandidaten: Herzpralinen werden vorgeschlagen (Saisonende hat
  Vorrang), Ente als „weiterer Kandidat (nicht vorgeschlagen)“.
- S8 Agent rät ab: Plüschhase als Ladenhüter markiert, der Belege-Agent
  (fast) sieht steigenden Abverkauf, der Planer (planning) empfiehlt
  „keine Preisänderung“.
- S1b Nach Freigabe (ohne Reset): Ente 7,99 € AKTION, Ente gesperrt.

## Ablauf S1 (Hauptdemo)

1. Szenario-Karte „Ladenhüter“ antippen (oder Bon von Hand: Ente,
   Bio-Bananen, Vollmilch, „Bezahlen (bar)“).
2. Monitor: Zeile „GEBIT Ente 9,99 €“, Chip rot „Ladenhüter: 9 von 35
   geplanten Stück verkauft (7 Tage), Reichweite 6,5 Wochen“.
3. Nach „Bezahlen“: Review-Karte „Regel-Analyse (ohne KI)“, dann die
   KI-Schritte (Zeitachse, Spezifikation 1.4 und 10.4):
   „Regel-Analyse (ohne KI): 1 Kandidat(en) markiert“ →
   „Claude Haiku 4.5 fragt Kasse: get_transaction“ und „… fragt
   Warenwirtschaft: get_sales_performance“ → „Claude Haiku 4.5 prüft
   Belege über 2 API-Abfragen“ („1 von 1 Anlässen bestätigt“) →
   „Claude Sonnet 5 empfiehlt: GEBIT Ente (Quietscheente gelb)
   (Ladenhüter)“ → „Engine prüft Leitplanken und rechnet den Preis
   (ohne KI): 9,99 € → 7,99 €“. Nach etwa 15 bis 25 s (hängt der
   Planer, etwa 45 bis 60 s, siehe Störungen) Vorschlagskarte
   „GEBIT Ente 9,99 → 7,99 € (−20 %)“ mit „KI-Empfehlung · planning
   (Claude Sonnet 5)“ und „Leitplanken der Engine (ohne KI)“; dann
   „Claude Haiku 4.5 legt der Marktleitung die Freigabe vor“.
4. Station 4 pulsiert „Liegt in Agent Mesh bei der Marktleitung“.
   Die Marktleitung öffnet in der SAM-WebUI „Notifications“, liest
   die Zusammenfassung und beantwortet die Anfrage „Your input is
   requested“ mit „Approve“. Frist: 2 Minuten.
5. Stempel „Freigegeben · Marktleitung · in Agent Mesh“, darunter
   „empfohlen von KI (planning), geprüft von der Engine“, Ereigniskarte
   `PriceChangeApplied`. Fußzeile: „13 Kassenereignisse → 6 SAM-Läufe →
   3 KI-Agenten-Läufe (fast 2, planning 1) · 2 API-Abfragen der Agenten
   → 1 Freigabe(n)“.
6. Neuer Bon, Ente scannen: „GEBIT Ente 7,99 € AKTION“, Chip „Messe-
   Aktion aktiv bis Di 23.02. 20:00“.

## Talk-Track (Freigabe durch den Owner offen, Spezifikation 16.1 Nr. 11)

- Identität: „Alle Läufe laufen in Agent Mesh unter der Identität der
  Marktleitung. Empfohlen von KI (planning), geprüft von der Engine,
  freigegeben von der Marktleitung.“
- Zwei KI-Stufen: „Die Regeln markieren Kandidaten ohne KI. Ein
  schnelles Modell (fast) holt die Belege über die APIs von Kasse und
  Warenwirtschaft, bei Kartenkunden mit Einwilligung auch von Loyalty,
  ein stärkeres Modell (planning) schreibt daraus die KI-Empfehlung.
  Preise und Leitplanken rechnet immer die Engine.“
- Ablehnen: „Lehnt die Marktleitung ab, bleibt der Preis; der Monitor
  zeigt ‚Abgelehnt – kein neuer Preis‘.“ Ablauf: „Ohne Antwort binnen
  2 Minuten: ‚Abgelaufen – kein neuer Preis‘.“
- Längere Wartezeit bei „Claude Sonnet 5 wertet die Belege aus …“:
  „Der Planer braucht diesmal länger. Agent Mesh wartet höchstens 30 s
  auf einen Versuch und startet dann einen zweiten; der Vorschlag kommt
  gleich.“
- Zurückgestellt (`deferred`): „Solange an dieser Kasse ein Vorschlag
  offen ist, wird der nächste Bon nicht geprüft und auch nicht
  nachgeholt. Der Artikel kommt mit dem nächsten Bon wieder.“
- 30-Tage-Tiefstpreis: „Der Monitor zeigt den niedrigsten Preis der
  letzten 30 Tage. Vereinfachung: Messe-Aktionen zählen dafür nicht
  mit, damit die Demo wiederholbar bleibt.“
- S3: „Der Vorschlag ist die Rücknahme der Preiserhöhung vom 11.01.:
  Seitdem kaufen Stammkunden den Espresso seltener. Der Agent fragt
  dafür alle drei Systeme: die Kasse nach dem Bon, die Warenwirtschaft
  nach Artikel und Marge und Loyalty nach dem Kaufverhalten der Karte,
  das nur mit Einwilligung.“
- Daten: „Alle Artikel, Karten und Kartenkunden-Statistiken sind
  fiktiv.“
- Kernsatz: „KI schlägt vor. Regeln prüfen. Mensch entscheidet.“

## Reset

- Knopf auf `/kasse` („Reset“): Engine, Warenwirtschaft, Kasse,
  Loyalty und Zähler. Offene Freigabeanfragen räumt nur der Mac ab:
  der laufende Inbox-Wächter binnen 5 s oder `make demo-reset`.
- `make demo-reset` (`scripts/reset.sh`): Reset-Kette, danach offene
  `gpos`-Anfragen abbrechen (Reihenfolge wichtig: Vorschläge sind dann
  schon `superseded`), danach verwaiste Queues listen. Ziel unter 15 s.
- `scripts/reset.sh --scope day`: zusätzlich Laufzeitdaten des Tages
  und die Zentralaktion; zählt die gelesenen `gpos`-Meldungen im
  Posteingang.

## Posteingang der Marktleitung

- Je Vorschlag bleiben zwei bis drei gelesene Meldungen liegen
  (Zusammenfassung, Ergebnis). Ein Lösch- oder Archiv-Weg der
  Notify-API ist nicht belegt (A-23); `scripts/sam_inbox.py hygiene`
  zählt sie. Bei Bedarf in der WebUI von Hand archivieren.
- Offene Anfragen nie stehen lassen: `scripts/sam_inbox.py list`,
  Abbruch mit `scripts/sam_inbox.py cancel-gpos`.

## Störungen

- Zweite Freigabeanfrage zur selben Ref: Der Wächter genehmigt sie, wenn
  der Preis schon aktiv ist (Monitor: „Zweite Freigabeanfrage erkannt –
  Preis ist bereits aktiv“), sonst bricht er sie ab. Ohne Wächter:
  `scripts/sam_inbox.py answer GP-… approve` bzw. `cancel-gpos`.
- Abgelaufen (2 Minuten ohne Antwort): Die Anfragekarte der
  Marktleitung zeigt den Ablauf („timed out“); auf dem sauberen Pfad
  folgt die Meldung „Abgelaufen: GEBIT Ente … bleibt bei 9,99 €“ /
  „Keine Antwort binnen 2 Minuten. Ref GP-…“. Monitor „Abgelaufen –
  kein neuer Preis“, Laufliste „Abgelaufen“. Kein Eingriff nötig.
- Abgelehnt („Deny“): Monitor „Abgelehnt – kein neuer Preis“, Stempel
  „Abgelehnt“ mit „Abgelehnt in Agent Mesh“. Sauberer Pfad: Laufliste
  „ok“, die Marktleitung bekommt die Meldung „Abgelehnt: GEBIT Ente …
  bleibt bei 9,99 €“ / „Abgelehnt in Agent Mesh. Kein neuer Preis. Ref
  GP-…“. Rückfallpfad (der Approver beendete seine Aufgabe als Fehler):
  Laufliste vorläufig „Abgelehnt“, keine Ergebnis-Meldung im
  Posteingang (Spezifikation 16.1 Nr. 32). Kein Eingriff nötig.
- Woran die Engine Ablehnung und Ablauf erkennt (seit 12.11.,
  Spezifikation 11.5 und 15.3): Agent Mesh gibt dem Approver nach einem
  „Deny“ den Text „Tool call denied by user.“, nach dem Ablauf „Tool
  approval timed out after 2 minutes.“, beide mit Status `error`. Der
  Approver reicht den Text als `message` weiter; die Engine wertet ihn
  als Ablehnung bzw. Ablauf, auch wenn der Agent `error` meldet, aber
  nur bei unberührtem Gate und im richtigen Zeitfenster. Nachsehen:
  `GET /api/proposals/GP-…` (BFF) zeigt unter `approval.evidence` die
  Regel (`R5m` = SAMs Ablehnungstext, `R5` = sauberer Status, `R6` =
  Fehler-Rückfall, `R3a`/`R3b` = Ablauf) und den Pfad (`message`,
  `status`, `error`, `window`); dieselben Werte stehen in
  `engine.audit_event` (`outcome_evidence`, bei R5m zusätzlich
  `deny_via_message`).
- „Technischer Fehler – kein neuer Preis“ oder „Agent meldete keinen
  Status – kein neuer Preis“: kein Preis; Lauf in der SAM-WebUI,
  `approval.evidence` und `engine.audit_event` ansehen, bei Häufung
  Gate-Verifikation erneut. Ein Ablauftext vor Ablauf der 2 Minuten
  gilt immer als technischer Fehler. „Ablehnung schneller als möglich
  – Agent prüfen“: der Agent meldete eine Ablehnung, bevor ein Mensch
  antworten konnte.
- „Technischer Fehler“ oder hängender Vorschlag nach einem awe-Neustart:
  `make demo-reset` (Vorschläge `superseded`, dann Anfragen abbrechen).
  gwe, awe und str nie selbst neu starten; ist es unvermeidbar, nur awe
  und danach sofort `make demo-reset`.
- Vorschlag kommt etwa 30 s später als sonst (etwa 45 bis 60 s nach
  „Bezahlen“), die Zeitachse steht so lange bei „Claude Sonnet 5 wertet
  die Belege aus …“: Der Planer hing im ersten Versuch. Agent Mesh
  wartet nach 30 s nicht mehr auf ihn und startet nach 1 s einen
  zweiten Versuch; der erste läuft im Hintergrund zu Ende (bis etwa
  100 s, weitere Sonnet-Tokens), sein spätes Ergebnis wird verworfen
  (seit 12.11., UC1-30, Spezifikation 9.5, 13.4 und A-38). Kein
  Eingriff nötig.
  - Während der Wartezeit keinen zweiten Bon an der Messekasse
    abschließen: Er wird zum aktuellen Review auf dem Monitor, der
    Vorschlag des ersten Bons erscheint später. Ist der zweite Review
    zuerst fertig, bekommt er den Vorschlag, und der erste endet
    `deferred` (Zurückgestellt). Keine Daten gehen verloren, kein Preis
    ohne Freigabe. Den nächsten Bon erst nach der Vorschlagskarte oder
    einem Review-Ende abschließen; Reset ist sicher, verwirft aber den
    S1-Lauf.
  - Erkennen an der Zeit: im e2e-Lauf `a4b_evidence_decided_s` über
    35 s (sonst meist 8 bis 18 s, einzelne Läufe ohne Wiederholung bis
    etwa 28 s; Ziel seit 13.11. p50 ≤ 12 s, p90 ≤ 18 s) und
    `planner_attempts` 2, in der Zusammenfassung `planner_retried_runs`.
  - Erkennen im awe-Log (lesend, Symptom des Hängers): Warnungen des
    Planers „LLM emitted internal continuation call“ oder „dropping
    LLM-generated _notify_artifact_save call“. Mehrere mit derselben
    `taskID` bedeuten einen Hänger; eine einzelne Zeile kommt auch in
    Läufen vor, die sich selbst erholen.

    ```bash
    kubectl -n sam-solace-lab logs deploy/agent-mesh-solace-agent-mesh-awe \
      -c awe --since=15m \
      | grep -E 'internal continuation call|LLM-generated _notify_artifact_save' \
      | grep -o '"taskID":"[^"]*"' | sort | uniq -c
    ```

  - Beweis in der webui-DB (nur SELECT, das Passwort bleibt im Pod):
    zwei Zeilen mit derselben `retry_group_id`, `retry_attempt` 0 und
    1, etwa 31 s auseinander (neueste zuerst).

    ```bash
    kubectl -n sam-solace-lab exec -i agent-mesh-postgresql-0 -- sh -c \
      'PGOPTIONS="-c default_transaction_read_only=on" PGPASSWORD="$POSTGRES_PASSWORD" psql -X -U postgres -d sam-solace-lab_webui -At' <<'SQL'
    SELECT task_id, to_timestamp(created_time / 1000.0),
      substring(payload from '"retry_attempt":[0-9]+'),
      substring(payload from '"retry_group_id":"[^"]+"')
    FROM task_events
    WHERE direction = 'request' AND payload LIKE '%"node_id":"recommend"%'
    ORDER BY created_time DESC LIMIT 6;
    SQL
    ```

  - awe schreibt bei einer gelungenen Wiederholung weder „timed out“
    noch „retrying node“ (Debug-Zeile). Steht „node "recommend" timed
    out after 30s“ in einer Zeile „node failed“, scheiterte auch der
    zweite Versuch: Der Review endet ohne Vorschlag und ohne Preis,
    neuer Bon.
  - Diagnose: Die verwendete Ausgabe ist die Version in
    `output_artifact_ref` des Knotens `recommend`, nicht die neueste
    Version von `wf_recommend_output_<id>.json`; die neueste kann vom
    verworfenen ersten Versuch stammen.
- Kein Scan-Chip, aber Bonzeile: R1 prüfen mit
  `scripts/broker.sh r1-show` (genau ein Flow). Ereignisse älter als
  20 s verwirft die Queue (max TTL), die Engine zusätzlich
  (`STALE_SECONDS`).
- Verwaiste SAM-Queue (`scripts/broker.sh orphans` meldet `ORPHAN`):
  nur Queues entfernter `gpos`-Regeln löschen, nach Rücksprache.
- Broker-Rückstau: Der DMR-Link `solace-1` → `solace-2` ist unten; im
  Lab läuft alles Direct (`GPOS_DELIVERY=direct`).
- Posteingang zeigt keine Anfrage: Anmeldeprüfung
  (`scripts/reset.sh --preflight`), sonst Gate-Verifikation erneut.

## R1-Modus wechseln (harte Regel 4)

1. `.env`: `R1_MODE=sam` bzw. `own`.
2. `scripts/install.sh mesh --switch-r1`: wendet den Messe-Entrypoint
   an, ruft `scripts/broker.sh r1-switch <alt> <neu>` (von `sam` nach
   `own` wird die SAM-Queue `…/eventmesh/<id>/r1_booth_till` gelöscht,
   von `own` nach `sam` verliert `gpos-booth-r1` ihre Abos) und listet
   verwaiste Queues.
3. Ohne `--switch-r1` bricht `scripts/render_mesh.py` ab.
4. Regelnamen (`r1_booth_till`, `r3_basket_review`, `r4_price_approval`,
   `p1_probe_till`, `p3_probe_review`, `p4_probe_approval`) nie
   umbenennen oder entfernen.

## Gate-Verifikation und Rückfälle (Spezifikation 9.9)

- Vorher: `sam auth login solace-lab --url https://sam.solace.lab`
  (e2e liest die Agentenliste der Plattform, um die IDs des awe-Logs
  Agentennamen zuzuordnen; ohne Login scheitert der Preflight).
- `make gate-verify`: S1 auf Kasse 98 dreimal mit Freigabe, fünfmal
  mit Ablehnung (A9) und zweimal ohne Antwort (Ablauf, A10), zusammen
  ≈ 11 min, danach Reset Laden 199. PASS nur, wenn jede Anfrage im
  Posteingang (Kategorie `hil`) stand, `apply_calls` unmittelbar vor
  der Antwort 0 war, nach der Freigabe `applied` mit
  `first_apply_at − checked_at ≥ 3 s` und `PriceChangeApplied` für
  Laden 199 kam, nach jeder Ablehnung `rejected` ohne Aufruf binnen
  8 s, nach jedem Ablauf `expired` 105–150 s nach `pending`, der
  Belege-Agent je Lauf Kasse und Warenwirtschaft ohne Rechtefehler
  gefragt hat, `decision.model` `planning` war und das awe-Log den
  Belege-Agenten und den Approver zeigt, den Planer ohne Tool (sonst
  „awe log not parsed“ bzw. „planner called a tool“). Ergebnis, Läufe
  (`modes`) und Hash in `build/gate-verified`, dazu `awe_tools`,
  `deny_paths`, `timeout_paths`, `deny_evidence`, `timeout_evidence`,
  `timeout_text` und seit UC1-30 `planner_retried_runs` (wiederholte
  von allen Läufen) und `planner_internal_tool_calls` (nur gemeldet,
  PASS hängt nicht daran); `deny_path`, `agent_status`,
  `evidence_path`, `engine_rule`, `tool_message`, `planner_attempts`
  und `planner_internal_tool_calls` je Lauf stehen im Lauf-Log
  (`build/e2e/`).
- A9 und A10 (Pflicht seit 12.11.) sind damit Teil der
  Gate-Verifikation: `scripts/install.sh mesh` wendet den
  Messe-Entrypoint nur nach ihrem PASS an. Ergebnisse vorher ansehen:
  `scripts/install.sh mesh --no-booth` (endet nach der
  Gate-Verifikation), `build/gate-verified` und das Lauf-Log prüfen,
  danach wendet der Owner mit `scripts/install.sh mesh` den
  Messe-Entrypoint an (bei PASS ohne neue Verifikation).
- Nach jeder Änderung an `mesh/connectors/`, `mesh/agents/` oder
  `mesh/workflows/` läuft die Verifikation in `scripts/install.sh mesh`
  erneut; ohne PASS kein Messe-Entrypoint.
- Ändern sich die Booth-Tools (wie am 12.11. `record_outcome` mit
  `tool_message`), zuerst das neue Image ausrollen (`make k8s-up`),
  dann `.venv/bin/python scripts/check_manifests.py` gegen die Pods,
  erst danach `scripts/install.sh mesh --no-booth`.
- Stand 12.11. (zweiter Lauf, Spezifikation 15.3): FAIL 4/10. Ablehnung
  4/4 ohne Preis, aber „Technischer Fehler“ (der Approver kopierte
  SAMs Status `error`); der Planer rief zweimal `append_to_artifact`.
  Behoben mit UC1-29 (Werkzeug-Ausschlüsse, `message`, Regel R5m).
- Stand 12.11. (dritter Lauf, Image 0.1.2, Spezifikation 15.4): FAIL
  8/10. Ablehnung 5/5 `rejected` über SAMs Text (R5m), Ablauf 2/2
  `expired` (R3a); Freigabe 1/3, weil der Planer zweimal in
  SAM-internen Tools hing, bis `recommend` nach 50 s abbrach. Behoben
  mit UC1-30 (Antwort als Text, `recommend` 30 s mit einer
  Wiederholung), verifiziert im vierten Lauf.
- Stand 12.11. (vierter Lauf, UC1-30, Spezifikation 15.5): PASS 10/10.
  In einem Ablauf-Lauf hing der erste Planer-Versuch trotz der neuen
  Prompt-Sätze; die Wiederholung rettete den Review (A4b 41,5 s statt
  etwa 10 s, A-38 belegt). Tragend ist die Wiederholung, eine weitere
  Prompt-Regel gibt es nicht (Entscheidung des Leads).
- Stand 12.11. (UC1-31, Spezifikation 15.6): Auf Kasse 01 ließ der
  Belege-Agent in S3 `get_article` aus (6/6, Preis richtig). Tool-Regel
  1b ist jetzt eine Liste je Signal, R3 `gpos-basket-review` 0.2.3;
  S3 danach 10/10 mit drei API-Abfragen. Der Gate-Hash ist neu.
- Stand 12.11. (fünfter Lauf, UC1-31, Hash `5180e515…`,
  `build/logs/mesh-up-7.log`, Spezifikation 15.6): PASS 10/10.
  Freigabe 3/3, Ablehnung 5/5 `rejected` über R5m (1,6 bis 1,7 s nach
  der Antwort), Ablauf 2/2 `expired` über R3a (124,7 und 127,9 s nach
  `pending`), kein Preis ohne Freigabe, `planner_retried_runs` 0/10.
  Danach Messe-Schritte 4.8 bis 4.10, Probes r1, r3 und r4 PASS.
- Stand 13.11. (UC1-32, Spezifikation 15.7): Image 0.1.3 läuft in
  allen sechs Deployments; die Engine übernimmt die Beleg-`numbers` bis
  160 Zeichen (vorher 120, S3 ohne `last_change`). `mesh/` ist
  unverändert, `make manifests` zeichengleich, smoke READY; der
  Gate-Hash `5180e515…` und das PASS des fünften Laufs gelten weiter,
  keine neue Gate-Verifikation.
- Rechtefehler eines Agent-Tools (A-16): den in der Ablehnung genannten
  Connector-Scope in `mesh/rbac/roles/gpos_marktleitung.yaml` ergänzen,
  `make mesh-up`.
- Keine Pause am Gate (A-1): F1 versuchen (Spezifikation 9.9,
  `toolsetConfigs` am Approver), auf Kasse 98 prüfen.
- F1 scheitert: F2. `.env` `GATE_GUARD=f2`, `scripts/install.sh k8s`,
  `scripts/install.sh mesh --fallback-f2`; die Gate-Verifikation mit
  F2 enthält die Pflicht-Ablehnungen (5/5 ohne Preis) und erwartet im
  awe-Log das gegatete `get_current_time` des F2-Approvers (A-34).
- Artefakt-Tools in der Werkzeugliste (A-21): `toolsetExcludedTools` am
  Agenten ergänzen, Gate-Verifikation erneut. Beide Toolsets müssen in
  `toolsets` stehen, sonst verwirft SAM die Ausschlüsse still; e2e
  meldet jedes der 12 ausgeschlossenen Tools als „artifact tool(s)
  called“.

## Abnahmeprotokoll UC1 (Spezifikation 13.5)

Vor jeder Messreihe `make demo-reset`; `make demo-watch` beenden
(e2e enthält dieselbe Logik). Ergebnisse aus `build/e2e/*.jsonl`
(eine Zeile je Lauf, Zusammenfassung mit p50/p90/p95). Je Kriterium
ausfüllen: Ergebnis, Datum, Image-Version, Bemerkung.

Abnahme 12.11.2026, Image 0.1.2, UC1-31 (Gate-Hash `5180e515…`): Reihe
auf Kasse 01 in `build/logs/acceptance-12-11.log` (102 Läufe, 102 ok,
0 falsche Preise, 0 Doppelanfragen). A1 bis A7 über die 82
Vorschlagsläufe (A8 und A10); A9 und der Ablauf in A10 aus dem fünften
Gate-Lauf auf Kasse 98 (`build/logs/mesh-up-7.log`). Ergebnis:
abgenommen bis auf die Owner-Entscheidungen (Spezifikation 16.1 Nr. 38,
40 und 41).

Nachtrag 13.11.2026: Nr. 41 ist entschieden und umgesetzt (UC1-32,
Spezifikation 15.7). Aktuell läuft Image 0.1.3 (`sha256:ea7e96ea…`),
Gate-Hash unverändert `5180e515…`. Die Werte unten stammen aus der
Reihe mit 0.1.2; die e2e-Messung S3 mit Regression (S1, S2, S7, S8) auf
Kasse 01 mit 0.1.3 lief am 13.11. (`build/logs/e2e-013-13-11.log`,
22/22 ok, Spezifikation 15.7). Offen bleibt Nr. 40.

Nachtrag 13.11.2026, Owner-Entscheidung Nr. 38 („Ziel anpassen“): Die
Latenzziele sind angepasst, nicht getunt: A4 p50 ≤ 18 s, p90 ≤ 24 s;
A4b p50 ≤ 12 s, p90 ≤ 18 s; A4a unverändert. Gegen die neuen Ziele
erfüllen der fünfte Gate-Lauf, die Reihe vom 12.11. und der
UC1-32-Lauf A4 und A4b (Ergebnis-Zeilen unten). Ergebnis: abgenommen
bis auf Nr. 40 (Vendor-Ticket 2, nicht gesendet).

- A1 Scan → Zeile auf `/monitor`, Ziel p95 ≤ 0,5 s
  - Messung: `make e2e SCENARIO=S1 RUNS=20`, Segment `a1_scan_row_s`
  - Ergebnis: 12.11., p95 0,05 s (186 Scans), erfüllt
- A2 Scan → Scan-Analyse-Chip (über SAM R1), Ziel p95 ≤ 1,5 s
  - Messung: wie A1, Segment `a2_scan_insight_s`
  - Ergebnis: 12.11., p95 0,12 s (186 Scans), erfüllt
- A3 `Closed` → Review `prepared`, Ziel p95 ≤ 2 s
  - Messung: wie A1, Segment `a3_closed_prepared_s`
  - Ergebnis: 12.11., p95 0,18 s (n = 82), erfüllt
- A4 `Closed` → Vorschlag `ready`, Ziel p50 ≤ 18 s, p90 ≤ 24 s (seit
  13.11., Owner-Entscheidung Spezifikation 16.1 Nr. 38; vorher p50
  ≤ 16 s, p90 ≤ 24 s seit 12.11., zwei KI-Stufen)
  - Messung: wie A1, Segment `a4_closed_ready_s`
  - Vormessung 12.11. (Gate-Lauf, Kasse 98, Image 0.1.1, n = 9): p50
    14,6 s, p90 18,6 s
  - Vormessung 12.11., dritter Lauf (Image 0.1.2, n = 8): p50 17,6 s,
    p90 21,2 s
  - Zählweise (auch A4b): Perzentile über alle Läufe, Läufe mit
    Planer-Wiederholung eingeschlossen; daneben die Perzentile der
    Läufe mit `planner_attempts` 1 angeben
  - Vormessung 12.11., vierter Lauf (UC1-30, n = 10, davon 1
    wiederholt): p50 15,2 s, p90 21,8 s, p95 34,0 s; ohne Wiederholung
    (n = 9) p50 15,1 s, p90 18,7 s
  - Vormessung 12.11., fünfter Lauf (UC1-31, n = 10): p50 15,7 s, p90
    18,5 s
  - Ergebnis: 12.11. (n = 82, 1 wiederholt): p50 16,03 s, p90 19,8 s,
    p95 23,2 s; ohne Wiederholung (n = 81) p50 16,00 s, p90 19,6 s.
    p90 erfüllt, p50 genau an der Grenze (0,03 s über 16 s; S3 und S7
    je 17,1 s); S1 ×20 allein p50 14,9 s, p90 21,9 s. Owner
    (Spezifikation 16.1 Nr. 38)
  - Ergebnis 13.11. gegen das neue Ziel, fünfter Lauf (n = 10): p50
    15,7 s, p90 18,5 s, erfüllt
  - Ergebnis 13.11. gegen das neue Ziel, Reihe 12.11. (n = 82, 1
    wiederholt): p50 16,03 s, p90 19,8 s, erfüllt
  - Ergebnis 13.11., UC1-32-Lauf (Kasse 01, Image 0.1.3, n = 20
    Vorschläge, keine Wiederholung): p50 16,5 s, p90 22,8 s, erfüllt
- A4a `Closed` → Belege (fast), Ziel p50 ≤ 9 s, p90 ≤ 12 s
  - Messung: wie A1, Segment `a4a_closed_evidence_s`
  - Vormessung 12.11. (n = 10): p50 4,9 s, p90 5,3 s
  - Vormessung 12.11., dritter Lauf (n = 10): p50 5,7 s, p90 8,3 s
  - Vormessung 12.11., vierter Lauf (n = 10): p50 4,7 s, p90 5,6 s
  - Vormessung 12.11., fünfter Lauf (n = 10): p50 4,6 s, p90 5,7 s
  - Ergebnis: 12.11. (n = 82): p50 5,1 s, p90 6,2 s, erfüllt
- A4b Belege → `ready`/`no_action` (planning), Ziel p50 ≤ 12 s, p90
  ≤ 18 s (seit 13.11., Owner-Entscheidung Spezifikation 16.1 Nr. 38;
  vorher p50 ≤ 8 s, p90 ≤ 12 s)
  - Messung: wie A1, Segment `a4b_evidence_decided_s`
  - Vormessung 12.11. (n = 9): p50 9,4 s, p90 13,3 s, knapp verfehlt;
    Ziel annehmen oder tunen entscheidet der Owner (Spezifikation 16.1
    Nr. 38)
  - Vormessung 12.11., dritter Lauf (n = 8): p50 11,3 s, p90 13,2 s;
    eine Planer-Wiederholung (seit UC1-30) kostet etwa 31 s mehr
  - Vormessung 12.11., vierter Lauf (n = 10, davon 1 wiederholt mit
    41,5 s): p50 10,4 s, p90 17,1 s, p95 29,3 s; ohne Wiederholung
    (n = 9) p50 10,3 s, p90 13,0 s
  - Vormessung 12.11., fünfter Lauf (n = 10, ohne Wiederholung): p50
    10,8 s, p90 13,9 s
  - Ergebnis: 12.11. (n = 82, 1 wiederholt mit 40,2 s): p50 10,8 s, p90
    14,3 s; ohne Wiederholung p50 10,8 s, p90 14,1 s. Verfehlt,
    Owner-Entscheidung (Spezifikation 16.1 Nr. 38)
  - Ergebnis 13.11. gegen das neue Ziel, fünfter Lauf (n = 10): p50
    10,8 s, p90 13,9 s, erfüllt
  - Ergebnis 13.11. gegen das neue Ziel, Reihe 12.11. (n = 82, 1
    wiederholt): p50 10,8 s, p90 14,3 s, erfüllt
  - Ergebnis 13.11., UC1-32-Lauf (Kasse 01, Image 0.1.3, n = 22 mit
    S8 und `deny`, keine Wiederholung): p50 11,4 s, p90 16,9 s,
    Läufe 8,4–27,5 s, erfüllt
- A5 `ready` → Anfrage im Posteingang, Ziel p90 ≤ 4 s
  - Messung: wie A1, Segment `a5_ready_request_s`
  - Vormessung 12.11. (n = 9): p50 3,4 s, p90 3,5 s
  - Vormessung 12.11., dritter Lauf (n = 8): p50 3,5 s, p90 4,3 s
  - Vormessung 12.11., vierter Lauf (n = 10): p50 3,4 s, p90 3,6 s
  - Vormessung 12.11., fünfter Lauf (n = 10): p50 3,4 s, p90 3,7 s
  - Ergebnis: 12.11. (n = 82): p50 3,4 s, p90 3,75 s, erfüllt
- A6 Freigabe → `PriceChangeApplied`, Ziel p95 ≤ 2 s
  - Messung: wie A1, Segment `a6_answer_applied_s`
  - Ergebnis: 12.11. (n = 82): p95 0,14 s, erfüllt
- A7 Freigabe → nächster Scan zeigt den neuen Preis, Ziel sofort
  - Messung: wie A1, Feld `a7_next_scan_ok`
  - Ergebnis: 12.11.: 82/82 mit neuem Preis, erfüllt
- A8 S1, S2, S3, S7 mit Freigabe, je 20 Läufe, Ziel je ≥ 19/20 richtig
  (Artikel, Anlass, Preis), kein falscher Preis, Gate- und
  Agent-Prüfung 20/20, `decision.model` `planning`, S1 genau 2
  API-Abfragen
  - Messung: `make e2e SCENARIO=S1 RUNS=20` (ebenso S2, S3, S7), Felder
    `correct`, `wrong_price`, `apply_calls_before`, `agent_tools`,
    `ai_model`, `api_queries`, `planner_attempts`
  - Planer-Wiederholungen: `planner_retried_runs` der Zusammenfassung
    je Reihe eintragen; Ziel höchstens 1/20, 2/20 an den Owner melden,
    ab 3/20 gilt A8 als verfehlt (Spezifikation 13.5 A8, 15.4 F3 wieder
    offen)
  - S3 (seit UC1-31): Tool-Regel 1b fragt `get_transaction`,
    `get_article` und `get_purchase_behaviour`, also 3 API-Abfragen
    (`api_queries` 3, in S3 nur gemeldet); die Agent-Prüfung scheitert
    ohne WWS-Aufruf oder ohne `get_purchase_behaviour`. Vormessung
    12.11. (Kasse 01, n = 10): 10/10, A4 16,4–23,7 s
  - Ergebnis 12.11. (Kasse 01, je 20): S1 20/20, S2 20/20, S3 20/20
    (alle mit 3 API-Abfragen), S7 20/20; 0 falsche Preise, Gate- und
    Agent-Prüfung je 20/20, `planning` 80/80, S1 je 2 API-Abfragen.
    `planner_retried_runs` S1 1/20 (Lauf 3, A4 44,7 s, richtig), S2,
    S3 und S7 je 0/20. Erfüllt
- A9 Ablehnung, Ziel 5/5 `rejected`, kein Preis, ≤ 8 s nach der Antwort,
  `deny_path` gemeldet (Ziel `clean`; `error_fallback` besteht) und der
  Beleg der Engine `evidence_path` (`status`, `message` = SAMs Text
  über den Approver, `error`; jeder Pfad besteht)
  - Messung: Teil von `make gate-verify` (vor dem Messe-Entrypoint,
    einzeln `make e2e TILL=98 SCENARIO=S1 MODE=deny RUNS=5`), Felder
    `deny_paths`, `deny_evidence`, `agent_status`, `status_reason`,
    `awe_refusal_ok`
  - Vormessung 12.11. (vor UC1-29): 4/4 ohne Preis, aber `failed`;
    behoben mit UC1-29 (Messungen unten)
  - Vormessung 12.11., dritter Lauf (mit UC1-29): 5/5 `rejected` ohne
    Preis, `evidence_path` `message`, Regel R5m
  - Vormessung 12.11., vierter Lauf (mit UC1-30): 5/5 `rejected` ohne
    Preis über R5m, 1,6 bis 1,9 s nach der Antwort
  - Ergebnis: 12.11., fünfter Lauf (Kasse 98): 5/5 `rejected` ohne
    Preis über R5m, `deny_paths` 5 `clean`, `deny_evidence` `message`
    5, 1,6 bis 1,7 s nach der Antwort. Erfüllt
- A10 Ablauf und späte Freigabe, Ziel 2/2 `expired` nach 120 s ± 15 s,
  2/2 `approved` trotz Antwort nach 100 s
  - Messung: Teil von `make gate-verify` (vor dem Messe-Entrypoint,
    einzeln `make e2e TILL=98 SCENARIO=S1 MODE=timeout RUNS=2`, Felder
    `timeout_path`, `timeout_evidence`, `evidence_path`),
    `make e2e SCENARIO=S1 RUNS=2 ANSWER_DELAY=100`
  - Vormessung 12.11. (vor UC1-29): 2/2 `expired` 125 s nach `pending`,
    kein Preis; späte Freigabe noch nicht gemessen
  - Vormessung 12.11., dritter Lauf (mit UC1-29): 2/2 `expired` 125 s
    nach `pending` über SAMs Ablauftext (R3a), kein Preis
  - Vormessung 12.11., vierter Lauf (mit UC1-30): 2/2 `expired` 125 s
    nach `pending` über R3a, einer davon mit Planer-Wiederholung
  - Ergebnis: 12.11., fünfter Lauf (Kasse 98): 2/2 `expired` 124,7 und
    127,9 s nach `pending` über R3a (`timeout_paths` 2 `clean`), kein
    Preis; Kasse 01 mit `--answer-delay 100`: 2/2 `approved`, Preis
    100,13 und 100,19 s nach `checked_at` (`check_proposal`). Erfüllt
    (A-18 belegt)
- A11 Doppelanfragen, Ziel je Vorschlag genau eine Preisaktion, Banner
  binnen 2 s, Rate gemeldet (Erwartung ≤ 2/20)
  - Messung: Feld `duplicates` aller A8-Läufe
  - Ergebnis: 12.11.: 0 Doppelanfragen in 102 Läufen (Gate-Lauf 0/10),
    je Freigabe genau eine Preisaktion (82/82). Erfüllt; der Banner kam
    nicht vor
- A12 S4, S5, S6 und S8, Ziel je 5/5: S4–S6 ohne KI im Review und mit
  richtigem Zustand, S8 zwei Agentenläufe (fast, planning), Review
  `no_action`
  - Messung: `make e2e SCENARIO=S4 RUNS=5` (ebenso S5, S6, S8)
  - Ergebnis: 12.11.: S4 5/5 `no_candidates`, S5 5/5 `only_blocked`,
    S6 5/5 `no_candidates`, je ohne KI; S8 5/5 `no_action` mit
    `planning`, kein Vorschlag. Erfüllt
- A13 Hygiene, Ziel `check_hygiene.sh` und `--platform` grün, keine
  GEBIT-Datei im Image
  - Messung: `make hygiene`, `scripts/check_hygiene.sh --platform`,
    `docker run --rm <image> find / -name '*.pb'` zeigt nur
    `showcase.pb`
  - Ergebnis: 12.11.: `check_hygiene.sh` und `--platform` (31
    `gpos-*`-Ressourcen) sauber. Image 0.1.2 lesend geprüft: einziges
    `*.pb` ist `showcase.pb`, keine LLM- oder Key-Variable, Nutzer
    10001; erfüllt
  - Ergebnis 13.11. (Image 0.1.3 `sha256:ea7e96ea…`, Deploy UC1-32,
    Spezifikation 15.7): einziges `*.pb` ist
    `/app/descriptors/showcase.pb`, keine LLM- oder Key-Variable und
    keine GEBIT-Datei im Image, Nutzer 10001:10001; `check_hygiene.sh`
    vor und nach dem Deploy sauber (`--platform` nicht neu, `mesh/`
    unverändert); erfüllt
- A14 Reset, Ziel < 15 s, danach Ente 9,99 €, keine offene Anfrage,
  kein Vorschlag `pending`, keine Queue ohne `txFlows`; S1 und S3 direkt
  danach wiederholbar; Knopf-Reset mit Wächter: Anfrage binnen 5 s weg
  - Messung: Feld `reset_s` der e2e-Läufe, `scripts/broker.sh orphans`
  - Ergebnis: …
- A15 Größen, Ziel alle Tool-Ergebnisse innerhalb der Grenzen 8.1
  - Messung: `make smoke` (Zeilen `size …`)
  - Ergebnis: …

Annahmen, die diese Läufe belegen oder widerlegen (in 16.2 nachtragen):
A-1 und A-16 (Gate-Verifikation), A-4 (Probe p4/r4 ohne `hil`-Anfrage),
A-17 (Probes aus dem Pod), A-18 (A10), A-21 (Werkzeugliste), A-22
(Form von `successOutput`), A-23 (Posteingang), A-36 (Antwortfälle
und `message` des Approvers, A9/A10), A-37 (Planer ohne Tool), A-38
(Planer-Wiederholung mit 30 s je Versuch, seit dem vierten Lauf am
12.11. belegt).
