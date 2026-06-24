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
    consumer_to_container_request,
    domain_to_create_request,
    domain_to_database_schema_request,
    event_api_to_container_request,
    event_to_topic_request,
    modeled_mesh_to_data_product_request,
    pipeline_to_pipeline_lineage_request,
    schema_version_to_table_request,
    topic_fqn,
    topic_segment_container_fqn,
    topic_segment_to_container_request,
)
from .owner_resolver import OwnerResolver, parse_user_id_map

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
        # Wave 3 (#44): emit OM Containers per EP Event API + lineage to topics.
        # Default ON since ALDI Cluster 1.7 confirmed they use Event APIs.
        self.emit_event_apis: bool = _as_bool(opts.get("emitEventApis", "true"))
        # Wave 3 (#45): emit OM DataProducts per EP Event API Product.
        self.emit_event_api_products: bool = _as_bool(
            opts.get("emitEventApiProducts", "true")
        )
        # Wave 3 (#55): emit OM Containers per applicationVersion.consumers[]
        # entry (the Solace queue / topic-endpoint the consuming app binds
        # to) plus Topic -> Container -> Pipeline lineage.
        self.emit_consumers: bool = _as_bool(opts.get("emitConsumers", "true"))
        # Wave 3 (#52): promote EP Schemas to first-class OM Tables under
        # the synthetic `solace-event-portal-schemas` DatabaseService.
        # Default ON since ALDI Cluster 3.1 confirmed schemas must be
        # browsable/queryable independent of their carrying topic.
        self.emit_schemas: bool = _as_bool(opts.get("emitSchemas", "true"))
        # Wave 3 (#53): materialise the Solace topic-address namespace
        # as nested Containers + lineage from the deepest segment to the
        # Topic. Depth cap defaults to 3 -- below that the visual tree
        # gets noisy for typical EP customers (5-6 segments are common).
        self.emit_topic_tree: bool = _as_bool(opts.get("emitTopicTree", "true"))
        try:
            self.topic_tree_max_depth: int = max(
                1, int(opts.get("topicTreeMaxDepth", 3))
            )
        except (TypeError, ValueError):
            self.topic_tree_max_depth = 3
        self.since: Optional[str] = opts.get("since") or None
        # Wave 5 (#41): multi-tenant. Two EP tenants share the synthetic
        # services (apps PipelineService, schemas DatabaseService, the
        # StorageServices), so an optional tenantPrefix isolates their FQNs.
        # Empty prefix => byte-identical single-tenant FQNs (zero drift for
        # the existing ALDI tenant). The MessagingService (self.service_name)
        # is already isolated by a distinct serviceName per tenant workflow.
        from .fqn import apply_tenant_prefix
        from .property_keys import (
            APP_PIPELINE_SERVICE_NAME,
            CONSUMER_STORAGE_SERVICE_NAME,
            EVENT_API_STORAGE_SERVICE_NAME,
            SCHEMA_DATABASE_SERVICE_NAME,
            TOPIC_TREE_STORAGE_SERVICE_NAME,
        )
        self.tenant_prefix: str = opts.get("tenantPrefix") or ""
        self.app_pipeline_service = apply_tenant_prefix(
            APP_PIPELINE_SERVICE_NAME, self.tenant_prefix
        )
        self.event_api_service = apply_tenant_prefix(
            EVENT_API_STORAGE_SERVICE_NAME, self.tenant_prefix
        )
        self.consumer_service = apply_tenant_prefix(
            CONSUMER_STORAGE_SERVICE_NAME, self.tenant_prefix
        )
        self.schema_db_service = apply_tenant_prefix(
            SCHEMA_DATABASE_SERVICE_NAME, self.tenant_prefix
        )
        self.topic_tree_service = apply_tenant_prefix(
            TOPIC_TREE_STORAGE_SERVICE_NAME, self.tenant_prefix
        )
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
            # Wave 4 (#56): wire the API base URL into EpUrls so Pipeline
            # mapper can compose the downloadable AsyncAPI sourceUrl.
            # Overridable spec version + format are forwarded too.
            api_url=self.api_url,
            async_api_version=opts.get("asyncApiVersion") or "2.5.0",
            async_api_format=opts.get("asyncApiFormat") or "json",
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

        # Wave 4 (#57): static map from EP user-ID -> e-mail. EP Cloud
        # Enterprise returns IDs on createdBy / changedBy with no
        # /users/{id} endpoint to resolve them. Operators populate this
        # map at workflow-config time. Accepts either an inline mapping
        # (dict) or a comma-separated `id1:email1,id2:email2` string.
        raw_user_map = opts.get("userIdToEmailMap") or {}
        self._user_id_to_email: Dict[str, str] = parse_user_id_map(raw_user_map)

        # Wave 4 (#48): static map from EP-domain name -> OM parent-Domain
        # FQN. Lets operators stitch the per-tenant EP domain set under a
        # pre-existing OM domain hierarchy (e.g. all EP domains under
        # `Marketplace`). Same dict-or-string shape as userIdToEmailMap.
        raw_dom_map = opts.get("omDomainParentMap") or {}
        self._om_domain_parent_map: Dict[str, str] = _parse_string_map(raw_dom_map)

        # Resolves EP owner e-mails to OM users via the OM REST API.
        # Negative results are cached too so we don't keep re-querying for
        # owners that are not Keycloak users (yet).
        self.owner_resolver = OwnerResolver(
            self.metadata,
            user_id_to_email=self._user_id_to_email,
        )
        # Wave 4 (#57): default flipped to ON. With userIdToEmailMap in
        # place, the resolver now degrades gracefully (WARN log on miss)
        # so the previous "opt-in" gating is no longer needed. Set
        # resolveOwners=false to suppress all owner resolution.
        self.resolve_owners: bool = _as_bool(opts.get("resolveOwners", "true"))

        # Sample-data via live broker subscribe (opt-in).
        self.sample_data_enabled: bool = _as_bool(
            opts.get("sampleDataEnabled", "false")
        )
        # Buffered as (topic_fqn, topic_address) tuples during the topic pass
        # and drained at the end of _iter_rest_api into the broker session.
        self._pending_samples: List[Tuple[str, str]] = []

        # Wave 5 (#62): PII detection. All signals are READ-ONLY against EP
        # (registering a pii CA definition back into EP needs an EP write
        # path -- reserved for Wave 4.5 / #49). Detection is active iff at
        # least one signal source is configured.
        from .pii import parse_pii_ca_names, parse_pii_tag_names

        self._pii_ca_names: List[str] = parse_pii_ca_names(opts.get("piiCaName"))
        self._pii_tag_names: List[str] = parse_pii_tag_names(opts.get("piiTagNames"))
        self._pii_topic_pattern: str = opts.get("piiTopicSegmentPattern") or ""
        self._pii_enabled: bool = bool(
            self._pii_ca_names or self._pii_tag_names or self._pii_topic_pattern
        )

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

        # Wave 3 (#44 / #45): EventAPI Container cache for EAPP assets.
        self._event_api_version_to_container_id: Dict[str, str] = {}
        self._event_api_version_to_container_fqn: Dict[str, str] = {}

        # Wave 3 (#52): per-domain Schema Table cache for Schema -> Topic
        # lineage. Keyed by EP schemaVersionId; values are OM Table ids.
        self._schema_version_to_table_id: Dict[str, str] = {}
        # Domains for which the DatabaseSchema has already been ensured in
        # this run (one-shot per domain).
        self._database_schema_ensured: Set[str] = set()
        # Reverse lookup populated during pass 1: topic FQN -> the EP
        # schemaVersionId it carries (when present). Pass 1.4 walks this
        # to emit Table -> Topic lineage without re-fetching anything.
        self._topic_fqn_to_schema_version: Dict[str, str] = {}
        # Wave 3 (#53): topic FQN -> its full topic-address (parsed during
        # pass 1) for the topic-tree pass to consume without re-fetching.
        # The leading reconstruction lives inside `mappers.extract_topic_address`.
        self._topic_fqn_to_address: Dict[str, str] = {}
        # Cache of segment FQNs already emitted this run so we don't
        # repeatedly POST the same shared prefix containers.
        self._topic_segment_ensured: Set[str] = set()

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
                # Wave 4 (#48): map EP-domain -> OM parent-Domain FQN to
                # render a sub-domain hierarchy in the OM UI. Lookup is
                # case-sensitive by EP domain name; misses leave the
                # Domain at the top level.
                parent_fqn = self._om_domain_parent_map.get(domain.get("name") or "")
                req = domain_to_create_request(
                    domain, owner=owner, parent_fqn=parent_fqn or None,
                )
                if req is not None:
                    yield Either(right=req)

        # Pass 1 - one Topic per event version, tagged with state + custom
        # properties; plus synthetic Application Topics for the lineage pass.
        for domain in domains:
            yield from self._emit_domain_topics(domain, mesh_by_domain.get(domain["id"]))

        # Pass 1.4 - Wave 3 (#52): first-class Schemas as OM Tables, plus
        # Table -> Topic lineage for every Topic carrying that schema
        # version. Runs after the Topic pass so the lineage POSTs can
        # resolve Topic ids by FQN.
        if self.emit_schemas:
            for domain in domains:
                yield from self._emit_domain_schemas(domain)

        # Pass 1.5 - Wave 3 (#44): EventAPI Containers + their topic lineage.
        if self.emit_event_apis:
            for domain in domains:
                yield from self._emit_domain_event_apis(domain)

        # Pass 1.6 - Wave 3 (#45): EventAPI Product -> OM DataProduct.
        if self.emit_event_api_products:
            for domain in domains:
                yield from self._emit_domain_event_api_products(domain)

        # Pass 1.7 - Wave 3 (#53): topic-tree segment Containers + lineage
        # from the deepest in-cap segment to every matching Topic. Runs
        # after pass 1 so it can read `_topic_fqn_to_address`, and after
        # pass 1.4-1.6 because there's no inter-pass dependency either way.
        if self.emit_topic_tree:
            yield from self._emit_topic_tree()

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
                    from .mappers import extract_topic_address
                    addr = extract_topic_address(version)
                    # Wave 1 (#43): EP custom-attribute -> OM Tag bindings
                    # from both the event and the event-version payloads.
                    # Computed once and reused for PII detection below.
                    ca_tags = (
                        self._custom_attribute_tags(event)
                        + self._custom_attribute_tags(version)
                    )
                    # Wave 5 (#62): declarative PII detection (read-only).
                    contains_pii = self._detect_pii(
                        entity=event,
                        version=version,
                        topic_address=addr,
                        schema_payload=schema_payload,
                        ca_tags=ca_tags,
                    )
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
                        custom_attribute_tags=ca_tags,
                        contains_pii=contains_pii,
                    )
                    fqn = topic_fqn(
                        self.service_name,
                        event.get("name") or "unnamed-event",
                        str(version.get("version") or "1.0.0"),
                    )
                    self._event_version_to_topic_fqn[version["id"]] = fqn
                    # Wave 3 (#52): remember which schema version this Topic
                    # carries so the Schema pass can build Table -> Topic
                    # lineage without re-walking events.
                    sv_id = (schema_payload or {}).get("version", {}).get("id")
                    if sv_id:
                        self._topic_fqn_to_schema_version[fqn] = sv_id
                    # Wave 3 (#53): also keep the topic address indexed by
                    # FQN so the topic-tree pass can walk segments without
                    # re-parsing the EP payload.
                    if addr:
                        self._topic_fqn_to_address[fqn] = addr
                    # Wave 5 (#62): HARD-BLOCK sample-data for PII topics --
                    # never subscribe to a topic that may carry PII payloads.
                    # The gate is the pure, unit-tested pii.should_sample().
                    if self.sample_data_enabled and addr:
                        from .pii import should_sample

                        if should_sample(True, True, contains_pii):
                            self._pending_samples.append((fqn, addr))
                        else:
                            logger.info(
                                "PII topic %s excluded from sample-data "
                                "collection (#62)", fqn,
                            )
                    yield Either(right=request)
            except Exception as exc:
                yield self._fail(
                    f"event:{event.get('name', event.get('id'))}", exc
                )

    def _emit_domain_schemas(self, domain: Dict[str, Any]) -> Iterable[Either]:
        """Wave 3 (#52): emit one OM DatabaseSchema per EP Application Domain
        and one OM Table per EP Schema + version below it. Then build
        Table -> Topic lineage for every Topic that referenced this
        schema version in pass 1.

        Schemas without any version are skipped.
        """
        domain_name = domain.get("name") or domain.get("id")
        try:
            schemas = self.client.list_schemas(domain["id"], since=self.since)
        except Exception as exc:
            yield self._fail(f"list-schemas:{domain_name}", exc)
            return

        # Apply schemaFilterPattern -- same gate the Topic pass uses for
        # message-schema attachment, but here we drop the whole Table.
        schemas = [
            s for s in schemas if self.schema_filter.match(s.get("name"))
        ]
        if not schemas:
            return

        # One-shot DatabaseSchema ensure (per-domain) before any Tables go in.
        if domain["id"] not in self._database_schema_ensured:
            try:
                ds_req = domain_to_database_schema_request(
                    domain, service_name=self.schema_db_service
                )
                if ds_req is not None:
                    self.metadata.create_or_update(data=ds_req)
                self._database_schema_ensured.add(domain["id"])
            except Exception as exc:
                yield self._fail(
                    f"create-database-schema:{domain_name}", exc
                )
                return

        for schema in schemas:
            try:
                versions = (
                    self.client.list_schema_versions(schema["id"])
                    if self.ingest_all_versions
                    else [self.client.get_latest_schema_version(schema["id"])]
                )
                latest_id = _latest_version_id(versions)
                for version in versions:
                    if not version:
                        continue
                    req = schema_version_to_table_request(
                        schema=schema,
                        schema_version=version,
                        domain=domain,
                        ep_urls=self.ep_urls,
                        is_latest_version=(
                            version.get("id") == latest_id if latest_id else None
                        ),
                        service_name=self.schema_db_service,
                        mark_pii=self._pii_enabled,
                    )
                    if req is None:
                        continue
                    try:
                        table_entity = self.metadata.create_or_update(data=req)
                    except Exception as exc:
                        yield self._fail(
                            f"create-schema-table:{schema.get('name')}", exc
                        )
                        continue
                    table_id = str(
                        getattr(
                            getattr(table_entity, "id", None),
                            "root",
                            getattr(table_entity, "id", ""),
                        )
                    )
                    if not table_id:
                        continue
                    self._schema_version_to_table_id[version["id"]] = table_id

                    # Table -> Topic lineage for every Topic carrying this
                    # schemaVersionId. Built from the cache populated in
                    # pass 1.
                    for topic_fqn_, sv_id in self._topic_fqn_to_schema_version.items():
                        if sv_id != version["id"]:
                            continue
                        topic_id = self._resolve_id("topic", topic_fqn_)
                        if not topic_id:
                            continue
                        self._post_consumer_lineage(
                            source_id=table_id, source_type="table",
                            dest_id=topic_id, dest_type="topic",
                            label=(
                                f"Solace EP schema '{schema.get('name')}' "
                                f"v{version.get('version')} carried on topic"
                            ),
                        )
            except Exception as exc:
                yield self._fail(
                    f"schema:{schema.get('name', schema.get('id'))}", exc
                )

    def _emit_domain_event_apis(self, domain: Dict[str, Any]) -> Iterable[Either]:
        """Wave 3 (#44): emit one OM Container per EP Event API version
        and the produces / consumes edges to the topics it references.

        Container lives under the synthetic StorageService
        ``solace-event-portal-event-apis`` (created by bootstrap). Lineage
        is emitted only for produced/consumed event-version ids that are
        present in this run's topic-FQN cache (#54 latest-only ingests
        only carry the latest version of each event so older Event API
        versions referencing deprecated event versions silently skip
        those edges -- expected behaviour, not a regression).
        """
        try:
            event_apis = self.client.list_event_apis(domain["id"], since=self.since)
        except Exception as exc:
            yield self._fail(f"list-event-apis:{domain.get('name')}", exc)
            return

        for ea in event_apis:
            try:
                versions = (
                    self.client.list_event_api_versions(ea["id"])
                    if self.ingest_all_versions
                    else [self.client.get_latest_event_api_version(ea["id"])]
                )
                latest_id = _latest_version_id(versions)
                for version in versions:
                    if not version:
                        continue
                    container_req = event_api_to_container_request(
                        event_api=ea,
                        event_api_version=version,
                        domain=domain,
                        ep_urls=self.ep_urls,
                        is_latest_version=(
                            version.get("id") == latest_id if latest_id else None
                        ),
                        service_name=self.event_api_service,
                    )
                    if container_req is None:
                        continue
                    try:
                        container_entity = self.metadata.create_or_update(
                            data=container_req
                        )
                    except Exception as exc:
                        yield self._fail(
                            f"create-event-api:{ea.get('name')}", exc
                        )
                        continue
                    container_id = str(
                        getattr(
                            getattr(container_entity, "id", None),
                            "root",
                            getattr(container_entity, "id", ""),
                        )
                    )
                    if not container_id:
                        continue

                    # Wave 3 (#45): cache for EAPP DataProduct asset refs.
                    self._event_api_version_to_container_id[version["id"]] = container_id
                    from .mappers import event_api_container_fqn
                    self._event_api_version_to_container_fqn[version["id"]] = (
                        event_api_container_fqn(
                            ea.get("name") or "unnamed-event-api",
                            str(version.get("version") or "1.0.0"),
                            service_name=self.event_api_service,
                        )
                    )

                    # Lineage edges Container <-> Topic.
                    ea_name = ea.get("name") or "EventAPI"
                    for ev_id in version.get("producedEventVersionIds") or []:
                        fqn = self._event_version_to_topic_fqn.get(_as_event_version_id(ev_id))
                        if not fqn:
                            continue
                        topic_id = self._resolve_id("topic", fqn)
                        if not topic_id:
                            continue
                        self._post_event_api_lineage(
                            container_id, topic_id, "produces", ea_name,
                        )
                    for ev_id in version.get("consumedEventVersionIds") or []:
                        fqn = self._event_version_to_topic_fqn.get(_as_event_version_id(ev_id))
                        if not fqn:
                            continue
                        topic_id = self._resolve_id("topic", fqn)
                        if not topic_id:
                            continue
                        self._post_event_api_lineage(
                            container_id, topic_id, "consumes", ea_name,
                        )
            except Exception as exc:
                yield self._fail(
                    f"event-api:{ea.get('name', ea.get('id'))}", exc
                )

    def _emit_topic_tree(self) -> Iterable[Either]:
        """Wave 3 (#53): materialise the topic-address namespace as a
        Container tree.

        For every cached (topic FQN, address) pair from pass 1 we walk
        the address's segments (capped at `topic_tree_max_depth`),
        creating one Container per unique segment-path, then emit
        ContainerLeaf -> Topic lineage for the topic at the matching
        prefix. Shared prefixes across topics dedupe via
        `_topic_segment_ensured`.

        Errors during a single segment's create do not abort sibling
        addresses -- topic-tree is a navigation aid, never a hard
        dependency of the metadata model.
        """
        if not self._topic_fqn_to_address:
            return
        emitted = 0
        for tfqn, address in self._topic_fqn_to_address.items():
            try:
                segments = [s for s in (address or "").split("/") if s]
                if not segments:
                    continue
                capped = segments[: self.topic_tree_max_depth]
                leaf_fqn: Optional[str] = None
                leaf_id: Optional[str] = None
                parent_fqn: Optional[str] = None
                for depth, seg in enumerate(capped, start=1):
                    path_so_far = capped[:depth]
                    seg_fqn = topic_segment_container_fqn(
                        path_so_far, service_name=self.topic_tree_service
                    )
                    leaf_fqn = seg_fqn
                    if seg_fqn in self._topic_segment_ensured:
                        # Already created on a sibling topic. Still pull
                        # the id so we can use it for lineage at the leaf.
                        if depth == len(capped):
                            leaf_id = self._resolve_id("container", seg_fqn)
                        parent_fqn = seg_fqn
                        continue
                    req = topic_segment_to_container_request(
                        segment=seg,
                        depth=depth,
                        segment_path=path_so_far,
                        parent_fqn=parent_fqn,
                        service_name=self.topic_tree_service,
                    )
                    if req is None:
                        parent_fqn = seg_fqn
                        continue
                    try:
                        container_entity = self.metadata.create_or_update(data=req)
                        self._topic_segment_ensured.add(seg_fqn)
                        emitted += 1
                        if depth == len(capped):
                            leaf_id = str(
                                getattr(
                                    getattr(container_entity, "id", None),
                                    "root",
                                    getattr(container_entity, "id", ""),
                                )
                            )
                    except Exception as exc:
                        yield self._fail(
                            f"create-topic-segment:{seg_fqn}", exc
                        )
                    parent_fqn = seg_fqn

                if not leaf_id and leaf_fqn:
                    leaf_id = self._resolve_id("container", leaf_fqn)
                if not leaf_id:
                    continue
                topic_id = self._resolve_id("topic", tfqn)
                if not topic_id:
                    continue
                self._post_consumer_lineage(
                    source_id=leaf_id, source_type="container",
                    dest_id=topic_id, dest_type="topic",
                    label=(
                        f"Solace topic-tree segment '{capped[-1]}' "
                        f"(depth {len(capped)}) carries topic"
                    ),
                )
            except Exception as exc:
                yield self._fail(f"topic-tree:{tfqn}", exc)
        logger.info(
            "Topic-tree pass: %d new segment Containers emitted across %d topics",
            emitted, len(self._topic_fqn_to_address),
        )

    def _emit_app_version_consumers(
        self,
        *,
        domain: Dict[str, Any],
        app: Dict[str, Any],
        app_version: Dict[str, Any],
        pipeline_id: str,
    ) -> Iterable[Either]:
        """Wave 3 (#55): one OM Container per applicationVersion.consumers[]
        entry, plus Topic -> Container -> Pipeline lineage.

        Subscribed topics are derived from each consumer's
        ``subscriptions[].attractedEventVersionIds`` (EP pre-resolves which
        event versions a pattern would match). Failures on a single
        consumer are reported via Either and do not abort sibling
        consumers / the broader app pass.
        """
        consumers = app_version.get("consumers") or []
        if not consumers:
            return
        app_name = app.get("name") or app.get("id") or "unknown-app"
        for consumer in consumers:
            try:
                req = consumer_to_container_request(
                    consumer=consumer,
                    app=app,
                    app_version=app_version,
                    domain=domain,
                    service_name=self.consumer_service,
                )
                if req is None:
                    continue
                try:
                    container_entity = self.metadata.create_or_update(data=req)
                except Exception as exc:
                    yield self._fail(
                        f"create-consumer:{app_name}:{consumer.get('name')}", exc
                    )
                    continue
                container_id = str(
                    getattr(
                        getattr(container_entity, "id", None),
                        "root",
                        getattr(container_entity, "id", ""),
                    )
                )
                if not container_id:
                    logger.warning(
                        "Consumer container %s persisted but id missing; "
                        "skipping lineage", consumer.get("name"),
                    )
                    continue

                # Topic -> Container per matched event version.
                seen_topic_ids: Set[str] = set()
                for sub in consumer.get("subscriptions") or []:
                    for ev_id in sub.get("attractedEventVersionIds") or []:
                        fqn = self._event_version_to_topic_fqn.get(_as_event_version_id(ev_id))
                        if not fqn:
                            continue
                        topic_id = self._resolve_id("topic", fqn)
                        if not topic_id or topic_id in seen_topic_ids:
                            continue
                        seen_topic_ids.add(topic_id)
                        self._post_consumer_lineage(
                            source_id=topic_id, source_type="topic",
                            dest_id=container_id, dest_type="container",
                            label=(
                                f"Solace EP consumer queue '{consumer.get('name')}' "
                                f"subscribed pattern"
                            ),
                        )

                # Container -> Pipeline (the owning consuming app).
                if pipeline_id:
                    self._post_consumer_lineage(
                        source_id=container_id, source_type="container",
                        dest_id=pipeline_id, dest_type="pipeline",
                        label=(
                            f"Solace EP consumer queue '{consumer.get('name')}' "
                            f"feeds app '{app_name}'"
                        ),
                    )
            except Exception as exc:
                yield self._fail(
                    f"consumer:{app_name}:{consumer.get('name', consumer.get('id'))}",
                    exc,
                )

    def _post_consumer_lineage(
        self,
        *,
        source_id: str,
        source_type: str,
        dest_id: str,
        dest_type: str,
        label: str,
    ) -> None:
        """Wave 3 (#55) helper. Build + POST a generic AddLineage edge."""
        try:
            from metadata.generated.schema.api.lineage.addLineage import (
                AddLineageRequest,
            )
            from metadata.generated.schema.type.entityLineage import (
                EntitiesEdge,
                LineageDetails,
            )
            from metadata.generated.schema.type.entityReference import (
                EntityReference,
            )
        except Exception:
            return
        # OM 1.13 renamed the LineageSource enum to Source; resolve it via the
        # version-robust helper instead of a hard import (a failed import here
        # used to silently drop ALL container lineage on 1.13).
        from .mappers import lineage_source_manual

        details_kwargs = {"description": label}
        src = lineage_source_manual()
        if src is not None:
            details_kwargs["source"] = src
        req = AddLineageRequest(
            edge=EntitiesEdge(
                fromEntity=EntityReference(id=source_id, type=source_type),
                toEntity=EntityReference(id=dest_id, type=dest_type),
                lineageDetails=LineageDetails(**details_kwargs),
            )
        )
        self._add_lineage(req)

    def _post_event_api_lineage(
        self,
        container_id: str,
        topic_id: str,
        direction: str,
        event_api_name: str,
    ) -> None:
        """Wave 3 (#44) helper. Build + POST Container<->Topic lineage."""
        try:
            from metadata.generated.schema.api.lineage.addLineage import (
                AddLineageRequest,
            )
            from metadata.generated.schema.type.entityLineage import (
                EntitiesEdge,
                LineageDetails,
            )
            from metadata.generated.schema.type.entityReference import (
                EntityReference,
            )
        except Exception:
            return
        from .mappers import lineage_source_manual

        if direction == "produces":
            from_id, from_type = container_id, "container"
            to_id, to_type = topic_id, "topic"
        else:  # consumes
            from_id, from_type = topic_id, "topic"
            to_id, to_type = container_id, "container"
        details_kwargs = {
            "description": (
                f"Solace Event Portal Event API: {event_api_name} {direction}"
            ),
        }
        src = lineage_source_manual()
        if src is not None:
            details_kwargs["source"] = src
        req = AddLineageRequest(
            edge=EntitiesEdge(
                fromEntity=EntityReference(id=from_id, type=from_type),
                toEntity=EntityReference(id=to_id, type=to_type),
                lineageDetails=LineageDetails(**details_kwargs),
            )
        )
        self._add_lineage(req)

    def _emit_domain_event_api_products(
        self, domain: Dict[str, Any]
    ) -> Iterable[Either]:
        """Wave 3 (#45): emit one OM DataProduct per EP Event API Product
        version, with ``assets`` referencing the EventAPI Containers
        created by pass 1.5 (#44).
        """
        try:
            from .mappers import eapp_to_data_product_request
        except Exception as exc:
            yield self._fail("import-mapper:eapp", exc)
            return
        try:
            eapps = self.client.list_event_api_products(
                domain["id"], since=self.since,
            )
        except Exception as exc:
            yield self._fail(f"list-eapps:{domain.get('name')}", exc)
            return

        for eapp in eapps:
            try:
                versions = (
                    self.client.list_event_api_product_versions(eapp["id"])
                    if self.ingest_all_versions
                    else [
                        self.client.get_latest_event_api_product_version(eapp["id"])
                    ]
                )
                latest_id = _latest_version_id(versions)
                for version in versions:
                    if not version:
                        continue
                    asset_refs = self._build_eapp_asset_refs(version)
                    req = eapp_to_data_product_request(
                        eapp=eapp,
                        eapp_version=version,
                        domain=domain,
                        container_asset_refs=asset_refs or None,
                        ep_urls=self.ep_urls,
                        is_latest_version=(
                            version.get("id") == latest_id if latest_id else None
                        ),
                    )
                    if req is None:
                        continue
                    try:
                        self.metadata.create_or_update(data=req)
                    except Exception as exc:
                        yield self._fail(f"create-eapp:{eapp.get('name')}", exc)
            except Exception as exc:
                yield self._fail(
                    f"eapp:{eapp.get('name', eapp.get('id'))}", exc
                )

    def _build_eapp_asset_refs(self, eapp_version: Dict[str, Any]) -> List[Any]:
        """For each EAPP version, build EntityReference[] pointing at the
        EventAPI Containers that #44 emitted in this run."""
        try:
            from metadata.generated.schema.type.entityReference import (
                EntityReference,
            )
        except Exception:
            return []
        refs = []
        for ea_v_id in eapp_version.get("eventApiVersionIds") or []:
            container_id = self._event_api_version_to_container_id.get(ea_v_id)
            if not container_id:
                continue
            try:
                refs.append(
                    EntityReference(id=container_id, type="container")
                )
            except Exception:
                continue
        return refs

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
                    # Wave 1 (#43): EP custom-attribute -> OM Tag bindings
                    # from the application + version payloads (reused for
                    # PII detection). Wave 5 (#62): apps have no topic
                    # address / schema, so the CA-name + tag signals apply.
                    app_ca_tags = (
                        self._custom_attribute_tags(app)
                        + self._custom_attribute_tags(version)
                    )
                    app_contains_pii = self._detect_pii(
                        entity=app,
                        version=version,
                        topic_address=None,
                        schema_payload=None,
                        ca_tags=app_ca_tags,
                    )
                    pipeline_request = app_to_pipeline_request(
                        domain=domain, app=app, app_version=version,
                        owner=self._resolve(app, domain),
                        ep_urls=self.ep_urls,
                        attach_to_domain=self.emit_domains,
                        is_latest_version=(
                            version.get("id") == latest_id if latest_id else None
                        ),
                        custom_attribute_tags=app_ca_tags,
                        service_name=self.app_pipeline_service,
                        contains_pii=app_contains_pii,
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
                        fqn = self._event_version_to_topic_fqn.get(_as_event_version_id(ev_id))
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
                        fqn = self._event_version_to_topic_fqn.get(_as_event_version_id(ev_id))
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

                    # Wave 3 (#55): per-consumer Container + lineage
                    # Topic -> Container -> Pipeline. Captures EP's queue /
                    # topic-endpoint binding (the Solace fan-out point).
                    if self.emit_consumers:
                        yield from self._emit_app_version_consumers(
                            domain=domain,
                            app=app,
                            app_version=version,
                            pipeline_id=pipeline_id,
                        )
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
        # Container is imported lazily because not every OM version we
        # support ships it (1.6 did; 1.11 still does).
        container_cls = None
        try:
            from metadata.generated.schema.entity.data.container import (
                Container as container_cls,  # noqa: N813
            )
        except Exception:
            container_cls = None
        cls = {
            "pipeline": Pipeline,
            "topic": Topic,
            "container": container_cls,
        }.get(entity_kind)
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

    def _present_ca_names(self, entity: Dict[str, Any]) -> set:
        """Set of EP custom-attribute *names* present on an entity (Wave 5
        #62). PII CA detection matches by name, never by free-text value."""
        id_to_name = self._ca_name_by_id_map()
        names = set()
        for ca in entity.get("customAttributes") or []:
            nm = id_to_name.get(ca.get("customAttributeDefinitionId"))
            if nm:
                names.add(nm)
        return names

    @staticmethod
    def _schema_text_and_type(schema_payload):
        """Extract (content, schemaType) from a resolved schema payload,
        matching how mappers.event_to_topic_request reads it (#62)."""
        if not schema_payload:
            return None, None
        schema = schema_payload.get("schema") or {}
        version = schema_payload.get("version") or {}
        stype = schema.get("schemaType") or schema.get("contentType")
        return version.get("content"), stype

    def _detect_pii(self, *, entity, version, topic_address, schema_payload,
                    ca_tags) -> bool:
        """Combine the four declarative PII signals for an entity (#62).

        No-op (False) unless at least one PII signal source is configured,
        so single-tenant deployments that don't opt in pay nothing.
        """
        if not self._pii_enabled:
            return False
        from .pii import has_pii_signal

        present_ca = self._present_ca_names(entity) | self._present_ca_names(version)
        present_tags = {
            getattr(t, "tagFQN", None) for t in (ca_tags or [])
        }
        present_tags.discard(None)
        schema_text, schema_type = self._schema_text_and_type(schema_payload)
        return has_pii_signal(
            present_ca_names=present_ca,
            pii_ca_names=self._pii_ca_names,
            present_tag_names=present_tags,
            pii_tag_names=self._pii_tag_names,
            topic_address=topic_address,
            topic_pattern=self._pii_topic_pattern,
            schema_text=schema_text,
            schema_type=schema_type,
        )

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


def _as_event_version_id(ev: Any) -> Optional[str]:
    """Normalise an EP event-version-id list entry to a bare id string.

    EP returns these lists (``attractedEventVersionIds``,
    ``declared{Produced,Consumed}EventVersionIds``, ...) as EITHER bare id
    strings OR objects like ``{"eventVersionId": ..., "eventMeshIds": [...]}``
    depending on tenant / API version. Returning the bare id keeps the FQN
    lookup from being handed a dict (TypeError: unhashable type: 'dict').
    """
    if isinstance(ev, dict):
        return ev.get("eventVersionId") or ev.get("id")
    return ev


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_string_map(raw: Any) -> Dict[str, str]:
    """Coerce a workflow-config value to a plain ``{str: str}`` map.

    Same shape as ``parse_user_id_map`` but without the e-mail check.
    Used for Wave 4 (#48) ``omDomainParentMap`` and any future
    string-to-string options.
    """
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {
            str(k).strip(): str(v).strip()
            for k, v in raw.items()
            if k and v
        }
    if isinstance(raw, str):
        out: Dict[str, str] = {}
        for pair in raw.split(","):
            if ":" not in pair:
                continue
            k, _, v = pair.partition(":")
            k = k.strip()
            v = v.strip()
            if k and v:
                out[k] = v
        return out
    return {}




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
