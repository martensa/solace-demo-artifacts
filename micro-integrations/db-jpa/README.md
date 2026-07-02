# Database JPA Micro-Integration (db-jpa)

A Solace Micro-Integration that moves data between a relational
database and a Solace PubSub+ broker using JPA. It ships as three
cooperating components: a runtime **DB Connector**, a low-code
**DB Designer** that models and packages connectors, and a
**DB CLI** that generates the JPA entity code both of them rely on.

> **Built on**: Spring Boot 3.4 + Spring Boot PropertiesLauncher
> (connector runtime), Spring Shell 3.4 (CLI), a Node.js + React
> Connector Control Center (Designer), and Postgres/MySQL/MariaDB/
> Oracle/SQL Server via JDBC.
>
> **Status**: First working draft. The connector runtime, the
> Designer stack, and the CLI each run today; a few rough edges are
> tracked under [Known limitations](#known-limitations).

## What it does

<!-- markdownlint-disable MD013 -->

| Component | Role | Runs as |
| --- | --- | --- |
| **DB CLI** (`DB CLI/`) | Introspects a database schema and generates JPA entities, Spring Data repositories, DAOs, and packages them as `entity.jar` | Java 17 / Maven project, Spring Shell CLI |
| **DB Designer** (`DB Designer/`) | Web UI to model source/sink flows, introspect databases, invoke the CLI, and build a downloadable connector package | docker-compose: Postgres + Node backend (`:6002`) + React UI (`:6003`) |
| **DB Connector** (`DB Connector/`) | The deployable runtime: one Spring Boot JVM per direction (source DB->Solace, sink Solace->DB) | `java` launched from `jpa_source_start.sh` / `jpa_sink_start.sh` |

<!-- markdownlint-enable MD013 -->

## Architecture

The three components form a build-and-run pipeline. The DB CLI
produces the entity code; the DB Designer packages a runnable
connector (and calls the CLI to do so); the DB Connector runs the
package against a broker and a database.

```text
                    +------------------+
                    |     DB CLI       |  reverse-engineers a schema
                    | jpa-entity-      |  -> JPA entities + repos +
                    |   generator      |     DAOs -> entity.jar
                    +--------+---------+
                             | entity.jar
                             v
   +---------------------------------------------------+
   |                   DB Designer                     |
   |   Connector Control Center (docker-compose)       |
   |   - models source/sink flows in the web UI        |
   |   - introspects the DB (meta-api)                 |
   |   - invokes the DB CLI to generate entity.jar     |
   |   - builds + zips the connector package           |
   +--------------------------+------------------------+
                              | connector package (zip):
                              |   connector jar + Config/ +
                              |   dependencies/entity.jar + launcher
                              v
   +---------------------------------------------------+
   |                   DB Connector                    |
   |   source JVM  DB  --->  Solace   (port 8392)      |
   |   sink   JVM  Solace --> DB       (port 8092)     |
   +----------------+---------------------+------------+
        publishes / consumes             reads / writes
                    v                          v
             Solace PubSub+                Database
             broker                        (SQL Server, Oracle,
                                            Postgres, MySQL, ...)
```

Default ports: Designer UI `6003`, Designer API `6002`, Designer
metadata Postgres `5435`, source connector `8392` (management
`9002`), sink connector `8092` (management `9003`).

## Repository layout

Only human-authored, reviewable content is tracked in git. The heavy
runtime artifacts are reproducible and are obtained separately (see
[Obtaining the binaries](#obtaining-the-binaries)); they are excluded
by `.gitignore`.

```text
db-jpa/
  DB CLI/                     entity generator (Maven source + CLI wrapper)
    jpa-entity-generator/     the generator (has its own README.md)
    generateEntity-cli/       interactive shell wrapper + backend service
    order_management.sql      sample schema for the demo
  DB Connector/               the runtime connector
    jpa_source_start.sh       launcher: database -> Solace
    jpa_sink_start.sh         launcher: Solace -> database
    configs/source/           source Spring config (application*.yml)
    configs/sink/             sink Spring config (application*.yml)
    dependencies/             drop generated entity.jar here (kept empty)
  DB Designer/                Connector Control Center
    docker-compose.yml        Postgres + services + UI
    artifacts/                templates, tools, meta-api, connector types
    database/                 metadata schema seed (Postgres / Oracle)
    env/, environment-config.js   backend + UI configuration
  README.md, .gitignore, .markdownlint.json
```

Not tracked (obtained separately, `.gitignore`d):

- `*.tar` -- Docker image exports (~2.4 GB total).
- `*.jar` -- the connector fat-jar, meta-api, and CLI/tool jars
  (build or release artifacts).
- `DB Designer/binary-downloads/` and `*.zip` -- generated packages.
- `target/`, `logs/`, `.idea/`, `entityFolders/`, and local `*.env`.

## Prerequisites

| Requirement | Version / notes |
| --- | --- |
| Java (JDK) | 17 or later (JDK 21 recommended for the CLI) |
| Apache Maven | 3.9 or later (to build the CLI from source) |
| Docker + Docker Compose | for the DB Designer stack |
| Solace PubSub+ broker | reachable SMF + SEMP endpoints |
| Target database | Postgres, MySQL, MariaDB, Oracle, or SQL Server |

## Obtaining the binaries

The connector runtime jar, the Docker images, and generated packages
are not stored in git. Depending on your setup, obtain them from:

- **Docker images** (`connector_designer_services`,
  `connector_designer_ui`, and the connector image): `docker load -i
  <image>.tar` from your Solace-provided image bundle, or pull from
  your registry.
- **Connector fat-jar** (`pubsubplus-connector-database-2.0.2.jar`):
  from the corresponding Solace connector release, placed at
  `DB Connector/`.
- **`entity.jar`**: generate it with the DB CLI (below) or let the
  DB Designer generate it as part of a connector package.

## Component 1 -- DB CLI (entity generator)

Generates JPA entities, Spring Data repositories, and DAOs from a live
database schema and packages them as `entity.jar`. See
[DB CLI/jpa-entity-generator/README.md](DB%20CLI/jpa-entity-generator/README.md)
for the full command reference, type mappings, and strategy details.

Build from source:

```bash
cd "DB CLI/jpa-entity-generator"
mvn clean package -DskipTests
# -> target/jpa-entity-generator-1.0.0.jar
```

Generate source-side entities (database -> Solace) for the sample
`order_management` schema:

```bash
java -jar target/jpa-entity-generator-1.0.0.jar generate \
  --vendor POSTGRESQL \
  --url "jdbc:postgresql://localhost:5432/order_management" \
  --username postgres --password postgres \
  --schema public \
  --package com.solace.connectors.database.source \
  --mode SOURCE --strategy SEQUENTIAL \
  --tables ALL \
  --output ./generated-source-entities \
  --jar ./generated-source-entities/entity.jar
```

Sink-side entities (Solace -> database) are generated with
`--mode SINK` and a `.sink` package. Run the tool once per direction.
The resulting `entity.jar` is what the DB Connector loads from its
`dependencies/` folder.

An interactive wrapper (`DB CLI/generateEntity-cli/`) drives the same
generator with prompts and, optionally, packaging via the Designer
backend.

## Component 2 -- DB Designer (Connector Control Center)

A web UI that models a connector, introspects the database, invokes
the DB CLI to build `entity.jar`, and produces a downloadable
connector package.

```bash
cd "DB Designer"
docker load -i connector_designer_services.tar
docker load -i connector_designer_ui.tar
docker compose up -d
```

Then open the UI at `http://localhost:6003` (API at
`http://localhost:6002`, health at `http://localhost:6002/health`).
The metadata Postgres is on host port `5435`.

The stack is three services on the `cd-network` bridge:

- `postgres_db` -- metadata database, seeded from
  `database/CD_SCHEMA_POSTGRES.sql` (the `CD_CONFIGURATION_TEMPLATE`
  rows drive the UI forms). An Oracle seed exists but is commented
  out in `docker-compose.yml`.
- `connector_designer_ui` -- the React SPA.
- `connector_designer_services` -- the Node.js backend. On startup it
  loads `additionals/startup-patch.js`, which routes entity generation
  through the DB CLI (`DB_CLI_*` variables in `env/cd-services.env`).

Generated connector packages appear on the host under
`DB Designer/binary-downloads/` as a versioned zip containing the
connector jar, `Config/`, `dependencies/entity.jar`, and a launcher
script -- exactly the shape the DB Connector runs.

### Kubernetes / OpenShift deployment

Beyond docker-compose, the Designer ships a Helm chart at
`DB Designer/charts/db-designer` with a local-lab overlay
(`values-rancher.yaml`) and a Bosch OpenShift overlay
(`values-openshift.yaml`), plus hardened non-root images under
`DB Designer/hardened-images/`. Deploy locally with
`DB Designer/scripts/start.sh`. See the handover docs in
`DB Designer/docs/`: `BOSCH-HANDOVER.md`, `OPENSHIFT-DEPLOYMENT.md`,
and `SECURITY.md`.

## Component 3 -- DB Connector (runtime)

Runs one Spring Boot JVM per direction from the connector fat-jar via
the Spring Boot `PropertiesLauncher`. Layout of the `DB Connector/`
directory:

```text
DB Connector/
  pubsubplus-connector-database-2.0.2.jar   (obtain separately)
  jpa_source_start.sh
  jpa_sink_start.sh
  configs/source/  application.yml, application-operator.yml
  configs/sink/    application.yml, application-operator.yml
  dependencies/    entity.jar goes here (obtain / generate)
```

Before starting, this directory must be completed per deployment with
artifacts the DB Designer package provides:

1. Place the connector fat-jar at the top level.
2. Drop the generated `entity.jar` into `dependencies/`.
3. Add `application-db-processor.yml` (and any `mapper/` files) into
   `configs/source/` and/or `configs/sink/`. The operator configs
   import it via `spring.config.import`, so the connector will not
   start without it. A concrete example ships inside the Designer
   package under `Config/`.

Start the connectors (run from inside `DB Connector/`):

```bash
bash jpa_source_start.sh   # database -> Solace, app :8392, mgmt :9002
bash jpa_sink_start.sh     # Solace -> database, app :8092, mgmt :9003
```

Each script sets `-Dloader.path` to `dependencies` (for `entity.jar`)
and the matching `configs/` folder, then layers
`application.yml` + `application-operator.yml` +
`application-db-processor.yml`. Source and sink use distinct
management ports (`9002` / `9003`) so both can run on one host.

## End-to-end demo (order_management)

1. Start a Postgres with the sample schema
   (`DB CLI/order_management.sql`).
2. Generate `entity.jar` with the DB CLI (Component 1).
3. Either run the DB Designer to build a full package, or assemble the
   `DB Connector/` directory by hand (jar + `entity.jar` +
   `application-db-processor.yml`).
4. Start a Solace PubSub+ broker and point the connector configs at
   it.
5. Run `jpa_source_start.sh` and/or `jpa_sink_start.sh`.

## Configuration and secrets

The YAML configs, `env/cd-services.env`, and the SQL seeds contain
**demo-only** credentials and sample host addresses (for example
`admin/admin`, `postgres/postgres`, and placeholder broker/database
endpoints). These are intentional for local demo use, consistent with
the rest of this repository, and are **not** real secrets. Do not add
production credentials to any tracked file. Deployment-specific
secrets belong in untracked `.env` files.

## Known limitations

- **`application-db-processor.yml` is not in `configs/`.** The operator
  configs import it, so the bare `DB Connector/` directory will not
  start until the file is supplied from a Designer package (by design;
  see Component 3).
- **Single shared `dependencies/`.** Source and sink need different
  `entity.jar` contents. As shipped, run one direction at a time, or
  give each direction its own connector directory.
- **Sink dialect mix.** `configs/sink/application-operator.yml`
  combines a SQL Server JDBC URL/driver with `database: oracle` and
  `OracleSchemaNameStrategy`. Align these to the actual sink database.
- **Docker image naming.** Two connector image tars ship with
  inconsistent names (`...AMD64.tar`, `...V2.0.2.tar`); confirm which
  maps to the 2.0.2 jar.
- **Java version note.** The CLI README states JDK 21 while
  `pom.xml` targets `java.version 17`; 17+ works, 21 is recommended.

## Related

- Companion infrastructure repository:
  <https://github.com/martensa/solace-lab-infrastructure>
- Repository root `README.md` and `CLAUDE.md` for the wider Solace
  demo environment.
