"""Generate the G0-05 spike resources (prefix gpos-spike-p05) into mesh/.

Secrets never land in a file: api_key and broker credentials are
${VAR} placeholders that `sam config apply` resolves from the process
environment (run.sh exports them from the .env files).
Variant e passes the LITERAL strings ${LLM_SERVICE_ENDPOINT} and
${LLM_SERVICE_API_KEY} to the platform (via ${P05_DOLLAR} = "$") to
see whether awe resolves env placeholders in tool_config at runtime.
"""
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
MESH = HERE / "mesh"
MODEL = "claude-haiku-4-5-20251001"
# Retired 2026-11-11: variants a-d and s5 carried the real key into
# tool_config (platform API returns it). They are no longer generated;
# the last rendered copies are in ../mesh-retired/, never re-apply them.
PROMPT = (
    'Read the price tag or flyer. Answer only with JSON: {"readable": bool, '
    '"product_text": str, "pack_size": str, "price_eur": number, "unit_price": str, '
    '"valid_text": str, "confidence": number}. If the price is not clearly legible, '
    'set readable to false and price_eur to null.')

S1 = {  # variant: (model, api_base, api_key) ; None = no tool_config
    "e": (f"openai/{MODEL}", "${P05_DOLLAR}{LLM_SERVICE_ENDPOINT}",
          "${P05_DOLLAR}{LLM_SERVICE_API_KEY}"),
    "f": None,
}


def q(s):
    return json.dumps(s, ensure_ascii=False)


def tool_entry(cfg):
    out = ["      - tool_type: builtin", "        tool_name: describe_image"]
    if cfg:
        m, b, k = cfg
        out += ["        tool_config:", f"          model: {q(m)}",
                f"          api_base: {q(b)}", f"          api_key: {q(k)}"]
    return "\n".join(out)


def wf_s1(v, cfg):
    note = "no tool_config" if cfg is None else f"model={cfg[0]} api_base={cfg[1]}"
    return f"""# G0-05 S1/S3 variant {v}: describe_image as tool node, input = artifact
# attached by the entrypoint (artifactProcessing). {note}
kind: workflow
name: gpos-spike-p05-s1{v}
description: >-
  Gate 0 spike G0-05 S1 variant {v}: describe_image tool node reads the
  photo artifact that the event rule attached.
spec:
  appConfig:
    version: "0.1.0"
    workflow_timeout: "40s"
    default_node_timeout: "30s"
    fail_fast: true
    skills:
      - id: gpos_spike_p05_s1{v}
        name: G0-05 S1 {v}
        description: describe_image tool node spike (Gate 0).
    input_schema:
      type: object
      required: [scan_id, photo_name]
      properties:
        scan_id: {{type: string}}
        photo_name: {{type: string}}
        device: {{type: [string, "null"]}}
        store: {{type: [string, "null"]}}
    tools:
{tool_entry(cfg)}
    nodes:
      - id: read
        type: tool
        tool_name: describe_image
        timeout: "30s"
        input:
          input_image: "{{{{workflow.input.photo_name}}}}"
          prompt: {q(PROMPT)}
    output_mapping:
      scan_id: "{{{{workflow.input.scan_id}}}}"
      variant: "s1{v}"
      description: "{{{{read.output.description}}}}"
      image_filename: "{{{{read.output.image_filename}}}}"
      image_version: "{{{{read.output.image_version}}}}"
"""


def agent(name, inline, toolsets, prompt):
    ts = "[]" if not toolsets else "\n" + "\n".join(f"    - {t}" for t in toolsets)
    return f"""# G0-05 S3b: agent target of an event rule with artifactProcessing.
kind: agent
name: {name}
description: >-
  Gate 0 spike G0-05 S3b: reads a competitor price tag photo
  ({'inline vision' if inline else 'load_artifact'}) and answers with JSON.
spec:
  type: standard
  modelProvider:
    - fast
  toolsets: {ts}
  additionalConfigurations:
    supportsStreaming: false
    enableInlineVision: {str(inline).lower()}
  skills:
    - id: {name.replace('-', '_')}
      name: Price tag reader
      description: Reads a competitor price tag photo (Gate 0 spike).
  inputModes: [text, image]
  outputModes: [text]
  systemPrompt: |
{prompt}
"""


AG_IV = """    You read photos of competitor price tags for a German trade fair
    demo. The photo is attached to the request. Answer only with one JSON
    object: {"readable": bool, "product_text": str, "pack_size": str,
    "price_eur": number or null, "unit_price": str, "valid_text": str,
    "confidence": number}. Never guess a price. Call no tool."""
AG_LA = """    You read photos of competitor price tags for a German trade fair
    demo. The request names an image artifact. Call load_artifact exactly
    once with that filename to see the image, then answer only with one
    JSON object: {"readable": bool, "product_text": str, "pack_size": str,
    "price_eur": number or null, "unit_price": str, "valid_text": str,
    "confidence": number}. Never guess a price. Call no other tool."""


def main():
    for d in ("workflows", "agents", "connectors"):
        (MESH / d).mkdir(parents=True, exist_ok=True)
    names = []
    for v, cfg in S1.items():
        (MESH / "workflows" / f"gpos-spike-p05-s1{v}.yaml").write_text(wf_s1(v, cfg))
        names.append(f"gpos-spike-p05-s1{v}")
    (MESH / "agents" / "gpos-spike-p05-scout.yaml").write_text(
        agent("gpos-spike-p05-scout", True, [], AG_IV))
    (MESH / "agents" / "gpos-spike-p05-scout-la.yaml").write_text(
        agent("gpos-spike-p05-scout-la", False, ["artifact_management"], AG_LA))
    print("workflows:", names)


if __name__ == "__main__":
    main()
