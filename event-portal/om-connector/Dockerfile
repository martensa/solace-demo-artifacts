# Bake the Solace Event Portal connector into the OpenMetadata ingestion image
# so it can be selected from a Messaging workflow in the OM UI.
#
# Build (lab):
#   ./scripts/build-and-push.sh
#
# Build (manual):
#   docker build --build-arg OM_INGESTION_VERSION=1.11.0.0 \
#     -t registry.solace.lab/openmetadata-ingestion-solace:0.4.0 .
#
# The image extends the official Collate ingestion image with the
# connector package (and its sample-data optional dep). The Helm chart
# of openmetadata-dependencies has to be flipped to this image; see
# openmetadata-deployment/local-k8s-deps-values.yaml's airflow.image
# section.
#
# OM_INGESTION_VERSION must match ALDI's OM server version EXACTLY to
# avoid schema-mismatch 4xx at runtime. Current ALDI server = 1.11.0.0.
# Bump only after ALDI Platform Team upgrades their server in lockstep.

ARG OM_INGESTION_VERSION=1.11.0.0
FROM docker.getcollate.io/openmetadata/ingestion:${OM_INGESTION_VERSION}

# The Collate base image guards against root-side pip installs and
# expects the `airflow` user. Switch first, set a writable workdir
# under that user's home, copy with chown.
USER airflow
WORKDIR /home/airflow/connector-build

# Copy only what the connector needs at runtime. Tests and the bridge
# code stay out of the ingestion image -- the bridge ships as its own
# container (Dockerfile.bridge).
COPY --chown=airflow:airflow pyproject.toml ./
COPY --chown=airflow:airflow connector ./connector

# `.[sample-data]` pulls solace-pubsubplus so sampleDataEnabled=true
# works inside Airflow workers. Without the extra the connector still
# works in metadata-only mode.
# The OM image ships a venv that the `airflow` user can write to, so a
# normal install lands the package in the same site-packages used by
# the Airflow workers at runtime.
RUN pip install --no-cache-dir ".[sample-data]"

# Smoke test: import succeeds inside the image (catches missing deps
# early, fails the build instead of failing the workflow run in OM).
RUN python -c "from connector.event_portal_connector import SolaceEventPortalSource; \
               from connector.filters import FilterPattern; \
               from connector.schema_parsers import parse_fields; \
               print('connector import OK')"
