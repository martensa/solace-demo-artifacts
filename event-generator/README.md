# Event Generator (Event Portal driven)

Spring Boot generator (`martensa/eventportal-event-generator`)
that discovers an Event API Product from Solace Event Portal and
publishes sample events to every runtime broker of the modeled
event mesh. Ships its own OpenTelemetry SDK preconfigured for
`otel-collector:4317` (traces, metrics and logs land in the
Grafana stack, see `event-mesh-deployment`).

## Setup

```bash
cp generator_config_keys.env.example generator_config_keys.env
# then replace EVENT_PORTAL_TOKEN=changeme with a real token
docker compose up -d
```

`generator_config_keys.env` is gitignored -- the Event Portal
token must never be committed. All other values are local demo
settings: the MEM runtime credentials `Acme Retail On-Prem`
resolve against the local event mesh brokers with the demo user
`default`/`default` (checked in intentionally, see the repo
secrets conventions).

## Prerequisite: local-only modeled event mesh

The generator connects to EVERY messaging service modeled in the
Event Portal event mesh and crash-loops if one is unreachable or
rejects the login. For the local demo the modeled mesh must only
contain the on-prem runtime (`Acme Retail On-Prem`) -- remove or
detach cloud messaging services (e.g. `MDM-EU`) from the modeled
event mesh / plan in Event Portal first.

The generator publishes guaranteed events; they are traced by the
brokers and visible end-to-end in Grafana Tempo
(`https://monitoring.solace.lab`), including the consumer span
from `event-consumer`.
