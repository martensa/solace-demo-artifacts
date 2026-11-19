# AKS-Aufbau: EuroCIS-Showcase (Runbook)

Stand 19.11.2026. Dieses Runbook baut den Messe-Stack der GEBIT-Demo (SAM,
Keycloak, Broker, gpos-Demo, Monitoring) auf AKS auf und regelt Betrieb und
Rückbau bis nach der EuroCIS (16.-18.02.2027); es ist die einzige Quelle für
AKS. Die lange Fassung bleibt in git (20a6316, davor 9f66efd, 7a860c5).
Abschnitt 1 einmal, Abschnitt 2 der Reihe nach: erst weiter, wenn die Prüfung
grün ist.

## 0. Zielbild auf einen Blick

Der Owner baut und betreibt allein, Claude bereitet Dateien vor und prüft; die
GEBIT-Stellvertretung hat kein Azure und nutzt nur die öffentlichen UIs.

### 0.1 Bausteine

| Baustein | AKS-Lösung |
|---|---|
| Azure | Subscription `azure-se`; Owner nur Contributor: keine Rollenzuweisung, kein Lock |
| Ressourcengruppen | genau zwei: `gebit-showcase` (vorhanden; Cluster, ACR, Key Vault) und die Node-RG `gebit-showcase-nodes`, die AKS anlegt; Pflicht-Tags `Owner` und `Created Date` (dd.mm.yyyy) über `az aks create --tags`, Werte aus `gebit-showcase` |
| Region | `germanywestcentral` für alle Ressourcen (RG-Metadaten westeurope); Quota reicht |
| Cluster | `aks-eurocis`: 1 Node `Standard_D8ps_v6` (arm64), Kubernetes 1.36.5, Free-Tier, kein HA |
| Netz | AKS-verwaltetes VNet, Azure CNI Overlay mit Cilium, AKS-verwaltete Egress-IP (neu nach jedem Neuaufbau) |
| Zugang | Admin-kubeconfig `~/.kube/aks-eurocis.yaml` (600, nie in `~/.kube/config`), Kontext `aks-eurocis-admin`; lokale Accounts an; API-Server aus allen Netzen |
| Entra | nicht integriert: Für einen Betreiber reicht das Admin-Zertifikat, Entra brächte kubelogin und Bindings ohne Nutzen |
| Updates, Laufzeit | Auto-Upgrade `none`, Node-OS `SecurityPatch` Mi 08:00-12:00; Sperre 20.01. und 27.01.-20.02.2027; Nachtstopp bis 04.02., ab 05.02. 24/7 |
| Name | Standard-IP `pip-aks-ingress` (statisch, Node-RG) mit DNS-Label `eurocis-showcase`; Traefik bindet sie per `azure-pip-name` |
| TLS | cert-manager v1.21.3, Let's Encrypt HTTP-01 (erst staging, dann prod), ein Zertifikat als Traefik-Default; Backup im Key Vault; Rückfall ZeroSSL |
| Ingress | Traefik v3.7.19 (Chart 42.4.1, Image per Digest) mit ingress-nginx-Provider, IngressClass `nginx`; einziger LoadBalancer-Service |
| Images | privat (SAM-Offline-Images, gpos-demo) in ACR Basic, Pull per Token `aks-pull`; öffentlich direkt upstream per Digest (1.7) |
| Secrets | Key Vault (Access Policies): generierte Passwörter, ACR-Token, TLS-Backup; der LiteLLM-Key (Lab-Key) nur in SAM |
| Monitoring | kube-prometheus-stack 83.5.0, Loki 6.55.0, Tempo 2.0.0, Alloy 1.11.0 wie im Lab; Prometheus auf PVC; nur Port-Forward |
| Keycloak | 26.8.2 mit Postgres im Cluster (Namespace `iam`), Realm `solace-lab` mit den Lab-Usern, unter `/auth` |
| Broker | PubSub+ Standard 10.26.0.9219 (Chart 3.10.0, `prod1k`), nur ClusterIP, VPNs `default` und `sam`; der Lab-Broker bleibt 10.25.0.208 |
| SAM | 2.542.1 (Chart 2.3.10, str 1.80.2), gebündelte Persistenz (Postgres, SeaweedFS 2 CPU/2Gi), eigenes PG-Superuser-Passwort, NetworkPolicy |
| GEBIT-Demo | gpos-demo 0.1.3, ab G2b 0.1.4; Overlay `aks`; Demo-DB Postgres 18 in `gpos-data`; Descriptor-Set nur als Secret aus `~/Downloads/Gebit` (GEBIT hat Azure und öffentliche Reflection freigegeben) |
| Nicht auf AKS | Kyverno, ValidatingAdmissionPolicy, trust-manager, Lab-CA, Entra, Budget, Defender (Free) |

### 0.2 Pfade auf dem einen Namen

Alle Apps teilen
`https://eurocis-showcase.germanywestcentral.cloudapp.azure.com` (in Befehlen
`$FQDN`); der längste Pfad gewinnt. gRPC läuft auf 443 mit
`backend-protocol: GRPC`, 3600 s Timeout; öffentlich sind alle drei Dienste
mit allen RPCs, auch den anonymen Schreib-RPCs (Owner-Entscheidung 17.11.),
dazu Reflection; gRPC-Health bleibt intern.

| Pfad | Ziel | Regeln |
|---|---|---|
| `/` | SAM (WebUI, API, `/gw/dev`) | OIDC; Body 10m, Puffer an |
| `/auth/realms/solace-lab/`, `/auth/resources/` | Keycloak | sonst nichts unter `/auth` |
| `/kasse`, `/monitor`, `/static/`, `/api/catalog`, `/api/cards`, `/api/scenarios`, `/api/state`, `/api/proposals/` | `gpos-ui` | ohne Login; Body 4m, Puffer an |
| `/api/pos/` | `gpos-ui` | Body 4m, Puffer an; 120 je min und IP |
| `/api/demo/` | `gpos-ui` | Body 4m, Puffer an; 2 je min und IP |
| `/api/events` | `gpos-ui` (SSE) | 10 Verbindungen je IP, kein Puffer |
| `/de.gebit.rp.purchase.purchase.v2.service.PurchaseTransactionService/` | `gpos-pos` | `Prefix`, alle RPCs; 60 je min und IP |
| `/de.showcase.wws.v1.service.MerchandiseService/` | `gpos-wws` | `Prefix`, alle RPCs inkl. `RequestPriceChange`; 60 je min und IP |
| `/de.showcase.loyalty.v1.service.LoyaltyService/` | `gpos-loyalty` | `Prefix`, alle RPCs inkl. `IssueCoupon`; 60 je min und IP |
| `/grpc.reflection.v1.ServerReflection/` und `v1alpha` | `gpos-pos` | ohne Limit; ab 0.1.4 für alle drei Dienste |
| `/freigabe`, `/foto`, `/op`, `/etikett` | kein Pfad | bis zur Owner-Entscheidung (7) |
| Grafana, Prometheus, SEMP, Keycloak-Admin, Traefik-Dashboard | kein Pfad | nur Port-Forward |

Alle Limits zählen je Client-IP (`limit-burst-multiplier: "1"`, Antwort 429);
alle Standgeräte teilen eine NAT-IP (Kalibrierung A21).

### 0.3 Kosten

24/7 rund 300-340 EUR im Monat (VM rund 220 EUR); mit Nachtstopp rund 145-185
EUR (gestoppt nur Disks, IPs, LB, ACR: rund 80 EUR). Preise 19.11.2026
(`prices.azure.com`, GWC): D8ps v6 0,3007 EUR/h, LB 0,0224 EUR/h, IP 0,0045
EUR/h, ACR Basic 0,1496 EUR/Tag, P10 19,46 EUR/Monat. Kein Defender, kein
Budget.

### 0.4 Termine

| Wann | Was |
|---|---|
| ab 19.11.2026 | Abschnitt 1, dann A1-A7 (sofort möglich) |
| bis 27.11. | A8-A11 (Plattform, Prod-Zertifikat) |
| bis 02.12. / 03.12. | A12-A17 (Broker, Keycloak, SAM) / Gate G0-11a |
| bis 10.12. | A18-A19 (GEBIT-Demo, Mesh) |
| 11.12. / 18.12. | Gate G0-11b / Gate G2a |
| KW52-KW2 | A20 (Image 0.1.4), A21 (Kalibrierung) |
| um 15.01.2027 | Zertifikat erneuern (4.3), Gate G2b |
| 18./19.01. / 22.01. | 24-h-Lauf ohne Nachtstopp / Gate G3 |
| 26.01. | letzter Node-Image-Refresh (4.2) |
| 28.01., 29.01., 03.02. | Probetage |
| 05.02. | Gate G4, Freeze, ab jetzt 24/7 |
| 16.-18.02. | Messe |
| 19./20.02. | GEBIT-Material löschen, Rückbau nach Entscheidung (5) |

## 1. Vorbereitung

### 1.1 Grundregeln

- Jedes Terminal (zsh) sourct im Repo-Root
  `~/Documents/GitHub/solace-demo-artifacts` zuerst
  `. gebit-price-agent-demo/infra/aks/aks.sh` (setzt `interactivecomments`).
  gpd-Befehle (`scripts/`, `make`, `build/`) laufen in `$GPD`: `cd "$GPD"` bzw.
  `(cd "$GPD" && ...)` steht davor.
- Claude legt die Dateien aus 1.4 an und prüft sie; der Owner liest den Diff,
  führt aus und committet auf master.
- Secrets nur per Pipe aus dem Key Vault (`kv`) in K8s-Secrets oder `--set`; nie
  als argv an `az`, nie auf den Bildschirm; `secret set` mit `-o none`,
  K8s-Secrets mit `apply --server-side`.
- Nie Flags, die Rollenzuweisungen oder Locks brauchen (`--attach-acr`,
  `--enable-azure-rbac`, `--assign-identity`, `--vnet-subnet-id`), nie
  `az group delete -n gebit-showcase`.

### 1.2 Werkzeuge und Anmeldung (nur lesend)

```bash
setopt interactivecomments                   # nur, solange aks.sh fehlt
az version --query '"azure-cli"' -o tsv      # 2.93.0
kubectl version --client | head -1; helm version --short   # v1.36.x, v4.x
cmctl version --client; jq --version; grpcurl -version
az login && az account set -s azure-se && az account show --query name -o tsv
az group show -n gebit-showcase --query "{l:location,k:keys(tags)}" -o json
az group exists -n gebit-showcase-nodes      # false
az aks get-versions -l germanywestcentral -o json \
  --query "values[?version=='1.36'].{p:keys(patchVersions)}"   # mit 1.36.5
az vm list-usage -l germanywestcentral -o tsv --query \
  "[?name.value=='cores'||name.value=='StandardDpsv6Family'].[name.value,currentValue,limit]"
nslookup eurocis-showcase.germanywestcentral.cloudapp.azure.com   # NXDOMAIN
kubectl config get-contexts -o name          # nur rancher-desktop
```

Prüfung: Am 19.11. alles grün (150 vCPU frei); jede Abweichung stoppt hier.
Quota vor A3 und vor dem 26.01. erneut prüfen (8, mit Surge 16).

### 1.3 Lokale Dateien und Namen

Zwei lokale Dateien, gitignored, Modus 600, nie in git, Chats oder Backups:

- `gebit-price-agent-demo/.env.aks` (ignoriert über `.env.*`) aus der Vorlage
  `infra/aks/env.aks.example`: alle Demo-Werte für AKS (SAM und e2e
  `https://$FQDN`, Broker `solace-pubsubplus.solace.svc.cluster.local` mit User
  `gpos`, SEMP `127.0.0.1:18080`, `PG_MODE=kubectl`; nie Passwörter). Der Owner
  trägt nur `AKS_ACR` und `AKS_KV` ein (global eindeutig; nur diese übernimmt
  aks.sh in die Shell); `OWNER_TAG`, `CREATED_DATE` nur, falls `gebit-showcase`
  keine Tags liefert, `ACME_EAB_*` nur im ZeroSSL-Rückfall (4.3).
- `agent-mesh-deployment/.env.aks` (ignoriert ab der neuen Zeile in
  `agent-mesh-deployment/.gitignore`), entsteht in A15: Keycloak-Werte,
  Client-Secret, Lab-LiteLLM-Key, Chart- und CLI-Pfad.

```bash
mkdir -p ~/.config/eurocis-aks/sam && chmod -R go-rwx ~/.config/eurocis-aks
(umask 077; cp gebit-price-agent-demo/infra/aks/env.aks.example \
  gebit-price-agent-demo/.env.aks)    # ACR- und Key-Vault-Namen eintragen
. gebit-price-agent-demo/infra/aks/aks.sh
az acr check-name -n "$AKS_ACR" --query nameAvailable -o tsv       # true
az rest --method post --query nameAvailable -o tsv \
  --url "https://management.azure.com/subscriptions/{subscriptionId}/providers/Microsoft.KeyVault/checkNameAvailability?api-version=2023-07-01" \
  --body "{\"name\":\"$AKS_KV\",\"type\":\"Microsoft.KeyVault/vaults\"}"   # true
az keyvault list-deleted --resource-type vault --query "[?name=='$AKS_KV'].name" -o tsv   # leer
for f in gebit-price-agent-demo/.env.aks agent-mesh-deployment/.env.aks; do
  git check-ignore -q "$f" && echo "ok $f" || echo "FEHLER: $f nicht ignoriert, STOP"
done
stat -f %Lp gebit-price-agent-demo/.env.aks  # 600
```

### 1.4 Dateien und Änderungen durch Claude

Alle Einträge sind anzulegen bzw. zu ändern, jeweils vor dem genannten Schritt.
Pfade ohne Ordner liegen unter `gebit-price-agent-demo/infra/aks/`.

| Datei | Inhalt | vor |
|---|---|---|
| `aks.sh` | Variablen, Wrapper und Helfer (1.5) | 1.3 |
| `env.aks.example` | Vorlage für `gebit-price-agent-demo/.env.aks` (ohne Punkt, sonst greift `.env.*`) | 1.3 |
| `agent-mesh-deployment/.gitignore` | Zeile `.env.aks` | 1.3 |
| `maint-window.json` | Wartungsfenster und Sperrtermine (Inhalt in A7) | A7 |
| `monitoring-values-aks.yaml` | Overlay zu den Lab-Values: etcd aus, Prometheus-PVC 16Gi `managed-csi-premium`, Grafana-Admin aus Secret `grafana-admin`, kein Ingress, nur Datasources Loki und Tempo | A8 |
| `loki-values-aks.yaml` | `lokiCanary` und `test` aus | A8 |
| `traefik-values.yaml` | Image `traefik` per Digest mit `versionOverride: v3.7.19`, `checkNewVersion: false`; Provider `kubernetesIngressNGINX` an (`ingressClass: nginx`, `controllerClass: k8s.io/ingress-nginx`, keine Snippets, `publishService` an), `kubernetesCRD` an, `kubernetesIngress` und eigene IngressClass aus; `extraObjects`: IngressClass `nginx` (Controller `k8s.io/ingress-nginx`, verlangt das SAM-Chart) und Middleware `traefik/hsts` (`stsSeconds: 604800`, ohne `includeSubDomains` und Preload); `websecure`: `readTimeout: 3600s`, Middleware `traefik-hsts@kubernetescrd`; `web` ohne Redirect (HTTP-01); Service `LoadBalancer`, `externalTrafficPolicy: Local`, Annotationen `azure-pip-name: pip-aks-ingress`, `azure-load-balancer-resource-group: gebit-showcase-nodes`, `azure-load-balancer-tcp-idle-timeout: "30"`, nie `azure-dns-label-name`; `tlsStore.default.defaultCertificate.secretName: ingress-tls`; Access-Log JSON, Header und Query-Parameter `drop`; `/tmp` emptyDir 2Gi; Requests 100m/256Mi, Limit 512Mi; Dashboard nur intern; ServiceMonitor an | A9 |
| `tls/issuers.yaml` | ClusterIssuer `letsencrypt-staging` und `letsencrypt-prod`, HTTP-01 mit Klasse `nginx`, ohne Kontakt-Mail | A10 |
| `tls/staging-probe.yaml` | Certificate `staging-probe` in `traefik` gegen staging | A10 |
| `tls/certificate.yaml` | Certificate `ingress-tls` in `traefik`, Issuer prod | A11 |
| `tls/zerossl-issuer.tpl.yaml` | ClusterIssuer `zerossl` (`acme.zerossl.com/v2/DV90`, EAB mit Platzhalter `__EAB_KID__`, Secret `zerossl-eab`) | 4.3 |
| `test/echo.yaml` | whoami per Digest in `aks-test`; Ingresses (Klasse `nginx`, `tls` nur `hosts`, `ssl-redirect`) `echo` (read-timeout 900), `body` (Puffer an, 1m), `limited` (10 rpm, Multiplikator 1) | A11 |
| `broker/pubsubplus-values.yaml` | `redundancy: false`, `size: prod1k`, `usernameAdminPasswordSecretName: solace-admin`, `extraEnvVars` `messagespool_maxspoolusage: "20000"`; Image `solace/solace-pubsub-standard`, Tag `10.26.0.9219@sha256:...`; `service.type: ClusterIP`; Storage `managed-csi-premium` 64Gi, `useStorageGroup: true`; kein Pull-Secret | A12 |
| `broker/main.tf` | Provider `solaceproducts/solacebroker` `= 1.3.0` nur gegen `http://127.0.0.1:18080`; Module `vpn` und `client` aus `../../../../event-mesh-deployment/terraform/modules`; VPN `default` (Dienste und SEMP-over-Msgbus an) und `sam` (aus), beide `dmr_enabled = false`; Clients `sam` (VPN sam), `gpos` (VPN default), `default` in beiden aus; Passwörter nur als `sensitive` Variablen | A13 |
| `keycloak/keycloak.yaml` | Lab-Manifeste 01, 02, 03, 05 aus `solace-lab-infrastructure/keycloak/manifests` mit: Images per Digest (`quay.io/keycloak/keycloak:26.8.2`, `postgres:17-alpine`); `KC_BOOTSTRAP_ADMIN_*` aus `keycloak-credentials` statt `KEYCLOAK_ADMIN*`; `KC_HOSTNAME=https://eurocis-showcase.germanywestcentral.cloudapp.azure.com/auth`, `KC_HTTP_RELATIVE_PATH=/auth`, `KC_HTTP_MANAGEMENT_RELATIVE_PATH=/` (Probes `/health/*` auf 9000); Limit 1536Mi; Realm `solace-lab` ohne Users und Roles, `resetPasswordAllowed: false`, Brute-Force-Schutz wie im Lab; `KC_HOSTNAME_ADMIN=http://127.0.0.1:18081/auth` für die Admin-Konsole per Port-Forward | A14 |
| `keycloak/ingress.yaml` | Ingress `keycloak` in `iam`, Klasse `nginx`, `ssl-redirect`, `tls` nur `hosts`, Prefix-Pfade `/auth/realms/solace-lab/` und `/auth/resources/` auf `keycloak:8080` | A15 |
| `sam/networkpolicies.yaml` | zwei Ingress-Policies in `sam-solace-lab`: Postgres (`app.kubernetes.io/name: postgresql`, Port 5432) und SeaweedFS nur von Pods desselben Namespace | A16 |
| `agent-mesh-deployment/aks-values.yaml` | zweites `-f` nach `local-k8s-values.yaml`, ohne Secrets und ACR-Namen: `sam.dnsName` und `ingress.host` = FQDN; `ingress.tls` nur `hosts` (kein `secretName`); Annotationen `proxy-body-size: "10m"`, `proxy-request-buffering: "on"`; Broker `ws://solace-pubsubplus.solace.svc.cluster.local:8008`, User und VPN `sam`; `global.imagePullSecrets: ["acr-pull"]`; StorageClass `managed-csi-premium` für Postgres und SeaweedFS. Annotation `cert-manager.io/cluster-issuer: ""` (leer überschreibt den Lab-Issuer; ingress-shim legt dann nie ein Certificate an; nie `null`, Helm rendert es wörtlich) | A16 |
| amd-Skripte | ohne gesetzte Variablen wie heute: `SAM_ENV_FILE` statt `.env`, `SAM_HOME` (Token-Cache), `SAM_URL` (mit `--url "$SAM_URL" --no-dotenv` an jedem `sam config plan/apply`), `SAM_DNS_NAME` und `SAM_REDIRECT_URI` in `scripts/lib/common.sh`, `provision.sh`, rbac-, models- und entrypoints-Apply, beiden `setup-keycloak-*.sh` und gpd `spikes/g0/keycloak-marktleitung.sh`; Lab-Regression: `lab_guard`, dann im Lab `setup-keycloak-client.sh` ("already exists") und `provision.sh` (OK), Lab-`.env` unverändert | A15 |
| gpd-Skripte | `scripts/lib.sh` und `opslib.py` mit `TARGET=lab/aks` (Default lab; aks: `.env.aks`, AKS-kubeconfig und -Kontext, Abbruch bei Lab-URLs wie `solace.lab`, `host.docker.internal`, `localhost`, `:8080`, Ausgaben `build/aks` und `mesh/.rendered/aks`); `install.sh` mit Teilen `pg/db/k8s/mesh/all`, psql per `kubectl exec`, `acr-pull` in `gpos-demo`, ohne Kyverno, Certificate und Lab-CA; `broker.sh/.py` prüfen bei aks erst `127.0.0.1:18080` (SEMP `about/api` und VPN-Prüfung) und nutzen einen offenen Port-Forward, sonst öffnen sie ihn selbst; Abbruch, wenn ein nur im Lab vorhandenes VPN existiert (Lab-Broker) | A18 |
| gpd `k8s/` | `base/`, `overlays/lab` (Render byte-gleich wie heute), `overlays/aks` (`acr-pull`, die acht Ingresses aus 0.2, gRPC je Dienst mit `pathType: Prefix`, `GPOS_GRPC_REFLECTION_SCOPE: all`); `k8s/postgres-aks/` (StatefulSet `gpos-postgres`, Postgres 18 per Digest, UID 999, PVC 8Gi `managed-csi` an `/var/lib/postgresql`) | A18 |
| gpd `scripts/aks-check.sh` | nur lesend gegen öffentliche Endpunkte: SAM `/` 200; `/kasse`, `/monitor` mit Titel; `/api/state` 200; kein Cookie auf `/kasse`; `http://` 308; OIDC-Issuer; `/auth/admin/`, `/auth/realms/master/`, Grafana zu (Inhalt prüfen, SAM antwortet sonst 200); HSTS ohne `includeSubDomains`; Zertifikat; `grpcurl list`; `grpc.health.v1.Health/Check` von außen scheitert; Exit 0 nur bei allen OK | A18 |
| gpd `scripts/tests/test_k8s.py` | Routentest: jede Route aus `app/gposdemo/ui/bff.py` genau einmal "öffentlich" oder "offen"; jede gpos-ui-Route außer `/api/events` hat `proxy-body-size` und `proxy-request-buffering: "on"`; jeder der drei gRPC-Dienste hat genau einen öffentlichen `Prefix`-Pfad; Abnahme `make test` grün, Lab-Render-Diff leer, Lab-Smoke READY | A18 |

### 1.5 aks.sh: Wrapper und Helfer

```bash
# gebit-price-agent-demo/infra/aks/aks.sh (Kern), im Repo-Root sourcen
[ -n "${ZSH_VERSION:-}" ] && setopt interactivecomments
[ -f gebit-price-agent-demo/infra/aks/aks.sh ] ||
  { echo "aks.sh: im Repo-Root sourcen" >&2; return 1; }
AKS_DIR=$PWD/gebit-price-agent-demo/infra/aks GPD=$PWD/gebit-price-agent-demo
AMD=$PWD/agent-mesh-deployment SLI=$HOME/Documents/GitHub/solace-lab-infrastructure
AKS_RG=gebit-showcase AKS_NODE_RG=gebit-showcase-nodes AKS_NAME=aks-eurocis
AKS_LOC=germanywestcentral AKS_VERSION=1.36.5 AKS_LABEL=eurocis-showcase
FQDN=eurocis-showcase.germanywestcentral.cloudapp.azure.com
AKS_KUBECONFIG=$HOME/.kube/aks-eurocis.yaml
AKS_CONTEXT=aks-eurocis-admin        # az hängt bei --admin immer -admin an
AKS_STATE=$HOME/.config/eurocis-aks AKS_SAM_HOME=$HOME/.config/eurocis-aks/sam
CURL_IMG=docker.io/curlimages/curl@sha256:3fb7e13e5d179a845c97d78204f3f1064d1907037f26a3ebf91710571151fd93
_aks_env() { sed -n "s/^$1=//p" "$GPD/.env.aks" 2>/dev/null | tail -1; }
AKS_ACR=$(_aks_env AKS_ACR) AKS_KV=$(_aks_env AKS_KV)
kaks() { KUBECONFIG="$AKS_KUBECONFIG" kubectl --context "$AKS_CONTEXT" "$@"; }
haks() { KUBECONFIG="$AKS_KUBECONFIG" helm --kube-context "$AKS_CONTEXT" "$@"; }
```

| Funktion | Zweck |
|---|---|
| `aks_guard` | vor jedem Schritt gegen AKS: Abbruch, wenn `$AKS_KUBECONFIG` fehlt oder sein Server nicht `https://aks-eurocis-*.hcp.germanywestcentral.azmk8s.io:443` ist |
| `lab_guard` | vor jedem Lab-Skript (amd, gpd, emd): Abbruch, wenn `KUBECONFIG` gesetzt ist, der Kontext nicht `rancher-desktop` heißt oder `aks-eurocis` in `~/.kube/config` steht |
| `aks_tags` | Pflicht-Tags aus `gebit-showcase` (Rückfall `.env.aks`) in das Array `TAGS`, ohne Ausgabe |
| `kv NAME`, `kv_new NAME [BYTES]` | Secret-Wert ohne Zeilenumbruch auf stdout (nur für Pipes); hex-Passwort (Standard 24 Bytes) per `--file /dev/stdin` anlegen, nur wenn es fehlt |
| `acr_pull NS` | Namespace anlegen, Secret `acr-pull` (dockerconfigjson aus `acr-pull-token`) per Server-Side-Apply |
| `aks_ips` | Ingress- und Egress-IP gegen das Register in `$AKS_STATE` prüfen, jede Änderung melden |
| `aks_stop`, `aks_start` | Stopp verweigert 05.-18.02. (`AKS_FORCE=1` übersteuert), schreibt `last-stop`; Start frühestens 30 min danach, wartet auf den Node, `aks_ips`, startet awe nach gwe-Ready einmal neu, listet Pods außer Running |
| `aks_sam CMD`, `aks_kc CMD` | Subshell gegen AKS: `KUBECONFIG` nur AKS-Datei (Kontext geprüft), `SAM_ENV_FILE=$AMD/.env.aks`, `SAM_HOME=$AKS_SAM_HOME`, `SAM_URL`, `SAM_DNS_NAME`, `SAM_REDIRECT_URI=https://$FQDN/api/v1/auth/callback`; `aks_kc` zusätzlich `KEYCLOAK_ADMIN_PASSWORD` |
| `amd_env_aks` | bricht ab, wenn `git -C "$AMD" check-ignore -q .env.aks` scheitert; schreibt `$AMD/.env.aks` (umask 077): `KEYCLOAK_URL=http://127.0.0.1:18081/auth`, `KEYCLOAK_REALM=solace-lab`, `KEYCLOAK_ADMIN_USER=admin`, `KEYCLOAK_CLIENT_ID=solace-agent-mesh`, `KEYCLOAK_ISSUER=https://eurocis-showcase.germanywestcentral.cloudapp.azure.com/auth/realms/solace-lab`; kopiert `LLM_SERVICE_API_KEY`, `SAM_CHART_PATH`, `SAM_CLI_PATH` per grep ohne Anzeige aus der Lab-`.env` |
| `kc_token`, `kc_set_passwords`, `kc_unlock USER` | über den Port-Forward 18081: Admin-Token (60 s gültig, je User neu); Passwort der Keycloak-User sam_admin, sam_user, sam_manager, power_user, data_engineer, viewer, marktleitung aus `kc-user-${u//_/-}` (Vault-Namen sam-admin, sam-user, sam-manager, power-user, data-engineer, viewer, marktleitung) per `reset-password` setzen (Wert per Pipe, Ausgabe Name und HTTP-Code); Exit 0 nur bei siebenmal 204; Brute-Force-Sperre eines Users aufheben |
| `semp PFAD`, `tfa ARGS` | SEMP-GET über den Port-Forward 18080; `terraform -chdir=$AKS_DIR/broker` mit `TF_VAR_*` aus dem Key Vault |
| `sam_helm [ARGS]` | Subshell lädt `$AMD/.env.aks`; `haks upgrade --install agent-mesh "$SAM_CHART_PATH" -n sam-solace-lab -f "$AMD/local-k8s-values.yaml" -f "$AMD/aks-values.yaml"` mit `--set` für OIDC `issuer`, `clientId`, `clientSecret`, `llmService.llmServiceApiKey`, `broker.password` (`solace-sam`), `sam.sessionSecretKey` (`sam-session-secret`), `persistence-layer.postgresql.password` (`sam-pg-admin`) und `image.registry` der sechs Images (gwe, str, s3Init, dbInit, postgresql, seaweedfs) = `$AKS_ACR.azurecr.io` |
| `tls_backup`, `tls_restore`, `sam_tls_copy` | Secret `ingress-tls` ohne uid, resourceVersion, managedFields als JSON per Pipe in den Key Vault (`tls-traefik-ingress-tls`, `-o none`), dann Ablage prüfen (`tls.crt` im Vault gleich Cluster, sonst Exit 1) und notAfter anzeigen; zurück per `kaks create`; `sam_tls_copy` (nur im Rückfall A16): nur `type` und `data` als `sam-tls` nach `sam-solace-lab`, ohne Annotationen |
| `zerossl_on` | Secret `zerossl-eab` aus `ACME_EAB_HMAC` (Pipe), Issuer aus der Vorlage mit `ACME_EAB_KID`, Certificate `ingress-tls` auf Issuer `zerossl` patchen, auf Ready warten, `tls_backup` |
| `net_check` | `nc` auf 8080, 9000, 8008, 55555 und den Traefik-NodePort der Ingress-IP (Ausgabe `OFFEN` je offenem Port); 200 HTTPS-Abrufe von `/api/state` über eine Verbindung, p50 und p95 in ms |
| `sam_netpol_check` | aus `gpos-demo/deploy/gpos-ui` per Python-Socket (3 s) jeden Port aller Services `*postgresql*` und `*seaweedfs*` in `sam-solace-lab` (S3, Filer, Master, Volume); Ausgabe je Ziel `zu` oder `OFFEN`, Exit 0 nur ohne `OFFEN` |

### 1.6 Lab-Schutzregeln

- AKS nur über `kaks`, `haks`, `aks_sam`, `aks_kc` oder Skripte mit `aks_guard`
  bzw. `TARGET=aks`; nie `export KUBECONFIG`, nie `use-context` auf AKS, nie
  `az aks get-credentials` ohne `--file`. Lab von Hand mit
  `--context rancher-desktop`, Lab-Skripte (sie nutzen den aktuellen Kontext)
  nur nach `lab_guard`.
- amd start.sh und stop.sh nie gegen AKS (stop.sh räumt Lab-Keycloak und
  Lab-Broker-Queues über `127.0.0.1:8080` ab, egal welcher Kontext);
  event-mesh-deployment start.sh und stop.sh gar nicht (`docker compose down -v`
  zerstört den Lab-Broker), nur `docker stop` und `start`.
- AKS-Terraform nur in `infra/aks/broker`; Mac-Port 8080 ist der Lab-Broker, AKS
  nutzt 18080 und 18081. `SAM_HOME` und `SAM_PLATFORM_TOKEN` nie in der
  interaktiven Shell. Der LiteLLM-Key nur in `agent-mesh-deployment/.env.aks`
  und SAM, nie in gpd-Dateien, Demo-Secrets, Key Vault, Backups oder git.

### 1.7 Image-Regel und Digests

Private Images (SAM-Offline-Paket: gwe/awe, str, Postgres, SeaweedFS; gpos-demo)
liegen nur in der ACR, `acr-pull` gibt es nur in `sam-solace-lab` und
`gpos-demo`. Öffentliche Images zieht der Cluster upstream: per Digest, wo wir
sie selbst setzen, sonst pinnt die Chart-Version (cert-manager, Monitoring).
Kein `az acr import`, keine Registry-Overrides; Docker Hub erlaubt anonym 100
Pulls je 6 h und IP. Claude trägt die Digests ein (19.11.: Broker
`c0020e53ed48...`, Traefik `a6c0194dda77...`, neu gebaut); der Owner prüft vor
A9, A12, A14 und A18:

```bash
for i in docker.io/library/traefik:v3.7.19 quay.io/keycloak/keycloak:26.8.2 \
  docker.io/library/postgres:17-alpine docker.io/library/postgres:18-trixie \
  docker.io/solace/solace-pubsub-standard:10.26.0.9219 \
  docker.io/curlimages/curl:8.23.0 docker.io/traefik/whoami:v1.12.0; do
  printf '%s ' "$i"; docker buildx imagetools inspect "$i" | awk '/^Digest:/{print $2}'
done
```

## 2. Aufbau Schritt für Schritt

Jeder Schritt läuft in einem Terminal mit gesourctem aks.sh; ab A4 steht vor
Cluster-Befehlen `aks_guard`. Dateiinhalte stehen in 1.4.

### A1 Key Vault

Ziel: Ablage für Passwörter, ACR-Token und TLS-Backup; nur Secret-Rechte für den
Owner, keine Rollenzuweisung.

```bash
az keyvault show -n "$AKS_KV" -o none 2>/dev/null ||
  az keyvault create -g "$AKS_RG" -l "$AKS_LOC" -n "$AKS_KV" \
    --enable-rbac-authorization false --no-self-perms --retention-days 7 -o none
az keyvault set-policy -g "$AKS_RG" -n "$AKS_KV" \
  --object-id "$(az ad signed-in-user show --query id -o tsv)" \
  --secret-permissions get list set delete recover -o none
for s in keycloak-admin keycloak-db grafana-admin solace-admin solace-sam \
         solace-gpos solace-default-off sam-pg-admin; do kv_new "$s"; done
kv_new sam-session-secret 16
for u in sam-admin sam-user sam-manager power-user data-engineer viewer \
         marktleitung; do kv_new "kc-user-$u" 16; done
kv keycloak-admin | grep -qx '[0-9a-f]\{48\}' && echo ok
az keyvault secret list --vault-name "$AKS_KV" --query "length([])" -o tsv  # 16
az keyvault show -n "$AKS_KV" --query "[location,properties.enableRbacAuthorization]" -o tsv
```

Prüfung: `ok`, 16 Secrets, germanywestcentral, false (sonst bräuchte der Vault
eine Rollenzuweisung). Forbidden direkt nach `set-policy`: 1-2 min warten.

### A2 ACR, Pull-Token, private Images

Ziel: ACR Basic im Modus `rbac`, Pull-Token bis 28.02.2027 im Key Vault,
SAM-Images und gpos-demo 0.1.3 (arm64) in der ACR.

```bash
az acr show -n "$AKS_ACR" -o none 2>/dev/null ||
  az acr create -g "$AKS_RG" -l "$AKS_LOC" -n "$AKS_ACR" --sku Basic \
    --admin-enabled false --role-assignment-mode rbac -o none
az acr token show -r "$AKS_ACR" -n aks-pull -o none 2>/dev/null ||
  az acr token create -r "$AKS_ACR" -n aks-pull \
    --scope-map _repositories_pull --no-passwords -o none
az keyvault secret show --vault-name "$AKS_KV" -n acr-pull-token -o none 2>/dev/null ||
  az acr token credential generate -r "$AKS_ACR" -n aks-pull --password1 \
    --expiration 2027-02-28T23:59:59Z \
    --query "passwords[?name=='password1'].value | [0]" -o tsv | tr -d '\n' |
  az keyvault secret set --vault-name "$AKS_KV" -n acr-pull-token \
    --file /dev/stdin -o none
kv acr-pull-token | wc -c                    # deutlich über 30
az acr login -n "$AKS_ACR"                   # Images aus dem Rancher-Desktop-Daemon
for i in solace-agent-mesh:2.542.1 solace-agent-mesh-str:1.80.2 \
         postgres:18.0-trixie chrislusf/seaweedfs:4.48-compliant \
         gpos-demo/gpos-demo:0.1.3; do
  docker image inspect -f "{{.Architecture}} $i" "registry.solace.lab/$i" &&
  docker tag "registry.solace.lab/$i" "$AKS_ACR.azurecr.io/$i" &&
  docker push -q "$AKS_ACR.azurecr.io/$i" || break
done
az acr show -n "$AKS_ACR" --query "[location,sku.name,roleAssignmentMode]" -o tsv
az acr token show -r "$AKS_ACR" -n aks-pull --query "credentials.passwords[].expiry"
```

Prüfung: jede Schleifenzeile `arm64`; germanywestcentral, Basic,
LegacyRegistryPermissions (= Modus rbac); Ablauf 2027-02-28. Fehlt ein Image
lokal: im Lab `load-images.sh` bzw. `make build` (gpd).

### A3 Cluster anlegen

Ziel: `aks-eurocis` wie in 0.1, Node-RG mit Pflicht-Tags.

```bash
az group exists -n "$AKS_NODE_RG"            # false
aks_tags && echo "${#TAGS[@]} Tags"          # 2
az aks create -g "$AKS_RG" -n "$AKS_NAME" -l "$AKS_LOC" \
  --kubernetes-version "$AKS_VERSION" --tier free \
  --dns-name-prefix aks-eurocis --node-resource-group "$AKS_NODE_RG" \
  --nodepool-name main --node-vm-size Standard_D8ps_v6 --node-count 1 \
  --max-pods 110 --node-osdisk-type Managed --node-osdisk-size 128 \
  --network-plugin azure --network-plugin-mode overlay --network-dataplane cilium \
  --pod-cidr 10.244.0.0/16 --service-cidr 10.0.0.0/16 --dns-service-ip 10.0.0.10 \
  --load-balancer-managed-outbound-ip-count 1 \
  --auto-upgrade-channel none --node-os-upgrade-channel SecurityPatch \
  --no-ssh-key --tags "${TAGS[@]}" -o none
az aks nodepool update -g "$AKS_RG" --cluster-name "$AKS_NAME" \
  -n main --max-surge 1 -o none
az aks show -g "$AKS_RG" -n "$AKS_NAME" -o tsv --query "[currentKubernetesVersion,\
sku.tier,nodeResourceGroup,networkProfile.networkDataplane,\
networkProfile.networkPolicy,autoUpgradeProfile.nodeOsUpgradeChannel]"
az group show -n "$AKS_NODE_RG" --query "keys(tags)" -o tsv   # Owner, Created Date
```

Prüfung: 1.36.5, Free, gebit-showcase-nodes, cilium, cilium, SecurityPatch.
Create dauert rund 10 min; Failed: `az aks delete` und neu.
`RequestDisallowedByPolicy` heißt Tags fehlen; scheitert ein späteres Update
daran (Azure/AKS #5856), dreimal mit 60 s Pause wiederholen, dann
`az aks update -g "$AKS_RG" -n "$AKS_NAME" --tags "${TAGS[@]}"` (ersetzt das
ganze Set).

### A4 Admin-kubeconfig

Ziel: Admin-Zertifikat in einer eigenen Datei.

```bash
rm -f "$AKS_KUBECONFIG"                      # vor jedem Neuabruf
az aks get-credentials -g "$AKS_RG" -n "$AKS_NAME" --admin --file "$AKS_KUBECONFIG"
chmod 600 "$AKS_KUBECONFIG"
KUBECONFIG="$AKS_KUBECONFIG" kubectl config get-contexts -o name   # aks-eurocis-admin
aks_guard && kaks get nodes -L kubernetes.io/arch                  # Ready, arm64
kaks get nodes -o custom-columns=CPU:.status.allocatable.cpu,MEM:.status.allocatable.memory
kubectl config current-context; grep -c aks-eurocis ~/.kube/config # rancher-desktop, 0
```

Prüfung wie kommentiert; allocatable rund 7,8 CPU und mindestens 28,5 GiB
(notieren). Die Datei ist ein Dauerschlüssel: nie in git, Cloud-Ordner, Chats,
Backups; abgeflossen hilft nur `az aks rotate-certs` (rund 30 min Ausfall).

### A5 Ingress-IP mit DNS-Label

Ziel: statische IP mit dem festen Namen (in der Node-RG).

```bash
az network public-ip show -g "$AKS_NODE_RG" -n pip-aks-ingress -o none 2>/dev/null ||
  az network public-ip create -g "$AKS_NODE_RG" -n pip-aks-ingress \
    -l "$AKS_LOC" --sku Standard --allocation-method Static \
    --version IPv4 --dns-name "$AKS_LABEL" -o none
az network public-ip show -g "$AKS_NODE_RG" -n pip-aks-ingress -o json \
  --query "{ip:ipAddress,fqdn:dnsSettings.fqdn,k:keys(tags)}"
dig +short "$FQDN"                           # = ip, nach 1-2 min
```

Prüfung: `fqdn` ist `$FQDN`, Tags geerbt. Kein `--dns-name-scope` (sonst Hash im
Namen). `az aks delete` löscht die IP mit, das Label ist dann frei: nach einem
Neuaufbau ohne Pause neu anlegen.

### A6 IP-Register, Pull- und LLM-Test

Ziel: beide öffentlichen IPs registrieren; Pull per Token und
LiteLLM-Erreichbarkeit aus dem Cluster belegen.

```bash
aks_guard && aks_ips                         # egress-ip, ingress-ip: registriert
acr_pull default
kaks -n default run acr-test --restart=Never \
  --image="$AKS_ACR.azurecr.io/gpos-demo/gpos-demo:0.1.3" \
  --overrides='{"apiVersion":"v1","spec":{"imagePullSecrets":[{"name":"acr-pull"}]}}' \
  --command -- python -c "print('pull ok')"
kaks -n default wait pod/acr-test --for=jsonpath='{.status.phase}'=Succeeded \
  --timeout=300s && kaks -n default logs acr-test   # pull ok
kaks -n default delete pod acr-test; kaks -n default delete secret acr-pull
LLM_BASE=$(sed -n 's/^  llmServiceEndpoint: "\(.*\)"$/\1/p' "$AMD/local-k8s-values.yaml")
kaks -n default run llm --rm -i --restart=Never --image="$CURL_IMG" -- \
  curl -s -o /dev/null --max-time 15 -w '%{http_code}\n' "$LLM_BASE/v1/models"
```

Prüfung: Pull ohne ImagePullBackOff; LLM-Test 401 oder 200 (ohne Key). 000 oder
Timeout: Der Owner klärt mit dem LiteLLM-Betreiber eine IP-Allowlist und meldet
die Egress-IP (nach jedem Neuaufbau erneut).

### A7 Wartungsfenster und Sperrtermine

Ziel: SecurityPatch nur Mi 08:00-12:00, keine geplante Wartung am 20.01. und vom
27.01. bis 20.02.2027. `maint-window.json`:

```json
{ "maintenanceWindow": {
    "schedule": { "weekly": { "intervalWeeks": 1, "dayOfWeek": "Wednesday" } },
    "durationHours": 4, "utcOffset": "+01:00", "startTime": "08:00",
    "notAllowedDates": [ { "start": "2027-01-20", "end": "2027-01-20" },
                         { "start": "2027-01-27", "end": "2027-02-20" } ] } }
```

```bash
for n in default aksManagedNodeOSUpgradeSchedule; do
  az aks maintenanceconfiguration add -g "$AKS_RG" --cluster-name "$AKS_NAME" \
    -n "$n" --config-file "$AKS_DIR/maint-window.json" -o none
done
az aks maintenanceconfiguration list -g "$AKS_RG" --cluster-name "$AKS_NAME" -o json \
  --query "[].{n:name,t:maintenanceWindow.startTime,x:maintenanceWindow.notAllowedDates}"
```

Prüfung: beide mit 08:00 und Sperren; Änderungen per
`maintenanceconfiguration update`. Gestoppt keine Wartung: Mi bis 08:00
starten, sonst entfällt das Fenster dieser Woche.

### A8 Monitoring

Ziel: Monitoring wie im Lab, nur Port-Forward; vor Traefik, weil dessen
ServiceMonitor die CRDs braucht.

```bash
aks_guard && M="$SLI/pki/manifests" && H=https://grafana.github.io/helm-charts
kaks create namespace monitoring --dry-run=client -o yaml | kaks apply -f -
kv grafana-admin | kaks -n monitoring create secret generic grafana-admin \
  --from-literal=admin-user=admin --from-file=admin-password=/dev/stdin \
  --dry-run=client -o yaml | kaks apply --server-side -f -
haks upgrade --install kube-prometheus kube-prometheus-stack \
  --repo https://prometheus-community.github.io/helm-charts --version 83.5.0 \
  -n monitoring -f "$M/05-monitoring-values.yaml" \
  -f "$AKS_DIR/monitoring-values-aks.yaml" --wait --timeout 15m
haks upgrade --install loki loki --repo "$H" --version 6.55.0 -n monitoring \
  -f "$M/05-loki-values.yaml" -f "$AKS_DIR/loki-values-aks.yaml" --wait
haks upgrade --install tempo tempo --repo https://grafana-community.github.io/helm-charts \
  --version 2.0.0 -n monitoring -f "$M/05-tempo-values.yaml" --wait
haks upgrade --install alloy alloy --repo "$H" --version 1.11.0 -n monitoring \
  -f "$M/05-alloy-values.yaml" --wait
kv grafana-admin | pbcopy                    # danach pbcopy </dev/null
kaks -n monitoring port-forward svc/kube-prometheus-grafana 3000:80
```

Prüfung: vier Releases, Pods Running, PVCs Bound, kein Ingress; Grafana
(`http://127.0.0.1:3000`, admin) zeigt Loki-Logs. Lab-`05-monitoring.yaml` nicht
anwenden (Kyverno). Besucher-IPs liegen 7 Tage in Loki.

### A9 Traefik und Hairpin

Ziel: Traefik als einziger Eingang auf `pip-aks-ingress`; Pods erreichen den
Namen (Hairpin für SAM, Keycloak und HTTP-01).

```bash
aks_guard && haks upgrade --install traefik traefik \
  --repo https://traefik.github.io/charts --version 42.4.1 \
  -n traefik --create-namespace -f "$AKS_DIR/traefik-values.yaml" --wait
kaks -n traefik get svc traefik -o jsonpath='{.status.loadBalancer.ingress[0].ip}{"\n"}'
curl -s -o /dev/null -w '%{http_code}\n' "http://$FQDN/"      # 404 von Traefik
kaks get ingressclass; kaks get svc -A | grep -c LoadBalancer  # nginx; 1
az network lb rule list -g "$AKS_NODE_RG" --lb-name kubernetes \
  --query "[].frontendPort" -o tsv           # 80 und 443
kaks run hairpin --rm -i --restart=Never --image="$CURL_IMG" -- \
  curl -s -o /dev/null -w '%{http_code}\n' --max-time 10 "http://$FQDN/"   # 404
```

Prüfung: Service-IP gleich `ingress-ip`, Image mit dem Digest aus 1.7. Liefert
der Hairpin 000 oder Timeout, den Namen clusterintern auf die Traefik-ClusterIP
legen (`fallthrough` ist Pflicht, sonst fällt das Cluster-DNS aus; entsteht der
Service neu, Eintrag neu schreiben):

```bash
TIP=$(kaks -n traefik get svc traefik -o jsonpath='{.spec.clusterIP}')
printf 'apiVersion: v1\nkind: ConfigMap\nmetadata: {name: coredns-custom, namespace: kube-system}\ndata:\n  eurocis.override: |\n    hosts {\n      %s %s\n      fallthrough\n    }\n' \
  "$TIP" "$FQDN" | kaks apply -f -
kaks -n kube-system rollout restart deployment coredns
```

### A10 cert-manager, Issuer, Staging-Probe

Ziel: cert-manager v1.21.3 mit beiden Issuern; HTTP-01 mit einer
Wegwerf-Bestellung gegen staging beweisen.

```bash
aks_guard && haks upgrade --install cert-manager cert-manager \
  --repo https://charts.jetstack.io --version v1.21.3 \
  -n cert-manager --create-namespace \
  -f "$SLI/pki/manifests/01-cert-manager-values.yaml" --wait
kaks apply -f "$AKS_DIR/tls/issuers.yaml" && kaks get clusterissuer   # READY True
kaks apply -f "$AKS_DIR/tls/staging-probe.yaml"
kaks -n traefik wait certificate/staging-probe --for=condition=Ready --timeout=10m
kaks delete -f "$AKS_DIR/tls/staging-probe.yaml"; kaks -n traefik delete secret staging-probe
```

Prüfung: Probe in Minuten Ready. Hängt die Challenge im Selbsttest ("propagation
check failed"), ist es der Hairpin (A9), kein CA-Problem.

### A11 Prod-Zertifikat, Backup, Abnahmetests

Ziel: Let's-Encrypt-Zertifikat als Traefik-Default, gesichert; Eingang,
Timeouts, Client-IP und Limits per Echo-Dienst belegt.

```bash
aks_guard && kaks apply -f "$AKS_DIR/tls/certificate.yaml"
kaks -n traefik wait certificate/ingress-tls --for=condition=Ready --timeout=15m
tls_backup                                   # Exit 0: Ablage geprüft
openssl s_client -connect "$FQDN:443" -servername "$FQDN" </dev/null 2>/dev/null |
  openssl x509 -noout -issuer -enddate       # Let's Encrypt, rund 90 Tage
kaks apply -f "$AKS_DIR/test/echo.yaml" && kaks -n aks-test rollout status deploy/echo
curl -sS "https://$FQDN/aks-test/echo" | grep -i x-real-ip   # eigene öffentl. IP
curl -sI "http://$FQDN/aks-test/echo" | head -1              # 308
curl -sI "https://$FQDN/aks-test/echo" | grep -i strict-transport   # max-age=604800
curl --http1.1 -s -o /dev/null -w '%{http_code} %{time_total}\n' \
  "https://$FQDN/aks-test/echo?wait=300s"                    # 200 nach 300 s
head -c 2000000 /dev/urandom | curl -s -o /dev/null -w '%{http_code}\n' \
  --data-binary @- "https://$FQDN/aks-test/body"             # 413
for i in $(seq 1 30); do curl -s -o /dev/null -w '%{http_code}\n' \
  "https://$FQDN/aks-test/limited"; done | sort | uniq -c    # ~10x 200, Rest 429
kaks run hairpin --rm -i --restart=Never --image="$CURL_IMG" -- \
  curl -sS -o /dev/null -w '%{http_code}\n' "https://$FQDN/aks-test/echo"   # 200
kaks delete -f "$AKS_DIR/test/echo.yaml"
# Restore-Probe, einmal, solange nichts live ist; löscht nur nach geprüftem Backup:
tls_backup && kaks -n traefik delete certificate ingress-tls &&
  kaks -n traefik delete secret ingress-tls && tls_restore &&
  kaks apply -f "$AKS_DIR/tls/certificate.yaml"
kaks -n traefik get certificaterequest       # keine Ressourcen
```

Prüfung wie kommentiert. `cloudapp.azure.com` fehlt auf der Public Suffix List,
alle Azure-Kunden teilen 50 neue Zertifikate je 7 Tage: `rateLimited` heißt
sofort ZeroSSL (4.3). Erneuerungen: 5 je 7 Tage, daher `tls_backup`.

### A12 Broker

Ziel: ein Broker ohne HA, nur im Cluster; früh, damit 2 CPU reserviert sind.

```bash
aks_guard && kaks create namespace solace --dry-run=client -o yaml | kaks apply -f -
kv solace-admin | kaks -n solace create secret generic solace-admin \
  --from-file=username_admin_password=/dev/stdin \
  --dry-run=client -o yaml | kaks apply --server-side -f -
kaks describe node | sed -n '/Allocated resources/,/Events/p'   # >= 2 CPU frei
haks upgrade --install solace pubsubplus --version 3.10.0 -n solace \
  --repo https://solaceproducts.github.io/pubsubplus-kubernetes-helm-quickstart/helm-charts \
  -f "$AKS_DIR/broker/pubsubplus-values.yaml"
kaks -n solace rollout status sts/solace-pubsubplus --timeout=600s
kaks -n solace get pod,svc,pvc               # 1/1, ClusterIP, 64Gi Bound
```

Prüfung wie kommentiert. Größe und Spool gelten ab dem ersten Boot (ändern heißt
PVC löschen). Pod Pending (CPU): Requests der anderen Releases prüfen
(`kaks describe node`), `size` bleibt `prod1k`; reicht der Node nicht, STOP und
Owner-Entscheidung.

### A13 Broker-VPNs und Client-Usernames

Ziel: VPNs wie im Lab; Client `sam` in VPN `sam`, `gpos` in VPN `default`,
Client `default` in beiden aus.

```bash
kaks -n solace port-forward svc/solace-pubsubplus 18080:8080   # Terminal 2, offen
semp '/SEMP/v2/config/msgVpns?select=msgVpnName' | jq -r '.data[].msgVpnName'
# nur "default"; steht ein weiteres VPN da: STOP, das ist der Lab-Broker
semp /SEMP/v2/monitor/about/api | jq -r .data.sempVersion     # 10.26.0.9219
tfa init && tfa plan && tfa apply
semp '/SEMP/v2/config/msgVpns/sam/clientUsernames?select=clientUsername,enabled' |
  jq -c '.data[]'                            # sam true, default false
```

Prüfung: VPN `default` ebenso (`gpos` true); zweites `tfa plan` leer. Scheitert
Provider 1.3.0 (bisher nur gegen 10.25): Objekte per SEMPv2 anlegen.
`terraform.tfstate` hält Passwörter (gitignored, nur lokal).

### A14 Keycloak (noch ohne Ingress)

Ziel: Keycloak 26.8.2 mit Postgres in `iam` unter `/auth`, erst nur per
Port-Forward.

```bash
aks_guard && kaks create namespace iam --dry-run=client -o yaml | kaks apply -f -
kv keycloak-db | kaks -n iam create secret generic postgres-credentials \
  --from-literal=username=keycloak --from-file=password=/dev/stdin \
  --dry-run=client -o yaml | kaks apply --server-side -f -
kv keycloak-admin | kaks -n iam create secret generic keycloak-credentials \
  --from-literal=admin-user=admin --from-file=admin-password=/dev/stdin \
  --dry-run=client -o yaml | kaks apply --server-side -f -
kaks apply -f "$AKS_DIR/keycloak/keycloak.yaml"
kaks -n iam rollout status deploy/keycloak --timeout=600s
kaks -n iam port-forward svc/keycloak 18081:8080             # Terminal 3, offen
curl -s http://127.0.0.1:18081/auth/realms/solace-lab/.well-known/openid-configuration |
  jq -r .issuer                              # https://$FQDN/auth/realms/solace-lab
kv keycloak-admin | pbcopy; open http://127.0.0.1:18081/auth/admin/   # Login admin
read -r '?Enter nach dem Login als admin '; pbcopy </dev/null
```

Prüfung wie kommentiert, Admin-Konsole lädt. Erster Start baut selbst (Pfad;
startupProbe rund 215 s); der Bootstrap-Admin entsteht nur bei leerer DB.

### A15 Realm-Inhalt und Keycloak-Ingress

Ziel: Client mit exakter Redirect-URI, Lab-Gruppen und -User plus `marktleitung`
mit Key-Vault-Passwörtern; danach zwei Pfade öffentlich.

```bash
shasum "$AMD/.env" > "$AKS_STATE/lab-env.sha"
amd_env_aks && (cd "$AMD" && aks_kc ./scripts/setup-keycloak-client.sh &&
  aks_kc ./scripts/setup-keycloak-users.sh &&
  aks_kc "$GPD/spikes/g0/keycloak-marktleitung.sh")   # $AMD/.env.aks, Modus 600
kc_set_passwords && kaks apply -f "$AKS_DIR/keycloak/ingress.yaml"   # 7x 204
curl -s "https://$FQDN/auth/realms/solace-lab/.well-known/openid-configuration" |
  jq -r .issuer                              # wie in A14, ohne -k
curl -s "https://$FQDN/auth/realms/master/.well-known/openid-configuration" |
  jq -e .issuer >/dev/null && echo "FEHLER: master erreichbar"
shasum -c "$AKS_STATE/lab-env.sha"           # OK
```

Prüfung: Client mit genau `https://$FQDN/api/v1/auth/callback`; 7 Gruppen, 7
User; `KEYCLOAK_CLIENT_SECRET` in `$AMD/.env.aks`. Ingress nur, wenn
`kc_set_passwords` mit Exit 0 endet (die Skripte setzen Passwort gleich
Username). Alter Client mit falschen URIs: per Admin-REST löschen, Skript neu.

### A16 SAM installieren

Ziel: SAM unter `https://$FQDN/` mit OIDC gegen `/auth`, Broker im Cluster,
gebündelter Persistenz und dem einen Zertifikat.

```bash
aks_guard && kaks -n traefik get certificate ingress-tls     # READY, prod
acr_pull sam-solace-lab
kaks apply -f "$AKS_DIR/sam/networkpolicies.yaml"
sam_helm
kaks -n sam-solace-lab wait --for=condition=ready pod \
  -l app.kubernetes.io/instance=agent-mesh --timeout=600s
O="$AMD/manifests/observability"
kaks apply -f "$O/sam-metrics-services.yaml" -f "$O/sam-servicemonitors.yaml" \
  -f "$O/sam-alerts.yaml" -f "$O/dashboards/"
kaks -n sam-solace-lab get pods -o jsonpath='{..image}' | tr ' ' '\n' | sort -u
curl -sS -o /dev/null -w '%{http_code} %{ssl_verify_result}\n' "https://$FQDN/health"
kaks -n iam exec sts/postgres -- pg_isready -t 5 \
  -h agent-mesh-postgresql.sam-solace-lab.svc.cluster.local   # no response
semp '/SEMP/v2/monitor/msgVpns/sam/clients?select=clientUsername&count=100' |
  jq -r '.data[].clientUsername' | sort | uniq -c   # nur sam
```

Prüfung: nur ACR-Images; `/health` `200 0` (Default-Zertifikat); `kaks get
certificate -A` nur `traefik/ingress-tls`; `pg_isready` ohne Antwort; Dashboard
`sam-token-cost` bleibt leer (Folge der NetworkPolicy, akzeptiert). Nur mit
Prod-Zertifikat installieren (OIDC-Discovery); PG-Passwort ist ab dem ersten
Install fest: nur `sam_helm`, nie `--reuse-values`. Rückfall bei
`ssl_verify_result` ungleich 0: `ingress.tls[0].secretName: sam-tls` in
`aks-values.yaml`, `sam_tls_copy && sam_helm` (Kopie auch nach 4.3 und 4.7).

### A17 sam-Login, provision.sh, SAM-Abnahme

Ziel: eigener Token-Cache für AKS; RBAC, Modelle, max_tokens, Pricing und
Entrypoint wie im Lab; Login und Chat belegt.

```bash
LC="$HOME/Library/Application Support/sam/auth/solace-lab.json"; stat -f %m "$LC"
kv kc-user-sam-admin | pbcopy
aks_sam sam auth login solace-lab --url "https://$FQDN"   # Browser: sam_admin
pbcopy </dev/null; aks_sam sam api /api/v1/user           # sam_admin@solace.lab
(cd "$AMD" && aks_sam ./scripts/provision.sh)
aks_sam sam api /api/v1/platform/models --jq '.data[] | .alias // .name'
curl -s -o /dev/null -w '%{http_code}\n' "https://$FQDN/gw/dev/"   # 401
open "https://$FQDN/"                        # Login sam_admin, Chat "Antworte nur mit OK"
stat -f %m "$LC"                             # unverändert
kaks apply -f "$AKS_DIR/tls/staging-probe.yaml"   # HTTP-01 neben SAMs Redirect
kaks -n traefik wait certificate/staging-probe --for=condition=Ready --timeout=10m
kaks delete -f "$AKS_DIR/tls/staging-probe.yaml"; kaks -n traefik delete secret staging-probe
```

Prüfung: provision.sh OK (Models OK oder WARN); Aliase general, planning,
report_gen, image_gen, workflow, reasoning, coding, expert, fast; Login ohne
Warnung; der Orchestrator antwortet (erst das beweist LiteLLM aus dem Cluster);
die Staging-Probe wird Ready; `/gw/dev` bleibt (provision.sh, OIDC-geschützt).
Logout "Invalid redirect uri": `post.logout.redirect.uris=https://$FQDN/*`.

### A18 Demo-DB, gpos-demo, öffentliche Prüfung

Ziel: Postgres 18 in `gpos-data` frisch geseedet; Secrets, sechs Deployments und
acht Ingresses in `gpos-demo`; Prüfung von außen und der SAM-NetworkPolicy.

```bash
cd "$GPD"
TARGET=aks scripts/install.sh pg && TARGET=aks scripts/install.sh db
kaks -n gpos-data get pods,pvc               # gpos-postgres-0 1/1, Bound
ls ~/Downloads/Gebit/purchase-api-2.50.0.pb ~/Downloads/Gebit/receipt-api-2.13.0.pb
TARGET=aks scripts/install.sh k8s
kaks -n gpos-demo get deploy,ingress
TARGET=aks make smoke                        # READY (Kasse 99, ohne SAM)
scripts/aks-check.sh                         # alle OK, Exit 0
kaks -n sam-solace-lab get svc; sam_netpol_check   # jede Zeile "zu", Exit 0
```

Prüfung: `db` endet nach den 95-checks ohne Fehler; 6 Deployments 1/1; 8
Ingresses (`gpos-ui`, `-ui-pos`, `-ui-demo`, `-ui-events`, `gpos-grpc`,
`gpos-wws-grpc`, `gpos-loyalty-grpc`, `gpos-grpc-reflection`); keine
WARNING "left out"; vom BFF kein SAM-Port `OFFEN` (Ergebnis in G0-11b
notieren). Das Descriptor-Set kommt nur zur Laufzeit aus `~/Downloads/Gebit`.

### A19 Mesh bis zum Booth-Entrypoint

Ziel: RBAC, Connectoren, Agenten, Workflows, volle Gate-Verifikation, R1-Queue
und Booth-Entrypoint `gpos-booth-events` auf AKS.

```bash
cd "$GPD"
kv kc-user-marktleitung | pbcopy             # Browser: einmal als marktleitung anmelden
read -r '?Enter nach dem Browser-Login als marktleitung '; pbcopy </dev/null
TARGET=aks scripts/install.sh mesh           # mit Gate-Verifikation, ca. 11 min
TARGET=aks scripts/broker.sh r1-show         # genau ein Flow auf gpos-booth-r1
TARGET=aks scripts/check_hygiene.sh --platform
cat build/aks/gate-verified                  # PASS, approve x3, deny x5, timeout x2
```

Prüfung: "== done (mesh)", Proben p1 p3 p4 notify r1 r3 r4 PASS,
`gpos-booth-events` ready. Nie `--prune`. Die Gate-Verifikation legt Karten in
den Posteingang der Marktleitung: nur vor Standöffnung.

### A20 Image 0.1.4 (Reflection für alle drei Dienste)

Ziel: ein kombinierter Reflection-Endpunkt auf `gpos-pos` (Claude: `grpcutil.py`
meldet bei `GPOS_GRPC_REFLECTION_SCOPE=all` alle drei Dienste, sucht erst im
GEBIT-, dann im Showcase-Pool, Default `own`; Tests, `smoke.py`, Version 0.1.4).
Erst Lab, dann ACR; bis dahin brauchen WWS und Loyalty
`-protoset build/descriptors/showcase.pb`.

```bash
cd "$GPD" && make test && make push GPOS_VERSION=0.1.4   # Lab-Registry
# Lab auf 0.1.4 umstellen (eigener Commit), dann:
lab_guard && scripts/install.sh k8s && make smoke && make e2e SCENARIO=S1
az acr login -n "$AKS_ACR"                   # Token gilt rund 3 h
docker tag registry.solace.lab/gpos-demo/gpos-demo:0.1.4 \
  "$AKS_ACR.azurecr.io/gpos-demo/gpos-demo:0.1.4"
docker push "$AKS_ACR.azurecr.io/gpos-demo/gpos-demo:0.1.4"
# in gebit-price-agent-demo/.env.aks: GPOS_VERSION=0.1.4
TARGET=aks scripts/install.sh k8s && TARGET=aks make smoke
grpcurl "$FQDN:443" list                     # Purchase, WWS, Loyalty
```

### A21 e2e, Reset-Zeit und Rate-Limits kalibrieren

Ziel: fachlich wie im Lab, Reset unter 15 s; Limits stoppen Schleifen, nicht den
Standbetrieb. Nur vor Standöffnung.

```bash
cd "$GPD"
for s in S1 S3 S7 S8; do TARGET=aks make e2e SCENARIO=$s RUNS=5; done
TARGET=aks make e2e SCENARIO=S1 MODE=deny RUNS=5
TARGET=aks make e2e SCENARIO=S1 MODE=timeout RUNS=2
time TARGET=aks scripts/reset.sh --scope day --preflight
for i in 1 2 3 4; do curl -s -o /dev/null -w '%{http_code} ' -X POST \
  -H 'Content-Type: application/json' -d '{"scope":"booth"}' \
  "https://$FQDN/api/demo/reset"; done; echo  # 200 200 429 429
for i in $(seq 12); do curl -s -o /dev/null -m 5 -w '%{http_code}\n' \
  "https://$FQDN/api/events" & done; wait     # 10x 200, 2x 429
make protos; P=build/descriptors/showcase.pb
for i in $(seq 120); do grpcurl -protoset $P \
  -d '{"store_id":"101","article_number":"100001"}' "$FQDN:443" \
  de.showcase.wws.v1.service.MerchandiseService/GetArticle \
  >/dev/null 2>&1 || printf X; done; echo   # X ab etwa Aufruf 65-75
TARGET=aks scripts/reset.sh
```

Prüfung: e2e 27/27 ohne 429 (S1 100001 7,99; S3 100012 12,99; S7 100008 5,49; S8
no_action), p50 <= 18 s, p90 <= 24 s; Limits wie kommentiert, ein Handy im
Mobilfunk lädt `/kasse` dabei. Zuletzt 30 min Kiosk aller Leihgeräte am
Leih-Router ohne 429, sonst Limits im Overlay `aks` anheben. e2e nie parallel
zum Inbox-Wächter.

## 3. Abnahmen gegen die Gates

### G0-11a (03.12.2026): SAM auf AKS mit LLM, Vision, Neustart

- [ ] A1-A17 grün; `haks -n sam-solace-lab list`: Chart 2.3.10, App 2.542.1.
- [ ] Text- und Bildprobe (Block unten) über die AKS-Egress-IP: Antwort OK und
  der Preis vom Schild (sonst `-a` an einen Agenten mit Vision).
- [ ] `kaks -n sam-solace-lab delete pod --all` (nur vor dem Demo-Install):
  Chatverlauf und Artefakt bleiben.

```bash
aks_sam sam task send --url "https://$FQDN" "Antworte nur mit: OK"
aks_sam sam task send --url "https://$FQDN" -f "$GPD/spikes/mm/img/competitor_tag.jpg" \
  "Welcher Preis steht auf dem Schild?"
```

### G0-11b (11.12.2026): HITL und gRPC über den einen Namen

- [ ] A18-A19 grün; `(cd "$GPD" && TARGET=aks scripts/e2e.sh --gate-status)`
  PASS; NetworkPolicy-Ergebnis aus A18 notiert.
- [ ] Bon S1 auf `/kasse`, Freigabe als `marktleitung` in SAM (Notifications),
  Preis auf `/monitor` aktiv.
- [ ] awe-Neustart bei offener Anfrage
  (`kaks -n sam-solace-lab rollout restart deploy/agent-mesh-solace-agent-mesh-awe`):
  kein Preis ohne Freigabe; `(cd "$GPD" && TARGET=aks scripts/reset.sh)` räumt
  auf.
- [ ] `grpcurl "$FQDN:443" list` und `describe` des Purchase-Dienstes; WWS
  `GetArticle` 100001 und Loyalty `ListEligibleOffers` per `-protoset`;
  WWS `GetArticle` per Reflection ab 0.1.4; `grpc.health.v1.Health/Check`
  scheitert von außen.
- [ ] Kein Ersatzserver auf AKS: `spikes/grpc-spike/gebitsim` läuft nur lokal
  auf dem Mac, nie als Image oder in der ACR. G0-11 = G0-11a und G0-11b grün.

### G2a (18.12.2026): Name, Zertifikat, eine IP, RTT

- [ ] `"$GPD/scripts/aks-check.sh"` alle OK, keine Warnung im Browser.
- [ ] `dig +short "$FQDN"` = `ingress-ip`; ein LoadBalancer-Service; LB-Regeln
  nur 80 und 443 (A9).
- [ ] `net_check` per Kabel aus Lab- oder Büronetz: keine Zeile `OFFEN`,
  HTTPS-RTT p95 <= 40 ms.
- [ ] G0-11a grün.

### G2b (15.01.2027): Demo per install.sh, TR1 von außen

- [ ] Zertifikat erneuert und gesichert (4.3).
- [ ] `cd "$GPD"`, `TARGET=aks scripts/uninstall.sh` (ohne `--drop-db`),
  `rm -f "$GPD/build/aks/gate-verified"`,
  `time TARGET=aks scripts/install.sh all` in höchstens 30 min; `gpos-data`
  unverändert.
- [ ] A20 und A21 grün (drei Dienste, e2e 27/27 ohne 429, Reset < 15 s).
- [ ] TR1 über das Internet (Leih-Router per Kabel und 5G, Handy-Hotspot) ohne
  Warnung und Login; `/freigabe`, `/foto`, `/op`, `/etikett` ohne gpos-Seite,
  solange Punkt 1 in 7 offen ist.
- [ ] Hygiene sauber (in `$GPD`: `scripts/check_hygiene.sh`, mit `TARGET=aks`
  auch `--platform`); Image 0.1.4 enthält nur `/app/descriptors/showcase.pb` und
  läuft als UID 10001. Lab danach: `lab_guard && (cd "$GPD" && make smoke)`
  READY.

### G3 (22.01.2027): Neuaufbau, Dauerlauf, Kiosk, Netz, L3

- [ ] Neuaufbau nach 4.7 bis `aks-check.sh` und Preflight grün in höchstens 4 h
  (falls der Drill bleibt, Punkt 3 in 7); nach dem TLS-Restore keine neue
  CertificateRequest.
- [ ] 24-h-Lauf Mo 18.01. 12:00 bis Di 19.01. 12:00 (450 POS-Läufe je Stunde,
  Bursts von 7, per Port-Forward) ohne OOMKilled und NotReady; parallel 10 h
  Kiosk (`/monitor`, `/kasse`) ohne manuelles Neuladen; danach awe-Neustart wie
  in G0-11b, Lauf läuft weiter; Kosten je Aufruf warm <= 0,006 USD, kalt <= 0,02
  USD.
- [ ] Drei Stop/Start-Zyklen: aus kalt bis READY in höchstens 30 min, `aks_ips`
  ohne Änderung.
- [ ] Missbrauchsschleifen bekommen 429, der Kiosk nicht; Kabel ziehen, 5G: SSE
  verbindet neu ohne 429.
- [ ] L3-Drill (4.6) in höchstens 3 min, falls L3 bleibt.

### G4 (05.02.2027): Generalprobe und Freeze

- [ ] 100 Läufe an den Probetagen mit mindestens 98 % ohne Rückfall.
- [ ] Zertifikat: notAfter nach dem 10.04.2027, renewalTime nach dem 20.02.2027;
  ACR-Token bis 2027-02-28; Node-Image wie nach dem 26.01.; Wartungssperre
  aktiv; Git-Tag gleich Image-Tag.
- [ ] Ab 05.02. 24/7 bis 19.02. (`aks_stop` verweigert).
- [ ] L3-Drill (4.6) zweites Mal, falls L3 bleibt; Fehlerdrills nach
  IMPLEMENTATION-PLAN 8.7 mit `kaks`: `kaks -n solace delete pod
  solace-pubsubplus-0`, awe-Neustart in Pause, LiteLLM aus.
- [ ] Freeze: erlaubt sind nur ein Traefik-Patch (Digest und `versionOverride`,
  danach `aks-check.sh` und Smoke), Limit senken oder Route sperren (4.7) und
  TLS-Restore.

## 4. Betrieb

### 4.1 Start und Stopp

- Bis 04.02. abends `aks_stop`, morgens `aks_start` (frühestens 30 min nach dem
  Stopp, 60 min vor Bedarf); nicht 18./19.01. Ab 05.02. kein Stopp (der Start
  könnte an Kapazität scheitern); Notfall `AKS_FORCE=1 aks_stop`.
- Meldet `aks_ips` eine neue Ingress-IP: Alarm, sofort A5 und A9; eine neue
  Egress-IP zählt nur bei einer LiteLLM-Allowlist. `RequestDisallowedByPolicy`:
  wie in A3.

### 4.2 Wartung und Sperre

Letztes automatisches Fenster Mi 13.01.2027, dann Sperre (A7); AKS darf sie für
dringende Wartung brechen (Rückfall L3/L4). Letzter Node-Image-Refresh von Hand
Di 26.01.2027 (Surge-Node, einige Minuten Ausfall):

```bash
az vm list-usage -l "$AKS_LOC" -o tsv --query "[?name.value=='cores'].[currentValue,limit]"   # >= 16 frei
az acr token show -r "$AKS_ACR" -n aks-pull --query "credentials.passwords[].expiry" -o tsv   # 2027-02-28
az aks nodepool upgrade -g "$AKS_RG" --cluster-name "$AKS_NAME" \
  -n main --node-image-only --yes
kaks get nodes -o wide; kaks get pods -A | grep -vE 'Running|Completed'
```

Danach Tagesablauf (4.4), Ausfalldauer notieren; bis 20.02. ungepatcht.

### 4.3 Zertifikat

Einmal um den 15.01.2027 erneuern (frühestens 11.01.2027, spätestens vor G3),
damit die Automatik nicht in Freeze oder Messe fällt:

```bash
cmctl --kubeconfig "$AKS_KUBECONFIG" --context "$AKS_CONTEXT" renew -n traefik ingress-tls
kaks -n traefik wait certificate/ingress-tls --for=condition=Ready --timeout=15m
kaks -n traefik get certificate ingress-tls \
  -o jsonpath='{.status.notBefore} {.status.notAfter} {.status.renewalTime}{"\n"}'
tls_backup                                   # Exit 0, zeigt notAfter im Backup
# nur im Rückfall aus A16: sam_tls_copy
```

Prüfung wie G4: notBefore heute, notAfter nach dem 10.04.2027, renewalTime nach
dem 20.02.2027 (rund Mitte März).
`tls_restore` immer nach Traefik und vor `certificate.yaml`; nie
`az keyvault certificate import` (verwirft die cert-manager-Annotationen, dann
bestellt cert-manager neu).

ZeroSSL-Rückfall nur bei `rateLimited`: Der Owner legt ein kostenloses
ZeroSSL-Konto an, trägt die EAB-Daten als `ACME_EAB_KID` und `ACME_EAB_HMAC` in
`gebit-price-agent-demo/.env.aks` ein (nie in git oder Key Vault) und ruft
`aks_guard && zerossl_on`; danach `kaks get clusterissuer zerossl` READY und
`certificate.yaml` auf `zerossl` umstellen. Scheitert dagegen die Challenge, ist
es Hairpin oder Routing (A9), kein Fall für einen CA-Wechsel.

### 4.4 Probetage und Messetage

```bash
aks_start                                    # bis 04.02., >= 60 min vor Bedarf
cd "$GPD" && scripts/aks-check.sh && TARGET=aks make smoke
TARGET=aks scripts/broker.sh r1-show         # genau ein Flow
TARGET=aks scripts/reset.sh --scope day --preflight   # < 15 s, notify PASS
aks_sam sam task send --url "https://$FQDN" "Antworte nur mit: OK"
cd "$GPD" && TARGET=aks make demo-watch      # eigenes Terminal, ganzer Tag
aks_stop                                     # abends, nur bis 04.02.
```

Prüfung: alles OK, `/monitor` zeigt Di 16.02.2027. Probeläufe auf Kasse 98 nur
vor Standöffnung; scheitert die notify-Probe, awe einmal neu starten, dann
`reset.sh`.

### 4.5 Anleitung für die GEBIT-Vertretung

Die Vertretung nutzt nur die öffentlichen Seiten; Cluster, Zertifikat und L3
bleiben beim Owner. Vorab vom Owner, nie im Repo oder Chat:
`marktleitung`-Passwort per Passwortmanager, Telefonnummer, Ablageort des
L4-Films auf dem Monitor-PC, QR-Codes (nur auf den Namen).

- Kasse `https://eurocis-showcase.germanywestcentral.cloudapp.azure.com/kasse`,
  Monitor `.../monitor`, Freigabe `.../` als `marktleitung` (Menü
  Notifications). Vorher: `/monitor` zeigt Di 16.02.2027, SAM angemeldet.
- Jede Anfrage binnen 2 min mit Approve oder Deny beantworten (abgelaufen ist
  harmlos); zweite Anfrage zum selben Bon: Approve, wenn der Monitor den Preis
  schon zeigt, sonst Deny. Nächsten Bon erst nach der Vorschlagskarte
  abschließen.
- Zwischen Gruppen der Reset-Knopf auf `/kasse`; "Zu viele Anfragen": 30 s
  warten; "Text aus Vorlage": KI nicht erreichbar, Demo läuft weiter, Owner
  informieren.
- Seite lädt nicht: neu laden; geht es per Handy-Hotspot, liegt es am Standnetz
  (Router auf 5G), sonst L4-Film und Owner anrufen. Login gesperrt: 15 min
  warten. Nie Einstellungen in SAM ändern.

### 4.6 L3-Notbetrieb

Fällt AKS oder der Uplink aus, zeigt der Owner die Demo vom Lab-MacBook im
Standnetz (Punkt 2 in 7). Vorbereitung bis G3: MacBook mit Lab-Demo und
`caffeinate` ab Aufbautag im Standnetz; Router-DNS `gpos.solace.lab`,
`sam.solace.lab`, `auth.solace.lab` auf seine LAN-IP (angelegt, aus); Lab-CA auf
Kiosk-PCs und Tablet; zweites Lesezeichen-Set. Ohne Uplink nur L1-Texte; im
Drill die LAN-Erreichbarkeit prüfen. Umschalten (zurück umgekehrt, dann
`"$GPD/scripts/aks-check.sh"`):

```bash
lab_guard && (cd "$GPD" && make smoke && scripts/reset.sh --scope day --preflight)
# dann Router-DNS an, L3-Lesezeichen
```

### 4.7 Störungen und Neuaufbau

```bash
# Diagnose, nur lesend: Zertifikat, LLM/Egress, Node, Missbrauch
cmctl --kubeconfig "$AKS_KUBECONFIG" --context "$AKS_CONTEXT" status certificate -n traefik ingress-tls
kaks -n sam-solace-lab logs deploy/agent-mesh-solace-agent-mesh-awe -c awe --since=15m |
  grep -ciE ' 429|401|timeout'; aks_ips
az aks show -g "$AKS_RG" -n "$AKS_NAME" --query "[powerState.code,provisioningState]" -o tsv
kaks -n traefik logs deploy/traefik --since=10m | jq -rR 'fromjson? | .ClientHost // empty' |
  sort | uniq -c | sort -rn | head
```

- Zertifikat: Secret kaputt heißt `tls_restore` (Eingriffe unten); bei
  Rate-Limit ZeroSSL (4.3); am Stand sofort L3.
- LLM ("Text aus Vorlage"): 429 = Limit des Lab-Keys (Demo läuft in L1,
  Lab-Nutzung pausieren); 401 = neuer Lab-Key zuerst in Lab-`.env` und Lab-SAM
  (`lab_guard`, wie im Lab-README), dann `amd_env_aks` (ohne Anzeige),
  Client-Secret per `aks_kc` wie in A15, `sam_helm`, provision.sh (im Freeze nur
  als Ausnahme); Timeout = Egress-IP dem LiteLLM-Betreiber melden (nur bei
  Allowlist).
- Node: Stopped heißt `aks_start`; NotReady über 10 min heißt L3, sonst L4;
  danach 4.4.
- Missbrauch: Limit senken oder Route sperren, danach
  `(cd "$GPD" && TARGET=aks make demo-reset)`; Routen zurück mit
  `(cd "$GPD" && TARGET=aks scripts/install.sh k8s)`.
- Login `marktleitung` gesperrt: endet nach höchstens 15 min, sofort per
  `kc_unlock` (Port-Forward 18081 wie in A14).
- Hänger, "Technischer Fehler", zweite Anfrage: RUNBOOK, Abschnitt Störungen,
  mit `kaks` statt `kubectl`.

```bash
# Eingriffe: nur einzeln und bewusst ausführen
kaks -n traefik delete secret ingress-tls && tls_restore         # Secret kaputt
kaks -n gpos-demo annotate ingress gpos-ui-pos nginx.ingress.kubernetes.io/limit-rpm=30 --overwrite
kaks -n gpos-demo delete ingress gpos-wws-grpc                   # Route sperren
kc_unlock marktleitung                                           # Login-Sperre
```

Neuaufbau (G3-Drill oder Notfall, nie am Messetag):

1. Zeit notieren, dann
   `tls_backup && az aks delete -g "$AKS_RG" -n "$AKS_NAME" --yes` (löscht nur
   nach geprüftem Backup; nimmt die Node-RG mit VM, PVCs, LB und beiden IPs mit;
   das Label ist frei).
2. Ohne Pause A3 bis A7 (gleicher Name, neue Adressen; LiteLLM ggf. neu melden).
3. A8 und A9, cert-manager und Issuer aus A10, dann `tls_restore` und
   `certificate.yaml` (keine Neuausstellung).
4. A12 bis A19; vor A13 den alten Terraform-State löschen; A15 schreibt ein
   neues Client-Secret; A17 meldet sich im AKS-Home neu an.

Key Vault und ACR überleben in `gebit-showcase`. Ohne TLS-Backup nur gegen
staging üben.

## 5. Rückbau nach der Messe

Ab 19.02.2027, GEBIT-Material zuerst und nachweisbar bis 20.02.:

```bash
aks_guard && kaks -n gpos-demo scale deploy --all --replicas=0
kaks -n gpos-demo delete secret gpos-gebit-descriptors
date '+%d.%m.%Y %H:%M Descriptor-Secret gelöscht'   # protokollieren
aks_stop                                     # bis zur Entscheidung (7)
```

Vor Rückgabe der Leihgeräte (falls L3 vorbereitet): Lab-CA von Kiosk-PCs und
Tablet entfernen, Router-DNS-Einträge `gpos`, `sam`, `auth.solace.lab` und
L3-Lesezeichen löschen; erledigt mit Datum protokollieren.

Rückbau erst nach der Owner-Entscheidung (Rückbau oder Übergabe):

```bash
az aks delete -g "$AKS_RG" -n "$AKS_NAME" --yes   # inkl. gebit-showcase-nodes
az group exists -n "$AKS_NODE_RG"            # false
az acr delete -n "$AKS_ACR" --yes
az keyvault delete -n "$AKS_KV" && az keyvault purge -n "$AKS_KV" -l "$AKS_LOC"
az resource list -g "$AKS_RG" -o table; nslookup "$FQDN"   # leer, NXDOMAIN
rm -f "$AKS_KUBECONFIG" "$GPD/.env.aks" "$AMD/.env.aks"
rm -rf "$AKS_STATE" "$GPD/mesh/.rendered/aks" "$GPD/build/aks"
lab_guard && (cd "$GPD" && make smoke)       # Lab unverändert READY
```

Nie `az group delete -n gebit-showcase` (Owner-Entscheidung); Purge ist
endgültig; den Lab-Key nicht deaktivieren. Danach ist `eurocis-showcase` frei
belegbar: Links und QR-Codes nicht weiterverwenden. Allowlist und ZeroSSL-Konto
aufräumen, lokale Exporte mit Messedaten löschen.

## 6. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| Ein Node ohne HA: jeder Node-Vorgang ist Minuten Komplettausfall | Refresh 26.01., Wartungssperre, L3, L4 |
| Admin-kubeconfig ist ein Dauerschlüssel, API-Server offen, jeder Contributor kann sie holen | Datei 600, FileVault, im Notfall `az aks rotate-certs`, Rückbau |
| Let's Encrypt: geteilter Topf `azure.com` (nicht auf der PSL) | erst staging, Backup, ZeroSSL, Erneuerung um 15.01. |
| Label-Verlust zwischen `az aks delete` und neuer IP | Neuaufbau nur im Drill, IP ohne Pause neu |
| Lab und Stand teilen den Lab-Key; öffentliche Endpunkte verbrauchen Budget | Rate-Limits je IP, L1-Texte, Limits klären (7) |
| Öffentlicher Approver: Fehlversuche sperren `marktleitung` bis 15 min | generiertes Passwort, Entsperren per Admin-REST |
| Anonyme gRPC-Schreib-RPCs (Preis ändern, Coupon, Reset) sind öffentlich (Owner-Entscheidung 17.11.) | 60 Aufrufe je min und IP, `scripts/reset.sh` stellt den Demo-Stand her (akzeptiert) |
| Gemeinsamer Origin von SAM und gpos (XSS in gpos könnte SAM-Tokens lesen) | gpos ohne Cookies, Web-Storage und `innerHTML` (akzeptiert) |
| Neue BFF-Seiten ohne Pfad landen bei SAM (200) | Routentest in `test_k8s.py` |
| Traefik weicht vom Lab-ingress-nginx ab (Defaults, 429 statt 503) | nur AKS-Prüfungen zählen, `aks-check.sh` nach jedem Patch |
| ACR-Token läuft am 28.02.2027 ab; Docker Hub limitiert anonyme Pulls | Prüfung vor dem 26.01. und in G4; Digests, keine Pull-Schleifen |

## 7. Offene Punkte

Nur Owner-Entscheidungen; Technisches klärt der Schritt mit Rückfall.

1. `/freigabe`, `/foto`, `/op`, `/etikett` (später `/kunde`) vor G2b: öffentlich
   mit eigenem Limit, nur Port-Forward oder gar nicht? Bis dahin kein Pfad, der
   Routentest erzwingt das.
2. L3 behalten (4.6) oder streichen und direkt L4?
3. G3-Kriterium "Neuaufbau in 4 h" behalten (Risiko: Label und Zertifikat) oder
   durch den Stop/Start-Nachweis ersetzen?
4. Nach der Messe Rückbau oder Übergabe an GEBIT (dann amd64-Build); bleibt
   `gebit-showcase` bestehen?
5. Lab-Broker später auf 10.26.0.9219 heben (heute 10.25.0.208)?
6. LiteLLM: Limits des Lab-Keys an Messetagen beim Betreiber erfragen.
7. Approver-Login: Sperr-Risiko hinnehmen oder im AKS-Realm einen nicht
   erratbaren Login-Namen ohne E-Mail-Login?
