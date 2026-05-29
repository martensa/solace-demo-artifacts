"""Dedicated cross-system lineage Source for the Solace Event Portal
connector.

Wave 2 (#66 + #50 + #60 + #65 framework). Runs as its own
``metadata ingest -c <yaml>`` job, ideally on a slower cadence than
the metadata source (which emits Topics + Pipelines). Its job is
narrow:

* read cross-system lineage edges from a YAML mapping in the workflow
  config (#50) -- e.g. ``SAP -> EP-Pipeline -> Kafka -> Snowflake``
* read EP Custom Attribute ``externalSourceOmFqn`` /
  ``externalSinkOmFqn`` on each EP App to fan-out implicit external
  edges (#60)
* dynamic system-vs-pipeline classification (#65), if enabled

Everything else (entity emission, schema fields, within-EP linked-apps
lineage) stays in :mod:`connector.event_portal_connector`. Splitting
them means a lineage-side bug or an EP API hiccup on the cross-system
endpoints does not derail the metadata pass.

The class is deliberately a thin scaffold in Wave 2 Pause 1: subsequent
sub-tickets (#50, #60, #65) fill in the per-feature emit logic.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from metadata.generated.schema.metadataIngestion.workflow import (
    Source as WorkflowSource,
)
from metadata.ingestion.api.models import Either
from metadata.ingestion.api.steps import InvalidSourceException, Source
from metadata.ingestion.ometa.ometa_api import OpenMetadata

from .event_portal_client import EventPortalClient

logger = logging.getLogger(__name__)

# Wave 2 (#60) -- the two EP Custom Attributes ALDI agreed on
# (see docs/asset-mapping-spec.md, Cluster 5). Values are OM FQNs
# pointing at non-EP entities (SAP table, Snowflake table, Databricks
# notebook, ...). Multiple values per CA = multiple edges.
CA_EXTERNAL_SOURCE = "externalSourceOmFqn"
CA_EXTERNAL_SINK = "externalSinkOmFqn"


class EventPortalLineageSource(Source):
    """Cross-system lineage emitter for the Solace EP connector.

    Wave 2 scaffold. Currently a no-op; per-feature emission is added
    in subsequent commits:

    - ``_emit_yaml_lineage_edges()`` (#50)
    - ``_emit_external_system_ca_edges()`` (#60)
    - ``_emit_dynamic_classification_edges()`` (#65)
    """

    def __init__(self, config: WorkflowSource, metadata: OpenMetadata):
        super().__init__()
        self.config = config
        self.metadata = metadata
        self.service_name = config.serviceName
        self.source_config = config.sourceConfig.config if config.sourceConfig else None

        # Connection options come in via the same path as the metadata
        # source so a workflow YAML can re-use its existing block.
        opts = self._read_options(config)
        self._yaml_edges: List[Dict[str, Any]] = list(
            opts.get("lineageEdges") or []
        )
        self._classification_cfg: Dict[str, Any] = dict(
            opts.get("appClassification") or {}
        )
        # Service FQNs to search when resolving external-system FQNs.
        self._cross_system_services: List[str] = list(
            opts.get("crossSystemServiceFqns") or []
        )

        # EP client for #60 + #65 -- shared shape with metadata source.
        self._ep_client = EventPortalClient(
            base_url=opts.get("apiUrl", "https://api.solace.cloud/api/v2"),
            api_token=opts.get("apiToken"),
        )
        # Lazy: def_id -> CA name (for resolving CA values on entities).
        self._ca_def_name_by_id: Optional[Dict[str, str]] = None

    # -------------------------------------------------------------- factories

    @classmethod
    def create(
        cls,
        config_dict: Dict[str, Any],
        metadata: OpenMetadata,
        pipeline_name: Optional[str] = None,
    ) -> "EventPortalLineageSource":
        config = WorkflowSource.model_validate(config_dict)
        if not config.serviceName:
            raise InvalidSourceException("Service name is required")
        return cls(config, metadata)

    @staticmethod
    def _read_options(config: WorkflowSource) -> Dict[str, Any]:
        sc = config.serviceConnection
        cfg = getattr(sc, "root", None) or getattr(sc, "__root__", None) or sc
        cfg = cfg.config
        raw = getattr(cfg, "connectionOptions", None)
        if not raw:
            return {}
        inner = getattr(raw, "root", None) or getattr(raw, "__root__", None) or raw
        return dict(inner or {})

    # ----------------------------------------------------------- workflow hooks

    def prepare(self) -> None:
        pass

    def test_connection(self) -> None:
        # Lineage source only reads OM + YAML; no new connection target.
        pass

    def close(self) -> None:
        pass

    def get_status(self):
        return self.status

    def _iter(self) -> Iterable[Either]:
        # Pause 1 scaffold: each per-feature emitter yields nothing yet.
        yield from self._emit_yaml_lineage_edges()
        yield from self._emit_external_system_ca_edges()
        yield from self._emit_dynamic_classification_edges()

    # ------------------------------------------------------- emission stubs
    # Filled in by subsequent Wave 2 sub-tickets.

    def _emit_yaml_lineage_edges(self) -> Iterable[Either]:
        """#50 -- emit one AddLineageRequest per entry in ``lineageEdges``.

        Each YAML entry has shape::

            {from: <om-fqn>, to: <om-fqn>, description: <optional>,
             entityType: <optional, default 'topic'>}

        We resolve each FQN to an entity id via OM's REST API (any
        entity-type that accepts ``GET /v1/<type>/name/<fqn>`` works:
        topic, pipeline, table, container, dashboard, ...). If either
        side fails to resolve we skip the edge with a WARN so the
        connector run still surfaces the rest of the YAML.
        """
        if not self._yaml_edges:
            return
        ok = 0
        skip = 0
        for entry in self._yaml_edges:
            if not isinstance(entry, dict):
                continue
            from_fqn = entry.get("from")
            to_fqn = entry.get("to")
            description = entry.get("description") or "Cross-system lineage (YAML)"
            from_type = (entry.get("fromEntityType") or "topic").lower()
            to_type = (entry.get("toEntityType") or "topic").lower()
            if not from_fqn or not to_fqn:
                logger.warning(
                    "Lineage YAML entry missing 'from' or 'to' FQN; skipping: %r",
                    entry,
                )
                skip += 1
                continue
            from_id = self._resolve_entity_id(from_type, from_fqn)
            to_id = self._resolve_entity_id(to_type, to_fqn)
            if not from_id or not to_id:
                logger.warning(
                    "Lineage YAML edge unresolved (from=%s id=%s, to=%s id=%s)",
                    from_fqn, from_id, to_fqn, to_id,
                )
                skip += 1
                continue
            req = _build_lineage_request(
                from_id=from_id, from_type=from_type,
                to_id=to_id, to_type=to_type,
                description=description,
            )
            if req is not None:
                self._post_lineage(req)
                ok += 1
        logger.info(
            "Cross-system YAML lineage: %d edges emitted, %d skipped.", ok, skip,
        )
        return
        yield  # pragma: no cover -- generator placeholder

    def _emit_external_system_ca_edges(self) -> Iterable[Either]:
        """#60 -- emit lineage edges from EP Application Custom Attributes
        ``externalSourceOmFqn`` and ``externalSinkOmFqn``.

        For each EP application's customAttributes:

        * ``externalSourceOmFqn`` value -> lineage from that OM entity
          to the app's OM Pipeline (the external system feeds the app).
        * ``externalSinkOmFqn`` value -> lineage from the app's
          Pipeline to that OM entity (the app feeds the external
          system).

        Each CA may carry a comma-separated list of FQNs so a single
        application can fan out to multiple downstream / upstream
        systems without further EP changes.
        """
        from .mappers import app_pipeline_fqn

        try:
            id_to_ca_name = self._ca_def_name_id_map()
        except Exception as exc:
            logger.warning("Could not load EP CA definitions: %s", exc)
            return
        source_id = next(
            (i for i, n in id_to_ca_name.items() if n == CA_EXTERNAL_SOURCE), None
        )
        sink_id = next(
            (i for i, n in id_to_ca_name.items() if n == CA_EXTERNAL_SINK), None
        )
        if not source_id and not sink_id:
            logger.info(
                "Neither %s nor %s CA defined in EP; skipping external-system "
                "edges. ALDI Platform Team adds these via "
                "/architecture/customAttributeDefinitions.",
                CA_EXTERNAL_SOURCE, CA_EXTERNAL_SINK,
            )
            return

        try:
            domains = self._ep_client.list_application_domains()
        except Exception as exc:
            logger.warning("Could not list EP domains: %s", exc)
            return

        ok = 0
        skip = 0
        for domain in domains:
            try:
                apps = self._ep_client.list_applications(domain["id"])
            except Exception:
                continue
            for app in apps:
                try:
                    latest = self._ep_client.get_latest_application_version(app["id"])
                except Exception:
                    latest = None
                if not latest:
                    continue
                cas = latest.get("customAttributes") or []
                source_fqns = _ca_values(cas, source_id)
                sink_fqns = _ca_values(cas, sink_id)
                if not source_fqns and not sink_fqns:
                    continue
                # Resolve our OM Pipeline FQN for this application version.
                pipe_fqn = f"solace-event-portal-apps.{app_pipeline_fqn(app['name'], str(latest.get('version') or '1.0.0'))}"
                pipe_id = self._resolve_entity_id("pipeline", pipe_fqn)
                if not pipe_id:
                    logger.debug(
                        "Pipeline %s not in OM yet; #60 edge deferred.",
                        pipe_fqn,
                    )
                    skip += 1
                    continue
                for src_fqn in source_fqns:
                    src_id = self._resolve_any_entity_id(src_fqn)
                    if not src_id:
                        skip += 1
                        continue
                    req = _build_lineage_request(
                        from_id=src_id, from_type="table",
                        to_id=pipe_id, to_type="pipeline",
                        description=(
                            f"External source -> EP application "
                            f"`{app['name']}` (CA {CA_EXTERNAL_SOURCE})"
                        ),
                    )
                    if req is not None:
                        self._post_lineage(req)
                        ok += 1
                for sink_fqn in sink_fqns:
                    sink_id_resolved = self._resolve_any_entity_id(sink_fqn)
                    if not sink_id_resolved:
                        skip += 1
                        continue
                    req = _build_lineage_request(
                        from_id=pipe_id, from_type="pipeline",
                        to_id=sink_id_resolved, to_type="table",
                        description=(
                            f"EP application `{app['name']}` -> external sink "
                            f"(CA {CA_EXTERNAL_SINK})"
                        ),
                    )
                    if req is not None:
                        self._post_lineage(req)
                        ok += 1
        logger.info(
            "External-system CA lineage: %d edges emitted, %d skipped.", ok, skip,
        )
        return
        yield  # pragma: no cover -- generator placeholder

    def _ca_def_name_id_map(self) -> Dict[str, str]:
        if self._ca_def_name_by_id is None:
            try:
                defs = self._ep_client.list_custom_attribute_definitions()
            except Exception:
                defs = []
            self._ca_def_name_by_id = {
                d["id"]: d["name"]
                for d in defs
                if d.get("id") and d.get("name")
            }
        return self._ca_def_name_by_id

    def _resolve_any_entity_id(self, fqn: str) -> Optional[str]:
        """Try the common entity types in order until one resolves.

        FQN syntax doesn't tell us the entity type, so probe Table
        first (most common cross-system target), then Container,
        Topic, Pipeline, Dashboard, MlModel.
        """
        for kind in ("table", "container", "topic", "pipeline", "dashboard", "mlmodel"):
            eid = self._resolve_entity_id(kind, fqn)
            if eid:
                return eid
        return None

    def _emit_dynamic_classification_edges(self) -> Iterable[Either]:
        """#65 -- emit edges via dynamic system-vs-pipeline classification
        of EP applications, mirroring the Databricks ``crossDatabaseServiceNames``
        pattern."""
        if not self._classification_cfg.get("enabled"):
            return
        logger.info(
            "EventPortalLineageSource: appClassification enabled, search "
            "services=%s (dryRun=%s); TBD in #65.",
            self._cross_system_services,
            self._classification_cfg.get("dryRun", True),
        )
        return
        yield  # pragma: no cover -- generator stub

    # ----------------------------------------------------------- shared helpers

    # Entity-kind string -> OM SDK entity class. Lazy imports so the
    # source module loads in slim test environments.
    _ENTITY_CLASS_BY_TYPE: Dict[str, str] = {
        "topic": "metadata.generated.schema.entity.data.topic:Topic",
        "pipeline": "metadata.generated.schema.entity.data.pipeline:Pipeline",
        "table": "metadata.generated.schema.entity.data.table:Table",
        "container": "metadata.generated.schema.entity.data.container:Container",
        "dashboard": "metadata.generated.schema.entity.data.dashboard:Dashboard",
        "mlmodel": "metadata.generated.schema.entity.data.mlmodel:MlModel",
    }

    @classmethod
    def _entity_class(cls, entity_type: str):
        spec = cls._ENTITY_CLASS_BY_TYPE.get(entity_type.lower())
        if not spec:
            return None
        module_path, attr = spec.split(":")
        try:
            module = __import__(module_path, fromlist=[attr])
            return getattr(module, attr)
        except Exception:
            return None

    def _resolve_entity_id(
        self, entity_type: str, fqn: str
    ) -> Optional[str]:
        """Look up an OM entity by FQN, return its id as a string."""
        cls = self._entity_class(entity_type)
        if cls is None:
            logger.warning(
                "Unknown entity type %s; cannot resolve %s", entity_type, fqn,
            )
            return None
        try:
            ent = self.metadata.get_by_name(entity=cls, fqn=fqn)
        except Exception:
            logger.debug("get_by_name failed for %s/%s", entity_type, fqn)
            return None
        if ent is None:
            return None
        ent_id = getattr(ent, "id", None)
        if ent_id is None:
            return None
        return str(getattr(ent_id, "root", ent_id))

    def _post_lineage(self, request) -> None:
        """Synchronously POST an AddLineageRequest, swallow failures."""
        try:
            self.metadata.add_lineage(data=request)
        except Exception:
            logger.exception("add_lineage failed; continuing")


def _ca_values(custom_attributes: List[Dict[str, Any]], def_id: Optional[str]) -> List[str]:
    """Extract values for one EP CA definition id; split comma-list."""
    if not def_id:
        return []
    out: List[str] = []
    for ca in custom_attributes:
        if ca.get("customAttributeDefinitionId") != def_id:
            continue
        raw = ca.get("value") or ""
        for chunk in str(raw).split(","):
            s = chunk.strip()
            if s:
                out.append(s)
    return out


def _build_lineage_request(
    *,
    from_id: str,
    from_type: str,
    to_id: str,
    to_type: str,
    description: str = "",
):
    """Build an AddLineageRequest for a generic Entity<->Entity edge.

    Lives at module level rather than on the class so it stays cleanly
    unit-testable. ``LineageDetails.source = Manual`` (OM 1.11+
    requirement) is set when the SDK exposes the enum value.
    """
    try:
        from metadata.generated.schema.api.lineage.addLineage import (
            AddLineageRequest,
        )
        from metadata.generated.schema.type.entityLineage import (
            EntitiesEdge,
            LineageDetails,
        )
        from metadata.generated.schema.type.entityReference import EntityReference
    except Exception:  # pragma: no cover - depends on OM version
        logger.warning(
            "OM Lineage SDK not importable; skipping cross-system edge."
        )
        return None
    lineage_source_value = None
    try:
        from metadata.generated.schema.type.entityLineage import LineageSource
        lineage_source_value = LineageSource.Manual
    except Exception:  # pragma: no cover
        pass
    details_kwargs = {
        "description": description or "Cross-system lineage (EP connector)",
    }
    if lineage_source_value is not None:
        details_kwargs["source"] = lineage_source_value
    return AddLineageRequest(
        edge=EntitiesEdge(
            fromEntity=EntityReference(id=from_id, type=from_type),
            toEntity=EntityReference(id=to_id, type=to_type),
            lineageDetails=LineageDetails(**details_kwargs),
        )
    )
