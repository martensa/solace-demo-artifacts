"""Measure the FULL CallToolResult of every stub tool on the max cases.

Calls the MCP endpoint over streamable-http (JSON-RPC, like SAM) and
reports, per tool:
  wire    bytes of the JSON-RPC response body as sent by the server
  result  bytes of the `result` object (content + structuredContent +
          isError + resultType), compact JSON, UTF-8  <- plan limit 1800
  struct  bytes of structuredContent alone, compact JSON, UTF-8
  text    bytes of the text content alone, UTF-8
  agent   bytes of writer_input / agent_input (plan limit 600)

  python measure_sizes.py --mcp http://127.0.0.1:8765/mcp [--label sdk/plan]
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request

H = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

# A TR2 PositionAdded and a card event, reduced to what assess_event reads,
# plus the max values (umlauts, long ids). Synthetic, no GEBIT sample data.
RAW_TR2 = json.dumps({
    "@type": "type.googleapis.com/de.gebit.rp.purchase.purchase.v2.event.PositionAdded",
    "purchaseTransactionId": "8f0c2a4e-1b7d-4c55-9a43-2f1e6b0d9c11",
    "metadata": {"offset": "12"}, "articleNumber": "article030",
    "description": "Kaffeepads Röstung „Würzig“ 36 Stück"}, ensure_ascii=False)
RAW_CARD = json.dumps({
    "@type": "type.googleapis.com/de.gebit.rp.purchase.purchase.v2.event."
             "LoyaltyMembershipAssigned",
    "purchaseTransactionId": "8f0c2a4e-1b7d-4c55-9a43-2f1e6b0d9c11",
    "metadata": {"offset": "13"}}, ensure_ascii=False)
RUN_ID = "gdk-task-0123456789abcdef0123456789abcdef"

CASES = [
    ("assess_event", "TR2", {"raw": RAW_TR2, "run_id": RUN_ID}),
    ("assess_event", "card", {"raw": RAW_CARD, "run_id": RUN_ID}),
    ("prepare_proposal", "TR2 2 slots",
     {"trigger_id": "TR2-8f0c2a4e-12", "run_id": RUN_ID}),
    ("get_offers", "card 4 offers",
     {"tx_id": "8f0c2a4e-1b7d-4c55-9a43-2f1e6b0d9c11", "member_ref": "M-0001",
      "run_id": RUN_ID}),
    ("note_event", "default",
     {"event_key": "8f0c2a4e-1b7d-4c55-9a43-2f1e6b0d9c11:14", "verdict": "none",
      "run_id": RUN_ID}),
]


def post(url: str, payload: dict) -> bytes:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=H)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read()


def call(url: str, tool: str, args: dict) -> tuple[bytes, dict]:
    body = post(url, {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                      "params": {"name": tool, "arguments": args}})
    text = body.decode()
    for line in text.splitlines():           # SSE framing, if any
        if line.startswith("data: "):
            text = line[6:]
    return body, json.loads(text)["result"]


def nbytes(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mcp", default="http://127.0.0.1:8765/mcp")
    ap.add_argument("--label", default="")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    post(a.mcp, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                            "clientInfo": {"name": "g0-01-measure", "version": "1"}}})
    rows = []
    for tool, case, args in CASES:
        wire, res = call(a.mcp, tool, args)
        sc = res.get("structuredContent") or {}
        text = "".join(c.get("text", "") for c in res.get("content", []))
        agent = sc.get("writer_input") or sc.get("agent_input") or ""
        rows.append({"label": a.label, "tool": tool, "case": case, "wire": len(wire),
                     "result": nbytes(res), "struct": nbytes(sc),
                     "text": len(text.encode()), "agent": len(agent.encode()),
                     "ok_1800": nbytes(res) <= 1800, "isError": res.get("isError")})
    if a.json:
        print(json.dumps(rows, ensure_ascii=False))
        return 0
    print(f"{'label':14} {'tool':17} {'case':14} {'wire':>5} {'result':>6} "
          f"{'struct':>6} {'text':>5} {'agent':>5} <=1800")
    for r in rows:
        print(f"{r['label']:14} {r['tool']:17} {r['case']:14} {r['wire']:5d} "
              f"{r['result']:6d} {r['struct']:6d} {r['text']:5d} {r['agent']:5d} "
              f"{'yes' if r['ok_1800'] else 'NO'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
