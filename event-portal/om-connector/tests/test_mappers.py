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
    CP_CONSUMER_BROKER_TYPE,
    CP_CONSUMER_ID,
    CP_CONSUMER_SUBSCRIPTIONS,
    CP_CONSUMER_TYPE,
    CP_EP_DOMAIN,
    CP_EP_EVENT,
    CP_STATE,
    CP_TOPIC_ADDRESS,
    EpUrls,
    _normalize_schema_format,
    app_to_pipeline_request,
    build_topic_name,
    lineage_source_manual,
    consumer_container_fqn,
    consumer_to_container_request,
    domain_to_create_request,
    event_to_topic_request,
    extract_topic_address,
    sanitize,
    topic_fqn,
    topic_segment_container_fqn,
    topic_segment_to_container_request,
)
from connector.property_keys import (  # noqa: E402
    CONSUMER_STORAGE_SERVICE_NAME,
    CP_TOPIC_SEGMENT,
    CP_TOPIC_SEGMENT_DEPTH,
    CP_TOPIC_SEGMENT_PATH,
    TOPIC_TREE_STORAGE_SERVICE_NAME,
)


def test_sanitize_replaces_invalid_chars():
    assert sanitize("orders/created v1") == "orders_created_v1"


def test_build_topic_name_includes_version():
    assert build_topic_name("OrderCreated", "1.2.0") == "OrderCreated_v1.2.0"


def test_lineage_source_manual_resolves_across_om_versions():
    # OM 1.13 renamed the LineageSource enum to Source; the helper must still
    # resolve the Manual member so container lineage edges carry a source
    # (a hard import of LineageSource silently dropped all container lineage).
    val = lineage_source_manual()
    assert val is not None
    assert getattr(val, "name", str(val)) == "Manual"


def test_normalize_schema_format_maps_ep_vocabulary():
    # EP returns schemaType="jsonSchema" / contentType="json", not "JSON".
    assert _normalize_schema_format("jsonSchema") == "JSON"
    assert _normalize_schema_format("json") == "JSON"
    assert _normalize_schema_format("AVRO") == "AVRO"
    assert _normalize_schema_format("protobuf") == "PROTOBUF"
    assert _normalize_schema_format("xsd") == "XSD"
    assert _normalize_schema_format(None) == "JSON"
    assert _normalize_schema_format("") == "JSON"


def test_event_to_topic_request_parses_jsonschema_payload():
    # Regression: EP schemaType "jsonSchema" must parse into structured
    # SchemaFields. It used to fall back to SchemaType.Other + [] because
    # "jsonSchema".upper() == "JSONSCHEMA" missed the format map.
    schema_text = (
        '{"$schema": "https://json-schema.org/draft/2019-09/schema",'
        ' "title": "PriceData", "type": "object",'
        ' "properties": {"price": {"type": "number"},'
        ' "currency": {"type": "string"}}}'
    )
    domain = {"id": "d-1", "name": "orders-domain"}
    event = {"id": "e-1", "name": "PriceChanged"}
    version = {
        "id": "ev-1",
        "version": "1.0.0",
        "stateId": "RELEASED",
        "deliveryDescriptor": {
            "address": {
                "addressLevels": [
                    {"name": "price", "addressLevelType": "LITERAL"},
                ]
            }
        },
    }
    schema_payload = {
        "schema": {"name": "PriceData", "schemaType": "jsonSchema"},
        "version": {"content": schema_text},
    }
    request = event_to_topic_request(
        service_name="solace-ep",
        domain=domain,
        event=event,
        event_version=version,
        schema_payload=schema_payload,
    )
    ms = request.messageSchema
    assert ms is not None
    assert ms.schemaType.value == "JSON"
    # OM's JSON-Schema parser yields a root RECORD whose children are the EP
    # properties; either way the field list must be non-empty (was [] pre-fix).
    assert ms.schemaFields, "schemaFields should be parsed, not empty"


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


# --------------------------------------------------------- Wave 3 (#55)


def test_consumer_container_fqn_is_under_consumer_storage_service():
    fqn = consumer_container_fqn("orders-svc", "orders.q")
    assert fqn.startswith(f"{CONSUMER_STORAGE_SERVICE_NAME}.")
    # Container name is sanitised ({app}_{consumer}) and the dotted segment
    # gets wrapped in double-quotes by `_quote_if_dotted` -- but neither
    # input contains a "." here once sanitised, so plain join.
    assert "orders-svc_orders_q" in fqn


def test_consumer_to_container_request_populates_extension():
    consumer = {
        "id": "c-1",
        "name": "orders.queue",
        "consumerType": "eventQueue",
        "brokerType": "solace",
        "subscriptions": [
            {
                "subscriptionType": "TOPIC",
                "value": "orders/*/created",
                "attractedEventVersionIds": ["ev-1", "ev-2"],
            },
            {
                "subscriptionType": "TOPIC",
                "value": "orders/*/cancelled",
                "attractedEventVersionIds": ["ev-3"],
            },
        ],
    }
    app = {"id": "a-1", "name": "OrdersConsumer"}
    app_version = {"id": "av-1", "version": "2.0.0"}
    domain = {"id": "d-1", "name": "orders-domain"}

    req = consumer_to_container_request(
        consumer=consumer, app=app, app_version=app_version, domain=domain,
    )
    assert req is not None
    # Service is the synthetic consumer StorageService.
    svc = getattr(req.service, "root", req.service)
    assert str(svc) == CONSUMER_STORAGE_SERVICE_NAME
    # Container name = sanitize("{app}_{consumer}"). The literal "." in
    # "orders.queue" becomes "_".
    assert req.name.root == "OrdersConsumer_orders_queue"

    ext_raw = getattr(req, "extension", None)
    ext = getattr(ext_raw, "root", ext_raw) or {}
    assert ext.get(CP_CONSUMER_ID) == "c-1"
    assert ext.get(CP_CONSUMER_TYPE) == "eventQueue"
    assert ext.get(CP_CONSUMER_BROKER_TYPE) == "solace"
    subs_md = ext.get(CP_CONSUMER_SUBSCRIPTIONS) or ""
    # Markdown table renders the patterns + their matched-events count.
    assert "orders/*/created" in subs_md
    assert "orders/*/cancelled" in subs_md
    # First row has 2 matched events, second has 1.
    assert "| 2 |" in subs_md
    assert "| 1 |" in subs_md


# --------------------------------------------------------- Wave 3 (#53)


def test_topic_segment_container_fqn_translates_variable_segments():
    """Variable segments `{region}` become `_region_` in the FQN."""
    fqn = topic_segment_container_fqn(["orders", "{region}", "created"])
    assert fqn.startswith(f"{TOPIC_TREE_STORAGE_SERVICE_NAME}.")
    # The variable segment was rewritten so it's a valid identifier.
    assert "_region_" in fqn
    assert "{region}" not in fqn


def test_topic_segment_to_container_request_populates_segment_metadata():
    req = topic_segment_to_container_request(
        segment="{region}",
        depth=2,
        segment_path=["orders", "{region}"],
        parent_fqn=f"{TOPIC_TREE_STORAGE_SERVICE_NAME}.orders",
    )
    assert req is not None
    svc = getattr(req.service, "root", req.service)
    assert str(svc) == TOPIC_TREE_STORAGE_SERVICE_NAME
    # The Container name (used in FQN) is identifier-safe; the displayName
    # keeps the original `{region}` form for UI readability.
    assert req.name.root == "_region_"
    dn = getattr(req, "displayName", None)
    assert dn == "{region}"
    # Parent reference is set (when supported).
    parent = getattr(req, "parent", None)
    parent_fqn = getattr(parent, "fullyQualifiedName", None) if parent else None
    parent_fqn_root = getattr(parent_fqn, "root", parent_fqn) if parent_fqn else None
    assert parent_fqn_root == f"{TOPIC_TREE_STORAGE_SERVICE_NAME}.orders"
    ext_raw = getattr(req, "extension", None)
    ext = getattr(ext_raw, "root", ext_raw) or {}
    assert ext.get(CP_TOPIC_SEGMENT) == "{region}"
    assert ext.get(CP_TOPIC_SEGMENT_PATH) == "orders/{region}"
    assert ext.get(CP_TOPIC_SEGMENT_DEPTH) == "2"


def test_consumer_to_container_request_handles_no_subscriptions():
    """No subscriptions -> subscription CP is absent (not the literal None)."""
    consumer = {"id": "c-2", "name": "orphan.queue"}
    app = {"id": "a-2", "name": "App2"}
    app_version = {"id": "av-2", "version": "1.0.0"}
    domain = {"id": "d-2", "name": "orphans"}

    req = consumer_to_container_request(
        consumer=consumer, app=app, app_version=app_version, domain=domain,
    )
    assert req is not None
    ext_raw = getattr(req, "extension", None)
    ext = getattr(ext_raw, "root", ext_raw) or {}
    # None-valued keys are stripped from the extension.
    assert CP_CONSUMER_SUBSCRIPTIONS not in ext
    # Sensible defaults filled in for missing consumerType/brokerType.
    assert ext.get(CP_CONSUMER_TYPE) == "eventQueue"
    assert ext.get(CP_CONSUMER_BROKER_TYPE) == "solace"


# --------------------------------------------------------- Wave 4 (#56)


def test_ep_urls_async_api_builds_downloadable_url():
    urls = EpUrls(
        api_url="https://api.solace.cloud/api/v2",
        async_api_version="2.5.0",
        async_api_format="json",
    )
    out = urls.async_api("av-123")
    assert out == (
        "https://api.solace.cloud/api/v2/architecture/applicationVersions/"
        "av-123/asyncApi?asyncApiVersion=2.5.0&format=json"
    )


def test_ep_urls_async_api_returns_none_when_api_url_missing():
    """Without api_url the connector must NOT emit a broken Pipeline.sourceUrl."""
    assert EpUrls().async_api("av-123") is None
    assert EpUrls(api_url="").async_api("av-123") is None


def test_ep_urls_async_api_returns_none_when_version_id_missing():
    urls = EpUrls(api_url="https://api.solace.cloud/api/v2")
    assert urls.async_api(None) is None
    assert urls.async_api("") is None


def test_app_to_pipeline_request_sets_async_api_source_url():
    """The Pipeline carries Pipeline.sourceUrl pointing at the
    downloadable AsyncAPI doc. Wave 4 (#56)."""
    urls = EpUrls(
        base="https://console.solace.cloud",
        api_url="https://api.solace.cloud/api/v2",
    )
    req = app_to_pipeline_request(
        domain={"id": "d-1", "name": "orders"},
        app={"id": "a-1", "name": "OrderService"},
        app_version={"id": "av-9", "version": "1.2.0"},
        ep_urls=urls,
        attach_to_domain=False,
    )
    assert req is not None
    src = getattr(req, "sourceUrl", None)
    src_str = getattr(src, "root", src)
    assert str(src_str) == (
        "https://api.solace.cloud/api/v2/architecture/applicationVersions/"
        "av-9/asyncApi?asyncApiVersion=2.5.0&format=json"
    )


# --------------------------------------------------------- Wave 4 (#48)


def test_domain_to_create_request_attaches_parent_fqn_when_given():
    """parent_fqn from the operator-configured map should land on
    CreateDomainRequest.parent so OM renders a sub-domain hierarchy."""
    req = domain_to_create_request(
        {"id": "d-1", "name": "Marketplace.Orders"},
        parent_fqn="Marketplace",
    )
    assert req is not None
    parent = getattr(req, "parent", None)
    # OM 1.11 accepts a plain FQN string; older SDKs an EntityReference.
    if hasattr(parent, "fullyQualifiedName"):
        fqn = getattr(parent, "fullyQualifiedName")
        fqn = getattr(fqn, "root", fqn)
        assert fqn == "Marketplace"
    else:
        # Plain string-form parent.
        assert str(getattr(parent, "root", parent)) == "Marketplace"


def test_domain_to_create_request_keeps_parent_none_without_mapping():
    """Without a parent_fqn the Domain is top-level (default behaviour)."""
    req = domain_to_create_request({"id": "d-1", "name": "Orders"})
    assert req is not None
    # No exception when accessing parent; pydantic returns None.
    assert getattr(req, "parent", None) is None


def test_app_to_pipeline_request_skips_source_url_when_api_url_missing():
    """If the operator hasn't passed api_url, the Pipeline should ingest
    without a sourceUrl rather than carrying a broken URL."""
    req = app_to_pipeline_request(
        domain={"id": "d-1", "name": "orders"},
        app={"id": "a-1", "name": "OrderService"},
        app_version={"id": "av-9", "version": "1.2.0"},
        ep_urls=EpUrls(),  # no api_url
        attach_to_domain=False,
    )
    assert req is not None
    src = getattr(req, "sourceUrl", None)
    assert src is None


def test_event_to_topic_request_pii_tag_and_cp():
    """Wave 5 (#62): contains_pii=True attaches the EventPortalCompliance.PII
    TagLabel + eventPortalContainsPii CP; default leaves both off."""
    from connector.mappers import CP_CONTAINS_PII, PII_TAG_FQN

    domain = {"id": "d-1", "name": "orders-domain"}
    event = {"id": "e-1", "name": "OrderCreated"}
    version = {"id": "ev-1", "version": "1.0.0", "stateId": "RELEASED"}

    base = event_to_topic_request(
        service_name="solace-ep", domain=domain, event=event,
        event_version=version, schema_payload=None,
    )
    base_ext = getattr(getattr(base, "extension", None), "root", {}) or {}
    assert CP_CONTAINS_PII not in base_ext
    base_tags = [str(getattr(t, "tagFQN", t)) for t in (base.tags or [])]
    assert not any(PII_TAG_FQN in s for s in base_tags)

    pii = event_to_topic_request(
        service_name="solace-ep", domain=domain, event=event,
        event_version=version, schema_payload=None, contains_pii=True,
    )
    pii_ext = getattr(getattr(pii, "extension", None), "root", {}) or {}
    assert pii_ext.get(CP_CONTAINS_PII) == "true"
    pii_tags = [str(getattr(t, "tagFQN", t)) for t in (pii.tags or [])]
    assert any(PII_TAG_FQN in s for s in pii_tags)
