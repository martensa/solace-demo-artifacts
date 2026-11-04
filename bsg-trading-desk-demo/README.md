# BSG Trading Desk Assistant demo

A short multi-agent demo for Boerse Stuttgart architects and market
data people: the same Solace mesh that carries their quote feeds
(MQTT), now with agents on top that act on live events, run in a
predictable SAM workflow, and are observable step by step.

Storyline (four steps, one thread, under 7 minutes) and the show
script: [RUNBOOK.md](RUNBOOK.md).

## Status

Work in progress. Built so far, without access to the lab cluster:

- `app/` -- feed publisher, deterministic watcher, MCP tools server
  and presenter UI (one Python image). 21 unit tests plus a smoke
  test of the whole deterministic path against a local MQTT broker
  (mosquitto) pass: a watch from the tool call, exactly one alert
  10 s after the scenario start, enrichment, desk note, action.
- `k8s/` -- Kustomize for namespace `bsg-demo`.
- `mesh/` -- SAM manifests as DRAFTS that follow the schema verified
  on 2.348.22 in the other demos of this repo. NOT applied yet:
  Gate 0 below has to run on the cluster first.
- Not started: the Grafana dashboard (needs the `tasks` columns of
  2.493.0) and the end-to-end acceptance on the cluster.

## Architecture

```text
bsg-demo namespace                solace-1, VPN sam         sam-solace-lab
feed-publisher --MQTT--> bsg/quotes|reference|news --> feed-watcher
demo-ui --MQTT--> bsg/control/*, bsg/desk/actions --> publisher, watcher
demo-ui --MQTT--> bsg/desk/requests/{id} --> entrypoint --> bsg-desk-assistant
feed-watcher ---> bsg/alerts/{watch_id} --> entrypoint --> bsg-alert-triage
bsg-tools (MCP) <-- tool calls of the agents (connector bsg-desk-tools)
bsg-tools ------> bsg/desk/notes|progress/{watch_id}
demo-ui <-- SSE <-- bsg/# (plus SAM status topics, read only)
```

Components (all in `app/bsgdemo/`, one image, see `app/Dockerfile`):

- `publisher.py` -- three fictional issuers (alpha, beta, gamma),
  five products each in `dax-turbo`, `nasdaq-knockout` and
  `discount-cert`; ISINs `DE000DEMO0001` to `DE000DEMO0015`. Quotes
  every 250-500 ms per product, spreads 0.10-0.30 %, prices as a
  random walk around the reference level. Scenarios on
  `bsg/control/scenario`: `wide_spread`, `market_wide`, `stale`,
  `reset`.
- `watcher.py` + `watch_engine.py` -- deterministic, no LLM. Keeps
  15 minutes in memory and in SQLite (emptyDir), evaluates watches
  (`spread_pct`, `quote_age_s`, `drift_vs_ref_pct`) with hold time,
  TTL and debounce, publishes alerts, tracks the issuer status, and
  serves `/recent`, `/reference`, `/news`, `/watches`, `/alerts`,
  `/issuer-status`, `/stats`.
- `tools_server.py` -- MCP server (streamable HTTP) with
  `watch_feed`, `list_watches`, `stop_watch`, `enrich_alert`,
  `publish_desk_note`, `report_progress`. SAM v2 (Go) has no
  in-process Python tools, so every deterministic data access runs
  here.
- `ui/` -- FastAPI + SSE presenter page (German, large type).
- `ctl.py` -- CLI for the scenario Make targets.

Topic layout (prefix `bsg/`):

- `bsg/quotes/{issuer}/{product_class}/{isin}`
- `bsg/reference/{underlying}`, `bsg/news`
- `bsg/control/scenario`, `bsg/control/scenario/state`,
  `bsg/control/watch`
- `bsg/watches/{watch_id}/{event}`
- `bsg/alerts/{watch_id}`
- `bsg/desk/requests/{id}`, `bsg/desk/replies`
- `bsg/desk/progress/{watch_id}`, `bsg/desk/notes/{watch_id}`,
  `bsg/desk/results`, `bsg/desk/errors`
- `bsg/desk/actions`, `bsg/desk/issuer-status/{issuer}`

## Environment (from this repo, to be confirmed in Gate 0)

- SAM v2 Enterprise, Go edition, 2.493.0 (chart 2.2.30), release
  `agent-mesh` in `sam-solace-lab`. Resources are applied
  declaratively with `sam config apply` (no `sam run` in v2).
- Broker `solace-1` runs in Docker Compose on the host
  (`event-mesh-deployment`), not in the cluster. SAM uses VPN `sam`
  via `ws://host.docker.internal:8008`; the demo uses the same VPN
  over MQTT `host.docker.internal:1883`.
- Models: `general` for the desk assistant, `fast` for all workflow
  agents (latency budget below 60 s from alert to note).
- Observability: SAM emits no OTel spans; traces come from the
  broker. Token usage per user comes from the platform DB `tasks`
  table (Grafana datasource `SAM Platform DB`). The existing
  dashboards have no filter variables, hence an own dashboard.

## Decisions and assumptions

Decided with the owner on 2026-11-04:

- No branch node in 2.493.0: stop and report version and upgrade
  path, no workaround.
- No tool node in workflows: the agent `bsg-alert-runner` (model
  `fast`, one MCP tool per step) runs `enrich_alert` and
  `publish_desk_note`. The data stays deterministic; only the call
  goes through an LLM.
- Event-triggered runs are attributed to `power_user@solace.lab`
  (`defaultUserIdentity`). Show the runs in SAM Activities as
  `power_user`. The other demos use the same persona, so the demo
  dashboard filters on the `bsg-` names and the time range as well.
- Documentation in English; UI and desk notes in German.

Assumptions:

- One alert per watch: a watch fires at most once (`max_alerts`
  1) and at most once per product, and the alert lists every
  product of the filter that breaches at that moment. Without this,
  two Alpha DAX turbos would start two workflow runs.
  `scenario reset` re-arms all watches.
- `drift_vs_ref_pct` is the absolute difference between the
  reference level an issuer quotes against and the live reference.
- `enrich_alert` resamples quotes to 5 s per product (about 1,000
  rows for three issuers and one class over 15 minutes) to keep
  the artifacts small.
- The market context verdict uses a fixed rule (two of: reference
  move above 1 % in 5 minutes, high-impact news, both peers above
  0.5 %), so both branches are reproducible.
- The UI draws its own spread chart from the watcher next to the
  agent's chart artifact name; showing the agent's PNG needs an
  authenticated artifact URL (open point).
- Workflow node progress: enrich and publish emit progress events;
  the agent nodes in between are shown as inferred unless SAM's own
  status topics are wired in (`SAM_STATUS_TOPICS`).

## Gate 0 (on the lab cluster, before `make mesh-up`)

1. `kubectl config current-context`, `helm list -A`; confirm SAM
   2.493.0 and the `sam` CLI version.
2. Workflow schema of 2.493.0 (docs and `sam` CLI): branch node
   type (stop if absent), tool node type, artifact hand-over between
   nodes, run id variable. Replace the `__GATE0__` markers in
   `mesh/workflows/bsg-alert-triage.yaml`.
3. Whether an MCP tool result with embedded resources becomes an
   artifact (`ENRICH_EMBED`); else adjust `bsg-alert-runner`.
4. Entrypoint to workflow: is the 2.348.22 bug fixed? Set
   `ENTRYPOINT_WORKFLOW_TARGET` accordingly.
5. Network: SAM `str` pod reaches `bsg-tools.bsg-demo.svc:8765`;
   pods in `bsg-demo` reach `host.docker.internal:1883`; Kyverno
   accepts the Deployments; DNS for `bsg-desk.solace.lab`.
6. A2A status topics of a workflow run on VPN `sam` (A2A sniff) for
   `SAM_STATUS_TOPICS`, and the `tasks` columns for the dashboard.

## Setup

```bash
cp .env.example .env            # broker credentials of VPN sam
pip install -r app/requirements-dev.txt
make test                       # unit tests
make k8s-up                     # build, push, deploy bsg-demo
make port-forward               # in a second shell
make smoke                      # deterministic path, no SAM
make mesh-up                    # after Gate 0
```

Local run without a cluster (any MQTT broker on 1883):

```bash
cd app
MQTT_HOST=127.0.0.1 python -m bsgdemo.watcher &
MQTT_HOST=127.0.0.1 python -m bsgdemo.publisher &
MQTT_HOST=127.0.0.1 WATCHER_URL=http://127.0.0.1:8080 \
  MCP_PORT=8765 python -m bsgdemo.tools_server &
MQTT_HOST=127.0.0.1 WATCHER_URL=http://127.0.0.1:8080 \
  ENTRY_MODE=direct PORT=8090 python -m bsgdemo.ui.server
```

## Removal

`make uninstall` deletes the SAM resources named `bsg-*`
(entrypoint, workflow, agents, connector), the dashboard ConfigMap
and the namespace `bsg-demo`. Nothing else is touched; it never
uses `sam config apply --prune`.

## Open points

- Gate 0 items above.
- Cancelling running workflow runs in `make demo-reset` (platform
  API endpoint unknown); today runs end within the 90 s timeout.
- Grafana dashboard `sam-bsg-trading-desk` (tokens and duration per
  `bsg-` agent for one run).
- Showing the agent's chart artifact in the UI.
- Screenshots of Grafana and SAM Activities for the final report.
