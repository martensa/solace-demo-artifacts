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

    client = _FakeClient(existing=populated)
    bootstrap.bootstrap(_make_om(client))
    assert client.posts == []
    assert client.puts == []


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
