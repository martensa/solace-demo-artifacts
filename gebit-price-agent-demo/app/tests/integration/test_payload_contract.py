"""Cross-package seams of UC1 (UC1-BUILD-SPEC 13.2, 2.2, 3.1, 7, 8, 9).

The packages were built in parallel against the spec; this module pins the places where
they meet, always against what the code really does, never against a copied list:

Static part (no marker, runs in ``make test``):

* ``python -m gposdemo.<svc> --dump-tools`` (2.4, 8.5) against ``mesh/``: the generated
  connector manifests, every tool node of every workflow (tool, input names, string
  inputs), every ``{{node.output.mcp_structured_content.<field>}}`` and every
  ``{{node.output.<field>}}`` reference, the switch/``when`` values, the tools the agent
  prompts name and the approval card of the gate (9.3-9.5).
* SAM inputs (7.2): the keys the engine and the ``ui.ctl`` probes publish against the
  ``input_schema`` of the target workflow (finding 3).
* Topics (7.1, 9.6): the producers' topic builders against the rendered entrypoint
  subscriptions (booth and probe), the ``successOutput``/``errorOutput`` topics against
  the BFF, every producer topic against the ``gpos-ui`` subscriptions.
* Config (2.2, 3.1): the variables ``load_settings`` reads against ConfigMap, Secrets and
  Deployments in ``k8s/``; ports of connectors, ConfigMap and Deployments.

Flow part (markers ``integration``, ``db``, ``gebit``): wws, loyalty, pos, engine and gate
run in this process on their own scratch DB (``create(settings, bus, db)``, real gRPC on
free ports, MCP over in-process JSON-RPC, one ``MemoryBus``). The GEBIT events of till 99
come from the BFF facade; the three workflow YAMLs are executed node by node by a small
interpreter with SAM's semantics (templates, switch, ``when``, Argo-aligned skips,
``coalesce``, ``on_exit`` with ``workflow.error.message``), so every reference resolves
against a real tool result. The three agents are simulated strictly by their prompt
contract: the evidence agent (fast) calls the real agent tools, the planner (planning)
has no tools, the approver calls the real gated ``apply_price`` and copies the result's
``message`` (SAM's texts on a denial or timeout, 12.11.) or ends its task with the
observed 12.11. error texts.
"""

from __future__ import annotations

import json
import math
import re
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
import yaml
from starlette.testclient import TestClient

from gposdemo.common import mcputil, topics
from gposdemo.common.bus import MemoryBus, Published, topic_matches
from gposdemo.common.config import DEFAULT_PORTS, Settings, load_settings
from gposdemo.common.jsonutil import canonical, compact
from gposdemo.engine.ingest import VERDICTS
from gposdemo.engine.state import APPROVAL_REQUEST_KEYS, REVIEW_REQUEST_KEYS
from gposdemo.ui import ctl, feed, refdata
from gposdemo.ui.counters import Counters

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "app"
MESH = ROOT / "mesh"
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:  # render_mesh, gen_connector_manifest (WP-H, single source)
    sys.path.insert(0, str(SCRIPTS))

import gen_connector_manifest  # noqa: E402
import render_mesh  # noqa: E402

LAB_ENV = {"GPOS_BOOTH_LOCATION": "Root.DE.999.101.01",
           "GPOS_PROBE_LOCATION": "Root.DE.999.199.98"}
# settings read only in tests (never in the ConfigMap): the HIL window of 11.5
TEST_ONLY_SETTINGS = {"HIL_TIMEOUT_S"}
PARTS = [("booth", "Root.DE.999.101.01"), ("probe", "Root.DE.999.199.98")]
TEST_LOCATION = "Root.DE.999.199.99"
TX = "5b1f0c2e-8d1e-4a43-9a51-0c7a2f0e1b11"
DUMMY_SECRETS = {"__BROKER_USERNAME__": "x", "__BROKER_PASSWORD__": "x"}
# server_url host of a connector -> module of `python -m gposdemo.<module>`
HOST_MODULE = {"gpos-engine": "engine", "gpos-gate": "engine.gate", "gpos-wws": "wws",
               "gpos-loyalty": "loyalty", "gpos-pos": "pos"}
MODULE_SERVICE = {"engine": "engine", "engine.gate": "gate", "wws": "wws",
                  "loyalty": "loyalty", "pos": "pos"}
R1_EVENTS = ("PositionAdded", "ArticlePositionVoided", "LoyaltyMembershipAssigned",
             "PurchaseTransactionClosed", "PurchaseTransactionCancelled")
# the other GEBIT events of 4.2: seen by the monitor only, never by R1/P1
NON_R1_EVENTS = ("PurchaseTransactionCreated", "PurchaseTransactionOpened",
                 "FiscalTransactionAssigned", "PaymentProcessStarted",
                 "CashPaymentPositionCreated", "PaymentProcessCompleted",
                 "PurchaseTransactionInChargingFinancialTransaction",
                 "PurchaseTransactionInClosing", "PurchaseTransactionInCancellation")
# result values of 8.2 the workflows branch on (models.py documents the same sets)
TOOL_VALUES = {
    ("assess_event", "verdict"): {"scan", "member", "void", "close", "cancel", "ignore",
                                  "duplicate", "stale"},
    ("prepare_review", "candidate"): {"yes", "no"},
    ("check_proposal", "status"): {"awaiting_approval", "unknown", "stale", "superseded",
                                   "decided", "probe"},
    ("record_outcome", "notify"): {"yes", "no"},
    ("note_evidence", "status"): {"noted", "stale", "unknown"},
}
# keys of the own UI payloads of 7.2 (the examples), as the monitor reads them
INSIGHT_KEYS = {"schema_version", "type", "ts", "tx_id", "store", "till", "event_key",
                "position_id", "article_number", "article_name", "code", "severity", "text",
                "price", "price_source", "run_id"}
REVIEW_KEYS = {"schema_version", "type", "state", "ts", "review_id", "tx_id", "store", "till",
               "membership", "candidates", "run_id", "lines"}
PROPOSAL_KEYS = {"schema_version", "type", "state", "ts", "proposal_id", "review_id", "store",
                 "till", "article_number", "article_name", "reason", "reason_label",
                 "step_pct", "clamped", "old_price", "new_price", "pct_shown", "pct_label",
                 "ref30", "margin_pct_new", "base_price_label", "valid_to", "valid_to_label",
                 "headline", "rationale", "facts_line", "note", "text_source", "ai_model",
                 "run_id", "guardrails"}
TELEMETRY_KEYS = {"schema_version", "type", "ts", "service", "tool", "caller", "ref",
                  "run_id", "ms", "ok", "summary"}
REF = re.compile(r"\{\{\s*([A-Za-z_]\w*(?:\.\w+)+)\s*\}\}")
CONDITION = re.compile(r"^\s*'(?P<left>.*)'\s*==\s*'(?P<right>.*)'\s*$", re.DOTALL)
GO_FIELD = re.compile(r"\{\{\s*\.(\w+)\s*\}\}")
TOOL_NAME = re.compile(r"\b(?:get|apply)_[a-z_]+\b")


# ============================================================================ helpers
def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def mesh_docs(kind: str) -> dict[str, dict[str, Any]]:
    """``{name: doc}`` of ``mesh/<kind>/*.yaml`` and ``mesh/fallback/<kind>/*.yaml``; the F2
    variant of a workflow is keyed ``<name>@f2``."""
    docs: dict[str, dict[str, Any]] = {}
    for base, suffix in ((MESH, ""), (MESH / "fallback", "@f2")):
        for path in sorted((base / kind).glob("*.yaml")):
            doc = load_yaml(path)
            docs[doc["name"] + (suffix if kind == "workflows" else "")] = doc
    return docs


def app_config(workflow: dict[str, Any]) -> dict[str, Any]:
    return workflow["spec"]["appConfig"]


def strings(value: Any) -> Iterator[str]:
    """Every string inside a YAML value, depth first."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def dump_tools(module: str) -> list[dict[str, Any]]:
    """``python -m gposdemo.<module> --dump-tools`` with an empty environment (no DSN,
    no broker, no descriptor sets: 2.4)."""
    proc = subprocess.run([sys.executable, "-m", f"gposdemo.{module}", "--dump-tools"],
                          cwd=APP, env={"PATH": "/usr/bin:/bin"}, capture_output=True,
                          text=True, timeout=120, check=False)
    assert proc.returncode == 0, proc.stderr[-400:]
    return gen_connector_manifest.tool_list(json.loads(proc.stdout))


def connector_module(connector: dict[str, Any]) -> tuple[str, int]:
    """``(module, port)`` from ``server_url`` ``http://<host>.gpos-demo.svc:<port>/mcp``."""
    url = connector["spec"]["values"]["server_url"]
    match = re.fullmatch(r"http://([a-z-]+)\.gpos-demo\.svc:(\d+)/mcp", url)
    assert match, url
    return HOST_MODULE[match.group(1)], int(match.group(2))


def rendered_rules(part: str, env: Mapping[str, str], mode: str = "sam") -> dict[str, dict]:
    """``{rule name: rule}`` of the entrypoint template as ``render_mesh`` renders it."""
    name = render_mesh.ENTRYPOINTS[part]
    text = (render_mesh.TEMPLATES / f"{name}.yaml.template").read_text(encoding="utf-8")
    if part == "booth":
        text = render_mesh.select_r1_block(text, mode)
    text = render_mesh.substitute(text, render_mesh.placeholder_values(env), DUMMY_SECRETS)
    rules = yaml.safe_load(text)["spec"]["values"]["event_rules"]
    return {rule["name"]: rule for rule in rules}


def subscriptions(rule: Mapping[str, Any]) -> list[str]:
    return [s["topic"] for s in rule.get("subscriptions", [])]


def rule_short(rule_name: str) -> str:
    """``r1_booth_till`` -> ``r1`` (the ``gpos/v1/sam/…/{rule}`` level)."""
    return rule_name.split("_", 1)[0]


def check_input_schema(schema: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    """What SAM checks on a structured input (finding 3): every key declared, required
    keys present, value types allowed; ``type``/``ts`` never appear in a SAM input."""
    props = schema["properties"]
    assert set(payload) <= set(props), f"undeclared keys {set(payload) - set(props)}"
    assert set(schema.get("required", [])) <= set(payload)
    assert not {"type", "ts"} & set(payload)
    for key, value in payload.items():
        allowed = props[key]["type"]
        allowed = allowed if isinstance(allowed, list) else [allowed]
        kind = "null" if value is None else "string" if isinstance(value, str) else "other"
        assert kind in allowed, f"{key}={value!r} not {allowed}"


class RecordingEnv(dict[str, str]):
    """A process environment that records every key ``load_settings`` asks for."""

    def __init__(self) -> None:
        super().__init__()
        self.asked: set[str] = set()

    def get(self, key: str, default: Any = None) -> Any:
        self.asked.add(key)
        return super().get(key, default)


# ============================================================================ fixtures
@pytest.fixture(scope="module")
def served() -> dict[str, list[dict[str, Any]]]:
    """The tool lists of the five MCP services, as ``--dump-tools`` prints them."""
    return {module: dump_tools(module) for module in MODULE_SERVICE}


@pytest.fixture(scope="module")
def connectors() -> dict[str, dict[str, Any]]:
    return mesh_docs("connectors")


@pytest.fixture(scope="module")
def tool_schemas(served: dict[str, list[dict[str, Any]]],
                 connectors: dict[str, dict[str, Any]]) -> dict[str, dict[str, dict]]:
    """``{connector: {tool: tools/list entry}}`` of the service each connector points at."""
    return {name: {t["name"]: t for t in served[connector_module(doc)[0]]}
            for name, doc in connectors.items()}


# ============================================================================ 8.5, 2.2
def test_dump_tools_lists_exactly_the_tools_of_8_2_to_8_4(
        served: dict[str, list[dict[str, Any]]]) -> None:
    names = {module: sorted(t["name"] for t in tools) for module, tools in served.items()}
    assert names == {
        "engine": ["assess_event", "check_proposal", "close_review", "note_event",
                   "note_evidence", "prepare_review", "raise_basket_review",
                   "record_outcome", "stage_proposal"],
        "engine.gate": ["apply_price"],
        "wws": ["get_article", "get_sales_performance", "get_season_info"],
        "loyalty": ["get_member_profile", "get_purchase_behaviour"],
        "pos": ["get_till_status", "get_transaction"]}
    for module, tools in served.items():
        workflow_tools = module in ("engine", "engine.gate")
        for tool in tools:
            props = tool["inputSchema"]["properties"]
            assert all(p["type"] == "string" for p in props.values()), tool["name"]  # 8.1
            optional = "run_id" if workflow_tools else "ref"
            assert props[optional]["default"] == "", tool["name"]
            assert bool(tool.get("outputSchema")) is workflow_tools, tool["name"]


@pytest.mark.parametrize("name", ["gpos-booth-tools", "gpos-price-gate", "gpos-wws-api",
                                  "gpos-loyalty-api", "gpos-pos-api", "gpos-price-apply"])
def test_connector_points_at_its_service_and_carries_the_generated_manifest(
        name: str, connectors: dict[str, dict[str, Any]],
        served: dict[str, list[dict[str, Any]]]) -> None:
    module, port = connector_module(connectors[name])
    assert port == DEFAULT_PORTS[MODULE_SERVICE[module]][1]  # 2.2 MCP port
    manifest = connectors[name]["spec"]["values"]["manifest"]
    assert manifest == gen_connector_manifest.build_entries(served[module]), (
        f"{name}: manifest differs from --dump-tools, run make manifests")


def test_gate_card_shows_only_apply_price_arguments(
        tool_schemas: dict[str, dict[str, dict]],
        connectors: dict[str, dict[str, Any]]) -> None:
    hil = connectors["gpos-price-gate"]["spec"]["values"]["hil"]["tools"]
    assert list(hil) == ["apply_price"]
    shown = set(GO_FIELD.findall(hil["apply_price"]["approval_message"]))
    params = set(tool_schemas["gpos-price-gate"]["apply_price"]["inputSchema"]["properties"])
    assert shown == {"article_name", "old_price", "new_price", "pct_label", "reason_label",
                     "valid_to_label", "proposal_id"}
    assert shown <= params
    assert "hil" not in connectors["gpos-price-apply"]["spec"]["values"]  # F2: ungated


# ============================================================================ 9.4, 9.5
WORKFLOW_KEYS = sorted(mesh_docs("workflows"))


@pytest.mark.parametrize("key", WORKFLOW_KEYS)
def test_every_workflow_reference_resolves_against_the_served_tools(
        key: str, tool_schemas: dict[str, dict[str, dict]]) -> None:
    app = app_config(mesh_docs("workflows")[key])
    nodes = {n["id"]: n for n in app["nodes"]}
    inputs = set(app["input_schema"]["properties"]) if "input_schema" in app else {"text"}
    for node in app["nodes"]:
        if node["type"] == "tool" and "connector" in node:
            schema = tool_schemas[node["connector"]][node["tool"]]["inputSchema"]
            given = node["input"]
            assert set(given) <= set(schema["properties"]), node["id"]
            assert set(schema.get("required", [])) <= set(given), node["id"]
            assert all(isinstance(v, str) for v in given.values()), node["id"]  # 8.1
    texts = [(n["id"], s) for n in app["nodes"] for s in strings(n)]
    texts += [("output_mapping", s) for s in strings(app.get("output_mapping", {}))]
    for where, text in texts:
        for path in REF.findall(text):
            head, *rest = path.split(".")
            if head == "workflow":
                assert rest[0] in ("run_id", "input", "error"), f"{where}: {path}"
                if rest[0] == "input":
                    assert rest[1] in inputs, f"{where}: {path} not in input_schema"
                continue
            ref = nodes[head]
            if ref["type"] == "tool" and "connector" in ref:
                assert rest[:2] == ["output", "mcp_structured_content"], f"{where}: {path}"
                out = tool_schemas[ref["connector"]][ref["tool"]]["outputSchema"]
                assert rest[2] in out["properties"], f"{where}: {path} not in {ref['tool']}"
            else:
                assert ref["type"] == "agent" and rest[0] == "output", f"{where}: {path}"
                assert rest[1] in ref["output_schema_override"]["properties"], (
                    f"{where}: {path} not in the output_schema_override of {head}")


@pytest.mark.parametrize("key", WORKFLOW_KEYS)
def test_switch_and_when_compare_with_values_the_producer_returns(key: str) -> None:
    app = app_config(mesh_docs("workflows")[key])
    nodes = {n["id"]: n for n in app["nodes"]}
    agents = mesh_docs("agents")
    conditions = [c["condition"] for n in app["nodes"] for c in n.get("cases", [])]
    conditions += [n["when"] for n in app["nodes"] if "when" in n]
    assert conditions
    for condition in conditions:
        match = CONDITION.match(condition)
        assert match, f"not a positive '…' == '…' condition (hard rule 6): {condition}"
        (path,) = REF.findall(match["left"])
        head, *rest = path.split(".")
        value, ref = match["right"], nodes[head]
        if ref["type"] == "tool":
            assert value in TOOL_VALUES[(ref["tool"], rest[-1])], condition
        else:
            prop = ref["output_schema_override"]["properties"][rest[-1]]
            if "enum" in prop:
                assert value in prop["enum"], condition
            else:  # F2: the word the approver prompt answers with
                prompt = agents[ref["agent_name"]]["spec"]["systemPrompt"]
                assert f'{rest[-1]} "{value}"' in prompt, condition
    assert VERDICTS["PurchaseTransactionClosed"] == "close"


def test_agent_prompts_name_only_tools_of_their_connectors(
        tool_schemas: dict[str, dict[str, dict]]) -> None:
    agents = mesh_docs("agents")
    assert {"gpos-pricing-agent", "gpos-price-planner", "gpos-price-approver",
            "gpos-price-approver-f2"} == set(agents)
    for name, agent in agents.items():
        spec = agent["spec"]
        reachable = {t for c in spec.get("connectors") or [] for t in tool_schemas[c]}
        named = set(TOOL_NAME.findall(spec["systemPrompt"]))
        if not reachable:
            if "builtin_time_tools" in spec.get("toolsets", []):  # F2: builtin time tool
                continue
            assert named == set(), f"{name} has no connector but names {named}"  # planner
            continue
        assert named and named <= reachable, f"{name}: {named - reachable}"


def test_planner_has_no_tools_and_the_planning_alias() -> None:
    planner = mesh_docs("agents")["gpos-price-planner"]["spec"]
    assert (planner["modelProvider"], planner.get("connectors")) == (["planning"], [])
    assert not {"temperature", "top_p", "top_k", "toolsetConfigs"} & set(planner)
    # A-21: the two auto-attached toolsets are listed only to carry their exclusions
    excluded = planner["toolsetExcludedTools"]
    assert planner["toolsets"] == list(excluded) == ["builtin_artifact_tools",
                                                     "data_analysis"]
    assert sum(len(tools) for tools in excluded.values()) == 12


def test_every_agent_excludes_the_auto_attached_toolsets() -> None:
    """A-21 (12.11.): exclusions survive only for listed toolsets; F2 adds its time tool."""
    for name, agent in mesh_docs("agents").items():
        spec = agent["spec"]
        excluded = spec["toolsetExcludedTools"]
        assert list(excluded) == ["builtin_artifact_tools", "data_analysis"], name
        assert [t for t in spec["toolsets"] if t != "builtin_time_tools"] == list(excluded)
        assert ("builtin_time_tools" in spec["toolsets"]) is name.endswith("-f2"), name
        assert sum(len(set(tools)) for tools in excluded.values()) == 12, name


def test_approver_copies_exactly_the_apply_price_arguments(
        tool_schemas: dict[str, dict[str, dict]]) -> None:
    approve = next(n for n in app_config(mesh_docs("workflows")["gpos-price-approval"])
                   ["nodes"] if n["id"] == "approve")
    params = tool_schemas["gpos-price-gate"]["apply_price"]["inputSchema"]["properties"]
    assert set(approve["input"]) == set(params) - {"approved_at"}
    prompt = mesh_docs("agents")["gpos-price-approver"]["spec"]["systemPrompt"]
    listed = re.search(r"values from the input: ([a-z_,\s]+)\.", prompt)
    assert listed is not None
    assert {p.strip() for p in listed.group(1).split(",")} == set(approve["input"])


def test_agent_inputs_chain_prepare_note_recommend(
        tool_schemas: dict[str, dict[str, dict]]) -> None:
    nodes = {n["id"]: n for n in app_config(mesh_docs("workflows")["gpos-basket-review"])
             ["nodes"]}
    agents = mesh_docs("agents")
    agent_input = "{{prepare.output.mcp_structured_content.agent_input}}"
    assert nodes["gather"]["input"] == {"review": agent_input}
    assert nodes["recommend"]["input"] == {
        "review": agent_input, "evidence": "{{note.output.mcp_structured_content.evidence}}"}
    for node, agent in (("gather", "gpos-pricing-agent"), ("recommend", "gpos-price-planner")):
        assert nodes[node]["agent_name"] == agent
        assert agents[agent]["spec"]["additionalConfigurations"]["outputSchema"] == nodes[
            node]["output_schema_override"]
    # every slot of the evidence agent reaches note_evidence under its own name
    gather = set(nodes["gather"]["output_schema_override"]["properties"])
    assert {k: v for k, v in nodes["note"]["input"].items() if k in gather} == {
        k: f"{{{{gather.output.{k}}}}}" for k in gather}
    params = tool_schemas["gpos-booth-tools"]["note_evidence"]["inputSchema"]["properties"]
    assert set(nodes["note"]["input"]) == set(params)
    f2 = {n["id"]: n for n in app_config(mesh_docs("workflows")["gpos-price-approval@f2"])
          ["nodes"]}
    assert f2["record"]["input"]["approved_at"] == "{{approve.output.time}}"


# ============================================================================ 7.2 SAM inputs
def test_engine_sam_inputs_are_exactly_the_input_schemas() -> None:
    workflows = mesh_docs("workflows")
    for key, keys in (("gpos-basket-review", REVIEW_REQUEST_KEYS),
                      ("gpos-price-approval", APPROVAL_REQUEST_KEYS),
                      ("gpos-price-approval@f2", APPROVAL_REQUEST_KEYS)):
        schema = app_config(workflows[key])["input_schema"]
        assert set(keys) == set(schema["properties"]), key
        check_input_schema(schema, dict.fromkeys(keys, "x"))
    assert "input_schema" not in app_config(workflows["gpos-pos-event"])  # raw text (R1)


@pytest.mark.parametrize("name", ctl.PROBE_NAMES)
def test_probe_topics_and_payloads_reach_their_rule(name: str) -> None:
    settings = load_settings("ui", LAB_ENV)
    probe = ctl.build_probe(name, settings, "00000000-0000-4000-8000-000000000000")
    part = "booth" if probe.rule.startswith("r") else "probe"
    rules = rendered_rules(part, LAB_ENV)
    hits = [r for r, rule in rules.items()
            if any(topic_matches(t, probe.topic) for t in subscriptions(rule))]
    assert [rule_short(r) for r in hits] == [probe.rule]
    target = rules[hits[0]]["targetWorkflowName"]
    app = app_config(mesh_docs("workflows")[target])
    if "input_schema" in app:
        check_input_schema(app["input_schema"], probe.payload)
    expected_keys = set(app["output_mapping"])
    assert set(probe.expect) <= expected_keys  # PASS reads keys of the output_mapping


# ============================================================================ 7.1, 9.6
@pytest.mark.gebit
@pytest.mark.parametrize("part,location", PARTS)
def test_pos_event_categories_hit_exactly_the_r1_subscriptions(
        part: str, location: str, gebit_pool: Any) -> None:
    """The POS derives the topic category from the GEBIT descriptor (4.2); the five R1
    kinds must hit exactly one R1/P1 subscription, the other nine none."""
    from gposdemo.pos.events import EventFactory

    factory = EventFactory(gebit_pool)
    r1 = rendered_rules(part, LAB_ENV)[render_mesh.RULES[part][0]]
    for event in R1_EVENTS + NON_R1_EVENTS:
        topic = topics.gebit_event(factory.category(event), event,
                                   *topics.parse_location(location), TX)
        hits = [t for t in subscriptions(r1) if topic_matches(t, topic)]
        assert len(hits) == (1 if event in R1_EVENTS else 0), topic


@pytest.mark.parametrize("part,location", PARTS)
def test_entrypoint_subscriptions_match_the_producer_topics(part: str, location: str) -> None:
    country, company, store, till = topics.parse_location(location)
    rules = rendered_rules(part, LAB_ENV)
    r1, r3, r4 = (rules[n] for n in render_mesh.RULES[part])
    prefix = f"/{country}/{company}/{store}/{till}/>"
    events = sorted(t.split("/")[5] for t in subscriptions(r1))
    assert events == sorted(R1_EVENTS)
    assert all(t.endswith(prefix) for t in subscriptions(r1))
    review = topics.review_request(store, till, "GR-270216-0007")
    approval = topics.approval_request(store, till, "GP-270216-0003")
    assert [topic_matches(t, review) for t in subscriptions(r3)] == [True]
    assert [topic_matches(t, approval) for t in subscriptions(r4)] == [True]
    others = [topics.review_state(s, store, till, "GR-270216-0007")
              for s in topics.REVIEW_STATES]
    others += [topics.proposal(s, store, till, "GP-270216-0003")
               for s in topics.PROPOSAL_STATES + topics.PROPOSAL_SIGNALS]
    others += [topics.review_request("199", "99", "GR-1"), topics.approval_request(
        "199", "99", "GP-1")]  # test till 99: never SAM
    others += [topics.review_request("199" if store == "101" else "101",
                                     "98" if till == "01" else "01", "GR-1")]
    for rule in rules.values():
        for topic in others:
            assert not any(topic_matches(t, topic) for t in subscriptions(rule)), topic


@pytest.mark.parametrize("part", ["booth", "probe"])
def test_sam_outputs_land_on_the_bff_rule_topics(part: str) -> None:
    workflows = mesh_docs("workflows")
    for name, rule in rendered_rules(part, LAB_ENV).items():
        short = rule_short(name)
        assert rule["successOutput"]["topic"] == topics.sam_done(short)
        assert rule["errorOutput"]["topic"] == topics.sam_error(short)
        assert rule["successOutput"]["responseType"] == "structured"
        assert rule["targetWorkflowName"] == feed.WORKFLOWS[short[1:]]
        assert rule["targetWorkflowName"] in workflows
        assert feed.classify(topics.sam_done(short)) == "sam_run"
    assert set(feed.EXPIRY_RULES) == {"r4", "p4"}


def test_r1_own_queue_takes_the_r1_subscriptions_of_the_sam_mode() -> None:
    own = rendered_rules("booth", LAB_ENV, mode="own")["r1_booth_till"]
    sam = rendered_rules("booth", LAB_ENV, mode="sam")["r1_booth_till"]
    assert own["existingQueueName"] == "gpos-booth-r1" and "subscriptions" not in own
    assert render_mesh.r1_topics(LAB_ENV) == subscriptions(sam)


def test_every_producer_topic_reaches_the_bff_as_its_sse_event() -> None:
    samples = {
        topics.gebit_event("basket", "PositionAdded", "DE", "999", "101", "01", "t"):
            "pos_event",
        topics.wws_price("PriceChangeApplied", "DE", "999", "101", "100001"): "price_change",
        topics.insight("101", "01", "t"): "insight",
        topics.review_state("prepared", "101", "01", "GR-1"): "review",
        topics.proposal("ready", "101", "01", "GP-1"): "proposal",
        topics.proposal("duplicate_request", "101", "01", "GP-1"): "proposal",
        topics.telemetry_tool("wws", "get_sales_performance"): "tool_call",
        topics.sam_done("r3"): "sam_run", topics.sam_error("p4"): "sam_run",
        topics.review_request("101", "01", "GR-1"): None,
        topics.approval_request("101", "01", "GP-1"): None,
    }
    for topic, kind in samples.items():
        assert any(topic_matches(f, topic) for f in topics.UI_SUBSCRIPTIONS), topic
        assert feed.classify(topic) == kind, topic


# ============================================================================ 3.1, 12.4
def k8s_docs() -> list[dict[str, Any]]:
    return [d for p in sorted((ROOT / "k8s").glob("*.yaml"))
            for d in yaml.safe_load_all(p.read_text(encoding="utf-8")) if d]


def test_every_setting_comes_from_configmap_secret_or_deployment() -> None:
    docs = k8s_docs()
    configmap = next(d for d in docs if d["kind"] == "ConfigMap")["data"]
    secrets = dict.fromkeys(("SOLACE_HOST", "SOLACE_VPN", "SOLACE_USERNAME",
                             "SOLACE_PASSWORD"), "secret")  # gpos-broker (12.4)
    ports = ("GRPC_PORT", "MCP_PORT", "HTTP_PORT")  # unset ones default to 2.2
    deployments = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Deployment"}
    assert set(deployments) == {f"gpos-{s}" for s in DEFAULT_PORTS}
    for name, dep in deployments.items():
        service = name.removeprefix("gpos-")
        container = dep["spec"]["template"]["spec"]["containers"][0]
        assert container["command"] == ["python", "-m", "gposdemo." + {
            "gate": "engine.gate"}.get(service, service)]
        refs = {r.get("configMapRef", r.get("secretRef", {})).get("name")
                for r in container.get("envFrom", [])}
        assert refs == {"gpos-config", "gpos-broker"}, name
        own = {e["name"]: e.get("value") or "secret" for e in container.get("env", [])}
        env = RecordingEnv()
        env.update({**configmap, **secrets, **own})
        pod = load_settings(service, env)
        missing = env.asked - set(env) - set(ports) - TEST_ONLY_SETTINGS
        assert missing == ({"GPOS_DSN"} if service == "ui" else set()), name  # ui: no DB
        assert (pod.grpc_port, pod.mcp_port, pod.http_port) == DEFAULT_PORTS[service], name
        exposed = {p["containerPort"] for p in container["ports"]}
        assert exposed == {p for p in DEFAULT_PORTS[service] if p}, name
    env = RecordingEnv()
    load_settings("engine", env)
    assert set(configmap) <= env.asked  # no dead ConfigMap key
    cluster = load_settings("ui", configmap)
    for target, service in ((cluster.pos_grpc, "pos"), (cluster.wws_grpc, "wws"),
                            (cluster.loyalty_grpc, "loyalty")):
        assert target == f"gpos-{service}:{DEFAULT_PORTS[service][0]}"
    assert cluster.engine_url == f"http://gpos-engine:{DEFAULT_PORTS['engine'][1]}"
    assert cluster.pos_admin_url == f"http://gpos-pos:{DEFAULT_PORTS['pos'][1]}"
    # check_manifests.py reads tools/list through ui.ctl: the same servers as the connectors
    for host, module in HOST_MODULE.items():
        service = MODULE_SERVICE[module]
        assert ctl.mcp_base_url(cluster, service) == f"http://{host}:{DEFAULT_PORTS[service][1]}"


def test_k8s_services_expose_the_ports_of_2_2() -> None:
    for doc in k8s_docs():
        if doc["kind"] != "Service":
            continue
        service = doc["metadata"]["name"].removeprefix("gpos-")
        ports = {p["port"] for p in doc["spec"]["ports"]}
        expected = {p for p in DEFAULT_PORTS[service] if p}
        assert ports == ({80} if service == "ui" else expected), service


# ============================================================================ flow part
# A tiny SAM workflow interpreter: enough of the 2.542.1 semantics of 9.1 to execute the
# three workflows against the real services.
ToolCall = Callable[[str, str, dict[str, Any]], dict[str, Any]]
Agent = Callable[[dict[str, Any]], dict[str, Any]]


class AgentFailed(Exception):
    """An agent ended its task with an error: SAM fails the node and the run (fail_fast),
    runs ``on_exit.on_failure`` with ``workflow.error.message`` and sends
    ``errorOutput`` instead of the ``output_mapping``."""


@dataclass
class WorkflowRun:
    """One workflow run: ``inputs`` = ``workflow.input``, tool and agent nodes are
    delegated; an unresolved reference inside a longer string stays as text (finding 3),
    a whole value referencing a skipped node is null and a missing ``workflow.input``
    key drops the input key (SAM 2.542 data flow), skipped predecessors do not skip
    successors (9.1), a switch skips only its unchosen direct targets."""

    app: dict[str, Any]
    inputs: dict[str, Any]
    call_tool: ToolCall
    agents: dict[str, Agent]
    run_id: str = "run-it-0001"
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    skipped: set[str] = field(default_factory=set)
    calls: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    notifications: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)  # resolved output_mapping
    error: str = ""         # workflow.error.message of a failed run
    failed: bool = False

    def lookup(self, path: str) -> Any:
        head, *rest = path.split(".")
        if head == "workflow":
            if rest == ["run_id"]:
                return self.run_id
            if rest == ["error", "message"]:
                return self.error if self.failed else None
            return self.inputs.get(rest[1]) if rest[0] == "input" else None
        if head not in self.outputs:
            return None
        node = self.node(head)
        out = self.outputs[head]
        name = rest[2] if node["type"] == "tool" and "connector" in node else rest[1]
        assert name in out, f"{path}: field missing in the result of {head}"
        return out[name]

    def node(self, node_id: str) -> dict[str, Any]:
        return next(n for n in self.app["nodes"] if n["id"] == node_id)

    def resolve(self, text: str) -> str:
        def one(match: re.Match[str]) -> str:
            value = self.lookup(match.group(1))
            return match.group(0) if value is None else str(value)
        return REF.sub(one, text)

    def holds(self, condition: str) -> bool:
        match = CONDITION.match(self.resolve(condition))
        assert match, condition
        return match["left"] == match["right"]

    def args(self, node: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in node.get("input", {}).items():
            whole = REF.fullmatch(value.strip()) if isinstance(value, str) else None
            if whole and self.lookup(whole.group(1)) is None:
                head, *rest = whole.group(1).split(".")
                if head == "workflow" and rest[:1] == ["input"]:
                    continue                    # missing input key: the key is dropped
                out[key] = None                 # skipped node: delivered as null
            else:
                out[key] = self.resolve(value) if isinstance(value, str) else value
        return out

    def execute(self) -> WorkflowRun:
        handler = self.app.get("on_exit", {}).get("on_failure")
        pending = [n for n in self.app["nodes"] if n["id"] != handler]
        not_chosen: set[str] = set()
        while pending:
            ready = next(n for n in pending if set(n.get("depends_on", []))
                         <= set(self.outputs) | self.skipped)
            pending.remove(ready)
            if ready["id"] in not_chosen or ("when" in ready and not self.holds(ready["when"])):
                self.skipped.add(ready["id"])
            elif ready["type"] == "switch":
                chosen = next((c["node"] for c in ready["cases"] if self.holds(c["condition"])),
                              ready["default"])
                not_chosen |= {c["node"] for c in ready["cases"]} | {ready["default"]}
                not_chosen.discard(chosen)
                self.outputs[ready["id"]] = {"selected": chosen}
            else:
                try:
                    self.outputs[ready["id"]] = self.run_node(ready)
                except AgentFailed as exc:
                    return self.fail(str(exc))
        self.result = self.output_mapping()
        return self

    def fail(self, message: str) -> WorkflowRun:
        """fail_fast: the run stops, ``on_exit.on_failure`` runs, no output_mapping."""
        self.error, self.failed, self.result = message, True, {}
        handler = self.app.get("on_exit", {}).get("on_failure")
        if handler:
            self.outputs[handler] = self.run_node(self.node(handler))
        return self

    def run_node(self, node: dict[str, Any]) -> dict[str, Any]:
        args = self.args(node)
        if node["type"] == "agent":
            out = self.agents[node["agent_name"]](args)
            schema = node["output_schema_override"]
            assert set(schema["required"]) <= set(out), node["id"]
            for key, prop in schema["properties"].items():
                assert "enum" not in prop or out[key] in prop["enum"], (key, out[key])
            return out
        for value in (v for v in args.values() if isinstance(v, str)):
            for path in REF.findall(value):    # unresolved stays text: skipped nodes only
                assert path.split(".")[0] in self.skipped, (node["id"], path)
        if node.get("tool_name") == "notify_user":
            self.notifications.append({"node": node["id"], **args})
            return {"status": "sent"}
        self.calls.append((node["id"], node["tool"], args))
        return self.call_tool(node["connector"], node["tool"], args)

    def output_mapping(self) -> dict[str, Any]:
        result = {}
        for key, value in self.app["output_mapping"].items():
            options = value["coalesce"] if isinstance(value, dict) else [value]
            resolved = [self.resolve(option) for option in options]
            result[key] = next((r for r in resolved if "{{" not in r), resolved[-1])
        return result

    def ran(self, tool: str) -> list[dict[str, Any]]:
        return [args for _node, name, args in self.calls if name == tool]


@dataclass
class Mcp:
    """JSON-RPC ``tools/call`` over HTTP, stateless, as SAM's str calls the servers."""

    clients: dict[str, httpx.Client]

    def call(self, service: str, tool: str, **arguments: str) -> dict[str, Any]:
        reply = self.clients[service].post(mcputil.MCP_PATH, headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"}, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments}})
        assert reply.status_code == 200, reply.text
        result = reply.json()["result"]
        text = "".join(c.get("text", "") for c in result["content"])
        assert not result.get("isError"), f"{tool}: {text}"
        return result

    def workflow_tool(self, service: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        result = self.call(service, tool, **args)
        text = result["content"][0]["text"]
        assert len(result["content"]) == 1 and "\n" not in text and text.startswith(tool)
        assert len(compact(result).encode()) <= 1800 and len(text.encode()) <= 1500  # 8.1
        return result["structuredContent"]

    def agent_tool(self, service: str, tool: str, **args: str) -> dict[str, Any]:
        result = self.call(service, tool, **args)
        assert not result.get("structuredContent")
        text = result["content"][0]["text"]
        assert len(text.encode()) <= 1200
        return json.loads(text)


# the F2 connector reaches the same gate service, run here with GATE_GUARD=f2 (9.9)
CONNECTOR_SERVICE = {"gpos-booth-tools": "engine", "gpos-price-gate": "gate",
                     "gpos-price-apply": "gate_f2"}
SIGNAL_TOOL = {"slow_seller": ("wws", "get_sales_performance"),
               "season_end": ("wws", "get_season_info"),
               "customer_behaviour": ("wws", "get_article")}
REASON_ORDER = ("season_end", "slow_seller", "customer_behaviour")


def evidence_holds(signal: str, result: dict[str, Any],
                   behaviour: dict[str, Any] | None) -> str:
    """The ``holds`` rules of the evidence agent prompt (9.4), on the real tool JSON."""
    if signal == "slow_seller":
        trend = result.get("trend")
        return "unknown" if trend is None else "yes" if trend in ("falling", "stable") else "no"
    if signal == "season_end":
        status, share = result.get("status"), result.get("leftover_share")
        if status == "ended":
            return "yes"
        if status == "running":
            return "unknown" if share is None else "yes" if share >= 0.4 else "no"
        return "no" if status else "unknown"
    if behaviour is None:
        return "unknown"
    factor, drop = behaviour.get("overdue_factor"), behaviour.get("cardholder_drop_pct")
    if factor is None or drop is None:
        return "unknown"
    return "yes" if factor >= 1.5 and drop >= 30 else "no"


def evidence_numbers(signal: str, result: dict[str, Any],
                     behaviour: dict[str, Any] | None) -> str:
    """``numbers`` as the prompt prescribes (9.4, UC1-31): key=value copied from the
    results in the order of its list (get_purchase_behaviour before get_article, then
    ``last_change``), "; ", at most 160 characters."""
    if signal == "slow_seller":
        weekly = result.get("weekly_units") or []
        pairs = [(k, result.get(k)) for k in ("trend", "sold_7d", "plan_7d", "weeks_of_supply")]
        pairs += [("weekly_first", weekly[0] if weekly else None),
                  ("weekly_last", weekly[-1] if weekly else None)]
    elif signal == "season_end":
        pairs = [(k, result.get(k)) for k in ("status", "days_to_end", "leftover_share",
                                               "stock")]
    else:
        pairs = [(k, (behaviour or {}).get(k)) for k in (
            "overdue_factor", "cardholder_drop_pct", "days_since_last", "median_interval_days")]
        pairs.append(("margin_pct", result.get("margin_pct")))
        change = result.get("last_price_change")
        if change:
            pairs.append(("last_change",
                          f"{change['date']} {change['from']}->{change['to']}"))
    return "; ".join(f"{k}={v}" for k, v in pairs if v is not None)[:160]


def pricing_agent(mcp: Mcp) -> Agent:
    """``gpos-pricing-agent`` (fast) as its prompt prescribes: tools in one first round,
    then the evidence of the first two candidates in the flat slots c1/c2; it decides
    nothing."""

    def run(inputs: dict[str, Any]) -> dict[str, Any]:
        review = json.loads(inputs["review"])
        ref = review["review_id"]
        tx = mcp.agent_tool("pos", "get_transaction", tx_id=review["tx_id"], ref=ref)
        assert tx["tx_id"] == review["tx_id"]
        out = {"tx_status": "closed" if tx["status"] == "CLOSED" else "not_closed"}
        card = review["card"]
        slots = []
        for cand in review["candidates"][:2]:
            signal = cand["signals"][0]
            service, tool = SIGNAL_TOOL[signal]
            result = mcp.agent_tool(service, tool, article_number=cand["a"], ref=ref)
            tools, behaviour = [tool], None
            if signal == "customer_behaviour" and card and card["consent_profiling"]:
                behaviour = mcp.agent_tool("loyalty", "get_purchase_behaviour",
                                           membership_id=card["membership_id"],
                                           article_number=cand["a"], ref=ref)
                tools.append("get_purchase_behaviour")
            slots.append((cand["a"], signal, evidence_holds(signal, result, behaviour),
                          evidence_numbers(signal, result, behaviour), ", ".join(tools)))
        slots += [("none", "none", "unknown", "none", "none")] * (2 - len(slots))
        for n, (article, reason, holds, numbers, tools_text) in enumerate(slots, 1):
            out.update({f"c{n}_article": article, f"c{n}_reason": reason,
                        f"c{n}_holds": holds, f"c{n}_numbers": numbers,
                        f"c{n}_tools": tools_text})
        return out

    return run


def planner() -> Agent:
    """``gpos-price-planner`` (planning, no tools): the decision rules of its prompt on
    review and evidence; German texts from the engine facts, never a computed number."""

    def run(inputs: dict[str, Any]) -> dict[str, Any]:
        review, evidence = json.loads(inputs["review"]), json.loads(inputs["evidence"])
        candidates = {c["a"]: (i, c) for i, c in enumerate(review["candidates"])}
        holding = [it for it in evidence["items"] if it["a"] in candidates
                   and it["holds"] == "yes"]
        holding.sort(key=lambda it: (REASON_ORDER.index(it["reason"]),
                                     candidates[it["a"]][0]))
        if not holding:
            checked = evidence["items"][0]["name"] if evidence["items"] else ""
            return {"decision": "no_action", "article_number": "", "reason": "none",
                    "step_pct": "0",
                    "headline": f"{checked}: keine Preisanpassung" if checked
                    else "Keine Preisanpassung",
                    "rationale": "Die Belege sprechen gegen eine Senkung.", "facts_line": ""}
        item = holding[0]
        cand = candidates[item["a"]][1]
        return {"decision": "propose", "article_number": item["a"], "reason": item["reason"],
                "step_pct": str(cand["suggested_step_pct"]),
                "headline": f"{cand['name']}: Preis senken",
                "rationale": f"Die Belege bestätigen den Anlass: {cand['facts']}"[:240],
                "facts_line": cand["facts"][:120]}

    return run


DENY_ERROR = "Agent reported error: Price approval was denied by store manager"  # 12.11.
TIMEOUT_ERROR = "Tool approval timed out after 2 minutes"
# the gated tool's result on a denial / an HIL timeout (SAM webui DB, task_events 12.11.)
SAM_DENIED = "Tool call denied by user."
SAM_TIMEOUT = "Tool approval timed out after 2 minutes."
TOOL_ERROR = "MCP server gpos-price-gate unreachable"


def approver(mcp: Mcp, answer: str, delay_s: float) -> Agent:
    """``gpos-price-approver``: the store manager answers after ``delay_s``; then ONE
    ``apply_price`` call with exactly its input and its result's status, action_id and
    message (``approve``), a final answer with the copied SAM message (``deny``,
    ``deny_late``, ``timeout``, ``error``; ``*_status_error`` = the 12.11. F1 answer with
    SAM's result status ``error``, ``deny_no_message`` = an answer without message) or
    the task ending as an error with the observed texts (``deny_error``,
    ``timeout_error``)."""
    clean = {"deny": ("denied", SAM_DENIED), "deny_late": ("denied", SAM_DENIED),
             "deny_status_error": ("error", SAM_DENIED), "deny_no_message": ("denied", ""),
             "error": ("error", TOOL_ERROR), "timeout": ("timeout", SAM_TIMEOUT),
             "timeout_status_error": ("error", SAM_TIMEOUT)}
    failure = {"deny_error": DENY_ERROR, "timeout_error": TIMEOUT_ERROR}

    def run(inputs: dict[str, Any]) -> dict[str, Any]:
        time.sleep(delay_s)
        if answer in clean:
            status, message = clean[answer]
            return {"status": status, "action_id": "", "message": message}
        if answer in failure:
            raise AgentFailed(failure[answer])
        result = mcp.workflow_tool("gate", "apply_price", inputs)
        return {"status": result["status"], "action_id": result["action_id"],
                "message": result["message"]}

    return run


def approver_f2(delay_s: float, status: str = "applied", with_time: bool = True,
                error: str = "", message: str | None = None) -> Agent:
    """``gpos-price-approver-f2``: the gated builtin ``get_current_time`` returns after the
    store manager's answer; ``status`` plus the tool's time (the G0-02 format, ISO 8601
    with offset) or ``""`` and the result's message (default: SAM's denial text with
    status ``denied``, else ``""``); ``error`` ends the task as an error."""

    def run(_inputs: dict[str, Any]) -> dict[str, Any]:
        time.sleep(delay_s)
        if error:
            raise AgentFailed(error)
        text = message if message is not None else SAM_DENIED if status == "denied" else ""
        return {"status": status, "time": datetime.now(UTC).isoformat() if with_time else "",
                "message": text}

    return run


@dataclass
class Lab:
    """The five services of UC1 in this process (till 99, store 199)."""

    bus: MemoryBus
    mcp: Mcp
    facade: Any
    catalog: dict[str, dict[str, Any]]
    scenarios: dict[str, list[dict[str, str]]]
    settings: Settings
    wws: Any  # gposdemo.ui.clients.WwsClient
    loyalty: Any  # gposdemo.ui.clients.LoyaltyClient
    ui_env: dict[str, str]  # POS_GRPC, WWS_GRPC, LOYALTY_GRPC, ENGINE_URL, POS_ADMIN_URL
    admin: Any  # superuser Db of the scratch DB, for assertions only

    def reset_store(self) -> None:
        """Reset chain of 11.7 (steps 1-4) for store 199 over the real seams: engine
        ``POST /api/reset``, WWS ``ResetDemoState``, POS ``POST /admin/reset``, loyalty
        ``ResetDemoState`` (as smoke.py and the BFF call them)."""
        engine = self.mcp.clients["engine"].post("/api/reset",
                                                 json={"scope": "booth", "store_id": "199"})
        assert engine.status_code == 200, engine.text
        self.wws.reset("199", False, "reset-booth")
        till = self.mcp.clients["pos"].post("/admin/reset", json={})
        assert till.status_code == 200 and till.json()["status"] == "ok", till.text
        self.loyalty.reset(False, "reset-booth")

    def pos(self, method: str, body: dict[str, Any]) -> dict[str, Any]:
        result = self.facade.call(method, body, "99")
        assert result.ok, result.body
        return result.body["result"]

    def play(self, scenario: str) -> str:
        """The scenario buttons of /kasse (1.3) on till 99; returns the tx id."""
        tx_id, total = "", Decimal("0")
        for step in self.scenarios[scenario]:
            if step["op"] == "new":
                tx_id = self.pos("CreatePurchaseTransaction", {})["purchaseTransactionId"]
            elif step["op"] == "card":
                self.pos("AssignLoyaltyMembership", {
                    "purchaseTransactionId": tx_id,
                    "membershipIdentificationValue": step["value"]})
            elif step["op"] == "scan":
                article = self.catalog[step["value"]]
                self.pos("AddArticle", {"purchaseTransactionId": tx_id,
                                        "articleId": article["article_id"], "itemCount": 1,
                                        "capturingInformation": {
                                            "inputMethod": "SCANNER", "inputType": "EAN13",
                                            "inputValue": article["gtin"]}})
                total += Decimal(article["price"].replace(",", "."))
            else:  # cash: the next full 5-euro amount (1.3)
                cents = max(5, math.ceil(total / 5) * 5) * 100
                self.pos("StartPaymentProcess", {"purchaseTransactionId": tx_id})
                self.pos("CreateCashPayment", {
                    "purchaseTransactionId": tx_id, "clientId": "kasse-99",
                    "clientTransactionId": f"{tx_id}-pay",
                    "amount": {"currency": "EUR", "amount": {"scale": 2,
                                                             "intVal": str(cents)}}})
        return tx_id

    def events(self, tx_id: str, closing: str) -> list[Published]:
        """Every GEBIT event of ``tx_id`` once the relay published ``closing``."""
        self.bus.wait_for(f"gebit/rp/purchase/v2/*/{closing}/*/*/*/*/{tx_id}", 1, 10)
        return [m for m in self.bus.messages("gebit/rp/purchase/v2/>")
                if m.topic.endswith(f"/{tx_id}")]

    def one(self, topic_filter: str, timeout: float = 10) -> Published:
        return self.bus.wait_for(topic_filter, 1, timeout)[-1]

    def run(self, workflow: str, inputs: dict[str, Any], agents: dict[str, Agent],
            run_id: str) -> WorkflowRun:
        def call_tool(connector: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
            return self.mcp.workflow_tool(CONNECTOR_SERVICE[connector], tool, args)

        return WorkflowRun(app_config(mesh_docs("workflows")[workflow]), inputs, call_tool,
                           agents, run_id).execute()


GATE_DELAY_S = 1.0
HIL_TIMEOUT_S = 4.0     # the 2-minute HIL window of 11.5, shortened for the lab engine


def serve_http(stack: ExitStack, mcp: Any) -> str:
    """Serve an MCP server (tools on ``/mcp`` plus its custom routes) like
    ``mcputil.run`` does, on a free local port; stopped by ``stack``."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(mcputil.http_app(mcp), host="127.0.0.1",
                                           port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, name=f"http-{port}", daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "HTTP server did not start"
        time.sleep(0.02)

    def stop() -> None:
        server.should_exit = True
        thread.join(5)

    stack.callback(stop)
    return f"http://127.0.0.1:{port}"


@pytest.fixture(scope="module")
def lab(make_settings: Callable[..., Settings],
        scratch_db_factory: Callable[..., Any]) -> Iterator[Lab]:
    """wws, loyalty, pos, engine and gate on an own seeded scratch DB (13.2 ``gpos_it``)."""
    from gposdemo import loyalty, pos, wws
    from gposdemo.common.descriptors import load_pool
    from gposdemo.engine import create as create_engine
    from gposdemo.engine.gate import create as create_gate
    from gposdemo.ui.bff import catalog_article
    from gposdemo.ui.clients import LoyaltyClient, WwsClient
    from gposdemo.ui.facade import PosFacade

    db_files = sorted((ROOT / "postgres" / "sql").glob("*.sql"))
    it_db = scratch_db_factory(db_files, seed=True)
    bus = MemoryBus()
    with ExitStack() as stack:
        stack.callback(bus.close)

        def started(create: Callable[[Settings, MemoryBus, Any], Any], service: str,
                    **env: str) -> Any:
            db = it_db.db(service, max_size=4)
            stack.callback(db.close)
            app = create(make_settings(service, GPOS_DSN=it_db.dsn(service), GRPC_PORT="0",
                                       **env), bus, db)
            app.start()
            stack.callback(app.stop)
            return app

        wws_app = started(wws.create, "wws")
        loyalty_app = started(loyalty.create, "loyalty")
        backends = {"WWS_GRPC": f"127.0.0.1:{wws_app.grpc_port}",
                    "LOYALTY_GRPC": f"127.0.0.1:{loyalty_app.grpc_port}",
                    "GATE_MIN_DELAY_S": str(GATE_DELAY_S)}
        pos_app = started(pos.create, "pos", **backends)
        engine_app = started(create_engine, "engine", **backends,
                             HIL_TIMEOUT_S=str(HIL_TIMEOUT_S))
        gate_app = started(create_gate, "gate", **backends)
        gate_f2 = started(create_gate, "gate", **backends, GATE_GUARD="f2")
        ui_settings = make_settings("ui", POS_GRPC=f"127.0.0.1:{pos_app.grpc_port}",
                                    **backends)
        facade = PosFacade.from_settings(ui_settings)
        stack.callback(facade.close)
        clients = {}
        for name, app in (("engine", engine_app), ("gate", gate_app), ("gate_f2", gate_f2),
                          ("wws", wws_app), ("loyalty", loyalty_app), ("pos", pos_app)):
            clients[name] = stack.enter_context(httpx.Client(
                base_url=serve_http(stack, app.mcp), timeout=30))
        ui_env = {"POS_GRPC": f"127.0.0.1:{pos_app.grpc_port}",
                  "WWS_GRPC": backends["WWS_GRPC"], "LOYALTY_GRPC": backends["LOYALTY_GRPC"],
                  "ENGINE_URL": str(clients["engine"].base_url).rstrip("/"),
                  "POS_ADMIN_URL": str(clients["pos"].base_url).rstrip("/")}
        showcase = load_pool([ui_settings.showcase_descriptor_set])
        wws_client = WwsClient(showcase, backends["WWS_GRPC"])
        stack.callback(wws_client.close)
        loyalty_client = LoyaltyClient(showcase, backends["LOYALTY_GRPC"])
        stack.callback(loyalty_client.close)
        catalog = {a["gtin"]: a for a in (catalog_article(raw, ui_settings.tz)
                                          for raw in wws_client.list_articles("199"))}
        ref = refdata.load(ui_settings.data_dir)
        admin = it_db.admin_db()
        stack.callback(admin.close)
        yield Lab(bus, Mcp(clients), facade, catalog,
                  {s["id"]: s["steps"] for s in ref.scenarios}, ui_settings, wws_client,
                  loyalty_client, ui_env, admin)


def r1_inputs(lab: Lab, tx_id: str, closing: str) -> list[tuple[str, str]]:
    """``(event, workflow.input.text)`` of every GEBIT event of ``tx_id`` that the R1
    subscriptions (rendered for till 99) select, as SAM re-serialises it (7.3)."""
    r1 = rendered_rules("booth", {**LAB_ENV, "GPOS_BOOTH_LOCATION": TEST_LOCATION})
    subs = subscriptions(r1["r1_booth_till"])
    return [(m.topic.split("/")[5], canonical(m.json())) for m in lab.events(tx_id, closing)
            if any(topic_matches(s, m.topic) for s in subs)]


def sam_input(lab: Lab, topic_filter: str, rule: str, workflow: str) -> dict[str, Any]:
    """The engine's SAM input on the bus, checked against the rule's subscription
    (rendered for till 99) and the target workflow's ``input_schema``."""
    message = lab.one(topic_filter)
    rules = rendered_rules("booth", {**LAB_ENV, "GPOS_BOOTH_LOCATION": TEST_LOCATION})
    assert any(topic_matches(t, message.topic) for t in subscriptions(rules[rule]))
    assert rules[rule]["targetWorkflowName"] == workflow
    payload = message.json()
    check_input_schema(app_config(mesh_docs("workflows")[workflow])["input_schema"], payload)
    return payload


def pos_event_runs(lab: Lab, tx_id: str,
                   closing: str = "PurchaseTransactionClosed") -> list[WorkflowRun]:
    """One ``gpos-pos-event`` run per R1 event of ``tx_id``, in publication order."""
    return [lab.run("gpos-pos-event", {"text": text}, {}, f"run-r1-{i}")
            for i, (_event, text) in enumerate(r1_inputs(lab, tx_id, closing))]


def review_agents(lab: Lab) -> dict[str, Agent]:
    """The two agents of R3: evidence (fast, API tools) and planner (planning, none)."""
    return {"gpos-pricing-agent": pricing_agent(lab.mcp), "gpos-price-planner": planner()}


def basket_review(lab: Lab, scenario: str) -> WorkflowRun:
    """Scenario on till 99 -> R1 runs -> the engine's review request -> R3 run with the
    evidence agent and the planner (as the booth chain does it, 1.4)."""
    runs = pos_event_runs(lab, lab.play(scenario))
    review_id = runs[-1].result["review_id"]
    payload = sam_input(lab, topics.review_request("199", "99", review_id),
                        "r3_basket_review", "gpos-basket-review")
    return lab.run("gpos-basket-review", payload, review_agents(lab), f"run-r3-{scenario}")


def approval_run(lab: Lab, proposal_id: str, answer: str,
                 delay_s: float | None = None) -> WorkflowRun:
    """The engine's approval request -> R4 run with the approver (modes of
    :func:`approver`); the answer comes ``GATE_DELAY_S + 1`` s after the check unless
    ``delay_s`` says otherwise."""
    payload = sam_input(lab, topics.approval_request("199", "99", proposal_id),
                        "r4_price_approval", "gpos-price-approval")
    delay = GATE_DELAY_S + 1 if delay_s is None else delay_s
    return lab.run("gpos-price-approval", payload,
                   {"gpos-price-approver": approver(lab.mcp, answer, delay)},
                   f"run-r4-{proposal_id}")


def proposal_record(lab: Lab, proposal_id: str) -> dict[str, Any]:
    return lab.mcp.clients["engine"].get(f"/api/proposals/{proposal_id}").json()


FLOW = (pytest.mark.integration, pytest.mark.db, pytest.mark.gebit)


def flow(fn: Callable[..., None]) -> Callable[..., None]:
    """Markers of the flow part (13.2: ``integration``, ``db``, ``gebit``)."""
    for mark in FLOW:
        fn = mark(fn)
    return fn


@flow
def test_probes_pass_against_the_real_engine(lab: Lab) -> None:
    """9.7/9.8: the ``ui.ctl`` probes PASS on what the real engine answers."""
    for name in ("p1", "p3", "p4", "notify"):
        probe = ctl.build_probe(name, lab.settings, "11111111-1111-4111-8111-111111111111")
        workflow = feed.WORKFLOWS[probe.rule[1:]]
        inputs = {"text": canonical(probe.payload)} if probe.rule == "p1" else probe.payload
        run = lab.run(workflow, inputs, {}, f"run-{name}")
        assert probe.matches(run.result), (name, run.result)
        assert not {"gather", "recommend", "approve"} & set(run.outputs)  # 0 tokens
        if name == "p3":
            assert len(run.ran("close_review")) == 1  # hard rule 6 (9.8 step 6)
        if name == "notify":
            assert [(n["node"], n["title"]) for n in run.notifications] == [
                ("ping", "gpos Preflight: Benachrichtigung ok")]


@flow
def test_s4_closes_the_review_once_without_the_agent(lab: Lab) -> None:
    tx_id = lab.play("S4")
    runs = pos_event_runs(lab, tx_id)
    assert [r.result["verdict"] for r in runs] == ["scan"] * 3 + ["close"]
    review_id = runs[-1].result["review_id"]
    payload = sam_input(lab, topics.review_request("199", "99", review_id),
                        "r3_basket_review", "gpos-basket-review")
    review = lab.run("gpos-basket-review", payload, {}, "run-r3-s4")
    assert review.result == {"review_id": review_id, "decision": "no_candidates",
                             "proposal_id": "none"}
    assert [a["outcome"] for a in review.ran("close_review")] == ["no_candidates"]
    assert {"gather", "note", "recommend", "stage", "conclude"} <= review.skipped


@flow
def test_s1_on_till_99_runs_all_three_workflows_to_the_new_price(lab: Lab) -> None:
    start = len(lab.bus.published)
    tx_id = lab.play("S1")
    events = lab.events(tx_id, "PurchaseTransactionClosed")
    assert len(events) == 13  # 1.4: 13 POS events of S1 (cash with change)
    for message in events:
        assert any(topic_matches(f, message.topic) for f in topics.UI_SUBSCRIPTIONS)
        assert feed.pos_event(message.topic, message.json(), ("199", "99"))["tx_id"] == tx_id

    # R1: four runs (3 scans, Closed), per-scan insight, the close raises the review
    runs = pos_event_runs(lab, tx_id)
    assert [(r.result["verdict"], r.result["insight"]) for r in runs] == [
        ("scan", "slow_seller"), ("scan", "on_plan"), ("scan", "on_plan"), ("close", "close")]
    assert [len(r.calls) for r in runs] == [2] * 4  # assess + note_event | raise
    insights = {m.json()["article_number"]: m.json()
                for m in lab.bus.messages(f"gpos/v1/insight/scan/199/99/{tx_id}")}
    duck = insights["100001"]
    assert (duck["code"], duck["price"], duck["price_source"]) == ("slow_seller", "9,99",
                                                                   "REGULAR")
    assert duck["text"].startswith("Ladenhüter: 9 von 35 geplanten Stück verkauft (7 Tage)")
    review_id = runs[-1].result["review_id"]

    # R3: the agent reads POS and WWS, the engine stages 7,99
    payload = sam_input(lab, topics.review_request("199", "99", review_id),
                        "r3_basket_review", "gpos-basket-review")
    assert payload["tx_id"] == tx_id
    review = lab.run("gpos-basket-review", payload, review_agents(lab), "run-r3-s1")
    assert review.result["decision"] == "propose"
    proposal_id = review.result["proposal_id"]
    gather, noted = review.outputs["gather"], review.outputs["note"]
    assert (gather["tx_status"], gather["c1_article"], gather["c1_holds"],
            gather["c2_article"]) == ("closed", "100001", "yes", "none")
    assert gather["c1_numbers"] == ("trend=falling; sold_7d=9; plan_7d=35; "
                                    "weeks_of_supply=6.5; weekly_first=34; weekly_last=9")
    assert (noted["status"], noted["checked"], noted["holding"]) == ("noted", 1, 1)
    assert [a["model"] for a in review.ran("note_evidence")] == ["fast"]
    assert review.outputs["recommend"]["article_number"] == "100001"
    assert review.ran("stage_proposal")[0]["model"] == "planning"
    staged = review.outputs["stage"]
    assert (staged["status"], staged["article_number"], staged["old_price"],
            staged["new_price"], staged["pct_label"], staged["proposal_id"]) == (
        "ready", "100001", "9,99", "7,99", "-20 %", proposal_id)
    assert staged["text_source"] == "ai"     # the planner's KI-Empfehlung survived 11.3
    assert {"skip", "conclude"} <= review.skipped and not review.ran("close_review")
    calls = [m.json() for m in lab.bus.messages("gpos/v1/telemetry/tool/>")]
    agent_calls = [(c["service"], c["tool"]) for c in calls
                   if c["caller"] == "agent" and c["ref"] == review_id]
    assert sorted(agent_calls) == [("pos", "get_transaction"),
                                   ("wws", "get_sales_performance")]   # talk track: 2
    assert [c["tool"] for c in calls if c["caller"] == "workflow" and c["ref"] == review_id
            and c["tool"] == "note_evidence"] == ["note_evidence"]

    # R4: summary, gated apply_price with the copied labels, outcome from the database
    payload = sam_input(lab, topics.approval_request("199", "99", proposal_id),
                        "r4_price_approval", "gpos-price-approval")
    approval = lab.run("gpos-price-approval", payload,
                       {"gpos-price-approver": approver(lab.mcp, "approve", GATE_DELAY_S + 1)},
                       "run-r4-s1")
    assert approval.result == {"proposal_id": proposal_id, "outcome": "approved"}
    assert [n["node"] for n in approval.notifications] == ["inform", "tell"]
    inform, tell = approval.notifications
    assert inform["title"] == ("Preisvorschlag GEBIT Ente (Quietscheente gelb): "
                               "9,99 € → 7,99 € (\u221220 %)")  # U+2212 (10.4)
    assert tell["title"] == ("Preis aktiv: GEBIT Ente (Quietscheente gelb) 7,99 € "
                             "bis Di 23.02. 20:00")
    assert approval.outputs["approve"]["status"] == "applied"
    record = lab.mcp.clients["engine"].get(f"/api/proposals/{proposal_id}").json()  # 9.9
    gate = record["approval"]
    assert (record["state"], gate["apply_calls"], gate["outcome"]) == ("approved", 1,
                                                                       "approved")
    gap = (datetime.fromisoformat(gate["first_apply_at"])
           - datetime.fromisoformat(gate["checked_at"])).total_seconds()
    assert gap >= GATE_DELAY_S
    (recorded,) = approval.ran("record_outcome")          # the result's message, copied
    assert recorded["tool_message"] == approval.outputs["approve"]["message"] == (
        "Neuer Preis 7,99 € aktiv")
    assert (gate["evidence"]["rule"], gate["evidence"]["path"],
            gate["evidence"]["tool_message"]) == ("R1", "price_change",
                                                  "Neuer Preis 7,99 € aktiv")

    # PriceChangeApplied reaches the monitor; the next scan costs 7,99 (BOOTH_ACTION)
    applied = lab.one("showcase/wws/v1/price/PriceChangeApplied/DE/999/199/100001")
    change = feed.price_change(applied.topic, applied.json(), lab.settings.tz)
    assert (change["old"], change["new"], change["proposal_id"], change["valid_to_label"]) == (
        "9,99", "7,99", proposal_id, "Di 23.02. 20:00")
    proposal = lab.one(f"gpos/v1/proposal/approved/199/99/{proposal_id}").json()
    assert proposal["action_id"] == change["action_id"] == approval.outputs["approve"][
        "action_id"]

    # 7.2 payloads as the engine, the gate and the MCP servers publish them
    s1 = lab.bus.published[start:]
    by_root = {root: [m.json() for m in s1 if m.topic.startswith(f"gpos/v1/{root}/")]
               for root in ("insight", "review/state", "proposal", "telemetry")}
    assert all(set(m) == INSIGHT_KEYS for m in by_root["insight"])
    assert [m["state"] for m in by_root["review/state"]] == ["requested", "prepared",
                                                             "prepared", "proposed"]
    assert all(set(m) >= REVIEW_KEYS for m in by_root["review/state"])
    assert ["evidence" in m for m in by_root["review/state"]] == [False, False, True, True]
    assert set(by_root["review/state"][-1]["decision"]) >= {
        "decision", "article_number", "reason", "step_pct", "headline", "rationale",
        "facts_line", "model"}
    assert by_root["review/state"][-1]["decision"]["model"] == "planning"
    assert by_root["review/state"][-1]["evidence"]["items"][0]["holds"] == "yes"
    assert [m["state"] for m in by_root["proposal"]] == ["ready", "pending", "approved"]
    assert all(set(m) >= PROPOSAL_KEYS for m in by_root["proposal"])
    assert {m["ai_model"] for m in by_root["proposal"]} == {"planning"}
    assert {"action_id", "decided_at", "status_reason"} <= set(by_root["proposal"][-1])
    assert all(set(m) == TELEMETRY_KEYS for m in by_root["telemetry"])

    # the monitor footer of 1.4 from the real events (till 99 counted as the booth)
    hub = feed.Hub(TEST_LOCATION, lab.settings.tz, refdata.load(lab.settings.data_dir),
                   Counters("199", "99"))
    for message in lab.bus.published[start:]:
        hub.handle(message.topic, message.payload)
    for rule, run in [("r1", r) for r in runs] + [("r3", review), ("r4", approval)]:
        hub.handle(topics.sam_done(rule), compact(run.result).encode())
    assert hub.counters.to_dict()["line"] == (   # 6.3, UI counters of the two-stage AI
        "13 Kassenereignisse → 6 SAM-Läufe → 3 KI-Agenten-Läufe (fast 2, planning 1) · "
        "2 API-Abfragen der Agenten → 1 Freigabe(n)")
    tx_next = lab.pos("CreatePurchaseTransaction", {})["purchaseTransactionId"]
    lab.pos("AddArticle", {"purchaseTransactionId": tx_next,
                           "articleId": lab.catalog["2099100000018"]["article_id"],
                           "itemCount": 1})
    lab.pos("CancelPurchaseTransaction", {"purchaseTransactionId": tx_next,
                                          "cancellationReason": "Integrationstest",
                                          "cancellationReasonCode": "CASHIER"})
    added = lab.one(f"gebit/rp/purchase/v2/basket/PositionAdded/DE/999/199/99/{tx_next}")
    row = feed.pos_event(added.topic, added.json(), ("199", "99"))
    assert (row["price"], row["price_source"], row["regular_price"], row["to_sam"]) == (
        "7,99", "BOOTH_ACTION", "9,99", True)
    after = pos_event_runs(lab, tx_next, "PurchaseTransactionCancelled")
    assert [(r.result["verdict"], r.result["review_id"]) for r in after] == [
        ("scan", "none"), ("cancel", "none")]
    chip = lab.bus.messages(f"gpos/v1/insight/scan/199/99/{tx_next}")[-1].json()
    assert chip["text"] == "Messe-Aktion aktiv bis Di 23.02. 20:00"
    s1b = basket_review(lab, "S1b")  # Ente is locked while the booth action runs (1.3)
    assert s1b.result["decision"] == "only_blocked" and "gather" not in s1b.outputs


# scenario -> (review decision, proposal: article, reason, name, old, new) of 1.3
SCENARIO_REVIEWS = [
    ("S2", "propose", ("100008", "season_end", "Herzpralinen Valentin", "7,99", "5,49")),
    ("S3", "propose", ("100012", "customer_behaviour", "Espresso Bohnen kräftig", "14,49",
                       "12,99")),
    ("S5", "only_blocked", None),
    ("S6", "no_candidates", None),
    ("S8", "no_action", None),
]


@flow
@pytest.mark.parametrize("scenario,decision,proposal", SCENARIO_REVIEWS)
def test_scenario_reviews_of_1_3_and_a_denied_approval(
        lab: Lab, scenario: str, decision: str,
        proposal: tuple[str, str, str, str, str] | None) -> None:
    review = basket_review(lab, scenario)
    assert review.result["decision"] == decision
    ai = decision in ("propose", "no_action")                                     # A12
    assert ("gather" in review.outputs and "recommend" in review.outputs) is ai
    assert ("gather" in review.outputs or "recommend" in review.outputs) is ai
    if decision == "no_action":                                  # S8: fast says "rising"
        assert review.outputs["gather"]["c1_holds"] == "no"
        assert review.ran("close_review")[0]["model"] == "planning"
    if proposal is None:
        assert review.result["proposal_id"] == "none"
        assert len(review.ran("close_review")) == 1  # hard rule 6
        return
    number, reason, name, old, new = proposal
    staged = review.outputs["stage"]
    assert (staged["article_number"], review.outputs["recommend"]["reason"],
            staged["article_name"], staged["old_price"], staged["new_price"]) == proposal
    proposal_id = staged["proposal_id"]
    ready = lab.one(f"gpos/v1/proposal/ready/199/99/{proposal_id}").json()
    assert (ready["reason"], ready["old_price"], ready["new_price"]) == (reason, old, new)
    assert (ready["text_source"], ready["ai_model"]) == ("ai", "planning")   # 6.5
    if scenario == "S3":  # pos -> loyalty ReportPurchase before the review (4.4, I11)
        (purchase,) = lab.admin.fetch(
            "select member_id, visit_id, is_seed, location, "
            "(closed_at at time zone 'Europe/Berlin')::date::text as day "
            "from loyalty.purchase where purchase_transaction_id = %s",
            (review.inputs["tx_id"],))
        assert purchase == {"member_id": "M-1001", "visit_id": "booth", "is_seed": False,
                            "location": TEST_LOCATION, "day": "2027-02-16"}
        assert "Rücknahme der Preiserhöhung vom 11.01." in ready["note"]
        tools = {m.json()["tool"] for m in lab.bus.messages("gpos/v1/telemetry/tool/loyalty/>")
                 if m.json()["ref"] == review.result["review_id"]}
        assert tools == {"get_purchase_behaviour"}
        # UC1-32 (16.1 Nr. 41): the planner gets the whole S3 evidence incl. last_change
        [item] = json.loads(review.outputs["note"]["evidence"])["items"]
        assert item["numbers"] == (
            "overdue_factor=2.5; cardholder_drop_pct=46.7; days_since_last=35; "
            "median_interval_days=14; margin_pct=34.3; last_change=2027-01-11 12,99->14,49")
        assert item["tools"] == ["get_article", "get_purchase_behaviour"]
    approval = approval_run(lab, proposal_id, "deny")
    assert approval.result == {"proposal_id": proposal_id, "outcome": "rejected"}
    assert approval.notifications[-1]["title"] == f"Abgelehnt: {name} bleibt bei {old} €"
    assert approval.notifications[-1]["message"] == (
        f"Abgelehnt in Agent Mesh. Kein neuer Preis. Ref {proposal_id}.")
    assert not lab.bus.messages(f"showcase/wws/v1/price/PriceChangeApplied/DE/999/199/{number}")


@flow
def test_s7_agent_picks_season_end_and_a_second_basket_is_deferred(lab: Lab) -> None:
    lab.reset_store()  # 1.3: expectations hold from a reset (S1 may have locked Ente)
    duck = next(a for a in lab.wws.list_articles("199") if a["articleNumber"] == "100001")
    assert duck["price"]["source"] == "PRICE_SOURCE_REGULAR"  # A14: Ente 9,99 again
    review = basket_review(lab, "S7")
    agent_input = json.loads(review.outputs["prepare"]["agent_input"])
    assert [c["a"] for c in agent_input["candidates"]] == ["100008", "100001"]  # I12
    evidence = json.loads(review.outputs["note"]["evidence"])
    assert [(i["a"], i["reason"], i["holds"]) for i in evidence["items"]] == [
        ("100008", "season_end", "yes"), ("100001", "slow_seller", "yes")]
    assert review.outputs["note"]["holding"] == 2
    staged = review.outputs["stage"]
    assert (staged["article_number"], staged["new_price"]) == ("100008", "5,49")
    second = basket_review(lab, "S1")  # same till while the proposal is open (1.2, I7)
    assert second.result["decision"] == "deferred" and "gather" not in second.outputs
    assert [a["outcome"] for a in second.ran("close_review")] == ["deferred"]
    assert approval_run(lab, staged["proposal_id"], "deny").result["outcome"] == "rejected"


def review_events(lab: Lab, start: int, review_id: str) -> list[dict[str, Any]]:
    return [m.json() for m in lab.bus.published[start:]
            if m.topic.startswith("gpos/v1/review/state/") and m.topic.endswith(f"/{review_id}")]


def booth_counters(lab: Lab, start: int) -> dict[str, Any]:
    """The UI counters (6.2) of the booth events published since ``start``."""
    counters = Counters("199", "99")
    hub = feed.Hub(TEST_LOCATION, lab.settings.tz, refdata.load(lab.settings.data_dir),
                   counters)
    for message in lab.bus.published[start:]:
        hub.handle(message.topic, message.payload)
    return counters.to_dict()


PLANNING_ERROR = "Agent reported error: structured output missing"


@flow
def test_planning_failure_closes_the_review_failed_and_keeps_the_evidence(lab: Lab) -> None:
    """9.5/3: the planner ends its task as an error -> fail_fast, on_exit ``fail`` closes
    the review ``failed`` with workflow.error.message; no proposal, evidence kept."""
    def broken(_inputs: dict[str, Any]) -> dict[str, Any]:
        raise AgentFailed(PLANNING_ERROR)

    lab.reset_store()
    runs = pos_event_runs(lab, lab.play("S2"))
    review_id = runs[-1].result["review_id"]
    payload = sam_input(lab, topics.review_request("199", "99", review_id),
                        "r3_basket_review", "gpos-basket-review")
    start = len(lab.bus.published)
    run = lab.run("gpos-basket-review", payload, {
        "gpos-pricing-agent": pricing_agent(lab.mcp), "gpos-price-planner": broken},
        "run-r3-planning-failed")
    assert run.failed and run.result == {} and run.error == PLANNING_ERROR
    assert "note" in run.outputs and "recommend" not in run.outputs
    assert not {"stage", "conclude", "skip"} & set(run.outputs)
    assert run.ran("close_review") == [{"review_id": review_id, "outcome": "failed",
                                        "rationale": PLANNING_ERROR,
                                        "run_id": "run-r3-planning-failed", "model": ""}]
    events = review_events(lab, start, review_id)
    assert [e["state"] for e in events] == ["prepared", "prepared", "failed"]
    assert ["evidence" in e for e in events] == [False, True, True]  # 7.2: kept
    assert "decision" not in events[-1]
    assert events[-1]["error"] == PLANNING_ERROR
    assert all(m.json()["review_id"] != review_id
               for m in lab.bus.messages("gpos/v1/proposal/ready/199/99/>"))
    counted = booth_counters(lab, start)
    assert (counted["agent_runs"], counted["agent_runs_by_model"]) == (
        1, {"fast": 1, "planning": 0})                     # 6.2: failed counts no planning
    lab.reset_store()


@flow
def test_engine_refuses_a_recommendation_without_confirmed_evidence(lab: Lab) -> None:
    """11.3 step 2b: a planner that proposes S8's candidate although the evidence says
    ``holds`` "no" -> ``invalid``, review ``blocked`` with the planner's decision."""
    def rogue(inputs: dict[str, Any]) -> dict[str, Any]:
        cand = json.loads(inputs["review"])["candidates"][0]
        return {"decision": "propose", "article_number": cand["a"],
                "reason": cand["signals"][0], "step_pct": str(cand["suggested_step_pct"]),
                "headline": f"{cand['name']}: Preis senken", "rationale": cand["facts"],
                "facts_line": cand["facts"][:120]}

    lab.reset_store()
    runs = pos_event_runs(lab, lab.play("S8"))
    review_id = runs[-1].result["review_id"]
    payload = sam_input(lab, topics.review_request("199", "99", review_id),
                        "r3_basket_review", "gpos-basket-review")
    start = len(lab.bus.published)
    run = lab.run("gpos-basket-review", payload, {
        "gpos-pricing-agent": pricing_agent(lab.mcp), "gpos-price-planner": rogue},
        "run-r3-rogue")
    assert run.outputs["gather"]["c1_holds"] == "no"
    staged = run.outputs["stage"]
    assert (staged["status"], staged["blocked_rule"]) == (
        "invalid", "KI-Empfehlung ohne bestätigten Beleg")
    # coalesce takes the stage's empty proposal_id (a value, not null) as SAM does
    assert run.result == {"review_id": review_id, "decision": "propose", "proposal_id": ""}
    assert not run.ran("close_review")
    last = review_events(lab, start, review_id)[-1]
    assert (last["state"], last["error"]) == ("blocked", "KI-Empfehlung ohne bestätigten Beleg")
    assert (last["decision"]["model"], last["decision"]["article_number"]) == (
        "planning", staged["article_number"])
    assert last["evidence"]["items"][0]["holds"] == "no"
    counted = booth_counters(lab, start)
    assert counted["agent_runs_by_model"] == {"fast": 1, "planning": 1}
    lab.reset_store()


@flow
def test_review_reset_during_the_evidence_costs_no_planning_call(lab: Lab) -> None:
    """9.5 node ``recommend``: ``note_evidence`` answers ``stale`` after a reset and the
    planner never runs (positive ``==`` on ``note.status``, hard rule 6)."""
    def gather_then_reset(inputs: dict[str, Any]) -> dict[str, Any]:
        out = pricing_agent(lab.mcp)(inputs)
        lab.reset_store()                  # /kasse reset while the agent was busy (11.7)
        return out

    def never(_inputs: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("the planner must not run on a stale review")

    lab.reset_store()
    runs = pos_event_runs(lab, lab.play("S2"))
    review_id = runs[-1].result["review_id"]
    payload = sam_input(lab, topics.review_request("199", "99", review_id),
                        "r3_basket_review", "gpos-basket-review")
    start = len(lab.bus.published)
    run = lab.run("gpos-basket-review", payload, {
        "gpos-pricing-agent": gather_then_reset, "gpos-price-planner": never},
        "run-r3-stale")
    assert not run.failed and run.outputs["note"]["status"] == "stale"
    assert run.outputs["note"]["evidence"] == ""
    assert {"recommend", "stage", "conclude"} <= run.skipped
    assert not run.ran("close_review") and not run.ran("stage_proposal")
    assert run.result == {"review_id": review_id, "decision": "has_candidates",
                          "proposal_id": "none"}
    events = review_events(lab, start, review_id)
    assert [e["state"] for e in events] == ["prepared", "superseded"]
    assert not any("evidence" in e for e in events)


@flow
def test_f2_fallback_applies_through_the_ungated_connector(lab: Lab) -> None:
    """Fallback F2 (9.9): gated time tool, then ``apply_price`` in a tool node on
    ``gpos-price-apply`` with ``approved_at``; the gate runs with ``GATE_GUARD=f2``."""
    lab.reset_store()
    review = basket_review(lab, "S2")
    proposal_id = review.outputs["stage"]["proposal_id"]
    payload = sam_input(lab, topics.approval_request("199", "99", proposal_id),
                        "r4_price_approval", "gpos-price-approval")
    run = lab.run("gpos-price-approval@f2", payload,
                  {"gpos-price-approver-f2": approver_f2(GATE_DELAY_S + 1)}, "run-r4-f2")
    assert run.result == {"proposal_id": proposal_id, "outcome": "approved"}
    (applied,) = run.ran("apply_price")
    assert applied["approved_at"] == run.outputs["approve"]["time"]
    assert run.outputs["apply"]["status"] == "applied"
    assert run.outputs["record"]["action_id"] == run.outputs["apply"]["action_id"]
    lab.reset_store()


@flow
@pytest.mark.parametrize("agent,outcome,reason", [
    (approver_f2(GATE_DELAY_S + 1, error=DENY_ERROR), "rejected",
     "Abgelehnt in Agent Mesh (Agent meldete einen Fehler)"),
    (approver_f2(GATE_DELAY_S + 1, status="denied", with_time=True), "failed",
     "Agent meldet Ablehnung trotz Freigabe – kein neuer Preis"),
    (approver_f2(GATE_DELAY_S + 1, status="denied", with_time=False), "rejected",
     "Abgelehnt in Agent Mesh"),
])
def test_f2_deny_paths(lab: Lab, agent: Agent, outcome: str, reason: str) -> None:
    """F2 (4.3): ``record`` passes ``approved_at``; a denial after a real approval time is
    no „Abgelehnt“, the deny-as-error path is recognised by the engine (R6). ``record``
    reads nothing of the skipped ``apply`` (a whole-value reference would be null)."""
    lab.reset_store()
    proposal_id = basket_review(lab, "S2").outputs["stage"]["proposal_id"]
    payload = sam_input(lab, topics.approval_request("199", "99", proposal_id),
                        "r4_price_approval", "gpos-price-approval")
    run = lab.run("gpos-price-approval@f2", payload, {"gpos-price-approver-f2": agent},
                  f"run-r4-f2-{outcome}")
    record = proposal_record(lab, proposal_id)
    assert (record["state"], record["status_reason"]) == (outcome, reason)
    assert record["approval"]["apply_calls"] == 0 and not run.ran("apply_price")
    if run.failed:
        assert run.result == {} and "record_fail" in run.outputs
    else:
        (recorded,) = run.ran("record_outcome")
        assert recorded["approved_at"] == run.outputs["approve"]["time"]
        assert recorded["tool_message"] == run.outputs["approve"]["message"] == SAM_DENIED
        assert "action_id" not in recorded       # apply is skipped: no null reference
    lab.reset_store()


EXPIRED = "Keine Antwort binnen 2 Minuten"
REJECTED = "Abgelehnt in Agent Mesh"
TECHNICAL = "Technischer Fehler – kein neuer Preis"
EVIDENCE_AUDITS = ("deny_via_error", "expired_by_window", "deny_after_approval",
                   "deny_via_message")
# mode, answer delay (None = GATE_DELAY_S + 1), failed run, outcome, status_reason,
# tell title prefix (record, or record_fail whose tell SAM never sends), audit row,
# engine rule of approval.evidence (11.5)
APPROVAL_PATHS = [
    pytest.param("deny", None, False, "rejected", REJECTED, "Abgelehnt: ",
                 "deny_via_message", "R5m", id="deny-clean"),
    pytest.param("deny_status_error", None, False, "rejected", REJECTED, "Abgelehnt: ",
                 "deny_via_message", "R5m", id="deny-status-error-sam-message"),  # F1 12.11.
    pytest.param("deny_no_message", None, False, "rejected", REJECTED, "Abgelehnt: ",
                 None, "R5", id="deny-clean-without-message"),
    pytest.param("deny", 0.0, False, "failed",
                 "Ablehnung schneller als möglich – Agent prüfen", "Nicht angewendet: ",
                 "deny_via_message", "R5m", id="deny-clean-too-early"),
    pytest.param("deny_error", None, True, "rejected",
                 "Abgelehnt in Agent Mesh (Agent meldete einen Fehler)", "Abgelehnt: ",
                 "deny_via_error", "R6", id="deny-via-error"),
    pytest.param("deny_error", 0.0, True, "failed", DENY_ERROR, "Nicht angewendet: ", None,
                 "R7", id="deny-via-error-too-early"),
    pytest.param("error", None, False, "failed", TECHNICAL, "Nicht angewendet: ", None,
                 "R8", id="error-clean"),
    pytest.param("deny_late", HIL_TIMEOUT_S + 1, False, "expired", EXPIRED, "Abgelaufen: ",
                 "expired_by_window", "R3b", id="deny-after-window"),
    pytest.param("timeout", HIL_TIMEOUT_S + 1, False, "expired", EXPIRED, "Abgelaufen: ",
                 None, "R3a", id="timeout-clean"),
    pytest.param("timeout_status_error", HIL_TIMEOUT_S + 1, False, "expired", EXPIRED,
                 "Abgelaufen: ", None, "R3a", id="timeout-status-error-sam-message"),
    pytest.param("timeout", None, False, "failed", TECHNICAL, "Nicht angewendet: ", None,
                 "R7m", id="timeout-message-inside-the-window"),
    pytest.param("timeout_error", HIL_TIMEOUT_S + 1, True, "expired", EXPIRED,
                 "Abgelaufen: ", None, "R3a", id="timeout-via-error"),
]


@flow
@pytest.mark.parametrize("mode,delay,failed,outcome,reason,title,audit,rule", APPROVAL_PATHS)
def test_deny_timeout_and_error_paths_of_r4(lab: Lab, mode: str, delay: float | None,
                                            failed: bool, outcome: str, reason: str,
                                            title: str, audit: str | None,
                                            rule: str) -> None:
    """UC1-27/UC1-29 (11.5): the approver's answers with SAM's copied message and its
    task errors (the observed 12.11. texts) end by the engine clock: denial only inside
    the window and never earlier than a human can answer, never with a price; on_exit
    has no tell. A deny with agent status ``error`` and SAM's message is ``rejected``
    (R5m), SAM's timeout message only after the window ``expired``."""
    lab.reset_store()
    start = len(lab.bus.published)
    review = basket_review(lab, "S2")
    proposal_id = review.outputs["stage"]["proposal_id"]
    run = approval_run(lab, proposal_id, mode, delay)
    assert run.failed is failed
    assert "approve" in run.outputs or failed
    if failed:  # fail_fast: on_exit record_fail with workflow.error.message, errorOutput
        assert run.result == {} and run.ran("record_outcome") == [
            {"proposal_id": proposal_id, "run_id": run.run_id, "agent_status": "",
             "action_id": "", "error": run.error}]
        assert "record" not in run.outputs and "tell" not in run.outputs  # 16.1 no. 32
        recorded = run.outputs["record_fail"]
    else:
        assert run.result == {"proposal_id": proposal_id, "outcome": outcome}
        assert [(a["error"], a["tool_message"]) for a in run.ran("record_outcome")] == [
            ("", run.outputs["approve"]["message"])]
        recorded = run.outputs["record"]
        assert run.notifications[-1]["title"] == recorded["notify_title"]
    assert recorded["outcome"] == outcome and recorded["notify"] == "yes"
    assert recorded["notify_title"].startswith(title)
    record = proposal_record(lab, proposal_id)
    assert (record["state"], record["status_reason"]) == (outcome, reason)
    assert record["approval"]["apply_calls"] == 0 and not record["approval"]["first_apply_at"]
    assert record["ai_model"] == "planning"
    audits = [r["kind"] for r in lab.admin.fetch(
        "select kind from engine.audit_event where ref = %s and kind = any(%s)",
        (proposal_id, list(EVIDENCE_AUDITS)))]
    assert audits == ([audit] if audit else [])
    evidence = record["approval"]["evidence"]
    assert evidence["rule"] == rule and evidence["tool_message"] == (
        "" if failed else run.outputs["approve"]["message"])
    assert not [m for m in lab.bus.published[start:]
                if m.topic.startswith("showcase/wws/v1/price/PriceChangeApplied/")]
    ended = lab.one(f"gpos/v1/proposal/{outcome}/199/99/{proposal_id}").json()
    assert (ended["status_reason"], ended["ai_model"]) == (reason, "planning")
    lab.reset_store()


@flow
@pytest.mark.parametrize("agent_status,outcome,reason,rule", [
    ("error", "failed", TECHNICAL, "R8"),
    ("", "failed", "Agent meldete keinen Status – kein neuer Preis", "R8"),
    ("denied", "rejected", REJECTED, "R5"),          # the clean status alone still counts
])
def test_an_unresolved_message_is_no_denial(lab: Lab, agent_status: str, outcome: str,
                                            reason: str, rule: str) -> None:
    """9.1: a ``{{approve.output.message}}`` SAM could not resolve stays text; over the
    real MCP tool the engine never reads it as SAM's denial (no R5m), it only shows it."""
    lab.reset_store()
    proposal_id = basket_review(lab, "S2").outputs["stage"]["proposal_id"]
    run_id = f"run-r4-unresolved-{agent_status or 'none'}"
    check = lab.mcp.workflow_tool("engine", "check_proposal",
                                  {"proposal_id": proposal_id, "run_id": run_id})
    assert check["status"] == "awaiting_approval"
    time.sleep(GATE_DELAY_S + 1)                     # inside the window, a human could
    recorded = lab.mcp.workflow_tool("engine", "record_outcome", {
        "proposal_id": proposal_id, "run_id": run_id, "agent_status": agent_status,
        "action_id": "", "error": "", "tool_message": "{{approve.output.message}}"})
    assert recorded["outcome"] == outcome
    record = proposal_record(lab, proposal_id)
    assert (record["state"], record["status_reason"]) == (outcome, reason)
    evidence = record["approval"]["evidence"]
    assert (evidence["rule"], evidence["tool_message"]) == (rule,
                                                            "{{approve.output.message}}")
    assert not lab.admin.fetch("select kind from engine.audit_event where ref = %s "
                               "and kind = 'deny_via_message'", (proposal_id,))
    lab.reset_store()


@flow
def test_get_transaction_of_nine_long_lines_shows_eight_and_more(lab: Lab) -> None:
    """8.4 / smoke step 4: the nine longest names -> 8 lines, ``more`` 1, <= 1200 B."""
    longest = sorted(lab.catalog.values(), key=lambda a: len(a["name"]), reverse=True)[:9]
    tx_id = lab.pos("CreatePurchaseTransaction", {})["purchaseTransactionId"]
    for article in longest:
        lab.pos("AddArticle", {"purchaseTransactionId": tx_id,
                               "articleId": article["article_id"], "itemCount": 1})
    view = lab.mcp.agent_tool("pos", "get_transaction", tx_id=tx_id, ref="it-sizes")
    assert (len(view["lines"]), view["more"], view["status"]) == (8, 1, "OPEN")
    lab.pos("CancelPurchaseTransaction", {"purchaseTransactionId": tx_id,
                                          "cancellationReason": "Integrationstest",
                                          "cancellationReasonCode": "CASHIER"})


@flow
def test_bff_reaches_engine_and_pos_over_their_http_apis(
        lab: Lab, make_settings: Callable[..., Settings]) -> None:
    """10.1/11.8 with the real BFF: health, state and proposal proxy from the engine, the
    R4 ``errorOutput`` forwarded to ``POST /api/sam-error`` (expired after the 5 s grace)
    and the reset chain 11.7. The BFF's booth is till 99 here, so nothing touches 101."""
    from gposdemo.ui import create as create_ui

    ui = create_ui(make_settings("ui", GPOS_BOOTH_LOCATION=TEST_LOCATION, **lab.ui_env),
                   lab.bus)
    ui.start()
    try:
        with TestClient(ui.app) as bff:
            assert bff.get("/health").json() == {"status": "ok", "bus": True, "pos": True,
                                                 "wws": True, "engine": True}
            staged = basket_review(lab, "S2").outputs["stage"]
            proposal_id = staged["proposal_id"]
            check = lab.mcp.workflow_tool("engine", "check_proposal",
                                          {"proposal_id": proposal_id, "run_id": "run-r4-x"})
            assert check["status"] == "awaiting_approval"
            state = bff.get("/api/state").json()
            assert (state["store"], state["till"], state["proposal"]["proposal_id"],
                    state["proposal"]["state"]) == ("199", "99", proposal_id, "pending")
            record = bff.get(f"/api/proposals/{proposal_id}").json()
            assert (record["state"], record["approval"]["apply_calls"]) == ("pending", 0)
            time.sleep(HIL_TIMEOUT_S + 0.5)    # a real HIL timeout ends after the window
            lab.bus.publish(topics.sam_error("r4"), compact(
                {"error": "Tool approval timed out after 2 minutes"}))
            deadline = time.monotonic() + 15
            while record["state"] == "pending" and time.monotonic() < deadline:
                time.sleep(0.25)
                record = bff.get(f"/api/proposals/{proposal_id}").json()
            assert (record["state"], record["approval"]["outcome"]) == ("expired", "expired")
            assert record["approval"]["sam_error_at"]
            reset = bff.post("/api/demo/reset", json={"scope": "booth"}).json()
            assert reset["ok"] and set(reset["steps"]) == {"engine", "wws", "pos", "loyalty",
                                                           "bff"}
            catalog = bff.get("/api/catalog", params={"till": "99"}).json()
            assert catalog["store"] == "199" and len(catalog["articles"]) == 30
    finally:
        ui.stop()
