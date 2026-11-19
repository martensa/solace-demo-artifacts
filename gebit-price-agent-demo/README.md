# EuroCIS price agent, use case UC1

GEBIT and Solace showcase "Preis- und Aktionsagent mit Freigabe" for
EuroCIS 2027, built end to end on Solace Agent Mesh (SAM) 2.542.1 in
the local lab. `UC1-BUILD-SPEC.md` is the binding build specification;
this README covers setup and operation, `RUNBOOK.md` (German) the fair
operation and the acceptance protocol. The fair itself runs on AKS:
`AKS-MIGRATION-PLAN.md` (German) is the procedure there, and the same
scripts serve both installations (see "AKS target").

Core sentence of the demo: "KI schlägt vor. Regeln prüfen. Mensch
entscheidet."

## What happens

1. Articles are scanned at booth till 01 (`/kasse`). The simulated
   GEBIT POS (`gpos-pos`, GEBIT Purchase API 2.50.0 over gRPC)
   publishes one event per step on the Solace broker.
2. SAM rule `r1_booth_till` starts workflow `gpos-pos-event` per event:
   the engine analyses it without a model (scan insight).
3. After `PurchaseTransactionClosed`, rule `r3_basket_review` starts
   `gpos-basket-review`: the engine flags candidates (rule analysis, no
   model), the evidence agent `gpos-pricing-agent` (`fast`) checks them
   through the POS, WWS and loyalty APIs, the engine records the
   evidence (`note_evidence`), and the planner `gpos-price-planner`
   (`planning`, no tools) writes the final recommendation
   (KI-Empfehlung): at most one temporary price reduction or no
   action. The engine computes every price and guardrail.
4. Rule `r4_price_approval` starts `gpos-price-approval`: a summary
   notification, then the approver agent (`fast`) calls the gated
   `apply_price`, which waits for the store manager's approval in the
   SAM inbox. A denial ends as `rejected`, an expiry as `expired`; the
   engine decides from its database and clock (spec 11.5). On a denial
   or a timeout SAM hands the agent its own text ("Tool call denied by
   user.", "Tool approval timed out after 2 minutes.") with status
   `error`; the approver passes that text on as `message` and the
   engine accepts it as evidence while the gate is untouched (rules
   R5m, R3a, R7m), so a denial reported as `error` still ends
   `rejected`. The store manager then gets the result notification
   "Abgelehnt: ..." or "Abgelaufen: ..." in the SAM inbox.
5. On approval the merchandise service (`gpos-wws`) sets the price
   action; the next scan costs less. `/monitor` shows every step; after
   S1 the footer counts 3 AI agent runs (fast 2, planning 1) and 2 agent
   API queries.

## Hard rules

- No LLM key or LLM endpoint anywhere in this demo. SAM manages the
  models; agents use the aliases `fast` (evidence, approver) and
  `planning` (planner) only.
- Agents get no artifact or data tools. SAM attaches the toolsets
  `builtin_artifact_tools` and `data_analysis` to every agent anyway,
  so every agent lists both in `toolsets` and excludes all 12 of their
  tools with `toolsetExcludedTools`; with an empty `toolsets` SAM drops
  the exclusions silently (spec 9.4, A-21).
- GEBIT vendor material (descriptor sets, protos, samples) never enters
  this directory or the image. The descriptor sets are mounted at
  runtime as the Secret `gpos-gebit-descriptors`.
- Never `sam config apply --prune`; `scripts/lib.sh` refuses it.
- Never rename or remove an entrypoint rule, never switch `R1_MODE`
  without removing the orphaned SAM queue (`scripts/broker.sh`).
- Published with GEBIT's written approval (confirmed by the owner on
  2026-11-17): API details in our own docs and code only; GEBIT files
  (descriptor sets, API docs, sample events, mail) never go in this
  tree.

`scripts/check_hygiene.sh` checks the first two rules before every
install; `--platform` checks the SAM objects after every mesh apply.

## Layout

- `app/` one Python 3.13 package `gposdemo`, one image, six commands
- `proto/`, `data/`, `policy/`, `postgres/` contracts, master data,
  pricing policy, database schemas and seed
- `k8s/base/` namespace `gpos-demo`: ConfigMap `gpos-config`, six
  Deployments and Services; no registry, host or certificate
- `k8s/overlays/lab/` lab only: ingresses on `*.solace.lab`, lab-CA
  certificate, Kyverno pull secret, image tag; `expected-render.yaml`
  pins its render
- `k8s/overlays/aks/` AKS: eight path ingresses on the one public
  name, pull secret `acr-pull`, `gpos-config` patch; the image comes
  from `scripts/k8s_render.py --image` at install time
- `k8s/postgres-aks/` AKS demo DB (Postgres 18, namespace `gpos-data`)
- `k8s/kustomization.yaml` compatibility entry, renders the lab overlay
- `infra/aks/` AKS platform files: `aks.sh` (wrappers and helpers),
  `env.aks.example` (template of `.env.aks`), Helm values, broker
  Terraform, Keycloak, TLS and NetworkPolicy manifests
- `mesh/` SAM resources: connectors, agents, workflows, the two
  entrypoint templates, RBAC copy, fallback F2 in `mesh/fallback/`
- `scripts/` install, reset, broker, inbox, smoke and e2e tooling;
  `aks-check.sh` read-only check of the public AKS name
- `build/` (ignored) lab CA, tool lists, e2e logs, `gate-verified`;
  `build/aks/` the same for `TARGET=aks`
- `build/notes/` (ignored) local, unversioned working notes
- `mesh/.rendered/` (ignored, chmod 700) rendered entrypoints with the
  broker credentials, DB passwords, the applied `R1_MODE`;
  `mesh/.rendered/aks/` for `TARGET=aks`

## Components and ports

- `gpos-pos`: gRPC 50051, MCP and admin API 8771
- `gpos-wws`: gRPC 50053, MCP 8773
- `gpos-loyalty`: gRPC 50052, MCP 8772
- `gpos-engine`: MCP `gpos-booth-tools` and HTTP API 8765
- `gpos-gate`: MCP `gpos-price-gate` 8766 (only `apply_price`)
- `gpos-ui`: BFF, `/kasse`, `/monitor`, SSE on 8090 (Service port 80)

Lab ingress hosts: `gpos.solace.lab` (UI) and `gpos-grpc`,
`gpos-wws-grpc`, `gpos-loyalty-grpc` (`.solace.lab`, gRPC over TLS).
On AKS the UI paths and the three gRPC services share the one public
name with SAM and Keycloak (runbook 0.2).
`scripts/install.sh k8s` leaves out an Ingress whose host and path an
Ingress of another namespace already serves (the NGINX admission
webhook would refuse it) and prints a WARNING naming that Ingress;
remove it, then run `scripts/install.sh k8s` again.

## Prerequisites

- The lab from `solace-lab-infrastructure` (NGINX ingress,
  cert-manager with `solace-lab-ca-issuer`, Kyverno, registry
  `registry.solace.lab`), SAM 2.542.1 in `sam-solace-lab`, the event
  mesh broker `solace-1`, the host container `postgres`.
- `sam` CLI 2.542.1 logged in as `sam_admin`:
  `sam auth login solace-lab --url https://sam.solace.lab`.
- The store manager `marktleitung@solace.lab` has logged in to the SAM
  WebUI at least once (otherwise event runs lack `notify:_:send`).
- The GEBIT descriptor sets in `~/Downloads/Gebit` (read only).
- Broker credentials in `../bsg-trading-desk-demo/.env`, the SEMP admin
  password in `../event-mesh-deployment/terraform/terraform.tfvars`;
  both are read at runtime and never printed.

## Setup

Lab setup, order of spec 9.8 (AKS: see "AKS target"). Every step is
idempotent.

```bash
cp .env.example .env            # adjust; it never holds an LLM key
make venv test                  # Python 3.13 .venv, offline tests
make db-up                      # DB gpos: roles, schemas, seed, checks
make k8s-up                     # build, push, Secrets, six Deployments
make manifests                  # connector manifests from the image
make smoke                      # lab smoke test without SAM (till 99)
make mesh-up                    # SAM resources, probe till, gate
                                # verification, R1 queue, booth
make e2e SCENARIO=S1            # end to end with SAM on till 01
```

`make mesh-up` (`scripts/install.sh mesh`) runs these steps:

1. RBAC (`mesh/manifest-rbac.yaml`, always).
2. Connectors, agents, workflows (`mesh/manifest.yaml`).
3. Platform hygiene (`check_hygiene.sh --platform`).
4. Probe entrypoint `gpos-probe-events` (till 98 of store 199).
5. Readiness through the platform API and SEMP `txFlows`.
6. Probes `p1`, `p3`, `p4` and the login check from the `gpos-ui` pod.
7. Gate verification on probe till 98 (`make gate-verify`: approve
   x3, deny x5 = A9, timeout x2 = A10, about 11 min) unless
   `build/gate-verified` is PASS for these runs and the current
   connectors, agents and workflows. Without PASS the booth entrypoint
   is not applied; `scripts/install.sh mesh --no-booth` stops here.
8. R1 queue `gpos-booth-r1` (`scripts/broker.sh r1-create`).
9. Booth entrypoint `gpos-booth-events` and its readiness.
10. Probes `r1`, `r3`, `r4` on the booth till.

The connector manifests are generated from the image (`make
manifests`); `scripts/install.sh mesh` refuses a placeholder and
compares the manifests with the running services first
(`check_manifests.py`). So when the engine tools change (2026-11-12:
`record_outcome` gained `tool_message`), roll out the new image first
(`make k8s-up`), then check the manifests, then run
`scripts/install.sh mesh`; the changed hash triggers a new gate
verification.

State 2026-11-12 (spec 15.3, next steps in `build/notes/NEXT-mesh.md`):
the second gate verification on image 0.1.1 failed 4/10 (denials
ended `failed`, the planner called `append_to_artifact` twice); the
fix UC1-29 is in `mesh/` and `app/`, tested offline, not yet built,
deployed or verified in the lab.

The GEBIT gRPC host names resolve via `/etc/hosts` (line 19, since
2026-11-12): `gpos-wws-grpc` and `gpos-loyalty-grpc.solace.lab:443`
answer with the lab CA `build/lab-ca.crt`. The POS host `gpos-grpc`
needs its Ingress first (owner, one-object apply, not
`scripts/install.sh k8s`, spec 12.4); until then use
`make port-forward` for the POS.

## Operation

- `make demo-reset` back to the starting state (target below 15 s):
  BFF reset chain, then open approval requests cancelled, then the
  orphaned queue check. Run it before every fair day and every probe.
- `make demo-watch` inbox watcher on the Mac during the fair: answers
  duplicate approval requests and cancels orphaned ones.
- `scripts/sam_inbox.py list|cancel-gpos|answer REF approve|deny`.
- `scripts/broker.sh r1-show|orphans` queue counters and flows.
- `make status`, `make logs`, `make urls`, `make port-forward`.

## End to end and acceptance

`scripts/e2e.py` plays a scenario over the BFF facade, records the SSE
stream, answers the approval request from the SAM inbox and checks
outcome, price, gate (on the engine clock) and agent tool calls. One
JSON line per run and a p50/p90/p95 summary go to `build/e2e/`.

```bash
make e2e TILL=01 SCENARIO=S2 MODE=approve RUNS=20
make e2e SCENARIO=S1 MODE=deny RUNS=5
make e2e SCENARIO=S1 MODE=timeout RUNS=2
make e2e SCENARIO=S1 MODE=approve RUNS=2 ANSWER_DELAY=100
make gate-verify
```

`e2e.py` and `sam_inbox.py watch` never run together
(`build/sam_inbox.lock`). The acceptance criteria A1 to A15 and their
protocol are in `RUNBOOK.md`.

## R1 mode switch

`R1_MODE=own` (default) binds rule `r1_booth_till` to the own queue
`gpos-booth-r1` (max TTL 20 s); `R1_MODE=sam` uses a SAM queue with
subscriptions. A switch needs
`scripts/install.sh mesh --switch-r1`, which applies the booth
entrypoint and then runs `scripts/broker.sh r1-switch OLD NEW` and the
orphan check. Without the flag `scripts/render_mesh.py` stops.

## Fallback F2

Only if the connector gate (A-1) and fallback F1 both fail the gate
verification: set `GATE_GUARD=f2` in `.env`, run
`scripts/install.sh k8s`, then `scripts/install.sh mesh --fallback-f2`.
That applies `mesh/fallback/` (ungated connector `gpos-price-apply`,
agent `gpos-price-approver-f2`, F2 variant of `gpos-price-approval`)
after the main manifest. F2 trusts the model's reported status; its
mandatory extra acceptance is `make e2e MODE=deny RUNS=5`.

## AKS target

`AKS-MIGRATION-PLAN.md` is the procedure (build A1 to A21, checks,
operation, teardown); this section only says how the files and
scripts behave there. `TARGET` is `lab` (default) or `aks`.

- `infra/aks/aks.sh`: source it from the repo root in every AKS
  terminal (`. gebit-price-agent-demo/infra/aks/aks.sh`). It defines
  `kaks` and `haks` (kubectl and helm bound to the AKS kubeconfig
  file and context), `aks_sam` and `aks_kc` (subshells for the
  agent-mesh-deployment scripts and the `sam` CLI against AKS; they
  refuse the lab-only scripts such as `start.sh` and `stop.sh`) and
  the other helpers of runbook 1.5.
- `.env.aks` (git-ignored, mode 600) is a copy of
  `infra/aks/env.aks.example`; it names Key Vault secrets and holds
  none, except the optional ZeroSSL key `ACME_EAB_HMAC` of runbook
  4.3: only `zerossl_on` reads it, the scripts drop it on load.
- With `TARGET=aks` the scripts
  - read `.env.aks` only, never `.env`, and refuse to start when
    `SAM_ENV_FILE`, `KEYCLOAK_CLIENT_SECRET` or the LLM key variable
    of agent-mesh-deployment is set in the environment, when a URL
    setting points to the lab (`solace.lab`, `host.docker.internal`,
    `localhost`, `:8080`), when `E2E_CA_FILE` is the lab CA or
    `GPOS_IMAGE` a lab image, when the namespaces, the DB pod or
    `PG_MODE` differ from the template, or when `SAM_HOME` is
    relative, the real `HOME` or the lab sam home (`scripts/lib.sh`
    and the Python scripts check the same);
  - run kubectl only with `AKS_KUBECONFIG` and `KUBE_CONTEXT` after
    checking the AKS API server, never the current context, and psql
    through `kubectl exec` in `gpos-data/gpos-postgres-0`;
  - run the `sam` CLI with `HOME=$SAM_HOME` and `--url $SAM_URL`,
    without a token of the shell: sam 2.542.1 keeps its login cache
    under `HOME` only, so the AKS login
    (`aks_sam sam auth login solace-lab --url https://<FQDN>`)
    never touches the lab login;
  - read secrets at runtime from the Key Vault (`AKS_KV`), through
    pipes only;
  - write `build/aks/` (gate record with `target=aks`, e2e logs,
    lock) and `mesh/.rendered/aks/`;
  - reach SEMP only through a port-forward on `127.0.0.1:18080`: the
    broker tooling reuses an open one or opens its own, and stops
    when the broker has the lab-only VPN (then it is the lab broker);
  - verify TLS against the system trust store (`E2E_CA_FILE=system`).
- `scripts/lib.sh` and the Python scripts also refuse a lab run
  inside `aks_sam` or `aks_kc` (`SAM_ENV_FILE` set). Run every
  command of this demo in a plain shell.
- `scripts/install.sh pg|db|k8s|mesh|all`: `pg` (AKS only, a no-op in
  the lab) applies namespace `gpos-data`, the Secret
  `gpos-postgres-admin` (random, only if absent) and
  `k8s/postgres-aks`; `db` runs the SQL through `kubectl exec`; `k8s`
  needs `db` first, applies `acr-pull` and `gpos-broker` from the Key
  Vault, renders `k8s/overlays/aks` with
  `--image "$GPOS_IMAGE:$GPOS_VERSION"` and restarts all six
  Deployments (a short outage); `all` is `pg`, `db`, `k8s`, `mesh`.
- A rendered AKS entrypoint is applied only by
  `TARGET=aks scripts/install.sh mesh` or through `aks_sam` (the line
  in the rendered file), never with a plain `sam`.
- Makefile: `build`, `push`, `k8s-up`, `manifests` and `demo-up`
  refuse (they build or push the lab image; the ACR push is runbook
  A20), `test-db`, `test-gebit` and `test-int` refuse (lab DB or
  `.env`);
  `status`, `logs`, `urls`, `port-forward`, `smoke`, `db-up`,
  `mesh-up`, `e2e`, `gate-verify`, `demo-reset`, `demo-watch` and
  `uninstall` follow `TARGET`.
- `scripts/aks-check.sh [FQDN]` checks the public name read-only:
  certificate (at least 14 days left), SAM, `/kasse`, `/monitor`,
  `/api/state`, SSE, OIDC issuer, HSTS, no cookie, closed admin and
  monitoring paths, gRPC routes. One `OK` or `FEHLER` line per check,
  exit 0 only if all pass; needs curl, openssl and grpcurl, but no
  kubeconfig, `.env.aks`, secret or login.

## Tests

- `make test` unit tests of all packages plus `scripts/tests`
  (contracts of `mesh/`, `k8s/`, rendering, inbox rules, broker
  convergence, hygiene, both targets of the scripts), no Docker and
  no lab. The lab render must equal
  `k8s/overlays/lab/expected-render.yaml`; the render tests skip
  without kubectl. `make test` strips an exported `TARGET=aks`, and
  `scripts/tests` drop `TARGET` themselves.
- `make test-db`, `make test-gebit`, `make test-int` need the host
  Postgres or the GEBIT descriptor sets (read at runtime only)

## Uninstall

`make uninstall` removes the SAM entrypoints, workflows, agents and
connectors (REST DELETE, never `--prune`), the own R1 queue and the
namespace. `scripts/uninstall.sh --drop-db` also drops the database.
With `TARGET=aks` the namespace `gpos-data` (the demo DB) stays
unless `--drop-db`. The role `gpos_marktleitung` and its claim mapping
stay (shared with Gate 0).
