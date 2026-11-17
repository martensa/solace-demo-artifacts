# Gate 0 – Stand 11.11.2026, 12:00

Owner-Freigaben O1, O2 (11.11.) sowie O3, O7 (10.11.) sind im Lab
umgesetzt. Berichte je Spike in diesem Ordner.

| Spike | Stand | Kern |
|---|---|---|
| G0-01 SAM-Paket, MCP-Grenzen | bestanden, mit Auflage | Apply/Deploy grün, 57/57 Läufe `completed`, 20/20 JSON-gleich mit `@type`, Weiche mit `default`, alle Strukturfelder lösen auf; `CallToolResult` ≤ 1800 B nur mit einzeiligem Text-Content (SDK-Standard 2755/4116 B); Ereignisse von gebitsim nach GEBIT-Deskriptor, Original-Beispiele nicht gesendet; nachgeprüft; [G0-01.md](G0-01.md) |
| G0-02 nativer HITL | entschieden: B1 | Agent-Knoten mit gegatetem Tool trägt im Ereignislauf; B2/B3 pausieren nicht (Frage an Solace); Risiken Doppelaufruf und verwaiste Anfragen; [G0-02.md](G0-02.md) |
| G0-03 `notify_user` | bestanden | 10/10, ≤ 0,1 s, Umlaute korrekt; Stolperstein `input_schema`; [G0-03.md](G0-03.md) |
| G0-04 Notify-API | teilweise | T6/T8 (Antwort und Abbruch per REST, `?userId=`) bestanden; T7/T7b, T13/T14 offen |
| G0-05 Foto in Workflow | teilweise, Rückfall gewählt | S1 `describe_image`-Tool-Knoten FAIL („No multimodal LLM“, `tool_config` wird nicht gelesen); S3 PASS mit `extractExpression` und `user:`-Namen; S3b, S5b PASS; Transport A2b mit Agent-Knoten 4,1–4,5 s (Kriterium < 4 s verfehlt, nur A2 Inline-Vision 2,3–2,6 s erfüllt es); echte Requisitenfotos OFFEN; nachgeprüft, zwei Korrekturen; [G0-05.md](G0-05.md) |
| G0-06 Bildgenerierung | Soll, nicht in G0a | – |
| G0-07 gRPC am Lab-Ingress | bestanden bis auf Postman | grpcurl über TLS mit Lab-CA, Kyverno, 2 MB mit `proxy-body-size`; Postman manuell offen; SAM-WebUI-Ingress steht auf 1 MB; [G0-07.md](G0-07.md) |
| G0-08a Last Tool-Läufe | bestanden | 450/h, Bursts von 7, 224/224 `completed`; p95 0,32 s (Client) / 0,25 s (SAM); 0 Neustarts; Spool flach; Rückfall nicht nötig; nachgeprüft; [G0-08a.md](G0-08a.md) |
| G0-08b Last Kette | bis 25.11. | Werkzeug `tools/hitl_api_test.py` als Basis |
| G0-09 Agentenlatenz | teilweise bestanden | Schreib-Agent p50 4,81 s, p90 5,65 s; 20/20 UTF-8 mit ä ö ü ß €; Pfad über MCP, Engine, SMF, Browser und je 20 Aufrufe `gpos-loyalty-agent`/`gpos-price-scout` OFFEN; B1-Doppelaufruf 5/50, gehärteter Prompt 0/50; nachgeprüft; [G0-09.md](G0-09.md) |
| G0-10 Broker-Optionen | bestanden | SAM-Queue und `existingQueueName` empfangen 100 %; `qos` ohne Wirkung; SAM-Queue ohne TTL, Undeploy löscht sie; Entscheidung: R1 eigene Queue (max-ttl 20 s), R2–R5 SAM-Queue mit Veraltungsschutz; gwe-Neustart OFFEN; nachgeprüft; [G0-10.md](G0-10.md) |
| G0-11a/b AKS | wartet auf O4 | – |
| G0-12 LiteLLM-Messe-Key, Preise | Preise gesetzt | Key wartet auf O5 |
| G0-13 Postgres, SMF | bestanden | DDL idempotent (Loyalty-SQL korrigiert), Wheel py3.13 arm64/amd64, persistentes Publish; Pods erreichen den Broker über `host.docker.internal:55557`; [G0-13.md](G0-13.md) |

## Befunde mit Wirkung auf den Plan

1. Native Freigabe = Variante B1 (Agent-Knoten, `fast`), zwei
   KI-Aufrufe je Freigabe; B2/B3 bis zur Antwort von Solace gesperrt.
2. Ereignisläufe erhalten Benutzerrollen erst nach einer ersten
   Anmeldung des Benutzers; sonst `system:default`.
3. Nicht deklarierte Felder in der Nutzlast leeren den Workflow-Input
   still; Templates bleiben als Text stehen.
4. `fast` ruft das gegatete Tool gelegentlich doppelt auf (G0-02 2/13,
   G0-09 5/50, immer nach dem ersten Tool-Ergebnis); der gehärtete
   Prompt aus G0-09 senkt das auf 0/50 (Fisher p = 0,056). Härtung in
   3.5/3.8 übernehmen; Idempotenz von `apply_price` und der Ausgang aus
   der Engine bleiben Pflicht (1/50 meldete `denied` trotz Freigabe).
5. awe-Neustart: Lauf scheitert, Agent-Aufgabe kehrt mit neuer
   Anfrage zurück; Abbruch per REST funktioniert;
   `durable_task_resume` hilft nicht (getestet, zurückgenommen).
6. SMF aus Pods: Port 55557 statt 55555; Nutzlast als `bytearray`.
7. SAM-WebUI-Ingress lässt nur 1 MB zu (Rückfall A3 Foto-Upload im
   Chat) – Annotation `proxy-body-size` wäre eine Infra-Änderung.
8. `loyalty.article_ref` fehlen article011 und article025; Plan 2.5
   zählt 14 statt 16 Loyalty-Tabellen; Hostname `pos-grpc` vs.
   `gpos-grpc` vereinheitlichen.
9. MCP-Tools liefern den Text-Content einzeilig
   (`Annotated[CallToolResult, Modell]`); der SDK-Standard schreibt das
   Ergebnis zusätzlich eingerückt in den Text und reißt 1800 B. Die
   2048-B-Grenze hängt in 2.542.1 am Text-Content, Strukturfelder lösen
   im Workflow-Tool-Knoten trotzdem auf (R16 präzisieren; Agent-Tool-
   Aufrufe ungetestet). Budget 1800 B bleibt, dazu Text ≤ 1500 B.
10. SAM serialisiert die Ereignis-Nutzlast neu (kompakt, Schlüssel
    sortiert): Engine hasht und dedupliziert nur kanonisches JSON.
    `initialRequestText` ist auf 1024 Zeichen gekürzt; die Tasks-API
    ignoriert `page=`, `pageSize` höchstens 100.
11. Die WebUI-Tabelle `tasks` ist unter Spitzenlast unvollständig: bei
    96 Läufen/s (G0-10 T2b) 183 von 1200 Läufen ohne Zeile, 137 ohne
    Status, obwohl alle Ergebnisse ankamen; bei 450/h vollständig.
    Zählungen und `/op` auf successOutput bzw. Engine stützen.
12. `describe_image` im Workflow-Tool-Knoten liest `tool_config` nicht
    (braucht ein Agenten-Modell): 3.6 `read` wird Agent-Knoten
    `gpos-price-scout` mit `load_artifact`; `tool_config` und
    `GPOS_VISION_MODEL` streichen; Frage an Solace (10).
13. `artifactProcessing` wirkt nur mit `extractExpression` und
    `artifactDefinition` (camelCase); `extractArtifactsExpression` aus
    Plan 3.2 und snake_case werden still ignoriert. Workflow-Ziele
    brauchen den Dateinamen `user:cp-<scan_id>.jpg`.
14. Jeder Workflow-Lauf legt Knoten-Artefakte (`wf_*`) bei der
    Laufidentität ab; `marktleitung` hat nach einem Lab-Tag 3 189.
    Findet ein Agent sein Bild nicht, ruft er `list_artifacts` und bekommt
    0,77–0,89 MB (bis 59 k Input-Token, 23–30 s, Timeout). Scout ohne
    `list_artifacts`, Reset löscht die Artefakte der Laufidentität,
    Speicher in G3 beobachten.
15. Negativbilder: Konfidenz 0,95 auch bei unlesbarem Bild; die
    Schranke liegt auf `readable`, Preis ≠ null und Katalogtreffer.
16. Umlaute: Schreib-Agent liefert 20/20 korrektes UTF-8; die ASCII-Regel
    in 3.8 kann fallen, endgültig erst nach dem MCP-Weg. Validator 8.4
    entfernt U+00AD und normalisiert NFC. Textqualität schwach (Längen
    12/20, Slot = Empfehlung 10/20) → AP06.
17. Broker: `qos` am Abo wirkt nicht (immer durable Queue); SAM-Queues
    haben keine TTL und verschwinden mit dem Undeploy samt Inhalt;
    Update per `apply` ist verlustfrei. R1 auf eigene Queue
    (`existingQueueName`, max-ttl 20 s statt 30 s in 3.2,
    max-redelivery 1), Preflight per SEMP `txFlows`; kein Undeploy auf der
    Messe. success-/errorOutput gehen als Direct-Nachrichten raus.
18. `successOutput` mit `responseType: structured` liefert in 2.542.1 die
    Workflow-Ausgabe (Doku: `null`); Doku-Abweichung an Solace melden.
19. Die Plattform-API gibt `tool_config.api_key` im Klartext zurück: Der
    LiteLLM-Key stand in den G0-05-Workflows `gpos-spike-p05-s1a`–`s1d`
    und `-s5`. Am 11.11. um 15:45 undeployt und gelöscht; danach enthält
    kein Workflow und kein Workflow-Deployment in der DB den Key mehr, und
    keine Antwort der Plattform-API (Workflows, Entrypoints, Deployments,
    Agents, Connectors, Models) liefert ihn. Plan 3.6 ohne `tool_config`.
    Plattform-Verhalten, nicht vom Spike: Jeder Entrypoint-Deployment-
    Snapshot (`gateway_deployments`, auch `developer-mcp` vom 10.11.)
    speichert das Standardmodell samt `api_key` als Text in der DB,
    wie `model_configurations`; die API gibt beides nicht heraus.
    Owner-Vorgabe 11.11.: SAM verwaltet die Modelle, der LiteLLM-Key
    bleibt in der SAM-Konfiguration (Modell-Aliasse); Demo-Dienste,
    Workflows und `tool_config` tragen nie einen Key.
    Die sieben Regeln von `gpos-spike-ep-p05` auf die gelöschten
    Workflows (s1a–s1d, s3sc, s3plan, s5) sind per `apply` entfernt; das
    Spike-Paket liest den Key nicht mehr (`run.sh`), die alten Dateien
    liegen in `g0-05/mesh-retired/`.
20. Lab: DMR-Link `solace-1` → `solace-2` ist unten; die Cluster-Queue auf
    VPN `default` hält 2058 Nachrichten (7,96 MB) und wächst mit jedem
    persistenten Ereignis. Vor G3 Event-Mesh `start.sh` oder Spool von
    VPN `default` mitbeobachten.
21. Broker: Entfernt ein `apply` eine Regel aus einem Entrypoint, bleibt
    ihre SAM-Queue stehen – ohne Konsument, mit Abo, ohne TTL (G0-05,
    7 Queues, per SEMP gelöscht). Auf der Messe sammelt eine solche Queue
    jedes passende Ereignis auf Dauer. Regeln nie umbenennen oder
    entfernen, ohne die Queue `…/eventmesh/<ep>/<regel>` danach per SEMP
    zu löschen; der Preflight listet Queues mit 0 `txFlows`.

## Laufende Lab-Ressourcen (Gate 0)

- SAM: Workflows `gpos-spike-hil-a`, `gpos-spike-hil-b1`,
  `gpos-spike-notify`, Agent `gpos-spike-approver`, Entrypoint
  `gpos-spike-events`.
- Von UC1 übernommen (`mesh/manifest-rbac.yaml`, Manifest
  `gpos-g0-rbac`; Laufidentität der Entrypoints, Freigabe-Inbox) – beim
  Gate-0-Aufräumen NICHT löschen: Rolle `gpos_marktleitung`,
  Claim-Mapping `keycloak-group-marktleitung`, Keycloak-Gruppe und
  -Benutzer `marktleitung`.
- Kubernetes: Namespace `gpos-g0` am 12.11.2026 gelöscht (mit
  Deployments, Services, Ingresses und Secret
  `gpos-g0-gebit-descriptors`); leerer Namespace `gpos-g0-13` besteht.
- Docker: Image `gpos-g0-grpc:spike`.
- G0-01/G0-08a: Connector `gpos-spike-p01-tools`, Workflow
  `gpos-spike-p01-pos`, Entrypoint `gpos-spike-ep-p01`; Image
  `gpos-spike-p01-stub:spike`. Deployment und Service
  `gpos-spike-p01-stub` in `gpos-g0`: mit dem Namespace gelöscht;
  Connector `gpos-spike-p01-tools` seither ohne Ziel.
- G0-05: SAM-Objekte am 12.11.2026 gelöscht (Entrypoint
  `gpos-spike-ep-p05`, Workflows `gpos-spike-p05-s1e`, `-s1f`, `-s5b`,
  `-s3a`, Agents `gpos-spike-p05-scout`, `-scout-la`, Connector
  `gpos-spike-p05-photo`; `s1a`–`s1d` und `-s5` schon am 11.11.);
  Deployment und Service `gpos-spike-p05-photo` mit dem Namespace
  `gpos-g0` gelöscht. Es bleiben Image `gpos-spike-p05-mcp:spike` und
  Artefakte bei `marktleitung`.
- G0-09: Entrypoint `gpos-spike-ep-p09`, Workflows `gpos-spike-p09-write`,
  `-write-n`, `-b1`, `-b1h`, Agents `gpos-spike-p09-writer`, `-approver`,
  `-approver-h`.
- G0-10: Entrypoint `gpos-spike-ep-p10`, Workflow `gpos-spike-p10-echo`,
  Queue `gpos-spike-p10-q` auf VPN `default` (`solace-1`).
- Aufräumbefehle je Spike im Bericht (nie `--prune`); lokale
  `.rendered/`-Ordner mit Zugangsdaten (chmod 600) in `g0-01`, `g0-09`,
  `g0-10` und im Spike-Wurzelordner.
