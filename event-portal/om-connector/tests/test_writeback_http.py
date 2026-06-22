"""OM webhook receiver tests (Wave 4.5 / #49).

Requires fastapi + httpx (the bridge extra); importorskip keeps the lean
environment green. Locks the security-relevant signature check + enqueue.
"""
import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from bridge.transport.writeback_http import build_writeback_app  # noqa: E402

SECRET = "om-shared-secret"
HEADER = "X-OM-Signature"


def _settings():
    return SimpleNamespace(
        writeback=SimpleNamespace(
            enabled=True, dry_run=True,
            om_webhook_secret=SECRET, om_webhook_header=HEADER,
        ),
        obs=SimpleNamespace(metrics_enabled=False),
    )


def _sign(body: bytes) -> str:
    return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def _client(processor):
    return TestClient(build_writeback_app(settings=_settings(), processor=processor))


def test_rejects_bad_signature():
    processor = MagicMock()
    client = _client(processor)
    body = json.dumps({"entityType": "topic"}).encode()
    resp = client.post(
        "/webhook/openmetadata", content=body, headers={HEADER: "deadbeef"}
    )
    assert resp.status_code == 401
    processor.enqueue.assert_not_called()


def test_accepts_signed_event_and_enqueues():
    processor = MagicMock()
    processor.enqueue.return_value = True
    client = _client(processor)
    body = json.dumps({"entityType": "topic", "entity": {}}).encode()
    resp = client.post(
        "/webhook/openmetadata", content=body, headers={HEADER: _sign(body)}
    )
    assert resp.status_code == 200
    processor.enqueue.assert_called_once()


def test_accepts_batch_list_of_events():
    processor = MagicMock()
    processor.enqueue.return_value = True
    client = _client(processor)
    body = json.dumps([{"entityType": "topic"}, {"entityType": "pipeline"}]).encode()
    resp = client.post(
        "/webhook/openmetadata", content=body, headers={HEADER: _sign(body)}
    )
    assert resp.status_code == 200
    assert processor.enqueue.call_count == 2


def test_readyz_reports_writeback_flags():
    client = _client(MagicMock())
    resp = client.get("/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["writeback_enabled"] is True
    assert body["dry_run"] is True
