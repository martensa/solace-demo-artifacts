# AKS-Migrationsplan: EuroCIS-Showcase vom Lab nach Azure

Stand 17.11.2026, überarbeitet nach den Owner-Entscheidungen vom 17.11.2026
(Abschnitt 2); die Fassung vom 16.11. liegt im sda-Commit 7a860c5.
Vorschlag für den Owner, read-only erarbeitet: Es wurde nichts
angelegt, geändert oder gelöscht. Messe: EuroCIS 2027, 16.-18.02.2027.
Gates: G2a 18.12.2026, G2b 15.01.2027, G3 22.01.2027, Freeze G4
05.02.2027 [Quelle: PLAN 0.3].

Lesehinweis:

- Abkürzungen für Quellen: `sda` = Repo solace-demo-artifacts, `sli` =
  Repo solace-lab-infrastructure, `amd` = sda/agent-mesh-deployment,
  `emd` = sda/event-mesh-deployment, `gpd` =
  sda/gebit-price-agent-demo, `PLAN` = gpd/IMPLEMENTATION-PLAN.md
  (zitiert nach Abschnitt, weil der PLAN parallel nachgezogen wird),
  `RA` = gpd/research/impl/research-aks.md.
- "Befehl (16.11.)" bzw. "Befehl (17.11.)" heißt: read-only im Lab oder
  gegen öffentliche APIs ausgeführt, am genannten Tag 2026.
- [A] markiert eine Annahme, die noch zu prüfen ist.
- Preise: Listenpreise Pay-as-you-go, EUR ohne MwSt., Germany West
  Central, 730 h/Monat [Quelle: `prices.azure.com/api/retail/prices`,
  16.11., am 17.11. neu geprüft].
- Platzhalter: `<p>` (neutrales DNS-Label-Präfix ohne Kunden- oder
  Projektnamen), `<fqdn>` =
  `<p>.germanywestcentral.cloudapp.azure.com`, `<acr>`, `<kv>`,
  `<owner-ip>`, `<owner-objectId>`, `<subscription>`, `<tenant>`. Die
  Werte stehen nur lokal, nie in diesem Dokument.
- Entscheidungen dieses Plans heißen `AKS-E1` bis `AKS-E20`, damit sie
  nicht mit den PLAN-Entscheidungen (PLAN-E1 bis PLAN-E8) und den
  Owner-Punkten O1-O9 kollidieren. Ihr Status steht in Abschnitt 2.
- `kaks` und `haks` sind die einzigen Ad-hoc-Wege zu AKS für kubectl
  und helm (Definition in P1 Schritt 6). Lab-Befehle tragen
  `--context rancher-desktop`.
- Keine Secrets, IDs, E-Mail-Adressen (außer Lab-Demo-Identitäten wie
  `marktleitung@solace.lab`) oder LLM-Hostnamen in diesem Dokument.
  Das GEBIT-Material heißt hier nur "GEBIT-Descriptor-Set"; den
  vollqualifizierten Namen des Purchase-Service nennt der Plan nicht
  ("Purchase-Service-FQN").

## 0. Kurzfassung

- **Festlegung (Owner, 17.11.):** Ein AKS-Cluster (Kubernetes 1.36,
  Germany West Central, 1 x `Standard_D8ps_v6`, arm64, Free-Tier, kein
  HA) baut den Lab-Stack mit denselben Charts, Versionen, Namen und
  Image-Digests nach ("Parität zuerst"). SAM bleibt gebündelt
  (Postgres + SeaweedFS), Keycloak, Broker und Demo-DB laufen im
  Cluster. Bewusst anders als im Lab: Traefik statt ingress-nginx, ein
  Hostname mit Pfad-Routing, Keycloak unter `/auth`.
- **Öffentlich für alle, ohne WireGuard:** Ein Azure-Name `<fqdn>` auf
  der statischen IP `pip-aks-ingress` (nur 80/443), dazu die
  Egress-IP `pip-aks-egress`. SAM bekommt `/`, Keycloak `/auth/...`,
  Kasse und Monitor ihre Pfade (`/kasse`, `/monitor`, unverändert und
  ohne Login), die drei gRPC-Server ihre Service-Pfade (Reflection an,
  Route erst nach der GEBIT-Bestätigung aus AKS-E16). Weitere
  BFF-Seiten mit Schreib- oder LLM-Wirkung (`/freigabe`, `/foto`,
  `/op`) und `/etikett` bekommen erst nach Owner-Entscheidung einen
  öffentlichen Pfad (Frage 23). Den API-Server erreichen nur
  freigegebene IPs (`aks-allow-me.sh`); Grafana, Prometheus, SEMP,
  Keycloak-Admin und Traefik-Dashboard gibt es nur per Port-Forward.
  Missbrauchsschutz: Rate-Limits je Client-IP (`public-guard`, auch
  auf den gRPC-Service-Pfaden) und rpm/tpm-Limits am Messe-Key.
- **TLS ohne eigene Domain:** Let's Encrypt HTTP-01, ein Zertifikat für
  `<fqdn>`. Risiko: Alle `cloudapp.azure.com`-Namen teilen das
  LE-Limit von `azure.com`. Deshalb Staging zuerst, Produktion früh in
  P2, vorbereiteter Rückfall-Issuer einer ACME-CA mit EAB, gesichertes
  Secret, Erneuerung um den 15.01. (AKS-E4).
- **Ersetzt statt portiert:** Lab-CA, trust-manager, Kyverno,
  registry:2 und (nur auf AKS) ingress-nginx werden zu Let's Encrypt,
  ACR, eingebauter ValidatingAdmissionPolicy und Traefik v3.7.19 mit
  NGINX-Provider. Das Lab behält ingress-nginx; dieselben
  NGINX-Ingress-Manifeste laufen auf beiden Zielen.
- **Zuerst Sicherheitsgeländer:** Kein Skript pinnt heute einen
  kube-Kontext. Ein Lab-`stop.sh` gegen AKS würde dort SAM löschen und
  zugleich Lab-Keycloak-Client und Lab-Broker-Queues abräumen. Deshalb
  laufen alle AKS-Aufrufe nur über `kaks`/`haks` oder Skript-Wrapper
  mit `require_kube_context`, und ein Call-Log-Gate belegt, dass die
  Lab-Aufrufe gleich bleiben.
- **LiteLLM-Key geschützt:** SAM speichert ihn im Klartext in der
  Plattform-DB. Auf AKS gibt es deshalb ein eigenes
  SAM-Postgres-Passwort, NetworkPolicies, `grafana_ro` ohne die
  Key-Tabellen und Backups ohne deren Daten (AKS-E19, 1.4). Neu:
  rpm/tpm-Limits am Messe-Key gegen anonyme Dauerschleifen (AKS-E11).
- **Broker 10.26.0.9219 (LTS) in Lab und AKS:** Neuer Arbeitsposten
  Lab-Upgrade von 10.25.0.208, Risiko mittel bis hoch, weil beide
  Broker-DBs im Container-Layer liegen und `start.sh` sie neu erzeugen
  und leeren würde. Eigenes Owner-Go und Wartungsfenster; fertig und
  mit SAM- und GEBIT-Flows im Lab bewiesen vor P4 Teil B (AKS) und P5
  (AKS-E8). `start.sh`, `stop.sh` und `docker compose up/pull/down`
  sind in emd tabu, bis die emd-Skripte an die externen Volumes
  angepasst sind (1.4).
- **Phasen:** P0 Klärungen und Geländer (bis 27.11.), P1 Azure,
  Cluster, CLI, öffentlicher Zugang (KW49), P2 Add-ons mit Traefik und
  TLS (KW49-50), P3 Keycloak unter `/auth` (KW50), P4 Broker (Lab
  KW48-49, AKS KW51), P5 SAM (KW51, G2a 18.12.), P6 Demo mit
  Pfad-Ingresses, `public-guard` und Image 0.1.4 (G2b 15.01.), P7
  Härtung und Betrieb (G3 22.01., G4 05.02.). Summe 23,5 PT,
  bis G2a 13,5 PT (Aufteilung und Puffer in Abschnitt 4).
  Prüfpunkte am 04.12. und 11.12. entscheiden früh, ob der AKS-Teil von
  G2a nach G2b wandert.
- **Kosten:** rund 300-340 EUR/Monat bei 24/7 (1 Node, Free-Tier, 2
  Public IPs, kein WireGuard), rund 145-185 EUR/Monat im Aufbau mit
  Nacht- und Wochenend-Stopp; Projektsumme bis 20.02.2027 rund
  470-600 EUR ohne LLM-Token (mit Defender for Containers rund
  520-660 EUR), Ziel unter 1.500 EUR (3.4). Ein Monatsbudget-Alarm
  über alle drei Ressourcengruppen bleibt, neu skaliert auf 250 EUR
  statt 450 EUR [A] (AKS-E1).
- **Bewusst akzeptiert (2.2):** gpos teilt den Origin mit SAM; das
  AKS-Routing weicht vom Lab ab; SAM ruft sich über `<fqdn>` selbst
  auf (Hairpin-Test in P1); anonyme Schreib-RPCs; ein Node ohne HA.
- **Vor den Schreibschritten in P0:** `az login` neu (der Token
  scheiterte am 16.11. mit AADSTS9002313; Abhilfe laut CLI: `az
  logout`, dann `az login --tenant <tenant>`), Azure CLI 2.85.0 auf
  2.93 oder neuer heben (freigegeben, AKS-E15 (e)).
- **Noch offen:** AKS-E18 (G0-11a/b nach G2a) und AKS-E20 (Betreiber
  und Stellvertreter) warten auf den Owner, ebenso die Exposition von
  `/freigabe`, `/foto`, `/op` und `/etikett` (AKS-E5, Frage 23, vor
  G2b). Offen mit harter Vorbedingung: die schriftliche Bestätigung,
  dass die GEBIT-Freigabe das Descriptor-Set als Secret in Azure und
  die öffentliche Reflection abdeckt (AKS-E16; vor dem ersten
  GEBIT-Secret in Azure, spätestens 09.12.). [A]-Bestätigungen: der
  API-Server-Weg (AKS-E5), die Budgethöhe (AKS-E1), AKS-E9 und
  AKS-E12. Zu belegen bzw. zu beantworten: der 1-Node-Systempool beim
  Create in P1 (AKS-E3), Betreiber-Antwort und Key-Limits bis 27.11.
  (AKS-E11). Dazu Go und Fenster für das Lab-Broker-Upgrade (AKS-E8),
  das Label-Präfix `<p>` (AKS-E4), das Konto beim Rückfall-ACME-CA
  (Owner, bis 04.12.) und der Schutz des Approver-Logins (P3).

## 1. Ziel und Abgrenzung

### 1.1 Ziel

AKS wird ein zusätzliches Ziel, kein Ersatz. Das Lab bleibt
Entwicklungsumgebung: Entwicklung und Tests laufen im Lab, zum Ende
jedes Gates geht derselbe Stand mit `install.sh TARGET=aks` auf AKS
[Quelle: PLAN 0.2 (PLAN-E8)]. Das Lab-Verhalten bleibt unverändert:
gleiche Aufrufe bis auf den expliziten Lab-Kontext, belegt durch ein
Call-Log-Gate und ein Render-Diff-Gate (P0 Schritt 13). Einzige
gewollte Lab-Änderung ist das Broker-Upgrade auf 10.26.0.9219
(AKS-E8), mit eigenem Go und eigenem Nachweis.

"Parität zuerst" gilt für Charts, Versionen, Namen und Image-Digests.
Bewusst anders als im Lab, und nur in den AKS-Overlays: Traefik statt
ingress-nginx (AKS-E6), ein öffentlicher Hostname mit Pfad-Routing
statt eines Hosts je App (AKS-E4, 2.1), Keycloak unter `/auth`
(AKS-E10), ein Node ohne HA (AKS-E3).

### 1.2 Was nach AKS geht

| Baustein | Lab heute | AKS | Quelle |
|---|---|---|---|
| Ingress | ingress-nginx 4.15.1 (Controller 1.15.1), Port-Forward auf den Mac | Traefik v3.7.19 (Chart 42.4.1, per Digest) mit NGINX-Provider, 1 Replika, genau ein öffentlicher LoadBalancer-Service auf `pip-aks-ingress` (80/443, `externalTrafficPolicy: Local`); das Lab bleibt bei ingress-nginx | Befehl `helm list -A` (16.11.); sli ingress/scripts/setup.sh:47-49; `api.github.com/repos/traefik/traefik/releases` (17.11.) |
| Hostnamen | ein Host je App unter `solace.lab` (sam, auth, gpos, drei gRPC-Hosts, monitoring) | ein Azure-Name `<fqdn>` mit Pfad-Routing auf 443 (2.1); Grafana ohne Namen | Befehl `kubectl --context rancher-desktop get ingress -A` (17.11.); `learn.microsoft.com/azure/virtual-network/ip-services/public-ip-addresses` |
| TLS | private Root/Intermediate-CA, nur `solace.lab`, cert-manager v1.20.2 | Let's Encrypt HTTP-01 über cert-manager v1.21.3, ein Zertifikat für `<fqdn>` als Traefik-Default (`TLSStore`); Rückfall-Issuer einer ACME-CA mit EAB | sli pki/manifests/02-pki-ca-hierarchy.yaml:126-131; `letsencrypt.org/docs/rate-limits` |
| Monitoring | kube-prometheus-stack 83.5.0, Loki 6.55.0, Tempo 2.0.0, Alloy 1.11.0 | gleiche Versionen, Prometheus auf PVC statt emptyDir, Images aus ACR, Grafana ohne Ingress (Port-Forward) | Befehl `helm list -A` (16.11.); sli pki/manifests/05-monitoring-values.yaml:48-70 |
| Identity | Keycloak 26.2 (Floating-Tag) + Postgres 17, Realm `solace-lab`, eigener Host | Keycloak 26.8.2 gepinnt unter `/auth`, gleicher Realm, `*@solace.lab` unverändert | sli keycloak/manifests/03-keycloak.yaml:141; `api.github.com/repos/keycloak/keycloak/releases`; `www.keycloak.org/server/hostname` |
| SAM | 2.542.1, Chart 2.3.10, str 1.80.2, ns `sam-solace-lab`, gebündelt | identisch, zweites Values-Overlay; `sam.dnsName` = `<fqdn>`, SAM besitzt `/` | amd local-k8s-values.yaml:156-160; SAM-Chart 2.3.10 templates/_config_helpers.tpl:10-108 |
| Broker | `solace-1` 10.25.0.208 in Docker, VPN `sam` + `default`; Upgrade auf 10.26.0.9219 geplant (AKS-E8) | ein PubSub+ Standard 10.26.0.9219 (LTS) per Helm, ClusterIP, kein DMR | Befehl SEMP monitor (16.11.); emd docker-compose.yaml:27-57; Docker-Hub-Tags-API (17.11.) |
| GEBIT-Demo | ns `gpos-demo`, 6 Deployments, Image 0.1.3 arm64 | gleiches Image in ACR, in P6 Image 0.1.4 (gebündelter Reflection-Endpunkt); kustomize-Overlay `aks` mit Pfad-Ingresses | Befehl `kubectl -n gpos-demo get deploy` (16.11.) |
| Demo-DB | Host-Docker `postgres` 18.3, DB `gpos` 25 MB | Postgres-18-StatefulSet im eigenen Namespace `gpos-data`, neu aus dem Seed | Befehl `docker exec postgres psql` (read-only, 16.11.) |
| SAM-Paket | `gpos-uc1`: 5 Connectoren, 3 Agents, 3 Workflows, RBAC, 2 Entrypoints | inhaltlich unverändert; Haupt-Manifeste unverändert angewendet, nur die Entrypoints je Ziel gerendert | gpd mesh/manifest.yaml:11-15 |
| Neu | - | ACR, Key Vault, 2 statische Public IPs (`pip-aks-ingress` mit DNS-Label, `pip-aks-egress`), 3 Ressourcengruppen | - |

### 1.3 Was im Lab bleibt

| Teil | Grund | Quelle |
|---|---|---|
| db-designer und die db-jpa-Queues | anderer Showcase | Befehl `kubectl top pods -A` (16.11.) |
| `mi-solace-lab` (PVC 10Gi) | einzige Kopie der Demo-Daten, nicht Teil des Showcase | Memory "Lab cleanup safety" |
| `sam-solace-lab-agents` (v1-Lab-Agents) | Lab-Agents aus solace-sam-artifacts, kein Teil von UC1 | Befehl `kubectl top pods -A` (16.11.) |
| searxng (`sam-solace-lab-shared`) | nur für Lab-Agents | dito |
| Registry `oci` (50Gi) | ersetzt durch ACR | sli registry/manifests |
| `solace-2`, DMR-Link | AKS braucht nur einen Broker; beim Lab-Upgrade wird `solace-2` zuerst umgestellt (Probelauf) | Befehl `docker inspect` (Exited seit 03.11., 17.11.) |
| EMA/Event Portal (VPN `amartens-test`), OTel-Collector, Broker-Tracing | Lab-Event-Mesh-Story, nicht GEBIT; Jaeger gibt es nicht mehr | emd docker-compose.yaml:7-105 |
| ingress-nginx, Kyverno, trust-manager, Lab-CA, pgadmin | im Lab weiter nötig; auf AKS ersetzt durch Traefik, VAP und Let's Encrypt | sli pki/manifests/04-kyverno-policies.yaml; Befehl `helm list -A` (16.11.) |
| getrennte Lab-Hosts (`sam`, `auth`, `gpos`, gRPC-Hosts) | Lab-Routing bleibt; die Pfad-Ingresses gibt es nur im AKS-Overlay | Befehl `kubectl --context rancher-desktop get ingress -A` (17.11.) |
| andere Demos (retail, manufacturing, insurance, bsg) | nicht im Scope | - |

### 1.4 Leitplanken, die der Plan einhält

- Der LiteLLM-Key lebt nur in SAMs eigener Konfiguration:
  `amd/.env.aks` → `helm --set` (vom Chart erzeugtes SAM-Core-Secret)
  und `apply-models.sh` in die Modellkonfiguration. Nie in gpd-`.env`,
  Demo-Secrets, Workflows, `tool_config` oder Key Vault
  [Quelle: Chart templates/secret-core.yaml:37-39 laut SAM-Leser].
  `rpm_limit` und `tpm_limit` am Messe-Key setzt der LiteLLM-Betreiber
  (AKS-E11); der Key-Wert selbst verlässt SAM nicht.
- Der LiteLLM-Key kommt nie in Backups, Snapshots, Grafana oder
  Scratch-DBs. SAM speichert ihn im Klartext in
  `model_configurations.model_auth_config` und in jedem
  `gateway_deployments`-Snapshot [Quelle: amd
  scripts/models/README.md:77-79; gpd spikes/g0/results/README.md:93-97;
  gpd UC1-BUILD-SPEC.md:3436-3440]. Die SAM-Plattform-DB wird nur ohne
  die Daten dieser beiden Tabellen gesichert, `grafana_ro` darf sie
  nicht lesen, NetworkPolicies schirmen die SAM-Postgres ab (AKS-E19).
- Nie `sam config apply --prune` [Quelle: gpd scripts/lib.sh:39-43].
- GEBIT-Material nie in Git, Images, ACR, Key Vault oder Backups
  [Quelle: gpd .dockerignore:1-17; scripts/check_hygiene.sh:24-30].
- Öffentlich ist genau ein Service: der Traefik-LoadBalancer mit den
  Ports 80 und 443. Jeder andere Service ist ClusterIP, eine VAP
  erzwingt das. Grafana, Prometheus, Broker-SEMP,
  Keycloak-Admin-Konsole und Traefik-Dashboard bekommen keine Route
  und sind nur per Port-Forward erreichbar.
- Kasse (`/kasse` mit der Kundenanzeige `/kunde` [Quelle: PLAN 0.1])
  und Monitor bleiben unverändert und ohne Login; Schutz gibt es nur
  über `public-guard` am Ingress und die Limits am Messe-Key. Andere
  BFF-Seiten (`/freigabe`, `/foto`, `/op`, `/etikett`) und ihre
  API-Routen bekommen erst nach Owner-Entscheidung einen öffentlichen
  Pfad (Frage 23).
- Das Traefik-Access-Log schreibt Client-IPs, aber weder Header noch
  Query-Parameter (die SAM-WebUI schickt ihr Access-Token als
  Query-Parameter); Loki hält es 7 Tage [A], der Export nach der Messe
  nimmt es nicht mit (P2 Schritt 5, P7 Schritt 8).
- Neue Zertifikate für `<fqdn>` nur über LE-Staging oder als bewusste
  Produktions-Bestellung. Drills und Neuaufbau spielen das gesicherte
  Secret ein, statt neu auszustellen (AKS-E4).
- Lab-Broker: Bis die emd-Skripte an die externen Volumes angepasst
  sind (eigene Freigabe, P4 Schritt A4), laufen in emd weder `start.sh`
  noch `stop.sh` noch `docker compose up`, `pull` oder `down` noch ein
  Prune. Heute liegen beide Broker-DBs im Container-Layer, und
  `start.sh` würde `solace-1` und `solace-2` neu erzeugen und leeren
  [Quelle: Befehl `docker inspect`, `docker compose config --hash`
  (17.11.); emd start.sh:4,6; emd stop.sh:2; A: per `docker compose up
  --dry-run` bestätigen]. Nach der Storage-Auslagerung (AKS-E8) bleibt
  die Regel: `stop.sh` löscht Terraform-State, Lock-Datei, tfvars und
  `.env`, die Broker-DBs überleben auf den Volumes, und das nächste
  `start.sh` scheitert mit leerem State an den vorhandenen Objekten,
  bevor die DMR-Links aktiviert sind [Quelle: emd stop.sh:2-7;
  start.sh:2, 20-21]. Sicher sind nur `docker start`/`docker stop` bzw.
  `docker compose stop`/`start` der bestehenden Container.
- Jeder kubectl- und helm-Aufruf gegen AKS läuft über `kaks`/`haks`
  oder einen Skript-Wrapper mit `require_kube_context`; die
  AKS-kubeconfig liegt nie in `~/.kube/config`.
- Änderungen an geteilter Lab-Infra nur im Rahmen der Freigaben
  AKS-E15 (a) bis (e); das Broker-Upgrade im Lab braucht zusätzlich
  ein eigenes Go und ein Wartungsfenster.
- Browser-Logins, Passwörter und das Konto bei der Rückfall-ACME-CA
  macht der Owner (der Stellvertreter nur für sein eigenes Konto),
  nicht Claude.
- Das Lab funktioniert nach jedem Schritt unverändert
  (Regressions-Gate); die einzige gewollte Ausnahme ist das
  Broker-Upgrade mit eigenem Nachweis.

## 2. Entscheidungen des Owners

Nummern mit Präfix `AKS-`; PLAN-Entscheidungen heißen hier PLAN-E1 bis
PLAN-E8. Die Owner-Entscheidungen vom 17.11.2026 sind bindend; die
Empfehlungen vom 16.11. stehen im sda-Commit 7a860c5.

Status:

- **entschieden 17.11.:** Owner-Entscheidung vom 17.11.2026.
- **[A] Bestätigung offen:** Annahme oder Default der Planung; gilt,
  bis der Owner abweicht.
- **Owner-Bestätigung offen:** vom Owner noch nicht beantwortet; die
  Empfehlung ist bis zur Frist die Arbeitsgrundlage.
- **offen:** noch zu klären oder freizugeben.

| Nr | Entscheidung | Status | Festlegung bzw. Empfehlung | Alternativen | Bis wann |
|---|---|---|---|---|---|
| AKS-E1 | Subscription, Kostenstelle, Quota, Budget (Plan-Punkt O4 [Quelle: PLAN 0.5]) | entschieden 17.11.; Budgethöhe [A] Bestätigung offen | Bestehende Subscription, die der Owner mit `az login` nutzt; P0 prüft Rechte, Policies und Defender-Pläne. Quota-Bedarf (3.5), Antrag am 20.11., falls P0 eine Lücke zeigt: DPSv6 16 vCPU (1 Node plus Surge-Node beim Node-Image-Update), DPSv5 16 vCPU nur, falls `az vm list-skus` für `Standard_D8ps_v6` eine Restriction zeigt (P0 Schritt 4), Total Regional mindestens 16; 2 Standard-Public-IPs (Default-Quota 10 oder 20 [Quelle: `learn.microsoft.com/azure/azure-resource-manager/management/azure-subscription-service-limits`]). Monatsbudget-Alarm wie bisher auf `rg-eurocis-base`, `rg-eurocis-aks` und `rg-eurocis-nodes` (Actual 100 %, Forecast 100 %, 01.12.2026-31.03.2027), neu skaliert: 250 EUR statt 450 EUR, zwischen Stopp-Betrieb und 24/7, damit ein vergessener Nachtstopp den Forecast auslöst [A: Kosten 3.4]. Projektziel unter 1.500 EUR, verfolgt per Cost-Analysis-Ansicht | eigene Subscription; ohne Rechte auf Subscription-Ebene je RG ein Budget; Quota-Antrag meist in Minuten (Auto-Freigabe), sonst Support-Fall mit Tagen [Quelle: `learn.microsoft.com/azure/quotas/per-vm-quota-requests`] | Quota-Antrag 20.11.; Budget in P1 |
| AKS-E2 | Region | entschieden 17.11. | Germany West Central; folgt aus dem Namen `<fqdn>` (AKS-E4) | West Europe (gleiche v6-Preise [Quelle: Retail-API 16.11.]), dann ein anderer Name | erledigt |
| AKS-E3 | Architektur, Größe, Verfügbarkeit | entschieden 17.11.; Zulässigkeit 1-Node-Systempool [A], Beweis beim Create in P1 | arm64, 1 x `Standard_D8ps_v6` (8 vCPU / 32 GiB) im Pool `main` (System-Modus), kein HA: gleiche Digests wie im Lab, kein Multi-Arch-Build. Die Requests passen auf einen Node (mit Broker `prod1k` rund 91 % CPU und 70 % RAM der Allocatable, 3.2); Abnahme in P1: mindestens 7,8 CPU und 28,5 GiB allocatable. Microsoft Learn verlangt für produktive System-Pools mindestens 2 Nodes (3 empfohlen) [Quelle: `learn.microsoft.com/azure/aks/use-system-pools`], der AKS-Quickstart legt mit `--node-count 1` an [Quelle: `learn.microsoft.com/azure/aks/learn/quick-kubernetes-deploy-cli`]; der Create in P1 ist der Beweis [A]. Kein N-1-Drill mehr. Folge: Node-Image-Update oder Node-Ausfall heißt einige Minuten Ausfall der ganzen Demo; Rückfall L3 (Lab) | 2 Nodes mit HA (vom Owner verworfen, rund +239 EUR/Monat bei 24/7 mit OS-Disk); amd64 1 x `D8as_v6` (rund +68 EUR/Monat bei 24/7, +1-1,5 PT, keine Quota mehr beantragt); `D8ps_v5` bei Dpsv6-Engpass | Beweis beim Create (P1, KW49) |
| AKS-E4 | Domain, DNS, TLS | entschieden 17.11.; Präfix `<p>` offen | Ein Azure-Name `<fqdn>` = `<p>.germanywestcentral.cloudapp.azure.com`: DNS-Label auf der statischen Standard-IP `pip-aks-ingress` in `rg-eurocis-base` mit Lock `CanNotDelete` (eine gelöschte IP gibt das Label für jeden frei). Der Traefik-Service nutzt `service.beta.kubernetes.io/azure-pip-name` (plus `azure-load-balancer-resource-group`), nie `azure-dns-label-name`; die Control-Plane-Identität `id-aks-cp` bekommt Network Contributor auf `rg-eurocis-base` [Quelle: `learn.microsoft.com/azure/aks/static-ip`]. Mit `pip-aks-egress` sind es 2 Public IPs; LB-Regeln nur für 80 und 443 (mit der Outbound-Regel 3 Regeln, innerhalb der 5 im LB-Grundpreis [Quelle: Retail-API 17.11.]). Keine eigene Domain, keine Azure-DNS-Zone, kein DNS-01. Pfad-Routing auf 443 nach 2.1. TLS: ACME HTTP-01 über cert-manager, ein Zertifikat für `<fqdn>` als Traefik-Default (`TLSStore`); ob der SAM-Ingress `secretName` weglässt oder `sam-tls` vor `helm install` im SAM-Namespace liegt, entscheidet ein Test in P2 [Quelle: SAM-Chart 2.3.10 templates/_validations.tpl:110-113]. LE-Risiko: `cloudapp.azure.com` steht nicht auf der Public Suffix List, alle Azure-Kunden teilen den Bucket `azure.com` (50 neue Zertifikate je Woche); die Ausstellung kann tagelang scheitern [Quelle: `publicsuffix.org/list/public_suffix_list.dat` (17.11.); `letsencrypt.org/docs/rate-limits`; `community.letsencrypt.org/t/217855`]. Gegenmittel: erst LE-Staging, dann früh Produktion (P2); vorbereiteter Rückfall-ClusterIssuer einer ACME-CA mit EAB (ZeroSSL oder Google Trust Services; das Konto legt der Owner an, EAB-Daten nur in Key Vault und `.env.aks`); ausgestelltes Secret sichern; `cmctl renew` um den 15.01., damit die automatische Erneuerung nicht in den Freeze fällt [A: 90 Tage Laufzeit, Erneuerung nach zwei Dritteln]. `<p>` ist neutral, ohne Kunden- oder Projektnamen (CT-Logs sind öffentlich), Verfügbarkeit per `CheckDnsNameAvailability` prüfen [A] | eigene Domain mit DNS-01 (bisherige Empfehlung, vom Owner verworfen); weitere Varianten in 8.5 | Präfix und `pip-aks-ingress` ab 20.11. (P0); LE-Produktion früh in P2; Rückfall-Konto und EAB-Daten bis 04.12. (Prüfpunkt) |
| AKS-E5 | Zugriffsmodell, Missbrauchsschutz | entschieden 17.11.; API-Server-Weg [A] Bestätigung offen; Exposition von `/freigabe`, `/foto`, `/op`, `/etikett`: Owner-Bestätigung offen | Öffentlich für alle, ohne WireGuard und ohne internes LB (was entfällt, steht in 8.5). Kasse (mit `/kunde`) und Monitor bleiben unverändert und ohne Login. Nicht vom Owner entschieden ist die Exposition der übrigen BFF-Seiten samt API-Routen: `/freigabe` beantwortet pausierte SAM-HITL-Läufe über die BFF (jeder könnte Preise freigeben oder ablehnen), `/foto` startet mit jedem Upload den Vision-Agenten, `/op` schaltet auf L4 [Quelle: PLAN 1.4 (Fläche A), PLAN 9 R24]. Bis zur Antwort (Frage 23) bekommen sie keinen Pfad auf `<fqdn>`. Öffentlich ist nur der Traefik-LoadBalancer-Service (VAP), mit `externalTrafficPolicy: Local` für echte Client-IPs. Nicht öffentlich: Grafana, Prometheus, Broker-SEMP, Keycloak-Admin-Konsole, Traefik-Dashboard (Port-Forward). Missbrauchsschutz: Komponente `public-guard` mit Traefik-Rate-Limits je Client-IP auf `/api/pos/`, `/api/demo/reset`, `/api/events` und den drei gRPC-Service-Pfaden (429 statt 503), dazu rpm/tpm-Limits am Messe-Key (AKS-E11); alle Standgeräte hinter einer NAT-IP teilen sich die Limits [A: Werte in P6 messen]. API-Server: authorized IP ranges; der Helfer `sli/aks/aks-allow-me.sh` ermittelt die aktuelle IP, mergt sie in die bestehende Liste und schreibt die volle Liste, weil `az aks update --api-server-authorized-ip-ranges` die Liste ersetzt (bis 2 min Laufzeit, höchstens 200 Bereiche) [Quelle: `learn.microsoft.com/azure/aks/api-server-authorized-ip-ranges`]; Break-glass `az aks command invoke` aus jedem Netz [Quelle: `learn.microsoft.com/azure/aks/access-private-cluster`]; `aks-allow-me.sh` gilt als Freeze-Ausnahme, weil es nur ergänzt [A] | API-Server nur mit Entra ID und Conditional Access, ohne IP-Bereiche (aus jedem Netz, Endpunkt aber scannbar); privat mit WireGuard (bisherige Empfehlung, vom Owner verworfen); für die offenen Seiten: öffentlich, nur Port-Forward bzw. Lab, oder ein Schutz vor G2b | Abweichung vom API-Server-Weg bis 27.11.; Seiten-Exposition vor G2b [Quelle: PLAN 9 R24] |
| AKS-E6 | Ingress-Controller | entschieden 17.11. | Traefik v3 mit ingress-nginx-Provider statt ingress-nginx: Chart 42.4.1, Image `traefik:v3.7.19` per Digest (nie unter v3.7.18, das fünf GHSAs behob; kein v3.8.0-rc) [Quelle: `api.github.com/repos/traefik/traefik/releases` und `.../security-advisories` (17.11.)], cert-manager v1.21.3; ein Deployment mit 1 Replika hinter genau einem LoadBalancer-Service (`pip-aks-ingress`, 80/443). Geschlossene Lücken: `ports.websecure.transport.respondingTimeouts.readTimeout: 3600s` (sonst schneidet Traefik HTTP/1.1-SSE und MCP nach 60 s ab); `azure-load-balancer-tcp-idle-timeout: "30"`; eigene IngressClass `nginx` (Controller `k8s.io/ingress-nginx`), weil das SAM-Chart die Klasse beim Install prüft und das Traefik-Chart sie nicht anlegt; Provider `kubernetesIngress` aus, `kubernetesCRD` an (Middleware, TLSStore); `proxy-request-buffering: "on"` für SAM und gpos-ui, sonst wirkt `proxy-body-size` nicht; HSTS per Headers-Middleware ohne `includeSubDomains`; kein Redirect auf EntryPoint-Ebene, damit HTTP-01 durchkommt (`ssl-redirect` je Ingress liefert 308); nie Buffering auf der SSE-Route `/api/events` [Quelle: Traefik v3.7.19 docs ingress-nginx.md:265-502, entrypoints.md:128-130; pkg/provider/kubernetes/ingress-nginx/middleware.go:176-213; SAM-Chart 2.3.10 templates/_validations.tpl:185-189]. Das Lab behält ingress-nginx (dieselben NGINX-Ingress-Manifeste laufen auf beiden); Traefik-eigene Werte beweist erst P2. Traefik-Patch-Releases im Freeze nur als Ausnahme mit Smoke-Test [A] | ingress-nginx 4.15.1 (bisherige Empfehlung; archiviert, CVE-2026-116472 ohne Fix); App-Routing Gateway API; Application Gateway for Containers (ab rund 125 EUR/Monat) | erledigt; Nachweis in P2 |
| AKS-E7 | SAM-Persistenz | entschieden 17.11. | gebündelt (Postgres + SeaweedFS 2 CPU/2Gi, seit sda-Commit cd08a17 in amd `local-k8s-values.yaml`) auf `managed-csi-premium`, Superuser-Passwort aus Key Vault (`sam-pg-admin`), Schutz nach AKS-E19; Keycloak- und Demo-DB ebenfalls im Cluster | extern: PG Flexible + Blob (+1,5-2 PT, rund +108 EUR/Monat, nie im Lab gelaufen); der PLAN nennt gebündelt selbst als Rückfall [Quelle: PLAN 6.2, Nr. 11] | erledigt |
| AKS-E8 | Broker | entschieden 17.11.; Lab-Upgrade: Go offen | PubSub+ Standard 10.26.0.9219 (LTS, Tags `latest`/`lts`, Index-Digest beginnt mit `sha256:c0020e53ed48`) für Lab und AKS, per Digest gepinnt; nicht 10.26.10 (Rolling Release ohne Wartungsreleases, Support nur bis zum nächsten LTS, kein Weg zurück auf 10.26.0.x) [Quelle: Docker-Hub-Tags-API (17.11.); `solace.com/support/support-dates-for-release-versions`; docs.solace.com Upgrade-Selector]. AKS: `pubsubplus` 3.10.0 mit `service.type: ClusterIP` und `storage.useStorageGroup: true` explizit, P10 128Gi, VPN-Layout wie im Lab, eigene User `sam` und `gpos`. Größe `prod1k` (Requests und Limits 2 vCPU / 6,4 GiB, Guaranteed, 1000 Verbindungen; mehr RAM, als der Lab-Broker heute belegt, 4,19 GiB); zwingt das Sizing dazu (Kriterium in 3.2: die nach P2 gemessenen CPU-Requests von System, Traefik, cert-manager, Monitoring und Defender liegen über 2044m, dann reißt `prod1k` die 92-%-Grenze), dann `dev` (Request 1 vCPU / 3,3 GiB, 100 Verbindungen): reicht für die rund 11 Verbindungen der Demo, liegt beim RAM aber unter dem Lab-Verbrauch (OOM-Risiko) [A]. Der Lab-Broker läuft mit dem Default von 100 Verbindungen [A: per SEMP `show system` bzw. SEMPv2-GET prüfen]. Neuer Arbeitsposten Lab-Upgrade 10.25.0.208 auf 10.26.0.9219: Beide Broker-DBs liegen im Container-Layer (1.4). Schritte: SEMPv2-Baseline, `docker commit` als Rückfall, Storage auf ein externes Volume, Tag plus Digest in emd `.env.example`, Terraform-Provider fest pinnen, `docker compose up -d --no-deps` je Broker, `solace-2` zuerst, danach `terraform plan` ohne Änderungen. Risiko mittel bis hoch: Volume-Kopie der SolOS-DB ungeprobt; 36 Queues, Client-Usernames und ein ACL-Profil liegen außerhalb von Terraform. Eigenes Owner-Go und Wartungsfenster; fertig und mit SAM- und GEBIT-Flows im Lab bewiesen vor P4 Teil B (AKS) und P5 | 10.26.10.14510 (Rolling, Support nur bis Juni 2027); 10.25.0.208 auf AKS (dann zwei Versionen); Solace Cloud (ein VPN je Service, TLS-only, Änderung an `bus.py` nach UC1-Freeze) | Go vor der Probe an `solace-2` (KW48) [A]; `solace-1` bis zum Prüfpunkt 04.12., spätestens 10.12. |
| AKS-E9 | Monitoring | [A] Bestätigung offen (Zugriff entschieden 17.11.) | OSS im Cluster, Lab-Versionen, Images aus ACR, Tempo bleibt (im Owner-Scope); Grafana und Prometheus ohne Ingress, Zugriff per Port-Forward | Azure Managed Prometheus + Grafana (+125-215 EUR/Monat, Dashboards und ServiceMonitors portieren) | 04.12. |
| AKS-E10 | Keycloak | entschieden 17.11. | bleibt im Cluster, Realm `solace-lab`, 26.8.2 gepinnt, generierte Passwörter. Unter `/auth`: `KC_HTTP_RELATIVE_PATH=/auth`, `KC_HOSTNAME=https://<fqdn>/auth`, `KC_HTTP_MANAGEMENT_RELATIVE_PATH=/` (Probes bleiben `/health/*` auf Port 9000); beide Pfade sind Build-Optionen, der Start ohne `--optimized` übernimmt sie [Quelle: `www.keycloak.org/server/hostname`; sli keycloak/manifests/03-keycloak.yaml:141-144]. Issuer `https://<fqdn>/auth/realms/solace-lab`; Ingress nur für `/auth/realms/solace-lab/` und `/auth/resources/`; Admin-Konsole per Port-Forward (ob `KC_HOSTNAME_ADMIN` nötig ist, klärt P3); die Keycloak-Admin-Skripte nehmen `KEYCLOAK_URL` als Präfix (`.../auth`). SAM-Client: `redirectUris` exakt `https://<fqdn>/api/v1/auth/callback` statt Wildcard, die auf dem geteilten Host auch gpos- und Keycloak-Pfade deckte [Quelle: amd scripts/setup-keycloak-client.sh:17, 124-125] | 26.2-Lab-Digest (Release-Linie ohne Upstream-Support); Entra ID als IdP (nicht empfohlen: RBAC-Manifeste, Claim-Mapping); eigener Host (verworfen mit AKS-E4) | `KC_HOSTNAME_ADMIN` in P3 |
| AKS-E11 | LiteLLM | entschieden 17.11.; Betreiber-Antwort offen | statische Egress-IP `pip-aks-egress` aus P0, an den Betreiber bis 25.11.; Messe-Key (O5, 150 USD, Alarme bei 50 und 80 % [Quelle: PLAN 0.5]) nur in die SAM-Konfiguration. Neu: Der Betreiber setzt `rpm_limit` und `tpm_limit` (dazu `max_budget`) am Messe-Key [Quelle: `docs.litellm.ai/docs/proxy/users`]; Grund: Kasse und Reset sind anonym, ein Skript mit einem Review alle 5 s kostet rund 7-36 USD/h und leert den Key in 4-21 h, danach steht die Demo [A; Quelle: PLAN 0.5 (O5), PLAN 8.6] | kein separater Messe-Key (dann Lab-Key auf AKS) | Anfrage 20.11., IP an den Betreiber bis 25.11., Bestätigung und Limits 27.11., Test in P1 (03.12.) |
| AKS-E12 | Kyverno, trust-manager, Lab-Registry auf AKS | [A] Bestätigung offen | nicht installieren; ValidatingAdmissionPolicy + PriorityClasses. VAP neu: `type: LoadBalancer` nur für den Service `traefik/traefik` mit `azure-pip-name: pip-aks-ingress` und `azure-load-balancer-resource-group: rg-eurocis-base` (fängt auch den öffentlichen LB-Default des `pubsubplus`-Charts und einen zweiten LB-Service im Namespace `traefik`); TLS- und Redirect-Regeln nehmen HTTP-01-Solver-Ingresses (Label `acme.cert-manager.io/http01-solver`) aus | Kyverno 3.7.1 gepinnt mit umgeschriebenen Policies (+0,5 PT; Chart 3.9.2+ blockiert `az aks stop`) | 27.11. |
| AKS-E13 | Cluster-Zugriff, Mac-Tools | entschieden 17.11. | Entra ID + Azure RBAC, lokale Accounts aus, eigene kubeconfig `~/.kube/aks-eurocis.yaml` nur über `kaks`/`haks`; Mac-Tools freigegeben (AKS-E15 (e)): Azure CLI als Cask (2.93 oder neuer), Microsoft-kubelogin aus dem Tap `Azure/kubelogin` | lokaler Admin-kubeconfig (statisches Admin-Zertifikat 3 Monate auf der Platte) | erledigt; Installation in P0 |
| AKS-E14 | Version, Tier, Wartung, Laufzeiten | entschieden 17.11. | 1.36.x gepinnt, Auto-Upgrade aus, Node-OS-Kanal SecurityPatch Mi 08-12 Uhr; manueller Node-Image-Refresh Di 26.01.2027; `notAllowedDates` 20.01.2027 und 27.01.-20.02.2027 auf allen drei Wartungskonfigurationen. Free-Tier für das ganze Projekt, kein Wechsel auf Standard (kein Uptime-SLA). Mit einem Node heißt jedes Node-Image-Update einige Minuten Ausfall; die Sperre um die Messe bleibt deshalb. Nachts stoppen bis G4 (Start frühestens 30 min nach Stop), ab 05.02. 24/7 | Standard-Tier ab G2b (bisherige Empfehlung, rund 66 EUR/Monat); 1.35 (EOL März 2027); Node-OS `None` mit einem manuellen Refresh | erledigt; Konfiguration in P1 |
| AKS-E15 | Freigaben geteilte Infra und Mac-Tools | entschieden 17.11. (alle erteilt) | (a) amd-Working-Tree committet (sda-Commit cd08a17, erledigt); (b) Profil + Kontext-Guard in amd-Skripten inkl. Keycloak-Teardown-Skripten; (c) neue Ordner `sli/aks/`, `emd/aks/`, `emd/terraform-aks/`, `amd/manifests/aks/`; (d) Broker-Pin 10.26.0.9219 per Tag und Digest in emd `.env.example`, wirksam erst mit dem Lab-Upgrade, das ein eigenes Go braucht (AKS-E8); (e) Mac-Tools Azure CLI 2.93 oder neuer und Microsoft-kubelogin | alles in gpd (Lab-Skripte ohne Guard) | erledigt |
| AKS-E16 | GEBIT, gRPC | entschieden 17.11.; Descriptor-Set in Azure und öffentliche Reflection: offen (Planungsannahme ja [A], gehandelt wird erst nach schriftlicher Bestätigung) | Laut Owner liegt die schriftliche GEBIT-Freigabe seit 17.11.2026 vor; gpd ist im öffentlichen sda-Repo committet (sda-Commit 7a860c5). Alle drei gRPC-Endpunkte sind öffentlich für alle, Reflection an; der Owner akzeptiert, dass jeder die anonymen Schreib-RPCs aufrufen kann (z. B. Preisänderung in der WWS, Coupons im Loyalty-Dienst, Reset); `public-guard` bremst sie je Client-IP (P6 Schritt 8). Routing über den Service-Pfad auf `<fqdn>:443` (2.1). Neuer Arbeitsposten in P6: Image 0.1.4 mit einem gebündelten Reflection-Endpunkt, der für alle drei Dienste aus beiden Descriptor-Pools antwortet (GEBIT aus dem Secret-Mount, Showcase aus dem Image) [A: rund 0,5 PT]; bis dahin nutzen grpcurl und Postman für zwei der drei Server das lokale Descriptor-Set (`-protoset`); gRPC-Health nur im Cluster. Planungsannahme: Die Freigabe deckt auch das GEBIT-Descriptor-Set als K8s-Secret in Azure GWC, Zugriff von Owner und Stellvertretung (AKS-E20), Löschung bis 20.02. und die öffentliche Reflection. Diese gibt nicht nur die Dienstliste heraus, sondern die GEBIT-Descriptor-Dateien selbst (Purchase-API samt Abhängigkeiten) [A: Owner bestätigt]. Harte Vorbedingung: Ohne schriftliche Bestätigung kommt kein GEBIT-Material nach Azure (auch nicht für `gebitsim` in P2 Schritt 7) und keine Reflection-Route auf `<fqdn>`; nie in Git, Images oder ACR | deckt die Freigabe das Secret nicht: Descriptor-Set nur im Lab, Messe aus dem Lab (L3), G0-11b (3) mit einem Testserver ohne GEBIT-Material; deckt sie nur die öffentliche Reflection nicht: Reflection-Pfade ungeroutet (bisherige Variante c), `-protoset` für alle drei Dienste | Bestätigung bis 27.11., spätestens 09.12. (vor dem ersten GEBIT-Secret in Azure, P2 Schritt 7; G0-11b (3) mit `gebitsim` am 11.12.); Image 0.1.4 in P6 |
| AKS-E17 | Secrets | entschieden 17.11. (mit AKS-E4) | Key Vault (RBAC-Modus, Soft-Delete 7 Tage, ohne Purge-Schutz) als Kopie außerhalb des Macs für generierte Secrets (hex, ohne Zeilenumbruch), TLS-Backups und die EAB-Daten des Rückfall-Issuers, ohne CSI-Treiber; LiteLLM-Key und GEBIT-Material nie im Key Vault | nur `.env.aks` + Passwortmanager des Owners | Anlage in P1 |
| AKS-E18 | Gate-Verschiebung G0-11a/G0-11b | Owner-Bestätigung offen | G0-11a nach G2a (18.12., P5), die LiteLLM-Probe in P1 ist nur Frühindikator; Prüfung (4) DSN-TLS entfällt mit AKS-E7; Prüfung (2) Vision auf Modellebene in P5, mit `gpos-price-scout` in P6; G0-11b gRPC (3) bleibt am 11.12. (P2 Schritt 7, über Traefik und `<fqdn>`), HITL (1) wandert nach P5 (18.12.); AP12 S1-S3 von KW48 nach KW49/50 | PLAN-Termine 03.12./11.12. halten (verlangt den Cluster schon in KW48, vor dem Ende von P0) | 27.11. |
| AKS-E19 | Schutz der SAM-Datenbank | entschieden 17.11. | eigenes Superuser-Passwort `sam-pg-admin` ab dem ersten Install; NetworkPolicies nur für SAM-Postgres und SeaweedFS (abweichend von RA R15 [Quelle: RA:599]); `grafana_ro` nur mit expliziter Tabellenliste | Chart-Default `password` ohne NetworkPolicy (RA R15): dann kann jeder Pod im Cluster, auch die öffentliche BFF ohne Login, den LiteLLM-Key lesen | vor dem ersten SAM-Install (P5) |
| AKS-E20 | Betrieb an Probetagen und Messe | Owner-Bestätigung offen | Betreiber und Stellvertreter namentlich; Vorschlag nach PLAN 6.4/7.3: Person C Betreiber, Entwickler A Stellvertreter (bei O9 = (b): A Betreiber, Owner Stellvertreter) [A]; eigene Konten, Rollen, Allowlist-Eintrag und Keycloak-User. Die Stellvertreter-Rolle (P7 Schritt 7) bekommt `managedClusters/write` für `aks-allow-me.sh`, ohne `delete` und `stop` [A]; Test mit seinem Konto direkt nach der Zuweisung, vor G3; scheitert er an verknüpften Ressourcen, kommen Join- und Assign-Rechte dazu [A]; Break-glass `az aks command invoke` | nur der Owner (Risiko in Abschnitt 7) | Name 20.11., Rollen bis G3 |

### 2.1 Pfade auf `<fqdn>` (AKS-E4)

Alle Routen hängen am selben Host auf Port 443; Port 80 dient nur ACME
HTTP-01 und dem 308-Redirect je Ingress. Traefik gibt der längsten
Regel Vorrang [Quelle: Traefik-Doku v3.7, routing/rules-and-priority],
deshalb schlagen die gpos-, Keycloak- und gRPC-Pfade SAMs `/`.

| Pfad (Präfix) | Ziel | Hinweis |
|---|---|---|
| `/` | SAM (gwe, Port `webui`) | Chart rendert nur `/` und kennt keinen Basispfad; WebUI, `/api/v1`, `/api/v2`, `/.well-known/*`, `/gw/*`, `/health`; OIDC-Callback `https://<fqdn>/api/v1/auth/callback` |
| `/auth/realms/solace-lab/`, `/auth/resources/` | Keycloak | Issuer `https://<fqdn>/auth/realms/solace-lab`; Admin-Konsole und Realm `master` ohne Route |
| `/kasse`, `/monitor`, `/static/` | gpos-ui | Kasse `https://<fqdn>/kasse`, Monitor `https://<fqdn>/monitor`; der gpos-Redirect von `/` auf `/monitor` ist nicht erreichbar |
| `/kunde` | gpos-ui | Kundenanzeige der Kasse [Quelle: PLAN 0.1], öffentlich wie `/kasse`, sobald AP11 die Seite baut |
| `/api/catalog`, `/api/cards`, `/api/scenarios`, `/api/state`, `/api/proposals/` | gpos-ui (REST, nur lesend) | disjunkt zu SAMs `/api/v1` und `/api/v2` |
| `/api/pos/`, `/api/demo/` | gpos-ui (REST, schreibend) | Rate-Limits je Client-IP (`public-guard`) auf `/api/pos/` und `/api/demo/reset` |
| `/api/events` | gpos-ui (SSE) | eigenes Ingress-Objekt ohne Buffering, Lesetimeout 3600 s, Verbindungslimit je Client-IP |
| `/freigabe`, `/foto`, `/op`, `/etikett` samt API-Routen | keine Route bis zur Owner-Entscheidung (Frage 23) | `/freigabe` beantwortet SAM-HITL über die BFF, `/foto` startet den Vision-Agenten; ungeroutet fallen sie auf SAMs `/` |
| Purchase-Service-FQN, `/de.showcase.wws.v1.service.MerchandiseService/`, `/de.showcase.loyalty.v1.service.LoyaltyService/` | je ein gRPC-Server, `backend-protocol: GRPC` | öffentlich, Schreib-RPCs anonym, `limit-rpm` je Client-IP (AKS-E16) |
| `/grpc.reflection.v1.ServerReflection/`, `/grpc.reflection.v1alpha.ServerReflection/` | ab Image 0.1.4 der gebündelte Reflection-Endpunkt, eigenes Ingress-Objekt | Route erst nach der Bestätigung aus AKS-E16; bis 0.1.4 ein Server [A: POS], für die anderen zwei `-protoset` mit dem lokalen Descriptor-Set |
| `/grpc.health.v1.Health/` | keine eigene Route | gRPC-Health nur im Cluster; die Anfrage fiele auf SAMs `/` und scheiterte |
| keine | Grafana, Prometheus, Broker-SEMP, Keycloak-Admin, Traefik-Dashboard | nur Port-Forward |

`/health` bleibt bei SAM; die gpos-Probes rufen `/health` nur im
Cluster. [Quelle: gpd app/gposdemo/ui/bff.py:326-412;
app/gposdemo/common/descriptors.py:18-22;
app/gposdemo/common/grpcutil.py:150-167; SAM-Chart 2.3.10
templates/ingress.yaml:27-41; Befehl `curl` (GET) gegen die Lab-SAM,
17.11.]

### 2.2 Abwägungen und Restrisiken

Vom Owner am 17.11. akzeptiert:

- **Gemeinsamer Origin:** Die öffentliche gpos-Seite ohne Login teilt
  den Origin mit SAM, dessen Bearer-Tokens im `localStorage` liegen.
  Risiko gering: gpos setzt keine Cookies, nutzt keinen Web-Storage
  und baut das DOM nur mit `textContent` [Quelle: gpd
  app/gposdemo/ui/static/shared/common.js; ui/bff.py:326-412; Befehl
  `curl` gegen die Lab-SAM, 17.11.].
- **AKS-Routing weicht vom Lab ab:** Das Lab behält getrennte Hosts.
  Die AKS-Overlays (gpos-Pfad-Ingresses, Keycloak unter `/auth`,
  gRPC-Pfad-Ingresses) sind daher erst auf AKS prüfbar: Traefik-Werte
  in P2, Keycloak in P3, gpos und gRPC in P6.
- **Hairpin:** SAM ruft sich selbst und Keycloak (Back-Channel) über
  `<fqdn>` auf, also über die eigene öffentliche LB-IP [Quelle: amd
  scripts/start.sh:136-147]. Test in P1; scheitert er, schreibt
  `coredns-custom` `<fqdn>` auf die Traefik-ClusterIP um.
- **Anonyme Schreibzugriffe:** Kasse, Reset und die gRPC-Schreib-RPCs
  sind für jeden aufrufbar, gRPC auch an der SAM-Freigabe vorbei.
  Grenzen setzen `public-guard` (HTTP-Pfade und gRPC-Service-Pfade je
  Client-IP) und die Limits am Messe-Key.
- **Ein Node, Free-Tier:** kein Uptime-SLA; Node-Image-Update oder
  Node-Ausfall stoppt alles für einige Minuten. Gegenmittel:
  Wartungssperre um die Messe, Neuaufbau-Drill in P7, L3 warm.

Restrisiken mit Gegenmittel:

- **Let's Encrypt im geteilten Bucket:** Ausstellung kann tagelang
  scheitern (AKS-E4); Staging zuerst, Produktion früh in P2,
  Rückfall-Issuer mit EAB, Secret-Backup statt Neuausstellung.
- **Sichtbarkeit:** Scanner finden `<fqdn>` über die CT-Logs sofort
  [A]; deshalb nur 80/443 offen und keine Route für
  Admin-Oberflächen.
- **Keycloak-Sperre (offen, Entscheidung in P3):** Jeder kann den
  Approver `marktleitung@solace.lab` über den Brute-Force-Schutz
  wiederholt bis zu 15 min sperren (5 Fehlversuche,
  `maxFailureWaitSeconds` 900). Der Name steht in rund 35 Dateien des
  öffentlichen Repos, und der Realm erlaubt den Login per E-Mail
  [Quelle: sli keycloak/manifests/03-keycloak.yaml:30-47; Befehl
  `git grep -l` auf Commit 7a860c5, 17.11.]. Bestehende Sitzungen
  laufen weiter. P3 entscheidet: nicht erratbarer Username und
  `loginWithEmailAllowed: false` in der AKS-Realm-Kopie, oder bewusst
  hinnehmen mit Runbook-Schritt "Sperre aufheben".
- **LLM-Kosten über gRPC:** Kassenvorgänge über die öffentliche
  Purchase-gRPC-Schnittstelle lösen Reviews aus. Die gRPC-Service-Pfade
  bekommen deshalb eigene `limit-rpm` je Client-IP (P6 Schritt 8);
  die Kostengrenze bleibt das Limit am Messe-Key [A].
- **Freigabe- und Operator-Seiten (offen, nicht akzeptiert):**
  `/freigabe` beantwortet pausierte SAM-HITL-Läufe, `/foto` startet den
  teuersten LLM-Pfad, `/op` schaltet auf L4. Öffentlich ohne Login
  könnte jeder Preise freigeben oder den Messe-Key leeren. Bis zur
  Owner-Entscheidung (Frage 23) gibt es für sie keinen Pfad auf
  `<fqdn>` [Quelle: PLAN 1.4; PLAN 9 R24].
- **GEBIT-Schema öffentlich:** Schon mit 0.1.3 beantwortet gpos-pos
  Reflection aus dem GEBIT-Pool, ab 0.1.4 sucht der gemeinsame
  Endpunkt Symbole und Dateien zuerst dort; öffentliche Reflection
  gibt damit die GEBIT-Descriptor-Dateien heraus, nicht nur die
  Dienstliste. Die Reflection-Route kommt erst
  nach der schriftlichen Bestätigung aus AKS-E16.
- **Ein Eingang mit Request-Buffering:** Traefik puffert Bodies für
  SAM und gpos-ui in einem emptyDir; viele parallele Uploads können es
  füllen und den einzigen Traefik-Pod verdrängen. Gegenmittel je
  Client-IP: `limit-connections`, kleineres Body-Limit, größeres
  emptyDir (P2 Schritt 5, P5 Schritt 2); verteilte Uploads aus vielen
  IPs bleiben Restrisiko (Abschnitt 7).

## 3. Sizing

Stand 17.11.2026, nach den Owner-Entscheidungen vom selben Tag: ein
Node ohne HA, Free-Tier für das ganze Projekt, arm64, Traefik statt
ingress-nginx, öffentlich ohne WireGuard, Broker 10.26.0.9219 LTS.

### 3.1 Gemessener Lab-Footprint der umziehenden Teile

Nutzung = `kubectl top` bzw. `docker stats`; Peak = Prometheus
`max_over_time` 11.-16.11. (Pod-Ebene, plus Page-Cache-Abstand)
[Quelle: Befehle `kubectl top pods -A`, `kubectl get pods -A -o json`
summiert, Prometheus-Query, `docker stats --no-stream`, alle 16.11.].

| Namespace / Teil | Nutzung CPU / RAM | 6-Tage-Peak RAM | Requests CPU / RAM | Limits |
|---|---|---|---|---|
| ingress-nginx (nur Lab, AKS nutzt Traefik) | 3m / 215Mi | 246Mi | 100m / 90Mi | keine |
| cert-manager + trust-manager | 6m / 329Mi | 382Mi | 100m / 320Mi | RAM 640Mi |
| kyverno (entfällt auf AKS) | 43m / 536Mi | 647Mi, CPU-Spitze 7,0 Kerne | 400m / 320Mi | RAM 768Mi |
| monitoring | 61m / 4788Mi | 5728Mi | 660m / 1266Mi | 4700m / 9984Mi |
| iam (Keycloak + PG) | 4m / 841Mi | 875Mi | 300m / 768Mi | RAM 1536Mi |
| sam-solace-lab | 43m / 1849Mi | 2565Mi | 2450m / 4608Mi | 14500m / 10752Mi |
| gpos-demo | 20m / 433Mi | 541Mi | 300m / 768Mi | RAM 2304Mi |
| **Summe Kubernetes** | **180m / 8991Mi** | 8391Mi gleichzeitig (+2,4 GiB Cache) | **4310m / 8140Mi** | 19200m / 25984Mi |
| solace-1 (Docker, 10.25.0.208) | 57m / 4,19 GiB | - | keine | keine |
| Demo-Postgres (Docker) | ~1m / 173 MiB | - | keine | keine |
| **Gesamt** | **~0,24 Kerne / 13,1 GiB** | | | |

Befunde:

- Die Lab-Requests liegen 3- bis 4-mal unter der Nutzung (Monitoring
  1,2 GiB angefordert, 4,7 GiB genutzt). Auf AKS werden Requests auf
  die Ist-Werte gesetzt.
- Keycloak wurde am 04.11. bei 1Gi OOMKilled [Quelle: Befehl `kubectl
  get pods -A -o json` lastState;
  sli keycloak/manifests/03-keycloak.yaml:201-204].
- SeaweedFS hing am Subchart-Default 500m/512Mi; der Fix (2 CPU/2Gi)
  ist seit 17.11. committet [Quelle: amd
  local-k8s-values.yaml:262-273, Commit cd08a17].
- Prometheus liegt auf emptyDir (4,7 GiB TSDB) [Quelle: Befehl
  `kubectl get statefulset ... -o json`, 16.11.].
- Die ingress-nginx-Zeile ist nur Vergleichswert: Das Lab behält
  ingress-nginx, AKS bekommt Traefik v3.7.19 (AKS-E6). Einen
  Traefik-Messwert gibt es erst in P2.
- `solace-1` läuft ohne Skalierungsvorgabe (emd docker-compose.yaml
  setzt kein `system_scaling_*`) und trägt mehr VPNs und Queues als
  der künftige AKS-Broker [Quelle: emd docker-compose.yaml:20-60].

Ausgeschlossen (bleibt im Lab):

| Teil | Nutzung | Requests | Storage |
|---|---|---|---|
| sam-solace-lab-agents | 16m / 4653Mi (Peak 9355Mi) | 1500m / 1536Mi | - |
| db-designer | 8m / 120Mi | 450m / 896Mi | PVC 9Gi |
| sam-solace-lab-shared (searxng) | 2m / 143Mi | 50m / 128Mi | - |
| oci (Registry) | 1m / 30Mi | 100m / 256Mi | PVC 50Gi |
| mi-solace-lab | 0 Pods | - | PVC 10Gi |
| kube-system (k3s) | 7m / 240Mi | - | ersetzt durch AKS-Systempods |
| otel-collector, pgadmin (Docker) | 122 MiB, 249 MiB | - | - |
| solace-2, EMA (Docker) | Exited seit 13 Tagen (Stand 16.11.) | - | - |

### 3.2 Rechenweg

Requests auf AKS = max(Lab-Request, gemessener Peak + Cache), gerundet
[Quelle: Footprint-Leser 16.11.]. Alles läuft auf einem Node
(Owner-Entscheidung 17.11.: kein HA):

| Komponente | CPU | RAM | Begründung |
|---|---|---|---|
| Traefik v3.7.19, 1 Replik | 100m | 256Mi | statt ingress-nginx im Lab; Chart-Default `resources: {}` [Quelle: traefik 42.4.1 values.yaml:1274]; Wert [A], Messung in P2 |
| cert-manager v1.21.3 (ohne trust-manager) | 125m | 384Mi | Peak 382Mi |
| Monitoring inkl. Tempo | 1000m | 5760Mi | Peak 5728Mi |
| iam (Keycloak 1Gi/1,5Gi + PG) | 300m | 1280Mi | OOM bei 1Gi |
| SAM (gwe, awe, str, PG, SeaweedFS) | 2450m | 4608Mi | Lab-Requests, Peak 2565Mi |
| gpos-demo (6 Pods) | 300m | 768Mi | Lab-Requests |
| Demo-Postgres (neu, `gpos-data`) | 100m | 256Mi | Ist 173 MiB |
| Broker `prod1k` (10.26.0.9219) | 2000m | 6515Mi | Chart-Größe [Quelle: pubsubplus 3.10.0 templates/solaceStatefulSet.yaml:70-72, 92-94] |
| **Summe Workloads** | **6375m** | **19827Mi (19,4 GiB)** | |
| AKS-Systempods auf einem Node [A] | 750m | 1536Mi | RA:414 nennt 0,3-0,5 CPU und 0,7-1 GiB je Node; die Deployments (CoreDNS, metrics-server, konnectivity je 2 Replikas) liegen jetzt alle auf dem einen Node |
| **Summe auf 1 Node** | **7125m** | **21363Mi (20,9 GiB)** | |
| zum Vergleich: Broker `dev` statt `prod1k` | 1000m | 3410Mi | [Quelle: pubsubplus 3.10.0 templates/solaceStatefulSet.yaml:67-69, 89-91] |
| **Summe auf 1 Node mit `dev`** | **6125m** | **18258Mi (17,8 GiB)** | |

Allocatable des Nodes bei `--max-pods 110`: CPU 8000m - 180m = 7820m;
RAM 32768Mi - (20 MB x 110 + 50 MB) - 100Mi = 30418Mi
[Quelle: `learn.microsoft.com/azure/aks/node-resource-reservations`].
Mit dem Overlay-Default 250 Pods gingen 2,7 GiB verloren
[Quelle: `learn.microsoft.com/azure/aks/concepts-network-ip-address-planning`].
"MB" als MiB gerechnet, echte Kapazität 2-3 % darunter [A]; nach dem
Create per `kaks get nodes` bestätigen. Die nominellen 29 GiB werden
nur erreicht, wenn die echte Kapazität höchstens rund 2 % unter
32768Mi liegt; die P1-Abnahme verlangt deshalb mindestens 28,5 GiB
(29184Mi). Gegen diesen Wert liegen die `prod1k`-Requests bei 73 %
RAM; P1 prüft höchstens 92 % CPU und 75 % RAM.

| Kennzahl (Allocatable 7820m / 30418Mi) | Wert |
|---|---|
| Requests / Allocatable mit `prod1k` (7125m / 21363Mi) | 91 % CPU / 70 % RAM |
| Requests / Allocatable mit `dev` (6125m / 18258Mi) | 78 % CPU / 60 % RAM |
| freie Requests mit `prod1k` bzw. `dev` | 695m / 9055Mi bzw. 1695m / 12160Mi |
| Peak-Working-Set inkl. WAL-Reserve und Broker-Reservierung | rund 20,3 GiB (68 %) |
| Summe aller Memory-Limits | rund 33 GiB (rund 111 %, Overcommit) |
| reale CPU-Nutzung | p99 0,65 Kerne, Spitze 2,26 Kerne (ohne Kyverno) |
| Pods | rund 60 [A], Grenze 110 |

Die Limits überbuchen den Node. Das ist vertretbar, weil die Peaks bei
rund 20,3 GiB liegen; unter Speicherdruck räumt das Kubelet zuerst
Pods über ihrem Request, bei gleicher Lage zuerst die niedrigere
PriorityClass `demo-observability` (P2). Der Broker ist Guaranteed
(Requests = Limits).

Freier Platz für kurzlebige Pods: Ein Rolling Update legt erst den
neuen Pod an. Der SAM-Chart setzt keine `strategy`, also gilt der
Default mit einem Zusatz-Pod [Quelle: SAM-Chart 2.3.10 templates,
`grep strategy` ohne Treffer]; der größte ist awe mit 1000m/1Gi
[Quelle: SAM-Chart 2.3.10 values.yaml:555]. Dazu kommen der
Break-glass-Pod von `az aks command invoke` (200m/500Mi [Quelle:
`learn.microsoft.com/azure/aks/access-private-cluster`]) und der
HTTP-01-Solver von cert-manager. Mit `prod1k` bleiben 695m frei: Ein
awe-Update passt nicht sofort. Der neue Pod (`demo-critical` als
`globalDefault`) verdrängt dann einen `demo-observability`-Pod
(Preemption); Monitoring hat einige Minuten eine Lücke, die Demo
nicht. Mit `dev` (1695m frei) passt awe ohne Verdrängung.

Broker `prod1k` oder `dev` (AKS-E8: `prod1k`, außer das
Sizing erzwingt `dev`):

- `prod1k`: 2000m/6515Mi, Guaranteed, 1000 Verbindungen [Quelle:
  pubsubplus 3.10.0 templates/solaceConfigMap.yaml:45], mehr RAM als
  die 4,19 GiB, die `solace-1` im Lab belegt. Der Lab-Broker selbst
  läuft mit dem Default von 100 Verbindungen [A: per SEMP prüfen].
  Passt mit 91 % CPU-Requests; große Updates laufen über Preemption
  der Monitoring-Pods.
- `dev`: Request 1000m/3410Mi, Limit 2 CPU/3410Mi (Burstable),
  100 Verbindungen [Quelle: solaceConfigMap.yaml:43;
  solaceStatefulSet.yaml:67-69, 89-91]; die Demo braucht rund 11. Der
  Chart nennt `dev` ein Minimal-Profil ohne Leistungszusage [Quelle:
  pubsubplus values.yaml:53-54]. Das Limit liegt unter den 4,19 GiB,
  die `solace-1` im Lab belegt [A: OOM-Risiko; der Lab-Broker trägt
  mehr VPNs und Queues]. Spart 1000m und 3105Mi.
- Empfehlung: `prod1k`. Das Sizing erzwingt `dev` nicht.
  Umschaltkriterium vor P4, dieselbe Grenze wie in P1 und P7: Liegt
  die nach P2 gemessene Summe der CPU-Requests (System, Traefik,
  cert-manager, Monitoring, ggf. Defender-Sensor) über 2044m (geplant
  1975m), überschreitet `prod1k` mit den restlichen 5150m die
  92-%-Grenze (7194m von 7820m), und P4 installiert `dev`.
- Die Größe gilt ab dem ersten Boot: Die Skalierungsparameter werden
  nur beim ersten Start ohne Datenbank ausgewertet [Quelle:
  `docs.solace.com/Software-Broker/SW-Broker-Upgrade/Docker-Upgrade-Current-Release.htm`;
  A: gilt im Chart gleich]. Ein späterer Wechsel heißt Neuaufbau des
  Brokers, also vor dem ersten Install in P4 entscheiden.

Verworfen (Preise: Retail-API 17.11., siehe 3.4):

- 2 x D8ps_v6 (Empfehlung vom 16.11., N-1-fähig): +239 EUR/Monat bei
  24/7 (Node 219,5 plus OS-Disk P10 19,5); Owner-Entscheidung 17.11.:
  kein HA.
- 1 x D4ps_v6 (4 vCPU, 0,1508/h): 7125m Requests gegen 3860m
  Allocatable.
- 1 x E8ps_v6 (8 vCPU/64 GiB, 0,3959/h): gleiche CPU-Enge, RAM nicht
  nötig, +69,5 EUR/Monat.
- 1 x D16ps_v6 (16 vCPU/64 GiB, 0,6015/h): löst die CPU-Enge, kostet
  +219,6 EUR/Monat und für den Surge-Node 32 vCPU Quota.
- B-Serie (als System-Pool nicht unterstützt [Quelle:
  `learn.microsoft.com/azure/aks/use-system-pools`]), AKS Automatic und
  Node Auto-Provisioning (nicht stoppbar [Quelle:
  `learn.microsoft.com/azure/aks/node-auto-provisioning`]).

### 3.3 Empfohlener Node-Pool, Updates und Storage

- Ein Pool `main` im System-Modus, 1 x `Standard_D8ps_v6` (Cobalt
  100, 8 vCPU / 32 GiB, arm64), `--node-count 1`, `--max-pods 110`,
  kein Autoscaler, `max-surge 1`. Microsoft Learn verlangt für
  produktive System-Pools mindestens 2 Nodes und empfiehlt 3 [Quelle:
  `learn.microsoft.com/azure/aks/use-system-pools`]; der
  AKS-Quickstart legt mit `--node-count 1` an [Quelle:
  `learn.microsoft.com/azure/aks/learn/quick-kubernetes-deploy-cli`].
  Dass AKS einen System-Pool mit einem Node annimmt, ist [A]; der
  Create in P1 ist der Beweis. App-Pods auf dem System-Pool sind für
  eine Demo akzeptiert [A].
- Kein HA (Owner-Entscheidung 17.11.): Fällt die VM aus, steht alles,
  bis AKS den Node repariert; Rückfall ist L3 im Lab. Einen N-1-Drill
  gibt es nicht mehr.
- Keine Zonenfestlegung: regionaler Pool, LRS-Disks [A: hängen an
  jedem nicht-zonalen Node]. Test in P1: Pool kurz auf 2 Nodes
  skalieren, einen Test-Pod mit PVC per cordon auf den zweiten Node
  zwingen, zurück auf 1 Node; das ist derselbe Weg wie beim
  Surge-Node. Alternative `--zones 1`, falls `az vm list-skus`
  Restriktionen zeigt.
- OS-Disk 128 GiB P10 managed: Dpsv6 hat keine ephemeral OS-Disk
  [Quelle: `learn.microsoft.com/azure/virtual-machines/sizes/general-purpose/dpsv6-series`];
  die arm64-Images allein sind rund 17,6 GB unkomprimiert [Quelle:
  Befehl `docker system df -v`, 16.11.].
- arm64 trägt alle Images (AKS-E3): SAM und gpos-demo
  sind arm64-only; Broker 10.26.0.9219 ist multi-arch (Index-Digest
  beginnt mit `sha256:c0020e53ed48`); Traefik v3.7.19 und cert-manager
  v1.21.3 haben arm64-Images; Keycloak, Postgres und Monitoring laufen
  heute auf dem arm64-Lab-Node [Quelle: Docker-Hub-Tags-API und
  `quay.io`-Manifeste, 17.11.; Befehl `docker buildx imagetools
  inspect`, 16.11.]. Ein amd64-Pool wäre nur für eine GEBIT-Übergabe
  nach der Messe Thema und bräuchte je Image eine Prüfung. arm64 als
  System-Pool auf v6 ist nicht ausdrücklich dokumentiert (die
  Learn-Seite nennt nur v5) [A]; der Create in P1 ist der Beweis.
- Ist Defender for Containers in der Subscription aktiv (P0), belegt
  sein Sensor-DaemonSet CPU und RAM auf dem Node; in P2 mit `kaks top
  pods -A` messen und in 3.2 nachtragen [A: Größe]. Der Messwert
  zählt beim Umschaltkriterium für den Broker mit.
- Die Node-Ressourcengruppe heißt fest `rg-eurocis-nodes`
  (`--node-resource-group`, nur beim Create setzbar). VM, OS-Disk,
  PVC-Disks und der Load Balancer liegen dort. Beide statischen
  Public IPs (`pip-aks-ingress` mit DNS-Label und Lock
  `CanNotDelete`, `pip-aks-egress`) liegen in `rg-eurocis-base`; die
  AKS-Steuerungsebenen-Identität braucht dort Network Contributor
  [Quelle: `learn.microsoft.com/azure/aks/static-ip`].

Node-Image-Update auf einem Node:

1. AKS legt mit `max-surge 1` einen zweiten Node mit neuem Image an
   (Quota +8 vCPU, rund 0,30 EUR je Stunde) [Quelle:
   `learn.microsoft.com/azure/aks/auto-upgrade-node-os-image`].
2. Der alte Node wird gesperrt und geleert. Alle Pods starten auf dem
   neuen Node neu, die Azure-Disks hängen um, und die Images fehlen
   dort noch im Cache (rund 17,6 GB, aus ACR in derselben Region). Der
   Broker hat bis 1200 s Zeit zum Herunterfahren [Quelle: pubsubplus
   3.10.0 templates/solaceStatefulSet.yaml:57].
3. Ausfall: einige Minuten für Demo, SAM und Keycloak [A: 5-15 min];
   der erste Refresh misst den echten Wert.
4. Keine PDB darf den Drain blockieren: Traefik ohne PDB [Quelle:
   traefik 42.4.1 values.yaml:125-126], Broker-PDB nur bei HA [Quelle:
   pubsubplus 3.10.0 templates/podDisruptionBudget.yaml:2,
   values.yaml:18], keine eigene PDB mit `minAvailable: 1` auf einem
   Einzel-Pod [A: sonst scheitert das Update am Drain-Timeout]. Die
   P2-Abnahme prüft `kaks get pdb -A` (erlaubte Unterbrechungen
   mindestens 1 oder keine PDB).
5. Zeitpunkte bleiben wie in AKS-E14: Node-OS-Kanal SecurityPatch
   Mi 08:00-12:00 (Reimage nur bei Bedarf), manueller Refresh Di
   26.01.2027, `notAllowedDates` 20.01. und 27.01.-20.02.2027. Reaktive
   Wartung bleibt ein Risiko (Abschnitt 7).
6. Reicht die Quota nur für 8 vCPU, geht der Refresh ohne Surge
   (`--max-surge 0` mit `--max-unavailable 1`) [A: Flag in Azure CLI
   2.93 prüfen]; der Ausfall dauert dann bis zum Reimage des Nodes.

| PVC | Größe | Klasse | Tier, EUR/Monat |
|---|---|---|---|
| Broker | 128Gi | managed-csi-premium | P10, 500 IOPS, 19,46 |
| Prometheus (neu) | 16Gi | managed-csi-premium | P3, 2,80 |
| SAM-Postgres | 10Gi | managed-csi-premium | P3, 2,80 |
| SeaweedFS | 20Gi | managed-csi-premium | P4, 5,21 |
| Keycloak-Postgres | 5Gi | managed-csi (Default) | Standard SSD E2, 0,54 |
| Loki | 10Gi | managed-csi | E3, 1,08 |
| Tempo | 10Gi | managed-csi | E3, 1,08 |
| Demo-Postgres | 8Gi | managed-csi | E2, 0,54 |
| **Summe** | **207Gi** | | **33,5 plus Transaktionen** |

Quellen: Solace-Richtwert mindestens 300 IOPS für 1000 Verbindungen
[Quelle: `docs.solace.com/Software-Broker/System-Resource-Requirements.htm`];
P6 64Gi hätte nur 240 IOPS. Lab-Manifeste ohne `storageClassName`
binden an den AKS-Default `managed-csi` [Quelle:
`learn.microsoft.com/azure/aks/concepts-storage`]; Premium nur dort,
wo ein Chartwert existiert (SAM:
`persistence-layer.<store>.persistence.storageClassName`, Render
verifiziert vom SAM-Leser; AKS-E7). Abgerechnet wird je Disk die
nächste Tier-Stufe (E1 4 GiB, E2 8 GiB, E3 16 GiB) [A]; Standard SSD
kostet zusätzlich 0,0018 EUR je 10.000 Operationen [Quelle:
Retail-API 17.11.].

### 3.4 Kosten

Listenpreise Pay-as-you-go, EUR ohne MwSt., 730 h/Monat [Quelle:
Befehl `curl https://prices.azure.com/api/retail/prices` mit
`currencyCode=EUR`, `armRegionName` germanywestcentral, LB-Zähler
unter `Global`, 17.11.]. Nachtstopp = Laufzeit 10 h an 22
Arbeitstagen (220 Laufstunden je Monat) wie bisher.

| Posten | Ressourcengruppe | EUR/Monat 24/7 | EUR/Monat Nachtstopp | Quelle |
|---|---|---|---|---|
| 1 x D8ps_v6 (0,3007/h) | rg-eurocis-nodes | 219,5 | 66,2 | Retail-API |
| AKS Free-Tier, ganzes Projekt | rg-eurocis-aks | 0 | 0 | Owner-Entscheidung 17.11. |
| Zeile "FreeTierInfrastructureCost Uptime SLA" (0,0449/h ab 01.10.2026) | rg-eurocis-aks [A] | 0-32,8 | 0-32,8 [A: 9,9 bei Abrechnung nur der Laufzeit] | Retail-API, ohne Doku |
| OS-Disk P10 | rg-eurocis-nodes | 19,5 | 19,5 | Retail-API 19,4623 |
| Broker-PVC P10 | rg-eurocis-nodes | 19,5 | 19,5 | Retail-API |
| Premium-PVCs P3, P3, P4 | rg-eurocis-nodes | 10,8 | 10,8 | Retail-API (P3 2,8008, P4 5,213) |
| Standard-SSD-PVCs E2, E3, E3, E2 | rg-eurocis-nodes | 3,2 + bis rund 6 Transaktionen [A] | 3,2 + bis rund 2 [A] | Retail-API (E2 0,5386, E3 1,0772) |
| Standard LB, 3 Regeln (TCP 80, TCP 443, Outbound) | rg-eurocis-nodes | 16,4 | 16,4 [A: läuft im Stopp weiter] | Retail-API 0,0224/h für die ersten 5 Regeln |
| 2 statische Public IPs (`pip-aks-ingress`, `pip-aks-egress`) | rg-eurocis-base | 6,6 | 6,6 | Retail-API 0,0045/h |
| ACR Basic (0,1496/Tag) | rg-eurocis-base | 4,6 | 4,6 | Retail-API [A: bis 10 GiB inklusive, darüber 0,0898/GB] |
| Key Vault (0,0269 je 10.000 Operationen) | rg-eurocis-base | unter 0,1 | unter 0,1 | Retail-API |
| Datenabfluss ins Internet, LB-Datenverarbeitung | - | rund 0 | rund 0 | Retail-API: die ersten 100 GB/Monat frei, LB 0,0045/GB [A: Demo unter 10 GB] |
| **Summe Messe-Konfiguration** | | **rund 300-340** | **rund 145-185** | |

- **Rechnung:** 24/7 ohne Free-Tier-Zeile 300,0 EUR, mit ihr 332,8 EUR,
  plus Transaktionen. Nachtstopp: 80,5 EUR Fixkosten (Disks, LB, IPs,
  ACR, KV) plus 66,2 EUR Node = 146,7 EUR; mit der Free-Tier-Zeile
  156,6 EUR (nur Laufzeit) bis 179,5 EUR (jede Stunde), plus
  Transaktionen.
- **LB-Regeln:** Traefik ist der einzige LoadBalancer-Service, mit TCP
  80 und 443 auf `pip-aks-ingress`; dazu die Outbound-Regel auf
  `pip-aks-egress`. Mit 3 Regeln bleibt es beim Grundpreis 0,0224/h;
  ab der sechsten Regel kostet jede 0,009/h (6,57 EUR/Monat).
  Ausgehende Regeln zählen mit, eingehende NAT-Regeln nicht [Quelle:
  `azure.microsoft.com/pricing/details/load-balancer`]. Die VAP (nur
  der Service `traefik/traefik` darf LoadBalancer sein, P2 Schritt 3)
  hält das so.
- **Gegenüber dem 16.11.:** rund 300 EUR/Monat weniger bei 24/7; die
  Posten je Owner-Entscheidung und die verworfene Variante mit 6
  DNS-Labels (7 IPs, 13 LB-Regeln, rund 69 EUR/Monat mehr) stehen in
  8.5.
- **Aufteilung je RG (24/7):** `rg-eurocis-base` rund 11 EUR,
  `rg-eurocis-aks` 0-33 EUR (nur die unklare Free-Tier-Zeile [A]),
  `rg-eurocis-nodes` rund 289-295 EUR. Ein Budget nur auf
  `rg-eurocis-base` und `rg-eurocis-aks` sähe also höchstens rund 44
  von 300-340 EUR.
- **Free-Tier:** Die Steuerungsebene hat kein Uptime-SLA; das betrifft
  kubectl und helm, nicht die laufenden Pods. Die Preiszeile
  "FreeTierInfrastructureCost Uptime SLA" steht seit 01.10.2026 in der
  Retail-API, ohne Doku [Quelle: Retail-API 17.11.;
  `azure.microsoft.com/pricing/details/kubernetes-service`]. Nach Tag 1
  im Cost Management prüfen, ob und wann sie abgerechnet wird.
- **Mit Stopp (Aufbau):** Im Stopp laufen Disks, IPs, LB [A], ACR und
  KV weiter: rund 80,5 EUR/Monat. Der Node kostet 0,30 EUR je
  Laufstunde (0,35 mit Free-Tier-Zeile).
- **amd64-Variante (nicht geplant, AKS-E3):** 1 x
  D8as_v6 (0,3941/h) kostet +68,2 EUR/Monat bei 24/7, +20,5 EUR mit
  Stopp. Rückfall-Familie Dpsv5 (D8ps_v5, 0,3304/h): +21,7 bzw. +6,5
  EUR.
- **Bedingt, nur wenn Defender in der Subscription aktiv ist** (nicht
  in der Basissumme) [Quelle: Retail-API 17.11.]: Defender for
  Containers kostet 0,0084 EUR je vCore-Stunde, also 49,1 EUR/Monat bei
  24/7 (8 vCores) und 14,8 EUR/Monat mit Nachtstopp. [A] Defender for
  Servers könnte auch die Node-VM abrechnen: P1 0,006/h (4,4 bzw. 1,3
  EUR), P2 0,018/h (13,1 bzw. 4,0 EUR). Die SecurityPatch-VHDs in
  `rg-eurocis-nodes` kosten einige EUR [Quelle:
  `learn.microsoft.com/azure/aks/auto-upgrade-node-os-image`; A: Höhe].
- **Projektsumme** (Free-Tier durchgehend, Nachtstopp bis G4, ab 05.02.
  24/7, Rückbau 20.02.2027) [A: Laufmuster]:
  - November rund 8 EUR (beide IPs ab rund 20.11., rund 2 EUR; ACR,
    Key Vault und Cluster ab 30.11. aus P1);
  - Dezember rund 135-185 EUR (180-230 Laufstunden, Feiertage
    gestoppt);
  - Januar rund 140-190 EUR (200-250 Laufstunden inkl. 24-h-Lauf
    18./19.01.);
  - Februar bis 20.02. rund 180-210 EUR (Nachtstopp bis 04.02., dann
    24/7, zusammen rund 425-435 Laufstunden).
  - Gesamt rund 470-600 EUR ohne LLM-Token; mit aktivem Defender for
    Containers rund 520-660 EUR. Beides liegt deutlich unter dem Ziel
    von 1.500 EUR (AKS-E1). Das obere Ende enthält die Free-Tier-Zeile
    für jede Stunde und die Disk-Transaktionen.
- **Budget (AKS-E1), neu skaliert:** ein Budget auf
  Subscription-Ebene, gefiltert auf `ResourceGroupName` in
  `rg-eurocis-base`, `rg-eurocis-aks`, `rg-eurocis-nodes`; Zeitraster
  monatlich, **250 EUR** (statt 450 EUR), 01.12.2026 bis 31.03.2027;
  Benachrichtigung bei Actual 100 % und Forecast 100 %. Begründung:
  Die erwarteten Monate liegen bei 135-210 EUR, ein Monat 24/7 bei
  300-340 EUR; 450 EUR würde nicht einmal einen ganzen vergessenen
  Monat melden. Budgets setzen sich je Periode zurück, Kostendaten
  kommen mit 8-24 h Verzug [Quelle:
  `learn.microsoft.com/azure/cost-management-billing/costs/tutorial-acm-create-budgets`].
  Zweck: ein mehrtägig vergessener Stopp im Dezember oder Januar und
  Restkosten im März (ein weiterlaufender Cluster mit rund 10-11
  EUR/Tag hebt den Forecast innerhalb weniger Tage über 250 EUR [A:
  Forecast-Modell]). Im Februar (24/7 ab 05.02.) löst der Forecast sehr
  wahrscheinlich aus, weil er den Rückbau am 20.02. nicht kennt; das ist
  erwartet. Die Projektsumme läuft separat über eine gespeicherte
  Cost-Analysis-Ansicht mit demselben Filter im wöchentlichen
  Kosten-Check; den vergessenen Nachtstopp fängt der Abend-Check (P1).
  Das Azure-Budget sieht keine LLM-Kosten; die begrenzen der Messe-Key
  (O5) und seine rpm-/tpm-Limits (AKS-E11).

### 3.5 Quota-Bedarf

| Quota (Germany West Central) | Bedarf | Vorhanden |
|---|---|---|
| Standard DPSv6 Family vCPUs | 16 (8 für den Node + 8 für den Surge-Node beim Node-Image-Update) | unbekannt |
| Standard DPSv5 Family vCPUs (arm64-Rückfall, nur bei Restriction für `Standard_D8ps_v6`, P0 Schritt 4) | 16 | unbekannt |
| Total Regional vCPUs | mindestens 16 | unbekannt |
| Standard Public IPv4 | 2 (`pip-aks-ingress`, `pip-aks-egress`) | unbekannt; Default 10 für die meisten Angebote, 20 für Pay-as-you-go [Quelle: `learn.microsoft.com/azure/azure-resource-manager/management/azure-subscription-service-limits`] |

Andere Familien (amd64, B-Serie) braucht der Plan nicht (AKS-E3). Der
Surge-Node bleibt Pflicht, sonst gilt der Weg ohne Surge aus 3.3
Punkt 6.

"Unbekannt", weil am 16.11. jeder ARM-Aufruf mit AADSTS9002313
scheiterte [Quelle: Befehl `az aks get-versions -l
germanywestcentral`, 16.11., zweimal]. P0 prüft nach dem Owner-Login
in der bestehenden Subscription mit `az vm list-usage -l
germanywestcentral` und `az network list-usages -l
germanywestcentral`. Fehlen DPSv6-vCPUs, stellt der Owner am 20.11.
den Antrag über "My quotas" im Portal (eine Schreibaktion), DPSv5 16
vCPU nur, falls `az vm list-skus` für `Standard_D8ps_v6` eine
Restriction zeigt (P0 Schritt 4), dann im selben Antrag. Eine
freigegebene Familien-Quota hebt die
regionale Quota mit an [Quelle:
`learn.microsoft.com/azure/quotas/per-vm-quota-requests`]; P0 prüft sie
trotzdem. Zeigt DPSv6 "not available for increase", stellt der Owner
noch am selben Tag einen Support-Fall und weicht auf DPSv5 oder West
Europe aus.

## 4. Vorgehen in Phasen

| Phase | Inhalt | PT | Kalender | Gate |
|---|---|---|---|---|
| P0 | Vorbereitung, Klärungen, Azure-Vorab (RG, Ingress-IP mit DNS-Label, Egress-IP), Sicherheitsgeländer, Lab-Broker-Upgrade einplanen | 2,5 | KW47-48 (16.-27.11.) | - |
| P1 | Azure-Grundlagen, Cluster (1 Node, Free-Tier), ACR, Key Vault, CLI, API-Server-Allowlist, Hairpin-Test | 2,0 | KW49 (30.11.-04.12.) | Prüfpunkt 04.12. |
| P2 | Plattform-Add-ons (Traefik, cert-manager mit HTTP-01, VAP, Monitoring) | 3,0 | KW49-50 (03.-10.12.) | - |
| P3 | Keycloak unter `/auth` | 1,25 | KW50 (10.-11.12.) | Prüfpunkt 11.12. (P2 + P3) |
| P4 | Broker 10.26.0.9219: Teil A Lab-Broker-Upgrade (1,0 PT, eigenes Go), Teil B AKS (1,25 PT) | 2,25 | Teil A KW48-49 (bis 04.12., spätestens 10.12.), Teil B KW51 (14.-15.12.) | Prüfpunkt 04.12. (Teil A) |
| P5 | SAM | 2,5 | KW51 (15.-17.12.), 0,5 PT Puffer bis 18.12. | G2a 18.12. |
| P6 | GEBIT-Demo portieren, Image 0.1.4 mit gemeinsamem Reflection-Endpunkt | 5,75 | KW52-KW1 (Vorarbeit im Lab), KW1-2 auf AKS | G2b 15.01. |
| P7 | Härtung und Betrieb | 4,25 | KW3-KW7 | G3 22.01., G4 05.02. |
| | **Summe** | **23,5** (mit 15 % Puffer von 3,5 PT rund 27,0) | | |

Wer: "Claude" heißt Skripte schreiben, read-only prüfen und
Schreibbefehle erst nach Freigabe des Owners je Schritt ausführen.
"Owner" heißt Logins, Passwörter, Freigaben, Wahl des DNS-Labels,
Konten (etwa beim ACME-Rückfall-CA) und Kontakte. "C" ist die dritte
Person aus O9 (ab 23.11.); die PT des Plans sind ihr Aufwand.

Namen: `<p>` ist das DNS-Label der Ingress-IP (AKS-E4), `<fqdn>`
steht für `<p>.germanywestcentral.cloudapp.azure.com`. Das ist der
einzige öffentliche Name des Projekts; alle Apps hängen per Pfad
darunter.

Kontext-Regel für alle Phasen: Jeder AKS-Befehl in diesem Plan läuft
über `kaks`/`haks` (P1 Schritt 6) oder über ein Skript, das
`require_kube_context aks-eurocis` aufruft. Lab-Befehle tragen
`--context rancher-desktop`. Ausgenommen ist nur `helm template` ohne
`--validate`, weil es keinen Cluster kontaktiert.

### P0 Vorbereitung und Klärungen (2,5 PT, 16.-27.11.)

**Ziel:** Azure-Lage geklärt, die Owner-Entscheidungen vom 17.11.
(AKS-E1 bis AKS-E20) im PLAN verankert, Ingress-IP mit DNS-Label und
Egress-IP angelegt, Lab-Broker-Upgrade terminiert, Lab gegen
Verwechslung mit AKS geschützt, bevor eine AKS-Credential auf dem Mac
existiert.

**Schritte:**

1. Owner: Neu anmelden, in der bestehenden Subscription (AKS-E1). Der
   gecachte Token scheitert mit AADSTS9002313,
   `~/.azure/azureProfile.json` ist vom 11.09.2025 [Quelle: Befehl
   `ls -la ~/.azure`, 16.11.]. Die CLI selbst nennt als Abhilfe
   `az logout` und `az login` mit `--tenant` [Quelle: Befehl
   `az aks get-versions -l germanywestcentral`, 16.11.].

   ```bash
   az logout
   az login --tenant <tenant>     # Tenant nur lokal, nie im Dokument
   az account set --subscription <subscription>
   ```

2. Claude, read-only:

   ```bash
   for p in ContainerService ContainerRegistry Network Compute \
            KeyVault ManagedIdentity; do
     az provider show -n Microsoft.$p --query registrationState -o tsv
   done
   az aks get-versions -l germanywestcentral -o table
   az vm list-skus -l germanywestcentral --resource-type virtualMachines \
     --query "[?name=='Standard_D8ps_v6'||name=='Standard_D8ps_v5'].\
   {n:name,z:locationInfo[0].zones,r:restrictions}"
   az vm list-usage -l germanywestcentral -o table
   az network list-usages -l germanywestcentral -o table  # Standard-IPs
   # Policies inkl. der von Management Groups geerbten
   az policy assignment list --filter "atScope()" \
     --query "[].{n:displayName,s:scope,mode:enforcementMode,def:policyDefinitionId}" \
     -o table
   # je Zuweisung zu Public IP, managedClusters, Region, Tags, SKUs:
   az policy set-definition show --name <name> [--management-group <mg>] \
     --query "policyDefinitions[].policyDefinitionId" -o tsv
   az policy definition show --name <name> [--management-group <mg>] \
     --query "{e:policyRule.then.effect,p:parameters.effect.defaultValue}"
   # Rollen inkl. Gruppen, Management Groups und Resource Groups
   az role assignment list --assignee <owner-objectId> --all \
     --include-groups --query "[].{r:roleDefinitionName,s:scope,c:condition}" \
     -o table
   # effektive Rechte (Gruppen und Vererbung inklusive, Deny Assignments nicht)
   az rest --method get --url "/subscriptions/{subscriptionId}/providers/\
   Microsoft.Authorization/permissions?api-version=2022-04-01" \
     --query "value[].{a:actions,n:notActions}"
   # nur falls leer oder ohne Owner: PIM-berechtigte Rollen
   az rest --method get --url "/subscriptions/{subscriptionId}/providers/\
   Microsoft.Authorization/roleEligibilityScheduleInstances?\
   api-version=2020-10-01&\$filter=asTarget()"
   # Defender-Pläne (Ausgabe ist {value:[...]})
   az security pricing list \
     --query "value[?pricingTier=='Standard'].{plan:name,sub:subPlan}" -o table
   ```

   `az policy assignment list` zeigt ohne `--filter` nur Zuweisungen
   genau auf der Subscription; geerbte Deny-Policies fehlten dann
   [Quelle: azure-cli 2.85.0 resource/policy.py:231-237].
   `az role assignment list` zeigt ohne `--all` nur die
   Subscription-Ebene; `--include-inherited` ist neben `--all` überflüssig
   [Quelle: `az role assignment list --help`, 2.85.0]. `az rest` setzt
   `{subscriptionId}` selbst ein, die ID erscheint nirgends. Eine
   `az policy state summarize`-Abfrage ist kein Beleg: Sie bewertet nur
   bestehende Ressourcen. `D8ps_v5` steht nur als Kapazitäts-Rückfall
   in der Abfrage (arm64 bleibt, AKS-E3). Zu klären ist:
   - Darf der Owner Rollen zuweisen
     (`Microsoft.Authorization/roleAssignments/write` effektiv, nicht in
     notActions)? Gebraucht für `--attach-acr`, AKS-RBAC, Network
     Contributor auf `rg-eurocis-base` und Key Vault Secrets Officer.
     Bei "Role Based Access Control Administrator" mit Condition muss
     sie diese Rollen erlauben.
   - Darf der Owner Locks setzen (`Microsoft.Authorization/locks/write`
     effektiv)? Von den eingebauten Rollen haben das nur Owner und User
     Access Administrator [A: laut Learn "lock-resources", hier mit dem
     Rechte-Abruf belegen]. Gebraucht für den Lock auf
     `pip-aks-ingress` (Schritt 5).
   - Welche Key-Vault-Datenrollen erbt der Owner schon?
   - Hat der Owner Owner, Contributor oder Cost Management Contributor
     auf der Subscription (für das Budget mit Filter)?
   - Welche Anmeldehäufigkeit setzt Conditional Access (Frage an die
     IT)? Bei kurzer Frequenz plant P7 eine tägliche Neuanmeldung.
3. Owner: Entscheidungen. Am 17.11. hat der Owner die Kernfragen
   entschieden; Inhalt und Status je AKS-E stehen in Abschnitt 2.
   AKS-E9, AKS-E12 und die [A]-Teile anderer Zeilen gelten als
   Annahme der Planung, bis der Owner zur dortigen Frist abweicht. Ohne
   Antwort sind AKS-E18 (Gate-Verschiebung G0-11a/b, bis 27.11.) und
   AKS-E20 (Betreiber und Stellvertreter, Name bis 20.11.); für beide
   gilt die Empfehlung des Plans als Arbeitsstand mit dem Vermerk
   "Owner-Bestätigung offen", ebenso für die Exposition von
   `/freigabe`, `/foto`, `/op` und `/etikett` (Frage 23, bis dahin
   kein Pfad auf `<fqdn>`). Mit Status "offen" ist, ob die
   GEBIT-Freigabe das Descriptor-Set als K8s-Secret in Azure und die
   öffentliche Reflection abdeckt (Schritt 6): Die Planung nimmt ja an
   [A], gehandelt wird aber erst nach schriftlicher Bestätigung
   (AKS-E16).
4. Owner, am 20.11.: Quota-Antrag über "My quotas" für Germany West
   Central (3.5), nur wo `az vm list-usage` bzw.
   `az network list-usages` darunter liegt:
   - Standard DPSv6 Family 16 vCPU: ein Node plus ein Surge-Node beim
     Node-Image-Upgrade (P1 Schritt 4); Total Regional mindestens 16.
   - Standard Public IPs: Platz für 2 (`pip-aks-ingress`,
     `pip-aks-egress`); der Default liegt für die meisten Angebote bei
     10 [Quelle: learn.microsoft.com, Seite
     "azure-subscription-service-limits"].
   - DPSv5 16 vCPU nur, falls Schritt 2 für `Standard_D8ps_v6` eine
     Restriction zeigt.

   Bei "not available for increase" am selben Tag einen Support-Fall
   stellen.
5. Claude nach Freigabe, Azure-Vorab (show-or-create, idempotent), ab
   20.11. und nach grünem Schritt 2:
   - Basis-RG und Egress-IP:

     ```bash
     az group show -n rg-eurocis-base -o none 2>/dev/null || \
       az group create -n rg-eurocis-base -l germanywestcentral \
         --tags purpose=eurocis2027 deleteAfter=2027-02-28
     az network public-ip show -g rg-eurocis-base -n pip-aks-egress \
       -o none 2>/dev/null || \
       az network public-ip create -g rg-eurocis-base -n pip-aks-egress \
         --sku Standard --allocation-method Static -l germanywestcentral
     az network public-ip show -g rg-eurocis-base -n pip-aks-egress \
       --query ipAddress -o tsv
     ```

   - Ingress-IP mit DNS-Label, erst nach Owner-Go. Der Owner wählt
     `<p>` bis 20.11.: neutral, ohne Kunden- oder Projektnamen, weil
     der Name mit dem ersten Zertifikat in den öffentlichen CT-Logs
     steht [A]; 3-63 Zeichen nach `^[a-z][a-z0-9-]{1,61}[a-z0-9]$`
     [Quelle: Recherche 17.11.; PSRule-Regel Azure.PublicIP.DNSLabel].
     Erst die Verfügbarkeit, dann anlegen und sperren:

     ```bash
     nslookup <p>.germanywestcentral.cloudapp.azure.com  # NXDOMAIN
     az rest --method get --url "/subscriptions/{subscriptionId}/\
     providers/Microsoft.Network/locations/germanywestcentral/\
     CheckDnsNameAvailability?domainNameLabel=<p>&api-version=2024-05-01" \
       --query available                   # true
     az network public-ip show -g rg-eurocis-base -n pip-aks-ingress \
       -o none 2>/dev/null || \
       az network public-ip create -g rg-eurocis-base -n pip-aks-ingress \
         --sku Standard --allocation-method Static -l germanywestcentral \
         --dns-name <p> \
         --tags purpose=eurocis2027 deleteAfter=2027-02-28
     az lock create -n lock-pip-aks-ingress --lock-type CanNotDelete \
       -g rg-eurocis-base --resource pip-aks-ingress \
       --resource-type Microsoft.Network/publicIPAddresses
     az network public-ip show -g rg-eurocis-base -n pip-aks-ingress \
       --query "{ip:ipAddress,fqdn:dnsSettings.fqdn}" -o tsv
     ```

     Gründe:
     - Ein Label gehört zu genau einer Public IP; Subdomains oder
       Wildcards darunter gibt es nicht [Quelle: learn.microsoft.com,
       Seite "public-ip-addresses"; Befehl `dig`, 17.11.]. Ein Name,
       eine Ingress-IP (AKS-E4).
     - Das Label hängt an der IP, nicht am Service. Ein Neuaufbau des
       Clusters behält Name und IP; erst das Löschen der IP gibt den
       Namen für jeden frei. Daher der Lock `CanNotDelete`, und der
       Traefik-Service nutzt `azure-pip-name`, nie
       `azure-dns-label-name` (ein leerer Wert löscht das Label)
       [Quelle: `learn.microsoft.com/azure/aks/static-ip`;
       `cloud-provider-azure.sigs.k8s.io/topics/loadbalancer`].
     - Ohne `--dns-name-scope`: Die Preview hängt einen Hash an den
       Namen [Quelle: learn public-ip-addresses, "Domain Name Label
       Scope"].
     - Der Endpunkt `CheckDnsNameAvailability` ist nur über die Recherche
       belegt [A]; maßgeblich sind NXDOMAIN und ein erfolgreicher
       Create, denn Azure lehnt ein vergebenes Label ab.
     - Beim Rückbau (P7 Schritt 8) zuerst den Lock entfernen.

     Kosten je IP rund 1 EUR bis 30.11. (0,0045 EUR/h). Keine DNS-Zone,
     kein Azure DNS, kein DNS-01 (AKS-E4).
6. Owner: Anfragen und Konten.
   - GEBIT (AKS-E16): Die schriftliche Freigabe liegt laut Owner seit
     17.11. vor. Der Owner bestätigt schriftlich bis 27.11., spätestens
     09.12. (vor `gebitsim` in P2 Schritt 7), dass sie auch das
     GEBIT-Descriptor-Set als K8s-Secret in Azure GWC abdeckt
     (Zugriff Owner und Stellvertretung aus AKS-E20, Löschung bis
     20.02.) [A: ja]. Ebenso, dass sie die öffentliche Reflection
     abdeckt; die gibt die GEBIT-Descriptor-Dateien selbst an jeden
     heraus, nicht nur die Dienstliste. Technisch ist Reflection
     entschieden: öffentlich und an (AKS-E16). Ohne Bestätigung kommt
     kein GEBIT-Material nach Azure.
   - LiteLLM-Betreiber in zwei Stufen: am 20.11. Gibt es eine
     Quell-IP-Allowlist, gilt sie auch für `/v1/*`, wie lange dauert
     eine Freischaltung, kommt ein Messe-Key (O5)? Dazu der
     Missbrauchsschutz (AKS-E11): `rpm_limit` und `tpm_limit` auf dem
     Messe-Key, neben `max_budget` 150 USD [Quelle:
     `docs.litellm.ai/docs/proxy/users`]; Werte nach der Lab-Messung
     in P5 [A]. Den Key setzt der Betreiber; sein Wert landet nur in
     SAMs Modellkonfiguration. Hinweis: Das Lab erreicht den Proxy
     heute ohne Firmen-VPN, eine Allowlist ist daher unwahrscheinlich
     [Quelle: RA:90; Befehl `scutil --nc list`, 16.11.] [A].
     Spätestens am 25.11. die Egress-IP aus Schritt 5, falls die
     Antwort "Allowlist ja" lautet oder noch fehlt.
   - ACME-Rückfall (AKS-E4): Der Owner legt bis 04.12. ein Konto bei
     einem ACME-CA mit External Account Binding an (ZeroSSL oder
     Google Trust Services). Die EAB-Daten kommen nur in den Key Vault
     (P1 Schritt 3, ab 30.11.) und nach `sli/aks/.env.aks`
     (gitignored, Schritt 10), nie in Git oder ein Dokument.
7. Erledigt am 17.11. (AKS-E15 (a)): Der offene amd-Working-Tree ist
   als Commit cd08a17 im Repo. Darin stecken SeaweedFS 2 CPU/2Gi,
   beide HIL-Flags, Sonnet-5-Planning, `scripts/models/set-pricing.sh`
   und `notify:_:send` für power_user [Quelle: Befehl
   `git show --stat cd08a17`, 17.11.]. Damit installiert AKS aus einem
   sauberen Checkout nicht mehr den SeaweedFS-Default, der am 16.11.
   hing. cd08a17 ist zugleich die Baseline für Schritt 13.
8. Mac-Tools, vom Owner am 17.11. freigegeben (AKS-E15 (e), AKS-E13);
   Claude installiert vor P1:

   ```bash
   brew uninstall --formula azure-cli   # verwaiste Formel 2.85.0
   brew install --cask azure-cli        # 2.93.0 oder neuer; ~/.azure bleibt
   az version                           # azure-cli >= 2.93.0
   brew install Azure/kubelogin/kubelogin
   ```

   Die Mac-CLI ist 2.85.0 vom 07.04.2026, aktuell ist 2.93.0 vom
   15.11.2026 [Quelle: Befehl `az version`;
   `api.github.com/repos/Azure/azure-cli/releases`, 16.11.].
   homebrew-core hat `azure-cli` nach `homebrew/cask` verschoben
   (`brew info --formula azure-cli`: "No available formula";
   tap_migrations.json); `brew upgrade azure-cli` und `az upgrade`
   migrieren eine verwaiste Formel nicht. Nach dem Wechsel die zitierten
   Hilfetexte (`az aks maintenanceconfiguration add --help`,
   `az aks get-credentials --help`, `az aks update --help`) erneut
   prüfen. Für kubelogin die Tap-Formel, nicht die Core-Formel
   `kubelogin` (int128/OIDC) und nicht `az aks install-cli` (legt ein
   zweites kubectl nach `/usr/local/bin`) [Quelle: Befehl
   `brew info kubelogin`; `az aks install-cli --help`]. Später kommt
   `cmctl` dazu (P2).
9. Owner und Claude, vor jeder gpd-Änderung: Baseline festhalten. gpd
   ist seit 17.11.2026 im sda-Repo versioniert (Commit 7a860c5;
   GEBIT-Zustimmung, O8 entfällt [Quelle: PLAN 0.5]); Baseline =
   sda-Commit vor dem Umbau; kein eigenes `git init`.
   - Die gpd-`.gitignore` hält `.env`, `.venv`, `build/`,
     `mesh/.rendered/` und `postgres/.generated/` heraus.
   - Baseline-Commit erst nach grünem `scripts/check_hygiene.sh`,
     `make test`, `make smoke` (Kasse 99) und S1-e2e ("proposed 100001
     7,99").
   - Referenzen außerhalb von Git, lokal, chmod 600, in kein Backup:
     `kubectl kustomize k8s > ~/gpd-baseline/k8s-lab.yaml` (lokal, ohne
     Cluster; das "heute" für P6 Schritt 2), der
     gerenderte Mesh-Stand und Kopien von `build/gate-verified`,
     `build/lab-ca.crt` und `mesh/.rendered/` (gitignored, ein
     Git-Rollback stellt sie nicht her).
   - Je Umbau-Schritt ein Commit mit Lab-Gate (Schritt 11 in drei
     Commits, P6 Schritte 2, 3 und 5, jeder Punkt aus 5.4).
   - Rückweg bei rotem Gate: `git revert` bzw. `git checkout
     <baseline> -- <pfade>`, Zustandsdateien zurückkopieren, wurde ein
     neuer Render schon im Lab angewendet, `install.sh k8s` aus dem
     wiederhergestellten Baum, nie `--prune`, dann das Gate erneut. Der
     Rückweg wird einmal in KW48 geprobt.
10. Claude: zuerst die Ignore-Regeln, bevor irgendeine `.env.aks`
    existiert (EAB-Daten ab P0 Schritt 6, Client-Secret ab P3,
    LiteLLM-Key ab P5); der Owner committet direkt auf master. Heute
    ignoriert die amd-`.gitignore` nur `.env`, die sli-`.gitignore`
    gar keine Env-Datei, und die gpd-Regel `.env.*` schluckt auch die
    geplante Vorlage `.env.aks.example` [Quelle: Befehl `git
    check-ignore -v`, 17.11.; sli .gitignore; gpd .gitignore:6-8]:
    - amd-`.gitignore` um `.env.aks` ergänzen;
    - neue `sli/aks/.gitignore` (AKS-E15 (c)) mit `.env.aks`, `*.pem`,
      `*.key` und `*.json` samt Ausnahme `!maint-*.json`; die
      sli-seitige Env-Datei heißt `sli/aks/.env.aks` (EAB-Daten,
      Directory-URL, `AKS_FQDN`);
    - gpd-`.gitignore` um `!.env.aks.example`.

    Dann das Sicherheitsgeländer in amd (Details in 5.2):
    `SAM_PROFILE=lab|aks` lädt `.env` bzw. `.env.aks`;
    `require_kube_context` prüft Kontextname und Server-URL des
    Clusters; `kaks`/`haks` für `aks`, `--context rancher-desktop` für
    `lab`; `SAM_HOME` je Profil und der Auth-Cache-Pfad unter
    `SAM_HOME`; `stop.sh` bricht auf `aks` ohne explizites
    `SAM_SEMP_URL` und `SAM_SEMP_PASSWORD` ab (Default 127.0.0.1:8080
    ist Lab-`solace-1` [Quelle: amd scripts/stop.sh:150-163]) und
    prüft vor dem ersten SEMP-DELETE die Broker-Identität wie
    `semp-aks.sh`: `localhost` und `127.0.0.1:8080` abgelehnt, erlaubt
    nur der selbst geöffnete Port-Forward-Port 18080, VPN
    `amartens-test` und DMR-Node `solace-1` müssen fehlen. Grund:
    `namespaceId` und damit das Queue-Präfix `sam-solace-lab` sind auf
    Lab und AKS gleich (P5 Schritt 3), eine `.env.aks` mit Lab-URL
    räumte sonst die Lab-Queues ab;
    `teardown-keycloak-client.sh` und `teardown-keycloak-users.sh`
    laden das Profil über `common.sh` und haben einen Identitäts-Guard;
    die Helm-Argumente baut eine Funktion `sam_helm_args <profil>`.
    Auf `aks` ist `SAM_URL` `https://<fqdn>`, und `KEYCLOAK_URL` endet
    auf `/auth`, weil die Keycloak-Skripte die URL als Präfix nehmen
    (P3).
11. Claude: dasselbe in gpd (Details in 5.4):
    - `TARGET=lab|aks`; ein Loader `opslib.env_file(target)` liest auf
      `aks` nur `.env.aks`, nie `.env` als Basis; `lib.sh` setzt
      `SAM_PROFILE="${TARGET:-lab}"` vor dem Sourcen von amd
      `common.sh` und bricht ab, wenn `SAM_PROFILE` schon anders
      gesetzt ist.
    - Ein gemeinsamer Fail-closed-Check (aus `lib.sh` und
      `demo_env`) bricht bei `TARGET=aks` ab, wenn ein Schlüssel aus
      `ENV_KEYS`, `PG_MODE` oder `BROKER_USERNAME`/`BROKER_PASSWORD`
      fehlt, `BROKER_CREDENTIALS_FROM` greifen würde oder eine URL-
      bzw. Host-Variable `solace.lab`, `host.docker.internal` oder einen
      Lab-Loopback-Port (`:8080`, `:8008`, `:55557`) enthält.
      `SAM_RUN_IDENTITY` ist davon ausgenommen.
    - `KUBE_CONTEXT`-Wrapper in `lib.sh` und `opslib.py` mit
      `KUBECONFIG=~/.kube/aks-eurocis.yaml` und `--context`.
    - Zustand je Ziel (`mesh/.rendered/<target>`,
      `build/<target>/gate-verified` mit Ziel-Feld) per Kopie, nicht per
      Umzug; der Lab-Pfad bleibt lesbar. Ohne Zustand je Ziel würde der
      Lab-PASS die AKS-Gate-Verifikation überspringen [Quelle: gpd
      scripts/opslib.py:150-174].
    - `broker.py` verweigert Schreibzugriffe, wenn bei `TARGET=aks` das
      Ziel VPN `amartens-test` oder DMR-Node `solace-1` hat (nur der
      Lab-Broker hat beides). Bei `TARGET=aks` gibt es keinen Rückfall
      auf die Lab-tfvars: Fehlen `SEMP_PASSWORD_FROM`,
      `SEMP_PASSWORD_KEY` oder `SEMP_URL`, zeigt `SEMP_PASSWORD_FROM`
      aufgelöst auf genau die Lab-Datei
      `../event-mesh-deployment/terraform/terraform.tfvars` (Vergleich
      der aufgelösten Pfade, nicht per Teilstring) oder ist `SEMP_URL`
      der Lab-Default (localhost/127.0.0.1:8080), endet der Aufruf mit
      `OpsError` vor jedem HTTP-Request [Quelle: gpd
      scripts/broker.py:16-18, 80-87].
    - Tests in `scripts/tests` für alle Abbruchfälle (Liste in 5.4).
12. Claude: sam-CLI-Spike read-only gegen das Lab plus leeres
    `SAM_HOME`. Schon beantwortet: `--url` ersetzt nur die URL; den
    OAuth-Token sucht die CLI unter `target.name` aus dem Manifest
    (überall `solace-lab`), und ein Login für einen anderen Ursprung
    wird abgelehnt [Quelle: Befehl `sam config plan -m manifest.yaml
    --url https://127.0.0.1:9 --sam-home <leer> --no-interactive
    --no-dotenv`, 16.11.]. Offen:
    - (a) Nutzen `config plan --url` und `sam api --manifest --url` nach
      `sam auth login solace-lab --url <aks>` in einem zweiten Home
      dessen Token, und lehnt die CLI eine abweichende gecachte URL ab?
      Kommt der Ursprungs-Check mit dem Token-Refresh zurecht?
    - (b) Sendet `config apply/plan --target <name>` einen Token? Der
      bekannte Fehler betrifft nur `sam api --target` [Quelle: gpd
      scripts/opslib.py:32-35].
    - (c) Feldname der URL im Cache und Ausgabe von `sam auth list`
      für den URL-Guard.
    - (d) Schlägt die Prozess-Umgebung das automatisch geladene `.env`?

    Gate: Der Lab-Cache bleibt unverändert.
13. Claude: Regressions-Gate im Lab, ohne Lab-Cluster und ohne echte
    Secrets, in drei Teilen.
    - (1) Call-Log-Gate: Eine Stub-Umgebung außerhalb des Repos legt
      `kubectl`, `helm`, `sam`, `curl` und `docker` als erste Einträge
      auf `PATH`. Jeder Stub schreibt sein argv in ein Log, maskiert
      Werte nach `*Secret*=`, `*ApiKey*=`, `*password*=` und `-u` als
      `***`, liefert feste Antworten (Ingress-ClusterIP, leere
      NodeHosts, HTTP 200, leere Queue-Liste) und berührt weder Cluster
      noch Broker. Dazu eine Dummy-`.env` mit festen Fake-Werten, `HOME`
      auf ein Temp-Verzeichnis, kein TTY (`</dev/null`).
      Baseline aus einem `git worktree` des Commits cd08a17 aus
      Schritt 7 (`git worktree add <tmp>/amd-before cd08a17`; liegt
      vor Schritt 10 ein späterer amd-Commit, dieser), neu aus dem
      geänderten Baum mit `SAM_PROFILE` leer und mit `SAM_PROFILE=lab`.
      Abgedeckt: alle Skripte aus 5.2 inkl. Keycloak-Setup und
      -Teardown. Vor dem Vergleich werden nur die geplanten Zusätze
      entfernt (`--context rancher-desktop`, `--kube-context
      rancher-desktop`, `--url https://sam.solace.lab`, `--no-dotenv`)
      und Worktree-Pfade auf `$PROJECT_DIR` abgebildet; getrennt wird
      geprüft, dass jeder kubectl- und helm-Aufruf diesen Kontext
      trägt. Bestanden: Diff leer; das angewendete Certificate ist
      byte-gleich zu `manifests/sam-tls-certificate.yaml`; der
      Keycloak-Writeback zielt auf `.env`; der Auth-Cache bleibt
      `solace-lab.json` im Default-Home; SEMP bleibt 127.0.0.1:8080.
      `sam_helm_args lab` ergibt dieselbe Liste wie start.sh:150-157,
      einzige erlaubte Abweichung `--kube-context rancher-desktop`.
    - (2) Render-Gate mit genau den protokollierten `--set`-Schlüsseln
      und Dummy-Werten. Ohne Issuer bricht Chart 2.3.10 ab
      ("sam.authorization.enabled is true but
      sam.oauthProvider.oidc.issuer is not set") [Quelle: Befehl
      `helm template` lokal, 16.11.]; echte `.env`-Werte würde der Chart
      base64-kodiert ins Secret schreiben (secret-core.yaml:37-39).

      ```bash
      set -euo pipefail
      S=$(mktemp -d)
      CHART=$(grep '^SAM_CHART_PATH=' .env | cut -d= -f2-)  # nur dieser Wert
      render() {
        helm template agent-mesh "$CHART" -n sam-solace-lab \
          -f local-k8s-values.yaml \
          --set sam.oauthProvider.oidc.issuer=https://dummy.invalid/realms/x \
          --set sam.oauthProvider.oidc.clientId=dummy \
          --set sam.oauthProvider.oidc.clientSecret=dummy \
          --set llmService.llmServiceApiKey=dummy
      }
      render > "$S/before.yaml"   # Stand cd08a17, vor Schritt 10
      render > "$S/after.yaml"    # nach Schritt 10
      diff "$S/before.yaml" "$S/after.yaml"
      git diff --exit-code cd08a17 -- local-k8s-values.yaml manifests/
      ```

      Läuft Schritt 10 schon, kommt die Baseline aus
      `git show cd08a17:agent-mesh-deployment/local-k8s-values.yaml`.
      `set -e` lässt einen gescheiterten Render abbrechen, statt zwei
      leere Dateien als gleich zu werten.
    - (3) Live und nicht-destruktiv im Lab: das neue `provision.sh`
      (idempotent), dann `make test`, `make smoke` und ein S1-e2e.
      `stop.sh` läuft nur in der Stub-Umgebung, nie live.
14. Owner und Claude: Lab-Broker-Upgrade einplanen (AKS-E8, AKS-E15
    (d)). Ziel für Lab und AKS ist PubSub+ Standard 10.26.0.9219 LTS
    (Tags `latest`/`lts`, Digest-Präfix `sha256:c0020e53ed48`), per
    Digest gepinnt; nicht 10.26.10 (Rolling, ohne Wartungsreleases,
    kein Rückweg auf 10.26.0.x) [Quelle: Docker-Hub-Tags-API, 17.11.;
    `solace.com/support/support-dates-for-release-versions`;
    `docs.solace.com` Upgrade-Selector]. Das Upgrade 10.25.0.208 auf
    10.26.0.9219 ist ein eigener Arbeitspunkt mit eigenem Owner-Go und
    Wartungsfenster; die Schritte stehen in P4. Es muss fertig und mit
    SAM- und GEBIT-Flows im Lab bewiesen sein, bevor P4 auf AKS
    beginnt. In P0 nur:
    - Sofort-Regel bis zur Anpassung der emd-Skripte (nicht nur bis
      zum Upgrade): Beide Broker-DBs liegen im Container-Layer (keine
      Mounts), und die Compose-Hashes von `solace-1` und `solace-2`
      weichen ab. Ein emd `start.sh` (kopiert `.env.example`, dann
      `docker compose up -d`) würde beide neu erzeugen und leeren,
      `stop.sh` löscht sie mit `docker compose down -v` [Quelle:
      Befehle `docker inspect`, `docker compose config --hash`, 17.11.;
      emd start.sh:4,6; stop.sh:2]. Auch nach dem Volume-Umzug
      scheitert der Zyklus `stop.sh`/`start.sh` am gelöschten
      Terraform-State (1.4). Also kein emd `start.sh` oder `stop.sh`,
      kein `docker compose up`, `pull` oder `down`, kein Prune; nur
      `docker start`/`docker stop` bzw. `docker compose stop`/`start`
      der bestehenden Container.
    - Claude, read-only: `docker compose up --dry-run` in emd bestätigt
      die Neuerzeugung [A: bisher nur per Hash-Vergleich].
    - Owner: Go und Wartungsfenster (SAM-Lab steht dabei) bis 27.11.
      festlegen, Termin spätestens KW49, damit der Lab-Nachweis vor dem
      11.12. steht. Risiko mittel bis hoch: Die Volume-Kopie der
      SolOS-DB ist ungeprobt, 36 Queues und die iCargo-User liegen
      außerhalb von Terraform.

**Wer:** Owner Schritte 1, 3, 4, 6 und die Freigaben bzw. Termine in
5, 9 und 14; Claude 2, 5, 8, 10-14; Schritt 7 ist erledigt. In KW47
tragen Owner und Claude P0 (Schritte 1-8); ab 23.11. übernimmt C die
Schritte 9-14 gemeinsam mit Claude.

**Abnahme:**

- `az version` zeigt 2.93.0 oder neuer; `az aks get-versions` listet
  1.36.x.
- Quota: Bis 27.11. zeigt `az vm list-usage` für Standard DPSv6 Family
  ein Limit von mindestens 16 vCPU, Total Regional mindestens 16, und
  `az network list-usages` Platz für 2 Standard Public IPs; keine
  SKU-Restriction für `Standard_D8ps_v6`.
- Alle Provider Registered. Unter den `atScope()`-Zuweisungen ist keine
  mit enforcementMode Default und Effekt Deny oder DenyAction auf
  `Microsoft.Network/publicIPAddresses`,
  `Microsoft.ContainerService/managedClusters`, die Region
  germanywestcentral, Pflicht-Tags oder die geplanten SKUs. Gibt es
  eine, steht eine Exemption oder ein Workaround als Entscheidung im
  PLAN.
- Die effektiven Aktionen des Owners decken
  `Microsoft.Authorization/roleAssignments/write` und
  `Microsoft.Authorization/locks/write` ab (auch über Gruppe oder
  Management Group); eine nur PIM-berechtigte Rolle ist vor P1
  aktiviert; die Rechte für das Budget sind geklärt (sonst je RG ein
  Budget).
- Defender-Pläne notiert (Containers, VirtualMachines inkl. subPlan,
  ContainerRegistry, KeyVault, Arm). Ist Containers oder
  VirtualMachines Standard, klärt der Owner Ausnahme oder
  Kostenübernahme mit dem Subscription-Owner (AKS-E1). Eine Ausnahme
  auf Ressourcenebene ist nicht zugesagt; Rückfall ist die eigene
  Subscription, sofern der Plan nicht von der Management Group erbt.
- AKS-E1 bis AKS-E20 schriftlich in PLAN 0.5 (oder neuem Abschnitt
  0.5a AKS), je mit dem Status aus Abschnitt 2 ("entschieden 17.11.",
  "[A] Bestätigung offen", "Owner-Bestätigung offen" für AKS-E18,
  AKS-E20 und die Seiten-Exposition in AKS-E5, "offen" für den
  Descriptor-Teil von AKS-E16). PLAN-E8 und der AKS-Teil von PLAN-E7
  (PLAN 0.2) verweisen auf AKS-E3 bis AKS-E8 (17.11.2026), O4 (PLAN
  0.5) auf
  AKS-E1/AKS-E2/AKS-E4, O6 (PLAN 0.5) auf AKS-E15. So gibt es je
  Entscheidung eine Quelle.
- `pip-aks-ingress` angelegt: `dnsSettings.fqdn` ist `<fqdn>`,
  `nslookup <fqdn>` liefert die IP der Ressource, `az lock list -g
  rg-eurocis-base` zeigt `lock-pip-aks-ingress` (CanNotDelete).
- `pip-aks-egress` angelegt; der Betreiber hat schriftlich bestätigt:
  keine Quell-IP- oder Key-IP-Einschränkung, oder die IP ist
  eingetragen (auch für den Messe-Key O5); die Anfrage zu
  `rpm_limit`/`tpm_limit` ist gestellt. Fehlt die Antwort am 27.11.:
  Eskalation, Eintrag im Risikoregister, der LiteLLM-Test am 03.12.
  gilt als gefährdet.
- `kubelogin --version` zeigt Azure-kubelogin; amd-Working-Tree sauber
  (Commit cd08a17).
- Ignore-Regeln vor der ersten `.env.aks`: `git check-ignore -q`
  gelingt für `sli/aks/.env.aks`,
  `agent-mesh-deployment/.env.aks` und
  `gebit-price-agent-demo/.env.aks`, nicht für
  `gebit-price-agent-demo/.env.aks.example` und
  `sli/aks/maint-default.json`.
- gpd: Baseline-Commit im sda-Repo benannt, Referenzen gesichert,
  Rückweg einmal geprobt.
- Lab: Call-Log-Diff leer (bis auf die Kontext-Zusätze), Render-Diff
  leer, `make test` grün, `make smoke` READY auf Kasse 99, ein S1-e2e
  liefert "proposed 100001 7,99".
- Negativtests, jeweils mit `set -x`-Log:
  - `SAM_PROFILE=aks scripts/stop.sh` bricht bei Kontext
    `rancher-desktop` ab, bevor ein kubectl-, helm-, SEMP- oder
    Keycloak-Aufruf läuft.
  - `SAM_PROFILE=aks scripts/stop.sh` mit
    `SAM_SEMP_URL=http://127.0.0.1:8080` bricht vor dem ersten
    SEMP-Request ab.
  - `SAM_PROFILE=aks scripts/teardown-keycloak-client.sh` und
    `...-users.sh` brechen vor dem ersten curl ab, wenn `.env.aks` kein
    `KEYCLOAK_URL` hat oder auf `auth.solace.lab` zeigt.
  - Ohne `KUBECONFIG` ist `kubectl config current-context` weiter
    `rancher-desktop`; `kaks get ns`, `haks list` und `setup-aks.sh`
    scheitern ohne AKS-Datei mit "context not found", statt das Lab zu
    treffen.
  - gpd: `TARGET=aks scripts/broker.sh r1-show` ohne
    SEMP-Passwortquelle (`SEMP_PASSWORD_FROM` fehlt) bricht ohne
    SEMP-Request ab; `TARGET=aks` mit `SAM_PROFILE=lab` bricht ab;
    `TARGET=aks scripts/uninstall.sh` mit einer `.env.aks` ohne
    `SAM_URL` bricht vor dem ersten `api()`- oder kubectl-Aufruf ab.
- Lint: Nach dem Zusammenfügen von Fortsetzungszeilen (z. B.
  `awk '/\\$/{sub(/\\$/,"");printf "%s ",$0;next}1'`) findet
  `grep -E '\b(kubectl|helm)\b'` über die AKS-Abschnitte dieses Plans,
  `sli/aks`, `emd/aks`, `emd/terraform-aks` und die AKS-Pfade in gpd
  `scripts/` und amd `scripts/` keinen Aufruf ohne `kaks`/`haks`,
  `KUBECONFIG=` bzw. `--kubeconfig` oder `require_kube_context`.
  `--context` allein reicht nicht, weil der Kontext ohne die Datei nicht
  existiert. Ausgenommen und aufgelistet: Kommentarzeilen, Lab-Befehle
  mit `--context rancher-desktop`, `helm template`/`helm lint` und die
  Lab-Messquellen in den Tabellen.
- sam-CLI-Spike mit Antworten auf (a) bis (d) dokumentiert.
- Lab-Broker: Owner-Go und Wartungsfenster terminiert (`solace-2` in
  KW48, `solace-1` bis 04.12., spätestens 10.12.);
  die Sofort-Regel aus Schritt 14 steht im Risikoregister (Abschnitt 7);
  das Ergebnis von `docker compose up --dry-run` ist notiert.

**Abhängigkeiten:** Owner-Login; Owner-Go und Label `<p>` für
`pip-aks-ingress`; O9 für C ab 23.11. AKS-E15 ist seit 17.11. erteilt.

### P1 Azure-Grundlagen, Cluster, ACR, CLI-Anbindung (2,0 PT, KW49)

**Ziel:** Cluster in Endform (ein Node, Free-Tier), per CLI nur von
freigegebenen IPs erreichbar, ohne die Default-kubeconfig zu berühren;
die Ingress-IP ist einmal öffentlich und aus dem Cluster heraus
(Hairpin) belegt. Prüfpunkt 04.12.: Ist die P1-Abnahme nicht grün,
wandert der AKS-Teil von G2a nach G2b (Mechanik aus PLAN 6.2)
und P5 nach KW1.

**Layout:** Drei Ressourcengruppen, damit ein Neuaufbau Ingress-IP mit
Label, Egress-IP (LiteLLM-Allowlist), ACR und Key Vault behält.

- `rg-eurocis-base`: VNet `10.20.0.0/16` (`snet-aks` /22), ACR, Key
  Vault, `pip-aks-ingress` (Label `<p>`, Lock), `pip-aks-egress`, UAMI
  `id-aks-cp`. Genau zwei öffentliche IPs im Projekt.
- `rg-eurocis-aks`: nur der Cluster.
- `rg-eurocis-nodes`: die Node-Ressourcengruppe mit festem Namen (VM,
  Disks, LB); sie verschwindet mit dem Cluster.
- Pod-CIDR 10.244.0.0/16, Service-CIDR 10.0.0.0/16: keine Überlappung
  mit Lab-k3s 10.42/10.43. Stand-LAN und Firmen-VPN spielen für den
  Adressplan keine Rolle, weil kein Netz gekoppelt wird.

**Schritte (Claude nach Freigabe):**

1. Basis prüfen: `rg-eurocis-base`, `pip-aks-egress` und
   `pip-aks-ingress` mit Label und Lock stammen aus P0 Schritt 5.
   Show-or-create wie dort, dann `nslookup <fqdn>` (liefert die IP von
   `pip-aks-ingress`) und `az lock list -g rg-eurocis-base -o table`.
2. Netz, Identität, Netzrechte:

   ```bash
   az network vnet create -g rg-eurocis-base -n vnet-eurocis \
     --address-prefixes 10.20.0.0/16 \
     --subnet-name snet-aks --subnet-prefixes 10.20.0.0/22
   az identity create -g rg-eurocis-base -n id-aks-cp
   CP_PID=$(az identity show -g rg-eurocis-base -n id-aks-cp \
     --query principalId -o tsv)
   BASE_ID=$(az group show -n rg-eurocis-base --query id -o tsv)
   az role assignment create --role "Network Contributor" \
     --assignee-object-id "$CP_PID" \
     --assignee-principal-type ServicePrincipal --scope "$BASE_ID"
   ```

   Network Contributor auf der ganzen `rg-eurocis-base`: Der
   Cloud-Provider verwaltet dort das BYO-Subnetz, die Outbound-IP und
   die Ingress-IP, die der Traefik-Service per `azure-pip-name` und
   `azure-load-balancer-resource-group` aus einer fremden RG bindet;
   dafür braucht die Control-Plane-Identität Rechte auf diese RG
   [Quelle: `learn.microsoft.com/azure/aks/static-ip`]. Die Rolle
   wirkt nur auf `Microsoft.Network/*`, ACR und Key Vault bleiben
   unberührt [A]. Die Rolle wird **vor** dem Create vergeben. Für eine
   frisch angelegte Identity kann der RBAC-Dienst die Zuweisung während
   der Replikation ablehnen (PrincipalNotFound);
   `--assignee-principal-type` vermeidet den Graph-Lookup [Quelle:
   `az role assignment create --help`, 2.85.0;
   `learn.microsoft.com/azure/role-based-access-control/role-assignments-cli`].
   Ein erneuter Lauf ist harmlos, weil die CLI eine bestehende Zuweisung
   als Erfolg wertet. `id-cert-manager` entfällt: HTTP-01 braucht weder
   Workload Identity noch DNS Zone Contributor (AKS-E4).
3. ACR, Testimages, Key Vault; Secrets generiert, nie ausgegeben:

   ```bash
   az acr create -g rg-eurocis-base -n <acr> --sku Basic --admin-enabled false
   az acr import -n <acr> --source docker.io/curlimages/curl:8.23.0 \
     --image curl:8.23.0                     # multi-arch inkl. arm64
   az acr import -n <acr> --source docker.io/traefik/whoami:v1.12.0 \
     --image whoami:v1.12.0                  # multi-arch inkl. arm64
   az keyvault create -g rg-eurocis-base -n <kv> \
     --enable-rbac-authorization true --retention-days 7 -o none
   KV_ID=$(az keyvault show -n <kv> -g rg-eurocis-base --query id -o tsv)
   OWNER_OID=$(az ad signed-in-user show --query id -o tsv)
   [ -n "$(az role assignment list --assignee-object-id "$OWNER_OID" \
       --scope "$KV_ID" --role "Key Vault Secrets Officer" -o tsv)" ] || \
     az role assignment create --role "Key Vault Secrets Officer" \
       --assignee-object-id "$OWNER_OID" --assignee-principal-type User \
       --scope "$KV_ID" -o none
   for i in $(seq 1 40); do         # Rolle greift nach einigen Minuten
     az keyvault secret list --vault-name <kv> -o none 2>/dev/null && break
     sleep 15
   done
   az keyvault secret list --vault-name <kv> -o none || \
     { echo "KV-Rolle greift nicht: az logout/az login" >&2; exit 1; }
   newsecret() {                    # nur anlegen, wenn er fehlt
     az keyvault secret show --vault-name <kv> -n "$1" -o none 2>/dev/null ||
       openssl rand -hex 24 | tr -d '\n' |
       az keyvault secret set --vault-name <kv> -n "$1" \
         --file /dev/stdin -o none
   }
   newsecret keycloak-admin
   ```

   `newsecret` gilt auch für: keycloak-db, Realm-User (je User),
   grafana-admin, grafana-ro, solace-admin, broker-sam, broker-gpos,
   sam-session, sam-pg-admin, gpos-postgres-admin, gpos-db-Rollen (je
   Rolle). Begründungen:
   - Im RBAC-Modus bekommt der Ersteller des Vaults kein Recht auf
     Secrets, auch nicht als Owner; nur Key Vault Secrets Officer oder
     Administrator, und die Zuweisung greift erst nach einigen Minuten
     [Quelle: `learn.microsoft.com/azure/key-vault/general/rbac-guide`].
     Secrets Officer deckt auch die späteren Lesezugriffe ab.
   - `-o none` ist Pflicht: `secret set` gibt den Wert sonst aus
     [Quelle: azure-cli 2.85.0 keyvault/_transformers.py:192-200].
     Nie `--value "$(...)"`, das legt den Wert in die argv.
   - `--file` übernimmt den Inhalt unverändert [Quelle: azure-cli 2.85.0
     keyvault/_validators.py:90-98], daher `tr -d '\n'`.
   - hex statt base64: `/`, `+` und `=` zerlegen die unkodierten
     `postgresql://`-DSNs der gpos-Pods; das Lab nutzt deshalb
     `openssl rand -hex 12` [Quelle: gpd scripts/install.sh:51, 136-138].
   - Nicht generiert, sondern vom Owner selbst eingetragen: die
     EAB-Kennung und der EAB-HMAC des ACME-Rückfall-CA (P0 Schritt 6),
     als `acme-eab-kid` und `acme-eab-hmac`, je per
     `pbpaste | tr -d '\n' | az keyvault secret set --vault-name <kv>
     -n <name> --file /dev/stdin -o none`; daneben nur in
     `sli/aks/.env.aks`.
     P2 baut daraus den Rückfall-ClusterIssuer.
   - `whoami` dient nur dem Hairpin-Test in Schritt 8 (Docker Hub
     v1.12.0 vom 29.07.2026, Index-Digest-Präfix
     `sha256:c4717a8d1f01`, amd64/arm64/arm) [Quelle:
     Docker-Hub-Tags-API, 17.11.].
   - `--retention-days 7` ist das Minimum und nur beim Anlegen setzbar;
     ohne Purge-Schutz, damit ein Purge beim Rückbau möglich bleibt.
   - Der LiteLLM-Key kommt nicht in den Key Vault.
4. Cluster:

   ```bash
   az group create -n rg-eurocis-aks -l germanywestcentral \
     --tags purpose=eurocis2027 deleteAfter=2027-02-28
   OWNER_IP=$(dig -4 +short myip.opendns.com @resolver1.opendns.com |
     grep -E '^[0-9.]+$')
   az aks create -g rg-eurocis-aks -n aks-eurocis -l germanywestcentral \
     --kubernetes-version 1.36.<patch> --tier free \
     --node-resource-group rg-eurocis-nodes \
     --nodepool-name main --node-vm-size Standard_D8ps_v6 --node-count 1 \
     --max-pods 110 --node-osdisk-size 128 \
     --network-plugin azure --network-plugin-mode overlay \
     --network-dataplane cilium --vnet-subnet-id <snet-aks-id> \
     --pod-cidr 10.244.0.0/16 --service-cidr 10.0.0.0/16 \
     --dns-service-ip 10.0.0.10 \
     --assign-identity <id-aks-cp-id> \
     --load-balancer-outbound-ips <pip-aks-egress-id> \
     --attach-acr <acr-id> \
     --enable-aad --enable-azure-rbac --disable-local-accounts \
     --api-server-authorized-ip-ranges "${OWNER_IP}/32" \
     --auto-upgrade-channel none --node-os-upgrade-channel SecurityPatch \
     --no-ssh-key --tags purpose=eurocis2027 deleteAfter=2027-02-28
   az aks nodepool update -g rg-eurocis-aks --cluster-name aks-eurocis \
     -n main --max-surge 1
   az group update -n rg-eurocis-nodes \
     --tags purpose=eurocis2027 deleteAfter=2027-02-28   # [A]
   az role assignment create \
     --role "Azure Kubernetes Service RBAC Cluster Admin" \
     --assignee-object-id <owner-objectId> --assignee-principal-type User \
     --scope <aks-id>
   ```

   - Ein Node, kein HA (AKS-E3, AKS-E14). Learn nennt für produktive
     System-Pools mindestens 2 Nodes, empfohlen 3; der AKS-Quickstart
     legt mit `--node-count 1` an [Quelle:
     `learn.microsoft.com/azure/aks/use-system-pools`;
     `learn.microsoft.com/azure/aks/learn/quick-kubernetes-deploy-cli`]
     [A: AKS nimmt den Ein-Node-System-Pool ohne Einschränkung an; der
     Create ist der Beweis]. Einen N-1-Fall und einen N-1-Drill gibt es
     nicht mehr. `--max-surge 1` heißt beim Node-Image-Upgrade ein
     zweiter Node auf Zeit, daher 16 vCPU Quota (P0 Schritt 4)
     [Quelle: `az aks nodepool update --help`, 2.85.0].
   - Free-Tier für das ganze Projekt, kein Wechsel auf Standard
     (AKS-E14).
   - `--api-server-authorized-ip-ranges` enthält beim Create nur die
     aktuelle Owner-IP. API-Server-IP und Outbound-IP des Standard-LB
     fügt AKS beim Create selbst hinzu; höchstens 200 Bereiche
     [Quelle: `learn.microsoft.com/azure/aks/api-server-authorized-ip-ranges`].
     Weitere IPs kommen nur über den Helfer aus Schritt 7. Der Owner
     kann AKS-E5 auf reines Entra ID mit Conditional Access umstellen;
     dann entfallen Liste und Helfer.
   - Ohne `--enable-oidc-issuer` und `--enable-workload-identity`:
     HTTP-01 braucht keine Workload Identity (Schritt 2); beides ist
     später per `az aks update` nachrüstbar.
   - `--node-resource-group` geht nur beim Create, die Gruppe darf
     vorher nicht existieren; ohne den Parameter hieße sie
     `MC_rg-eurocis-aks_aks-eurocis_germanywestcentral`.
     Entra-Integration ist nicht rückbaubar [Quelle:
     `learn.microsoft.com/azure/aks/enable-authentication-microsoft-entra-id`].
   - Break-glass von jedem Netz: `az aks command invoke` (läuft über
     die Azure-API, nicht über den API-Server-Endpunkt [Quelle:
     `learn.microsoft.com/azure/aks/access-private-cluster`]),
     `sli/aks/aks-allow-me.sh` (ebenfalls über ARM) oder
     `az aks update --enable-local-accounts`. Rollen für den
     Stellvertreter folgen bis G3 (P7 Schritt 7).
5. Wartung: drei JSON-Dateien (`default`,
   `aksManagedAutoUpgradeSchedule`, `aksManagedNodeOSUpgradeSchedule`),
   je mit zwei `notAllowedDates`-Bereichen: 2027-01-20 bis 2027-01-20
   (Mittwochsfenster der G3-Woche, nach dem 24-h-Lauf 18./19.01.) und
   2027-01-27 bis 2027-02-20 (Probetage, G4, Messe).
   `notAllowedTime` ist die veraltete Eigenschaft, und
   `az aks maintenanceconfiguration add` hat dafür kein Flag (nur
   `--config-file`) [Quelle:
   `learn.microsoft.com/azure/aks/planned-maintenance`;
   Befehl `az aks maintenanceconfiguration add --help`, CLI 2.85.0,
   nach dem CLI-Wechsel erneut prüfen].

   ```bash
   for n in default aksManagedAutoUpgradeSchedule \
            aksManagedNodeOSUpgradeSchedule; do
     az aks maintenanceconfiguration add -g rg-eurocis-aks \
       --cluster-name aks-eurocis -n $n --config-file maint-$n.json
   done
   ```

   Node-OS-Fenster: wöchentlich Mi 08:00-12:00, `utcOffset` +01:00; das
   letzte automatische Fenster ist damit Mi 13.01. Das `default`-Fenster
   liegt ebenfalls nicht auf Do/Fr in KW4 oder am 03.02. Der Cluster muss
   im Fenster laufen (nachts gestoppt passt). Warum so: Probetage am
   28.01., 29.01. und 03.02. [Quelle: PLAN 6.5, 7.3]. Ein SecurityPatch-Lauf
   setzt den Node nur bei Bedarf per Surge neu auf, sonst patcht er live
   [Quelle: `learn.microsoft.com/azure/aks/auto-upgrade-node-os-image`].
   Mit einem Node heißt jedes Neuaufsetzen einige Minuten Ausfall: Alle
   Pods ziehen auf den Surge-Node um, Broker, Keycloak und SAM starten
   neu [A: Dauer; P7 Schritt 5 misst sie]. Dass die LRS-PVCs am neuen
   Node anhängen, belegt vorab der PVC-Test in Schritt 8 (3.3).
   Deshalb bleiben die Sperren in der G3-Woche, um Probetage und Messe. Der
   manuelle Refresh liegt am Di 26.01. (P7 Schritt 5), einen Tag vor
   der Sperre; ob `notAllowedDates` manuelle Upgrades blockiert, ist
   nicht dokumentiert [A], spielt so aber keine Rolle. Der Node bleibt
   vom 26.01. bis 20.02. ungepatcht (rund 25 Tage), weit unter den drei
   Monaten, die AKS-E14 vermeiden will. Reaktive Wartung kann die
   Sperre trotzdem brechen (Abschnitt 7). Die JSON-Dateien gehören in
   die Neuaufbau-Skripte, weil die Konfigurationen mit dem Cluster
   verschwinden.
6. CLI anbinden, getrennt vom Lab, und die Wrapper festlegen:

   ```bash
   az aks get-credentials -g rg-eurocis-aks -n aks-eurocis \
     --file ~/.kube/aks-eurocis.yaml --context aks-eurocis
   kubelogin convert-kubeconfig -l azurecli \
     --kubeconfig ~/.kube/aks-eurocis.yaml
   AKS_KUBECONFIG="$HOME/.kube/aks-eurocis.yaml"
   kaks() { KUBECONFIG="$AKS_KUBECONFIG" kubectl --context aks-eurocis "$@"; }
   haks() { KUBECONFIG="$AKS_KUBECONFIG" helm --kube-context aks-eurocis "$@"; }
   kaks get nodes -o wide
   ```

   Ohne `--file` würde `az` in `~/.kube/config` mergen und den aktuellen
   Kontext auf AKS umstellen [Quelle: azure-cli acs/custom.py:1874-1880,
   2040]. Regeln:
   - `~/.kube/aks-eurocis.yaml` enthält nur den Kontext `aks-eurocis`.
     Ein Aufruf über die Wrapper erreicht das Lab also nie, auch wenn
     der Kontext-Parameter fehlt; ein Aufruf mit nur `--context
     aks-eurocis` ohne die Datei scheitert geschlossen.
   - `KUBECONFIG` wird in einer interaktiven Shell nie exportiert. Die
     Skripte laden `KUBECONFIG` und `SAM_KUBE_CONTEXT=aks-eurocis` aus
     `.env.aks` über den Profil-Loader in ihren eigenen Prozess.
   - Dieselben zwei Wrapper gibt es einmal je Repo, nicht per Sourcing
     über Repo-Grenzen: `sli/aks/lib.sh`, `emd/aks/lib.sh` (auch für
     `semp-aks.sh` und den Terraform-Port-Forward), amd
     `scripts/lib/common.sh` bei `SAM_PROFILE=aks`, gpd `lib.sh` und
     `opslib.py` bei `TARGET=aks` (dort per subprocess-Umgebung plus
     `--context`/`--kube-context`). In Skripten ruft der Wrapper vorher
     `require_kube_context aks-eurocis` auf, der auch die Server-URL
     des Clusters prüft.
7. API-Server-Zugriff: `sli/aks/aks-allow-me.sh` (AKS-E5; Arbeitsstand,
   solange der Owner nichts anderes vorgibt). `az aks update
   --api-server-authorized-ip-ranges` ersetzt die ganze Liste; eine
   nicht genannte IP fliegt raus, und die Änderung braucht bis zu
   2 min [Quelle:
   `learn.microsoft.com/azure/aks/api-server-authorized-ip-ranges`].
   Ein leerer Wert gibt den API-Server für alle frei [Quelle:
   `az aks update --help`, 2.85.0]. Der Helfer schreibt deshalb nie
   eine einzelne IP und nie eine leere Liste:
   - ohne Option: `powerState.code` muss `Running` sein [A: `az aks
     update` wird auf einem gestoppten Cluster abgelehnt]; die Liste
     lesen (`az aks show -g rg-eurocis-aks -n aks-eurocis --query
     apiServerAccessProfile.authorizedIpRanges -o tsv`), die aktuelle
     IPv4 per `dig -4 +short myip.opendns.com @resolver1.opendns.com`
     ermitteln und als /32 ergänzen, wenn sie fehlt; die vollständige,
     deduplizierte Liste mit `az aks update -g rg-eurocis-aks -n
     aks-eurocis --api-server-authorized-ip-ranges <liste>` schreiben;
     dann bis 2 min `kaks get --raw /readyz` (nach
     `require_kube_context aks-eurocis`).
   - `--print`: nur die aktuelle IPv4 ausgeben; `--check`: Exit 1, wenn
     sie in der Liste fehlt (für `aks-start.sh` und Preflight).
   - `--prune <ip>`: einen Eintrag entfernen, den der Helfer selbst
     hinzugefügt hat; bricht ab, wenn die Liste danach leer wäre.
     Einträge, die AKS selbst gesetzt hat, bleiben unberührt.
   - Register `~/.config/eurocis-aks/allowed-ips` (chmod 600; IP, Datum,
     Zweck wie "Büro", "5G", "Stand"); nie im Repo, nie in diesem
     Dokument.

   Der Owner ruft den Helfer selbst auf (sein `az login`), Claude nur
   nach Freigabe. Aufrufe: nach dem Create zur Kontrolle und nach jedem
   Netzwechsel (Stand, 5G, Hotel); `aks-start.sh` schreibt die Liste
   nie, sondern prüft nur mit `aks-allow-me.sh --check` und bricht mit
   Hinweis auf `aks-allow-me.sh` ab (so bleibt jeder Start, auch im
   Freeze und durch den Stellvertreter, ohne `az aks update`). Dass
   die API-Server-IP nach `az aks start` wechseln kann [Quelle:
   `learn.microsoft.com/azure/aks/start-stop-cluster`], spielt keine
   Rolle mehr, weil kubectl den FQDN auflöst. Offen für P7 und
   Abschnitt 7: Im Freeze ist der Helfer der einzige erlaubte
   `az aks update`, und er ändert nur die IP-Liste [A]; der
   Stellvertreter braucht dafür
   `Microsoft.ContainerService/managedClusters/write`, eventuell plus
   Join- und Assign-Rechte (Test vor G3, P7 Schritt 7), oder arbeitet
   über `az aks command invoke`.
8. Prüfungen und Wächter. `az aks check-acr` entfällt: Es startet
   `mcr.microsoft.com/aks/canipull:v0.1.0`, ein reines amd64-Image (auf
   Cobalt-Nodes "exec format error"), und holt eine temporäre
   Devicecode-kubeconfig, die nicht konvertiert wird [Quelle: azure-cli
   2.85.0 acs/_consts.py:226, acs/custom.py:1897-1906, 2150-2195; Befehl
   `curl https://mcr.microsoft.com/v2/aks/canipull/manifests/v0.1.0`,
   16.11.]. `check-acr` kommt nur bei einem amd64-Rückfall wieder in
   Frage.

   ```bash
   KUBELET=$(az aks show -g rg-eurocis-aks -n aks-eurocis \
     --query identityProfile.kubeletidentity.objectId -o tsv)
   az role assignment list --assignee-object-id "$KUBELET" \
     --scope "$(az acr show -n <acr> --query id -o tsv)" \
     --query "[].roleDefinitionName" -o tsv          # enthält AcrPull
   kaks -n default run acr-pull --restart=Never --image-pull-policy=Always \
     --image=<acr>.azurecr.io/curl:8.23.0 -- curl --version
   kaks -n default wait pod/acr-pull \
     --for=jsonpath='{.status.phase}'=Succeeded --timeout=120s
   kaks -n default delete pod acr-pull
   kaks -n default run egress --rm -i --restart=Never \
     --image=<acr>.azurecr.io/curl:8.23.0 -- curl -s ifconfig.me
   kaks -n default run llm --rm -i --restart=Never \
     --image=<acr>.azurecr.io/curl:8.23.0 -- \
     curl -s --max-time 15 -o /dev/null -w '%{http_code}' \
     <litellm-base>/v1/models
   ```

   Das curl-Image nimmt `curl` als erstes Argument an [A: Entrypoint
   von curlimages].

   Hairpin- und Ingress-IP-Test, bevor P2 Traefik installiert. SAM
   ruft sich über seine externe URL selbst auf (OAuth-Flow, Platform
   zu WebUI) [Quelle: amd scripts/start.sh:136-138], und der
   Back-Channel von SAM zu Keycloak geht an denselben Namen
   (`https://<fqdn>/auth/...`). Auf AKS löst `<fqdn>` auch im Cluster
   auf die öffentliche Ingress-IP auf; ob ein Pod sie erreicht
   (Hairpin mit `externalTrafficPolicy: Local` auf Overlay/Cilium), ist
   offen [A]. Ein Echo-Pod hinter einem befristeten LoadBalancer-Service
   auf `pip-aks-ingress` klärt das, Manifest
   `sli/aks/hairpin-test.yaml` (enthält keine IP):

   ```yaml
   apiVersion: v1
   kind: Service
   metadata:
     name: hairpin-test
     namespace: default
     annotations:
       service.beta.kubernetes.io/azure-pip-name: pip-aks-ingress
       service.beta.kubernetes.io/azure-load-balancer-resource-group: rg-eurocis-base
   spec:
     type: LoadBalancer
     externalTrafficPolicy: Local
     selector:
       app: echo
     ports:
       - name: http
         port: 80
         targetPort: 80
   ```

   ```bash
   kaks -n default run echo --labels app=echo --port 80 \
     --image=<acr>.azurecr.io/whoami:v1.12.0
   kaks apply -f sli/aks/hairpin-test.yaml
   kaks -n default get svc hairpin-test -w  # EXTERNAL-IP = pip-aks-ingress
   curl -s http://<fqdn>/                   # vom Mac: 200, RemoteAddr
   kaks -n default run hairpin --rm -i --restart=Never \
     --image=<acr>.azurecr.io/curl:8.23.0 -- \
     curl -s --max-time 10 -o /dev/null -w '%{http_code}' http://<fqdn>/
   # Handy-Hotspot (nicht in der Liste): curl wie oben 200,
   # kaks get nodes Timeout; dann aks-allow-me.sh, readyz ok,
   # danach aks-allow-me.sh --prune <hotspot-ip>
   kaks -n default delete svc hairpin-test
   kaks -n default delete pod echo
   az network public-ip show -g rg-eurocis-base -n pip-aks-ingress \
     --query "{c:ipConfiguration.id,f:dnsSettings.fqdn}" -o tsv
   ```

   Gründe und Rückfall:
   - Der Test belegt zugleich, dass der Lock das Binden nicht stört
     [A], dass `azure-pip-name` mit `azure-load-balancer-resource-group`
     die IP aus `rg-eurocis-base` nimmt, statt eine neue zu erzeugen,
     und dass `externalTrafficPolicy: Local` die echte Client-IP
     erhält (`RemoteAddr` in der whoami-Antwort ist die öffentliche
     Mac-IP), Voraussetzung für die Traefik-Rate-Limits je Client-IP
     (Komponente `public-guard`, P2) [Quelle:
     `learn.microsoft.com/azure/aks/configure-load-balancer-standard`].
     Die Annotation muss beim Anlegen da sein, sonst erzeugt AKS
     zuerst eine eigene IP [A].
   - Port 80 ist nur für die Testdauer offen; der Service verschwindet
     vor P2, weil die VAP dort LoadBalancer nur für den Service
     `traefik/traefik` zulässt.
   - Scheitert nur der Pod-Aufruf (Timeout) bei grünem Mac-Aufruf, ist
     der Rückfall gesetzt: P2 legt `kube-system/coredns-custom` mit
     einem `*.override`-Key und hosts-Block `<Traefik-ClusterIP>
     <fqdn>` plus `fallthrough` an und startet CoreDNS neu (`kaks -n
     kube-system rollout restart deploy coredns`) [Quelle:
     `learn.microsoft.com/azure/aks/coredns-custom`]. Zeitpunkt: nach
     der Traefik-Installation und vor dem ersten Certificate (P2
     Schritt 6), weil auch der HTTP-01-Selbsttest von cert-manager
     über den Hairpin läuft. Die ClusterIP
     liest das Skript aus dem Service, wie Lab `start.sh:139-147` es
     für NodeHosts tut. SNI und Host bleiben `<fqdn>`, das
     LE-Zertifikat passt also. P5 bestätigt das Ergebnis mit dem
     echten SAM-Selbstaufruf.

   PVC-Umzug (3.3): Ein Node-Image-Update hängt alle Disks an den
   Surge-Node. Der Test belegt das vor P4, mit einem zweiten Node für
   rund 1 h (rund 0,30 EUR, Quota aus P0 Schritt 4):

   ```bash
   az aks nodepool scale -g rg-eurocis-aks --cluster-name aks-eurocis \
     -n main --node-count 2
   # Test-Pod mit 1Gi-PVC (managed-csi) schreibt eine Datei; den
   # ersten Node mit kaks cordon sperren, Pod löschen und neu anlegen:
   # er startet auf dem zweiten Node, die Datei ist da
   kaks uncordon <node-1>
   az aks nodepool scale -g rg-eurocis-aks --cluster-name aks-eurocis \
     -n main --node-count 1
   ```

   Stop und Start:

   ```bash
   az aks stop -g rg-eurocis-aks -n aks-eurocis   # blockiert bis zum Ende
   az aks show -g rg-eurocis-aks -n aks-eurocis \
     --query "{p:powerState.code,s:provisioningState}" -o tsv
   # = Stopped / Succeeded, dann mindestens 30 min warten
   az aks start -g rg-eurocis-aks -n aks-eurocis  # Dauer ab hier notieren
   sli/aks/aks-allow-me.sh --check && kaks get --raw /readyz
   ```

   Microsoft verlangt nach einem Stop 15-30 min Pause vor dem Start
   [Quelle: `learn.microsoft.com/azure/aks/start-stop-cluster`, Caution
   unter "Start an AKS cluster"]. Dazu entstehen hier minimale Wrapper
   `sli/aks/aks-stop.sh` (schreibt die UTC-Zeit eines erfolgreichen
   Stops nach `~/.config/eurocis-aks/last-stop`) und
   `sli/aks/aks-start.sh` (verweigert den Start innerhalb von 30 min
   nach dem Stop und nennt die Restminuten, wartet nur mit `--wait`;
   prüft nach dem Start mit `aks-allow-me.sh --check` und bricht mit
   Hinweis auf `aks-allow-me.sh` ab); P5 Schritt 6 erweitert
   sie. Das Activity Log
   (`Microsoft.ContainerService/managedClusters/stop/action`) ist nur
   zweite Prüfung, weil Einträge spät kommen können [A].

   Kostenwächter:
   - Budget nach 3.4 (Betrag laut AKS-E1) im Portal oder per
     `az rest --method put` auf
     `/subscriptions/{subscriptionId}/providers/Microsoft.Consumption/budgets/eurocis-aks`
     mit `filter.dimensions` und `notifications`. Nicht
     `az consumption budget create`: Preview ohne
     Benachrichtigungs-Parameter.
   - Abend-Check auf dem Owner-Mac bis 05.02. (launchd, read-only):
     `az aks show -g rg-eurocis-aks -n aks-eurocis --query
     powerState.code -o tsv` meldet abends per Benachrichtigung, wenn der
     Cluster noch `Running` ist. Ein Activity-Log-Alarm bemerkt einen
     ausgebliebenen Stopp nicht.
   - Activity-Log-Alarm auf start/stop (nur Information),
     Resource-Health-Alarm (kostenlos).

**Wer:** Claude Schritte 1-8 nach Freigabe; Owner Entra-Login,
`aks-allow-me.sh` für die eigenen Netze, Hotspot-Test, EAB-Daten in
den Key Vault, Budget im Portal.

**Abnahme:**

- `az aks show`: Version 1.36.x, overlay/cilium, maxPods 110,
  `upgradeChannel none`, `nodeOSUpgradeChannel SecurityPatch`,
  `disableLocalAccounts true`, `nodeResourceGroup rg-eurocis-nodes`,
  `sku.tier Free`; `apiServerAccessProfile.authorizedIpRanges` enthält
  die Owner-IP und sonst nur Einträge, die AKS selbst gesetzt hat.
- 1 Node Ready, `kubernetes.io/arch=arm64`, mindestens 7,8 CPU und
  28,5 GiB (29184Mi) allocatable, gemessen mit
  `kaks get nodes -o custom-columns=N:.metadata.name,CPU:.status.allocatable.cpu,MEM:.status.allocatable.memory`.
  Die Messwerte ersetzen 7820m / 30418Mi in 3.2; die Request-Summe
  aus 3.2 (7125m / 21363Mi mit `prod1k`) liegt bei höchstens 92 % CPU
  und 75 % RAM. `maxSurge` des Pools ist 1.
- `kubectl config current-context` ohne `KUBECONFIG` ist weiter
  `rancher-desktop`; `~/.kube/config` enthält kein `aks-eurocis`.
- API-Zugriff: Von der Owner-IP ist `kaks get --raw /readyz` ok. Vom
  Handy-Hotspot (nicht in der Liste) läuft `kaks get nodes` in den
  Timeout; nach `aks-allow-me.sh` auf dem Hotspot ist `kaks get --raw
  /readyz` innerhalb von 2 min ok; `aks-allow-me.sh --prune
  <hotspot-ip>` stellt die vorherige Liste her (Vergleich vorher und
  nachher). `--prune` auf den letzten Eintrag bricht ab, ohne
  `az aks update` aufzurufen.
- Ingress-IP und Hairpin: `hairpin-test` bekommt die IP von
  `pip-aks-ingress`; `curl http://<fqdn>/` liefert vom Mac und vom
  Hotspot 200, `RemoteAddr` ist die öffentliche Client-IP. Aus einem
  Pod liefert derselbe Aufruf 200, oder das Ergebnis "Hairpin
  scheitert" ist dokumentiert und der `coredns-custom`-Rückfall für P2
  eingeplant. Nach dem Löschen des Tests ist `ipConfiguration` leer,
  Label und Lock sind da, `nslookup <fqdn>` liefert dieselbe IP, und
  kein Service im Cluster hat den Typ LoadBalancer
  (`kaks get svc -A | grep -c LoadBalancer` ergibt 0).
- `id-aks-cp` hat Network Contributor auf `rg-eurocis-base`
  (`az role assignment list --assignee-object-id "$CP_PID" --scope
  "$BASE_ID"`).
- PVC-Umzug: Die Datei ist nach dem Neustart auf dem zweiten Node da;
  danach hat der Pool wieder 1 Node, Test-Pod und PVC sind gelöscht.
- `az aks maintenanceconfiguration show` listet für alle drei
  Konfigurationen beide Sperrbereiche.
- Die Kubelet-Identity hat AcrPull auf der ACR; Pod `acr-pull` (arm64,
  Pull-Policy Always) erreicht `Succeeded` ohne ErrImagePull,
  ImagePullBackOff oder exec format error; der Egress-Pod meldet
  `pip-aks-egress`; LiteLLM antwortet aus dem Pod mit einem HTTP-Code
  (kein Timeout). Der HTTP-Code belegt nur TCP/TLS; den Nachweis der
  Freischaltung bringen die Betreiber-Bestätigung (P0) und P5.
- Key Vault: Owner hat Secrets Officer; für jedes generierte
  Passwort-Secret ist `az keyvault secret show --vault-name <kv> -n
  <name> --query value -o tsv | grep -qx '[0-9a-f]\{48\}'` erfolgreich,
  ohne Ausgabe. `acme-eab-kid` und `acme-eab-hmac` existieren bis
  04.12. (Abfrage nur mit `-o none`).
- Hygiene: `grep -rnE '([0-9]{1,3}\.){3}[0-9]{1,3}' sli/aks/` findet
  nur die Plan-Netze (10.20.0.0/16, 10.20.0.0/22, 10.244.0.0/16,
  10.0.0.0/16, 10.0.0.10), keine öffentliche IP; das IP-Register liegt
  nur unter `~/.config/eurocis-aks/`.
- Stop, mindestens 30 min Pause, Start fehlerfrei, Startdauer (ab
  `az aks start`) notiert; danach `aks-allow-me.sh --check` grün und
  `kaks get --raw /readyz` ok; `nslookup <fqdn>` liefert vor und nach
  dem Zyklus dieselbe IP.
- Budget mit Drei-RG-Filter aktiv; Abend-Check einmal ausgelöst.

**Abhängigkeiten:** P0; `pip-aks-ingress` mit Label aus P0 Schritt 5
(sonst blockiert nur der Hairpin-Test, nicht der Cluster); EAB-Daten
bis 04.12. (Prüfpunkt).

### P2 Plattform-Add-ons (3,0 PT, KW49-50)

**Ziel:** Traefik als einziger öffentlicher Eingang auf `<fqdn>`, ein
Let's-Encrypt-Zertifikat per HTTP-01, Guardrails per
ValidatingAdmissionPolicy und Monitoring in Lab-Versionen auf AKS;
keine CA-Hierarchie, kein trust-manager, kein Kyverno, keine Registry,
keine DNS-Zone, kein Workload Identity für cert-manager. Öffentlich ist
nur der Traefik-Service, alles andere bleibt ClusterIP (AKS-E5).
Prüfpunkt 11.12. zusammen mit P3.

`<fqdn>` steht hier und in P3 für
`<p>.germanywestcentral.cloudapp.azure.com`, das DNS-Label auf der
statischen IP `pip-aks-ingress` (AKS-E4, Owner 17.11.). Es gibt nur
diesen einen Namen, die Apps bekommen Pfade darauf. Bei gleichem Host
gewinnt in Traefik die längste Regel [Quelle: Traefik-Doku v3.7
"Rules and Priority", `doc.traefik.io`]. Zielbild nach P6, P2 legt nur
die Grundlage:

| Pfad auf `<fqdn>:443` | Ziel | Ingress, Phase |
|---|---|---|
| `/` (damit auch `/health` und `/.well-known/`) | SAM `gwe:webui` | SAM-Chart, P5 |
| `/auth/realms/solace-lab/`, `/auth/resources/` | Keycloak `:8080` | `iam/keycloak`, P3 |
| `/kasse`, `/monitor`, `/static/`, `/api/catalog`, `/api/cards`, `/api/scenarios`, `/api/pos/`, `/api/state`, `/api/proposals/`, `/api/demo/`, `/api/events`, später `/kunde` | `gpos-ui` (Kasse, Monitor, REST, SSE) | gpos-Overlay `aks`, P6; `/freigabe`, `/foto`, `/op`, `/etikett` erst nach Frage 23 |
| `/<purchase-svc-fqn>/`, `/de.showcase.wws.v1.service.MerchandiseService/`, `/de.showcase.loyalty.v1.service.LoyaltyService/` (GRPC) | `gpos-pos`, `gpos-wws`, `gpos-loyalty` | P6 |
| `/grpc.reflection.v1.ServerReflection/`, `/grpc.reflection.v1alpha.ServerReflection/` (GRPC) | gebündelte Reflection aus Image 0.1.4 | `gpos-grpc-reflection`, P6, nur nach der Bestätigung aus AKS-E16 |
| `/.well-known/acme-challenge/<token>` auf Port 80 | cert-manager-Solver, nur während einer Bestellung | P2 |
| keiner | Grafana, Prometheus, SEMP, Keycloak-Admin, Traefik-Dashboard; gRPC-Health nur clusterintern | Port-Forward |

[Quelle: gpd app/gposdemo/ui/bff.py:326-412; common/grpcutil.py:150-167;
SAM-Chart 2.3.10 templates/ingress.yaml:27-41]

**Schritte:**

1. Neuer Ordner `sli/aks/` (nur neue Dateien, Freigabe AKS-E15 (c)
   liegt seit 17.11. vor): `versions.env` mit den Pins (Traefik-Chart
   42.4.1, Image `traefik:v3.7.19` per Index-Digest, cert-manager
   v1.21.3, Monitoring-Charts wie im Lab) und `AKS_FQDN`; `lib.sh` mit
   `kaks`/`haks` und `require_kube_context`; je Komponente
   `values-aks.yaml`; `setup-aks.sh <teil>`, das `lib.sh` lädt,
   `require_kube_context aks-eurocis` aufruft und `AKS_FQDN` in die
   Manifeste rendert. Lab-`setup.sh` bleibt unverändert, das Lab
   behält ingress-nginx. Grundlage sind die Skizzen in
   `gpd/spikes/aks/`; deren DNS-01-Issuer und interne LB-Werte sind
   überholt. Vor jedem Arbeitsblock läuft `sli/aks/aks-allow-me.sh`
   (P1), sonst lehnt der API-Server die Mac-IP ab.
2. Vorbedingungen read-only prüfen (`CP_PID` wie in P1 Schritt 2):

   ```bash
   az network public-ip show -g rg-eurocis-base -n pip-aks-ingress \
     --query "{ip:ipAddress,fqdn:dnsSettings.fqdn,sku:sku.name}" -o tsv
   az lock list -g rg-eurocis-base --resource-name pip-aks-ingress \
     --resource-type Microsoft.Network/publicIPAddresses \
     --query "[].level" -o tsv                     # CanNotDelete
   az role assignment list --assignee-object-id "$CP_PID" \
     --scope "$(az group show -n rg-eurocis-base --query id -o tsv)" \
     --query "[].roleDefinitionName" -o tsv        # Network Contributor
   dig +short <fqdn>                               # = ipAddress
   ```

   Das Label hängt an der IP, nicht am Service. Kein Manifest setzt
   `azure-dns-label-name`, also löscht auch ein gelöschter Service das
   Label nicht; der Lock verhindert, dass eine gelöschte IP den Namen
   für jeden freigibt. Liegt die IP außerhalb der
   Node-Ressourcengruppe, braucht die Control-Plane-Identität Rechte
   auf deren RG [Quelle: `learn.microsoft.com/azure/aks/static-ip`;
   `cloud-provider-azure.sigs.k8s.io/topics/loadbalancer`].
3. PriorityClasses und Guardrails per `kaks apply -f`, vor Traefik,
   damit schon dessen Service die Regeln durchläuft:
   - `demo-critical` als `globalDefault` (der SAM-Chart kennt kein
     `priorityClassName` [Quelle: values.schema.json, SAM-Leser]),
     `demo-observability` niedriger, explizit in den Monitoring-Values.
   - ValidatingAdmissionPolicy (GA seit 1.30, kein Webhook, blockiert
     `az aks stop` nicht), ein Binding mit `validationActions: [Deny]`
     je Policy (AKS-E12):
     - Service: `type: LoadBalancer` nur für `traefik/traefik`, nur
       mit `azure-pip-name: pip-aks-ingress` und
       `azure-load-balancer-resource-group: rg-eurocis-base`, nie mit
       `azure-dns-label-name`; `externalIPs` nirgends. Das fängt den
       öffentlichen LB-Default des pubsubplus-Charts (P4), einen
       zweiten LB-Service im Namespace `traefik` (weitere LB-Regeln
       auf der öffentlichen IP) und einen Traefik-Service ohne
       RG-Annotation (dann legte der Cloud-Provider eine neue IP in
       der Node-RG an, und `<fqdn>` zeigte ins Leere, P1 Schritt 8).
     - Ingress: `ingressClassName: nginx`; jeder Host gleich
       `<fqdn>`; keine Annotation `*-snippet` oder `mirror-*`; keine
       Annotation `cert-manager.io/*` (genau ein Zertifikat, Schritt
       6); `spec.tls` ist Pflicht. Ausgenommen sind Solver-Ingresses
       mit Label `acme.cert-manager.io/http01-solver: "true"`; sie
       laufen ohne TLS und ohne Redirect auf Port 80 [Quelle:
       cert-manager pkg/apis/acme/v1/types.go;
       pkg/issuer/acme/http/pod.go und ingress.go].
     - Certificate: nur in `traefik`, `dnsNames` genau `[<fqdn>]`,
       `issuerRef` ein ClusterIssuer aus `letsencrypt-staging`,
       `letsencrypt-prod`, `acme-eab-fallback`.
     - IngressRoute und IngressRouteTCP: nur in `traefik` und nur auf
       Entrypoint `traefik` (Dashboard). Öffentliche Routen gibt es
       nur als NGINX-Ingress, damit dieselben Manifeste im Lab laufen.

   Ausschnitt LB-Regel (CEL, `request.namespace`, weil Manifeste ohne
   Namespace-Feld kommen können) [A: Ausdrücke per
   `kaks apply --dry-run=server` mit Negativ-Manifesten prüfen]:

   ```yaml
   validations:
     - expression: >-
         object.spec.type != 'LoadBalancer' ||
         (request.namespace == 'traefik' &&
          object.metadata.name == 'traefik' &&
          has(object.metadata.annotations) &&
          object.metadata.annotations[?
            'service.beta.kubernetes.io/azure-pip-name']
            == optional.of('pip-aks-ingress') &&
          object.metadata.annotations[?
            'service.beta.kubernetes.io/azure-load-balancer-resource-group']
            == optional.of('rg-eurocis-base') &&
          !('service.beta.kubernetes.io/azure-dns-label-name' in
            object.metadata.annotations))
       message: "LoadBalancer nur traefik/traefik mit pip-aks-ingress"
   ```

4. Docker-Hub-Images per `az acr import` mit festen Tags in ACR
   spiegeln, bevor ein Chart sie zieht. Die Liste kommt aus
   `helm template` mit Lab- und aks-Values (alle Images mit Registry
   docker.io); heute: `traefik:v3.7.19` (Index-Digest
   `sha256:aa942a00bce0...`, enthält linux/arm64 [Quelle: Docker Hub
   Tags-API 17.11.]), `grafana/grafana:12.4.3`, `grafana/loki:3.6.7`,
   `grafana/tempo:2.10.1`, `grafana/alloy:v1.18.0`,
   `kiwigrid/k8s-sidecar:2.5.0` (Loki-Rules-Sidecar; alternativ
   `sidecar.rules.enabled: false`). Für die Tests in Schritt 7:
   `python:3.13-alpine` und ein gRPC-Testserver mit Reflection ohne
   GEBIT-Material [A: Tag und arm64 beim Import festlegen]. Später
   `postgres` (P3, P6) und `solace` (P4); `curl:8.23.0` und
   `whoami:v1.12.0` liegen seit P1 dort. Für `gebitsim` (G0-11b (3),
   Schritt 7) kommt das gpos-demo-Image 0.1.3 (arm64) schon hier per
   `docker buildx imagetools create` aus `registry.solace.lab` nach
   ACR, wie in P6 Schritt 5. Es enthält grpcio mit Reflection und
   Health [Quelle: gpd app/requirements.txt:2-4] und kein
   GEBIT-Material (Prüfung wie in der P6-Abnahme); den Spike-Code
   `spikes/grpc-spike/gebitsim` bekommt der Pod als ConfigMap, das
   GEBIT-Descriptor-Set nur als Secret in `p2-test` und nur nach der
   Bestätigung aus AKS-E16.
   `nginx-unprivileged` nur, falls das Loki-Gateway an ist. Grund: Alle
   Node-Pulls gehen über `pip-aks-egress`, anonyme Docker-Hub-Limits
   träfen sonst Drills. cert-manager kommt von quay.io (multi-arch).
5. Traefik v3 mit NGINX-Provider (AKS-E6), eine Replika, ein
   LoadBalancer-Service:

   ```bash
   haks upgrade --install traefik traefik \
     --repo https://traefik.github.io/charts --version 42.4.1 \
     -n traefik --create-namespace \
     -f sli/aks/traefik-values.yaml
   ```

   ```yaml
   # sli/aks/traefik-values.yaml (Auszug)
   image:
     registry: <acr>.azurecr.io
     repository: traefik
     tag: v3.7.19
     digest: <traefik-index-digest>   # sha256:aa942a00bce0...
   deployment:
     replicas: 1                      # kein HA (AKS-E3)
     tmpVolume:
       emptyDir:
         sizeLimit: 2Gi               # Request-Buffer (Lücke 7)
   global:
     checkNewVersion: false
     sendAnonymousUsage: false
   accessLog:
     enabled: true                    # Client-IP für public-guard
     format: json
     fields:
       headers:
         defaultMode: drop            # keine Header, kein Bearer
       queryParameters:
         defaultMode: drop            # SAM-Token steht in der Query
   ingressClass:
     enabled: false                   # keine Klasse "traefik"
   providers:
     kubernetesIngress:
       enabled: false
     kubernetesCRD:
       enabled: true                  # HSTS-Middleware, TLSStore
       defaultTLSResourcesNamespace: traefik
     kubernetesIngressNGINX:
       enabled: true
       ingressClass: nginx
       controllerClass: k8s.io/ingress-nginx
       allowSnippetAnnotations: false
       publishService:
         enabled: true
   ports:
     web:
       http:
         redirections:
           entryPoint: {}             # kein globaler Redirect (HTTP-01)
     websecure:
       transport:
         respondingTimeouts:
           readTimeout: 3600s         # Default 60 s kappt SSE und MCP
       http:
         middlewares:
           - traefik-hsts@kubernetescrd
   service:
     annotations:
       service.beta.kubernetes.io/azure-pip-name: pip-aks-ingress
       service.beta.kubernetes.io/azure-load-balancer-resource-group: rg-eurocis-base
       service.beta.kubernetes.io/azure-load-balancer-tcp-idle-timeout: "30"
     spec:
       type: LoadBalancer
       externalTrafficPolicy: Local   # echte Client-IP
   tlsStore:
     default:
       defaultCertificate:
         secretName: ingress-tls      # Schritt 6
   ingressRoute:
     dashboard:
       enabled: true                  # nur Entrypoint traefik, nicht im LB
   resources:
     requests: {cpu: 100m, memory: 256Mi, ephemeral-storage: 2Gi}
     limits: {memory: 512Mi}
   extraObjects:
     - apiVersion: networking.k8s.io/v1
       kind: IngressClass
       metadata:
         name: nginx
       spec:
         controller: k8s.io/ingress-nginx
     - apiVersion: traefik.io/v1alpha1
       kind: Middleware
       metadata:
         name: hsts
         namespace: traefik
       spec:
         headers:
           stsSeconds: 604800
           stsIncludeSubdomains: false
           stsPreload: false
   ```

   [Quelle: Traefik-Chart 42.4.1 values.yaml:130-134, 314-345,
   424-505, 1086, 1126, 1175-1198, 1329]. Pins: Chart 42.4.1 (App
   v3.7.19, kubeVersion ab 1.30), nie unter v3.7.18 (fünf GHSAs am
   12.11. behoben), kein v3.8.0-rc [Quelle: GitHub-API Releases und
   Security-Advisories, 17.11.]. Der Service öffnet nur 80 und 443
   (Ports `traefik` und `metrics` sind nicht exponiert, HTTP/3 aus):
   zwei LB-Regeln plus Outbound, also innerhalb der fünf im
   Grundpreis enthaltenen Regeln. Mit `externalTrafficPolicy: Local`
   probt Azure den `healthCheckNodePort` per HTTP; ein eigener
   Probe-Pfad entfällt [Quelle:
   `learn.microsoft.com/azure/aks/configure-load-balancer-standard`].
   `forwardedHeaders` bleibt leer: Traefik ersetzt `X-Forwarded-*` aus
   dem Internet, Keycloak (`KC_PROXY_HEADERS=xforwarded`) und die
   Rate-Limits sehen nur Traefiks Werte.

   Lücken aus der Prüfung vom 17.11. und ihre Schließung:
   1. EntryPoint-`readTimeout` 60 s bricht HTTP/1.1-SSE und SAMs
      MCP-Aufrufe (bis 900 s) ab: `websecure` auf 3600 s [Quelle:
      Traefik v3.7.19 entrypoints.md:128-130; Go net/http
      server.go].
   2. Azure-LB-Idle-Timeout ist 4 min: Annotation auf 30 min.
   3. Der Chart legt IngressClass `nginx` nicht an, das SAM-Install
      bräche ab: eigene Klasse `nginx` (Controller
      `k8s.io/ingress-nginx`) in `extraObjects`, `kubernetesIngress`
      aus, `kubernetesCRD` an [Quelle: SAM-Chart 2.3.10
      templates/_validations.tpl:185-189, 206; Traefik
      nginx-to-traefik.md:630-728].
   4. `proxy-body-size` greift unter Traefik nur mit
      `proxy-request-buffering: "on"`: an für SAM (P5) und die
      gpos-UI-Ingresses (P6), nie für `/api/events` und gRPC. HSTS
      kommt als Middleware am Entrypoint `websecure`, ohne
      `includeSubDomains` und ohne `preload`, weil die Elternzone
      Azure gehört; 7 Tage statt 1 Jahr, weil der Name nach dem
      Rückbau wieder frei wird [A].
   5. Kein Redirect auf Entrypoint-Ebene, sonst scheitert HTTP-01;
      `ssl-redirect` wirkt je Ingress mit `spec.tls` (308), der
      Solver-Ingress hat kein TLS und bekommt keinen Redirect [Quelle:
      Traefik middleware.go:47-61; translator.go:432-438].
   6. HTTP-01, GRPC und Default-Zertifikat sind erst hier testbar
      (Schritt 7). Traefik-Patches (v3.7.x per Digest) nach G4 nur als
      Freeze-Ausnahme mit Owner-Go [A].
   7. Mit Request-Buffering schreibt Traefik große Bodies nach `/tmp`,
      das der Chart als emptyDir einhängt [Quelle: Traefik-Chart
      42.4.1 values.yaml:119-121; Recherche 17.11.]. Überschreitet es
      sein `sizeLimit`, verdrängt das Kubelet den einzigen
      Traefik-Pod, und alle öffentlichen Pfade fallen aus; `limit-rps`
      begrenzt nur die Rate, nicht parallele Uploads. Deshalb
      `limit-connections` je Client-IP am SAM-Ingress (20 [A]),
      SAM-Body-Limit 10m statt 100m [A: realer Upload-Bedarf, P5
      Schritt 2], `sizeLimit` 2Gi (20 x 10m für SAM plus 4m-Bodies der
      gpos-UI, mit Reserve) und ein Request auf `ephemeral-storage`,
      damit der Scheduler den Platz einplant. Viele IPs zugleich können
      das emptyDir weiter füllen (Restrisiko, Abschnitt 7).
   8. Das Access-Log ist im Chart aus [Quelle: Traefik-Chart 42.4.1
      values.yaml:607-641], P6 braucht es als Beleg für echte
      Client-IPs. Header bleiben beim Default `drop`; Query-Parameter
      entfernt `queryParameters.defaultMode: drop` (ab v3.7.3) aus
      `RequestPath`, weil die SAM-WebUI ihr Access-Token als
      Query-Parameter an die SSE-Aufrufe hängt [Quelle: SAM-WebUI-Bundle
      und ingress-nginx-Log aus dem Lab, 17.11.]. Alloy schickt das Log
      nach Loki; dort liegen die Client-IPs der Messebesucher 7 Tage
      [A: Loki-Retention], der Export nach der Messe nimmt es nicht
      mit (P7 Schritt 8).

   Annotationen der umziehenden Ingresses unter Traefik:

   | Annotation | Unter Traefik | Folge im aks-Overlay |
   |---|---|---|
   | `ssl-redirect`, `backend-protocol` HTTP/GRPC | unterstützt (308, GRPC als h2c) | unverändert |
   | `proxy-read-timeout`/`-send-timeout` 900/3600 | unterstützt, gleiche Semantik | plus EntryPoint-`readTimeout` |
   | `proxy-buffering: "off"` | unterstützt, SSE sofort geflusht | gpos `/api/events` |
   | `limit-rps`, `limit-rpm`, `limit-connections` | unterstützt, je Client-IP, 429 statt 503 | SAM, `public-guard` (Schritt 8) |
   | `proxy-buffer-size`, `proxy-buffers-number` | ohne Wirkung (Header-Limit 1 MiB) | entfallen |
   | `proxy-body-size` | nur mit `proxy-request-buffering: "on"` | SAM, gpos-UI an; gRPC und SSE ohne Grenze |
   | `ssl-ciphers`, `ssl-protocols` | nicht unterstützt bzw. ignoriert | nur Lab-Grafana, zieht nicht um |
   | `mirror-*`, `*-snippet` | nicht ausgewertet bzw. Ingress verworfen | VAP lehnt ab; CVE-2026-116472 entfällt |
   | `cert-manager.io/cluster-issuer` | (cert-manager-Shim) | entfällt, VAP lehnt ab |

   [Quelle: Traefik v3.7.19 ingress-nginx.md:265-502;
   annotations.go:14-131; middleware.go:176-213; build.go:662-692].
   Das Lab läuft weiter auf ingress-nginx; dieselben NGINX-Ingresses
   funktionieren dort (Limits antworten dort mit 503). Alles nur für
   Traefik (IngressClass-Ressource, HSTS-Middleware, TLSStore,
   Entrypoint-Timeouts) liegt in `sli/aks/` und wird hier zum ersten
   Mal bewiesen. Dashboard nur per
   `kaks -n traefik port-forward deploy/traefik 18090:8080`, dann
   `http://127.0.0.1:18090/dashboard/`.
6. cert-manager, Issuer, ein Zertifikat (AKS-E4). Ist in P1 der
   Pod-Aufruf gescheitert (Hairpin), legt `setup-aks.sh` nach Schritt 5
   (Traefik-ClusterIP bekannt) und vor dem ersten Certificate
   `kube-system/coredns-custom` mit Key `*.override` und hosts-Block
   `<traefik-clusterip> <fqdn>` plus `fallthrough` an und startet
   CoreDNS neu [Quelle: `learn.microsoft.com/azure/aks/coredns-custom`].
   Der HTTP-01-Selbsttest von cert-manager ruft
   `http://<fqdn>/.well-known/acme-challenge/...` aus dem Cluster auf,
   läuft also über denselben Hairpin; ohne den Rückfall käme kein
   Certificate über den Selbsttest hinaus, auch nicht beim
   EAB-Rückfall.

   ```bash
   haks upgrade --install cert-manager cert-manager \
     --repo https://charts.jetstack.io --version v1.21.3 \
     -n cert-manager --create-namespace \
     -f sli/pki/manifests/01-cert-manager-values.yaml \
     -f sli/aks/cert-manager-values.yaml   # Requests nach 3.2
   sli/aks/setup-aks.sh tls   # ClusterIssuer, Certificate, EAB-Secret
   ```

   ```yaml
   # sli/aks/tls/ (Auszug, gerendert von setup-aks.sh)
   apiVersion: cert-manager.io/v1
   kind: ClusterIssuer
   metadata:
     name: letsencrypt-staging        # dito letsencrypt-prod
   spec:
     acme:
       # prod: https://acme-v02.api.letsencrypt.org/directory
       server: https://acme-staging-v02.api.letsencrypt.org/directory
       privateKeySecretRef:
         name: letsencrypt-staging-account
       solvers:
         - http01:
             ingress:
               ingressClassName: nginx
   ---
   apiVersion: cert-manager.io/v1
   kind: ClusterIssuer
   metadata:
     name: acme-eab-fallback
   spec:
     acme:
       server: ${EAB_ACME_SERVER}     # ZeroSSL oder GTS, aus .env.aks
       externalAccountBinding:
         keyID: ${EAB_KID}            # aus .env.aks, nie im Repo
         keySecretRef:
           name: acme-eab-hmac        # aus Key Vault angelegt
           key: secret
       privateKeySecretRef:
         name: acme-eab-fallback-account
       solvers:
         - http01:
             ingress:
               ingressClassName: nginx
   ---
   apiVersion: cert-manager.io/v1
   kind: Certificate
   metadata:
     name: ingress-tls
     namespace: traefik
   spec:
     secretName: ingress-tls          # TLSStore default (Schritt 5)
     dnsNames: [<fqdn>]
     issuerRef:
       kind: ClusterIssuer
       name: ${TLS_ISSUER}            # erst staging, dann prod
   ```

   Kein Kontakt-Mail-Feld, keine Workload Identity, keine
   `id-cert-manager`, keine Rolle "DNS Zone Contributor": DNS-01 ist
   für cloudapp-Namen unmöglich, die Zone gehört Azure. Der Solver
   läuft über die IngressClass `nginx`, also durch Traefik; die
   Solver-Annotation `whitelist-source-range: 0.0.0.0/0,::/0` erlaubt
   alles und wird von Traefik unterstützt [Quelle: cert-manager
   pkg/issuer/acme/http/ingress.go:158-191; Traefik v3.7.19
   ingress-nginx.md:265-420]. Die CAA-Kette (`azure.com`) beschränkt
   keine CA [Quelle: Befehl `dig +short CAA`, 17.11.].

   Ablauf und Schutz vor dem Let's-Encrypt-Risiko:
   - Risiko: `cloudapp.azure.com` steht nicht auf der Public Suffix
     List, alle Azure-Kunden teilen sich den Topf `azure.com` mit
     50 neuen Zertifikaten je 7 Tage; eine Ausstellung kann tagelang
     scheitern [Quelle: PSL-Datei 17.11.;
     `letsencrypt.org/docs/rate-limits`;
     `community.letsencrypt.org/t/217855`]. Das Risiko trägt die
     Erstausstellung. Spätere Bestellungen für dieselbe Namensmenge
     gelten als Erneuerung und sind von diesem Topf ausgenommen,
     zählen aber gegen 5 je Namensmenge und Woche (ohne Override).
   - Erst `TLS_ISSUER=letsencrypt-staging`; `openssl s_client
     -connect <fqdn>:443 -servername <fqdn>` zeigt einen Aussteller
     mit "(STAGING)". Dann sofort `letsencrypt-prod`, möglichst am
     ersten P2-Tag (03.12.).
   - Rückfall: `acme-eab-fallback` für eine ACME-CA mit External
     Account Binding (ZeroSSL oder Google Trust Services). Der Owner
     legt das Konto an (P0 Schritt 6) und trägt die EAB-Daten selbst
     als `acme-eab-kid` und `acme-eab-hmac` in den Key Vault (P1
     Schritt 3) sowie mit der Directory-URL in `sli/aks/.env.aks`
     ein;
     `setup-aks.sh` legt daraus das Secret `cert-manager/acme-eab-hmac`
     an, ohne einen Wert auszugeben [A: Directory-URL und Limits der
     gewählten CA beim Anlegen prüfen]. Der Issuer wird
     angelegt und registriert, aber nicht benutzt. Ist bis 07.12.,
     12:00 kein Prod-Zertifikat Ready (Events `rateLimited` oder
     abgelehnte Orders), stellt `TLS_ISSUER=acme-eab-fallback` um; das
     Zertifikat bleibt dann bis nach der Messe bei dieser CA. Zeigt
     `kaks get challenges -A` dagegen einen gescheiterten Selbsttest
     statt `rateLimited`, ist es der Hairpin, kein Fall für einen
     CA-Wechsel: erst `coredns-custom` wie oben.
   - Backup: Nach jeder Ausstellung sichert `sli/aks/tls-backup.sh`
     das Secret als volles JSON samt cert-manager-Annotationen (ohne
     Cluster-Felder) als `tls-traefik-ingress-tls` im Key Vault, per
     Pipe ohne Zwischendatei und mit `-o none` (AKS-E17; Verfahren wie
     P7 Schritt 2). Ein Neuaufbau
     spielt es vor dem Certificate ein; cert-manager übernimmt ein
     passendes Secret ohne neue Bestellung [A: Restore-Drill in P2,
     belegt durch keine neue CertificateRequest].
   - Erneuerung: cert-manager erneuert bei 2/3 der Laufzeit. Bei
     Ausstellung um den 03.-07.12. fiele das in die Sperre ab 27.01.;
     deshalb am 15.01. `cmctl renew -n traefik ingress-tls`, danach
     Backup erneut [A: 90 Tage Laufzeit, per `openssl x509 -enddate`
     prüfen]; Ablauf in P7 Schritt 6. `cmctl` (Homebrew) installiert
     Claude in P2 nach Owner-Go; AKS-E15 (e) nennt es nicht
     ausdrücklich. Ab P5 hat SAMs `/`-Router auf Port 80 einen 308;
     der Solver-Router ist länger und gewinnt, das belegt die
     Erneuerung am 15.01.
7. Tests in einem Namespace `p2-test`, alle Ingresses auf `<fqdn>`
   mit `spec.tls.hosts: [<fqdn>]` ohne `secretName`:
   - `p2-echo` (`/p2-echo/`, `<acr>.azurecr.io/whoami:v1.12.0`,
     `proxy-read-timeout: "900"`): vom Mac ohne `-k` 200; aus einem
     Pod (`<acr>.azurecr.io/curl:8.23.0`, System-Truststore) ebenso.
     Das wiederholt den Hairpin-Test aus P1 Schritt 8 mit Traefik und
     echtem Zertifikat; SAM ruft sich über `<fqdn>` selbst auf und
     spricht Keycloak über denselben Namen an [Quelle: amd
     scripts/start.sh:136-147]. Scheitert der Pod-Aufruf erst hier,
     kommt `coredns-custom` wie in Schritt 6 nachträglich dazu.
   - Client-IP: `X-Real-Ip` im whoami-Echo ist die öffentliche IP des
     Macs (`curl -s ifconfig.me`), nicht eine Node-IP.
   - 900-s-Hold über HTTP/1.1 (`curl --http1.1` mit whoami-Parameter
     `wait=890s` [A]) endet mit 200; das belegt Lücke 1.
   - `p2-sse` (`/p2-sse/`, Python-Skript per ConfigMap, Heartbeat alle
     15 s wie gpos [Quelle: gpd app/gposdemo/ui/feed.py:54];
     `proxy-buffering: "off"`, `proxy-read-timeout: "3600"`): 20 min
     ohne Abriss, je einmal mit `curl --http1.1 -N` und HTTP/2.
   - `p2-body` (`/p2-body/`, `proxy-request-buffering: "on"`,
     `proxy-body-size: "1m"`, `limit-connections: "5"`): POST mit
     2 MiB ergibt 413; ohne Request-Buffering 200 (belegt die Lücke);
     10 parallele, langsam gesendete POSTs (`curl --limit-rate 50k`)
     mit je 900 KiB von einer IP: 5 bekommen 429, der Traefik-Pod
     bleibt Running (Lücke 7).
   - `p2-guard` (`/p2-guard/`, `limit-rpm: "10"`,
     `limit-burst-multiplier: "1"`): 30 Aufrufe vom Mac in einer Minute
     liefern ab dem 11. Aufruf 429, ein Pod bekommt parallel 200. Ohne
     den Multiplikator gälte der Default 5, also ein Eimer von 50
     Aufrufen, und der Test bliebe grün ohne 429 [Quelle: Traefik
     v3.7.19 pkg/provider/kubernetes/ingress-nginx/middleware.go:353-358;
     kubernetes.go:64].
   - `p2-grpc`: G0-11b (3) verlangt `gebitsim` [Quelle: PLAN 7.1
     G0-11b]. Der Pod läuft mit dem gpos-demo-Image 0.1.3 und dem
     Spike-Code als ConfigMap (Schritt 4) hinter dem Pfad des
     Purchase-Service und den beiden Reflection-Pfaden,
     `backend-protocol: GRPC`. Das GEBIT-Descriptor-Set kommt dafür
     als Secret nach `p2-test`, nur mit der schriftlichen Bestätigung
     aus AKS-E16 (bis 09.12.). `grpcurl <fqdn>:443 list` und ein
     Aufruf grün; Pfade mit Punkten bestehen `strictValidatePathType`
     [Quelle: Traefik kubernetes.go:76; build.go:1196-1209];
     `grpc.health.v1.Health` ist von außen nicht erreichbar. Das deckt
     den gRPC-Teil (3) von G0-11b am 11.12. (AKS-E18,
     Owner-Bestätigung offen). Direkt danach löscht `setup-aks.sh` den
     Pod und das Secret und protokolliert Zeit und Befehlsausgabe wie
     P7 Schritt 8 (2) (AKS-E16). Ohne Bestätigung bis 09.12. läuft (3)
     nach Zustimmung des PLAN-Eigners mit dem Testserver ohne
     GEBIT-Material (eigener Showcase-Descriptor) als dokumentierte
     Abweichung von PLAN 7.1, sonst wandert (3) nach G2b.
   - `http://<fqdn>/p2-echo/` antwortet 308 auf https; HTTPS trägt
     `Strict-Transport-Security: max-age=604800` ohne
     `includeSubDomains`.
   - SAM-TLS-Variante (Owner-Vorgabe: in P2 per Test entscheiden):
     Variante A, App-Ingresses ohne `secretName`. Traefik markiert ein
     Ingress mit `spec.tls` ohne Secret als TLS und liefert das
     Default-Zertifikat [Quelle: Traefik build.go:366-367, 873-877];
     der SAM-Chart prüft ein Secret nur bei gesetztem `secretName`
     und nimmt https, sobald `ingress.tls` nicht leer ist [Quelle:
     SAM-Chart 2.3.10 templates/_validations.tpl:100-113;
     _config_helpers.tpl:34-50]. Sind die Echo-Tests oben grün und
     zeigt `helm template` mit den aks-Values ein SAM-Ingress mit
     leerem `secretName` und ohne `cert-manager.io/*`, gilt A.
     Variante B als Rückfall: `setup-aks.sh` kopiert vor
     `helm install` `traefik/ingress-tls` als `sam-tls` nach
     `sam-solace-lab` und nach der Erneuerung am 15.01. erneut.
   - Nach der P3-Abnahme: `kaks delete ns p2-test`; für Netz-Drills
     per `setup-aks.sh p2-test` wieder anlegbar, ab P6 ohne `p2-grpc`
     (keine Reflection-Pfade, sonst gäbe es zwei Ingresses mit
     denselben Regeln wie `gpos-grpc-reflection`).
8. `public-guard` (Missbrauchsschutz ohne Login und ohne UI-Änderung,
   Owner 17.11.): Die NGINX-Ingresses können keine Traefik-Middleware
   referenzieren, der Provider liest keine `traefik.*`-Annotationen
   [Quelle: Traefik v3.7.19 pkg/provider/kubernetes/ingress-nginx,
   Quelltextsuche 17.11.; kubernetes.go:106-112]. Deshalb
   setzt die Komponente NGINX-Limits, die Traefik je Ingress in
   RateLimit- bzw. InFlight-Middlewares je Client-IP übersetzt
   [Quelle: Traefik v3.7.19 middleware.go:346-367] und die auch
   ingress-nginx im Lab versteht (dort 503 statt 429). Festgelegt
   wird hier die Form, die Werte stehen in P6 Schritt 3:
   - je geschützter Route ein eigenes Ingress-Objekt, damit jede Route
     ihren eigenen Zähler hat: `gpos-ui-pos` (`/api/pos/`,
     `limit-rpm`), `gpos-ui-demo` (`/api/demo/`, einzige Route
     `/api/demo/reset`; `limit-rpm` mit
     `limit-burst-multiplier: "1"`), `gpos-ui-events` (`/api/events`,
     `limit-connections`, ohne jedes Buffering), dazu die drei
     gRPC-Service-Pfade (`limit-rpm`, P6 Schritt 8) und jede spätere
     BFF-Route, die SAM oder ein LLM anstößt (etwa der Foto-Upload),
     mit `limit-rpm` und `proxy-body-size`;
   - nur Annotationen, keine Traefik-CRDs, damit das Lab dieselbe
     Datei rendern und testen kann;
   - Quelle der Client-IP ist die Remote-Adresse, deshalb
     `externalTrafficPolicy: Local` (Schritt 5) und kein Vertrauen in
     `X-Forwarded-For` von außen.

   Die Komponente `gpd/k8s/components/public-guard` entsteht mit den
   Pfad-Ingresses in P6 (Schritte 2 und 3); P2 belegt nur die Mechanik
   mit `p2-guard` (Schritt 7). Alle Standgeräte teilen sich eine
   öffentliche IP [A: Werte in P6 und P7 kalibrieren]. Das bremst
   Fluten von einer IP, nicht verteilte Aufrufe; die Kostengrenze für
   LLM-Aufrufe sind `rpm_limit` und `tpm_limit` am Messe-Key, die der
   LiteLLM-Betreiber setzt (P0 Schritt 6, P5).
9. Monitoring: kube-prometheus-stack 83.5.0 (Release
   `kube-prometheus` wie im Lab), loki 6.55.0, tempo 2.0.0 (Repo
   grafana-community), alloy 1.11.0, je `haks ... -f <Lab-Values> -f
   <aks-Values>`. Overlay:
   - Registry je Image, nicht global: kube-prometheus-stack
     `grafana.image.registry: <acr>.azurecr.io` (kein
     `global.imageRegistry`, sonst würden quay.io- und
     registry.k8s.io-Images umgelenkt, die nicht gespiegelt sind); loki
     `loki.image.registry` und `sidecar.image.registry`; tempo
     `tempo.registry`; alloy nur `image.registry` (der config-reloader
     bleibt auf quay.io). Tags bleiben Chart-Default, die Charts sind
     gepinnt.
   - Grafana ohne Ingress und ohne Pfad auf `<fqdn>`; Zugriff per
     `kaks -n monitoring port-forward svc/kube-prometheus-grafana
     3000:80`; Admin aus Secret. Prometheus ebenso nur per
     Port-Forward.
   - `grafana.additionalDataSources` vollständig neu deklariert, weil
     Helm Listen bei mehreren `-f` ersetzt: Loki, Tempo (mit
     derivedFields, tracesToLogs, tracesToMetrics) und "SAM Platform DB"
     mit denselben uids wie im Lab. Deren Passwort ist
     `$__env{GRAFANA_RO_PASSWORD}`, gespeist über `grafana.envValueFrom`
     aus einem K8s-Secret `monitoring/grafana-ro`, das aus dem Key Vault
     angelegt wird (wie `solace-admin` in P4). Ein Render-Check
     vergleicht die uids mit den Lab-Values.
   - Prometheus `storageSpec` 16Gi premium (Retention 7d/5GB und 3600 s
     Startfenster bleiben), Requests auf Ist-Werte (Prometheus 2Gi,
     Tempo 1Gi, Grafana/Loki 512Mi, Alloy 384Mi),
     kubeEtcd/ControllerManager/Scheduler/Proxy aus, loki-canary aus,
     `priorityClassName demo-observability`. Tempo-Retention bleibt
     48 h.
   - Danach `sli/pki/manifests/05-monitoring.yaml` ohne
     Kyverno-ServiceMonitor. Kein Container Insights.
   - Traefik-Metriken: zweiter `haks upgrade` mit
     `metrics.prometheus.serviceMonitor.enabled: true`, damit
     429-Zahlen der `public-guard`-Routen in Grafana sichtbar sind
     [A: Label-Selektor der Lab-Prometheus-Values].
   - Ist Defender aktiv: Sensor-DaemonSet mit `kaks top pods -A`
     messen (3.3). Traefik-Ist-Werte ebenso, dann 3.2 nachtragen.

**Wer:** Claude Schritte 1-9 nach Freigabe je Schreibschritt; Owner
legt das Konto bei der Rückfall-CA an und trägt die EAB-Werte selbst
in Key Vault und `sli/aks/.env.aks` ein.

**Abnahme:**

- `kaks get certificate -A`: genau ein Certificate,
  `traefik/ingress-tls`, Ready mit `letsencrypt-prod` (oder nach der
  Regel in Schritt 6 mit `acme-eab-fallback`) nach grünem
  staging-Lauf; `tls-traefik-ingress-tls` liegt im Key Vault; der
  Restore-Drill erzeugt keine neue CertificateRequest.
- `acme-eab-fallback` ist Ready (Konto registriert), kein Certificate
  nutzt ihn; die EAB-Werte stehen in keiner Datei unter Git.
- Vom Mac ohne `-k`: `curl -sS https://<fqdn>/p2-echo/` liefert 200;
  aus einem Pod ebenso (Hairpin); `http://` liefert 308; HSTS ohne
  `includeSubDomains`; whoami zeigt die echte Client-IP.
- `kaks get svc -A`: genau ein Service vom Typ LoadBalancer,
  `traefik/traefik`, mit der IP von `pip-aks-ingress`;
  `az network lb rule list -g rg-eurocis-nodes --lb-name kubernetes`
  zeigt nur TCP 80 und 443; `nc -z -w 5 <fqdn>` auf 8080, 8443, 9000
  und 9100 läuft in den Timeout.
- Negativ-Manifeste werden per VAP abgelehnt: LoadBalancer in einem
  anderen Namespace, ein zweiter LoadBalancer-Service im Namespace
  `traefik`, der Traefik-Service ohne
  `azure-load-balancer-resource-group`, LoadBalancer mit
  `azure-dns-label-name`, Ingress
  mit `server-snippet`, mit `mirror-target`, mit
  `cert-manager.io/cluster-issuer`, mit fremdem Host, Certificate mit
  fremdem Issuer oder Namen, IngressRoute auf `websecure`. Der
  Solver-Ingress des staging-Laufs wurde zugelassen.
- `haks list -A`: Traefik 42.4.1 (App v3.7.19), cert-manager v1.21.3,
  Monitoring exakt in Lab-Versionen; das Traefik-Image läuft mit dem
  gepinnten Index-Digest.
- 900-s-Hold, SSE 20 min (HTTP/1.1 und HTTP/2), 413 mit
  Request-Buffering, 429 ab dem 11. Aufruf von einer IP bei 200 von
  einer anderen, 429 über `limit-connections` ohne Eviction
  (`kaks -n traefik get pod` zeigt restartCount 0, kein `Evicted`),
  `grpcurl list` und ein Aufruf durch Traefik grün; das
  GEBIT-Descriptor-Secret aus `p2-grpc` ist gelöscht und die Löschung
  protokolliert.
- Access-Log: In Loki zeigt das Traefik-Access-Log die öffentliche
  Client-IP des Macs (nicht eine Node-IP); eine Zählabfrage auf
  `[?&]token=` über alle Namespaces seit dem ersten SAM-Login ergibt
  0 (ab P5 wiederholt), ohne Treffer auszugeben.
- SAM-TLS-Variante A oder B entschieden und in `sli/aks/README.md`
  festgehalten.
- Prometheus-PVC Bound, nach Pod-Neustart sind Vortagesdaten da;
  Loki hat Logs aller Namespaces; Loki- und Tempo-Datasource grün.
- Keine Images von Docker Hub mehr, weder explizit noch implizit:
  `for n in traefik monitoring; do kaks -n $n get pods -o
  jsonpath='{..image}'; done | tr ' ' '\n' | sort -u | grep -vE
  '^(<acr>\.azurecr\.io|quay\.io|registry\.k8s\.io|mcr\.microsoft\.com)/'
  | wc -l` ergibt 0.
- Grafana, Prometheus und Traefik-Dashboard: kein Ingress, keine
  IngressRoute auf `websecure`, Zugriff nur per Port-Forward.
- `kaks get pdb -A`: keine PDB mit 0 erlaubten Unterbrechungen auf
  einem Einzel-Pod, sonst blockiert sie den Drain beim
  Node-Image-Update (3.3).
- CPU-Requests von System, Traefik, cert-manager, Monitoring und ggf.
  Defender gemessen und in 3.2 eingetragen; liegen sie über 2044m,
  installiert P4 den Broker als `dev` (Kriterium 3.2).

**Abhängigkeiten:** P1 (Cluster, `pip-aks-ingress` mit Label `<p>`
und Lock, Network Contributor auf `rg-eurocis-base`,
`aks-allow-me.sh`, Hairpin-Ergebnis aus P1 Schritt 8); EAB-Konto und
EAB-Daten des Owners bis 04.12. (P0 Schritt 6), sonst nur Let's
Encrypt mit dem Risiko aus Schritt 6; für `gebitsim` in Schritt 7 die
schriftliche GEBIT-Bestätigung bis 09.12. (AKS-E16).

### P3 Keycloak (1,25 PT, KW50)

**Ziel:** OIDC für SAM unter `https://<fqdn>/auth` mit Lab-Realm,
ohne Lab-Standardpasswörter; öffentlich nur die Realm- und
Ressourcenpfade, Admin-Oberfläche nur per Port-Forward (AKS-E10).

**Schritte:**

1. `az acr import` für `quay.io/keycloak/keycloak:26.8.2` und
   `postgres:17-alpine`, danach per Digest gepinnt. 26.8.2 ist das
   aktuelle Release vom 05.11.2026 [Quelle:
   `api.github.com/repos/keycloak/keycloak/releases`, 16.11.]; der
   Realm wird per Skript neu angelegt, es gibt also keine Migration.
   Das Lab bleibt auf 26.2 an der Wurzel von `auth.solace.lab`.
2. Overlay `sli/aks/keycloak/` (ein Pfad, wie in 5.1). Lab
   `keycloak/manifests` hat keine `kustomization.yaml` [Quelle: Befehl
   `ls sli/keycloak/manifests`, 16.11.]; die aks-kustomization listet
   deshalb `../../keycloak/manifests/01-namespace.yaml` bis
   `05-monitoring.yaml` einzeln als Ressourcen und hält ihre Patches
   daneben. Anwendung nur über das Skript:

   ```bash
   sli/aks/setup-aks.sh keycloak
   # intern: require_kube_context aks-eurocis, Secrets aus Key Vault
   # anlegen, dann
   # kubectl kustomize --load-restrictor LoadRestrictionsNone \
   #   sli/aks/keycloak | kaks apply -f -
   # und vor dem Readiness-Check von Keycloak auf postgres warten
   ```

   Env-Patch für den Container (Strategic Merge über `name`):

   ```yaml
   - name: KC_HOSTNAME
     value: https://<fqdn>/auth
   - name: KC_HTTP_RELATIVE_PATH
     value: /auth
   - name: KC_HTTP_MANAGEMENT_RELATIVE_PATH
     value: /                       # Probes bleiben /health/* auf 9000
   - name: KC_HOSTNAME_ADMIN        # nur falls der Test es verlangt [A]
     value: http://127.0.0.1:18081/auth
   ```

   - `KC_HOSTNAME` darf eine volle URL mit Pfad sein [Quelle:
     `www.keycloak.org/server/hostname`]. `KC_PROXY_HEADERS=xforwarded`
     und `KC_HTTP_ENABLED=true` bleiben wie im Lab [Quelle: sli
     keycloak/manifests/03-keycloak.yaml:184-189].
   - Beide Pfad-Optionen sind Build-Optionen. Das Lab startet mit
     `start --import-realm` ohne `--optimized` (03-keycloak.yaml:143-144),
     und dann baut Keycloak beim Start selbst [Quelle:
     `www.keycloak.org/server/configuration`, "Creating an optimized
     Keycloak build"]. Kein eigenes Image; der Start dauert länger [A:
     im ersten Start messen, die startupProbe erlaubt rund 215 s].
   - Ohne `KC_HTTP_MANAGEMENT_RELATIVE_PATH=/` erbte der Management-Port
     den Pfad, und die Probes lägen unter `/auth/health/*` [Quelle:
     Keycloak ManagementOptions.java:53-58]. So bleiben
     `/health/{ready,live,started}` auf Port 9000 unverändert
     (03-keycloak.yaml:205-224).
   - `KC_HOSTNAME_ADMIN`: Die Admin-Konsole ruft die Admin-API unter
     der Adresse aus `hostname-admin` auf, sonst unter `hostname`
     [Quelle: `www.keycloak.org/server/hostname`]; auf `<fqdn>` ist
     `/auth/admin/` nicht geroutet. P3 testet zuerst ohne die Option;
     leitet die Konsole über den Port-Forward auf `<fqdn>` um, kommt
     sie dazu.
   - Admin-Zugang: Das Lab setzt `KEYCLOAK_ADMIN` und
     `KEYCLOAK_ADMIN_PASSWORD` (03-keycloak.yaml:154-163); seit 26.0
     heißen sie `KC_BOOTSTRAP_ADMIN_USERNAME`/`_PASSWORD` [A: ob 26.8.2
     die alten Namen noch liest, im Start-Log prüfen; der Patch setzt
     beide aus dem Key-Vault-Secret `keycloak-admin`].

   Ingress (ersetzt `04-ingress.yaml` im Overlay):

   ```yaml
   apiVersion: networking.k8s.io/v1
   kind: Ingress
   metadata:
     name: keycloak
     namespace: iam
     annotations:
       nginx.ingress.kubernetes.io/ssl-redirect: "true"
       nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
   spec:
     ingressClassName: nginx
     tls:
       - hosts: [<fqdn>]            # ohne secretName (P2 Schritt 7)
     rules:
       - host: <fqdn>
         http:
           paths:
             - path: /auth/realms/solace-lab/
               pathType: Prefix
               backend:
                 service: {name: keycloak, port: {number: 8080}}
             - path: /auth/resources/
               pathType: Prefix
               backend:
                 service: {name: keycloak, port: {number: 8080}}
   ```

   - Gegenüber dem Lab entfallen `cert-manager.io/cluster-issuer` (ein
     Zertifikat, VAP) und `proxy-buffer-size`/`-buffers-number` (unter
     Traefik ohne Wirkung, Header-Limit 1 MiB) [Quelle: sli
     keycloak/manifests/04-ingress.yaml:17-25; Traefik
     middleware.go:182-237].
   - Nicht geroutet: `/auth/admin/`, `/auth/realms/master/` (laut
     Keycloak "Internal only" [Quelle:
     `www.keycloak.org/server/reverseproxy`]), die Startseite `/auth/`
     und `/.well-known/`. Letzteres gehört SAM (OAuth-Metadaten unter
     `/gw/dev`); die Keycloak-Discovery liegt unter dem Realm-Pfad.
     Diese Pfade fallen auf SAMs `/`: vor P5 404 von Traefik, ab P5
     die SPA mit 200 text/html. Ein Tippfehler in einer Regel fällt
     deshalb nicht als 404 auf; die Abnahme prüft Inhalte, nicht nur
     Statuscodes.
   - Cookies: Keycloak setzt seine Cookies mit Pfad unter
     `/auth/realms/solace-lab/`, keines auf `/`; die Namen
     überschneiden sich nicht mit SAMs `csrf_token` und
     `sam_oidc_state` [Quelle: Keycloak CookiePathResolver.java:17-23;
     A: 26.8.2 wie main].
   - Realm-Import ohne die 3 Inline-User [Quelle: sli
     keycloak/manifests/03-keycloak.yaml:29-114]. Weil der Realm ein
     einziger JSON-String in ConfigMap `keycloak-realm` ist
     (03-keycloak.yaml:21-29), ersetzt das Overlay den ganzen Schlüssel
     `solace-lab-realm.json`; diese Kopie kann vom Lab-Realm abdriften.
     Sie behält `bruteForceProtected: true`, `failureFactor: 5` und
     `registrationAllowed: false` (03-keycloak.yaml:35-47), denn die
     Realm-Pfade sind jetzt öffentlich. Neu kommt
     `"passwordPolicy": "length(16) and notUsername and notEmail"`
     dazu: Die Account-Konsole ist öffentlich, und Schritt 4 lässt die
     User ihre Passwörter selbst wechseln; das Lab-Realm hat keine
     Policy [Quelle: sli keycloak/manifests/03-keycloak.yaml:29-47].
   - Approver-Login (2.2, offen): `marktleitung@solace.lab` steht im
     öffentlichen Repo, der Realm erlaubt den Login per E-Mail
     (`loginWithEmailAllowed: true`), jeder kann den Approver also
     wiederholt sperren. P3 entscheidet mit dem Owner: in der
     AKS-Realm-Kopie ein nicht erratbarer Username für den Approver
     und `loginWithEmailAllowed: false`, E-Mail und
     `SAM_RUN_IDENTITY` bleiben [A: zuerst prüfen, dass SAM die
     Identität am E-Mail-Claim festmacht]; oder bewusst hinnehmen mit
     dem Runbook-Schritt "Sperre aufheben". Die übrigen Realm-User aus
     dem öffentlichen Repo trifft dasselbe.
   - Secrets aus Key Vault (`keycloak-admin`, `keycloak-db`, je
     Realm-User eines, P1 Schritt 3). Speicher 1Gi Request / 1,5Gi
     Limit.
   - Saubere Alternative mit eigener Freigabe (nicht von AKS-E15 (c)
     gedeckt, das nur neue Ordner umfasst): eine rein additive
     `sli/keycloak/manifests/kustomization.yaml` (Lab-`setup.sh` wendet
     die Dateien einzeln mit `-f` an), dann ohne
     `LoadRestrictionsNone`.
   - Abweichung vom Lab, vom Owner am 17.11. akzeptiert: Lab-Issuer
     `https://auth.solace.lab/realms/solace-lab`, AKS-Issuer
     `https://<fqdn>/auth/realms/solace-lab`. SAM und Keycloak teilen
     den Origin, SAMs Back-Channel zu Keycloak geht über `<fqdn>`
     (Hairpin, P1 und P2 Schritt 7).
3. Realm-Inhalt per Profil. Die Skripte hängen `/realms/...` und
   `/admin/realms/...` an ihre Basis-URL an [Quelle: amd
   scripts/setup-keycloak-client.sh:17, 39, 54;
   setup-keycloak-users.sh:17, 53, 68], deshalb tragen beide Basen
   den Pfad `/auth`. Öffentlich sind nur die Realm-Pfade; Token für
   `master` und Admin-API laufen über einen Port-Forward, den das
   Skript mit Kontext-Guard selbst öffnet
   (`kaks -n iam port-forward svc/keycloak 18081:8080` [A: Port frei]):

   ```bash
   # .env.aks (Auszug, ohne Secrets)
   KEYCLOAK_URL=https://<fqdn>/auth                 # öffentliche Basis
   KEYCLOAK_ADMIN_URL=http://127.0.0.1:18081/auth   # Port-Forward
   KEYCLOAK_ISSUER=https://<fqdn>/auth/realms/solace-lab
   SAM_DNS_NAME=<fqdn>
   ```

   ```bash
   SAM_PROFILE=aks amd/scripts/setup-keycloak-client.sh  # exakte URI
   SAM_PROFILE=aks amd/scripts/setup-keycloak-users.sh   # Passwörter aus KV
   TARGET=aks gpd/scripts/keycloak-marktleitung.sh       # aus spikes/g0
   ```

   - Client `solace-agent-mesh` auf `aks` mit `redirectUris` genau
     `["https://<fqdn>/api/v1/auth/callback"]` und `webOrigins`
     `["https://<fqdn>"]`. Das Lab behält `https://sam.solace.lab/*`
     [Quelle: amd scripts/setup-keycloak-client.sh:22, 124-125; SAM-Chart
     2.3.10 templates/_config_helpers.tpl:50]. Grund: Auf dem geteilten
     Origin deckte `/*` auch `/kasse` und `/monitor` ohne Login ab, ein
     Code könnte dorthin umgeleitet werden. `SAM_DNS_NAME` ist heute
     fest verdrahtet (Zeile 22) und kommt auf `aks` aus dem Profil
     (5.2). Bei bestehendem Client gleicht das Skript auf `aks` die
     Redirect-URIs ab; heute kehrt es ohne Abgleich zurück [Quelle:
     setup-keycloak-client.sh:96-104].
   - [A] Der CLI- und MCP-Login läuft über SAMs eigenen
     Autorisierungsserver unter `/gw/dev` und nutzt bei Keycloak
     denselben Callback; P5 prüft `sam auth login`. Ebenfalls in P5:
     der Logout-Redirect; verlangt Keycloak dafür eine eigene URI,
     kommt `post.logout.redirect.uris` genau `https://<fqdn>/` dazu.
   - Das Client-Secret wird in `.env.aks` bzw. Key Vault geschrieben,
     nicht in die Lab-`.env` [Quelle: amd
     scripts/setup-keycloak-client.sh:65-90]; `KEYCLOAK_ISSUER` wird in
     `.env.aks` von Hand gesetzt. Generierte Passwörter für Admin und
     Realm-User liegen nur im Key Vault (hex, P1 Schritt 3). Kein
     `curl -k` auf `aks` (öffentlich gilt das Prod-Zertifikat, der
     Port-Forward ist HTTP), kein Passwort gleich Username [Quelle: gpd
     spikes/g0/keycloak-marktleitung.sh:8-30].
4. Owner: erste Logins und Passwortwechsel im Browser über
   `https://<fqdn>/auth/realms/solace-lab/account/`.

**Wer:** Claude 1-3; Owner 4.

**Abnahme:**

- `https://<fqdn>/auth/realms/solace-lab/.well-known/openid-configuration`
  liefert 200 vom Mac (öffentlich) und aus einem Pod
  (Hairpin); `issuer` ist genau
  `https://<fqdn>/auth/realms/solace-lab`, alle Endpunkte liegen
  darunter.
- Die Login-Seite lädt ihre Dateien unter `/auth/resources/` mit 200.
- Kein Keycloak-Inhalt auf nicht gerouteten Pfaden:
  `curl -s https://<fqdn>/auth/realms/master/.well-known/openid-configuration
  | jq -e .issuer` scheitert, ebenso für `/auth/admin/master/console/`
  (vor P5 404, ab P5 SAM-SPA; P5 wiederholt den Test).
- Ein Autorisierungsaufruf mit `redirect_uri=https://<fqdn>/kasse`
  endet mit "Invalid parameter: redirect_uri"; mit dem Callback
  erscheint die Login-Seite. Keine Antwort setzt ein Cookie mit
  `Path=/`.
- Probes laufen auf `/health/*` an Port 9000, Pod Ready; der
  Start-Log zeigt den automatischen Build mit `/auth`.
- Admin-Login über den Port-Forward funktioniert
  (`http://127.0.0.1:18081/auth/admin/`; Token-Request mit dem
  Key-Vault-Passwort liefert HTTP 200); Login mit dem
  Lab-Admin-Passwort scheitert; festgehalten, ob
  `KC_HOSTNAME_ADMIN` nötig war.
- Client `solace-agent-mesh` mit genau einer Redirect-URI
  `https://<fqdn>/api/v1/auth/callback`; 7 Gruppen und 7 User inkl.
  `marktleitung`; Realm mit Brute-Force-Schutz, ohne
  Selbstregistrierung und mit `passwordPolicy` (ein Passwortwechsel
  auf 12 Zeichen wird abgelehnt); die Entscheidung zum Approver-Login
  ist festgehalten (nicht erratbarer Username mit
  `loginWithEmailAllowed: false` oder hingenommen mit Runbook-Schritt).
- Lab unverändert: Keycloak-Client und -User (Diff vorher/nachher
  leer); `kubectl --context rancher-desktop -n iam get deploy/keycloak
  sts/postgres -o jsonpath='{..image}'` vorher und nachher gleich
  (Keycloak 26.2), restartCount unverändert. Das Lab-Deployment nutzt
  Strategy Recreate (sli keycloak/manifests/03-keycloak.yaml:131-132):
  ein Apply gegen das Lab würde Keycloak sofort trennen.
- Negativtest: `sli/aks/setup-aks.sh keycloak` bricht im Kontext
  `rancher-desktop` vor jedem Apply ab.

**Abhängigkeiten:** P2 (Traefik, Prod-Zertifikat, IngressClass
`nginx`, VAP), Key-Vault-Secrets aus P1, Profil-Änderungen der
amd-Skripte (P0 Schritt 10, AKS-E15 (b), freigegeben 17.11.).

### P4 Broker (2,25 PT, Lab KW48-49, AKS KW51)

**Ziel:** Lab und AKS laufen auf derselben Broker-Version: Solace
PubSub+ Standard 10.26.0.9219 LTS (Tags `latest` und `lts`,
Index-Digest `sha256:c0020e53ed48...`), überall per Digest gepinnt
(AKS-E8, entschieden 17.11.). Zuerst wechselt das Lab (Teil A), und
SAM- und GEBIT-Flows sind dort belegt; erst danach folgt AKS (Teil B):
ein Broker ohne HA, nur im Cluster erreichbar, VPNs wie im Lab.

Warum 10.26.0.9219 und nicht 10.26.10: 10.26.0 ist die LTS-Linie mit
Wartungsreleases bis 23.06.2028. 10.26.10.14510 ist ein Rolling
Release (Tags `edge` und `rolling`) ohne Wartungsreleases, mit Support
nur bis zum nächsten LTS (Juni 2027), und von dort führt kein Weg
zurück auf 10.26.0.x [Quelle: Docker-Hub-Tags-API, 17.11.;
`solace.com/support/support-dates-for-release-versions`;
`docs.solace.com` Upgrade-Selector]. Die Demo braucht kein
10.26.x-Feature. Docker Hub zeigt nur den letzten Push von `latest`
(10.11.), nicht, seit wann der Tag auf 10.26.0 zeigt.

**Teil A: Lab-Broker von 10.25.0.208 auf 10.26.0.9219 (neues
Arbeitspaket, 1,0 PT [A])**

Ausgangslage: `solace-1` und `solace-2` haben keine Mounts; ihre
Datenbank (`/var/lib/solace`, rund 2,2 GB) liegt im beschreibbaren
Container-Layer [Quelle: Befehle `docker inspect`, `docker exec ... du`
read-only, 17.11.]. Die Compose-Hashes beider Broker weichen schon
heute von den Container-Labels ab: Ein `docker compose up -d` (emd
`start.sh:6`) würde beide neu erzeugen und damit leeren, `stop.sh`
(`docker compose down -v`) löscht sie [Quelle: Befehl `docker compose
config --hash` gegen die Labels, 17.11.; emd start.sh:4-6, stop.sh:2;
A: per `docker compose up --dry-run` bestätigen]. Jede Änderung an
`PUBSUB_IMG` erzeugt die Container ebenfalls neu, auch ein
`docker compose pull`, das `latest` lokal verschiebt.

Bis Schritt A6 gilt deshalb im Lab: nur `docker start` und
`docker stop` der bestehenden Broker-Container; kein emd-`start.sh`
oder -`stop.sh`, kein `docker compose up/pull/down`, kein
Container-Prune. Die Regel endet nicht mit A6: Auch mit externen
Volumes löscht `stop.sh` Terraform-State, Lock-Datei, tfvars und
`.env`, und das nächste `start.sh` läuft mit leerem State per
`terraform apply -auto-approve` gegen Broker, die alle Objekte schon
haben; die Creates scheitern, `set -e` bricht vor den DMR-PATCH-Aufrufen
ab, und der Lab-State ist verloren [Quelle: emd stop.sh:2-7;
start.sh:2, 20-21, 23-35]. Bis die emd-Skripte angepasst sind (A4,
eigene Freigabe), ist der Lab-Zyklus nur `docker compose stop`/`start`
bzw. `docker stop`/`start`.

Freigabe: AKS-E15 (d) deckt den Versions-Pin. Volume-Umzug und Upgrade
brauchen ein eigenes Owner-Go und ein Wartungsfenster. Das Fenster für
`solace-1` trifft alle Lab-Demos auf diesem Broker (SAM-Lab, db-jpa,
iCargo). Termin: Probe an `solace-2` in KW48, `solace-1` spätestens
am 04.12. (Prüfpunkt), damit G1 (11.12.) schon auf 10.26 läuft
[A: Fenster wählt der Owner].

1. **A1** Claude, read-only: Baseline beider Broker. `solace-2` (seit 03.11.
   gestoppt) dafür per `docker start` hochfahren, nicht neu erzeugen.
   - SEMPv2-GET-Export aller Objekte je VPN (`default`, `sam`,
     `amartens-test`) mit Queue-Nachrichtenzählern,
     Client-Usernames, ACL-Profilen und DMR-Links, über ein neues
     `emd/aks/semp-export.sh` (nur GET; dient auch dem Vergleich in
     Teil B).
   - Kopie von `terraform.tfstate` und `.terraform.lock.hcl`.
   - Je VPN `show current-config` als portabler Rückfall; ein
     Backup der Broker-Konfiguration ließe sich nur auf exakt
     derselben Version zurückspielen [Quelle:
     `docs.solace.com/Admin/Managing-Event-Broker-Configurations.htm`].
   - Außerhalb von Terraform liegen auf `solace-1` 36 Queues (u. a.
     `db-jpa-*`, `gpos-booth-r1`, SAM-Queues) sowie zwei
     Client-Usernames und ein ACL-Profil des iCargo-Showcase
     [Quelle: SEMPv2-GETs und tfstate read-only, 17.11.]. Nur der
     Volume-Weg erhält sie.
2. **A2** Owner-Go, Rückfallpunkt für `solace-2`:

   ```bash
   docker stop --time 1200 solace-2
   docker commit solace-2 lab/solace-2-pre1026:10.25.0.208  # 2-3 GB
   ```

3. **A3** Storage auf ein externes Volume, noch auf 10.25.0.208. Docker
   füllt ein leeres Volume beim ersten Mount mit dem Inhalt des
   Images [Quelle: `docs.docker.com/engine/storage/volumes`]:

   ```bash
   docker volume create solace-2-storage
   docker run -d --name solace-2-seed --hostname solace-2 \
     --shm-size 1g --ulimit core=-1 --ulimit nofile=2448:1048576 \
     -p 127.0.0.1:8090:8080 \
     -v solace-2-storage:/var/lib/solace \
     lab/solace-2-pre1026:10.25.0.208
   ```

   `shm_size` und `ulimits` wie im Compose-Dienst [Quelle: emd
   docker-compose.yaml:59-84]. Den SEMP-Export gegen A1 vergleichen,
   dann `docker stop --time 1200 solace-2-seed` und den Container
   löschen (das Volume bleibt).
4. **A4** emd-Änderungen (Freigabe AKS-E15 (d) plus Go aus A2):
   - `docker-compose.yaml`: je Broker ein Volume auf
     `/var/lib/solace` (`solace-1-storage`, `solace-2-storage`), beide
     `external: true`, damit `down -v` sie nie löscht. Fehlt ein
     Volume noch, bricht Compose ab, statt einen leeren Broker zu
     starten.
   - `.env.example`: `PUBSUB_IMG` mit Tag und Digest, weil
     `start.sh:4` die `.env` aus `.env.example` überschreibt. Die
     `.env` danach per `cp .env.example .env` nachziehen; Compose liest
     nur die `.env`.
   - `terraform/provider.tf`: Provider exakt `= 1.3.0`, weil
     `stop.sh` die Lock-Datei löscht und `~> 1.2` sonst 1.4.0 zöge
     [Quelle: emd stop.sh:2-6; terraform/provider.tf:7].
   - Optional, nur mit eigenem Owner-Go: `stop.sh` behält
     `terraform.tfstate`, `.terraform.lock.hcl` und `terraform.tfvars`;
     `start.sh` ruft vor `apply` `terraform plan -detailed-exitcode`
     auf und bricht bei geplanten Änderungen ab. Ohne diese Anpassung
     bleibt die Regel oben (nur `docker compose stop`/`start`). In
     beiden Fällen ziehen der emd-README, der Abschnitt "Start and
     Stop" der sda-`CLAUDE.md` und die Memory-Notiz "Lab cleanup
     safety" die geltende Lab-Regel nach, weil "`./stop.sh` tears down
     containers and cleans up generated files" sonst still seine
     Bedeutung ändert.

   ```bash
   D=sha256:c0020e53ed487ecffed6a15ef7ff1086ce969fd8b772cb06cfefc044eff5c0c8
   docker pull "solace/solace-pubsub-standard:10.26.0.9219@$D"
   # .env.example: PUBSUB_IMG=solace/solace-pubsub-standard:10.26.0.9219@<D>
   ```

5. **A5** Upgrade `solace-2`: `docker compose up -d --no-deps solace-2`.
   Compose erzeugt den Container auf dem befüllten Volume neu, der
   Broker hebt seine Datenbank beim Boot an. Config-Keys wirken nur
   beim ersten Boot ohne Datenbank, Skalierung und Spool bleiben also
   [Quelle: `docs.solace.com` Docker-Upgrade-Current-Release].
   Prüfen: SEMPv1 `show version` meldet 10.26.0.9219, der
   SEMP-Export gleicht A1 bis auf Versionsfelder.
6. **A6** `solace-1` im SAM-Lab-Wartungsfenster: A2, A3 und A5 für
   `solace-1` (Writable Layer 3,15 GB [Quelle: Befehl `docker ps -s`,
   17.11.], SEMP-Port 8080). Danach die beiden DMR-PATCH-Aufrufe aus
   emd `start.sh:23-35`, falls die Links down sind, und im Lab
   `terraform plan` ohne Änderungen. Das belegt auch Provider 1.3.0
   gegen 10.26.0.
7. **A7** Lab-Flows belegen, bevor Teil B beginnt:
   - SAM: gwe, awe und str auf VPN `sam` verbunden, Agents geladen,
     A2A-Queues, gdk-Leader, Eventmesh-Gateways und `notify_user`
     funktionieren.
   - gpd: `make test`, `make smoke` (Kasse 99), S1-e2e ("proposed
     100001 7,99"), `TARGET=lab scripts/broker.sh r1-show` liefert
     200.
   - Broker-Spans des OTel-Collectors kommen in Tempo an (der
     `solacereceiver` 0.149.0 kennt nur v1-Trace-Topics [Quelle:
     opentelemetry-collector-contrib v0.149.0
     receiver/solacereceiver/unmarshaller.go:62-119]).
   - SAM 2.542.1 nennt keine Broker-Version; sein eingebetteter
     Default ist 10.25.0.193 [Quelle: SAM-Chart 2.3.10
     values.yaml:717-727]. Das Lab ist damit der erste SAM-Lauf auf
     10.26, nicht AKS [A].
8. **A8** Rückfall und Aufräumen: Ein Downgrade ist nicht unterstützt
   [Quelle: `docs.solace.com` Upgrade-Selector]. Zurück heißt: den
   10.26-Container entfernen und aus dem Snapshot-Image ohne Volume
   neu erzeugen. Nie 10.25.x auf einem angehobenen Volume starten.
   Die Snapshot-Images nach rund einer Woche per `docker rmi`
   entfernen, nie per Prune.

Risiko mittel bis hoch: Die Volume-Kopie der SolOS-Datenbank
(Symlinks `adb`, `internalSpool`, `diags`; Eigentümer 1000001:0,
Modus 1777) ist ungeprobt, deshalb zuerst `solace-2`, das nicht Teil
der AKS-Story ist. Rückfall B (frische 10.26-Container auf neuen
Volumes plus `terraform apply`) ist einfacher, verliert aber alles
außerhalb von Terraform (A1) und alle gespoolten Nachrichten.

**Teil B: AKS (1,25 PT, KW51), Schritte:**

1. Image per Digest in ACR, gleicher Index-Digest wie im Lab nach
   Teil A:

   ```bash
   D=sha256:c0020e53ed487ecffed6a15ef7ff1086ce969fd8b772cb06cfefc044eff5c0c8
   az acr import -n <acr> \
     --source "docker.io/solace/solace-pubsub-standard@$D" \
     --image solace/solace-pubsub-standard:10.26.0.9219
   az acr repository show -n <acr> \
     --image solace/solace-pubsub-standard:10.26.0.9219 \
     --query digest -o tsv                   # erwartet: $D
   ```

   Der Index enthält amd64 und arm64 (arm64-Manifest
   `sha256:d89f0d9c2399...`) [Quelle: Docker-Hub-Tags-API, 17.11.].
   [A: `az acr import` übernimmt die Manifestliste unverändert; weicht
   der Digest ab, gilt der ACR-Digest, und `docker buildx imagetools
   inspect` vergleicht das arm64-Manifest mit dem Lab.]
2. Installation: zuerst der Namespace, dann das Secret, dann helm.

   ```bash
   kaks create namespace solace --dry-run=client -o yaml | kaks apply -f -
   kaks -n solace create secret generic solace-admin \
     --from-literal=username_admin_password="$(az keyvault secret show \
       --vault-name <kv> -n solace-admin --query value -o tsv)" \
     --dry-run=client -o yaml | kaks apply -f -
   haks upgrade --install solace pubsubplus \
     --repo https://solaceproducts.github.io/pubsubplus-kubernetes-helm-quickstart/helm-charts \
     --version 3.10.0 -n solace -f emd/aks/pubsubplus-values.yaml
   ```

   `--create-namespace` allein reicht nicht: Das Chart prüft schon beim
   Rendern per `lookup`, dass das Secret im Release-Namespace existiert
   [Quelle: pubsubplus 3.10.0 templates/secret.yaml:1-7,
   values.yaml:66-70]. Werte in `emd/aks/pubsubplus-values.yaml`:
   - `solace.redundancy: false`,
     `solace.usernameAdminPasswordSecretName: solace-admin`.
   - `image.repository: <acr>.azurecr.io/solace/solace-pubsub-standard`,
     `image.tag: "10.26.0.9219@<D>"`. Das Chart baut
     `repository:tag`, Tag plus Digest ist eine gültige Referenz, und
     die Versionsprüfung im Template liest daraus 10.26 [Quelle:
     pubsubplus 3.10.0 templates/solaceStatefulSet.yaml:60, 118].
     Chart-Default wäre `latest` [Quelle: values.yaml:113-117].
   - `service.type: ClusterIP` mit 55555/8008/8080/5550. Chart-Default
     ist ein LoadBalancer, auf AKS also öffentlich [Quelle:
     values.yaml:157-159]; die VAP aus P2 lässt LoadBalancer ohnehin
     nur für den Traefik-Service zu.
   - `storage.persistent: true`, `storage.useStorageClass:
     managed-csi-premium`, `storage.size: 128Gi`,
     `storage.useStorageGroup: true` (ein Mount statt der Altform,
     empfohlen ab Broker 9.12 [Quelle: values.yaml:238-266]).
   - `solace.extraEnvVars` mit `messagespool_maxspoolusage` explizit
     (rund 20000 MB).
   - Größe `solace.size: prod1k`, außer der Platz erzwingt `dev`.
     `prod1k` heißt Requests und Limits 2 CPU/6515Mi (Guaranteed),
     mehr RAM, als der Lab-Broker heute belegt (4,19 GiB), und 1000
     Verbindungen; der Lab-Broker läuft mit dem Default von 100
     Verbindungen [A: per SEMP `show system` bzw. SEMPv2-GET prüfen].
     `dev` heißt Requests 1 CPU/3410Mi, Limit 2 CPU [Quelle:
     templates/solaceStatefulSet.yaml:67-72, 89-94], Mindestressourcen
     ohne Leistungszusage [Quelle: values.yaml:53-54], 100
     Verbindungen und beim RAM unter dem Lab-Verbrauch (OOM-Risiko);
     die Demo braucht rund 11 Verbindungen (3.2). Auf dem einen Node
     (AKS-E3) gilt das Kriterium aus 3.2: Liegen die nach P2
     gemessenen CPU-Requests von System, Traefik, cert-manager,
     Monitoring und Defender über 2044m, oder bleibt der Broker-Pod
     Pending, dann `dev`. Vor dem ersten Install
     entscheiden: Größe und
     Spool wirken als Config-Keys nur beim ersten Boot, ein Wechsel
     heißt neues PVC [Quelle: `docs.solace.com`
     Docker-Upgrade-Current-Release; A: gleiches Verhalten im
     Helm-Chart].
3. Terraform-Root `emd/terraform-aks/`: ein Provider-Alias
   `solacebroker.aks`, Provider exakt `= 1.3.0` mit eigener,
   versionierter Lock-Datei (keine Kopie der Lab-Lock-Datei, die emd
   `stop.sh` löscht). Module `vpn` und `client` wiederverwendet: VPN
   `default` und `sam`, Client `sam` (VPN sam), `gpos` (VPN default),
   `default` deaktiviert; kein DMR, keine Telemetry, kein AMQP 5673.
   State lokal, gitignored. Die sda-Root-`.gitignore` ignoriert auch
   `.terraform.lock.hcl`; eine eigene `emd/terraform-aks/.gitignore`
   nimmt die Lock-Datei mit `!.terraform.lock.hcl` wieder auf, sonst
   wäre sie nicht versioniert [Quelle: sda .gitignore].
   - Seit 10.25.22 meldet SEMP als `sempVersion` die Broker-Version,
     also etwa `10.26.0.9219` statt `2.48` [Quelle:
     `docs.solace.com/Admin/SEMP/SEMP-API-Versions.htm`]. Provider
     1.3.0 und 1.4.0 bestehen ihren API-Check auch damit [Quelle:
     terraform-provider-solacebroker v1.3.0
     internal/broker/resource.go:45, 101-111; A: gegen 10.26.0 nicht
     live geprüft, Schritt A6 belegt es mit `terraform plan`].
   - 1.4.0 ist aus dem Rolling Release 10.26.8 generiert und bringt
     Attribute, die die LTS-Linie 10.26.0 nicht kennt [Quelle:
     GitHub-Release v1.4.0], daher 1.3.0 wie im Lab.
   - Port-Forward auf 18080, weil 8080/8008/1883/55557 auf dem Mac vom
     Lab-`solace-1` belegt sind [Quelle: Befehl `docker ps`, 16.11.].
     Das Passwort kommt direkt aus dem Key Vault, nie als Literal in
     die Shell-History:

   ```bash
   emd/aks/semp-aks.sh port-forward     # kaks ... port-forward 18080:8080
   TF_VAR_admin_password="$(az keyvault secret show --vault-name <kv> \
     -n solace-admin --query value -o tsv)" \
     terraform -chdir=emd/terraform-aks apply
   ```

4. R1-Queue bleibt bei `gpd/scripts/broker.py` (das Queue-Modul kann
   TTL und Redelivery nicht [Quelle: emd terraform/modules/queue/main.tf:11-26;
   gpd scripts/broker.py:41-50]). Helfer `emd/aks/semp-aks.sh` öffnet
   den Port-Forward über `kaks` und prüft Kontext und
   Broker-Identität; die Prüfung akzeptiert `sempVersion` im neuen
   Format, nicht nur `2.x`. Er schreibt kein Passwort. Die
   SEMP-Passwortquelle für gpd legt `gpd/scripts/broker.sh` bei
   `TARGET=aks` selbst an (P6, `gpd/.env.aks`; 5.4), weil `broker.py`
   das Passwort nur aus einer tfvars-Datei liest [Quelle: gpd
   scripts/broker.py:80-87].

**Wer:** Teil A: Claude mit C (Baseline, Skripte, Prüfungen), Owner
(Go, Wartungsfenster, Freigabe der emd-Änderungen). Teil B: Claude.

**Abnahme Teil A (vor Teil B):**

- Beide Lab-Broker melden per SEMPv1 `show version` 10.26.0.9219;
  `docker image inspect` zeigt in `RepoDigests` `sha256:c0020e53ed48...`,
  `docker inspect` je ein externes Volume auf `/var/lib/solace`.
- SEMP-Export nach dem Upgrade gleich der Baseline A1 (VPNs, alle
  Queues inklusive der 36 außerhalb von Terraform, Client-Usernames,
  ACL-Profile, DMR-Links), bis auf Versionsfelder; DMR-Links up.
- Lab-`terraform plan` ohne Änderungen; `docker compose up --dry-run`
  plant für die Broker kein Neuerzeugen mehr.
- Der danach dokumentierte Lab-Zyklus (`docker compose stop`/`start`,
  oder mit Go aus A4 die angepassten `stop.sh`/`start.sh`) lief einmal
  ohne Datenverlust (SEMP-Export gleich A1) und mit leerem
  `terraform plan`; README, `CLAUDE.md` und Memory-Notiz nennen ihn.
- A7 grün: `make test`, `make smoke` READY auf Kasse 99, S1-e2e
  "proposed 100001 7,99", `broker.sh r1-show` 200, SAM-Agents geladen,
  Broker-Spans in Tempo.
- Snapshot-Images bis zum Aufräumen vorhanden; kein Prune.

**Abnahme Teil B:**

- Vor dem helm-Aufruf: `kaks -n solace get secret solace-admin -o
  jsonpath='{.data}' | jq 'has("username_admin_password")'` liefert
  `true` (nur der Schlüssel, nie der Wert).
- `kaks -n solace get sts solace-pubsubplus -o jsonpath='{..image}'`
  endet auf `@sha256:c0020e53ed48...`; SEMP meldet 10.26.0.9219; ein
  PVC 128Gi `managed-csi-premium` Bound; die gewählte Größe (`prod1k`
  oder `dev`) ist mit Begründung notiert.
- SEMP über 18080 zeigt VPN `sam` und `default`, User `sam` und `gpos`
  aktiv, `default` aus.
- Kein Broker-Port öffentlich: `kaks get svc -A` zeigt als einziges
  LoadBalancer-Service den Traefik-Service; von außen laufen
  `nc -z -w 5 <fqdn>` auf 55555, 8008, 8080 und 1883 in den Timeout
  (LB-Regeln nur 80 und 443); ein Service vom Typ LoadBalancer in
  `solace` wird per `kaks apply --dry-run=server` von der VAP
  abgelehnt.
- `semp-aks.sh` besteht die Identitätsprüfung gegen AKS und bricht
  gegen den Lab-Broker (127.0.0.1:8080) vor jedem Schreibzugriff ab.
- Nach `kaks -n solace delete pod solace-pubsubplus-0` ist der Broker
  in unter 5 min Ready und eine Test-Queue noch da.
- Lab-`solace-1` unverändert (Queue-Liste vorher/nachher gleich).

**Abhängigkeiten:** Teil A: eigenes Owner-Go, Wartungsfenster,
AKS-E15 (d). Teil B: Teil A grün; P2 (ACR-Spiegel, PriorityClasses,
VAP); AKS-E15 (c) für `emd/aks/` und `emd/terraform-aks/`. Ist Teil A
am 04.12. nicht grün, entscheidet der Owner am Prüfpunkt: Teil A bis
10.12. nachholen (Teil B beginnt erst danach) oder Rückfall
"G2a-AKS-Abnahme nach G2b" (Abschnitt 6).

### P5 SAM (2,5 PT, KW51, Gate G2a 18.12.)

**Ziel:** SAM 2.542.1 auf AKS unter `https://<fqdn>/` (`<fqdn>` =
`<p>.germanywestcentral.cloudapp.azure.com`, P1), Login über Keycloak
unter `/auth` (P3), Modelle aus dem Cluster erreichbar, Datenbank mit
LiteLLM-Key abgeschirmt. Das erfüllt "AKS RA-Schritte 1-6 bis SAM"
samt öffentlichem Ingress mit einem öffentlich vertrauenswürdigen
ACME-Zertifikat per HTTP-01 (Let's Encrypt oder EAB-Rückfall-CA),
API-Server nur von freigegebenen IPs und HTTPS-RTT [Quelle: PLAN 0.3
und 7.2, Zeile G2a] und nach
AKS-E18
(Empfehlung, Owner-Bestätigung offen) G0-11a sowie den HITL-Teil von
G0-11b.

**Schritte:**

1. Images registry-zu-registry, ohne `docker load` in den k3s-dockerd:

   ```bash
   az acr login -n <acr>
   for i in solace-agent-mesh:2.542.1 solace-agent-mesh-str:1.80.2 \
            postgres:18.0-trixie chrislusf/seaweedfs:4.48-compliant; do
     docker buildx imagetools create -t <acr>.azurecr.io/$i \
       registry.solace.lab/$i
   done
   ```

   Rückfall: `docker tag` + `docker push` aus dem Lab-dockerd (Images
   liegen dort). Nicht `load-images.sh`: Es lädt Tarballs in den
   dockerd, der zugleich die k3s-Runtime ist, und retaggt Bare-Namen
   [Quelle: amd scripts/load-images.sh:139, 185-186].
2. `amd/aks-values.yaml` als zweites `-f` (ohne Secret-Werte):
   - Host: `sam.dnsName: <fqdn>`, `ingress.host: <fqdn>`. Der Chart
     kennt keinen Basispfad und baut alle externen URLs (Frontend,
     OIDC-Callback, Plattform) aus `sam.dnsName`; die WebUI lädt ihre
     Assets ab `/` [Quelle: SAM-Chart 2.3.10
     templates/_config_helpers.tpl:10-108, ingress.yaml:27-41; Befehl
     `curl` gegen das Lab, 17.11.]. SAM bekommt deshalb `/` der einen
     FQDN; Keycloak (`/auth`, P3) und die gpos-Pfade (P6) gewinnen als
     längere Regeln [Quelle: Traefik-Doku routing rules-and-priority].
     OIDC-Callback ist `https://<fqdn>/api/v1/auth/callback`, exakt so
     als Redirect-URI im Client (P3).
   - TLS: `ingress.tls` mit `hosts: [<fqdn>]` und ohne `secretName`;
     die Liste ersetzt die Lab-Liste mit `sam-tls`. Traefik liefert
     dann das eine Zertifikat aus dem Default-TLSStore (P2), und die
     Chart-Prüfung greift nur bei gesetztem `secretName` [Quelle:
     SAM-Chart 2.3.10 templates/_validations.tpl:110-113]. Entscheidet
     der P2-Test anders, bleibt `secretName: sam-tls`, und Schritt 3
     legt das Secret vorher an.
   - `cert-manager.io/cluster-issuer: null` entfernt die
     Lab-Annotation `solace-lab-ca-issuer` [Quelle: amd
     local-k8s-values.yaml:127]; es gibt keine zweite ACME-Bestellung
     für denselben Namen.
   - `nginx.ingress.kubernetes.io/proxy-body-size: "10m"` plus
     `nginx.ingress.kubernetes.io/proxy-request-buffering: "on"`. Unter
     Traefik setzt nur das gepufferte Lesen ein Body-Limit durch, ohne
     die zweite Annotation gälte gar keins [Quelle: Traefik v3.7.19
     pkg/provider/kubernetes/ingress-nginx/middleware.go:176-213]. Im
     Lab fehlt das Limit (NGINX-Default 1m [Quelle: amd
     local-k8s-values.yaml:110-133]). 10m statt der 100m aus der
     PLAN-5.2-Skizze, weil jeder gepufferte Body im emptyDir des
     einzigen Traefik-Pods landet (P2 Schritt 5, Lücke 7); die
     Demo-Fotos bleiben unter 200 KB, G0-07 testete 2 MB [Quelle: PLAN
     5.1] [A: realer Upload-Bedarf der SAM-WebUI, in P5 prüfen]. Kein
     `proxy-buffering: "on"`, das würde Antworten und SSE puffern.
   - `nginx.ingress.kubernetes.io/limit-connections: "20"` [A]:
     höchstens 20 gleichzeitige Anfragen je Client-IP, also höchstens
     200 MiB gepufferte Bodies von einer IP; `limit-rps` allein
     begrenzt nur die Rate.
   - Die übrigen Lab-Annotationen wirken unter Traefik gleich:
     `ssl-redirect` (308), `backend-protocol` HTTP, `limit-rps` 100
     (429 statt 503, je Client-IP dank `externalTrafficPolicy: Local`
     aus P2), Timeouts 900 s. `proxy-buffer-size` und
     `proxy-buffers-number` wirken nicht und sind auch nicht nötig
     (Header-Limit 1 MiB) [Quelle: Traefik v3.7.19
     ingress-nginx.md:265-420; middleware.go:182-237].
   - `ingress.className` bleibt `nginx`. Die IngressClass `nginx`
     (Controller `k8s.io/ingress-nginx`) legt P2 für den NGINX-Provider
     von Traefik an; ohne sie bricht die Chart-Prüfung ab [Quelle:
     SAM-Chart 2.3.10 templates/_validations.tpl:185-206].
   - `global.imagePullSecrets: []`; Registry `<acr>.azurecr.io` in
     allen sechs Image-Blöcken; `broker.url:
     ws://solace-pubsubplus.solace.svc.cluster.local:8008`,
     `broker.clientUsername: sam`, `broker.vpn: sam`;
     `persistence-layer.{postgresql,seaweedfs}.persistence.storageClassName:
     managed-csi-premium`; awe-Limit 3Gi, str-Limit 6Gi.
3. Installation per Profil (AKS-E19 entschieden 17.11.). Das
   Broker-Passwort heißt im Chart `broker.password` [Quelle: amd
   local-k8s-values.yaml:67-71]:

   ```bash
   SAM_PROFILE=aks amd/scripts/start.sh
   # intern (KUBECONFIG aus .env.aks, wie haks): kein Certificate und
   # kein NodeHosts-Eintrag; nur bei secretName aus P2 vorher das
   # Secret sam-tls als Kopie des Default-Zertifikats anlegen, dann:
   helm upgrade --install agent-mesh "$SAM_CHART_PATH" -n sam-solace-lab \
     --kube-context "$SAM_KUBE_CONTEXT" \
     -f local-k8s-values.yaml -f aks-values.yaml \
     --set sam.oauthProvider.oidc.issuer="$KEYCLOAK_ISSUER" \
     --set sam.oauthProvider.oidc.clientId="$KEYCLOAK_CLIENT_ID" \
     --set sam.oauthProvider.oidc.clientSecret="$KEYCLOAK_CLIENT_SECRET" \
     --set llmService.llmServiceApiKey="$LLM_SERVICE_API_KEY" \
     --set broker.password="$SAM_BROKER_PASSWORD" \
     --set sam.sessionSecretKey="$SAM_SESSION_SECRET_KEY" \
     --set persistence-layer.postgresql.password="$SAM_PG_ADMIN_PASSWORD"
   ```

   Ohne Issuer bricht der Chart ab (P0 Schritt 13); `KEYCLOAK_ISSUER`
   ist `https://<fqdn>/auth/realms/solace-lab` (P3). `start.sh:72-85`
   prüft auf `aks` zusätzlich `SAM_BROKER_PASSWORD`,
   `SAM_SESSION_SECRET_KEY` und `SAM_PG_ADMIN_PASSWORD`. Das
   Superuser-Passwort steht auf **jedem** `helm upgrade` (start.sh nutzt
   kein `--reuse-values`) und nie in `local-k8s-values.yaml`, damit der
   Lab-Render gleich bleibt. Es landet im Secret `agent-mesh-postgresql`
   (PGPASSWORD), db-init liest es dort [Quelle: Befehl `helm template`
   lokal mit Dummy-Werten, 16.11., im Review]; der Chart-Default
   `password` lässt sich nach der Installation nicht mehr ändern
   [Quelle: SAM-Chart 2.3.10 charts/persistence-layer/values.yaml:27].
   Ein späterer Wechsel braucht `ALTER ROLE postgres` plus denselben
   Helm-Wert.
   - Certificate und CoreDNS-NodeHosts sind Lab-Schritte und laufen auf
     `aks` nicht [Quelle: amd scripts/start.sh:120-147]. SAM ruft sich
     selbst und den Keycloak-Back-Channel über `<fqdn>` auf, also über
     die öffentliche LB-IP (Hairpin-Test in P1, Rückfall
     `coredns-custom` auf die Traefik-ClusterIP).
   - Die Kopie `sam-tls` (nur bei der P2-Variante mit `secretName`)
     trägt keine cert-manager-Annotationen; nach jeder Erneuerung wird
     sie neu kopiert (um den 15.01.).
   - Namespace, Release und `namespaceId` bleiben `sam-solace-lab`
     (Queue-Präfix, e2e und Observability-Manifeste unverändert
     [Quelle: gpd scripts/broker.py:40; scripts/e2e.py:116]). Weil
     das Queue-Präfix damit auf Lab und AKS gleich ist, prüft
     `stop.sh` auf `aks` vor jedem SEMP-DELETE die Broker-Identität
     (P0 Schritt 10).
4. NetworkPolicies (AKS-E19, versioniert unter `amd/manifests/aks/`,
   Freigabe AKS-E15), durchgesetzt von der Cilium-Dataplane:
   - Policy A, podSelector `app.kubernetes.io/name=postgresql,
     app.kubernetes.io/instance=agent-mesh`: Ingress TCP 5432 nur aus
     dem eigenen Namespace (podSelector `{}`, deckt db-init und den
     sam-doctor-Hook) und vom Grafana-Pod (`namespaceSelector
     kubernetes.io/metadata.name=monitoring` plus podSelector
     `app.kubernetes.io/name=grafana`).
   - Policy B, podSelector `app.kubernetes.io/name=seaweedfs,
     app.kubernetes.io/instance=agent-mesh`: Ingress auf allen Ports
     (8333, 9333 und die internen) nur aus dem eigenen Namespace; der
     `s3-init`-Container fragt 9333 vor 8333 ab.
   - Keine Policy auf gwe, awe oder str: Prometheus-Scrapes auf
     9090/8090 und der Egress nach `gpos-engine:8765` (RA R15) bleiben.
     `kubectl exec` ist nicht betroffen.
   - Vorher die Labels mit `kaks -n monitoring get pod --show-labels`
     prüfen.

   Warum: Die App-User behalten im gebündelten Modus Passwort =
   Username [Quelle: SAM-Chart 2.3.10 `templates/_helpers.tpl`:359-397];
   nicht das Superuser-Passwort, sondern die NetworkPolicy schützt den
   Klartext-Key in `model_configurations`. Das gilt erst recht, seit die
   gpos-BFF ohne Login öffentlich ist (Entscheidung 17.11.).
5. Logins und Provisionierung:
   - Owner: `SAM_HOME=<aks-home> sam auth login solace-lab --url
     https://<fqdn>` als sam_admin, aus jedem Netz. Die CLI meldet sich
     am Autorisierungsserver von SAM an, nicht direkt bei Keycloak; der
     Pfad `/auth` ändert für sie nichts [Quelle: `sam auth login
     --help`, CLI 2.542.1; Lab
     `/.well-known/oauth-authorization-server`, 17.11.]. Alle Manifeste
     tragen den Zielnamen `solace-lab`, und der Token-Cache ist nach
     diesem Namen geschlüsselt; ein Login unter `eurocis-aks` wäre für
     plan/apply unsichtbar [Quelle: P0 Schritt 12].
   - Claude: `SAM_PROFILE=aks amd/scripts/provision.sh` (RBAC inkl.
     `notify:_:send`, Modelle `fast` und `planning`, max_tokens,
     Pricing, developer-mcp). Das Profil setzt nur `SAM_HOME`; jedes
     `sam config plan/apply` läuft mit `--url $SAM_URL --no-dotenv`, und
     ein Guard vergleicht vorher die gecachte URL des Ziels `solace-lab`
     in diesem Home mit `$SAM_URL` und bricht bei Abweichung ab.
     `developer-mcp` ist damit unter `<fqdn>` öffentlich, aber nur mit
     OIDC erreichbar (`enableAuth: "true"` [Quelle: amd
     scripts/entrypoints/entrypoints/developer-mcp.yaml:29]). Der
     LiteLLM-Key aus `amd/.env.aks` (Messe-Key O5, sobald vorhanden)
     trägt rpm- und tpm-Limits, die der LiteLLM-Betreiber setzt
     (Missbrauchsschutz, Entscheidung 17.11.); der Wert erscheint in
     keiner Ausgabe.
   - Owner: einmal als `marktleitung` in der AKS-WebUI anmelden; der
     Grant wirkt erst nach der ersten Anmeldung [Quelle: PLAN 0.5,
     O2].
   - Owner, nach dem ersten Login in den Devtools: Cookies und
     Web-Storage von `https://<fqdn>` notieren. Erwartet sind
     `csrf_token` und `sam_oidc_state` mit Path=/, die
     Keycloak-Cookies unter `/auth/realms/solace-lab/` und die Tokens
     im localStorage [Quelle: Lab-Prüfung per `curl -D` und WebUI-JS,
     17.11.]; ob SAM nach dem Callback weitere Cookies setzt, ist offen
     [A]. Hintergrund: Die öffentliche gpos-UI ohne Login teilt diesen
     Origin (akzeptierter Trade-off, Entscheidung 17.11.). gpos setzt
     weder Cookies noch Web-Storage und baut das DOM nur mit
     `textContent` [Quelle: gpd app/gposdemo/ui/static/shared/common.js;
     ui/bff.py:326-412].
   - Stellvertreter (AKS-E20, Owner-Bestätigung offen): eigener
     Keycloak-User mit sam_admin im AKS-Realm, eigenes `SAM_HOME`,
     meldet sich selbst an.
   - Grafana-Rechte auf AKS: `grant-grafana-platform-db.sh` bricht auf
     `aks` ab (es gibt SELECT auf alle Tabellen der Plattform-DB inkl.
     `model_configurations` [Quelle: amd
     scripts/observability/grant-grafana-platform-db.sh:36, 72, 85]).
     Stattdessen der AKS-Schritt `grant-grafana-aks.sh` (Kontext-Guard,
     SQL per stdin, nach `provision.sh`, wenn die WebUI-Migrationen
     gelaufen sind): CREATE oder ALTER ROLE `grafana_ro` mit dem
     Key-Vault-Passwort `grafana-ro`; in `sam-solace-lab_webui` GRANT
     CONNECT, USAGE ON SCHEMA public und SELECT nur auf `tasks`,
     `task_events`, `sessions`, `feedback` und die `scheduled_*`-Tabellen
     (aufgelöst über `pg_tables` mit `tablename LIKE 'scheduled\_%'`)
     [Quelle: sli pki/manifests/05-monitoring-values.yaml:141-142]; in
     `sam-solace-lab_platform` nur eine explizite Liste der Tabellen,
     die die Dashboards im Scope lesen (vorher aus deren Queries
     ermitteln [A: z. B. `eval_runs`]), nie `model_configurations` oder
     `gateway_deployments`, kein `ALL TABLES`, keine Default
     Privileges. Die ConfigMap `grafana-datasource-sam-platform-config`
     wird auf AKS nicht angewendet; nur die Insurance-Demo nutzt sie.
     Rückfall, falls die Verdrahtung des Key-Vault-Passworts (P2,
     Monitoring) zu aufwendig wird: `grafana-ro` aus der Key-Vault-Liste
     streichen und das clusterinterne Demo-Passwort bewusst behalten
     (es steht fest in sli 05-monitoring-values.yaml:156, amd
     grafana-datasource-sam-platform-config.yaml:37 und
     grant-grafana-platform-db.sh:36); Grants und NetworkPolicy schützen
     den Key trotzdem. Ein generiertes Secret, das nichts nutzt, ist
     keine Option.
   - Read-only Metadatenabfrage für die Backups (keine Werte):
     `SELECT table_name, column_name FROM information_schema.columns
     WHERE column_name ILIKE '%auth%' OR column_name ILIKE '%api_key%';`
     plus die Fremdschlüssel auf `model_configurations`. Jede weitere
     Tabelle mit Auth-Konfiguration kommt auf die Ausschlussliste in P7.
6. Wrapper `aks-start.sh` und `aks-stop.sh` (aus P1) erweitern:
   - Nach `az aks start` lesend prüfen, ob die aktuelle öffentliche IP
     in `apiServerAccessProfile.authorizedIpRanges` steht (dieselbe
     Abfrage wie `sli/aks/aks-allow-me.sh`; authorized IP ranges sind
     der Vorschlag der Planung für AKS-E5, der Owner kann abweichen).
     Fehlt sie, bricht der Wrapper vor jedem kubectl-Aufruf mit dem
     Hinweis auf `aks-allow-me.sh` ab. Das Skript ersetzt die ganze
     Liste per `az aks update`, die Änderung greift nach bis zu 2 min
     [Quelle: `learn.microsoft.com/azure/aks/api-server-authorized-ip-ranges`].
   - Dann auf den Node, Broker und gwe warten, awe einmal neu starten
     (gwe/awe-Race [Quelle: amd README.md:511-513]), dann Preflight.
     Die 30-min-Sperre aus P1 bleibt.
   - kubectl erreicht den API-Server über dessen FQDN; eine neue
     API-Server-IP nach dem Start braucht keinen eigenen Schritt.
7. HITL-, Artefakt- und Vision-Test (G0-11b (1) und G0-11a nach
   AKS-E18, Owner-Bestätigung offen):
   - 7a: Approver-RBAC: `SAM_HOME=<aks-home> sam config apply -m
     manifest-rbac.yaml --url $SAM_URL --no-dotenv` (Rolle
     `gpos_marktleitung`, Claim-Mapping `keycloak-group-marktleitung`,
     dieselben Objekte wie gpd `mesh/manifest-rbac.yaml`). Sie bleiben
     auf AKS; `install.sh mesh` wendet sie später erneut an.
   - 7b: Spike-Paket für AKS in ein Verzeichnis `.rendered-aks/`
     (chmod 600) rendern; nicht mit `render.sh`, das die BSG-Lab-`.env`
     liest und das Ziel `solace-lab` fest setzt. Nur Workflow
     `gpos-spike-hil-a` und Entrypoint `gpos-spike-events` mit Regel
     `hil_a`: `broker_url
     ws://solace-pubsubplus.solace.svc.cluster.local:8008`, VPN
     `default`, User `gpos` aus P4, Passwort aus Key Vault. Anwenden mit
     `--url $SAM_URL --no-dotenv`, nie `--prune`.
   - 7c: Claude publiziert ein Event auf `gpos/spike/hil/a/<seq>` aus
     einem Debug-Pod im Cluster (kein Broker-LoadBalancer). Der Lauf
     pausiert; Claude startet awe während der Pause einmal neu, wie
     G0-11b verlangt, und protokolliert das Ergebnis (laut
     spikes/g0/results/README Punkt 5 wird der Lauf scheitern). Ein
     zweiter Lauf wird vom Owner in der Inbox von `marktleitung`
     (`https://<fqdn>/`) freigegeben; die `tell`-Benachrichtigung kommt
     an, ein `wf_*`-Artefakt für `marktleitung` liegt in SeaweedFS.
   - 7d: Vision-Probe aus dem Cluster: ein neutrales Testbild (rund
     150-500 KB, kein GEBIT-Material) wird in der AKS-WebUI hochgeladen;
     ein temporärer Probe-Agent (Präfix `gpos-spike-`, `load_artifact`,
     Alias `fast` wie bei A2b [Quelle: PLAN 2.6]) beschreibt es
     korrekt. Das belegt LiteLLM mit Bild-Payload, SeaweedFS und den
     Upload-Weg durch Traefik mit Request-Buffering und erfüllt G0-11a
     Prüfung (2) auf Modellebene [Quelle: PLAN 7.1, G0-11a]; der Teil mit
     `gpos-price-scout` folgt in P6.
   - 7e: Aufräumen (G0-02.md nennt keine Befehle): `gpos-spike-events`,
     `gpos-spike-hil-a` und den Probe-Agent einzeln per sam CLI oder
     Plattform-API entfernen, nie `--prune`; die Rest-Queue
     `.../eventmesh/gpos-spike-events/hil_a` per SEMP auf 18080 löschen
     (README Punkt 21); die `wf_*`-Artefakte des Spikes löschen (README
     Punkt 14). Rolle und Claim-Mapping bleiben.
8. HTTPS-RTT vom Owner-Mac zum öffentlichen Ingress messen, über Kabel
   (einmal zusätzlich vom Handy-Hotspot, nur zur Information):

   ```bash
   for i in $(seq 1 100); do
     curl -s -o /dev/null -w '%{time_connect}\n' https://<fqdn>/health
   done | sort -n | awk '{v[NR]=$1} END {print v[int(NR*0.95)]}'
   ```

   `time_connect` ist der TCP-Handshake, also eine Rundlaufzeit;
   `/health` beantwortet SAM selbst [Quelle: Befehl `curl` gegen das
   Lab, 17.11.]. Das ist die HTTPS-RTT aus PLAN 7.1 (Absatz unter der
   Gate-0-Tabelle) [A: Messgröße mit dem PLAN-Eigner abstimmen].

**Wer:** Claude 1-4, 5 (Provisionierung, Grants), 6-8; Owner 5
(Logins, Devtools-Befund) und die Freigabe in 7c; Stellvertreter sein
Login.

**Abnahme (G2a):**

- WebUI-Login `https://<fqdn>/` über Keycloak (`/auth`) als sam_admin
  ohne Zertifikatswarnung, vom Mac über Kabel und einmal vom
  Handy-Hotspot; der Redirect endet auf
  `https://<fqdn>/api/v1/auth/callback`. `openssl s_client -connect
  <fqdn>:443 -servername <fqdn> </dev/null | openssl x509 -noout
  -issuer -enddate` zeigt Let's Encrypt (Produktion) oder die
  Rückfall-CA aus P2 (öffentlich vertrauenswürdiges ACME-Zertifikat
  per HTTP-01, wie PLAN 0.3 G2a es verlangt).
- `curl -sI https://<fqdn>/` zeigt `strict-transport-security` ohne
  `includeSubDomains`; `http://<fqdn>/` antwortet mit 308 auf https.
- Aliase `fast` und `planning` antworten aus dem Cluster (beweist
  LiteLLM über die Egress-IP); die Vision-Probe ist grün.
- Body-Limit: Ein POST mit 12 MB an `https://<fqdn>/api/v1/x`
  (`curl --data-binary @<datei>`) endet mit 413 von Traefik.
- Puffer-Last: 30 parallele, langsam gesendete POSTs mit je 9 MB von
  einer IP an `https://<fqdn>/api/v1/x`: ab der 21. Verbindung 429;
  der Traefik-Pod wird nicht `Evicted`, restartCount bleibt 0, und
  `/kasse` antwortet währenddessen von einer anderen IP.
- Langläufer: Eine HTTP/1.1-Anfrage an SAM mit mehr als 60 s Laufzeit
  (`curl --http1.1`, z. B. ein MCP-`tools/call` über `developer-mcp`
  [A: Endpunkt in P5 festlegen]) bricht nicht nach 60 s ab
  (EntryPoint-`readTimeout` 3600 s aus P2 [Quelle: Traefik v3.7.19
  entrypoints.md:128-130]). Browser über HTTP/2 verdecken den Fehler.
- Hairpin: Aus einem Debug-Pod in `sam-solace-lab`
  (`<acr>.azurecr.io/curl:8.23.0`) liefern `https://<fqdn>/health` und
  `https://<fqdn>/auth/realms/solace-lab/.well-known/openid-configuration`
  200 ohne `-k`; die gwe-Logs zeigen keinen Fehler bei der
  OIDC-Discovery.
- Spike-Workflow mit Artefakt-Speicherung läuft (SeaweedFS); eine
  HITL-Pause wird von `marktleitung` freigegeben; das Ergebnis des
  awe-Neustarts ist protokolliert; Spike-Reste entfernt.
- SAM-Dashboards zeigen Daten; SEMP zeigt gwe, awe und str auf VPN
  `sam`.
- Grafana: In der WebUI-DB liefert `SELECT
  has_table_privilege('grafana_ro','tasks','SELECT')` t; in der
  Plattform-DB liefern `has_table_privilege('grafana_ro',
  'model_configurations','SELECT')` und
  `has_column_privilege('grafana_ro','model_configurations',
  'model_auth_config','SELECT')` f; das Dashboard "SAM Token und Cost
  (Chargeback)" zeigt nach einem Workflow-Lauf Zeilen und kein
  "permission denied"; die Datasource "SAM Platform DB" besteht
  "Save & test"; `kaks get cm -n monitoring -o yaml` enthält das
  `grafana_ro`-Passwort nicht (Zählprüfung ohne Ausgabe); kein anonymer
  Zugang und keine Viewer-Konten mit Explore, keine offene
  Admin-Sitzung auf einem Stand-Bildschirm.
- AKS-E19: Ein Testpod in `gpos-demo` bekommt auf 5432, 8333 und 9333
  nach `sam-solace-lab` einen Timeout; nach `kaks rollout restart` von
  gwe, awe und str laufen db-init und s3-init durch; ein Login als
  `postgres` mit "password" scheitert; PGPASSWORD im Secret
  `agent-mesh-postgresql` gleicht dem Key-Vault-Wert (Vergleich ohne
  Ausgabe).
- Devtools-Befund (Cookies, Web-Storage) aus Schritt 5 dokumentiert.
- Metadatenabfrage dokumentiert, Ausschlussliste für P7 fest.
- API-Server: `kaks get --raw /readyz` ok von einer freigegebenen IP.
  Ein Zyklus `aks-stop.sh`, mindestens 30 min Pause, `aks-start.sh`
  endet mit geladenen Agents. Einmal vom Handy-Hotspot: `aks-start.sh`
  bricht mit dem Hinweis auf `aks-allow-me.sh` ab, nach dessen Lauf
  (bis 2 min) läuft er durch; die WebUI ist vom Hotspot auch ohne
  Freigabe erreichbar.
- Ein AKS-Zyklus `SAM_PROFILE=aks stop.sh`, dann `start.sh`,
  `provision.sh` und Schritte 4-5 erneut: Lab-Keycloak-Client und -User
  bleiben unverändert (Diff leer), die Queue-Liste der Lab-VPN `sam`
  auf `solace-1` ist vorher und nachher gleich (SEMP-Identitätsprüfung
  aus P0 Schritt 10), AKS ist danach wieder G2a-grün; eine
  Zählabfrage auf `[?&]token=` in Loki ergibt weiter 0.
- HTTPS-RTT p95 höchstens 40 ms über Kabel [Quelle: PLAN 0.3 und 7.2,
  Zeile G2a].
- Lab am selben Tag: Call-Log- und Render-Diff leer, Lab-Smoke grün,
  Lab-sam-Cache (`solace-lab.json` im Default-Home) unverändert.

**Abhängigkeiten:** P3; P4 Teil A und Teil B; amd-Working-Tree
committet (cd08a17, AKS-E15 (a), erledigt); AKS-E19 entschieden
17.11.; aus P1 der Hairpin-Test und `aks-allow-me.sh`; aus P2 die
IngressClass `nginx`, das Default-Zertifikat für `<fqdn>` und die
TLS-Variante (mit oder ohne `secretName`).

### P6 GEBIT-Demo portieren (5,75 PT, Vorarbeit KW52-KW1 im Lab, AKS KW1-2, Gate G2b 15.01.)

**Ziel:** UC1 mit S1, S3, S7, S8 Ende zu Ende auf AKS unter dem einen
Namen `<fqdn>` (= `<p>.germanywestcentral.cloudapp.azure.com`), dazu
TR3 (A2b), sobald es im Lab grün ist (TR3 ist "Nie gestrichen"
[Quelle: PLAN 6.2]), und je ein TR1-Besuch über das öffentliche
Internet: vom Leih-Router mit Kabel-Uplink, vom Leih-Router mit 5G und
von einem Handy-Hotspot [Quelle: PLAN 0.3 G2b; PLAN 7.2 G2b]. Kasse und
Monitor bleiben unverändert und ohne Login.

**Routing und Abwägungen:** Die Pfade auf `<fqdn>:443` stehen in
2.1 (Owner-Entscheidung 17.11.2026); P6 legt die gpos-Pfade (Schritt
3) und die gRPC-Service-Pfade (Schritt 8) an, SAM (`/`) und Keycloak
(`/auth`) kommen aus P5 und P3. Die akzeptierten Abwägungen stehen in
2.2. Für P6 heißt das: Jede neue gpos-Seite setzt keine Cookies,
nutzt keinen Web-Storage und baut das DOM nur mit `textContent`
(Review-Punkt in AP10/AP11) [Quelle: Befehl `grep` nach
`localStorage`, `document.cookie`, `innerHTML` in gpd
app/gposdemo/ui/static, 17.11.: 0 Treffer]; die gRPC-Schreib-RPCs
(WWS-Preisänderung und Reset, Loyalty-Coupons, Consent und Reset,
POS-Transaktionen) sind für jeden aufrufbar, gebremst nur durch
`limit-rpm` je Client-IP (Schritt 8) [Quelle: gpd
proto/de/showcase/wws/v1/service/wws_service.proto,
proto/de/showcase/loyalty/v1/service/loyalty_service.proto].

**Schritte:**

1. Voraussetzung GEBIT (AKS-E16): Die schriftliche Freigabe liegt laut
   Owner seit 17.11.2026 vor; das Demo-Verzeichnis ist seit Commit
   7a860c5 im Repo. Dass sie auch das GEBIT-Descriptor-Set als
   K8s-Secret in Azure (Germany West Central), den Zugriff der
   Stellvertretung und die öffentliche Reflection abdeckt, ist die
   Planungsannahme [A]; der Status ist bewusst "offen", gehandelt wird
   erst nach schriftlicher Bestätigung (AKS-E16). Fällig ist sie bis
   27.11., spätestens 09.12., weil schon `gebitsim` in P2 Schritt 7
   (G0-11b (3), 11.12.) das Descriptor-Set als Secret in Azure
   braucht. Ohne Bestätigung legt `install.sh k8s` auf AKS kein
   `gpos-gebit-descriptors` an, und die Demo läuft nur im Lab oder in
   L3. Bestätigt der Owner das Secret, aber nicht die öffentliche
   Reflection, bleiben die Reflection-Pfade ungeroutet (Schritt 8).
   Alle anderen Schritte laufen unabhängig davon; `pg` und `db`
   brauchen kein GEBIT-Material. Das Descriptor-Set kommt nie in Git,
   Images, ACR, Key Vault oder Backups.
2. Lab-Vorarbeit (keine AKS-Abhängigkeit): `k8s/` in `base`,
   `overlays/lab` (rendert byte-identisch zur Baseline aus P0 Schritt
   9), `overlays/aks`, später `overlays/l3`, dazu die kustomize-
   Komponente `k8s/components/public-guard` (Schritt 3). Das
   Certificate `gpos-demo` (4 dnsNames, Lab-CA) gehört ins Lab-Overlay,
   nicht nach `base`. Das aks-Overlay:
   - setzt das Image `<acr>.azurecr.io/gpos-demo/gpos-demo`, entfernt
     `imagePullSecrets` per JSON-Patch und setzt
     `SAM_URL=https://<fqdn>` (nur ein Link in der UI, kein
     Serveraufruf [Quelle: gpd app/gposdemo/ui/bff.py:188;
     common/config.py:212]);
   - hat kein eigenes Certificate und keine `secretName`-Felder. Die
     Ingresses behalten `spec.tls.hosts: [<fqdn>]`, damit `ssl-redirect`
     greift, und Traefik liefert das eine Zertifikat aus dem
     Default-TLSStore (P2) [Quelle: Traefik v3.7.19
     pkg/provider/kubernetes/ingress-nginx/build.go:365-367;
     middleware.go:47-61]. Entscheidet P2 für eine Secret-Kopie je
     Namespace (wie `sam-tls`), setzt das Overlay `secretName` auf die
     Kopie. Je identischem Namensset gibt es nur 5 Ausstellungen in 7
     Tagen, ohne Override [Quelle: `letsencrypt.org/docs/rate-limits`];
   - patcht `gpos-ui` auf die Pfade aus Schritt 3, ergänzt
     `gpos-ui-pos`, `gpos-ui-demo` und `gpos-ui-events`, patcht die
     drei gRPC-Ingresses auf Service-Pfade und ergänzt
     `gpos-grpc-reflection` (Schritt 8), alle auf Host `<fqdn>`;
   - behält `ingressClassName: nginx`. Dieselben NGINX-Manifeste laufen
     im Lab unter ingress-nginx und auf AKS unter dem NGINX-Provider von
     Traefik (IngressClass aus P2). Was nur unter Traefik gilt (429
     statt 503, Body-Limit nur mit Request-Buffering, Punkte in
     Präfix-Pfaden), belegen erst P2 und dieser Schritt auf AKS.

   Die Demo-DB liegt nicht im Overlay, sondern in einer eigenen
   kustomization `k8s/postgres-aks/`: Namespace `gpos-data`, headless
   Service `gpos-postgres`, StatefulSet `gpos-postgres` (Postgres 18 aus
   ACR per Digest, 8Gi `managed-csi`, `POSTGRES_PASSWORD` aus Secret
   `gpos-postgres-admin`, Mount auf `/var/lib/postgresql` mit dem
   Image-Default-PGDATA [A: damit `lost+found` der Azure-Disk initdb
   nicht stört]). So berühren `install.sh k8s`/`uninstall.sh` und das
   globale `namespace: gpos-demo` die Datenhaltung nicht. Die
   Namespace-Regel in `k8s_render.py`/`install.sh` wird ausdrücklich um
   `gpos-data` erweitert. `scripts/tests/test_k8s.py` prüft Basis, alle
   Overlays, `public-guard` und `postgres-aks` [Quelle: heute pinnt der
   Test Lab-Hosts, gpd scripts/tests/test_k8s.py:95-120]. Neu prüft er
   für das aks-Overlay gegen eine ausdrückliche Liste (Routenliste aus
   `bff.py`) [A: Test neu]:
   - öffentlich: `/kasse`, `/monitor`, `/static/`, die lesenden
     `/api/...`-Pfade aus Schritt 3, `/api/pos/`, `/api/demo/`,
     `/api/events` und später `/kunde` (Kundenanzeige der Kasse);
     jede dieser Routen hat genau einen Pfad;
   - Exposition offen (Frage 23): `/freigabe`, `/foto`, `/op`,
     `/etikett` und ihre API-Routen (etwa die Antwort-Route der
     Freigabe und der Foto-Upload) haben keinen Pfad auf `<fqdn>`; der
     Test schlägt fehl, wenn einer geroutet ist. Nach der
     Owner-Entscheidung wandert eine Route in die öffentliche Liste
     (mit `public-guard`, falls sie SAM oder ein LLM anstößt) oder
     bleibt bei Port-Forward bzw. Lab;
   - jede neue BFF-Route steht in genau einer der beiden Listen, sonst
     schlägt der Test fehl; kein gpos-Pfad belegt `/` oder `/health`.
3. Pfad-Ingresses für gpos-ui und Komponente `public-guard` (nur im
   aks-Overlay):
   - `gpos-ui`: `/kasse`, `/monitor`, `/static/`, `/api/catalog`,
     `/api/cards`, `/api/scenarios`, `/api/state`, `/api/proposals/`;
     `proxy-request-buffering: "on"` und `proxy-body-size: "4m"`. Unter
     Traefik greift das Body-Limit nur mit Request-Buffering [Quelle:
     Traefik v3.7.19 middleware.go:176-213].
   - `gpos-ui-pos` (`/api/pos/`) und `gpos-ui-demo` (`/api/demo/`,
     einzige Route `/api/demo/reset` [Quelle: gpd ui/bff.py:395-402])
     mit denselben Annotationen.
   - `gpos-ui-events` (`/api/events`): `proxy-buffering: "off"`, kein
     Request-Buffering, `proxy-read-timeout: "3600"`. Auf der SSE-Route
     nie Buffering, sonst bleibt der Strom hängen; ohne Buffering flusht
     Traefik `text/event-stream` sofort [Quelle: Traefik v3.7.19
     middleware.go:182-189]. Heartbeat alle 15 s [Quelle: gpd
     app/gposdemo/ui/feed.py:54].
   - `public-guard` setzt je Client-IP: `limit-rpm` rund 120 auf
     `gpos-ui-pos`, `limit-rpm` 2 mit `limit-burst-multiplier` 1 auf
     `gpos-ui-demo`, `limit-connections` rund 10 auf `gpos-ui-events`
     [A: Werte, kalibriert in Schritt 12 und P7 gegen e2e, Kiosklauf
     und alle Standgeräte hinter einer NAT-IP]. Traefik antwortet mit
     429 und schlüsselt nach der Remote-Adresse; echte Client-IPs gibt
     es nur mit `externalTrafficPolicy: Local` am Traefik-Service (P2)
     [Quelle: Traefik v3.7.19 middleware.go:346-367;
     `learn.microsoft.com/azure/aks/configure-load-balancer-standard`].
     Kein Login, keine Änderung an UI oder Image. Die Annotationen sind
     auch native ingress-nginx-Annotationen (dort 503 statt 429).
   - Regel für spätere Routen: Jede BFF-Route, die SAM oder ein LLM
     anstößt (etwa der Foto-Upload von `/foto` mit `load_photo` und
     dem Vision-Agenten `gpos-price-scout`), bekommt, sobald der Owner
     sie öffentlich macht (Frage 23), ein eigenes Ingress-Objekt in
     `public-guard` mit `limit-rpm` (Multiplikator 1) und
     `proxy-body-size`; der Routentest aus Schritt 2 prüft das.
   - `reset.sh` und `smoke.py` gehen nicht über den Ingress (Reset im
     Pod, Smoke über den Port-Forward); e2e geht über `E2E_BASE_URL` und
     damit durch die Limits [Quelle: gpd scripts/reset.sh:28-29;
     scripts/smoke.py:50; scripts/opslib.py:425].
4. sam-CLI-Seam (Ergebnis P0 Schritt 12):
   - Alle sam-Aufrufe (`sam_apply`, `opslib.SamApi`, `check_hygiene
     --platform`) mit `--sam-home <ziel-home> --url $SAM_URL
     --no-dotenv`.
   - Die Haupt-Manifeste (`mesh/manifest.yaml`, `manifest-rbac.yaml`,
     `fallback/`) werden **nicht** je Ziel gerendert, sondern an Ort und
     Stelle angewendet; der Resolver sucht `connectors/`, `agents/` und
     `workflows/` neben dem Manifest [Quelle: amd
     scripts/models/apply-models.sh:62-68].
   - `opslib.SamApi` und `check_hygiene` behalten `sam api --manifest
     mesh/manifest.yaml` und ergänzen `--url $SAM_URL` (`--url` hat
     Vorrang; der Token kommt über den Zielnamen aus dem Home).
   - Je Ziel gerendert werden nur die Entrypoints (Broker-Credentials):
     `render_mesh.py --out mesh/.rendered/<target>` mit Name
     `solace-lab` und URL aus `SAM_URL`; `entrypoints/` liegt im selben
     Verzeichnis. Falls je Ziel eigene Haupt-Manifeste nötig werden,
     gilt das CLI-Layout `<root>/manifests/<ziel>.yaml`.
   - e2e: `AWE_NS`/`AWE_DEPLOY` aus der Umgebung; `E2E_CA_FILE=system`.
5. Image:

   ```bash
   docker buildx imagetools create \
     -t <acr>.azurecr.io/gpos-demo/gpos-demo:0.1.3 \
     registry.solace.lab/gpos-demo/gpos-demo:0.1.3
   ```

   Neues Arbeitspaket Image 0.1.4, gemeinsamer Reflection-Endpunkt
   [A: rund 0,5 PT], Lab-Vorarbeit KW52-53:
   - Grund: Reflection und Health liegen auf allen drei Servern unter
     denselben Pfaden; über einen Host erreicht `/grpc.reflection.*`
     nur einen Server [Quelle: gpd app/gposdemo/common/grpcutil.py:
     150-167].
   - Änderung: gpos-pos beantwortet Reflection für alle drei Dienste.
     Ein Reflection-Servicer sucht Symbole und Dateien zuerst im
     GEBIT-Pool, dann im Showcase-Pool (`SHOWCASE_DESCRIPTOR_SET`); die
     Pools bleiben getrennt [Quelle: gpd
     app/gposdemo/common/descriptors.py:1-9]. Ein Schalter in
     `gpos-config` (Vorschlag `GPOS_GRPC_REFLECTION_SCOPE=all`, Default
     `own`) steht nur in den Overlays `aks` und `l3`, damit das Lab
     unverändert bleibt [A: Name und Form].
   - Tests: Unit-Test in `app/tests/common/test_grpcutil.py` (Liste mit
     drei Diensten, `describe` eines Showcase-Dienstes über gpos-pos,
     getrennte Pools); `smoke.py` erwartet bei Scope `all` alle drei
     Dienste in der Liste von gpos-pos, im Lab weiter nur den
     PurchaseTransactionService [Quelle: gpd scripts/smoke.py:329-335].
   - Ablauf: zuerst im Lab (`make test`, `make smoke`, S1-e2e), dann
     0.1.4 statt 0.1.3 nach ACR (Makefile `GPOS_VERSION`,
     kustomization-Tag, G2b-Abnahme). Der Tag-Wechsel ist ein eigener
     Commit nach dem Render-Diff-Gate des Overlay-Umbaus. PLAN 2.3
     (Reflection vom Stand und aus der Tiefenecke [Quelle: PLAN 2.3])
     bekommt nach Freigabe einen Satz zum gemeinsamen Endpunkt auf AKS.
   - Bis 0.1.4 auf AKS läuft, nutzen grpcurl und Postman für wws und
     loyalty das lokale Showcase-Descriptor-Set: `make protos` baut
     `build/descriptors/showcase.pb` aus `proto/`, ohne GEBIT-Material
     [Quelle: gpd Makefile:35-36]; grpcurl mit `-protoset`, Postman mit
     Import der `.proto`-Dateien statt Reflection.
6. Demo-DB in zwei Teilen; Reihenfolge auf AKS: `pg` → `db` → `k8s` →
   `mesh`, und `install.sh all` folgt auf `aks` genau dieser Reihenfolge
   (im Lab bleibt `all` = db, k8s, mesh [Quelle: gpd
   scripts/install.sh:243-247]). Heute legt erst `install_k8s` den
   Namespace an, und `install.sh k8s` bricht ohne die db.env aus
   `install.sh db` ab [Quelle: gpd scripts/install.sh:117, 123].
   - 6a `TARGET=aks scripts/install.sh pg` (nur auf `aks`, im Lab ein
     No-op): Namespace `gpos-data`, Secret `gpos-postgres-admin` vom Mac
     an den API-Server (Wert aus Key Vault, Muster `apply_secret`),
     `kaks apply -k k8s/postgres-aks`, `kaks -n gpos-data rollout status
     sts/gpos-postgres --timeout=300s`, dann `pg_isready`.
   - 6b `TARGET=aks scripts/install.sh db`: psql-Seam
     `PG_MODE=docker|kubectl`; auf AKS ist `psql_admin` =
     `kaks -n gpos-data exec -i gpos-postgres-0 -- psql -X -U postgres
     -v ON_ERROR_STOP=1` über den gpd-`KUBE_CONTEXT`-Wrapper (lokaler
     Socket, kein Passwort in der argv). Die `docker inspect`-Prüfung in
     `install_db` (install.sh:67-68) wird je `PG_MODE` zur
     Readiness-Prüfung. Dann SQL 00-40, Rollen-Passwörter aus Key Vault
     (hex; zusätzlich URL-Kodierung im DSN auf `aks`), Seed 2027-02-16,
     95-checks. Der Guard bei install.sh:117 prüft auf `aks` zusätzlich,
     dass die DB existiert (z. B. Rolle `gpos_engine` in `pg_roles`);
     sonst startet eine übrig gebliebene db.env die Demo gegen ein leeres
     Postgres.
7. `gpd/.env.aks` (gitignored) und `.env.aks.example` (Obermenge von
   `ENV_KEYS`):
   - `SAM_URL=https://<fqdn>`, `SAM_HOME=<aks-home>`,
     `SAM_RUN_IDENTITY=marktleitung@solace.lab` (bewusst unverändert,
     8.2), `KUBE_CONTEXT=aks-eurocis`,
     `KUBECONFIG=~/.kube/aks-eurocis.yaml`, `AWE_NS=sam-solace-lab`,
     `AWE_DEPLOY=agent-mesh-solace-agent-mesh-awe`
   - `E2E_BASE_URL=https://<fqdn>` (die BFF-Pfade sind ausgeschnitten,
     Schritt 3), `E2E_CA_FILE=system`,
     `GPOS_IMAGE=<acr>.azurecr.io/gpos-demo/gpos-demo`
   - `BROKER_SMF_URL=tcp://solace-pubsubplus.solace.svc.cluster.local:55555`,
     `BROKER_WS_URL=ws://...:8008`, `BROKER_VPN=default`,
     `BROKER_USERNAME=gpos` + `BROKER_PASSWORD` (statt der BSG-`.env`
     [Quelle: gpd scripts/opslib.py:111-124])
   - `SEMP_URL=http://127.0.0.1:18080`, `SEMP_USER=admin`,
     `SEMP_PASSWORD_FROM=mesh/.rendered/aks/semp.tfvars`,
     `SEMP_PASSWORD_KEY=aks_admin_password`
   - `PG_MODE=kubectl`, `PG_NS=gpos-data`,
     `PG_HOST_FROM_PODS=gpos-postgres.gpos-data.svc.cluster.local`,
     `PG_PORT=5432`, `PG_DB=gpos`; ohne `PG_HOST_FROM_PODS` zeigten die
     DSNs in `gpos-db` auf `host.docker.internal` [Quelle: gpd
     scripts/install.sh:135-139]
   - `GPOS_DELIVERY=direct`

   Kein LLM-Key und kein SEMP-Passwort in dieser Datei: `load_env`
   exportiert sie, und `sam config apply` expandiert `${VAR}` aus der
   Umgebung [Quelle: gpd scripts/lib.sh:4-6]. Das SEMP-Passwort schreibt
   `scripts/broker.sh` bei `TARGET=aks` vor jedem `broker.py`-Aufruf
   neu: `umask 077`, `mkdir -p mesh/.rendered/aks`, eine Zeile
   `aks_admin_password = "<wert>"` aus `az keyvault secret show
   --vault-name <kv> -n solace-admin --query value -o tsv`, `chmod 600`,
   nie ausgegeben, nie unter `set -x`. Jeder Aufruf, damit auch ein
   alleinstehendes `reset.sh` oder `uninstall.sh` die Datei findet und
   ein rotiertes Secret ankommt; der hex-Wert enthält weder `"` noch
   einen Zeilenumbruch. Die Fail-closed-Prüfung aus P0 Schritt 11 läuft
   vor jedem Skript.
8. `TARGET=aks scripts/install.sh k8s`: Secrets `gpos-broker` und
   `gpos-db` direkt vom Mac an den API-Server, `gpos-gebit-descriptors`
   nur mit der schriftlichen Bestätigung aus Schritt 1. Die
   gRPC-Endpunkte sind öffentlich auf `<fqdn>:443`; das Overlay patcht
   die drei Lab-Ingresses (Namen bleiben) und legt für Reflection ein
   viertes an:
   - `gpos-grpc` → gpos-pos: `/<purchase-svc-fqn>/`
     (Purchase-Service-FQN, siehe Lesehinweis).
   - `gpos-wws-grpc` → gpos-wws:
     `/de.showcase.wws.v1.service.MerchandiseService/`.
   - `gpos-loyalty-grpc` → gpos-loyalty:
     `/de.showcase.loyalty.v1.service.LoyaltyService/`.
   - `gpos-grpc-reflection` → gpos-pos:
     `/grpc.reflection.v1.ServerReflection/` und
     `/grpc.reflection.v1alpha.ServerReflection/`; nur mit der
     schriftlichen Bestätigung der öffentlichen Reflection (AKS-E16),
     denn gpos-pos beantwortet Reflection aus dem GEBIT-Pool (ab 0.1.4
     zuerst dort) und gibt so die GEBIT-Descriptor-Dateien heraus.
     Ohne Bestätigung fehlt dieses Ingress, grpcurl und Postman nutzen
     `-protoset` für alle drei Dienste; ein Image-Schalter ist nicht
     nötig.
   - Annotationen: `backend-protocol: "GRPC"` (h2c zum Backend),
     `proxy-read-timeout` und `proxy-send-timeout` 3600, kein
     Request-Buffering [A: Reflection ist ein bidirektionaler Stream].
     `proxy-body-size` bleibt damit ohne Wirkung; die 4-MiB-Grenze
     setzt der Server selbst [Quelle: gpd
     app/gposdemo/common/grpcutil.py:37, 180]. Präfix-Pfade mit Punkten
     bestehen `strictValidatePathType` [Quelle: Traefik v3.7.19
     annotations.go:180-187; build.go:1196-1209; kubernetes.go:76].
   - `public-guard` auf den drei Service-Pfaden (nicht auf
     Reflection): `limit-rpm` rund 60 mit `limit-burst-multiplier: "1"`
     je Client-IP [A: Werte in Schritt 12 kalibrieren]; Traefik zählt
     jeden RPC über HTTP/2 als eine Anfrage [A]. Die Kasse im BFF
     spricht gRPC clusterintern über Service-DNS und ist nicht
     betroffen. Das bremst anonyme Purchase-Transaktionen (SAM-Reviews,
     LLM-Kosten) und Schreib-RPCs wie Preisänderung, Coupons und
     `ResetDemoState` je IP; die Kostengrenze bleibt der Messe-Key.
   - Kein Pfad für `/grpc.health.v1.Health/`: Health bleibt
     clusterintern (Probes, Smoke). Clusterinterne Clients nutzen
     weiter Service-DNS [Quelle: gpd k8s/configmap.yaml:22-24].
   - Reflection ist für alle an (Owner-Entscheidung 17.11.2026,
     AKS-E16). Die frühere Variante "Schalter im Image" entfällt; die
     "Sperre am Ingress" bleibt nur als Rückfall, solange die
     Bestätigung der öffentlichen Reflection fehlt (fehlendes
     `gpos-grpc-reflection`). Mit 0.1.3 meldet die Liste nur den
     PurchaseTransactionService, mit 0.1.4 alle drei Dienste
     (Schritt 5).

   `install.sh` überspringt auf `aks` das Warten auf Kyverno und den
   Lab-CA-Export.
9. `make manifests`, `TARGET=aks make smoke`; die Anmeldung als
   `marktleitung` (P5 Schritt 5) nur noch prüfen.
10. `TARGET=aks scripts/install.sh mesh`: RBAC, Manifest, hygiene
    `--platform`, Probe-Entrypoint, Proben p1/p3/p4/notify, **volle**
    Gate-Verifikation auf Kasse 98 (rund 11 min, in
    `build/aks/gate-verified`), R1-Queue, Booth-Entrypoint, Proben
    r1/r3/r4.
11. `TARGET=aks make e2e`: S1 x5, S3 x5, S7 x5, S8 x5, S1 deny x5, S1
    timeout x2; `scripts/reset.sh --scope day --preflight`; TR3 (A2b),
    sobald es im Lab grün ist: Foto über `/foto` → `load_photo` →
    `gpos-price-scout` mit Alias `fast` [Quelle: PLAN 6 AP10; PLAN 7.1
    G0-11a]. Öffentlich über `https://<fqdn>/foto` nur, wenn der Owner
    die Seite freigibt (Frage 23), dann mit eigenem
    `public-guard`-Limit (Schritt 3); bis dahin über den Port-Forward
    auf gpos-ui [A]. Damit ist auch der `gpos-price-scout`-Teil von G0-11a
    Prüfung (2) erfüllt (AKS-E18, Owner-Bestätigung offen). Liegt TR3
    bis G2b nicht vor, wandert der Punkt in die G3-Abnahme.
12. Öffentlicher Zugang am Stand, spätestens KW1 (die Leihgeräte stehen ab
    11.12. im Lab [Quelle: PLAN 6.5]):
    - Der Leih-Router braucht nur ausgehendes TCP 443 (und 80 für den
      Redirect): kein Peer, keine Router-Konfiguration, keine
      DNS-Ausnahme. Für L3 legt der Owner einen lokalen DNS-Eintrag
      `<fqdn>` → Lab-MacBook auf dem Router an, ausgeschaltet (AP14b).
    - Owner (physischer Zugang): Kiosk-Start-URLs, Lesezeichen und
      QR-Codes auf `https://<fqdn>/kasse` und `https://<fqdn>/monitor`;
      das Standpersonal tippt nichts.
    - Kalibrierung von `public-guard`: e2e (27 Läufe) und 30 min
      Kioskbetrieb mit allen Leihgeräten hinter dem Router ohne 429;
      sonst Werte anheben [A]. Ebenso die `limit-rpm` der drei
      gRPC-Service-Pfade gegen eine Postman- und grpcurl-Vorführung
      von einem Standgerät.
    - Der Free-Tier bleibt für das ganze Projekt; es gibt keinen
      Tier-Wechsel an G2b.

**Wer:** Claude 2-8, 10-11, 12 (Kalibrierung); Owner 1 (Bestätigung),
9 (Login), 12 (Router, Kiosk-URLs, TR1-Besuche).

**Abnahme (G2b):**

- 6 Deployments 1/1; Image-Plattform-Digest gleich Lab (`docker buildx
  imagetools inspect` beider Refs), für 0.1.3 und, sobald gebaut, 0.1.4.
- Vor `install.sh mesh`: `TARGET=aks scripts/broker.sh r1-show`
  liefert 200, nicht 401; ohne `SEMP_PASSWORD_FROM` bricht derselbe
  Aufruf mit der Guard-Meldung ab, ohne dass ein Request einen Broker
  erreicht.
- Smoke READY auf Kasse 99; `build/aks/gate-verified` PASS 10/10 mit
  `target=aks`.
- e2e 27/27 mit Lab-Erwartungen und ohne 429: S1 100001 7,99; S3
  100012 12,99 mit Loyalty; S7 100008 5,49 mit 3 api_queries; S8
  no_action; deny und timeout korrekt [Quelle: gpd
  scripts/e2e.py:156-164].
- TR3 auf AKS (falls im Lab grün): 5/5 Läufe korrekt, Werte auf dem
  Monitor p90 höchstens 5 s (AP10).
- `uninstall.sh` ohne `--drop-db` lässt `gpos-postgres` und sein PVC
  stehen; `TARGET=aks scripts/install.sh all` aus leerem Namespace in
  höchstens 30 min inklusive voller Gate-Verifikation, Dauer
  protokolliert [Quelle: PLAN 6 AP12].
- Alle gpos-Pods Ready, keine DSN-, Port- oder `invalid integer
  value`-Fehler in den Logs von engine, wws, loyalty und pos.
- Reset unter 15 s; A4 p50 höchstens 18 s, p90 höchstens 24 s.
- TR1: je ein TR1-Besuch Ende zu Ende über das öffentliche Internet,
  (a) Leihgerät hinter dem Leih-Router mit Kabel-Uplink, (b) derselbe
  Router mit 5G, (c) ein Gerät am Handy-Hotspot; Kasse und Monitor ohne
  Zertifikatswarnung und ohne Login, Freigabe durch `marktleitung` in
  der SAM-Inbox [Quelle: PLAN 0.3 G2b; PLAN 6 AP12].
- Routing: `https://<fqdn>/` liefert die SAM-WebUI, kein 302 auf
  `/monitor`; `/kasse`, `/monitor` und `/api/state` liefern gpos, ohne
  `Set-Cookie`; `http://<fqdn>/kasse` antwortet mit 308 auf https.
- Negativtests vom Hotspot: `/auth/realms/master/` und `/auth/admin/`
  erreichen Keycloak nicht (SAM-SPA-Fallback statt Keycloak-Antwort);
  `/grafana/` liefert keine Grafana-Antwort; auf `<ingress-ip>`
  antworten nur TCP 80 und 443 (Stichprobe 8080, 9000, 8008, 55555 und
  ein NodePort: Timeout); `kaks get svc -A` zeigt genau einen Service
  vom Typ LoadBalancer (Traefik); `kaks` vom Hotspot ohne
  `aks-allow-me.sh` läuft in den Timeout.
- gRPC aus dem Internet: Mit bestätigter öffentlicher Reflection
  (AKS-E16) zeigt `grpcurl <fqdn>:443 list` mit 0.1.3 den
  PurchaseTransactionService, mit 0.1.4 alle drei Dienste, und Postman
  "Using server reflection" sieht mit 0.1.4 alle drei Dienste; ohne
  Bestätigung scheitert `list`, und alle Aufrufe laufen per
  `-protoset`. Je ein lesender Aufruf an wws und loyalty gelingt (mit
  0.1.3 per `-protoset build/descriptors/showcase.pb`); `grpcurl
  <fqdn>:443 grpc.health.v1.Health/Check` scheitert (kein Pfad).
  `kaks get ingress -A -o json` enthält jeden Reflection-Pfad genau
  einmal (ohne Bestätigung gar nicht), also kein `p2-grpc` mehr.
- `public-guard`: Eine Schleife von einer IP auf `POST /api/demo/reset`
  (`{"scope": "booth"}`) bekommt nach dem Limit 429, ebenso die
  (Limit+1)-te SSE-Verbindung auf `/api/events` und eine
  grpcurl-Schleife auf einen lesenden WWS-RPC über dem gRPC-Limit; ein
  Kiosk an einer anderen IP läuft dabei ohne Fehler; das
  Traefik-Access-Log (an seit P2) zeigt die echte Client-IP, nicht die
  Node-IP.
- Routen: Der Routentest aus Schritt 2 ist grün; `/freigabe`, `/foto`,
  `/op` und `/etikett` liefern auf `<fqdn>` keine gpos-Antwort,
  solange Frage 23 offen ist.
- Hygiene: `check_hygiene.sh` und `check_hygiene.sh --platform`
  (`SAM_HOME`/`SAM_URL` des AKS-Ziels) sauber. Image-Teil wie A13
  (UC1-BUILD-SPEC.md:6418-6419) gegen die ACR-Ref per Digest
  (arm64-Variante, nach `az acr login`), nicht per `kubectl exec` (Pods
  mounten das GEBIT-Secret absichtlich unter `/descriptors`):
  `docker run --rm --entrypoint sh <acr>.azurecr.io/gpos-demo/gpos-demo@<digest>
  -c "find / -xdev \( -name '*.pb' -o -name '*.proto' -o -name
  'purchase-api*' -o -name 'receipt-api*' -o -name 'simpleSale*' \)
  2>/dev/null"`. Einziger erwarteter Treffer ist
  `/app/descriptors/showcase.pb` (eigener Showcase-Descriptor [Quelle:
  gpd app/Dockerfile:8-9, 19]); keine `.proto`-, `purchase-api*`-,
  `receipt-api*`- oder `simpleSale*`-Datei, keine LLM- oder
  Key-Variable in der Image-Umgebung, User 10001:10001. Gilt für 0.1.3
  und 0.1.4.
- `TARGET=aks scripts/uninstall.sh` mit einer `.env.aks` ohne `SAM_URL`
  bricht vor dem ersten `api()`- oder kubectl-Aufruf ab (`set -x`-Log).
- In allen Namespaces kein Image mehr von Docker Hub (Prüfung wie P2
  mit `-A`).
- Lab danach: Overlay-Render identisch zur Baseline (bis auf den
  Tag-Commit 0.1.4), `make smoke` und S1 grün.

**Abhängigkeiten:** P5; P2 (Traefik mit IngressClass `nginx`,
`externalTrafficPolicy: Local`, Default-Zertifikat, Access-Log); P3
(Keycloak unter `/auth`); schriftliche Owner-Bestätigung zur
Azure-Abdeckung der GEBIT-Freigabe (AKS-E16, Status offen; ohne sie
läuft die Demo nur im Lab oder in L3); Owner-Antwort zu Frage 23 für
`/freigabe`, `/foto`, `/op`, `/etikett`; Leih-Router (11.12.);
TR3-Stand im Lab.

### P7 Härtung und Betrieb (4,25 PT, KW3-KW7, Gates G3 und G4)

**Ziel:** Drills bestanden, Backups getestet, Runbook steht, Betreiber
und Stellvertreter einsatzbereit, Freeze ohne Überraschungen. Ein Node
ohne HA (Owner-Entscheidung 17.11.2026): Es gibt keinen N-1-Drill mehr;
jeder Node-Vorgang ist ein Ausfall von einigen Minuten, den
Wartungssperre, Refresh-Termin und L3 abfangen.

**Schritte:**

1. Requests mit einer Woche AKS-Prometheus-Daten nachziehen; die Summe
   der Requests bleibt bei höchstens 92 % CPU und 75 % RAM des einen
   Nodes (Allocatable aus P1, Grenzen wie in 3.2).
2. Backups vor G3, jeweils im Pod erzeugt; nur der fertige Dump geht
   auf den Mac:
   - Vollständig: Keycloak-DB, SAM-WebUI-DB, gpos-DB
     (`kaks -n gpos-data exec gpos-postgres-0 -- pg_dump -Fc gpos`).
   - SAM-Plattform-DB `sam-solace-lab_platform` nur in
     `agent-mesh-postgresql-0` mit `pg_dump -Fc
     --exclude-table-data='*.model_configurations'
     --exclude-table-data='*.gateway_deployments'` (plus jede Tabelle
     aus der Metadatenabfrage in P5), nie die ganze DB mit Filter auf
     dem Mac [Quelle: amd scripts/models/README.md:77-79].
   - GEBIT-Prüfung (`check_hygiene` scannt keine Dumps): Die DB enthält
     kein Descriptor-Set, es kommt nur aus dem Secret-Mount.
     `pos.receipt.receipt_b64` enthält Demo-Belege im Format der
     GEBIT-Receipt-API; ob das GEBIT-Material ist, entscheidet der Owner
     (Abschnitt 9); im Zweifel `--exclude-table-data=pos.receipt`.
   - Zählprüfung je Dump, ohne Ausgabe von Treffern:
     `pg_restore -l <dump> | grep -cE 'TABLE DATA [^ ]+
     (model_configurations|gateway_deployments) '` ergibt 0;
     `pg_restore -f - <dump> | grep -c -F -f <(printf '%s\n'
     "$LLM_SERVICE_API_KEY")` ergibt 0, die Variable aus `amd/.env.aks`
     geladen, nie ausgegeben.
   - Restore-Test in einen Scratch-Pod; danach `SAM_PROFILE=aks
     provision.sh` (Modelle `fast`/`planning` mit Key aus
     `amd/.env.aks`, max_tokens, Pricing, developer-mcp; der Chart-Seed
     ist insert-only) und `install.sh mesh` (nie `--prune`, legt
     `gateway_deployments` neu an); der Owner setzt manuelle
     Alias-Einstellungen (Thinking/Effort) neu. Fremdschlüssel auf
     `model_configurations` sind ungetestet [A]; scheitert
     `pg_restore` daran, Reihenfolge dokumentieren (ohne Constraints
     restoren, provision, Constraints anlegen).
   - Ablage: chmod 600, außerhalb aller Repos und Cloud-Sync-Ordner,
     verschlüsselt (z. B. `age`) empfohlen; nie nach Key Vault, ACR oder
     Blob; Löschung in Schritt 8.
   - Das eine Ingress-Zertifikat (Namespace `traefik`,
     Default-TLSStore, P2; dazu eine `sam-tls`-Kopie, falls P2 sie
     anlegt) als volles Secret-Objekt in JSON, mit `data`, allen
     `cert-manager.io/*`-Annotationen (issuer-name, issuer-kind,
     issuer-group, certificate-name, alt-names, common-name) und Labels,
     ohne Cluster-Felder (Limit 25 KB, ein TLS-Secret hat rund 7-8 KB):

     ```bash
     kaks -n <ns> get secret <x> -o json | jq 'del(.metadata.uid,
       .metadata.resourceVersion, .metadata.creationTimestamp,
       .metadata.managedFields, .metadata.ownerReferences)' |
       az keyvault secret set --vault-name <kv> -n tls-<ns>-<x> \
         --file /dev/stdin -o none
     ```

     Per Pipe, ohne Zwischendatei: Das JSON enthält `tls.key`,
     `tls-backup.sh` läuft aus `sli/aks/`, und der Owner committet
     direkt auf master (Muster wie `newsecret` in P1 Schritt 3).
     Braucht ein Werkzeug doch eine
     Datei, dann nur mit `umask 077; f=$(mktemp); trap 'rm -f "$f"'
     EXIT`. Nicht `az keyvault certificate import`: Es verwirft die
     Annotationen, und cert-manager stellte dann wegen IncorrectIssuer
     neu aus [A]. Die EAB-Zugangsdaten des Rückfall-Issuers liegen nur
     in Key Vault und `.env.aks` (P2), nie in einem Dump.
   - Keine CSI-VolumeSnapshots: `pg_dump` mit Restore-Test ist der
     einzige Backup-Pfad; das SAM-Postgres-PVC würde den Key enthalten.
3. Drills vor G3 [Quelle: PLAN 0.3 G3; PLAN 8.6]:
   - Neuaufbau: `az group delete -n rg-eurocis-aks` (nimmt
     `rg-eurocis-nodes` mit), dann alles aus Skripten inklusive der
     Wartungskonfigurationen mit beiden Sperrbereichen und der
     API-Server-Allowlist aus der Liste von `aks-allow-me.sh` (P1);
     Rollen des Stellvertreters neu (neue `<aks-id>`); Federated
     Credentials nur, falls noch eine Workload Identity besteht [A: mit
     HTTP-01 braucht cert-manager keine]. `pip-aks-ingress` (Label,
     Lock `CanNotDelete`) und die Rolle Network Contributor der
     Control-Plane-Identität auf `rg-eurocis-base` bleiben; `<fqdn>`,
     Ingress-IP, Kiosk-URLs und QR-Codes ändern sich nicht.
     TLS: das Secret direkt nach dem Anlegen des Namespace `traefik`
     einspielen, vor dem Certificate-Objekt, vor Traefik mit
     Default-TLSStore und vor dem SAM-Install; sonst den Drill nur gegen
     den LE-Staging-Issuer. Jeder Drill ohne wirksames Backup verbraucht
     eine von 5 Ausstellungen für das Namensset `<fqdn>` in 7 Tagen
     (aufgefüllt um eine je 34 h). Als Erneuerung desselben Sets zählt
     sie nicht gegen das Limit von 50 je Woche, das sich alle
     Azure-Kunden für `azure.com` teilen (`cloudapp.azure.com` fehlt auf
     der Public Suffix List) [Quelle: `letsencrypt.org/docs/rate-limits`;
     `publicsuffix.org/list/public_suffix_list.dat`, 17.11.]. Scheitert
     LE trotzdem, stellt der vorbereitete Rückfall-Issuer mit EAB aus
     (P2). `export-le-certs.sh` stellt nichts aus.
   - 24-h-Lauf mit 450 Läufen/h von Mo 18.01. 12:00 bis Di 19.01.
     12:00, also nicht über das Mittwochsfenster (der 20.01. ist
     zusätzlich gesperrt); danach Neustart von awe allein, der Lauf geht
     weiter [Quelle: PLAN 8.6]. Der Lastgenerator läuft clusterintern
     oder über den Port-Forward auf gpos-ui, damit `public-guard` ihn
     nicht drosselt [A]. 3 Stop/Start-Zyklen mit je mindestens 30 min
     Pause (zusammen rund 2,5-3 h [A]). Kein N-1-Drain (ein Node).
   - 10-h-Kiosklauf (AP11) parallel zum 24-h-Lauf: `/monitor`,
     `/kasse` und `/kunde` im Kiosk-Browser der Messe-Hardware über den
     öffentlichen Ingress (Leih-Router, Kabel-Uplink) gegen AKS
     [Quelle: PLAN 6 AP11; PLAN 8.6]; `/kunde` hat bis dahin seinen
     Pfad im aks-Overlay (Routentest aus P6 Schritt 2). `/freigabe`
     läuft im Kiosklauf nur dann über den öffentlichen Ingress, wenn
     der Owner die Seite öffentlich gemacht hat (Frage 23); sonst über
     den Weg, den er gewählt hat (Port-Forward, Lab oder Schutz am
     Ingress) [A]. Bis zur Antwort gilt für `/freigabe`: Pfad
     vorgesehen, Exposition offen.
   - Netz: TR1 über den Leih-Router mit Kabel, dann Kabel ziehen und
     Umschaltung auf 5G während eines Laufs; die Kiosk-Seiten verbinden
     SSE neu, ohne 429 durch die Reconnects. kubectl vom 5G-Netz nach
     `aks-allow-me.sh` (Ausbreitung bis 2 min) und einmal ohne
     Allowlist-Eintrag per `az aks command invoke` [Quelle:
     `learn.microsoft.com/azure/aks/api-server-authorized-ip-ranges`;
     `learn.microsoft.com/azure/aks/access-private-cluster`]. Die
     Negativtests aus P6 von außen wiederholen.
   - Missbrauchs- und Kostentest (neu):
     - Rate-Limits: Skript-Schleifen von einer IP auf `POST /api/pos/`,
       `POST /api/demo/reset`, `GET /api/events`, auf die drei
       gRPC-Service-Pfade und, falls öffentlich (Frage 23), auf den
       Foto-Upload bekommen 429; die Standgeräte hinter einer NAT-IP
       (zwei Kassen, Monitor, Tablet) bleiben im Normalbetrieb
       darunter.
     - LLM-Deckel: Der Owner lässt sich `rpm_limit`, `tpm_limit` und
       das Budget des Messe-Keys vom LiteLLM-Betreiber bestätigen
       (Werte nicht in diesem Dokument; der Key-Wert bleibt nur in SAMs
       Modellkonfiguration) [Quelle: `docs.litellm.ai/docs/proxy/users`;
       PLAN 0.5 O5]. Dann ein kurzer Burst von Reviews über den
       Port-Forward auf gpos-ui (umgeht `public-guard`) bis zur ersten
       429 von LiteLLM: Die Demo fällt auf L1, ohne Hänger, und läuft
       nach Ablauf des Fensters wieder [Quelle: PLAN 9 R24] [A: Kosten
       wenige USD]. Ohne Deckel kostet eine Schleife mit einer Prüfung
       alle 5 s rund 7-36 USD/h [A; Quelle: PLAN 9 R24].
   - L3-Drill (AP14b): Lab-MacBook im Profil `l3`, Router-DNS-Eintrag
     `<fqdn>` → Lab-MacBook eingeschaltet [Quelle: PLAN 6 AP14b]. Mit
     einem Namen übernimmt L3 das AKS-Pfadlayout: gpos-Pfade,
     gRPC-Service-Pfade und Keycloak unter `/auth` auf `<fqdn>`, mit dem
     exportierten Zertifikat. Wie Keycloak im Lab unter `/auth` läuft,
     klärt AP14b [A: Änderung an geteilter Lab-Infra mit eigener
     Freigabe oder eine eigene L3-Keycloak-Instanz]. Der Wechsel `lab`
     ↔ `l3` ist umkehrbar und endet mit dem Lab-Regressions-Gate.
   - Tempo: Füllstand des Tempo-PVC nach dem 24-h-Lauf ablesen. Die
     Retention bleibt 48 h; nur bei Reserve im aks-Overlay auf 168 h
     erhöhen (AKS-E15), sonst bleiben die Span-Metriken 7 Tage in
     Prometheus.
4. Runbook und `preflight.sh TARGET=aks`: öffentliche Endpunkte
   (`https://<fqdn>/kasse`, `/monitor`, SAM `/`, OIDC-Discovery unter
   `/auth/realms/solace-lab/`, gRPC-Reflection auf 443, falls nach
   AKS-E16 geroutet), Zertifikat
   (Ablauf, Aussteller LE oder Rückfall), Broker-Spool, SAM-Health,
   Modellprobe, Inbox-Token, gRPC-Health (clusterintern), Node Ready und
   Node-Image. Erster Schritt für jeden Betreiber morgens: eigene IP mit
   `aks-allow-me.sh` in die Allowlist, dann ein nicht-interaktiver
   Aufruf über kubelogin: `kaks auth can-i get pods -n gpos-demo`;
   scheitert er, meldet sich die Person selbst mit `az login` an, vor
   Standöffnung. Runbook-Regeln: Start frühestens 30 min nach Stop;
   Umfang des Stellvertreters (Schritt 7); bei Missbrauch die
   betroffene Route sperren (Limit senken oder Pfad-Ingress löschen,
   Freeze-Ausnahme), bei 429 vom Messe-Key L1 [Quelle: PLAN 9 R24].
   Keycloak-Admin ist seit P3 nicht über den Ingress erreichbar; P7
   prüft das nur noch.
5. Di 26.01., nach Ende eines eventuell laufenden Auto-Vorgangs:
   `az aks nodepool upgrade --node-image-only` als letztes Node-Image
   vor der Sperre (ab 27.01.). Mit einem Node ersetzt AKS ihn per Surge
   (8 vCPU Quota für den Surge-Node, 3.5) und zieht alle Pods samt
   Disks um: einige Minuten Ausfall [A: Dauer messen, ins Runbook];
   deshalb an keinem Probetag und während keines Laufs. Danach `az aks
   nodepool show --query nodeImageVersion` und Name, Label
   `kubernetes.azure.com/node-image-version` und `bootID` notieren:

   ```bash
   COLS='NAME:.metadata.name,BOOT:.status.nodeInfo.bootID'
   COLS="$COLS,IMG:.metadata.labels.kubernetes\.azure\.com/node-image-version"
   kaks get nodes -o custom-columns="$COLS"
   ```

   Das Label allein reicht nicht, weil SecurityPatch auch ohne
   VHD-Wechsel live patchen kann. `bootID` ändert sich mit jedem
   Nachtstopp; verglichen wird er erst im 24/7-Betrieb ab 05.02.
   Probetage 1-3 (28.01., 29.01., 03.02.), G4 und Messe laufen auf
   diesem Image.
6. Um den 15.01. (vor dem Neuaufbau-Drill in KW3): das eine Zertifikat
   mit `cmctl renew -n traefik ingress-tls` erneuern. Ein
   90-Tage-Zertifikat vom 15.01. läuft bis rund 15.04.; cert-manager
   erneuert nach zwei Dritteln der Laufzeit, also um den 15.03., nach
   der Messe. Das Zertifikat aus P2 (Anfang Dezember) würde dagegen
   Anfang Februar im Freeze erneuert [A: Ausstellungstag in P2]. Der
   LE-Wechsel auf 64 Tage am 10.02.2027 betrifft es nicht [Quelle:
   `letsencrypt.org/ca/upcoming-features`]. Als Erneuerung desselben
   Sets zählt die Bestellung nicht gegen das geteilte `azure.com`-Limit.
   Danach TLS-Backup (Schritt 2), eine `sam-tls`-Kopie aktualisieren
   (falls P2 sie anlegt; eine Kopie erneuert sich nicht selbst) und
   `export-le-certs.sh` für L3. Die L3-Kopie von Zertifikat und
   Schlüssel liegt nur als K8s-Secret im Lab-Cluster (Profil `l3`)
   oder als Datei mit chmod 600 außerhalb aller Repos und
   Sync-Ordner; Löschung in Schritt 8.
7. Betrieb mit Betreiber und Stellvertreter (AKS-E20,
   Owner-Bestätigung offen):
   - Bis G3 bekommt der Stellvertreter: "Azure Kubernetes Service RBAC
     Cluster Admin" auf `<aks-id>` (enthält
     `listClusterUserCredential`); eine eigene Rolle mit
     `Microsoft.ContainerService/managedClusters/read`,
     `.../runcommand/action`, `.../commandResults/read`,
     `.../start/action` für `az aks start` und Break-glass sowie
     `.../write` für `aks-allow-me.sh` (`az aks update` ersetzt die
     ganze Liste), ohne `delete`, `stop/action`, Agent-Pool-Rechte und
     `listClusterAdminCredential` [A: `az aks update
     --api-server-authorized-ip-ranges` braucht nur `write`]. Die
     AKS-Contributor-Rolle ginge auch, erlaubt aber zusätzlich stop und
     delete. Dazu "Key Vault Secrets User" auf `<kv>`, ein eigener
     Allowlist-Eintrag, eigener Keycloak-User und eigenes `SAM_HOME`
     (P5). Er meldet sich selbst an; Owner und Claude geben nie seine
     Passwörter ein.
   - Direkt nach der Zuweisung, vor G3: Der Stellvertreter ruft
     `aks-allow-me.sh` mit seinem eigenen Konto auf. `az aks update`
     schickt das ganze Cluster-Objekt, das auf `id-aks-cp`, das
     BYO-Subnetz und `pip-aks-egress` in `rg-eurocis-base` verweist;
     eine Rolle nur mit `managedClusters/write` kann deshalb mit
     `LinkedAuthorizationFailed` scheitern [A]. Dann kommen
     `Microsoft.ManagedIdentity/userAssignedIdentities/assign/action`
     auf `id-aks-cp` sowie
     `Microsoft.Network/virtualNetworks/subnets/join/action` und
     `Microsoft.Network/publicIPAddresses/join/action` auf
     `rg-eurocis-base` dazu [A]. Der Lauf an Probetag 1 ist nur noch
     Wiederholung.
   - GEBIT: Jede schreibende AKS-RBAC-Rolle liest Secrets, also auch
     `gpos-gebit-descriptors`. Deckt die GEBIT-Freigabe den
     Stellvertreter nicht ab [A, P6 Schritt 1], bekommt er seine
     Datenrolle nur je Namespace ohne `gpos-demo` (oder "RBAC Reader");
     ein Fehler in `gpos-demo` heißt dann L3, und nur der Owner stellt
     das Descriptor-Secret wieder her.
   - Umfang des Stellvertreters: Preflight, `aks-allow-me.sh`,
     `aks-start.sh`, Pod- und awe-Neustarts, Backups, Umschaltung auf L3
     oder L4. Kein Neuaufbau und kein SAM-Helm-Upgrade
     (Descriptor-Secret nur vom Owner-Mac, LiteLLM-Key nur in dessen
     `amd/.env.aks`).
   - Laufzeiten bis G4: nachts stoppen mit `aks-stop.sh`/`aks-start.sh`
     (Start frühestens 30 min nach Stop, Start 60 min vor Bedarf),
     Abend-Check (P1) bis 05.02.; am 18./19.01. kein Stopp (24-h-Lauf).
     Der Free-Tier bleibt für das ganze Projekt.
   - Ein Node: Jeder Node-Vorgang (reaktive Wartung, VM-Fehler) ist ein
     Ausfall des ganzen Clusters; PDBs helfen dabei nicht. Der
     Resource-Health-Alarm (P1) meldet ihn; ist der Node nicht binnen
     weniger Minuten Ready, schaltet das Runbook auf L3 [A: Schwelle im
     Runbook festlegen].
   - Ab 05.02.: Freeze, 24/7, kein `az aks stop` bis 19.02., Preflight
     jeden Morgen durch den Betreiber, L3 warm, Netztest am 14.02.
     [Quelle: PLAN 0.3 Messe]. Im Freeze sind nur erlaubt:
     `aks-allow-me.sh` (ändert nur die IP-Liste, bis 2 min), das Sperren
     einer Route bei Missbrauch und ein Traefik-Sicherheitspatch nach
     Owner-Freigabe (nie unter v3.7.18) [A]. Am Morgen des 14.02. melden
     sich Owner und Stellvertreter frisch an (bei kurzer
     Conditional-Access-Frequenz täglich) und tragen die IP des
     Stand-Uplinks ein.
   - Tägliche Backups wie Schritt 2, inklusive gpos-DB, nach jedem
     Messetag nach Standschluss und vor `reset.sh --scope day` (damit
     auch der 18.02. gesichert ist).
8. Nach der Messe (19./20.02.), jeder Schritt erst nach Erfolg des
   vorigen:
   - (1) Export auf den Mac, nie in Git: gpos-DB, SAM-WebUI-DB,
     Plattform-DB mit den Ausschlüssen aus Schritt 2, Loki-Export für
     16.-18.02. (Loki hält 7 Tage) ohne die Traefik-Access-Logs
     (Client-IPs der Besucher). Tempo nur, falls die Retention erhöht
     wurde. Die Zählprüfungen aus Schritt 2 gelten auch für den
     Loki-Export: `[?&]token=` und der LiteLLM-Key ergeben je 0, ohne
     Treffer auszugeben.
   - (2) Descriptor-Material entfernen: `kaks -n gpos-demo scale deploy
     --all --replicas=0` (gpos-pos und gpos-ui halten den Mount), dann
     `kaks -n gpos-demo delete secret gpos-gebit-descriptors`; oder den
     Namespace `gpos-demo` löschen (die Demo-DB in `gpos-data` bleibt).
     Zeit und Befehlsausgabe protokollieren (AKS-E16).
   - (3) `az aks stop`; Disks und PVCs bleiben.
   - (4) `gpos-data` nur mit der Rückbau-Entscheidung oder der
     GEBIT-Übergabe löschen.
   - (5) Owner entscheidet Rückbau oder GEBIT-Übergabe. Rückbau: zuerst
     das Zertifikat für `<fqdn>` per ACME widerrufen (etwa `certbot
     revoke --cert-path <crt> --key-path <key> --server <directory>`
     mit einer Temp-Datei nach dem Muster aus Schritt 2; cert-manager
     widerruft nicht selbst [A: Werkzeug]), denn nach dem Rückbau ist
     das Label für jeden frei, das Zertifikat aber bis rund Mitte April
     gültig (Schritt 6). Dann den Lock `CanNotDelete` auf
     `pip-aks-ingress` entfernen (`az lock delete`), sonst scheitert
     die Löschung von `rg-eurocis-base` [Quelle:
     `learn.microsoft.com/azure/azure-resource-manager/management/lock-resources`];
     mit der IP wird das DNS-Label für jeden frei. Dann `az group
     delete` von `rg-eurocis-aks` und `rg-eurocis-base`
     (`rg-eurocis-nodes` geht mit dem Cluster). Ohne Übergabe danach
     `az keyvault list-deleted --query "[?name=='<kv>']" -o table` und
     `az keyvault purge -n <kv> -l germanywestcentral` (eigene Freigabe
     des Owners, nicht umkehrbar, braucht Purge-Recht; gibt den global
     reservierten Namen frei). Den EAB-Zugang beim Rückfall-Anbieter
     schließt der Owner; den Messe-Key deaktiviert der
     LiteLLM-Betreiber (O5) und bestätigt das schriftlich. Alle Dumps,
     Scratch-DBs und die L3- und Backup-Kopien des Zertifikats löschen;
     dazu die lokalen Dateien mit Secrets: `amd/.env.aks`
     (LiteLLM-Key, OIDC-Client-Secret, PG- und Broker-Passwörter),
     `gpd/.env.aks`, `sli/aks/.env.aks` (EAB),
     `gpd/mesh/.rendered/aks/semp.tfvars`, `gpd/.rendered-aks/`, den
     State unter `emd/terraform-aks/` (Client-Passwörter im Klartext),
     `~/.kube/aks-eurocis.yaml` und das AKS-`SAM_HOME` mit
     Token-Cache. Widerruf, Löschungen und Key-Deaktivierung
     protokollieren; Budget, Abend-Check und die lokale Liste von
     `aks-allow-me.sh` entfernen.
9. Doku: AKS-Abschnitte in README und RUNBOOK, Drift korrigieren (siehe
   Abschnitt 8), markdownlint.

**Wer:** Claude 1-6, 9; Betreiber und Stellvertreter (AKS-E20) 7 und
die Probetage; Owner Freigaben, Bestätigung der Key-Limits beim
LiteLLM-Betreiber, Drill-Teilnahme, 8.

**Abnahme:**

- G3: Neuaufbau bis Preflight READY in höchstens 4 h [Quelle: PLAN 6
  AP13]; `<fqdn>` und Ingress-IP danach unverändert; nach dem
  TLS-Restore zeigt `kaks get certificaterequest -A` keine neuen
  Requests, das Certificate ist Ready, `notAfter` gleich dem Backup
  (`openssl x509 -noout -enddate`); 24-h-Lauf ohne OOMKilled und ohne
  NotReady; 10-h-Kiosklauf über den öffentlichen Ingress mit 0
  manuellen Reloads, Browser-Speicher stabil (±20 %), Attract-Loop
  läuft; aus gestopptem Cluster bis READY in höchstens 30 min, gemessen
  ab `az aks start` [A: Zielwert]; L3-Drill höchstens 3 min [Quelle:
  PLAN 6 AP14b]; Restore-Test aller Dumps grün, Zählprüfungen 0;
  Missbrauchs- und Kostentest grün (429 auf allen geschützten HTTP-
  und gRPC-Routen, Kiosk unbeeinflusst, Key-Limits bestätigt,
  L1-Rückfall gesehen); Rollen, Allowlist-Eintrag und Keycloak-User
  des Stellvertreters bereit, `aks-allow-me.sh` mit seinem Konto
  einmal grün. Fehlt TR3 aus P6, folgt es hier.
- Probetag 1 (28.01.): Runbook-Durchlauf des Stellvertreters mit
  eigenem Konto, inklusive `aks-allow-me.sh` aus seinem Netz
  (Wiederholung); vor G4 (z. B. 03.02.) einmal Break-glass mit
  `az aks command invoke` mit eigenem Konto.
- G4: 100 Läufe mindestens 98 % ohne Rückfall [Quelle: PLAN 0.3 G4];
  das Certificate hat `notAfter` nach dem 10.04.2027 und
  `status.renewalTime` nach dem 20.02.2027; `az aks
  maintenanceconfiguration show` zeigt beide Sperrbereiche auf allen
  drei Konfigurationen; Node-Image (`nodeImageVersion` und Label
  `kubernetes.azure.com/node-image-version`) am 28.01., 03.02. und
  05.02. gleich dem Stand nach dem Refresh am 26.01.; `bootID` nur
  innerhalb eines Laufs ohne Stopp vergleichen, weil jeder
  Nachtstopp die Node-VM neu bootet (ab 05.02., 24/7: 05.02. gegen
  16.02.); das
  Activity Log (`az monitor activity-log list` auf die
  Cluster-Ressource) zeigt zwischen 27.01. und 05.02. keinen
  automatischen Node-OS- oder Upgrade-Vorgang; nach dem letzten Start
  vor dem 05.02. funktioniert kubectl vom 5G-Netz nach
  `aks-allow-me.sh`; Preflight READY in unter 15 min aus kalt [Quelle:
  PLAN 6 AP14].
- Messe: Node-Image-Vergleich am 16.02. wie bei G4, dazu `bootID`
  gleich dem Wert vom 05.02. (seitdem kein Stopp); die Allowlist
  enthält nur aktuelle Einträge.
- Löschung des Descriptor-Secrets bis 20.02.2027 protokolliert; Dumps,
  Zertifikatskopien und lokale Secret-Dateien nach der Messe gelöscht,
  das Zertifikat vor der Freigabe des Labels widerrufen, der Messe-Key
  deaktiviert; alles protokolliert.

**Abhängigkeiten:** P6; Netzparameter des Stands (Uplink mit
ausgehendem HTTPS, 5G-Option, fällig 18.12. [Quelle: PLAN 6.5]);
Kiosk-Hardware und `/monitor` live (G2b); `aks-allow-me.sh` (P1);
Bestätigung der Key-Limits durch den LiteLLM-Betreiber; AKS-E20
(Owner-Bestätigung offen).

## 5. Notwendige Änderungen je Repo

Grundsatz: AKS kommt als additives Profil dazu. Lab-Pfade und
Lab-Defaults bleiben unverändert, belegt durch Call-Log- und
Render-Diff (P0 Schritt 13). Die Freigaben AKS-E15 (a) bis (e) hat der
Owner am 17.11.2026 erteilt; (a) ist mit Commit `cd08a17` erledigt.
Einzige gewollte Lab-Änderung ist das Broker-Upgrade in 5.3 (P4 Teil
A, 1,0 PT); es braucht ein eigenes Go des Owners und ein
Wartungsfenster. `<fqdn>` steht in diesem Plan für
`<p>.germanywestcentral.cloudapp.azure.com`.

### 5.1 solace-lab-infrastructure (geteilt, Freigabe AKS-E15 (c))

- Neuer Ordner `aks/`, nur neue Dateien:
  - `versions.env` (Traefik-Chart 42.4.1, Image `traefik:v3.7.19` per
    Digest und nie unter v3.7.18, cert-manager v1.21.3, Monitoring in
    den Lab-Versionen), `lib.sh` (`kaks`/`haks`,
    `require_kube_context` mit Prüfung der Server-URL).
  - `foundation.sh`, idempotent show-or-create: RGs, VNet nur mit
    `snet-aks`, `pip-aks-egress` und `pip-aks-ingress` (Standard,
    statisch, DNS-Label `<p>`, Lock `CanNotDelete`), UAMI `id-aks-cp`
    mit Network Contributor auf `rg-eurocis-base` (Subnetz und beide
    IPs) über `--assignee-principal-type`, ACR mit curl und whoami, Key
    Vault mit Secrets-Officer-Zuweisung (nur wenn sie fehlt),
    Warteschleife und Secrets nach P1 Schritt 3 (create-if-missing,
    hex, `-o none`). Eine gelöschte IP gibt das Label für jeden frei;
    der Lock verhindert das [Quelle:
    `learn.microsoft.com/azure/aks/static-ip`].
  - `aks-allow-me.sh` mit Kontext-Guard: liest
    `apiServerAccessProfile.authorizedIpRanges`, ergänzt die aktuelle
    öffentliche IP als /32 und schreibt die vollständige Liste mit
    `az aks update --api-server-authorized-ip-ranges`. Der Aufruf
    ersetzt die ganze Liste und braucht bis 2 min [Quelle:
    `learn.microsoft.com/azure/aks/api-server-authorized-ip-ranges`];
    das Skript entfernt deshalb nie stillschweigend einen Eintrag (nur
    mit `--prune <ip>`, nie den letzten), wartet und prüft danach
    `kaks get --raw /readyz`; dazu `--print` und `--check` (P1
    Schritt 7).
  - Wartungs-JSONs mit beiden Sperrbereichen (auch für den Neuaufbau).
  - `setup-aks.sh` mit Kontext-Guard; Values-Overlays für Traefik,
    cert-manager und Monitoring (Registry je Image, vollständige
    `additionalDataSources`, Grafana ohne Ingress).
  - Traefik-Values, mit den Lücken aus dem Annotations-Abgleich
    geschlossen [Quelle: Traefik v3.7.19
    `ingress-nginx.md`:265-502, `entrypoints.md`:128-130]:
    - NGINX-Provider an, `kubernetesIngress` aus, `kubernetesCRD` an
      (Middleware, TLSStore); eigene IngressClass `nginx` mit Controller
      `k8s.io/ingress-nginx`, weil der Chart sie nicht anlegt und der
      SAM-Install sonst abbricht [Quelle: SAM-Chart 2.3.10
      `_validations.tpl`; Traefik `nginx-to-traefik.md`:630-728].
    - Genau ein LoadBalancer-Service, Ports 80 und 443, Annotationen
      `service.beta.kubernetes.io/azure-pip-name: pip-aks-ingress`,
      `azure-load-balancer-resource-group: rg-eurocis-base` und
      `azure-load-balancer-tcp-idle-timeout: "30"`, nie
      `azure-dns-label-name`; `externalTrafficPolicy: Local` für echte
      Client-IPs [Quelle: `learn.microsoft.com/azure/aks/static-ip`;
      `.../configure-load-balancer-standard`].
    - `ports.websecure.transport.respondingTimeouts.readTimeout:
      3600s`; der Default 60 s schneidet HTTP/1.1-SSE und MCP ab.
    - Kein Redirect auf EntryPoint-Ebene, damit HTTP-01 auf Port 80
      durchkommt; HSTS als Headers-Middleware ohne
      `includeSubDomains`.
    - 1 Replika; Dashboard nur auf dem EntryPoint `traefik`, Zugriff
      per Port-Forward. Kein PDB, dessen `minAvailable` der
      Replikazahl gleicht: Er blockierte den Drain beim
      Node-Image-Update auf dem einzigen Node [A].
  - cert-manager v1.21.3 ohne Workload Identity; ClusterIssuer
    `letsencrypt-staging` und `letsencrypt-prod`
    (`solvers.http01.ingress.ingressClassName: nginx`); ein Certificate
    `ingress-tls` für `<fqdn>` in Namespace `traefik`, Default über
    `TLSStore default`. Rückfall-Issuer `acme-eab-fallback` (ZeroSSL
    oder Google Trust Services) nur als Vorlage: `keyID` und HMAC
    kommen beim Anwenden aus Key Vault (`acme-eab-kid`,
    `acme-eab-hmac`) und `.env.aks`, nie aus Git.
  - `tls-backup.sh`: sichert `ingress-tls` nach jeder Ausstellung als
    volles Secret-JSON mit den cert-manager-Annotationen im Key Vault,
    per Pipe ohne Zwischendatei (`--file /dev/stdin -o none`, AKS-E17,
    P7 Schritt 2).
  - `.gitignore` (P0 Schritt 10, erste Datei im Ordner): `.env.aks`,
    `*.pem`, `*.key`, `*.json` mit Ausnahme `!maint-*.json`.
  - VAP nach P2 Schritt 3: Service `LoadBalancer` nur für
    `traefik/traefik` mit `pip-aks-ingress` und
    `azure-load-balancer-resource-group: rg-eurocis-base`, nie
    `azure-dns-label-name`;
    Ingress nur mit Klasse `nginx` und Host `<fqdn>`, ohne
    `*-snippet`, `mirror-*` und `cert-manager.io/*`, mit `spec.tls`
    (Solver-Ingresses mit Label
    `acme.cert-manager.io/http01-solver=true` ausgenommen); Certificate
    nur in `traefik` mit den drei Issuern. PriorityClasses wie bisher.
  - `keycloak/` (kustomization mit den Lab-Manifesten als einzeln
    gelisteten Ressourcen, Realm-JSON-Kopie, Patches für den Pfad
    `/auth`: `KC_HTTP_RELATIVE_PATH=/auth`,
    `KC_HOSTNAME=https://<fqdn>/auth`,
    `KC_HTTP_MANAGEMENT_RELATIVE_PATH=/`, damit die Probes auf
    `/health/*` an Port 9000 bleiben; `KC_HOSTNAME_ADMIN` nur, wenn P3
    ihn braucht; Ingress nur für `/auth/realms/solace-lab/` und
    `/auth/resources/`) [Quelle: `www.keycloak.org/server/hostname`].
  - `aks-start.sh`, `aks-stop.sh` (30-min-Sperre; `aks-start.sh`
    prüft die Allowlist mit `aks-allow-me.sh --check`).
- Was gegenüber dem Stand vom 16.11. entfällt, steht in 8.5.
- Kein Eingriff in `ingress/`, `pki/`, `registry/` und die
  `keycloak/`-Lab-Skripte. Das Lab behält ingress-nginx; dieselben
  NGINX-Ingress-Manifeste laufen auf beiden Zielen. Traefik-eigene
  Teile (IngressClass, Middleware, TLSStore, Values) gibt es nur unter
  `aks/`, und P2 beweist sie zuerst. Hinweis: Die Lab-Skripte pinnen
  keine Chart-Version [Quelle: sli ingress/scripts/setup.sh:47-49;
  pki/scripts/setup.sh:49-52, 82-84, 137-139, 171-174, 184-186,
  193-195, 202-204]; Pinning im Lab ist eine eigene, optionale
  Freigabe. Ebenso eigene Freigabe: eine additive
  `keycloak/manifests/kustomization.yaml` (P3 Schritt 2).
- Keine GEBIT-Inhalte, daher versionierbar; Hygiene-Prüfung über die
  versionierten Dateien (`git ls-files aks/`):
  `grep -nE 'PRIVATE KEY|[A-Za-z0-9+/]{43}=|EAB_[A-Z_]+=.'` und
  `grep -noE '[A-Za-z0-9_-]{40,}' | grep -vE ':[0-9a-f]{64}$'` ohne
  Treffer; die zweite Prüfung fängt base64url-HMACs ohne Padding und
  nimmt nur reine Hex-Digests der Images aus. EAB-Werte nur im Key
  Vault und in `sli/aks/.env.aks`.

### 5.2 agent-mesh-deployment (geteilt, Freigaben AKS-E15 (a) und (b))

- Working Tree committet (`cd08a17`, 17.11.): SeaweedFS 2 CPU/2Gi,
  beide HIL-Flags, Sonnet 5 für `planning`, Preise für `fast`,
  `workflow` und `planning` [Quelle: amd
  scripts/models/set-pricing.sh:34-37].
- `scripts/lib/common.sh`: `SAM_PROFILE`, `.env.aks`, `KUBECONFIG`,
  `SAM_KUBE_CONTEXT`, `require_kube_context`, `kaks`/`haks` auf `aks`,
  `SAM_HOME` je Profil, `sam_helm_args <profil>` (gibt die Liste mit
  maskierten Secret-Werten aus). Auth-Cache unter dem Home statt fest:
  `SAM_AUTH_CACHE="${SAM_HOME:-$HOME/Library/Application
  Support/sam}/auth/solace-lab.json"` in common.sh:21 und stop.sh:15;
  sonst löscht ein AKS-`stop.sh` den Lab-Login (stop.sh:264-266). Die
  Login-Hinweise nennen `$SAM_URL`. Der URL-Guard (Cache-URL gegen
  `$SAM_URL`, sonst Abbruch) sitzt in `sam_auth_token`, weil curl und
  `sam api` davon abhängen (set-max-tokens.sh, set-pricing.sh,
  apply-rbac.sh:60, generate-manifest.sh). `SAM_AUTH_TOKEN`
  überschreibt den OAuth-Cache von `config plan/apply` nicht, nur
  `SAM_PLATFORM_TOKEN`.
- `start.sh`, `stop.sh`, `provision.sh`, `apply-rbac.sh`,
  `apply-models.sh`, `apply-entrypoints.sh`, `set-max-tokens.sh`,
  `set-pricing.sh`, `upgrade-preflight.sh`, `load-images.sh`:
  Konstanten aus dem Profil (Lab-Werte als Default),
  `--context rancher-desktop` bzw. die Wrapper, `--url` und
  `--no-dotenv`; CoreDNS-NodeHosts nur auf `lab`. `start.sh` prüft auf
  `aks` zusätzlich `SAM_BROKER_PASSWORD`, `SAM_SESSION_SECRET_KEY`,
  `SAM_PG_ADMIN_PASSWORD` und setzt
  `persistence-layer.postgresql.password` nur dort. `stop.sh` verlangt
  auf `aks` `SAM_SEMP_URL` und `SAM_SEMP_PASSWORD`, sonst gälte
  admin/admin [Quelle: amd scripts/stop.sh:150-163], und schluckt
  Fehler der Keycloak-Teardowns dort nicht mit `|| true`; optional
  überspringt es auf `aks` den Keycloak-Teardown ohne `--keycloak`.
  Vor dem ersten SEMP-DELETE prüft es auf `aks` die Broker-Identität
  wie `semp-aks.sh` (P0 Schritt 10): `localhost` und `127.0.0.1:8080`
  abgelehnt, nur der selbst geöffnete Port-Forward-Port 18080, VPN
  `amartens-test` und DMR-Node `solace-1` dürfen nicht existieren.
  Heute löscht `stop.sh` Queues unter `<ns>/q/` ohne Consumer auf der
  SAM-VPN und auf `SAM_EXTRA_CLEANUP_VPNS` (Default `default`), und
  `<ns>` ist auf Lab und AKS gleich [Quelle: amd
  scripts/stop.sh:150-212, 224].
- TLS auf `aks`, entschieden per Test in P2. Der SAM-Chart prüft ein
  `secretName` im eigenen Release-Namespace [Quelle: SAM-Chart 2.3.10
  `_validations.tpl`:110-113]:
  - Variante 1: SAM-Ingress mit `spec.tls.hosts`, aber ohne
    `secretName`; Traefik liefert das Default-Zertifikat aus dem
    TLSStore. `start.sh` rendert auf `aks` dann kein Certificate.
  - Variante 2: `start.sh` legt `sam-tls` vor `helm install` als Kopie
    des gesicherten Secrets an und zieht die Kopie nach jeder
    Erneuerung (um den 15.01.) nach.
  - Nie ein zweites Certificate für denselben FQDN: Je exaktem
    Namensset gibt es 5 Ausstellungen in 7 Tagen, ohne Override
    [Quelle: `letsencrypt.org/docs/rate-limits`]. Im Lab rendert
    `start.sh` das Certificate unverändert.
- `teardown-keycloak-client.sh` und `teardown-keycloak-users.sh`
  sourcen heute selbst die Lab-`.env`, haben den Default
  `auth.solace.lab` und nutzen `curl -sk` [Quelle: amd
  scripts/teardown-keycloak-client.sh:8-17, 28; stop.sh:88-90,
  247-249]. Neu: Konfiguration nur über `common.sh` (auf `aks` nur
  `.env.aks`, nie `$PROJECT_DIR/.env`); auf `aks` keine Defaults, ein
  fehlendes `KEYCLOAK_URL`/`KEYCLOAK_ADMIN_*` bricht vor jedem curl ab;
  ein Guard verweigert Hosts unter `solace.lab`, eine Admin-URL auf
  127.0.0.1 nur auf dem selbst geöffneten Port-Forward-Port; `curl`
  ohne `-k` auf `aks`, im Lab unverändert mit `-k`; `stop.sh` reicht
  `SAM_PROFILE` und Kontext durch.
- Keycloak-Setup-Skripte: `SAM_DNS_NAME`/`KEYCLOAK_URL` aus dem Profil;
  `KEYCLOAK_URL` trägt auf `aks` das Präfix `/auth`, die Skripte hängen
  `/realms/...` und `/admin/realms/...` daran an. Admin-API auf `aks`
  über `KEYCLOAK_ADMIN_URL` (Port-Forward, ebenfalls mit `/auth`).
  `setup-keycloak-client.sh` setzt auf `aks` `redirectUris` exakt auf
  `https://<fqdn>/api/v1/auth/callback` und `webOrigins` auf
  `https://<fqdn>`; eine Wildcard deckte auf dem geteilten Host auch
  die öffentlichen gpos- und Keycloak-Pfade ab. Das Lab behält
  `https://sam.solace.lab/*` [Quelle: amd
  scripts/setup-keycloak-client.sh:124-125]. Secret-Writeback in die
  Profildatei [Quelle: amd scripts/setup-keycloak-client.sh:22, 65-90].
  Mit eigener Freigabe: `--data-urlencode` statt `-d "password=..."`
  (setup-keycloak-client.sh:44, setup-keycloak-users.sh:58); durch
  hex-Secrets nicht zwingend.
- Grafana: `grant-grafana-platform-db.sh` bricht auf `aks` ab; neu
  `scripts/observability/grant-grafana-aks.sh` (P5 Schritt 5: Rolle mit
  Key-Vault-Passwort, CREATE oder ALTER ROLE, explizite Tabellenlisten,
  SQL per stdin).
- `provision.sh`: Schalter für developer-mcp, auf `aks` nach der
  Entscheidung in Abschnitt 9 (Default an wie im Lab); der Endpunkt
  wäre öffentlich, aber per OIDC geschützt.
- Neu: `aks-values.yaml`, `manifests/aks/` (NetworkPolicies nach P5
  Schritt 4), `.env.aks.example`; `.env.aks` in `.gitignore`, und zwar
  in P0 Schritt 10, bevor eine `.env.aks` existiert (heute ignoriert
  amd nur `.env`); README-Abschnitt "AKS".
- `aks-values.yaml` (ohne Secret-Werte): `sam.dnsName` und
  `ingress.host` = `<fqdn>`; SAM bekommt `/`, weil der Chart keinen
  Basispfad kennt und die WebUI fest an der Wurzel hängt [Quelle:
  SAM-Chart 2.3.10 `_config_helpers.tpl`:10-108,
  `templates/ingress.yaml`:27-41]; `ingress.className: nginx`;
  Annotationen `proxy-body-size: "10m"` [A] und
  `proxy-request-buffering: "on"` (sonst setzt Traefik das Limit nicht
  durch) sowie `limit-connections: "20"` [A] gegen volle
  Request-Puffer (P2 Schritt 5, Lücke 7); keine
  `cert-manager.io`-Annotation; Registry, Broker und Persistenz wie in
  P5 Schritt 2.
- Schlüssel in `.env.aks.example`:
  - Keycloak: `KEYCLOAK_URL=https://<fqdn>/auth`,
    `KEYCLOAK_ADMIN_URL=http://127.0.0.1:18081/auth` (Port-Forward),
    `KEYCLOAK_REALM=solace-lab`, `KEYCLOAK_ADMIN_USER`,
    `KEYCLOAK_ADMIN_PASSWORD` (Wert aus Key Vault).
  - OIDC: `KEYCLOAK_CLIENT_ID=solace-agent-mesh`,
    `KEYCLOAK_ISSUER=https://<fqdn>/auth/realms/solace-lab` (von Hand;
    `setup-keycloak-client.sh` schreibt nur `KEYCLOAK_CLIENT_SECRET`
    zurück), `KEYCLOAK_CLIENT_SECRET`.
  - Secrets: `LLM_SERVICE_API_KEY` (nur hier und in der
    SAM-Modellkonfiguration), `SAM_BROKER_PASSWORD`,
    `SAM_SESSION_SECRET_KEY`, `SAM_PG_ADMIN_PASSWORD`,
    `GRAFANA_RO_PASSWORD`, `SAM_SEMP_PASSWORD` (Werte aus Key Vault).
  - Pfade: `SAM_CHART_PATH`, `SAM_CLI_PATH`.
  - Ziel: `KUBECONFIG=~/.kube/aks-eurocis.yaml`,
    `SAM_KUBE_CONTEXT=aks-eurocis`, `SAM_HOME`,
    `SAM_DNS_NAME=<fqdn>`, `SAM_URL=https://<fqdn>`,
    `SAM_SEMP_URL=http://127.0.0.1:18080`.
  - Nicht enthalten: die `SAM_*_IMAGE_TAR`-Schlüssel (Images über ACR)
    und `GOOGLE_AI_STUDIO_API_KEY` (AKS stellt nur `fast` und
    `planning` bereit).
- Gate: Call-Log- und Render-Diff des Lab-Profils leer (P0 Schritt 13).

### 5.3 event-mesh-deployment (geteilt, Freigaben AKS-E15 (c) und (d))

AKS-Teil, nur neue Dateien:

- `aks/pubsubplus-values.yaml`: Image aus ACR per Digest
  (`solace/solace-pubsub-standard:10.26.0.9219`, Index
  `sha256:c0020e53ed48...`), `service.type: ClusterIP` explizit
  (Chart-Default wäre ein öffentliches LoadBalancer mit `latest`),
  `storage.useStorageGroup: true` ab dem ersten Install,
  `solace.usernameAdminPasswordSecretName: solace-admin`, Größe
  `prod1k` (Kriterium für `dev` in 3.2) [Quelle: pubsubplus
  3.10.0 values.yaml:113-133].
- `aks/lib.sh` (`kaks`), `aks/semp-aks.sh` (Port-Forward und
  Identitätsprüfung, schreibt kein Passwort). Die Prüfung akzeptiert
  `sempVersion` im neuen Format (Broker-Version) neben `2.x` [Quelle:
  `docs.solace.com/Admin/SEMP/SEMP-API-Versions.htm`; A: an einem
  10.26-Broker noch nicht gesehen].
- `terraform-aks/` (eigener Root, ein Provider-Alias, Provider exakt
  `= 1.3.0` mit eigener, versionierter Lock-Datei statt der Lab-Kopie,
  Module `vpn`/`client` wiederverwendet, State gitignored, Passwort per
  `TF_VAR_admin_password` aus dem Key Vault). Provider 1.3.0 und 1.4.0
  bestehen beide den API-Check [Quelle: terraform-provider-solacebroker
  internal/broker/resource.go:45, 101-111].
- `aks/semp-export.sh` (nur GET): SEMPv2-Export je VPN für die
  Baseline des Lab-Upgrades und den Vergleich auf AKS.

Lab-Teil: P4 Teil A, Broker-Upgrade 10.25.0.208 → 10.26.0.9219
(1,0 PT [A]; Freigabe AKS-E15 (d), dazu eigenes Owner-Go und ein
Wartungsfenster des SAM-Labs; Ablauf A1-A8 in P4, Probe an solace-2 in
KW48, solace-1 spätestens am 04.12.):

- Warum dieselbe Version wie AKS: SAM 2.542.1 nennt keine
  Broker-Version, sein eingebetteter Default ist 10.25.0.193 [Quelle:
  SAM-Chart 2.3.10 values.yaml:717-727]. AKS soll nicht der erste
  SAM-Test auf 10.26 sein. 10.26.0.9219 ist LTS (Tags `latest` und
  `lts`, Wartung bis 23.06.2028). 10.26.10 ist ein Rolling Release
  (Tags `edge` und `rolling`) ohne Wartungsreleases, mit Support nur
  bis zum nächsten LTS, und von dort führt kein Weg zurück auf
  10.26.0.x [Quelle: Docker-Hub-Tags-API 17.11.;
  `solace.com/support/support-dates-for-release-versions`;
  `docs.solace.com` Upgrade-Selector].
- Ausgangslage, schon heute eine Gefahr: solace-1 und solace-2 haben
  keine Mounts, beide Broker-DBs liegen im beschreibbaren
  Container-Layer, und die Compose-Hashes weichen von den Labels ab.
  Ein `start.sh` (`docker compose up -d`) würde beide Broker neu
  erzeugen und leeren; `stop.sh` (`docker compose down -v`) löscht sie
  [Quelle: Befehle `docker inspect` (Mounts) und `docker compose config
  --hash`, 17.11.; emd start.sh:4-6, stop.sh:2; A: per `docker compose
  up --dry-run` bestätigen]. Bis die emd-Skripte angepasst sind, gilt
  im emd-Lab: nur `docker start`/`docker stop` bzw. `docker compose
  stop`/`start`; kein `start.sh`, `stop.sh`, `compose up/pull/down`
  und kein Prune. Die Regel gilt auch nach der Migration weiter, weil
  `stop.sh` Terraform-State, Lock-Datei, tfvars und `.env` löscht und
  das nächste `start.sh` mit leerem State an den befüllten Brokern
  scheitert, bevor die DMR-Links aktiviert sind [Quelle: emd
  stop.sh:2-7; start.sh:2, 20-35].
- Geänderte Lab-Dateien (erst nach dem Go in A2):
  - `docker-compose.yaml`: je Broker ein Volume (`solace-1-storage`,
    `solace-2-storage`) auf `/var/lib/solace`, beide `external: true`,
    damit `down -v` sie nie löscht.
  - `.env.example`: `PUBSUB_IMG` mit Tag und Digest
    (`10.26.0.9219@sha256:c0020e53ed48...`), weil `start.sh` die
    `.env` daraus kopiert [Quelle: emd start.sh:4; .env.example:3].
  - `terraform/provider.tf`: Provider exakt `= 1.3.0`; `stop.sh`
    löscht die Lock-Datei, und `~> 1.2` zöge sonst 1.4.0 [Quelle: emd
    stop.sh:2-6; terraform/provider.tf:7].
  - Optional mit eigenem Owner-Go (P4 A4): `stop.sh` behält State,
    Lock-Datei und tfvars, `start.sh` ruft vor `apply`
    `terraform plan -detailed-exitcode` auf. In jedem Fall nennen der
    emd-README, der Abschnitt "Start and Stop" der sda-`CLAUDE.md` und
    die Memory-Notiz "Lab cleanup safety" den geltenden Lab-Zyklus.
- Ablauf in Kürze (Details P4 A1-A8): Baseline, `docker commit` als
  Rückfallpunkt, Volume per Copy-up auf derselben Version,
  `docker compose up -d --no-deps` je Broker (solace-2 zuerst, weil
  gestoppt und nicht im AKS-Pfad), DMR-Links und `terraform plan`
  leer, Lab-Flows belegt. Ein Downgrade ist nicht unterstützt; der
  Rückweg ist das Snapshot-Image ohne Volume. Snapshots nach rund einer
  Woche per `docker rmi`, nie per Prune.
- Abnahme (P4 Teil A): Beide Broker melden 10.26.0.9219. VPNs, die 36
  Queues außerhalb von Terraform, die iCargo-User und die DMR-Links
  gleichen der Baseline; `terraform plan` ist leer. Im Lab sind SAM
  (A2A-Queues, gdk-Leader, Eventmesh-Gateways, notify) und die
  GEBIT-Demo (R1-Queue, `make smoke`, S1-e2e "proposed 100001 7,99")
  grün; Broker-Spans erreichen Tempo. Der dokumentierte Lab-Zyklus lief
  einmal ohne Datenverlust und mit leerem `terraform plan`.
- Risiko mittel bis hoch (Abschnitt 7): Die Volume-Kopie der SolOS-DB
  ist ungeprobt.

### 5.4 gebit-price-agent-demo (im sda-Repo versioniert, keine Infra-Freigabe)

- Baseline und Rückweg über sda-Commits (P0 Schritt 9). gpd ist seit
  17.11.2026 im öffentlichen Repo versioniert (Commit `7a860c5`), das
  GEBIT-Descriptor-Set nie [Quelle: gpd
  scripts/check_hygiene.sh:24-30].
- `.gitignore`: `.env.*` deckt `.env.aks` schon ab, schluckt aber auch
  die Vorlage; deshalb `!.env.aks.example` (P0 Schritt 10).
- `TARGET`-Schalter; ein Loader `opslib.env_file(target)` (lab
  `.env`, aks nur `.env.aks`), den `demo_env()` und damit `e2e.py`,
  `sam_inbox.py`, `broker.py`, `render_mesh.py` und
  `check_manifests.py` nutzen; `lib.sh` setzt `SAM_PROFILE` aus
  `TARGET` vor dem Sourcen von amd `common.sh` und bricht bei
  Widerspruch ab; das Makefile verzichtet für env-abhängige Rezepte
  (`manifests`, `push`, `test-gebit`, `test-int`, `urls`) auf eigenes
  `LOAD_ENV` und den Lab-Default `GPOS_IMAGE ?=` und holt die Werte
  über `scripts/lib.sh` bzw. einen Helfer `scripts/env.sh TARGET`.
- Fail-closed-Check bei `TARGET=aks` (P0 Schritt 11) mit Tests in
  `scripts/tests/test_env_and_hygiene.py`: `.env.aks.example` ist eine
  Obermenge von `ENV_KEYS`; der Check lehnt eine `.env.aks` ohne
  `SAM_URL` und eine mit `E2E_BASE_URL=https://gpos.solace.lab` ab; mit
  `TARGET=aks` liest `demo_env()` keine `.env` (Scratch-Baum mit
  abweichender `.env`); `TARGET=aks` mit `SAM_PROFILE=lab` bricht ab.
- Zustand je Ziel (`mesh/.rendered/<target>`, `build/<target>`) per
  Kopie; `KUBE_CONTEXT`-Wrapper mit `KUBECONFIG`.
- sam-CLI-Seam nach P6 Schritt 4: Haupt-Manifeste an Ort und Stelle,
  nur Entrypoints je Ziel gerendert; `--sam-home`, `--url $SAM_URL`,
  `--no-dotenv`.
- psql-Seam `PG_MODE=docker|kubectl`; `install.sh` mit den Teilen
  `pg|db|k8s|mesh|all`, `pg` nur auf `aks`, `all` auf `aks` = pg, db,
  k8s, mesh (Lab unverändert); `k8s/postgres-aks/` im Namespace
  `gpos-data`; DSN mit URL-kodiertem Passwort auf `aks`; Guard bei
  install.sh:117 prüft die DB.
- `broker.py`/`broker.sh`: Port-Forward und Identitätsprüfung;
  `broker.sh` schreibt bei `TARGET=aks` vor jedem Aufruf
  `mesh/.rendered/aks/semp.tfvars` aus dem Key Vault (P6 Schritt 7);
  `broker.py` ohne Rückfall auf die Lab-tfvars; Negativtests für
  fehlendes `SEMP_PASSWORD_FROM`/`SEMP_PASSWORD_KEY`, Lab-Pfad, fehlende
  und Lab-`SEMP_URL`.
- e2e mit `AWE_NS`/`AWE_DEPLOY`, `E2E_BASE_URL=https://<fqdn>` und
  `E2E_CA_FILE=system`; `uninstall.sh` zielbewusst: auf `aks` wird
  Namespace `gpos-demo` gelöscht, `gpos-data` nur mit `--drop-db`
  (vorher DB und Rollen über den Seam löschen und die aks-db.env
  entfernen).
- `k8s/base` + `overlays/lab|aks|l3`. Das aks-Overlay:
  - gpos-ui-Ingress auf `<fqdn>` mit ausgeschnittenen Prefix-Pfaden
    `/kasse`, `/monitor`, `/static/`, `/api/catalog`, `/api/cards`,
    `/api/scenarios`, `/api/pos/`, `/api/state`, `/api/proposals/`,
    `/api/demo/` und `/api/events`; `/` und `/health` bleiben bei SAM.
    Traefik wählt die längere Regel, und keine SAM-Route nutzt diese
    Namen [Quelle: `doc.traefik.io` rules-and-priority; gpd
    app/gposdemo/ui/bff.py:326-412; SAM-WebUI main.js, Befehl `curl`
    17.11.].
  - Getrennte Ingresses `gpos-ui`, `gpos-ui-pos` (`/api/pos/`),
    `gpos-ui-demo` (`/api/demo/`) und `gpos-ui-events`
    (`/api/events`): `gpos-ui-events` ohne jedes Buffering (SSE), die
    übrigen mit `proxy-request-buffering: "on"` und
    `proxy-body-size: "4m"`.
  - gRPC-Ingress auf `<fqdn>:443` mit `backend-protocol: GRPC` und je
    Dienst einem Prefix-Pfad aus dem voll qualifizierten Servicenamen:
    Purchase-Service (FQN aus dem GEBIT-Paket) → `gpos-pos`,
    `/de.showcase.wws.v1.service.MerchandiseService/` → `gpos-wws`,
    `/de.showcase.loyalty.v1.service.LoyaltyService/` →
    `gpos-loyalty`, je mit `limit-rpm` (Multiplikator 1) in
    `public-guard`. `/grpc.reflection.v1.ServerReflection/` und
    `/grpc.reflection.v1alpha.ServerReflection/` gehen über ein
    eigenes Ingress `gpos-grpc-reflection` ohne Limit an `gpos-pos` (ab
    Image 0.1.4 der gemeinsame Endpunkt), nur mit der schriftlichen
    Bestätigung der öffentlichen Reflection (AKS-E16). Keine Route für
    `/grpc.health.v1.Health/`: Health bleibt clusterintern.
  - Kein `certificate.yaml` und keine `cert-manager.io`-Annotation:
    Die Ingresses tragen `spec.tls.hosts` ohne `secretName`, TLS kommt
    aus dem Default-TLSStore [A: Test in P2].
  - Komponente `public-guard`, im aks-Overlay an, je Client-IP:
    `limit-rpm` rund 120 auf `gpos-ui-pos`, `limit-rpm` 2 auf
    `gpos-ui-demo`, `limit-connections` rund 10 auf `gpos-ui-events`,
    `limit-rpm` rund 60 auf den drei gRPC-Service-Pfaden [A: Werte in
    P6 und P7 kalibrieren; Quelle: Traefik-Doku
    Kubernetes-Ingress-NGINX-Annotationen]. Jede spätere BFF-Route,
    die SAM oder ein LLM anstößt (Foto-Upload), bekommt bei
    öffentlicher Freigabe ein eigenes Ingress mit `limit-rpm` und
    `proxy-body-size`. UI-Dateien und BFF-Pfade bleiben unverändert.
    Alle Stand-Geräte hinter einer NAT-IP teilen sich die Limits.
  - Tests in `scripts/tests/test_k8s.py` für alle Overlays und
    `postgres-aks`, dazu der Routentest aus P6 Schritt 2 mit zwei
    ausdrücklichen Listen: öffentlich (`/kasse`, `/monitor`,
    `/static/`, die `/api/...`-Pfade oben, später `/kunde`) und
    Exposition offen (`/freigabe`, `/foto`, `/op`, `/etikett` samt
    API-Routen, Frage 23). Eine Route der zweiten Liste mit Pfad auf
    `<fqdn>` oder eine BFF-Route in keiner Liste lässt den Test
    scheitern; ohne Pfad landet eine Seite bei SAM.
  - `install.sh` überspringt auf `aks` die Kyverno-Wartezeit und den
    Lab-CA-Export.
- Image 0.1.4 (neuer Arbeitspunkt in P6, rund 0,5 PT [A]): Ein
  gemeinsamer Reflection-Endpunkt in `gpos-pos` beantwortet Reflection
  für alle drei Dienste aus beiden Descriptor-Pools (GEBIT aus dem
  Secret-Mount, Showcase aus dem Image); die Pools bleiben getrennt
  [Quelle: gpd app/gposdemo/common/descriptors.py:6-8]. Änderung in
  `grpcutil` mit Unit-Test in `app/tests/common/test_grpcutil.py`;
  `smoke.py`
  erwartet bei Scope `all` alle drei Dienste in der Liste von
  `gpos-pos`. Zuerst im Lab
  (`make test`, `make smoke`, S1-e2e), dann nach ACR (Makefile
  `GPOS_VERSION`). Bis dahin nutzen Postman und grpcurl für WWS und
  Loyalty `-protoset` aus dem eigenen Showcase-Descriptor.
- Kein Image-Schalter zum Abschalten von Reflection: Sie bleibt an
  (AKS-E16). Öffentlich erreichbar wird sie erst mit dem Ingress
  `gpos-grpc-reflection`, und das kommt nur mit der schriftlichen
  Bestätigung ins Overlay, weil sie die GEBIT-Descriptor-Dateien
  ausliefert. Der Scope-Schalter für 0.1.4
  (`GPOS_GRPC_REFLECTION_SCOPE`, P6 Schritt 5) steht nur in den
  Overlays `aks` und `l3`.
- `keycloak-marktleitung.sh` aus `spikes/g0` in `scripts/` übernehmen,
  zielbewusst, ohne `-k`, Admin-API über den Port-Forward mit Präfix
  `/auth`.
- Makefile-Ziel für die ACR-Kopie (arm64); amd64-Build nur bei einer
  GEBIT-Übergabe (`buildx` mit QEMU oder `az acr build --platform
  linux/amd64`).
- Die Skizzen in `spikes/aks/` (ingress-nginx-Values,
  DNS-01-Issuer, `pubsubplus-values-aks.yaml` mit 10.25.0.208 und
  internem MQTT-LB) sind überholt und bekommen einen Vermerk;
  maßgeblich sind die Dateien aus 5.1 bis 5.3.
- Doku-Drift korrigieren (Abschnitt 8). Kiosk-URLs sind
  `https://<fqdn>/kasse` und `https://<fqdn>/monitor`; die
  gpos-Weiterleitung von `/` auf `/monitor` ist auf AKS nicht
  erreichbar.

## 6. Zeitplan gegen die Gates

KW nach ISO 8601; 2026 hat eine KW53. Gates nach PLAN 0.3.

| KW | Daten | Arbeit | Gate/Meilenstein |
|---|---|---|---|
| KW47 | 16.-22.11. | P0 (Owner + Claude): Owner-Entscheidungen vom 17.11. eingetragen; Login, read-only-Checks, Quota-Antrag (DPSv6 und Standard-IPs; DPSv5 nur bei Restriction), Anfragen an den LiteLLM-Betreiber (Allowlist, Messe-Key mit `max_budget`, `rpm_limit`, `tpm_limit`), schriftliche Owner-Bestätigung zur GEBIT-Freigabe erbeten (Descriptor-Secret in Azure, öffentliche Reflection; fällig 27.11., spätestens 09.12.), Mac-Tools (Azure CLI 2.93+, kubelogin); ab 20.11. RG, `pip-aks-egress` und `pip-aks-ingress` mit DNS-Label und Lock | O9 bis 20.11. [Quelle: PLAN 0.5 O9]; AKS-E20 (Name) bis 20.11. |
| KW48 | 23.-27.11. | P0 (C ab 23.11.): gpd-Baseline, Geländer, sam-CLI-Spike, Regressions-Gate; P4 Teil A: A1 Baseline (read-only), dann solace-2 (nach Owner-Go); Egress-IP an den Betreiber bis 25.11. | offene AKS-E (Abschnitt 2) bis 27.11.; Betreiber-Bestätigung 27.11.; Wartungsfenster für solace-1 festgelegt |
| KW49 | 30.11.-04.12. | P1: Cluster (1 Node), CLI, `aks-allow-me.sh`, Hairpin- und PVC-Test, LiteLLM-Probe; P4 Teil A an solace-1 im Wartungsfenster, Lab-Flows (A7); P2 Beginn (ACR-Spiegel, PriorityClasses, VAP, Traefik, LE staging, dann prod am 03.12.); ACME-Rückfallkonto und EAB-Daten in Key Vault und `sli/aks/.env.aks` (Owner) | LiteLLM-Probe 03.12. als Frühindikator (AKS-E18); EAB-Daten bis 04.12.; **Prüfpunkt 04.12.** (P1, P4 Teil A) |
| KW50 | 07.-11.12. | P2 Rest (cert-manager HTTP-01, TLSStore, Traefik-Lückentests, Monitoring), P3 Keycloak unter `/auth` | LE-prod-Zertifikat Ready bis 07.12., 12:00, sonst EAB-Rückfall; GEBIT-Bestätigung (Descriptor-Secret) liegt bis 09.12. vor, sonst G0-11b (3) ohne `gebitsim`; gRPC-Teil G0-11b (11.12.); **Prüfpunkt 11.12.** |
| KW51 | 14.-18.12. | P4 Teil B Broker 10.26.0.9219 auf AKS, P5 SAM, HITL- und Vision-Test (G0-11a/b nach AKS-E18), HTTPS-RTT; Puffer | **G2a 18.12.** |
| KW52-53 | 21.12.-03.01. | Feiertage; Lab-Vorarbeit P6 (Overlays mit Pfad-Ingresses, `public-guard`, Seams, `postgres-aks`, Image 0.1.4 mit gemeinsamem Reflection-Endpunkt); C: AP14 Preflight; Cluster gestoppt | - |
| KW1 | 04.-10.01. | P6 auf AKS: pg, db, Image 0.1.4, k8s, mesh, Gate-Verifikation | ohne schriftliche GEBIT-Bestätigung kein `gpos-gebit-descriptors` auf AKS, Demo dann nur im Lab oder in L3 (AKS-E16) |
| KW2 | 11.-15.01. | P6 e2e, TR1-Besuche über das öffentliche Internet (Leih-Router mit Kabel und 5G, Mobilfunk-Hotspot), TR3 (falls im Lab grün), `install.sh all` aus leerem Namespace; am 15.01. `cmctl renew -n traefik ingress-tls` und TLS-Backup | **G2b 15.01.** |
| KW3 | 18.-22.01. | P7 Drills: Neuaufbau (TLS aus dem Backup), 24-h-Lauf (Mo 18.01. 12:00 bis Di 19.01. 12:00) mit 10-h-Kiosklauf über den öffentlichen Ingress, 3 Stop/Start-Zyklen mit je 30 min Pause, Netz (Kabel ziehen, 5G), Missbrauchstest `public-guard`, L3; Backups mit Restore-Test; Runbook; Rollen des Stellvertreters | **G3 22.01.**; Wartungssperre 20.01. |
| KW4 | 25.-31.01. | Node-Image-Refresh Di 26.01. (Ausfallzeit messen); Runbook, Preflight, Fixes; Probetage 28.01. (Runbook-Durchlauf des Stellvertreters) und 29.01. | Wartungssperre ab 27.01. |
| KW5 | 01.-05.02. | Probetag 3 am 03.02. (Break-glass-Test des Stellvertreters); Traefik-Patchstand prüfen | **G4 Freeze 05.02.** |
| KW6 | 08.-14.02. | 24/7, Preflight täglich; LE-64-Tage-Wechsel am 10.02. ohne Wirkung (das Zertifikat vom 15.01. gilt bis Mitte April) | Netztest 14.02. |
| KW7 | 15.-21.02. | Messe 16.-18.02.; 19./20.02. Export, Descriptor-Secret löschen, stoppen | Rückbau-Entscheidung |

**O9 als Weiche (Stichtag 20.11.):**

- O9 = (a): Der Kalender oben gilt, C trägt P0 (ab 23.11.) bis P7.
- O9 = (b) oder bis 20.11. nicht entschieden: sofort die Mechanik aus
  PLAN 6.2 (Rechnung für Variante (b)). Die AKS-Schritte bis SAM
  wandern mit G0-11a/b nach G2b, die G2a-AKS-Abnahme ebenso; P5 liegt
  dann in KW1, P6 in KW2, G2b wird eng. Die Kapazität ist ohnehin
  knapp: Muss 118,75 PT gegen 93,6 PT netto [Quelle: PLAN 0.4]; der
  PLAN empfiehlt eine dritte Person für AKS ab 23.11. [Quelle: PLAN 0.5
  O9].

**Wochenlast von C (Variante a), gegen 4,3 PT netto je 5-Tage-Woche,
3,5 PT über die Feiertage und 6,1 PT in KW1-2 [Quelle: PLAN 7.2,
7.3]:**

| KW | AKS-Plan | übrige PLAN-Pakete von C | Summe |
|---|---|---|---|
| 48 | P0-Rest 1,75 (0,75 tragen Owner und Claude in KW47); P4 Teil A an solace-2 0,5 | AP04a Container 0,5; AP07b Loyalty-Tools 0,75 (aus KW51 vorgezogen) | 3,5 |
| 49 | P1 2,0; P4 Teil A an solace-1 0,5; P2 Beginn 0,75 | AP08 `install.sh mesh` 0,75 | 4,0 |
| 50 | P2 Rest 2,25; P3 1,25 | AP04a gRPC-Ingress Lab 0,75 | 4,25 |
| 51 | P4 Teil B 1,25; P5 2,5; Puffer 0,5 | - (AP07b vorgezogen, AP14-Runbook geht in P7 Schritt 4 auf) | 4,25 |
| 52-1 | P6 Lab-Vorarbeit 1,5 (darin Image 0.1.4) | AP14 1; AP13 `hitl_e2e.py` 0,5; AP14 Preflight 0,5 (aus KW50) | 3,5 |
| 1-2 | P6 auf AKS 4,25; Puffer 0,75 | AP14b 1; AP14 1; AP11 `/op` 1,5 | 8,5 |
| 3 | P7 3,0; Puffer 1,25 | - (24-h-Lauf, Neuaufbau, Kiosklauf und L3-Drill sind P7) | 4,25 |

[A] Die Verschiebungen von AP07b, AP04a und AP14 müssen ihre
Abhängigkeiten erlauben; mit dem PLAN-Eigner prüfen. AP07b bleibt für
die TR5-Abnahme an G2a vor dem 18.12. Vom Puffer (3,5 PT,
15 %) liegen 0,5 PT sichtbar vor G2a in KW51,
0,75 PT in KW1-2 und 1,25 PT in KW3; der Rest
(1,0 PT) liegt mit dem P7-Rest (1,25 PT) in
KW4-5, wo C laut PLAN 7.3 3,5 bzw. 1,5 PT trägt.

KW1-2 ist für C überbucht (8,5 gegen 6,1 PT netto), weil P6
die PLAN-Posten AP12 S7-S8 aus KW51 aufnimmt. Vorschlag [A], mit dem
PLAN-Eigner zu klären:

- AP11 `/op` (1,5 PT) geht an Entwickler B; B trägt in KW1-2 laut
  PLAN 7.3 5,0 PT, darin 1 PT G2-Puffer.
- Der AP14-Rest (1 PT) wandert nach KW5 (C dort sonst 1,5 PT).
- Danach trägt C in KW1-2 6,0 PT.

**Prüfpunkte statt eines Rückfalls am 18.12.:**

- 04.12.: P1-Abnahme und Abnahme P4 Teil A grün (Lab auf
  10.26.0.9219, SAM- und GEBIT-Flows belegt). Ist Teil A rot,
  entscheidet der Owner: Teil A bis 10.12. nachholen (Teil B beginnt
  erst danach) oder Rückfall wie unten.
- 07.12., 12:00: LE-prod-Zertifikat Ready, sonst stellt P2 auf
  `acme-eab-fallback` um.
- 11.12., zusammen mit G1 und dem gRPC-Teil von G0-11b: P2- und
  P3-Abnahme grün.
- Ist der Prüfpunkt am 04.12. (nach dem Nachholtermin 10.12.) oder am
  11.12. rot, wandert die G2a-AKS-Abnahme nach G2b (Mechanik aus PLAN
  6.2, nicht die ganze Variante (b) mit Streichliste) und P5 nach KW1.
  Name dieses Rückfalls: "G2a-AKS-Abnahme nach G2b".

## 7. Risiken und Gegenmaßnahmen

| Risiko | Gegenmaßnahme |
|---|---|
| Skript oder Ad-hoc-Befehl wirkt auf das falsche Ziel: kein Skript pinnt einen Kontext; `stop.sh` löscht Release, PVCs, Namespace und räumt Lab-Keycloak und Lab-Broker-Queues ab; ein `kubectl apply -k` ohne Kontext träfe den Lab-Keycloak in `iam` [Quelle: amd scripts/stop.sh:102-115, 161-162, 247-249; Befehl `grep -rnE -- '--context\|KUBECONFIG'`; Befehl `kubectl config current-context` = rancher-desktop, 16.11.] | P0 vor jeder AKS-Credential: eigene kubeconfig-Datei nur über `kaks`/`haks`, `require_kube_context` mit Server-URL, SEMP-Identitätsprüfung, Keycloak-Teardown-Guard, `SAM_HOME` je Ziel, Negativtests, Lint gegen nackte kubectl/helm-Aufrufe, Call-Log- und Render-Diff-Gate |
| Azure ungeprüft: Token, Quota, SKU, Policy, Rollenrechte; Deny-Policies (etwa gegen Public IPs oder öffentliche Load Balancer) zeigen sich sonst erst beim Create als RequestDisallowedByPolicy | P0 sofort nach Login mit `atScope()`, `--all --include-groups` und effektiven Rechten; Quota-Antrag am 20.11. für DPSv6 16 vCPU (ein Node plus Surge-Node, 3.5), DPSv5 nur bei Restriction, und 2 Standard-IPs; Rückfall D8ps_v5 oder West Europe, amd64 nur als letzter Ausweg (AKS-E3) |
| Ein Node ohne HA: Node-Ausfall, Host-Wartung, Node-Image-Update oder Neustart legt alle Dienste für einige Minuten still, die Disks hängen danach neu an. Learn verlangt für produktive System-Pools mindestens 2 Nodes (empfohlen 3), der AKS-Quickstart nutzt `--node-count 1` [Quelle: `learn.microsoft.com/azure/aks/use-system-pools`; AKS-Quickstart] [A] | vom Owner am 17.11. akzeptiert; der Create in P1 belegt die Zulässigkeit; manueller Refresh Di 26.01. mit gemessener Ausfallzeit, Sperre ab 27.01.; L3 warm an Probetagen und Messe, L4 über `/op`; Resource-Health-Alarm; Runbook-Schritt "Node NotReady"; aus gestopptem Cluster bis READY höchstens 30 min (G3) |
| Requests auf einem Node knapp: mit Broker `prod1k` rund 91 % CPU- und 70 % RAM-Requests (3.2); ein zusätzlicher Pod (Defender-Sensor, Debug-Pod, Surge beim Rollout, Restore-Scratch-Pod) bleibt Pending; Keycloak-OOM und SeaweedFS-Hänger wie im Lab | Requests auf Ist-Werte, Keycloak 1,5Gi, SeaweedFS 2 CPU/2Gi (committet in `cd08a17`), Prometheus-PVC; Nachzug nach einer Woche AKS-Daten (P7 Schritt 1); Broker `dev` als Rückfall (78 % CPU, Kriterium in 3.2, nur vor dem ersten Install in P4); `maxSurge 0` für große Deployments, wo nötig [A] |
| Let's Encrypt, geteilter Bucket: `cloudapp.azure.com` steht nicht auf der Public Suffix List, alle Azure-Kunden teilen das Limit von 50 neuen Zertifikaten je Woche für `azure.com`; die Ausstellung kann tagelang scheitern [Quelle: PSL, abgerufen 17.11.; PSL-PR 1966; `letsencrypt.org/docs/rate-limits`; `community.letsencrypt.org/t/217855`] | ein Zertifikat (`ingress-tls`) für den einen FQDN, kein Certificate je Namespace; erst staging, dann prod am ersten P2-Tag; ist bis 07.12., 12:00 kein Prod-Zertifikat Ready, übernimmt der vorbereitete Rückfall-ClusterIssuer `acme-eab-fallback` mit EAB (ZeroSSL oder Google Trust Services, Konto vom Owner, EAB nur in Key Vault und `.env.aks`); Secret nach jeder Ausstellung sichern; Erneuerungen desselben Namenssets zählen nicht gegen das 50er-Limit |
| LE-Limits bei Drills; eine automatische Erneuerung fiele um den 02.02. in die Sperre; LE wechselt am 10.02.2027 auf 64 Tage [Quelle: `letsencrypt.org/ca/upcoming-features`] | TLS-Backup als volles Secret mit cert-manager-Annotationen, vor Certificate und Ingresses eingespielt, sonst Drill gegen staging; `cmctl renew` um den 15.01., damit die nächste Erneuerung erst Mitte März fällt; danach Backup und `export-le-certs.sh` für L3 |
| Traefik weicht vom Lab ab: Das Lab bleibt auf ingress-nginx; Traefik-eigene Teile (IngressClass, Middleware, TLSStore, Timeouts, Request-Buffering) und die AKS-Pfad-Ingresses (gpos, gRPC, Keycloak `/auth`) laufen nur auf AKS; Annotationen wirken anders (`proxy-body-size` nur mit `proxy-request-buffering: "on"`, Rate-Limits mit 429 statt 503); Sicherheits-Patches etwa wöchentlich [Quelle: Traefik v3.7.19 ingress-nginx.md:265-502; GitHub-Security-Advisories, 17.11.] | P2 beweist die Traefik-Konfiguration zuerst: HTTP-01, GRPC, SSE 20 min mit `curl --http1.1 -N`, ein 900-s-Halt, Default-Zertifikat, 413 über dem Body-Limit; Abweichungen nur im aks-Overlay, Render-Tests für alle Overlays; Image per Digest, nie unter v3.7.18; im Freeze nur Patch-Releases mit Smoke-Wiederholung (Owner-Frage, Abschnitt 9) |
| Öffentliche anonyme Schreibpfade: Kasse (`/api/pos/...`), `/api/demo/reset` (auch Scope `day`) und die gRPC-Schreib-RPCs (WWS `RequestPriceChange`, `EndPriceChange`, `ResetDemoState`; Loyalty `IssueCoupon`, `VoidCoupon`, `ResetDemoState`) ruft jeder auf. Preise ändern sich ohne SAM-Freigabe, Resets stören die Demo, Skript-Schleifen kosten LLM-Geld: eine Prüfung alle 5 s rund 7-36 USD/h, der 150-USD-Key ist in 4-21 h leer, danach steht die Demo [A; Quelle: PLAN 0.5 O5, PLAN R24] | Owner hat anonyme gRPC-Schreibaufrufe, Reflection und die Kasse ohne Login am 17.11. akzeptiert; `public-guard` mit Rate-Limits je Client-IP auf `/api/pos`, `/api/demo/reset`, `/api/events` und den drei gRPC-Service-Pfaden (`externalTrafficPolicy: Local`); der LiteLLM-Betreiber setzt `max_budget`, `rpm_limit` und `tpm_limit` am Messe-Key [Quelle: `docs.litellm.ai/docs/proxy/users`]; Preflight und Day-Reset jeden Morgen; Grafana-Ansicht der Läufe je Stunde, bei Missbrauch Limits verschärfen; SAM-Budget unter dem Key-Limit als sichtbarer Notschalter [A: Umfang des Budgets in P5 prüfen] |
| Ein öffentlicher Eingang mit einem Traefik-Pod: Request-Buffering für SAM und gpos-ui legt Bodies im emptyDir ab; viele parallele Uploads füllen es, das Kubelet verdrängt den Pod, und Kasse, Monitor, SAM, Keycloak und gRPC sind bis zum Neustart weg; `limit-rps` begrenzt nur die Rate [Quelle: Traefik-Chart 42.4.1 values.yaml:119-121; Recherche 17.11.] | `limit-connections` 20 je Client-IP am SAM-Ingress, SAM-Body-Limit 10m [A], `sizeLimit` 2Gi plus Request auf `ephemeral-storage` (P2 Schritt 5, P5 Schritt 2), Lasttest in P2 und P5; Restrisiko: verteilte Uploads aus vielen IPs können das emptyDir weiter füllen, dann die Route sperren (Runbook, Freeze-Ausnahme) |
| Access-Log mit Tokens oder Besucher-IPs: Die SAM-WebUI hängt ihr Access-Token als Query-Parameter an SSE-Aufrufe; ein Access-Log mit vollem `RequestPath` brächte Tokens von sam_admin und `marktleitung` nach Loki, Grafana und in den Export [Quelle: SAM-WebUI-Bundle und ingress-nginx-Log aus dem Lab, 17.11.] | Traefik-Access-Log mit `queryParameters.defaultMode: drop` und ohne Header (P2 Schritt 5); Zählabfrage `[?&]token=` in Loki ergibt 0 (P2, P5); Loki-Export nach der Messe ohne Access-Logs und mit Zählprüfung (P7 Schritt 8); Besucher-IPs liegen 7 Tage in Loki [A] |
| Geteilter Origin: gpos (öffentlich, ohne Login) liegt auf demselben Origin wie SAM, dessen Bearer-Tokens im localStorage liegen; ein XSS in gpos könnte sie lesen [Quelle: SAM-WebUI main.js, Befehl `curl` 17.11.] | Risiko niedrig, vom Owner akzeptiert: gpos setzt keine Cookies, nutzt keinen Web-Storage und baut das DOM nur mit `textContent` [Quelle: gpd app/gposdemo/ui/static/shared/common.js; kasse.js; monitor.js]; Hygiene-Test gegen `innerHTML` und `insertAdjacentHTML` in den gpos-UI-Dateien [A]; `redirectUris` exakt auf den Callback; HSTS ohne `includeSubDomains`; Rückfall nur mit neuer Owner-Entscheidung: ein zweites DNS-Label nur für gpos (dritte Public IP, rund 3,3 EUR/Monat; mit zwei weiteren Regeln 5 LB-Regeln, noch im Grundpreis) |
| Admin-Oberflächen öffentlich erreichbar (Keycloak-Admin und Master-Realm, Grafana, Prometheus, Broker-SEMP, Traefik-Dashboard, NodePorts) | VAP erlaubt `LoadBalancer` nur für `traefik/traefik` mit `pip-aks-ingress` und RG-Annotation (zweiter LB-Service und fehlende RG-Annotation als Negativtests in P2); das Azure-LB hat nur Regeln für 80 und 443, die Nodes haben keine öffentliche IP; Keycloak-Ingress nur `/auth/realms/solace-lab/` und `/auth/resources/`; Grafana, Prometheus, SEMP und Traefik-Dashboard nur per Port-Forward. Negativtests aus dem Internet in P3, P6 und P7: `/auth/admin/` und `/auth/realms/master/` liefern keine Keycloak-Seite (sie fallen auf SAMs SPA-Fallback mit 200, geprüft wird das Fehlen von Keycloak-Inhalt, nicht ein 404) |
| CT-Logs: Die Ausstellung veröffentlicht den FQDN, Scanner finden den Host binnen Minuten [A]. Offenes Risiko: Jeder kann den Approver `marktleitung@solace.lab` mit 5 Fehlversuchen wiederholt bis 900 s sperren; der Name steht in rund 35 Dateien des öffentlichen Repos, der Realm erlaubt Login per E-Mail [Quelle: sli keycloak/manifests/03-keycloak.yaml:30-47; Befehl `git grep -l` auf Commit 7a860c5, 17.11.] | neutrales Präfix `<p>` ohne Kunden- oder Produktnamen; keine Admin-Oberfläche öffentlich; Rate-Limits; Brute-Force-Schutz bleibt an; Entscheidung in P3: nicht erratbarer Approver-Username mit `loginWithEmailAllowed: false` in der AKS-Realm-Kopie (E-Mail und `SAM_RUN_IDENTITY` bleiben [A]) oder bewusst hinnehmen mit Runbook-Schritt "Sperre aufheben" über die Admin-Konsole per Port-Forward; `passwordPolicy` gegen kurze Passwörter |
| API-Server: Die IP von Owner oder Betreiber wechselt (Heimnetz, 5G, Messe), kubectl scheitert; `az aks update --api-server-authorized-ip-ranges` ersetzt die ganze Liste [Quelle: `learn.microsoft.com/azure/aks/api-server-authorized-ip-ranges`] | `sli/aks/aks-allow-me.sh` ergänzt die aktuelle IP und schreibt die vollständige Liste; Break-glass ohne Allowlist mit `az aks command invoke` (die Rolle des Stellvertreters enthält runcommand) [Quelle: `learn.microsoft.com/azure/aks/access-private-cluster`]; im Freeze nur `aks-allow-me.sh`, das ergänzt und nichts entfernt [A: Owner bestätigt die Ausnahme] |
| Hairpin: SAM-Selbstaufrufe und der Back-Channel von SAM zu Keycloak gehen an denselben öffentlichen FQDN; Pod → öffentliche LB-IP mit `externalTrafficPolicy: Local` ist auf Overlay mit Cilium ungeprüft [A] | Test in P1 (Curl-Pod gegen `https://<fqdn>/`, ab P3 gegen den Issuer); Rückfall `kube-system/coredns-custom` mit Rewrite des FQDN auf die Traefik-ClusterIP [Quelle: `learn.microsoft.com/azure/aks/coredns-custom`; amd scripts/start.sh:136-147] |
| gRPC-Reflection bis Image 0.1.4: Reflection- und Health-Pfade sind auf allen drei Servern gleich, über einen Host erreichen `grpcurl list` und Postman nur einen Server [Quelle: gpd app/gposdemo/common/grpcutil.py:150-167] | bis 0.1.4 geht Reflection an `gpos-pos`; WWS und Loyalty per `-protoset` aus dem eigenen Showcase-Descriptor; 0.1.4 mit gemeinsamem Reflection-Endpunkt in der Lab-Vorarbeit KW52-53, Lab zuerst (`make test`, `make smoke`, S1-e2e); gRPC-Health bleibt clusterintern |
| Neue BFF-Seiten: Das aks-Overlay routet gpos nur über ausgeschnittene Pfade; eine neue Seite ohne Pfad landet bei SAM (SPA-Fallback 200). Umgekehrt wären `/freigabe` (beantwortet SAM-HITL über die BFF), `/foto` (startet den Vision-Agenten), `/op` und `/etikett` mit Pfad öffentlich ohne Login: Jeder könnte Preise freigeben oder den Messe-Key leeren [Quelle: PLAN 1.4; PLAN 9 R24]; `/` und `/health` gehören SAM | Owner-Entscheidung offen (Frage 23, vor G2b), nicht akzeptiert; bis dahin kein Pfad. Test in `scripts/tests/test_k8s.py` mit zwei ausdrücklichen Listen (öffentlich, Exposition offen), der bei einer gerouteten offenen Route scheitert; LLM-auslösende Routen nur mit eigenem `public-guard`-Limit; Kollisionsprüfung gegen die SAM-Routen je SAM-Release [A]; Kiosk-URLs direkt auf `/kasse` und `/monitor` |
| Lab-Broker-Upgrade (P4 Teil A) mit DBs im Container-Layer: solace-1 und solace-2 haben keine Mounts, die Compose-Hashes weichen ab; `start.sh` würde beide neu erzeugen und leeren, `stop.sh` löscht sie; 36 Queues und die iCargo-User liegen außerhalb von Terraform; ein Downgrade ist nicht unterstützt [Quelle: Befehle `docker inspect`, `docker compose config --hash` und SEMPv2-GETs, 17.11.; emd start.sh:4-6, stop.sh:2; `docs.solace.com` Upgrade-Selector] | Risiko mittel bis hoch; eigenes Owner-Go und Wartungsfenster; bis zur Anpassung der emd-Skripte (auch nach der Migration, weil `stop.sh` den Terraform-State löscht) im emd-Lab nur `docker start/stop` bzw. `docker compose stop/start`, kein `start.sh`, `stop.sh`, `compose up/pull/down`, kein Prune; README, `CLAUDE.md` und Memory-Notiz nennen den geltenden Zyklus; Schritte nach P4 A1-A8: SEMPv2-Baseline, `docker commit` als Rückfall, externes Volume, Tag plus Digest in `.env.example`, `compose up -d --no-deps` je Broker, solace-2 zuerst, `terraform plan` leer; SAM- und GEBIT-Flows im Lab belegt, bevor P4 Teil B und P5 beginnen (Prüfpunkt 04.12., spätestens 10.12.) |
| LiteLLM aus Azure nicht erreichbar oder langsamer (rund +100 ms je Aufruf [A: RA 5.2]) | Egress-IP ab P0 (KW47/48), an den Betreiber bis 25.11., schriftliche Bestätigung 27.11.; Probe aus dem Pod in P1; A4-Vergleich in P6 |
| LiteLLM-Key außerhalb von SAM lesbar: Klartext in `model_configurations` und `gateway_deployments`, Grafana-Grant auf alle Tabellen, pg_dumps, App-User mit Passwort = Username; die BFF ohne Login läuft im selben Cluster [Quelle: amd scripts/models/README.md:77-79; grant-grafana-platform-db.sh:72; SAM-Chart `_helpers.tpl`:359-397] | AKS-E19: eigenes Superuser-Passwort, NetworkPolicies für Postgres und SeaweedFS; `grafana_ro` nur mit expliziten Tabellen; Dumps ohne die Daten beider Tabellen, Zählprüfung je Dump, verschlüsselt, nach der Messe gelöscht; keine Snapshots |
| GEBIT-Freigabe (vom Owner am 17.11. berichtet) deckt das Descriptor-Set als K8s-Secret in Azure oder die öffentliche Reflection nicht ab; die Reflection gibt die GEBIT-Descriptor-Dateien selbst heraus [A] | Status offen, harte Vorbedingung: Owner bestätigt beides schriftlich bis 27.11., spätestens 09.12. (vor `gebitsim` in P2 Schritt 7, G0-11b (3) am 11.12.); ohne Bestätigung kein GEBIT-Material in Azure, G0-11b (3) mit einem Testserver ohne GEBIT-Material (dokumentierte Abweichung von PLAN 7.1) oder nach G2b, `install.sh k8s` auf AKS ohne Descriptor-Secret, Demo nur im Lab oder in L3; ohne Bestätigung nur der Reflection kein `gpos-grpc-reflection`. P1-P5 ohne P2 Schritt 7 mit `gebitsim` und die Lab-Vorarbeit laufen unabhängig. Secret nur zur Laufzeit vom Owner-Mac, nie in Git, Images, ACR, Key Vault oder Backups; das `gebitsim`-Secret in `p2-test` direkt nach dem Test gelöscht; Löschung bis 20.02. protokolliert |
| arm64 als System-Pool auf v6 oder Dpsv6-Kapazität nicht verfügbar [A] | der Create in P1 ist der Test; DPSv5-Quota bei Restriction im selben Antrag (P0 Schritt 4); Rückfall D8ps_v5, sonst amd64 (+1-1,5 PT, `crane` oder `az acr build`) |
| sam CLI mit zwei Targets schreibt auf die falsche Plattform oder zieht die Lab-`.env` | Login je Home unter dem Manifest-Zielnamen `solace-lab`; `SAM_HOME` je Ziel; URL-Guard gegen den Cache; immer `--url` und `--no-dotenv`; nie `--prune`; Spike in P0 |
| Stop/Start: Kapazität beim Start, gwe/awe-Race, Start zu früh nach dem Stop; die API-Server-IP kann wechseln [Quelle: `learn.microsoft.com/azure/aks/start-stop-cluster`] | kubectl nutzt den FQDN des API-Servers, ein IP-Wechsel braucht keinen Abgleich; die Ingress-IP bleibt (`pip-aks-ingress` in `rg-eurocis-base`); Start frühestens 30 min nach Stop (Sperre im Wrapper, RUNBOOK); Wartelogik und awe-Neustart; Start 60 min vor Bedarf; ab 05.02. kein Stopp |
| Wartung trotz Sperre (reaktive Wartung kann `notAllowedDates` brechen); mit einem Node heißt jedes Node-Image-Update einige Minuten Ausfall [Quelle: `learn.microsoft.com/azure/aks/planned-maintenance`] | Refresh Di 26.01. mit gemessener Ausfallzeit, Sperre ab 27.01.; kein PDB, das den Drain blockiert; L3 warm; Preflight nach jedem Wartungsereignis |
| Datenverlust im Cluster (gebündelte Persistenz, Neuaufbau löscht PVCs, Namespace-Löschung löscht die Demo-DB) | Inhalte per Skript und deterministischem Seed reproduzierbar; Demo-DB im eigenen Namespace `gpos-data`; `pg_dump` vor G3 und nach jedem Messetag vor dem Day-Reset, inklusive gpos-DB; Restore-Test; Export vor jeder Löschung (P7 Schritt 8) |
| Zeitplan: 13,5 PT bis G2a neben der TR5/TR3-Laborarbeit, das Lab-Broker-Upgrade (P4 Teil A) schon in KW48/49, dann Feiertage; KW1-2 für C überbucht (Abschnitt 6); AKS-E18 und AKS-E20 ohne Owner-Bestätigung | O9 als Weiche am 20.11.; Last von C in KW48/49 vorgezogen; Prüfpunkte 04.12. und 11.12. mit Rückfall "G2a-AKS-Abnahme nach G2b"; Umverteilung in KW1-2 mit dem PLAN-Eigner |
| Messebetrieb hängt an Konto und Mac des Owners; AKS-E20 ist ohne Owner-Bestätigung | AKS-E20: Stellvertreter mit eigenen Rollen, eigenem Keycloak-User, `aks-allow-me.sh` und Break-glass, Runbook-Durchlauf bis G3; wird bis G3 niemand benannt: L3 warm, L4 über `/op`, Preflight vor Standöffnung durch den Owner |
| Defender oder andere Subscription-Vorgaben verursachen Kosten oder blockieren Ressourcen | P0 prüft Defender-Pläne und Policies; Kosten bedingt in 3.4; Klärung mit dem Subscription-Owner (AKS-E1) |
| gpd-Umbau ohne Rückweg | Baseline = sda-Commit vor dem Umbau, Commit je Schritt, Rückweg in KW48 geprobt (P0 Schritt 9) |
| Kosten laufen weiter (vergessener Nachtstopp, nach der Messe); LLM-Kosten sieht das Azure-Budget nicht | Monatsbudget 250 EUR (neu skaliert, 3.4) auf drei RGs mit Forecast bis 31.03.; Abend-Check; Activity-Log-Alarm nur als Information; `deleteAfter`-Tag; datierter Rückbau-Schritt mit Key-Vault-Purge in P7; LLM-Limits am Messe-Key beim Betreiber |

## 8. Abgleich mit dem früheren AKS-Konzept

Bezug: PLAN 5.2/5.3 [Quelle: PLAN 5.2, 5.3], RA vom 10.11.2026
[Quelle: RA:29-71, RA:552-573], DESIGN 4.8 [Quelle: gpd DESIGN.md:794].

### 8.1 Was bleibt

- Germany West Central, Kubernetes 1.36, Azure CNI Overlay mit
  Cilium, ACR ohne Pull-Secret.
- NGINX-Ingress-Manifeste mit denselben Annotationen (Traefiks
  NGINX-Provider liest sie); gRPC mit h2c-Backend; SSE ohne Buffering,
  LB-Idle-Timeout 30 min.
- Let's Encrypt über cert-manager (jetzt HTTP-01 statt DNS-01).
- PubSub+ per Helm, ClusterIP, Terraform-Module aus emd;
  Lab-Standardpasswörter ersetzt.
- Keycloak 26 im Cluster, gleicher Realm, `*@solace.lab`.
- Stop/Start mit awe-Neustart, Preflight `TARGET=aks`, L3 mit
  exportierten LE-Zertifikaten, Neuaufbau-Drill höchstens 4 h.
- Nie `--prune`; LiteLLM-Key nur in SAM.

### 8.2 Was sich ändert und warum

| Thema | Früher | Jetzt | Warum |
|---|---|---|---|
| Nodes | 2 x D8as_v6 amd64 [Quelle: PLAN 5.2] | 1 x D8ps_v6 arm64, ohne HA | gleiche Digests wie Lab, kein Multi-Arch-Build; Owner-Entscheidung 17.11.; rund -355 EUR/Monat |
| Zugang | Stand-Router mit WireGuard (PLAN-E8, RA); AKS-Plan 16.11.: internes LB, WireGuard-VM | öffentlich ohne WireGuard: ein öffentliches LB nur für Traefik, API-Server mit authorized IP ranges, Admin per Port-Forward | Owner-Entscheidung 17.11.; Kasse und Monitor unverändert ohne Login |
| Ingress | ingress-nginx 1.15.1, nur internes LB [Quelle: PLAN 5.2] | Traefik v3.7.19 (Chart 42.4.1) mit NGINX-Provider, ein öffentliches LB mit 80 und 443 | ingress-nginx archiviert, CVE-2026-116472 ohne Fix; das Lab bleibt auf ingress-nginx |
| Hostnamen | `sam.<d>`, `auth.<d>`, `gpos.<d>`, je gRPC-Server ein Host, `grafana.<d>` (RA 4.1) | ein FQDN `<fqdn>`; Pfade: SAM `/`, Keycloak `/auth`, gpos ausgeschnittene Pfade, gRPC je Service-Präfix; kein Grafana-Name | Owner-Entscheidung 17.11.: ein Azure-DNS-Label, eine Ingress-IP |
| TLS | LE DNS-01 mit Workload Identity auf delegierter Zone, ein Certificate je Host | LE HTTP-01, ein Zertifikat als Default-TLSStore, EAB-Rückfall | keine eigene DNS-Zone; geteilter LE-Bucket unter `azure.com` |
| Persistenz | PG Flexible B2ms + Blob [Quelle: PLAN 5.2] | alles im Cluster, gebündelt, mit eigenem Superuser-Passwort und NetworkPolicies; Demo-DB im Namespace `gpos-data` | nie getesteter Pfad, +1,5-2 PT, rund +108 EUR/Monat; Plan-Rückfall Nr. 11 [Quelle: PLAN 6.2] |
| Tier | Standard ab Start | Free-Tier für das ganze Projekt | Owner-Entscheidung 17.11.; rund 65,6 EUR/Monat gespart, kein Uptime-SLA |
| Wartung | außerhalb 12.-20.02., Node-OS `None` [Quelle: PLAN 5.2; RA:592] | `notAllowedDates` 20.01. und 27.01.-20.02. auf drei Konfigurationen, manueller Refresh 26.01., SecurityPatch bis zur Sperre | Probetage, G4 und Messe auf einem Image; ein Refresh heißt einige Minuten Ausfall |
| Struktur | eine RG, Skripte in `gpd/infra/aks` [Quelle: PLAN 4] | drei RGs (Basis, Cluster, feste Node-RG), BYO-UAMI, versioniert in sli/emd | Neuaufbau behält ACR, Egress- und Ingress-IP samt DNS-Label und Key Vault; Budget-Filter mit festen Namen |
| Sicherheitsgeländer | nicht vorgesehen | P0 vor jedem AKS-Kontakt, `kaks`/`haks`, Call-Log-Gate | kein Skript pinnt einen Kontext |
| SAM-Profil | 0,5 PT [Quelle: PLAN 0.5 O6] | rund 2,5-3 PT | Guards, CLI-Seam, Keycloak-Writeback, TLS-Variante, Image-Pfad |
| SAM-Broker | `tcp://...:55555` [Quelle: PLAN 5.2] | `ws://...:8008`, User `sam` | im Lab getesteter Transport |
| Broker-Version | 10.25.0.208 [Quelle: PLAN 5.2] | 10.26.0.9219 LTS per Digest, Lab und AKS | Owner-Entscheidung 17.11.; `latest`/`lts` zeigt darauf, Wartung bis 23.06.2028 |
| GEBIT-VPN | VPN `sam` [Quelle: PLAN 5.1; RA:86,106] | VPN `default` | so implementiert und live [Quelle: gpd UC1-BUILD-SPEC.md:6621; .env.example:9-13] |
| Broker-Disk | 64Gi P6 | 128Gi P10 | P6 hat 240 IOPS, Richtwert 300 |
| MQTT-LB | internes LB für ESP32 | entfällt | ESP32 nur "Soll" [Quelle: PLAN 6, Soll S2]; ohne WireGuard gibt es dafür keinen Weg [A] |
| Aliase | `fast`, `workflow` [Quelle: PLAN 0.5 O5] | `fast`, `planning` | UC1-Stand [Quelle: amd local-k8s-values.yaml:89] |
| Descriptor | ConfigMap [Quelle: PLAN 5.2] | Secret, nur zur Laufzeit vom Mac | UC1-Stand, Vertraulichkeit |
| gRPC-Reflection | an, Ingress nur intern | an und öffentlich, Route erst nach der schriftlichen GEBIT-Bestätigung (AKS-E16); Image 0.1.4 mit gemeinsamem Endpunkt | Owner-Entscheidung 17.11.; ein Host für drei Server; die Reflection gibt die GEBIT-Descriptor-Dateien heraus |
| Laufidentität | power_user (RA 1.2) | `marktleitung@solace.lab` | UC1-Stand |
| Gate-Verifikation | - | volle Verifikation je Ziel | Lab-PASS darf AKS nicht überspringen |
| Kyverno, trust-manager | implizit portiert (DESIGN 4.8) | nicht auf AKS; VAP + PriorityClasses | Enforce-Policies lehnen LE ab; Kyverno 3.9.2+ blockiert Stop |
| Gateway API | nur Ausweichweg, "SAM rendert nur Ingress" [Quelle: RA:231-245] | nicht im Scope; der Nachfolger für ingress-nginx im Lab ist offen | Traefik deckt AKS ab |
| Images SAM | amd64 per `gunzip` + `crane push` [Quelle: PLAN 5.2] | arm64 registry-zu-registry | kein Tarball-Load in den k3s-dockerd |
| Topologie | k3s-Cloud-VM (DESIGN 4.8) | AKS | bereits durch PLAN-E8 ersetzt |
| Aufwand | rund 14 PT [Quelle: RA:567]; PLAN: AKS-Anteil von C 21,5 PT plus 2,5 PT Puffer [Quelle: PLAN 7.3] | 23,5 PT (27,0 mit Puffer) | Geländer, SAM-Profil, Demo-Seams, Lab-Broker-Upgrade, Drills; Abgleich in 8.4 |
| Kosten | rund 860 EUR/Monat [Quelle: RA:499] | rund 300-340 EUR/Monat bei 24/7 (Defender bedingt rund +49) | ein Node, Free-Tier, kein PG Flexible, kein WireGuard |

### 8.3 Korrekturen an Befunden

- Keycloak: aktuell ist 26.8.2 (05.11.2026), nicht 26.7.0 [Quelle:
  GitHub-Releases-API].
- "Läuft auf dem arm64-Lab-Node" belegt nur arm64, nicht multi-arch.
- PLAN 6.2 erlaubt keine Abnahme "Plattform plus Tunnel", sondern
  verschiebt die G2a-AKS-Abnahme in Variante (b) nach G2b.
- Quota muss den Surge-Node einrechnen (16 statt 8 vCPU bei einem
  Node).
- SAM-Broker-Passwort heißt `broker.password`, nicht `clientPassword`.
- Der Lab-SAM-Ingress hat keine `proxy-body-size` (NGINX-Default 1m);
  unter Traefik wirkt ein Limit nur mit `proxy-request-buffering:
  "on"`.
- `az aks check-acr` taugt auf einem reinen arm64-Cluster nicht
  (Prüf-Image nur amd64); P1 prüft AcrPull und einen echten
  arm64-Pull.
- Quota-Anträge werden meist in Minuten automatisch freigegeben; nur
  bei Ablehnung folgt ein Support-Fall mit Tagen.
- Ein Budget nur auf den beiden eigenen RGs sähe die Node-Kosten
  nicht; dafür gibt es die feste Node-RG im Budget-Filter.
- Broker: `latest` und `lts` zeigen auf 10.26.0.9219 (LTS), nicht auf
  10.26.10; 10.26.10.14510 trägt die Tags `edge` und `rolling`
  [Quelle: Docker-Hub-Tags-API, 17.11.].
- Lab-Broker: Nicht nur solace-2, auch solace-1 hält seine DB im
  Container-Layer; `start.sh` würde heute beide neu erzeugen [Quelle:
  Befehle `docker inspect` und `docker compose config --hash`, 17.11.;
  A: per `--dry-run` bestätigen].
- `cloudapp.azure.com` steht nicht auf der Public Suffix List; seit dem
  PSL-PR 1966 (2024) teilen sich alle Azure-Kunden das LE-Limit von
  `azure.com` [Quelle: PSL, abgerufen 17.11.].
- Traefik "v3.6.2+" (AKS-E6, 16.11.) ist veraltet: Minimum v3.7.18,
  fünf Sicherheitsfixes am 12.11. [Quelle: GitHub-Security-Advisories,
  17.11.].
- Der Traefik-Chart legt die IngressClass `nginx` nicht an, der
  SAM-Chart verlangt sie [Quelle: SAM-Chart 2.3.10
  `_validations.tpl`; Traefik-Chart 42.4.1].
- Unter Pfad-Routing liefern `/auth/admin/` und `/auth/realms/master/`
  kein 404 mehr, sondern SAMs SPA-Fallback (200); die Negativtests
  prüfen das Fehlen von Keycloak-Inhalt [Quelle: Befehl `curl` gegen
  den Lab-SAM, 17.11.].

### 8.4 Abgleich mit Aufwand, Terminen und Kosten des PLAN

Die AKS-Posten des PLAN gegen die Phasen dieses Plans [Quelle: PLAN 6
(AP12-AP14b), 7.1 (G0-11a/b), 7.3]:

| PLAN-Posten | PT PLAN | Phasen hier | Bemerkung |
|---|---|---|---|
| AP12 S1-S3 (Subscription, Foundation, Add-ons) | 3,5 | P0 Schritt 5, P1, P2 | eine Woche später als PLAN 7.3 (KW49/50 statt KW48): O4 überfällig, `az login` blockiert |
| AP12 S4 Broker, S5 Keycloak | 2,0 | P4 Teil B, P3 | P4 Teil B erst nach der Abnahme von Teil A |
| AP12 S6 SAM, darin O6 0,5 | 2,0 | P5 | SAM-Profil hier rund 2,5-3 PT |
| AP12 S7-S8 (Overlay, gRPC-Ingresse, Demo) | 2,0 | P6 | plus Seams, `pg`-Teil, Env-Prüfung, Pfad-Ingresses, `public-guard`, Image 0.1.4 |
| AP12 S9 öffentlicher Zugang, HTTPS-RTT, L3-Kopie | 1,5 | P1 (`aks-allow-me.sh`), P2 (öffentliches LB, VAP), P5 (HTTPS-RTT), P6 (TR1-Besuche) | früher WireGuard; netto rund 1,25 PT weniger [A] |
| AP12 S10 Härtung | 1,5 | P7 | - |
| G0-11a, G0-11b | 1,5 | P1 (Probe), P2 Schritt 7, P5 Schritt 7 | Termine nach AKS-E18 (Owner-Bestätigung offen) |
| AP13 AKS-Anteil (24 h, Neuaufbau) | 2,0 | P7 Schritt 3 | ohne N-1-Drain |
| AP14 Betrieb | 3,5 | P7 Schritte 4-7 | Kanarienlauf, Tagesroutine, Exporte und Freeze-Snapshots bleiben PLAN-Posten |
| AP14b L3 | 2,0 | P7 nur der Drill | Aufbau des L3-Profils (Overlay `l3`, SAM-Values `l3`, Export) bleibt PLAN-Posten |
| neu: Sicherheitsgeländer | - | P0 | 2,5 PT |
| neu: Lab-Broker-Upgrade | - | P4 Teil A | 1,0 PT |
| **Summe** | **21,5** (+2,5 Puffer) | **23,5** (+3,5 Puffer) | |

- Mit gebündelter Persistenz (Streichliste Nr. 11, 1,5 PT [Quelle:
  PLAN 6.2]) sinkt die PLAN-Basis auf 20,0 PT.
- P0-P7 decken die AP14- und AP14b-Teile aus der Tabelle nicht ab:
  rund 4,5 PT (AP14 3,0: Preflight 0,5, KW52-1 1,0, KW1-2 1,0, Freeze
  0,5; AP14b 1,5: Aufbau 1,0, G4-Drill 0,5) [Quelle: Abschnitt 6;
  PLAN 7.3]. P7 übernimmt davon nur das AP14-Runbook (0,5) und den
  L3-Drill zu G3 (0,5). Vergleichbar sind damit rund 28,0 PT gegen
  21,5 PT (Delta +6,5 PT) bzw. gegen 20,0 PT (+8,0 PT). Echte
  Neuposten: Geländer (2,5 PT),
  SAM-Profil (+2-2,5 PT gegen 0,5 PT O6), Lab-Broker-Upgrade
  (1,0 PT), Traefik (+0,5 PT), Image 0.1.4 (0,5 PT) und der
  Missbrauchsschutz (0,5 PT); der Wegfall von WireGuard spart netto
  rund 1,25 PT.
- Variante (a): C hat 32,25 von 39,9 PT netto verplant [Quelle: PLAN
  0.4]; frei sind 7,65 PT. Das Delta von 6,5 PT passt rechnerisch
  hinein, lässt aber nur rund 1,15 PT frei. Nach Abschnitt 6 trägt C
  39,5 PT (38,0 nach der Umverteilung von AP11 `/op`) gegen 39,9 PT
  netto, und KW1-2 braucht die Umverteilung aus Abschnitt 6.
  Variante (b): Das Delta vergrößert die Lücke von 6,4 bzw. 7,9 PT
  [Quelle: PLAN 0.4, 6.2]. Das Muss von 118,75 PT steigt um das
  Delta, sofern der Owner die Geländer und das Lab-Broker-Upgrade nicht
  als Teil von AP12 verbucht.
- Termine: G0-11a und G0-11b nach AKS-E18 (Owner-Bestätigung offen);
  die Abhängigkeit "AP12 S6-S10 nach G0-11a" [Quelle: PLAN 6 (AP12),
  6.1] wird phasengerecht umgeschrieben; P0 in KW47 tragen Owner und
  Claude, bevor C am 23.11. beginnt; AP12 S1-S3 rutschen eine Woche
  (O4 überfällig).
- Kosten: Die AKS-Kosten in PLAN 0.4 ("etwa 2,0-3,0 Tsd. €") sinken auf
  rund 470-600 EUR bis zum Rückbau am 20.02.2027 (mit aktivem Defender
  for Containers rund 520-660 EUR) [A: Laufmuster 3.4; Quelle:
  Retail-API 17.11.]; Ziel unter 1.500 EUR (AKS-E1), Monatsbudget
  250 EUR. Gründe: ein Node, Free-Tier, kein WireGuard,
  gebündelte Persistenz, Nachtstopp bis G4, Cluster erst ab 30.11.
- Nach Freigabe im PLAN nachziehen: 0.2 (E7 AKS-Persistenz im Cluster
  statt PG Flexible; E8 mit 1 x D8ps_v6 arm64, Free-Tier, Traefik,
  HTTP-01 mit Azure-DNS-Label, Broker 10.26.0.9219; der Zugang ist dort
  schon nachgezogen), 0.3 (G0b ohne "externe Persistenz" und
  "DSN-TLS"), 0.4 (Kosten), 0.5 (O4 Azure-DNS-Label statt delegierter
  Zone, O6 mit 0,5 PT, AKS-E1 bis AKS-E20), 5.2 (Cluster, Images,
  Ingress, Hosts, SAM-Persistenz, Broker), 6 (AP12-Zeile "SAM extern",
  PT), 6.1 (kritischer Pfad), 6.4, 7.1 (G0-11a/b), 7.2, 7.3 und R5
  (externe Persistenz, ingress-nginx); in 5.2 außerdem das
  SAM-Body-Limit 10m statt 100m mit `limit-connections` (P5 Schritt 2).

### 8.5 Änderungen durch die Owner-Entscheidungen vom 17.11.2026

Gegenüber dem Stand vom 16.11. (Commit `7a860c5`); PT als Aufwand von
C, EUR je Monat bei 24/7 [Quelle: Retail-API 17.11.]:

| Nr | Entscheidung | Stand 16.11. | Stand 17.11. | PT | EUR/Monat 24/7 |
|---|---|---|---|---|---|
| 1 | ein Cluster ohne HA, Free-Tier | 2 x D8ps_v6, Free bis G2b, dann Standard; N-1-Drill | 1 x D8ps_v6, Free durchgehend, kein N-1-Drill; ein Node-Image-Update heißt einige Minuten Ausfall | -0,25 (P7) | -219,5 Node, -19,5 OS-Disk, -65,6 Standard-Tier; dafür unklar 0 bis +32,8 Free-Tier-Zeile |
| 2 | Subscription, Budget | Default nach `az login` prüfen, Budget 450 EUR | vorhandene Subscription des Owners; Budget 250 EUR; Ziel unter 1.500 EUR | 0 | 0 |
| 3 | Domain und TLS | delegierte Subdomain, Azure-DNS-Zone, DNS-01 mit Workload Identity, ein Certificate je Host | ein Azure-DNS-Label auf `pip-aks-ingress`, HTTP-01, ein Zertifikat, Pfad-Routing, Keycloak unter `/auth` | +0,5 (P2 0, P3 +0,25, P6 +0,25) | +3,3 Ingress-IP, rund -0,5 DNS-Zone [A] |
| 4 | Architektur | arm64 | unverändert | 0 | 0 |
| 5 | Zugang | internes LB, WireGuard-VM, Router-Peer, Split-DNS, Mac-Profile, `aks-wg-sync.sh` | öffentlich, nur Traefik am LB, `aks-allow-me.sh`, Admin per Port-Forward | -1,25 (P1 -0,75, P6 -0,25, P7 -0,25 für Peer und UDP-Drill) [A] | -10 VM, -3,3 `pip-wg`, 0 bis -16,4 internes LB [A] |
| 6 | Ingress | ingress-nginx 4.15.1 intern, 2 Replikas; Traefik nur Notschalter | Traefik 42.4.1 mit v3.7.19, 1 Replika, Lücken geschlossen; Lab bleibt ingress-nginx | +0,5 (P2) [A] | 0 |
| 7 | SAM-Persistenz | gebündelt | unverändert, AKS-E19 bleibt | 0 | 0 |
| 8 | Freigaben AKS-E15 | offen | (a) bis (e) erteilt, (a) erledigt (`cd08a17`); Mac-Tools ohne `wireguard-tools` | 0 | 0 |
| 9 | Broker | 10.25.0.208, Lab-Pin auf 10.25.0.208 | 10.26.0.9219 LTS per Digest in Lab und AKS; Lab-Upgrade als P4 Teil A | +1,0 (P4) [A] | 0 |
| 10 | Missbrauchsschutz | nicht nötig (privat) | `public-guard`, LiteLLM-Limits am Messe-Key, Missbrauchs- und Kostentest | +0,5 (P6 +0,25, P7 +0,25) [A] | 0 |
| 11 | gRPC | nur intern, Reflection-Frage an GEBIT, Varianten (b) und (c) | öffentlich, Reflection an; Image 0.1.4 mit gemeinsamem Reflection-Endpunkt | +0,5 (P6) [A] | 0 |
| 12 | GEBIT | Anfrage offen | Freigabe vom Owner berichtet; Descriptor-Secret in Azure und öffentliche Reflection als Planungsannahme [A], gehandelt erst nach schriftlicher Bestätigung (Status offen, spätestens 09.12.) | 0 | 0 |
| 13 | AKS-E18, AKS-E20 | Empfehlung | Empfehlung bleibt, Owner-Bestätigung offen | 0 | 0 |
| | **Summe** | 22,0 PT; rund 620-640 EUR/Monat | 23,5 PT; rund 300-340 EUR/Monat | +1,5 | rund -300 |

- Je Phase gegenüber dem 16.11.: P1 -0,75, P2 +0,5, P3 +0,25, P4
  +1,0, P6 +0,75, P7 -0,25; P0 und P5 unverändert [A].
- Kosten im Aufbau mit Nachtstopp (220 Laufstunden im Monat): rund
  145-185 statt 250-300 EUR/Monat. Projektsumme bis 20.02.2027: rund
  470-600 statt 900-1.200 EUR, mit aktivem Defender for Containers
  rund 520-660 statt 1.000-1.350 EUR [A: Laufmuster 3.4].
- Neue Arbeitspunkte: Lab-Broker-Upgrade (P4 Teil A, 5.3), Image 0.1.4
  (5.4), `aks-allow-me.sh`, Traefik-Values mit den Lückenschlüssen,
  EAB-Rückfall-Issuer, Pfad-Ingresses für gpos, gRPC und Keycloak,
  `public-guard` mit Missbrauchstest, Hairpin-Test schon in P1.
- Nachträge aus dem Review vom 17.11. laufen ohne eigene PT in den
  Phasen mit [A]: Routentest mit zwei Listen und ungeroutete
  `/freigabe`, `/foto`, `/op`, `/etikett` (P6), `limit-rpm` auf den
  gRPC-Service-Pfaden (P6), `gebitsim` mit Descriptor-Secret nur nach
  Bestätigung (P2), Puffer-Schutz und Access-Log ohne Query (P2, P5),
  `coredns-custom` vor dem ersten Certificate (P2), VAP nur für
  `traefik/traefik` (P2), SEMP-Identitätsprüfung in `stop.sh` und
  Ignore-Regeln (P0), Passwort-Policy und Approver-Login (P3),
  Zertifikats-Widerruf und Löschung lokaler Secrets (P7).
- Entfallen: WireGuard-VM mit `cloud-init-wg.yaml`, `pip-wg`,
  `nsg-wg`, `snet-wg`, `wg-server-key`, Router-Peer, Mac-Profile
  `aks-admin` und `aks-admin-full`, `wireguard-tools`,
  `aks-wg-sync.sh`, Split-DNS und Rebind-Ausnahmen, internes LB,
  ingress-nginx-Values für AKS, DASv6- und Basv2-Quota, Tunnel-RTT,
  UDP-Drill, N-1-Drill, Standard-Tier-Wechsel, DNS-Zone und
  Delegation, `id-cert-manager` mit Workload Identity und Federated
  Credential.
- Unverändert: P0-Geländer, `kaks`/`haks`, `require_kube_context`,
  Call-Log- und Render-Diff-Gates, die Regeln für den LiteLLM-Key, Key
  Vault für generierte Secrets, AKS-E19, die Wartungssperre per
  `notAllowedDates`, der Nachtstopp bis G4 und der Notbetrieb L3 aus
  dem Lab.

Abgelehnt (Owner, 17.11.2026): ein Azure-DNS-Label je Hostname, also
sechs Namen (`<p>-sam`, `<p>-auth`, `<p>-gpos` und drei gRPC-Namen)
mit je einer statischen IP, Traefik mit `service.additionalServices`
und rund 13 LB-Regeln. Die Variante hätte das Lab-Modell "ein Host je
App" und Reflection je Server ohne neues Image behalten. Sie kostet
aber rund 69 EUR/Monat mehr bei 24/7 (5 IPs und 10 LB-Regeln mehr)
und braucht ein Zertifikat über sechs Namen [Quelle:
Retail-API 17.11.;
`learn.microsoft.com/azure/virtual-network/ip-services/public-ip-addresses`].
Ebenfalls verworfen: ein Name mit Port-Mapping (Firmen-Proxys erlauben
CONNECT meist nur auf 443 [Quelle: Squid cf.data.pre:1764, 2005], und
der NGINX-Provider kennt nur einen HTTPS-EntryPoint), Azure Front Door
(gRPC erst in Preview, Origin-Timeout höchstens 240 s), Application
Gateway for Containers (ab rund 125 EUR/Monat), das
App-Routing-Add-on und eine gekaufte Domain (beide mit eigener
DNS-Zone).

## 9. Offene Fragen

1. AKS-E18 (Owner-Bestätigung offen): G0-11a nach G2a (18.12., P5),
   HITL-Teil von G0-11b nach P5, gRPC-Teil am 11.12.?
2. AKS-E20 (Owner-Bestätigung offen): Wer sind Betreiber und
   Stellvertreter an Probetagen und Messe? Vorschlag: C Betreiber,
   Entwickler A Stellvertreter (bei O9 = (b): A Betreiber, Owner
   Stellvertreter).
3. O9: Gibt es ab 23.11. eine dritte Person für den AKS-Track, oder
   läuft er neben TR5/TR3 (Stichtag 20.11.)?
4. GEBIT (AKS-E16, Status offen, harte Vorbedingung): Deckt die am
   17.11. berichtete Freigabe das Descriptor-Set als K8s-Secret in
   Azure Germany West Central, den Zugriff des Stellvertreters und die
   öffentliche Reflection, die die GEBIT-Descriptor-Dateien selbst an
   jeden ausliefert [A: ja als Planungsannahme]? Schriftlich bis 27.11.,
   spätestens 09.12. (vor `gebitsim` in P2 Schritt 7, G0-11b (3) am
   11.12.); sonst G0-11b (3) mit einem Testserver ohne GEBIT-Material
   als dokumentierte Abweichung von PLAN 7.1 oder nach G2b, und kein
   GEBIT-Material in Azure. Wann kommen die Netzparameter des Stands
   (Uplink, 5G; fällig 18.12. [Quelle: PLAN 6.5])?
5. LiteLLM: Gibt es eine Quell-IP-Allowlist (auch für `/v1/*`)? Kommt
   der Messe-Key (O5) mit `max_budget` 150 USD, und welche
   `rpm_limit`- und `tpm_limit`-Werte setzt der Betreiber?
6. Subscription: Darf der Owner Rollen zuweisen (Network Contributor
   auf `rg-eurocis-base` für `id-aks-cp`, `--attach-acr`, AKS-RBAC, Key
   Vault Secrets Officer) und ein Budget mit Filter anlegen? Gibt es
   Policies gegen Public IPs oder öffentliche Load Balancer, eine
   Tag-Pflicht, aktive Defender-Pläne und eine kurze
   Conditional-Access-Anmeldehäufigkeit?
7. Welches neutrale Präfix `<p>` bekommt das DNS-Label (CT-Logs sind
   öffentlich)? Die Verfügbarkeit in Germany West Central prüft P0.
8. ACME-Rückfall: ZeroSSL oder Google Trust Services, und legt der
   Owner das EAB-Konto bis zum Prüfpunkt 04.12. an?
9. API-Server: authorized IP ranges mit `aks-allow-me.sh` (Vorschlag)
   oder nur Entra ID mit Conditional Access? Darf `aks-allow-me.sh`
   im Freeze laufen?
10. Traefik im Freeze: Ausnahme nur für Patch-Releases mit
    Smoke-Wiederholung?
11. Lab-Broker-Upgrade (P4 Teil A): Wann gibt der Owner das Go, und
    wann liegt das Wartungsfenster für solace-1 (Vorschlag: Probe an
    solace-2 in KW48, solace-1 spätestens 04.12.)? Das Fenster trifft
    alle Lab-Demos auf diesem Broker. Woher kommen die iCargo-User und
    die ACL `iCargo` (nicht in Terraform)?
12. Bestätigt der sam-CLI-Spike (P0 Schritt 12) die Fragen (a) bis (d)?
13. Entschieden (AKS-E8, 17.11.), keine offene Frage mehr: `prod1k`;
    `dev` nur nach Kriterium 3.2 (CPU-Requests nach P2 über 2044m,
    92-%-Grenze) vor dem ersten Install in P4. `prod1k` hat mehr RAM
    als der Lab-Broker heute belegt, `dev` liegt darunter (OOM-Risiko);
    später hieße ein Wechsel Neuaufbau des Brokers.
14. `GPOS_DELIVERY=persistent` auf AKS testen (kein DMR-Rückstau dort)
    oder bei `direct` bleiben?
15. Wird die Preiszeile "FreeTierInfrastructureCost Uptime SLA"
    abgerechnet, und laufen LB-Regeln und IPs im Stopp weiter?
16. developer-mcp auf AKS bereitstellen? UC1 braucht ihn nicht, der
    Endpunkt wäre öffentlich (per OIDC geschützt).
17. L3 (AP14b) behalten? Streichliste Nr. 4 würde 3 PT sparen
    [Quelle: PLAN 6.2], nimmt aber den Notbetrieb.
18. Nach der Messe: Rückbau (mit Key-Vault-Purge) oder GEBIT-Übergabe
    (dann amd64-Pool und Multi-Arch-Build)?
19. Nachfolger für ingress-nginx im Lab nach der Messe: Traefik wie auf
    AKS (dieselben Manifeste) oder Gateway API?
20. Lab-Chart-Versionen in sli pinnen?
21. Gilt `pos.receipt.receipt_b64` (Demo-Belege im Format der
    GEBIT-Receipt-API) als GEBIT-Material, das nicht in Backups darf?
22. Mac-Tool `cmctl` (Homebrew) für die Erneuerung am 15.01. (P2
    Schritt 6, P7 Schritt 6): Go des Owners? AKS-E15 (e) nennt es
    nicht.
23. Exposition weiterer BFF-Seiten (AKS-E5, Owner-Bestätigung offen,
    vor G2b [Quelle: PLAN 9 R24]): `/freigabe` (Freigabe-Tablet,
    beantwortet pausierte SAM-HITL-Läufe über die BFF; öffentlich
    könnte jeder Preise freigeben oder ablehnen), `/foto` (Upload
    startet den Vision-Agenten), `/op` (Operator-Seite aus AP11,
    Umschaltung auf L4) und `/etikett`, je samt API-Routen. Optionen:
    öffentlich (LLM-auslösende Routen nur mit eigenem
    `public-guard`-Limit), nur per Port-Forward bzw. im Lab, oder ein
    Schutz vor G2b (etwa `whitelist-source-range` auf die Stand-IP,
    bricht beim 5G-Wechsel). Bis zur Antwort haben sie keinen Pfad auf
    `<fqdn>`; der Routentest aus P6 Schritt 2 scheitert, wenn einer
    geroutet ist. Der 10-h-Kiosklauf in P7 nimmt `/freigabe` nur nach
    der Antwort über den gewählten Weg mit.
