# Sign-off-Memo: Solace Event Portal → OpenMetadata Connector v1.0

**An:** ALDI Nord Platform Team + IT-Security
**Von:** Solace Technical Account Team
**Datum:** 2026-05-27
**Betreff:** Freigabe Implementierungsplan v1.0.0 für Production-Deployment
**Status:** Entscheidung erbeten bis Ende KW22

---

## 1. Zusammenfassung

Am 26. und 27. Mai 2026 hat das Solace-Team mit ALDI Nord eine
strukturierte Discovery über sechs Themen-Cluster durchgeführt
(EP-Edition, OM-Edition, Asset-Mapping, Identity, Source-of-Truth,
Security). Alle Antworten wurden gegen ALDI's Referenz-Tenant `seall`
(Solace Cloud Enterprise) verifiziert; das Mapping ist im Living-Doc
`docs/asset-mapping-spec.md` dokumentiert. Auf Basis dieser Discovery
plus zwei nachgereichter Anforderungen (Field-Level-Schema-Parsing
und dynamische System-vs-Pipeline-Klassifizierung) liegt jetzt ein
finaler Implementierungsplan über sieben Wellen vor, der die heutige
Pilot-Version in eine production-ready v1.0.0 für den Live-Betrieb
bei ALDI überführt.

**Gesamtaufwand:** 10 Wochen Solace-Engineering vom Kick-off bis
v1.0.0 GA. Optional anschließend ein Quartal Upstream-Contribution
zu OpenMetadata, damit ALDI langfristig auf dem nativen Connector
statt auf einer Custom-Image-Variante laufen kann.

Der Plan baut auf drei tiefgehenden Vergleichsanalysen auf
(Databricks-, Confluent-Kafka- und OpenMetadata-Upstream-Connector
für Messaging-Systeme), aus denen sieben konkrete Punkte abgeleitet
sind, in denen unser EP-Connector den nativen Kafka-Connector strikt
übertrifft (siehe `docs/discovery-closure-summary.md`, Abschnitt
„Strategische Deltas").

---

## 2. Geltungsbereich

| Wellenplan | Inhalt | Dauer | Image |
| --- | --- | --- | --- |
| Welle 0 | OM-1.11-SDK-Migration (Foundation) | 1 Woche | 0.4.0 |
| Welle 1 | Schema-Field-Parsing + Custom-Attributes-als-Tags | 1 Woche | 0.5.0 |
| Welle 2 | Lineage (within-EP + Cross-System SAP/Kafka/Snowflake/Databricks) | 2 Wochen | 0.6.0 |
| Welle 3 | Neue Entitätstypen (Event-API, EAPP, First-class-Schemas, Topic-Tree, Consumer-Queue) | 1 Woche | 0.7.0 |
| Welle 4 | Identity-Resolution + Bi-Direktionaler Sync (OM → EP) + Soft-Delete | 1 Woche | 0.8.0 |
| Welle 5 | Production Hardening (Multi-Tenant, PII-Erkennung, OTel-Audit, Helm, Vault-Vorbereitung) | 2 Wochen | 0.9.0 |
| Welle 6 | GA-Release + ALDI-Production-Cutover | 1 Woche | **1.0.0** |
| Welle 7 | OpenMetadata Upstream-Contribution (Q3, optional) | post-GA | upstream |

Detaillierte Pro-Welle-Acceptance-Kriterien siehe
`docs/implementation-plan.md`.

---

## 3. Risiken, die ALDI bewusst akzeptiert (Stand v1.0)

| Risiko | Bewertung | Mitigation v1.0 | Mitigation v1.1 |
| --- | --- | --- | --- |
| 90-Tage-manuelle Token-Rotation (EP + OM-Bot-JWT) | **HOCH** | Prometheus-Alert auf 401-Counter, Runbook | Vault-basierte Automation (geplant Q3) |
| EP-Token mit Write-Scope für Bi-Dir-Sync (#49) | **HOCH** | Separates Secret `ep-token-writer`, Scope nur auf `/architecture/<entity>/{id}` CA-PUT | Vault-Rotation mit kurzer TTL |
| Plain-K8s-Secrets statt Vault | **MITTEL** | Audit-Log, Network-Policies, RBAC-Tightening | Vault-Backend ab v1.1 |
| Statischer `userIdToEmailMap` (EP exponiert kein IAM-API) | **MITTEL** | Quarterly-Sync-Skript, WARN-Log bei Miss | Synchronisation aus ALDI Keycloak |
| OM-1.11-SDK-Migration potenziell breaking | **MITTEL** | Staged Release: Smoke-Test gegen `openmetadata/server:1.11.x` vor Production | dauerhafter CI-Job |
| Linked-App-Auto-Klassifizierung (#65) False-Positives | **MITTEL** | Default OFF, Dry-Run-Modus, explizite Allow-List | Machine-Learning-basierte Heuristik (nicht geplant) |
| EP-API-Felddeprecation zwischen Cloud-Releases | **NIEDRIG** | Defensive Dict-Access, CI-Smoke-Test gegen live Tenant | unverändert |

---

## 4. Endgültig parkierte Themen

Die folgenden Themen sind durch die Discovery als nicht-anwendbar
bzw. nicht-implementierbar markiert worden:

- **Modeled Event Mesh → DataProduct** (Cluster 1.3): nicht in
  ALDI's Cloud-Enterprise-Edition verfügbar. Wird durch das
  Event-API-Product-Mapping (Welle 3) funktional abgedeckt.
- **OutBound-Webhooks von EP**: EP Cloud Enterprise exponiert sie
  nicht. Polling-Mode dauerhaft. Konsequenz: minimale Latenz für
  EP-Änderungen ≈ 10 Sekunden (Polling-Intervall, konfigurierbar).
- **EP-Teams → OM-Teams**: EP exponiert kein Team-API. Wenn
  gewünscht, müsste ALDI eine externe Quelle (Keycloak-Groups,
  HR-System) anbinden — eigenes Folge-Projekt.
- **EP-User-Lookup-API**: nachweislich nicht vorhanden (10-Pfad-
  Probe). Identity-Resolution dauerhaft über statische Map.

---

## 5. Sign-off-Fragen

Für die finale Plan-Freigabe benötigen wir Antworten auf vier Fragen.
Wir empfehlen pro Frage einen Default; ALDI kann jederzeit überstimmen.

### Frage 1 — OM-Patch-Version (Welle 0)

ALDI hat in Cluster 2.1 angegeben „OM 1.11, demnächst 1.13". 1.13
ist noch nicht released. Wir benötigen die genaue 1.11-Patch-Version,
gegen die wir Welle 0 testen.

- [ ] Wir laufen aktuell auf OM 1.11.\_\_\_\_ (genaue Patch-Version
  bitte ausfüllen).
- [ ] Bis Ende KW22 planen wir den Upgrade auf 1.11.14 (latest
  stable) — **Solace-Empfehlung**.
- [ ] Anders: \_\_\_\_

### Frage 2 — Scope Bi-Direktionaler Sync (Welle 4, #49)

Welche OM-Felder dürfen zurück nach EP geschrieben werden? Solace-
Empfehlung in **fett**.

- [ ] **Extended Description (additiv)** — ja / nein
- [ ] **Tags (CA-gemappt, OM-added)** — ja / nein
- [ ] **Classification (OM-zugewiesen)** — ja / nein
- [ ] **Certification** — ja / nein
- [ ] **Additional Owners (OM-zugewiesen)** — ja / nein
- [ ] **External-System-Linkage** — ja / nein

Außerdem: Approval für einen separaten, write-scoped EP-Token
(`ep-token-writer`)? Solace-Empfehlung: **ja**, getrennt vom
read-only-Token rotieren.

- [ ] Write-Token freigegeben — ja / nein

### Frage 3 — PII-Source-Signal-Patterns (Welle 5, #62)

ALDI hat in Cluster 6.1 bestätigt, dass PII vorkommt und über
Tag/CA/Topic-Segment/Schema-Feld-Annotation gekennzeichnet wird.
Bitte konkretisieren:

- Custom-Attribute-Name auf Domain/Event/App, der PII signalisiert:
  z. B. `containsPii` oder `pii` — \_\_\_\_
- Tag-Pattern auf Entity, das PII signalisiert: z. B. `pii-*` oder
  `PII.*` — \_\_\_\_
- Topic-Adress-Segment, das PII signalisiert: z. B. `/personal/`
  oder `/pii/` — \_\_\_\_
- Schema-Feld-Annotation in JSON-Schema / Avro doc: z. B.
  `x-pii: true` (Solace-Empfehlung als Standard) — bitte
  bestätigen oder Alternative angeben — \_\_\_\_

### Frage 4 — Upstream-Contribution (Welle 7)

Wir möchten den Connector im Q3 2026 nach Production-GA als nativen
Connector an die OpenMetadata-Community contributen. Vorteil für
ALDI: langfristig kein Custom-Image, sondern offizieller Support
durch OM-Maintainer.

- [ ] **ALDI als Reference-Customer in der PR-Description nennen** —
  ja / nein (Solace-Empfehlung: **ja**, beschleunigt Review)
- [ ] **Zeitpunkt**: 30 Tage nach GA-Stabilität — OK / anders: \_\_\_\_

---

## 6. Empfehlung

Solace empfiehlt:

1. Freigabe des Plans wie vorliegend (alle sieben Wellen,
   chronologisch).
2. Wave 0 startet sofort nach Sign-off.
3. Akzeptanz der drei „HOCH"-Risiken im obigen Risikoregister für
   v1.0 mit verbindlicher Vault-Migration in v1.1.
4. Wöchentliche Demo-Sitzung am Ende jeder Welle (ca. 30 Min) für
   Live-Verifikation des Stands in der ALDI-Staging-OM-Instanz.

---

## 7. Sign-off

**ALDI Platform Team**

Name: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

Rolle: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

Datum: \_\_\_\_\_\_\_\_\_\_\_

Unterschrift: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**ALDI IT-Security**

Name: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

Rolle: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

Datum: \_\_\_\_\_\_\_\_\_\_\_

Unterschrift: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Solace Technical Account Team**

Name: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

Datum: \_\_\_\_\_\_\_\_\_\_\_

Unterschrift: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

---

**Anhang (zur Vertiefung verfügbar)**

- `docs/discovery-closure-summary.md` — vollständige Discovery-Auswertung
- `docs/asset-mapping-spec.md` — Mapping-Spezifikation pro Cluster
- `docs/implementation-plan.md` — Pro-Welle-Detailplan mit
  Acceptance-Kriterien
- `docs/EP-edition-compatibility.md` — EP-Endpoint-Matrix
- `docs/workshop-demo-script.md` — Pilot-Demo-Drehbuch
