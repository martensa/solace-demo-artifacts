"""ServiceSpec registration for the Solace Event Portal connector.

Wave 2 (#66): wire the connector into OpenMetadata's native
``BaseSpec`` so the ingestion workflow can be selected as
``type: messaging`` with this package's source classes auto-resolved.

Two Source classes are registered:

- ``SolaceEventPortalSource`` -- the existing monolithic metadata
  source. Emits Domains, Topics (with parsed schemas), Pipelines
  (per EP application) and within-EP Pipeline<->Topic lineage. This
  is what existing workflow YAMLs already reference via the
  ``sourcePythonClass`` field; it stays backward-compatible.

- ``EventPortalLineageSource`` -- a dedicated lineage workflow for
  the *cross-system* edges (#50 YAML mapping, #60 external-system
  via EP Custom Attribute, #65 dynamic system-vs-pipeline
  classification). Runs as a separate ``metadata ingest`` job so it
  can be scheduled independently from the metadata pass and so a
  lineage-side failure does not abort topic ingestion.

Mirrors the Databricks pattern documented in
``docs/asset-mapping-spec.md`` (Cluster 2.5) and OpenMetadata's own
``metadata/ingestion/source/messaging/kafka/service_spec.py`` --
keep this file tiny so the wiring stays grokable from one screen.
"""
from __future__ import annotations

from metadata.utils.service_spec import BaseSpec

from connector.event_portal_connector import SolaceEventPortalSource
from connector.lineage_source import EventPortalLineageSource

ServiceSpec = BaseSpec(
    metadata_source_class=SolaceEventPortalSource,
    lineage_source_class=EventPortalLineageSource,
)
