"""Mapper tests.

These tests are skipped automatically when the OpenMetadata ingestion
package is not installed (the package is only available inside the OM
ingestion image). Run them inside the bridge / connector container, or
install `openmetadata-ingestion` in a dev env.
"""
from __future__ import annotations

import pytest

pytest.importorskip("metadata.generated.schema.api.data.createTopic")

from connector.mappers import (  # noqa: E402
    CP_EP_DOMAIN,
    CP_EP_EVENT,
    CP_STATE,
    CP_TOPIC_ADDRESS,
    build_topic_name,
    event_to_topic_request,
    extract_topic_address,
    sanitize,
    topic_fqn,
)


def test_sanitize_replaces_invalid_chars():
    assert sanitize("orders/created v1") == "orders_created_v1"


def test_build_topic_name_includes_version():
    assert build_topic_name("OrderCreated", "1.2.0") == "OrderCreated_v1.2.0"


def test_topic_fqn_joins_service_and_topic():
    # FQN segments with dots get auto-quoted because OM treats '.' as the
    # FQN separator. The version suffix `v1.0.0` contains dots -> the topic
    # part is wrapped in double-quotes by `_quote_if_dotted()`.
    assert topic_fqn("solace-ep", "Order", "1.0.0") == 'solace-ep."Order_v1.0.0"'


def test_extract_topic_address_with_variables():
    ev = {
        "deliveryDescriptor": {
            "address": {
                "addressLevels": [
                    {"name": "orders", "addressLevelType": "LITERAL"},
                    {"name": "region", "addressLevelType": "VARIABLE"},
                    {"name": "created", "addressLevelType": "LITERAL"},
                ]
            }
        }
    }
    assert extract_topic_address(ev) == "orders/{region}/created"


def test_extract_topic_address_returns_none_when_empty():
    assert extract_topic_address({}) is None


def test_event_to_topic_request_sets_custom_properties():
    domain = {"id": "d-1", "name": "orders-domain"}
    event = {"id": "e-1", "name": "OrderCreated", "description": "fires on order"}
    version = {
        "id": "ev-1",
        "version": "1.0.0",
        "stateId": "RELEASED",
        "updatedTime": "2026-05-01T12:00:00Z",
        "schemaVersionId": "sv-1",
        "deliveryDescriptor": {
            "address": {
                "addressLevels": [
                    {"name": "orders", "addressLevelType": "LITERAL"},
                    {"name": "created", "addressLevelType": "LITERAL"},
                ]
            }
        },
    }
    request = event_to_topic_request(
        service_name="solace-ep",
        domain=domain,
        event=event,
        event_version=version,
        schema_payload=None,
    )
    # Pydantic v2 RootModel exposes the wrapped value via `.root`
    # (was `.__root__` under v1). OM 1.6+ ships Pydantic v2.
    assert request.name.root == "OrderCreated_v1.0.0"
    assert request.service.root == "solace-ep"
    # `extension` is wrapped in EntityExtension(root=dict) under Pydantic v2;
    # unwrap so the test can dict-access the custom-property values.
    ext_raw = getattr(request, "extension", None)
    ext = getattr(ext_raw, "root", ext_raw) or {}
    # Since #35 the mapper emits markdown-link CPs (`[name](url)`) instead
    # of the legacy plain-id/name CPs. Domain + event still carry their
    # human-readable name and EP-version-id inside the markdown URL.
    assert "orders-domain" in str(ext.get(CP_EP_DOMAIN, ""))
    assert "ev-1" in str(ext.get(CP_EP_EVENT, ""))
    assert ext.get(CP_TOPIC_ADDRESS) == "orders/created"
    assert ext.get(CP_STATE) == "Released"
