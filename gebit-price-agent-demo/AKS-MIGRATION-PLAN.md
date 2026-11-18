# AKS-Migrationsplan: EuroCIS-Showcase vom Lab nach Azure

Stand 18.11.2026, überarbeitet nach der Azure-Prüfung und der
Owner-Entscheidung vom 18.11.2026 (Abschnitt 2; die
Owner-Entscheidungen vom 17.11. gelten weiter). Die Fassung vom 17.11.
liegt im sda-Commit 9f66efd, die vom 16.11. in 7a860c5. Was sich am
18.11. geändert hat, fasst 8.6 zusammen. Vorschlag für den Owner,
read-only erarbeitet: Für diese Fassung wurde in Azure und im Lab nichts
angelegt, geändert oder gelöscht; die Ressourcengruppe
`gebit-showcase` hat der Owner selbst angelegt. Messe: EuroCIS 2027,
16.-18.02.2027. Gates: G2a 18.12.2026, G2b 15.01.2027, G3 22.01.2027,
Freeze G4 05.02.2027 [Quelle: PLAN 0.3].

Lesehinweis:

- Abkürzungen für Quellen: `sda` = Repo solace-demo-artifacts, `sli` =
  Repo solace-lab-infrastructure, `amd` = sda/agent-mesh-deployment,
  `emd` = sda/event-mesh-deployment, `gpd` =
  sda/gebit-price-agent-demo, `PLAN` = gpd/IMPLEMENTATION-PLAN.md
  (zitiert nach Abschnitt, weil der PLAN parallel nachgezogen wird),
  `RA` = gpd/research/impl/research-aks.md.
- "Befehl (16.11.)", "Befehl (17.11.)" bzw. "Befehl (18.11.)" heißt:
  read-only im Lab oder gegen öffentliche APIs ausgeführt, am genannten
  Tag 2026. Am 18.11. kam ein read-only Azure-Check in der Subscription
  `azure-se` dazu (Azure CLI 2.85.0, nach dem `az login` des Owners).
- [A] markiert eine Annahme, die noch zu prüfen ist.
- Preise: Listenpreise Pay-as-you-go, EUR ohne MwSt., Germany West
  Central, 730 h/Monat [Quelle: `prices.azure.com/api/retail/prices`,
  16.11., am 17.11. und 18.11. neu geprüft].
- Platzhalter: `<p>` (neutrales DNS-Label-Präfix ohne Kunden- oder
  Projektnamen), `<fqdn>` =
  `<p>.germanywestcentral.cloudapp.azure.com`, `<acr>`, `<kv>`,
  `<owner-ip>`, `<owner-upn>` und `<deputy-upn>` (Subjekte der
  ClusterRoleBindings), `<owner-objectId>` und `<deputy-objectId>`
  (Key-Vault-Access-Policies), `<owner-name>` und `<dd.mm.yyyy>`
  (Werte der Pflicht-Tags `Owner` und `Created Date`), `<subscription>`
  (nur die ID) und `<tenant>`. Die Werte stehen nur lokal, nie in
  diesem Dokument. Ausgeschrieben stehen dürfen die Subscription
  `azure-se`, die Ressourcengruppe `gebit-showcase` und die
  Node-Ressourcengruppe `gebit-showcase-nodes`.
- Entscheidungen dieses Plans heißen `AKS-E1` bis `AKS-E21`, damit sie
  nicht mit den PLAN-Entscheidungen (PLAN-E1 bis PLAN-E8) und den
  Owner-Punkten O1-O9 kollidieren. Ihr Status steht in Abschnitt 2.
- `kaks` und `haks` sind die einzigen Ad-hoc-Wege zu AKS für kubectl
  und helm (Definition in P1 Schritt 6). Lab-Befehle tragen
  `--context rancher-desktop`.
- Keine Secrets, IDs (Objekt-, Subscription-, Tenant-IDs), UPNs,
  Personennamen, E-Mail-Adressen (außer Lab-Demo-Identitäten wie
  `marktleitung@solace.lab`) oder LLM-Hostnamen in diesem Dokument.
  Das GEBIT-Material heißt hier nur "GEBIT-Descriptor-Set"; den
  vollqualifizierten Namen des Purchase-Service nennt der Plan nicht
  ("Purchase-Service-FQN").

## 0. Kurzfassung

- **Festlegung (Owner, 17.11. und 18.11.):** Ein AKS-Cluster
  (Kubernetes 1.36, Germany West Central, 1 x `Standard_D8ps_v6`,
  arm64, Free-Tier, kein HA) in der Subscription `azure-se`,
  Ressourcengruppe `gebit-showcase`, baut den Lab-Stack mit denselben
  Charts, Versionen, Namen und Image-Digests nach ("Parität zuerst").
  SAM bleibt gebündelt (Postgres + SeaweedFS), Keycloak, Broker und
  Demo-DB laufen im Cluster. Bewusst anders als im Lab: Traefik statt
  ingress-nginx, ein Hostname mit Pfad-Routing, Keycloak unter `/auth`.
- **Nur Contributor, keine Rollenzuweisungen (Owner, 18.11.,
  AKS-E21):** Der Owner ist über eine Gruppe Contributor auf
  `azure-se`, nicht Owner und nicht User Access Administrator.
  Rollenzuweisungen, Locks und Policy-Ausnahmen kommen im Plan nicht
  mehr vor. Folgen: AKS-verwaltetes VNet in der Node-RG statt
  BYO-Subnetz (Azure CNI Overlay mit Cilium bleibt), System-Identität
  statt `id-aks-cp`, ACR-Pull über ein Pull-only-Token mit dem Secret
  `acr-pull` je Namespace statt `--attach-acr`, Entra ID mit
  Kubernetes-RBAC statt Azure RBAC (Bootstrap per Admin-Zugang, dann
  lokale Accounts aus und Zertifikate rotieren, oder eine eigene
  Admin-Gruppe, AKS-E13), Key Vault im Access-Policy-Modus,
  `pip-aks-ingress` ohne Lock in der Node-RG, AKS-verwaltete
  Egress-IP. Der Preis: Kubernetes-RBAC und Access Policies sind keine
  Grenze gegen die anderen Contributors von `azure-se`, und Label und
  IPs leben nur so lange wie der Cluster (2.2).
- **Azure-Lage geprüft (18.11., read-only):** Eine Deny-Policy
  verlangt die Tags `Owner` und `Created Date` auf jeder
  Ressourcengruppe; `az aks create` gibt sie deshalb für die Node-RG
  `gebit-showcase-nodes` mit (AKS-E1). Die Quota reicht ohne Antrag
  (DPSv6 0 von 350 vCPU belegt, regional 150 frei bei einem Bedarf von
  16), `Standard_D8ps_v6` hat keine Restriction, AKS 1.36.5 ist
  verfügbar, Defender kostet nichts (alle relevanten Pläne Free). Vor
  P1 offen: Azure CLI 2.85.0 auf 2.93 oder neuer heben und kubelogin
  installieren (freigegeben, AKS-E15 (e)).
- **Öffentlich für alle, ohne WireGuard:** Ein Azure-Name `<fqdn>` auf
  der statischen IP `pip-aks-ingress` (nur 80/443), die direkt nach dem
  Create in `gebit-showcase-nodes` entsteht; ausgehend nutzt der
  Cluster die AKS-verwaltete Egress-IP (Adresse erst nach dem Create
  bekannt, neu bei jedem Neuaufbau). SAM bekommt `/`, Keycloak
  `/auth/...`, Kasse und Monitor ihre Pfade (`/kasse`, `/monitor`,
  unverändert und ohne Login), die drei gRPC-Server ihre Service-Pfade
  (Reflection an, Route erst nach der GEBIT-Bestätigung aus AKS-E16).
  Weitere BFF-Seiten mit Schreib- oder LLM-Wirkung (`/freigabe`,
  `/foto`, `/op`) und `/etikett` bekommen erst nach Owner-Entscheidung
  einen öffentlichen Pfad (Frage 23). Den API-Server erreichen nur
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
  ACR (Pull per Token), eingebauter ValidatingAdmissionPolicy und
  Traefik v3.7.19 mit NGINX-Provider. Das Lab behält ingress-nginx;
  dieselben NGINX-Ingress-Manifeste laufen auf beiden Zielen.
- **Zuerst Sicherheitsgeländer:** Kein Skript pinnt heute einen
  kube-Kontext. Ein Lab-`stop.sh` gegen AKS würde dort SAM löschen und
  zugleich Lab-Keycloak-Client und Lab-Broker-Queues abräumen. Deshalb
  laufen alle AKS-Aufrufe nur über `kaks`/`haks` oder Skript-Wrapper
  mit `require_kube_context`, und ein Call-Log-Gate belegt, dass die
  Lab-Aufrufe gleich bleiben.
- **LiteLLM-Key geschützt:** SAM speichert ihn im Klartext in der
  Plattform-DB. Auf AKS gibt es deshalb ein eigenes
  SAM-Postgres-Passwort, NetworkPolicies, `grafana_ro` ohne die
  Key-Tabellen und Backups ohne deren Daten (AKS-E19, 1.4), dazu
  rpm/tpm-Limits am Messe-Key gegen anonyme Dauerschleifen (AKS-E11).
  Gegen ein Mitglied der Contributor-Gruppe, das sich Cluster-Admin
  verschafft, hilft das nicht (AKS-E21, 2.2).
- **Broker 10.26.0.9219 (LTS) in Lab und AKS:** Neuer Arbeitsposten
  Lab-Upgrade von 10.25.0.208, Risiko mittel bis hoch, weil beide
  Broker-DBs im Container-Layer liegen und `start.sh` sie neu erzeugen
  und leeren würde. Eigenes Owner-Go und Wartungsfenster; fertig und
  mit SAM- und GEBIT-Flows im Lab bewiesen vor P4 Teil B (AKS) und P5
  (AKS-E8). `start.sh`, `stop.sh` und `docker compose up/pull/down`
  sind in emd tabu, bis die emd-Skripte an die externen Volumes
  angepasst sind (1.4).
- **Phasen:** P0 Klärungen und Geländer (bis 27.11.; die Azure-Checks
  sind seit 18.11. erledigt), P1 Azure nur mit Contributor: Cluster,
  Zugriff mit Kubernetes-RBAC, ACR-Token, Key Vault, CLI, öffentlicher
  Zugang (KW49), P2 Add-ons mit Traefik und TLS (KW49-50), P3 Keycloak
  unter `/auth` (KW50), P4 Broker (Lab KW48-49, AKS KW51), P5 SAM
  (KW51, G2a 18.12.), P6 Demo mit Pfad-Ingresses, `public-guard` und
  Image 0.1.4 (G2b 15.01.), P7 Härtung und Betrieb (G3 22.01., G4
  05.02.). Summe 23,5 PT (mit Puffer rund 27,0), bis G2a 13,5 PT (Aufteilung
  und Puffer in Abschnitt 4). Prüfpunkte am 04.12. und 11.12.
  entscheiden früh, ob der AKS-Teil von G2a nach G2b wandert.
- **Kosten:** rund 300-340 EUR/Monat bei 24/7 (1 Node, Free-Tier,
  2 Public IPs, kein WireGuard), rund 145-185 EUR/Monat im Aufbau
  mit Nacht- und Wochenend-Stopp; Projektsumme bis 20.02.2027 rund
  460-590 EUR ohne LLM-Token, Ziel unter 1.500 EUR (3.4).
  Defender-Kosten entfallen (alle relevanten Pläne Free, 18.11.). Ein
  Monatsbudget-Alarm auf Subscription-Ebene, gefiltert auf
  `gebit-showcase` und `gebit-showcase-nodes`, bleibt, skaliert auf
  250 EUR statt 450 EUR [A] (AKS-E1).
- **Bewusst akzeptiert (2.2):** gpos teilt den Origin mit SAM; das
  AKS-Routing weicht vom Lab ab; SAM ruft sich über `<fqdn>` selbst
  auf (Hairpin-Test in P1); anonyme Schreib-RPCs; ein Node ohne HA.
  Seit 18.11. als Folge von AKS-E21: Label, Ingress- und Egress-IP
  verschwinden mit dem Cluster, und jedes Mitglied der
  Contributor-Gruppe kann sich Zugang zu Cluster und Key Vault
  verschaffen [A: ausdrückliche Bestätigung des Owners offen].
- **Noch offen:** AKS-E18 (G0-11a/b nach G2a) und AKS-E20 (Betreiber
  und Stellvertreter, neu: dessen Azure-Zugang über eine
  Contributor-Gruppe, bis 27.11.) warten auf den Owner, ebenso die
  Exposition von `/freigabe`, `/foto`, `/op` und `/etikett` (AKS-E5,
  Frage 23, vor G2b). Offen mit harter Vorbedingung: die schriftliche
  Bestätigung, dass die GEBIT-Freigabe das Descriptor-Set als Secret in
  Azure, die öffentliche Reflection und den Zugriffskreis aus AKS-E21
  abdeckt (AKS-E16; vor dem ersten GEBIT-Secret in Azure, spätestens
  09.12.). Owner-Wahl bis 27.11.: Label-Scope `SubscriptionReuse`
  (AKS-E4), Bootstrap mit Zertifikatsrotation oder eigener
  Admin-Gruppe (AKS-E13), Ablauf und Scope-Map des ACR-Tokens
  (AKS-E21); NRG-Lockdown als Lock-Ersatz erst
  nach dem LB-Nachweis in P2 (P2 Schritt 10).
  [A]-Bestätigungen: der API-Server-Weg (AKS-E5), die Budgethöhe
  (AKS-E1), AKS-E9 und AKS-E12. Zu belegen in P1: der
  1-Node-Systempool (AKS-E3), die Node-RG mit Pflicht-Tags trotz
  Deny-Policy (AKS-E1), Ingress- und Egress-IP über Stop/Start
  (AKS-E4, AKS-E11). Dazu Betreiber-Antwort und Key-Limits bis 27.11.
  (AKS-E11), Go und Fenster für das Lab-Broker-Upgrade (AKS-E8), das
  Label-Präfix `<p>` (AKS-E4), das Konto beim Rückfall-ACME-CA (Owner,
  bis 04.12.) und der Schutz des Approver-Logins (P3).

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
(AKS-E10), ein Node ohne HA (AKS-E3). Auf Azure-Seite kommt der Plan
ohne Rollenzuweisungen und Locks aus (AKS-E21).

### 1.2 Was nach AKS geht

| Baustein | Lab heute | AKS | Quelle |
|---|---|---|---|
| Ingress | ingress-nginx 4.15.1 (Controller 1.15.1), Port-Forward auf den Mac | Traefik v3.7.19 (Chart 42.4.1, per Digest) mit NGINX-Provider, 1 Replika, genau ein öffentlicher LoadBalancer-Service auf `pip-aks-ingress` (80/443, `externalTrafficPolicy: Local`); das Lab bleibt bei ingress-nginx | Befehl `helm list -A` (16.11.); sli ingress/scripts/setup.sh:47-49; `api.github.com/repos/traefik/traefik/releases` (17.11.) |
| Hostnamen | ein Host je App unter `solace.lab` (sam, auth, gpos, drei gRPC-Hosts, monitoring) | ein Azure-Name `<fqdn>` mit Pfad-Routing auf 443 (2.1); Grafana ohne Namen | Befehl `kubectl --context rancher-desktop get ingress -A` (17.11.); `learn.microsoft.com/azure/virtual-network/ip-services/public-ip-addresses` |
| TLS | private Root/Intermediate-CA, nur `solace.lab`, cert-manager v1.20.2 | Let's Encrypt HTTP-01 über cert-manager v1.21.3, ein Zertifikat für `<fqdn>` als Traefik-Default (`TLSStore`); Rückfall-Issuer einer ACME-CA mit EAB | sli pki/manifests/02-pki-ca-hierarchy.yaml:126-131; `letsencrypt.org/docs/rate-limits` |
| Monitoring | kube-prometheus-stack 83.5.0, Loki 6.55.0, Tempo 2.0.0, Alloy 1.11.0 | gleiche Versionen, Prometheus auf PVC statt emptyDir, Images aus ACR, Grafana ohne Ingress (Port-Forward) | Befehl `helm list -A` (16.11.); sli pki/manifests/05-monitoring-values.yaml:48-70 |
| Identity | Keycloak 26.2 (Floating-Tag) + Postgres 17, Realm `solace-lab`, eigener Host | Keycloak 26.8.2 gepinnt unter `/auth`, gleicher Realm, `*@solace.lab` unverändert | sli keycloak/manifests/03-keycloak.yaml:141; `api.github.com/repos/keycloak/keycloak/releases`; `www.keycloak.org/server/hostname` |
| Cluster-Zugriff | kubeconfig von Rancher Desktop (Kontext `rancher-desktop`) | Entra ID mit Kubernetes-RBAC (ClusterRoleBindings), kubelogin, eigene kubeconfig `~/.kube/aks-eurocis.yaml` nur über `kaks`/`haks`; lokale Accounts nach dem Bootstrap aus (AKS-E13) | `learn.microsoft.com/azure/aks/kubernetes-rbac-entra-id`; `learn.microsoft.com/azure/aks/manage-local-accounts-managed-azure-ad` |
| SAM | 2.542.1, Chart 2.3.10, str 1.80.2, ns `sam-solace-lab`, gebündelt | identisch, zweites Values-Overlay; `sam.dnsName` = `<fqdn>`, SAM besitzt `/` | amd local-k8s-values.yaml:156-160; SAM-Chart 2.3.10 templates/_config_helpers.tpl:10-108 |
| Broker | `solace-1` 10.25.0.208 in Docker, VPN `sam` + `default`; Upgrade auf 10.26.0.9219 geplant (AKS-E8) | ein PubSub+ Standard 10.26.0.9219 (LTS) per Helm, ClusterIP, kein DMR | Befehl SEMP monitor (16.11.); emd docker-compose.yaml:27-57; Docker-Hub-Tags-API (17.11.) |
| GEBIT-Demo | ns `gpos-demo`, 6 Deployments, Image 0.1.3 arm64 | gleiches Image in ACR, in P6 Image 0.1.4 (gebündelter Reflection-Endpunkt); kustomize-Overlay `aks` mit Pfad-Ingresses | Befehl `kubectl -n gpos-demo get deploy` (16.11.) |
| Demo-DB | Host-Docker `postgres` 18.3, DB `gpos` 25 MB | Postgres-18-StatefulSet im eigenen Namespace `gpos-data`, neu aus dem Seed | Befehl `docker exec postgres psql` (read-only, 16.11.) |
| SAM-Paket | `gpos-uc1`: 5 Connectoren, 3 Agents, 3 Workflows, RBAC, 2 Entrypoints | inhaltlich unverändert; Haupt-Manifeste unverändert angewendet, nur die Entrypoints je Ziel gerendert | gpd mesh/manifest.yaml:11-15 |
| Neu | - | ACR Basic mit Pull-only-Token (Secret `acr-pull` je Namespace), Key Vault im Access-Policy-Modus, `pip-aks-ingress` (statisch, DNS-Label) und die AKS-verwaltete Egress-IP in der Node-RG; zwei Ressourcengruppen: `gebit-showcase` (vom Owner angelegt, Metadaten in West Europe; Cluster, ACR und Key Vault in Germany West Central) und `gebit-showcase-nodes` (legt AKS beim Create an: VM, Disks, LB, VNet, beide IPs) | Befehl (18.11.) `az group show`; `learn.microsoft.com/azure/aks/faq` |

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
  AKS-kubeconfig liegt nie in `~/.kube/config`. Die Admin-kubeconfig
  entsteht bei jedem Bootstrap- und Break-glass-Lauf nur in einem per
  `trap` gelöschten Temp-Verzeichnis (umask 077), nie unter `~/.kube`;
  danach sind die lokalen Accounts aus (AKS-E13, P1 Schritt 6).
- Keine Rollenzuweisungen, Locks oder Policy-Ausnahmen (AKS-E21).
  Tabu sind damit auch Flags, die eine Zuweisung auslösen oder
  voraussetzen: `--attach-acr` (die CLI scheitert nach dem Create mit
  einem Fehler, der Cluster bleibt ohne AcrPull), `--vnet-subnet-id`,
  auch zusammen mit `--assign-identity` (nur eine Warnung, der Cluster
  bleibt ohne Subnetzrechte), `--enable-azure-rbac`, eine
  BYO-Kubelet-Identität und AKS Automatic [Quelle: azure-cli dev
  acs/_roleassignments.py:101-140,
  acs/managed_cluster_decorator.py, Stand 18.11.;
  `learn.microsoft.com/azure/aks/cluster-container-registry-integration`].
- Regionale Ressourcen bekommen `-l germanywestcentral`, also `az aks
  create`, `az acr create`, `az keyvault create` und `az network
  public-ip create`: Die Ressourcengruppe `gebit-showcase` liegt in
  West Europe, ohne `-l` landeten ACR und Key Vault dort. Ohne Region
  bleiben die globalen Activity-Log- und Resource-Health-Alarme (`az
  monitor activity-log alert create` kennt kein `-l`), die Action
  Group mit `-l Global` (ohne Angabe nähme sie die Region der RG) und
  das Budget per `az rest`; auch `az acr token create` kennt kein
  `-l`. Alarme und Action Group liegen in `gebit-showcase`, nie in der
  Node-RG [Quelle: `az monitor activity-log alert create --help`, `az
  monitor action-group create --help`, `az acr token create --help`,
  2.85.0].
- Nie `az group delete -n gebit-showcase`: Die Ressourcengruppe gehört dem Owner
  und trägt ACR und Key Vault. Den Cluster entfernt nur `az aks delete`, und das
  nur über `sli/aks/aks-rebuild.sh` (P7); es nimmt `gebit-showcase-nodes` samt
  beider IPs mit. In der Node-RG liegt außer den AKS-Ressourcen nur
  `pip-aks-ingress`, weil Learn sie nur für Ressourcen mit dem Lebenszyklus des
  Clusters vorsieht [Quelle: `learn.microsoft.com/azure/aks/faq`].
- `az aks create` und jedes `az aks update --tags` nur mit allen vier
  Tags (`Owner`, `Created Date`, `purpose`, `deleteAfter`): `--tags`
  ersetzt das ganze Set auf Cluster, zugehörigen Ressourcen und
  Node-RG, und ohne die Pflicht-Tags lehnt die Deny-Policy die Node-RG
  ab [Quelle: `learn.microsoft.com/azure/aks/use-tags`].
- Das Passwort des ACR-Tokens erscheint nie in argv oder Ausgabe; es
  liegt nur im Key Vault (`acr-pull-token`) und in `sli/aks/.env.aks`
  (chmod 600, P1 Schritt 3).
- `set -x`-Mitschnitte gehen nur per `BASH_XTRACEFD` nach
  `~/.config/eurocis-aks/xtrace/` (chmod 700), nie in ein Repo. In
  `sli/aks/*.sh` und gpd `install.sh` laufen Zuweisungen und Aufrufe
  mit Secret, objectId, UPN, Tag-Wert oder IP ohne xtrace, also
  zwischen `{ set +x; } 2>/dev/null` und `set -x`: das Laden von
  `.env.aks`, `aks_tags` samt `az aks create --tags`, `OWNER_OID`,
  `kaks auth whoami`, die IP-Abfragen und `db_password`. P1 und P6
  prüfen die Mitschnitte per Zählabfrage.
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
PLAN-E8. Die Owner-Entscheidungen vom 17.11. und 18.11.2026 sind
bindend; die Empfehlungen vom 16.11. stehen im sda-Commit 7a860c5, die
Fassung vom 17.11. im sda-Commit 9f66efd.

Status:

- **entschieden 17.11.:** Owner-Entscheidung vom 17.11.2026.
- **entschieden 18.11.:** Owner-Entscheidung vom 18.11.2026 (nur
  Contributor, AKS-E21). "Geändert 18.11." heißt: eine Zeile vom 17.11.
  folgt dieser Entscheidung; "ergänzt 18.11." heißt: sie nimmt die
  Prüfung vom 18.11. auf.
- **[A] Bestätigung offen:** Annahme oder Default der Planung; gilt,
  bis der Owner abweicht.
- **Owner-Bestätigung offen:** vom Owner noch nicht beantwortet; die
  Empfehlung ist bis zur Frist die Arbeitsgrundlage.
- **offen:** noch zu klären oder freizugeben.

**Prüfung 18.11.2026** (read-only nach dem `az login` des Owners,
Azure CLI 2.85.0) [Quelle: Befehl (18.11.): Konto, Rollen inklusive
Gruppen, Ressourcengruppe, Policy-Zuweisungen, Provider, Usages,
Compute-SKU-API, AKS-Versionen, Defender-Pläne]:

- **Subscription und Rechte:** `azure-se` ist die einzige Subscription
  (Enabled, Default). Der Owner hat über eine Gruppe Contributor auf
  Subscription-Ebene, dazu "Azure Service Bus Data Sender"; er ist
  nicht Owner und nicht User Access Administrator. Contributor hat die
  NotActions `Microsoft.Authorization/*/Write` und `.../Delete`, also
  keine Rollenzuweisungen, keine Locks und keine Policy-Ausnahmen. Er
  hat aber `listClusterAdminCredential`, `listClusterUserCredential`,
  `runCommand`, `managedClusters/write`, `rotateClusterCertificates`,
  `vaults/accessPolicies/write`, `registries/tokens/write` und darf
  eigene Budgets anlegen [Quelle:
  `learn.microsoft.com/azure/role-based-access-control/built-in-roles/privileged`;
  `learn.microsoft.com/azure/azure-resource-manager/management/lock-resources`;
  `learn.microsoft.com/azure/cost-management-billing/costs/tutorial-acm-create-budgets`].
- **Ressourcengruppe:** Der Owner hat `gebit-showcase` in West Europe
  angelegt, mit den Tags `Owner` und `Created Date` (Format
  dd.mm.yyyy). Ressourcen darin dürfen in Germany West Central liegen;
  die Metadaten der RG bleiben in West Europe [Quelle:
  `learn.microsoft.com/azure/azure-resource-manager/management/overview`].
- **Policies:** 2 x "Require a tag on resource groups" (deny, Tags
  `Owner` und `Created Date`), 2 x "Inherit a tag from the resource
  group" (modify, dieselben Tags), "ASC Default" (audit). Die
  Deny-Policy prüft nur, ob der Tag da ist, nicht Wert oder Format;
  die Inherit-Policy überschreibt beide Tags an jeder Ressource mit dem
  Wert ihrer RG [Quelle: `github.com/Azure/azure-policy`
  built-in-policies/policyDefinitions/Tags, Stand 18.11.; A: dass die
  Zuweisungen genau diese Built-ins nutzen]. AKS legt seine Node-RG
  selbst an; `az aks create --tags` gilt für Cluster, zugehörige
  Ressourcen und Node-RG [Quelle:
  `learn.microsoft.com/azure/aks/use-tags`]. Ohne die beiden Tags
  verweigert die Policy den Create.
- **Provider:** ContainerService, ContainerRegistry, KeyVault, Network,
  Compute, ManagedIdentity, OperationsManagement, Insights und Security
  sind registriert; Microsoft.Quota nicht, es wird nicht gebraucht.
- **Quota Germany West Central:** DPSv6 0 von 350 vCPU, DPSv5 0 von
  350, Total Regional 200 von 350 (150 frei; Bedarf 16 mit
  Surge-Node), Public IPs 7 von 1000, Standard-LBs 0 von 1000. Kein
  Antrag; Re-Check vor dem Create und vor dem Refresh am 26.01., weil
  die Subscription geteilt ist.
- **SKUs:** `Standard_D8ps_v6` (Arm64) in den Zonen 1-3 ohne
  Restriction, ohne Ephemeral-OS-Disk; `Standard_D8ps_v5` und
  `Standard_D8as_v6` ebenfalls ohne Restriction.
- **AKS-Versionen:** 1.36 (Default, Patch 1.36.5), 1.37 (1.37.1),
  1.35 (1.35.9).
- **Defender for Cloud:** alle Pläne Free (unter anderem Containers,
  KubernetesService, ContainerRegistry, KeyVaults, VirtualMachines),
  Standard nur Discovery und FoundationalCspm, ohne Kostenwirkung hier.
  Defender-Kosten 0 EUR, kein Sensor auf dem Node zu erwarten [A:
  Re-Check vor G4].
- **Mac:** Azure CLI weiter 2.85.0, kubelogin fehlt; beides ist
  freigegeben (AKS-E15 (e)), aber noch nicht installiert.

| Nr | Entscheidung | Status | Festlegung bzw. Empfehlung | Alternativen | Bis wann |
|---|---|---|---|---|---|
| AKS-E1 | Subscription, Ressourcengruppen, Kostenstelle, Quota, Budget (Plan-Punkt O4 [Quelle: PLAN 0.5]) | entschieden 17.11., ergänzt 18.11.; Budgethöhe [A] Bestätigung offen; Werte der Pflicht-Tags und Zahl der RGs entschieden 18.11.; Kostenstelle offen [A] | Subscription `azure-se` (Prüfung 18.11.). Owner-Vorgabe 18.11.: so wenige Ressourcengruppen wie möglich, also genau zwei; mehr legt der Plan nicht an. Ressourcengruppe `gebit-showcase` (vom Owner angelegt, West Europe) für den Cluster `aks-eurocis`, ACR und Key Vault, alle mit `-l germanywestcentral` (AKS-E2). Die Node-RG `gebit-showcase-nodes` legt AKS beim Create an (`--node-resource-group`; nur beim Create setzbar, die RG darf vorher nicht existieren und ist später nicht umbenennbar [Quelle: `learn.microsoft.com/azure/aks/faq`]), mit `--tags Owner=<owner-name> "Created Date=<dd.mm.yyyy>" purpose=eurocis2027 deleteAfter=2027-02-28`; ohne die beiden Pflicht-Tags verweigert die Deny-Policy sie [Quelle: `learn.microsoft.com/azure/aks/use-tags`]. `Owner` ist immer der Owner selbst (Owner-Vorgabe 18.11.); der Wert kommt aus dem Tag von `gebit-showcase` bzw. aus `OWNER_TAG` in der nicht versionierten `.env.aks` und steht nie im Repo. `Owner` und `Created Date` tragen die Werte von `gebit-showcase`, weil die Inherit-Policy abweichende Werte am Cluster überschreibt und Cluster und Node-RG sonst auseinanderlaufen [A]; der Tag-Name `Owner` ist für neue Cluster nicht mehr reserviert [Quelle: faq]. Nach dem Create `az group show -n gebit-showcase-nodes --query "keys(tags)" -o tsv` prüfen (nur Schlüssel, Werte per stillem Vergleich gegen `gebit-showcase`, P1 Schritt 4). Die Namen `rg-eurocis-base`, `rg-eurocis-aks` und `rg-eurocis-nodes` entfallen. Quota reicht ohne Antrag (Bedarf 16 vCPU mit Surge-Node und 2 Public IPs, 3.5; Bestand siehe Prüfung 18.11.); Re-Check vor dem Create und vor dem Refresh am 26.01. Defender: alle relevanten Pläne Free, 0 EUR. Budget: ein Monatsbudget auf Subscription-Ebene `azure-se`, gefiltert auf `gebit-showcase` und `gebit-showcase-nodes` (Actual 100 %, Forecast 100 %, 01.12.2026-31.03.2027), 250 EUR statt 450 EUR, zwischen Stopp-Betrieb und 24/7, damit ein vergessener Nachtstopp den Forecast auslöst [A: Kosten 3.4]; Contributor darf eigene Budgets anlegen [Quelle: tutorial-acm-create-budgets]. Der feste Name der Node-RG hält den Filter über Neuaufbauten stabil; `gebit-showcase` enthält nur Showcase-Ressourcen [A]; ob Cost Management für den Angebotstyp von `azure-se` verfügbar ist, prüft P0 read-only [A]. Projektziel unter 1.500 EUR, verfolgt per Cost-Analysis-Ansicht | je RG ein Budget (ebenfalls mit Contributor möglich); eigene Subscription (nicht vorhanden); Policy-Ausnahme für die Node-RG (nur durch einen Subscription-Owner) | Policy-Built-ins und Cost Management read-only in P0 (Frage 6); Quota-Re-Check vor dem Create (P1); Budget in P1 nach dem Create |
| AKS-E2 | Region | entschieden 17.11., ergänzt 18.11. | Germany West Central für alle regionalen Ressourcen; folgt aus dem Namen `<fqdn>` (AKS-E4). Die RG `gebit-showcase` liegt in West Europe: zulässig, ihre Metadaten bleiben dort, und jede regionale Ressource braucht `-l germanywestcentral` (1.4; Activity-Log-Alarme, Action Group und Budget sind global bzw. ohne Region). Fällt West Europe aus, leitet ARM Control-Plane-Aufrufe in eine Backup-Region um; Microsoft empfiehlt dieselbe Region für RG und Ressourcen [Quelle: `learn.microsoft.com/azure/azure-resource-manager/management/overview`]; Restrisiko gering [A] | West Europe (gleiche v6-Preise [Quelle: Retail-API 16.11.], passend zur RG), dann ein anderer Name | erledigt |
| AKS-E3 | Architektur, Größe, Verfügbarkeit | entschieden 17.11.; Zulässigkeit 1-Node-Systempool [A], Beweis beim Create in P1 | arm64, 1 x `Standard_D8ps_v6` (8 vCPU / 32 GiB) im Pool `main` (System-Modus), kein HA: gleiche Digests wie im Lab, kein Multi-Arch-Build. Die SKU ist in Germany West Central ohne Restriction verfügbar, Zonen 1-3 (Prüfung 18.11.). Die Requests passen auf einen Node (mit Broker `prod1k` rund 91 % CPU und 70 % RAM der Allocatable, 3.2); Abnahme in P1: mindestens 7,8 CPU und 28,5 GiB allocatable. Microsoft Learn verlangt für produktive System-Pools mindestens 2 Nodes (3 empfohlen) [Quelle: `learn.microsoft.com/azure/aks/use-system-pools`], der AKS-Quickstart legt mit `--node-count 1` an [Quelle: `learn.microsoft.com/azure/aks/learn/quick-kubernetes-deploy-cli`]; der Create in P1 ist der Beweis [A]. Kein N-1-Drill mehr. Folge: Node-Image-Update oder Node-Ausfall heißt einige Minuten Ausfall der ganzen Demo; Rückfall L3 (Lab) | 2 Nodes mit HA (vom Owner verworfen, rund +239 EUR/Monat bei 24/7 mit OS-Disk); amd64 1 x `D8as_v6` (rund +68 EUR/Monat bei 24/7, +1-1,5 PT; SKU frei (18.11.); Familien-Quota Standard DASv6 nicht geprüft [A], vor einem Wechsel read-only prüfen); `D8ps_v5` bei Dpsv6-Engpass (ebenfalls frei) | Beweis beim Create (P1, KW49) |
| AKS-E4 | Domain, DNS, TLS | entschieden 17.11., geändert 18.11. (AKS-E21); Präfix `<p>`, Label-Scope und NRG-Lockdown: Owner-Bestätigung offen | Ein Azure-Name `<fqdn>` = `<p>.germanywestcentral.cloudapp.azure.com`: DNS-Label auf der statischen Standard-IP `pip-aks-ingress`. Claude legt sie nach Freigabe direkt nach dem Create in der Node-RG an (`az network public-ip create -g gebit-showcase-nodes -n pip-aks-ingress -l germanywestcentral --sku Standard --allocation-method Static --version IPv4 --dns-name <p>`, P1 Schritt 4); die Pflicht-Tags erbt sie von der Node-RG. Keine Rollenzuweisung: Die Control-Plane-Identität hat per Default Contributor auf ihrer Node-RG [Quelle: `learn.microsoft.com/azure/aks/static-ip`; `learn.microsoft.com/azure/aks/managed-identity-overview`]. Kein Lock, er bräuchte Owner oder User Access Administrator (AKS-E21). Der Traefik-Service nutzt `service.beta.kubernetes.io/azure-pip-name: pip-aks-ingress` und setzt `azure-load-balancer-resource-group: gebit-showcase-nodes` explizit wie das Manifest auf Learn [Quelle: static-ip]; ohne die Annotation sucht der Cloud-Provider in der RG seiner Cloud-Konfiguration, bei AKS der Node-RG [Quelle: cloud-provider-azure master pkg/provider/azure_loadbalancer.go:4298-4307; A: gleiches Verhalten in der CCM-Version von AKS 1.36]; die VAP lässt die Annotation nur fehlend oder mit `gebit-showcase-nodes` zu. Nie `azure-dns-label-name`: Der Cloud-Provider gleicht DNS-Settings nur mit dieser Annotation ab, ein leerer Wert löscht das Label; eine IP ohne sein Service-Tag gilt als nutzererstellt und wird nie gelöscht, auch nicht mit dem Service [Quelle: `github.com/kubernetes-sigs/cloud-provider-azure` pkg/provider/azure_loadbalancer.go, master 18.11.; A: gleiches Verhalten in der CCM-Version von AKS 1.36]. Folge ohne Lock: `az aks delete` löscht die Node-RG samt IP; eine gelöschte statische IP ist nicht wiederherstellbar, das Label ist danach für jeden in der Region frei [Quelle: faq; `learn.microsoft.com/azure/virtual-network/ip-services/public-ip-addresses`]. Ein Neuaufbau bindet `<p>` sofort neu und bekommt eine neue IP. Owner-Optionen: (1) Domain Name Label Scope `--dns-name-scope SubscriptionReuse`, nur beim Anlegen setzbar (Public Preview ohne SLA; der Name bekommt einen Hash, `<p>.<hash>.germanywestcentral.cloudapp.azure.com`, ist aus anderen Subscriptions nicht belegbar, und ein Neuaufbau in `azure-se` bekommt denselben Namen) [Quelle: public-ip-addresses, "Domain Name Label Scope"]; (2) NRG-Lockdown `az aks update --nrg-lockdown-restriction-level ReadOnly` nach dem LB-Nachweis in P2 als Lock-Ersatz gegen versehentliches Löschen (keine Rollenzuweisung nötig; im Modus ReadOnly kann auch der Owner die IP nicht ändern, dafür kurz auf Unrestricted) [Quelle: `learn.microsoft.com/azure/aks/node-resource-group-lockdown`; A: Zusammenspiel mit dem Cloud-Provider in P2 testen]. Mit der AKS-verwalteten Outbound-IP sind es 2 Public IPs; LB-Regeln nur für 80 und 443 (mit der Outbound-Regel 3 Regeln, innerhalb der 5 im LB-Grundpreis [Quelle: Retail-API 17.11.]). Keine eigene Domain, keine Azure-DNS-Zone, kein DNS-01. Pfad-Routing auf 443 nach 2.1. TLS: ACME HTTP-01 über cert-manager, ein Zertifikat für `<fqdn>` als Traefik-Default (`TLSStore`); ob der SAM-Ingress `secretName` weglässt oder `sam-tls` vor `helm install` im SAM-Namespace liegt, entscheidet ein Test in P2 [Quelle: SAM-Chart 2.3.10 templates/_validations.tpl:110-113]. LE-Risiko: `cloudapp.azure.com` steht nicht auf der Public Suffix List, alle Azure-Kunden teilen den Bucket `azure.com` (50 neue Zertifikate je Woche); die Ausstellung kann tagelang scheitern [Quelle: `publicsuffix.org/list/public_suffix_list.dat` (17.11.); `letsencrypt.org/docs/rate-limits`; `community.letsencrypt.org/t/217855`]. Gegenmittel: erst LE-Staging, dann früh Produktion (P2); vorbereiteter Rückfall-ClusterIssuer einer ACME-CA mit EAB (ZeroSSL oder Google Trust Services; das Konto legt der Owner an, EAB-Daten nur in Key Vault und `.env.aks`); ausgestelltes Secret sichern; `cmctl renew` um den 15.01., damit die automatische Erneuerung nicht in den Freeze fällt [A: 90 Tage Laufzeit, Erneuerung nach zwei Dritteln]. `<p>` ist neutral, ohne Kunden- oder Projektnamen (CT-Logs sind öffentlich). Verfügbarkeit per `CheckDnsNameAvailability` am 20.11. und direkt vor dem Anlegen erneut prüfen, weil das Label bis zum Create frei bleibt [A] | eigene Domain mit DNS-01 (bisherige Empfehlung, vom Owner verworfen); IP schon in P0 in `gebit-showcase` anlegen und nach dem Create per `az resource move` in die Node-RG schieben, um das Label früher zu reservieren [A: Move in die Node-RG und Erhalt des Labels ungeprüft]; IP mit Lock außerhalb der Node-RG (bräuchte Lock und Network Contributor, ausgeschlossen durch AKS-E21); weitere Varianten in 8.5 | Präfix `<p>` bis 20.11.; Label-Scope bis 27.11. (Frage 7); NRG-Lockdown nach dem LB-Nachweis in P2 (P2 Schritt 10, Frage 29); neues G3-Kriterium (Frage 31); Verfügbarkeit am 20.11. und direkt vor dem Anlegen; `pip-aks-ingress` direkt nach dem Create (P1, ab 30.11.); LE-Produktion früh in P2; Rückfall-Konto und EAB-Daten bis 04.12. (Prüfpunkt) |
| AKS-E5 | Zugriffsmodell, Missbrauchsschutz | entschieden 17.11., Break-glass geändert 18.11.; API-Server-Weg [A] Bestätigung offen; Exposition von `/freigabe`, `/foto`, `/op`, `/etikett`: Owner-Bestätigung offen | Öffentlich für alle, ohne WireGuard und ohne internes LB (was entfällt, steht in 8.5). Kasse (mit `/kunde`) und Monitor bleiben unverändert und ohne Login. Nicht vom Owner entschieden ist die Exposition der übrigen BFF-Seiten samt API-Routen: `/freigabe` beantwortet pausierte SAM-HITL-Läufe über die BFF (jeder könnte Preise freigeben oder ablehnen), `/foto` startet mit jedem Upload den Vision-Agenten, `/op` schaltet auf L4 [Quelle: PLAN 1.4 (Fläche A), PLAN 9 R24]. Bis zur Antwort (Frage 23) bekommen sie keinen Pfad auf `<fqdn>`. Öffentlich ist nur der Traefik-LoadBalancer-Service (VAP), mit `externalTrafficPolicy: Local` für echte Client-IPs. Nicht öffentlich: Grafana, Prometheus, Broker-SEMP, Keycloak-Admin-Konsole, Traefik-Dashboard (Port-Forward). Missbrauchsschutz: Komponente `public-guard` mit Traefik-Rate-Limits je Client-IP auf `/api/pos/`, `/api/demo/reset`, `/api/events` und den drei gRPC-Service-Pfaden (429 statt 503), dazu rpm/tpm-Limits am Messe-Key (AKS-E11); alle Standgeräte hinter einer NAT-IP teilen sich die Limits [A: Werte in P6 messen]. API-Server: authorized IP ranges; der Helfer `sli/aks/aks-allow-me.sh` ermittelt die aktuelle IP, mergt sie in die bestehende Liste und schreibt die volle Liste, weil `az aks update --api-server-authorized-ip-ranges` die Liste ersetzt (bis 2 min Laufzeit, höchstens 200 Bereiche) [Quelle: `learn.microsoft.com/azure/aks/api-server-authorized-ip-ranges`]; er braucht `managedClusters/write`, also Contributor (AKS-E20), und bekommt eine Option für eine fremde IP. Break-glass bei IP-Sperre: `az aks command invoke` aus jedem Netz; es läuft über ARM, aber mit dem Entra-Token des Aufrufers und damit unter Kubernetes-RBAC, hilft also nicht bei fehlendem ClusterRoleBinding; der Run-Pod fordert 200m CPU und 500Mi an [Quelle: `learn.microsoft.com/azure/aks/access-private-cluster`; azure-cli acs/custom.py, 2.85.0 und 2.93.0]. Break-glass bei RBAC-Lockout: `aks_update --enable-local-accounts`, `az aks get-credentials --admin --file` nur in ein per `trap` gelöschtes Temp-Verzeichnis (Muster aus P1 Schritt 6), reparieren, wieder `--disable-local-accounts` mit Nachweis (`disableLocalAccounts` gleich `true`, Negativtest), danach Zertifikate rotieren (AKS-E13). `aks-allow-me.sh` gilt als Freeze-Ausnahme, weil es nur ergänzt [A] | API-Server nur mit Entra ID und Conditional Access, ohne IP-Bereiche (aus jedem Netz, Endpunkt aber scannbar); privat mit WireGuard (bisherige Empfehlung, vom Owner verworfen); für die offenen Seiten: öffentlich, nur Port-Forward bzw. Lab, oder ein Schutz vor G2b | Abweichung vom API-Server-Weg bis 27.11.; Seiten-Exposition vor G2b [Quelle: PLAN 9 R24] |
| AKS-E6 | Ingress-Controller | entschieden 17.11. | Traefik v3 mit ingress-nginx-Provider statt ingress-nginx: Chart 42.4.1, Image `traefik:v3.7.19` per Digest (nie unter v3.7.18, das fünf GHSAs behob; kein v3.8.0-rc) [Quelle: `api.github.com/repos/traefik/traefik/releases` und `.../security-advisories` (17.11.)], cert-manager v1.21.3; ein Deployment mit 1 Replika hinter genau einem LoadBalancer-Service (`pip-aks-ingress`, 80/443). Geschlossene Lücken: `ports.websecure.transport.respondingTimeouts.readTimeout: 3600s` (sonst schneidet Traefik HTTP/1.1-SSE und MCP nach 60 s ab); `azure-load-balancer-tcp-idle-timeout: "30"`; eigene IngressClass `nginx` (Controller `k8s.io/ingress-nginx`), weil das SAM-Chart die Klasse beim Install prüft und das Traefik-Chart sie nicht anlegt; Provider `kubernetesIngress` aus, `kubernetesCRD` an (Middleware, TLSStore); `proxy-request-buffering: "on"` für SAM und gpos-ui, sonst wirkt `proxy-body-size` nicht; HSTS per Headers-Middleware ohne `includeSubDomains`; kein Redirect auf EntryPoint-Ebene, damit HTTP-01 durchkommt (`ssl-redirect` je Ingress liefert 308); nie Buffering auf der SSE-Route `/api/events` [Quelle: Traefik v3.7.19 docs ingress-nginx.md:265-502, entrypoints.md:128-130; pkg/provider/kubernetes/ingress-nginx/middleware.go:176-213; SAM-Chart 2.3.10 templates/_validations.tpl:185-189]. Das Lab behält ingress-nginx (dieselben NGINX-Ingress-Manifeste laufen auf beiden); Traefik-eigene Werte beweist erst P2. Traefik-Patch-Releases im Freeze nur als Ausnahme mit Smoke-Test [A] | ingress-nginx 4.15.1 (bisherige Empfehlung; archiviert, CVE-2026-116472 ohne Fix); App-Routing Gateway API; Application Gateway for Containers (ab rund 125 EUR/Monat) | erledigt; Nachweis in P2 |
| AKS-E7 | SAM-Persistenz | entschieden 17.11. | gebündelt (Postgres + SeaweedFS 2 CPU/2Gi, seit sda-Commit cd08a17 in amd `local-k8s-values.yaml`) auf `managed-csi-premium`, Superuser-Passwort aus Key Vault (`sam-pg-admin`), Schutz nach AKS-E19; Keycloak- und Demo-DB ebenfalls im Cluster | extern: PG Flexible + Blob (+1,5-2 PT, rund +108 EUR/Monat, nie im Lab gelaufen); der PLAN nennt gebündelt selbst als Rückfall [Quelle: PLAN 6.2, Nr. 11] | erledigt |
| AKS-E8 | Broker | entschieden 17.11.; Lab-Upgrade: Go offen | PubSub+ Standard 10.26.0.9219 (LTS, Tags `latest`/`lts`, Index-Digest beginnt mit `sha256:c0020e53ed48`) für Lab und AKS, per Digest gepinnt; nicht 10.26.10 (Rolling Release ohne Wartungsreleases, Support nur bis zum nächsten LTS, kein Weg zurück auf 10.26.0.x) [Quelle: Docker-Hub-Tags-API (17.11.); `solace.com/support/support-dates-for-release-versions`; docs.solace.com Upgrade-Selector]. AKS: `pubsubplus` 3.10.0 mit `service.type: ClusterIP` und `storage.useStorageGroup: true` explizit, P10 128Gi, VPN-Layout wie im Lab, eigene User `sam` und `gpos`. Größe `prod1k` (Requests und Limits 2 vCPU / 6,4 GiB, Guaranteed, 1000 Verbindungen; mehr RAM, als der Lab-Broker heute belegt, 4,19 GiB); zwingt das Sizing dazu (Kriterium in 3.2: die nach P2 gemessenen CPU-Requests von System, Traefik, cert-manager und Monitoring liegen über 2044m, dann reißt `prod1k` die 92-%-Grenze; einen Defender-Sensor gibt es nicht, alle Pläne Free, 18.11.), dann `dev` (Request 1 vCPU / 3,3 GiB, 100 Verbindungen): reicht für die rund 11 Verbindungen der Demo, liegt beim RAM aber unter dem Lab-Verbrauch (OOM-Risiko) [A]. Der Lab-Broker läuft mit dem Default von 100 Verbindungen [A: per SEMP `show system` bzw. SEMPv2-GET prüfen]. Neuer Arbeitsposten Lab-Upgrade 10.25.0.208 auf 10.26.0.9219: Beide Broker-DBs liegen im Container-Layer (1.4). Schritte: SEMPv2-Baseline, `docker commit` als Rückfall, Storage auf ein externes Volume, Tag plus Digest in emd `.env.example`, Terraform-Provider fest pinnen, `docker compose up -d --no-deps` je Broker, `solace-2` zuerst, danach `terraform plan` ohne Änderungen. Risiko mittel bis hoch: Volume-Kopie der SolOS-DB ungeprobt; 36 Queues, Client-Usernames und ein ACL-Profil liegen außerhalb von Terraform. Eigenes Owner-Go und Wartungsfenster; fertig und mit SAM- und GEBIT-Flows im Lab bewiesen vor P4 Teil B (AKS) und P5 | 10.26.10.14510 (Rolling, Support nur bis Juni 2027); 10.25.0.208 auf AKS (dann zwei Versionen); Solace Cloud (ein VPN je Service, TLS-only, Änderung an `bus.py` nach UC1-Freeze) | Go vor der Probe an `solace-2` (KW48) [A]; `solace-1` bis zum Prüfpunkt 04.12., spätestens 10.12. |
| AKS-E9 | Monitoring | [A] Bestätigung offen (Zugriff entschieden 17.11.) | OSS im Cluster, Lab-Versionen, Images aus ACR, Tempo bleibt (im Owner-Scope); Grafana und Prometheus ohne Ingress, Zugriff per Port-Forward | Azure Managed Prometheus + Grafana (+125-215 EUR/Monat, Dashboards und ServiceMonitors portieren) | 04.12. |
| AKS-E10 | Keycloak | entschieden 17.11. | bleibt im Cluster, Realm `solace-lab`, 26.8.2 gepinnt, generierte Passwörter. Unter `/auth`: `KC_HTTP_RELATIVE_PATH=/auth`, `KC_HOSTNAME=https://<fqdn>/auth`, `KC_HTTP_MANAGEMENT_RELATIVE_PATH=/` (Probes bleiben `/health/*` auf Port 9000); beide Pfade sind Build-Optionen, der Start ohne `--optimized` übernimmt sie [Quelle: `www.keycloak.org/server/hostname`; sli keycloak/manifests/03-keycloak.yaml:141-144]. Issuer `https://<fqdn>/auth/realms/solace-lab`; Ingress nur für `/auth/realms/solace-lab/` und `/auth/resources/`; Admin-Konsole per Port-Forward (ob `KC_HOSTNAME_ADMIN` nötig ist, klärt P3); die Keycloak-Admin-Skripte nehmen `KEYCLOAK_URL` als Präfix (`.../auth`). SAM-Client: `redirectUris` exakt `https://<fqdn>/api/v1/auth/callback` statt Wildcard, die auf dem geteilten Host auch gpos- und Keycloak-Pfade deckte [Quelle: amd scripts/setup-keycloak-client.sh:17, 124-125] | 26.2-Lab-Digest (Release-Linie ohne Upstream-Support); Entra ID als IdP (nicht empfohlen: RBAC-Manifeste, Claim-Mapping); eigener Host (verworfen mit AKS-E4) | `KC_HOSTNAME_ADMIN` in P3 |
| AKS-E11 | LiteLLM | entschieden 17.11., geändert 18.11. (AKS-E21); Betreiber-Antwort offen | Egress über die AKS-verwaltete Outbound-IP des Standard-LB in `gebit-showcase-nodes` (Default `managedOutboundIPs.count` 1), kein BYO `pip-aks-egress`: Eine eigene IP außerhalb der Node-RG bräuchte Rechte der Cluster-Identität, also eine Rollenzuweisung [Quelle: `learn.microsoft.com/azure/aks/configure-load-balancer-standard`]. Die Adresse steht erst nach dem Create fest; P1 liest sie aus `networkProfile.loadBalancerProfile.effectiveOutboundIPs[].id` und meldet sie sofort dem Betreiber. Stop/Start behält sie [A: nicht dokumentiert, P1 misst vor und nach dem ersten Zyklus]; jeder Neuaufbau bringt eine neue IP und, falls es eine Allowlist gibt, eine neue Freischaltung (Vorlaufzeit des Betreibers erfragen, ins Neuaufbau-Runbook). Anfrage an den Betreiber am 20.11. ohne IP, mit dem Hinweis auf die wechselnde IP. Messe-Key (O5, 150 USD, Alarme bei 50 und 80 % [Quelle: PLAN 0.5]) nur in die SAM-Konfiguration. Der Betreiber setzt `rpm_limit` und `tpm_limit` (dazu `max_budget`) am Messe-Key [Quelle: `docs.litellm.ai/docs/proxy/users`]; Grund: Kasse und Reset sind anonym, ein Skript mit einem Review alle 5 s kostet rund 7-36 USD/h und leert den Key in 4-21 h, danach steht die Demo [A; Quelle: PLAN 0.5 (O5), PLAN 8.6] | kein separater Messe-Key (dann Lab-Key auf AKS); stabile BYO-Egress-IP außerhalb der Node-RG (braucht eine Rollenzuweisung, ausgeschlossen durch AKS-E21) | Anfrage 20.11. (ohne IP), Antwort und Limits 27.11., IP direkt nach dem Create (P1, ab 30.11.), Freischaltung vor dem LLM-Test in P1 (03.12.) (Fragen 5 und 26) |
| AKS-E12 | Kyverno, trust-manager, Lab-Registry auf AKS | [A] Bestätigung offen; geändert 18.11. (AKS-E21) | nicht installieren; ValidatingAdmissionPolicy + PriorityClasses. VAP neu: `type: LoadBalancer` nur für den Service `traefik/traefik` mit `azure-pip-name: pip-aks-ingress`, `azure-load-balancer-resource-group` fehlend oder gleich `gebit-showcase-nodes` (fängt auch den öffentlichen LB-Default des `pubsubplus`-Charts und einen zweiten LB-Service im Namespace `traefik`); TLS- und Redirect-Regeln nehmen HTTP-01-Solver-Ingresses (Label `acme.cert-manager.io/http01-solver`) aus | Kyverno 3.7.1 gepinnt mit umgeschriebenen Policies (+0,5 PT; Chart 3.9.2+ blockiert `az aks stop`) | 27.11. |
| AKS-E13 | Cluster-Zugriff, Mac-Tools | entschieden 17.11., geändert 18.11. (AKS-E21); Bootstrap-Variante: Owner-Bestätigung offen | AKS-verwaltetes Entra ID mit Kubernetes-RBAC: `--enable-aad` ohne `--enable-azure-rbac` (Azure RBAC für Kubernetes bräuchte Rollenzuweisungen). Bootstrap einmal direkt nach dem Create, mit noch aktiven lokalen Accounts: (1) Entra-kubeconfig per `az aks get-credentials --file ~/.kube/aks-eurocis.yaml --context aks-eurocis`, dann `kubelogin convert-kubeconfig -l azurecli --kubeconfig ~/.kube/aks-eurocis.yaml --context aks-eurocis` (nutzt die `az login`-Sitzung; ohne `--file` bzw. `--kubeconfig` träfen beide `~/.kube/config`) [Quelle: `azure.github.io/kubelogin/cli/convert-kubeconfig.html`]; (2) `kaks auth whoami` zeigt den Benutzernamen, den AKS ableitet (nur notieren, nie ins Repo); (3) `az aks get-credentials --admin` in ein per `trap` gelöschtes Temp-Verzeichnis (umask 077; Contributor hat `listClusterAdminCredential`), damit ein ClusterRoleBinding auf `cluster-admin` mit `kind: User` und `name: <owner-upn>`; Learn bindet Nutzer desselben Tenants per UPN, Nutzer aus anderen Tenants per objectId und Gruppen per objectId mit `kind: Group` [Quelle: `learn.microsoft.com/azure/aks/kubernetes-rbac-entra-id`]; (4) `kaks auth can-i '*' '*' -A` ergibt yes; (5) `aks_update --disable-local-accounts`, dann `disableLocalAccounts` gleich `true` prüfen; erst danach der Negativtest, bei dem `--admin` in einem per `trap` gelöschten Temp-Verzeichnis mit "Getting static credential isn't allowed" scheitern muss (P1 Schritt 6); (6) `az aks rotate-certs` vor dem ersten Workload, weil Learn nach genutzten lokalen Accounts die Rotation verlangt; Nodes, VMSS und Disks entstehen neu, bis 30 min Ausfall, danach die kubeconfig neu holen [Quelle: `learn.microsoft.com/azure/aks/manage-local-accounts-managed-azure-ad`; `learn.microsoft.com/azure/aks/rotate-certificates`]. Das Binding des Stellvertreters legt der Owner später mit seiner Entra-Identität an (AKS-E20). Eigene kubeconfig nur über `kaks`/`haks`. Mac-Tools freigegeben (AKS-E15 (e)): Azure CLI als Cask (2.93 oder neuer), Microsoft-kubelogin aus dem Tap `Azure/kubelogin` | Azure RBAC für Kubernetes (braucht Rollenzuweisungen, ausgeschlossen); Admin-Gruppe per `--aad-admin-group-object-ids <group-objectId>` beim Create mit `--disable-local-accounts`, ohne Admin-Zertifikat und ohne Rotation, nur wenn der Owner eine eigene Entra-Sicherheitsgruppe anlegen darf (nicht die Contributor-Gruppe); lokale Accounts dauerhaft an (statisches Admin-Zertifikat für jeden Contributor abrufbar) | Bootstrap-Variante bis 27.11. (Frage 28); Bootstrap in P1 (KW49); Installation der Mac-Tools in P0 (noch offen) |
| AKS-E14 | Version, Tier, Wartung, Laufzeiten | entschieden 17.11. | 1.36.x gepinnt (am 18.11. Default in Germany West Central, Patch 1.36.5), Auto-Upgrade aus, Node-OS-Kanal SecurityPatch Mi 08-12 Uhr; manueller Node-Image-Refresh Di 26.01.2027; `notAllowedDates` 20.01.2027 und 27.01.-20.02.2027 auf allen drei Wartungskonfigurationen. Free-Tier für das ganze Projekt, kein Wechsel auf Standard (kein Uptime-SLA). Mit einem Node heißt jedes Node-Image-Update einige Minuten Ausfall; die Sperre um die Messe bleibt deshalb. Nachts stoppen bis G4 (Start frühestens 30 min nach Stop), ab 05.02. 24/7 | Standard-Tier ab G2b (bisherige Empfehlung, rund 66 EUR/Monat); 1.35 (EOL März 2027); 1.37 (1.37.1, am 18.11. verfügbar, nicht Default); Node-OS `None` mit einem manuellen Refresh | erledigt; Konfiguration in P1 |
| AKS-E15 | Freigaben geteilte Infra und Mac-Tools | entschieden 17.11. (alle erteilt); (e) am 18.11. noch nicht ausgeführt | (a) amd-Working-Tree committet (sda-Commit cd08a17, erledigt); (b) Profil + Kontext-Guard in amd-Skripten inkl. Keycloak-Teardown-Skripten; (c) neue Ordner `sli/aks/`, `emd/aks/`, `emd/terraform-aks/`, `amd/manifests/aks/`; (d) Broker-Pin 10.26.0.9219 per Tag und Digest in emd `.env.example`, wirksam erst mit dem Lab-Upgrade, das ein eigenes Go braucht (AKS-E8); (e) Mac-Tools Azure CLI 2.93 oder neuer und Microsoft-kubelogin; freigegeben, am 18.11. noch nicht installiert (CLI 2.85.0, kein kubelogin) | alles in gpd (Lab-Skripte ohne Guard) | Freigaben (a) bis (e) erteilt (17.11.); umgesetzt: (a) (cd08a17); (b) in P0 Schritt 10, (c) ab P0/P1, (d) mit P4 Teil A, (e) Installation vor P1 (P0 Schritt 8) |
| AKS-E16 | GEBIT, gRPC | entschieden 17.11.; Descriptor-Set in Azure und öffentliche Reflection: offen (Planungsannahme ja [A], gehandelt wird erst nach schriftlicher Bestätigung) | Laut Owner liegt die schriftliche GEBIT-Freigabe seit 17.11.2026 vor; gpd ist im öffentlichen sda-Repo committet (sda-Commit 7a860c5). Alle drei gRPC-Endpunkte sind öffentlich für alle, Reflection an; der Owner akzeptiert, dass jeder die anonymen Schreib-RPCs aufrufen kann (z. B. Preisänderung in der WWS, Coupons im Loyalty-Dienst, Reset); `public-guard` bremst sie je Client-IP (P6 Schritt 8). Routing über den Service-Pfad auf `<fqdn>:443` (2.1). Neuer Arbeitsposten in P6: Image 0.1.4 mit einem gebündelten Reflection-Endpunkt, der für alle drei Dienste aus beiden Descriptor-Pools antwortet (GEBIT aus dem Secret-Mount, Showcase aus dem Image) [A: rund 0,5 PT]; bis dahin nutzen grpcurl und Postman für zwei der drei Server das lokale Descriptor-Set (`-protoset`); gRPC-Health nur im Cluster. Planungsannahme: Die Freigabe deckt auch das GEBIT-Descriptor-Set als K8s-Secret in Azure GWC, Zugriff von Owner und Stellvertretung (AKS-E20), Löschung bis 20.02. und die öffentliche Reflection. Diese gibt nicht nur die Dienstliste heraus, sondern die GEBIT-Descriptor-Dateien selbst (Purchase-API samt Abhängigkeiten) [A: Owner bestätigt]. Seit 18.11.: Technisch erreicht jedes Mitglied der Contributor-Gruppe von `azure-se` das Secret, weil es lokale Accounts wieder einschalten kann (AKS-E21); die Bestätigung muss diesen Kreis abdecken [A: Owner klärt den Mitgliederkreis]. Harte Vorbedingung: Ohne schriftliche Bestätigung kommt kein GEBIT-Material nach Azure (auch nicht für `gebitsim` in P2 Schritt 7) und keine Reflection-Route auf `<fqdn>`; nie in Git, Images oder ACR | deckt die Freigabe das Secret nicht: Descriptor-Set nur im Lab, Messe aus dem Lab (L3), G0-11b (3) mit einem Testserver ohne GEBIT-Material; deckt sie nur die öffentliche Reflection nicht: Reflection-Pfade ungeroutet (bisherige Variante c), `-protoset` für alle drei Dienste | Bestätigung bis 27.11., spätestens 09.12. (vor dem ersten GEBIT-Secret in Azure, P2 Schritt 7; G0-11b (3) mit `gebitsim` am 11.12.; Fragen 4 und 27); Image 0.1.4 in P6 |
| AKS-E17 | Secrets | entschieden 17.11. (mit AKS-E4), geändert 18.11. (AKS-E21) | Key Vault im Access-Policy-Modus (`az keyvault create -g gebit-showcase -l germanywestcentral -n <kv> --enable-rbac-authorization false --no-self-perms --retention-days 7`; Soft-Delete 7 Tage, ohne Purge-Schutz) als Kopie außerhalb des Macs für generierte Secrets (hex, ohne Zeilenumbruch), TLS-Backups, die EAB-Daten des Rückfall-Issuers und das Passwort des ACR-Tokens (`acr-pull-token`, AKS-E21), ohne CSI-Treiber; LiteLLM-Key und GEBIT-Material nie im Key Vault. Rechte per Access Policy, nur auf Secrets: Owner `az keyvault set-policy -n <kv> --object-id <owner-objectId> --secret-permissions get list set delete recover` (objectId zur Laufzeit aus `az ad signed-in-user show`), Stellvertreter `--object-id <deputy-objectId> --secret-permissions get list`; Contributor darf Access Policies setzen [Quelle: `learn.microsoft.com/azure/key-vault/general/assign-access-policy`]. Ohne `--no-self-perms` bekäme der Owner beim Create automatisch alle Rechte auf Keys, Secrets, Zertifikate und Storage; ohne `--enable-rbac-authorization false` legt die CLI den Vault im RBAC-Modus an [Quelle: azure-cli keyvault/custom.py und _params.py, 2.85.0 und 2.93.0]. Access Policies nennt Learn ein Legacy-Modell, sie bleiben aber voll unterstützt [Quelle: `learn.microsoft.com/azure/key-vault/general/rbac-access-policy`]. Key-Vault-Schritte (Anlage, Policies, Rückbau) mit Azure CLI 2.93: 2.85.0 nutzt die Kontroll-API 2025-05-01, die am 27.02.2027 endet [Quelle: `learn.microsoft.com/azure/key-vault/general/access-control-default`]. Grenze: Jeder Contributor von `azure-se` kann sich selbst eine Policy setzen (AKS-E21); "ASC Default" meldet den Modus vermutlich als Abweichung, nur kosmetisch [A] | Key Vault im RBAC-Modus (braucht die Rollenzuweisung "Key Vault Secrets Officer", ausgeschlossen); nur `.env.aks` + Passwortmanager des Owners | Anlage in P1 |
| AKS-E18 | Gate-Verschiebung G0-11a/G0-11b | Owner-Bestätigung offen | G0-11a nach G2a (18.12., P5), die LiteLLM-Probe in P1 ist nur Frühindikator; Prüfung (4) DSN-TLS entfällt mit AKS-E7; Prüfung (2) Vision auf Modellebene in P5, mit `gpos-price-scout` in P6; G0-11b gRPC (3) bleibt am 11.12. (P2 Schritt 7, über Traefik und `<fqdn>`), HITL (1) wandert nach P5 (18.12.); AP12 S1-S3 von KW48 nach KW49/50 | PLAN-Termine 03.12./11.12. halten (verlangt den Cluster schon in KW48, vor dem Ende von P0) | 27.11. |
| AKS-E19 | Schutz der SAM-Datenbank | entschieden 17.11. | eigenes Superuser-Passwort `sam-pg-admin` ab dem ersten Install; NetworkPolicies nur für SAM-Postgres und SeaweedFS (abweichend von RA R15 [Quelle: RA:599]); `grafana_ro` nur mit expliziter Tabellenliste | Chart-Default `password` ohne NetworkPolicy (RA R15): dann kann jeder Pod im Cluster, auch die öffentliche BFF ohne Login, den LiteLLM-Key lesen | vor dem ersten SAM-Install (P5) |
| AKS-E20 | Betrieb an Probetagen und Messe | Owner-Bestätigung offen; geändert 18.11. (AKS-E21); Azure-Zugang des Stellvertreters offen | Betreiber und Stellvertreter namentlich; Vorschlag nach PLAN 6.4/7.3: Person C Betreiber, Entwickler A Stellvertreter (bei O9 = (b): A Betreiber, Owner Stellvertreter) [A]; eigene Konten, Allowlist-Eintrag und Keycloak-User. Azure: Eine eigene Rolle ohne `delete` und `stop` gibt es nicht, weil der Owner keine Rollen zuweisen kann (AKS-E21). `az aks get-credentials`, `aks-allow-me.sh` (`managedClusters/write`), `az aks start`/`stop` und `command invoke` kann der Stellvertreter nur mit eigenem Contributor (oder Ähnlichem) auf `azure-se`, etwa über eine Gruppe; damit hat er auch `stop` und `delete`, die Grenze ist eine Runbook-Regel. Fehlt dieser Zugang, bleiben diese Schritte beim Owner, oder ein Subscription-Owner weist zu (offen für den Owner). kubectl allein geht auch ohne Azure-Recht [A: Test vor G3 mit einem Konto ohne Subscription-Zugriff, P7 Schritt 7]: Die Entra-User-kubeconfig enthält kein Geheimnis und fordert nur die Anmeldung [Quelle: `learn.microsoft.com/azure/aks/control-kubeconfig-access`]. Ohne Subscription bricht ein einfaches `az login` mit "No subscriptions found" ab; er meldet sich deshalb mit `az login --tenant <tenant> --allow-no-subscriptions` an (bei einem Gast liefert erst `--tenant` ein Token des richtigen Tenants), prüft `kaks auth whoami` und nennt seine objectId per `az ad signed-in-user show --query id -o tsv`. Ohne Azure CLI konvertiert er die weitergegebene kubeconfig mit `kubelogin convert-kubeconfig -l interactive` (oder `-l devicecode`) statt `-l azurecli`, je mit `--kubeconfig ~/.kube/aks-eurocis.yaml` [Quelle: azure-cli 2.85.0 core/_profile.py:206-207; `az login --help`, 2.85.0]. Dazu braucht er ein Konto im Tenant, ein ClusterRoleBinding (`<deputy-upn>`, bei einem Gast aus einem anderen Tenant die objectId; Username vorher per `kaks auth whoami` bestätigen) und seine IP in der Allowlist, die der Owner per `aks-allow-me.sh` mit der Option für eine fremde IP einträgt. Key Vault: Access Policy mit `<deputy-objectId>` (AKS-E17). Test mit seinem Konto vor G3; Break-glass wie AKS-E5 | nur der Owner (Risiko in Abschnitt 7) | Name 20.11. (Frage 2); Azure-Zugang des Stellvertreters bis 27.11. (Frage 24); Binding, Policy und Test bis G3 |
| AKS-E21 | Azure-Rechte: nur Contributor | entschieden 18.11.; Folgen (2.2) und Zugriffskreis der Contributor-Gruppe: Owner-Bestätigung offen [A]; Scope-Map und Ablauf des ACR-Tokens: Owner-Bestätigung offen | Keine Rollenzuweisungen, keine Locks, keine Policy-Ausnahmen; alles läuft mit Contributor (Prüfung 18.11.). Umsetzung: (1) Netz: kein BYO-VNet (dafür bräuchte die Cluster-Identität Network Contributor, und der Ersteller müsste die Zuweisung anlegen), sondern das AKS-verwaltete VNet in der Node-RG, weiter Azure CNI Overlay mit Cilium [Quelle: `learn.microsoft.com/azure/aks/azure-cni-powered-by-cilium`; `learn.microsoft.com/azure/aks/concepts-network-cni-overview`]; Name und Adressraum stehen auf keiner Learn-Seite [A: beobachtet 10.224.0.0/12, ohne Überlappung mit Pod- und Service-CIDR; nach dem Create protokollieren], eigene UDRs oder Service-Endpoints daran sind nicht supportet. (2) Identität: System-Identität statt UAMI `id-aks-cp`. (3) ACR Basic in `gebit-showcase` mit `--role-assignment-mode rbac` (explizit, weil Contributor im ABAC-Modus weder pusht noch pullt) und ohne `--attach-acr`; Pull über ein repository-scoped Token mit Pull-only-Scope-Map über alle Repositories (`content/read`, `metadata/read`; eigene Scope-Map mit `*` oder die System-Scope-Map `_repositories_pull`), angelegt mit `--no-passwords`; das Passwort (`password1`, `password2` als Rotationsreserve) hat einen Ablauf nach dem Rückbau (Vorschlag 28.02.2027 [A: Owner]) und liegt nur im Key Vault und in `sli/aks/.env.aks` (chmod 600); Secret `acr-pull` (Typ dockerconfigjson) in jedem Namespace, der aus ACR zieht, vor `helm`/`kustomize` (Helfer `sli/aks/acr-pull.sh`); `imagePullSecrets` über die Chart-Werte, ein Patch des default-ServiceAccount nur für Test-Pods; `az aks check-acr` sagt hier nichts [Quelle: `learn.microsoft.com/azure/container-registry/container-registry-token-based-repository-permissions`; `learn.microsoft.com/azure/container-registry/container-registry-rbac-abac-repository-permissions`; `learn.microsoft.com/azure/container-registry/container-registry-auth-kubernetes`]. (4) Cluster-Zugriff: Entra ID mit Kubernetes-RBAC (AKS-E13). (5) Key Vault im Access-Policy-Modus (AKS-E17). (6) `pip-aks-ingress` ohne Lock in der Node-RG (AKS-E4), AKS-verwaltete Egress-IP (AKS-E11). (7) Pflicht-Tags beim Create (AKS-E1). (8) Budget und Activity-Log-Alarme legt der Owner als Contributor an, die Zugriffs- und Löschalarme schon vor dem Create (`foundation.sh pre`, P1 Schritt 8). Die CLI-Flags, die Zuweisungen auslösen, sind tabu (1.4). Preis: Kubernetes-RBAC und Access Policies sind keine Grenze gegen die anderen Contributors von `azure-se`; jeder von ihnen kann lokale Accounts wieder einschalten und Admin-Credentials holen, sich eine Key-Vault-Policy setzen oder ACR-Tokens anlegen [Quelle: `learn.microsoft.com/azure/key-vault/general/assign-access-policy`; `learn.microsoft.com/azure/aks/manage-local-accounts-managed-azure-ad`]. Das steht im Activity Log; Alarme darauf erkennen Missbrauch, verhindern ihn aber nicht (2.2) | Rollenzuweisungen durch einen Subscription-Owner (`--attach-acr`, Azure RBAC für Kubernetes, Network Contributor für BYO-Netz und IPs, Key-Vault-RBAC, Lock auf der Ingress-IP); vom Owner am 18.11. ausgeschlossen | erledigt; Umsetzung in P1; Ablauf und Scope-Map des ACR-Tokens bis 27.11. (Frage 30); Zugriffskreis (Frage 27) bis 27.11., spätestens 09.12. (AKS-E16) |

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

Folgen der Entscheidung vom 18.11. (AKS-E21), mit ihr in Kauf
genommen [A: ausdrückliche Bestätigung des Owners offen]:

- **Label und IPs ohne Lock:** Jedes `az aks delete`, auch durch ein
  beliebiges Mitglied der Contributor-Gruppe, löscht
  `gebit-showcase-nodes` samt `pip-aks-ingress` und Outbound-IP; das
  Label ist sofort für jeden in der Region frei, eine gelöschte
  statische IP ist nicht wiederherstellbar [Quelle:
  `learn.microsoft.com/azure/aks/faq`; public-ip-addresses]. Ein
  Neuaufbau bekommt neue Ingress- und Egress-IPs; `<fqdn>` bleibt nur
  bei sofortiger Neubindung. Das G3-Kriterium "Ingress-IP
  unverändert" (P7-Abnahme der Fassung vom 17.11., sda-Commit
  9f66efd) soll "`<fqdn>` unverändert" heißen (Owner-Bestätigung
  offen, Frage 31). Gegenmittel: Runbook-Regel (den Cluster nur beim
  Rückbau oder im Neuaufbau-Drill löschen, nur über
  `sli/aks/aks-rebuild.sh`, dann sofort neu binden),
  Activity-Log-Alarme vor dem Create auf `managedClusters/delete`,
  das Löschen von `pip-aks-ingress`, Key Vault, ACR und der beiden
  RGs (P1 Schritt 8), Owner-Optionen Label-Scope und NRG-Lockdown
  (AKS-E4).
- **Egress-IP spät und nicht stabil:** Bekannt erst nach dem Create
  (ab 30.11.), neu bei jedem Neuaufbau (AKS-E11). Mit einer Allowlist
  liegen zwischen Create und LLM-Test (03.12.) nur wenige Tage, und
  jeder Neuaufbau wartet auf eine neue Freischaltung; das kann den
  Neuaufbau-Drill in P7 verlängern.
- **Contributor-Gleichrang:** Jedes Mitglied der Contributor-Gruppe
  von `azure-se` kann lokale Accounts einschalten und Cluster-Admin
  werden, sich eine Key-Vault-Policy setzen oder ein ACR-Token
  anlegen, und so an das GEBIT-Descriptor-Secret, den LiteLLM-Key
  (über die SAM-Datenbank) und die generierten Secrets kommen.
  Gegenmittel: Activity-Log-Alarme (Contributor darf sie anlegen) auf
  `managedClusters/write`, `listClusterAdminCredential/action`,
  `vaults/accessPolicies/write`, `registries/tokens/write` und
  `registries/generateCredentials/action`, angelegt in P1 vor dem
  Create (`foundation.sh pre`); der Owner klärt den Mitgliederkreis und
  prüft ihn gegen die GEBIT-Freigabe (AKS-E16). Die Grenze ist
  organisatorisch, nicht technisch.
- **Admin-Zertifikat aus dem Bootstrap:** Es bleibt bis zur Rotation
  gültig; `az aks rotate-certs` vor dem ersten Workload kostet bis 30
  min, im Neuaufbau-Drill erneut (AKS-E13).
- **Ablauf des ACR-Tokens:** Ein abgelaufenes Passwort fällt erst beim
  nächsten Pull auf, etwa beim Surge-Node am 26.01. (ImagePullBackOff).
  Gegenmittel: Ablauf nach dem Rückbau, Restlaufzeit im Preflight,
  `password2` als Rotationsreserve (AKS-E21).
- **Tag-Deny bei Cluster-Updates:** Laut einem Community-Report
  schrieben spätere `az aks update` und `az aks nodepool update` die
  Node-RG zeitweise ohne die Cluster-Tags und scheiterten mit
  RequestDisallowedByPolicy [Quelle:
  `github.com/Azure/AKS/issues/5856`, ohne Antwort von Microsoft].
  Betroffen wären etwa `--disable-local-accounts`, `aks-allow-me.sh`
  und der NRG-Lockdown. Gegenmittel: begrenzt wiederholen, bei einem
  Failed-State `az aks update -g gebit-showcase -n aks-eurocis` zum
  Reconcile [Quelle:
  `learn.microsoft.com/troubleshoot/azure/azure-kubernetes/error-codes/requestdisallowedbypolicy-error`];
  eine Ausnahme kann nur ein Subscription-Owner anlegen [A: P1
  beobachtet].
- **RG-Metadaten in West Europe:** Fällt die Region aus, laufen
  Schreibzugriffe auf `gebit-showcase` über eine Backup-Region
  (AKS-E2) [A: Risiko gering].

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

Stand 18.11.2026, nach den Owner-Entscheidungen vom 17.11. (ein Node
ohne HA, Free-Tier für das ganze Projekt, arm64, Traefik statt
ingress-nginx, öffentlich ohne WireGuard, Broker 10.26.0.9219 LTS)
und vom 18.11. (nur Contributor, keine Rollenzuweisungen; Cluster,
ACR und Key Vault in `gebit-showcase`, Node-RG
`gebit-showcase-nodes`). Quota, SKUs und Defender-Pläne stammen aus
dem read-only Azure-Check vom 18.11. [Quelle: read-only Azure-Check
mit az CLI 2.85.0 in der Subscription `azure-se`, 18.11.].

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
| AKS-Systempods auf einem Node [A] | 750m | 1536Mi | RA:414 nennt 0,3-0,5 CPU und 0,7-1 GiB je Node; die Deployments (CoreDNS, metrics-server, konnectivity je 2 Replikas) liegen jetzt alle auf dem einen Node; kein Defender-Sensor (3.3) |
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
[Quelle: SAM-Chart 2.3.10 values.yaml:555]. Dazu kommen der Pod von
`az aks command invoke` (Notweg bei fehlender IP-Freigabe, läuft mit
der Entra-Identität des Aufrufers unter Kubernetes-RBAC; 200m/500Mi
Requests, 500m/1Gi Limits [Quelle:
`learn.microsoft.com/azure/aks/access-private-cluster`; azure-cli dev
acs/custom.py, 18.11.]) und der HTTP-01-Solver von cert-manager. Mit
`prod1k` bleiben 695m frei: Ein awe-Update passt nicht sofort. Der
neue Pod (`demo-critical` als `globalDefault`) verdrängt dann einen
`demo-observability`-Pod (Preemption); Monitoring hat einige Minuten
eine Lücke, die Demo nicht. Mit `dev` (1695m frei) passt awe ohne
Verdrängung.

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
  cert-manager, Monitoring) über 2044m (geplant 1975m), überschreitet
  `prod1k` mit den restlichen 5150m die 92-%-Grenze (7194m von
  7820m), und P4 installiert `dev`. Ein Defender-Sensor zählt nur
  mit, falls entgegen dem Check vom 18.11. doch einer läuft (3.3).
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
  aber +219,6 EUR/Monat. Die Quota wäre da (32 vCPU mit Surge-Node;
  3.5), sie ist nicht der Grund.
- B-Serie (als System-Pool nicht unterstützt [Quelle:
  `learn.microsoft.com/azure/aks/use-system-pools`]), AKS Automatic und
  Node Auto-Provisioning (nicht stoppbar [Quelle:
  `learn.microsoft.com/azure/aks/node-auto-provisioning`]). AKS
  Automatic würde zudem beim Create eine Rollenzuweisung anlegen, die
  ein Contributor nicht darf [Quelle: azure-cli dev
  acs/managed_cluster_decorator.py, 18.11.].

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
  jedem nicht-zonalen Node]. `Standard_D8ps_v6` ist in Germany West
  Central in den Zonen 1-3 ohne Restriction verfügbar (SKU-Check
  18.11.); der frühere Rückfall `--zones 1` bei einer Restriction ist
  damit nicht nötig. Test in P1: Pool kurz auf 2 Nodes skalieren,
  einen Test-Pod mit PVC per cordon auf den zweiten Node zwingen,
  zurück auf 1 Node; das ist derselbe Weg wie beim Surge-Node.
- OS-Disk 128 GiB P10 managed: Dpsv6 hat keine ephemeral OS-Disk
  [Quelle: `learn.microsoft.com/azure/virtual-machines/sizes/general-purpose/dpsv6-series`;
  SKU-Check 18.11.]; die arm64-Images allein sind rund 17,6 GB
  unkomprimiert [Quelle: Befehl `docker system df -v`, 16.11.].
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
- Defender for Cloud: Laut Check vom 18.11. stehen alle für das
  Projekt relevanten Pläne auf Free (Containers, KubernetesService,
  ContainerRegistry, KeyVaults, VirtualMachines); nur Discovery und
  FoundationalCspm laufen als Standard, ohne Kostenwirkung hier. Ein
  Sensor-DaemonSet ist damit nicht zu erwarten [A: in P2 mit `kaks
  get ds -A` bestätigen]. Die Subscription ist geteilt; schaltet
  jemand einen Plan ein, ändern sich Kosten (3.4) und Node-Last.
  Re-Check der Pläne vor G4 [A].
- Die Node-Ressourcengruppe heißt fest `gebit-showcase-nodes`
  (`--node-resource-group`, nur beim Create setzbar; die RG darf
  vorher nicht existieren und ist später nicht umbenennbar) [Quelle:
  `learn.microsoft.com/azure/aks/faq`]. AKS legt sie selbst an und
  gibt ihr die Tags aus `--tags`, darunter die Pflicht-Tags `Owner`
  und `Created Date` (AKS-E1, P1 Schritt 4) [Quelle:
  `learn.microsoft.com/azure/aks/use-tags`]. Darin liegen VM-Scale-Set,
  OS-Disk, PVC-Disks, der Load Balancer, das AKS-verwaltete VNet, die
  AKS-verwaltete Outbound-IP und `pip-aks-ingress`.
- Kein BYO-Netz: Ein eigenes Subnetz bräuchte Network Contributor für
  die Cluster-Identität, also eine Rollenzuweisung; das verwaltete
  VNet in der Node-RG umgeht das [Quelle:
  `learn.microsoft.com/azure/aks/concepts-network-cni-overview`].
  Name und Adressraum stehen auf keiner Learn-Seite (beobachtet
  `aks-vnet-<n>` mit 10.224.0.0/12) [A]; gegen Pod-CIDR 10.244.0.0/16
  und Service-CIDR 10.0.0.0/16 gäbe es keine Überlappung. Nach dem
  Create mit `az network vnet list -g gebit-showcase-nodes -o table`
  protokollieren.
- `pip-aks-ingress` (Standard, statisch, DNS-Label `<p>`) entsteht
  direkt nach dem Create in `gebit-showcase-nodes` (P1 Schritt 4).
  Die Steuerungsebenen-Identität hat in ihrer Node-RG per Default
  Contributor, eine Rollenzuweisung entfällt [Quelle:
  `learn.microsoft.com/azure/aks/static-ip`]. Einen Lock gibt es
  nicht, weil Locks Owner oder User Access Administrator brauchen
  [Quelle:
  `learn.microsoft.com/azure/azure-resource-manager/management/lock-resources`].
  Folge: `az aks delete` löscht die Node-RG samt beider IPs und der
  PVC-Disks; das Label ist danach für jeden frei, und ein Neuaufbau
  braucht neue IPs und die Backups (AKS-E4, P7) [Quelle:
  `learn.microsoft.com/azure/aks/faq`]. Cluster, ACR und Key Vault
  liegen in `gebit-showcase` (RG in westeurope, Ressourcen in
  germanywestcentral) und überleben einen Neuaufbau.

Node-Image-Update auf einem Node:

1. AKS legt mit `max-surge 1` einen zweiten Node mit neuem Image an
   (8 vCPU mehr, rund 0,30 EUR je Stunde; die Quota reicht laut
   Check vom 18.11., 3.5) [Quelle:
   `learn.microsoft.com/azure/aks/auto-upgrade-node-os-image`].
2. Der alte Node wird gesperrt und geleert. Alle Pods starten auf dem
   neuen Node neu, die Azure-Disks hängen um, und die Images fehlen
   dort noch im Cache (rund 17,6 GB, aus ACR in derselben Region).
   Die Pulls laufen über das ACR-Token im Secret `acr-pull` (P1
   Schritt 3); ein abgelaufenes Token-Passwort fällt erst hier auf,
   als `ImagePullBackOff` auf dem neuen Node. Der Preflight vor dem
   26.01. prüft deshalb die Restlaufzeit [A: Ablauf nach dem Rückbau,
   Owner bestätigt]. Der Broker hat bis 1200 s Zeit zum
   Herunterfahren [Quelle: pubsubplus 3.10.0
   templates/solaceStatefulSet.yaml:57].
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
6. Fällt die freie regionale Quota der geteilten Subscription vor dem
   Refresh unter 16 vCPU (18.11.: 150 frei, 3.5), geht der Refresh
   ohne Surge (`--max-surge 0` mit `--max-unavailable 1`) [A: Flag in
   Azure CLI 2.93 prüfen]; der Ausfall dauert dann bis zum Reimage
   des Nodes.

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
Retail-API 17.11.]. Alle PVC-Disks entstehen in
`gebit-showcase-nodes`.

### 3.4 Kosten

Listenpreise Pay-as-you-go, EUR ohne MwSt., 730 h/Monat [Quelle:
Befehl `curl https://prices.azure.com/api/retail/prices` mit
`currencyCode=EUR`, `armRegionName` germanywestcentral, LB-Zähler
unter `Global`, 17.11.; Node, LB, Public IP und ACR am 18.11.
unverändert]. Nachtstopp = Laufzeit 10 h an 22 Arbeitstagen (220
Laufstunden je Monat) wie bisher.

| Posten | Ressourcengruppe | EUR/Monat 24/7 | EUR/Monat Nachtstopp | Quelle |
|---|---|---|---|---|
| 1 x D8ps_v6 (0,3007/h) | gebit-showcase-nodes | 219,5 | 66,2 | Retail-API |
| AKS Free-Tier, ganzes Projekt | gebit-showcase | 0 | 0 | Owner-Entscheidung 17.11. |
| Zeile "FreeTierInfrastructureCost Uptime SLA" (0,0449/h ab 01.10.2026) | gebit-showcase [A: am Cluster-Objekt] | 0-32,8 | 0-32,8 [A: 9,9 bei Abrechnung nur der Laufzeit] | Retail-API, ohne Doku |
| OS-Disk P10 | gebit-showcase-nodes | 19,5 | 19,5 | Retail-API 19,4623 |
| Broker-PVC P10 | gebit-showcase-nodes | 19,5 | 19,5 | Retail-API |
| Premium-PVCs P3, P3, P4 | gebit-showcase-nodes | 10,8 | 10,8 | Retail-API (P3 2,8008, P4 5,213) |
| Standard-SSD-PVCs E2, E3, E3, E2 | gebit-showcase-nodes | 3,2 + bis rund 6 Transaktionen [A] | 3,2 + bis rund 2 [A] | Retail-API (E2 0,5386, E3 1,0772) |
| Standard LB, 3 Regeln (TCP 80, TCP 443, Outbound) | gebit-showcase-nodes | 16,4 | 16,4 [A: läuft im Stopp weiter] | Retail-API 0,0224/h für die ersten 5 Regeln |
| 2 Standard-Public-IPs: `pip-aks-ingress` (DNS-Label) und die AKS-verwaltete Outbound-IP | gebit-showcase-nodes | 6,6 | 6,6 [A: beide bleiben im Stopp bestehen] | Retail-API 0,0045/h je IP (Zähler "Standard IPv4 Static Public IP") |
| ACR Basic (0,1496/Tag), Pull-Token ohne Aufpreis | gebit-showcase | 4,6 | 4,6 | Retail-API [A: bis 10 GiB inklusive, darüber 0,0898/GB; Tokens ohne eigene Preisposition] |
| Key Vault im Access-Policy-Modus (0,0269 je 10.000 Operationen) | gebit-showcase | unter 0,1 | unter 0,1 | Retail-API |
| Defender for Cloud | - | 0 | 0 | Check 18.11.: alle relevanten Pläne Free (3.3) |
| Datenabfluss ins Internet, LB-Datenverarbeitung | gebit-showcase-nodes [A] | rund 0 | rund 0 | Retail-API: die ersten 100 GB/Monat frei, LB 0,0045/GB [A: Demo unter 10 GB] |
| **Summe Messe-Konfiguration** | | **rund 300-340** | **rund 145-185** | |

- **Rechnung:** 24/7 ohne Free-Tier-Zeile 300,0 EUR, mit ihr 332,8 EUR,
  plus Transaktionen. Nachtstopp: 80,5 EUR Fixkosten (Disks, LB, IPs,
  ACR, KV) plus 66,2 EUR Node = 146,7 EUR; mit der Free-Tier-Zeile
  156,6 EUR (nur Laufzeit) bis 179,5 EUR (jede Stunde), plus
  Transaktionen.
- **Outbound-IP:** Ohne BYO-IP (die bräuchte außerhalb der Node-RG
  eine Rollenzuweisung) legt AKS genau eine Standard-SKU-IP in der
  Node-RG an und verwaltet sie selbst [Quelle:
  `learn.microsoft.com/azure/aks/load-balancer-standard`;
  `learn.microsoft.com/azure/aks/configure-load-balancer-standard`].
  Standard-IPs sind immer statisch [Quelle:
  `learn.microsoft.com/azure/virtual-network/ip-services/public-ip-addresses`],
  und die Retail-API kennt für Standard nur den Zähler "Standard IPv4
  Static Public IP" mit 0,0045/h [Quelle: Retail-API 18.11.]. Die
  Outbound-IP kostet also wie die frühere `pip-aks-egress`; die Summe
  ändert sich nicht.
- **LB-Regeln:** Traefik ist der einzige LoadBalancer-Service, mit TCP
  80 und 443 auf `pip-aks-ingress`; dazu die Outbound-Regel auf der
  AKS-verwalteten Outbound-IP. Mit 3 Regeln bleibt es beim
  Grundpreis 0,0224/h; ab der sechsten Regel kostet jede 0,009/h
  (6,57 EUR/Monat). Ausgehende Regeln zählen mit, eingehende
  NAT-Regeln nicht [Quelle:
  `azure.microsoft.com/pricing/details/load-balancer`]. Die VAP (nur
  der Service `traefik/traefik` darf LoadBalancer sein, P2 Schritt 3)
  hält das so.
- **Gegenüber dem 16.11.:** rund 300 EUR/Monat weniger bei 24/7; die
  Posten je Owner-Entscheidung und die verworfene Variante mit 6
  DNS-Labels (7 IPs, 13 LB-Regeln, rund 69 EUR/Monat mehr) stehen in
  8.5.
- **Gegenüber dem 17.11.:** Die Summen bleiben. Die Entscheidung vom
  18.11. verschiebt nur Posten: LB und beide IPs liegen in
  `gebit-showcase-nodes`, die verwaltete Outbound-IP ersetzt
  `pip-aks-egress` zum gleichen Preis, ACR-Token und Access Policies
  kosten nichts extra. Der bedingte Defender-Zuschlag (bis rund
  +49 EUR/Monat bei 24/7) entfällt, weil alle Pläne Free sind.
- **Aufteilung je RG (24/7):** `gebit-showcase` rund 4,6 EUR (ACR,
  Key Vault) plus 0-32,8 EUR, falls die Free-Tier-Zeile am
  Cluster-Objekt abgerechnet wird [A]; `gebit-showcase-nodes` rund
  295 EUR (Node, Disks, LB, beide IPs) plus bis rund 6 EUR
  Transaktionen. Ein Budget nur auf `gebit-showcase` sähe also
  höchstens rund 38 von 300-340 EUR; die Node-RG gehört in den
  Filter.
- **Free-Tier:** Die Steuerungsebene hat kein Uptime-SLA; das betrifft
  kubectl und helm, nicht die laufenden Pods. Die Preiszeile
  "FreeTierInfrastructureCost Uptime SLA" steht seit 01.10.2026 in der
  Retail-API, ohne Doku [Quelle: Retail-API 17.11.;
  `azure.microsoft.com/pricing/details/kubernetes-service`]. Nach Tag 1
  im Cost Management prüfen, ob und wann sie abgerechnet wird.
- **Mit Stopp (Aufbau):** Im Stopp laufen Disks, beide IPs, LB [A],
  ACR und KV weiter: rund 80,5 EUR/Monat. Dass Ingress- und
  Outbound-IP Stopp und Start unverändert überstehen, ist nicht
  dokumentiert [A: Messung in P1]. Der Node kostet 0,30 EUR je
  Laufstunde (0,35 mit Free-Tier-Zeile).
- **Neuaufbau:** `az aks delete` gibt beide IPs frei, der Create legt
  neue an. Die Kosten bleiben gleich; neu zu binden sind aber das
  Label `<p>` auf der neuen `pip-aks-ingress` und die neue Egress-IP
  beim LiteLLM-Betreiber (AKS-E4, AKS-E11, P7).
- **amd64-Variante (nicht geplant, AKS-E3):** 1 x
  D8as_v6 (0,3941/h) kostet +68,2 EUR/Monat bei 24/7, +20,5 EUR mit
  Stopp. Rückfall-Familie Dpsv5 (D8ps_v5, 0,3304/h): +21,7 bzw. +6,5
  EUR. Beide SKUs sind laut SKU-Check vom 18.11. ohne Restriction.
- **Defender for Cloud:** 0 EUR, alle relevanten Pläne Free (3.3).
  Schaltet jemand in der geteilten Subscription Defender for
  Containers ein, kämen 0,0084 EUR je vCore-Stunde dazu, also 49,1
  EUR/Monat bei 24/7 (8 vCores) und 14,8 EUR/Monat mit Nachtstopp
  [Quelle: Retail-API 17.11.]; der Re-Check vor G4 fängt das [A].
- **SecurityPatch-VHDs:** Die Node-OS-Updates im Kanal SecurityPatch
  legen VHDs in `gebit-showcase-nodes` ab; sie kosten einige EUR
  [Quelle: `learn.microsoft.com/azure/aks/auto-upgrade-node-os-image`;
  A: Höhe].
- **Projektsumme** (Free-Tier durchgehend, Nachtstopp bis G4, ab 05.02.
  24/7, Rückbau 20.02.2027) [A: Laufmuster]:
  - November rund 6 EUR (vor P1 keine Azure-Ressource; Cluster, beide
    IPs, ACR und Key Vault ab 30.11. aus P1);
  - Dezember rund 135-185 EUR (180-230 Laufstunden, Feiertage
    gestoppt);
  - Januar rund 140-190 EUR (200-250 Laufstunden inkl. 24-h-Lauf
    18./19.01.);
  - Februar bis 20.02. rund 180-210 EUR (Nachtstopp bis 04.02., dann
    24/7, zusammen rund 425-435 Laufstunden).
  - Gesamt rund 460-590 EUR ohne LLM-Token (Summe der Monate 461-591 EUR);
    Defender kommt nicht mehr dazu. Das liegt deutlich unter dem Ziel von 1.500
    EUR (AKS-E1). Das obere Ende enthält die Free-Tier-Zeile für jede Stunde und
    die Disk-Transaktionen.
- **Budget (AKS-E1):** ein Budget auf Subscription-Ebene `azure-se`,
  gefiltert auf `ResourceGroupName` in `gebit-showcase` und
  `gebit-showcase-nodes`; Zeitraster monatlich, **250 EUR** (statt
  450 EUR), 01.12.2026 bis 31.03.2027; Benachrichtigung bei Actual
  100 % und Forecast 100 % per Mail. Recht: Contributor darf eigene
  Budgets anlegen, ändern und löschen, auch auf Subscription-Ebene mit
  RG-Filter [Quelle:
  `learn.microsoft.com/azure/cost-management-billing/costs/tutorial-acm-create-budgets`].
  Anlage in P1 nach dem Create, weil `gebit-showcase-nodes` erst dann
  existiert. Der feste Name der Node-RG hält den Filter über
  Neuaufbauten stabil. Annahmen: `gebit-showcase` enthält nur
  Showcase-Ressourcen, sonst zählt das Budget fremde Kosten mit [A];
  Cost Management ist für den Angebotstyp von `azure-se` verfügbar
  [A: P0 prüft read-only, im Portal unter "Budgets" oder mit `az
  consumption budget list`; die CLI-Gruppe ist Preview, Learn rät zu
  REST oder Portal]. Alternative: je RG ein Budget mit geteiltem
  Betrag. Begründung der Höhe: Die erwarteten Monate liegen bei
  135-210 EUR, ein Monat 24/7 bei 300-340 EUR; 450 EUR würde nicht
  einmal einen ganzen vergessenen Monat melden. Budgets setzen sich je
  Periode zurück, Kostendaten kommen mit 8-24 h Verzug [Quelle:
  dito]. Zweck: ein mehrtägig vergessener Stopp im Dezember oder
  Januar und Restkosten im März (ein weiterlaufender Cluster mit rund
  10-11 EUR/Tag hebt den Forecast innerhalb weniger Tage über 250 EUR
  [A: Forecast-Modell]). Im Februar (24/7 ab 05.02.) löst der Forecast
  sehr wahrscheinlich aus, weil er den Rückbau am 20.02. nicht kennt;
  das ist erwartet. Die Projektsumme läuft separat über eine
  gespeicherte Cost-Analysis-Ansicht mit demselben Filter im
  wöchentlichen Kosten-Check; den vergessenen Nachtstopp fängt der
  Abend-Check (P1). Das Azure-Budget sieht keine LLM-Kosten; die
  begrenzen der Messe-Key (O5) und seine rpm-/tpm-Limits (AKS-E11).

### 3.5 Quota

Geprüft am 18.11., kein Antrag nötig [Quelle: read-only Azure-Check
mit az CLI 2.85.0, Subscription `azure-se`, 18.11.]:

| Quota (Germany West Central) | Bedarf | Stand 18.11. (belegt von Limit) |
|---|---|---|
| Standard DPSv6 Family vCPUs | 16 (8 für den Node + 8 für den Surge-Node beim Node-Image-Update; ebenso beim 2-Node-Test in P1) | 0 von 350 |
| Standard DPSv5 Family vCPUs (arm64-Rückfall `Standard_D8ps_v5`) | 16, nur bei einem Wechsel der Familie | 0 von 350 |
| Total Regional vCPUs | 16 | 200 von 350 (150 frei) |
| Public IPs | 2 (`pip-aks-ingress`, AKS-verwaltete Outbound-IP) | 7 von 1000 |
| Standard Load Balancers | 1 (der AKS-LB in `gebit-showcase-nodes`) | 0 von 1000 |

SKU-Lage am selben Tag (Compute-SKU-API): `Standard_D8ps_v6` Arm64,
Zonen 1-3, keine Restriction, keine ephemeral OS-Disk;
`Standard_D8ps_v5` und `Standard_D8as_v6` ebenfalls ohne
Restriction. Andere Familien (amd64, B-Serie) braucht der Plan nicht
(AKS-E3). Der Surge-Node bleibt Pflicht, sonst gilt der Weg ohne
Surge aus 3.3 Punkt 6. Der Resource Provider Microsoft.Quota ist
nicht registriert und wird nicht gebraucht.

Damit entfällt der frühere Ablauf (Antrag am 20.11. über "My quotas",
DPSv5 nur bei Restriction, Support-Fall bei "not available for
increase"); P0 Schritt 4 ist ein erledigter Check.

Re-Check, weil die Subscription geteilt ist und andere schon 200
regionale vCPUs belegen (read-only, `az vm list-usage -l
germanywestcentral -o table` und `az network list-usages -l
germanywestcentral -o table`):

- direkt vor dem Create (P1 Schritt 1);
- vor dem Node-Image-Refresh am 26.01.2027 (Surge-Node, 8 vCPU mehr);
- vor G4 (05.02.).

Grenzen: Unter 16 freien regionalen vCPU läuft der Refresh ohne Surge
(3.3 Punkt 6). Unter 8 scheitern schon Create und Neuaufbau.
Dann stellt der Owner einen Antrag über "My quotas"; dafür reicht
Contributor, und eine freigegebene Familien-Quota hebt die regionale
Quota mit an [Quelle:
`learn.microsoft.com/azure/quotas/per-vm-quota-requests`]. Ob der
Antrag die Registrierung von Microsoft.Quota verlangt, ist offen [A].

## 4. Vorgehen in Phasen

| Phase | Inhalt | PT | Kalender | Gate |
|---|---|---|---|---|
| P0 | Vorbereitung, Klärungen, Azure-Checks (am 18.11. erledigt: Rechte, Policies, Quota, SKUs, Defender), Wahl und Prüfung des DNS-Labels `<p>`, Sicherheitsgeländer, Lab-Broker-Upgrade einplanen | 2,25 | KW47-48 (16.-27.11.) | - |
| P1 | Azure-Grundlagen nur mit Contributor: Cluster in `gebit-showcase` (1 Node, Free-Tier, Pflicht-Tags, Node-RG `gebit-showcase-nodes`), Zugriff per Entra ID und Kubernetes-RBAC (Bootstrap, lokale Accounts aus), ACR mit Pull-Token, Key Vault mit Access Policies, `pip-aks-ingress` mit DNS-Label, Egress-IP an den LiteLLM-Betreiber, Budget, CLI, API-Server-Allowlist, Hairpin-Test | 2,25 | KW49 (30.11.-04.12.) | Prüfpunkt 04.12. |
| P2 | Plattform-Add-ons (Traefik, cert-manager mit HTTP-01, VAP, Monitoring), Pull-Secret `acr-pull` je Namespace | 3,0 | KW49-50 (03.-10.12.) | - |
| P3 | Keycloak unter `/auth` | 1,25 | KW50 (10.-11.12.) | Prüfpunkt 11.12. (P2 + P3) |
| P4 | Broker 10.26.0.9219: Teil A Lab-Broker-Upgrade (1,0 PT, eigenes Go), Teil B AKS (1,25 PT) | 2,25 | Teil A KW48-49 (bis 04.12., spätestens 10.12.), Teil B KW51 (14.-15.12.) | Prüfpunkt 04.12. (Teil A) |
| P5 | SAM | 2,5 | KW51 (15.-17.12.), 0,5 PT Puffer bis 18.12. | G2a 18.12. |
| P6 | GEBIT-Demo portieren, Image 0.1.4 mit gemeinsamem Reflection-Endpunkt | 5,75 | KW52-KW1 (Vorarbeit im Lab), KW1-2 auf AKS | G2b 15.01. |
| P7 | Härtung und Betrieb, Neuaufbau-Drill mit neuer Ingress- und Egress-IP und Neubindung des Labels | 4,25 | KW3-KW7 | G3 22.01., G4 05.02. |
| | **Summe** | **23,5** (mit 15 % Puffer von 3,5 PT rund 27,0) | | |

Wer: "Claude" heißt Skripte schreiben, read-only prüfen und
Schreibbefehle erst nach Freigabe des Owners je Schritt ausführen.
"Owner" heißt Logins, Passwörter, Freigaben, Wahl des DNS-Labels,
Konten (etwa beim ACME-Rückfall-CA) und Kontakte. "C" ist die dritte
Person aus O9 (ab 23.11.); die PT des Plans sind ihr Aufwand, bis auf
0,5 PT von P0 in KW47 (Owner und Claude).

Namen: `<p>` ist das DNS-Label der Ingress-IP (AKS-E4), `<fqdn>`
steht für `<p>.germanywestcentral.cloudapp.azure.com`. Das ist der
einzige öffentliche Name des Projekts; alle Apps hängen per Pfad
darunter. Ressourcengruppen: `gebit-showcase` (vom Owner angelegt,
westeurope, mit Cluster, ACR und Key Vault in germanywestcentral)
und `gebit-showcase-nodes` (legt AKS beim Create an). Die Ingress-IP
`pip-aks-ingress` liegt in der Node-RG und lebt nur so lange wie der
Cluster; ein Cluster-Delete gibt IP und Label frei.

Rechte-Regel für alle Phasen (Owner-Entscheidung 18.11., AKS-E21):
Jeder Azure-Schritt kommt mit Contributor aus. Der Plan legt keine
Rollenzuweisung, keinen Lock und keine Policy-Ausnahme an und nutzt
keine Flags, die eine Zuweisung auslösen; die Liste der tabuisierten
Befehle und Flags sowie die Regeln zu `-l germanywestcentral` (nur
regionale Ressourcen), Tags, `az group delete` und `set -x` stehen in
1.4.

Kontext-Regel für alle Phasen: Jeder AKS-Befehl in diesem Plan läuft
über `kaks`/`haks` (P1 Schritt 6) oder über ein Skript, das
`require_kube_context aks-eurocis` aufruft. Lab-Befehle tragen
`--context rancher-desktop`. Ausgenommen ist nur `helm template` ohne
`--validate`, weil es keinen Cluster kontaktiert.

### P0 Vorbereitung und Klärungen (2,25 PT, 16.-27.11.)

**Ziel:** Azure-Lage geklärt (am 18.11. read-only erledigt), die
Owner-Entscheidungen vom 17.11. und 18.11. (AKS-E1 bis AKS-E21) im
PLAN verankert, DNS-Label `<p>` gewählt und geprüft, Mac-Tools
aktualisiert, Lab-Broker-Upgrade terminiert, Lab gegen Verwechslung
mit AKS geschützt, bevor eine AKS-Credential auf dem Mac existiert.
In P0 entsteht keine Azure-Ressource: Die Ingress-IP legt erst P1 nach
dem Create in der Node-RG an, die Egress-IP verwaltet AKS selbst
(Owner-Entscheidung 18.11.).

"Azure-Check 18.11." heißt in diesem Plan: read-only-Abfragen mit
Azure CLI 2.85.0 nach dem `az login` des Owners am 18.11.2026 (Konto,
Rollen, Provider, Usages, SKUs, AKS-Versionen, Policy-Zuweisungen,
Defender-Pläne).

**Schritte:**

1. Erledigt am 18.11.: Der Owner hat sich neu angemeldet. Ergebnis:
   Die einzige Subscription ist `azure-se` (Enabled, Default). Der
   Owner hat dort Contributor über eine Gruppe und "Azure Service Bus
   Data Sender", weder Owner noch User Access Administrator. Er hat
   die Ressourcengruppe `gebit-showcase` angelegt (westeurope, Tags
   `Owner` und `Created Date` im Format dd.mm.yyyy). Der
   AADSTS9002313-Fehler vom 16.11. ist damit erledigt [Quelle:
   Azure-Check 18.11.]. Tenant-ID, Subscription-ID und Tag-Werte
   stehen nur lokal, nie in diesem Dokument.
2. Erledigt am 18.11. (Claude, read-only) [Quelle: Azure-Check 18.11.]:
   - Provider registriert: ContainerService, ContainerRegistry,
     KeyVault, Network, Compute, ManagedIdentity,
     OperationsManagement, Insights, Security. `Microsoft.Quota` ist
     nicht registriert und wird nicht gebraucht (kein Antrag,
     Schritt 4).
   - AKS-Versionen in Germany West Central: 1.36 (Default, neuester
     Patch 1.36.5), 1.37 (1.37.1), 1.35 (1.35.9).
   - SKUs: `Standard_D8ps_v6` Arm64, Zonen 1-3, ohne Restriction, ohne
     ephemeral OS-Disk; `Standard_D8ps_v5` und `Standard_D8as_v6`
     ebenfalls ohne Restriction.
   - Quota: Schritt 4.
   - Policies auf der Subscription: 2 x "Require a tag on resource
     groups" (Effekt deny; Tags `Owner` und `Created Date`), 2 x
     "Inherit a tag from the resource group" (modify, dieselben Tags),
     "ASC Default" (audit). Folgen: Jede neue RG braucht beide Tags.
     AKS legt seine Node-RG selbst an, also gibt `az aks create` die
     Tags per `--tags` mit; sie gehen an den Cluster, seine Ressourcen
     und die Node-RG [Quelle:
     `learn.microsoft.com/azure/aks/use-tags`]. Die Inherit-Policy
     setzt `Owner` und `Created Date` an jeder Ressource einer RG auf
     die Werte der RG, auch wenn ein anderer Wert mitkommt [A: gilt,
     wenn die Zuweisungen die Built-in-Definitionen nutzen; Rest-Check
     unten; Quelle: `github.com/Azure/azure-policy`,
     Tags/InheritTag_AddOrReplace_Modify.json]. Die Deny-Policy prüft
     nur, ob ein Tag da ist, nicht Wert oder Format [Quelle:
     Tags/ResourceGroupRequireTag_Deny.json].
   - Rollen: Contributor hat `Microsoft.Authorization/*/Write` und
     `Microsoft.Authorization/*/Delete` als NotActions, also keine
     Rollenzuweisungen, keine Locks und keine Policy-Exemptions
     [Quelle:
     `learn.microsoft.com/azure/role-based-access-control/built-in-roles/privileged`;
     `learn.microsoft.com/azure/azure-resource-manager/management/lock-resources`].
     Enthalten sind unter anderem `listClusterAdminCredential`,
     `listClusterUserCredential`, `runCommand`,
     `rotateClusterCertificates`, `vaults/accessPolicies/write`,
     `registries/tokens/write` und eigene Budgets [Quelle: dieselbe
     Rollenseite;
     `learn.microsoft.com/azure/cost-management-billing/costs/tutorial-acm-create-budgets`].
   - Defender for Cloud: Alle Pläne sind Free (unter anderem
     Containers, KubernetesService, ContainerRegistry, KeyVaults,
     VirtualMachines), nur Discovery und FoundationalCspm sind Standard
     und hier ohne Kostenwirkung. Kein Defender-Sensor, keine
     Defender-Kosten; Re-Check vor G4 [A].

   Antworten auf die früheren Klärungsfragen, nach der
   Owner-Entscheidung vom 18.11. (keine Rollenzuweisungen, alles mit
   Contributor):
   - Rollen zuweisen: nein. Daher kein `--attach-acr`, kein Azure RBAC
     für Kubernetes, keine Network-Contributor-Zuweisung, keine
     Key-Vault-Datenrolle, keine eigene Rolle für den Stellvertreter.
   - Locks setzen: nein. Daher kein Lock auf der Ingress-IP
     (Schritt 5).
   - Key-Vault-Datenrollen: entfallen, der Vault läuft im
     Access-Policy-Modus (P1 Schritt 3).
   - Budget: Contributor reicht (P1 Schritt 8).

   Rest, Claude read-only bis 27.11.:

   ```bash
   az group show -n gebit-showcase --query "{l:location,t:tags}" -o json
   # Zuweisungen inkl. der geerbten; Built-in oder Custom an der ID
   az policy assignment list --filter "atScope()" \
     --query "[].{n:displayName,d:policyDefinitionId,e:enforcementMode}" \
     -o table
   # nur für IDs /providers/Microsoft.Authorization/policyDefinitions/<guid>
   az policy definition show --name <guid> \
     --query "{n:displayName,m:mode,e:policyRule.then.effect}"
   # Cost Management für den Angebotstyp verfügbar? (Preview-Gruppe)
   az consumption budget list -o none && echo ok
   # optional, schriftlicher Beleg der NotActions
   az rest --method get --url "/subscriptions/{subscriptionId}/providers/\
   Microsoft.Authorization/permissions?api-version=2022-04-01" \
     --query "value[].notActions"
   ```

   `az policy assignment list` zeigt ohne `--filter` nur Zuweisungen genau auf
   der Subscription; geerbte Deny-Policies fehlten dann [Quelle: azure-cli
   2.85.0 resource/policy.py:231-237]. Built-in oder Custom zeigt schon die
   `policyDefinitionId`: Präfix
   `/providers/Microsoft.Authorization/policyDefinitions/<guid>` (bzw.
   `.../policySetDefinitions/` für Initiativen wie "ASC Default") ist Built-in,
   `/subscriptions/...` oder
   `/providers/Microsoft.Management/managementGroups/...` ist Custom. `az policy
   definition show` läuft nur für Built-ins: Es sucht in der Subscription und
   unter den Built-ins, eine Custom-Definition auf Management-Group-Ebene
   bräuchte `--management-group` und Leserecht dort, das Contributor auf
   Subscription-Ebene nicht hat [Quelle: `az policy definition show --help`,
   2.85.0]. Die Regel einer solchen Definition geht als Frage an den
   Subscription-Owner (Frage 6). `az rest` setzt `{subscriptionId}` selbst ein,
   die ID erscheint nirgends. Die Tag-Werte von `gebit-showcase` erscheinen nur
   im Terminal. Offen bleibt die Anmeldehäufigkeit per Conditional Access (Frage
   an die IT); bei kurzer Frequenz plant P7 eine tägliche Neuanmeldung.
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

   Am 18.11. hat der Owner entschieden: keine Rollenzuweisungen, alles
   mit Contributor. Daraus folgen RG `gebit-showcase` für Cluster, ACR
   und Key Vault (Ressourcen in germanywestcentral), die Node-RG
   `gebit-showcase-nodes`, kein BYO-VNet, `pip-aks-ingress` in der
   Node-RG ohne Lock, die AKS-verwaltete Outbound-IP als Egress-IP,
   ACR-Pull per Token, Entra ID mit Kubernetes-RBAC und der Key Vault
   im Access-Policy-Modus. Betroffen sind laut Abschnitt 2 (Stand
   18.11.) AKS-E4, AKS-E5, AKS-E11, AKS-E12, AKS-E13, AKS-E17 und
   AKS-E20 (geändert) sowie AKS-E1 und AKS-E2 (ergänzt). Neu zu entscheiden,
   bis 27.11. und damit vor dem Create (bis auf den Lockdown); bis
   dahin gilt die Empfehlung:
   - Tag-Werte: Der Owner hat `Owner` und `Created Date` auf
     `gebit-showcase` gesetzt. Cluster, Node-RG und alle Ressourcen
     tragen dieselben Werte; P1 liest sie zur Laufzeit aus der RG und
     schreibt sie nie in eine Datei. Ein eigenes `Created Date` für die
     Node-RG ist praktisch nicht möglich, weil die Inherit-Policy den
     Cluster-Tag ohnehin auf den RG-Wert setzt [A]. Empfehlung: so
     akzeptieren.
   - Zugang zum Cluster: einmaliger Bootstrap mit dem
     Admin-Zertifikat, danach lokale Accounts aus und `az aks
     rotate-certs` (P1 Schritt 6; Empfehlung). Alternative: eine
     eigene Entra-Sicherheitsgruppe (Owner und Stellvertreter) und
     `--aad-admin-group-object-ids <group-objectId>` beim Create; dann
     gibt es kein Admin-Zertifikat und keine Rotation. Geht nur, wenn
     der Tenant dem Owner das Anlegen von Gruppen erlaubt; die Gruppe,
     über die er Contributor hat, kommt nicht in Frage [A:
     Mitgliederkreis].
   - DNS-Label-Optionen (bis 27.11., vor dem Anlegen in P1 Schritt
     4a; Schritt 5): Label-Scope oder IP-Umzug; Empfehlung: keins von
     beiden.
   - Node-RG-Lockdown `ReadOnly` als Ersatz für den Lock (P1 Schritt
     4, P2 Schritt 10): nicht bis 27.11., sondern nach dem LB-Nachweis
     in P2 (P2 Schritt 10, Frage 29).
   - Ablauf des ACR-Token-Passworts: 2027-02-28T23:59:59Z (gleich
     `deleteAfter`, nach der Messe) [A].
   - Contributor-Gleichrang: Jedes Mitglied der Contributor-Gruppe
     von `azure-se` kann sich im Access-Policy-Modus selbst Zugriff
     auf die Key-Vault-Secrets geben [Quelle:
     `learn.microsoft.com/azure/key-vault/general/assign-access-policy`]
     und mit `az aks update --enable-local-accounts` plus `az aks
     get-credentials --admin` Cluster-Admin werden [Quelle:
     `learn.microsoft.com/azure/aks/local-accounts`], also auch
     GEBIT-Descriptor-Secret und LiteLLM-Key lesen. Der Owner
     akzeptiert das oder klärt es mit dem Subscription-Owner und
     prüft es gegen die GEBIT-Freigabe (AKS-E16: Zugriff "Owner und
     Stellvertretung"). Gegenmittel sind nur Activity-Log-Alarme (P1
     Schritt 8).
   - Kostenstelle aus O4 (PLAN 0.5) [A: offen].
4. Erledigt am 18.11., ohne Antrag: Quota-Check für Germany West
   Central (3.5) [Quelle: Azure-Check 18.11.]. Standard DPSv6 Family
   0 von 350 vCPU, Standard DPSv5 Family 0 von 350, Total Regional 200
   von 350 (150 frei; Bedarf 16 mit dem Surge-Node), Public IPs 7 von
   1000 (Bedarf 2: `pip-aks-ingress` und die AKS-verwaltete
   Outbound-IP), Standard-LBs 0 von 1000. Weil die Subscription
   geteilt ist, prüft P1 Schritt 1 direkt vor dem Create erneut, ebenso
   P7 vor dem Refresh am 26.01. Fallen die freien regionalen vCPU unter
   16, gilt der Weg ohne Surge aus 3.3 Punkt 6, und der Owner stellt
   dann den Antrag.
5. Owner, bis 20.11.: DNS-Label `<p>` wählen; Claude prüft read-only.
   Eine Anlage von RG und IPs in P0 entfällt. Die frühere Anlage von
   `rg-eurocis-base` mit nur `purpose` und `deleteAfter` hätte die
   Tag-Policy ohnehin abgelehnt. `<p>` ist neutral, ohne Kunden- oder
   Projektnamen, weil der Name mit dem ersten Zertifikat in den
   öffentlichen CT-Logs steht [A]; 3-63 Zeichen nach
   `^[a-z][a-z0-9-]{1,61}[a-z0-9]$` [Quelle: Recherche 17.11.;
   PSRule-Regel Azure.PublicIP.DNSLabel]. Dazu ein Ersatz-Label, falls
   `<p>` bis zum Create belegt wird.

   ```bash
   nslookup <p>.germanywestcentral.cloudapp.azure.com  # NXDOMAIN
   az rest --method get --url "/subscriptions/{subscriptionId}/\
   providers/Microsoft.Network/locations/germanywestcentral/\
   CheckDnsNameAvailability?domainNameLabel=<p>&api-version=2024-05-01" \
     --query available                   # true
   ```

   Gründe:
   - Ein Label gehört zu genau einer Public IP; Subdomains oder
     Wildcards darunter gibt es nicht [Quelle: learn.microsoft.com,
     Seite "public-ip-addresses"; Befehl `dig`, 17.11.]. Ein Name,
     eine Ingress-IP (AKS-E4).
   - Das Label hängt an der IP, nicht am Service. Die IP entsteht in
     P1 Schritt 4 in der Node-RG `gebit-showcase-nodes`: Nur dort
     bindet der Cluster eine selbst angelegte IP ohne Rollenzuweisung,
     weil seine Control-Plane-Identität per Default Contributor auf
     der Node-RG hat [Quelle: `learn.microsoft.com/azure/aks/static-ip`;
     `learn.microsoft.com/azure/aks/managed-identity-overview`]. Einen
     Lock kann der Owner nicht setzen (Schritt 2).
   - Folge: Wer den Cluster löscht, löscht die Node-RG samt IP, und
     das Label ist danach für jeden in der Region frei [Quelle:
     `learn.microsoft.com/azure/aks/faq`; learn public-ip-addresses].
     Ein Neuaufbau bindet `<p>` sofort neu (P7). Zwischen der Wahl am
     20.11. und dem Create (ab 30.11.) und bei jedem Neuaufbau kann ein
     Dritter `<p>` belegen; deshalb prüft P1 Schritt 4 die
     Verfügbarkeit direkt vor der Anlage erneut.
   - Der Traefik-Service nutzt `azure-pip-name`, nie
     `azure-dns-label-name`: Der Cloud-Provider fasst das Label nur an,
     wenn diese Annotation da ist, und ein leerer Wert löscht es
     [Quelle: `learn.microsoft.com/azure/aks/static-ip`;
     `cloud-provider-azure.sigs.k8s.io/topics/loadbalancer`;
     cloud-provider-azure azure_loadbalancer.go, Stand 18.11.].
   - Der Endpunkt `CheckDnsNameAvailability` ist nur über die
     Recherche belegt [A]; maßgeblich sind NXDOMAIN und ein
     erfolgreicher Create, denn Azure lehnt ein vergebenes Label ab.

   Owner-Optionen gegen das freigegebene Label, Entscheidung bis
   27.11., vor P1 Schritt 4a (Empfehlung: keine):
   - (a) Label-Scope `--dns-name-scope SubscriptionReuse` beim Anlegen
     der IP: Ein Neuaufbau in `azure-se` bekommt dasselbe FQDN, andere
     Subscriptions nicht. Das FQDN erhält einen Hash-Anteil
     (`<p>.<hash>.germanywestcentral.cloudapp.azure.com`, dann gilt
     dieser Name als `<fqdn>`), der Scope ist nur beim Anlegen setzbar,
     und die Funktion ist Public Preview ohne SLA [Quelle: learn
     public-ip-addresses, "Domain Name Label Scope"]. Mit Scope
     wiederholt P1 Schritt 4a die Verfügbarkeitsprüfung in der
     gescopten Form.
   - (b) Die IP schon in P0 in `gebit-showcase` anlegen und nach dem
     Create per `az resource move` in die Node-RG schieben, vor einem
     Neuaufbau zurück. Standard-IPs dürfen innerhalb einer
     Subscription die RG wechseln [Quelle:
     `learn.microsoft.com/azure/azure-resource-manager/management/move-limitations/networking-move-limitations`];
     ob der Move in die AKS-Node-RG geht und das Label ihn übersteht,
     ist ungeprüft [A].

   Kosten vor P1: keine. Keine DNS-Zone, kein Azure DNS, kein DNS-01
   (AKS-E4).
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
     kein GEBIT-Material nach Azure. Dazu der Contributor-Gleichrang
     aus Schritt 3.
   - LiteLLM-Betreiber in zwei Stufen. Am 20.11.: Gibt es eine
     Quell-IP-Allowlist, gilt sie auch für `/v1/*`, wie lange dauert
     eine Freischaltung und eine Änderung, kommt ein Messe-Key (O5)?
     Dazu der Missbrauchsschutz (AKS-E11): `rpm_limit` und `tpm_limit`
     auf dem Messe-Key, neben `max_budget` 150 USD [Quelle:
     `docs.litellm.ai/docs/proxy/users`]; Werte nach der Lab-Messung
     in P5 [A]. Den Key setzt der Betreiber; sein Wert landet nur in
     SAMs Modellkonfiguration. Hinweis: Das Lab erreicht den Proxy
     heute ohne Firmen-VPN, eine Allowlist ist daher unwahrscheinlich
     [Quelle: RA:90; Befehl `scutil --nc list`, 16.11.] [A]. Der
     Betreiber erfährt am 20.11. auch: Die Egress-IP ist die
     AKS-verwaltete Outbound-IP, bekannt erst nach dem Create (P1
     Schritt 4, ab 30.11.), und jeder Neuaufbau des Clusters bringt
     eine neue. Zweite Stufe: Der Owner meldet die IP direkt nach dem
     Create, falls die Antwort "Allowlist ja" lautet oder noch fehlt;
     die Bestätigung braucht es vor dem LLM-Test in P1 Schritt 8
     (03.12.).
   - ACME-Rückfall (AKS-E4): Der Owner legt bis 04.12. ein Konto bei
     einem ACME-CA mit External Account Binding an (ZeroSSL oder
     Google Trust Services). Die EAB-Daten kommen nur in den Key Vault
     (P1 Schritt 3, ab 30.11.) und nach `sli/aks/.env.aks`
     (gitignored, Schritt 10), nie in Git oder ein Dokument.
   - Stellvertreter (AKS-E20), bis 27.11.: Hat er ein Konto im
     Tenant von `azure-se`, als Mitglied oder Gast? Ist er über eine
     Gruppe Contributor (oder hat eine Rolle mit
     `listClusterUserCredential`, `runCommand` und
     `managedClusters/write`)? Ohne das bleiben `az aks
     get-credentials`, `aks-allow-me.sh`, `az aks start` und `az aks
     command invoke` beim Owner (P1 Schritt 7), oder ein
     Subscription-Owner weist eine Rolle zu; das liegt außerhalb der
     Rechte des Owners.
7. Erledigt am 17.11. (AKS-E15 (a)): Der offene amd-Working-Tree ist
   als Commit cd08a17 im Repo. Darin stecken SeaweedFS 2 CPU/2Gi,
   beide HIL-Flags, Sonnet-5-Planning, `scripts/models/set-pricing.sh`
   und `notify:_:send` für power_user [Quelle: Befehl
   `git show --stat cd08a17`, 17.11.]. Damit installiert AKS aus einem
   sauberen Checkout nicht mehr den SeaweedFS-Default, der am 16.11.
   hing. cd08a17 ist zugleich die Baseline für Schritt 13.
8. Offen: Mac-Tools, vom Owner am 17.11. freigegeben (AKS-E15 (e),
   AKS-E13); Claude installiert vor P1, am 18.11. noch nicht
   ausgeführt (`az version` 2.85.0):

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
   migrieren eine verwaiste Formel nicht. Zusätzlicher Grund seit
   18.11.: Key Vault schaltet alle Kontroll-API-Versionen vor
   2026-02-01 am 27.02.2027 ab; erst Azure CLI 2.90 kann 2026-02-01,
   2.85.0 nutzt 2025-05-01. Ein Rückbau oder Purge des Vaults nach
   dem 27.02.2027 scheiterte mit 2.85.0 [Quelle:
   `learn.microsoft.com/azure/key-vault/general/access-control-default`;
   azure-cli 2.85.0 site-packages azure/mgmt/keyvault/_configuration.py:49].
   Alle Azure-Schreibschritte ab P1 laufen deshalb nur mit 2.93 oder
   neuer. Nach dem Wechsel die zitierten Hilfetexte erneut prüfen:
   `az aks maintenanceconfiguration add --help`, `az aks
   get-credentials --help`, `az aks update --help` (auch
   `--disable-local-accounts`, `--nrg-lockdown-restriction-level`),
   `az acr create --help` (`--role-assignment-mode`), `az acr token
   credential generate --help` und `az network public-ip create
   --help` (`--dns-name-scope`). Diese drei Flags gibt es schon in
   2.85.0 [Quelle: `--help`-Ausgaben 2.85.0, 18.11.]; 2.93 bleibt
   wegen der Key-Vault-API Pflicht. Nach der kubelogin-Installation
   `kubelogin convert-kubeconfig --help` prüfen (`--kubeconfig`,
   `--context`, `-l interactive`, `-l devicecode`). Für kubelogin die
   Tap-Formel, nicht
   die Core-Formel `kubelogin` (int128/OIDC) und nicht `az aks
   install-cli` (legt ein zweites kubectl nach `/usr/local/bin`)
   [Quelle: Befehl `brew info kubelogin`; `az aks install-cli
   --help`]. Später kommt `cmctl` dazu (P2).
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
    existiert (EAB-Daten ab P0 Schritt 6, Kopie des
    ACR-Pull-Token-Passworts ab P1 Schritt 3, Client-Secret ab P3,
    LiteLLM-Key ab P5); der Owner committet direkt auf master. Heute
    ignoriert die amd-`.gitignore` nur `.env`, die sli-`.gitignore`
    gar keine Env-Datei, und die gpd-Regel `.env.*` schluckt auch die
    geplante Vorlage `.env.aks.example` [Quelle: Befehl `git
    check-ignore -v`, 17.11.; sli .gitignore; gpd .gitignore:6-8]:
    - amd-`.gitignore` um `.env.aks*` mit Ausnahme
      `!.env.aks.example` (amd-Vorlage, 5.2), `*.swp` und `*~`
      ergänzen, damit auch Swap- und Backup-Dateien wie
      `.env.aks.swp`, `.env.aks~` und `.env.aks.bak` draußen bleiben;
    - neue `sli/aks/.gitignore` (AKS-E15 (c)) mit `.env.aks*`,
      `*.swp`, `*~`, `*.log`, `*.pem`, `*.key` und `*.json` samt
      Ausnahme `!maint-*.json`; die sli-seitige Env-Datei heißt
      `sli/aks/.env.aks` (EAB-Daten, ACR-Pull-Token, Directory-URL,
      `AKS_FQDN`);
    - gpd-`.gitignore` um `!.env.aks.example` (`*.swp` und `*~` deckt
      sie schon ab);
    - jede `.env.aks` entsteht per `umask 077` mit Modus 600, bevor
      ein Secret hineinkommt; xtrace-Mitschnitte nur unter
      `~/.config/eurocis-aks/xtrace/` (chmod 700, 1.4).

    Dann das Sicherheitsgeländer in amd (Details in 5.2):
    `SAM_PROFILE=lab|aks` lädt `.env` bzw. `.env.aks`, nur über
    `load_env DIR` und nie schon beim Sourcen von `common.sh`;
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
    - Owner: Go und Wartungsfenster (SAM-Lab steht dabei) bis 27.11. festlegen,
      Termin `solace-1` bis 04.12. (Prüfpunkt), spätestens 10.12., damit der
      Lab-Nachweis vor dem 11.12. steht. Risiko mittel bis hoch: Die
      Volume-Kopie der SolOS-DB ist ungeprobt, 36 Queues und die iCargo-User
      liegen außerhalb von Terraform.

**Wer:** Owner Schritte 3, 5 (Label), 6 und die Freigaben bzw.
Termine in 9 und 14; Claude 8 und 10-14. Erledigt sind Schritt 7
(17.11.) sowie die Schritte 1, 2 und 4 (18.11.; Login des Owners,
read-only-Checks von Claude); offen aus Schritt 2 sind nur die
Rest-Checks. In KW47 tragen Owner und Claude P0 (Schritte 2 Rest, 3,
5, 6, 8); ab 23.11. übernimmt C die Schritte 9-14 gemeinsam mit
Claude.

**Abnahme:**

- `az version` zeigt 2.93.0 oder neuer; `az aks get-versions -l
  germanywestcentral` listet 1.36.x (am 18.11.: 1.36.5);
  `kubelogin --version` zeigt Azure-kubelogin.
- Azure-Lage, erfüllt am 18.11. [Quelle: Azure-Check 18.11.]:
  Subscription `azure-se`; alle gebrauchten Provider Registered; keine
  SKU-Restriction für `Standard_D8ps_v6`; Quota ohne Antrag
  ausreichend (DPSv6 0 von 350, Total Regional 150 frei, Public IPs 7
  von 1000, Standard-LBs 0 von 1000); Defender-Pläne Free (außer
  Discovery und FoundationalCspm), also keine Defender-Kosten und kein
  Sensor.
- Policies: Die Tag-Pflicht auf RGs (deny) und die Tag-Vererbung
  (modify) sind gefunden. Workaround als Entscheidung im PLAN: RG
  `gebit-showcase` vom Owner, `--tags` mit `Owner` und `Created Date`
  beim Create für die Node-RG. Der Rest-Check hat notiert, ob die
  Zuweisungen die Built-in-Definitionen nutzen und ob es weitere
  Deny- oder DenyAction-Zuweisungen auf
  `Microsoft.Network/publicIPAddresses`,
  `Microsoft.ContainerService/managedClusters`,
  `Microsoft.ContainerRegistry/registries`,
  `Microsoft.KeyVault/vaults`, die Region germanywestcentral oder die
  geplanten SKUs gibt (am 18.11. außer der Tag-Pflicht keine).
- Rechte: Der Owner hat Contributor ohne
  `Microsoft.Authorization/roleAssignments/write` und
  `Microsoft.Authorization/locks/write`; der Plan kommt ohne beides
  aus. Budgets darf er als Contributor anlegen; `az consumption budget
  list` gelingt (Cost Management für den Angebotstyp verfügbar), sonst
  ist das Budget ein offener Punkt für P1.
- AKS-E1 bis AKS-E21 schriftlich in PLAN 0.5 (oder neuem Abschnitt 0.5a AKS), je
  mit dem Status aus Abschnitt 2 ("entschieden 17.11.", "geändert 18.11." bzw.
  "ergänzt 18.11." für die Zeilen aus Schritt 3, "entschieden 18.11." für
  AKS-E21, "[A] Bestätigung offen", "Owner-Bestätigung offen" für AKS-E18,
  AKS-E20, die Seiten-Exposition in AKS-E5, die Tag-Werte in AKS-E1, Präfix,
  Label-Scope und Lockdown in AKS-E4, die Bootstrap-Variante in AKS-E13 und die
  offenen Punkte in AKS-E21, "offen" für den Descriptor-Teil von AKS-E16).
  PLAN-E8 und der AKS-Teil von PLAN-E7 (PLAN 0.2) verweisen auf AKS-E3 bis
  AKS-E8 (17.11.2026), O4 (PLAN 0.5) auf AKS-E1/AKS-E2/AKS-E4 und ist am 18.11.
  erledigt (bis auf die Kostenstelle), O6 (PLAN 0.5) auf AKS-E15. So gibt es je
  Entscheidung eine Quelle.
- Die neuen Owner-Punkte aus Schritt 3 sind entschieden oder tragen
  bis 27.11. die Empfehlung als Arbeitsstand: Tag-Werte, Bootstrap
  (Admin-Zertifikat plus Rotation oder Entra-Gruppe), Label-Optionen,
  Token-Ablauf, Contributor-Gleichrang. Der Lockdown ist vertagt auf
  P2 Schritt 10.
- Label: `<p>` und ein Ersatz-Label gewählt; `nslookup
  <p>.germanywestcentral.cloudapp.azure.com` liefert NXDOMAIN,
  `CheckDnsNameAvailability` liefert `true`. Eine Public IP gibt es
  noch nicht; die Anlage prüft P1.
- LiteLLM: Die Anfrage ist gestellt, auch zu `rpm_limit`/`tpm_limit`
  und zur Vorlaufzeit einer Allowlist-Änderung; der Betreiber weiß,
  dass die Egress-IP erst nach dem Create kommt und sich bei jedem
  Neuaufbau ändert. Bis 27.11. liegt schriftlich vor: keine Quell-IP-
  oder Key-IP-Einschränkung, oder "Allowlist ja" mit der Zusage, die
  IP ab 30.11. kurzfristig einzutragen (auch für den Messe-Key O5).
  Fehlt die Antwort am 27.11.: Eskalation, Eintrag im
  Risikoregister, der LiteLLM-Test am 03.12. gilt als gefährdet.
- Stellvertreter: Bis 27.11. ist bekannt, ob er im Tenant ist (Mitglied
  oder Gast) und ob er über eine Gruppe Contributor hat; sonst steht
  der Punkt offen in AKS-E20 und im Risikoregister.
- amd-Working-Tree sauber (Commit cd08a17).
- Ignore-Regeln vor der ersten `.env.aks`: `git check-ignore -q`
  gelingt für `sli/aks/.env.aks`,
  `agent-mesh-deployment/.env.aks` und
  `gebit-price-agent-demo/.env.aks`, in amd und `sli/aks` auch für
  `.env.aks.swp`, `.env.aks~`, `.env.aks.bak` und in `sli/aks` für
  `x.log`, nicht für `gebit-price-agent-demo/.env.aks.example`,
  `agent-mesh-deployment/.env.aks.example` und
  `sli/aks/maint-default.json`. Jede vorhandene `.env.aks` hat Modus
  600 (`stat -f %Lp`), `~/.config/eurocis-aks/xtrace/` Modus 700.
- gpd: Baseline-Commit im sda-Repo benannt, Referenzen gesichert,
  Rückweg einmal geprobt.
- Lab: Call-Log-Diff leer (bis auf die Kontext-Zusätze), Render-Diff
  leer, `make test` grün, `make smoke` READY auf Kasse 99, ein S1-e2e
  liefert "proposed 100001 7,99".
- Negativtests, jeweils mit `set -x`-Log per `BASH_XTRACEFD` unter
  `~/.config/eurocis-aks/xtrace/` (nie im Repo, 1.4):
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
  Lab-Messquellen in den Tabellen. Ebenso hat jedes `kubelogin
  convert-kubeconfig` ein `--kubeconfig` und jedes `az aks
  get-credentials` ein `--file`; sonst träfen beide `~/.kube/config`.
- sam-CLI-Spike mit Antworten auf (a) bis (d) dokumentiert.
- Lab-Broker: Owner-Go und Wartungsfenster terminiert (`solace-2` in
  KW48, `solace-1` bis 04.12., spätestens 10.12.);
  die Sofort-Regel aus Schritt 14 steht im Risikoregister (Abschnitt 7);
  das Ergebnis von `docker compose up --dry-run` ist notiert.

**Abhängigkeiten:** Owner-Login (erledigt 18.11.); Label `<p>` bis
20.11.; Antworten des Owners zu Schritt 3 und zum Stellvertreter bis
27.11.; O9 für C ab 23.11. AKS-E15 ist seit 17.11. erteilt.

### P1 Azure-Grundlagen, Cluster, ACR, CLI-Anbindung (2,25 PT, KW49)

**Ziel:** Cluster in Endform (ein Node, Free-Tier), angelegt nur mit
Contributor-Rechten, ohne eine einzige Rollenzuweisung und ohne Lock.
Per CLI nur von freigegebenen IPs und nur mit Entra-Identität
erreichbar (lokale Accounts nach dem Bootstrap aus), ohne die
Default-kubeconfig zu berühren. Pull aus ACR per Token, Key Vault im
Access-Policy-Modus, die Ingress-IP mit Label in der Node-RG einmal
öffentlich und aus dem Cluster heraus (Hairpin) belegt, die Egress-IP
an den LiteLLM-Betreiber gemeldet. Prüfpunkt 04.12.: Ist die
P1-Abnahme nicht grün, wandert der AKS-Teil von G2a nach G2b (Mechanik
aus PLAN 6.2) und P5 nach KW1.

**Layout:** Zwei Ressourcengruppen (Owner-Entscheidung 18.11.).

- `gebit-showcase`: vom Owner angelegt, Metadaten in westeurope,
  Pflicht-Tags `Owner` und `Created Date`. Darin der Cluster
  `aks-eurocis`, die ACR `<acr>` und der Key Vault `<kv>`, alle in
  germanywestcentral. Eine RG in einer anderen Region als ihre
  Ressourcen ist zulässig; fällt westeurope aus, leitet ARM
  Steuerungsaufrufe in eine Backup-Region um, Microsoft empfiehlt aber
  dieselbe Region [Quelle:
  `learn.microsoft.com/azure/azure-resource-manager/management/overview`].
- `gebit-showcase-nodes`: die Node-RG, von AKS beim Create angelegt
  (`--node-resource-group`, Tags aus `--tags`). Darin VM-Scale-Set,
  OS- und PVC-Disks, Standard-LB, das AKS-verwaltete VNet, die
  AKS-verwaltete Outbound-IP (Egress) und `pip-aks-ingress` (Label
  `<p>`, angelegt nach dem Create). Sie verschwindet mit dem Cluster,
  samt beider IPs; das Label wird dann frei [Quelle:
  `learn.microsoft.com/azure/aks/faq`].
- Ein Neuaufbau behält ACR mit Token, Key Vault und Budget, aber
  nicht Ingress-IP, Label-Bindung und Egress-IP (P7). Genau zwei
  öffentliche IPs im Projekt.
- Kein BYO-VNet, keine UAMI, keine Rollenzuweisung, kein Lock.
  `vnet-eurocis`, `snet-aks`, `id-aks-cp`, `pip-aks-egress` und die
  RGs `rg-eurocis-*` entfallen. Ein BYO-Subnetz bräuchte Network
  Contributor für die Cluster-Identität, vergeben vom Ersteller
  [Quelle: `learn.microsoft.com/azure/aks/azure-cni-powered-by-cilium`,
  Prerequisites; `learn.microsoft.com/azure/aks/concepts-network-cni-overview`].
- Netz: Azure CNI Overlay mit Cilium im AKS-verwalteten VNet
  (eigene UDRs oder Service-Endpoints dort sind nicht unterstützt und
  nicht nötig [Quelle: concepts-network-cni-overview]). Pod-CIDR
  10.244.0.0/16, Service-CIDR 10.0.0.0/16: keine Überlappung mit
  Lab-k3s 10.42/10.43 und mit dem VNet, das AKS beobachtet als
  10.224.0.0/12 anlegt [A: steht nicht auf Learn; Schritt 4
  protokolliert es]. Stand-LAN und Firmen-VPN spielen keine Rolle,
  weil kein Netz gekoppelt wird.

Regeln für jeden Azure-Schreibbefehl ab P1:

- Nur mit Azure CLI 2.93 oder neuer (P0 Schritt 8).
- `az aks create`, `az acr create`, `az keyvault create` und `az
  network public-ip create` bekommen `-l germanywestcentral`, weil
  `gebit-showcase` in westeurope liegt und ein Befehl ohne `-l` die
  Region der RG nähme. Globale Ressourcen ohne Region: Activity-Log-
  und Resource-Health-Alarme, die Action Group mit `-l Global` und das
  Budget per `az rest` (1.4).
- Nie `az group delete -n gebit-showcase` (nimmt ACR und Key Vault
  mit, und die RG gehört dem Owner); den Cluster löscht nur `az aks
  delete` (P7).
- `az aks update --tags` und `az aks nodepool update --tags` ersetzen
  das ganze Tag-Set; nur mit allen vier Tags, besser gar nicht
  [Quelle: `learn.microsoft.com/azure/aks/use-tags`].
- Kein Secret in argv oder Ausgabe: Werte laufen per Pipe nach
  `--file /dev/stdin`, jede Secret-Schreibung endet mit `-o none`.
- Scheitert `az aks update`, `az aks nodepool update` oder `az aks
  rotate-certs` mit `RequestDisallowedByPolicy`: höchstens dreimal im
  Abstand von 60 s wiederholen (`aks_update`, 5.1), bei einem
  Failed-State `az aks update
  -g gebit-showcase -n aks-eurocis` als Reconcile [Quelle:
  `learn.microsoft.com/troubleshoot/azure/azure-kubernetes/error-codes/requestdisallowedbypolicy-error`].
  Ein Community-Report beschreibt, dass AKS die Node-RG bei späteren
  Updates zeitweise ohne die Cluster-Tags schreibt und dann an einer
  Tag-Deny-Policy scheitert [Quelle: `github.com/Azure/AKS/issues/5856`,
  ohne Antwort von Microsoft] [A]. Eine Exemption kann der Owner nicht
  anlegen; dafür braucht es einen Subscription-Owner.

Die Befehle der Schritte 3 und 4a/4b fasst `sli/aks/foundation.sh
pre|post` zusammen, die Alarme und das Budget aus Schritt 8
`sli/aks/alerts.sh` (Zugriffs- und Löschalarme schon in
`foundation.sh pre`, vor dem Create), den Bootstrap aus Schritt 6
`sli/aks/bootstrap-rbac.sh`; `az aks delete` läuft nur über
`sli/aks/aks-rebuild.sh` (P7, Dateiliste in 5.1).

**Schritte (Claude nach Freigabe, in der `az`-Sitzung des Owners):**

1. Vorbedingungen prüfen, read-only:

   ```bash
   az version --query '"azure-cli"' -o tsv          # >= 2.93.0
   kubelogin --version
   az group show -n gebit-showcase --query \
     '[location, tags.Owner != `null`, tags."Created Date" != `null`]' -o tsv
   az group exists -n gebit-showcase-nodes          # false
   az vm list-usage -l germanywestcentral -o table  # DPSv6, Regional
   az network list-usages -l germanywestcentral -o table
   nslookup <p>.germanywestcentral.cloudapp.azure.com  # NXDOMAIN
   ```

   Die Abfrage zeigt nur, ob die Tags von `gebit-showcase` gesetzt
   sind (`true`), nicht ihre Werte; fehlt einer, endet P1 hier. Die
   Node-RG darf vor dem Create nicht existieren.
   Standard DPSv6 Family und Total Regional brauchen je mindestens 16
   freie vCPU (3.5); weniger als 16 heißt Refresh ohne Surge (3.3
   Punkt 6), weniger als 8 heißt Antrag durch den Owner. Ist `<p>`
   inzwischen belegt, gilt das Ersatz-Label (P0 Schritt 5).
2. Netz, Identität und Netzrechte: entfällt seit 18.11. Kein VNet,
   keine UAMI `id-aks-cp`, keine `az role assignment create`, also
   auch kein Risiko `PrincipalNotFound`. Das VNet legt AKS in der
   Node-RG an (Schritt 4); die System-Identität des Clusters hat dort
   per Default Contributor, vergeben von AKS, nicht vom Aufrufer
   [Quelle: `learn.microsoft.com/azure/aks/managed-identity-overview`,
   Tabelle "Control plane"]. `id-cert-manager` entfällt weiterhin:
   HTTP-01 braucht weder Workload Identity noch DNS Zone Contributor
   (AKS-E4). Die Schrittnummern bleiben, weil andere Phasen auf
   Schritt 3, 4, 6 und 8 verweisen.
3. Key Vault, ACR, Testimages, Pull-Token; Secrets generiert, nie
   ausgegeben:

   ```bash
   az keyvault show -n <kv> -o none 2>/dev/null ||
     az keyvault create -g gebit-showcase -l germanywestcentral -n <kv> \
       --enable-rbac-authorization false --no-self-perms \
       --retention-days 7 -o none
   OWNER_OID=$(az ad signed-in-user show --query id -o tsv)
   az keyvault set-policy -g gebit-showcase -n <kv> \
     --object-id "$OWNER_OID" \
     --secret-permissions get list set delete recover -o none
   for i in $(seq 1 20); do         # Wirkzeit undokumentiert [A]
     az keyvault secret list --vault-name <kv> -o none 2>/dev/null && break
     sleep 15
   done
   az keyvault secret list --vault-name <kv> -o none || \
     { echo "KV-Policy greift nicht" >&2; exit 1; }
   newsecret() {                    # nur anlegen, wenn er fehlt
     az keyvault secret show --vault-name <kv> -n "$1" -o none 2>/dev/null ||
       openssl rand -hex 24 | tr -d '\n' |
       az keyvault secret set --vault-name <kv> -n "$1" \
         --file /dev/stdin -o none
   }
   newsecret keycloak-admin

   az acr show -n <acr> -o none 2>/dev/null ||
     az acr create -g gebit-showcase -l germanywestcentral -n <acr> \
       --sku Basic --admin-enabled false --role-assignment-mode rbac -o none
   az acr show -n <acr> --query roleAssignmentMode -o tsv
   az acr import -n <acr> --source docker.io/curlimages/curl:8.23.0 \
     --image curl:8.23.0                     # multi-arch inkl. arm64
   az acr import -n <acr> --source docker.io/traefik/whoami:v1.12.0 \
     --image whoami:v1.12.0                  # multi-arch inkl. arm64
   az acr repository list -n <acr> -o tsv    # Datenebene als Contributor

   az acr token show -r <acr> -n aks-pull -o none 2>/dev/null ||
     az acr token create -r <acr> -n aks-pull \
       --scope-map _repositories_pull --no-passwords -o none
   az keyvault secret show --vault-name <kv> -n acr-pull-token \
     -o none 2>/dev/null ||
     az acr token credential generate -r <acr> -n aks-pull --password1 \
       --expiration 2027-02-28T23:59:59Z \
       --query "passwords[?name=='password1'].value | [0]" -o tsv |
       tr -d '\n' |
       az keyvault secret set --vault-name <kv> -n acr-pull-token \
         --file /dev/stdin -o none
   az acr token show -r <acr> -n aks-pull \
     --query "{s:status,p:credentials.passwords[].{n:name,e:expiry}}" -o json
   # Kopie für acr-pull.sh, nie ausgegeben, nur wenn noch keine da ist
   umask 077; E=<sli>/aks/.env.aks
   git -C <sli> check-ignore -q aks/.env.aks || exit 1
   grep -q '^ACR_PULL_TOKEN=' "$E" 2>/dev/null ||
     { printf 'ACR_PULL_TOKEN='
       az keyvault secret show --vault-name <kv> -n acr-pull-token \
         --query value -o tsv; } >> "$E"
   chmod 600 "$E"
   sli/aks/alerts.sh access   # Zugriffs- und Löschalarme vor dem Create
   ```

   `newsecret` gilt auch für: keycloak-db, Realm-User (je User),
   grafana-admin, grafana-ro, solace-admin, broker-sam, broker-gpos,
   sam-session, sam-pg-admin, gpos-postgres-admin, gpos-db-Rollen (je
   Rolle). Begründungen:
   - Access-Policy-Modus statt RBAC: Eine Key-Vault-Datenrolle
     bräuchte eine Rollenzuweisung. `--enable-rbac-authorization false`
     muss explizit stehen, weil die CLI RBAC als Default nimmt und neue
     Vaults ab API 2026-02-01 ohnehin RBAC bekommen [Quelle: `az
     keyvault create --help`, 2.85.0;
     `learn.microsoft.com/azure/key-vault/general/access-control-default`].
     Access Policies gelten als Legacy-Modell, sind aber voll
     unterstützt [Quelle:
     `learn.microsoft.com/azure/key-vault/general/rbac-access-policy`].
     `vaults/accessPolicies/write` hat Contributor (P0 Schritt 2), aber
     auch jeder andere Contributor von `azure-se` kann sich so selbst
     eine Policy setzen [Quelle: Learn assign-access-policy]; Alarm in
     Schritt 8, Abwägung in P0 Schritt 3. "ASC Default" meldet den
     Vault vermutlich als Abweichung (Audit ohne Wirkung) [A].
   - `--no-self-perms`: Ohne das Flag legt die CLI für den Aufrufer
     eine Policy mit allen Key-, Secret-, Zertifikats- und
     Storage-Rechten an [Quelle: azure-cli 2.85.0
     keyvault/custom.py:419-426]. Der Owner braucht nur Secrets (auch
     TLS-Backups und EAB-Daten sind Secrets). `OWNER_OID` entsteht zur
     Laufzeit und steht nirgends. Die Policy des Stellvertreters
     (`az keyvault set-policy --object-id <deputy-objectId>
     --secret-permissions get list`) folgt in P7 Schritt 7.
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
     als `acme-eab-kid` und `acme-eab-hmac`, je per `read -rs V`
     (Wert einfügen, kein Echo), `printf %s "$V" | az keyvault secret
     set --vault-name <kv> -n <name> --file /dev/stdin -o none`, dann
     `unset V` und `pbcopy </dev/null`, damit der Wert nicht in der
     Zwischenablage, ihrem Verlauf oder Universal Clipboard bleibt;
     daneben nur in `sli/aks/.env.aks` (chmod 600). P2 baut daraus den
     Rückfall-ClusterIssuer.
   - `--retention-days 7` ist das Minimum und nur beim Anlegen setzbar;
     ohne Purge-Schutz, damit ein Purge beim Rückbau möglich bleibt.
     Vault und ACR nur per show-or-create: Ein zweites `az keyvault
     create` auf einen bestehenden Vault schriebe ihn per PUT neu und
     könnte die Access Policies leeren [A].
   - ACR im Modus `rbac`, explizit: Im Modus "RBAC Registry + ABAC
     Repository Permissions" hat Contributor keine Datenebene, also
     weder Push noch Pull, und Learn kündigt ABAC als künftigen Default
     an [Quelle: Learn container-registry-rbac-abac-repository-permissions
     und container-registry-rbac-built-in-roles-directory-reference].
     Heute ist `rbac` der CLI-Default [Quelle: `az acr create --help`,
     2.85.0]. Der Owner pusht in P2, P5 und P6 per `az acr login` und
     `docker buildx imagetools create`. Erwartet ist
     `LegacyRegistryPermissions` als `roleAssignmentMode`: Die CLI
     bildet `rbac` darauf ab [Quelle: azure-cli 2.85.0
     acr/custom.py:676-689; azure-mgmt-containerregistry
     models/_enums.py:356].
   - `--admin-enabled false`: kein Admin-Benutzer; Pods ziehen nur per
     Token. `az acr import` ist eine ARM-Aktion, die Contributor deckt,
     und übernimmt bei Multi-Arch-Images alle Plattformen [Quelle:
     Learn container-registry-import-images].
   - Pull-Token statt `--attach-acr`: Die AcrPull-Zuweisung für die
     Kubelet-Identität verlangt Owner oder vergleichbare Rechte
     [Quelle:
     `learn.microsoft.com/azure/aks/cluster-container-registry-integration`].
     Tokens und Scope Maps gibt es in allen Tarifen, in Basic je 100
     [Quelle: Learn container-registry-token-based-repository-permissions
     und container-registry-skus]. `_repositories_pull` ist die
     System-Scope-Map "pull any repository" und deckt auch künftige
     Repos; eine eigene Scope Map mit Repo-Liste wäre enger, verlangt
     aber Pflege je neuem Image (Owner-Option). Ein Token gehört zu
     keiner Entra-Identität: Wer das Passwort hat, zieht jedes Image
     dieser ACR, pusht aber nichts.
   - `--no-passwords`, weil `token create` sonst zwei Passwörter ohne
     Ablauf (9999-12-31) erzeugt und ausgibt [Quelle: `az acr token
     create --help`, 2.85.0]. Das Passwort entsteht erst per
     `credential generate` mit Ablauf 2027-02-28T23:59:59Z (gleich
     `deleteAfter`, nach der Messe, nicht im Freeze) [A: Owner, P0
     Schritt 3] und geht ohne Ausgabe in den Key Vault; die Replikation
     dauert bis 60 s [Quelle: Learn token-based-repository-permissions].
     Das Filterformat der `--query` prüft der erste Lauf [A]. Eine
     Kopie liegt nur in `sli/aks/.env.aks` (gitignored, P0 Schritt 10,
     chmod 600); der Block oben schreibt sie per `umask 077` und nur
     nach erfolgreichem `git check-ignore`, ohne den Wert auszugeben.
     `password2` bleibt Reserve für eine Rotation ohne Ausfall. Ein
     abgelaufenes Passwort fällt erst beim nächsten Pull auf (Surge-Node
     am 26.01., Pod-Neustart auf neuem Node); P7 prüft die Restlaufzeit
     im Preflight.
   - `whoami` dient nur dem Hairpin-Test in Schritt 8 (Docker Hub
     v1.12.0 vom 29.07.2026, Index-Digest-Präfix
     `sha256:c4717a8d1f01`, amd64/arm64/arm) [Quelle:
     Docker-Hub-Tags-API, 17.11.].
   - Basic enthält 10 GiB; `az acr show-usage` misst nach den ersten
     Pushes in P2, ob die arm64-Images darunter bleiben [A].
   - Der LiteLLM-Key kommt nicht in den Key Vault.
4. Cluster, danach Ingress-IP und Egress-IP:

   ```bash
   OWNER_IP=$(dig -4 +short myip.opendns.com @resolver1.opendns.com |
     grep -E '^[0-9.]+$')
   T_OWNER=$(az group show -n gebit-showcase --query tags.Owner -o tsv)
   T_DATE=$(az group show -n gebit-showcase \
     --query 'tags."Created Date"' -o tsv)
   [ -n "$T_OWNER" ] && [ -n "$T_DATE" ] || \
     { echo "Pflicht-Tags auf gebit-showcase fehlen" >&2; exit 1; }
   TAGS=("Owner=$T_OWNER" "Created Date=$T_DATE" \
     purpose=eurocis2027 deleteAfter=2027-02-28)
   az aks create -g gebit-showcase -n aks-eurocis -l germanywestcentral \
     --kubernetes-version 1.36.<patch> --tier free \
     --node-resource-group gebit-showcase-nodes \
     --nodepool-name main --node-vm-size Standard_D8ps_v6 --node-count 1 \
     --max-pods 110 --node-osdisk-size 128 \
     --network-plugin azure --network-plugin-mode overlay \
     --network-dataplane cilium \
     --pod-cidr 10.244.0.0/16 --service-cidr 10.0.0.0/16 \
     --dns-service-ip 10.0.0.10 \
     --load-balancer-managed-outbound-ip-count 1 \
     --enable-aad \
     --api-server-authorized-ip-ranges "${OWNER_IP}/32" \
     --auto-upgrade-channel none --node-os-upgrade-channel SecurityPatch \
     --no-ssh-key --tags "${TAGS[@]}" --nodepool-tags "${TAGS[@]}" -o none
   az aks nodepool update -g gebit-showcase --cluster-name aks-eurocis \
     -n main --max-surge 1 -o none
   az group show -n gebit-showcase-nodes --query "keys(tags)" -o tsv
   [ "$(az group show -n gebit-showcase-nodes --query tags.Owner -o tsv)" \
     = "$T_OWNER" ] || echo "Owner-Tag der Node-RG weicht ab" >&2
   az network vnet list -g gebit-showcase-nodes \
     --query "[].{n:name,a:addressSpace.addressPrefixes}" -o tsv
   ```

   4a. Ingress-IP in der Node-RG, direkt nach dem Create; vorher die
   Verfügbarkeit von `<p>` erneut prüfen (P0 Schritt 5):

   ```bash
   nslookup <p>.germanywestcentral.cloudapp.azure.com  # NXDOMAIN
   az network public-ip show -g gebit-showcase-nodes -n pip-aks-ingress \
     -o none 2>/dev/null || \
     az network public-ip create -g gebit-showcase-nodes \
       -n pip-aks-ingress -l germanywestcentral \
       --sku Standard --allocation-method Static --version IPv4 \
       --dns-name <p> \
       --tags purpose=eurocis2027 deleteAfter=2027-02-28 -o none
   az network public-ip show -g gebit-showcase-nodes -n pip-aks-ingress \
     --query "{ip:ipAddress,fqdn:dnsSettings.fqdn,t:keys(tags)}" -o json
   nslookup <fqdn>                          # = ipAddress
   ```

   4b. Egress-IP lesen; der Owner meldet sie dem LiteLLM-Betreiber (P0
   Schritt 6), die Adresse steht nur lokal in
   `~/.config/eurocis-aks/egress-ip` (chmod 600), die Ingress-IP aus
   4a ebenso in `~/.config/eurocis-aks/ingress-ip` (Register für den
   Vergleich in P5 Schritt 6 und P7):

   ```bash
   EGRESS_ID=$(az aks show -g gebit-showcase -n aks-eurocis --query \
     "networkProfile.loadBalancerProfile.effectiveOutboundIPs[0].id" -o tsv)
   az network public-ip show --ids "$EGRESS_ID" --query ipAddress -o tsv
   ```

   - Ein Node, kein HA (AKS-E3, AKS-E14). Learn nennt für produktive
     System-Pools mindestens 2 Nodes, empfohlen 3; der AKS-Quickstart
     legt mit `--node-count 1` an [Quelle:
     `learn.microsoft.com/azure/aks/use-system-pools`;
     `learn.microsoft.com/azure/aks/learn/quick-kubernetes-deploy-cli`]
     [A: AKS nimmt den Ein-Node-System-Pool ohne Einschränkung an; der
     Create ist der Beweis]. Einen N-1-Fall und einen N-1-Drill gibt es
     nicht mehr. `--max-surge 1` heißt beim Node-Image-Upgrade ein
     zweiter Node auf Zeit; die 16 vCPU Quota sind da (P0 Schritt 4)
     [Quelle: `az aks nodepool update --help`, 2.85.0]. `az aks create`
     kennt in 2.85.0 kein `--max-surge`, daher das Nodepool-Update.
   - `--kubernetes-version`: der neueste 1.36-Patch am Tag des Creates
     (am 18.11.: 1.36.5) [Quelle: Azure-Check 18.11.].
   - Free-Tier für das ganze Projekt, kein Wechsel auf Standard
     (AKS-E14).
   - Nur Contributor: Der Befehl enthält bewusst kein
     `--vnet-subnet-id`, `--assign-identity`,
     `--load-balancer-outbound-ips`, `--attach-acr` und
     `--enable-azure-rbac`; der Default-Create mit System-Identität
     löst keine Rollenzuweisung aus [Quelle: Learn
     aks-service-permissions; azure-cli dev
     acs/managed_cluster_decorator.py, 18.11.]. `--attach-acr` endete
     nach dem Cluster-PUT und rund 110 s Versuchen mit "Could not create
     a role assignment for ACR" und Exit-Code ungleich 0, der Cluster
     stünde ohne Pull-Recht da; `--vnet-subnet-id` gäbe nur eine
     Warnung, und der Cluster hätte keine Netzrechte [Quelle: azure-cli
     dev acs/_roleassignments.py, 18.11.]. `--enable-azure-rbac`
     bräuchte Rollenzuweisungen für jeden Zugriff.
   - `--disable-local-accounts` fehlt beim Create mit Absicht: Der
     Bootstrap in Schritt 6 braucht einmal das Admin-Zertifikat, weil
     es ohne Rollenzuweisung und ohne Admin-Gruppe sonst niemanden mit
     Kubernetes-Rechten gibt [Quelle:
     `learn.microsoft.com/azure/aks/kubernetes-rbac-entra-id`]. Mit der
     Entra-Gruppe aus P0 Schritt 3 stünden stattdessen
     `--aad-admin-group-object-ids <group-objectId>` und
     `--disable-local-accounts` schon im Create.
   - `--load-balancer-managed-outbound-ip-count 1` ist der Default und
     steht explizit, damit niemand eine BYO-IP ergänzt. AKS verwaltet
     den Lebenszyklus dieser IP; sie ist nicht als BYO-IP
     wiederverwendbar und nach einem Neuaufbau neu [Quelle:
     `learn.microsoft.com/azure/aks/configure-load-balancer-standard`].
     Eine über Neuaufbauten stabile Egress-IP gibt es ohne
     Rollenzuweisung nicht: Eine IP außerhalb der Node-RG braucht
     Rechte der Cluster-Identität darauf [Quelle: ebenda].
   - Tags: `--tags` gehen an den Cluster, seine Ressourcen (LB, IPs,
     NSG, VNet, Kubelet-Identität) und an die Node-RG [Quelle:
     `learn.microsoft.com/azure/aks/use-tags`]; `--nodepool-tags`
     tagt Pool, Scale-Set und Instanzen. `Owner` und `Created Date`
     kommen zur Laufzeit aus `gebit-showcase`, weil die Inherit-Policy
     abweichende Werte am Cluster ohnehin überschreibt [A]; die Werte
     stehen nur in der Shell-Variable, die Prüfungen zeigen nur
     Schlüssel. Tag-Namen mit Leerzeichen sind erlaubt [Quelle: Learn
     tag-resources; A: Parsing von `"Created Date=..."` durch die CLI,
     die Abfrage danach belegt es]. `Owner` war früher für AKS
     reserviert, das gilt nur für Altressourcen [Quelle: AKS-FAQ].
     Annahme [A]: AKS legt die Node-RG in einem Schritt mit den
     Cluster-Tags an, sodass die Deny-Policy durchlässt (ein
     Community-Report sah das beim Create durchweg so, Azure/AKS
     #5856). Scheitert der Create trotzdem mit
     `RequestDisallowedByPolicy`, braucht es eine Exemption durch
     einen Subscription-Owner.
   - `--node-resource-group` geht nur beim Create; die Gruppe darf
     vorher nicht existieren, liegt in derselben Subscription, ist
     später nicht umbenennbar, und die Namen darin wählt AKS. Ohne den
     Parameter hieße sie
     `MC_gebit-showcase_aks-eurocis_germanywestcentral` [Quelle:
     AKS-FAQ]. Der feste Name hält den Budget-Filter über Neuaufbauten
     stabil (Schritt 8).
   - Die Node-RG ist per Default `Unrestricted`, ein Contributor darf
     dort Ressourcen anlegen [Quelle:
     `learn.microsoft.com/azure/aks/node-resource-group-lockdown`], und
     Learn legt die statische IP eines Service selbst dorthin, ohne
     weitere Rollenzuweisung [Quelle:
     `learn.microsoft.com/azure/aks/static-ip`]. Owner-Option als
     Ersatz für den Lock (P0 Schritt 3): nach dem LB-Nachweis in P2
     `az aks update --nrg-lockdown-restriction-level ReadOnly` (laut
     FAQ Schutz gegen versehentliches Löschen; Recht: nur
     `managedClusters/write`). Danach kann auch der Owner
     `pip-aks-ingress` weder ändern noch löschen; zum Ändern kurz auf
     `Unrestricted` [A: Zusammenspiel mit dem Cloud-Provider testen].
   - `pip-aks-ingress`: Standard, statisch, IPv4, Label `<p>` (mit
     Option (a) aus P0 Schritt 5 zusätzlich `--dns-name-scope
     SubscriptionReuse`). `Owner` und `Created Date` erbt die IP per
     Policy von der Node-RG [A]. Kein Lock und keine Rollenzuweisung;
     der Cloud-Provider löscht eine selbst angelegte IP nie, auch nicht
     mit dem Service (Schritt 8 belegt das).
   - Egress: Die Adresse ist erst nach dem Create bekannt und geht
     sofort an den Betreiber, falls er eine Allowlist hat oder noch
     nicht geantwortet hat. Schritt 8 vergleicht sie nach `az aks
     rotate-certs` (Schritt 6) mit der Adresse, die ein Pod nach außen
     zeigt, und erneut nach Stop/Start [A: bleibt gleich].
   - `--api-server-authorized-ip-ranges` enthält beim Create nur die
     aktuelle Owner-IP. API-Server-IP und Outbound-IP des Standard-LB
     fügt AKS beim Create selbst hinzu; höchstens 200 Bereiche
     [Quelle: `learn.microsoft.com/azure/aks/api-server-authorized-ip-ranges`].
     Weitere IPs kommen nur über den Helfer aus Schritt 7. Der Owner
     kann AKS-E5 auf reines Entra ID mit Conditional Access umstellen;
     dann entfallen Liste und Helfer.
   - Ohne `--enable-oidc-issuer` und `--enable-workload-identity`:
     HTTP-01 braucht keine Workload Identity (AKS-E4); beides ist
     später per `az aks update` nachrüstbar.
   - Entra-Integration ist nicht rückbaubar [Quelle:
     `learn.microsoft.com/azure/aks/enable-authentication-microsoft-entra-id`].
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
     az aks maintenanceconfiguration add -g gebit-showcase \
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
6. CLI anbinden, getrennt vom Lab, die Wrapper festlegen und den
   Zugriff bootstrappen:

   ```bash
   az aks get-credentials -g gebit-showcase -n aks-eurocis \
     --file ~/.kube/aks-eurocis.yaml --context aks-eurocis
   kubelogin convert-kubeconfig -l azurecli \
     --kubeconfig ~/.kube/aks-eurocis.yaml --context aks-eurocis
   AKS_KUBECONFIG="$HOME/.kube/aks-eurocis.yaml"
   kaks() { KUBECONFIG="$AKS_KUBECONFIG" kubectl --context aks-eurocis "$@"; }
   haks() { KUBECONFIG="$AKS_KUBECONFIG" helm --kube-context aks-eurocis "$@"; }
   kaks auth whoami                 # Username und Gruppen, ohne Binding
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
   - Die User-kubeconfig eines Entra-Clusters enthält kein Geheimnis;
     sie fordert eine Anmeldung an [Quelle:
     `learn.microsoft.com/azure/aks/control-kubeconfig-access`].
     `kubelogin -l azurecli` nutzt die `az login`-Sitzung im selben
     Tenant [Quelle:
     `azure.github.io/kubelogin/concepts/login-modes/azurecli.html`].

   Bootstrap der Kubernetes-Rechte, einmal je Cluster, als Skript
   `sli/aks/bootstrap-rbac.sh` (nach `require_kube_context
   aks-eurocis`, idempotent):

   ```bash
   set -euo pipefail
   umask 077
   { set +x; } 2>/dev/null                          # Username nie im Log
   ME=$(kaks auth whoami -o jsonpath='{.status.userInfo.username}')
   [ -n "$ME" ] || { echo "whoami leer" >&2; exit 1; }
   ADM_DIR=$(mktemp -d); ADM="$ADM_DIR/admin.yaml"   # nie unter ~/.kube
   trap 'rm -rf "$ADM_DIR"' EXIT                    # auch bei exit 1
   trap 'exit 1' INT TERM HUP                       # Signal -> EXIT-Trap
   az aks get-credentials -g gebit-showcase -n aks-eurocis --admin \
     --file "$ADM"
   [ "$(kubectl --kubeconfig "$ADM" config view --minify \
         -o jsonpath='{.clusters[0].cluster.server}')" = \
     "$(kaks config view --minify \
         -o jsonpath='{.clusters[0].cluster.server}')" ] || exit 1
   kubectl --kubeconfig "$ADM" create clusterrolebinding \
     eurocis-owner-admin --clusterrole=cluster-admin --user="$ME" \
     --dry-run=client -o yaml | kubectl --kubeconfig "$ADM" apply -f -
   rm -rf "$ADM_DIR"
   kaks auth can-i '*' '*' -A                       # yes
   ```

   Danach im selben Skript (Schritte 6 und 7 von `bootstrap-rbac.sh`,
   5.1), je mit eigener Freigabe:

   ```bash
   aks_update --disable-local-accounts -o none       # sli/aks/lib.sh
   [ "$(az aks show -g gebit-showcase -n aks-eurocis \
         --query disableLocalAccounts -o tsv)" = true ] ||
     { echo "lokale Accounts noch an" >&2; exit 1; }
   D=$(mktemp -d); trap 'rm -rf "${ADM_DIR:-}" "$D"' EXIT  # Negativtest
   if az aks get-credentials -g gebit-showcase -n aks-eurocis --admin \
        --file "$D/x.yaml" 2>"$D/err"; then
     echo "FEHLER: Admin-Credential abrufbar" >&2; exit 1
   fi
   grep -q "Getting static credential isn't allowed" "$D/err"
   az aks rotate-certs -g gebit-showcase -n aks-eurocis --yes  # bis 30 min
   az aks get-credentials -g gebit-showcase -n aks-eurocis \
     --file ~/.kube/aks-eurocis.yaml --context aks-eurocis \
     --overwrite-existing
   kubelogin convert-kubeconfig -l azurecli \
     --kubeconfig ~/.kube/aks-eurocis.yaml --context aks-eurocis
   kaks auth can-i '*' '*' -A                       # yes
   ```

   `rotate-certs` läuft erst, wenn `disableLocalAccounts` gleich
   `true` ist und `--admin` mit der erwarteten Meldung scheitert.
   Scheitert `--disable-local-accounts` an RequestDisallowedByPolicy
   (Azure/AKS #5856), wiederholt `aks_update` begrenzt; gelingt der
   Negativtest dennoch, liegt die Admin-Datei nur im per `trap`
   gelöschten Verzeichnis.

   - Kubernetes-RBAC mit Entra: Für Nutzer desselben Tenants ist das
     Subjekt der UPN, für Nutzer aus einem anderen Tenant die
     objectId, Gruppen gehen per `kind: Group` mit ihrer objectId
     [Quelle: `learn.microsoft.com/azure/aks/kubernetes-rbac-entra-id`].
     Gast-UPNs haben die Form `<name>_<domain>#EXT#@<tenant>...`
     [Quelle: Learn control-kubeconfig-access]. Das Skript nimmt den
     Namen, den `kaks auth whoami` vor jeder Bindung meldet; damit ist
     das Format für Mitglied und Gast richtig, und der Name kommt nie
     ins Repo (Platzhalter `<owner-upn>`) [A: AKS erlaubt jedem
     angemeldeten Nutzer die SelfSubjectReview; sonst zeigt die
     Forbidden-Meldung von `kaks get ns` denselben Namen].
   - Der Server-Vergleich verhindert, dass eine fremde Admin-Datei die
     Bindung in einen anderen Cluster schreibt. Die Admin-Datei liegt
     nur für Sekunden in einem eigenen Temp-Verzeichnis mit umask 077
     und nie in `~/.kube`; der `trap` löscht es auch dann, wenn ein
     Schritt scheitert (`set -e`, `exit 1`, Abbruch per Signal). Dieses
     Muster gilt für jeden Weg zur Admin-kubeconfig, auch für
     Break-glass (unten, P7 Schritte 3 und 7). `--admin` geht vor
     `--context` [Quelle: `az aks get-credentials --help`, 2.85.0].
   - Erst wenn `kaks auth can-i '*' '*' -A` mit der Entra-kubeconfig
     `yes` ergibt, gehen die lokalen Accounts aus; sonst sperrte sich
     der Owner aus. Danach scheitert `get-credentials --admin` mit
     "Getting static credential isn't allowed because this cluster is
     set to disable local accounts" [Quelle:
     `learn.microsoft.com/azure/aks/local-accounts`].
   - Rotation: Learn verlangt sie, wenn auf dem Cluster schon lokale
     Accounts genutzt wurden, damit ausgegebene Zertifikate ungültig
     werden; ob AKS ein altes Admin-Zertifikat nach
     `--disable-local-accounts` sonst noch annimmt, sagt Learn nicht
     [Quelle: Learn local-accounts]. `az aks rotate-certs` legt Nodes,
     Scale-Set und Disks neu an und kann bis zu 30 min Ausfall bringen
     [Quelle: `learn.microsoft.com/azure/aks/rotate-certificates`];
     deshalb jetzt, vor dem ersten Workload und vor dem PVC-Test in
     Schritt 8. Danach die kubeconfig neu holen. Mit der Entra-Gruppe
     aus P0 Schritt 3 entfallen Admin-Zertifikat und Rotation.
   - Die Bindung des Stellvertreters legt der Owner später mit seiner
     Entra-Identität an (P7 Schritt 7), mit dem Namen aus dessen
     eigenem `kaks auth whoami`; dafür braucht es keinen Admin-Zugang
     mehr.
   - Kubernetes-RBAC ist keine Grenze gegenüber den anderen
     Contributors von `azure-se`: Jeder von ihnen kann lokale Accounts
     wieder einschalten und Admin-Credentials holen [Quelle: Learn
     local-accounts]. Das Activity Log zeichnet es auf; den Alarm
     setzt Schritt 8.

   Break-glass, jeweils mit Contributor:
   - Eigene IP nicht in der Liste (fremdes Netz):
     `sli/aks/aks-allow-me.sh` oder `az aks command invoke`; beide
     laufen über die Azure-API, nicht über den API-Server-Endpunkt
     [Quelle: `learn.microsoft.com/azure/aks/access-private-cluster`].
     `command invoke` reicht das Entra-Token des Aufrufers weiter, es
     gilt also Kubernetes-RBAC [Quelle: azure-cli acs/custom.py, 2.85.0
     Z. 2620-2626]. Sein Pod fordert 200m CPU und 500Mi an [Quelle:
     Learn access-private-cluster]; auf dem knappen Node braucht er
     zeitweise Platz (3.2).
   - Bindung fehlt oder ist falsch (RBAC-Lockout): `aks_update
     --enable-local-accounts`, Admin-Datei nach dem Muster oben (`set -euo
     pipefail`, `umask 077`, `mktemp -d` mit `trap`), Bindung reparieren,
     `--disable-local-accounts` mit demselben Nachweis wie oben, danach `az aks
     rotate-certs`. Das kostet bis zu 30 min Ausfall, also nie an Probetagen
     oder auf der Messe, außer im Notfall.
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
     lesen (`az aks show -g gebit-showcase -n aks-eurocis --query
     apiServerAccessProfile.authorizedIpRanges -o tsv`), die aktuelle
     IPv4 per `dig -4 +short myip.opendns.com @resolver1.opendns.com`
     ermitteln und als /32 ergänzen, wenn sie fehlt; die vollständige,
     deduplizierte Liste mit `az aks update -g gebit-showcase -n
     aks-eurocis --api-server-authorized-ip-ranges <liste>` schreiben;
     dann bis 2 min `kaks get --raw /readyz` (nach
     `require_kube_context aks-eurocis`).
   - `--print`: nur die aktuelle IPv4 ausgeben; `--check`: Exit 1, wenn
     sie in der Liste fehlt (für `aks-start.sh` und Preflight).
   - `--prune <ip>`: einen Eintrag entfernen, den der Helfer selbst
     hinzugefügt hat; bricht ab, wenn die Liste danach leer wäre.
     Einträge, die AKS selbst gesetzt hat, bleiben unberührt.
   - `--add <ip>`: nur durch den Owner, für die IP des Stellvertreters,
     falls dieser keine Azure-Rechte hat (siehe unten).
   - Register `~/.config/eurocis-aks/allowed-ips` (chmod 600; IP, Datum,
     Zweck wie "Büro", "5G", "Stand"); nie im Repo, nie in diesem
     Dokument.
   - Bei `RequestDisallowedByPolicy` gilt die Regel aus dem Kopf von
     P1 (begrenzt wiederholen, Reconcile).

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
   `az aks update`, und er ändert nur die IP-Liste [A].

   Stellvertreter: Eine eigene, enge Rolle ist ohne Rollenzuweisung
   nicht möglich. Für `aks-allow-me.sh`, `az aks start`, `az aks
   get-credentials` und `az aks command invoke` braucht er Azure-Rechte
   aus einer Gruppe mit Contributor (oder Ähnlichem) auf `azure-se`
   (P0 Schritt 6). Dann hat er auch `stop` und `delete`; die Grenze
   ist eine Runbook-Regel. Ohne diese Gruppe bleiben diese Schritte
   beim Owner; kubectl ginge mit der weitergegebenen User-kubeconfig,
   einem eigenen Binding und seiner IP per `--add` [A: Test in P7
   Schritt 7 mit einem Konto ohne Subscription-Zugriff]. Dann scheitert
   ein einfaches `az login` mit "No subscriptions found" [Quelle:
   azure-cli 2.85.0 core/_profile.py:206-207]; der Stellvertreter
   meldet sich mit `az login --tenant <tenant> --allow-no-subscriptions`
   an (bei einem Gast holt erst `--tenant` ein Token des richtigen
   Tenants), prüft `kaks auth whoami` und liest seine objectId mit `az
   ad signed-in-user show --query id -o tsv`. Ohne Azure CLI geht
   `kubelogin convert-kubeconfig -l interactive` (oder `-l devicecode`)
   `--kubeconfig ~/.kube/aks-eurocis.yaml --context aks-eurocis` statt
   `-l azurecli`. Ein `LinkedAuthorizationFailed` wie bei BYO-Ressourcen
   droht nicht mehr, weil der Cluster nur auf eigene Ressourcen
   verweist [A].
8. Prüfungen und Wächter. `az aks check-acr` entfällt: Es startet
   `mcr.microsoft.com/aks/canipull:v0.1.0`, ein reines amd64-Image (auf
   Cobalt-Nodes "exec format error"), holt eine temporäre
   Devicecode-kubeconfig, die nicht konvertiert wird [Quelle: azure-cli
   2.85.0 acs/_consts.py:226, acs/custom.py:1897-1906, 2150-2195; Befehl
   `curl https://mcr.microsoft.com/v2/aks/canipull/manifests/v0.1.0`,
   16.11.], und prüft die AcrPull-Zuweisung der Kubelet-Identität, die
   es ohne `--attach-acr` nicht gibt.

   Pull-Secret per Helfer `sli/aks/acr-pull.sh <ns>...` (nach
   `require_kube_context aks-eurocis`, idempotent; entsteht hier, P2
   Schritt 1 führt ihn in der Dateiliste von `sli/aks/`). Kern je
   Namespace, ohne Passwort in einer argv:

   ```bash
   az keyvault secret show --vault-name <kv> -n acr-pull-token \
     --query value -o tsv |
     jq -Rc --arg r <acr>.azurecr.io --arg u aks-pull \
       '{auths:{($r):{username:$u,password:.,auth:(($u+":"+.)|@base64)}}}' |
     kaks -n "$ns" create secret generic acr-pull \
       --type=kubernetes.io/dockerconfigjson \
       --from-file=.dockerconfigjson=/dev/stdin \
       --dry-run=client -o yaml |
     kaks -n "$ns" apply --server-side -f -
   ```

   ```bash
   sli/aks/acr-pull.sh default
   kaks -n default patch serviceaccount default \
     -p '{"imagePullSecrets":[{"name":"acr-pull"}]}'
   kaks -n default run acr-pull --restart=Never --image-pull-policy=Always \
     --image=<acr>.azurecr.io/curl:8.23.0 -- curl --version
   kaks -n default wait pod/acr-pull \
     --for=jsonpath='{.status.phase}'=Succeeded --timeout=120s
   kaks -n default delete pod acr-pull
   kaks -n default run egress --rm -i --restart=Never \
     --image=<acr>.azurecr.io/curl:8.23.0 -- curl -s ifconfig.me
   # = Adresse aus Schritt 4b
   kaks -n default run llm --rm -i --restart=Never \
     --image=<acr>.azurecr.io/curl:8.23.0 -- \
     curl -s --max-time 15 -o /dev/null -w '%{http_code}' \
     <litellm-base>/v1/models
   ```

   - Das curl-Image nimmt `curl` als erstes Argument an [A: Entrypoint
     von curlimages].
   - `--from-file=...=/dev/stdin` mit kubectl auf macOS ist [A];
     Rückfall: das Secret-Manifest per `jq` aus stdin bauen und per
     `kaks apply --server-side -f -` anlegen. `--server-side` schreibt
     keine `last-applied-configuration`-Annotation mit den Daten.
   - Der Patch des default-ServiceAccount gilt nur für neue Pods ohne
     eigene `imagePullSecrets`, die genau diesen ServiceAccount nutzen
     [Quelle:
     `kubernetes.io/docs/tasks/configure-pod-container/configure-service-account`,
     "Add ImagePullSecrets to a service account";
     `kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin`].
     Er dient nur den Test-Pods in `default` (und `p2-test` in P2).
     Charts mit eigenem ServiceAccount bekommen `acr-pull` über ihre
     Values; jede Phase legt Namespace und Secret vor helm oder
     kustomize an: `traefik`, `monitoring` und `p2-test` (P2), `iam`
     (P3), `solace` (P4), `sam-solace-lab` (P5; Pflicht vor `helm
     install`, weil das SAM-Chart jedes genannte Pull-Secret per lookup
     prüft), `gpos-data` und `gpos-demo` (P6).

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
       service.beta.kubernetes.io/azure-load-balancer-resource-group: gebit-showcase-nodes
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
   az network public-ip show -g gebit-showcase-nodes -n pip-aks-ingress \
     --query "{c:ipConfiguration.id,f:dnsSettings.fqdn}" -o tsv
   ```

   Gründe und Rückfall:
   - Der Test belegt, dass `azure-pip-name` die IP aus der Node-RG
     nimmt, statt eine neue zu erzeugen, und dass
     `externalTrafficPolicy: Local` die echte Client-IP erhält
     (`RemoteAddr` in der whoami-Antwort ist die öffentliche Mac-IP),
     Voraussetzung für die Traefik-Rate-Limits je Client-IP
     (Komponente `public-guard`, P2) [Quelle:
     `learn.microsoft.com/azure/aks/configure-load-balancer-standard`].
     `azure-load-balancer-resource-group: gebit-showcase-nodes` steht
     explizit wie beim Traefik-Service (P2 Schritt 5) und wie im
     Manifest auf Learn [Quelle:
     `learn.microsoft.com/azure/aks/static-ip`]; ohne sie suchte der
     Cloud-Provider in der RG seiner Cloud-Konfiguration, bei AKS der
     Node-RG [Quelle: cloud-provider-azure master
     pkg/provider/azure_loadbalancer.go:4298-4307; A: CCM-Stand von AKS
     1.36]. Fehlt die IP, legt
     der Cloud-Provider keine an; der Service scheitert mit "PublicIP
     from annotation
     azure-pip-name(-IPv6)=... doesn't exist" [Quelle:
     cloud-provider-azure azure_loadbalancer.go, Stand 18.11.]. Die
     Annotation muss beim Anlegen da sein, sonst erzeugt AKS zuerst
     eine eigene IP [A].
   - Pflicht, als Ersatz für den Lock: Nach dem Löschen von
     `hairpin-test` existiert `pip-aks-ingress` weiter, mit
     unverändertem Label. Der Cloud-Provider wertet eine IP ohne Tag
     `k8s-azure-service` als vom Nutzer angelegt und löscht sie nie,
     auch nicht mit dem Service [Quelle: cloud-provider-azure
     azure_loadbalancer.go und pkg/consts/consts.go, Stand 18.11.; A:
     welche CCM-Version AKS 1.36 ausliefert, ist nicht geprüft].
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
   rund 1 h (rund 0,30 EUR; Quota vorhanden, P0 Schritt 4):

   ```bash
   az aks nodepool scale -g gebit-showcase --cluster-name aks-eurocis \
     -n main --node-count 2
   # Test-Pod mit 1Gi-PVC (managed-csi) schreibt eine Datei; den
   # ersten Node mit kaks cordon sperren, Pod löschen und neu anlegen:
   # er startet auf dem zweiten Node, die Datei ist da
   kaks uncordon <node-1>
   az aks nodepool scale -g gebit-showcase --cluster-name aks-eurocis \
     -n main --node-count 1
   ```

   Stop und Start, mit beiden öffentlichen IPs vorher und nachher (nur
   lokal notiert):

   ```bash
   az network public-ip show --ids "$EGRESS_ID" --query ipAddress -o tsv
   az network public-ip show -g gebit-showcase-nodes -n pip-aks-ingress \
     --query ipAddress -o tsv
   az aks stop -g gebit-showcase -n aks-eurocis   # blockiert bis zum Ende
   az aks show -g gebit-showcase -n aks-eurocis \
     --query "{p:powerState.code,s:provisioningState}" -o tsv
   # = Stopped / Succeeded, dann mindestens 30 min warten
   az aks start -g gebit-showcase -n aks-eurocis  # Dauer ab hier notieren
   sli/aks/aks-allow-me.sh --check && kaks get --raw /readyz
   # danach beide IP-Abfragen von oben wiederholen
   ```

   Microsoft verlangt nach einem Stop 15-30 min Pause vor dem Start
   [Quelle: `learn.microsoft.com/azure/aks/start-stop-cluster`, Caution
   unter "Start an AKS cluster"]. Zu Public IPs in der Node-RG sagt die
   Seite nichts; dokumentiert ist nur, dass alle Objekte außer
   Standalone-Pods erhalten bleiben [Quelle: ebenda]. Erwartung:
   Beide IPs bleiben, weil LB und IP-Ressourcen in der Node-RG
   bestehen [A]; dieser Zyklus ist die Messung. Ändert sich die
   Egress-IP doch, meldet der Owner sie neu, und das Risiko kommt ins
   Register. Dazu entstehen hier minimale Wrapper
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
   - Budget nach 3.4 (250 EUR, Actual 100 % und Forecast 100 %,
     01.12.2026-31.03.2027) auf Subscription-Ebene `azure-se`,
     gefiltert auf `ResourceGroupName` in `gebit-showcase` und
     `gebit-showcase-nodes`; im Portal oder per `az rest --method put`
     auf
     `/subscriptions/{subscriptionId}/providers/Microsoft.Consumption/budgets/eurocis-aks`
     mit `filter.dimensions` und `notifications`. Nicht
     `az consumption budget create`: Preview ohne
     Benachrichtigungs-Parameter. Ein Contributor darf eigene Budgets
     anlegen, ändern und löschen, auch mit RG-Filter [Quelle:
     `learn.microsoft.com/azure/cost-management-billing/costs/tutorial-acm-create-budgets`].
     Annahme: `gebit-showcase` enthält nur Showcase-Ressourcen, sonst
     zählt das Budget fremde Kosten mit [A].
   - Abend-Check auf dem Owner-Mac bis 05.02. (launchd, read-only):
     `az aks show -g gebit-showcase -n aks-eurocis --query
     powerState.code -o tsv` meldet abends per Benachrichtigung, wenn der
     Cluster noch `Running` ist. Ein Activity-Log-Alarm bemerkt einen
     ausgebliebenen Stopp nicht.
   - Activity-Log-Alarm auf start/stop (nur Information),
     Resource-Health-Alarm (kostenlos); Budget und diese beiden legt
     `alerts.sh cost` nach dem Create an, in `gebit-showcase` und ohne
     Region (1.4).

   Zugriffs- und Löschwächter (Activity-Log-Alarme, kostenlos;
   Contributor darf Alarme und Aktionsgruppen anlegen, weil seine
   Actions `*` sind, P0 Schritt 2), angelegt schon in Schritt 3 per
   `alerts.sh access` aus `foundation.sh pre`, also vor dem Create und
   vor dem Fenster mit aktiven lokalen Accounts. Regeln und Action
   Group liegen in `gebit-showcase`, ohne `-l` bzw. mit `-l Global`
   (1.4); Scope ist die Subscription, eingegrenzt per Bedingung auf
   `resourceGroup` `gebit-showcase` bzw. `gebit-showcase-nodes`, weil
   die Node-RG vor dem Create noch nicht existiert. Je ein Alarm auf
   `Microsoft.ContainerService/managedClusters/listClusterAdminCredential/action`
   (löst beim eigenen Bootstrap in Schritt 6 einmal aus),
   `.../managedClusters/write` (unter anderem das Wiedereinschalten
   lokaler Accounts; jeder Lauf von `aks-allow-me.sh` löst ihn auch
   aus), `.../managedClusters/delete`,
   `Microsoft.KeyVault/vaults/accessPolicies/write`,
   `Microsoft.KeyVault/vaults/delete`,
   `Microsoft.KeyVault/locations/deletedVaults/purge/action`
   (Subscription),
   `Microsoft.ContainerRegistry/registries/tokens/write`,
   `Microsoft.ContainerRegistry/registries/generateCredentials/action`
   (ein zweites Passwort für `aks-pull` per `az acr token credential
   generate --password2` löst `tokens/write` nicht aus),
   `Microsoft.ContainerRegistry/registries/delete`,
   `Microsoft.Network/publicIPAddresses/delete` in
   `gebit-showcase-nodes` und
   `Microsoft.Resources/subscriptions/resourceGroups/delete` für
   `gebit-showcase` und `gebit-showcase-nodes`. Der Key Vault ist die
   einzige Kopie der generierten Secrets und des TLS-Backups außerhalb
   des Macs, hat nur 7 Tage Soft-Delete und keinen Purge-Schutz (AKS-E17);
   nach einem Vault-Delete stellt `az keyvault recover -n <kv>` ihn
   binnen 7 Tagen wieder her (Runbook, P7 Schritt 4). Die Alarme
   erkennen Missbrauch durch andere Contributors oder ein
   versehentliches Löschen, verhindern aber nichts (P0 Schritt 3,
   Abschnitt 7).

**Wer:** Claude Schritte 1-8 nach Freigabe, in der `az`-Sitzung des
Owners; Owner: Freigabe je Schreibschritt, Entra-Login (der Bootstrap
bindet seinen Namen), `aks-allow-me.sh` für die eigenen Netze,
Hotspot-Test, EAB-Daten in den Key Vault, Meldung der Egress-IP an
den LiteLLM-Betreiber, Budget im Portal und Empfänger der Alarme.

**Abnahme:**

- Create ohne Rollenzuweisung: `az aks create` endet mit Exit-Code 0
  und ohne die Warnung "Could not create a role assignment". `az aks
  show`: Version 1.36.x, overlay/cilium, maxPods 110,
  `upgradeChannel none`, `nodeOSUpgradeChannel SecurityPatch`,
  `aadProfile.managed true`, `aadProfile.enableAzureRbac false`,
  `disableLocalAccounts true`, `nodeResourceGroup
  gebit-showcase-nodes`, `identity.type SystemAssigned`,
  `networkProfile.loadBalancerProfile.managedOutboundIPs.count 1`,
  `sku.tier Free`; `apiServerAccessProfile.authorizedIpRanges` enthält
  die Owner-IP und sonst nur Einträge, die AKS selbst gesetzt hat.
- Policy-Tags, nur Schlüssel ausgegeben: `az group show -n
  gebit-showcase-nodes --query "keys(tags)" -o tsv` und `az aks show
  -g gebit-showcase -n aks-eurocis --query "keys(tags)" -o tsv` nennen
  `Owner`, `Created Date`, `purpose` und `deleteAfter`. Die Werte von
  `Owner` und `Created Date` prüft ein stiller Vergleich gegen
  `gebit-showcase`, etwa `[ "$(az group show -n gebit-showcase-nodes
  --query tags.Owner -o tsv)" = "$(az group show -n gebit-showcase
  --query tags.Owner -o tsv)" ] && echo ok`, ebenso für `Created Date`
  und für `az aks show`; `pip-aks-ingress` trägt `Owner` und `Created
  Date` [A: per Vererbung; Prüfung ebenfalls nur per `keys(tags)`].
  Name und Adressraum des AKS-verwalteten VNet sind protokolliert.
- 1 Node Ready, `kubernetes.io/arch=arm64`, mindestens 7,8 CPU und
  28,5 GiB (29184Mi) allocatable, gemessen mit
  `kaks get nodes -o custom-columns=N:.metadata.name,CPU:.status.allocatable.cpu,MEM:.status.allocatable.memory`.
  Die Messwerte ersetzen 7820m / 30418Mi in 3.2; die Request-Summe
  aus 3.2 (7125m / 21363Mi mit `prod1k`) liegt bei höchstens 92 % CPU
  und 75 % RAM. `maxSurge` des Pools ist 1.
- `kubectl config current-context` ohne `KUBECONFIG` ist weiter
  `rancher-desktop`; `~/.kube/config` enthält kein `aks-eurocis`.
- Entra-Login und lokale Accounts: `kaks get nodes` läuft über
  kubelogin (azurecli) ohne statische Credential; `kaks auth whoami`
  zeigt den Namen des Owners (UPN bei einem Mitglied [A]); `kaks auth
  can-i '*' '*' -A` ergibt `yes` über die Bindung
  `eurocis-owner-admin`; `disableLocalAccounts` ist `true`, und erst
  danach scheitert `az aks get-credentials --admin` mit "Getting static
  credential isn't allowed"; kein Temp-Verzeichnis aus Schritt 6
  existiert mehr (auch nicht nach einem gezielt abgebrochenen
  Probelauf); `az aks rotate-certs` ist gelaufen (Datum
  notiert) oder die Entra-Gruppe ersetzt den Bootstrap
  (Owner-Entscheidung aus P0 Schritt 3).
- API-Zugriff: Von der Owner-IP ist `kaks get --raw /readyz` ok. Vom
  Handy-Hotspot (nicht in der Liste) läuft `kaks get nodes` in den
  Timeout; nach `aks-allow-me.sh` auf dem Hotspot ist `kaks get --raw
  /readyz` innerhalb von 2 min ok; `aks-allow-me.sh --prune
  <hotspot-ip>` stellt die vorherige Liste her (Vergleich vorher und
  nachher). `--prune` auf den letzten Eintrag bricht ab, ohne
  `az aks update` aufzurufen.
- Ingress-IP und Hairpin: `pip-aks-ingress` liegt in
  `gebit-showcase-nodes` (Standard, Static), `dnsSettings.fqdn` ist
  `<fqdn>`. `hairpin-test` bekommt diese IP; `curl http://<fqdn>/`
  liefert vom Mac und vom Hotspot 200, `RemoteAddr` ist die
  öffentliche Client-IP. Aus einem Pod liefert derselbe Aufruf 200,
  oder das Ergebnis "Hairpin scheitert" ist dokumentiert und der
  `coredns-custom`-Rückfall für P2 eingeplant. Nach dem Löschen des
  Tests existiert `pip-aks-ingress` weiter, `ipConfiguration` ist
  leer, das Label ist unverändert, `nslookup <fqdn>` liefert dieselbe
  IP, und kein Service im Cluster hat den Typ LoadBalancer
  (`kaks get svc -A | grep -c LoadBalancer` ergibt 0).
- PVC-Umzug: Die Datei ist nach dem Neustart auf dem zweiten Node da;
  danach hat der Pool wieder 1 Node, Test-Pod und PVC sind gelöscht.
- `az aks maintenanceconfiguration show` listet für alle drei
  Konfigurationen beide Sperrbereiche.
- Pull per Token: `roleAssignmentMode` der ACR ist
  `LegacyRegistryPermissions` [Quelle: azure-cli 2.85.0
  acr/custom.py:676-689], der Admin-Benutzer ist aus, `az acr
  repository list` zeigt `curl` und `whoami`. Token `aks-pull` ist
  `enabled`, Scope Map `_repositories_pull`, `password1` läuft am
  2027-02-28T23:59:59Z ab (nach dem 20.02.2027, nicht im Freeze).
  `sli/aks/.env.aks` hat Modus 600.
  Secret `acr-pull` (Typ `kubernetes.io/dockerconfigjson`) liegt in
  `default`; Pod `acr-pull` (arm64, Pull-Policy Always) erreicht
  `Succeeded` ohne ErrImagePull, ImagePullBackOff oder exec format
  error.
- Egress: Der Egress-Pod meldet die AKS-verwaltete Outbound-IP (gleich
  der Adresse aus `effectiveOutboundIPs`, Schritt 4b); der Owner hat
  sie dem Betreiber gemeldet (Datum notiert, Adresse nur lokal), falls
  er eine Allowlist hat oder noch nicht geantwortet hat; LiteLLM
  antwortet aus dem Pod mit einem HTTP-Code (kein Timeout). Der
  HTTP-Code belegt nur TCP/TLS; den Nachweis der Freischaltung bringen
  die Betreiber-Bestätigung (P0) und P5.
- Key Vault: `properties.enableRbacAuthorization` ist `false`; die
  einzige Access Policy gehört dem Owner und enthält nur
  Secret-Rechte; für jedes generierte Passwort-Secret ist
  `az keyvault secret show --vault-name <kv> -n <name> --query value
  -o tsv | grep -qx '[0-9a-f]\{48\}'` erfolgreich, ohne Ausgabe.
  `acr-pull-token` existiert, `acme-eab-kid` und `acme-eab-hmac`
  existieren bis 04.12. (Abfrage nur mit `-o none`).
- Hygiene: `grep -rnE '([0-9]{1,3}\.){3}[0-9]{1,3}' sli/aks/` findet
  nur die Plan-Netze (10.244.0.0/16, 10.0.0.0/16, 10.0.0.10), keine
  öffentliche IP; IP-Register und Egress-Notiz liegen nur unter
  `~/.config/eurocis-aks/`. Kein Tag-Wert, kein Username und keine ID
  steht in `sli/aks/`.
- xtrace: Die `set -x`-Mitschnitte aller P1-Läufe liegen nur unter
  `~/.config/eurocis-aks/xtrace/` (chmod 700, per `BASH_XTRACEFD`).
  Eine Zählabfrage ohne Ausgabe von Treffern ergibt 0: `cat
  ~/.config/eurocis-aks/xtrace/* | grep -c -F -f <(...)`, wobei die
  Prozess-Substitution die Werte aller Key-Vault-Secrets, die Secrets
  aus `sli/aks/.env.aks`, `OWNER_OID`, den UPN aus `kaks auth whoami`
  und die Tag-Werte `Owner` und `Created Date` liefert, wie in P7
  Schritt 2 nie per argv.
- Stop, mindestens 30 min Pause, Start fehlerfrei, Startdauer (ab
  `az aks start`) notiert; danach `aks-allow-me.sh --check` grün und
  `kaks get --raw /readyz` ok; Ingress-IP und Egress-IP sind vor und
  nach dem Zyklus gleich (oder die Abweichung ist gemeldet und im
  Risikoregister), `nslookup <fqdn>` liefert dieselbe IP.
- Budget mit Zwei-RG-Filter aktiv; Abend-Check einmal ausgelöst; die
  Zugriffs- und Löschwächter sind vor dem Create angelegt (`az monitor
  activity-log alert list -g gebit-showcase` listet alle Regeln aus
  Schritt 8, `az resource list -g gebit-showcase-nodes` enthält keine
  `Microsoft.Insights`-Ressource); der Alarm auf
  `listClusterAdminCredential` hat beim eigenen Bootstrap (Schritt 6)
  und der auf `managedClusters/write` beim Hotspot-Test
  (`aks-allow-me.sh`) je einmal ausgelöst.

**Abhängigkeiten:** P0; Azure CLI 2.93 oder neuer und kubelogin (P0
Schritt 8); Tags auf `gebit-showcase`; Label `<p>` oder das
Ersatz-Label aus P0 Schritt 5 (sonst blockiert nur `pip-aks-ingress`
mit dem Hairpin-Test, nicht der Cluster); Owner-Entscheidung zum
Bootstrap (Rotation oder Entra-Gruppe) vor dem Create; Antwort des
LiteLLM-Betreibers vor dem LLM-Test (03.12.); EAB-Daten bis 04.12.
(Prüfpunkt).

### P2 Plattform-Add-ons (3,0 PT, KW49-50)

**Ziel:** Traefik als einziger öffentlicher Eingang auf `<fqdn>`, ein
Let's-Encrypt-Zertifikat per HTTP-01, Guardrails per
ValidatingAdmissionPolicy und Monitoring in Lab-Versionen auf AKS;
keine CA-Hierarchie, kein trust-manager, kein Kyverno, keine Registry,
keine DNS-Zone, kein Workload Identity für cert-manager. Öffentlich ist
nur der Traefik-Service, alles andere bleibt ClusterIP (AKS-E5). Alles
läuft ohne Rollenzuweisung (Owner 18.11.): Pods ziehen aus ACR über
das Secret `acr-pull` ihres Namespace, die Ingress-IP liegt in der
Node-RG. Prüfpunkt 11.12. zusammen mit P3.

`<fqdn>` steht hier und in P3 für
`<p>.germanywestcentral.cloudapp.azure.com`, das DNS-Label auf der
statischen IP `pip-aks-ingress` (AKS-E4, Owner 17.11.). Seit 18.11.
liegt sie in der Node-RG `gebit-showcase-nodes` und entsteht in P1
direkt nach dem Create; mit dem Cluster verschwinden IP und Label.
Wählt der Owner `--dns-name-scope` (P1, offen), trägt `<fqdn>` einen
Hash-Anteil; für P2 ändert sich dann nur der Wert von `AKS_FQDN`. Es
gibt nur diesen einen Namen, die Apps bekommen Pfade darauf. Bei
gleichem Host gewinnt in Traefik die längste Regel [Quelle:
Traefik-Doku v3.7 "Rules and Priority", `doc.traefik.io`]. Zielbild
nach P6, P2 legt nur die Grundlage:

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

1. Ordner `sli/aks/` ausbauen (nur neue Dateien, Freigabe AKS-E15 (c)
   liegt seit 17.11. vor; die Helfer aus P1 liegen schon dort):
   `versions.env` mit den Pins (Traefik-Chart 42.4.1, Image
   `traefik:v3.7.19` per Index-Digest, cert-manager v1.21.3,
   Monitoring-Charts wie im Lab) und `AKS_FQDN`; `lib.sh` mit
   `kaks`/`haks` und `require_kube_context`; je Komponente
   `values-aks.yaml`; `setup-aks.sh <teil>`, das `lib.sh` lädt,
   `require_kube_context aks-eurocis` aufruft, `AKS_FQDN` in die
   Manifeste rendert und vor jedem `haks` oder `kaks apply` Namespace
   und Pull-Secret per `sli/aks/acr-pull.sh <ns>` (P1) anlegt.
   `--create-namespace` allein reicht nicht mehr: Ohne Secret laufen
   Pods mit ACR-Image in `ImagePullBackOff`, weil die
   Kubelet-Identität ohne Rollenzuweisung kein AcrPull hat (Owner
   18.11.). Lab-`setup.sh` bleibt unverändert, das Lab behält
   ingress-nginx. Grundlage sind die Skizzen in `gpd/spikes/aks/`;
   deren DNS-01-Issuer und interne LB-Werte sind überholt. Vor jedem
   Arbeitsblock läuft `sli/aks/aks-allow-me.sh` (P1), sonst lehnt der
   API-Server die Mac-IP ab; scheitert dessen `az aks update` mit
   `RequestDisallowedByPolicy`, gilt die Regel aus P1 (Azure/AKS
   #5856).

   Pull-Secrets und Key Vault (Owner 18.11.):
   - `acr-pull` ist ein Secret vom Typ `kubernetes.io/dockerconfigjson`
     mit dem Pull-Token `aks-pull` (Scope-Map nur zum Lesen, P1); das
     Passwort kommt per Pipe aus dem Key-Vault-Secret
     `acr-pull-token`, nie in argv oder Ausgabe (P1).
     Namespaces in P2: `traefik`, `monitoring`, `p2-test`; in P3:
     `iam`. `cert-manager` braucht keins, alle Images kommen von
     quay.io [Quelle: cert-manager v1.21.3
     deploy/charts/cert-manager/values.yaml:6-13, 182].
   - Der Chart-Wert unterscheidet sich je Chart (Liste von Strings
     oder von Objekten):
     - Traefik 42.4.1: `deployment.imagePullSecrets: [{name: acr-pull}]`
       [Quelle: Traefik-Chart 42.4.1 values.yaml:18-19, 102-103,
       910-911; templates/_podtemplate.tpl:28-31].
     - kube-prometheus-stack 83.5.0: `grafana.image.pullSecrets:
       [acr-pull]` (Strings); nur Grafana kommt aus ACR [Quelle:
       kube-prometheus-stack 83.5.0 values.yaml:349-355;
       charts/grafana/values.yaml:108-113;
       charts/grafana/templates/_pod.tpl:594-597].
     - loki 6.55.0: `imagePullSecrets: [{name: acr-pull}]` auf oberster
       Ebene; gilt für das SingleBinary-StatefulSet samt
       Rules-Sidecar [Quelle: loki 6.55.0 values.yaml:48-49;
       templates/single-binary/statefulset.yaml:75-76].
     - tempo 2.0.0: `tempo.pullSecrets: [acr-pull]` (Strings) [Quelle:
       tempo 2.0.0 values.yaml:31-36; templates/statefulset.yaml:44-48].
     - alloy 1.11.0: `image.pullSecrets: [{name: acr-pull}]`; der
       config-reloader im selben Pod bekommt es mit [Quelle: alloy
       1.11.0 values.yaml:18-19, 162-163;
       templates/controllers/_pod.yaml:23-30].
     - Keycloak und Postgres (P3): kustomize-Patch, weil die
       Lab-Manifeste weder `imagePullSecrets` noch
       `serviceAccountName` setzen.

     `haks template` mit Lab- und aks-Values zeigt vor jedem Install
     an jedem Pod mit ACR-Image `acr-pull`; das ersetzt den
     AcrPull-Nachweis.
   - Ad-hoc-Pods (`kaks run`) in `default` und `p2-test` bekommen das
     Secret über einen Patch des default-ServiceAccounts. Der wirkt
     nur auf Pods, die nach dem Patch entstehen und keine eigenen
     `imagePullSecrets` tragen, also nie auf Chart-Pods mit eigenem
     ServiceAccount [Quelle:
     `kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin`;
     `kubernetes.io/docs/tasks/configure-pod-container/configure-service-account`].
   - Key Vault im Access-Policy-Modus (P1 Schritt 3): Die Skripte lesen
     und schreiben mit dem `az login` des Owners über seine Access
     Policy; der Cluster selbst hat keinen Zugriff auf den Key Vault
     (kein CSI-Treiber, AKS-E17). K8s-Secrets aus dem Key Vault
     entstehen per Pipe mit `--from-file=<key>=/dev/stdin`, nie per
     `--from-literal` [A: `/dev/stdin` mit kubectl auf macOS, Test in
     P1].
2. Vorbedingungen read-only prüfen:

   ```bash
   az network public-ip show -g gebit-showcase-nodes -n pip-aks-ingress \
     --query "{ip:ipAddress,fqdn:dnsSettings.fqdn,sku:sku.name}" -o tsv
   az network public-ip show -g gebit-showcase-nodes -n pip-aks-ingress \
     --query 'tags."k8s-azure-service"' -o tsv     # leer
   dig +short <fqdn>                               # = ipAddress
   kaks auth can-i '*' '*' -A                      # yes (Binding, P1)
   ```

   Das Label hängt an der IP, nicht am Service. Der Cloud-Provider
   gleicht DNS-Einstellungen nur ab, wenn ein Service
   `azure-dns-label-name` trägt, ein leerer Wert löscht das Label;
   kein Manifest setzt die Annotation, die VAP aus Schritt 3
   verbietet sie [Quelle:
   `cloud-provider-azure.sigs.k8s.io/topics/loadbalancer`;
   cloud-provider-azure master
   pkg/provider/azure_loadbalancer.go:1557-1566, 1626-1675]. Eine IP
   ohne Tag `k8s-azure-service` gilt als nutzererstellt: Der
   Cloud-Provider setzt dort keine Service-Tags und löscht sie nie,
   auch nicht mit dem Service [Quelle: ebd. :3791-3802, 4401-4460;
   A: CCM-Stand von AKS 1.36]. Rollen braucht niemand: Die
   Control-Plane-Identität hat per AKS-Default Contributor auf der
   Node-RG [Quelle: `learn.microsoft.com/azure/aks/static-ip`;
   `learn.microsoft.com/azure/aks/managed-identity-overview`]. Einen
   Lock gibt es nicht, weil der Rolle Contributor
   `Microsoft.Authorization/locks/*` fehlt [Quelle:
   `learn.microsoft.com/azure/azure-resource-manager/management/lock-resources`].
   Die IP verschwindet deshalb mit jedem `az aks delete` (die Node-RG
   wird samt Inhalt gelöscht [Quelle:
   `learn.microsoft.com/azure/aks/faq`]) oder durch ein manuelles
   Löschen; danach kann jeder das Label in der Region belegen
   (Restrisiko, Abschnitt 7; Option in Schritt 10).
   Fehlt die IP, legt der Cloud-Provider trotz `azure-pip-name` keine
   neue an, der Service bleibt mit "PublicIP from annotation
   azure-pip-name ... doesn't exist" ohne Adresse [Quelle: ebd.
   :1359-1362, 1496-1498]; ein Neuaufbau legt sie deshalb vor
   Traefik an (P1).
3. PriorityClasses und Guardrails per `kaks apply -f`, vor Traefik,
   damit schon dessen Service die Regeln durchläuft:
   - `demo-critical` als `globalDefault` (der SAM-Chart kennt kein
     `priorityClassName` [Quelle: values.schema.json, SAM-Leser]),
     `demo-observability` niedriger, explizit in den Monitoring-Values.
   - ValidatingAdmissionPolicy (GA seit 1.30, kein Webhook, blockiert
     `az aks stop` nicht), ein Binding mit `validationActions: [Deny]`
     je Policy (AKS-E12):
     - Service: `type: LoadBalancer` nur für `traefik/traefik`, nur
       mit `azure-pip-name: pip-aks-ingress`; die Annotation
       `azure-load-balancer-resource-group` fehlt oder ist gleich
       `gebit-showcase-nodes`; nie mit `azure-dns-label-name`;
       `externalIPs` nirgends. Das fängt den öffentlichen LB-Default
       des pubsubplus-Charts (P4), einen zweiten LB-Service im
       Namespace `traefik` (weitere LB-Regeln auf der öffentlichen IP),
       einen Traefik-Service ohne `azure-pip-name` (dann legte der
       Cloud-Provider eine eigene IP in der Node-RG an, und `<fqdn>`
       zeigte ins Leere) und eine RG-Annotation auf eine fremde
       Ressourcengruppe (dort hat die Cluster-Identität keine Rechte,
       und mit Contributor lassen sie sich nicht vergeben).
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
            .orValue('gebit-showcase-nodes') == 'gebit-showcase-nodes' &&
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
   `nginx-unprivileged` nur, falls das Loki-Gateway an ist. Gründe:
   Alle Node-Pulls gehen über die eine AKS-verwaltete Outbound-IP
   (nach jedem Neuaufbau eine andere), anonyme Docker-Hub-Limits
   träfen sonst Drills. cert-manager kommt von quay.io (multi-arch).
   `az acr import` ist eine ARM-Aktion und mit Contributor möglich.
   Den Push per `az acr login` und `docker buildx imagetools create`
   darf der Owner als Contributor nur, weil P1 die Registry im Modus
   `rbac` anlegt; im Modus mit ABAC hätte Contributor keine Rechte auf
   der Datenebene [Quelle:
   `learn.microsoft.com/azure/container-registry/container-registry-rbac-built-in-roles-directory-reference`].
   Aus ACR zieht der Node nur über `acr-pull` (Schritt 1).
5. Traefik v3 mit NGINX-Provider (AKS-E6), eine Replika, ein
   LoadBalancer-Service:

   ```bash
   sli/aks/acr-pull.sh traefik       # Namespace und Secret acr-pull
   haks upgrade --install traefik traefik \
     --repo https://traefik.github.io/charts --version 42.4.1 \
     -n traefik -f sli/aks/traefik-values.yaml
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
     imagePullSecrets:
       - name: acr-pull               # Token aks-pull (Schritt 1)
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
       # IP in der Node-RG, RG explizit wie im Learn-Manifest static-ip
       service.beta.kubernetes.io/azure-pip-name: pip-aks-ingress
       service.beta.kubernetes.io/azure-load-balancer-resource-group: gebit-showcase-nodes
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

   [Quelle: Traefik-Chart 42.4.1 values.yaml:102-103, 130-134,
   314-345, 424-505, 1086, 1126, 1175-1198, 1329]. Pins: Chart 42.4.1
   (App v3.7.19, kubeVersion ab 1.30), nie unter v3.7.18 (fünf GHSAs
   am 12.11. behoben), kein v3.8.0-rc [Quelle: GitHub-API Releases und
   Security-Advisories, 17.11.]. `azure-load-balancer-resource-group:
   gebit-showcase-nodes` steht explizit, wie im Manifest auf Learn,
   dessen Troubleshooting sich auf genau diese Annotation bezieht
   [Quelle: `learn.microsoft.com/azure/aks/static-ip`]. Ohne sie
   suchte der Cloud-Provider die IP aus `azure-pip-name` in der
   Ressourcengruppe seiner Cloud-Konfiguration, bei AKS der Node-RG;
   das belegt nur der Code [Quelle: cloud-provider-azure master
   pkg/provider/azure_loadbalancer.go:4298-4307; A: CCM-Stand von AKS
   1.36], nicht Learn. Die VAP lässt beide Formen zu (Schritt 3).
   Eine Annotation `azure-pip-resource-group` gibt es nicht; der
   Name der RG-Annotation lautet `azure-load-balancer-resource-group`.
   Der Service öffnet nur 80 und 443 (Ports `traefik` und `metrics`
   sind nicht exponiert, HTTP/3 aus): zwei LB-Regeln plus die
   Outbound-Regel der AKS-verwalteten Egress-IP, also innerhalb der
   fünf im Grundpreis enthaltenen Regeln. Mit
   `externalTrafficPolicy: Local` probt Azure den
   `healthCheckNodePort` per HTTP; ein eigener Probe-Pfad entfällt
   [Quelle:
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
      Azure gehört; 7 Tage statt 1 Jahr, weil der Name mit jedem
      Löschen des Clusters (Rückbau oder Neuaufbau) frei wird und dann
      ein anderer Azure-Kunde ihn belegen kann [A].
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
   EAB-Rückfall. cert-manager braucht kein Pull-Secret (quay.io,
   Schritt 1).

   ```bash
   haks upgrade --install cert-manager cert-manager \
     --repo https://charts.jetstack.io --version v1.21.3 \
     -n cert-manager --create-namespace \
     -f sli/pki/manifests/01-cert-manager-values.yaml \
     -f sli/aks/cert-manager-values.yaml   # Requests nach 3.2
   sli/aks/setup-aks.sh tls   # ClusterIssuer, Certificate, EAB-Secret
   # darin, ohne gerenderte Datei:
   envsubst '${EAB_KID} ${EAB_ACME_SERVER} ${TLS_ISSUER} ${AKS_FQDN}' \
     < sli/aks/tls/issuers.tpl.yaml | kaks apply -f -
   ```

   Die Vorlage bleibt im Repo mit den Platzhaltern; die Werte kommen
   aus der Umgebung (`sli/aks/.env.aks`), nie aus argv, und eine
   gerenderte Datei entsteht nicht, weil `*.yaml` unter `sli/aks/tls/`
   nicht ignoriert ist. `envsubst` (gettext) liegt auf dem Owner-Mac
   [Quelle: Befehl `which envsubst`, 18.11.]. Das HMAC-Secret läuft
   per Pipe aus dem Key Vault (unten).

   ```yaml
   # sli/aks/tls/issuers.tpl.yaml (Auszug, Vorlage im Repo)
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
     Geht `<p>` bei einem Neuaufbau verloren (Label inzwischen von
     Dritten belegt), braucht der Ersatzname wieder eine
     Erstausstellung aus dem geteilten Topf; deshalb bindet der
     Neuaufbau das Label sofort neu (P1, P7).
   - Erst `TLS_ISSUER=letsencrypt-staging`; `openssl s_client
     -connect <fqdn>:443 -servername <fqdn>` zeigt einen Aussteller
     mit "(STAGING)". Dann sofort `letsencrypt-prod`, möglichst am
     ersten P2-Tag (03.12.).
   - Rückfall: `acme-eab-fallback` für eine ACME-CA mit External
     Account Binding (ZeroSSL oder Google Trust Services). Der Owner
     legt das Konto an (P0 Schritt 6) und trägt die EAB-Daten selbst
     als `acme-eab-kid` und `acme-eab-hmac` in den Key Vault (P1
     Schritt 3, über seine Access Policy) sowie mit der Directory-URL
     in `sli/aks/.env.aks` ein;
     `setup-aks.sh` legt daraus das Secret `cert-manager/acme-eab-hmac`
     per Pipe an, ohne einen Wert auszugeben [A: Directory-URL und
     Limits der gewählten CA beim Anlegen prüfen]. Der Issuer wird
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
     P7 Schritt 2). Key Vault und Backup überleben ein `az aks delete`,
     weil sie in `gebit-showcase` liegen, nicht in der Node-RG. Ein
     Neuaufbau spielt das Backup vor dem Certificate ein, sofern `<p>`
     wieder auf der neuen `pip-aks-ingress` liegt (P1); cert-manager
     übernimmt ein passendes Secret ohne neue Bestellung [A:
     Restore-Drill in P2, belegt durch keine neue CertificateRequest].
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
   mit `spec.tls.hosts: [<fqdn>]` ohne `secretName`. Vor dem ersten
   Pod legt `setup-aks.sh p2-test` Namespace und `acr-pull` an
   (`acr-pull.sh p2-test`) und patcht den default-ServiceAccount für
   die Ad-hoc-Pods (Schritt 1):

   ```bash
   kaks -n p2-test patch serviceaccount default \
     -p '{"imagePullSecrets":[{"name":"acr-pull"}]}'
   ```

   Die Test-Manifeste in `sli/aks/p2-test/` tragen
   `imagePullSecrets: [{name: acr-pull}]` zusätzlich selbst.
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
     per `setup-aks.sh p2-test` wieder anlegbar (samt `acr-pull` und
     Patch des default-ServiceAccounts), ab P6 ohne `p2-grpc` (keine
     Reflection-Pfade, sonst gäbe es zwei Ingresses mit denselben
     Regeln wie `gpos-grpc-reflection`).
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
   <aks-Values>`; vorher `sli/aks/acr-pull.sh monitoring`. Overlay:
   - Registry je Image, nicht global: kube-prometheus-stack
     `grafana.image.registry: <acr>.azurecr.io` (kein
     `global.imageRegistry`, sonst würden quay.io- und
     registry.k8s.io-Images umgelenkt, die nicht gespiegelt sind); loki
     `loki.image.registry` und `sidecar.image.registry`; tempo
     `tempo.registry`; alloy nur `image.registry` (der config-reloader
     bleibt auf quay.io). Tags bleiben Chart-Default, die Charts sind
     gepinnt.
   - Pull-Secrets genau an diesen Pods, mit den Keys aus Schritt 1:
     `grafana.image.pullSecrets: [acr-pull]`, loki
     `imagePullSecrets: [{name: acr-pull}]`, `tempo.pullSecrets:
     [acr-pull]`, alloy `image.pullSecrets: [{name: acr-pull}]`. Der
     Render-Check aus Schritt 1 läuft vor jedem `haks upgrade`.
   - Grafana ohne Ingress und ohne Pfad auf `<fqdn>`; Zugriff per
     `kaks -n monitoring port-forward svc/kube-prometheus-grafana
     3000:80`; Admin aus Secret. Prometheus ebenso nur per
     Port-Forward.
   - `grafana.additionalDataSources` vollständig neu deklariert, weil
     Helm Listen bei mehreren `-f` ersetzt: Loki, Tempo (mit
     derivedFields, tracesToLogs, tracesToMetrics) und "SAM Platform DB"
     mit denselben uids wie im Lab. Deren Passwort ist
     `$__env{GRAFANA_RO_PASSWORD}`, gespeist über `grafana.envValueFrom`
     aus einem K8s-Secret `monitoring/grafana-ro`. Das Skript legt es
     aus dem Key Vault per Pipe an, ohne den Wert in die argv zu legen:

     ```bash
     az keyvault secret show --vault-name <kv> -n grafana-ro \
       --query value -o tsv | tr -d '\n' |
       kaks -n monitoring create secret generic grafana-ro \
         --from-file=password=/dev/stdin --dry-run=client -o yaml |
       kaks -n monitoring apply -f -
     ```

     Ein Render-Check vergleicht die uids mit den Lab-Values.
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
   - Defender for Cloud: Die Pläne für Container, Kubernetes und
     Registry sind Free (Check vom 18.11.), es läuft kein
     Defender-Sensor. Traefik-Ist-Werte mit `kaks top pods -A` messen,
     dann 3.2 nachtragen.
10. Option NRG-Lockdown als Ersatz für den Lock (Owner-Entscheidung
    offen; nur nach Owner-Go und nach grünen Schritten 5 und 6):

    ```bash
    az aks update -g gebit-showcase -n aks-eurocis \
      --nrg-lockdown-restriction-level ReadOnly
    az aks show -g gebit-showcase -n aks-eurocis \
      --query nodeResourceGroupProfile.restrictionLevel -o tsv  # ReadOnly
    ```

    ReadOnly legt eine Deny Assignment auf `gebit-showcase-nodes`,
    die Nutzern nur `*/read` lässt; ein versehentliches
    `az network public-ip delete` oder ein Löschen der Node-RG
    scheitert dann [Quelle:
    `learn.microsoft.com/azure/aks/node-resource-group-lockdown`;
    `learn.microsoft.com/azure/aks/faq`]. Kein Schutz gegen
    `az aks delete`, das die Node-RG samt IP über den AKS-RP löscht.
    Das Flag braucht nur `managedClusters/write`, keine
    Rollenzuweisung [Quelle: azure-cli dev acs/_params.py:451, 773].
    Tests [A]:
    - Ein harmloser Schreibversuch des Owners,
      `az network public-ip update -g gebit-showcase-nodes -n
      pip-aks-ingress --set tags.lockdowntest=1`, wird abgelehnt.
      Gelingt er doch, den Tag sofort entfernen und den Lockdown als
      unwirksam vermerken. Nie mit einem Delete testen.
    - Der Cloud-Provider darf weiter schreiben: Idle-Timeout-Annotation
      des Traefik-Service per `haks upgrade` kurz auf "29" und zurück
      auf "30"; beide Male kein Event `SyncLoadBalancerFailed`
      (`kaks -n traefik get events --field-selector
      involvedObject.name=traefik`), EXTERNAL-IP unverändert.

    Muss `pip-aks-ingress` geändert werden (etwa das Label), vorher
    `--nrg-lockdown-restriction-level Unrestricted`. Jeder
    `az aks update` folgt der Policy-Regel aus P1 (Azure/AKS #5856).
    Ohne Owner-Go bleibt das Restrisiko aus Abschnitt 7.

**Wer:** Claude Schritte 1-9 nach Freigabe je Schreibschritt, Schritt
10 nur nach Owner-Go; Owner legt das Konto bei der Rückfall-CA an und
trägt die EAB-Werte selbst in Key Vault und `sli/aks/.env.aks` ein.

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
  `az network lb rule list -g gebit-showcase-nodes --lb-name
  kubernetes` zeigt nur TCP 80 und 443; `nc -z -w 5 <fqdn>` auf 8080,
  8443, 9000 und 9100 läuft in den Timeout.
- `pip-aks-ingress` in `gebit-showcase-nodes`: `ipConfiguration.id`
  zeigt auf den LB `kubernetes`, `dnsSettings.fqdn` ist `<fqdn>`, der
  Tag `k8s-azure-service` fehlt (nutzererstellt, der Cloud-Provider
  löscht die IP nie).
- Negativ-Manifeste werden per VAP abgelehnt: LoadBalancer in einem
  anderen Namespace, ein zweiter LoadBalancer-Service im Namespace
  `traefik`, der Traefik-Service ohne `azure-pip-name`, der
  Traefik-Service mit `azure-load-balancer-resource-group:
  gebit-showcase`, LoadBalancer mit `azure-dns-label-name`, Ingress
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
- Pull-Secrets: Kein Pod mit ACR-Image ohne `acr-pull`, kein
  `ImagePullBackOff` (ab P3 je Phase wiederholt):

  ```bash
  kaks get pods -A -o json | jq -r '.items[]
    | select([.spec.containers[]?, .spec.initContainers[]?]
        | any(.image | startswith("<acr>.azurecr.io/")))
    | select((.spec.imagePullSecrets // []) | map(.name)
        | index("acr-pull") | not)
    | .metadata.namespace + "/" + .metadata.name'      # leer
  ```

- Grafana, Prometheus und Traefik-Dashboard: kein Ingress, keine
  IngressRoute auf `websecure`, Zugriff nur per Port-Forward.
- `kaks get pdb -A`: keine PDB mit 0 erlaubten Unterbrechungen auf
  einem Einzel-Pod, sonst blockiert sie den Drain beim
  Node-Image-Update (3.3).
- CPU-Requests von System, Traefik, cert-manager und Monitoring
  gemessen und in 3.2 eingetragen, dazu als zeitweilige Reserve der
  Run-Pod von `az aks command invoke` (200m CPU, 500Mi) [Quelle:
  `learn.microsoft.com/azure/aks/access-private-cluster`]; liegen sie
  über 2044m, installiert P4 den Broker als `dev` (Kriterium 3.2).
  `kaks get ds -A | grep -ci defender` ergibt 0.
- Option NRG-Lockdown entschieden; bei Ja: `restrictionLevel`
  `ReadOnly`, beide Tests aus Schritt 10 grün.

**Abhängigkeiten:** P1 (Cluster mit ClusterRoleBinding des Owners,
`pip-aks-ingress` mit Label `<p>` in `gebit-showcase-nodes`, Token
`aks-pull` mit Passwort im Key Vault und `acr-pull.sh`, Registry im
Modus `rbac`, `aks-allow-me.sh`, Hairpin-Ergebnis aus P1 Schritt 8);
EAB-Konto und EAB-Daten des Owners bis 04.12. (P0 Schritt 6), sonst
nur Let's Encrypt mit dem Risiko aus Schritt 6; für `gebitsim` in
Schritt 7 die schriftliche GEBIT-Bestätigung bis 09.12. (AKS-E16);
Owner-Entscheidung zu Schritt 10.

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
   Beide Pods ziehen im Namespace `iam` aus ACR, also mit `acr-pull`
   (P2 Schritt 1). Die Lab-Manifeste setzen weder `imagePullSecrets`
   noch `serviceAccountName` [Quelle: sli
   keycloak/manifests/02-postgres.yaml:31-54;
   03-keycloak.yaml:119-141]; das Overlay patcht deshalb beide
   Workloads (Schritt 2). Ein Patch des default-ServiceAccounts
   reicht nicht: Er wirkt nur auf Pods, die nach ihm entstehen, und
   liefe mit den ersten Pods eines frisch angelegten Namespace um die
   Wette [Quelle:
   `kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin`].
2. Overlay `sli/aks/keycloak/` (ein Pfad, wie in 5.1). Lab
   `keycloak/manifests` hat keine `kustomization.yaml` [Quelle: Befehl
   `ls sli/keycloak/manifests`, 16.11.]; die aks-kustomization listet
   deshalb `../../keycloak/manifests/01-namespace.yaml` bis
   `05-monitoring.yaml` einzeln als Ressourcen und hält ihre Patches
   daneben. Anwendung nur über das Skript:

   ```bash
   sli/aks/setup-aks.sh keycloak
   # intern: require_kube_context aks-eurocis, acr-pull.sh iam
   # (Namespace und Pull-Secret), Secrets aus Key Vault per Pipe
   # anlegen, dann
   # kubectl kustomize --load-restrictor LoadRestrictionsNone \
   #   sli/aks/keycloak | kaks apply -f -
   # und vor dem Readiness-Check von Keycloak auf postgres warten
   ```

   Images und Pull-Secret im Overlay (Auszug):

   ```yaml
   # sli/aks/keycloak/kustomization.yaml (Auszug)
   images:
     - name: quay.io/keycloak/keycloak
       newName: <acr>.azurecr.io/keycloak/keycloak
       digest: <keycloak-digest>
     - name: postgres
       newName: <acr>.azurecr.io/postgres
       digest: <postgres-digest>
   patches:
     - target: {kind: Deployment, name: keycloak}
       patch: |-
         - op: add
           path: /spec/template/spec/imagePullSecrets
           value: [{name: acr-pull}]
     - target: {kind: StatefulSet, name: postgres}
       patch: |-
         - op: add
           path: /spec/template/spec/imagePullSecrets
           value: [{name: acr-pull}]
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
     Realm-User eines, P1 Schritt 3), gelesen über die Access Policy
     des Owners und per Pipe als K8s-Secrets angelegt (P2 Schritt 1).
     Speicher 1Gi Request / 1,5Gi Limit.
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
- Images: `kaks -n iam get deploy/keycloak sts/postgres -o
  jsonpath='{..image} {..imagePullSecrets}'` zeigt beide Images aus
  `<acr>.azurecr.io` per Digest und `acr-pull`; kein
  `ImagePullBackOff`; die Pull-Secret-Prüfung aus der P2-Abnahme
  bleibt leer.
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
`nginx`, VAP), Key-Vault-Secrets aus P1, Token `aks-pull` und
`acr-pull.sh` aus P1, Profil-Änderungen der amd-Skripte (P0 Schritt
10, AKS-E15 (b), freigegeben 17.11.).

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
   `az acr import` kopiert bei einer Manifestliste alle Plattformen
   (höchstens 50 Manifeste) [Quelle: Learn-Seite
   `container-registry-import-images`, ms.date 26.08.2026]. [A: Der
   Index-Digest bleibt dabei unverändert; weicht er ab, gilt der
   ACR-Digest, und `docker buildx imagetools inspect` vergleicht das
   arm64-Manifest mit dem Lab.] Rechte: Der Import ist eine ARM-Aktion,
   die Contributor deckt. `az acr repository show` liest dagegen über
   die Datenebene; die hat Contributor nur im Registry-Modus `rbac`,
   den P1 Schritt 3 beim Anlegen explizit setzt. Im Modus `rbac-abac`
   hätte Contributor weder Pull noch Push [Quelle: Learn-Seite
   `container-registry-rbac-built-in-roles-directory-reference`].
2. Installation: zuerst der Namespace, dann die beiden Secrets
   `solace-admin` und `acr-pull`, dann helm.

   ```bash
   kaks create namespace solace --dry-run=client -o yaml | kaks apply -f -
   az keyvault secret show --vault-name <kv> -n solace-admin \
     --query value -o tsv | tr -d '\n' |
     kaks -n solace create secret generic solace-admin \
       --from-file=username_admin_password=/dev/stdin \
       --dry-run=client -o yaml | kaks apply -f -
   sli/aks/acr-pull.sh solace     # Pull-Secret aus dem ACR-Token
   kaks -n solace get secret solace-admin acr-pull -o name
   haks upgrade --install solace pubsubplus \
     --repo https://solaceproducts.github.io/pubsubplus-kubernetes-helm-quickstart/helm-charts \
     --version 3.10.0 -n solace -f emd/aks/pubsubplus-values.yaml
   ```

   - Das Admin-Passwort läuft per stdin in das Secret, nie über die
     argv von `kubectl`; das ist die Regel aus P1 Schritt 3 (die
     Fassung vom 17.11. nutzte hier noch `--from-literal="$(...)"`).
     `--from-file` mit `/dev/stdin` prüft P1 auf macOS [A]; Rückfall:
     das Secret-Manifest per `jq` aus stdin bauen und per
     `kaks apply -f -` anlegen. Gelesen wird über die Access Policy
     des Owners im Key Vault (P1 Schritt 3).
   - `acr-pull` (Typ `kubernetes.io/dockerconfigjson`) baut der Helfer
     aus P1 Schritt 8 aus dem Token-Passwort im Key Vault
     (`acr-pull-token`, P1 Schritt 3), ohne Passwort in der argv.
     Einen Pull über die Kubelet-Identität gibt es nicht: `--attach-acr`
     bräuchte eine Rollenzuweisung, und die schließt die
     Owner-Entscheidung vom 18.11. aus. Das `pubsubplus`-Chart prüft
     das Pull-Secret nicht beim Rendern; fehlt es, bleibt der Pod in
     `ImagePullBackOff`. Ein Patch des default-ServiceAccounts hilft
     nicht, weil das Chart ein eigenes ServiceAccount anlegt [Quelle:
     pubsubplus 3.10.0 templates/solaceStatefulSet.yaml:42-45, 56;
     Kubernetes-Doku "Configure Service Accounts for Pods", Abschnitt
     "Add ImagePullSecrets to a service account"].

   `--create-namespace` allein reicht nicht: Das Chart prüft schon beim
   Rendern per `lookup`, dass das Admin-Secret im Release-Namespace
   existiert [Quelle: pubsubplus 3.10.0 templates/secret.yaml:1-7,
   values.yaml:66-70]. Werte in `emd/aks/pubsubplus-values.yaml`:
   - `solace.redundancy: false`,
     `solace.usernameAdminPasswordSecretName: solace-admin`.
   - `image.repository: <acr>.azurecr.io/solace/solace-pubsub-standard`,
     `image.tag: "10.26.0.9219@<D>"`. Das Chart baut
     `repository:tag`, Tag plus Digest ist eine gültige Referenz, und
     die Versionsprüfung im Template liest daraus 10.26 [Quelle:
     pubsubplus 3.10.0 templates/solaceStatefulSet.yaml:60, 118].
     Chart-Default wäre `latest` [Quelle: values.yaml:113-117].
   - `image.pullSecretName: acr-pull`: ein einzelner String, keine
     Liste wie bei SAM [Quelle: pubsubplus 3.10.0 values.yaml:122-123].
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
     gemessenen CPU-Requests von System, Traefik, cert-manager und
     Monitoring über 2044m, oder bleibt der Broker-Pod Pending, dann
     `dev`. Ein Defender-Sensor fällt aus der Summe: Alle
     Defender-Pläne der Subscription `azure-se` stehen auf Free
     (Prüfung 18.11.), es läuft also kein Sensor-DaemonSet [A:
     Re-Check vor G4]. Die Reserve unter der 92-%-Grenze (mindestens
     626m) trägt auch kurzlebige Pods, etwa den Run-Pod von
     `az aks command invoke` (Request 200m/500Mi) [Quelle:
     `learn.microsoft.com/azure/aks/access-private-cluster`] und die
     Debug-Pods aus P5. Vor dem ersten Install entscheiden: Größe und
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
  `true` (nur der Schlüssel, nie der Wert); `kaks -n solace get secret
  acr-pull -o jsonpath='{.type}'` liefert
  `kubernetes.io/dockerconfigjson`.
- `kaks -n solace get sts solace-pubsubplus -o jsonpath='{..image}'`
  endet auf `@sha256:c0020e53ed48...`, und
  `-o jsonpath='{.spec.template.spec.imagePullSecrets}'` nennt
  `acr-pull`; die Events des Pods zeigen einen erfolgreichen Pull aus
  `<acr>.azurecr.io`, kein `ImagePullBackOff`. SEMP meldet
  10.26.0.9219; ein PVC 128Gi `managed-csi-premium` Bound; die
  gewählte Größe (`prod1k` oder `dev`) ist mit Begründung notiert.
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
AKS-E15 (d). Teil B: Teil A grün; aus P1 ACR im Modus `rbac`, das
ACR-Token mit Passwort im Key Vault (Ablauf nach dem 20.02.2027) und
die Access Policy des Owners und der Helfer `sli/aks/acr-pull.sh`
(P1 Schritt 8); P2 (ACR-Spiegel, PriorityClasses, VAP); AKS-E15 (c) für
`emd/aks/` und `emd/terraform-aks/`. Ist Teil A
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
   - Push mit der Entra-Identität des Owners (`az acr login`, Rolle
     Contributor). Das geht nur, weil P1 Schritt 3 die Registry im
     Modus `rbac` anlegt; im Modus `rbac-abac` hätte Contributor keine
     Datenebene [Quelle: Learn-Seite
     `container-registry-rbac-built-in-roles-directory-reference`].
     Vorher `az acr show -n <acr> --query roleAssignmentMode -o tsv`,
     erwartet `LegacyRegistryPermissions` [Quelle: azure-cli 2.85.0
     acr/custom.py:676-689; azure-mgmt-containerregistry
     models/_enums.py:356].
   - Das Pull-Token aus P1 hängt an einer Scope-Map nur mit
     Leserechten; mit ihm ist kein Push möglich, und der Cluster
     braucht auch keinen.
   - Danach `az acr show-usage -n <acr> -o table`: Basic enthält
     10 GiB [Quelle: Learn-Seite `container-registry-skus`, ms.date
     15.10.2026], und die SAM-Images sind die größten des Projekts
     [A: Messung nach diesem Push].
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
   - `global.imagePullSecrets: ["acr-pull"]`, eine Liste reiner
     Strings wie im Lab (dort `registry-pull-secret` [Quelle: amd
     local-k8s-values.yaml:144-150]). Helm ersetzt Listen beim
     Zusammenführen der `-f`-Dateien, statt sie zu mischen; der
     Lab-Eintrag verschwindet also [A: im Render-Diff aus P0
     Schritt 13 sichtbar]. Die Liste gilt für gwe, awe, str, Postgres,
     SeaweedFS und den Pre-Install-Hook `sam-doctor`, der das
     gwe-Image zieht [Quelle: SAM-Chart 2.3.10
     charts/sam-common/templates/_images.tpl:46-61,
     templates/sam-doctor-hook.yaml:36-49]. Bei `helm upgrade
     --install` prüft der Chart per `lookup`, dass jedes genannte
     Secret im Release-Namespace liegt, und bricht sonst ab
     (`validations.clusterResourceChecks`, Default `true`) [Quelle:
     SAM-Chart 2.3.10 templates/_validations.tpl:97-126, 191-210;
     values.yaml:89]. `helm template` überspringt diese Prüfung; der
     Render-Diff beweist das Secret also nicht. Die Fassung vom 17.11.
     setzte hier `[]`, weil der Kubelet per AcrPull zog; das entfällt
     mit der Owner-Entscheidung vom 18.11. (keine Rollenzuweisungen).
   - Nicht genutzt: `global.imagePullKey`. Damit legte der Chart das
     Pull-Secret selbst an, und das Token-Passwort stünde in jeder
     Helm-Revision; zudem schließt der Chart es neben
     `global.imagePullSecrets` aus [Quelle: SAM-Chart 2.3.10
     values.yaml:43-51, templates/_validations.tpl:26-29].
     `samDeployment.imagePullSecret` bleibt leer, der Chart empfiehlt
     die globale Liste [Quelle: values.yaml:474-476].
   - Registry `<acr>.azurecr.io` in allen sechs Image-Blöcken;
     `broker.url: ws://solace-pubsubplus.solace.svc.cluster.local:8008`,
     `broker.clientUsername: sam`, `broker.vpn: sam`;
     `persistence-layer.{postgresql,seaweedfs}.persistence.storageClassName:
     managed-csi-premium`; awe-Limit 3Gi, str-Limit 6Gi.
3. Installation per Profil (AKS-E19 entschieden 17.11.). Das
   Broker-Passwort heißt im Chart `broker.password` [Quelle: amd
   local-k8s-values.yaml:67-71]:

   ```bash
   kaks create namespace sam-solace-lab --dry-run=client -o yaml |
     kaks apply -f -
   sli/aks/acr-pull.sh sam-solace-lab   # Secret acr-pull
   SAM_PROFILE=aks amd/scripts/start.sh
   # intern (KUBECONFIG aus .env.aks, wie haks): kein Certificate und
   # kein NodeHosts-Eintrag; Abbruch, wenn das Secret acr-pull im
   # Namespace fehlt (Hinweis auf den Helfer); nur bei secretName aus
   # P2 vorher das Secret sam-tls als Kopie des Default-Zertifikats
   # anlegen, dann:
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
   - Pull-Secret: `start.sh` legt das Secret auf `aks` nicht selbst an
     und ruft kein Skript aus sli auf; wie bei den Wrappern aus P1
     Schritt 6 koppelt nichts die Repos. Auf `aks` prüft es nach dem
     Anlegen des Namespace per `kaks -n sam-solace-lab get secret
     acr-pull -o name` und bricht vor `helm` mit dem Hinweis auf
     `sli/aks/acr-pull.sh sam-solace-lab` ab; so scheitert der
     Lauf mit einer eigenen Meldung statt in der Chart-Validierung.
     Weil `stop.sh` den Namespace löscht [Quelle: amd
     scripts/stop.sh:113-115], verschwindet das Secret mit ihm; jeder
     AKS-Zyklus (Abnahme unten, Neuaufbau in P7) ruft den Helfer vor
     `start.sh` erneut auf. Im Lab bleibt alles beim Alten (Kyverno
     synchronisiert `registry-pull-secret`).
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
     keiner Ausgabe. SAM erreicht LiteLLM über die von AKS verwaltete
     Outbound-IP in `gebit-showcase-nodes`. Ihre Adresse steht erst
     seit dem Create in P1 fest und ging direkt danach an den
     Betreiber (AKS-E11); arbeitet er mit einer Allowlist, muss seine
     Bestätigung für genau diese Adresse vorliegen. Vor `provision.sh`
     vergleicht Claude die aktuelle Adresse mit der gemeldeten
     (Abfrage wie in Schritt 6). Weicht sie ab (etwa nach einem
     Neuaufbau zwischen P1 und P5), geht die neue Adresse sofort an
     den Betreiber; bis zur Freischaltung scheitern Modell-Aufrufe
     aus dem Cluster, und P5 wartet um die Vorlaufzeit des Betreibers
     [A: Vorlaufzeit erfragen, AKS-E11].
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
   - Neu: Egress-Prüfung nach dem Start, nur lesend. Der Wrapper liest
     die AKS-verwaltete Outbound-IP und die Adresse von
     `pip-aks-ingress` und vergleicht beide mit dem lokalen Register
     aus P1 (`~/.config/eurocis-aks/`, chmod 600, nie im Repo):

     ```bash
     EGRESS_ID=$(az aks show -g gebit-showcase -n aks-eurocis --query \
       "networkProfile.loadBalancerProfile.effectiveOutboundIPs[].id" \
       -o tsv)                              # erwartet: genau eine Zeile
     az network public-ip show --ids "$EGRESS_ID" --query ipAddress -o tsv
     az network public-ip show -g gebit-showcase-nodes -n pip-aks-ingress \
       --query ipAddress -o tsv
     ```

     Weicht die Egress-IP ab, endet der Wrapper nach dem Start mit
     einem Exit-Code ungleich 0 und dem Hinweis auf die
     Betreiber-Meldung (AKS-E11); der Cluster bleibt gestartet, der
     Preflight ist rot. Fehlt `pip-aks-ingress` oder trägt sie eine
     andere Adresse, ist das ein Alarm: Ohne Lock kann jedes Mitglied
     der Contributor-Gruppe sie löschen, und mit ihr wird das Label
     `<p>` frei; dann sofort neu anlegen und das Label neu binden (P1,
     Ablauf wie beim Neuaufbau in P7). Ob beide Adressen `az aks stop`/`start`
     überstehen, sagt Learn nicht [A]: Die Outbound-IP verwaltet AKS
     selbst, `pip-aks-ingress` liegt als eigene statische Ressource in
     der Node-RG [Quelle: `learn.microsoft.com/azure/aks/start-stop-cluster`;
     `learn.microsoft.com/azure/aks/configure-load-balancer-standard`].
     P1 misst den ersten Zyklus, die Abnahme unten wiederholt die
     Messung.
   - Scheitert `az aks start` oder ein `aks-allow-me.sh`-Lauf mit
     `RequestDisallowedByPolicy` (die Tag-Pflicht der Subscription trifft
     einen Schreibzugriff auf `gebit-showcase-nodes`; einzelner
     Community-Report Azure/AKS #5856, von Microsoft unbestätigt [A]),
     wiederholt der Wrapper höchstens dreimal mit 60 s Pause. Bleibt
     es dabei, meldet er `az aks update -g gebit-showcase -n
     aks-eurocis` als Reconcile-Schritt an den Owner [Quelle:
     `github.com/Azure/AKS/issues/5856`; Learn-Troubleshooting-Seite
     `requestdisallowedbypolicy-error`]. Eine Policy-Ausnahme kann der
     Owner als Contributor nicht anlegen.
   - Dann auf den Node, Broker und gwe warten, awe einmal neu starten
     (gwe/awe-Race [Quelle: amd README.md:511-513]), dann Preflight.
     Die 30-min-Sperre aus P1 bleibt.
   - kubectl erreicht den API-Server über dessen FQDN; eine neue
     API-Server-IP nach dem Start braucht keinen eigenen Schritt.
   - Rechte: `az aks start`/`stop`, die Egress-Prüfung und
     `aks-allow-me.sh` laufen mit der Azure-Identität des Aufrufers
     (Contributor auf `azure-se`). Der Stellvertreter kann die Wrapper
     nur nutzen, wenn er über eine Gruppe ebenfalls Contributor hat
     (AKS-E20, offen); sonst bleiben Start und Stopp beim Owner.
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
     einem Debug-Pod im Cluster (kein Broker-LoadBalancer; Image aus
     ACR, Pull-Secret per `--overrides` wie beim Hairpin-Pod in der
     Abnahme). Der Lauf
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
(Logins, Devtools-Befund), die Freigabe in 7c und, falls nötig, die
Meldung einer geänderten Egress-IP an den LiteLLM-Betreiber
(Kontakte sind Owner-Sache); Stellvertreter sein Login.

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
  LiteLLM über die AKS-verwaltete Outbound-IP; bei einer Allowlist ist
  es die Adresse, die der Betreiber freigeschaltet hat, Vergleich aus
  Schritt 6); die Vision-Probe ist grün.
- Pull aus ACR per Token: `kaks -n sam-solace-lab get pods -o
  jsonpath='{..image}' | tr ' ' '\n' | sort -u | grep -v
  '^<acr>\.azurecr\.io/' | wc -l` ergibt 0; jedes Pod-Spec im
  Namespace nennt `acr-pull` unter `imagePullSecrets`, ebenso der
  `sam-doctor`-Hook (`haks get hooks agent-mesh -n sam-solace-lab`);
  kein Pod in `ImagePullBackOff`. Die Restlaufzeit des
  Token-Passworts (`az acr token show -r <acr> -n aks-pull --query
  "credentials.passwords[].expiry"`) reicht über den 20.02.2027.
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
  OIDC-Discovery. Der Debug-Pod bekommt das Pull-Secret explizit, weil
  `kaks run` den default-ServiceAccount nutzt und dieser in
  `sam-solace-lab` kein Pull-Secret trägt:

  ```bash
  kaks -n sam-solace-lab run hairpin --rm -i --restart=Never \
    --image=<acr>.azurecr.io/curl:8.23.0 \
    --overrides='{"apiVersion":"v1","spec":{"imagePullSecrets":[{"name":"acr-pull"}]}}' \
    -- curl -sS -o /dev/null -w '%{http_code}\n' https://<fqdn>/health
  ```

  `--overrides` verlangt ein `apiVersion` im JSON [Quelle: `kubectl
  run --help`, Client 1.36.3]; Rückfall: Pod-Manifest mit
  `imagePullSecrets` per `kaks apply -f -`.
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
- AKS-E19: Ein Testpod in `gpos-demo` (Namespace und `acr-pull` per
  Helfer, solange P6 sie noch nicht angelegt hat; Pull-Secret per
  `--overrides` wie beim Hairpin-Pod) bekommt auf 5432, 8333 und 9333
  nach `sam-solace-lab` einen Timeout; nach `kaks rollout restart` von
  gwe, awe und str laufen db-init und s3-init durch; ein Login als
  `postgres` mit "password" scheitert; PGPASSWORD im Secret
  `agent-mesh-postgresql` gleicht dem Key-Vault-Wert (Vergleich ohne
  Ausgabe).
- Devtools-Befund (Cookies, Web-Storage) aus Schritt 5 dokumentiert.
- Metadatenabfrage dokumentiert, Ausschlussliste für P7 fest.
- API-Server: `kaks get --raw /readyz` ok von einer freigegebenen IP.
  Ein Zyklus `aks-stop.sh`, mindestens 30 min Pause, `aks-start.sh`
  endet mit geladenen Agents. Die AKS-Outbound-IP und die Adresse von
  `pip-aks-ingress` sind vor und nach dem Zyklus gleich, `<fqdn>` löst
  weiter auf `pip-aks-ingress` auf; das Ergebnis steht im Protokoll
  (Messung zu [A] aus Schritt 6). Einmal vom Handy-Hotspot:
  `aks-start.sh` bricht mit dem Hinweis auf `aks-allow-me.sh` ab,
  nach dessen Lauf (bis 2 min) läuft er durch; die WebUI ist vom
  Hotspot auch ohne Freigabe erreichbar.
- Ein AKS-Zyklus `SAM_PROFILE=aks stop.sh`, dann ohne Helfer
  `start.sh` (bricht vor `helm` mit dem Hinweis auf
  `acr-pull.sh` ab, weil `stop.sh` den Namespace samt Secret
  gelöscht hat), dann Namespace und Helfer, `start.sh`,
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
17.11.; aus P1 der Hairpin-Test, `aks-allow-me.sh`, ACR im Modus
`rbac`, das ACR-Token (Passwort im Key Vault, Ablauf nach dem
20.02.2027), das Register mit Egress- und Ingress-IP und die
Meldung der Egress-IP an den LiteLLM-Betreiber samt Bestätigung,
falls er eine Allowlist führt (AKS-E11) sowie der Helfer
`sli/aks/acr-pull.sh` (P1 Schritt 8); aus P2 die IngressClass
`nginx`, das
Default-Zertifikat für `<fqdn>` und die TLS-Variante (mit oder ohne
`secretName`); in amd die `aks`-Prüfung auf `acr-pull` in `start.sh`
(5.2).

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

**Images ohne Kubelet-Rechte (Owner-Entscheidung 18.11.2026):** Der
Cluster hat kein AcrPull, weil `--attach-acr` eine Rollenzuweisung
braucht [Quelle:
`learn.microsoft.com/azure/aks/cluster-container-registry-integration`].
Jeder Pod, der aus ACR zieht, braucht deshalb das Pull-Secret
`acr-pull` (Typ `kubernetes.io/dockerconfigjson`, gebaut aus dem
Pull-Token `aks-pull` aus P1 Schritt 3, Passwort nur im Key Vault als
`acr-pull-token` und in `sli/aks/.env.aks`) in seinem Namespace und
einen Verweis in `imagePullSecrets` [Quelle:
`learn.microsoft.com/azure/container-registry/container-registry-auth-kubernetes`].
Für gpos heißt das: `acr-pull` in `gpos-data` und `gpos-demo`, beide
von `install.sh` angelegt (Schritte 6a und 8), und ein Verweis in
jedem Deployment und im StatefulSet. Ein Patch des default-SA reicht
nicht: Die Admission übernimmt die Pull-Secrets des SA nur, wenn der
Pod-Spec keine eigenen trägt, und die sechs gpos-Deployments tragen
`registry-pull-secret` [Quelle:
`kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin`;
gpd k8s/{pos,engine,wws,loyalty,gate,ui}.yaml:21-23].

**Schritte:**

1. Voraussetzung GEBIT (AKS-E16): Die schriftliche Freigabe liegt laut
   Owner seit 17.11.2026 vor; das Demo-Verzeichnis ist seit Commit
   7a860c5 im Repo. Dass sie auch das GEBIT-Descriptor-Set als
   K8s-Secret in Azure (Germany West Central), den Zugriff der
   Stellvertretung und die öffentliche Reflection abdeckt, ist die
   Planungsannahme [A]; der Status ist bewusst "offen", gehandelt wird
   erst nach schriftlicher Bestätigung (AKS-E16). Neu seit 18.11.:
   Technisch kommt nicht nur die Stellvertretung an das Secret,
   sondern jedes Mitglied der Contributor-Gruppe von `azure-se`
   (lokale Accounts einschalten, Admin-Credentials holen); sichtbar
   ist das nur im Activity Log [Quelle:
   `learn.microsoft.com/azure/aks/manage-local-accounts-managed-azure-ad`;
   `learn.microsoft.com/azure/role-based-access-control/built-in-roles/privileged`].
   Die Bestätigung muss diesen Kreis abdecken, oder der Owner klärt
   den Mitgliederkreis der Gruppe [A]. Fällig ist sie bis 27.11.,
   spätestens 09.12., weil schon `gebitsim` in P2 Schritt 7
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
   9, also weiter mit `registry-pull-secret`), `overlays/aks`, später
   `overlays/l3`, dazu die kustomize-Komponente
   `k8s/components/public-guard` (Schritt 3). Das Certificate
   `gpos-demo` (4 dnsNames, Lab-CA) gehört ins Lab-Overlay, nicht nach
   `base`. Das aks-Overlay:
   - setzt das Image `<acr>.azurecr.io/gpos-demo/gpos-demo`, ersetzt
     den Pull-Secret-Namen per JSON-Patch mit `target: {kind:
     Deployment}` und `op: replace`, `path:
     /spec/template/spec/imagePullSecrets/0/name`, `value: acr-pull`
     (alle sechs Deployments tragen genau einen Eintrag) und setzt
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
   ACR per Digest, `imagePullSecrets: [{name: acr-pull}]` direkt im
   Manifest, 8Gi `managed-csi`, `POSTGRES_PASSWORD` aus Secret
   `gpos-postgres-admin`, Mount auf `/var/lib/postgresql` mit dem
   Image-Default-PGDATA [A: damit `lost+found` der Azure-Disk initdb
   nicht stört]). So berühren `install.sh k8s`/`uninstall.sh` und das
   globale `namespace: gpos-demo` die Datenhaltung nicht. Die
   Namespace-Regel in `k8s_render.py`/`install.sh` wird ausdrücklich um
   `gpos-data` erweitert. `scripts/tests/test_k8s.py` prüft Basis, alle
   Overlays, `public-guard` und `postgres-aks` [Quelle: heute pinnt der
   Test Lab-Hosts, gpd scripts/tests/test_k8s.py:95-120]. Neu prüft er
   für das aks-Overlay und `postgres-aks`: Jedes Deployment und jedes
   StatefulSet verweist auf `acr-pull` und nirgends auf
   `registry-pull-secret`; im Lab-Overlay bleibt es umgekehrt. Dazu
   gegen eine ausdrückliche Liste (Routenliste aus `bff.py`) [A: Test
   neu]:
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
   az acr login -n <acr>
   docker buildx imagetools create \
     -t <acr>.azurecr.io/gpos-demo/gpos-demo:0.1.3 \
     registry.solace.lab/gpos-demo/gpos-demo:0.1.3
   ```

   Den Push darf der Owner als Contributor nur, weil die Registry im
   Modus `rbac` (API: `LegacyRegistryPermissions`) läuft (P1 Schritt
   3); im Modus `rbac-abac` hätte Contributor keine Daten-Ebene
   [Quelle:
   `learn.microsoft.com/azure/container-registry/container-registry-rbac-built-in-roles-directory-reference`].

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
     No-op): Namespace `gpos-data`, dann Secret `acr-pull` (vor dem
     StatefulSet, sonst bleibt `gpos-postgres-0` in ImagePullBackOff)
     und Secret `gpos-postgres-admin` vom Mac an den API-Server (Werte
     aus Key Vault, Muster `apply_secret`), `kaks apply -k
     k8s/postgres-aks`, `kaks -n gpos-data rollout status
     sts/gpos-postgres --timeout=300s`, dann `pg_isready`. Das
     Pull-Secret baut eine neue Funktion `apply_pull_secret` in
     `install.sh` nach demselben Verfahren wie `sli/aks/acr-pull.sh`
     (P1), aber in gpd selbst, weil Skripte nicht über Repo-Grenzen
     gesourct werden (P1 Schritt 6). Das Passwort läuft nur durch
     Pipes, nie durch argv, Ausgabe oder eine Datei:

     ```bash
     az keyvault secret show --vault-name <kv> -n acr-pull-token \
         --query value -o tsv |
       jq -Rc --arg u "$ACR_PULL_USER" --arg s "<acr>.azurecr.io" \
         '{auths: {($s): {username: $u, password: .,
           auth: (($u + ":" + .) | @base64)}}}' |
       apply_secret acr-pull --type=kubernetes.io/dockerconfigjson \
         --from-file=.dockerconfigjson=/dev/stdin
     ```

     `apply_secret` ruft `kubectl create secret generic` mit
     `--dry-run=client` und einem server-side apply auf [Quelle: gpd
     scripts/install.sh:92-97] [A: `--from-file` mit `/dev/stdin` auf
     macOS, Test in P1].
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
   - `ACR_PULL_USER=aks-pull` (Token-Name, kein Geheimnis); das
     Token-Passwort liest `install.sh` bei jedem Aufruf aus dem Key
     Vault (Schritt 6a), nie aus dieser Datei
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

   Kein LLM-Key, kein SEMP-Passwort und kein ACR-Token-Passwort in
   dieser Datei: `load_env` exportiert sie, und `sam config apply`
   expandiert `${VAR}` aus der Umgebung [Quelle: gpd scripts/lib.sh:4-6].
   Das SEMP-Passwort schreibt `scripts/broker.sh` bei `TARGET=aks` vor
   jedem `broker.py`-Aufruf neu: `umask 077`, `mkdir -p
   mesh/.rendered/aks`, eine Zeile `aks_admin_password = "<wert>"` aus
   `az keyvault secret show --vault-name <kv> -n solace-admin --query
   value -o tsv`, `chmod 600`, nie ausgegeben, nie unter `set -x`.
   Jeder Aufruf, damit auch ein alleinstehendes `reset.sh` oder
   `uninstall.sh` die Datei findet und ein rotiertes Secret ankommt;
   der hex-Wert enthält weder `"` noch einen Zeilenumbruch. Lesen
   darf der Owner den Key Vault über seine Access Policy (P1 Schritt
   3). Die Fail-closed-Prüfung aus P0 Schritt 11 läuft vor jedem
   Skript.
8. `TARGET=aks scripts/install.sh k8s`: Secrets `acr-pull` (wie 6a,
   jetzt in `gpos-demo`), `gpos-broker` und `gpos-db` direkt vom Mac
   an den API-Server, `gpos-gebit-descriptors` nur mit der
   schriftlichen Bestätigung aus Schritt 1. Statt auf den
   Kyverno-Klon von `registry-pull-secret` zu warten (install.sh:124-129)
   legt `install_k8s` auf `aks` das Secret `acr-pull` selbst an; weil
   `uninstall.sh` den Namespace `gpos-demo` löscht, entsteht es bei
   jedem Install neu. Die gRPC-Endpunkte sind öffentlich auf
   `<fqdn>:443`; das Overlay patcht die drei Lab-Ingresses (Namen
   bleiben) und legt für Reflection ein viertes an:
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

   `install.sh` überspringt auf `aks` den Lab-CA-Export (das Warten
   auf Kyverno ersetzt das eigene `acr-pull`, siehe oben).
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
      das Standpersonal tippt nichts. Kiosk und QR-Codes zeigen nur auf
      den Namen, nie auf eine IP: Ein Neuaufbau ändert die Ingress-IP
      (P7 Schritt 3).
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
- Pull-Secrets: `kaks -n gpos-demo get secret acr-pull` und
  `kaks -n gpos-data get secret acr-pull` zeigen Typ
  `kubernetes.io/dockerconfigjson`; alle gpos-Pods und
  `gpos-postgres-0` tragen `imagePullSecrets` = `acr-pull`
  (`kaks get pods -n gpos-demo -o
  jsonpath='{..imagePullSecrets[*].name}'`); kein Event mit
  ErrImagePull oder ImagePullBackOff in beiden Namespaces; kein
  `registry-pull-secret` im aks-Render.
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
- `uninstall.sh` ohne `--drop-db` lässt `gpos-postgres`, sein PVC und
  `gpos-data/acr-pull` stehen; `TARGET=aks scripts/install.sh all` aus
  leerem Namespace in höchstens 30 min inklusive voller
  Gate-Verifikation, Dauer protokolliert [Quelle: PLAN 6 AP12];
  `acr-pull` in `gpos-demo` entsteht dabei neu.
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
  und 0.1.4. Dazu: `grep -c` auf das Token-Passwort (aus dem Key
  Vault, nie ausgegeben) über `gpd/.env.aks` und den aks-Render ergibt
  0.
- xtrace: Die `set -x`-Logs von `install.sh` liegen nur unter
  `~/.config/eurocis-aks/xtrace/` (per `BASH_XTRACEFD`, 1.4). Das
  Laden von `.env.aks` (`set -a` mit `.`) und jedes `db_password`
  laufen ohne xtrace. Eine Zählabfrage ohne Ausgabe von Treffern über
  diese Logs ergibt 0: `grep -c -F -f <(...)` mit den Werten des
  Token-Passworts, aller Secrets aus `gpd/.env.aks` (darunter
  `BROKER_PASSWORD`) und der gpos-DB-Passwörter, per
  Prozess-Substitution wie in P7 Schritt 2, nie per argv.
- `TARGET=aks scripts/uninstall.sh` mit einer `.env.aks` ohne `SAM_URL`
  bricht vor dem ersten `api()`- oder kubectl-Aufruf ab (`set -x`-Log
  unter `~/.config/eurocis-aks/xtrace/`).
- In allen Namespaces kein Image mehr von Docker Hub (Prüfung wie P2
  mit `-A`).
- Lab danach: Overlay-Render identisch zur Baseline (bis auf den
  Tag-Commit 0.1.4), `make smoke` und S1 grün; das Lab-Overlay
  verweist weiter auf `registry-pull-secret`.

**Abhängigkeiten:** P5; P1 (ACR im Modus `rbac`, Pull-Token `aks-pull`
mit `acr-pull-token` im Key Vault, Access Policy des Owners); P2
(Traefik mit IngressClass `nginx`, `externalTrafficPolicy: Local`,
Default-Zertifikat, Access-Log); P3 (Keycloak unter `/auth`);
schriftliche Owner-Bestätigung zur Azure-Abdeckung der GEBIT-Freigabe
(AKS-E16, Status offen, inklusive Contributor-Kreis aus Schritt 1;
ohne sie läuft die Demo nur im Lab oder in L3); Owner-Antwort zu Frage
23 für `/freigabe`, `/foto`, `/op`, `/etikett`; Leih-Router (11.12.);
TR3-Stand im Lab.

### P7 Härtung und Betrieb (4,25 PT, KW3-KW7, Gates G3 und G4)

**Ziel:** Drills bestanden, Backups getestet, Runbook steht, Betreiber
und Stellvertreter einsatzbereit, Freeze ohne Überraschungen. Ein Node
ohne HA (Owner-Entscheidung 17.11.2026): Es gibt keinen N-1-Drill mehr;
jeder Node-Vorgang ist ein Ausfall von einigen Minuten, den
Wartungssperre, Refresh-Termin und L3 abfangen. Seit der
Owner-Entscheidung vom 18.11.2026 (nur Contributor, keine
Rollenzuweisungen, kein Lock) gilt zusätzlich: `pip-aks-ingress` und
die Egress-IP leben in der Node-RG `gebit-showcase-nodes` und
verschwinden mit dem Cluster [Quelle:
`learn.microsoft.com/azure/aks/faq`]. Der Neuaufbau-Drill bindet
deshalb das Label `<p>` neu und meldet eine neue Egress-IP; der
Rückbau hat keinen Lock mehr zu entfernen.

**Schritte:**

1. Requests mit einer Woche AKS-Prometheus-Daten nachziehen; die Summe
   der Requests bleibt bei höchstens 92 % CPU und 75 % RAM des einen
   Nodes (Allocatable aus P1, Grenzen wie in 3.2). Frei bleiben muss
   zusätzlich der Run-Pod von `az aks command invoke` (Requests 200m
   CPU und 500Mi RAM, 60 s Scheduling-Timeout), sonst bleibt der
   Break-glass-Weg Pending [Quelle:
   `learn.microsoft.com/azure/aks/access-private-cluster`].
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
     (Frage 21); im Zweifel `--exclude-table-data=pos.receipt`.
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
   - Ad-hoc-Pods (Scratch-Pod, Lastgenerator in Schritt 3, Debug-Pods)
     ziehen ihr Image aus ACR. Sie laufen nur in einem Namespace mit
     `acr-pull` (`sli/aks/acr-pull.sh <ns>`, P1) und tragen
     `imagePullSecrets: [{name: acr-pull}]` im eigenen Pod-Spec; ein
     Patch des default-SA erreicht nur Pods, die danach entstehen
     [Quelle:
     `kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin`].
     Ein eigener Namespace (z. B. `restore-test`) wird nach dem Test
     samt Secret gelöscht.
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
     Schreiben darf der Owner über seine Access Policy im Key Vault
     (P1 Schritt 3); ein Stellvertreter mit `get list` kann das Backup
     lesen, aber nicht schreiben. Braucht ein Werkzeug doch eine
     Datei, dann nur mit `umask 077; f=$(mktemp); trap 'rm -f "$f"'
     EXIT`. Nicht `az keyvault certificate import`: Es verwirft die
     Annotationen, und cert-manager stellte dann wegen IncorrectIssuer
     neu aus [A]. Die EAB-Zugangsdaten des Rückfall-Issuers liegen nur
     in Key Vault und `.env.aks` (P2), nie in einem Dump.
   - Keine CSI-VolumeSnapshots: `pg_dump` mit Restore-Test ist der
     einzige Backup-Pfad; das SAM-Postgres-PVC würde den Key enthalten.
3. Drills vor G3 [Quelle: PLAN 0.3 G3; PLAN 8.6]:
   - Neuaufbau. Der Cluster nimmt beim Löschen die Node-RG
     `gebit-showcase-nodes` mit allen Ressourcen mit, auch die dort
     selbst angelegte `pip-aks-ingress` und die AKS-verwaltete
     Outbound-IP [Quelle: `learn.microsoft.com/azure/aks/faq`]. Damit
     ist das Label `<p>` von der Löschung bis zur Neuanlage frei, und
     beide Adressen sind danach neu [Quelle:
     `learn.microsoft.com/azure/virtual-network/ip-services/public-ip-addresses`,
     "IP address assignment" und "Domain Name Label Scope"]. Ablauf:
     - Vorher: TLS-Backup `tls-traefik-ingress-tls` im Key Vault mit
       `notAfter` des laufenden Zertifikats, Dumps aus Schritt 2,
       aktuelle Liste von `aks-allow-me.sh`, Drill-Termin dem
       LiteLLM-Betreiber angekündigt (falls Allowlist, AKS-E11).
     - Gelöscht wird nur über `sli/aks/aks-rebuild.sh delete` (5.1);
       ein nacktes `az aks delete` verbietet der Lint in `sli/aks/`.
       Das Skript verlangt den eingetippten Clusternamen, verweigert
       vom 27.01. bis 20.02.2027 ohne `--freeze-override` und prüft
       vorher, dass `tls-traefik-ingress-tls` im Key Vault dasselbe
       `notAfter` wie das laufende Zertifikat hat, dass Dumps vom
       selben Tag existieren (Schritt 2) und dass `foundation.sh post`
       bereitsteht.
     - Löschen und sofort neu anlegen, ohne Pause zwischen den
       Befehlen; der Create läuft wie in P1 Schritt 4 aus demselben
       Skript, mit `--node-resource-group gebit-showcase-nodes` und
       denselben vier Tags (`Owner` und `Created Date` mit den Werten
       von `gebit-showcase`, `purpose`, `deleteAfter`), denn ohne sie
       verweigert die Tag-Pflicht die Node-RG [Quelle:
       `learn.microsoft.com/azure/aks/use-tags`]:

       ```bash
       sli/aks/aks-rebuild.sh delete   # fragt den Namen ab, blockiert
       az group exists -n gebit-showcase-nodes   # false, sonst warten
       # Create wie P1 Schritt 4 (gleiches Skript, gleiche Tags)
       az network public-ip create -g gebit-showcase-nodes \
         -n pip-aks-ingress -l germanywestcentral --sku Standard \
         --allocation-method Static --version IPv4 --dns-name <p> \
         --tags purpose=eurocis2027 deleteAfter=2027-02-28 -o none
       az group show -n gebit-showcase-nodes --query "keys(tags)" -o tsv
       # 4 Schlüssel; Werte nur per stillem Vergleich (P1-Abnahme)
       ```

       Nie `az group delete -n gebit-showcase`: Die RG gehört dem Owner
       und hält ACR und Key Vault, die den Neuaufbau überleben. Die
       Node-RG darf beim Create nicht existieren [Quelle:
       `learn.microsoft.com/azure/aks/faq`]. `pip-aks-ingress` entsteht
       als erste Ressource nach dem Create, vor jedem Workload; die
       Cluster-Identität braucht dafür keine Rollenzuweisung [Quelle:
       `learn.microsoft.com/azure/aks/static-ip`]. Scheitert der Create
       mit RequestDisallowedByPolicy, fehlt ein Tag; eine
       Policy-Ausnahme kann nur ein Subscription-Owner anlegen.
     - Label belegt: Scheitert `public-ip create`, weil ein Fremder
       `<p>` in der Region übernommen hat [A: Fehlertext beim Drill
       notieren], ist `<fqdn>` verloren. Dann L3 und Owner-Entscheidung
       über ein neues Präfix; das heißt neues Zertifikat (geteilter
       LE-Topf, sonst EAB-Rückfall), `KC_HOSTNAME`, SAM `dnsName`,
       `redirectUris`, `E2E_BASE_URL`, Kiosk-URLs und QR-Codes neu
       [A: rund 0,5-1 PT]. Das TLS-Backup hilft dann nicht. Das
       Zeitfenster ist die Dauer von Delete und Create [A: rund
       20-30 min, im Drill messen]. Gegenmittel bleiben das neutrale
       Präfix und die sofortige Neuanlage. Optionen für den Owner
       (Frage 7): `--dns-name-scope SubscriptionReuse` (Preview
       ohne SLA, FQDN mit Hash-Anteil, gleiches FQDN bei jedem
       Neuaufbau in `azure-se`; muss schon beim ersten Anlegen in P1
       gesetzt sein, weil der Hash `<fqdn>` ändert) oder vor dem
       Delete die IP per `az resource move` nach `gebit-showcase` und
       nach dem Create zurück [A: ungeprüft, ob das Label den Move
       übersteht und ob ein Move in die AKS-Node-RG geht; vorher mit
       einer Wegwerf-IP und eigenem Test-Label belegen; Quelle:
       `learn.microsoft.com/azure/azure-resource-manager/management/move-limitations/networking-move-limitations`].
     - Bootstrap wie P1 Schritt 6 mit `bootstrap-rbac.sh`: Admin-kubeconfig nur
       im per `trap` gelöschten Temp-Verzeichnis (`set -euo pipefail`, `umask
       077`, nie nach `~/.kube`), ClusterRoleBinding des Owners (Username aus
       `kaks auth whoami`, bei Mitgliedern des Tenants der UPN), `kaks auth
       can-i '*' '*' -A` mit der Entra-kubeconfig, dann `aks_update
       --disable-local-accounts` mit demselben Nachweis wie in P1
       (`disableLocalAccounts` gleich `true`, danach scheitert `--admin` im
       Negativtest) [Quelle:
       `learn.microsoft.com/azure/aks/kubernetes-rbac-entra-id`]. Im selben Zug
       die Break-glass-Probe aus Schritt 7: einmal `--enable-local-accounts`,
       `get-credentials --admin` nach demselben Muster, Binding prüfen, wieder
       `--disable-local-accounts` mit Nachweis. Erst danach `az aks
       rotate-certs`, vor dem ersten Workload (bis 30 min, erneuert Nodes, VMSS
       und Disks), weil ausgegebene Admin-Zertifikate sonst gültig bleiben
       [Quelle:
       `learn.microsoft.com/azure/aks/manage-local-accounts-managed-azure-ad`;
       `learn.microsoft.com/azure/aks/rotate-certificates`] [A:
       Owner-Entscheidung; entfällt, wenn eine Entra-Gruppe per
       `--aad-admin-group-object-ids` den Bootstrap ohne Admin-Zertifikat
       erlaubt]. Dann Entra-kubeconfig neu (`az aks get-credentials --file
       ~/.kube/aks-eurocis.yaml --context aks-eurocis --overwrite-existing`,
       `kubelogin convert-kubeconfig -l azurecli --kubeconfig
       ~/.kube/aks-eurocis.yaml --context aks-eurocis`): Der neue Cluster hat
       einen neuen API-Server-FQDN. Jedes `az aks update` im Drill, das an
       RequestDisallowedByPolicy scheitert, wird begrenzt wiederholt; bei
       Failed-State `az aks update -g gebit-showcase -n aks-eurocis` zum
       Reconcile [Quelle: `github.com/Azure/AKS/issues/5856`;
       `learn.microsoft.com/troubleshoot/azure/azure-kubernetes/error-codes/requestdisallowedbypolicy-error`].
     - Danach alles aus Skripten: Wartungskonfigurationen mit beiden
       Sperrbereichen, API-Server-Allowlist aus der Liste von
       `aks-allow-me.sh` (P1), `acr-pull` in jedem Namespace vor dessen
       Installation (`traefik`, `monitoring`, `iam`, `solace`,
       `sam-solace-lab`; `gpos-data` und `gpos-demo` legt `install.sh`
       an), dann P2 bis P6. Keine Workload Identity, keine UAMI und
       keine Federated Credentials (AKS-E21); der OIDC-Issuer bleibt
       aus. ACR mit Images und Token, Key Vault mit allen Secrets
       und Access Policies, Budget-Filter (fester Name der Node-RG) und
       die Keycloak-, SAM- und gpos-Inhalte aus Skripten und Seed
       bleiben bzw. entstehen gleich. Die Activity-Log- und
       Resource-Health-Alarme zeigen auf dieselbe Ressourcen-ID [A:
       nach dem Drill je einmal auslösen bzw. prüfen].
     - Neu sind Ingress-IP, Egress-IP, API-Server-FQDN und
       Cluster-RBAC. Die Egress-IP liest das Skript aus
       `networkProfile.loadBalancerProfile.effectiveOutboundIPs[].id`
       und `az network public-ip show --ids <id> --query ipAddress -o
       tsv` [Quelle:
       `learn.microsoft.com/azure/aks/configure-load-balancer-standard`];
       sie geht nur in das lokale Register, nie in dieses Dokument. Gibt
       es eine LiteLLM-Allowlist, meldet der Owner die neue IP sofort
       und lässt die alte austragen (Azure vergibt eine freigegebene
       Adresse neu). Die Freischaltung muss in das 4-h-Fenster passen;
       die Vorlaufzeit des Betreibers steht im Rebuild-Runbook. Das
       Binding des Stellvertreters entsteht neu (Schritt 7), seine
       Key-Vault-Policy bleibt; Owner und Stellvertreter holen ihre
       kubeconfig neu.
     - `<fqdn>`, Kiosk-URLs und QR-Codes bleiben gleich, solange das
       Label neu gebunden ist; `nslookup <fqdn>` liefert die neue
       Ingress-IP. Der Traefik-Service bindet sie per `azure-pip-name`
       ohne RG-Annotation (P2 Schritt 5), nie per
       `azure-dns-label-name`.
     - TLS: das Secret direkt nach dem Anlegen des Namespace `traefik`
       einspielen, vor dem Certificate-Objekt, vor Traefik mit
       Default-TLSStore und vor dem SAM-Install; sonst den Drill nur
       gegen den LE-Staging-Issuer. Jeder Drill ohne wirksames Backup
       verbraucht eine von 5 Ausstellungen für das Namensset `<fqdn>`
       in 7 Tagen (aufgefüllt um eine je 34 h). Als Erneuerung
       desselben Sets zählt sie nicht gegen das Limit von 50 je Woche,
       das sich alle Azure-Kunden für `azure.com` teilen
       (`cloudapp.azure.com` fehlt auf der Public Suffix List) [Quelle:
       `letsencrypt.org/docs/rate-limits`;
       `publicsuffix.org/list/public_suffix_list.dat`, 17.11.].
       Scheitert LE trotzdem, stellt der vorbereitete Rückfall-Issuer
       mit EAB aus (P2). `export-le-certs.sh` stellt nichts aus.
   - 24-h-Lauf mit 450 Läufen/h von Mo 18.01. 12:00 bis Di 19.01.
     12:00, also nicht über das Mittwochsfenster (der 20.01. ist
     zusätzlich gesperrt); danach Neustart von awe allein, der Lauf geht
     weiter [Quelle: PLAN 8.6]. Der Lastgenerator läuft clusterintern
     (mit `acr-pull`, Schritt 2) oder über den Port-Forward auf
     gpos-ui, damit `public-guard` ihn nicht drosselt [A]. 3
     Stop/Start-Zyklen mit je mindestens 30 min Pause (zusammen rund
     2,5-3 h [A]); vor und nach jedem Zyklus Egress-IP und
     `pip-aks-ingress` protokollieren, weil Learn zum Verhalten der
     IPs in der Node-RG bei Stop und Start nichts sagt [A: Erwartung
     unverändert; Quelle: `learn.microsoft.com/azure/aks/start-stop-cluster`].
     Kein N-1-Drain (ein Node).
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
     `learn.microsoft.com/azure/aks/access-private-cluster`]. `command
     invoke` läuft über ARM, aber mit dem Entra-Token des Aufrufers und
     damit unter Kubernetes-RBAC: Es hilft gegen die IP-Sperre, nicht
     gegen ein fehlendes Binding [Quelle: azure-cli acs/custom.py,
     Kommentar "current user identity", 2.93.0 Z. 3284-3286]. Scheitert
     `aks-allow-me.sh` an RequestDisallowedByPolicy (Azure/AKS #5856),
     begrenzt wiederholen und bis dahin `command invoke` nutzen. Die
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
   Node-Image. Neu seit 18.11. (alles read-only):
   - `pip-aks-ingress` existiert in `gebit-showcase-nodes`,
     `nslookup <fqdn>` liefert ihre Adresse;
   - die Egress-IP aus `effectiveOutboundIPs` ist die beim
     LiteLLM-Betreiber gemeldete (nur bei Allowlist; Vergleich gegen
     das lokale Register);
   - `acr-pull` existiert in jedem Namespace, der aus ACR zieht, und
     das Passwort von `aks-pull` läuft nach dem 20.02.2027 ab (`az acr
     token show -r <acr> -n aks-pull --query
     "credentials.passwords[].expiry"`); ein abgelaufenes Passwort fällt
     erst beim nächsten Pull auf, etwa auf dem Surge-Node am 26.01.;
   - `disableLocalAccounts` ist `true`, und das Activity Log der
     letzten 24 h zeigt keine `listClusterAdminCredential`-Aktion,
     kein `vaults/accessPolicies/write` und kein
     `registries/tokens/write` außer dokumentierten eigenen (die
     Alarme aus P1 melden sie zusätzlich).

   Erster Schritt für jeden Betreiber morgens: eigene IP mit
   `aks-allow-me.sh` in die Allowlist (ohne eigenes Azure-Recht trägt
   der Owner sie ein, Schritt 7), dann ein nicht-interaktiver
   Aufruf über kubelogin: `kaks auth can-i get pods -n gpos-demo`;
   scheitert er, meldet sich die Person selbst mit `az login` an, vor
   Standöffnung; ohne Subscription-Zugriff mit `az login --tenant
   <tenant> --allow-no-subscriptions` (sonst "No subscriptions found",
   Schritt 7). Runbook-Regeln: Start frühestens 30 min nach Stop;
   Umfang des Stellvertreters (Schritt 7); bei Missbrauch die
   betroffene Route sperren (Limit senken oder Pfad-Ingress löschen,
   Freeze-Ausnahme), bei 429 vom Messe-Key L1 [Quelle: PLAN 9 R24];
   nie `az group delete -n gebit-showcase`, den Cluster nur per
   `sli/aks/aks-rebuild.sh` und nur mit Owner-Go; meldet der Alarm ein
   Löschen des Key Vault, stellt `az keyvault recover -n <kv>` ihn
   binnen 7 Tagen wieder her (Soft-Delete ohne Purge-Schutz, AKS-E17);
   nach einem Purge ist diese Kopie endgültig weg, dann entscheidet
   sofort der Owner; `az aks update --tags` nur mit allen
   vier Tags, weil der Aufruf das ganze Tag-Set ersetzt [Quelle:
   `learn.microsoft.com/azure/aks/use-tags`]; scheitert ein `az aks
   update` an RequestDisallowedByPolicy, begrenzt wiederholen, dann
   Reconcile (Schritt 3). Keycloak-Admin ist seit P3 nicht über den
   Ingress erreichbar; P7 prüft das nur noch.
5. Di 26.01., nach Ende eines eventuell laufenden Auto-Vorgangs:
   `az aks nodepool upgrade -g gebit-showcase --cluster-name aks-eurocis
   -n main --node-image-only` als letztes Node-Image vor der Sperre (ab
   27.01.). Mit einem Node ersetzt AKS ihn per Surge und zieht alle Pods
   samt Disks um: einige Minuten Ausfall [A: Dauer messen, ins
   Runbook]; deshalb an keinem Probetag und während keines Laufs. Die
   Quota für den Surge-Node war am 18.11. vorhanden (Total Regional 150
   von 350 frei); weil die Subscription geteilt ist, am Vortag `az vm
   list-usage -l germanywestcentral` erneut prüfen (3.5). Vorher den
   Preflight laufen lassen: Der Surge-Node hat einen leeren
   Image-Cache und zieht jedes Image neu, also müssen `acr-pull` in
   allen Namespaces und ein gültiges Token-Passwort da sein. Egress-IP
   und `pip-aks-ingress` vorher und nachher protokollieren [A:
   unverändert erwartet]. Scheitert der Vorgang an
   RequestDisallowedByPolicy, Reconcile wie in Schritt 3, noch am
   26.01. Danach `az aks nodepool show --query nodeImageVersion` und
   Name, Label `kubernetes.azure.com/node-image-version` und `bootID`
   notieren:

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
   Owner-Bestätigung offen). Rollenzuweisungen gibt es nicht
   (Owner-Entscheidung 18.11.2026), also auch keine eigene
   Stellvertreter-Rolle und kein "AKS RBAC Cluster Admin". Der Zugang
   hat zwei Teile; was hier für den Stellvertreter steht, gilt ebenso
   für einen Betreiber, der nicht der Owner ist:
   - Kubernetes (ohne Azure-Recht): Der Stellvertreter braucht ein
     Konto im Tenant von `azure-se` und meldet sich selbst an. Ohne
     Subscription-Zugriff scheitert ein einfaches `az login` mit "No
     subscriptions found" [Quelle: azure-cli 2.85.0
     core/_profile.py:206-207]; er nimmt deshalb `az login --tenant
     <tenant> --allow-no-subscriptions` (bei einem Gast liefert erst
     `--tenant` ein Token des richtigen Tenants) [Quelle: `az login
     --help`, 2.85.0], danach `kaks auth whoami` und `az ad
     signed-in-user show --query id -o tsv`. Ohne Azure CLI konvertiert
     er die weitergegebene kubeconfig mit `kubelogin convert-kubeconfig
     -l interactive` (oder `-l devicecode`) `--kubeconfig
     ~/.kube/aks-eurocis.yaml --context aks-eurocis` statt `-l
     azurecli`. `kaks auth whoami` mit seiner Entra-kubeconfig zeigt
     seinen Username (bei Mitgliedern des Tenants der UPN, bei Konten
     aus einem anderen Tenant laut Learn die objectId) [Quelle:
     `learn.microsoft.com/azure/aks/kubernetes-rbac-entra-id`;
     `learn.microsoft.com/azure/aks/control-kubeconfig-access`]; der
     Wert steht nur im lokalen Register
     `~/.config/eurocis-aks/subjects` (chmod 600), nie im Repo. Der
     Owner legt mit seiner eigenen Entra-Identität das Binding an,
     ohne Admin-Zertifikat:

     ```bash
     DEPUTY_USER=$(sed -n 's/^deputy=//p' ~/.config/eurocis-aks/subjects)
     kaks create clusterrolebinding eurocis-deputy \
       --clusterrole=cluster-admin --user="$DEPUTY_USER" \
       --dry-run=client -o yaml | kaks apply -f -
     kaks auth can-i get pods -n gpos-demo --as="$DEPUTY_USER"  # yes
     ```

     Die kubeconfig bekommt er vom Owner als Datei
     `~/.kube/aks-eurocis.yaml` oder, mit eigenem Azure-Recht, per `az
     aks get-credentials -g gebit-showcase -n aks-eurocis --file
     ~/.kube/aks-eurocis.yaml --context aks-eurocis`; ohne `--file`
     mergte `az` in seine `~/.kube/config` und stellte seinen aktuellen
     Kontext auf AKS um (P1 Schritt 6). Auf seinem Mac gelten dieselben
     Wrapper `kaks`/`haks` wie in P1 Schritt 6. Die
     Entra-User-kubeconfig enthält kein Geheimnis [Quelle:
     `learn.microsoft.com/azure/aks/control-kubeconfig-access`] [A:
     Test unten, vor G3]. Dazu ein eigener Allowlist-Eintrag, eigener
     Keycloak-User und eigenes `SAM_HOME` (P5). Er meldet sich selbst
     an; Owner und Claude geben nie seine Passwörter ein.
   - Azure (für `aks-allow-me.sh` = `managedClusters/write`,
     `aks-start.sh` und `aks-stop.sh`, `az aks command invoke` =
     `runCommand/action` und `commandResults/read`, `get-credentials`
     = `listClusterUserCredential/action`): Ohne Rollenzuweisung geht
     das nur, wenn der Stellvertreter schon über eine Gruppe
     Contributor (oder eine Rolle mit diesen Aktionen) auf `azure-se`
     hat [Quelle:
     `learn.microsoft.com/azure/role-based-access-control/built-in-roles/privileged`].
     Ob er das hat, ist offen (AKS-E20, Owner bis 27.11.). Fehlt es,
     bleiben diese Schritte beim Owner: Er trägt die IP des
     Stellvertreters mit `aks-allow-me.sh --add <ip>` ein [A: neue
     Option des Helfers, P1 Schritt 7], startet und stoppt den Cluster
     selbst, und Break-glass ohne Allowlist gibt es dann nur über ihn.
     Mit Contributor hat der Stellvertreter auch `stop` und `delete`;
     die Grenze zieht das Runbook, nicht das Recht.
   - Key Vault (Access-Policy-Modus, P1 Schritt 3): `az keyvault
     set-policy -n <kv> -g gebit-showcase --object-id <deputy-objectId>
     --secret-permissions get list -o none`; die objectId nennt der
     Stellvertreter selbst (`az ad signed-in-user show --query id -o
     tsv`), sie steht nur im lokalen Register [Quelle:
     `learn.microsoft.com/azure/key-vault/general/assign-access-policy`].
     Contributor reicht dafür, eine Rollenzuweisung nicht.
   - Direkt nach dem Einrichten, vor G3: Der Stellvertreter ruft mit
     seinem eigenen Konto `kaks auth whoami`, `kaks auth can-i '*' '*'
     -A` und, falls er Contributor hat, `aks-allow-me.sh` auf. Hat er
     kein Azure-Recht, läuft der Test ausdrücklich mit einem Konto ohne
     Subscription-Zugriff, über `az login --tenant <tenant>
     --allow-no-subscriptions` bzw. `-l interactive`. Auf seinem Mac
     ist `kubectl config current-context` danach unverändert, und
     `~/.kube/config` enthält kein `aks-eurocis`. Das
     frühere Risiko `LinkedAuthorizationFailed` entfällt: Der Cluster
     verweist auf keine BYO-Identität, kein BYO-Subnetz und keine
     BYO-IP mehr. Der Lauf an Probetag 1 ist nur noch Wiederholung.
   - GEBIT: Mit Kubernetes-RBAC lässt sich der Stellvertreter enger
     binden als mit "AKS RBAC Cluster Admin". Deckt die GEBIT-Freigabe
     ihn nicht ab [A, P6 Schritt 1], bekommt er statt `cluster-admin`
     je Namespace die ClusterRole `admin` per RoleBinding, nur in
     `gpos-demo` eine Role ohne `secrets` und ohne `pods/exec` (Pods,
     Logs, Events lesen; `rollout restart` per `patch` auf
     Deployments), dazu Lesen von `nodes` für den Preflight; ein
     Fehler, der das Descriptor-Secret braucht, heißt dann L3, und nur
     der Owner stellt es wieder her. Technisch bleibt
     die Grenze organisatorisch: Wer Contributor auf `azure-se` hat,
     kann lokale Accounts einschalten, Admin-Credentials holen oder
     sich eine Key-Vault-Policy setzen [Quelle:
     `learn.microsoft.com/azure/aks/manage-local-accounts-managed-azure-ad`;
     `learn.microsoft.com/azure/key-vault/general/assign-access-policy`];
     die Activity-Log-Alarme aus P1 und der Preflight (Schritt 4)
     zeigen das, verhindern es aber nicht.
   - Break-glass bei RBAC-Lockout (nur Owner oder ein Contributor):
     `aks_update --enable-local-accounts`, `az aks get-credentials
     --admin --file <tmp>` nur nach dem Muster aus P1 Schritt 6 (`set
     -euo pipefail`, `umask 077`, `mktemp -d` mit `trap`), Binding
     reparieren, wieder `--disable-local-accounts` mit Nachweis
     (`disableLocalAccounts` gleich `true`, Negativtest), danach `az aks
     rotate-certs` (bis 30 min Ausfall) [Quelle:
     `learn.microsoft.com/azure/aks/manage-local-accounts-managed-azure-ad`;
     `learn.microsoft.com/azure/aks/rotate-certificates`]. Im Freeze
     verschiebt das Runbook die Rotation auf nach Standschluss [A:
     Owner-Entscheidung]. `az aks command invoke` ist kein Weg am
     RBAC vorbei (Schritt 3).
   - Umfang des Stellvertreters: Preflight, Pod- und awe-Neustarts,
     Backups, Umschaltung auf L3 oder L4; `aks-allow-me.sh`,
     `aks-start.sh` und Break-glass nur mit eigenem Azure-Recht (siehe
     oben). Kein Neuaufbau, kein `aks-rebuild.sh` bzw. `az aks
     delete` und kein SAM-Helm-Upgrade (Descriptor-Secret nur vom
     Owner-Mac, LiteLLM-Key nur in dessen `amd/.env.aks`).
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
     Owner-Freigabe (nie unter v3.7.18) [A]. Ein Neuaufbau im Freeze
     ist kein Routinefall: Er ändert Ingress- und Egress-IP und
     riskiert das Label (Schritt 3); zuerst L3, dann Owner-Go. Am
     Morgen des 14.02. melden sich Owner und Stellvertreter frisch an
     (bei kurzer Conditional-Access-Frequenz täglich) und tragen die IP
     des Stand-Uplinks ein.
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
   - (3) `az aks stop -g gebit-showcase -n aks-eurocis`; Disks, PVCs
     und beide IPs bleiben (der Cluster existiert weiter).
   - (4) `gpos-data` nur mit der Rückbau-Entscheidung oder der
     GEBIT-Übergabe löschen.
   - (5) Owner entscheidet Rückbau oder GEBIT-Übergabe. Bei der
     Übergabe bleiben alle Ressourcen; ein Wechsel des Token-Passworts
     geht ohne Ausfall über `password2`, und `az aks update --tags`
     nur mit allen vier Tags. Rückbau mit Azure CLI 2.93 oder neuer
     (die Key-Vault-API von 2.85 endet am 27.02.2027 [Quelle:
     `learn.microsoft.com/azure/key-vault/general/access-control-default`]),
     in dieser Reihenfolge:
     - Zuerst das Zertifikat für `<fqdn>` per ACME widerrufen (etwa
       `certbot revoke --cert-path <crt> --key-path <key> --server
       <directory>` mit einer Temp-Datei nach dem Muster aus Schritt
       2; cert-manager widerruft nicht selbst [A: Werkzeug]). Grund:
       `az aks delete` löscht mit der Node-RG auch `pip-aks-ingress`,
       danach ist das Label für jeden frei, das Zertifikat aber bis
       rund Mitte April gültig (Schritt 6).
     - `sli/aks/aks-rebuild.sh teardown` (eingetippter Clustername,
       erst ab 19.02. und erst nach (1) bis (3) und dem Widerruf; ruft
       intern `az aks delete -g gebit-showcase -n aks-eurocis --yes`):
       Es nimmt `gebit-showcase-nodes` mit VM, Disks samt allen PVCs,
       LB, AKS-VNet, `pip-aks-ingress` und Outbound-IP mit [Quelle:
       `learn.microsoft.com/azure/aks/faq`]. Einen Lock gibt es nicht,
       also auch nichts zu entfernen. Danach ist `az group exists -n
       gebit-showcase-nodes` gleich `false`.
     - Der LiteLLM-Betreiber trägt die Egress-IP aus seiner Allowlist
       aus (falls es eine gibt; Azure vergibt die Adresse neu) und
       deaktiviert den Messe-Key (O5); beides bestätigt er schriftlich.
     - `az acr delete -n <acr> --yes` (nimmt Images, Scope-Map und
       Token `aks-pull` mit).
     - `az keyvault delete -n <kv>` (die Access Policies gehen mit dem
       Vault), dann `az keyvault list-deleted --query
       "[?name=='<kv>']" -o table` und `az keyvault purge -n <kv> -l
       germanywestcentral` (eigene Freigabe des Owners, nicht
       umkehrbar; gibt den global reservierten Namen frei; Contributor
       enthält die Purge-Aktion [Quelle:
       `learn.microsoft.com/azure/role-based-access-control/built-in-roles/privileged`]).
     - Budget per `az rest --method delete` auf denselben Pfad wie in
       P1 (Contributor darf eigene Budgets löschen [Quelle:
       `learn.microsoft.com/azure/cost-management-billing/costs/tutorial-acm-create-budgets`]),
       dazu Activity-Log-Alarme, Resource-Health-Alarm und ihre Action
       Group.
     - `gebit-showcase` selbst löscht nur der Owner, der sie angelegt
       hat, und nur, wenn sie danach leer ist; nie `az group delete
       -n gebit-showcase`, solange etwas anderes darin liegt.
     - Den EAB-Zugang beim Rückfall-Anbieter schließt der Owner. Alle
       Dumps, Scratch-DBs und die L3- und Backup-Kopien des
       Zertifikats löschen; dazu die lokalen Dateien mit Secrets:
       `amd/.env.aks` (LiteLLM-Key, OIDC-Client-Secret, PG- und
       Broker-Passwörter), `gpd/.env.aks`, `sli/aks/.env.aks` (EAB,
       Kopie des ACR-Token-Passworts),
       `gpd/mesh/.rendered/aks/semp.tfvars`, `gpd/.rendered-aks/`, den
       State unter `emd/terraform-aks/` (Client-Passwörter im
       Klartext), `~/.kube/aks-eurocis.yaml`, das AKS-`SAM_HOME` mit
       Token-Cache und die Register unter `~/.config/eurocis-aks/`
       (IPs, Subjekte) samt `~/.config/eurocis-aks/xtrace/`
       (Mitschnitte). Der Stellvertreter löscht seine kubeconfig und
       sein `SAM_HOME` selbst. Widerruf, Löschungen und
       Key-Deaktivierung protokollieren; Abend-Check entfernen.
9. Doku: AKS-Abschnitte in README und RUNBOOK, Drift korrigieren (siehe
   Abschnitt 8), markdownlint.

**Wer:** Claude 1-6, 9; Betreiber und Stellvertreter (AKS-E20) 7 und
die Probetage; Owner Freigaben, Bestätigung der Key-Limits beim
LiteLLM-Betreiber, Drill-Teilnahme mit dem Bootstrap im Neuaufbau
(Admin-Zugang, Bindings, `rotate-certs`) und der Meldung der neuen
Egress-IP, Bindings und Key-Vault-Policy des Stellvertreters (7),
Rückbau (8).

**Abnahme:**

- G3: Neuaufbau bis Preflight READY in höchstens 4 h [Quelle: PLAN 6
  AP13], inklusive Bootstrap mit `rotate-certs` und, falls es eine
  Allowlist gibt, Freischaltung der neuen Egress-IP; Dauer je
  Abschnitt protokolliert. Danach: `<fqdn>` unverändert (Label `<p>`
  neu gebunden, `az network public-ip show -g gebit-showcase-nodes -n
  pip-aks-ingress --query dnsSettings.fqdn` gleich `<fqdn>`), Kiosk-URLs
  und QR-Codes ohne Änderung; Ingress- und Egress-IP neu und nur im
  lokalen Register notiert, die alte Egress-IP beim Betreiber
  ausgetragen; `gebit-showcase-nodes` trägt die vier Tags;
  `disableLocalAccounts true`, `aadProfile.enableAzureRbac false`,
  `get-credentials --admin` scheitert mit "Getting static credential
  isn't allowed"; Bindings von Owner und Stellvertreter wirken
  (`kaks auth can-i`), die Break-glass-Probe ist protokolliert; kein
  Event mit ErrImagePull oder ImagePullBackOff, `acr-pull` in allen
  Namespaces, die aus ACR ziehen. Nach dem TLS-Restore zeigt `kaks get
  certificaterequest -A` keine neuen Requests, das Certificate ist
  Ready, `notAfter` gleich dem Backup (`openssl x509 -noout
  -enddate`). Das Kriterium "Ingress-IP unverändert" (P7-Abnahme der
  Fassung vom 17.11., sda-Commit 9f66efd) gilt ohne Move-Variante
  nicht mehr; Vorschlag: "`<fqdn>` unverändert" (Owner-Bestätigung
  offen, Frage 31). 24-h-Lauf ohne
  OOMKilled und ohne NotReady; Egress-IP und `pip-aks-ingress` über
  alle 3 Stop/Start-Zyklen gleich, sonst prüft der Wrapper
  `aks-start.sh` künftig die Egress-IP und das Runbook meldet sie dem
  Betreiber [A]; 10-h-Kiosklauf über den öffentlichen Ingress mit 0
  manuellen Reloads, Browser-Speicher stabil (±20 %), Attract-Loop
  läuft; aus gestopptem Cluster bis READY in höchstens 30 min, gemessen
  ab `az aks start` [A: Zielwert]; L3-Drill höchstens 3 min [Quelle:
  PLAN 6 AP14b]; Restore-Test aller Dumps grün, Zählprüfungen 0;
  Missbrauchs- und Kostentest grün (429 auf allen geschützten HTTP-
  und gRPC-Routen, Kiosk unbeeinflusst, Key-Limits bestätigt,
  L1-Rückfall gesehen); Binding, Key-Vault-Policy, Allowlist-Eintrag
  und Keycloak-User des Stellvertreters bereit, `kaks auth whoami` und
  `kaks auth can-i` mit seinem Konto grün (ohne Azure-Recht mit einem
  Konto ohne Subscription-Zugriff, Schritt 7); auf seinem Mac ist
  `kubectl config current-context` unverändert, und `~/.kube/config`
  enthält kein `aks-eurocis`; mit eigenem Azure-Recht
  zusätzlich `aks-allow-me.sh` mit seinem Konto einmal grün, sonst
  ist dokumentiert, dass der Owner diese Schritte übernimmt. Fehlt TR3
  aus P6, folgt es hier.
- Probetag 1 (28.01.): Runbook-Durchlauf des Stellvertreters mit
  eigenem Konto, inklusive `aks-allow-me.sh` aus seinem Netz
  (Wiederholung; ohne Azure-Recht durch den Owner mit `--add`); vor
  G4 (z. B. 03.02.) einmal `az aks command invoke` mit eigenem Konto,
  falls er das Azure-Recht hat, sonst durch den Owner.
- G4: 100 Läufe mindestens 98 % ohne Rückfall [Quelle: PLAN 0.3 G4];
  das Certificate hat `notAfter` nach dem 10.04.2027 und
  `status.renewalTime` nach dem 20.02.2027; das Passwort von
  `aks-pull` läuft nach dem 20.02.2027 ab; `az aks
  maintenanceconfiguration show` zeigt beide Sperrbereiche auf allen
  drei Konfigurationen; Node-Image (`nodeImageVersion` und Label
  `kubernetes.azure.com/node-image-version`) am 28.01., 03.02. und
  05.02. gleich dem Stand nach dem Refresh am 26.01.; `bootID` nur
  innerhalb eines Laufs ohne Stopp vergleichen, weil jeder
  Nachtstopp die Node-VM neu bootet (ab 05.02., 24/7: 05.02. gegen
  16.02.); das Activity Log (`az monitor activity-log list` auf die
  Cluster-Ressource) zeigt zwischen 27.01. und 05.02. keinen
  automatischen Node-OS- oder Upgrade-Vorgang und seit dem
  Neuaufbau-Drill keine `listClusterAdminCredential`-Aktion außer
  dokumentiertem Break-glass; `disableLocalAccounts true`; nach dem
  letzten Start vor dem 05.02. funktioniert kubectl vom 5G-Netz nach
  `aks-allow-me.sh`; Preflight READY in unter 15 min aus kalt [Quelle:
  PLAN 6 AP14].
- Messe: Node-Image-Vergleich am 16.02. wie bei G4, dazu `bootID`
  gleich dem Wert vom 05.02. (seitdem kein Stopp); die Allowlist
  enthält nur aktuelle Einträge; die Egress-IP ist die beim Betreiber
  gemeldete (falls Allowlist).
- Löschung des Descriptor-Secrets bis 20.02.2027 protokolliert; Dumps,
  Zertifikatskopien und lokale Secret-Dateien nach der Messe gelöscht,
  das Zertifikat vor `az aks delete` widerrufen, der Messe-Key
  deaktiviert; beim Rückbau außerdem `gebit-showcase-nodes`, ACR und
  Key Vault (purged) weg, Budget und Alarme gelöscht, Egress-IP beim
  Betreiber ausgetragen; alles protokolliert.

**Abhängigkeiten:** P6; Netzparameter des Stands (Uplink mit
ausgehendem HTTPS, 5G-Option, fällig 18.12. [Quelle: PLAN 6.5]);
Kiosk-Hardware und `/monitor` live (G2b); aus P1 `aks-allow-me.sh`
(mit `--add`), das Bootstrap-Verfahren, `acr-pull.sh`, die
Activity-Log-Alarme und das IP-Register; Bestätigung der Key-Limits
und der Vorlaufzeit für Allowlist-Änderungen durch den
LiteLLM-Betreiber; AKS-E20 (Owner-Bestätigung offen, inklusive der
Frage, ob Betreiber und Stellvertreter über eine Gruppe Contributor
auf `azure-se` haben); Owner-Entscheidungen zu `rotate-certs` bzw.
Admin-Gruppe, zu `--dns-name-scope` oder Move-Variante und zum neuen
G3-Kriterium "`<fqdn>` unverändert".

## 5. Notwendige Änderungen je Repo

Grundsatz: AKS kommt als additives Profil dazu. Lab-Pfade und
Lab-Defaults bleiben unverändert, belegt durch Call-Log- und
Render-Diff (P0 Schritt 13). Die Freigaben AKS-E15 (a) bis (e) hat der
Owner am 17.11.2026 erteilt; (a) ist mit Commit `cd08a17` erledigt.
Einzige gewollte Lab-Änderung ist das Broker-Upgrade in 5.3 (P4 Teil
A, 1,0 PT); es braucht ein eigenes Go des Owners und ein
Wartungsfenster. `<fqdn>` steht in diesem Plan für
`<p>.germanywestcentral.cloudapp.azure.com`.

Seit der Owner-Entscheidung vom 18.11.2026 kommt jedes AKS-Skript mit
der Rolle Contributor aus. Kein Skript ruft `az role assignment
create` oder `az lock create` auf oder braucht eine Policy-Ausnahme,
und keines nutzt einen Schalter, der eine Rollenzuweisung auslöst
(`--attach-acr`, `--enable-azure-rbac`, `--vnet-subnet-id`,
`--assign-identity`) [Quelle: azure-cli dev
acs/managed_cluster_decorator.py und acs/_roleassignments.py, 18.11.].
Cluster, ACR und Key Vault liegen in `gebit-showcase` (vom Owner
angelegt, Metadaten in westeurope) und tragen `-l
germanywestcentral`; die Node-RG `gebit-showcase-nodes` legt AKS beim
Create an (8.6).

### 5.1 solace-lab-infrastructure (geteilt, Freigabe AKS-E15 (c))

- Neuer Ordner `aks/`, nur neue Dateien:
  - `versions.env` (Traefik-Chart 42.4.1, Image `traefik:v3.7.19` per
    Digest und nie unter v3.7.18, cert-manager v1.21.3, Monitoring in
    den Lab-Versionen), `lib.sh` (`kaks`/`haks`,
    `require_kube_context` mit Prüfung der Server-URL). Neu in
    `lib.sh` seit dem 18.11.:
    - Namen an einer Stelle: `gebit-showcase`, `gebit-showcase-nodes`,
      `aks-eurocis`, `germanywestcentral`. `az aks create`, `az acr
      create`, `az keyvault create` und `az network public-ip create`
      tragen `-l germanywestcentral`, weil die RG in westeurope liegt;
      Activity-Log- und Resource-Health-Alarme, `az acr token create`
      und das Budget per `az rest` haben keine Region, die Action Group
      `-l Global` (1.4).
    - xtrace nur per `BASH_XTRACEFD` nach
      `~/.config/eurocis-aks/xtrace/` (chmod 700); Zuweisungen und
      Aufrufe mit Secret, objectId, UPN, Tag-Wert oder IP (auch
      `aks_tags`, das Laden von `.env.aks` und `az aks create --tags`)
      laufen zwischen `{ set +x; } 2>/dev/null` und `set -x` (1.4).
    - `aks_tags` liest `Owner` und `Created Date` zur Laufzeit aus
      `az group show -n gebit-showcase --query tags` und ergänzt
      `purpose=eurocis2027` und `deleteAfter=2027-02-28`. Es gilt für
      `az aks create --tags` und `--nodepool-tags` und für jedes
      `az aks update --tags`, das das ganze Tag-Set ersetzt [Quelle:
      `learn.microsoft.com/azure/aks/use-tags`]. Die Werte stehen in
      keiner Datei des Repos.
    - `aks_update` ist der einzige Weg zu `az aks update` und
      `az aks nodepool update`: bei `RequestDisallowedByPolicy`
      begrenzt wiederholen (3 Versuche, je 60 s Pause [A]), bei einem
      Failed-State `az aks update -g gebit-showcase -n aks-eurocis`
      zum Reconcile [Quelle: `github.com/Azure/AKS/issues/5856`;
      `learn.microsoft.com/troubleshoot/azure/azure-kubernetes/error-codes/requestdisallowedbypolicy-error`].
    - `require_kube_context` lehnt einen kubeconfig-Nutzer mit
      Client-Zertifikat (Admin-Zugang) ab; nur `bootstrap-rbac.sh`
      arbeitet mit einer Admin-kubeconfig.
    - Lint über `sli/aks/`: kein `az group delete`, kein `az role
      assignment`, kein `az lock` und kein `az aks delete` außerhalb
      von `aks-rebuild.sh`; `-l germanywestcentral` bei genau den vier
      regionalen `create`-Befehlen; jedes `kubelogin
      convert-kubeconfig` mit `--kubeconfig`, jedes `az aks
      get-credentials` mit `--file`.
  - `foundation.sh`, idempotent show-or-create, ohne Rollenzuweisung
    und ohne Lock, in zwei Teilen:
    - `foundation.sh pre` (P1, vor dem Create) bricht ab, wenn
      `gebit-showcase` fehlt oder die Tags `Owner` und `Created Date`
      nicht trägt; eine RG legt es nie an. Dann der Key Vault im
      Access-Policy-Modus (`--enable-rbac-authorization false`,
      `--retention-days 7`) mit einer Access Policy des Owners nach
      P1 Schritt 3 (Empfehlung: nur Secret-Rechte, also
      `--no-self-perms` und `az keyvault set-policy` mit get, list,
      set, delete, recover; die objectId kommt zur Laufzeit aus `az
      ad signed-in-user show`). Contributor darf das
      (`vaults/accessPolicies/write`); die Rolle "Key Vault Secrets
      Officer" und ihre Warteschleife entfallen [Quelle: azure-cli
      2.85.0 keyvault/custom.py:419-426, 623-639;
      `learn.microsoft.com/azure/key-vault/general/assign-access-policy`].
      Secrets nach P1 Schritt 3 (create-if-missing, hex, `-o none`).
      Am Ende von `pre`, noch vor `az aks create`: `alerts.sh access`
      mit den Zugriffs- und Löschalarmen (P1 Schritt 8), damit sie
      schon das Fenster mit aktiven lokalen Accounts abdecken.
    - Danach ACR Basic mit `--admin-enabled false
      --role-assignment-mode rbac` und Prüfung von
      `roleAssignmentMode`: Im Modus `rbac-abac` hätte Contributor
      weder Push noch Pull [Quelle:
      `learn.microsoft.com/azure/container-registry/container-registry-rbac-built-in-roles-directory-reference`].
      Test-Imports wie bisher mit curl und whoami. Pull-Token
      `aks-pull` auf einer Scope-Map nur zum Lesen
      (`_repositories_pull` oder eine eigene mit `content/read`,
      Frage 30), angelegt mit `--no-passwords`; ohne das Flag stünden
      zwei Passwörter ohne Ablauf in der Ausgabe. Das Passwort
      entsteht per `az acr token credential generate --password1
      --expiration <ablauf>` und geht per Pipe in den Key Vault
      (`acr-pull-token`, `--file /dev/stdin -o none`), eine Kopie nur
      in `sli/aks/.env.aks` (per `umask 077` nach `git check-ignore`,
      chmod 600, P1 Schritt 3); `password2` bleibt Rotationsreserve
      [Quelle:
      `learn.microsoft.com/azure/container-registry/container-registry-token-based-repository-permissions`;
      `az acr token create --help`, 2.85.0].
    - `foundation.sh post` (direkt nach dem Create): Label-Prüfung per
      `CheckDnsNameAvailability`, dann `pip-aks-ingress` in
      `gebit-showcase-nodes` (Standard, statisch, IPv4, `--dns-name
      <p>`); die Pflicht-Tags erbt sie [A]. Keine Rollenzuweisung: Die
      Control-Plane-Identität hat in ihrer Node-RG per Default
      Contributor [Quelle: `learn.microsoft.com/azure/aks/static-ip`;
      `learn.microsoft.com/azure/aks/managed-identity-overview`]. Kein
      Lock, weil Locks Owner oder User Access Administrator brauchen
      [Quelle:
      `learn.microsoft.com/azure/azure-resource-manager/management/lock-resources`];
      ein Cluster-Delete löscht IP und Label mit [Quelle:
      `learn.microsoft.com/azure/aks/faq`]. Dann liest `post` die
      AKS-verwaltete Egress-IP aus
      `networkProfile.loadBalancerProfile.effectiveOutboundIPs[].id`
      und schreibt beide Adressen ins lokale Register
      `~/.config/eurocis-aks/` (chmod 600, nie im Repo); die Egress-IP
      geht sofort an den LiteLLM-Betreiber (AKS-E11). Owner-Option
      `--dns-name-scope SubscriptionReuse`, nur beim ersten Anlegen
      setzbar (Frage 7).
  - `bootstrap-rbac.sh` (P1, direkt nach `foundation.sh post`; der
    Owner führt es aus, weil seine Entra-Identität gebunden wird):
    1. Entra-kubeconfig per `az aks get-credentials --file
       ~/.kube/aks-eurocis.yaml --context aks-eurocis`, dann `kubelogin
       convert-kubeconfig -l azurecli --kubeconfig
       ~/.kube/aks-eurocis.yaml --context aks-eurocis`; ohne `--file`
       bzw. `--kubeconfig` träfen beide `~/.kube/config`.
    2. Benutzername per `kaks auth whoami` (jsonpath
       `{.status.userInfo.username}`): bei Mitgliedern des Tenants der
       UPN, bei Nutzern aus einem anderen Tenant laut Learn die
       objectId [A: `whoami` zeigt die maßgebliche Form]. Der Wert
       steht nur im lokalen Register, nie im Repo oder Log.
    3. Admin-kubeconfig nach dem Muster aus P1 Schritt 6: `set -euo
       pipefail`, `umask 077`, `ADM_DIR=$(mktemp -d)` außerhalb des
       Repos, `trap 'rm -rf "$ADM_DIR"' EXIT` und `trap 'exit 1' INT
       TERM HUP` (ein `trap` mit `rm` direkt auf INT ließe das Skript
       nach Strg-C weiterlaufen), dann `az aks get-credentials --admin
       --file "$ADM_DIR/admin.yaml"`; nie nach `~/.kube`.
    4. ClusterRoleBinding `eurocis-owner-admin` (ClusterRole
       `cluster-admin`, `kind: User`, `name: <owner-upn>`) per stdin
       mit der Admin-kubeconfig, nach derselben Server-URL-Prüfung wie
       `require_kube_context` [Quelle:
       `learn.microsoft.com/azure/aks/kubernetes-rbac-entra-id`].
    5. `kaks auth can-i '*' '*' -A` mit der Entra-kubeconfig ergibt
       `yes`, sonst Abbruch vor Schritt 6.
    6. `aks_update --disable-local-accounts`; dann muss `az aks show
       --query disableLocalAccounts` `true` liefern, sonst Abbruch;
       erst danach der Negativtest in einem per `trap` gelöschten
       Temp-Verzeichnis: `az aks get-credentials --admin --file
       "$D/x.yaml" 2>"$D/err"` muss scheitern (gelingt er, Abbruch mit
       "FEHLER: Admin-Credential abrufbar"), und `$D/err` enthält
       "Getting static credential isn't allowed" [Quelle: `az aks
       get-credentials --help`, 2.85.0]. Erst dann Schritt 7.
    7. Option `--rotate-certs` (Frage 28): `az aks rotate-certs` vor
       dem ersten Workload (bis 30 min Ausfall), danach Schritt 1
       erneut. Learn verlangt die Rotation, wenn vor dem Abschalten
       lokale Accounts benutzt wurden [Quelle:
       `learn.microsoft.com/azure/aks/manage-local-accounts-managed-azure-ad`;
       `learn.microsoft.com/azure/aks/rotate-certificates`].
    8. Option `--bind <username> --name eurocis-deputy` für den
       Stellvertreter, später und mit der Entra-Identität des Owners,
       ohne Admin-Zugang (Rolle nach P7 Schritt 7).

    Notweg bei einem RBAC-Lockout: `aks_update
    --enable-local-accounts`, Admin-kubeconfig wie in Schritt 3,
    Binding reparieren, wieder `--disable-local-accounts` mit dem
    Nachweis aus Schritt 6, rotieren.
    `az aks command invoke` hilft dabei nicht, weil es mit dem
    Entra-Token des Aufrufers unter Kubernetes RBAC läuft [Quelle:
    azure-cli 2.85.0 acs/custom.py:2620-2626]. Ganz ohne
    Admin-Zertifikat ginge der Bootstrap nur mit einer eigenen
    Entra-Gruppe in `--aad-admin-group-object-ids` beim Create (Frage
    28).
  - `acr-pull.sh <ns>...` (nach `require_kube_context aks-eurocis`)
    liest `acr-pull-token` aus dem Key Vault (Rückfall
    `ACR_PULL_TOKEN` aus `sli/aks/.env.aks`, nur über die Umgebung),
    baut die `.dockerconfigjson` mit `jq` aus stdin und legt das
    Secret `acr-pull` idempotent an, per `kaks -n <ns> create secret
    generic acr-pull --type=kubernetes.io/dockerconfigjson
    --from-file=.dockerconfigjson=/dev/stdin --dry-run=client -o
    yaml` und `kaks -n <ns> apply --server-side -f -` (keine
    `last-applied-configuration` mit den Daten, wie P1 Schritt 8). Nie
    `create secret docker-registry --docker-password`, das legte das
    Passwort in die argv [A: `/dev/stdin` mit kubectl auf macOS in P1
    testen; Rückfall: Manifest per `jq` und `kaks apply --server-side
    -f -`].
    - Namespaces: `default` und `p2-test` (P1, P2), `traefik` und
      `monitoring` (P2), `iam` (P3), `solace` (P4), `sam-solace-lab`
      (P5); `gpos-data` und `gpos-demo` bedient `install.sh` selbst
      (5.4). Jede Phase legt Namespace und Secret vor helm bzw.
      kustomize an; `--create-namespace` allein reicht nicht mehr.
    - An die Pods kommt das Secret über Chart-Werte und Patches
      (`setup-aks.sh`, `keycloak/`, 5.2 bis 5.4). `--patch-default-sa`
      nur in Namespaces mit Ad-hoc-Pods (`default`, `p2-test`): Die
      ServiceAccount-Admission übernimmt Pull-Secrets nur in neue Pods
      dieses ServiceAccounts und nur, wenn der Pod-Spec keine nennt
      [Quelle:
      `kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin`].
    - `--check` meldet das Ablaufdatum des Passworts (`az acr token
      show --query "credentials.passwords[].expiry"`) für den
      Preflight; rot ist ein Ablauf vor dem 21.02.2027.
  - `aks-allow-me.sh` mit Kontext-Guard: liest
    `apiServerAccessProfile.authorizedIpRanges`, ergänzt die aktuelle
    öffentliche IP als /32 und schreibt die vollständige Liste über
    `aks_update --api-server-authorized-ip-ranges`. Der Aufruf
    ersetzt die ganze Liste und braucht bis 2 min [Quelle:
    `learn.microsoft.com/azure/aks/api-server-authorized-ip-ranges`];
    das Skript entfernt deshalb nie stillschweigend einen Eintrag (nur
    mit `--prune <ip>`, nie den letzten), wartet und prüft danach
    `kaks get --raw /readyz`; dazu `--print` und `--check` (P1
    Schritt 7). Neu: `--add <ip>`, mit dem der Owner die IP eines
    Stellvertreters ohne Azure-Recht einträgt (Frage 24). Das Skript
    braucht `managedClusters/write`, also Contributor.
  - Wartungs-JSONs mit beiden Sperrbereichen (auch für den Neuaufbau).
  - `setup-aks.sh` mit Kontext-Guard; Values-Overlays für Traefik,
    cert-manager und Monitoring (Registry je Image, vollständige
    `additionalDataSources`, Grafana ohne Ingress). Vor jedem `haks`
    legt es Namespace und Secret per `acr-pull.sh` an. Pull-Secret nur
    für Pods mit Images aus ACR, je Chart mit eigenem Schlüssel
    (Belege in P2 Schritt 1) [Quelle: Chart-Quellen, gelesen 18.11.]:
    - Traefik 42.4.1: `deployment.imagePullSecrets: [{name:
      acr-pull}]`.
    - kube-prometheus-stack 83.5.0: `grafana.image.pullSecrets:
      [acr-pull]` (Strings; nur Grafana kommt aus ACR).
    - loki 6.55.0: `imagePullSecrets: [{name: acr-pull}]`
      (SingleBinary samt Rules-Sidecar).
    - tempo 2.0.0: `tempo.pullSecrets: [acr-pull]` (Strings).
    - alloy 1.11.0: `image.pullSecrets: [{name: acr-pull}]`.
    - cert-manager v1.21.3: keins, die Images kommen von quay.io.
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
      `azure-load-balancer-resource-group: gebit-showcase-nodes`
      (explizit wie im Learn-Manifest static-ip; der Default auf die
      Node-RG ist nur durch cloud-provider-azure belegt, P2 Schritt 5)
      und `azure-load-balancer-tcp-idle-timeout: "30"`. Nie
      `azure-dns-label-name`: Fehlt diese Annotation, lässt der
      Cloud-Provider das beim Anlegen gesetzte Label stehen, ein
      leerer Wert löschte es. Eine fehlende `pip-aks-ingress` legt er
      nicht an (der Service scheitert sichtbar), eine selbst angelegte
      löscht er nie, auch nicht mit dem Service [Quelle:
      `learn.microsoft.com/azure/aks/static-ip`; cloud-provider-azure
      master pkg/provider/azure_loadbalancer.go:1359-1362, 1496-1498,
      1557-1566, 3791-3802, 18.11.]. `externalTrafficPolicy: Local`
      für echte Client-IPs [Quelle:
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
    oder Google Trust Services) nur als Vorlage
    `sli/aks/tls/issuers.tpl.yaml`: `keyID` und HMAC kommen beim
    Anwenden aus Key Vault (`acme-eab-kid`, `acme-eab-hmac`) und
    `.env.aks`, nie aus Git. `setup-aks.sh tls` rendert per `envsubst
    '${EAB_KID} ${EAB_ACME_SERVER} ${TLS_ISSUER} ${AKS_FQDN}' <
    sli/aks/tls/issuers.tpl.yaml | kaks apply -f -`, ohne gerenderte
    Datei (P2 Schritt 6).
  - `tls-backup.sh`: sichert `ingress-tls` nach jeder Ausstellung als
    volles Secret-JSON mit den cert-manager-Annotationen im Key Vault,
    per Pipe ohne Zwischendatei (`--file /dev/stdin -o none`, AKS-E17,
    P7 Schritt 2).
  - `.gitignore` (P0 Schritt 10, erste Datei im Ordner): `.env.aks*`,
    `*.swp`, `*~`, `*.log`, `*.pem`, `*.key`, `*.json` mit Ausnahme
    `!maint-*.json`.
  - VAP nach P2 Schritt 3: Service `LoadBalancer` nur für
    `traefik/traefik` mit `pip-aks-ingress`; die Annotation
    `azure-load-balancer-resource-group` fehlt oder ist
    `gebit-showcase-nodes`; nie `azure-dns-label-name`;
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
    Dazu ein Patch `imagePullSecrets: [{name: acr-pull}]` auf
    Deployment `keycloak` und StatefulSet `postgres`, weil die
    Lab-Manifeste weder Pull-Secret noch ServiceAccount setzen
    [Quelle: sli keycloak/manifests/02-postgres.yaml:31-54,
    03-keycloak.yaml:119-141]; ein Patch des default-ServiceAccounts
    liefe mit den ersten Pods um die Wette.
  - `aks-start.sh`, `aks-stop.sh` (30-min-Sperre; `aks-start.sh`
    prüft die Allowlist mit `aks-allow-me.sh --check` und vergleicht
    Ingress- und Egress-IP mit dem lokalen Register, P5 Schritt 6).
  - `alerts.sh` in zwei Teilen; alle Regeln und die Action Group (Mail
    an den Owner, Adresse nur lokal) liegen in `gebit-showcase` (`-g
    gebit-showcase`), nie in der Node-RG, die mit jedem
    Cluster-Delete verschwände und unter NRG-Lockdown nicht änderbar
    wäre. Activity-Log- und Resource-Health-Alarme ohne `-l` (global),
    die Action Group mit `-l Global`; Scopes per Ressourcen-ID bzw.
    Subscription mit Bedingung auf `resourceGroup` (1.4). Das Recht
    dazu folgt aus den Actions `*` von Contributor (P1 Schritt 8).
    - `alerts.sh access` (aus `foundation.sh pre`, vor dem Create):
      Activity-Log-Alarme auf `managedClusters/write`,
      `managedClusters/delete`,
      `managedClusters/listClusterAdminCredential/action`,
      `vaults/accessPolicies/write`, `vaults/delete`,
      `locations/deletedVaults/purge/action` (Subscription),
      `registries/tokens/write`,
      `registries/generateCredentials/action`, `registries/delete`,
      `publicIPAddresses/delete` (Node-RG) und
      `subscriptions/resourceGroups/delete` für `gebit-showcase` und
      `gebit-showcase-nodes`.
    - `alerts.sh cost` (nach dem Create): Budget per `az rest` (3.4),
      Resource-Health-Alarm auf den Cluster, Activity-Log-Alarm auf
      start/stop.
    - Abnahme: `az monitor activity-log alert list -g gebit-showcase`
      listet alle Regeln; `az resource list -g gebit-showcase-nodes`
      enthält keine `Microsoft.Insights`-Ressource. Die Alarme melden,
      verhindern aber nichts (Abschnitt 7).
  - `aks-rebuild.sh delete|teardown`: der einzige Weg zu `az aks
    delete` (Lint). Beide Modi verlangen den eingetippten
    Clusternamen. `delete` (Neuaufbau-Drill, P7 Schritt 3) verweigert
    vom 27.01. bis 20.02.2027 ohne `--freeze-override` und prüft
    vorher, dass `tls-traefik-ingress-tls` im Key Vault dasselbe
    `notAfter` wie das laufende Zertifikat hat, dass Dumps vom selben
    Tag existieren (P7 Schritt 2) und dass `foundation.sh post`
    bereitsteht. `teardown` (Rückbau, P7 Schritt 8) läuft erst ab
    19.02.2027 und nach Export, Descriptor-Löschung und Widerruf.
- Was gegenüber dem Stand vom 16.11. entfällt, steht in 8.5, was
  gegenüber dem 17.11. entfällt, in 8.6.
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
  nimmt nur reine Hex-Digests der Images aus. Eine kurze EAB-Kennung
  (rund 22 Zeichen) fängt sie nicht; deshalb zusätzlich `git ls-files
  aks/ | xargs grep -n 'keyID:'` nur mit `${EAB_KID}` und beim
  EAB-Issuer `server:` nur mit `${EAB_ACME_SERVER}`. EAB-Werte und das
  Passwort des ACR-Tokens nur im Key Vault und in `sli/aks/.env.aks`.

### 5.2 agent-mesh-deployment (geteilt, Freigaben AKS-E15 (a) und (b))

- Working Tree committet (`cd08a17`, 17.11.): SeaweedFS 2 CPU/2Gi,
  beide HIL-Flags, Sonnet 5 für `planning`, Preise für `fast`,
  `workflow` und `planning` [Quelle: amd
  scripts/models/set-pricing.sh:34-37].
- `scripts/lib/common.sh` lädt beim Sourcen keine Env-Datei, wie
  heute: Laden geht nur über `load_env DIR` [Quelle: amd
  scripts/lib/common.sh:23-31], und das liest auf `aks` nur
  `DIR/.env.aks`, sonst `DIR/.env`. Grund: gpd sourct `common.sh` und
  ruft `load_env` mit dem eigenen Verzeichnis; läse `common.sh` die
  amd-`.env.aks` selbst, stünden `LLM_SERVICE_API_KEY` und die übrigen
  amd-Secrets in der Umgebung aller gpd-Prozesse, und `sam config
  apply` expandiert `${VAR}` aus der Prozess-Umgebung [Quelle: gpd
  scripts/lib.sh:3-6, 12-13]. Test in gpd 5.4.
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
- Pull-Secret auf `aks` (P5 Schritt 3): `start.sh` legt `acr-pull`
  nicht selbst an und ruft kein sli-Skript auf; es prüft nach dem
  Anlegen des Namespace `sam-solace-lab`, dass das Secret existiert,
  und bricht sonst vor `helm` mit dem Hinweis auf `sli/aks/acr-pull.sh
  sam-solace-lab` ab. Ohne das Secret bräche das Chart selbst ab: Es
  prüft jedes Pull-Secret per `lookup`, auch für den Hook
  `sam-doctor` [Quelle: SAM-Chart 2.3.10 `_validations.tpl`:97-101,
  122-126; `templates/sam-doctor-hook.yaml`:36-49]. `stop.sh` löscht
  den Namespace samt Secret; jeder AKS-Zyklus ruft den Helfer vor
  `start.sh` erneut auf. `load-images.sh` pusht auf `aks` per `az acr
  login`; als Contributor geht das nur im Registry-Modus `rbac`
  (5.1).
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
  Schritt 4), `.env.aks.example`; `.env.aks*` mit Ausnahme
  `!.env.aks.example` sowie `*.swp` und `*~` in `.gitignore`, und zwar
  in P0 Schritt 10, bevor eine `.env.aks` existiert (heute ignoriert
  amd nur `.env`); `.env.aks` mit Modus 600; README-Abschnitt "AKS".
- `aks-values.yaml` (ohne Secret-Werte): `sam.dnsName` und
  `ingress.host` = `<fqdn>`; SAM bekommt `/`, weil der Chart keinen
  Basispfad kennt und die WebUI fest an der Wurzel hängt [Quelle:
  SAM-Chart 2.3.10 `_config_helpers.tpl`:10-108,
  `templates/ingress.yaml`:27-41]; `ingress.className: nginx`;
  Annotationen `proxy-body-size: "10m"` [A] und
  `proxy-request-buffering: "on"` (sonst setzt Traefik das Limit nicht
  durch) sowie `limit-connections: "20"` [A] gegen volle
  Request-Puffer (P2 Schritt 5, Lücke 7); keine
  `cert-manager.io`-Annotation; `global.imagePullSecrets:
  ["acr-pull"]` als Liste von Strings, gültig für gwe, awe, str,
  postgresql, seaweedfs und `sam-doctor` [Quelle: SAM-Chart 2.3.10
  `_images.tpl`:46-61; persistence-layer `statefulset.yaml`:34-46]
  (das Lab behält `registry-pull-secret` [Quelle: amd
  local-k8s-values.yaml:149-150]); Registry, Broker und Persistenz wie
  in P5 Schritt 2.
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
  - Nicht enthalten: die `SAM_*_IMAGE_TAR`-Schlüssel (Images über ACR),
    `GOOGLE_AI_STUDIO_API_KEY` (AKS stellt nur `fast` und `planning`
    bereit) und das Passwort des ACR-Tokens (nur Key Vault und
    `sli/aks/.env.aks`).
- Gate: Call-Log- und Render-Diff des Lab-Profils leer (P0 Schritt 13).

### 5.3 event-mesh-deployment (geteilt, Freigaben AKS-E15 (c) und (d))

AKS-Teil, nur neue Dateien:

- `aks/pubsubplus-values.yaml`: Image aus ACR per Digest
  (`solace/solace-pubsub-standard:10.26.0.9219`, Index
  `sha256:c0020e53ed48...`), `image.pullSecretName: acr-pull` (ein
  String; das Chart legt einen eigenen ServiceAccount an, ein Patch
  des default-ServiceAccounts erreichte den Broker nicht),
  `service.type: ClusterIP` explizit (Chart-Default wäre ein
  öffentliches LoadBalancer mit `latest`),
  `storage.useStorageGroup: true` ab dem ersten Install,
  `solace.usernameAdminPasswordSecretName: solace-admin`, Größe
  `prod1k` (Kriterium für `dev` in 3.2) [Quelle: pubsubplus
  3.10.0 values.yaml:113-133; templates/solaceStatefulSet.yaml:42-45,
  56]. Vor `helm` legt P4 Teil B Schritt 2 die Secrets `solace-admin`
  (per stdin) und `acr-pull` (`sli/aks/acr-pull.sh solace`) an.
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
KW48, solace-1 bis 04.12. (Prüfpunkt), spätestens 10.12.):

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
  `scripts/install.sh` schreibt xtrace nur nach
  `~/.config/eurocis-aks/xtrace/` (1.4) und lädt `.env.aks` (über
  `load_env` mit `set -a`) sowie die `printf`-Zeilen mit
  `$(db_password ...)` ohne xtrace [Quelle: gpd
  scripts/install.sh:133-138; scripts/lib.sh:13].
  Dazu ein Test gegen das Durchsickern der amd-Secrets: Mit einer
  amd-`.env.aks` voller Dummy-Werte im Scratch-Baum sind nach
  `TARGET=aks . scripts/lib.sh` `LLM_SERVICE_API_KEY`,
  `KEYCLOAK_CLIENT_SECRET`, `SAM_PG_ADMIN_PASSWORD` und
  `SAM_SESSION_SECRET_KEY` nicht gesetzt (`[ -z
  "${LLM_SERVICE_API_KEY+x}" ]`).
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
- Pull-Secret auf `aks` (P6 Schritt 6): `install.sh` legt `acr-pull`
  in `gpos-data` (Teil `pg`, vor dem StatefulSet) und `gpos-demo`
  (Teil `k8s`) selbst an, mit einer Funktion `apply_pull_secret` nach
  demselben Verfahren wie `sli/aks/acr-pull.sh`: Passwort aus dem
  Key Vault nur durch Pipes, nie in argv, Ausgabe oder Datei; kein
  Sourcing über Repo-Grenzen (P1 Schritt 6).
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
- `preflight.sh TARGET=aks` mit den read-only-Prüfungen aus P7 Schritt
  4, neu seit 18.11.: `pip-aks-ingress` und `nslookup <fqdn>`,
  Egress-IP gegen das lokale Register, `acr-pull` je Namespace und
  Ablauf des Token-Passworts nach dem 20.02.2027,
  `disableLocalAccounts true` und keine unerwarteten
  `listClusterAdminCredential`-, `accessPolicies/write`- oder
  `tokens/write`-Einträge im Activity Log.
- `k8s/base` + `overlays/lab|aks|l3`. Das aks-Overlay:
  - Pull-Secret: Ein JSON-Patch mit `target: {kind: Deployment}`
    ersetzt in allen sechs Deployments den Namen
    `registry-pull-secret` durch `acr-pull` (`op: replace`, `path:
    /spec/template/spec/imagePullSecrets/0/name`), statt die Liste zu
    entfernen; ohne `--attach-acr` bräche sonst jeder Pull aus ACR
    [Quelle: gpd k8s/{pos,engine,wws,loyalty,gate,ui}.yaml:21-23].
    `k8s/postgres-aks` trägt `imagePullSecrets: [{name: acr-pull}]`
    direkt. Ein Patch des default-ServiceAccounts wirkte hier nicht,
    weil die Pod-Specs eigene Pull-Secrets tragen [Quelle:
    `kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin`].
    `overlays/lab` bleibt byte-gleich mit `registry-pull-secret`.
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
    scheitern; ohne Pfad landet eine Seite bei SAM. Neu: Jeder
    Pod-Spec im Overlay `aks` und in `postgres-aks` nennt `acr-pull`,
    keiner `registry-pull-secret`.
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
  linux/amd64`). Push per `az acr login` und `docker buildx
  imagetools create` als Contributor, nur im Registry-Modus `rbac`
  (5.1).
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
| KW47 | 16.-22.11. | P0 (Owner + Claude): Owner-Entscheidungen vom 17.11. und 18.11. eingetragen; Login und read-only-Checks am 18.11. erledigt (Subscription `azure-se`, nur Contributor, Tag-Pflicht-Policies, Quota ohne Antrag, SKUs ohne Restriction, Defender Free); Anfragen an den LiteLLM-Betreiber (Allowlist mit dem Hinweis, dass die Egress-IP erst nach dem Create feststeht und sich bei jedem Neuaufbau ändert; Messe-Key mit `max_budget`, `rpm_limit`, `tpm_limit`), schriftliche Owner-Bestätigung zur GEBIT-Freigabe erbeten (Descriptor-Secret in Azure, öffentliche Reflection, Zugriffskreis der Contributor-Gruppe; fällig 27.11., spätestens 09.12.), Mac-Tools (Azure CLI 2.93+, kubelogin; freigegeben, noch nicht installiert); ab 20.11. nur die Label-Prüfung für `<p>`, keine Azure-Ressource vor P1 | O9 bis 20.11. [Quelle: PLAN 0.5 O9]; AKS-E20 (Name) bis 20.11. |
| KW48 | 23.-27.11. | P0 (C ab 23.11.): gpd-Baseline, Geländer, sam-CLI-Spike, Regressions-Gate; P4 Teil A: A1 Baseline (read-only), dann solace-2 (nach Owner-Go) | offene AKS-E (Abschnitt 2) bis 27.11.; Betreiber-Antwort (Allowlist ja oder nein, Key-Limits, Vorlaufzeit) 27.11.; Azure-Rechte und Tenant-Status des Stellvertreters geklärt 27.11. (Frage 24); Wartungsfenster für solace-1 festgelegt |
| KW49 | 30.11.-04.12. | P1: Re-Check von Label und Quota, Key Vault mit Access Policies, ACR mit Pull-Token, Cluster (1 Node, Pflicht-Tags, Node-RG `gebit-showcase-nodes`), `pip-aks-ingress` mit Label, Egress-IP sofort an den Betreiber, Bootstrap mit ClusterRoleBinding und abgeschalteten lokalen Accounts (`rotate-certs` nach Frage 28), CLI, `aks-allow-me.sh`, `acr-pull`, Budget und Alarme, Hairpin- und PVC-Test, LiteLLM-Probe; P4 Teil A an solace-1 im Wartungsfenster, Lab-Flows (A7); P2 Beginn (ACR-Spiegel, PriorityClasses, VAP, Traefik, LE staging, dann prod am 03.12.); ACME-Rückfallkonto und EAB-Daten in Key Vault und `sli/aks/.env.aks` (Owner) | Freischaltung der Egress-IP vor der LiteLLM-Probe (falls Allowlist); LiteLLM-Probe 03.12. als Frühindikator (AKS-E18); EAB-Daten bis 04.12.; **Prüfpunkt 04.12.** (P1, P4 Teil A) |
| KW50 | 07.-11.12. | P2 Rest (cert-manager HTTP-01, TLSStore, Traefik-Lückentests, Monitoring), P3 Keycloak unter `/auth` | LE-prod-Zertifikat Ready bis 07.12., 12:00, sonst EAB-Rückfall; GEBIT-Bestätigung (Descriptor-Secret) liegt bis 09.12. vor, sonst G0-11b (3) ohne `gebitsim`; gRPC-Teil G0-11b (11.12.); **Prüfpunkt 11.12.** |
| KW51 | 14.-18.12. | P4 Teil B Broker 10.26.0.9219 auf AKS, P5 SAM, HITL- und Vision-Test (G0-11a/b nach AKS-E18), HTTPS-RTT; Puffer | **G2a 18.12.** |
| KW52-53 | 21.12.-03.01. | Feiertage; Lab-Vorarbeit P6 (Overlays mit Pfad-Ingresses, `public-guard`, Seams, `postgres-aks`, Image 0.1.4 mit gemeinsamem Reflection-Endpunkt); C: AP14 Preflight; Cluster gestoppt | - |
| KW1 | 04.-10.01. | P6 auf AKS: pg, db, Image 0.1.4, k8s, mesh, Gate-Verifikation | ohne schriftliche GEBIT-Bestätigung kein `gpos-gebit-descriptors` auf AKS, Demo dann nur im Lab oder in L3 (AKS-E16) |
| KW2 | 11.-15.01. | P6 e2e, TR1-Besuche über das öffentliche Internet (Leih-Router mit Kabel und 5G, Mobilfunk-Hotspot), TR3 (falls im Lab grün), `install.sh all` aus leerem Namespace; am 15.01. `cmctl renew -n traefik ingress-tls` und TLS-Backup | **G2b 15.01.** |
| KW3 | 18.-22.01. | P7 Drills: Neuaufbau (`az aks delete`, Create mit Pflicht-Tags, Label `<p>` sofort neu gebunden, Bootstrap, neue Egress-IP an den Betreiber, TLS aus dem Backup), 24-h-Lauf (Mo 18.01. 12:00 bis Di 19.01. 12:00) mit 10-h-Kiosklauf über den öffentlichen Ingress, 3 Stop/Start-Zyklen mit je 30 min Pause (Ingress- und Egress-IP vor und nach jedem Zyklus), Netz (Kabel ziehen, 5G), Missbrauchstest `public-guard`, L3; Backups mit Restore-Test; Runbook; Binding und Key-Vault-Policy des Stellvertreters | **G3 22.01.**; Wartungssperre 20.01. |
| KW4 | 25.-31.01. | Node-Image-Refresh Di 26.01. (vorher Quota-Re-Check und Ablauf des Token-Passworts prüfen; Ausfallzeit messen); Runbook, Preflight, Fixes; Probetage 28.01. (Runbook-Durchlauf des Stellvertreters) und 29.01. | Wartungssperre ab 27.01. |
| KW5 | 01.-05.02. | Probetag 3 am 03.02. (Break-glass-Test des Stellvertreters mit eigenem Azure-Recht, sonst durch den Owner); Traefik-Patchstand und Defender-Pläne prüfen | **G4 Freeze 05.02.** |
| KW6 | 08.-14.02. | 24/7, Preflight täglich; LE-64-Tage-Wechsel am 10.02. ohne Wirkung (das Zertifikat vom 15.01. gilt bis Mitte April) | Netztest 14.02. |
| KW7 | 15.-21.02. | Messe 16.-18.02.; 19./20.02. Export, Descriptor-Secret löschen, stoppen; Rückbau nach Entscheidung (`az aks delete`, ACR samt Token, Key Vault mit Purge, Budget und Alarme) | Rückbau-Entscheidung |

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
| 48 | P0-Rest 1,75 (0,5 von 2,25 PT tragen Owner und Claude in KW47); P4 Teil A an solace-2 0,5 | AP04a Container 0,5; AP07b Loyalty-Tools 0,75 (aus KW51 vorgezogen) | 3,5 |
| 49 | P1 2,25; P4 Teil A an solace-1 0,5; P2 Beginn 0,75 | AP08 `install.sh mesh` 0,75 | 4,25 |
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

Die Prüfung vom 18.11. verschiebt Arbeit von P0 nach P1: Die
Azure-Vorab-Anlage aus P0 (RG, beide IPs, Lock) entfällt, dafür
bringt P1 Pull-Token, `acr-pull`, Bootstrap und die IP-Anlage nach
dem Create (8.6). KW49 bleibt mit 4,25 PT nahe an den 4,3 PT
netto; ein Überhang geht in den Puffer von KW51.

KW1-2 ist für C überbucht (8,5 gegen 6,1 PT netto), weil P6
die PLAN-Posten AP12 S7-S8 aus KW51 aufnimmt. Vorschlag [A], mit dem
PLAN-Eigner zu klären:

- AP11 `/op` (1,5 PT) geht an Entwickler B; B trägt in KW1-2 laut
  PLAN 7.3 5,0 PT, darin 1 PT G2-Puffer.
- Der AP14-Rest (1 PT) wandert nach KW5 (C dort sonst 1,5 PT).
- Danach trägt C in KW1-2 6,0 PT.

**Prüfpunkte statt eines Rückfalls am 18.12.:**

- 04.12.: P1-Abnahme und Abnahme P4 Teil A grün (Lab auf
  10.26.0.9219, SAM- und GEBIT-Flows belegt). Zur P1-Abnahme gehören
  seit dem 18.11. die Pflicht-Tags auf `gebit-showcase-nodes`,
  abgeschaltete lokale Accounts, `pip-aks-ingress` mit Label `<p>` und
  die beim Betreiber gemeldete (und, falls Allowlist, freigeschaltete)
  Egress-IP. Ist Teil A rot, entscheidet der Owner: Teil A bis 10.12.
  nachholen (Teil B beginnt erst danach) oder Rückfall wie unten.
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
| Skript oder Ad-hoc-Befehl wirkt auf das falsche Ziel: kein Skript pinnt einen Kontext; `stop.sh` löscht Release, PVCs, Namespace und räumt Lab-Keycloak und Lab-Broker-Queues ab; ein `kubectl apply -k` ohne Kontext träfe den Lab-Keycloak in `iam` [Quelle: amd scripts/stop.sh:102-115, 161-162, 247-249; Befehl `grep -rnE -- '--context\|KUBECONFIG'`; Befehl `kubectl config current-context` = rancher-desktop, 16.11.] | P0 vor jeder AKS-Credential: eigene kubeconfig-Datei nur über `kaks`/`haks`, `require_kube_context` mit Server-URL (lehnt auch Admin-kubeconfigs ab), SEMP-Identitätsprüfung, Keycloak-Teardown-Guard, `SAM_HOME` je Ziel, Negativtests, Lint gegen nackte kubectl/helm-Aufrufe, Call-Log- und Render-Diff-Gate |
| Tag-Pflicht und Policies in `azure-se`: 2 x "Require a tag on resource groups" (deny) für `Owner` und `Created Date`, 2 x "Inherit a tag from the resource group" (modify). AKS legt die Node-RG selbst an; ohne `--tags` scheitert der Create. Laut einem Community-Report schreibt der Resource Provider die Node-RG bei späteren Updates zeitweise ohne die Cluster-Tags und scheitert mit RequestDisallowedByPolicy, auch Stunden nach dem Create (betrifft `--disable-local-accounts`, `aks-allow-me.sh`, Lockdown, eventuell Upgrades). Eine Policy-Ausnahme kann der Owner nicht anlegen; ob die Zuweisungen die Built-in-Definitionen nutzen, ist ungeprüft. Die RG-Metadaten liegen in westeurope; fällt die Region aus, leitet ARM Schreibzugriffe auf `gebit-showcase` in eine Backup-Region um [Quelle: Befehle `az` read-only, 18.11.; `learn.microsoft.com/azure/aks/use-tags`; `github.com/Azure/AKS/issues/5856`; `learn.microsoft.com/azure/azure-resource-manager/management/overview`] | `aks_tags` mit allen vier Tags bei Create (`--tags`, `--nodepool-tags`) und bei jedem `--tags`-Update, Werte von `Owner` und `Created Date` wie an `gebit-showcase`; nach dem Create `az group show -n gebit-showcase-nodes --query "keys(tags)" -o tsv` und ein stiller Wertvergleich (P1-Abnahme); `aks_update` wiederholt begrenzt und reconciled; Built-in-Check read-only in P0 (Frage 6); bleibt ein Update blockiert, braucht es eine Ausnahme durch einen Subscription-Admin (Frage 6), bis dahin L3 als Rückfall; die Lage in westeurope ist ein geringes Restrisiko [A] |
| Kein Lock, Label an der Node-RG: Ein `az aks delete` (auch durch ein anderes Mitglied der Contributor-Gruppe oder im Neuaufbau) löscht `gebit-showcase-nodes` samt `pip-aks-ingress`; die IP ist nicht wiederherstellbar, das Label `<p>` kann danach jeder in der Region belegen, und Kiosk-URLs und QR-Codes zeigten auf einen fremden Host. `az group delete -n gebit-showcase` nähme zusätzlich ACR und Key Vault mit. Locks brauchen Owner oder User Access Administrator. Bis zum Create (ab 30.11.) ist das Label gar nicht reserviert [Quelle: `learn.microsoft.com/azure/aks/faq`; `learn.microsoft.com/azure/virtual-network/ip-services/public-ip-addresses`; `learn.microsoft.com/azure/azure-resource-manager/management/lock-resources`] | Runbook-Regel: Cluster nur über das Neuaufbau- bzw. Rückbau-Verfahren aus P7 löschen, und zwar nur per `sli/aks/aks-rebuild.sh` (`delete` bzw. `teardown`; eingetippter Clustername, Sperre 27.01.-20.02. ohne `--freeze-override`, Vorprüfung von TLS-Backup, Dumps und `foundation.sh post`); nie `az group delete -n gebit-showcase`; der Lint in `sli/aks/` verbietet beides und jedes nackte `az aks delete`; `foundation.sh post` bindet das Label direkt nach jedem Create, vorher `CheckDnsNameAvailability`; Activity-Log-Alarme schon vor dem Create auf `managedClusters/delete`, `publicIPAddresses/delete`, das Löschen von Key Vault, ACR und beiden RGs und auf den Vault-Purge (P1 Schritt 8), bei Vault-Delete binnen 7 Tagen `az keyvault recover`; TLS-Backup; neutrales Präfix; Owner-Optionen NRG-Lockdown `ReadOnly` nach P2 (verhindert Löschen und Ändern in der Node-RG durch Nutzer, nicht `az aks delete`; Frage 29) und Label-Scope `SubscriptionReuse` (Preview, FQDN mit Hash; Frage 7) [Quelle: `learn.microsoft.com/azure/aks/node-resource-group-lockdown`]; Nachweis in P1 und P2: `pip-aks-ingress` überlebt das Löschen eines Test-Service, der Tag `k8s-azure-service` fehlt |
| Contributor-Gleichrang in `azure-se`: Kubernetes RBAC und Key-Vault-Access-Policies sind keine Grenze gegen andere Contributors. Jeder kann lokale Accounts wieder einschalten und Admin-Credentials holen, sich eine Key-Vault-Policy setzen oder ACR-Tokens anlegen und so Secrets, das GEBIT-Descriptor-Secret und (über die SAM-Datenbank) den LiteLLM-Key lesen [Quelle: `learn.microsoft.com/azure/aks/manage-local-accounts-managed-azure-ad`; `learn.microsoft.com/azure/key-vault/general/assign-access-policy`; `learn.microsoft.com/azure/role-based-access-control/built-in-roles/privileged`] | Owner-Entscheidung offen (Frage 27), auch gegen die GEBIT-Freigabe (AKS-E16, Frage 4); Activity-Log-Alarme auf `managedClusters/write`, `listClusterAdminCredential/action`, `vaults/accessPolicies/write`, `registries/tokens/write` und `registries/generateCredentials/action` (ein zweites Token-Passwort löst `tokens/write` nicht aus), angelegt vor dem Create (`alerts.sh access`; sie melden, verhindern aber nichts); Preflight prüft `disableLocalAccounts true` und das Activity Log der letzten 24 h; Descriptor-Secret wie bisher nur zur Laufzeit und bis 20.02. |
| Bootstrap mit lokalem Admin: Zwischen Create und `--disable-local-accounts` gelten lokale Accounts, jeder Contributor kann Admin-Credentials holen; das Admin-Zertifikat aus dem Bootstrap bleibt bis zu einer Rotation gültig [A]. Ein falsches Binding-Subjekt (UPN bei Mitgliedern, objectId bei Nutzern anderer Tenants) sperrt den Owner nach dem Abschalten aus [Quelle: `learn.microsoft.com/azure/aks/kubernetes-rbac-entra-id`; `learn.microsoft.com/azure/aks/manage-local-accounts-managed-azure-ad`] | `bootstrap-rbac.sh` direkt nach dem Create in einem Zug: Subjekt aus `kaks auth whoami`, `can-i` vor dem Abschalten, Admin-kubeconfig nur in einem Temp-Verzeichnis mit `set -euo pipefail`, `umask 077` und `trap` (auch bei Abbruch gelöscht); `disableLocalAccounts true` geprüft, erst dann der Beweis, dass `get-credentials --admin` scheitert, und erst danach `rotate-certs`; Zugriffsalarme schon vor dem Create; `az aks rotate-certs` vor dem ersten Workload (bis 30 min) oder eine eigene Entra-Gruppe für `--aad-admin-group-object-ids` (Frage 28); Notweg `--enable-local-accounts`, reparieren, abschalten, rotieren; `az aks command invoke` ist kein Weg am RBAC vorbei |
| ACR-Token: Ein abgelaufenes Passwort fällt erst beim nächsten Pull auf (Surge-Node am 26.01., Pod-Neustart auf neuem Node, Neuaufbau) und führt zu ImagePullBackOff. Ein geleaktes Passwort erlaubt jedem den Pull aller Repos (SAM-, gpos- und Plattform-Images, kein GEBIT-Material); das Secret `acr-pull` liest, wer im Namespace Secrets lesen darf [Quelle: `learn.microsoft.com/azure/container-registry/container-registry-token-based-repository-permissions`] | Ablauf 2027-02-28T23:59:59Z, also nach dem Rückbau am 20.02. und außerhalb des Freeze (Frage 30); `acr-pull.sh --check` im Preflight, rot bei Ablauf vor dem 21.02.2027; `password2` als Reserve für einen Wechsel ohne Ausfall; nur Pull, kein Push; Passwort nie in argv oder Ausgabe, nur Key Vault und `sli/aks/.env.aks` (chmod 600); Alarm auf `registries/generateCredentials/action`; Widerruf per `az acr token update --status disabled`; der Rückbau löscht die Registry samt Token |
| Egress-IP wechselt: Die AKS-verwaltete Outbound-IP ist erst nach dem Create bekannt und nach jedem Neuaufbau neu; eine BYO-IP außerhalb der Node-RG bräuchte Rechte der Cluster-Identität. Mit einer Allowlist beim LiteLLM-Betreiber läuft SAM nach einem Neuaufbau ohne LLM, bis die neue IP freigeschaltet ist; das kann den 4-h-Drill in G3 sprengen. Ob die IP Stop/Start und den Node-Image-Refresh übersteht, ist nicht dokumentiert [Quelle: `learn.microsoft.com/azure/aks/configure-load-balancer-standard`] | Vorankündigung am 20.11., Meldung direkt nach dem Create (`foundation.sh post`), Freischaltung vor der Probe am 03.12.; Vorlaufzeit des Betreibers erfragen und ins Neuaufbau-Runbook übernehmen, Drill-Termin vorher ankündigen (Frage 26); G3-Kriterium neu fassen (Frage 31); `aks-start.sh` vergleicht die IPs nach jedem Start mit dem lokalen Register, P1 und P7 messen Stop/Start [A]; ohne Allowlist (Frage 5) entfällt das Risiko |
| Azure CLI noch 2.85.0, kubelogin fehlt: 2.85.0 nutzt für Key Vault die API 2025-05-01, und alle Versionen vor 2026-02-01 enden am 27.02.2027; die Flags (`--role-assignment-mode`, `--dns-name-scope`, `--nrg-lockdown-restriction-level`) sind in 2.85.0 vorhanden, 2.93 bleibt Pflicht wegen der Key-Vault-API; `az aks create` kennt in 2.85.0 kein `--max-surge` (daher das Nodepool-Update) [Quelle: `--help`-Ausgaben 2.85.0, 18.11.; `learn.microsoft.com/azure/key-vault/general/access-control-default`; azure-cli 2.85.0 site-packages, 18.11.] | Upgrade auf 2.93 oder neuer und kubelogin (freigegeben, AKS-E15 (e)) vor dem ersten Azure-Schreibschritt in P1; danach die Flags per `--help` gegenprüfen; Rückbau nur mit der neuen CLI |
| Ein Node ohne HA: Node-Ausfall, Host-Wartung, Node-Image-Update oder Neustart legt alle Dienste für einige Minuten still, die Disks hängen danach neu an. Learn verlangt für produktive System-Pools mindestens 2 Nodes (empfohlen 3), der AKS-Quickstart nutzt `--node-count 1` [Quelle: `learn.microsoft.com/azure/aks/use-system-pools`; AKS-Quickstart] [A] | vom Owner am 17.11. akzeptiert; der Create in P1 belegt die Zulässigkeit; manueller Refresh Di 26.01. mit gemessener Ausfallzeit, Sperre ab 27.01.; L3 warm an Probetagen und Messe, L4 über `/op`; Resource-Health-Alarm; Runbook-Schritt "Node NotReady"; aus gestopptem Cluster bis READY höchstens 30 min (G3) |
| Requests auf einem Node knapp: mit Broker `prod1k` rund 91 % CPU- und 70 % RAM-Requests (3.2); ein zusätzlicher Pod (Debug-Pod, Run-Pod von `az aks command invoke` mit 200m CPU und 500Mi, Surge beim Rollout, Restore-Scratch-Pod) bleibt Pending; Keycloak-OOM und SeaweedFS-Hänger wie im Lab | Requests auf Ist-Werte, Keycloak 1,5Gi, SeaweedFS 2 CPU/2Gi (committet in `cd08a17`), Prometheus-PVC; Nachzug nach einer Woche AKS-Daten (P7 Schritt 1); Broker `dev` als Rückfall (78 % CPU, Kriterium in 3.2, nur vor dem ersten Install in P4); `maxSurge 0` für große Deployments, wo nötig [A]; kein Defender-Sensor (Pläne Free, 18.11.) |
| Let's Encrypt, geteilter Bucket: `cloudapp.azure.com` steht nicht auf der Public Suffix List, alle Azure-Kunden teilen das Limit von 50 neuen Zertifikaten je Woche für `azure.com`; die Ausstellung kann tagelang scheitern [Quelle: PSL, abgerufen 17.11.; PSL-PR 1966; `letsencrypt.org/docs/rate-limits`; `community.letsencrypt.org/t/217855`] | ein Zertifikat (`ingress-tls`) für den einen FQDN, kein Certificate je Namespace; erst staging, dann prod am ersten P2-Tag; ist bis 07.12., 12:00 kein Prod-Zertifikat Ready, übernimmt der vorbereitete Rückfall-ClusterIssuer `acme-eab-fallback` mit EAB (ZeroSSL oder Google Trust Services, Konto vom Owner, EAB nur in Key Vault und `.env.aks`); Secret nach jeder Ausstellung sichern; Erneuerungen desselben Namenssets zählen nicht gegen das 50er-Limit |
| LE-Limits bei Drills; eine automatische Erneuerung fiele um den 02.02. in die Sperre; LE wechselt am 10.02.2027 auf 64 Tage [Quelle: `letsencrypt.org/ca/upcoming-features`] | TLS-Backup als volles Secret mit cert-manager-Annotationen, vor Certificate und Ingresses eingespielt, sonst Drill gegen staging; `cmctl renew` um den 15.01., damit die nächste Erneuerung erst Mitte März fällt; danach Backup und `export-le-certs.sh` für L3 |
| Traefik weicht vom Lab ab: Das Lab bleibt auf ingress-nginx; Traefik-eigene Teile (IngressClass, Middleware, TLSStore, Timeouts, Request-Buffering) und die AKS-Pfad-Ingresses (gpos, gRPC, Keycloak `/auth`) laufen nur auf AKS; Annotationen wirken anders (`proxy-body-size` nur mit `proxy-request-buffering: "on"`, Rate-Limits mit 429 statt 503); Sicherheits-Patches etwa wöchentlich [Quelle: Traefik v3.7.19 ingress-nginx.md:265-502; GitHub-Security-Advisories, 17.11.] | P2 beweist die Traefik-Konfiguration zuerst: HTTP-01, GRPC, SSE 20 min mit `curl --http1.1 -N`, ein 900-s-Halt, Default-Zertifikat, 413 über dem Body-Limit; Abweichungen nur im aks-Overlay, Render-Tests für alle Overlays; Image per Digest, nie unter v3.7.18; im Freeze nur Patch-Releases mit Smoke-Wiederholung (Owner-Frage, Abschnitt 9) |
| Öffentliche anonyme Schreibpfade: Kasse (`/api/pos/...`), `/api/demo/reset` (auch Scope `day`) und die gRPC-Schreib-RPCs (WWS `RequestPriceChange`, `EndPriceChange`, `ResetDemoState`; Loyalty `IssueCoupon`, `VoidCoupon`, `ResetDemoState`) ruft jeder auf. Preise ändern sich ohne SAM-Freigabe, Resets stören die Demo, Skript-Schleifen kosten LLM-Geld: eine Prüfung alle 5 s rund 7-36 USD/h, der 150-USD-Key ist in 4-21 h leer, danach steht die Demo [A; Quelle: PLAN 0.5 O5, PLAN R24] | Owner hat anonyme gRPC-Schreibaufrufe, Reflection und die Kasse ohne Login am 17.11. akzeptiert; `public-guard` mit Rate-Limits je Client-IP auf `/api/pos`, `/api/demo/reset`, `/api/events` und den drei gRPC-Service-Pfaden (`externalTrafficPolicy: Local`); der LiteLLM-Betreiber setzt `max_budget`, `rpm_limit` und `tpm_limit` am Messe-Key [Quelle: `docs.litellm.ai/docs/proxy/users`]; Preflight und Day-Reset jeden Morgen; Grafana-Ansicht der Läufe je Stunde, bei Missbrauch Limits verschärfen; SAM-Budget unter dem Key-Limit als sichtbarer Notschalter [A: Umfang des Budgets in P5 prüfen] |
| Ein öffentlicher Eingang mit einem Traefik-Pod: Request-Buffering für SAM und gpos-ui legt Bodies im emptyDir ab; viele parallele Uploads füllen es, das Kubelet verdrängt den Pod, und Kasse, Monitor, SAM, Keycloak und gRPC sind bis zum Neustart weg; `limit-rps` begrenzt nur die Rate [Quelle: Traefik-Chart 42.4.1 values.yaml:119-121; Recherche 17.11.] | `limit-connections` 20 je Client-IP am SAM-Ingress, SAM-Body-Limit 10m [A], `sizeLimit` 2Gi plus Request auf `ephemeral-storage` (P2 Schritt 5, P5 Schritt 2), Lasttest in P2 und P5; Restrisiko: verteilte Uploads aus vielen IPs können das emptyDir weiter füllen, dann die Route sperren (Runbook, Freeze-Ausnahme) |
| Access-Log mit Tokens oder Besucher-IPs: Die SAM-WebUI hängt ihr Access-Token als Query-Parameter an SSE-Aufrufe; ein Access-Log mit vollem `RequestPath` brächte Tokens von sam_admin und `marktleitung` nach Loki, Grafana und in den Export [Quelle: SAM-WebUI-Bundle und ingress-nginx-Log aus dem Lab, 17.11.] | Traefik-Access-Log mit `queryParameters.defaultMode: drop` und ohne Header (P2 Schritt 5); Zählabfrage `[?&]token=` in Loki ergibt 0 (P2, P5); Loki-Export nach der Messe ohne Access-Logs und mit Zählprüfung (P7 Schritt 8); Besucher-IPs liegen 7 Tage in Loki [A] |
| Geteilter Origin: gpos (öffentlich, ohne Login) liegt auf demselben Origin wie SAM, dessen Bearer-Tokens im localStorage liegen; ein XSS in gpos könnte sie lesen [Quelle: SAM-WebUI main.js, Befehl `curl` 17.11.] | Risiko niedrig, vom Owner akzeptiert: gpos setzt keine Cookies, nutzt keinen Web-Storage und baut das DOM nur mit `textContent` [Quelle: gpd app/gposdemo/ui/static/shared/common.js; kasse.js; monitor.js]; Hygiene-Test gegen `innerHTML` und `insertAdjacentHTML` in den gpos-UI-Dateien [A]; `redirectUris` exakt auf den Callback; HSTS ohne `includeSubDomains`; Rückfall nur mit neuer Owner-Entscheidung: ein zweites DNS-Label nur für gpos (dritte Public IP, rund 3,3 EUR/Monat; mit zwei weiteren Regeln 5 LB-Regeln, noch im Grundpreis) |
| Admin-Oberflächen öffentlich erreichbar (Keycloak-Admin und Master-Realm, Grafana, Prometheus, Broker-SEMP, Traefik-Dashboard, NodePorts) | VAP erlaubt `LoadBalancer` nur für `traefik/traefik` mit `pip-aks-ingress`, RG-Annotation fehlend oder `gebit-showcase-nodes` (zweiter LB-Service, fehlendes `azure-pip-name` und eine fremde RG als Negativtests in P2); das Azure-LB hat nur Regeln für 80 und 443, die Nodes haben keine öffentliche IP; Keycloak-Ingress nur `/auth/realms/solace-lab/` und `/auth/resources/`; Grafana, Prometheus, SEMP und Traefik-Dashboard nur per Port-Forward. Negativtests aus dem Internet in P3, P6 und P7: `/auth/admin/` und `/auth/realms/master/` liefern keine Keycloak-Seite (sie fallen auf SAMs SPA-Fallback mit 200, geprüft wird das Fehlen von Keycloak-Inhalt, nicht ein 404) |
| CT-Logs: Die Ausstellung veröffentlicht den FQDN, Scanner finden den Host binnen Minuten [A]. Offenes Risiko: Jeder kann den Approver `marktleitung@solace.lab` mit 5 Fehlversuchen wiederholt bis 900 s sperren; der Name steht in rund 35 Dateien des öffentlichen Repos, der Realm erlaubt Login per E-Mail [Quelle: sli keycloak/manifests/03-keycloak.yaml:30-47; Befehl `git grep -l` auf Commit 7a860c5, 17.11.] | neutrales Präfix `<p>` ohne Kunden- oder Produktnamen; keine Admin-Oberfläche öffentlich; Rate-Limits; Brute-Force-Schutz bleibt an; Entscheidung in P3: nicht erratbarer Approver-Username mit `loginWithEmailAllowed: false` in der AKS-Realm-Kopie (E-Mail und `SAM_RUN_IDENTITY` bleiben [A]) oder bewusst hinnehmen mit Runbook-Schritt "Sperre aufheben" über die Admin-Konsole per Port-Forward; `passwordPolicy` gegen kurze Passwörter |
| API-Server: Die IP von Owner oder Betreiber wechselt (Heimnetz, 5G, Messe), kubectl scheitert; `az aks update --api-server-authorized-ip-ranges` ersetzt die ganze Liste [Quelle: `learn.microsoft.com/azure/aks/api-server-authorized-ip-ranges`] | `sli/aks/aks-allow-me.sh` ergänzt die aktuelle IP und schreibt die vollständige Liste (mit `--add` auch für einen Stellvertreter ohne Azure-Recht); Break-glass ohne Allowlist mit `az aks command invoke`: läuft über ARM mit dem Entra-Token des Aufrufers, also nur mit eigenem ClusterRoleBinding, und braucht `runCommand/action` (in Contributor enthalten) [Quelle: `learn.microsoft.com/azure/aks/access-private-cluster`; azure-cli 2.85.0 acs/custom.py:2620-2626]; jeder Lauf von `aks-allow-me.sh` ist ein `az aks update` (Zeile zur Tag-Pflicht); im Freeze nur `aks-allow-me.sh`, das ergänzt und nichts entfernt [A: Owner bestätigt die Ausnahme] |
| Hairpin: SAM-Selbstaufrufe und der Back-Channel von SAM zu Keycloak gehen an denselben öffentlichen FQDN; Pod → öffentliche LB-IP mit `externalTrafficPolicy: Local` ist auf Overlay mit Cilium ungeprüft [A] | Test in P1 (Curl-Pod gegen `https://<fqdn>/`, ab P3 gegen den Issuer); Rückfall `kube-system/coredns-custom` mit Rewrite des FQDN auf die Traefik-ClusterIP [Quelle: `learn.microsoft.com/azure/aks/coredns-custom`; amd scripts/start.sh:136-147] |
| gRPC-Reflection bis Image 0.1.4: Reflection- und Health-Pfade sind auf allen drei Servern gleich, über einen Host erreichen `grpcurl list` und Postman nur einen Server [Quelle: gpd app/gposdemo/common/grpcutil.py:150-167] | bis 0.1.4 geht Reflection an `gpos-pos`; WWS und Loyalty per `-protoset` aus dem eigenen Showcase-Descriptor; 0.1.4 mit gemeinsamem Reflection-Endpunkt in der Lab-Vorarbeit KW52-53, Lab zuerst (`make test`, `make smoke`, S1-e2e); gRPC-Health bleibt clusterintern |
| Neue BFF-Seiten: Das aks-Overlay routet gpos nur über ausgeschnittene Pfade; eine neue Seite ohne Pfad landet bei SAM (SPA-Fallback 200). Umgekehrt wären `/freigabe` (beantwortet SAM-HITL über die BFF), `/foto` (startet den Vision-Agenten), `/op` und `/etikett` mit Pfad öffentlich ohne Login: Jeder könnte Preise freigeben oder den Messe-Key leeren [Quelle: PLAN 1.4; PLAN 9 R24]; `/` und `/health` gehören SAM | Owner-Entscheidung offen (Frage 23, vor G2b), nicht akzeptiert; bis dahin kein Pfad. Test in `scripts/tests/test_k8s.py` mit zwei ausdrücklichen Listen (öffentlich, Exposition offen), der bei einer gerouteten offenen Route scheitert; LLM-auslösende Routen nur mit eigenem `public-guard`-Limit; Kollisionsprüfung gegen die SAM-Routen je SAM-Release [A]; Kiosk-URLs direkt auf `/kasse` und `/monitor` |
| Lab-Broker-Upgrade (P4 Teil A) mit DBs im Container-Layer: solace-1 und solace-2 haben keine Mounts, die Compose-Hashes weichen ab; `start.sh` würde beide neu erzeugen und leeren, `stop.sh` löscht sie; 36 Queues und die iCargo-User liegen außerhalb von Terraform; ein Downgrade ist nicht unterstützt [Quelle: Befehle `docker inspect`, `docker compose config --hash` und SEMPv2-GETs, 17.11.; emd start.sh:4-6, stop.sh:2; `docs.solace.com` Upgrade-Selector] | Risiko mittel bis hoch; eigenes Owner-Go und Wartungsfenster; bis zur Anpassung der emd-Skripte (auch nach der Migration, weil `stop.sh` den Terraform-State löscht) im emd-Lab nur `docker start/stop` bzw. `docker compose stop/start`, kein `start.sh`, `stop.sh`, `compose up/pull/down`, kein Prune; README, `CLAUDE.md` und Memory-Notiz nennen den geltenden Zyklus; Schritte nach P4 A1-A8: SEMPv2-Baseline, `docker commit` als Rückfall, externes Volume, Tag plus Digest in `.env.example`, `compose up -d --no-deps` je Broker, solace-2 zuerst, `terraform plan` leer; SAM- und GEBIT-Flows im Lab belegt, bevor P4 Teil B und P5 beginnen (Prüfpunkt 04.12., spätestens 10.12.) |
| LiteLLM aus Azure nicht erreichbar oder langsamer (rund +100 ms je Aufruf [A: RA 5.2]) | Vorankündigung an den Betreiber am 20.11., Egress-IP direkt nach dem Create (P1, ab 30.11.), schriftliche Antwort zu Allowlist und Limits bis 27.11.; Probe aus dem Pod in P1; A4-Vergleich in P6 |
| LiteLLM-Key außerhalb von SAM lesbar: Klartext in `model_configurations` und `gateway_deployments`, Grafana-Grant auf alle Tabellen, pg_dumps, App-User mit Passwort = Username; die BFF ohne Login läuft im selben Cluster [Quelle: amd scripts/models/README.md:77-79; grant-grafana-platform-db.sh:72; SAM-Chart `_helpers.tpl`:359-397] | AKS-E19: eigenes Superuser-Passwort, NetworkPolicies für Postgres und SeaweedFS; `grafana_ro` nur mit expliziten Tabellen; Dumps ohne die Daten beider Tabellen, Zählprüfung je Dump, verschlüsselt, nach der Messe gelöscht; keine Snapshots; der Zugriff der Contributor-Gruppe steht in der eigenen Zeile oben |
| GEBIT-Freigabe (vom Owner am 17.11. berichtet) deckt das Descriptor-Set als K8s-Secret in Azure oder die öffentliche Reflection nicht ab; die Reflection gibt die GEBIT-Descriptor-Dateien selbst heraus; technisch kommt jedes Mitglied der Contributor-Gruppe von `azure-se` an das Secret [A] | Status offen, harte Vorbedingung: Owner bestätigt beides schriftlich bis 27.11., spätestens 09.12. (vor `gebitsim` in P2 Schritt 7, G0-11b (3) am 11.12.), und die Bestätigung deckt den Zugriffskreis der Contributor-Gruppe (Frage 27); ohne Bestätigung kein GEBIT-Material in Azure, G0-11b (3) mit einem Testserver ohne GEBIT-Material (dokumentierte Abweichung von PLAN 7.1) oder nach G2b, `install.sh k8s` auf AKS ohne Descriptor-Secret, Demo nur im Lab oder in L3; ohne Bestätigung nur der Reflection kein `gpos-grpc-reflection`. P1-P5 ohne P2 Schritt 7 mit `gebitsim` und die Lab-Vorarbeit laufen unabhängig. Secret nur zur Laufzeit vom Owner-Mac, nie in Git, Images, ACR, Key Vault oder Backups; das `gebitsim`-Secret in `p2-test` direkt nach dem Test gelöscht; Löschung bis 20.02. protokolliert |
| arm64 als System-Pool auf v6 oder Dpsv6-Kapazität beim Create nicht verfügbar [A]; am 18.11. ist `Standard_D8ps_v6` in den Zonen 1-3 ohne Restriction (ohne ephemeral OS-Disk), und die Quota reicht [Quelle: Befehle `az` read-only, 18.11.] | der Create in P1 ist der Test; Rückfall `Standard_D8ps_v5` (ebenfalls ohne Restriction, DPSv5 0 von 350), sonst amd64 `Standard_D8as_v6` (+1-1,5 PT, `crane` oder `az acr build`) |
| sam CLI mit zwei Targets schreibt auf die falsche Plattform oder zieht die Lab-`.env` | Login je Home unter dem Manifest-Zielnamen `solace-lab`; `SAM_HOME` je Ziel; URL-Guard gegen den Cache; immer `--url` und `--no-dotenv`; nie `--prune`; Spike in P0 |
| Stop/Start: Kapazität beim Start, gwe/awe-Race, Start zu früh nach dem Stop; die API-Server-IP kann wechseln [Quelle: `learn.microsoft.com/azure/aks/start-stop-cluster`] | kubectl nutzt den FQDN des API-Servers, ein IP-Wechsel braucht keinen Abgleich; Ingress- und Egress-IP bleiben, solange der Cluster existiert [A: nicht dokumentiert; P1 und P7 protokollieren beide vor und nach jedem Zyklus, `aks-start.sh` vergleicht mit dem Register]; Start frühestens 30 min nach Stop (Sperre im Wrapper, RUNBOOK); Wartelogik und awe-Neustart; Start 60 min vor Bedarf; ab 05.02. kein Stopp |
| Wartung trotz Sperre (reaktive Wartung kann `notAllowedDates` brechen); mit einem Node heißt jedes Node-Image-Update einige Minuten Ausfall [Quelle: `learn.microsoft.com/azure/aks/planned-maintenance`] | Refresh Di 26.01. mit gemessener Ausfallzeit, Sperre ab 27.01.; kein PDB, das den Drain blockiert; L3 warm; Preflight nach jedem Wartungsereignis |
| Datenverlust im Cluster (gebündelte Persistenz, Neuaufbau löscht PVCs, Namespace-Löschung löscht die Demo-DB) | Inhalte per Skript und deterministischem Seed reproduzierbar; Demo-DB im eigenen Namespace `gpos-data`; `pg_dump` vor G3 und nach jedem Messetag vor dem Day-Reset, inklusive gpos-DB; Restore-Test; Export vor jeder Löschung (P7 Schritt 8) |
| Zeitplan: 13,5 PT bis G2a neben der TR5/TR3-Laborarbeit, das Lab-Broker-Upgrade (P4 Teil A) schon in KW48/49, dann Feiertage; KW1-2 für C überbucht (Abschnitt 6); AKS-E18 und AKS-E20 ohne Owner-Bestätigung | O9 als Weiche am 20.11.; Last von C in KW48/49 vorgezogen; Prüfpunkte 04.12. und 11.12. mit Rückfall "G2a-AKS-Abnahme nach G2b"; Umverteilung in KW1-2 mit dem PLAN-Eigner |
| Messebetrieb hängt an Konto und Mac des Owners; AKS-E20 ist ohne Owner-Bestätigung. Eine eigene, eingeschränkte Azure-Rolle für den Stellvertreter gibt es ohne Rollenzuweisung nicht: Ohne Contributor über eine Gruppe kann er weder `aks-allow-me.sh` noch `az aks start/stop` noch `az aks command invoke` nutzen; mit Contributor darf er auch stoppen und löschen | Owner klärt bis 27.11. Gruppe und Tenant-Status (Frage 24); sonst gibt der Owner ihm die User-kubeconfig (ohne Geheimnis [A: Test vor G3 mit einem Konto ohne Subscription-Zugriff, P7 Schritt 7]); er meldet sich mit `az login --tenant <tenant> --allow-no-subscriptions` an (ein einfaches `az login` bricht ohne Subscription mit "No subscriptions found" ab) oder konvertiert die kubeconfig mit `kubelogin convert-kubeconfig -l interactive`; der Owner trägt seine IP per `aks-allow-me.sh --add` ein, Start/Stop und Break-glass bleiben beim Owner; ab 05.02. läuft der Cluster 24/7, ein Start ist an Messetagen nicht nötig; mit Contributor sind stop und delete ein Runbook-Verbot, die Alarme zeigen Verstöße; eigener Keycloak-User, ClusterRoleBinding und Key-Vault-Policy, Runbook-Durchlauf bis G3; wird bis G3 niemand benannt: L3 warm, L4 über `/op`, Preflight vor Standöffnung durch den Owner |
| Geteilte Subscription ändert sich während des Projekts: neue Policies, eingeschaltete Defender-Pläne, andere Projekte belegen regionale vCPU (am 18.11. 200 von 350); ASC Default (Audit) meldet den Key Vault im Access-Policy-Modus vermutlich als Abweichung [A] | Stand 18.11.: alle relevanten Defender-Pläne Free, also 0 EUR (3.4); Re-Check von Defender-Plänen, Policy-Zuweisungen und Quota (`az vm list-usage`) vor dem Create, vor dem Refresh am 26.01. und vor G4 [A]; ASC-Hinweis im README vermerken (kosmetisch) |
| gpd-Umbau ohne Rückweg | Baseline = sda-Commit vor dem Umbau, Commit je Schritt, Rückweg in KW48 geprobt (P0 Schritt 9) |
| Kosten laufen weiter (vergessener Nachtstopp, nach der Messe); LLM-Kosten sieht das Azure-Budget nicht | Monatsbudget 250 EUR (3.4) auf Subscription-Ebene mit Filter auf `gebit-showcase` und `gebit-showcase-nodes` (Contributor darf eigene Budgets anlegen [Quelle: `learn.microsoft.com/azure/cost-management-billing/costs/tutorial-acm-create-budgets`]), Forecast bis 31.03.; Annahme, dass `gebit-showcase` nur Showcase-Ressourcen hält [A]; Abend-Check; Activity-Log-Alarm nur als Information; `deleteAfter`-Tag; datierter Rückbau-Schritt mit Key-Vault-Purge in P7; LLM-Limits am Messe-Key beim Betreiber |

## 8. Abgleich mit dem früheren AKS-Konzept

Bezug: PLAN 5.2/5.3 [Quelle: PLAN 5.2, 5.3], RA vom 10.11.2026
[Quelle: RA:29-71, RA:552-573], DESIGN 4.8 [Quelle: gpd DESIGN.md:794].

### 8.1 Was bleibt

- Germany West Central, Kubernetes 1.36, Azure CNI Overlay mit
  Cilium, ACR als einzige Registry des Clusters.
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
| Rechte | implizit vorausgesetzt (AcrPull für den Cluster, Workload Identity mit DNS-Rechten) | nur Contributor auf `azure-se` über eine Gruppe; keine Rollenzuweisung, kein Lock, keine Policy-Ausnahme | geprüft 18.11.: Der Owner hat weder Owner noch User Access Administrator; Owner-Entscheidung 18.11. |
| Struktur | eine RG, Skripte in `gpd/infra/aks` [Quelle: PLAN 4]; AKS-Plan 17.11.: drei RGs, BYO-VNet, UAMI | RG `gebit-showcase` (vom Owner angelegt, westeurope; Cluster, ACR und Key Vault in Germany West Central) und Node-RG `gebit-showcase-nodes` (von AKS, Pflicht-Tags per `--tags`); AKS-verwaltetes VNet, System-Identität; versioniert in sli/emd | BYO-Netz und UAMI bräuchten Rollenzuweisungen; Tag-Pflicht der Subscription; Neuaufbau behält ACR, Token und Key Vault, nicht IPs und Label; fester Name der Node-RG für den Budget-Filter |
| Image-Pull | ACR an den Cluster gebunden, kein Pull-Secret [Quelle: PLAN 5.2] | Pull-Token `aks-pull` (nur Pull, mit Ablauf), Secret `acr-pull` je Namespace, Chart-Werte und Patches | `--attach-acr` braucht eine Rollenzuweisung und bricht ohne Owner-Recht erst nach dem Cluster-PUT ab [Quelle: azure-cli dev acs/_roleassignments.py:101-140] |
| Cluster-Zugriff | AKS-Plan 17.11.: Entra ID mit Azure RBAC | Entra ID mit Kubernetes RBAC: Bootstrap mit Admin-Zertifikat, ClusterRoleBindings auf den UPN, dann lokale Accounts aus | Azure RBAC für Kubernetes braucht Rollenzuweisungen |
| Secrets | AKS-Plan 17.11.: Key Vault im RBAC-Modus | Key Vault im Access-Policy-Modus, Policies für Owner und Stellvertreter | eine Datenrolle bräuchte eine Rollenzuweisung |
| Egress | AKS-Plan 16./17.11.: statische `pip-aks-egress` | AKS-verwaltete Outbound-IP, nach dem Create gemeldet | eine BYO-IP bräuchte Rechte der Cluster-Identität; neu bei jedem Neuaufbau |
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
| Kosten | rund 860 EUR/Monat [Quelle: RA:499] | rund 300-340 EUR/Monat bei 24/7; Defender Free (18.11.) | ein Node, Free-Tier, kein PG Flexible, kein WireGuard |

### 8.3 Korrekturen an Befunden

- Keycloak: aktuell ist 26.8.2 (05.11.2026), nicht 26.7.0 [Quelle:
  GitHub-Releases-API].
- "Läuft auf dem arm64-Lab-Node" belegt nur arm64, nicht multi-arch.
- PLAN 6.2 erlaubt keine Abnahme "Plattform plus Tunnel", sondern
  verschiebt die G2a-AKS-Abnahme in Variante (b) nach G2b.
- Quota muss den Surge-Node einrechnen (16 statt 8 vCPU bei einem
  Node); am 18.11. reicht sie ohne Antrag (3.5).
- SAM-Broker-Passwort heißt `broker.password`, nicht `clientPassword`.
- Der Lab-SAM-Ingress hat keine `proxy-body-size` (NGINX-Default 1m);
  unter Traefik wirkt ein Limit nur mit `proxy-request-buffering:
  "on"`.
- `az aks check-acr` taugt auf einem reinen arm64-Cluster nicht
  (Prüf-Image nur amd64) und prüft ohnehin die Kubelet-Identität, die
  hier kein AcrPull hat; P1 prüft das Secret `acr-pull` und einen
  echten arm64-Pull.
- Ein Budget nur auf `gebit-showcase` sähe die Node-Kosten nicht
  (höchstens rund 38 von 300-340 EUR); dafür steht die feste Node-RG
  `gebit-showcase-nodes` im Filter.
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
- Neu am 18.11.: `--attach-acr` ohne Owner-Recht scheitert nicht vor
  dem Create. Die CLI legt den Cluster an, versucht die
  AcrPull-Zuweisung danach rund 110 s lang und endet mit "Could not
  create a role assignment for ACR" und einem Exit-Code ungleich 0;
  der Cluster bleibt ohne AcrPull [Quelle: azure-cli dev
  acs/_roleassignments.py:101-140; acs/managed_cluster_decorator.py:9204-9222;
  `learn.microsoft.com/azure/aks/cluster-container-registry-integration`].
- Neu am 18.11.: `--vnet-subnet-id` ohne Rollenrecht gibt nur eine
  Warnung aus; der Create läuft durch, die Identität hat dann keine
  Subnetzrechte [Quelle: azure-cli dev
  acs/managed_cluster_decorator.py:7513-7627, 9085-9122].
- Neu am 18.11.: Der Plan vom 17.11. wäre an der Tag-Pflicht
  gescheitert: `az group create rg-eurocis-base` trug nur `purpose`
  und `deleteAfter`, und `az group update -n rg-eurocis-nodes --tags`
  ersetzt das ganze Tag-Set. `--tags` beim Create taggt auch die
  Node-RG; der Hinweis auf `--nodepool-tags` aus einem FastTrack-Blog
  von 2022/2023 ist überholt [Quelle:
  `learn.microsoft.com/azure/aks/use-tags`].
- Neu am 18.11.: Kubernetes-RBAC-Bindungen nennen für Nutzer desselben
  Tenants den UPN, nicht die objectId; nur Nutzer anderer Tenants und
  Gruppen gehen per objectId [Quelle:
  `learn.microsoft.com/azure/aks/kubernetes-rbac-entra-id`].
- Neu am 18.11.: `az aks command invoke` ist kein Weg am RBAC vorbei;
  es reicht das Entra-Token des Aufrufers weiter. Break-glass bei
  einem RBAC-Lockout ist `--enable-local-accounts` [Quelle: azure-cli
  2.85.0 acs/custom.py:2620-2626].
- Neu am 18.11.: Defender ist nicht "bedingt", sondern in allen
  relevanten Plänen Free; nur Discovery und Foundational CSPM laufen
  als Standard, ohne Kostenwirkung hier [Quelle: Befehle `az`
  read-only, 18.11.].
- Neu am 18.11.: Key Vault macht ab API 2026-02-01 RBAC zum Default
  für neue Vaults; Access Policies bleiben unterstützt, brauchen dann
  aber `enableRbacAuthorization=false` ausdrücklich. Azure CLI 2.85.0
  nutzt noch API 2025-05-01; alle Versionen vor 2026-02-01 enden am
  27.02.2027 [Quelle:
  `learn.microsoft.com/azure/key-vault/general/access-control-default`].
- Neu am 18.11.: Im ACR-Modus "RBAC Registry + ABAC Repository
  Permissions" hat Contributor keine Daten-Ebene, und Learn kündigt
  ihn als künftigen Default an; deshalb `--role-assignment-mode rbac`
  ausdrücklich [Quelle:
  `learn.microsoft.com/azure/container-registry/container-registry-rbac-abac-repository-permissions`].
- Neu am 18.11.: Der Tag-Name `Owner` war nur für AKS-Legacy-Ressourcen
  reserviert; für neue Cluster gilt die Einschränkung nicht [Quelle:
  `learn.microsoft.com/azure/aks/faq`].

### 8.4 Abgleich mit Aufwand, Terminen und Kosten des PLAN

Die AKS-Posten des PLAN gegen die Phasen dieses Plans [Quelle: PLAN 6
(AP12-AP14b), 7.1 (G0-11a/b), 7.3]:

| PLAN-Posten | PT PLAN | Phasen hier | Bemerkung |
|---|---|---|---|
| AP12 S1-S3 (Subscription, Foundation, Add-ons) | 3,5 | P0 (Checks am 18.11. erledigt), P1, P2 | eine Woche später als PLAN 7.3 (KW49/50 statt KW48); O4 erst am 17. und 18.11. geklärt (`azure-se`, RG `gebit-showcase`, nur Contributor), die Azure-Ressourcen entstehen erst in P1 |
| AP12 S4 Broker, S5 Keycloak | 2,0 | P4 Teil B, P3 | P4 Teil B erst nach der Abnahme von Teil A |
| AP12 S6 SAM, darin O6 0,5 | 2,0 | P5 | SAM-Profil hier rund 2,5-3 PT |
| AP12 S7-S8 (Overlay, gRPC-Ingresse, Demo) | 2,0 | P6 | plus Seams, `pg`-Teil, Env-Prüfung, Pfad-Ingresses, `public-guard`, Image 0.1.4 |
| AP12 S9 öffentlicher Zugang, HTTPS-RTT, L3-Kopie | 1,5 | P1 (`aks-allow-me.sh`), P2 (öffentliches LB, VAP), P5 (HTTPS-RTT), P6 (TR1-Besuche) | früher WireGuard; netto rund 1,25 PT weniger [A] |
| AP12 S10 Härtung | 1,5 | P7 | - |
| G0-11a, G0-11b | 1,5 | P1 (Probe), P2 Schritt 7, P5 Schritt 7 | Termine nach AKS-E18 (Owner-Bestätigung offen) |
| AP13 AKS-Anteil (24 h, Neuaufbau) | 2,0 | P7 Schritt 3 | ohne N-1-Drain; Neuaufbau mit Neubindung des Labels und neuer Egress-IP |
| AP14 Betrieb | 3,5 | P7 Schritte 4-7 | Kanarienlauf, Tagesroutine, Exporte und Freeze-Snapshots bleiben PLAN-Posten |
| AP14b L3 | 2,0 | P7 nur der Drill | Aufbau des L3-Profils (Overlay `l3`, SAM-Values `l3`, Export) bleibt PLAN-Posten |
| neu: Sicherheitsgeländer | - | P0 | 2,25 PT (ganz P0, seit 18.11. ohne Azure-Vorab-Anlage) |
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
  Neuposten: Geländer (P0, 2,25 PT),
  SAM-Profil (+2-2,5 PT gegen 0,5 PT O6), Lab-Broker-Upgrade
  (1,0 PT), Traefik (+0,5 PT), Image 0.1.4 (0,5 PT) und der
  Missbrauchsschutz (0,5 PT); der Wegfall von WireGuard spart netto
  rund 1,25 PT. Die Entscheidung vom 18.11. ändert die Summe nicht,
  sie verschiebt nur Arbeit von P0 nach P1 (8.6) [A].
- Variante (a): C hat 32,25 von 39,9 PT netto verplant [Quelle: PLAN
  0.4]; frei sind 7,65 PT. Das Delta von 6,5 PT passt rechnerisch
  hinein, lässt aber nur rund 1,15 PT frei. Nach Abschnitt 6 trägt C
  39,75 PT (38,25 nach der Umverteilung von
  AP11 `/op`) gegen 39,9 PT netto, und KW1-2 braucht die Umverteilung
  aus Abschnitt 6. Variante (b): Das Delta vergrößert die Lücke von
  6,4 bzw. 7,9 PT [Quelle: PLAN 0.4, 6.2]. Das Muss von 118,75 PT
  steigt um das Delta, sofern der Owner die Geländer und das
  Lab-Broker-Upgrade nicht als Teil von AP12 verbucht.
- Termine: G0-11a und G0-11b nach AKS-E18 (Owner-Bestätigung offen);
  die Abhängigkeit "AP12 S6-S10 nach G0-11a" [Quelle: PLAN 6 (AP12),
  6.1] wird phasengerecht umgeschrieben; P0 in KW47 tragen Owner und
  Claude, bevor C am 23.11. beginnt; AP12 S1-S3 rutschen eine Woche
  (O4 erst am 17. und 18.11. geklärt).
- Kosten: Die AKS-Kosten in PLAN 0.4 ("etwa 2,0-3,0 Tsd. €") sinken auf
  rund 460-590 EUR bis zum Rückbau am 20.02.2027; einen
  Defender-Zuschlag gibt es nicht, alle relevanten Pläne sind Free
  [A: Laufmuster 3.4; Quelle: Retail-API 17.11.; Befehle `az`
  read-only, 18.11.]. Ziel unter 1.500 EUR (AKS-E1), Monatsbudget
  250 EUR. Gründe: ein Node, Free-Tier, kein WireGuard,
  gebündelte Persistenz, Nachtstopp bis G4, Cluster erst ab 30.11.
- Am 18.11. im PLAN schon nachgezogen: der 0.2-Nachtrag (beide IPs in
  der Node-RG, ohne Lock und ohne Rollenzuweisung, nur Contributor)
  und der Hinweis auf den Stand vom 11.11. in 0.2 (erweitert um G0b,
  5.3, AP12, Ressourcengruppe, VNet, Identitäten und die Pfade unter
  `infra/aks/`), in 4 der Dateibaum (`infra/aks/` verweist auf
  `sli/aks/`, `amd/aks-values.yaml` und `emd/terraform-aks/`) und die
  Descriptor-Regel (Secret statt ConfigMap), in 5.2
  die Zeilen Images (Pull-Weg), TLS/Name und LiteLLM sowie die
  SAM-Values-Skizze (`imagePullSecrets: ["acr-pull"]`), in 5.3 Nr. 1
  (Verweis auf `sli/aks/foundation.sh pre|post`, ohne RG-, VNet- und
  Identitätsanlage) und Nr. 4 (Descriptor-Secret statt ConfigMap).
- Nach Freigabe im PLAN nachziehen: 0.2 (E7 AKS-Persistenz im Cluster
  statt PG Flexible; E8 mit 1 x D8ps_v6 arm64, Free-Tier, Traefik,
  HTTP-01 mit Azure-DNS-Label, Broker 10.26.0.9219; der Zugang ist dort
  schon nachgezogen; aus dem 18.11. noch RG `gebit-showcase`, Node-RG
  mit Pflicht-Tags, ACR-Token, Kubernetes RBAC und Key Vault mit
  Access Policies), 0.3 (G0b ohne "externe Persistenz" und
  "DSN-TLS"), 0.4 (Kosten), 0.5 (O4 erledigt 17. und
  18.11.: `azure-se`, RG `gebit-showcase`, nur Contributor, Quota
  DPSv6 ohne Antrag, Abbau 20.02.2027, Kostenstelle offen [A]; O4
  Azure-DNS-Label statt delegierter Zone, O6 mit 0,5 PT, AKS-E1 bis
  AKS-E21), 2.1 (Architekturbild ohne PG Flexible und Blob), 5.2
  (Zeilen Cluster, Images bis auf den Pull-Weg, Postgres,
  SAM-Persistenz, Broker und Monitoring sowie der Persistenzteil der
  SAM-Values-Skizze), 6 (AP12-Zeile "SAM extern", PT; AP13 mit
  Neubindung des Labels und neuer Egress-IP), 6.1 (kritischer Pfad,
  O4 erledigt), 6.4, 7.1 (G0-11a/b), 7.2, 7.3, 8.6 (Neuaufbau
  höchstens 4 h inklusive Label und Egress-IP) und R5 (externe
  Persistenz, ingress-nginx; Subscription-Richtlinien am 18.11.
  geprüft); neues Risiko für das Label ohne Lock und den Zugriff der
  Contributor-Gruppe; in 5.2 außerdem das SAM-Body-Limit 10m statt
  100m mit `limit-connections` (P5 Schritt 2).

### 8.5 Änderungen durch die Owner-Entscheidungen vom 17.11.2026

Gegenüber dem Stand vom 16.11. (Commit `7a860c5`); PT als Aufwand von
C, EUR je Monat bei 24/7 [Quelle: Retail-API 17.11.]. Was die Prüfung
und die Entscheidung vom 18.11. daran ändern, steht in 8.6.

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
  460-590 statt 900-1.200 EUR (die Fassung vom 17.11. nannte 470-600
  bei 8 EUR im November; die Monatswerte ergeben 463-593, seit 18.11.
  461-591). Der damals genannte Zusatz "mit aktivem
  Defender for Containers rund 520-660 EUR" ist seit dem 18.11.
  gegenstandslos (8.6) [A: Laufmuster 3.4].
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

### 8.6 Änderungen durch die Prüfung und Owner-Entscheidung vom 18.11.2026

Gegenüber dem Stand vom 17.11. (sda-Commit `9f66efd`). Prüfung:
read-only mit Azure CLI 2.85.0 nach dem `az login` des Owners.
Entscheidung des Owners: keine Rollenzuweisungen, alles mit
Contributor. PT als Aufwand von C (die P0-Anteile in KW47 tragen
Owner und Claude), EUR je Monat bei 24/7 [Quelle: Retail-API 17.11.;
Befehle `az` read-only, 18.11.]:

| Nr | Thema | Stand 17.11. | Stand 18.11. | PT | EUR/Monat 24/7 |
|---|---|---|---|---|---|
| 1 | Rechte | P0 prüft die Rechte; der Plan setzt Rollenzuweisungen und einen Lock voraus | Owner ist Contributor auf `azure-se` über eine Gruppe, weder Owner noch User Access Administrator; keine Rollenzuweisung, kein Lock, keine Policy-Ausnahme | 0 | 0 |
| 2 | Subscription, Policies | Default nach `az login`, Policies ungeprüft | `azure-se` (einzige, Default); Tag-Pflicht für `Owner` und `Created Date` auf RGs (deny), Vererbung beider Tags (modify), ASC Default (audit); Provider registriert, `Microsoft.Quota` nicht nötig | 0 | 0 |
| 3 | Ressourcengruppen, Netz, Identität | `rg-eurocis-base`, `rg-eurocis-aks`, `rg-eurocis-nodes`; `vnet-eurocis` mit `snet-aks`; UAMI `id-aks-cp` mit Network Contributor | `gebit-showcase` (Owner, westeurope, Ressourcen in Germany West Central) und `gebit-showcase-nodes` (von AKS, `--tags` mit allen vier Tags); AKS-verwaltetes VNet in der Node-RG, System-Identität | P0 -0,25 (RG, IPs, Lock entfallen), P1 -0,25 (VNet, UAMI, Rolle entfallen) [A] | 0 |
| 4 | Ingress-IP | `pip-aks-ingress` ab 20.11. in `rg-eurocis-base`, Lock `CanNotDelete`, Network Contributor | in `gebit-showcase-nodes` direkt nach dem Create, ohne Lock und ohne Rolle; ein Cluster-Delete gibt IP und Label frei | 0 (in P1 enthalten) | 0; Projekt rund -2 (keine IP im November) |
| 5 | Egress | statische `pip-aks-egress` ab 20.11., Adresse an den Betreiber bis 25.11. | AKS-verwaltete Outbound-IP, Adresse erst nach dem Create, neu bei jedem Neuaufbau | 0 | 0 (weiter eine Standard-IP) |
| 6 | Image-Pull | `--attach-acr` (AcrPull der Kubelet-Identität) | Pull-Token `aks-pull` (nur Pull, Ablauf), `acr-pull.sh`, Secret je Namespace, Chart-Werte und Patches | P1 +0,25; P2-P6 ohne eigene PT [A] | 0 |
| 7 | Cluster-Zugriff | Entra ID mit Azure RBAC, Rolle "Azure Kubernetes Service RBAC Cluster Admin" | Entra ID mit Kubernetes RBAC, `bootstrap-rbac.sh`, lokale Accounts aus, `rotate-certs` nach Frage 28 | P1 +0,25 [A] | 0 |
| 8 | Key Vault | RBAC-Modus, "Key Vault Secrets Officer", Warteschleife | Access-Policy-Modus, `set-policy` für Owner und Stellvertreter | 0 | 0 |
| 9 | Quota, SKU | Antrag am 20.11., falls eine Lücke besteht | geprüft: DPSv6 0 von 350, DPSv5 0 von 350, Total Regional 200 von 350, Public IPs 7 von 1000, Standard-LBs 0 von 1000; `Standard_D8ps_v6` Arm64 in den Zonen 1-3 ohne Restriction; kein Antrag, nur Re-Checks | in Nr. 3 enthalten | 0 |
| 10 | Defender | bedingt +49,1 (Containers), Servers [A] | alle relevanten Pläne Free; Discovery und Foundational CSPM ohne Kostenwirkung | 0 | bedingte +49,1 entfallen |
| 11 | AKS-Version | 1.36.x | 1.36 ist Default in Germany West Central, Patch 1.36.5 (daneben 1.37.1 und 1.35.9) | 0 | 0 |
| 12 | Stellvertreter | eigene Rolle mit `managedClusters/write`, dazu Join- und Assign-Rechte | Contributor über eine Gruppe (offen, Frage 24) oder nur kubectl; ClusterRoleBinding und Key-Vault-Policy | P7 -0,25 [A] | 0 |
| 13 | Neuaufbau | IPs und Label bleiben (Lock) | `az aks delete`; Label sofort neu binden, Bootstrap erneut, neue Egress-IP an den Betreiber | P7 +0,25 [A] | 0 |
| 14 | Budget, Alarme | Budget auf drei RGs | Budget auf Subscription-Ebene mit Filter auf zwei RGs (Contributor reicht); Activity-Log-Alarme (`alerts.sh`) | 0 [A] | 0 [A: Activity-Log-Alarme ohne Gebühr] |
| | **Summe** | 23,5 PT; rund 300-340 EUR/Monat | 23,5 PT; rund 300-340 EUR/Monat | netto 0 [A] | 0; Projekt rund -2 |

- Je Phase gegenüber dem 17.11.: P0 -0,25 (Anteil von Owner und
  Claude in KW47), P1 +0,25, P7 0 (-0,25 und +0,25), P2 bis P6 0
  [A]. Für C heißt das +0,25 PT in KW49 (Abschnitt 6).
- Kosten: 24/7 unverändert rund 300-340 EUR/Monat, im Aufbau rund
  145-185 EUR/Monat. Projektsumme rund 460-590 EUR (November rund 6
  statt 8 EUR, Summe der Monate 461-591 EUR); der Zusatz "mit
  Defender" entfällt (3.4).
- Entfallen: `rg-eurocis-base`, `rg-eurocis-aks`, `rg-eurocis-nodes`,
  `vnet-eurocis` und `snet-aks`, die UAMI `id-aks-cp` mit Network
  Contributor, `pip-aks-egress`, der Lock `CanNotDelete`,
  `--attach-acr` mit AcrPull, Azure RBAC für Kubernetes samt Rolle
  "Azure Kubernetes Service RBAC Cluster Admin", "Key Vault Secrets
  Officer" mit Warteschleife, die eigene Rolle des Stellvertreters
  mit Join- und Assign-Rechten, der Quota-Antrag und die
  Defender-Kostenzeilen.
- Neu: `aks_tags`, `aks_update` und der Admin-kubeconfig-Guard in
  `sli/aks/lib.sh`, `foundation.sh pre|post`, `bootstrap-rbac.sh`,
  `acr-pull.sh`, `alerts.sh`, Pull-Token `aks-pull` mit
  `acr-pull-token` im Key Vault, Secret `acr-pull` je Namespace samt
  Chart-Werten und Patches, Pflicht-Tags beim Create,
  `pip-aks-ingress` nach dem Create, Meldung der Egress-IP nach dem
  Create, lokales IP-Register, Wiederholung bei
  RequestDisallowedByPolicy; aus dem Review vom 18.11. ohne eigene PT
  [A]: `aks-rebuild.sh` als einziger Weg zu `az aks delete`,
  Zugriffs- und Löschalarme schon vor dem Create (auch für Key Vault,
  ACR, Vault-Purge, `generateCredentials` und beide RGs),
  Admin-kubeconfig nur im per `trap` gelöschten Temp-Verzeichnis,
  geprüfter Nachweis vor `rotate-certs`, xtrace nur unter
  `~/.config/eurocis-aks/xtrace/`, `az login
  --allow-no-subscriptions` für einen Stellvertreter ohne
  Subscription.
- Owner-Optionen ohne Rollenzuweisung: NRG-Lockdown `ReadOnly` nach P2
  (Frage 29), Label-Scope `SubscriptionReuse` (Frage 7),
  `rotate-certs` oder eine eigene Entra-Gruppe für den Bootstrap
  (Frage 28).
- Verworfen, weil jede Variante eine Rollenzuweisung, einen Lock oder
  eine Ausnahme braucht: BYO-VNet und -Subnetz (Network Contributor
  für die Cluster-Identität; die CLI warnt nur, und der Cluster hätte
  keine Subnetzrechte), `--attach-acr`, Azure RBAC für Kubernetes,
  Key-Vault-Datenrolle im RBAC-Modus, BYO-Egress-IP außerhalb der
  Node-RG, Lock auf `pip-aks-ingress` und eine Policy-Ausnahme für
  die Node-RG.
- Unverändert: ein Node `Standard_D8ps_v6` arm64, Free-Tier, Traefik
  v3.7.19, Let's Encrypt HTTP-01 mit EAB-Rückfall, ein Name mit
  Pfad-Routing, gebündelte SAM-Persistenz, Broker 10.26.0.9219 LTS,
  Rate-Limits und LiteLLM-Key-Limits, gRPC öffentlich mit Reflection,
  P0-Geländer, `kaks`/`haks`, Wartungssperre, Nachtstopp bis G4 und
  L3 aus dem Lab.

## 9. Offene Fragen

1. AKS-E18 (Owner-Bestätigung offen): G0-11a nach G2a (18.12., P5),
   HITL-Teil von G0-11b nach P5, gRPC-Teil am 11.12.?
2. AKS-E20 (Owner-Bestätigung offen): Wer sind Betreiber und
   Stellvertreter an Probetagen und Messe? Vorschlag: C Betreiber,
   Entwickler A Stellvertreter (bei O9 = (b): A Betreiber, Owner
   Stellvertreter). Ihre Azure-Rechte klärt Frage 24.
3. O9: Gibt es ab 23.11. eine dritte Person für den AKS-Track, oder
   läuft er neben TR5/TR3 (Stichtag 20.11.)?
4. GEBIT (AKS-E16, Status offen, harte Vorbedingung): Deckt die am
   17.11. berichtete Freigabe das Descriptor-Set als K8s-Secret in
   Azure Germany West Central, den Zugriff des Stellvertreters und die
   öffentliche Reflection, die die GEBIT-Descriptor-Dateien selbst an
   jeden ausliefert [A: ja als Planungsannahme]? Deckt sie auch, dass
   jedes Mitglied der Contributor-Gruppe von `azure-se` technisch an
   das Secret kommt (Frage 27)? Schriftlich bis 27.11.,
   spätestens 09.12. (vor `gebitsim` in P2 Schritt 7, G0-11b (3) am
   11.12.); sonst G0-11b (3) mit einem Testserver ohne GEBIT-Material
   als dokumentierte Abweichung von PLAN 7.1 oder nach G2b, und kein
   GEBIT-Material in Azure. Wann kommen die Netzparameter des Stands
   (Uplink, 5G; fällig 18.12. [Quelle: PLAN 6.5])?
5. LiteLLM: Gibt es eine Quell-IP-Allowlist (auch für `/v1/*`)? Kommt
   der Messe-Key (O5) mit `max_budget` 150 USD, und welche
   `rpm_limit`- und `tpm_limit`-Werte setzt der Betreiber? Zum
   Zeitpunkt der Egress-IP siehe Frage 26.
6. Subscription `azure-se` (am 18.11. geprüft; Rollenrechte, Quota,
   Defender und Tag-Pflicht sind beantwortet, 8.6): Nutzen die
   Policy-Zuweisungen die Built-in-Definitionen "Require a tag on
   resource groups" und "Inherit a tag from the resource group"
   (read-only: `az policy assignment list --query
   "[].{n:displayName,d:policyDefinitionId}"`)? Ist Cost Management
   mit Budgets für den Angebotstyp verfügbar (`az consumption budget
   list` oder Portal)? Built-in oder Custom zeigt schon das Präfix der
   `policyDefinitionId` (P0 Schritt 2); liegt eine Custom-Definition
   auf Management-Group-Ebene, kann der Owner sie als Contributor
   nicht lesen: Wie lauten dann ihre Regel und ihr Effekt (Frage an
   den Subscription-Owner)? Wie kurz ist die Anmeldehäufigkeit per
   Conditional Access (Frage an die IT)? Wer kann eine
   Policy-Ausnahme für `gebit-showcase-nodes` anlegen, falls Updates
   an der Tag-Pflicht scheitern (Azure/AKS #5856)?
7. Welches neutrale Präfix `<p>` bekommt das DNS-Label (CT-Logs sind
   öffentlich)? Die Verfügbarkeit in Germany West Central prüft P0 und
   erneut direkt vor dem Create; die IP entsteht erst in P1, bis
   dahin kann ein Fremder das Label belegen. Domain Name Label Scope
   `SubscriptionReuse` (Preview ohne SLA, FQDN mit Hash-Anteil, bei
   jedem Neuaufbau in `azure-se` dasselbe FQDN, nur beim ersten
   Anlegen setzbar) ja oder nein?
8. ACME-Rückfall: ZeroSSL oder Google Trust Services, und legt der
   Owner das EAB-Konto bis zum Prüfpunkt 04.12. an?
9. API-Server: authorized IP ranges mit `aks-allow-me.sh` (Vorschlag)
   oder nur Entra ID mit Conditional Access? Darf `aks-allow-me.sh`
   im Freeze laufen?
10. Traefik im Freeze: Ausnahme nur für Patch-Releases mit
    Smoke-Wiederholung?
11. Lab-Broker-Upgrade (P4 Teil A): Wann gibt der Owner das Go, und
    wann liegt das Wartungsfenster für solace-1 (Vorschlag: Probe an
    solace-2 in KW48, solace-1 bis 04.12. (Prüfpunkt), spätestens
    10.12.)? Das Fenster trifft
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
    abgerechnet, und laufen LB-Regeln und IPs im Stopp weiter? Bleiben
    die AKS-verwaltete Egress-IP und `pip-aks-ingress` über Stop/Start
    und den Node-Image-Refresh gleich (Messung in P1, P7 und am
    26.01.)?
16. developer-mcp auf AKS bereitstellen? UC1 braucht ihn nicht, der
    Endpunkt wäre öffentlich (per OIDC geschützt).
17. L3 (AP14b) behalten? Streichliste Nr. 4 würde 3 PT sparen
    [Quelle: PLAN 6.2], nimmt aber den Notbetrieb.
18. Nach der Messe: Rückbau (mit Key-Vault-Purge) oder GEBIT-Übergabe
    (dann amd64-Pool und Multi-Arch-Build)? Wird `gebit-showcase`
    danach gelöscht, oder behält der Owner die RG? Der Rückbau läuft
    mit Azure CLI 2.93 oder neuer, weil die Key-Vault-API von 2.85.0
    am 27.02.2027 endet.
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
24. Stellvertreter (AKS-E20, bis 27.11.): Ist er über eine Gruppe
    Contributor auf `azure-se` (oder hat er eine Rolle mit
    `listClusterUserCredential`, `runCommand/action` und
    `managedClusters/write`)? Ist er Mitglied oder Gast im Tenant, also
    Bindung per UPN oder per objectId? Ohne Azure-Recht bekommt er vom
    Owner die User-kubeconfig (ohne Geheimnis [A: Test vor G3 mit
    einem Konto ohne Subscription-Zugriff, P7 Schritt 7]) und meldet
    sich mit `az login --tenant <tenant> --allow-no-subscriptions` an
    (ein einfaches `az login` endet ohne Subscription mit "No
    subscriptions found") oder konvertiert sie mit `kubelogin
    convert-kubeconfig -l interactive`; seine IP trägt der Owner per
    `aks-allow-me.sh --add` ein, und `az aks
    start/stop`, `aks-allow-me.sh` und `az aks command invoke` bleiben
    beim Owner. Eine Zuweisung könnte nur ein Subscription-Owner
    vornehmen.
25. Entschieden 18.11. (Owner): `Owner` ist immer der Owner selbst,
    `Created Date` im Format dd.mm.yyyy; beide Werte übernimmt
    `aks_tags` aus `gebit-showcase` (Rückfall `OWNER_TAG` aus
    `.env.aks`). Die Werte stehen nie im Repo.
26. LiteLLM-Allowlist nach dem Create: Reicht die Vorankündigung am
    20.11. ohne IP, und schaltet der Betreiber die IP binnen eines
    Arbeitstags nach der Meldung frei (Create am 30.11. oder 01.12.,
    Probe am 03.12.)? Welche Vorlaufzeit braucht er bei einem
    Neuaufbau (Drill in KW3, Probetage, Messe), und zählt die
    Wartezeit in die 4 h aus G3?
27. Contributor-Gleichrang: Jedes Mitglied der Contributor-Gruppe von
    `azure-se` kann lokale Accounts einschalten und Admin-Credentials
    holen, sich eine Key-Vault-Policy setzen und ACR-Tokens anlegen,
    also an Secrets, das GEBIT-Descriptor-Secret und den LiteLLM-Key
    kommen. Akzeptiert der Owner das, wer gehört zur Gruppe, und deckt
    es die GEBIT-Freigabe (Frage 4)? Die Activity-Log-Alarme melden
    solche Aktionen nur.
28. Bootstrap ohne Restzertifikat: `az aks rotate-certs` nach dem
    Bootstrap (bis 30 min Ausfall, nur vor dem ersten Workload
    sinnvoll, beim Neuaufbau erneut), eine eigene Entra-Sicherheitsgruppe
    für `--aad-admin-group-object-ids` (geht nur, wenn der Tenant
    Nutzern das Anlegen erlaubt; die Contributor-Gruppe kommt dafür
    nicht in Frage) oder das Admin-Zertifikat bewusst hinnehmen?
29. NRG-Lockdown `ReadOnly` nach dem LB-Nachweis in P2 (P2 Schritt 10)
    als Ersatz für den Lock: ja oder nein? Er verhindert, dass Nutzer
    `pip-aks-ingress` löschen oder ändern, nicht aber `az aks delete`;
    für Änderungen an der IP muss er kurz auf `Unrestricted`.
30. ACR-Token: System-Scope-Map `_repositories_pull` (alle Repos,
    keine Pflege) oder eine eigene Scope-Map mit Repo-Liste? Ablauf
    des Passworts 2027-02-28T23:59:59Z (gleich `deleteAfter`) und
    Rotation über `password2`?
31. G3-Kriterium "Ingress-IP unverändert" (P7-Abnahme der Fassung vom
    17.11., sda-Commit 9f66efd; im PLAN steht es nicht): Ohne
    Lock und mit der IP in der Node-RG ist es nach einem Neuaufbau
    nicht erreichbar. Gilt künftig "`<fqdn>` unverändert, Label neu
    gebunden, neue Egress-IP gemeldet"? Die Move-Variante (IP vor dem
    Delete per `az resource move` nach `gebit-showcase`, danach
    zurück) ist ungeprüft [A].
