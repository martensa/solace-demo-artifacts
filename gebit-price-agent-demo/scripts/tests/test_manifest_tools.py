"""gen_connector_manifest.py and check_manifests.py (spec 8.1, 8.5)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

import check_manifests
import gen_connector_manifest as gen
from conftest import ROOT
from opslib import OpsError

SPECS = {c.path.rsplit("/", 1)[1][:-5]: c for c in gen.CONNECTORS}


def tool(name: str, output: bool, description: str = "One  tool,\n folded.") -> dict:
    entry = {"name": name, "description": description, "title": name,
             "inputSchema": {"type": "object", "properties": {"run_id": {"type": "string"}}}}
    if output:
        entry["outputSchema"] = {"type": "object", "properties": {"status": {"type": "string"}}}
    return entry


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    for spec in gen.CONNECTORS:
        target = tmp_path / spec.path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / spec.path, target)
    return tmp_path


def test_contract_matches_spec_8() -> None:
    assert SPECS["gpos-booth-tools"].tools == (
        "assess_event", "close_review", "check_proposal", "note_event", "note_evidence",
        "prepare_review", "raise_basket_review", "record_outcome", "stage_proposal")
    assert SPECS["gpos-price-gate"].tools == ("apply_price",)
    assert SPECS["gpos-price-apply"].tools == ("apply_price",)
    assert [s.workflow_tools for s in gen.CONNECTORS] == [True, True, True, False, False, False]
    assert {s.service for s in gen.CONNECTORS} == {"engine", "engine.gate", "wws", "loyalty",
                                                  "pos"}


def test_every_connector_carries_a_generated_manifest() -> None:
    """The manifests are generated (make manifests / --tools-json, 8.5); the comparison
    with --dump-tools itself is app/tests/integration/test_payload_contract.py."""
    for spec in gen.CONNECTORS:
        assert check_manifests.static_errors(spec) == []
        assert gen.GENERATED_MARK in (ROOT / spec.path).read_text()
        assert not gen.is_placeholder(ROOT / spec.path)


def test_a_placeholder_manifest_is_refused(tree: Path) -> None:
    spec = SPECS["gpos-wws-api"]
    path = tree / spec.path
    path.write_text(gen.replace_block(path.read_text(), "    manifest:\n"
                                      f"      {gen.PLACEHOLDER_MARK} -- make manifests\n"
                                      '      - name: "get_article"\n'))
    assert check_manifests.static_errors(spec, tree) == [
        f"{spec.path}: still the PLACEHOLDER manifest (make manifests)"]


def test_generated_gate_block_keeps_the_hil_gate(tree: Path) -> None:
    spec = SPECS["gpos-price-gate"]
    gen.write_connector(spec, [tool("apply_price", True)], root=tree)
    doc = yaml.safe_load((tree / spec.path).read_text())
    values = doc["spec"]["values"]
    assert values["manifest"] == [{
        "name": "apply_price", "description": "One tool, folded.",
        "inputSchema": tool("apply_price", True)["inputSchema"],
        "outputSchema": tool("apply_price", True)["outputSchema"]}]
    assert values["hil"]["tools"]["apply_price"]["require_approval"] is True
    assert gen.GENERATED_MARK in (tree / spec.path).read_text()
    assert check_manifests.static_errors(spec, tree) == []
    # regenerating is idempotent
    before = (tree / spec.path).read_text()
    gen.write_connector(spec, [tool("apply_price", True)], root=tree)
    assert (tree / spec.path).read_text() == before


def test_contract_violations_are_refused(tree: Path) -> None:
    before = (tree / SPECS["gpos-wws-api"].path).read_text()
    with pytest.raises(OpsError, match="without outputSchema"):
        gen.write_connector(SPECS["gpos-price-gate"], [tool("apply_price", False)], root=tree)
    with pytest.raises(OpsError, match="has an outputSchema"):
        gen.write_connector(SPECS["gpos-pos-api"], [tool("get_transaction", True),
                                                    tool("get_till_status", False)], root=tree)
    with pytest.raises(OpsError, match="!= spec"):
        gen.write_connector(SPECS["gpos-wws-api"], [tool("get_article", False)], root=tree)
    assert (tree / SPECS["gpos-wws-api"].path).read_text() == before  # nothing written


def test_tool_list_shapes() -> None:
    tools = [tool("x", False)]
    assert gen.tool_list(tools) == tools
    assert gen.tool_list({"tools": tools}) == tools
    assert gen.tool_list({"result": {"tools": tools}}) == tools
    with pytest.raises(OpsError):
        gen.tool_list({"tools": "nope"})


def test_live_diff_names_the_changed_field() -> None:
    spec = SPECS["gpos-wws-api"]
    stored = gen.build_entries([tool("get_article", False), tool("get_season_info", False)])
    live = gen.build_entries([tool("get_article", False, "changed"),
                              tool("get_sales_performance", False)])
    assert check_manifests.diff_entries(spec, stored, live) == [
        f"{spec.path}: get_article.description differs from the running service",
        f"{spec.path}: get_sales_performance only live",
        f"{spec.path}: get_season_info only in the file",
    ]
