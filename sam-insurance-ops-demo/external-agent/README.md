# Claims Intake Analyst (external agent)

The one agent of the triage demo that runs OUTSIDE the SAM
platform. It is a SAM v1 Python-SDK app (image
`solace-agent-mesh-enterprise:1.97.2` with the `sam_mongodb` 0.1.0
plugin) deployed as a plain Kubernetes workload in the namespace
`sam-solace-lab-agents`, next to the Web Research and Web Scraper
agents. It joins the mesh over the broker only: the platform holds
no deployment and no database row for it, just the one allow-list
entry that permits the hop.

## Why this is "external"

The customer's estate is heterogeneous: agents built on Azure, AWS
or Databricks that nobody wants to rebuild inside a new tool. The
demo proves that such an agent stays where it is and still becomes
a governed participant of the mesh:

- it publishes its agent card over the broker and the platform
  discovers it (Agent Management lists it as type `discovered`,
  no database row, no Undeploy button, "Chat with Agent" works);
- every request to it is an A2A hop over the broker, carried out
  under the caller's user identity and visible in Activities, Loki
  and Tempo;
- the workflow contract that validates its answer (the intake
  node's output schema) lives on the platform; the agent only
  fills in the JSON shape its own instruction defines.

## What the mesh sees of it, and what it does not

Seen: the agent card (name `ClaimsIntakeAnalyst`, display name
`Claims Intake Analyst`, skill `analyze_claim_intake`), every A2A
request and response with the user identity, the latency of the
hop, the broker span in Tempo, the liaison's peer task in
Activities.

Not seen: its inner tool calls, its tokens and its model. Those
stay in the pod log
(`kubectl logs -n sam-solace-lab-agents deploy/sam-claims-intake-agent`)
and in Loki under
`{namespace="sam-solace-lab-agents", pod=~"sam-claims-intake-.*"}`
as plain text. The `sam_*` Prometheus metrics do not count it
(`sam_component_count` covers platform agents only).

## How it is reached

A workflow node cannot target a broker-discovered v1 agent: the CLI
rejects the cross-reference, and forced in through the REST API the
v1 structured-invocation handler never answers the v2 workflow
engine (the node times out after 90 s). The `intake` node of the
`claim-triage` workflow therefore targets a platform agent, the
`Claims Intake Liaison`, which has no toolsets of its own and
carries one key in its `additionalConfigurations`:

```yaml
interAgentCommunication:
  allowList:
    - ClaimsIntakeAnalyst
```

That key is the whole mechanism. An agent without it has no
delegation tool at all, only its own `sub_task`; the built-in
Orchestrator carries the same key set to `["*"]`. So the liaison
may call exactly one agent in the world, by name, declared in its
config and reviewable in the UI -- reach across the platform
boundary is declared and enforced, not implicit. It delegates ONE
task to the `ClaimsIntakeAnalyst` card ("Per-claim intake JSON for
claim_id <claim_id>. Answer with ONLY the intake JSON contract.")
and hands the peer's values back unchanged. The analyst holds the
lookup recipe and the JSON contract in its own instruction, so the
request stays one line.

An earlier build routed the same hop through the built-in
`Orchestrator`, which also keeps its peer tools inside a workflow
node. That works, but it costs about 13 s of Opus-tier overhead on
the critical path; the liaison does the hop on the `fast` tier.

The agent itself has `agent_discovery` disabled and an empty
`allow_list`: a v1 SDK agent cannot parse v2 agent cards, so it is
a leaf that never calls anyone.

## Files

- `sam-claims-intake-agent-secret.yaml` -- agent-specific values,
  committed with demo values: its own model
  (`LLM_SERVICE_GENERAL_MODEL_NAME`, Haiku 4.5) and the `MONGO_*`
  connection to the host store (`sam_ro/sam_ro`, database
  `acme_claims`). Broker, LLM endpoint and key, S3 and `NAMESPACE`
  come from `sam-shared-secret` in the same namespace.
- `sam-claims-intake-agent-config.yaml` -- ConfigMap with the v1
  app YAML under the key `claims_intake_agent.yaml`: the
  `sam_mongodb` lifecycle (one connection, `auto_detect_schema`
  off), four `mongo_query` tools -- `claim_intake_facts_query` on
  the `claim_intake_facts` view plus `fnol_intake_query`,
  `scanner_results_query` and `weather_cells_query` on the raw
  collections -- the per-claim analyst instruction and the agent
  card. The per-claim recipe is ONE `claim_intake_facts_query`
  call with the pipeline `[{"$match": {"claim_id": "CLM-..."}}]`.
  That view, created by `mongodb/seed/02-anchors.js`, joins the
  drive-in scan, the other claims on the same VIN, the repeat
  contacts and the claim's hail cell, and already computes
  `photos_before_cell` and `days_before_cell` against that cell's
  start, so a single round trip returns every intake fact and the
  answer is the fixed 12-field intake JSON contract
  (`max_llm_calls_per_task` 6: one lookup plus the answer, with
  room for a pipeline fix). The raw collections stay reachable for
  anything the view does not answer.
- `sam-claims-intake-agent-deployment.yaml` -- the pod (500m/512Mi
  to 1 CPU/1Gi). No `imagePullSecrets`: Kyverno injects the
  registry pull secret and the lab CA bundle.

Two things are switched off for the same reason -- prompt weight on
every request. `auto_detect_schema` is `false`, because the
instruction already carries the field lists and the start-up schema
summary cost about 4 s per run; and there is no
`artifact_management` tool group, because `mongo_query` writes its
result through the configured artifact service, not through
LLM-visible tools, so the twelve extra tool declarations only slowed
the per-claim turn. With the view, the single call and those two
cuts, the analyst answers a per-claim request in about 5 s -- its
share of an `intake` node of about 19 s, measured on the live
platform on 2026-09-16.

## Install, verify, remove

`../install.sh` (default profile) applies the directory, waits for
the rollout and polls the platform for the card. By hand:

```bash
kubectl apply -f external-agent/
kubectl rollout status deployment/sam-claims-intake-agent \
  -n sam-solace-lab-agents --timeout=120s
kubectl logs -n sam-solace-lab-agents deploy/sam-claims-intake-agent \
  | grep -E "MongoDB Agent initialization completed|Loaded Python tool"
```

The card is discovered when the gateway log shows
`"discovered agent" agentName=ClaimsIntakeAnalyst` or when
`GET /api/v1/agentCards` (bearer token) lists the name; the pod log
line `MongoDB Agent initialization completed successfully` proves
the store connection. Remove with
`kubectl delete -f external-agent/ --ignore-not-found`
(`../uninstall.sh` does this).

## A note on the MongoDB connection

`MONGO_HOST` is a connection URI, not a bare host name. The plugin
opens `MongoClient(host, port, username, password)` without an
`authSource`; a bare host name would authenticate against `admin`
and fail for `sam_ro`, which is defined in `acme_claims`. pymongo
takes the `authSource` from the URI and still applies the separate
port, user and password values.

## How a Databricks or Azure host would differ

Not at all from the mesh's point of view. The same app YAML runs
wherever Python and a route to the broker exist; only the
environment differs: the `MONGO_*` values point at the real intake
store, `LLM_SERVICE_*` at the host's own model endpoint, and
`SOLACE_BROKER_*` at the customer's event mesh. The card, the hops,
the identities and the contract on the platform stay the same.
