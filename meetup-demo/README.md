# Meetup Demo: AI Worker Lifecycle on SAM v2

20-minute live demo package. Start with `demo-script.md` (timeline,
builder prompt, talk-to-data queries, pre-flight checklist).

## Contents

- `demo-script.md` -- the run book (German)
- `slides/` -- the meetup deck: lifecycle, platform architecture,
  the high-level POS scenario (adapted from the Solace POS
  analytics slide) and the lifecycle mapping of the demo
- `shop/index.html` -- the Acme online shop: publishes order
  events straight to the sam VPN via solclientjs
  (`ws://localhost:8008`) and displays workflow responses live
- `mongodb/` -- POSLOG store: `docker compose up -d` imports 57
  transactions -- the original blog artifact
  ([solace-sam-demos/sam-retail][repo], 20 receipts) plus the
  meetup story transactions in the same document shape
  (read-only user `sam_ro` for the SAM connector)

- `fallback/` -- break-glass declarative configs for the live
  Builder beat (`sam config apply`; NEVER `--prune`)
- `eval/` -- offline evaluation (dataset + LLM-judge experiment);
  apply once, then `sam eval run retail-ops-quality --threshold 0.8`
  (plus `retail-ops-model-benchmark` for the model comparison)

The SAM-side resources (Order Incident Reporter agent, the
order-incident-report workflow and the shop-events event-mesh
entrypoint) live in the regular declarative home:
`agent-mesh-deployment/scripts/agents/`.

[repo]: https://github.com/martensa/solace-sam-demos/tree/master/sam-retail
