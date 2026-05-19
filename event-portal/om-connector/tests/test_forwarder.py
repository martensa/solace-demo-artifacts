"""Forwarder tests.

Skipped automatically when FastAPI is not installed (it is the bridge's
optional extra). Uses FastAPI's TestClient to drive the receiver and a
fake publisher to assert the published topic + payload.
"""
import hashlib
import hmac
import json

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from bridge.config import (  # noqa: E402
    BridgeSettings,
    EventPortalSettings,
    OpenMetadataSettings,
    TransportSettings,
)
from bridge.forwarder import build_forwarder_app  # noqa: E402


class _FakePublisher:
    def __init__(self):
        self.published = []

    def publish(self, topic, body, properties):
        self.published.append({"topic": topic, "body": body, "properties": properties})

    def close(self):
        pass


def _settings_with_secret(secret: str) -> BridgeSettings:
    s = BridgeSettings(
        ep=EventPortalSettings(webhook_secret=secret),
        om=OpenMetadataSettings(),
        transport=TransportSettings(),
    )
    return s


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_forwarder_publishes_to_topic_with_event_type_suffix():
    secret = "fwd-secret"
    publisher = _FakePublisher()
    app = build_forwarder_app(
        settings=_settings_with_secret(secret), publisher=publisher
    )
    payload = {"eventType": "event.updated", "eventId": "evt-42"}
    body = json.dumps(payload).encode()

    client = TestClient(app)
    resp = client.post(
        "/webhook/event-portal",
        data=body,
        headers={"Solace-Signature": _sign(body, secret)},
    )

    assert resp.status_code == 200
    assert len(publisher.published) == 1
    msg = publisher.published[0]
    assert msg["topic"] == "om/sync/eventportal/event.updated"
    assert msg["body"] == body
    assert msg["properties"]["eventType"] == "event.updated"
    assert msg["properties"]["eventId"] == "evt-42"


def test_forwarder_rejects_bad_signature():
    publisher = _FakePublisher()
    app = build_forwarder_app(
        settings=_settings_with_secret("right"), publisher=publisher
    )
    body = b'{"eventType":"event.updated"}'

    client = TestClient(app)
    resp = client.post(
        "/webhook/event-portal",
        data=body,
        headers={"Solace-Signature": _sign(body, "wrong")},
    )

    assert resp.status_code == 401
    assert publisher.published == []


def test_forwarder_rejects_malformed_json():
    secret = "s"
    publisher = _FakePublisher()
    app = build_forwarder_app(
        settings=_settings_with_secret(secret), publisher=publisher
    )
    body = b"not-json"

    client = TestClient(app)
    resp = client.post(
        "/webhook/event-portal",
        data=body,
        headers={"Solace-Signature": _sign(body, secret)},
    )

    assert resp.status_code == 400
    assert publisher.published == []
