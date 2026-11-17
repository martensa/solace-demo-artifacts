# AKS-Migrationsplan: EuroCIS-Showcase vom Lab nach Azure

Stand 16.11.2026, nach dem Review vom selben Tag überarbeitet.
Vorschlag für den Owner, read-only erarbeitet: Es wurde nichts
angelegt, geändert oder gelöscht. Messe: EuroCIS 2027, 16.-18.02.2027.
Gates: G2a 18.12.2026, G2b 15.01.2027, G3 22.01.2027, Freeze G4
05.02.2027 [Quelle: PLAN:141-150].

Lesehinweis:

- Abkürzungen für Quellen: `sda` = Repo solace-demo-artifacts, `sli` =
  Repo solace-lab-infrastructure, `amd` = sda/agent-mesh-deployment,
  `emd` = sda/event-mesh-deployment, `gpd` =
  sda/gebit-price-agent-demo, `PLAN` = gpd/IMPLEMENTATION-PLAN.md,
  `RA` = gpd/research/impl/research-aks.md.
- "Befehl (16.11.)" heißt: read-only im Lab oder gegen öffentliche
  APIs ausgeführt, am 16.11.2026.
- [A] markiert eine Annahme, die noch zu prüfen ist.
- Preise: Listenpreise Pay-as-you-go, EUR ohne MwSt., Germany West
  Central, 730 h/Monat [Quelle: `prices.azure.com/api/retail/prices`,
  16.11.].
- Platzhalter: `<zone>` (DNS-Zone), `<acr>`, `<kv>`, `<owner-ip>`,
  `<owner-objectId>`, `<subscription>`, `<tenant>`. Die Werte stehen
  nur lokal, nie in diesem Dokument.
- Entscheidungen dieses Plans heißen `AKS-E1` bis `AKS-E20`, damit sie
  nicht mit den PLAN-Entscheidungen (PLAN-E1 bis PLAN-E8) und den
  Owner-Punkten O1-O9 kollidieren.
- `kaks` und `haks` sind die einzigen Ad-hoc-Wege zu AKS für kubectl
  und helm (Definition in P1 Schritt 6). Lab-Befehle tragen
  `--context rancher-desktop`.
- Keine Secrets, IDs, E-Mail-Adressen oder LLM-Hostnamen in diesem
  Dokument. Das GEBIT-Material heißt hier nur "GEBIT-Descriptor-Set".

## 0. Kurzfassung

- **Empfehlung:** Ein neuer AKS-Cluster (Kubernetes 1.36, Germany West
  Central, 2 x `Standard_D8ps_v6`, arm64) baut den Lab-Stack mit
  denselben Charts, Versionen, Namen und Image-Digests nach ("Parität
  zuerst"). SAM bleibt gebündelt (Postgres + SeaweedFS), Keycloak,
  Broker und Demo-DB laufen im Cluster.
- **Von Tag 1 in Messe-Form erreichbar:** ingress-nginx auf internem
  LB, öffentliche DNS-Namen auf private IP, WireGuard-VM für Macs und
  Stand (der Stand-Peer erreicht nur die Ingress-IP), API-Server nur
  von freigegebenen IPs. Keycloak-Admin und Grafana nur per
  Port-Forward. G2a und G2b verlangen WireGuard ohnehin [Quelle:
  PLAN:145, PLAN:147].
- **Ersetzt statt portiert:** Lab-CA, trust-manager, Kyverno und
  registry:2 werden zu Let's Encrypt DNS-01, ACR und eingebauter
  ValidatingAdmissionPolicy.
- **Zuerst Sicherheitsgeländer:** Kein Skript pinnt heute einen
  kube-Kontext. Ein Lab-`stop.sh` gegen AKS würde dort SAM löschen und
  zugleich Lab-Keycloak-Client und Lab-Broker-Queues abräumen. Deshalb
  laufen alle AKS-Aufrufe nur über `kaks`/`haks` oder Skript-Wrapper
  mit `require_kube_context`, und ein Call-Log-Gate belegt, dass die
  Lab-Aufrufe gleich bleiben.
- **LiteLLM-Key geschützt:** SAM speichert ihn im Klartext in der
  Plattform-DB. Auf AKS gibt es deshalb ein eigenes
  SAM-Postgres-Passwort, NetworkPolicies, `grafana_ro` ohne die
  Key-Tabellen und Backups ohne deren Daten (AKS-E19, 1.4).
- **Phasen:** P0 Klärungen + Geländer (2,5 PT, bis 27.11.), P1 Azure,
  Cluster, CLI, WireGuard (2,75 PT, KW49), P2 Add-ons (2,5 PT), P3
  Keycloak (1,0 PT), P4 Broker (1,25 PT), P5 SAM (2,5 PT, G2a 18.12.),
  P6 Demo (5,0 PT, G2b 15.01.), P7 Härtung und Betrieb (4,5 PT, G3/G4).
  Summe rund 22 PT, mit Puffer rund 25 PT; bis G2a 12,5 PT.
  Prüfpunkte am 04.12. und 11.12. entscheiden früh, ob der AKS-Teil von
  G2a nach G2b wandert.
- **Kosten:** rund 620-640 EUR/Monat bei 24/7 mit Standard-Tier, rund
  250-300 EUR/Monat im Aufbau mit Nacht- und Wochenend-Stopp,
  Projektsumme bis 20.02.2027 rund 0,9-1,2 Tsd. EUR (mit aktivem
  Defender for Containers rund 1,0-1,35 Tsd. EUR). Ein Monatsbudget
  von 450 EUR überwacht alle drei Ressourcengruppen.
- **Blocker heute:** `az login` (Token scheitert mit AADSTS9002313;
  Abhilfe laut CLI: `az logout`, dann `az login --tenant <tenant>`),
  Azure CLI 2.85.0 veraltet, delegierte DNS-Zone, schriftliche
  GEBIT-Freigabe, Repo-Freigaben.
- **Die 9 Owner-Entscheidungen zuerst:** (1) Subscription, Quota,
  Budget, Domain; (2) arm64; (3) privat mit WireGuard ab Tag 1; (4)
  ingress-nginx 4.15.1 eingefroren bis nach der Messe; (5) gebündelte
  Persistenz statt PG Flexible + Blob; (6) Freigabe der Änderungen an
  geteilter Infra und der Mac-Tools; (7) GEBIT-Freigabe für das
  Descriptor-Set in Azure; (8) G0-11a/b auf G2a verschieben
  (AKS-E18); (9) Betreiber und Stellvertreter für Probetage und Messe
  (AKS-E20).

## 1. Ziel und Abgrenzung

### 1.1 Ziel

AKS wird ein zusätzliches Ziel, kein Ersatz. Das Lab bleibt
Entwicklungsumgebung: Entwicklung und Tests laufen im Lab, zum Ende
jedes Gates geht derselbe Stand mit `install.sh TARGET=aks` auf AKS
[Quelle: PLAN:135 (PLAN-E8)]. Das Lab-Verhalten bleibt unverändert:
gleiche Aufrufe bis auf den expliziten Lab-Kontext, belegt durch ein
Call-Log-Gate und ein Render-Diff-Gate (P0 Schritt 13).

### 1.2 Was nach AKS geht

| Baustein | Lab heute | AKS | Quelle |
|---|---|---|---|
| Ingress | ingress-nginx 4.15.1, Port-Forward auf den Mac | gleicher Chart gepinnt, internes Azure-LB, 2 Replikas | Befehl `helm list -A` (16.11.); sli ingress/scripts/setup.sh:47-49 |
| TLS | private Root/Intermediate-CA, nur `solace.lab` | Let's Encrypt DNS-01 auf Azure DNS (Workload Identity) | sli pki/manifests/02-pki-ca-hierarchy.yaml:126-131 |
| Monitoring | kube-prometheus-stack 83.5.0, Loki 6.55.0, Tempo 2.0.0, Alloy 1.11.0 | gleiche Versionen, Prometheus auf PVC statt emptyDir, Images aus ACR, Grafana ohne Ingress (Port-Forward) | Befehl `helm list -A` (16.11.); sli pki/manifests/05-monitoring-values.yaml:48-70 |
| Identity | Keycloak 26.2 (Floating-Tag) + Postgres 17, Realm `solace-lab` | Keycloak 26.8.2 gepinnt, gleicher Realm, `*@solace.lab` unverändert | sli keycloak/manifests/03-keycloak.yaml:141; `api.github.com/repos/keycloak/keycloak/releases` |
| SAM | 2.542.1, Chart 2.3.10, str 1.80.2, ns `sam-solace-lab`, gebündelt | identisch, zweites Values-Overlay | amd local-k8s-values.yaml:156-160 |
| Broker | `solace-1` 10.25.0.208 in Docker, VPN `sam` + `default` | ein PubSub+ Standard 10.25.0.208 per Helm, ClusterIP, kein DMR | Befehl SEMP monitor (16.11.); emd docker-compose.yaml:27-57 |
| GEBIT-Demo | ns `gpos-demo`, 6 Deployments, Image 0.1.3 arm64 | gleiches Image in ACR, kustomize-Overlay `aks` | Befehl `kubectl -n gpos-demo get deploy` (16.11.) |
| Demo-DB | Host-Docker `postgres` 18.3, DB `gpos` 25 MB | Postgres-18-StatefulSet im eigenen Namespace `gpos-data`, neu aus dem Seed | Befehl `docker exec postgres psql` (read-only, 16.11.) |
| SAM-Paket | `gpos-uc1`: 5 Connectoren, 3 Agents, 3 Workflows, RBAC, 2 Entrypoints | inhaltlich unverändert; Haupt-Manifeste unverändert angewendet, nur die Entrypoints je Ziel gerendert | gpd mesh/manifest.yaml:11-15 |
| Neu | - | ACR, Key Vault, Azure-DNS-Zone, WireGuard-VM, 2 statische IPs, 3 Ressourcengruppen | - |

### 1.3 Was im Lab bleibt

| Teil | Grund | Quelle |
|---|---|---|
| db-designer und die db-jpa-Queues | anderer Showcase | Befehl `kubectl top pods -A` (16.11.) |
| `mi-solace-lab` (PVC 10Gi) | einzige Kopie der Demo-Daten, nicht Teil des Showcase | Memory "Lab cleanup safety" |
| `sam-solace-lab-agents` (v1-Lab-Agents) | Lab-Agents aus solace-sam-artifacts, kein Teil von UC1 | Befehl `kubectl top pods -A` (16.11.) |
| searxng (`sam-solace-lab-shared`) | nur für Lab-Agents | dito |
| Registry `oci` (50Gi) | ersetzt durch ACR | sli registry/manifests |
| `solace-2`, DMR-Link | AKS braucht nur einen Broker | Befehl `docker ps -a` (Exited seit 13 Tagen) |
| EMA/Event Portal (VPN `amartens-test`), OTel-Collector, Broker-Tracing | Lab-Event-Mesh-Story, nicht GEBIT; Jaeger gibt es nicht mehr | emd docker-compose.yaml:7-105 |
| Kyverno, trust-manager, Lab-CA, pgadmin | im Lab weiter nötig, auf AKS ersetzt | sli pki/manifests/04-kyverno-policies.yaml |
| andere Demos (retail, manufacturing, insurance, bsg) | nicht im Scope | - |

### 1.4 Leitplanken, die der Plan einhält

- Der LiteLLM-Key lebt nur in SAMs eigener Konfiguration:
  `amd/.env.aks` → `helm --set` (vom Chart erzeugtes SAM-Core-Secret)
  und `apply-models.sh` in die Modellkonfiguration. Nie in gpd-`.env`,
  Demo-Secrets, Workflows, `tool_config` oder Key Vault
  [Quelle: Chart templates/secret-core.yaml:37-39 laut SAM-Leser].
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
- Jeder kubectl- und helm-Aufruf gegen AKS läuft über `kaks`/`haks`
  oder einen Skript-Wrapper mit `require_kube_context`; die
  AKS-kubeconfig liegt nie in `~/.kube/config`.
- Änderungen an geteilter Lab-Infra nur mit ausdrücklicher Freigabe.
- Browser-Logins und Passwörter macht der Owner (der Stellvertreter
  nur für sein eigenes Konto), nicht Claude.
- Das Lab funktioniert nach jedem Schritt unverändert (Regressions-Gate).

## 2. Entscheidungen des Owners

Nummern mit Präfix `AKS-`; PLAN-Entscheidungen heißen hier PLAN-E1 bis
PLAN-E8.

| Nr | Entscheidung | Empfehlung | Alternativen | Bis wann |
|---|---|---|---|---|
| AKS-E1 | Subscription, Kostenstelle, Quota, Budget (Plan-Punkt O4, fällig war 13.11. [Quelle: PLAN:203]) | Default-Subscription nach `az login` prüfen; Quota-Antrag am 20.11. für DPSv6, DPSv5 und DASv6 je 24 vCPU plus Basv2 2 vCPU (Total Regional mindestens 26); Monatsbudget 450 EUR auf `rg-eurocis-base`, `rg-eurocis-aks` und `rg-eurocis-nodes` (Actual 100 %, Forecast 100 %, 01.12.2026-31.03.2027); Projektsumme (Ziel bis 1.500 EUR) per Cost-Analysis-Ansicht; Defender-Pläne der Subscription geklärt | eigene Subscription; Quota-Antrag meist in Minuten (Auto-Freigabe), sonst Support-Fall mit Tagen [Quelle: `learn.microsoft.com/azure/quotas/per-vm-quota-requests`]; ohne Rechte auf Subscription-Ebene je RG ein Budget | 20.11. |
| AKS-E2 | Region | Germany West Central | West Europe (gleiche v6-Preise [Quelle: Retail-API 16.11.]) | 20.11. |
| AKS-E3 | Architektur | arm64, 2 x `Standard_D8ps_v6`: gleiche Digests wie Lab, kein Multi-Arch-Build, 439 statt 575 EUR/Monat | amd64 2 x `D8as_v6` (+136 EUR/Monat, +1-1,5 PT, GEBIT-Übergabe-Parität); `D8ps_v5` bei Dpsv6-Engpass; Quota für alle drei ist schon beantragt | 27.11. |
| AKS-E4 | Domain, DNS, TLS | Subdomain einer Solace-Domain an Azure DNS delegieren, LE DNS-01 mit Workload Identity, ein Certificate je Host; Zone schon in P0 (25.11.) anlegen | eigene Demo-Domain, falls die Delegation nicht bis 02.12. steht; private CA nicht empfohlen (Keychain, iPads, JVM) | 25.11. |
| AKS-E5 | Zugriffsmodell | privat ab Tag 1: internes LB, WireGuard-VM mit FORWARD-Regeln je Peer, API-Server mit authorized IP ranges (WG-VM-IP + Owner-IP); Admin-Peers mit Voll-Tunnel-Profil für Netze außerhalb der Allowlist; kein späterer Wechsel nötig | öffentliches LB mit IP-Allowlist nur als Notpfad im Aufbau; Wechsel auf privat dann spätestens vor G2a (18.12.), nie nach G3 (5G-Failover bricht Allowlists, BFF hat kein Login [Quelle: RA:569-573]) | 27.11. |
| AKS-E6 | Ingress-Controller | ingress-nginx 4.15.1 gepinnt, nur intern, Snippets aus, VAP blockt `mirror-target`; Nachfolger für Lab und AKS nach der Messe gemeinsam | Traefik v3.6.2+ mit NGINX-Provider (1-PT-Notschalter); App-Routing Gateway API `approuting-istio` (az 2.86+, HTTPRoute-Zwillinge, kein Body-Limit); Application Gateway for Containers (rund 125 EUR/Monat) | 27.11. |
| AKS-E7 | SAM-Persistenz | gebündelt (Postgres + SeaweedFS 2 CPU/2Gi) auf `managed-csi-premium`, Superuser-Passwort aus Key Vault (`sam-pg-admin`); Keycloak- und Demo-DB ebenfalls im Cluster | extern: PG Flexible + Blob (+1,5-2 PT, rund +108 EUR/Monat, nie im Lab gelaufen); der Plan nennt gebündelt selbst als Rückfall [Quelle: PLAN:2545] | 27.11. |
| AKS-E8 | Broker | PubSub+ Standard 10.25.0.208 per `pubsubplus` 3.10.0 im Cluster, `prod1k`, ClusterIP, P10 128Gi, VPN-Layout wie Lab, eigene User `sam` und `gpos` | Solace Cloud (ein VPN je Service, TLS-only, Änderung an `bus.py` nach UC1-Freeze); Größe `dev` (1 vCPU/3,4 GiB) | 27.11. |
| AKS-E9 | Monitoring | OSS im Cluster, Lab-Versionen, Images aus ACR, Tempo bleibt (im Owner-Scope); Grafana ohne Ingress, Zugriff per Port-Forward | Azure Managed Prometheus + Grafana (+125-215 EUR/Monat, Dashboards und ServiceMonitors portieren) | 04.12. |
| AKS-E10 | Keycloak | bleibt, im Cluster, Realm `solace-lab`, 26.8.2 gepinnt, generierte Passwörter; Ingress nur für die Realm-Pfade, Admin-Konsole per Port-Forward | 26.2-Lab-Digest (Release-Linie ohne Upstream-Support); Entra ID als IdP (nicht empfohlen: RBAC-Manifeste, Claim-Mapping) | 04.12. |
| AKS-E11 | LiteLLM | statische Egress-IP `pip-aks-egress` schon in P0 angelegt, an den Betreiber bis 25.11.; Messe-Key (O5) nur in die SAM-Konfiguration | kein separater Messe-Key (dann Lab-Key auf AKS) | Anfrage 20.11., IP an Betreiber bis 25.11., Bestätigung 27.11., Test P1 (03.12.) |
| AKS-E12 | Kyverno, trust-manager, Lab-Registry auf AKS | nicht installieren; ValidatingAdmissionPolicy + PriorityClasses | Kyverno 3.7.1 gepinnt mit umgeschriebenen Policies (+0,5 PT; Chart 3.9.2+ blockiert `az aks stop`) | 27.11. |
| AKS-E13 | Cluster-Zugriff, Mac-Tools | Entra ID + Azure RBAC, lokale Accounts aus, eigene kubeconfig `~/.kube/aks-eurocis.yaml` nur über `kaks`/`haks`, Azure-kubelogin aus dem Tap, Azure CLI als Cask (2.93 oder neuer), WireGuard als `wireguard-tools` (wg-quick, skriptbar) | lokaler Admin-kubeconfig (statisches Admin-Zertifikat 3 Monate auf der Platte); WireGuard-App aus dem App Store (nicht skriptbar) | 27.11. |
| AKS-E14 | Version, Tier, Wartung, Laufzeiten | 1.36.x gepinnt, Auto-Upgrade aus, Node-OS-Kanal SecurityPatch Mi 08-12 Uhr; manueller Node-Image-Refresh Di 26.01.2027; `notAllowedDates` 20.01.2027 und 27.01.-20.02.2027 auf allen drei Wartungskonfigurationen; Free-Tier bis G2b, dann Standard; nachts stoppen bis G4 (Start frühestens 30 min nach Stop), ab 05.02. 24/7 | 1.35 (im Testbereich von ingress-nginx, EOL März 2027); Node-OS `None` mit einem manuellen Refresh | 27.11. |
| AKS-E15 | Freigaben geteilte Infra | (a) offenen amd-Working-Tree committen, (b) Profil + Kontext-Guard in amd-Skripten inkl. Keycloak-Teardown-Skripten, (c) neue Ordner `sli/aks/` und `emd/aks/`, `emd/terraform-aks/`, `amd/manifests/aks/`, (d) Lab-Broker-Image auf 10.25.0.208 pinnen | alles in gpd (Lab-Skripte ohne Guard) | 20.11. |
| AKS-E16 | GEBIT | schriftliche Freigabe: Descriptor-Set als K8s-Secret in Azure GWC, Zugriff Owner und namentlich benannte Stellvertretung (AKS-E20), Löschung bis 20.02.; gRPC-Ingresses nur intern; Frage: Darf Reflection (grpcurl/Postman an Stand und Tiefenecke [Quelle: PLAN:546-550]) über die nur internen, nur per WireGuard erreichbaren gRPC-Ingresses aktiv sein?; Netzparameter des Stands | ohne Freigabe läuft die Demo nur im Lab oder L3; verlangt GEBIT Reflection aus: Sperre am aks-Ingress (Variante c, kein neues Image) oder Schalter in Image 0.1.4 (Variante b), P6 Schritt 7 | Anfrage 20.11., Antwort 11.12. |
| AKS-E17 | Secrets | Key Vault (RBAC-Modus, Soft-Delete 7 Tage, ohne Purge-Schutz) als Kopie außerhalb des Macs für generierte Secrets (hex, ohne Zeilenumbruch) und TLS-Backups, ohne CSI-Treiber | nur `.env.aks` + Passwortmanager des Owners | 27.11. |
| AKS-E18 | Gate-Verschiebung G0-11a/G0-11b | G0-11a nach G2a (18.12., P5), die LiteLLM-Probe in P1 ist nur Frühindikator; Prüfung (4) DSN-TLS entfällt mit AKS-E7; Prüfung (2) Vision auf Modellebene in P5, mit `gpos-price-scout` in P6; G0-11b gRPC (3) bleibt am 11.12. (P2 Schritt 6), HITL (1) wandert nach P5 (18.12.); AP12 S1-S3 von KW48 nach KW49/50 | PLAN-Termine 03.12./11.12. halten (verlangt den Cluster in KW48, vor AKS-E3 bis AKS-E17) | 27.11. |
| AKS-E19 | Schutz der SAM-Datenbank | eigenes Superuser-Passwort `sam-pg-admin` ab dem ersten Install; NetworkPolicies nur für SAM-Postgres und SeaweedFS (abweichend von RA R15 [Quelle: RA:599]); `grafana_ro` nur mit expliziter Tabellenliste | Chart-Default `password` ohne NetworkPolicy (RA R15): dann kann jeder Pod im Cluster, auch die BFF ohne Login, den LiteLLM-Key lesen | 04.12. (vor dem ersten SAM-Install) |
| AKS-E20 | Betrieb an Probetagen und Messe | Betreiber und Stellvertreter namentlich; Vorschlag nach PLAN 6.4/7.3: Person C Betreiber, Entwickler A Stellvertreter (bei O9 = (b): A Betreiber, Owner Stellvertreter) [A]; eigene Konten, Rollen, WG-Peer, Keycloak-User | nur der Owner (Risiko in Abschnitt 7) | Name 20.11. (für die GEBIT-Anfrage), Rollen bis G3 |

## 3. Sizing

### 3.1 Gemessener Lab-Footprint der umziehenden Teile

Nutzung = `kubectl top` bzw. `docker stats`; Peak = Prometheus
`max_over_time` 11.-16.11. (Pod-Ebene, plus Page-Cache-Abstand)
[Quelle: Befehle `kubectl top pods -A`, `kubectl get pods -A -o json`
summiert, Prometheus-Query, `docker stats --no-stream`, alle 16.11.].

| Namespace / Teil | Nutzung CPU / RAM | 6-Tage-Peak RAM | Requests CPU / RAM | Limits |
|---|---|---|---|---|
| ingress-nginx | 3m / 215Mi | 246Mi | 100m / 90Mi | keine |
| cert-manager + trust-manager | 6m / 329Mi | 382Mi | 100m / 320Mi | RAM 640Mi |
| kyverno (entfällt auf AKS) | 43m / 536Mi | 647Mi, CPU-Spitze 7,0 Kerne | 400m / 320Mi | RAM 768Mi |
| monitoring | 61m / 4788Mi | 5728Mi | 660m / 1266Mi | 4700m / 9984Mi |
| iam (Keycloak + PG) | 4m / 841Mi | 875Mi | 300m / 768Mi | RAM 1536Mi |
| sam-solace-lab | 43m / 1849Mi | 2565Mi | 2450m / 4608Mi | 14500m / 10752Mi |
| gpos-demo | 20m / 433Mi | 541Mi | 300m / 768Mi | RAM 2304Mi |
| **Summe Kubernetes** | **180m / 8991Mi** | 8391Mi gleichzeitig (+2,4 GiB Cache) | **4310m / 8140Mi** | 19200m / 25984Mi |
| solace-1 (Docker) | 57m / 4,19 GiB | - | keine | keine |
| Demo-Postgres (Docker) | ~1m / 173 MiB | - | keine | keine |
| **Gesamt** | **~0,24 Kerne / 13,1 GiB** | | | |

Befunde:

- Die Lab-Requests liegen 3- bis 4-mal unter der Nutzung (Monitoring
  1,2 GiB angefordert, 4,7 GiB genutzt). Auf AKS werden Requests auf
  die Ist-Werte gesetzt.
- Keycloak wurde am 04.11. bei 1Gi OOMKilled [Quelle: Befehl `kubectl
  get pods -A -o json` lastState; sli keycloak/manifests/03-keycloak.yaml:201-204].
- SeaweedFS hing am Subchart-Default 500m/512Mi; der Fix (2 CPU/2Gi)
  liegt uncommittet im Working Tree [Quelle: amd
  local-k8s-values.yaml:258-273; `git status`].
- Prometheus liegt auf emptyDir (4,7 GiB TSDB) [Quelle: Befehl
  `kubectl get statefulset ... -o json`, 16.11.].

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
| solace-2, EMA (Docker) | Exited seit 13 Tagen | - | - |

### 3.2 Rechenweg

Requests auf AKS = max(Lab-Request, gemessener Peak + Cache), gerundet
[Quelle: Footprint-Leser 16.11.]:

| Komponente | CPU | RAM | Begründung |
|---|---|---|---|
| ingress-nginx, 2 Replikas | 200m | 512Mi | Ist 215Mi je Pod |
| cert-manager (ohne trust-manager) | 125m | 384Mi | Peak 382Mi |
| Monitoring inkl. Tempo | 1000m | 5760Mi | Peak 5728Mi |
| iam (Keycloak 1Gi/1,5Gi + PG) | 300m | 1280Mi | OOM bei 1Gi |
| SAM (gwe, awe, str, PG, SeaweedFS) | 2450m | 4608Mi | Lab-Requests, Peak 2565Mi |
| gpos-demo (6 Pods) | 300m | 768Mi | Lab-Requests |
| Demo-Postgres (neu, `gpos-data`) | 100m | 256Mi | Ist 173 MiB |
| Broker `prod1k` | 2000m | 6515Mi | Chart-Größe [Quelle: pubsubplus 3.10.0 templates/solaceStatefulSet.yaml:70-72, 92-94] |
| **Summe Workloads** | **6475m** | **20083Mi (19,6 GiB)** | |
| AKS-Systempods 2 x 500m/1024Mi [A] | 1000m | 2048Mi | RA:414 |
| Monitoring-DaemonSets auf Node 2 | 110m | 400Mi | Alloy, node-exporter |
| **Summe auf 2 Nodes** | **7585m** | **22531Mi (22,0 GiB)** | |

Allocatable je Node bei `--max-pods 110`: CPU 8000m - 180m = 7820m;
RAM 32768Mi - (20 MB x 110 + 50 MB) - 100Mi = 30418Mi
[Quelle: `learn.microsoft.com/azure/aks/node-resource-reservations`].
Mit dem Overlay-Default 250 Pods gingen 2,7 GiB je Node verloren
[Quelle: `learn.microsoft.com/azure/aks/concepts-network-ip-address-planning`].
"MB" als MiB gerechnet, echte Kapazität 2-3 % darunter [A]; nach dem
Create per `kaks get nodes` bestätigen. Die nominellen 29 GiB je Node
werden nur erreicht, wenn die echte Kapazität höchstens rund 2 % unter
32768Mi liegt; die P1-Abnahme verlangt deshalb mindestens 28,5 GiB.

| Kennzahl | Wert |
|---|---|
| Requests / Allocatable (2 Nodes, 15640m / 60836Mi) | 48 % CPU / 37 % RAM |
| N-1 (ein Node trägt alles: 6975m / 21107Mi) | 89 % CPU / 69 % RAM, passt |
| Peak-Working-Set inkl. WAL-Reserve und Broker-Reservierung | rund 20,3 GiB |
| Summe aller Memory-Limits | rund 33 GiB (56 %) |
| reale CPU-Nutzung | p99 0,65 Kerne, Spitze 2,26 Kerne (ohne Kyverno) |

Verworfen: 3 x D4 (N-1 bei 102 % CPU), 2 x E4ps_v6 (CPU-Requests
102 %), B-Serie (als Systempool nicht unterstützt [Quelle:
`learn.microsoft.com/azure/aks/use-system-pools`]), AKS Automatic und
Node Auto-Provisioning (nicht stoppbar [Quelle:
`learn.microsoft.com/azure/aks/node-auto-provisioning`]).

### 3.3 Empfohlene Node-Pools und Storage

- Ein Pool `main` im System-Modus, 2 x `Standard_D8ps_v6` (Cobalt 100,
  8 vCPU / 32 GiB, arm64), `--max-pods 110`, kein Autoscaler,
  `max-surge 1`. Ein System-Pool braucht mindestens 2 Nodes; App-Pods
  auf dem System-Pool sind für eine Demo akzeptiert [A] [Quelle:
  `learn.microsoft.com/azure/aks/use-system-pools`].
- Keine Zonenfestlegung: regionaler Pool, LRS-Disks [A: hängen an
  jedem nicht-zonalen Node; Test in P1 per Pod-Umzug mit PVC].
  Alternative `--zones 1`, falls `az vm list-skus` Restriktionen zeigt.
- OS-Disk 128 GiB P10 managed: Dpsv6 hat keine ephemeral OS-Disk
  [Quelle: `learn.microsoft.com/azure/virtual-machines/sizes/general-purpose/dpsv6-series`];
  die arm64-Images allein sind rund 17,6 GB unkomprimiert [Quelle:
  Befehl `docker system df -v`, 16.11.].
- arm64 trägt alle Images: SAM und gpos-demo sind arm64-only, Broker
  10.25.0.208 ist multi-arch, Keycloak, Postgres und Monitoring laufen
  heute auf dem arm64-Lab-Node [Quelle: Befehl `docker buildx
  imagetools inspect`; `hub.docker.com` Tags]. Das belegt nur die
  arm64-Variante; für den amd64-Rückfall ist je Image eine Prüfung
  nötig. arm64 als System-Pool auf v6 ist nicht ausdrücklich
  dokumentiert (Learn-Seite nennt nur v5) [A]; der Create in P1 ist
  der Beweis.
- WireGuard-VM `Standard_B2ats_v2` außerhalb des Clusters.
- Ist Defender for Containers in der Subscription aktiv (P0 Schritt
  2), belegt sein Sensor-DaemonSet CPU und RAM auf beiden Nodes; in P2
  mit `kaks top pods -A` messen und in 3.2 nachtragen [A: Größe].
- Die Node-Ressourcengruppe heißt fest `rg-eurocis-nodes`
  (`--node-resource-group`, nur beim Create setzbar). VMs, OS-Disks,
  PVC-Disks und Load Balancer liegen dort.

| PVC | Größe | Klasse | Tier, EUR/Monat |
|---|---|---|---|
| Broker | 128Gi | managed-csi-premium | P10, 500 IOPS, 19,46 |
| Prometheus (neu) | 16Gi | managed-csi-premium | P3, 2,80 |
| SAM-Postgres | 10Gi | managed-csi-premium | P3, 2,80 |
| SeaweedFS | 20Gi | managed-csi-premium | P4, 5,21 |
| Keycloak-Postgres | 5Gi | managed-csi (Default) | Standard SSD [A: E-Stufe] |
| Loki | 10Gi | managed-csi | dito |
| Tempo | 10Gi | managed-csi | dito |
| Demo-Postgres | 8Gi | managed-csi | dito |
| **Summe** | **207Gi** | | |

Quellen: Solace-Richtwert mindestens 300 IOPS für 1000 Verbindungen
[Quelle: `docs.solace.com/Software-Broker/System-Resource-Requirements.htm`];
P6 64Gi hätte nur 240 IOPS. Lab-Manifeste ohne `storageClassName`
binden an den AKS-Default `managed-csi` [Quelle:
`learn.microsoft.com/azure/aks/concepts-storage`]; Premium nur dort,
wo ein Chartwert existiert (SAM: `persistence-layer.<store>.persistence.storageClassName`,
Render verifiziert vom SAM-Leser).

### 3.4 Kosten

| Posten | Ressourcengruppe | EUR/Monat 24/7 | Quelle |
|---|---|---|---|
| 2 x D8ps_v6 (0,3007/h) | rg-eurocis-nodes | 439,0 | Retail-API |
| AKS Standard-Tier (0,0898/h) | rg-eurocis-aks | 65,6 | Retail-API |
| 2 x OS-Disk P10 | rg-eurocis-nodes | 38,9 | Retail-API |
| Broker-PVC P10 | rg-eurocis-nodes | 19,5 | Retail-API |
| Premium-PVCs P3, P3, P4 | rg-eurocis-nodes | 10,8 | Retail-API (P2 1,40, P3 2,80, P4 5,21) |
| Standard-SSD-PVCs (4 Stück) | rg-eurocis-nodes | bis 8,6 | [A: Obergrenze Disk-Tier E4 2,15 je Disk] |
| Standard LB (Outbound + intern) | rg-eurocis-nodes | 16,4-32,7 | Retail-API 0,0224/h [A: je LB abgerechnet] |
| 2 statische Public IPs (Egress, WireGuard) | rg-eurocis-base | 6,6 | Retail-API 0,0045/h |
| WireGuard-VM B2ats_v2 (0,0097/h) + OS-Disk | rg-eurocis-base | rund 10 | Retail-API [A: Disk] |
| ACR Basic (0,1496/Tag) | rg-eurocis-base | 4,6 | Retail-API |
| Key Vault, DNS-Zone | rg-eurocis-base | rund 1,5 | Retail-API |
| **Summe Messe-Konfiguration** | | **rund 620-640** | |

- **Aufteilung je RG (24/7):** `rg-eurocis-base` rund 23 EUR,
  `rg-eurocis-aks` 0-66 EUR (Tier), `rg-eurocis-nodes` rund
  525-550 EUR. Ein Budget nur auf `rg-eurocis-base` und
  `rg-eurocis-aks` sähe also höchstens rund 90 von 620-640 EUR.
- **Free-Tier 24/7:** rund 555-570 EUR. Unklar ist eine neue
  Preiszeile "FreeTierInfrastructureCost Uptime SLA" (0,0449/h ab
  01.10.2026, bis 32,8 EUR/Monat), ohne Doku [Quelle: Retail-API;
  `azure.microsoft.com/pricing/details/kubernetes-service`]. Nach Tag 1
  im Cost Management prüfen.
- **Mit Stopp (Aufbau):** Im Stopp laufen nur Disks, IPs, LB [A],
  WG-VM, ACR, KV und DNS weiter: rund 117-133 EUR/Monat. Nodes kosten
  0,60 EUR je Laufstunde. Bei 10 h an 22 Tagen (220 h): rund
  250-300 EUR/Monat inklusive möglicher Free-Tier-Zeile.
- **amd64-Variante:** +136,4 EUR/Monat bei 24/7, +41 EUR mit Stopp.
- **Bedingt, nur wenn Defender in der Subscription aktiv ist** (nicht
  in der Basissumme) [Quelle: Retail-API GWC 16.11.]: Defender for
  Containers kostet 0,0084 EUR je vCore-Stunde, also 98 EUR/Monat bei
  24/7 (16 vCores) und rund 30 EUR/Monat mit Nachtstopp (220 h).
  Defender for Servers auf der WG-VM kostet 4,4 EUR/Monat (P1) oder
  13,1 EUR/Monat (P2). [A] Defender for Servers könnte auch die zwei
  Node-VMs abrechnen, bis 26 EUR/Monat (P2). Die SecurityPatch-VHDs in
  `rg-eurocis-nodes` kosten einige EUR [Quelle:
  `learn.microsoft.com/azure/aks/auto-upgrade-node-os-image`; A: Höhe].
- **Projektsumme** (Cluster ab 30.11., Egress-IP ab rund 20.11.,
  Rückbau 20.02.2027): Nov. rund 10, Dez. rund 230-280 (Feiertage
  gestoppt), Jan. rund 300-350 (Standard ab 15.01., 24-h-Lauf), Feb.
  bis 20.02. rund 360-400 (24/7 ab 05.02.). Gesamt rund
  0,9-1,2 Tsd. EUR ohne LLM-Token; mit aktivem Defender for Containers
  rund 1,0-1,35 Tsd. EUR, beides innerhalb von 1.500 EUR (AKS-E1).
- **Budget (AKS-E1):** ein Budget auf Subscription-Ebene, gefiltert
  auf `ResourceGroupName` in `rg-eurocis-base`, `rg-eurocis-aks`,
  `rg-eurocis-nodes`; Zeitraster monatlich, 450 EUR, 01.12.2026 bis
  31.03.2027; Benachrichtigung bei Actual 100 % und Forecast 100 %.
  Budgets setzen sich je Periode zurück, Kostendaten kommen mit 8-24 h
  Verzug [Quelle:
  `learn.microsoft.com/azure/cost-management-billing/costs/tutorial-acm-create-budgets`].
  Zweck: ein vergessener Stopp im Dezember oder Januar und Restkosten
  im März (ein weiterlaufender Cluster mit 620-640 EUR/Monat löst den
  Forecast innerhalb weniger Tage aus). Im Februar (24/7 ab 05.02.,
  rund 21 EUR/Tag) löst der Forecast sehr wahrscheinlich aus; das ist
  erwartet. Die Projektsumme läuft separat über eine gespeicherte
  Cost-Analysis-Ansicht mit demselben Filter im wöchentlichen
  Kosten-Check; den vergessenen Nachtstopp fängt der Abend-Check (P1
  Schritt 8).

### 3.5 Quota-Bedarf

| Quota (Germany West Central) | Bedarf | Vorhanden |
|---|---|---|
| Standard DPSv6 Family vCPUs | 24 (2 x 8 + 8 für den Surge-Node beim Node-Image-Upgrade) | unbekannt |
| Standard DPSv5 Family vCPUs (arm64-Rückfall bei Kapazitätsmangel) | 24 | unbekannt |
| Standard DASv6 Family vCPUs (amd64-Rückfall, AKS-E3) | 24 | unbekannt |
| Basv2 Family vCPUs (WireGuard-VM) [A: Familienzuordnung] | 2 | unbekannt |
| Total Regional vCPUs | mindestens 26 | unbekannt |
| Standard Public IPs | 2 | unbekannt |

"Unbekannt", weil jeder ARM-Aufruf mit AADSTS9002313 scheitert
[Quelle: Befehl `az aks get-versions -l germanywestcentral`, 16.11.,
zweimal]. P0 prüft das nach dem Owner-Login. Der Owner stellt den
Antrag für alle drei Familien gemeinsam am 20.11. über "My quotas" im
Portal (eine Schreibaktion). Eine freigegebene Familien-Quota hebt die
regionale Quota mit an [Quelle:
`learn.microsoft.com/azure/quotas/per-vm-quota-requests`]; P0 prüft sie
trotzdem mit `az vm list-usage`. So hängt der Antrag nicht an AKS-E3
(27.11.). Zeigt eine Familie "not available for increase", stellt der
Owner noch am selben Tag einen Support-Fall und weicht auf eine
verfügbare Familie oder West Europe aus.

## 4. Vorgehen in Phasen

| Phase | Inhalt | PT | Kalender | Gate |
|---|---|---|---|---|
| P0 | Vorbereitung, Klärungen, Azure-Vorab (RG, Zone, Egress-IP), Sicherheitsgeländer | 2,5 | KW47-48 (16.-27.11.) | - |
| P1 | Azure-Grundlagen, Cluster, ACR, CLI, WireGuard | 2,75 | KW49 (30.11.-04.12.) | Prüfpunkt 04.12. |
| P2 | Plattform-Add-ons | 2,5 | KW49-50 (03.-10.12.) | - |
| P3 | Keycloak | 1,0 | KW50 (10.-11.12.) | Prüfpunkt 11.12. (P2 + P3) |
| P4 | Broker | 1,25 | KW50-51 (11.-15.12.) | - |
| P5 | SAM | 2,5 | KW51 (15.-17.12.), 1 PT Puffer bis 18.12. | G2a 18.12. |
| P6 | GEBIT-Demo portieren | 5,0 | KW52-KW1 (Vorarbeit im Lab), KW1-2 auf AKS | G2b 15.01. |
| P7 | Härtung und Betrieb | 4,5 | KW3-KW7 | G3 22.01., G4 05.02. |
| | **Summe** | **22,0** (mit 15 % Puffer rund 25) | | |

Wer: "Claude" heißt Skripte schreiben, read-only prüfen und
Schreibbefehle erst nach Freigabe des Owners je Schritt ausführen.
"Owner" heißt Logins, Passwörter, Freigaben, DNS-Delegation, Kontakte.
"C" ist die dritte Person aus O9 (ab 23.11.); die PT des Plans sind
ihr Aufwand.

Kontext-Regel für alle Phasen: Jeder AKS-Befehl in diesem Plan läuft
über `kaks`/`haks` (P1 Schritt 6) oder über ein Skript, das
`require_kube_context aks-eurocis` aufruft. Lab-Befehle tragen
`--context rancher-desktop`. Ausgenommen ist nur `helm template` ohne
`--validate`, weil es keinen Cluster kontaktiert.

### P0 Vorbereitung und Klärungen (2,5 PT, 16.-27.11.)

**Ziel:** Azure-Lage geklärt, Entscheidungen AKS-E1 bis AKS-E20
getroffen, Zone und Egress-IP angelegt, Lab gegen Verwechslung mit AKS
geschützt, bevor eine AKS-Credential auf dem Mac existiert.

**Schritte:**

1. Owner: Neu anmelden. Der gecachte Token scheitert mit
   AADSTS9002313, `~/.azure/azureProfile.json` ist vom 11.09.2025
   [Quelle: Befehl `ls -la ~/.azure`, 16.11.]. Die CLI selbst nennt als
   Abhilfe `az logout` und `az login` mit `--tenant` [Quelle: Befehl
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
     --query "[?name=='Standard_D8ps_v6'||name=='Standard_D8ps_v5'||\
   name=='Standard_D8as_v6'||name=='Standard_B2ats_v2'].\
   {n:name,z:locationInfo[0].zones,r:restrictions}"
   az vm list-usage -l germanywestcentral -o table
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
   bestehende Ressourcen. Zu klären ist:
   - Darf der Owner Rollen zuweisen
     (`Microsoft.Authorization/roleAssignments/write` effektiv, nicht in
     notActions)? Gebraucht
     für `--attach-acr`, AKS-RBAC, Network Contributor, DNS Zone
     Contributor und Key Vault Secrets Officer. Bei "Role Based Access
     Control Administrator" mit Condition muss sie diese Rollen
     erlauben.
   - Welche Key-Vault-Datenrollen erbt der Owner schon?
   - Hat der Owner Owner, Contributor oder Cost Management Contributor
     auf der Subscription (für das Budget mit Filter)?
   - Welche Anmeldehäufigkeit setzt Conditional Access (Frage an die
     IT)? Bei kurzer Frequenz plant P7 eine tägliche Neuanmeldung.
3. Owner: Entscheidungen AKS-E1 bis AKS-E20 in einer Sitzung; AKS-E1,
   AKS-E2, AKS-E15 und der Name für AKS-E20 bis 20.11., AKS-E4 bis
   25.11., die übrigen bis 27.11. (AKS-E9, AKS-E10, AKS-E19 bis 04.12.).
4. Owner, am 20.11.: Quota-Antrag über "My quotas" für Germany West
   Central (3.5): DPSv6, DPSv5 und DASv6 je 24 vCPU, Basv2 2 vCPU. Bei
   "not available for increase" am selben Tag einen Support-Fall
   stellen.
5. Claude nach Freigabe, Azure-Vorab (show-or-create, idempotent):
   - ab 20.11., nach AKS-E1 und AKS-E2 und grünem Schritt 2:

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

     Kosten rund 1 EUR zusätzlich bis 30.11. (0,0045 EUR/h).
   - am 25.11., nach AKS-E4: Zone anlegen und die Nameserver ausgeben.

     ```bash
     az network dns zone show -g rg-eurocis-base -n <zone> -o none \
       2>/dev/null || az network dns zone create -g rg-eurocis-base -n <zone>
     az network dns zone show -g rg-eurocis-base -n <zone> \
       --query nameServers -o tsv
     ```

     Azure vergibt die Nameserver erst beim Anlegen der Zone; ohne
     diesen Schritt ist keine Delegation vor P1 möglich. Der Owner gibt
     alle 4 NS-Werte (mit Punkt am Ende) am selben Tag an den
     Parent-Owner. Ziel: delegiert bis 27.11., spätestens 02.12.
6. Owner: Anfragen versenden.
   - GEBIT (AKS-E16), mit dem Namen des Stellvertreters aus AKS-E20 und
     der Reflection-Frage.
   - LiteLLM-Betreiber in zwei Stufen: am 20.11. Gibt es eine
     Quell-IP-Allowlist, gilt sie auch für `/v1/*`, wie lange dauert
     eine Freischaltung, kommt ein Messe-Key (O5)? Hinweis: Das Lab
     erreicht den Proxy heute ohne Firmen-VPN, eine Allowlist ist daher
     unwahrscheinlich [Quelle: RA:90; Befehl `scutil --nc list`, 16.11.]
     [A]. Spätestens am 25.11. die IP aus Schritt 5, falls die Antwort
     "Allowlist ja" lautet oder noch fehlt.
7. Owner: offenen amd-Working-Tree committen (`git status`: 4 geänderte
   Dateien, `scripts/models/set-pricing.sh` untracked). Darin stecken
   SeaweedFS 2 CPU/2Gi, beide HIL-Flags, Sonnet-5-Planning und
   `notify:_:send` für power_user. Ohne Commit installiert AKS aus einem
   sauberen Checkout den SeaweedFS-Default, der am 16.11. hing.
8. Owner gibt Mac-Tools frei (AKS-E13), Claude installiert, vor P1:

   ```bash
   brew uninstall --formula azure-cli   # verwaiste Formel 2.85.0
   brew install --cask azure-cli        # 2.93.0 oder neuer; ~/.azure bleibt
   az version                           # azure-cli >= 2.93.0
   brew install Azure/kubelogin/kubelogin
   brew install wireguard-tools         # wg, wg-quick; skriptbar
   ```

   Die Mac-CLI ist 2.85.0 vom 07.04.2026, aktuell ist 2.93.0 vom
   15.11.2026 [Quelle: Befehl `az version`;
   `api.github.com/repos/Azure/azure-cli/releases`, 16.11.].
   homebrew-core hat `azure-cli` nach `homebrew/cask` verschoben
   (`brew info --formula azure-cli`: "No available formula";
   tap_migrations.json); `brew upgrade azure-cli` und `az upgrade`
   migrieren eine verwaiste Formel nicht. Nach dem Wechsel die zitierten
   Hilfetexte (`az aks maintenanceconfiguration add --help`,
   `az aks get-credentials --help`) erneut prüfen. Für kubelogin die
   Tap-Formel, nicht die Core-Formel `kubelogin` (int128/OIDC) und nicht
   `az aks install-cli` (legt ein zweites kubectl nach `/usr/local/bin`)
   [Quelle: Befehl `brew info kubelogin`; `az aks install-cli --help`].
   WireGuard als `wireguard-tools`, weil nur `wg-quick` sich per Skript
   umkonfigurieren lässt (P1 Schritt 7); später `cmctl`.
9. Owner und Claude, vor jeder gpd-Änderung: Baseline festhalten. gpd
   ist seit 17.11.2026 im sda-Repo versioniert (GEBIT-Zustimmung, O8
   entfällt [Quelle: PLAN:209]); Baseline = sda-Commit vor dem Umbau;
   kein eigenes `git init`.
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
10. Claude: Sicherheitsgeländer in amd (Details in 5.2):
    `SAM_PROFILE=lab|aks` lädt `.env` bzw. `.env.aks`;
    `require_kube_context` prüft Kontextname und Server-URL des
    Clusters; `kaks`/`haks` für `aks`, `--context rancher-desktop` für
    `lab`; `SAM_HOME` je Profil und der Auth-Cache-Pfad unter
    `SAM_HOME`; `stop.sh` bricht auf `aks` ohne explizites
    `SAM_SEMP_URL` und `SAM_SEMP_PASSWORD` ab (Default 127.0.0.1:8080
    ist Lab-`solace-1` [Quelle: amd scripts/stop.sh:150-163]);
    `teardown-keycloak-client.sh` und `teardown-keycloak-users.sh`
    laden das Profil über `common.sh` und haben einen Identitäts-Guard;
    die Helm-Argumente baut eine Funktion `sam_helm_args <profil>`.
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
    Secrets, in zwei Teilen.
    - (1) Call-Log-Gate: Eine Stub-Umgebung außerhalb des Repos legt
      `kubectl`, `helm`, `sam`, `curl` und `docker` als erste Einträge
      auf `PATH`. Jeder Stub schreibt sein argv in ein Log, maskiert
      Werte nach `*Secret*=`, `*ApiKey*=`, `*password*=` und `-u` als
      `***`, liefert feste Antworten (Ingress-ClusterIP, leere
      NodeHosts, HTTP 200, leere Queue-Liste) und berührt weder Cluster
      noch Broker. Dazu eine Dummy-`.env` mit festen Fake-Werten, `HOME`
      auf ein Temp-Verzeichnis, kein TTY (`</dev/null`).
      Baseline aus einem `git worktree` des Commits aus Schritt 7
      (`git worktree add <tmp>/amd-before <sha>`), neu aus dem geänderten
      Baum mit `SAM_PROFILE` leer und mit `SAM_PROFILE=lab`. Abgedeckt:
      alle Skripte aus 5.2 inkl. Keycloak-Setup und -Teardown. Vor dem
      Vergleich werden nur die geplanten Zusätze entfernt
      (`--context rancher-desktop`, `--kube-context rancher-desktop`,
      `--url https://sam.solace.lab`, `--no-dotenv`) und Worktree-Pfade
      auf `$PROJECT_DIR` abgebildet; getrennt wird geprüft, dass jeder
      kubectl- und helm-Aufruf diesen Kontext trägt. Bestanden: Diff
      leer; das angewendete Certificate ist byte-gleich zu
      `manifests/sam-tls-certificate.yaml`; der Keycloak-Writeback zielt
      auf `.env`; der Auth-Cache bleibt `solace-lab.json` im
      Default-Home; SEMP bleibt 127.0.0.1:8080. `sam_helm_args lab`
      ergibt dieselbe Liste wie start.sh:150-157, einzige erlaubte
      Abweichung `--kube-context rancher-desktop`.
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
      render > "$S/before.yaml"   # nach Schritt 7, vor Schritt 10
      render > "$S/after.yaml"    # nach Schritt 10
      diff "$S/before.yaml" "$S/after.yaml"
      git diff --exit-code <sha-schritt-7> -- local-k8s-values.yaml manifests/
      ```

      Läuft Schritt 10 schon, kommt die Baseline aus
      `git show <sha>:local-k8s-values.yaml`. `set -e` lässt einen
      gescheiterten Render abbrechen, statt zwei leere Dateien als gleich
      zu werten.
    - (3) Live und nicht-destruktiv im Lab: das neue `provision.sh`
      (idempotent), dann `make test`, `make smoke` und ein S1-e2e.
      `stop.sh` läuft nur in der Stub-Umgebung, nie live.

**Wer:** Owner Schritte 1, 3, 4, 6, 7 und die Freigaben in 5, 8, 9;
Claude 2, 5, 8, 10-13. In KW47 tragen Owner und Claude P0 (Schritte
1-8); ab 23.11. übernimmt C die Schritte 9-13 gemeinsam mit Claude.

**Abnahme:**

- `az version` zeigt 2.93.0 oder neuer; `az aks get-versions` listet
  1.36.x.
- Quota: Bis 27.11. zeigt `az vm list-usage` ein Limit von mindestens
  24 vCPU für die gewählte Familie und für den nächsten Rückfall
  (D8ps_v5 bei arm64, D8as_v6 bei amd64), Basv2 mindestens 2, Total
  Regional mindestens 26; keine SKU-Restriction für beide.
- Alle Provider Registered. Unter den `atScope()`-Zuweisungen ist keine
  mit enforcementMode Default und Effekt Deny oder DenyAction auf
  `Microsoft.Network/publicIPAddresses`,
  `Microsoft.ContainerService/managedClusters`, die Region
  germanywestcentral, Pflicht-Tags oder die geplanten SKUs. Gibt es
  eine, steht eine Exemption oder ein Workaround als Entscheidung im
  PLAN.
- Die effektiven Aktionen des Owners decken
  `Microsoft.Authorization/roleAssignments/write` ab (auch über Gruppe
  oder Management Group);
  eine nur PIM-berechtigte Rolle ist vor P1 aktiviert; die Rechte für
  das Budget sind geklärt (sonst je RG ein Budget).
- Defender-Pläne notiert (Containers, VirtualMachines inkl. subPlan,
  ContainerRegistry, KeyVault, Arm). Ist Containers oder
  VirtualMachines Standard, klärt der Owner Ausnahme oder
  Kostenübernahme mit dem Subscription-Owner (AKS-E1). Eine Ausnahme
  auf Ressourcenebene ist nicht zugesagt; Rückfall ist die eigene
  Subscription, sofern der Plan nicht von der Management Group erbt.
- AKS-E1 bis AKS-E20 schriftlich in PLAN 0.5 (oder neuem Abschnitt
  0.5a AKS). Dabei bekommen PLAN-E8 (PLAN:135) und der AKS-Teil von
  PLAN-E7 (PLAN:134) den Vermerk "ersetzt durch AKS-E3/AKS-E7/AKS-E8
  (Datum)", O4 (PLAN:203) "übernommen durch AKS-E1/AKS-E2/AKS-E4", O6
  (PLAN:205) "übernommen durch AKS-E15". So gibt es je Entscheidung eine
  Quelle.
- Zone angelegt, 4 NS-Records am 25.11. an den Parent-Owner übergeben,
  Delegationstermin spätestens 02.12. bestätigt.
- `pip-aks-egress` angelegt; der Betreiber hat schriftlich bestätigt:
  keine Quell-IP- oder Key-IP-Einschränkung, oder die IP ist
  eingetragen (auch für den Messe-Key O5). Fehlt die Antwort am 27.11.:
  Eskalation, Eintrag im Risikoregister, der LiteLLM-Test am 03.12. gilt
  als gefährdet.
- `kubelogin --version` zeigt Azure-kubelogin; `wg-quick` vorhanden;
  amd-Working-Tree sauber.
- gpd: lokales Repo mit Baseline-Commit, Referenzen gesichert, Rückweg
  einmal geprobt.
- Lab: Call-Log-Diff leer (bis auf die Kontext-Zusätze), Render-Diff
  leer, `make test` grün, `make smoke` READY auf Kasse 99, ein S1-e2e
  liefert "proposed 100001 7,99".
- Negativtests, jeweils mit `set -x`-Log:
  - `SAM_PROFILE=aks scripts/stop.sh` bricht bei Kontext
    `rancher-desktop` ab, bevor ein kubectl-, helm-, SEMP- oder
    Keycloak-Aufruf läuft.
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

**Abhängigkeiten:** Owner-Login; Freigabe AKS-E15; O9 für C ab 23.11.

### P1 Azure-Grundlagen, Cluster, ACR, CLI-Anbindung (2,75 PT, KW49)

**Ziel:** Cluster in Endform, per CLI erreichbar, ohne die
Default-kubeconfig zu berühren; WireGuard-Tunnel steht. Prüfpunkt
04.12.: Ist die P1-Abnahme nicht grün, wandert der AKS-Teil von G2a nach
G2b (Mechanik aus PLAN:2561-2564) und P5 nach KW1.

**Layout:** Drei Ressourcengruppen, damit ein Neuaufbau
DNS-Delegation, ACR, Egress-IP (LiteLLM-Allowlist), WireGuard-IP und Key
Vault behält.

- `rg-eurocis-base`: VNet `10.20.0.0/16` (`snet-aks` /22, `snet-wg`
  /28), DNS-Zone, ACR, Key Vault, `pip-aks-egress`, `pip-wg`, `nsg-wg`,
  WireGuard-VM, UAMIs `id-aks-cp` und `id-cert-manager`.
- `rg-eurocis-aks`: nur der Cluster.
- `rg-eurocis-nodes`: die Node-Ressourcengruppe mit festem Namen (VMs,
  Disks, LB); sie verschwindet mit dem Cluster.
- Pod-CIDR 10.244.0.0/16, Service-CIDR 10.0.0.0/16: keine Überlappung
  mit Lab-k3s 10.42/10.43 [A: Stand-LAN und Firmen-VPN in P0 prüfen].

**Schritte (Claude nach Freigabe, Owner für Delegation):**

1. Basis prüfen: `rg-eurocis-base`, Zone und `pip-aks-egress` stammen
   aus P0 Schritt 5. Show-or-create wie dort, dann `dig NS <zone>`.
2. Netz, WireGuard-IP, NSG, Identitäten. `pip-wg` und `nsg-wg` entstehen
   hier, damit Schritt 4 die WireGuard-IP kennt und ein VM-Neuaufbau
   sie behält.

   ```bash
   az network vnet create -g rg-eurocis-base -n vnet-eurocis \
     --address-prefixes 10.20.0.0/16 \
     --subnet-name snet-aks --subnet-prefixes 10.20.0.0/22
   az network vnet subnet create -g rg-eurocis-base \
     --vnet-name vnet-eurocis -n snet-wg --address-prefixes 10.20.9.0/28
   az network public-ip create -g rg-eurocis-base -n pip-wg \
     --sku Standard --allocation-method Static
   az network nsg create -g rg-eurocis-base -n nsg-wg
   az network nsg rule create -g rg-eurocis-base --nsg-name nsg-wg \
     -n allow-wg-udp --priority 100 --direction Inbound --access Allow \
     --protocol Udp --source-address-prefixes Internet \
     --source-port-ranges '*' --destination-port-ranges 51820 443
   az network vnet subnet update -g rg-eurocis-base \
     --vnet-name vnet-eurocis -n snet-wg --network-security-group nsg-wg
   az identity create -g rg-eurocis-base -n id-aks-cp
   az identity create -g rg-eurocis-base -n id-cert-manager
   CP_PID=$(az identity show -g rg-eurocis-base -n id-aks-cp \
     --query principalId -o tsv)
   for scope in <snet-aks-id> <pip-aks-egress-id>; do
     az role assignment create --role "Network Contributor" \
       --assignee-object-id "$CP_PID" \
       --assignee-principal-type ServicePrincipal --scope "$scope"
   done
   ```

   Ohne `--destination-port-ranges` wäre der Default Port 80; eine
   Standard-Public-IP ist eingehend geschlossen, solange keine Regel sie
   öffnet. Kein SSH. Die Rolle wird **vor** dem Create vergeben. Für eine
   frisch angelegte Identity kann der RBAC-Dienst die Zuweisung während
   der Replikation ablehnen (PrincipalNotFound);
   `--assignee-principal-type` vermeidet den Graph-Lookup [Quelle:
   `az role assignment create --help`, 2.85.0;
   `learn.microsoft.com/azure/role-based-access-control/role-assignments-cli`].
   Ein erneuter Lauf ist harmlos, weil die CLI eine bestehende Zuweisung
   als Erfolg wertet.
3. ACR, Testimage, Key Vault; Secrets generiert, nie ausgegeben:

   ```bash
   az acr create -g rg-eurocis-base -n <acr> --sku Basic --admin-enabled false
   az acr import -n <acr> --source docker.io/curlimages/curl:8.23.0 \
     --image curl:8.23.0                     # multi-arch inkl. arm64
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
   az keyvault secret show --vault-name <kv> -n wg-server-key -o none \
     2>/dev/null || wg genkey | tr -d '\n' |
     az keyvault secret set --vault-name <kv> -n wg-server-key \
       --file /dev/stdin -o none
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
   - WireGuard: nur der Server-Key kommt in den Key Vault
     (`wg-server-key`, WireGuard-Format statt hex). Client-Private-Keys
     entstehen auf Mac und Router selbst; nur wenn der Leih-Router keine
     Schlüssel erzeugen kann, kommt seine komplette Peer-Konfiguration
     als ein Secret in den Key Vault. Der Public Key ist nicht geheim
     (`az keyvault secret show ... --query value -o tsv | wg pubkey`).
   - `--retention-days 7` ist das Minimum und nur beim Anlegen setzbar;
     ohne Purge-Schutz, damit ein Purge beim Rückbau möglich bleibt.
   - Der LiteLLM-Key kommt nicht in den Key Vault.
4. Cluster:

   ```bash
   WG_IP=$(az network public-ip show -g rg-eurocis-base -n pip-wg \
     --query ipAddress -o tsv)
   az group create -n rg-eurocis-aks -l germanywestcentral \
     --tags purpose=eurocis2027 deleteAfter=2027-02-28
   az aks create -g rg-eurocis-aks -n aks-eurocis -l germanywestcentral \
     --kubernetes-version 1.36.<patch> --tier free \
     --node-resource-group rg-eurocis-nodes \
     --nodepool-name main --node-vm-size Standard_D8ps_v6 --node-count 2 \
     --max-pods 110 --node-osdisk-size 128 \
     --network-plugin azure --network-plugin-mode overlay \
     --network-dataplane cilium --vnet-subnet-id <snet-aks-id> \
     --pod-cidr 10.244.0.0/16 --service-cidr 10.0.0.0/16 \
     --dns-service-ip 10.0.0.10 \
     --assign-identity <id-aks-cp-id> \
     --load-balancer-outbound-ips <pip-aks-egress-id> \
     --enable-oidc-issuer --enable-workload-identity \
     --attach-acr <acr-id> \
     --enable-aad --enable-azure-rbac --disable-local-accounts \
     --api-server-authorized-ip-ranges <owner-ip>/32,${WG_IP}/32 \
     --auto-upgrade-channel none --node-os-upgrade-channel SecurityPatch \
     --no-ssh-key --tags purpose=eurocis2027 deleteAfter=2027-02-28
   az group update -n rg-eurocis-nodes \
     --tags purpose=eurocis2027 deleteAfter=2027-02-28   # [A]
   az role assignment create \
     --role "Azure Kubernetes Service RBAC Cluster Admin" \
     --assignee-object-id <owner-objectId> --assignee-principal-type User \
     --scope <aks-id>
   ```

   `--node-resource-group` geht nur beim Create, die Gruppe darf vorher
   nicht existieren; ohne den Parameter hieße sie
   `MC_rg-eurocis-aks_aks-eurocis_germanywestcentral`. Entra-Integration
   ist nicht rückbaubar [Quelle:
   `learn.microsoft.com/azure/aks/enable-authentication-microsoft-entra-id`].
   Break-glass: `az aks command invoke` oder
   `az aks update --enable-local-accounts`. Rollen für den
   Stellvertreter folgen bis G3 (P7 Schritt 7).
5. Wartung: drei JSON-Dateien (`default`,
   `aksManagedAutoUpgradeSchedule`, `aksManagedNodeOSUpgradeSchedule`),
   je mit zwei `notAllowedDates`-Bereichen: 2027-01-20 bis 2027-01-20
   (24-h-Lauf) und 2027-01-27 bis 2027-02-20 (Probetage, G4, Messe).
   `notAllowedTime` ist die veraltete Eigenschaft, und
   `az aks maintenanceconfiguration add` hat dafür kein Flag (nur
   `--config-file`) [Quelle: `learn.microsoft.com/azure/aks/planned-maintenance`;
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
   28.01., 29.01. und 03.02. [Quelle: PLAN:2620]. Ein SecurityPatch-Lauf
   setzt Nodes nur bei Bedarf per Surge neu auf, sonst patcht er live;
   das Risiko ist ein möglicher Drain während eines Probetags oder des
   24-h-Laufs [Quelle:
   `learn.microsoft.com/azure/aks/auto-upgrade-node-os-image`]. Der
   manuelle Refresh liegt am Di 26.01. (P7 Schritt 5), einen Tag vor der
   Sperre; ob `notAllowedDates` manuelle Upgrades blockiert, ist nicht
   dokumentiert [A], spielt so aber keine Rolle. Die Nodes bleiben vom
   26.01. bis 20.02. ungepatcht (rund 25 Tage), weit unter den drei
   Monaten, die AKS-E14 vermeiden will. Reaktive Wartung kann die Sperre
   trotzdem brechen (Abschnitt 7). Die JSON-Dateien gehören in die
   Neuaufbau-Skripte, weil die Konfigurationen mit dem Cluster
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
7. WireGuard-VM:

   ```bash
   az vm create -g rg-eurocis-base -n vm-wg --image Ubuntu2404 \
     --size Standard_B2ats_v2 --vnet-name vnet-eurocis --subnet snet-wg \
     --private-ip-address 10.20.9.4 --public-ip-address pip-wg \
     --nsg nsg-wg --assign-identity '[system]' --generate-ssh-keys \
     --custom-data sli/aks/cloud-init-wg.yaml
   NIC_ID=$(az vm show -g rg-eurocis-base -n vm-wg \
     --query 'networkProfile.networkInterfaces[0].id' -o tsv)
   az network nic update --ids "$NIC_ID" --ip-forwarding true
   VM_PID=$(az vm show -g rg-eurocis-base -n vm-wg \
     --query identity.principalId -o tsv)
   az role assignment create --role "Key Vault Secrets User" \
     --assignee-object-id "$VM_PID" \
     --assignee-principal-type ServicePrincipal \
     --scope "$KV_ID/secrets/wg-server-key"
   ```

   `--public-ip-address pip-wg` und `--nsg nsg-wg` verweisen auf die
   Ressourcen aus Schritt 2 [Quelle: `az vm create --help`: "creating
   one (default) or referencing an existing one"; azure-cli 2.85.0
   vm/_validators.py:1065-1068]; `--public-ip-sku` und `--nsg-rule`
   entfallen. Den NIC-Namen liefert `az vm show`, nicht geraten.

   `cloud-init-wg.yaml` (in `sli/aks/`, enthält keinen Schlüssel):
   - holt beim Boot per IMDS ein Token (Resource `vault.azure.net`),
     liest `wg-server-key` per Key-Vault-REST und schreibt ihn mit
     `umask 077` nach `/etc/wireguard/server.key`; mit Retry bis
     10 min, weil die Rolle erst nach dem Create zugewiesen wird. Die VM
     erreicht den Key Vault über `pip-wg`. Eine neu erstellte VM behält
     so denselben Public Key; Mac und Router brauchen keine neue
     Konfiguration.
   - `wg0.conf` mit `ListenPort = 51820`; NAT-Regeln als
     `PostUp`/`PostDown`, damit sie Reboots und unattended upgrades
     überleben:
     `iptables -t nat -A PREROUTING -i eth0 -p udp --dport 443 -j
     REDIRECT --to-ports 51820; iptables -t nat -A POSTROUTING -o eth0
     -j MASQUERADE` (und die passenden `-D` in `PostDown`). `-i eth0`
     verhindert, dass weitergeleitetes UDP/443 (QUIC) aus dem Tunnel
     umgeleitet wird. `net.ipv4.ip_forward=1` per sysctl.d.
   - FORWARD-Policy DROP für Verkehr aus `wg0`, dazu
     `ESTABLISHED,RELATED` ACCEPT. Admin-Peers (je eine Tunnel-IP) dürfen
     alles: 10.20.0.0/16 und, im Voll-Tunnel-Profil, das Internet über
     `pip-wg`. Der Router-Peer (seine Tunnel-IP bzw. das Stand-LAN,
     falls der Router routet statt zu maskieren [A]) darf nur
     10.20.0.250 auf tcp/443 und tcp/80, optional ICMP. WireGuard
     bindet Quell-IPs an den Peer-Schlüssel, das Matching auf Quell-IP
     ist daher sicher. Die Regeln greifen vor dem MASQUERADE.
   - Tunnelnetz außerhalb von 10.244/16 und 10.0/16 [A: Adressplan in
     P1 festlegen]; unattended upgrades an; Verwaltung nur per
     `az vm run-command`.

   Peers: Owner-Mac jetzt, Stellvertreter-Mac bis G3 (AKS-E20),
   Leih-Stand-Router (P6 Schritt 12; die Leihgeräte stehen ab 11.12.
   im Lab [Quelle: PLAN:2618]). Jeder Peer erzeugt sein Schlüsselpaar
   selbst; nur der Public Key wird per `az vm run-command invoke ...
   --scripts 'wg set wg0 peer <pub> allowed-ips <tunnel-ip>/32 &&
   wg-quick save wg0'` eingetragen. Zwei Admin-Profile je Mac (unter
   `/opt/homebrew/etc/wireguard/`):
   - `aks-admin` (Split): `AllowedIPs` 10.20.0.0/16 plus API-Server-IP/32,
     damit die Allowlist nur die WG-VM-IP braucht.
   - `aks-admin-full` (Voll-Tunnel): `AllowedIPs` 0.0.0.0/0 für Netze
     außerhalb der Allowlist (Stand, 5G, unterwegs). Die Quell-IP ist
     dann immer `pip-wg`; eine API-IP-Route ist nicht nötig.

   Die API-Server-IP kann sich nach `az aks start` ändern [Quelle:
   `learn.microsoft.com/azure/aks/start-stop-cluster`]. Dafür entsteht
   hier `sli/aks/aks-wg-sync.sh` (mit Kontext-Guard): FQDN per
   `az aks show -g rg-eurocis-aks -n aks-eurocis --query fqdn -o tsv`,
   IPv4 per `dig +short A @1.1.1.1 <fqdn> | grep -E '^[0-9.]+$' | tail
   -1`, Vergleich mit dem /32 in `aks-admin.conf` und
   `route -n get <ip>` (Interface muss `utun` sein). Weicht es ab, stoppt
   das Skript vor jedem kubectl-Aufruf und gibt genau die sudo-Befehle
   für den Owner aus (AllowedIPs `10.20.0.0/16,<neu>/32` in der
   Konfiguration, dann `sudo wg-quick down aks-admin && sudo wg-quick up
   aks-admin`); der zuletzt gesehene Wert liegt in
   `~/.config/eurocis-aks/`. Aufrufe: nach dem ersten Create, als
   erster Schritt jedes `aks-start.sh`, nach dem Tier-Wechsel an G2b
   [A: IP-Wechsel dort nicht belegt] und nach dem Neuaufbau-Drill. API
   Server VNet Integration ist keine gleichwertige Abhilfe, höchstens
   eine optionale P0-Prüfung: Routing durch den Tunnel bräuchte den
   Private-Cluster-Modus (nicht mit authorized IP ranges kombinierbar)
   und DNS-Forwarding über die WG-VM; die dokumentierte Einschränkung
   für Node-SKUs ab v4 ist für `Standard_D8ps_v6` zu prüfen [A].
8. Prüfungen und Wächter. `az aks check-acr` entfällt: Es startet
   `mcr.microsoft.com/aks/canipull:v0.1.0`, ein reines amd64-Image (auf
   Cobalt-Nodes "exec format error"), und holt eine temporäre
   Devicecode-kubeconfig, die nicht konvertiert wird [Quelle: azure-cli
   2.85.0 acs/_consts.py:226, acs/custom.py:1897-1906, 2150-2195; Befehl
   `curl https://mcr.microsoft.com/v2/aks/canipull/manifests/v0.1.0`,
   16.11.]. `check-acr` kommt nur beim amd64-Rückfall wieder in Frage.

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
   az aks stop -g rg-eurocis-aks -n aks-eurocis   # blockiert bis zum Ende
   az aks show -g rg-eurocis-aks -n aks-eurocis \
     --query "{p:powerState.code,s:provisioningState}" -o tsv
   # = Stopped / Succeeded, dann mindestens 30 min warten
   az aks start -g rg-eurocis-aks -n aks-eurocis  # Dauer ab hier notieren
   sli/aks/aks-wg-sync.sh && kaks get --raw /readyz
   ```

   Das curl-Image nimmt `curl` als erstes Argument an [A: Entrypoint
   von curlimages]. Microsoft verlangt nach einem Stop 15-30 min Pause
   vor dem Start [Quelle:
   `learn.microsoft.com/azure/aks/start-stop-cluster`, Caution unter
   "Start an AKS cluster"]. Dazu entstehen hier minimale Wrapper
   `sli/aks/aks-stop.sh` (schreibt die UTC-Zeit eines erfolgreichen
   Stops nach `~/.config/eurocis-aks/last-stop`) und
   `sli/aks/aks-start.sh` (verweigert den Start innerhalb von 30 min
   nach dem Stop und nennt die Restminuten, wartet nur mit `--wait`;
   ruft zuerst `aks-wg-sync.sh`); P5 Schritt 6 erweitert sie. Das
   Activity Log (`Microsoft.ContainerService/managedClusters/stop/action`)
   ist nur zweite Prüfung, weil Einträge spät kommen können [A].

   Kostenwächter:
   - Budget nach 3.4 im Portal oder per `az rest --method put` auf
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

**Wer:** Claude Schritte 1-8 nach Freigabe; Owner Delegation,
Entra-Login, WireGuard-Profile auf dem Mac (sudo), Budget im Portal.

**Abnahme:**

- `az aks show`: Version 1.36.x, overlay/cilium, maxPods 110,
  `upgradeChannel none`, `nodeOSUpgradeChannel SecurityPatch`,
  `disableLocalAccounts true`, `nodeResourceGroup rg-eurocis-nodes`;
  `apiServerAccessProfile.authorizedIpRanges` enthält die Owner-IP und
  `${WG_IP}/32`.
- 2 Nodes Ready, `kubernetes.io/arch=arm64`, je mindestens 7,8 CPU und
  28,5 GiB (29184Mi) allocatable, gemessen mit
  `kaks get nodes -o custom-columns=N:.metadata.name,CPU:.status.allocatable.cpu,MEM:.status.allocatable.memory`.
  Die Messwerte ersetzen 30418Mi in 3.2; die N-1-Requests (6975m /
  21107Mi) liegen bei höchstens 90 % CPU und 80 % RAM des kleineren
  Nodes.
- `kubectl config current-context` ohne `KUBECONFIG` ist weiter
  `rancher-desktop`; `~/.kube/config` enthält kein `aks-eurocis`.
- Ein API-Aufruf von einer nicht freigegebenen IP ohne Tunnel läuft in
  den Timeout.
- `az aks maintenanceconfiguration show` listet für alle drei
  Konfigurationen beide Sperrbereiche.
- Die Kubelet-Identity hat AcrPull auf der ACR; Pod `acr-pull` (arm64,
  Pull-Policy Always) erreicht `Succeeded` ohne ErrImagePull,
  ImagePullBackOff oder exec format error; der Egress-Pod meldet
  `pip-aks-egress`; LiteLLM antwortet aus dem Pod mit einem HTTP-Code
  (kein Timeout). Der HTTP-Code belegt nur TCP/TLS; den Nachweis der
  Freischaltung bringen die Betreiber-Bestätigung (P0) und P5.
- Key Vault: Owner hat Secrets Officer; für jedes Passwort-Secret ist
  `az keyvault secret show --vault-name <kv> -n <name> --query value
  -o tsv | grep -qx '[0-9a-f]\{48\}'` erfolgreich, ohne Ausgabe.
- `az network nsg rule list -g rg-eurocis-base --nsg-name nsg-wg` zeigt
  nur UDP 51820/443 eingehend, kein SSH.
- WireGuard-Handshake vom Owner-Mac einmal mit Endpoint `:51820` und
  einmal mit `:443` (`wg show` latest-handshake per run-command); eine
  Node-IP antwortet durch den Tunnel; `route -n get <api-ip>` zeigt
  `utun`; `dig NS <zone>` liefert die Azure-Nameserver (spätestens
  02.12.).
- Hygiene: `grep -rnE 'PrivateKey|[A-Za-z0-9+/]{43}=' sli/aks/` ohne
  Treffer; die VM-Identity hat ihre Rolle nur auf dem Secret
  `wg-server-key`.
- Stop, mindestens 30 min Pause, Start fehlerfrei, Startdauer (ab
  `az aks start`) notiert; danach `aks-wg-sync.sh` grün und
  `kaks get --raw /readyz` ok durch den Tunnel. Ein Zyklus wird von
  einem Handy-Hotspot aus geprüft (nicht in der Allowlist): mit Tunnel
  ok, ohne Tunnel Timeout.
- Budget mit Drei-RG-Filter aktiv; Abend-Check einmal ausgelöst.

**Abhängigkeiten:** P0; Zone delegiert spätestens 02.12. (sonst P2
blockiert, nicht P1).

### P2 Plattform-Add-ons (2,5 PT, KW49-50)

**Ziel:** Ingress, TLS, DNS, Guardrails und Monitoring in Lab-Versionen
auf AKS; keine CA-Hierarchie, kein trust-manager, kein Kyverno, keine
Registry. Prüfpunkt 11.12. zusammen mit P3.

**Schritte:**

1. Neuer Ordner `sli/aks/` (nur neue Dateien): `versions.env` mit den
   gepinnten Lab-Versionen, `lib.sh` mit `kaks`/`haks` und
   `require_kube_context`, je Komponente `values-aks.yaml`,
   `setup-aks.sh`, das `lib.sh` lädt und `require_kube_context
   aks-eurocis` aufruft. Lab-`setup.sh` bleibt unverändert. Grundlage:
   die Skizzen in `gpd/spikes/aks/`.
2. PriorityClasses und Guardrails (per `kaks apply -f`):
   - `demo-critical` als `globalDefault` (der SAM-Chart kennt kein
     `priorityClassName` [Quelle: values.schema.json, SAM-Leser]),
     `demo-observability` niedriger, explizit in den Monitoring-Values.
   - ValidatingAdmissionPolicy (GA seit 1.30, kein Webhook, blockiert
     `az aks stop` nicht): Service `LoadBalancer` nur mit
     `azure-load-balancer-internal: "true"` (fängt den öffentlichen
     LB-Default des pubsubplus-Charts); Ingress ohne `mirror-target`,
     `mirror-host`, `*-snippet`; Certificate und Ingress nur mit Issuer
     `letsencrypt-dns(-staging)` und Hosts unter `<zone>`.
3. ingress-nginx:

   ```bash
   haks upgrade --install ingress-nginx ingress-nginx \
     --repo https://kubernetes.github.io/ingress-nginx --version 4.15.1 \
     -n ingress-nginx --create-namespace \
     -f sli/aks/ingress-nginx-values.yaml
   ```

   Werte: `replicaCount: 2` mit PDB; Service-Annotationen
   `azure-load-balancer-internal: "true"`,
   `azure-load-balancer-ipv4: 10.20.0.250`,
   `azure-load-balancer-health-probe-request-path: /healthz` (sonst
   probt Azure `/` wegen appProtocol http/https),
   `azure-load-balancer-tcp-idle-timeout: "30"` (Default 4 min, SAM
   braucht 900 s, SSE 3600 s) [Quelle:
   `cloud-provider-azure.sigs.k8s.io/topics/loadbalancer`];
   `allowSnippetAnnotations: false`; `annotations-risk-level` gesenkt
   wie im CVE-2026-116472-Hinweis [Quelle:
   `www.openwall.com/lists/oss-security/2026/11/05/4`] [A: vorher alle
   Ingresses per `kaks apply --dry-run=server` prüfen].
4. cert-manager mit Workload Identity:

   ```bash
   haks upgrade --install cert-manager cert-manager \
     --repo https://charts.jetstack.io --version v1.20.2 \
     -n cert-manager --create-namespace \
     -f sli/pki/manifests/01-cert-manager-values.yaml \
     -f sli/aks/cert-manager-values.yaml   # podLabels, SA-client-id
   az identity federated-credential create -g rg-eurocis-base \
     --identity-name id-cert-manager -n cert-manager \
     --issuer "$(az aks show -g rg-eurocis-aks -n aks-eurocis \
       --query oidcIssuerProfile.issuerUrl -o tsv)" \
     --subject system:serviceaccount:cert-manager:cert-manager \
     --audience api://AzureADTokenExchange
   CM_PID=$(az identity show -g rg-eurocis-base -n id-cert-manager \
     --query principalId -o tsv)
   az role assignment create --role "DNS Zone Contributor" \
     --assignee-object-id "$CM_PID" \
     --assignee-principal-type ServicePrincipal --scope <zone-id>
   ```

   ClusterIssuer `letsencrypt-dns-staging` und `letsencrypt-dns`
   [Quelle: gpd spikes/aks/clusterissuer-letsencrypt-dns.yaml;
   `cert-manager.io/docs/configuration/acme/dns01/azuredns`]. Erst ein
   Test-Certificate für `echo.<zone>` gegen staging, dann prod. Ein
   Certificate je Host: Ein Wildcard-Secret müsste in jeden Namespace
   kopiert werden, und der SAM-Chart prüft beim Install, dass das
   TLS-Secret im eigenen Namespace existiert (SAM-Leser).
5. DNS-Records auf die interne IP. Grafana bekommt keinen Namen (kein
   Stand-Bestandteil, Zugriff per Port-Forward); `echo` dient nur den
   Tests in Schritt 6 und den Netz-Drills:

   ```bash
   for h in auth sam gpos gpos-grpc gpos-wws-grpc gpos-loyalty-grpc echo; do
     az network dns record-set a add-record -g rg-eurocis-base \
       -z <zone> -n $h -a 10.20.0.250
   done
   ```

6. Hairpin- und gRPC/SSE-Test mit einem Echo-Pod hinter
   `echo.<zone>`: Curl-Pod (`<acr>.azurecr.io/curl:8.23.0`) gegen
   `https://echo.<zone>` (System-Truststore); ein gRPC-h2c-Echo per
   `grpcurl` und ein 20-min-SSE-Stream durch den Ingress. Ab P3 läuft
   derselbe Test zusätzlich gegen
   `https://auth.<zone>/realms/solace-lab/.well-known/openid-configuration`.
   Rückfall bei Hairpin-Problemen: `kube-system/coredns-custom` mit Key
   `*.override` und hosts-Block auf die Ingress-ClusterIP [Quelle:
   `learn.microsoft.com/azure/aks/coredns-custom`]. Das deckt den
   gRPC-Teil (3) von G0-11b am 11.12. [Quelle: PLAN:2702; AKS-E18].
7. Docker-Hub-Images per `az acr import` mit den festen Tags der
   gepinnten Charts in ACR spiegeln. Die Liste kommt aus `helm template`
   mit Lab- und aks-Values (alle Images mit Registry docker.io); heute:
   `grafana/grafana:12.4.3`, `grafana/loki:3.6.7`,
   `grafana/tempo:2.10.1`, `grafana/alloy:v1.18.0`,
   `kiwigrid/k8s-sidecar:2.5.0` (Loki-Rules-Sidecar; alternativ
   `sidecar.rules.enabled: false`). Dazu `postgres` (P3, P6), `solace`
   (P4); `curl` liegt seit P1 dort. `nginx-unprivileged` nur, falls das
   Loki-Gateway an ist. Grund: Alle Node-Pulls gehen über eine
   Egress-IP, anonyme Docker-Hub-Limits träfen sonst Drills.
8. Monitoring: kube-prometheus-stack 83.5.0 (Release
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
   - Grafana ohne Ingress; Zugriff per `kaks -n monitoring port-forward
     svc/kube-prometheus-grafana 3000:80`; Admin aus Secret.
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
   - Ist Defender aktiv: Sensor-DaemonSet mit `kaks top pods -A`
     messen (3.3).

**Wer:** Claude; Owner gibt `sli/aks/` frei (AKS-E15).

**Abnahme:**

- `kaks get certificate -A`: alle Ready mit `letsencrypt-dns` nach
  grünem staging-Lauf.
- Vom Mac über WireGuard ohne `-k`: `curl -sS https://echo.<zone>`
  liefert 200; aus einem Pod ebenso (Hairpin).
- `kaks get svc -A`: jedes LoadBalancer-Service hat eine 10.20.x-IP.
- Drei Negativ-Manifeste werden per VAP abgelehnt (öffentliches LB,
  `mirror-target`, fremder Issuer).
- `haks list -A` zeigt exakt die Lab-Chart-Versionen.
- grpcurl list durch den Ingress; SSE 20 min ohne Abriss.
- Prometheus-PVC Bound, nach Pod-Neustart sind Vortagesdaten da;
  Loki hat Logs aller Namespaces; Loki- und Tempo-Datasource grün.
- Keine Images von Docker Hub mehr, weder explizit noch implizit:
  `kaks -n monitoring get pods -o jsonpath='{..image}' | tr ' ' '\n' |
  sort -u | grep -vE '^(<acr>\.azurecr\.io|quay\.io|registry\.k8s\.io|mcr\.microsoft\.com)/'
  | wc -l` ergibt 0.
- Grafana: `kaks -n monitoring get ingress` ist leer; kein
  `monitoring.<zone>`-Record.

**Abhängigkeiten:** P1, delegierte Zone, Freigabe AKS-E15.

### P3 Keycloak (1,0 PT, KW50)

**Ziel:** OIDC für SAM auf `auth.<zone>` mit Lab-Realm, ohne
Lab-Standardpasswörter, Admin-Oberfläche nicht über den Ingress.

**Schritte:**

1. `az acr import` für `quay.io/keycloak/keycloak:26.8.2` und
   `postgres:17-alpine`, danach per Digest gepinnt. 26.8.2 ist das
   aktuelle Release vom 05.11.2026 [Quelle:
   `api.github.com/repos/keycloak/keycloak/releases`]; der Realm wird
   per Skript neu angelegt, es gibt also keine Migration. Das Lab
   bleibt auf 26.2.
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

   Inhalt: `KC_HOSTNAME https://auth.<zone>`, Ingress-Host und Issuer;
   das Ingress routet nur `/realms/solace-lab/`, `/resources/` und
   `/.well-known/` (pathType Prefix, keine Snippets), denn `/admin/` und
   `/realms/master/` sind laut Keycloak "Internal only" [Quelle:
   `www.keycloak.org/server/reverseproxy`]; Admin-Konsole nur per
   Port-Forward mit `KC_HOSTNAME_ADMIN` [A: hostname v2, in P3 testen];
   Secrets aus Key Vault; Realm-Import ohne die 3 Inline-User [Quelle:
   sli keycloak/manifests/03-keycloak.yaml:29-114]. Weil der Realm ein
   einziger JSON-String in ConfigMap `keycloak-realm` ist
   (03-keycloak.yaml:21-29), ersetzt das Overlay den ganzen Schlüssel
   `solace-lab-realm.json`; diese Kopie kann vom Lab-Realm abdriften.
   Speicher 1Gi Request / 1,5Gi Limit. Saubere Alternative mit eigener
   AKS-E15-Freigabe: eine rein additive
   `sli/keycloak/manifests/kustomization.yaml` (Lab-`setup.sh` wendet
   die Dateien einzeln mit `-f` an), dann ohne `LoadRestrictionsNone`.
3. Realm-Inhalt per Profil, Admin-API über einen Port-Forward, den das
   Skript mit Kontext-Guard selbst öffnet
   (`kaks -n iam port-forward svc/keycloak 18081:8080`,
   `KEYCLOAK_ADMIN_URL=http://127.0.0.1:18081` [A: Port frei]):

   ```bash
   SAM_PROFILE=aks amd/scripts/setup-keycloak-client.sh  # Redirect sam.<zone>
   SAM_PROFILE=aks amd/scripts/setup-keycloak-users.sh   # Passwörter aus KV
   TARGET=aks gpd/scripts/keycloak-marktleitung.sh       # aus spikes/g0
   ```

   Die Skripte brauchen `/realms/master` und `/admin/realms` [Quelle:
   amd scripts/setup-keycloak-client.sh:39, 54;
   setup-keycloak-users.sh:53, 68]. Das Client-Secret wird in
   `.env.aks` bzw. Key Vault geschrieben, nicht in die Lab-`.env`
   [Quelle: amd scripts/setup-keycloak-client.sh:65-90];
   `KEYCLOAK_ISSUER` wird in `.env.aks` von Hand gesetzt. Kein
   `curl -k` auf `aks`, kein Passwort gleich Username [Quelle: gpd
   spikes/g0/keycloak-marktleitung.sh:8-30].
4. Owner: erste Logins und Passwortwechsel im Browser.

**Wer:** Claude 1-3; Owner 4.

**Abnahme:**

- `https://auth.<zone>/realms/solace-lab/.well-known/openid-configuration`
  liefert 200 vom Mac (WireGuard) und aus einem Pod.
- `https://auth.<zone>/admin/` und `/realms/master/` liefern 404.
- Admin-Login über den Port-Forward funktioniert (Token-Request mit dem
  Key-Vault-Passwort liefert HTTP 200); Login mit dem Lab-Admin-Passwort
  scheitert.
- Client `solace-agent-mesh` mit Redirect `https://sam.<zone>/*`;
  7 Gruppen und 7 User inkl. `marktleitung`.
- Lab unverändert: Keycloak-Client und -User (Diff vorher/nachher
  leer); `kubectl --context rancher-desktop -n iam get deploy/keycloak
  sts/postgres -o jsonpath='{..image}'` vorher und nachher gleich
  (Keycloak 26.2), restartCount unverändert. Das Lab-Deployment nutzt
  Strategy Recreate (sli keycloak/manifests/03-keycloak.yaml:131-132):
  ein Apply gegen das Lab würde Keycloak sofort trennen.
- Negativtest: `sli/aks/setup-aks.sh keycloak` bricht im Kontext
  `rancher-desktop` vor jedem Apply ab.

**Abhängigkeiten:** P2.

### P4 Broker (1,25 PT, KW50-51)

**Ziel:** Ein PubSub+ Standard ohne HA, Lab-Version, nur im Cluster
erreichbar, VPNs wie im Lab.

**Schritte:**

1. Image in ACR, Digest gegen Lab prüfen (`sha256:e58d8b69...`;
   `latest` zeigt seit 10.11. auf 10.26.0 [Quelle:
   `hub.docker.com/v2/repositories/solace/solace-pubsub-standard/tags`]):

   ```bash
   az acr import -n <acr> \
     --source docker.io/solace/solace-pubsub-standard:10.25.0.208 \
     --image solace/solace-pubsub-standard:10.25.0.208
   ```

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
   [Quelle: pubsubplus 3.10.0 templates/secret.yaml:1-7, values.yaml:66-70].
   Werte: `redundancy: false`, `solace.size: prod1k`, Image aus ACR,
   `service.type: ClusterIP` mit 55555/8008/8080/5550,
   `solace.usernameAdminPasswordSecretName: solace-admin`, Storage
   `managed-csi-premium` 128Gi, `extraEnvVars`
   `messagespool_maxspoolusage` explizit (rund 20000 MB). Chart-Default
   wäre `latest` und ein öffentliches LoadBalancer [Quelle:
   pubsubplus values.yaml, Broker-Leser].
3. Terraform-Root `emd/terraform-aks/`: ein Provider-Alias
   `solacebroker.aks` (1.3.0, Lock-Datei aus dem Lab kopiert), Module
   `vpn` und `client` wiederverwendet: VPN `default` und `sam`, Client
   `sam` (VPN sam), `gpos` (VPN default), `default` deaktiviert; kein
   DMR, keine Telemetry, kein AMQP 5673. State lokal, gitignored.
   Port-Forward auf 18080, weil 8080/8008/1883/55557 auf dem Mac vom
   Lab-`solace-1` belegt sind [Quelle: Befehl `docker ps`, 16.11.].
   Das Passwort kommt direkt aus dem Key Vault, nie als Literal in die
   Shell-History:

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
   Broker-Identität; er schreibt kein Passwort. Die SEMP-Passwortquelle
   für gpd legt `gpd/scripts/broker.sh` bei `TARGET=aks` selbst an (P6
   Schritt 6, 5.4), weil `broker.py` das Passwort nur aus einer
   tfvars-Datei liest [Quelle: gpd scripts/broker.py:80-87].

**Wer:** Claude.

**Abnahme:**

- Vor dem helm-Aufruf: `kaks -n solace get secret solace-admin -o
  jsonpath='{.data}' | jq 'has("username_admin_password")'` liefert
  `true` (nur der Schlüssel, nie der Wert).
- SEMP über 18080 zeigt VPN `sam` und `default`, User `sam` und `gpos`
  aktiv, `default` aus; kein Broker-Port auf einem LoadBalancer.
- Nach `kaks -n solace delete pod solace-pubsubplus-0` ist der Broker
  in unter 5 min Ready und eine Test-Queue noch da.
- Lab-`solace-1` unverändert (Queue-Liste vorher/nachher gleich).

**Abhängigkeiten:** P2 (ACR-Spiegel, PriorityClasses, VAP).

### P5 SAM (2,5 PT, KW51, Gate G2a 18.12.)

**Ziel:** SAM 2.542.1 auf AKS, Login über Keycloak, Modelle aus dem
Cluster erreichbar, Datenbank mit LiteLLM-Key abgeschirmt. Das erfüllt
"AKS RA-Schritte 1-6 bis SAM" plus Tunnel-RTT [Quelle: PLAN:2734] und
nach AKS-E18 G0-11a sowie den HITL-Teil von G0-11b.

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
   `sam.dnsName`, `ingress.host`, `ingress.tls` auf `sam.<zone>`;
   `cert-manager.io/cluster-issuer: letsencrypt-dns`;
   `nginx.ingress.kubernetes.io/proxy-body-size: "100m"` (heute fehlt
   die Annotation, es gilt der NGINX-Default 1m [Quelle: amd
   local-k8s-values.yaml:110-126]; Wert wie in PLAN 5.2);
   `global.imagePullSecrets: []`; Registry `<acr>.azurecr.io` in allen
   sechs Image-Blöcken; `broker.url:
   ws://solace-pubsubplus.solace.svc.cluster.local:8008`,
   `broker.clientUsername: sam`, `broker.vpn: sam`;
   `persistence-layer.{postgresql,seaweedfs}.persistence.storageClassName:
   managed-csi-premium`; awe-Limit 3Gi, str-Limit 6Gi.
3. Installation per Profil (AKS-E19 vorher entschieden). Das
   Broker-Passwort heißt im Chart `broker.password` [Quelle: amd
   local-k8s-values.yaml:67-71]:

   ```bash
   SAM_PROFILE=aks amd/scripts/start.sh
   # intern (KUBECONFIG aus .env.aks, wie haks): Certificate aus dem
   # Profil rendern und bis 5 min warten, dann:
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

   Ohne Issuer bricht der Chart ab (P0 Schritt 13). `start.sh:73-86`
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
   CoreDNS-NodeHosts-Schritt ist auf `aks` aus; Namespace, Release und
   `namespaceId` bleiben `sam-solace-lab` (Queue-Präfix, e2e und
   Observability-Manifeste unverändert [Quelle: gpd scripts/broker.py:40;
   scripts/e2e.py:116]).
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
   Klartext-Key in `model_configurations`.
5. Logins und Provisionierung:
   - Owner: `SAM_HOME=<aks-home> sam auth login solace-lab --url
     https://sam.<zone>` als sam_admin. Alle Manifeste tragen den
     Zielnamen `solace-lab`, und der Token-Cache ist nach diesem Namen
     geschlüsselt; ein Login unter `eurocis-aks` wäre für plan/apply
     unsichtbar [Quelle: P0 Schritt 12].
   - Claude: `SAM_PROFILE=aks amd/scripts/provision.sh` (RBAC inkl.
     `notify:_:send`, Modelle `fast` und `planning`, max_tokens,
     Pricing, developer-mcp). Das Profil setzt nur `SAM_HOME`; jedes
     `sam config plan/apply` läuft mit `--url $SAM_URL --no-dotenv`, und
     ein Guard vergleicht vorher die gecachte URL des Ziels `solace-lab`
     in diesem Home mit `$SAM_URL` und bricht bei Abweichung ab.
   - Owner: einmal als `marktleitung` in der AKS-WebUI anmelden; der
     Grant wirkt erst nach der ersten Anmeldung [Quelle: PLAN:191].
   - Stellvertreter (AKS-E20): eigener Keycloak-User mit sam_admin im
     AKS-Realm, eigenes `SAM_HOME`, meldet sich selbst an.
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
     Rückfall, falls die Verdrahtung des Key-Vault-Passworts (P2
     Schritt 8) zu aufwendig wird: `grafana-ro` aus der Key-Vault-Liste
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
6. Wrapper `aks-start.sh` und `aks-stop.sh` erweitern: nach
   `az aks start` erst `aks-wg-sync.sh`, dann auf Nodes, Broker und gwe
   warten, awe einmal neu starten (gwe/awe-Race [Quelle: amd
   README.md:502-504]), dann Preflight. Die 30-min-Sperre aus P1
   Schritt 8 bleibt.
7. HITL-, Artefakt- und Vision-Test (G0-11b (1) und G0-11a nach
   AKS-E18):
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
     freigegeben; die `tell`-Benachrichtigung kommt an, ein
     `wf_*`-Artefakt für `marktleitung` liegt in SeaweedFS.
   - 7d: Vision-Probe aus dem Cluster: ein neutrales Testbild (rund
     150-500 KB, kein GEBIT-Material) wird in der AKS-WebUI hochgeladen;
     ein temporärer Probe-Agent (Präfix `gpos-spike-`, `load_artifact`,
     Alias `fast` wie bei A2b [Quelle: PLAN:2694]) beschreibt es
     korrekt. Das belegt LiteLLM mit Bild-Payload, SeaweedFS und
     `proxy-body-size` 100m und erfüllt G0-11a Prüfung (2) auf
     Modellebene [Quelle: PLAN:2701]; der Teil mit `gpos-price-scout`
     folgt in P6.
   - 7e: Aufräumen (G0-02.md nennt keine Befehle): `gpos-spike-events`,
     `gpos-spike-hil-a` und den Probe-Agent einzeln per sam CLI oder
     Plattform-API entfernen, nie `--prune`; die Rest-Queue
     `.../eventmesh/gpos-spike-events/hil_a` per SEMP auf 18080 löschen
     (README Punkt 21); die `wf_*`-Artefakte des Spikes löschen (README
     Punkt 14). Rolle und Claim-Mapping bleiben.
8. Tunnel-RTT (Kabel) messen.

**Wer:** Claude 1-4, 5 (Provisionierung, Grants), 6-8; Owner 5
(Logins), die Freigabe in 7c und AKS-E19; Stellvertreter sein Login.

**Abnahme (G2a):**

- WebUI-Login `https://sam.<zone>` über Keycloak als sam_admin, ohne
  Zertifikatswarnung, über WireGuard.
- Aliase `fast` und `planning` antworten aus dem Cluster (beweist
  LiteLLM über die Egress-IP); die Vision-Probe ist grün.
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
- Metadatenabfrage dokumentiert, Ausschlussliste für P7 fest.
- Ein Zyklus `aks-stop.sh`, mindestens 30 min Pause, `aks-start.sh`
  endet mit geladenen Agents; `route -n get <api-ip>` zeigt `utun`,
  `kaks get --raw /readyz` ok; mindestens ein Zyklus vom Handy-Hotspot
  aus.
- Ein AKS-Zyklus `SAM_PROFILE=aks stop.sh`, dann `start.sh`,
  `provision.sh` und Schritte 4-5 erneut: Lab-Keycloak-Client und -User
  bleiben unverändert (Diff leer), AKS ist danach wieder G2a-grün.
- Tunnel-RTT p95 höchstens 40 ms über Kabel [Quelle: PLAN:2480].
- Lab am selben Tag: Call-Log- und Render-Diff leer, Lab-Smoke grün,
  Lab-sam-Cache (`solace-lab.json` im Default-Home) unverändert.

**Abhängigkeiten:** P3, P4; Commit des Working Trees (P0); AKS-E19.

### P6 GEBIT-Demo portieren (5,0 PT, Vorarbeit KW52-KW1 im Lab, AKS KW1-2, Gate G2b 15.01.)

**Ziel:** UC1 mit S1, S3, S7, S8 Ende zu Ende auf AKS, dazu TR3 (A2b),
sobald es im Lab grün ist (TR3 ist "Nie gestrichen" [Quelle:
PLAN:2564]), und ein TR1-Besuch über WireGuard [Quelle: PLAN:2736].

**Schritte:**

1. Voraussetzung: schriftliche GEBIT-Freigabe (AKS-E16). Ohne sie läuft
   `install.sh k8s` auf AKS nicht. Alle anderen Schritte laufen vorher;
   `pg` und `db` brauchen kein GEBIT-Material.
2. Lab-Vorarbeit (keine AKS-Abhängigkeit): `k8s/` in `base`,
   `overlays/lab` (rendert byte-identisch zur Baseline aus P0 Schritt
   9), `overlays/aks`, später `overlays/l3`. Das aks-Overlay setzt Image
   `<acr>.azurecr.io/gpos-demo/gpos-demo`, Hosts und `dnsNames` unter
   `<zone>`, Issuer `letsencrypt-dns`, entfernt `imagePullSecrets` per
   JSON-Patch und setzt `SAM_URL`. Die Demo-DB liegt nicht im Overlay,
   sondern in einer eigenen kustomization `k8s/postgres-aks/`:
   Namespace `gpos-data`, headless Service `gpos-postgres`, StatefulSet
   `gpos-postgres` (Postgres 18 aus ACR per Digest, 8Gi `managed-csi`,
   `POSTGRES_PASSWORD` aus Secret `gpos-postgres-admin`, Mount auf
   `/var/lib/postgresql` mit dem Image-Default-PGDATA [A: damit
   `lost+found` der Azure-Disk initdb nicht stört]). So berühren
   `install.sh k8s`/`uninstall.sh` und das globale `namespace:
   gpos-demo` die Datenhaltung nicht. Die Namespace-Regel in
   `k8s_render.py`/`install.sh` wird ausdrücklich um `gpos-data`
   erweitert. `scripts/tests/test_k8s.py` prüft Basis, alle Overlays und
   `postgres-aks` [Quelle: heute pinnt der Test Lab-Hosts, gpd
   scripts/tests/test_k8s.py:97-120].
3. sam-CLI-Seam (Ergebnis P0 Schritt 12):
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
4. Image:

   ```bash
   docker buildx imagetools create \
     -t <acr>.azurecr.io/gpos-demo/gpos-demo:0.1.3 \
     registry.solace.lab/gpos-demo/gpos-demo:0.1.3
   ```

5. Demo-DB in zwei Teilen; Reihenfolge auf AKS: `pg` → `db` → `k8s` →
   `mesh`, und `install.sh all` folgt auf `aks` genau dieser Reihenfolge
   (im Lab bleibt `all` = db, k8s, mesh [Quelle: gpd
   scripts/install.sh:243-247]). Heute legt erst `install_k8s` den
   Namespace an, und `install.sh k8s` bricht ohne die db.env aus
   `install.sh db` ab [Quelle: gpd scripts/install.sh:117, 123].
   - 5a `TARGET=aks scripts/install.sh pg` (nur auf `aks`, im Lab ein
     No-op): Namespace `gpos-data`, Secret `gpos-postgres-admin` vom Mac
     an den API-Server (Wert aus Key Vault, Muster `apply_secret`),
     `kaks apply -k k8s/postgres-aks`, `kaks -n gpos-data rollout status
     sts/gpos-postgres --timeout=300s`, dann `pg_isready`.
   - 5b `TARGET=aks scripts/install.sh db`: psql-Seam
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
6. `gpd/.env.aks` (gitignored) und `.env.aks.example` (Obermenge von
   `ENV_KEYS`):
   - `SAM_URL=https://sam.<zone>`, `SAM_HOME=<aks-home>`,
     `SAM_RUN_IDENTITY=marktleitung@solace.lab` (bewusst unverändert,
     8.2), `KUBE_CONTEXT=aks-eurocis`,
     `KUBECONFIG=~/.kube/aks-eurocis.yaml`, `AWE_NS=sam-solace-lab`,
     `AWE_DEPLOY=agent-mesh-solace-agent-mesh-awe`
   - `E2E_BASE_URL=https://gpos.<zone>`, `E2E_CA_FILE=system`,
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
7. `TARGET=aks scripts/install.sh k8s`: Secrets `gpos-broker`,
   `gpos-db`, `gpos-gebit-descriptors` direkt vom Mac an den
   API-Server; gRPC-Ingresses nur intern. Reflection nach AKS-E16:
   - Standard (a): Reflection bleibt an wie im Lab (PLAN-E2,
     Tiefenecke [Quelle: PLAN:546-550]); die Ingresses sind nur intern
     und nur per WireGuard erreichbar. Image 0.1.3, Digest-Parität und
     Smoke-Schritt 1 (Reflection auf gpos-pos meldet den
     PurchaseTransactionService [Quelle: gpd scripts/smoke.py:329-335])
     bleiben gültig.
   - Verlangt GEBIT Reflection aus, Variante (c) ohne neues Image: Das
     aks-Overlay ersetzt den gRPC-Ingress-Pfad `/` (k8s/ingress-grpc.yaml)
     durch Prefix-Pfade der Dienste, z. B. für gpos-pos
     `/de.gebit.rp.purchase.purchase.v2.service.PurchaseTransactionService`
     und `/grpc.health.v1.Health` (wws und loyalty analog); für
     `/grpc.reflection.*` gibt es keine Route. Clusterintern bleibt
     Reflection an, Smoke (direkt auf gpos-pos:50051) und
     Digest-Parität sind nicht betroffen. Am Stand gehen Aufrufe dann mit
     `-protoset` vom Owner-Mac (nie in Git oder Images). [A]
     ingress-nginx könnte Prefix-Pfade mit Punkten ablehnen; dann
     ImplementationSpecific/Regex, Test in P2.
   - Nur wenn GEBIT Reflection auch im Cluster verbietet, Variante (b):
     Schalter `GPOS_GRPC_REFLECTION` in `grpcutil.serve` (Default an,
     Unit-Test in app/tests/common/test_grpcutil.py), gesetzt über die
     ConfigMap `gpos-config`; `smoke.py` erwartet bei aus
     `UNIMPLEMENTED`; gebaut als Image 0.1.4 in der Lab-Vorarbeit
     KW52-53 (GEBIT antwortet bis 11.12.), zuerst im Lab (`make test`,
     `make smoke`, S1-e2e), dann 0.1.4 statt 0.1.3 nach ACR (Makefile
     `GPOS_VERSION`, Schritt 4 und G2b-Abnahme); PLAN-E2 und die
     Abnahmen von AP04a und G0-07 werden als Änderung im PLAN
     nachgetragen ("auf AKS Tiefenecke nur per kubectl port-forward").

   `install.sh` überspringt auf `aks` das Warten auf Kyverno und den
   Lab-CA-Export.
8. `make manifests`, `TARGET=aks make smoke`; die Anmeldung als
   `marktleitung` (P5 Schritt 5) nur noch prüfen.
9. `TARGET=aks scripts/install.sh mesh`: RBAC, Manifest, hygiene
   `--platform`, Probe-Entrypoint, Proben p1/p3/p4/notify, **volle**
   Gate-Verifikation auf Kasse 98 (rund 11 min, in
   `build/aks/gate-verified`), R1-Queue, Booth-Entrypoint, Proben
   r1/r3/r4.
10. `TARGET=aks make e2e`: S1 x5, S3 x5, S7 x5, S8 x5, S1 deny x5, S1
    timeout x2; `scripts/reset.sh --scope day --preflight`; TR3 (A2b),
    sobald es im Lab grün ist: Foto über die BFF `/foto` per WireGuard
    → `load_photo` → `gpos-price-scout` mit Alias `fast` [Quelle:
    PLAN:2477, 2705]. Liegt TR3 bis G2b nicht vor, wandert der Punkt in
    die G3-Abnahme.
11. Wiederholbarkeit: `TARGET=aks scripts/uninstall.sh` (ohne
    `--drop-db`) lässt `gpos-postgres` samt PVC in `gpos-data` stehen;
    danach `TARGET=aks scripts/uninstall.sh --drop-db` (DB und Rollen
    über den Seam löschen, aks-db.env entfernen, optional Namespace
    `gpos-data`) und `TARGET=aks scripts/install.sh all` aus leerem
    Namespace, Dauer protokolliert [Quelle: PLAN:2480].
12. Router-Peer, spätestens KW1 (die Leihgeräte stehen ab 11.12. im Lab
    [Quelle: PLAN:2618]): Der Router erzeugt sein Schlüsselpaar selbst
    (sonst Ausnahme nach P1 Schritt 3); Claude trägt den Peer per
    `az vm run-command` mit den eingeschränkten FORWARD-Regeln ein (nur
    10.20.0.250 tcp/443 und tcp/80); das Stand-LAN-Subnetz darf
    10.20/16, 10.244/16 und 10.0/16 nicht überlappen. Owner
    (physischer Zugang, Router-UI-Login): Client-Konfiguration auf dem
    Router, Endpoint `pip-wg:51820`, Rückfall `:443`, `AllowedIPs`
    10.20.0.250/32, DNS-Rebind-Ausnahme für `<zone>`.
13. Tier auf Standard: `az aks update -g rg-eurocis-aks -n aks-eurocis
    --tier standard` (am 15.01.), danach `aks-wg-sync.sh`.

**Wer:** Claude 2-7, 9-11, 12 (VM-Seite); Owner 1, 8 (Login), 12
(Router), 13 (Freigabe).

**Abnahme (G2b):**

- 6 Deployments 1/1; Image-Plattform-Digest gleich Lab
  (`docker buildx imagetools inspect` beider Refs).
- Vor `install.sh mesh`: `TARGET=aks scripts/broker.sh r1-show`
  liefert 200, nicht 401; ohne `SEMP_PASSWORD_FROM` bricht derselbe
  Aufruf mit der Guard-Meldung ab, ohne dass ein Request einen Broker
  erreicht.
- Smoke READY auf Kasse 99; `build/aks/gate-verified` PASS 10/10 mit
  `target=aks`.
- e2e 27/27 mit Lab-Erwartungen: S1 100001 7,99; S3 100012 12,99 mit
  Loyalty; S7 100008 5,49 mit 3 api_queries; S8 no_action; deny und
  timeout korrekt [Quelle: gpd scripts/e2e.py:156-164].
- TR3 auf AKS (falls im Lab grün): 5/5 Läufe korrekt, Werte auf dem
  Monitor p90 höchstens 5 s (AP10).
- `uninstall.sh` ohne `--drop-db` lässt `gpos-postgres` und sein PVC
  stehen; `TARGET=aks scripts/install.sh all` aus leerem Namespace in
  höchstens 30 min inklusive voller Gate-Verifikation, Dauer
  protokolliert.
- Alle gpos-Pods Ready, keine DSN-, Port- oder `invalid integer
  value`-Fehler in den Logs von engine, wws, loyalty und pos.
- Reset unter 15 s; A4 p50 höchstens 18 s, p90 höchstens 24 s.
- TR1-Besuch vom Leihgerät hinter dem Leih-Router über WireGuard grün;
  `gpos-grpc` von außerhalb des Tunnels unerreichbar. Router-Peer:
  `wg show` auf vm-wg zeigt einen frischen Handshake auf 51820 und auf
  443; ein Gerät hinter dem Router erreicht die UI-Hostnamen; von dort
  liefern `/admin/` und `/realms/master/` auf `auth.<zone>` 404,
  `monitoring.<zone>` hat keinen Record, eine Node-IP auf 10250 und ein
  NodePort laufen in den Timeout.
- Reflection nach AKS-E16: bei (a) zeigt `grpcurl gpos-grpc.<zone>:443
  list` über WireGuard den PurchaseTransactionService; bei (c) scheitert
  `list` (404/UNIMPLEMENTED), ein Aufruf mit `-protoset` gelingt.
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
  Key-Variable in der Image-Umgebung, User 10001:10001.
- `TARGET=aks scripts/uninstall.sh` mit einer `.env.aks` ohne `SAM_URL`
  bricht vor dem ersten `api()`- oder kubectl-Aufruf ab (`set -x`-Log).
- In allen Namespaces kein Image mehr von Docker Hub (Prüfung wie P2
  mit `-A`).
- Lab danach: Overlay-Render identisch zur Baseline, `make smoke` und S1
  grün.

**Abhängigkeiten:** P5, AKS-E16, Leih-Router (11.12.), TR3-Stand im Lab.

### P7 Härtung und Betrieb (4,5 PT, KW3-KW7, Gates G3 und G4)

**Ziel:** Drills bestanden, Backups getestet, Runbook steht, Betreiber
und Stellvertreter einsatzbereit, Freeze ohne Überraschungen.

**Schritte:**

1. Requests mit einer Woche AKS-Prometheus-Daten nachziehen.
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
   - LE-TLS-Secrets als volles Secret-Objekt in JSON, mit `data`, allen
     `cert-manager.io/*`-Annotationen (issuer-name, issuer-kind,
     issuer-group, certificate-name, alt-names, common-name) und Labels,
     ohne Cluster-Felder (Limit 25 KB, ein TLS-Secret hat rund 7-8 KB):

     ```bash
     kaks -n <ns> get secret <x> -o json | jq 'del(.metadata.uid,
       .metadata.resourceVersion, .metadata.creationTimestamp,
       .metadata.managedFields, .metadata.ownerReferences)' > <x>.json
     az keyvault secret set --vault-name <kv> -n tls-<ns>-<x> \
       --file <x>.json -o none
     ```

     Nicht `az keyvault certificate import`: Es verwirft die
     Annotationen, und cert-manager stellte dann wegen IncorrectIssuer
     neu aus [A].
   - Keine CSI-VolumeSnapshots: `pg_dump` mit Restore-Test ist der
     einzige Backup-Pfad; das SAM-Postgres-PVC würde den Key enthalten.
3. Drills vor G3 [Quelle: PLAN:148]:
   - Neuaufbau: `az group delete -n rg-eurocis-aks` (nimmt
     `rg-eurocis-nodes` mit), dann alles aus Skripten inkl. der
     Wartungskonfigurationen mit beiden Sperrbereichen; Federated
     Credentials neu (neuer OIDC-Issuer); Rollen des Stellvertreters neu
     (neue `<aks-id>`); danach `aks-wg-sync.sh` (neuer FQDN, neue IP).
     TLS: die Secrets direkt nach dem Anlegen der Namespaces einspielen,
     **vor** den expliziten Certificates, vor jedem Ingress mit
     `cert-manager.io/cluster-issuer` und vor dem SAM-Install; sonst den
     Drill nur gegen `letsencrypt-dns-staging`. Jeder Drill ohne
     wirksames Backup verbraucht je Host eine von 5 Ausstellungen je
     exaktem Namensset in 7 Tagen, aufgefüllt um eine je 34 h;
     Neuausstellungen desselben Sets zählen nicht gegen das Limit von 50
     je registrierter Domain; `export-le-certs.sh` stellt nichts aus
     [Quelle: `letsencrypt.org/docs/rate-limits`].
   - 24-h-Lauf mit 450 Läufen/h von Mo 18.01. 12:00 bis Di 19.01.
     12:00, also nicht über das Mittwochsfenster (der 20.01. ist
     zusätzlich gesperrt); N-1-Drain während e2e; 3 Stop/Start-Zyklen
     mit je mindestens 30 min Pause (zusammen rund 2,5-3 h [A]).
   - 10-h-Kiosklauf (AP11) parallel zum 24-h-Lauf: `/monitor`,
     `/kasse`, `/kunde` und `/freigabe` im Kiosk-Browser der
     Messe-Hardware über WireGuard (Leih-Router) gegen AKS [Quelle:
     PLAN:148, 2479].
   - Netz: UDP 51820, UDP 443, 5G über den Leih-Router, inklusive
     DNS-Rebind-Einstellung des Routers [A: RutOS filtert private
     Antworten]; kubectl vom 5G-Netz über das Profil `aks-admin-full`;
     Negativtests des Router-Peers aus P6 wiederholen.
   - L3-Drill (AP14b): Lab-MacBook im Profil `l3` mit AKS-Hostnamen
     [Quelle: PLAN:2483]. Der Wechsel `lab` ↔ `l3` ist umkehrbar und
     endet mit dem Lab-Regressions-Gate.
   - Tempo: Füllstand des Tempo-PVC nach dem 24-h-Lauf ablesen. Die
     Retention bleibt 48 h; nur bei Reserve im aks-Overlay auf 168 h
     erhöhen (AKS-E15), sonst bleiben die Span-Metriken 7 Tage in
     Prometheus.
4. Runbook und `preflight.sh TARGET=aks` (Tunnel, Zertifikatsablauf,
   Broker-Spool, SAM-Health, Modellprobe, Inbox-Token, gRPC-Health).
   Erster Schritt für jeden Betreiber morgens ein nicht-interaktiver
   Aufruf über kubelogin: `kaks auth can-i get pods -n gpos-demo`;
   scheitert er, meldet sich die Person selbst mit `az login` an, vor
   Standöffnung. Runbook-Regeln: Start frühestens 30 min nach Stop;
   Umfang des Stellvertreters (Schritt 7). Keycloak-Admin ist seit P3
   nicht über den Ingress erreichbar; P7 prüft das nur noch.
5. Di 26.01., nach Ende eines eventuell laufenden Auto-Vorgangs:
   `az aks nodepool upgrade --node-image-only` als letztes Node-Image
   vor der Sperre (ab 27.01.). Danach `az aks nodepool show --query
   nodeImageVersion` und je Node Name, Label
   `kubernetes.azure.com/node-image-version` und `bootID` notieren:
   `kaks get nodes -o custom-columns=NAME:.metadata.name,IMG:.metadata.labels.kubernetes\.azure\.com/node-image-version,BOOT:.status.nodeInfo.bootID`.
   Das Label allein reicht nicht, weil SecurityPatch auch ohne
   VHD-Wechsel live patchen kann. Probetage 1-3 (28.01., 29.01.,
   03.02.), G4 und Messe laufen auf diesem Image.
6. Um den 04.02.: `cmctl renew --all -A`. So sind alle Zertifikate
   90-Tage-Zertifikate vor dem LE-Wechsel auf 64 Tage am 10.02.2027
   [Quelle: `letsencrypt.org/ca/upcoming-features`]; nächste Erneuerung
   erst im April. Danach TLS-Backup (Schritt 2) und
   `export-le-certs.sh` für L3.
7. Betrieb mit Betreiber und Stellvertreter (AKS-E20):
   - Bis G3 bekommt der Stellvertreter: "Azure Kubernetes Service RBAC
     Cluster Admin" auf `<aks-id>` (enthält
     `listClusterUserCredential`); eine eigene Rolle mit
     `Microsoft.ContainerService/managedClusters/read`,
     `.../runcommand/action`, `.../commandResults/read` und
     `.../start/action` für `az aks start` und Break-glass (die
     AKS-Contributor-Rolle ginge auch, erlaubt aber zusätzlich stop,
     delete und enable-local-accounts); "Key Vault Secrets User" auf
     `<kv>`; einen eigenen WireGuard-Admin-Peer mit beiden Profilen;
     eigener Keycloak-User und eigenes `SAM_HOME` (P5). Er meldet sich
     selbst an; Owner und Claude geben nie seine Passwörter ein.
   - GEBIT: Jede schreibende AKS-RBAC-Rolle liest Secrets, also auch
     `gpos-gebit-descriptors`. Ohne Zustimmung in AKS-E16 bekommt der
     Stellvertreter seine Datenrolle nur je Namespace ohne `gpos-demo`
     (oder "RBAC Reader"); ein Fehler in `gpos-demo` heißt dann L3, und
     nur der Owner stellt das Descriptor-Secret wieder her.
   - Umfang des Stellvertreters: Preflight, `aks-start.sh`, Pod- und
     awe-Neustarts, Backups, Umschaltung auf L3 oder L4. Kein Neuaufbau
     und kein SAM-Helm-Upgrade (Descriptor-Secret nur vom Owner-Mac,
     LiteLLM-Key nur in dessen `amd/.env.aks`).
   - Ab 05.02.: Freeze, kein `az aks stop` bis 19.02., Preflight jeden
     Morgen durch den Betreiber, L3 warm, Netztest am 14.02. [Quelle:
     PLAN:150]. Am Morgen des 14.02. melden sich Owner und Stellvertreter
     frisch an (bei kurzer Conditional-Access-Frequenz täglich).
   - Tägliche Backups wie Schritt 2, inklusive gpos-DB, nach jedem
     Messetag nach Standschluss und vor `reset.sh --scope day` (damit
     auch der 18.02. gesichert ist).
8. Nach der Messe (19./20.02.), jeder Schritt erst nach Erfolg des
   vorigen:
   - (1) Export auf den Mac, nie in Git: gpos-DB, SAM-WebUI-DB,
     Plattform-DB mit den Ausschlüssen aus Schritt 2, Loki-Export für
     16.-18.02. (Loki hält 7 Tage). Tempo nur, falls die Retention
     erhöht wurde.
   - (2) Descriptor-Material entfernen: `kaks -n gpos-demo scale deploy
     --all --replicas=0` (gpos-pos und gpos-ui halten den Mount), dann
     `kaks -n gpos-demo delete secret gpos-gebit-descriptors`; oder den
     Namespace `gpos-demo` löschen (die Demo-DB in `gpos-data` bleibt).
     Zeit und Befehlsausgabe protokollieren (AKS-E16).
   - (3) `az aks stop`; Disks und PVCs bleiben.
   - (4) `gpos-data` nur mit der Rückbau-Entscheidung oder der
     GEBIT-Übergabe löschen.
   - (5) Owner entscheidet Rückbau (`az group delete` von
     `rg-eurocis-aks` und `rg-eurocis-base`; `rg-eurocis-nodes` geht mit
     dem Cluster) oder GEBIT-Übergabe. Beim Rückbau ohne Übergabe danach
     `az keyvault list-deleted --query "[?name=='<kv>']" -o table` und
     `az keyvault purge -n <kv> -l germanywestcentral` (eigene Freigabe
     des Owners, nicht umkehrbar, braucht Purge-Recht; gibt den global
     reservierten Namen frei). Alle Dumps und Scratch-DBs löschen,
     protokolliert; Budget und Abend-Check entfernen.
9. Doku: AKS-Abschnitte in README und RUNBOOK, Drift korrigieren (siehe
   Abschnitt 8), markdownlint.

**Wer:** Claude 1-6, 9; Betreiber und Stellvertreter (AKS-E20) 7 und
die Probetage; Owner Freigaben, Drill-Teilnahme, 8.

**Abnahme:**

- G3: Neuaufbau bis Preflight READY in höchstens 4 h [Quelle:
  PLAN:2481]; nach dem TLS-Restore zeigt `kaks get certificaterequest
  -A` keine neuen Requests für die wiederhergestellten Hosts, alle
  Certificates Ready, `notAfter` gleich dem Backup (`openssl x509
  -noout -enddate`); 24-h-Lauf ohne OOMKilled und ohne NotReady;
  10-h-Kiosklauf mit 0 manuellen Reloads, Browser-Speicher stabil
  (±20 %), Attract-Loop läuft; N-1-Drain ohne fehlgeschlagenen
  e2e-Lauf; aus gestopptem Cluster bis READY in höchstens 30 min,
  gemessen ab `az aks start` [A: Zielwert]; L3-Drill höchstens 3 min
  [Quelle: PLAN:2483]; Restore-Test aller Dumps grün, Zählprüfungen 0;
  Rollen, Peer und Keycloak-User des Stellvertreters bereit. Fehlt TR3
  aus P6, folgt es hier.
- Probetag 1 (28.01.): Runbook-Durchlauf des Stellvertreters mit
  eigenem Konto; vor G4 (z. B. 03.02.) einmal Break-glass mit
  `az aks command invoke` mit eigenem Konto.
- G4: 100 Läufe mindestens 98 % ohne Rückfall [Quelle: PLAN:149]; alle
  Certificates `notAfter` nach dem 30.04.2027; `az aks
  maintenanceconfiguration show` zeigt beide Sperrbereiche auf allen
  drei Konfigurationen; Node-Image, Node-Namen und `bootID` am 28.01.,
  03.02. und 05.02. gleich dem Stand nach dem Refresh am 26.01.; das
  Activity Log (`az monitor activity-log list` auf die
  Cluster-Ressource) zeigt zwischen 27.01. und 05.02. keinen
  automatischen Node-OS- oder Upgrade-Vorgang; nach dem letzten Start
  vor dem 05.02. funktioniert kubectl vom 5G-Netz durch den Tunnel;
  Preflight READY in unter 15 min aus kalt.
- Messe: Node-Image-Vergleich am 16.02. wie bei G4.
- Löschung des Descriptor-Secrets bis 20.02.2027 protokolliert; Dumps
  nach der Messe gelöscht und protokolliert.

**Abhängigkeiten:** P6; GEBIT-Netzparameter (fällig 18.12. [Quelle:
PLAN:2619]); Kiosk-Hardware und `/monitor` live (G2b); AKS-E20.

## 5. Notwendige Änderungen je Repo

Grundsatz: AKS kommt als additives Profil dazu. Lab-Pfade und
Lab-Defaults bleiben unverändert, belegt durch Call-Log- und
Render-Diff (P0 Schritt 13); jede Änderung an einem geteilten Repo
braucht die Freigabe AKS-E15.

### 5.1 solace-lab-infrastructure (geteilt, Freigabe nötig)

- Neuer Ordner `aks/`, nur neue Dateien:
  - `versions.env` (gepinnte Lab-Versionen), `lib.sh` (`kaks`/`haks`,
    `require_kube_context` mit Prüfung der Server-URL).
  - `foundation.sh`, idempotent show-or-create: RGs, VNet,
    `pip-aks-egress`, `pip-wg`, `nsg-wg` mit Regel, UAMIs und
    Rollenzuweisungen mit `--assignee-principal-type`, DNS-Zone, ACR
    mit curl-Testimage, Key Vault mit Secrets-Officer-Zuweisung (nur
    wenn sie fehlt), Warteschleife und Secrets nach P1 Schritt 3
    (create-if-missing, hex, `-o none`), WG-VM mit System-Identity und
    Rolle auf genau `wg-server-key`.
  - Wartungs-JSONs mit beiden Sperrbereichen (auch für den Neuaufbau).
  - `setup-aks.sh` mit Kontext-Guard; Values-Overlays für
    ingress-nginx, cert-manager und Monitoring (Registry je Image,
    vollständige `additionalDataSources`, Grafana ohne Ingress);
    ClusterIssuer, VAP, PriorityClasses.
  - `cloud-init-wg.yaml` ohne Schlüssel (Key per IMDS aus dem Key
    Vault, FORWARD-Policy je Peer, Umleitung UDP 443).
  - `keycloak/` (kustomization mit den Lab-Manifesten als einzeln
    gelisteten Ressourcen, Patches, Realm-JSON-Kopie, Ingress nur für
    die Realm-Pfade).
  - `aks-start.sh`, `aks-stop.sh`, `aks-wg-sync.sh`.
- Kein Eingriff in `ingress/`, `pki/`, `registry/`, `keycloak/`-Lab-
  Skripte. Hinweis: Die Lab-Skripte pinnen keine Chart-Version [Quelle:
  sli ingress/scripts/setup.sh:47-49; pki/scripts/setup.sh:49-52,
  82-84, 137-139, 171-174, 184-186, 193-195, 202-204]; Pinning im Lab
  ist eine eigene, optionale Freigabe. Ebenso eigene Freigabe: eine
  additive `keycloak/manifests/kustomization.yaml` (P3 Schritt 2).
- Keine GEBIT-Inhalte, daher versionierbar; Hygiene-Prüfung
  `grep -rnE 'PrivateKey|[A-Za-z0-9+/]{43}=' aks/` ohne Treffer.

### 5.2 agent-mesh-deployment (geteilt, Freigabe nötig)

- Commit des offenen Working Trees (P0).
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
  apply-rbac.sh:60, generate-manifest.sh). `SAM_AUTH_TOKEN` überschreibt
  den OAuth-Cache von `config plan/apply` nicht, nur
  `SAM_PLATFORM_TOKEN`.
- `start.sh`, `stop.sh`, `provision.sh`, `apply-rbac.sh`,
  `apply-models.sh`, `apply-entrypoints.sh`, `set-max-tokens.sh`,
  `set-pricing.sh`, `upgrade-preflight.sh`, `load-images.sh`:
  Konstanten aus dem Profil (Lab-Werte als Default),
  `--context rancher-desktop` bzw. die Wrapper, `--url` und
  `--no-dotenv`; CoreDNS-NodeHosts nur auf `lab`; Certificate aus
  Variablen rendern. `start.sh` prüft auf `aks` zusätzlich
  `SAM_BROKER_PASSWORD`, `SAM_SESSION_SECRET_KEY`,
  `SAM_PG_ADMIN_PASSWORD` und setzt
  `persistence-layer.postgresql.password` nur dort. `stop.sh` verlangt
  auf `aks` `SAM_SEMP_URL` und `SAM_SEMP_PASSWORD`, sonst gälte
  admin/admin [Quelle: amd scripts/stop.sh:150-163], und schluckt
  Fehler der Keycloak-Teardowns dort nicht mit `|| true`; optional
  überspringt es auf `aks` den Keycloak-Teardown ohne `--keycloak`.
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
- Keycloak-Setup-Skripte: `SAM_DNS_NAME`/`KEYCLOAK_URL` aus dem Profil,
  Admin-API auf `aks` über `KEYCLOAK_ADMIN_URL` (Port-Forward),
  Secret-Writeback in die Profildatei [Quelle: amd
  scripts/setup-keycloak-client.sh:22, 65-90]. Mit eigener Freigabe:
  `--data-urlencode` statt `-d "password=..."` (setup-keycloak-client.sh:44,
  setup-keycloak-users.sh:58); durch hex-Secrets nicht zwingend.
- Grafana: `grant-grafana-platform-db.sh` bricht auf `aks` ab; neu
  `scripts/observability/grant-grafana-aks.sh` (P5 Schritt 5: Rolle mit
  Key-Vault-Passwort, CREATE oder ALTER ROLE, explizite Tabellenlisten,
  SQL per stdin).
- Neu: `aks-values.yaml`, `manifests/aks/` (NetworkPolicies nach P5
  Schritt 4), `.env.aks.example`; `.env.aks` in `.gitignore`;
  README-Abschnitt "AKS". Schlüssel in `.env.aks.example`:
  - Keycloak: `KEYCLOAK_URL=https://auth.<zone>`,
    `KEYCLOAK_ADMIN_URL=http://127.0.0.1:18081` (Port-Forward),
    `KEYCLOAK_REALM=solace-lab`, `KEYCLOAK_ADMIN_USER`,
    `KEYCLOAK_ADMIN_PASSWORD` (Wert aus Key Vault).
  - OIDC: `KEYCLOAK_CLIENT_ID=solace-agent-mesh`,
    `KEYCLOAK_ISSUER=https://auth.<zone>/realms/solace-lab` (von Hand;
    `setup-keycloak-client.sh` schreibt nur `KEYCLOAK_CLIENT_SECRET`
    zurück), `KEYCLOAK_CLIENT_SECRET`.
  - Secrets: `LLM_SERVICE_API_KEY` (nur hier und in der
    SAM-Modellkonfiguration), `SAM_BROKER_PASSWORD`,
    `SAM_SESSION_SECRET_KEY`, `SAM_PG_ADMIN_PASSWORD`,
    `GRAFANA_RO_PASSWORD`, `SAM_SEMP_PASSWORD` (Werte aus Key Vault).
  - Pfade: `SAM_CHART_PATH`, `SAM_CLI_PATH`.
  - Ziel: `KUBECONFIG=~/.kube/aks-eurocis.yaml`,
    `SAM_KUBE_CONTEXT=aks-eurocis`, `SAM_HOME`,
    `SAM_DNS_NAME=sam.<zone>`, `SAM_URL=https://sam.<zone>`,
    `SAM_SEMP_URL=http://127.0.0.1:18080`.
  - Nicht enthalten: die `SAM_*_IMAGE_TAR`-Schlüssel (Images über ACR)
    und `GOOGLE_AI_STUDIO_API_KEY` (AKS stellt nur `fast` und
    `planning` bereit).
- Gate: Call-Log- und Render-Diff des Lab-Profils leer (P0 Schritt 13).

### 5.3 event-mesh-deployment (geteilt, Freigabe nötig)

- Neu: `aks/pubsubplus-values.yaml` (u. a.
  `solace.usernameAdminPasswordSecretName: solace-admin`), `aks/lib.sh`
  (`kaks`), `aks/semp-aks.sh` (Port-Forward und Identitätsprüfung,
  schreibt kein Passwort), `terraform-aks/` (eigener Root, ein
  Provider-Alias, Module `vpn`/`client` wiederverwendet, State
  gitignored, Passwort per `TF_VAR_admin_password` aus dem Key Vault).
  Lab-Compose und Lab-Terraform unverändert.
- Empfohlen, eigene Freigabe: Lab-Image `PUBSUB_IMG` von `latest` auf
  10.25.0.208 pinnen. `latest` ist seit 10.11. 10.26.0, und ein neuer
  Lab-Container würde sonst die Version wechseln [Quelle: emd
  .env.example; Docker-Hub-Tags].

### 5.4 gebit-price-agent-demo (im sda-Repo versioniert, keine Infra-Freigabe)

- Baseline und Rückweg über sda-Commits (P0 Schritt 9).
- `TARGET`-Schalter; ein Loader `opslib.env_file(target)` (lab
  `.env`, aks nur `.env.aks`), den `demo_env()` und damit `e2e.py`,
  `sam_inbox.py`, `broker.py`, `render_mesh.py` und
  `check_manifests.py` nutzen; `lib.sh` setzt `SAM_PROFILE` aus
  `TARGET` vor dem Sourcen von amd `common.sh` und bricht bei
  Widerspruch ab; das Makefile verzichtet für env-abhängige Rezepte
  (`manifests`, `push`, `test-gebit`, `test-int`, `urls`) auf eigenes
  `LOAD_ENV` und den Lab-Default `GPOS_IMAGE ?=` und holt die Werte über
  `scripts/lib.sh` bzw. einen Helfer `scripts/env.sh TARGET`.
- Fail-closed-Check bei `TARGET=aks` (P0 Schritt 11) mit Tests in
  `scripts/tests/test_env_and_hygiene.py`: `.env.aks.example` ist eine
  Obermenge von `ENV_KEYS`; der Check lehnt eine `.env.aks` ohne
  `SAM_URL` und eine mit `E2E_BASE_URL=https://gpos.solace.lab` ab; mit
  `TARGET=aks` liest `demo_env()` keine `.env` (Scratch-Baum mit
  abweichender `.env`); `TARGET=aks` mit `SAM_PROFILE=lab` bricht ab.
- Zustand je Ziel (`mesh/.rendered/<target>`, `build/<target>`) per
  Kopie; `KUBE_CONTEXT`-Wrapper mit `KUBECONFIG`.
- sam-CLI-Seam nach P6 Schritt 3: Haupt-Manifeste an Ort und Stelle,
  nur Entrypoints je Ziel gerendert; `--sam-home`, `--url $SAM_URL`,
  `--no-dotenv`.
- psql-Seam `PG_MODE=docker|kubectl`; `install.sh` mit den Teilen
  `pg|db|k8s|mesh|all`, `pg` nur auf `aks`, `all` auf `aks` = pg, db,
  k8s, mesh (Lab unverändert); `k8s/postgres-aks/` im Namespace
  `gpos-data`; DSN mit URL-kodiertem Passwort auf `aks`; Guard bei
  install.sh:117 prüft die DB.
- `broker.py`/`broker.sh`: Port-Forward und Identitätsprüfung;
  `broker.sh` schreibt bei `TARGET=aks` vor jedem Aufruf
  `mesh/.rendered/aks/semp.tfvars` aus dem Key Vault (P6 Schritt 6);
  `broker.py` ohne Rückfall auf die Lab-tfvars; Negativtests für fehlendes
  `SEMP_PASSWORD_FROM`/`SEMP_PASSWORD_KEY`, Lab-Pfad, fehlende und
  Lab-`SEMP_URL`.
- e2e mit `AWE_NS`/`AWE_DEPLOY` und `E2E_CA_FILE=system`;
  `uninstall.sh` zielbewusst: auf `aks` wird Namespace `gpos-demo`
  gelöscht, `gpos-data` nur mit `--drop-db` (vorher DB und Rollen über
  den Seam löschen und die aks-db.env entfernen).
- `k8s/base` + `overlays/lab|aks|l3`, Tests für alle Overlays und
  `postgres-aks`, `install.sh` überspringt Kyverno-Wartezeit und
  Lab-CA-Export auf `aks`.
- Kein `GPOS_GRPC_REFLECTION`-Schalter im Standardweg; nur Variante (b)
  aus P6 Schritt 7, falls GEBIT es verlangt. `keycloak-marktleitung.sh`
  aus `spikes/g0` in `scripts/` übernehmen, zielbewusst, ohne `-k`,
  Admin-API über den Port-Forward.
- Makefile-Ziel für die ACR-Kopie (arm64); amd64-Build nur bei AKS-E3 =
  amd64 (`buildx` mit QEMU oder `az acr build --platform linux/amd64`).
- Doku-Drift korrigieren (Abschnitt 8).

## 6. Zeitplan gegen die Gates

KW nach ISO 8601; 2026 hat eine KW53.

| KW | Daten | Arbeit | Gate/Meilenstein |
|---|---|---|---|
| KW47 | 16.-22.11. | P0 (Owner + Claude): Login, Checks, Quota-Antrag, Anfragen an GEBIT und LiteLLM, Commit, Freigaben, Mac-Tools; ab 20.11. RG und Egress-IP | AKS-E1, AKS-E2, AKS-E15 und der Name für AKS-E20 bis 20.11.; O9 bis 20.11. [Quelle: PLAN:208] |
| KW48 | 23.-27.11. | P0 (C ab 23.11.): gpd-Git, Geländer, sam-CLI-Spike, Regressions-Gate; Zone und NS-Übergabe 25.11.; Egress-IP an den Betreiber bis 25.11. | übrige AKS-E bis 27.11. (AKS-E9, AKS-E10, AKS-E19 bis 04.12.); Zone delegiert angestrebt bis 27.11.; Betreiber-Bestätigung 27.11. |
| KW49 | 30.11.-04.12. | P1: Cluster, CLI, WireGuard, LiteLLM-Probe; P2 Beginn (ACR-Spiegel, PriorityClasses, VAP, ingress-nginx) | Zone delegiert spätestens 02.12.; LiteLLM-Probe 03.12. als Frühindikator (AKS-E18); **Prüfpunkt 04.12.** |
| KW50 | 07.-11.12. | P2 Rest, P3 Keycloak, P4 Beginn; Leih-Router ab 11.12. im Lab | gRPC-Teil G0-11b (11.12.); **Prüfpunkt 11.12.** |
| KW51 | 14.-18.12. | P4 Rest, P5 SAM, HITL- und Vision-Test (G0-11a/b nach AKS-E18), Tunnel-RTT; 1 PT Puffer | **G2a 18.12.** |
| KW52-53 | 21.12.-03.01. | Feiertage; Lab-Vorarbeit P6 (Overlays, Seams, `postgres-aks`, ggf. Image 0.1.4); C: AP14 Preflight und Runbook; Cluster gestoppt | - |
| KW1 | 04.-10.01. | P6 auf AKS: pg, db, Image, k8s, mesh, Gate-Verifikation; Router-Peer | GEBIT-Freigabe muss vorliegen |
| KW2 | 11.-15.01. | P6 e2e, TR1 über WireGuard, TR3 (falls im Lab grün), `install.sh all` aus leerem Namespace, Standard-Tier | **G2b 15.01.** |
| KW3 | 18.-22.01. | P7 Drills: Neuaufbau, 24-h-Lauf (Mo 18.01. 12:00 bis Di 19.01. 12:00) mit 10-h-Kiosklauf, N-1, 3 Stop/Start-Zyklen mit je 30 min Pause, Netz, L3; Backups mit Restore-Test; Rollen des Stellvertreters | **G3 22.01.**; Wartungssperre 20.01. |
| KW4 | 25.-31.01. | Node-Image-Refresh Di 26.01.; Runbook, Preflight, Fixes; Probetage 28.01. (Runbook-Durchlauf des Stellvertreters) und 29.01. | Wartungssperre ab 27.01. |
| KW5 | 01.-05.02. | Probetag 3 am 03.02. (Break-glass-Test des Stellvertreters), Zertifikats-Erneuerung 04.02. | **G4 Freeze 05.02.** |
| KW6 | 08.-14.02. | 24/7, Preflight täglich; LE-64-Tage-Wechsel 10.02. ohne Wirkung | Netztest 14.02. |
| KW7 | 15.-21.02. | Messe 16.-18.02.; 19./20.02. Export, Descriptor-Secret löschen, stoppen | Rückbau-Entscheidung |

**O9 als Weiche (Stichtag 20.11.):**

- O9 = (a): Der Kalender oben gilt, C trägt P0 (ab 23.11.) bis P5.
- O9 = (b) oder bis 20.11. nicht entschieden: sofort der Kalender aus
  PLAN 6.2. P1-P5 wandern nach KW52-KW2, die G2a-AKS-Abnahme wandert
  nach G2b [Quelle: PLAN:2561-2564]; P5 liegt dann in KW1, P6 in KW2,
  G2b wird eng. Die Kapazität ist ohnehin knapp: Muss 118,75 PT gegen
  93,6 PT netto [Quelle: PLAN:2487, PLAN:161]; der Plan empfiehlt eine
  dritte Person für AKS ab 23.11. [Quelle: PLAN:208].

**Wochenlast von C (Variante a), gegen 4,3 PT netto je 5-Tage-Woche
und 3,5 PT über die Feiertage [Quelle: PLAN 7.3, PLAN:2749-2770]:**

| KW | AKS-Plan | übrige PLAN-Pakete von C | Summe |
|---|---|---|---|
| 48 | P0-Rest 1,75 | AP04a Container 0,5; AP07b Loyalty-Tools 0,75 (aus KW51 vorgezogen) | 3,0 |
| 49 | P1 2,75; P2 Beginn 0,75 | AP08 `install.sh mesh` 0,75 | 4,25 |
| 50 | P2 Rest 1,75; P3 1,0; P4 Beginn 0,5 | AP04a gRPC-Ingress Lab 0,75 | 4,0 |
| 51 | P4 Rest 0,75; P5 2,5; Puffer 1,0 | - (AP07b vorgezogen, AP14 Runbook nach KW52-1) | 4,25 |
| 52-1 | P6 Lab-Vorarbeit 1,0 | AP14 1; AP13 `hitl_e2e.py` 0,5; AP14 Preflight 0,5 und Runbook 0,5 (aus KW50/51) | 3,5 |

[A] Die Verschiebungen von AP07b, AP04a und AP14 müssen ihre
Abhängigkeiten erlauben; mit dem PLAN-Eigner prüfen. AP07b bleibt für
die TR5-Abnahme an G2a vor dem 18.12. Ohne diese Verschiebung trüge C
in KW50 4,75 PT und in KW51 5,0 PT. Vom Puffer (15 %, rund 3,3 PT)
liegt 1 PT sichtbar vor G2a in KW51; der Rest gehört zu P6/P7: rund
1,25 PT in KW1-2 (G2b) und rund 1,0 PT in KW3 (G3).

**Prüfpunkte statt eines Rückfalls am 18.12.:**

- 04.12.: P1-Abnahme grün.
- 11.12., zusammen mit G1 und dem gRPC-Teil von G0-11b: P2- und
  P3-Abnahme grün.
- Fällt einer aus, wandert die G2a-AKS-Abnahme nach G2b (Mechanik aus
  PLAN:2561-2564, nicht die ganze Variante (b) mit Streichliste) und P5
  nach KW1. Name dieses Rückfalls: "G2a-AKS-Abnahme nach G2b".

## 7. Risiken und Gegenmaßnahmen

| Risiko | Gegenmaßnahme |
|---|---|
| Skript oder Ad-hoc-Befehl wirkt auf das falsche Ziel: kein Skript pinnt einen Kontext; `stop.sh` löscht Release, PVCs, Namespace und räumt Lab-Keycloak und Lab-Broker-Queues ab; ein `kubectl apply -k` ohne Kontext träfe den Lab-Keycloak in `iam` [Quelle: amd scripts/stop.sh:102-115, 161-162, 247-249; Befehl `grep -rnE -- '--context\|KUBECONFIG'`; Befehl `kubectl config current-context` = rancher-desktop, 16.11.] | P0 vor jeder AKS-Credential: eigene kubeconfig-Datei nur über `kaks`/`haks`, `require_kube_context` mit Server-URL, SEMP-Identitätsprüfung, Keycloak-Teardown-Guard, `SAM_HOME` je Ziel, Negativtests, Lint gegen nackte kubectl/helm-Aufrufe, Call-Log- und Render-Diff-Gate |
| Azure ungeprüft: Token ungültig, Quota, SKU, Policy, Rollenrechte unbekannt; Deny-Policies zeigen sich sonst erst beim Create als RequestDisallowedByPolicy | P0 sofort nach Login mit `atScope()`, `--all --include-groups` und effektiven Rechten; Quota-Antrag je 24 vCPU für DPSv6, DPSv5 und DASv6 bis 20.11.; Rückfall D8ps_v5, dann D8as_v6 oder West Europe |
| DNS-Delegation kommt spät | Zone in P0 direkt nach AKS-E4 (25.11.); eigene Demo-Domain, falls die Delegation nicht bis 02.12. steht; keine private CA |
| ingress-nginx ohne Patches (archiviert 24.03.2026, CVE-2026-116472 ohne Fix, getestet bis 1.35) [Quelle: `github.com/kubernetes/ingress-nginx`] | nur internes LB, Snippets aus, VAP gegen `mirror-*`, Risk-Level gesenkt; Traefik-Overlay als 1-PT-Notschalter; Nachfolger nach der Messe; Rückfall k8s 1.35 |
| LiteLLM aus Azure nicht erreichbar oder langsamer (rund +100 ms je Aufruf [A: RA 5.2]) | Egress-IP ab P0 (KW47/48), an den Betreiber bis 25.11., schriftliche Bestätigung 27.11.; Probe aus dem Pod in P1; A4-Vergleich in P6 |
| LiteLLM-Key außerhalb von SAM lesbar: Klartext in `model_configurations` und `gateway_deployments`, Grafana-Grant auf alle Tabellen, pg_dumps, App-User mit Passwort = Username [Quelle: amd scripts/models/README.md:77-79; grant-grafana-platform-db.sh:72; SAM-Chart `_helpers.tpl`:359-397] | AKS-E19: eigenes Superuser-Passwort, NetworkPolicies für Postgres und SeaweedFS; `grafana_ro` nur mit expliziten Tabellen; Dumps ohne die Daten beider Tabellen, Zählprüfung je Dump, verschlüsselt, nach der Messe gelöscht; keine Snapshots |
| GEBIT-Freigabe fehlt; Reflection gibt das Schema heraus | Anfrage in P0 mit Frist 11.12.; P1-P5 und Lab-Vorarbeit unabhängig; Reflection nur intern/WireGuard, Abschaltung nur auf GEBIT-Wunsch (Variante c am Ingress, Variante b als Image 0.1.4); Secret nur zur Laufzeit, nie im Backup |
| Stand-LAN erreicht Admin-Oberflächen (Keycloak-Admin, Grafana, Node-IPs, NodePorts); alle Namen zeigen auf dieselbe LB-IP, MASQUERADE verwischt die Quell-IP | FORWARD-Policy je Peer auf der WG-VM (Router nur 10.20.0.250 tcp/443 und 80); Keycloak-Ingress nur für die Realm-Pfade; Grafana ohne Ingress; Abnahme beim TR1-Besuch über den Router (P6) und beim Netztest 14.02. |
| Router-DNS-Rebind-Schutz verwirft öffentliche Namen mit privater IP (Stand-Router, Heimrouter des Owners) [A] | Test mit Leih-Router ab 11.12.; Rebind-Ausnahme für `<zone>` oder lokale DNS-Overrides; WireGuard-Client mit öffentlichem Resolver |
| Stand-Uplink filtert UDP oder wechselt IP (5G) | Tunnel startet am Stand, dynamische IP egal; WG zusätzlich auf UDP 443 (NSG-Regel und Umleitung auf 51820); Netz-Drill in P7 |
| Hairpin vom Pod auf die interne LB-IP scheitert [A] | Test in P2 gegen `echo.<zone>`; `coredns-custom` mit hosts-Block auf die Ingress-ClusterIP |
| arm64 als System-Pool oder Dpsv6-Kapazität nicht verfügbar [A] | Create in P1 ist der Test; Rückfall-Quota schon beantragt; Rückfall amd64 (+1-1,5 PT, `crane` oder `az acr build`) |
| sam CLI mit zwei Targets schreibt auf die falsche Plattform oder zieht Lab-`.env` | Login je Home unter dem Manifest-Zielnamen `solace-lab`; `SAM_HOME` je Ziel; URL-Guard gegen den Cache; immer `--url` und `--no-dotenv`; nie `--prune`; Spike in P0 |
| LE-Rate-Limits bei Drills; 64-Tage-Wechsel am 10.02.2027 im Freeze | TLS-Backup als volles Secret mit cert-manager-Annotationen, vor Certificates und Ingresses eingespielt; sonst staging-Issuer; `cmctl renew` um den 04.02. |
| Stop/Start: neue API-IP, Kapazität, gwe/awe-Race, Start zu früh nach dem Stop [Quelle: `learn.microsoft.com/azure/aks/start-stop-cluster`] | API-IP-Prüfung `aks-wg-sync.sh` als erster Schritt von `aks-start.sh` plus Voll-Tunnel-Profil `aks-admin-full`; Break-glass `az aks command invoke` oder `az aks update --api-server-authorized-ip-ranges` mit der vollständigen Liste (ersetzt die bestehende, bis 2 min Laufzeit), nicht im Freeze; Start frühestens 30 min nach Stop (Sperre im Wrapper, RUNBOOK); Wartelogik und awe-Neustart; Start 60 min vor Bedarf; ab 05.02. kein Stopp |
| Wartung trotz Sperre (reaktive Wartung kann `notAllowedDates` brechen) [Quelle: `learn.microsoft.com/azure/aks/planned-maintenance`] | Refresh 26.01., Sperre ab 27.01.; PDBs, 2 Ingress-Replikas, N-1 passt (89 %/69 %); L3 warm |
| Datenverlust im Cluster (gebündelte Persistenz, Neuaufbau löscht PVCs, Namespace-Löschung löscht die Demo-DB) | Inhalte per Skript und deterministischem Seed reproduzierbar; Demo-DB im eigenen Namespace `gpos-data`; `pg_dump` vor G3 und nach jedem Messetag vor dem Day-Reset, inklusive gpos-DB; Restore-Test; Export vor jeder Löschung (P7 Schritt 8) |
| Zu knappe Requests (Lab 3-4x unter Ist), Keycloak-OOM, SeaweedFS-Hänger | Requests auf Ist-Werte, Keycloak 1,5Gi, SeaweedFS-Fix committen, Prometheus-PVC |
| Zeitplan: 12,5 PT bis G2a neben TR5/TR3-Laborarbeit, dann Feiertage | Entscheidungen bis 27.11.; O9 als Weiche am 20.11.; Last von C in KW48/49 vorgezogen; Prüfpunkte 04.12. und 11.12. mit Rückfall "G2a-AKS-Abnahme nach G2b" |
| Messebetrieb hängt an Konto und Mac des Owners | AKS-E20: Stellvertreter mit eigenen Rollen, Peer, Keycloak-User und Runbook-Durchlauf bis G3; wird bis G3 niemand benannt: L3 warm, L4 über `/op`, Preflight vor Standöffnung durch den Owner |
| Defender oder andere Subscription-Vorgaben verursachen Kosten oder blockieren Ressourcen | P0 prüft Defender-Pläne und Policies; Kosten bedingt in 3.4; Klärung mit dem Subscription-Owner (AKS-E1) |
| gpd-Umbau ohne Rückweg | Baseline = sda-Commit vor dem Umbau, Commit je Schritt, Rückweg in KW48 geprobt (P0 Schritt 9) |
| Kosten laufen weiter (vergessener Nachtstopp, nach der Messe) | Monatsbudget 450 EUR auf drei RGs mit Forecast bis 31.03.; Abend-Check; Activity-Log-Alarm nur als Information; `deleteAfter`-Tag; datierter Rückbau-Schritt mit Key-Vault-Purge in P7 |

## 8. Abgleich mit dem früheren AKS-Konzept

Bezug: PLAN 5.2/5.3 [Quelle: PLAN:2365-2440], RA vom 10.11.2026
[Quelle: RA:29-71, RA:552-573], DESIGN 4.8 [Quelle: gpd DESIGN.md:794].

### 8.1 Was bleibt

- Germany West Central, Kubernetes 1.36, Azure CNI Overlay mit
  Cilium, ACR ohne Pull-Secret.
- ingress-nginx 1.15.1 selbst installiert, nur internes LB, gleiche
  Annotationen; je gRPC-Host ein Ingress mit h2c-Backend; SSE ohne
  Buffering, LB-Idle-Timeout 30 min.
- Let's Encrypt DNS-01 mit Workload Identity, öffentliche Namen auf
  private IPs.
- PubSub+ 10.25.0.208 per Helm, ClusterIP, Terraform-Module aus emd;
  Lab-Standardpasswörter ersetzt.
- Keycloak 26 im Cluster, gleicher Realm, `*@solace.lab`.
- WireGuard-Gateway-VM (UDP 51820, Rückfall 443 und 5G).
- Stop/Start mit awe-Neustart, Preflight `TARGET=aks`, L3 mit
  exportierten LE-Zertifikaten, Neuaufbau-Drill höchstens 4 h.
- Nie `--prune`; LiteLLM-Key nur in SAM.

### 8.2 Was sich ändert und warum

| Thema | Früher | Jetzt | Warum |
|---|---|---|---|
| Nodes | 2 x D8as_v6 amd64 [Quelle: PLAN:2369] | 2 x D8ps_v6 arm64 | gleiche Digests wie Lab, kein Multi-Arch-Build, -136 EUR/Monat |
| Persistenz | PG Flexible B2ms + Blob [Quelle: PLAN:2375-2376] | alles im Cluster, gebündelt, mit eigenem Superuser-Passwort und NetworkPolicies; Demo-DB im Namespace `gpos-data` | nie getesteter Pfad, +1,5-2 PT, rund +108 EUR/Monat; Plan-Rückfall Nr. 11 [Quelle: PLAN:2545] |
| Tier | Standard ab Start | Free bis G2b, dann Standard | rund 65 EUR/Monat im Aufbau gespart |
| Wartung | außerhalb 12.-20.02., Node-OS `None` [Quelle: PLAN:2369; RA:592] | `notAllowedDates` 20.01. und 27.01.-20.02. auf drei Konfigurationen, manueller Refresh 26.01., SecurityPatch bis zur Sperre | Probetage, G4 und Messe auf einem Image; Nodes nicht drei Monate ungepatcht |
| Struktur | eine RG, Skripte in `gpd/infra/aks` [Quelle: PLAN:2411-2415] | drei RGs (Basis, Cluster, feste Node-RG), BYO-UAMI, versioniert in sli/emd | Neuaufbau behält Zone, ACR, Egress- und WG-IP; Budget-Filter mit festen Namen; Infra-Code versioniert |
| Sicherheitsgeländer | nicht vorgesehen | P0 vor jedem AKS-Kontakt, `kaks`/`haks`, Call-Log-Gate | kein Skript pinnt einen Kontext |
| SAM-Profil | 0,5 PT [Quelle: PLAN:205] | rund 2,5-3 PT | Guards, CLI-Seam, Keycloak-Writeback, TLS-Manifest, Image-Pfad |
| SAM-Broker | `tcp://...:55555` [Quelle: PLAN:2399] | `ws://...:8008`, User `sam` | im Lab getesteter Transport |
| GEBIT-VPN | VPN `sam` [Quelle: PLAN:2334; RA:86,106] | VPN `default` | so implementiert und live [Quelle: gpd UC1-BUILD-SPEC.md:6621; .env.example:9-13] |
| Broker-Disk | 64Gi P6 | 128Gi P10 | P6 hat 240 IOPS, Richtwert 300 |
| MQTT-LB | internes LB für ESP32 | entfällt | ESP32 nur "Soll" [Quelle: PLAN:468] |
| Aliase | `fast`, `workflow` [Quelle: PLAN:204] | `fast`, `planning` | UC1-Stand [Quelle: amd local-k8s-values.yaml:89] |
| Descriptor | ConfigMap [Quelle: PLAN:2426] | Secret, nur zur Laufzeit vom Mac | UC1-Stand, Vertraulichkeit |
| Hostnamen | `grafana.<d>`, `pos-grpc` (RA 4.1) | kein Grafana-Name (Port-Forward); `auth.<zone>` nur Realm-Pfade; `gpos-grpc`, `gpos-wws-grpc`, `gpos-loyalty-grpc` | wie im Lab; Stand erreicht keine Admin-Oberflächen |
| Laufidentität | power_user (RA 1.2) | `marktleitung@solace.lab` | UC1-Stand |
| Gate-Verifikation | - | volle Verifikation je Ziel | Lab-PASS darf AKS nicht überspringen |
| Kyverno, trust-manager | implizit portiert (DESIGN 4.8) | nicht auf AKS; VAP + PriorityClasses | Enforce-Policies lehnen LE ab; Kyverno 3.9.2+ blockiert Stop |
| Gateway API | nur Ausweichweg, "SAM rendert nur Ingress" [Quelle: RA:231-245] | Nachfolger-Spike nach der Messe | SAM mit `ingress.enabled=false` und `frontendServerUrl` rendert https (SAM-Leser) |
| Images SAM | amd64 per `gunzip` + `crane push` [Quelle: PLAN:2370] | arm64 registry-zu-registry | kein Tarball-Load in den k3s-dockerd |
| Topologie | k3s-Cloud-VM (DESIGN 4.8) | AKS | bereits durch PLAN-E8 ersetzt |
| Aufwand | rund 14 PT [Quelle: RA:567]; PLAN: AKS-Anteil von C 21,5 PT plus 2,5 PT Puffer [Quelle: PLAN 7.3] | rund 22 PT (25 mit Puffer) | Geländer, SAM-Profil, Demo-Seams, Drills; Abgleich in 8.4 |
| Kosten | rund 860 EUR/Monat [Quelle: RA:499] | rund 620-640 EUR/Monat (Defender bedingt extra) | arm64, kein PG Flexible |

### 8.3 Korrekturen an Befunden

- Keycloak: aktuell ist 26.8.2 (05.11.2026), nicht 26.7.0 [Quelle:
  GitHub-Releases-API].
- "Läuft auf dem arm64-Lab-Node" belegt nur arm64, nicht multi-arch.
- Plan 2561-2564 erlaubt keine Abnahme "Plattform plus Tunnel",
  sondern verschiebt die G2a-AKS-Abnahme in Variante (b) nach G2b.
- Quota muss den Surge-Node einrechnen (24 statt 16 vCPU).
- SAM-Broker-Passwort heißt `broker.password`, nicht `clientPassword`.
- Der Lab-SAM-Ingress hat keine `proxy-body-size` (NGINX-Default 1m).
- `az aks check-acr` taugt auf einem reinen arm64-Cluster nicht (Prüf-
  Image nur amd64); P1 prüft AcrPull und einen echten arm64-Pull.
- Quota-Anträge werden meist in Minuten automatisch freigegeben; nur bei
  Ablehnung folgt ein Support-Fall mit Tagen.
- Ein Budget nur auf den beiden eigenen RGs sähe die Node-Kosten nicht;
  dafür gibt es die feste Node-RG im Budget-Filter.

### 8.4 Abgleich mit Aufwand, Terminen und Kosten des PLAN

Die AKS-Posten des PLAN gegen die Phasen dieses Plans [Quelle:
PLAN:2480-2483, 2701-2702; PLAN 7.3 (2749-2770)]:

| PLAN-Posten | PT PLAN | Phasen hier | Bemerkung |
|---|---|---|---|
| AP12 S1-S3 (Subscription, Foundation, Add-ons) | 3,5 | P0 Schritt 5, P1, P2 | eine Woche später als PLAN 7.3 (KW49/50 statt KW48): O4 überfällig, `az login` blockiert |
| AP12 S4 Broker, S5 Keycloak | 2,0 | P4, P3 | - |
| AP12 S6 SAM, darin O6 0,5 | 2,0 | P5 | SAM-Profil hier rund 2,5-3 PT |
| AP12 S7-S8 (Overlay, gRPC-Ingresse, Demo) | 2,0 | P6 | plus Seams, `pg`-Teil, Env-Prüfung |
| AP12 S9 WireGuard, Peers, DNS, L3-Kopie | 1,5 | P1 Schritt 7, P6 Schritt 12 | - |
| AP12 S10 Härtung | 1,5 | P7 | - |
| G0-11a, G0-11b | 1,5 | P1 (Probe), P2 Schritt 6, P5 Schritt 7 | Termine nach AKS-E18 |
| AP13 AKS-Anteil (24 h, Neuaufbau) | 2,0 | P7 Schritt 3 | - |
| AP14 Betrieb | 3,5 | P7 Schritte 4-7 | Kanarienlauf, Tagesroutine, Exporte und Freeze-Snapshots bleiben PLAN-Posten |
| AP14b L3 | 2,0 | P7 nur der Drill | Aufbau des L3-Profils (Overlay `l3`, SAM-Values `l3`, Export) bleibt PLAN-Posten |
| neu: Sicherheitsgeländer | - | P0 | 2,5 PT |
| **Summe** | **21,5** (+2,5 Puffer) | **22,0** (+rund 3,3 Puffer) | |

- Mit gebündelter Persistenz (Streichliste Nr. 11, 1,5 PT [Quelle:
  PLAN 6.2]) sinkt die PLAN-Basis auf 20,0 PT.
- P0-P7 decken die AP14- und AP14b-Teile aus der Tabelle nicht ab
  [A: rund 3 PT]. Vergleichbar sind damit rund 25 PT gegen 21,5 PT
  (Delta rund +3,5 PT) bzw. gegen 20,0 PT (rund +5 PT). Echte
  Neuposten: Geländer (2,5 PT) und SAM-Profil (+2-2,5 PT gegen 0,5 PT
  O6).
- Variante (a): C hat 32,25 von 39,9 PT netto verplant [Quelle:
  PLAN:163-167]; frei sind 7,65 PT. Das Delta passt hinein, verbraucht
  aber den Großteil. Variante (b): Es vergrößert die Lücke von 6,4 bzw.
  7,9 PT [Quelle: PLAN:168-174]. Das Muss von 118,75 PT steigt um das
  Delta, sofern der Owner die Geländer nicht als Teil von AP12 verbucht.
- Termine: G0-11a und G0-11b nach AKS-E18; die Abhängigkeit "AP12
  S6-S10 nach G0-11a" [Quelle: PLAN:2480, 2515] wird phasengerecht
  umgeschrieben; P0 in KW47 tragen Owner und Claude, bevor C am 23.11.
  beginnt; AP12 S1-S3 rutschen eine Woche (O4 überfällig).
- Kosten: Die Projektsumme in PLAN 0.4 sinkt von 2,0-3,0 Tsd. EUR auf
  rund 0,9-1,2 Tsd. EUR (mit Defender bis rund 1,35 Tsd. EUR), Budget
  1.500 EUR (AKS-E1). Gründe: arm64, gebündelte Persistenz, Free-Tier
  bis G2b, Nachtstopp, Cluster erst ab 30.11. Das braucht keine eigene
  Entscheidung.
- Nach Freigabe im PLAN nachziehen: 0.3, 0.4, 0.5 (O6 mit 0,5 PT,
  AKS-E1 bis AKS-E20), 6 (AP12-Zeile: "SAM extern", PT), 6.1
  (kritischer Pfad), 6.4, 7.1 (G0-11a/b), 7.2 und 7.3.

## 9. Offene Fragen

1. Welche Subscription und Kostenstelle; darf der Owner Rollen
   zuweisen (`--attach-acr`, AKS-RBAC, DNS Zone Contributor, Key Vault
   Secrets Officer) und ein Budget mit Filter anlegen? Gibt es
   Policies gegen Public IPs, Tags-Pflicht, aktive Defender-Pläne und
   eine kurze Conditional-Access-Anmeldehäufigkeit?
2. Welche Domain, wer delegiert, bis wann (spätestens 02.12.)?
3. Gibt es eine dritte Person für den AKS-Track (O9), oder läuft er
   neben TR5/TR3? Wer sind Betreiber und Stellvertreter an Probetagen
   und Messe (AKS-E20)?
4. Hat der LiteLLM-Proxy eine Quell-IP-Allowlist (auch für `/v1/*`),
   wie lange dauert eine Freischaltung, und kommt ein separater
   Messe-Key (O5)?
5. Was sagt GEBIT zum Descriptor-Set in Azure, zum Zugriff des
   Stellvertreters, zu Reflection über die internen gRPC-Ingresses und
   zu den Netzparametern (Uplink, UDP 51820/443, Router-Modell,
   DNS-Rebind)?
6. Bestätigt der sam-CLI-Spike (P0 Schritt 12) die Fragen (a) bis (d)?
7. Broker `prod1k` oder `dev`? Die Verbindungszahl der Demo (rund 11)
   spricht für `dev`, Lab-Parität für `prod1k`.
8. `GPOS_DELIVERY=persistent` auf AKS testen (kein DMR-Rückstau dort)
   oder bei `direct` bleiben?
9. Wird die neue Preiszeile "FreeTierInfrastructureCost" abgerechnet,
   und laufen LB-Regeln und Standard-Tier im Stopp weiter?
10. L3 (AP14b) behalten? Streichliste Nr. 4 würde 3 PT sparen
    [Quelle: PLAN:2532], nimmt aber den Notbetrieb.
11. Nach der Messe: Rückbau (mit Key-Vault-Purge) oder GEBIT-Übergabe
    (dann amd64-Pool und Multi-Arch-Build)?
12. Nachfolger für ingress-nginx in Lab und AKS nach der Messe:
    Gateway API (`approuting-istio`) oder Traefik?
13. Lab-Versionen pinnen (Charts in sli, Broker-Image in emd)?
14. Gilt `pos.receipt.receipt_b64` (Demo-Belege im Format der
    GEBIT-Receipt-API) als GEBIT-Material, das nicht in Backups darf?
