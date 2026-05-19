# Bake the Solace Event Portal connector into the OpenMetadata ingestion image
# so it can be selected from a custom Messaging workflow in the OM UI.
#
# Build (lab):
#   ./scripts/build-and-push.sh
#
# Build (manual):
#   docker build --build-arg OM_INGESTION_VERSION=1.6.5 \
#     -t registry.solace.lab/openmetadata-ingestion-solace:0.3.0 .
#
# The image extends the official Collate ingestion image with the
# connector package (and its sample-data optional dep). The Helm chart
# of openmetadata-dependencies has to be flipped to this image; see
# openmetadata-deployment/local-k8s-deps-values.yaml's airflow.image
# section.

ARG OM_INGESTION_VERSION=1.6.5
FROM docker.getcollate.io/openmetadata/ingestion:${OM_INGESTION_VERSION}

USER root
WORKDIR /opt/connectors/solace-eventportal

# Copy only what the connector needs at runtime. Tests and the bridge
# code stay out of the ingestion image -- the bridge ships as its own
# container (Dockerfile.bridge).
COPY pyproject.toml ./
COPY connector ./connector

# `.[sample-data]` pulls solace-pubsubplus so sampleDataEnabled=true
# works inside Airflow workers. Without the extra the connector still
# works in metadata-only mode.
RUN pip install --no-cache-dir ".[sample-data]"

# Smoke test: import succeeds inside the image (catches missing deps
# early, fails the build instead of failing the workflow run in OM).
RUN python -c "from connector.event_portal_connector import SolaceEventPortalSource; \
               from connector.filters import FilterPattern; \
               from connector.schema_parsers import parse_fields; \
               print('connector import OK')"

USER airflow
