# Event Mesh Deployment

Automated deployment of a two-broker Solace Event Mesh with
distributed tracing and Event Portal integration. Everything runs
locally via Docker Compose and is configured through Terraform
using the Solace PubSub+ Terraform provider.

## Architecture Overview

```text
                    +------------------+
                    |   Event Portal   |
                    | (Solace SE Cloud)|
                    +--------+---------+
                             |
                    +--------+---------+
                    | Event Management |
                    |      Agent       |
                    |   (port 8180)    |
                    +--------+---------+
                             |
           +-----------------+-----------------+
           |                                   |
    +------+------+                     +------+------+
    |   solace-1  |        DMR          |   solace-2  |
    |  (port 8080)|<------------------->|  (port 8090)|
    +------+------+                     +------+------+
           |                                   |
           +-----------------------------------+
           |                                   |
    +------+------+                     +--------------------+
    |    OTel     |   traces, metrics,  | Grafana stack (k3s)|
    |  Collector  |-------------------->| Tempo, Prometheus, |
    | (4317/4318) |        logs         | Loki               |
    +-------------+                     +--------------------+
```

## Containers

**solace-1** -- `solace/solace-pubsub-standard:latest`

- SEMP: 8080, SMF: 55557, AMQP: 5672, MQTT: 1883
- WebSocket: 8000, REST: 9000, SSH: 2222

**solace-2** -- `solace/solace-pubsub-standard:latest`

- SEMP: 8090, SMF: 55558, AMQP: 5674, SSH: 2223

**otel-collector** -- `otel/opentelemetry-collector-contrib`

- OTLP gRPC: 4317, OTLP HTTP: 4318
- Exports to the Grafana stack in the local k3s cluster
  (`monitoring` namespace, from `solace-lab-infrastructure`)

**event-management-agent** -- `solace/event-management-agent`

- API: 8180

## Message VPNs

### solace-1

- **default** -- General messaging, all protocols enabled
  (AMQP, MQTT, REST, SMF, WebSocket)
- **amartens-test** -- Modeled Event Mesh in Event Portal
  (Solace SE tenant), messaging services disabled
- **sam** -- Solace Agent Mesh connectivity,
  messaging services disabled

### solace-2

- **default** -- General messaging, all protocols enabled
  (AMQP, MQTT, REST, SMF, WebSocket)
- **amartens-test** -- Modeled Event Mesh in Event Portal
  (Solace SE tenant), messaging services disabled

## DMR Event Mesh

The two brokers form an event mesh via Dynamic Message Routing
(DMR). DMR cluster links bridge the `default` and `amartens-test`
VPNs across both brokers.

- solace-1 runs DMR cluster `cluster-solace-1` (link initiator)
- solace-2 runs DMR cluster `cluster-solace-2` (remote initiator)

DMR links are **disabled by default** in the Terraform
configuration. The `start.sh` script enables them via SEMP API
calls after Terraform applies.

To manually toggle DMR, set `dmr_enabled = true` in
`terraform.tfvars` and re-apply, then enable the links via SEMP
as shown in `start.sh`.

## Distributed Tracing

Distributed tracing is enabled on the `default` VPN of both
brokers using the OpenTelemetry-based Solace tracing integration.

### Trace Pipeline

1. Both brokers publish trace spans to a telemetry queue
   (`#telemetry-trace`)
2. The OpenTelemetry Collector receives spans from both brokers
   via the Solace receiver plugin (AMQP on port 5672)
3. Spans are exported to Grafana Tempo (OTLP HTTP) in the local
   k3s cluster

### Telemetry Configuration

- Telemetry profile: `trace`
- Trace filter: `>` (matches all topics)
- Trace client username: `trace`
- The OTel Collector also accepts standard OTLP input on
  4317 (gRPC) and 4318 (HTTP)

### Central OTLP Endpoint (Grafana Stack)

The collector is the single telemetry hub for the lab. It runs
three pipelines against the monitoring stack of the local k3s
cluster (`monitoring` namespace, deployed by
`solace-lab-infrastructure`):

- Traces -> Grafana Tempo (`tempo.monitoring:4318`, OTLP HTTP)
- Metrics -> Prometheus remote write (`/api/v1/write`; the
  receiver is enabled via `enableRemoteWriteReceiver` in the
  infrastructure repo)
- Logs -> Grafana Loki native OTLP ingest (`:3100/otlp`)

The cluster service names resolve because the collector container
uses kube-dns (`10.43.0.10`) as upstream DNS -- the compose
containers share the Rancher Desktop VM with k3s, so ClusterIPs
are directly routable. Container-name resolution (solace-1/-2)
still works through Docker's embedded DNS.

Future producers (e.g. Solace Agent Mesh) push OTLP to the
collector from inside the cluster via
`http://host.docker.internal:4318` (HTTP) or `:4317` (gRPC) --
for SAM: `management_server.exporters` in the component config.

### Viewing Traces

Open Grafana at `https://monitoring.solace.lab` (admin /
prom-operator) and use Explore with the Tempo datasource to view
distributed traces across both brokers. The Tempo datasource is
pre-wired with tracesToLogs (Loki) and tracesToMetrics
(Prometheus) links.

## Event Portal Integration

The Event Management Agent (EMA) connects both brokers to Solace
Event Portal in the Solace SE tenant. This enables:

- **Runtime Discovery** -- EMA scans broker configurations and
  reports them to Event Portal
- **Runtime Provisioning** -- Event Portal can push configuration
  changes to the brokers through EMA
- **Audit** -- Event Portal tracks configuration drift between
  the modeled and runtime state

The EMA is configured to manage the `amartens-test` VPN on both
brokers, which is modeled as a Modeled Event Mesh in Event Portal.

### EMA Configuration

The EMA configuration is in
`config/event-management-agent/amartens_ema.yml`.
It registers two plugin resources:

- `solace-1` connecting to `http://host.docker.internal:8080`
  (VPN: amartens-test)
- `solace-2` connecting to `http://host.docker.internal:8090`
  (VPN: amartens-test)

EMA credentials for the Event Portal gateway are configured via
environment variables in
`config/event-management-agent/ema_config_keys.env`.

## Prerequisites

- Docker and Docker Compose
- Terraform 1.5 or later
- curl

## Quick Start

### Start

```bash
./start.sh
```

This script performs the following steps:

1. Copies `.env.example` to `.env`
2. Starts all containers via Docker Compose
3. Copies `terraform.tfvars.example` to `terraform.tfvars`
4. Runs `terraform init` and `terraform apply` to configure
   both brokers
5. Enables the DMR cluster links via SEMP API calls

### Stop

```bash
./stop.sh
```

This tears down all containers and removes generated Terraform
state, lock files, and variable files.

## Configuration

### Environment Variables

Container image versions are defined in `.env.example`:

- **PUBSUB_IMG** -- `solace/solace-pubsub-standard:latest`
- **EMA_IMG** -- `solace/event-management-agent:latest`
- **OTELCOL_IMG** -- `otel/opentelemetry-collector-contrib:0.149.0`
  (pinned: the Solace receiver is a lower-stability component,
  `latest` occasionally removes or renames components)

### Terraform Variables

Defined in `terraform/terraform.tfvars.example`:

- **solace_1_url** -- `http://127.0.0.1:8080`
  (SEMP URL for solace-1)
- **solace_2_url** -- `http://127.0.0.1:8090`
  (SEMP URL for solace-2)
- **solace_1_username** / **solace_1_password** --
  `admin` / `admin`
- **solace_2_username** / **solace_2_password** --
  `admin` / `admin`
- **default_client_password** -- `default`
  (password for client usernames)
- **trace_password** -- `trace`
  (password for the trace telemetry user)
- **dmr_password** -- `cluster`
  (DMR cluster link authentication)
- **dmr_enabled** -- `false`
  (enable DMR links via Terraform)

### Broker Scaling

Both brokers are pre-configured with increased scaling limits
in their respective `solace_config_keys.env` files:

- Max connections: 1000
- Max queue message count: 240
- Max Kafka bridge count: 10
- Max Kafka broker connections: 300
- Max bridge count: 25
- Max subscriptions: 500,000
- Max guaranteed message size: 30 MB
- Max spool usage: 30,000 MB

## Terraform Modules

The Terraform configuration uses reusable modules in
`terraform/modules/`:

- **vpn** -- Creates a Message VPN with ACL and client profiles
- **client** -- Creates a client username on a VPN
- **dmr** -- Sets up DMR cluster, link, remote address,
  and VPN bridges
- **telemetry** -- Creates a telemetry profile, trace filter,
  and trace client
- **queue** -- Creates a queue with topic subscriptions

## Directory Structure

```text
event-mesh-deployment/
  .env.example                        Image versions
  docker-compose.yaml                 Service definitions
  start.sh                            One-command startup
  stop.sh                             Teardown and cleanup
  config/
    event-management-agent/
      amartens_ema.yml                EMA config
      ema_config_keys.env             EMA SEMP credentials
    otel-collector/
      otel-collector-config.yaml      OTel pipeline config
    solace-1/
      solace_config_keys.env          Broker 1 config
    solace-2/
      solace_config_keys.env          Broker 2 config
  terraform/
    provider.tf                       Provider aliases
    variables.tf                      Input variables
    terraform.tfvars.example          Example values
    outputs.tf                        Outputs
    broker_solace_1.tf                solace-1 resources
    broker_solace_2.tf                solace-2 resources
    dmr_mesh.tf                       DMR configuration
    modules/
      vpn/                            Message VPN module
      client/                         Client username module
      dmr/                            DMR cluster module
      telemetry/                      Telemetry module
      queue/                          Queue module
```

## Accessing the Brokers

**solace-1:**

- SEMP / PubSub+ Manager: `http://localhost:8080`
- SMF: `tcp://localhost:55557`
- AMQP: `amqp://localhost:5672`
- MQTT: `mqtt://localhost:1883`
- WebSocket: `ws://localhost:8000`
- REST: `http://localhost:9000`
- SSH CLI: `ssh admin@localhost -p 2222`

**solace-2:**

- SEMP / PubSub+ Manager: `http://localhost:8090`
- SMF: `tcp://localhost:55558`
- AMQP: `amqp://localhost:5674`
- SSH CLI: `ssh admin@localhost -p 2223`

Default admin credentials: `admin` / `admin`

Default client credentials: `default` / `default`
