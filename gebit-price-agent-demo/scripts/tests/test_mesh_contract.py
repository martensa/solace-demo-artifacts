"""mesh/ against UC1-BUILD-SPEC 9 (names, ports, gates, hard rule 6, payload contract)."""

from __future__ import annotations

import re
import sys

import pytest
from conftest import ROOT, load

import e2e
from gen_connector_manifest import CONNECTORS
from opslib import REF_RE

CONNECTOR_URLS = {
    "gpos-booth-tools": "http://gpos-engine.gpos-demo.svc:8765/mcp",
    "gpos-price-gate": "http://gpos-gate.gpos-demo.svc:8766/mcp",
    "gpos-wws-api": "http://gpos-wws.gpos-demo.svc:8773/mcp",
    "gpos-loyalty-api": "http://gpos-loyalty.gpos-demo.svc:8772/mcp",
    "gpos-pos-api": "http://gpos-pos.gpos-demo.svc:8771/mcp",
}
WORKFLOWS = ("gpos-pos-event", "gpos-basket-review", "gpos-price-approval")
AGENTS = ("gpos-pricing-agent", "gpos-price-planner", "gpos-price-approver")
# the artifact tools the evidence agent's prompt names (rule 3, hard rule 5)
PROMPT_ARTIFACT_TOOLS = ("list_artifacts", "load_artifact", "create_sqlite_db",
                         "merge_structured_data", "transform_data_with_jmespath",
                         "artifact_search_and_replace_regex", "append_to_artifact")
# A-21 (lab 12.11.): the two toolsets SAM attaches to every agent and all their tools
EXCLUDED_TOOLS = {
    "builtin_artifact_tools": ["list_artifacts", "load_artifact", "delete_artifact",
                               "append_to_artifact", "artifact_search_and_replace_regex",
                               "artifact_grep"],
    "data_analysis": ["query_data_with_sql", "create_sqlite_db", "transform_data_with_jmespath",
                      "merge_structured_data", "reinterpret_artifact",
                      "create_chart_from_plotly_config"],
}
SAM_DENIED = "Tool call denied by user."
SAM_TIMEOUT = "Tool approval timed out after 2 minutes."
# structuredContent fields of the workflow tools (spec 8.2 / 8.3 models)
MODEL_FIELDS = {
    "assess_event": {"verdict", "event_key", "event_type", "tx_id", "store", "till",
                     "article_number", "insight_code", "insight_text"},
    "raise_basket_review": {"status", "review_id", "tx_id"},
    "prepare_review": {"candidate", "review_id", "tx_id", "membership_id", "lines",
                       "candidates", "reason", "agent_input"},
    "stage_proposal": {"status", "proposal_id", "article_number", "article_name", "old_price",
                       "new_price", "pct_label", "reason_label", "step_pct", "clamped",
                       "blocked_rule", "text_source"},
    "check_proposal": {"status", "proposal_id", "proposal_hash", "article_name", "old_price",
                       "new_price", "pct_label", "reason_label", "valid_to_label",
                       "notify_title", "notify_message"},
    "record_outcome": {"outcome", "proposal_id", "action_id", "notify", "notify_title",
                       "notify_message"},
    "note_event": {"status", "event_key", "verdict"},
    "close_review": {"status", "event_key", "verdict"},
    "note_evidence": {"status", "review_id", "checked", "holding", "evidence"},
    "apply_price": {"status", "proposal_id", "action_id", "new_price", "message"},
}
TOOL_PARAMS = {
    "assess_event": {"raw", "run_id"},
    "raise_basket_review": {"tx_id", "run_id"},
    "note_event": {"event_key", "verdict", "run_id"},
    "prepare_review": {"review_id", "run_id"},
    "note_evidence": {"review_id", "model", "tx_status", "c1_article", "c1_reason",
                      "c1_holds", "c1_numbers", "c1_tools", "c2_article", "c2_reason",
                      "c2_holds", "c2_numbers", "c2_tools", "run_id"},
    "stage_proposal": {"review_id", "article_number", "reason", "step_pct", "headline",
                       "rationale", "facts_line", "run_id", "model"},
    "close_review": {"review_id", "outcome", "rationale", "run_id", "model"},
    "check_proposal": {"proposal_id", "run_id"},
    "record_outcome": {"proposal_id", "run_id", "agent_status", "action_id", "error",
                       "approved_at", "tool_message"},
    "apply_price": {"proposal_id", "proposal_hash", "article_name", "old_price", "new_price",
                    "pct_label", "reason_label", "valid_to_label", "run_id", "approved_at"},
}
# parameters a tool node may leave out (F2 only: approved_at, spec 4.3; record_fail:
# tool_message, there is no agent output to pass; F2 record: action_id, its apply is
# skipped after a deny, test_f2_record_reads_nothing_of_apply)
OPTIONAL_PARAMS = {"record_outcome": {"approved_at", "tool_message", "action_id"},
                   "apply_price": {"approved_at"}}
AGENT_REF = re.compile(r"\{\{\s*(\w+)\.output\.(\w+)")
# exactly the keys of the SAM inputs of spec 7.2 (no type, no ts)
REVIEW_REQUEST = {"schema_version", "review_id", "tx_id", "store", "till"}
APPROVAL_REQUEST = {"schema_version", "proposal_id", "store", "till"}
STRUCT_REF = re.compile(r"\{\{(\w+)\.output\.mcp_structured_content\.(\w+)\}\}")


def workflow(name: str, root: str = "mesh") -> dict:
    return load(f"{root}/workflows/{name}.yaml")


def nodes(wf: dict) -> dict[str, dict]:
    return {n["id"]: n for n in wf["spec"]["appConfig"]["nodes"]}


def test_manifest_lists_the_spec_resources_in_order() -> None:
    manifest = load("mesh/manifest.yaml")
    assert manifest["name"] == "gpos-uc1"
    assert manifest["target"] == {"name": "solace-lab", "url": "https://sam.solace.lab",
                                  "auth": {"type": "oauth"}}
    assert manifest["resources"] == {
        "connectors": list(CONNECTOR_URLS),
        "agents": list(AGENTS),
        "workflows": list(WORKFLOWS),
    }
    for kind, names in manifest["resources"].items():
        for name in names:
            doc = load(f"mesh/{kind}/{name}.yaml")
            assert doc["kind"] == kind[:-1] and doc["name"] == name


@pytest.mark.parametrize("name,url", CONNECTOR_URLS.items())
def test_connectors_point_at_the_services(name: str, url: str) -> None:
    values = load(f"mesh/connectors/{name}.yaml")["spec"]["values"]
    assert (values["server_url"], values["connection_type"], values["auth_type"]) == (
        url, "streamable-http", "none")
    assert ("hil" in values) == (name == "gpos-price-gate")


def test_gate_connector_gates_apply_price_with_a_ref() -> None:
    hil = load("mesh/connectors/gpos-price-gate.yaml")["spec"]["values"]["hil"]
    gate = hil["tools"]["apply_price"]
    assert (gate["require_approval"], gate["show_args"], gate["timeout"]) == (True, False, "2m")
    rendered = gate["approval_message"]
    for arg in ("article_name", "old_price", "new_price", "pct_label", "reason_label",
                "valid_to_label", "proposal_id"):
        rendered = rendered.replace(f"{{{{.{arg}}}}}", {"proposal_id": "GP-270216-0003"}
                                    .get(arg, arg))
    assert REF_RE.search(rendered).group(1) == "GP-270216-0003"   # inbox matching (12.6)
    assert rendered.startswith("Preisänderung article_name: old_price € auf new_price €")


def test_fallback_connector_is_ungated_and_on_the_gate_service() -> None:
    values = load("mesh/fallback/connectors/gpos-price-apply.yaml")["spec"]["values"]
    assert values["server_url"] == CONNECTOR_URLS["gpos-price-gate"]
    assert "hil" not in values


def test_agents_use_the_model_alias_only() -> None:
    """Hard rule 1: aliases only (fast, planning), no sampling parameter (Claude 5)."""
    pricing = load("mesh/agents/gpos-pricing-agent.yaml")["spec"]
    planner = load("mesh/agents/gpos-price-planner.yaml")["spec"]
    approver = load("mesh/agents/gpos-price-approver.yaml")["spec"]
    for spec, alias in ((pricing, "fast"), (planner, "planning"), (approver, "fast")):
        assert spec["modelProvider"] == [alias]
        assert spec["toolsets"] == list(EXCLUDED_TOOLS)            # A-21, test below
        assert not {"temperature", "top_p", "top_k", "toolsetConfigs"} & set(spec)
        assert not {"temperature", "top_p", "top_k"} & set(
            spec.get("additionalConfigurations") or {})
    assert pricing["connectors"] == ["gpos-wws-api", "gpos-loyalty-api", "gpos-pos-api"]
    assert planner["connectors"] == []                  # A-28: no tools at all
    assert approver["connectors"] == ["gpos-price-gate"]
    assert "additionalConfigurations" not in approver
    by_id = nodes(workflow("gpos-basket-review"))
    for spec, node, name in ((pricing, "gather", "gpos-pricing-agent"),
                             (planner, "recommend", "gpos-price-planner")):
        assert by_id[node]["agent_name"] == name
        assert spec["additionalConfigurations"]["supportsStreaming"] is False
        assert spec["additionalConfigurations"]["outputSchema"] == by_id[node][
            "output_schema_override"]                   # 9.1: same schema at both places


@pytest.mark.parametrize("path", ["mesh/agents/gpos-pricing-agent.yaml",
                                  "mesh/agents/gpos-price-planner.yaml",
                                  "mesh/agents/gpos-price-approver.yaml",
                                  "mesh/fallback/agents/gpos-price-approver-f2.yaml"])
def test_agents_exclude_every_artifact_and_data_tool(path: str) -> None:
    """Hard rule 5 / A-21: both auto-attached toolsets listed (SAM drops the exclusions
    of an unlisted toolset silently) with exactly their 12 tools excluded."""
    spec = load(path)["spec"]
    assert spec["toolsetExcludedTools"] == EXCLUDED_TOOLS
    assert sum(len(set(v)) for v in spec["toolsetExcludedTools"].values()) == 12
    extra = ["builtin_time_tools"] if path.endswith("-f2.yaml") else []  # F2's gated tool
    assert spec["toolsets"] == extra + list(EXCLUDED_TOOLS)


def test_e2e_flags_every_excluded_tool() -> None:
    """Hard rule 5 / 13.4: the e2e check covers exactly the 12 excluded tools, so a
    dropped exclusion (A-21) fails a run for any of them, not only the prompt's 7."""
    assert {k: list(v) for k, v in e2e.EXCLUDED_TOOLS.items()} == EXCLUDED_TOOLS
    assert sorted(e2e.ARTIFACT_TOOLS) == sorted(t for v in EXCLUDED_TOOLS.values() for t in v)
    assert len(set(e2e.ARTIFACT_TOOLS)) == 12
    assert set(PROMPT_ARTIFACT_TOOLS) < set(e2e.ARTIFACT_TOOLS)


def test_pricing_prompt_still_forbids_artifact_tools() -> None:
    prompt = load("mesh/agents/gpos-pricing-agent.yaml")["spec"]["systemPrompt"]
    for tool in PROMPT_ARTIFACT_TOOLS:
        assert tool in prompt                           # hard rule 5, unchanged rule 3


def test_planner_names_no_tool_and_writes_the_recommendation() -> None:
    planner = load("mesh/agents/gpos-price-planner.yaml")["spec"]
    prompt = planner["systemPrompt"]
    assert not re.findall(r"\b(?:get|apply)_[a-z_]+\b", prompt)
    assert not [t for t in e2e.ARTIFACT_TOOLS if t in prompt]  # F2 of 12.11.: no tool names
    # neutral output rule (UC1-29): no tool ban against SAM's output-file instruction,
    # and never SAM's output format itself (that broke structured invocation before)
    assert "You need no tools for this task" in prompt and "in your first response" in prompt
    # UC1-30 (third gate run): the model called SAM's internal _notify_artifact_save
    # itself and then looped on _continue_generation; both are named and banned, the
    # answer is text. Still no description of SAM's output format.
    assert "That result is text in\nyour answer, never a tool call." in prompt
    assert "Never call _notify_artifact_save or\n_continue_generation" in prompt
    without_internal = prompt.replace("_notify_artifact_save", "")
    for banned in ("You have no tools", "Never call a tool", "save_artifact", "artifact",
                   "\u00ab\u00ab\u00ab", "result:artifact", "filename"):
        assert banned not in without_internal, banned
    assert "holds \"yes\"" in prompt and "Never write a price, a euro amount" in prompt
    recommend = nodes(workflow("gpos-basket-review"))["recommend"]["instruction"]
    assert "You have no tools" not in recommend and "You need no tools" in recommend
    assert "save_artifact" not in recommend
    assert "as text in your first response, never as a tool call" in recommend
    pricing = load("mesh/agents/gpos-pricing-agent.yaml")["spec"]["systemPrompt"]
    assert "You decide nothing" in pricing and "at most 5 calls" in pricing
    # UC1-31: Haiku read rule c as a replacement of b (S3 6/6 without get_article)
    assert ("- customer_behaviour, card with consent_profiling true: get_article\n"
            "        AND get_purchase_behaviour (two calls)") in pricing
    assert "- customer_behaviour, no card or no consent: get_article" in pricing
    assert "also get_article for customer_behaviour." in pricing
    gather = nodes(workflow("gpos-basket-review"))["gather"]["instruction"]
    assert "get_article and get_purchase_behaviour" in gather
    assert "at most 160 characters, in the order of this list:" in pricing


@pytest.mark.parametrize("name", WORKFLOWS)
def test_workflow_basic_form(name: str) -> None:
    app = workflow(name)["spec"]["appConfig"]
    assert app["fail_fast"] is True
    for node in app["nodes"]:
        if node["type"] == "switch":
            assert node.get("default")
        if node["type"] == "agent":
            assert node.get("output_schema_override")


def after_switch(app: dict) -> tuple[set[str], set[str]]:
    """(direct switch targets, all nodes downstream of a switch)."""
    by_id = {n["id"]: n for n in app["nodes"]}
    switches = {i for i, n in by_id.items() if n["type"] == "switch"}
    targets = {c["node"] for i in switches for c in by_id[i]["cases"]} | {
        by_id[i]["default"] for i in switches}
    downstream: set[str] = set()
    changed = True
    while changed:
        changed = False
        for i, n in by_id.items():
            deps = set(n.get("depends_on", []))
            if i not in downstream and deps & (switches | downstream):
                downstream.add(i)
                changed = True
    return targets, downstream


@pytest.mark.parametrize("root,name", [("mesh", w) for w in WORKFLOWS]
                         + [("mesh/fallback", "gpos-price-approval")])
def test_hard_rule_6_positive_when_behind_switches(root: str, name: str) -> None:
    app = workflow(name, root)["spec"]["appConfig"]
    targets, downstream = after_switch(app)
    for node in app["nodes"]:
        conditions = [c["condition"] for c in node.get("cases", [])] + [node.get("when", "")]
        assert not any("!=" in c for c in conditions), node["id"]
        if node["id"] in downstream - targets:
            assert "==" in node.get("when", ""), f"{name}.{node['id']} needs a positive when"


@pytest.mark.parametrize("root,name", [("mesh", w) for w in WORKFLOWS]
                         + [("mesh/fallback", "gpos-price-approval")])
def test_tool_nodes_match_the_tool_contract(root: str, name: str) -> None:
    app = workflow(name, root)["spec"]["appConfig"]
    by_id = nodes(workflow(name, root))
    served = {c.path.rsplit("/", 1)[1][:-5]: set(c.tools) for c in CONNECTORS}
    for node in app["nodes"]:
        if node["type"] == "tool" and "connector" in node:
            assert node["tool"] in served[node["connector"]]
            given, params = set(node["input"]), TOOL_PARAMS[node["tool"]]
            assert params - OPTIONAL_PARAMS.get(node["tool"], set()) <= given <= params
            if node["connector"] == "gpos-price-gate":
                assert "approved_at" not in given        # B1: the gate checks the clock
        for text in [str(v) for v in node.get("input", {}).values()] + [node.get("when", "")]:
            for ref_node, fld in STRUCT_REF.findall(text):
                assert fld in MODEL_FIELDS[by_id[ref_node]["tool"]], f"{ref_node}.{fld}"


@pytest.mark.parametrize("root,name", [("mesh", w) for w in WORKFLOWS]
                         + [("mesh/fallback", "gpos-price-approval")])
def test_agent_fields_read_downstream_are_required(root: str, name: str) -> None:
    """9.1 (SAM 2.542 data flow): a field missing on a node that ran fails the consuming
    node, so every agent output field another node reads is required in the override
    and named in the instruction (the review of UC1-29: F2 ``message``)."""
    by_id = nodes(workflow(name, root))
    for node in by_id.values():
        texts = [str(v) for v in node.get("input", {}).values()] + [node.get("when", "")]
        texts += [c["condition"] for c in node.get("cases", [])]
        for ref_node, fld in AGENT_REF.findall(" ".join(texts)):
            source = by_id.get(ref_node, {})
            if source.get("type") != "agent":
                continue
            assert fld in source["output_schema_override"]["required"], (
                f"{name}: {node['id']} reads {ref_node}.{fld}")
            assert fld in source["instruction"], f"{ref_node} must name {fld}"


def test_on_exit_nodes_have_no_dependencies() -> None:
    for name in ("gpos-basket-review", "gpos-price-approval"):
        app = workflow(name)["spec"]["appConfig"]
        handler = nodes(workflow(name))[app["on_exit"]["on_failure"]]
        assert "depends_on" not in handler
        assert "{{workflow.error.message}}" in str(handler["input"])


def test_sam_input_schemas_declare_every_payload_key() -> None:
    assert "input_schema" not in workflow("gpos-pos-event")["spec"]["appConfig"]  # raw text
    review = workflow("gpos-basket-review")["spec"]["appConfig"]["input_schema"]
    approval = workflow("gpos-price-approval")["spec"]["appConfig"]["input_schema"]
    assert set(review["properties"]) == REVIEW_REQUEST and review["required"] == ["review_id"]
    assert set(approval["properties"]) == APPROVAL_REQUEST
    assert approval["required"] == ["proposal_id"]
    f2 = workflow("gpos-price-approval", "mesh/fallback")["spec"]["appConfig"]["input_schema"]
    assert f2 == approval


def test_basket_review_timeouts_fit_the_workflow_timeout() -> None:
    """8: gather 60 s (fast), note 5 s, recommend 30 s per attempt with one retry
    after 1 s (planning, UC1-30), workflow 150 s."""
    app = workflow("gpos-basket-review")["spec"]["appConfig"]
    by_id = nodes(workflow("gpos-basket-review"))
    seconds = {i: int(n.get("timeout", app["default_node_timeout"]).rstrip("s"))
               for i, n in by_id.items() if n["type"] != "switch"}
    assert (seconds["gather"], seconds["note"], seconds["recommend"]) == (60, 5, 30)
    assert app["workflow_timeout"] == "150s" and app["version"] == "0.2.3"
    # the parser only knows retry_strategy; any other key silently means no retry
    retry = by_id["recommend"]["retry_strategy"]
    assert retry == {"limit": 1, "retry_policy": "Always", "backoff": {"duration": "1s"}}
    assert not [i for i, n in by_id.items() if i != "recommend" and (
        "retry_strategy" in n or "retry" in n or "retryStrategy" in n)]
    recommend = seconds["recommend"] * (1 + retry["limit"]) + 1
    chain = sum(seconds[i] for i in ("prepare", "gather", "note", "stage")) + recommend
    assert chain == 146 < 150


def test_basket_review_chain_and_models() -> None:
    by_id = nodes(workflow("gpos-basket-review"))
    assert by_id["note"]["input"]["model"] == "fast"
    assert by_id["stage"]["input"]["model"] == by_id["conclude"]["input"]["model"] == "planning"
    assert by_id["skip"]["input"]["model"] == by_id["fail"]["input"]["model"] == ""
    assert by_id["recommend"]["input"] == {
        "review": "{{prepare.output.mcp_structured_content.agent_input}}",
        "evidence": "{{note.output.mcp_structured_content.evidence}}"}
    assert by_id["recommend"]["when"] == (
        "'{{note.output.mcp_structured_content.status}}' == 'noted'")
    assert {f"c{n}_{k}" for n in (1, 2) for k in ("article", "reason", "holds", "numbers",
                                                   "tools")} | {"tx_status"} == set(
        by_id["gather"]["output_schema_override"]["required"])


def test_hil_timeout_default_is_the_gate_timeout() -> None:
    """11.5: HIL_TIMEOUT_S (engine) = hil.timeout "2m" of the gate and of F2."""
    app = str(ROOT / "app")
    if app not in sys.path:
        sys.path.insert(0, app)
    from gposdemo.common.config import load_settings
    from gposdemo.engine.outcome import HIL_TIMEOUT_S

    gate = load("mesh/connectors/gpos-price-gate.yaml")["spec"]["values"]["hil"]["tools"]
    f2 = load("mesh/fallback/agents/gpos-price-approver-f2.yaml")["spec"]["toolsetConfigs"][0][
        "configValues"]["hil"]["get_current_time"]
    assert gate["apply_price"]["timeout"] == f2["timeout"] == "2m"
    assert load_settings("engine", {}).hil_timeout_s == HIL_TIMEOUT_S == 2 * 60


def test_approver_answers_in_sams_order_with_the_message() -> None:
    """UC1-29: SAM's denial and timeout texts quoted exactly and checked before the
    tool's own result (SAM's result status is "error"); message is the third key."""
    prompt = load("mesh/agents/gpos-price-approver.yaml")["spec"]["systemPrompt"]
    order = [prompt.index(s) for s in (f'"{SAM_DENIED}"', f'"{SAM_TIMEOUT}"',
                                       "apply_price returned its own result",
                                       "any other error")]
    assert order == sorted(order) and "FIRST of these cases" in prompt
    assert "exactly the keys status, action_id and message" in prompt
    assert "at most 200 characters" in " ".join(prompt.split())
    for rule in ("1. Call apply_price exactly once", "4. A second call", "5. A denial"):
        assert rule in prompt                           # rules 1-5 unchanged


@pytest.mark.parametrize("root", ["mesh", "mesh/fallback"])
def test_record_passes_the_approvers_message(root: str) -> None:
    """R4 B1 and F2: record passes ``tool_message`` from the approver's output;
    record_fail (no agent output after a failure) never passes a reference."""
    by_id = nodes(workflow("gpos-price-approval", root))
    approve = by_id["approve"]["output_schema_override"]
    assert approve["properties"]["message"] == {"type": "string"}
    assert "message" in approve["required"]            # F2 too: record reads it (review)
    assert "message" in by_id["approve"]["instruction"]
    assert by_id["record"]["input"]["tool_message"] == "{{approve.output.message}}"
    assert "tool_message" not in by_id["record_fail"]["input"]
    version = workflow("gpos-price-approval", root)["spec"]["appConfig"]["version"]
    assert version == ("0.1.2" if root == "mesh" else "0.1.2-f2")


def test_approval_times_survive_a_duplicate_request() -> None:
    app = workflow("gpos-price-approval")["spec"]["appConfig"]
    approve = nodes(workflow("gpos-price-approval"))["approve"]
    hil = load("mesh/connectors/gpos-price-gate.yaml")["spec"]["values"]["hil"]["tools"]
    assert (hil["apply_price"]["timeout"], approve["timeout"], app["workflow_timeout"]) == (
        "2m", "5m", "6m")                                # A-18: 120 + 1.5 + 120 s < 300 s
    assert set(approve["input"]) == TOOL_PARAMS["apply_price"] - {"approved_at"}


def test_f2_fallback_is_the_proven_spike_agent() -> None:
    manifest = load("mesh/fallback/manifest.yaml")
    assert manifest["resources"] == {"connectors": ["gpos-price-apply"],
                                     "agents": ["gpos-price-approver-f2"],
                                     "workflows": ["gpos-price-approval"]}
    f2 = load("mesh/fallback/agents/gpos-price-approver-f2.yaml")["spec"]
    spike = load("spikes/g0/g0-09/mesh/agents/gpos-spike-p09-approver-h.yaml")["spec"]
    assert f2["systemPrompt"] == spike["systemPrompt"]
    gate, spike_gate = (s["toolsetConfigs"][0]["configValues"]["hil"]["get_current_time"]
                        for s in (f2, spike))
    assert {k: v for k, v in gate.items() if k != "approval_message"} == {
        k: v for k, v in spike_gate.items() if k != "approval_message"}
    assert gate["approval_message"] == ("Preisvorschlag der Messekasse freigeben? Details in "
                                        "der Meldung davor.")
    by_id = nodes(workflow("gpos-price-approval", "mesh/fallback"))
    assert by_id["apply"]["connector"] == "gpos-price-apply"
    assert by_id["apply"]["when"] == "'{{approve.output.status}}' == 'applied'"
    assert by_id["apply"]["input"]["approved_at"] == "{{approve.output.time}}"
    assert by_id["record"]["input"]["approved_at"] == "{{approve.output.time}}"  # 4.3
    assert by_id["record"]["depends_on"] == ["apply"]
    assert by_id["approve"]["agent_name"] == "gpos-price-approver-f2"


def test_f2_record_reads_nothing_of_apply() -> None:
    """F2 (9.9): apply is skipped after every deny; a whole-value reference to a skipped
    node arrives as null (SAM 2.542 data flow) and a str parameter rejects it, so record
    (and everything after apply) reads nothing of apply; B1 passes the agent's
    action_id."""
    by_id = nodes(workflow("gpos-price-approval", "mesh/fallback"))
    for node_id in ("record", "tell"):
        assert "apply." not in str(by_id[node_id].get("input", {})), node_id
    assert "action_id" not in by_id["record"]["input"]
    b1 = nodes(workflow("gpos-price-approval"))["record"]["input"]
    assert b1["action_id"] == "{{approve.output.action_id}}"


def test_rbac_is_a_copy_of_gate_0() -> None:
    for rel in ("manifest-rbac.yaml", "rbac/roles/gpos_marktleitung.yaml",
                "rbac/claim-mappings/keycloak-group-marktleitung.yaml"):
        assert (ROOT / "mesh" / rel).read_bytes() == (ROOT / "spikes/g0" / rel).read_bytes()
    role = load("mesh/rbac/roles/gpos_marktleitung.yaml")["spec"]
    assert role["scopes"] == ["workflow:*:invoke", "agent:*:invoke", "notify:_:send"]


def test_no_environment_placeholders_in_mesh() -> None:
    for path in (ROOT / "mesh").rglob("*"):
        if path.is_file() and ".rendered" not in path.parts:
            assert "${" not in path.read_text(encoding="utf-8"), path
