"""OpenMetadata custom Source for Solace Event Portal.

Two modes:

* `rest_api` (default) - walks the Event Portal v2 REST API and emits
  Domains, Topics, Data Products and Lineage edges.
* `asyncapi` - pulls AsyncAPI 2.x specs per application version and emits
  Topics directly from those specs.

This Source is also the canonical reconciliation path: scheduling it daily
catches any change events the webhook bridge missed.

Register in OpenMetadata under:
  Settings -> Services -> Messaging -> Add New Service -> Custom

with Source Python Class Name:
  connector.event_portal_connector.SolaceEventPortalSource

Connection options are read from the service's `connectionOptions` map.
See README for the full option reference.
"""
from __future__ import annotations

import logging
import traceback
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from metadata.generated.schema.metadataIngestion.workflow import (
    Source as WorkflowSource,
)
from metadata.ingestion.api.models import Either, StackTraceError
from metadata.ingestion.api.steps import InvalidSourceException, Source
from metadata.ingestion.ometa.ometa_api import OpenMetadata

from .asyncapi_parser import asyncapi_to_topic_requests, parse_asyncapi
from .event_portal_client import EventPortalClient
from .filters import FilterPattern, parse_filter_options
from .mappers import (
    app_to_pipeline_request,
    app_topic_lineage_request,
    domain_to_create_request,
    event_to_topic_request,
    modeled_mesh_to_data_product_request,
    pipeline_to_pipeline_lineage_request,
    topic_fqn,
)
from .owner_resolver import OwnerResolver

logger = logging.getLogger(__name__)


class SolaceEventPortalSource(Source):
    """Custom OpenMetadata connector for Solace Event Portal."""

    def __init__(self, config: WorkflowSource, metadata: OpenMetadata):
        super().__init__()
        self.config = config
        self.metadata = metadata
        self.service_name = config.serviceName

        opts = self._read_options(config)
        self.api_url: str = opts.get("apiUrl", "https://api.solace.cloud/api/v2")
        self.api_token: Optional[str] = opts.get("apiToken")
        self.mode: str = (opts.get("mode") or "rest_api").lower()
        self.include_lineage: bool = _as_bool(opts.get("includeLineage", "true"))
        # Wave 1 (#54): default flipped to "true" -- ALDI explicitly
        # asked for full version history in OM (Cluster 3.5). Each per-
        # version Topic / Pipeline gets a `eventPortalIsLatestVersion`
        # custom property so the OM UI can filter to current versions
        # by default without losing history from the catalog.
        self.ingest_all_versions: bool = _as_bool(opts.get("ingestAllVersions", "true"))
        self.emit_domains: bool = _as_bool(opts.get("emitDomains", "true"))
        # Default OFF: Solace Cloud EP v2 does not expose
        # /architecture/modeledEventMeshes (verified by smoke test in
        # 2026-05). DataProduct mapping needs a higher-tier edition.
        # Enable explicitly with emitDataProducts=true if your edition
        # supports it; the EP client tolerates a 404 gracefully either way.
        self.emit_data_products: bool = _as_bool(opts.get("emitDataProducts", "false"))
        self.since: Optional[str] = opts.get("since") or None
        # EP-UI back-link configuration: base URL + per-entity path
        # templates. All overridable via connectionOptions so the user
        # can flip to a different SSO / regional console without a code
        # change or image rebuild.
        from .mappers import EpUrls
        from .property_keys import (
            DEFAULT_EP_CONSOLE_URL,
            DEFAULT_EP_DOMAIN_PATH,
            DEFAULT_EP_EVENT_PATH,
            DEFAULT_EP_EVENT_VERSION_PATH,
            DEFAULT_EP_SCHEMA_PATH,
            DEFAULT_EP_SCHEMA_VERSION_PATH,
            DEFAULT_EP_APPLICATION_PATH,
            DEFAULT_EP_APPLICATION_VERSION_PATH,
        )
        self.ep_urls = EpUrls(
            base=opts.get("epConsoleUrl") or DEFAULT_EP_CONSOLE_URL,
            domain_path=opts.get("epDomainUrlTemplate") or DEFAULT_EP_DOMAIN_PATH,
            event_path=opts.get("epEventUrlTemplate") or DEFAULT_EP_EVENT_PATH,
            event_version_path=(
                opts.get("epEventVersionUrlTemplate") or DEFAULT_EP_EVENT_VERSION_PATH
            ),
            schema_path=opts.get("epSchemaUrlTemplate") or DEFAULT_EP_SCHEMA_PATH,
            schema_version_path=(
                opts.get("epSchemaVersionUrlTemplate") or DEFAULT_EP_SCHEMA_VERSION_PATH
            ),
            application_path=(
                opts.get("epApplicationUrlTemplate") or DEFAULT_EP_APPLICATION_PATH
            ),
            application_version_path=(
                opts.get("epApplicationVersionUrlTemplate")
                or DEFAULT_EP_APPLICATION_VERSION_PATH
            ),
        )

        # Allow-list-first filter patterns. Empty `includes` => default-deny:
        # nothing in that category is ingested. See connector/filters.py.
        filters = parse_filter_options(opts)
        self.domain_filter: FilterPattern = filters["domainFilterPattern"]
        self.event_filter: FilterPattern = filters["eventFilterPattern"]
        self.schema_filter: FilterPattern = filters["schemaFilterPattern"]
        self.application_filter: FilterPattern = filters["applicationFilterPattern"]

        if self.domain_filter.is_empty_allow_list:
            logger.warning(
                "domainFilterPattern.includes is empty - allow-list-only "
                "default means no domains will be ingested. Set "
                "domainFilterPattern.includes to opt in."
            )

        self.client = EventPortalClient(base_url=self.api_url, api_token=self.api_token)

        # Resolves EP owner e-mails to OM users via the OM REST API.
        # Negative results are cached too so we don't keep re-querying for
        # owners that are not Keycloak users (yet).
        self.owner_resolver = OwnerResolver(self.metadata)
        # Default OFF: EP v2 returns user-ids (e.g. "udz8x00uz2o") on
        # `createdBy`/`changedBy`, NOT e-mails, and there is no public
        # `/users/{id}` lookup. Resolving against OM users via e-mail
        # therefore needs an explicit static mapping (planned: option
        # `userIdToEmailMap`). Enable resolveOwners=true only once your
        # EP edition either ships e-mails on owner fields or you wire
        # up the static map.
        self.resolve_owners: bool = _as_bool(opts.get("resolveOwners", "false"))

        # Sample-data via live broker subscribe (opt-in).
        self.sample_data_enabled: bool = _as_bool(
            opts.get("sampleDataEnabled", "false")
        )
        # Buffered as (topic_fqn, topic_address) tuples during the topic pass
        # and drained at the end of _iter_rest_api into the broker session.
        self._pending_samples: List[Tuple[str, str]] = []

        # Indexes built during pass 1 + consumed by pass 2 (lineage).
        # event_version_id -> topic FQN
        self._event_version_to_topic_fqn: Dict[str, str] = {}
        # event_version_id -> set of modeled-mesh ids it participates in
        self._event_version_to_meshes: Dict[str, Set[str]] = {}

        # Wave 1 (#43): EP custom attribute -> OM Tag bridge.
        # `customAttributeTagExclude` is a comma-separated list (or YAML
        # list) of CA names to skip (high-cardinality identity-like CAs
        # whose values would explode the tag space).
        raw_exclude = opts.get("customAttributeTagExclude") or ""
        if isinstance(raw_exclude, list):
            self._ca_exclude: Set[str] = {str(s).strip() for s in raw_exclude if s}
        else:
            self._ca_exclude = {
                s.strip() for s in str(raw_exclude).split(",") if s.strip()
            }
        # def-id -> CA name. Populated lazily on first use to avoid an
        # extra REST call when there are no CAs.
        self._ca_def_name_by_id: Optional[Dict[str, str]] = None
        # Cache of tags already ensured this run, keyed by FQN.
        self._ca_tag_ensured: Set[str] = set()

        # Wave 2 (#59): within-EP linked-applications lineage.
        # Populated as Pipelines are created during pass 3. The deferred
        # emission at the end of pass 3 then resolves each association's
        # destination via this cache so cross-domain linked apps work
        # regardless of iteration order.
        self._app_version_to_pipeline_id: Dict[str, str] = {}
        # Each entry: (src_pipeline_id, dest_av_id, src_app_name).
        # dest_app_name is filled at emit-time once the destination is
        # known (we may not have its name in scope when buffering).
        self._pending_linked_app_emits: List[Tuple[str, str, str]] = []

    # ------------------------------------------------------------- factories

    @classmethod
    def create(
        cls,
        config_dict: Dict[str, Any],
        metadata: OpenMetadata,
        pipeline_name: Optional[str] = None,
    ) -> "SolaceEventPortalSource":
        # Pydantic v2 idiom. `parse_obj()` is deprecated since pydantic 2.0
        # and removed in 2.10 (which OM 1.11+ may pull in transitively).
        config = WorkflowSource.model_validate(config_dict)
        if not config.serviceName:
            raise InvalidSourceException("Service name is required")
        return cls(config, metadata)

    @staticmethod
    def _read_options(config: WorkflowSource) -> Dict[str, Any]:
        # Pydantic v2 (OM 1.6+) exposes RootModel content via `.root`;
        # pydantic v1 (OM <= 1.5) used `.__root__`. Support both so the
        # connector works against either OM line.
        sc = config.serviceConnection
        cfg = getattr(sc, "root", None) or getattr(sc, "__root__", None) or sc
        cfg = cfg.config
        raw = getattr(cfg, "connectionOptions", None)
        if not raw:
            return {}
        inner = getattr(raw, "root", None) or getattr(raw, "__root__", None) or raw
        return dict(inner or {})

    # -------------------------------------------------------- workflow hooks

    def prepare(self) -> None:
        from .test_connection import run_test_connection

        report = run_test_connection(
            self.client,
            domain_filter=self.domain_filter,
            broker_config=self._broker_config_or_none(),
        )
        if not report.passed:
            raise InvalidSourceException(
                "Solace Event Portal connection check failed:\n" + str(report)
            )

    def test_connection(self) -> None:
        """Multi-step diagnostic surfaced in the OM UI 'Test Connection' button."""
        from .test_connection import run_test_connection

        report = run_test_connection(
            self.client,
            domain_filter=self.domain_filter,
            broker_config=self._broker_config_or_none(),
        )
        if not report.passed:
            raise InvalidSourceException(str(report))

    def _broker_config_or_none(self) -> Optional[Dict[str, Any]]:
        """Pull broker connection params from connectionOptions if sample data is on.

        Returns None when sampleDataEnabled is false (the broker check is then
        skipped). All four params (host, vpn, username, password) are required
        when sample data is on -- missing keys cause the test-connection step
        to fail with a clear message.
        """
        opts = self._read_options(self.config)
        if not _as_bool(opts.get("sampleDataEnabled", "false")):
            return None
        return {
            "host": opts.get("brokerHost") or "",
            "vpn": opts.get("brokerVpn") or "",
            "username": opts.get("brokerUsername") or "",
            "password": opts.get("brokerPassword") or "",
        }

    def close(self) -> None:
        self.client.close()

    def get_status(self):
        return self.status

    # --------------------------------------------------------- main iterator

    def _iter(self) -> Iterable[Either]:
        if self.mode == "asyncapi":
            yield from self._iter_asyncapi()
            return
        if self.mode != "rest_api":
            yield self._fail(
                "unsupported-mode",
                ValueError(f"Mode '{self.mode}' not supported"),
            )
            return
        yield from self._iter_rest_api()

    # --------------------------------------------------------- rest_api mode

    def _iter_rest_api(self) -> Iterable[Either]:
        try:
            all_domains = self.client.list_application_domains(since=self.since)
        except Exception as exc:
            yield self._fail("list-application-domains", exc)
            return

        # Allow-list-only: domains whose `name` does not match
        # domainFilterPattern.includes (and isn't excluded) are dropped here.
        domains = [
            d for d in all_domains if self.domain_filter.match(d.get("name"))
        ]
        logger.info(
            "Event Portal returned %d application domains, %d pass the filter",
            len(all_domains), len(domains),
        )
        if not domains:
            return

        # Pre-pass: modeled meshes -> {mesh_id: [domain_id, ...]}, plus the
        # reverse index used to stamp Topics with their mesh ids.
        try:
            meshes = (
                self.client.list_modeled_event_meshes(since=self.since)
                if self.emit_data_products
                else []
            )
        except Exception as exc:
            yield self._fail("list-modeled-event-meshes", exc)
            meshes = []
        mesh_by_domain: Dict[str, List[Dict[str, Any]]] = {}
        for mesh in meshes:
            for did in mesh.get("applicationDomainIds") or []:
                mesh_by_domain.setdefault(did, []).append(mesh)

        # Pass 0 - emit Domains (one per Application Domain).
        if self.emit_domains:
            for domain in domains:
                owner = self._resolve(domain)
                req = domain_to_create_request(domain, owner=owner)
                if req is not None:
                    yield Either(right=req)

        # Pass 1 - one Topic per event version, tagged with state + custom
        # properties; plus synthetic Application Topics for the lineage pass.
        for domain in domains:
            yield from self._emit_domain_topics(domain, mesh_by_domain.get(domain["id"]))

        # Pass 2 - Data Products (Modeled Event Meshes), with topic FQNs
        # discovered in pass 1 as their assets.
        if self.emit_data_products:
            for mesh in meshes:
                domain_name = self._mesh_domain_name(mesh, domains)
                req = modeled_mesh_to_data_product_request(mesh, domain_name)
                if req is not None:
                    yield Either(right=req)

        # Pass 3 - Application <-> Topic lineage edges.
        if self.include_lineage:
            for domain in domains:
                yield from self._emit_domain_lineage(domain)
            # Pass 3.5 - within-EP Linked-Applications lineage (#59).
            # Runs AFTER all domains so cross-domain destinations resolve.
            yield from self._emit_linked_app_lineage_edges()

        # Pass 4 - opt-in sample data via live broker subscribe. Runs last
        # because Topics must exist in OM before we can PUT sampleData onto
        # them. Errors are logged and swallowed: a broker outage must not
        # fail the whole metadata ingest.
        if self.sample_data_enabled and self._pending_samples:
            self._collect_and_push_samples()

    # ----------------------------------------------------------- topic pass

    def _emit_domain_topics(
        self,
        domain: Dict[str, Any],
        meshes: Optional[List[Dict[str, Any]]],
    ) -> Iterable[Either]:
        domain_name = domain.get("name") or domain.get("id")
        try:
            all_events = self.client.list_events(domain["id"], since=self.since)
        except Exception as exc:
            yield self._fail(f"list-events:{domain_name}", exc)
            return

        # Apply eventFilterPattern. When unset (default-deny), zero events are
        # forwarded — domain-level governance enforced at the next layer.
        events = [
            e for e in all_events if self.event_filter.match(e.get("name"))
        ]
        if all_events and not events:
            logger.info(
                "Domain %s: %d events found, none pass eventFilterPattern - skipping",
                domain_name, len(all_events),
            )
            return

        mesh_ids = [m["id"] for m in (meshes or []) if m.get("id")]

        for event in events:
            try:
                versions = (
                    self.client.list_event_versions(event["id"])
                    if self.ingest_all_versions
                    else [self.client.get_latest_event_version(event["id"])]
                )
                # Wave 1 (#54): mark the highest-semver version so the OM
                # UI can default-filter to current. Cheap because we
                # already have all versions in memory.
                latest_id = _latest_version_id(versions)
                for version in versions:
                    if not version:
                        continue
                    schema_payload = self._resolve_schema(version)
                    request = event_to_topic_request(
                        service_name=self.service_name,
                        domain=domain,
                        event=event,
                        event_version=version,
                        schema_payload=schema_payload,
                        modeled_mesh_ids=mesh_ids or None,
                        owner=self._resolve(event, domain),
                        ep_urls=self.ep_urls,
                        attach_to_domain=self.emit_domains,
                        is_latest_version=(
                            version.get("id") == latest_id if latest_id else None
                        ),
                        # Wave 1 (#43): merge EP custom-attribute tags from
                        # both the event and the event-version payloads.
                        custom_attribute_tags=(
                            self._custom_attribute_tags(event)
                            + self._custom_attribute_tags(version)
                        ),
                    )
                    fqn = topic_fqn(
                        self.service_name,
                        event.get("name") or "unnamed-event",
                        str(version.get("version") or "1.0.0"),
                    )
                    self._event_version_to_topic_fqn[version["id"]] = fqn
                    if self.sample_data_enabled:
                        from .mappers import extract_topic_address
                        addr = extract_topic_address(version)
                        if addr:
                            self._pending_samples.append((fqn, addr))
                    yield Either(right=request)
            except Exception as exc:
                yield self._fail(
                    f"event:{event.get('name', event.get('id'))}", exc
                )

    def _resolve_schema(
        self, event_version: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        schema_version_id = event_version.get("schemaVersionId")
        if not schema_version_id:
            return None
        schema_version = self.client.get_schema_version(schema_version_id)
        if not schema_version:
            return None
        schema_id = schema_version.get("schemaId")
        schema = self.client.get_schema(schema_id) if schema_id else None
        # schemaFilterPattern is applied here. A schema dropped by the filter
        # leaves the Topic without messageSchema -- the Topic itself still
        # ingests so lineage and lifecycle data are not lost.
        if schema and not self.schema_filter.match(schema.get("name")):
            logger.debug(
                "Schema %s blocked by schemaFilterPattern - omitting from topic",
                schema.get("name"),
            )
            return None
        return {"version": schema_version, "schema": schema}

    # ----------------------------------------------------------- lineage pass

    def _emit_domain_lineage(
        self, domain: Dict[str, Any]
    ) -> Iterable[Either]:
        try:
            all_apps = self.client.list_applications(domain["id"], since=self.since)
        except Exception as exc:
            yield self._fail(f"list-applications:{domain.get('name')}", exc)
            return

        # applicationFilterPattern keeps the ingestion focused on the apps a
        # team actually owns -- noise from neighbouring teams' apps in shared
        # domains gets dropped here.
        apps = [
            a for a in all_apps if self.application_filter.match(a.get("name"))
        ]
        if all_apps and not apps:
            logger.info(
                "Domain %s: %d apps found, none pass applicationFilterPattern",
                domain.get("name"), len(all_apps),
            )
            return

        for app in apps:
            try:
                versions = (
                    self.client.list_application_versions(app["id"])
                    if self.ingest_all_versions
                    else [self.client.get_latest_application_version(app["id"])]
                )
                # Wave 1 (#54): mark highest-semver app version too.
                latest_id = _latest_version_id(versions)
                for version in versions:
                    if not version:
                        continue
                    # Build the Pipeline request, then persist it
                    # *synchronously* so we get an OM id back for the
                    # subsequent AddLineage edges. (Yielding via Either
                    # would defer the actual create to the sink loop --
                    # too late for the in-iter lineage emit.)
                    pipeline_request = app_to_pipeline_request(
                        domain=domain, app=app, app_version=version,
                        owner=self._resolve(app, domain),
                        ep_urls=self.ep_urls,
                        attach_to_domain=self.emit_domains,
                        is_latest_version=(
                            version.get("id") == latest_id if latest_id else None
                        ),
                        # Wave 1 (#43): merge EP custom-attribute tags from
                        # both the application and the version payloads.
                        custom_attribute_tags=(
                            self._custom_attribute_tags(app)
                            + self._custom_attribute_tags(version)
                        ),
                    )
                    if pipeline_request is None:
                        continue
                    try:
                        pipeline_entity = self.metadata.create_or_update(
                            data=pipeline_request
                        )
                    except Exception as exc:
                        yield self._fail(
                            f"create-pipeline:{app.get('name')}", exc
                        )
                        continue
                    pipeline_id = str(
                        getattr(
                            getattr(pipeline_entity, "id", None),
                            "root",
                            getattr(pipeline_entity, "id", ""),
                        )
                    )
                    if not pipeline_id:
                        logger.warning(
                            "Pipeline %s persisted but id missing; skipping lineage",
                            pipeline_request.name,
                        )
                        continue

                    # Wave 2 (#59): cache the pipeline-id by EP app-version-id
                    # so the deferred linked-applications emit can look it up.
                    self._app_version_to_pipeline_id[version["id"]] = pipeline_id
                    # And buffer this version's outbound linked-app associations
                    # to be emitted once ALL domains have been processed (so
                    # destinations in not-yet-iterated domains resolve too).
                    for assoc in (
                        version.get("outboundApplicationVersionAssociations") or []
                    ):
                        dest_av = assoc.get("destinationId")
                        if dest_av:
                            self._pending_linked_app_emits.append(
                                (pipeline_id, dest_av, app.get("name") or "")
                            )

                    for ev_id in version.get("declaredProducedEventVersionIds") or []:
                        fqn = self._event_version_to_topic_fqn.get(ev_id)
                        if not fqn:
                            continue
                        topic_id = self._resolve_id("topic", fqn)
                        if not topic_id:
                            continue
                        req = app_topic_lineage_request(
                            topic_id=topic_id,
                            pipeline_id=pipeline_id,
                            app=app,
                            direction="publishes",
                        )
                        if req is not None:
                            self._add_lineage(req)
                    for ev_id in version.get("declaredConsumedEventVersionIds") or []:
                        fqn = self._event_version_to_topic_fqn.get(ev_id)
                        if not fqn:
                            continue
                        topic_id = self._resolve_id("topic", fqn)
                        if not topic_id:
                            continue
                        req = app_topic_lineage_request(
                            topic_id=topic_id,
                            pipeline_id=pipeline_id,
                            app=app,
                            direction="consumes",
                        )
                        if req is not None:
                            self._add_lineage(req)
            except Exception as exc:
                yield self._fail(
                    f"app-lineage:{app.get('name', app.get('id'))}", exc
                )

    def _emit_linked_app_lineage_edges(self) -> Iterable[Either]:
        """Wave 2 (#59): emit Pipeline<->Pipeline edges from buffered
        EP linked-applications associations.

        Runs once after all domains have been processed so cross-domain
        targets are resolvable. Missing destinations (deleted in EP,
        outside the filter, or in a non-ingested domain) are skipped
        with a DEBUG log rather than failing the run.
        """
        if not self._pending_linked_app_emits:
            return
        emitted = 0
        skipped = 0
        for src_pipeline_id, dest_av_id, src_app_name in self._pending_linked_app_emits:
            dest_pipeline_id = self._app_version_to_pipeline_id.get(dest_av_id)
            if not dest_pipeline_id:
                logger.debug(
                    "Linked-apps: destination app-version %s not found in "
                    "this run's pipeline cache; skipping edge.", dest_av_id,
                )
                skipped += 1
                continue
            req = pipeline_to_pipeline_lineage_request(
                source_pipeline_id=src_pipeline_id,
                dest_pipeline_id=dest_pipeline_id,
                source_app_name=src_app_name,
            )
            if req is not None:
                self._add_lineage(req)
                emitted += 1
        logger.info(
            "Linked-apps lineage: %d edges emitted, %d skipped (destination "
            "outside this ingest run).",
            emitted, skipped,
        )
        return
        yield  # pragma: no cover - generator placeholder

    # ------------------------------------------------------------- asyncapi

    def _iter_asyncapi(self) -> Iterable[Either]:
        try:
            all_domains = self.client.list_application_domains(since=self.since)
        except Exception as exc:
            yield self._fail("list-application-domains", exc)
            return
        domains = [
            d for d in all_domains if self.domain_filter.match(d.get("name"))
        ]
        if not domains:
            return

        for domain in domains:
            try:
                all_apps = self.client.list_applications(domain["id"], since=self.since)
            except Exception as exc:
                yield self._fail(f"list-applications:{domain.get('name')}", exc)
                continue
            apps = [
                a for a in all_apps if self.application_filter.match(a.get("name"))
            ]
            for app in apps:
                try:
                    version = self.client.get_latest_application_version(app["id"])
                    if not version:
                        continue
                    raw = self.client.export_application_asyncapi(version["id"])
                    if not raw:
                        continue
                    spec = parse_asyncapi(raw)
                    for request in asyncapi_to_topic_requests(
                        service_name=self.service_name,
                        spec=spec,
                        domain_hint=domain.get("name"),
                    ):
                        yield Either(right=request)
                except Exception as exc:
                    yield self._fail(
                        f"asyncapi:{app.get('name', app.get('id'))}", exc
                    )

    # --------------------------------------------------------- sample data

    def _collect_and_push_samples(self) -> None:
        from .sample_data import BrokerConfig, SampleDataCollector

        opts = self._read_options(self.config)
        broker = BrokerConfig.from_options(opts)
        if broker is None:
            logger.warning(
                "sampleDataEnabled=true but brokerHost not set - skipping samples"
            )
            return
        try:
            with SampleDataCollector(broker) as collector:
                for fqn, address in self._pending_samples:
                    sample = collector.collect(fqn, address)
                    if sample.error:
                        logger.info(
                            "Sample collect for %s skipped: %s", fqn, sample.error,
                        )
                        continue
                    collector.push_to_om(self.metadata, sample)
                    logger.info(
                        "Pushed %d sample message(s) to %s%s",
                        len(sample.messages), fqn,
                        " (truncated)" if sample.truncated else "",
                    )
        except Exception:
            logger.exception("Sample data collection failed; continuing")

    # ----------------------------------------------------------- owner helper

    def _resolve(self, *entities: Dict[str, Any]):
        """Try each EP object in turn until one yields an OM user."""
        if not self.resolve_owners:
            return None
        for ent in entities:
            if not ent:
                continue
            ref = self.owner_resolver.resolve_owner(ent)
            if ref is not None:
                return ref
        return None

    def _add_lineage(self, request) -> None:
        """Synchronously POST an AddLineageRequest to OM.

        The standard `metadata-rest` sink only knows how to dispatch
        Create*Request types -- AddLineageRequest is silently dropped if
        yielded. We post it ourselves and swallow exceptions to a log
        line so a single failed edge does not abort the whole run.
        """
        try:
            self.metadata.add_lineage(data=request)
        except Exception:
            logger.exception("AddLineage failed; continuing")

    def _resolve_id(self, entity_kind: str, fqn: str) -> Optional[str]:
        """Look up an OM entity id by FQN via the ingestion-bot OM client.

        Returns None on miss (lineage edge gets skipped, not crashed).
        Used to satisfy OM 1.6+ AddLineage which requires resolved ids
        on both EntitiesEdge ends.
        """
        try:
            from metadata.generated.schema.entity.data.pipeline import Pipeline
            from metadata.generated.schema.entity.data.topic import Topic
        except Exception:
            logger.warning("OM entity types not importable; skipping resolve")
            return None
        cls = {"pipeline": Pipeline, "topic": Topic}.get(entity_kind)
        if cls is None:
            logger.warning("Unknown entity_kind for id-resolve: %s", entity_kind)
            return None
        try:
            ent = self.metadata.get_by_name(entity=cls, fqn=fqn)
        except Exception:
            logger.debug("get_by_name failed for %s/%s", entity_kind, fqn)
            return None
        if ent is None:
            return None
        ent_id = getattr(ent, "id", None)
        # OM 1.6 returns id as a UUID pydantic field
        if ent_id is None:
            return None
        return str(getattr(ent_id, "root", ent_id))

    # -------------------------------------------------- custom attribute tags

    def _ca_name_by_id_map(self) -> Dict[str, str]:
        """Lazy-load EP custom-attribute definitions and build an id→name map."""
        if self._ca_def_name_by_id is None:
            try:
                defs = self.client.list_custom_attribute_definitions()
            except Exception as exc:
                logger.warning("CA definition fetch failed: %s", exc)
                defs = []
            self._ca_def_name_by_id = {
                d["id"]: d["name"]
                for d in defs
                if d.get("id") and d.get("name")
                and d["name"] not in self._ca_exclude
            }
        return self._ca_def_name_by_id

    def _custom_attribute_tags(self, entity: Dict[str, Any]) -> list:
        # Return type omitted (TagLabel imported inside body) to avoid
        # forward-reference at module-load time.
        """Build a list of TagLabels from an EP entity's customAttributes.

        Lazy-creates the Tag entity in OM the first time we see a (CA-name,
        value) combo. Excluded CAs (per workflow `customAttributeTagExclude`)
        are dropped silently.

        EP customAttribute shape (verified seall 2026-05):
            entity["customAttributes"] = [
                {"customAttributeDefinitionId": "<id>", "value": "<str>"}
            ]
        """
        from .bootstrap import _ca_classification_name
        from metadata.generated.schema.type.tagLabel import (
            LabelType, State, TagLabel, TagSource,
        )

        cas = entity.get("customAttributes") or []
        if not cas:
            return []
        id_to_name = self._ca_name_by_id_map()
        if not id_to_name:
            return []
        out: List[TagLabel] = []
        for ca in cas:
            def_id = ca.get("customAttributeDefinitionId")
            value = ca.get("value")
            if not def_id or not value:
                continue
            ca_name = id_to_name.get(def_id)
            if not ca_name:
                continue
            classification = _ca_classification_name(ca_name)
            # OM Tags accept [A-Za-z0-9_-]; sanitise CA values inline.
            tag_name = "".join(
                c if c.isalnum() or c in "_-" else "_" for c in str(value)
            )[:128] or "unnamed"
            tag_fqn = f"{classification}.{tag_name}"
            if tag_fqn not in self._ca_tag_ensured:
                self._lazy_create_tag(classification, tag_name, value)
                self._ca_tag_ensured.add(tag_fqn)
            out.append(
                TagLabel(
                    tagFQN=tag_fqn,
                    labelType=LabelType.Automated,
                    state=State.Suggested,
                    source=TagSource.Classification,
                )
            )
        return out

    def _lazy_create_tag(
        self, classification: str, tag_name: str, value: str
    ) -> None:
        """POST a Tag to OM, ignore 409 if it already exists."""
        body = {
            "classification": classification,
            "name": tag_name,
            "description": (
                f"Auto-created from Solace Event Portal custom attribute "
                f"value `{value}`."
            ),
        }
        try:
            self.metadata.client.post("/tags", json=body)
        except Exception as exc:
            # 409 / "already exists" is expected. Log others at DEBUG.
            logger.debug(
                "Lazy-create tag %s.%s failed (often 409): %s",
                classification, tag_name, exc,
            )

    # ------------------------------------------------------------- utilities

    @staticmethod
    def _mesh_domain_name(
        mesh: Dict[str, Any], domains: List[Dict[str, Any]]
    ) -> str:
        ids = set(mesh.get("applicationDomainIds") or [])
        for d in domains:
            if d.get("id") in ids and d.get("name"):
                return d["name"]
        return "default"

    @staticmethod
    def _fail(name: str, exc: Exception) -> Either:
        return Either(
            left=StackTraceError(
                name=name,
                error=str(exc),
                stackTrace=traceback.format_exc(),
            )
        )


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _semver_tuple(version_str: str) -> tuple:
    """Parse a semver-like string into a tuple for ordering.

    Non-numeric parts fall back to 0 so e.g. ``"1.0.0-rc1"`` < ``"1.0.0"``
    holds without raising.
    """
    parts = []
    for chunk in (version_str or "0").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _latest_version_id(versions: Iterable[Optional[Dict[str, Any]]]) -> Optional[str]:
    """Return the EP id of the highest-semver version in ``versions``.

    Returns None when the list is empty / all-None. Used by the topic
    and pipeline passes to stamp ``eventPortalIsLatestVersion`` on the
    matching OM entity (#54)."""
    best_id: Optional[str] = None
    best_tuple: tuple = ()
    for v in versions:
        if not v:
            continue
        t = _semver_tuple(str(v.get("version") or "0.0.0"))
        if best_id is None or t > best_tuple:
            best_id = v.get("id")
            best_tuple = t
    return best_id
