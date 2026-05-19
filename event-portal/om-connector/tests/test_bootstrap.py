"""Bootstrap idempotency tests.

We stub OpenMetadata's REST client because the bootstrap module talks to
OM exclusively through it. The tests verify:
  * classification + tag creation is skipped when already present
  * custom property creation is skipped when already present
  * fresh OM gets exactly the expected create calls
"""
from unittest.mock import MagicMock

from connector import bootstrap


class _FakeClient:
    """Pretends to be `OpenMetadata.client` with a configurable knowledge base."""

    def __init__(self, existing=None):
        self.existing = existing or {}
        self.posts = []
        self.puts = []

    def get(self, path):
        if path not in self.existing:
            raise RuntimeError(f"404 {path}")
        return self.existing[path]

    def post(self, path, data=None):
        self.posts.append((path, data))
        return data or {}

    def put(self, path, data=None):
        self.puts.append((path, data))
        return data or {}


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
