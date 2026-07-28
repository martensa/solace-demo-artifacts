# Event Consumer (local demo)

JMS consumer (`martensa/event-consumer`) bound to queue `q` on
the local `solace-2` broker (default VPN). The queue subscribes
to `>`, so every guaranteed message published into the mesh ends
up here -- including events from `event-generator` routed across
the DMR link.

The image ships the OpenTelemetry Java agent; the env file points
it at the event-mesh collector, so the consumer appears as its
own service (`event-consumer`) inside the broker traces (context
propagation via the Solace `traceparent` transport context).

## Run

```bash
docker compose up -d
docker logs -f consumer
```

`consumer_config_keys.env` contains only local demo values
(`default`/`default`, see the repo secrets conventions) and is
checked in on purpose. View the resulting traces in Grafana
(`https://monitoring.solace.lab`, Explore -> Tempo): one trace
spans solace-1 receive, DMR link, solace-2 queue delivery and the
consumer process span.
