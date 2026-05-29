"""Unit tests for the cross-system lineage source.

Pure-function helpers only; the full Source lifecycle is exercised by
the workflow-level smoke tests.
"""
from __future__ import annotations

import pytest

pytest.importorskip("metadata.utils.service_spec")

from connector.lineage_source import _ca_values  # noqa: E402


def test_ca_values_returns_empty_when_no_def_id():
    assert _ca_values([{"customAttributeDefinitionId": "a", "value": "v"}], None) == []


def test_ca_values_extracts_single_value():
    cas = [
        {"customAttributeDefinitionId": "a", "value": "sap-erp.SAPS4.HR.WORKFORCE"},
        {"customAttributeDefinitionId": "other", "value": "ignored"},
    ]
    assert _ca_values(cas, "a") == ["sap-erp.SAPS4.HR.WORKFORCE"]


def test_ca_values_splits_comma_list():
    cas = [
        {
            "customAttributeDefinitionId": "a",
            "value": "snowflake.RAW.STG_ORDERS, snowflake.RAW.STG_RETURNS",
        },
    ]
    assert _ca_values(cas, "a") == [
        "snowflake.RAW.STG_ORDERS",
        "snowflake.RAW.STG_RETURNS",
    ]


def test_ca_values_strips_whitespace_and_drops_empty():
    cas = [{"customAttributeDefinitionId": "a", "value": "x, , y"}]
    assert _ca_values(cas, "a") == ["x", "y"]


def test_ca_values_skips_unrelated_ca_entries():
    cas = [
        {"customAttributeDefinitionId": "wrong", "value": "drop"},
        {"customAttributeDefinitionId": "right", "value": "keep"},
    ]
    assert _ca_values(cas, "right") == ["keep"]


def test_service_spec_wiring_exposes_both_classes():
    """Smoke: the ServiceSpec object registers BOTH the metadata source
    and the new lineage source so a workflow YAML can pick either."""
    from connector.service_spec import ServiceSpec
    assert ServiceSpec.metadata_source_class.endswith("SolaceEventPortalSource")
    assert ServiceSpec.lineage_source_class.endswith("EventPortalLineageSource")
