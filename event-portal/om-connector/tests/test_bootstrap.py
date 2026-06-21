"""Bootstrap idempotency tests.

We stub OpenMetadata's REST client because the bootstrap module talks to
OM exclusively through it. The tests verify:
  * classification + tag creation is skipped when already present
  * custom property creation is skipped when already present
  * fresh OM gets exactly the expected create calls
"""
import json as _json
from unittest.mock import MagicMock

from connector import bootstrap


class _FakeClient:
    """Pretends to be `OpenMetadata.client` with a configurable knowledge base.

    Accepts the same kwargs the real OM REST client accepts:
      * `post(path, json=dict)` — JSON-encoded body (the bootstrap module's
        convention for create endpoints; OM rejects form-encoded payloads).
      * `put(path, data=str)` — `data` is a pre-serialised JSON string for
        JSON-Patch and a few other PUTs. We decode it so the test assertions
        can compare against the dict shape used in bootstrap.py.
    """

    def __init__(self, existing=None):
        self.existing = existing or {}
        self.posts = []
        self.puts = []

    def get(self, path):
        if path not in self.existing:
            raise RuntimeError(f"404 {path}")
        return self.existing[path]

    def post(self, path, data=None, json=None):
        body = json if json is not None else data
        self.posts.append((path, body))
        return body or {}

    def put(self, path, data=None, json=None):
        body = json if json is not None else data
        if isinstance(body, (str, bytes)):
            try:
                body = _json.loads(body)
            except (_json.JSONDecodeError, ValueError, TypeError):
                pass
        self.puts.append((path, body))
        return body or {}


def _make_om(client):
    om = MagicMock()
    om.client = client
    return om


def test_ensure_classification_creates_when_missing():
    client = _FakeClient(existing={})
    bootstrap.ensure_classification(_make_om(client), name="EventPortal")
    assert client.posts == [
        ("/classifications", {"name": "EventPortal", "description": bootstrap.CLASSIFICATION_DESC}),
    ]


def test_ensure_classification_noop_when_present():
    client = _FakeClient(
        existing={"/classifications/name/EventPortal": {"name": "EventPortal"}}
    )
    bootstrap.ensure_classification(_make_om(client), name="EventPortal")
    assert client.posts == []


def test_ensure_tag_creates_when_missing():
    client = _FakeClient(existing={})
    bootstrap.ensure_tag(_make_om(client), "EventPortal", "Draft", "desc")
    assert client.posts == [
        ("/tags", {"classification": "EventPortal", "name": "Draft", "description": "desc"}),
    ]


def test_ensure_tag_noop_when_present():
    client = _FakeClient(
        existing={"/tags/name/EventPortal.Draft": {"name": "Draft"}}
    )
    bootstrap.ensure_tag(_make_om(client), "EventPortal", "Draft", "desc")
    assert client.posts == []


def test_ensure_custom_property_adds_to_topic_type():
    client = _FakeClient(
        existing={
            "/metadata/types/name/topic": {"id": "topic-id", "customProperties": []},
            "/metadata/types/name/string": {"id": "string-id"},
        }
    )
    bootstrap.ensure_custom_property(
        _make_om(client),
        entity_type="topic",
        key="eventPortalDomainId",
        property_type_name="string",
        description="desc",
    )
    assert client.puts == [
        (
            "/metadata/types/topic-id",
            {
                "name": "eventPortalDomainId",
                "description": "desc",
                "propertyType": {"id": "string-id", "type": "type"},
            },
        )
    ]


def test_ensure_custom_property_noop_when_already_attached():
    client = _FakeClient(
        existing={
            "/metadata/types/name/topic": {
                "id": "topic-id",
                "customProperties": [{"name": "eventPortalDomainId"}],
            },
        }
    )
    bootstrap.ensure_custom_property(
        _make_om(client),
        entity_type="topic",
        key="eventPortalDomainId",
        property_type_name="string",
        description="desc",
    )
    assert client.puts == []


def test_full_bootstrap_is_idempotent_on_a_populated_om():
    """Second run on an already-bootstrapped OM should make zero writes."""
    populated = {
        "/classifications/name/EventPortal": {"name": "EventPortal"},
    }
    for tag, _ in bootstrap.TAGS:
        populated[f"/tags/name/EventPortal.{tag}"] = {"name": tag}
    # Wave 5 (#62): compliance classification + PII tag.
    populated[f"/classifications/name/{bootstrap.PII_CLASSIFICATION}"] = {
        "name": bootstrap.PII_CLASSIFICATION
    }
    populated[
        f"/tags/name/{bootstrap.PII_CLASSIFICATION}.{bootstrap.PII_TAG_NAME}"
    ] = {"name": bootstrap.PII_TAG_NAME}
    populated["/metadata/types/name/topic"] = {
        "id": "topic-id",
        "customProperties": [{"name": k} for k, _, _ in bootstrap.TOPIC_CUSTOM_PROPERTIES],
    }
    populated["/metadata/types/name/messagingService"] = {
        "id": "ms-id",
        "customProperties": [
            {"name": k} for k, _, _ in bootstrap.MESSAGING_SERVICE_CUSTOM_PROPERTIES
        ],
    }
    populated["/metadata/types/name/pipeline"] = {
        "id": "pipeline-id",
        "customProperties": [
            {"name": k} for k, _, _ in bootstrap.PIPELINE_CUSTOM_PROPERTIES
        ],
    }
    populated["/metadata/types/name/string"] = {"id": "string-id"}
    populated[
        f"/services/pipelineServices/name/{bootstrap.APP_PIPELINE_SERVICE_NAME}"
    ] = {"name": bootstrap.APP_PIPELINE_SERVICE_NAME}
    # Wave 3 (#44 + #55 + #53): Container CPs (EventAPI + Consumer +
    # TopicTree) + synthetic StorageServices.
    populated["/metadata/types/name/container"] = {
        "id": "container-id",
        "customProperties": [
            {"name": k}
            for k, _, _ in (
                bootstrap.CONTAINER_CUSTOM_PROPERTIES
                + bootstrap.CONSUMER_CUSTOM_PROPERTIES
                + bootstrap.TOPIC_TREE_CUSTOM_PROPERTIES
            )
        ],
    }
    populated[
        f"/services/storageServices/name/{bootstrap.EVENT_API_STORAGE_SERVICE_NAME}"
    ] = {"name": bootstrap.EVENT_API_STORAGE_SERVICE_NAME}
    populated[
        f"/services/storageServices/name/{bootstrap.CONSUMER_STORAGE_SERVICE_NAME}"
    ] = {"name": bootstrap.CONSUMER_STORAGE_SERVICE_NAME}
    populated[
        f"/services/storageServices/name/{bootstrap.TOPIC_TREE_STORAGE_SERVICE_NAME}"
    ] = {"name": bootstrap.TOPIC_TREE_STORAGE_SERVICE_NAME}
    # Wave 3 (#45): DataProduct CPs for EAPP.
    populated["/metadata/types/name/dataProduct"] = {
        "id": "dp-id",
        "customProperties": [
            {"name": k} for k, _, _ in bootstrap.DATAPRODUCT_CUSTOM_PROPERTIES
        ],
    }
    populated["/metadata/types/name/markdown"] = {"id": "markdown-id"}
    # Wave 3 (#52): Table CPs + synthetic DatabaseService + Database.
    populated["/metadata/types/name/table"] = {
        "id": "table-id",
        "customProperties": [
            {"name": k} for k, _, _ in bootstrap.TABLE_CUSTOM_PROPERTIES
        ],
    }
    populated[
        f"/services/databaseServices/name/{bootstrap.SCHEMA_DATABASE_SERVICE_NAME}"
    ] = {"name": bootstrap.SCHEMA_DATABASE_SERVICE_NAME}
    populated[
        f"/databases/name/{bootstrap.SCHEMA_DATABASE_SERVICE_NAME}."
        f"{bootstrap.SCHEMA_DATABASE_NAME}"
    ] = {"name": bootstrap.SCHEMA_DATABASE_NAME}

    client = _FakeClient(existing=populated)
    bootstrap.bootstrap(_make_om(client))
    assert client.posts == []
    assert client.puts == []


def test_ensure_database_service_creates_when_missing():
    client = _FakeClient(existing={})
    bootstrap.ensure_database_service(
        _make_om(client),
        bootstrap.SCHEMA_DATABASE_SERVICE_NAME,
        display_name="Solace Event Portal Schemas",
        description="d",
    )
    assert len(client.posts) == 1
    path, body = client.posts[0]
    assert path == "/services/databaseServices"
    assert body["name"] == bootstrap.SCHEMA_DATABASE_SERVICE_NAME
    assert body["serviceType"] == "CustomDatabase"


def test_ensure_database_service_noop_when_present():
    client = _FakeClient(
        existing={
            f"/services/databaseServices/name/{bootstrap.SCHEMA_DATABASE_SERVICE_NAME}":
                {"name": bootstrap.SCHEMA_DATABASE_SERVICE_NAME},
        }
    )
    bootstrap.ensure_database_service(
        _make_om(client),
        bootstrap.SCHEMA_DATABASE_SERVICE_NAME,
        display_name="x",
        description="d",
    )
    assert client.posts == []


def test_ensure_database_creates_when_missing():
    client = _FakeClient(existing={})
    bootstrap.ensure_database(
        _make_om(client),
        bootstrap.SCHEMA_DATABASE_NAME,
        service=bootstrap.SCHEMA_DATABASE_SERVICE_NAME,
        display_name="Schemas",
        description="d",
    )
    assert len(client.posts) == 1
    path, body = client.posts[0]
    assert path == "/databases"
    assert body["name"] == bootstrap.SCHEMA_DATABASE_NAME
    assert body["service"] == bootstrap.SCHEMA_DATABASE_SERVICE_NAME


def test_ensure_pipeline_service_creates_when_missing():
    client = _FakeClient(existing={})
    bootstrap.ensure_pipeline_service(_make_om(client))
    assert len(client.posts) == 1
    path, body = client.posts[0]
    assert path == "/services/pipelineServices"
    assert body["name"] == bootstrap.APP_PIPELINE_SERVICE_NAME
    assert body["serviceType"] == "CustomPipeline"


def test_ensure_pipeline_service_noop_when_present():
    client = _FakeClient(
        existing={
            f"/services/pipelineServices/name/{bootstrap.APP_PIPELINE_SERVICE_NAME}":
                {"name": bootstrap.APP_PIPELINE_SERVICE_NAME},
        }
    )
    bootstrap.ensure_pipeline_service(_make_om(client))
    assert client.posts == []
    assert client.puts == []


def test_bootstrap_tenant_prefix_creates_prefixed_synthetic_services():
    """Wave 5 (#41): bootstrap with a tenant prefix creates the five shared
    synthetic services under prefixed names so two tenants do not collide.
    The Database NAME stays unprefixed -- only its parent service shifts."""
    client = _FakeClient(existing={})
    bootstrap.bootstrap(_make_om(client), tenant_prefix="t1")

    created = {}
    for path, body in client.posts:
        if path in (
            "/services/pipelineServices",
            "/services/storageServices",
            "/services/databaseServices",
            "/databases",
        ):
            created.setdefault(path, []).append(body)

    pipe_names = [b["name"] for b in created["/services/pipelineServices"]]
    storage_names = {b["name"] for b in created["/services/storageServices"]}
    db_service_names = [b["name"] for b in created["/services/databaseServices"]]

    assert pipe_names == [f"t1-{bootstrap.APP_PIPELINE_SERVICE_NAME}"]
    assert storage_names == {
        f"t1-{bootstrap.EVENT_API_STORAGE_SERVICE_NAME}",
        f"t1-{bootstrap.CONSUMER_STORAGE_SERVICE_NAME}",
        f"t1-{bootstrap.TOPIC_TREE_STORAGE_SERVICE_NAME}",
    }
    assert db_service_names == [f"t1-{bootstrap.SCHEMA_DATABASE_SERVICE_NAME}"]

    db_body = created["/databases"][0]
    assert db_body["name"] == bootstrap.SCHEMA_DATABASE_NAME  # unprefixed
    assert db_body["service"] == f"t1-{bootstrap.SCHEMA_DATABASE_SERVICE_NAME}"


def test_bootstrap_default_prefix_is_single_tenant_unchanged():
    """Empty prefix must create the legacy service names byte-identically."""
    client = _FakeClient(existing={})
    bootstrap.bootstrap(_make_om(client))
    service_names = {
        b["name"]
        for p, b in client.posts
        if p.startswith("/services/")
    }
    assert bootstrap.APP_PIPELINE_SERVICE_NAME in service_names
    assert bootstrap.SCHEMA_DATABASE_SERVICE_NAME in service_names
    assert not any(n.startswith("t1-") for n in service_names)


def test_bootstrap_creates_pii_classification_and_tag():
    """Wave 5 (#62): a dedicated EventPortalCompliance classification with a
    PII tag. (The eventPortalContainsPii CP on Topic + Pipeline is covered
    by the idempotency test, whose populated set derives from the CP lists.)"""
    client = _FakeClient(existing={})
    bootstrap.bootstrap(_make_om(client))

    posted = [(p, b.get("name")) for p, b in client.posts]
    assert ("/classifications", bootstrap.PII_CLASSIFICATION) in posted
    pii_tags = [
        b for p, b in client.posts
        if p == "/tags" and b.get("name") == bootstrap.PII_TAG_NAME
    ]
    assert pii_tags and pii_tags[0]["classification"] == bootstrap.PII_CLASSIFICATION


def test_pii_cp_registered_on_topic_and_pipeline_types():
    """eventPortalContainsPii is registered on both Topic + Pipeline types
    when those types exist."""
    client = _FakeClient(
        existing={
            "/metadata/types/name/topic": {"id": "topic-id", "customProperties": []},
            "/metadata/types/name/pipeline": {"id": "pipe-id", "customProperties": []},
            "/metadata/types/name/string": {"id": "string-id"},
        }
    )
    for et, key, ptype, desc in (
        ("topic", bootstrap.CP_CONTAINS_PII, "string", "d"),
        ("pipeline", bootstrap.CP_CONTAINS_PII, "string", "d"),
    ):
        bootstrap.ensure_custom_property(
            _make_om(client), entity_type=et, key=key,
            property_type_name=ptype, description=desc,
        )
    put_names = [b.get("name") for _, b in client.puts]
    assert put_names.count(bootstrap.CP_CONTAINS_PII) == 2


# --------------------------------------------------------- Wave 1 (#43) tests


def test_ca_classification_name_sanitises_arbitrary_chars():
    """CA names can contain `.`, `-`, spaces; classification names must
    match `[A-Za-z][A-Za-z0-9_]*`."""
    name = bootstrap._ca_classification_name("acl-principal")
    assert name == "EventPortalCustomAttribute_acl_principal"
    name = bootstrap._ca_classification_name("Data Retention.v1")
    assert name == "EventPortalCustomAttribute_Data_Retention_v1"
    # Empty falls back to "unnamed" (already starts with alpha,
    # so no `x_` prefix needed).
    assert bootstrap._ca_classification_name("") == "EventPortalCustomAttribute_unnamed"
    # Numeric-leading names get an `x_` prefix so the classification
    # starts with a letter / underscore (OM requirement).
    assert bootstrap._ca_classification_name("9NumericFirst").startswith(
        "EventPortalCustomAttribute_x_"
    )


class _FakeEpClient:
    """Stand-in for `EventPortalClient` used in CA-discovery tests."""

    def __init__(self, defs):
        self._defs = defs
        self.calls = 0

    def list_custom_attribute_definitions(self):
        self.calls += 1
        return self._defs


def test_discover_custom_attribute_classifications_registers_per_ca_name():
    ep_client = _FakeEpClient(defs=[
        {"id": "a1", "name": "DataRetention", "valueType": "STRING"},
        {"id": "a2", "name": "DataUsage", "valueType": "STRING"},
    ])
    om_client = _FakeClient(existing={})
    bootstrap.discover_custom_attribute_classifications(
        _make_om(om_client), ep_client,
    )
    posted_paths = [path for path, _ in om_client.posts]
    assert posted_paths == ["/classifications", "/classifications"]
    posted_names = [body["name"] for _, body in om_client.posts]
    assert posted_names == [
        "EventPortalCustomAttribute_DataRetention",
        "EventPortalCustomAttribute_DataUsage",
    ]


def test_discover_custom_attribute_classifications_skips_exclude_list():
    """High-cardinality CAs in the exclude list must NOT be registered."""
    ep_client = _FakeEpClient(defs=[
        {"id": "a1", "name": "DataRetention", "valueType": "STRING"},
        {"id": "a2", "name": "acl-principal", "valueType": "STRING"},
        {"id": "a3", "name": "DataUsage", "valueType": "STRING"},
    ])
    om_client = _FakeClient(existing={})
    bootstrap.discover_custom_attribute_classifications(
        _make_om(om_client), ep_client,
        exclude={"acl-principal"},
    )
    posted_names = [body["name"] for _, body in om_client.posts]
    assert "EventPortalCustomAttribute_DataRetention" in posted_names
    assert "EventPortalCustomAttribute_DataUsage" in posted_names
    assert not any(
        "acl_principal" in n or "acl-principal" in n for n in posted_names
    )


def test_discover_custom_attribute_classifications_handles_empty_defs():
    ep_client = _FakeEpClient(defs=[])
    om_client = _FakeClient(existing={})
    out = bootstrap.discover_custom_attribute_classifications(
        _make_om(om_client), ep_client,
    )
    assert out == []
    assert om_client.posts == []


def test_bootstrap_with_ep_client_runs_ca_discovery_at_end():
    """Smoke-test that the top-level bootstrap() routes through to CA
    discovery when ep_client is provided."""
    ep_client = _FakeEpClient(defs=[
        {"id": "a1", "name": "DataRetention", "valueType": "STRING"},
    ])
    om_client = _FakeClient(existing={})
    bootstrap.bootstrap(_make_om(om_client), ep_client=ep_client)
    posted_names = [body.get("name") for _, body in om_client.posts]
    assert "EventPortalCustomAttribute_DataRetention" in posted_names
