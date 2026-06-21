"""Pure FQN-helper tests (Wave 5 / #41 multi-tenant).

connector.fqn has no OM-SDK dependency, so these run everywhere -- the
core regression guard that an empty tenant prefix leaves single-tenant
FQNs byte-identical (zero drift for the existing ALDI deployment).
"""
from connector.fqn import (
    APP_PIPELINE_SERVICE_NAME,
    app_pipeline_fqn,
    apply_tenant_prefix,
)


def test_apply_tenant_prefix_empty_is_identity():
    base = APP_PIPELINE_SERVICE_NAME
    assert apply_tenant_prefix(base, "") == base
    assert apply_tenant_prefix(base, None) == base


def test_apply_tenant_prefix_composes_and_sanitizes():
    assert apply_tenant_prefix("svc", "t1") == "t1-svc"
    # A stray dot in the prefix can never break the FQN separator.
    assert apply_tenant_prefix("svc", "eu.tenant") == "eu_tenant-svc"


def test_app_pipeline_fqn_default_is_legacy_byte_identical():
    # The exact FQN the single-tenant ALDI deployment already produces.
    assert app_pipeline_fqn("orders", "1.0.0") == (
        'solace-event-portal-apps."orders_v1.0.0"'
    )


def test_app_pipeline_fqn_with_prefix_is_distinct_and_noncolliding():
    legacy = app_pipeline_fqn("orders", "1.0.0")
    t1 = app_pipeline_fqn(
        "orders", "1.0.0",
        service_name=apply_tenant_prefix(APP_PIPELINE_SERVICE_NAME, "t1"),
    )
    t2 = app_pipeline_fqn(
        "orders", "1.0.0",
        service_name=apply_tenant_prefix(APP_PIPELINE_SERVICE_NAME, "t2"),
    )
    # The exact collision the ticket cites: same app name, two tenants.
    assert t1 != t2
    assert t1 != legacy
    assert t1 == 't1-solace-event-portal-apps."orders_v1.0.0"'


def test_app_pipeline_fqn_explicit_none_prefix_equals_default():
    assert app_pipeline_fqn("orders", "1.0.0", service_name=None) == app_pipeline_fqn(
        "orders", "1.0.0"
    )
