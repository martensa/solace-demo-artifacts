# CLAUDE.md - Database JPA Micro-Integration (db-jpa)

This file contains agentic context specific to the db-jpa MI
sub-project. It complements the root `CLAUDE.md` of
`solace-demo-artifacts`, which covers the broader demo environment.

## Project Overview

A Solace Micro-Integration that moves data between a relational
database and a Solace PubSub+ broker using JPA. It has three
cooperating components:

- **DB CLI** (`DB CLI/`) - generates JPA entities, repositories, and
  DAOs from a live schema and packages them as `entity.jar`.
- **DB Designer** (`DB Designer/`) - a low-code Connector Control
  Center (docker-compose) that models flows, invokes the CLI, and
  builds a downloadable connector package.
- **DB Connector** (`DB Connector/`) - the runtime; one Spring Boot
  JVM per direction (source DB->Solace, sink Solace->DB).

Status: first working draft, checked in for continuation. See the
[Status grid](#status-grid) and [Wave plan](#wave-plan) below.

## Build / Test / Run

All commands assume cwd = `micro-integrations/db-jpa/`. Folder names
contain spaces, so quote them.

```bash
# DB CLI - build the entity generator
cd "DB CLI/jpa-entity-generator" && mvn clean package -DskipTests
#   -> target/jpa-entity-generator-1.0.0.jar

# DB Designer - load images, then start the stack
cd "DB Designer"
docker load -i connector_designer_services.tar
docker load -i connector_designer_ui.tar
docker compose up -d          # UI :6003, API :6002, Postgres :5435
docker compose down           # stop (named volume cd_pgdata kept)

# DB Connector - run one JVM per direction (from "DB Connector/")
bash jpa_source_start.sh      # database -> Solace, app :8392, mgmt :9002
bash jpa_sink_start.sh        # Solace -> database, app :8092, mgmt :9003
```

There is no `start.sh`/`stop.sh`/`Makefile` wrapper yet (unlike
event-mesh/agent-mesh); the commands above are the entry points.

## Architecture (high level)

Build-and-run pipeline: DB CLI produces `entity.jar`; DB Designer
packages a runnable connector (calling the CLI); DB Connector runs
the package against a broker and a database.

```text
DB CLI  --entity.jar-->  DB Designer  --connector package-->  DB Connector
```

For the full picture, ports, and an end-to-end walkthrough, see
`README.md` in this directory. The DB CLI has its own detailed
`DB CLI/jpa-entity-generator/README.md`.

## Repository / commit hygiene

The tree on disk is ~3.4 GB but only ~6 MB is tracked. Everything
heavy or generated is excluded by this directory's `.gitignore`:

- `*.tar` - Docker image exports (~2.4 GB). Obtain via `docker load`
  or a registry, never commit.
- `*.jar` - the connector fat-jar, meta-api, and CLI/tool jars are
  build/release artifacts. Six copies of the 108 MB connector jar
  and the packaged zip each exceed GitHub's 100 MB hard limit; do
  NOT `git add -f` them.
- `DB Designer/binary-downloads/`, `target/`, `logs/`,
  `entityFolders/`, `connector-configuration/`, `.idea/`, `*.env`.

If you add a genuinely small jar that must ship, use
`git add -f <path>` and note it here.

## Common Pitfalls

### Launcher scripts must match the real layout

`jpa_source_start.sh` / `jpa_sink_start.sh` originally referenced a
non-existent `2.0.1-SNAPSHOT` jar and `SOURCE_JPA_SQ_mssql/` /
`SINK_DATABASE_DEV_JPA_mssql/` folders. They now use the actual
`pubsubplus-connector-database-2.0.2.jar` and the real
`./dependencies` + `./configs/{source,sink}` layout, with distinct
management ports (9002 / 9003). Run from inside `DB Connector/`.

### Missing application-db-processor.yml

Both operator configs do `spring.config.import:
application-db-processor.yml`, but that file is not present in
`configs/source|sink`; it ships inside a DB Designer package under
`Config/`. The bare `DB Connector/` directory will not start until
it (and any `mapper/` files) is supplied per deployment.

### Single shared dependencies/ folder

Source and sink need different `entity.jar` contents (different
entity packages; the sink may target a different database). As
shipped there is one `dependencies/` folder, so run one direction at
a time, or give each direction its own connector directory.

### Sink dialect mix

`configs/sink/application-operator.yml` combines a SQL Server JDBC
URL/driver with `database: oracle` and `OracleSchemaNameStrategy`.
Align these to the actual sink database before relying on it.

### Demo credentials are intentional; two files are excluded

Tracked YAML/`env`/SQL carry demo-only credentials and sample host
addresses (per the repo convention). No real secrets are tracked.
Two files with more sensitive leftovers - a Solace Cloud JWT in
`DB Designer/connector-configuration/ecosystem.config.js` and live
EC2 Postgres creds under `DB Designer/entityFolders/...` - fall in
`.gitignore`d directories. Keep them out of any commit.

### Root .gitignore does not match cd-services.env

The repo-root rule is literally `.env`, which does NOT match
`cd-services.env`. This directory's `.gitignore` adds `*.env`
(with `!*.env.example`) to cover them.

## Status grid

| Component | State | Notes |
| --- | --- | --- |
| DB CLI | Builds + runs | Java 17 (pom), Spring Boot 3.4.3; own README |
| DB Designer | compose + Helm; E2E verified | upload -> flow -> DB CLI entities -> compiled entity.jar -> package all work on Rancher; see below |
| DB Connector | Launchers fixed + example config | ships a runnable `application-db-processor.yml`(+mapper) example; sink dialect fixed to Postgres; runtime start still user-verified (Wave 4) |
| README / hygiene | Done | .gitignore, README, .markdownlint.json, .gitkeep |

## DB Designer on Kubernetes / OpenShift (customer track)

Besides docker-compose, the DB Designer deploys to Kubernetes/OpenShift via
a Helm chart at `DB Designer/charts/db-designer` (`values-rancher.yaml` for
the local lab, `values-openshift.yaml` for customer OpenShift).
`DB Designer/scripts/start.sh` / `stop.sh` drive the
local install (docker-load the image tars, CoreDNS + `/etc/hosts`,
`helm upgrade`).

Delivery model: NO vendor-managed registry. `release/package-release.sh`
builds a versioned, self-contained bundle (chart tgz + the three images
as tars + connector binaries + docs + MANIFEST with git SHA/sha256).
The customer pushes the images into THEIR registry via the bundled
`scripts/load-and-push.sh` (prints the exact Helm values) and deploys.
The seed image builds the DB CLI FROM SOURCE (multi-stage, `mvn verify`
gate, versionless `jpa-entity-generator.jar`, context = the db-jpa dir
with its `.dockerignore`) -- a bundle can never carry a stale CLI.

Enterprise notes:

- **Hardened images** (`DB Designer/hardened-images/`) wrap the vendor
  images to run non-root + OpenShift arbitrary-UID (verified as UID
  `26999:0`). With them the OpenShift overlay needs NO custom SCC (the
  default restricted-v2 works); the un-hardened root images would need
  `openshift.scc.create=true` (cluster-admin).
- **Two runtime fixes baked in**: Postgres runs as UID 999 on a FRESH PVC
  (fsGroup cannot re-own a root-owned data dir); the backend has no
  `/health`, so probes are `tcpSocket`.
- **Postgres**: embedded StatefulSet on Rancher; external/operator-managed
  DB is the OpenShift default (the official postgres UID 999 fails the
  restricted SCC).
- **DB CLI wiring**: `servicesApp.dbCli.enabled` loads the startup patch
  (args override + ConfigMap) so entity generation runs via the DB CLI; the
  seed image supplies the tools. Entity SOURCES come from the CLI; the
  connector `entity.jar` is COMPILED via the vendor Maven project (the CLI
  packager emits source-only jars the connector cannot load at runtime).
- **Offline Maven**: the seed bakes a complete `m2-repository` (pinned to
  the runtime Maven 3.9.2 so plugin versions match); the chart pins
  `maven.repo.local` (MAVEN_OPTS) and forces `--offline` (MAVEN_ARGS) -> the
  entity.jar build works air-gapped and on OpenShift arbitrary UID. The
  compiled entity.jar is cached per schema so repeat downloads skip Maven.
- **Download button (lab)**: the vendor WEB download serializes the whole
  package as base64-in-JSON synchronously; under QEMU emulation this exceeds
  the UI's ~20s axios timeout (HTTP 499). Server + CORS are fine (proven via
  HAR); it works natively on amd64. Two lab mitigations are baked in: the
  startup patch installs a 10-min response cache on
  `/generate/connector/binary` (first click builds + caches in the
  background, a repeat click serves instantly, beating the timeout; the
  cache clears on entity regeneration), and
  `DB Designer/scripts/extract-connector-package.sh` pulls the built
  package straight from the pod as a fallback. Downloading configs +
  `entity.jar` only (unchecking the static core connector jar) is the
  smoothest path.
- **Known image-level limitations** (out of scope for this chart; each
  closes with a future vendor image update, tracked as R1-R11 in
  `SECURITY.md`): current-Node-LTS + multi-arch + scan-clean images, a real
  `/health` endpoint, and streaming the package download (R10) instead of
  base64-in-JSON. The demo IPs/creds in `artifacts/connectorType/**` have
  already been replaced with `.example` placeholders.
- Handover docs: `DB Designer/docs/CUSTOMER-HANDOVER.md`,
  `OPENSHIFT-DEPLOYMENT.md`, `OPENSHIFT-READINESS.md`, `SECURITY.md`
  (residual-risk register R1-R11).

## Wave plan

- **Wave 1 (done)** - repo hygiene: `.gitignore`, fixed launcher
  scripts, comprehensive `README.md`, `.gitkeep`, first commit.
- **Wave 2 (done)** - config gaps: shipped a runnable
  `application-db-processor.yml`(+mapper) example; reconciled the sink
  dialect (SQL Server/oracle mix -> Postgres). Per-direction
  `dependencies/` kept single by design (run one direction at a time).
- **Wave 3 (done)** - K8s/OpenShift Helm chart, hardened non-root images,
  registry-free distribution bundle, DB CLI wiring, offline Maven, and the
  full Designer E2E (upload -> flow -> entities -> compiled package) verified
  on Rancher.
- **Wave 4 (in progress -- user-driven)** - start the generated connector
  for real (source/sink via the `.sh` scripts) against `solace-2`
  (SMF `localhost:55558`, SEMP `8090`) and the `order_management` Postgres.
- **Wave 5 (open, environment-owned)** - the image-level limitations above
  (each closes with a future vendor image update) and a real
  OpenShift-cluster deploy test (lab only has k3s).

## Code Style

- ASCII-only in source and docs (no unicode dashes, arrows, umlauts).
- English for code, comments, and docs; German is fine in
  operator-facing logs and runbooks.
- Keep markdown linted: lines under 80 chars (MD013), no bare URLs
  (MD034). Run `npx markdownlint-cli *.md`.
- Quote paths in shell - directory names contain spaces.
- Conventional Commits (`feat:`, `fix:`, `docs:`, ...).

## Related Repositories

- `solace-lab-infrastructure` - K8s base infra (PKI, registry,
  ingress).
- `solace-demo-artifacts/micro-integrations/topic-compaction` -
  sibling MI (Kafka-style log compaction over Solace).
- This MI lives in
  `solace-demo-artifacts/micro-integrations/db-jpa/`.
