#!/usr/bin/env python3
"""Regenerate the `manifest:` block of mesh/connectors/bsg-desk-tools.yaml
from the live MCP server.

Why the connector carries a manifest at all: SAM 2.493.0 refuses a
workflow whose tool node names a tool the connector has no stored list
for, and `sam config apply` does NOT trigger live discovery -- a
connector created or updated that way keeps an empty list, so the
workflow create fails with

    node "enrich": connector "bsg-desk-tools" (type mcp) has no stored
    tool list, so the platform cannot tell which tools it serves

With a manifest the connector skips discovery and registers exactly
these tools, which also makes the apply order independent of whether
the MCP server happened to be reachable at save time. The trade is that
the block has to be regenerated whenever a tool's name or signature
changes -- that is what this script is for.

The outputSchema entries are the contract the workflow reads. A
connector-backed MCP tool's structured result is addressed as
`{{<node>.output.mcp_structured_content.<field>}}`, and only the
top-level properties declared here are verified; anything else is
reported as unverified.

Usage (with the MCP server reachable, e.g. make port-forward):

    python scripts/gen_connector_manifest.py \
        --mcp http://127.0.0.1:8765/mcp

Then `sam config apply` in mesh/ to push the updated connector.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request

HEADERS = {"Content-Type": "application/json",
           "Accept": "application/json, text/event-stream"}

# Hand-written because an MCP tool does not advertise its result shape.
# Keep in sync with app/bsgdemo/tools_server.py.
OUTPUT_SCHEMAS: dict[str, dict] = {
    # Keep this the LEAN shape (detail=false). A response over
    # mcp_tool_response_save_threshold_bytes (2048) is stored as an
    # artifact and the node's output becomes a digest, at which point
    # none of these fields resolve any more.
    "enrich_alert": {
        "type": "object",
        "properties": {
            "watch_id": {"type": "string"},
            "issuer": {"type": "string", "description": "The alerting issuer."},
            "peer_issuers": {"type": "array",
                             "description": "The two peer issuers."},
            "primary_underlying": {"type": "string"},
            "window_minutes": {"type": "number",
                               "description": "History window in minutes."},
            "statistics": {
                "type": "object",
                "description": (
                    "spread.<issuer> with mean_spread_pct_window, "
                    "mean_spread_pct_last_60s and mean_spread_pct_since_alert; "
                    "reference.<underlying> with change_pct_window and "
                    "change_pct_last_60s; news_count and "
                    "high_impact_news_last_5m."),
            },
            "alert": {"type": "object",
                      "description": "Only with detail: the alert fields given."},
            "affected_products": {"type": "array",
                                  "description": "Only with detail."},
            "datasets": {"type": "object",
                         "description": "Only with detail: rows, columns, content."},
            "attachments": {"type": "array",
                            "description": "Only with detail and ENRICH_EMBED."},
            "error": {"type": "string", "description": "Only on failure."},
            "hint": {"type": "string", "description": "Only on failure."},
        },
    },
    "publish_desk_note": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "published"},
            "topic": {"type": "string", "description": "Topic the note went to."},
            "lines": {"type": "integer",
                      "description": "Lines in the published note."},
        },
    },
}


def _post(url: str, payload: dict, sid: str | None) -> tuple[str | None, str]:
    headers = dict(HEADERS)
    if sid:
        headers["Mcp-Session-Id"] = sid
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.headers.get("Mcp-Session-Id"), resp.read().decode()


def _result(body: str) -> dict:
    for line in body.splitlines():          # streamable-http may frame as SSE
        if line.startswith("data: "):
            body = line[6:]
    return json.loads(body)["result"]


def list_tools(url: str) -> list[dict]:
    sid, _ = _post(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"protocolVersion": "2025-06-18",
                                    "capabilities": {},
                                    "clientInfo": {"name": "bsg-manifest-gen",
                                                   "version": "1"}}}, None)
    try:
        _post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    except Exception:                        # noqa: BLE001 -- 202, no body
        pass
    _, body = _post(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, sid)
    return _result(body)["tools"]


def build(tools: list[dict]) -> list[dict]:
    out = []
    for tool in sorted(tools, key=lambda t: t["name"]):
        entry = {"name": tool["name"],
                 "description": " ".join((tool.get("description") or "").split()),
                 "inputSchema": tool.get("inputSchema", {"type": "object"})}
        if tool["name"] in OUTPUT_SCHEMAS:
            entry["outputSchema"] = OUTPUT_SCHEMAS[tool["name"]]
        out.append(entry)
    missing = sorted(set(OUTPUT_SCHEMAS) - {t["name"] for t in tools})
    if missing:
        print(f"WARNING: no such tool on the server: {', '.join(missing)}",
              file=sys.stderr)
    return out


def render(entries: list[dict], indent: str = "      ") -> str:
    """A YAML block list. The runtime rejects `manifest` as a string
    ("'manifest' must be a list of tool entries, got string"), so it
    cannot be a `|` block; the nested schemas stay JSON, which is valid
    YAML flow style."""
    lines = []
    for entry in entries:
        lines.append(f"{indent}- name: {json.dumps(entry['name'])}")
        lines.append(f"{indent}  description: "
                     f"{json.dumps(entry['description'], ensure_ascii=False)}")
        for key in ("inputSchema", "outputSchema"):
            if key in entry:
                lines.append(f"{indent}  {key}: "
                             f"{json.dumps(entry[key], ensure_ascii=False)}")
    return "\n".join(lines)


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    default_target = os.path.join(here, "..", "mesh", "connectors",
                                  "bsg-desk-tools.yaml")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mcp", default="http://127.0.0.1:8765/mcp",
                    help="MCP endpoint of bsg-tools (default: %(default)s)")
    ap.add_argument("--tools-json",
                    help="Read the tools/list result from this file instead of "
                         "calling the server. Use it when no port-forward is up: "
                         "kubectl -n bsg-demo exec deploy/bsg-tools -- python "
                         "-m bsgdemo.tools_server --dump-tools > tools.json")
    ap.add_argument("--out", default=os.path.normpath(default_target),
                    help="connector YAML to rewrite (default: %(default)s)")
    args = ap.parse_args()

    if args.tools_json:
        tools = json.load(open(args.tools_json, encoding="utf-8"))
    else:
        tools = list_tools(args.mcp)
    entries = build(tools)
    text = open(args.out, encoding="utf-8").read()
    block = f"    manifest:\n{render(entries)}\n"
    if re.search(r"^    manifest:", text, re.M):
        text = re.sub(r"\n    manifest:.*\n(?:(?:      .*)?\n)*", "\n" + block,
                      text, count=1)
    else:
        text = text.rstrip("\n") + "\n" + block
    open(args.out, "w", encoding="utf-8").write(text)
    names = ", ".join(e["name"] for e in entries)
    print(f"{args.out}: {len(entries)} tools ({names})")
    print(f"  outputSchema on: "
          f"{', '.join(e['name'] for e in entries if 'outputSchema' in e)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
