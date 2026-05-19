# Bake the Solace Event Portal connector into the OpenMetadata ingestion image
# so it can be selected from the UI and run by Airflow.
#
# Build:
#   docker build -t my-org/openmetadata-ingestion-solace:1.6.0 .
#
# Reference in your OM deployment (docker-compose):
#   ingestion:
#     image: my-org/openmetadata-ingestion-solace:1.6.0

ARG OM_INGESTION_VERSION=1.6.0
FROM docker.getcollate.io/openmetadata/ingestion:${OM_INGESTION_VERSION}

USER root
WORKDIR /opt/connectors/solace-eventportal

COPY pyproject.toml ./
COPY connector ./connector

RUN pip install --no-cache-dir .

USER airflow
