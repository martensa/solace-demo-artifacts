# Meetup Demo: AI Worker Lifecycle on SAM v2

20-minute live demo package. Start with `demo-script.md` (timeline,
builder prompt, talk-to-data queries, pre-flight checklist).

## Contents

- `demo-script.md` -- the run book (German)
- `slides/` -- the meetup deck (copy of the base deck + 2 new
  scenario slides)
- `shop/index.html` -- the Acme online shop: publishes order
  events straight to the sam VPN via solclientjs
  (`ws://localhost:8008`) and displays workflow responses live
- `mongodb/` -- POSLOG store: `docker compose up -d` seeds 74
  transactions matching the retail databases (read-only user
  `sam_ro` for the SAM connector)
- `fallback/` -- break-glass declarative configs for the live
  Builder beat (`sam config apply`; NEVER `--prune`)
- `eval/` -- offline evaluation (dataset + LLM-judge experiment);
  apply once, then `sam eval run meetup-quality --threshold 0.8`

The SAM-side resources (Order Incident Reporter agent, the
order-incident-report workflow and the shop-events event-mesh
entrypoint) live in the regular declarative home:
`agent-mesh-deployment/scripts/agents/`.
