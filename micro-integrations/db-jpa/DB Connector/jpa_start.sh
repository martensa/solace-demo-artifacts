#!/bin/bash
# Start the DB Connector for THIS package. Source (Database -> Solace) and
# sink (Solace -> Database) are separate, self-contained packages, so a single
# launcher serves both -- the package's own Config/ decides the direction.
#
# Run from inside a connector package directory (as produced by the DB
# Designer), which must contain:
#   - pubsubplus-connector-database-<version>.jar  the connector runtime
#   - Config/                                       application*.yml (+ mapper/)
#   - dependencies/entity.jar                       the JPA entity jar (DB CLI)
#
# Optional env override:
#   MGMT_PORT   management server port (default 9002). Set a distinct port
#               (e.g. 9003) if you run a second connector on the same host.
set -euo pipefail

JAR="$(ls pubsubplus-connector-database-*.jar 2>/dev/null | head -1)"
[ -n "$JAR" ] || { echo "ERROR: no pubsubplus-connector-database-*.jar found in $(pwd)"; exit 1; }

java -cp "./$JAR" \
  -D"loader.path=./dependencies,./Config" \
  org.springframework.boot.loader.launch.PropertiesLauncher \
  --spring.config.additional-location="./Config/application-operator.yml" \
  --management.server.port="${MGMT_PORT:-9002}"
