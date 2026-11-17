#!/usr/bin/env python3
"""Write the `manifest:` block of mesh/connectors/gpos-spike-p01-tools.yaml
from the stub's own tool list (pattern: bsg-trading-desk-demo
scripts/gen_connector_manifest.py, plan 3.7 scripts/gen_connector_manifest.py).

A connector applied with `sam config apply` keeps no tool list unless it
carries a manifest; workflow tool nodes then cannot bind. The manifest is
a YAML block list with JSON flow for the schemas (a `|` string is refused).

  kubectl -n gpos-g0 exec deploy/gpos-spike-p01-stub -- \
      python /app/stub_server.py --dump-tools > tools.json
  python gen_connector_manifest.py --tools-json tools.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys


def render(tools: list[dict], indent: str = "      ") -> str:
    lines = []
    for t in sorted(tools, key=lambda x: x["name"]):
        lines.append(f"{indent}- name: {json.dumps(t['name'])}")
        desc = " ".join((t.get("description") or "").split())
        lines.append(f"{indent}  description: {json.dumps(desc, ensure_ascii=False)}")
        lines.append(f"{indent}  inputSchema: "
                     f"{json.dumps(t.get('inputSchema') or {'type': 'object'}, ensure_ascii=False)}")
        if t.get("outputSchema"):
            lines.append(f"{indent}  outputSchema: "
                         f"{json.dumps(t['outputSchema'], ensure_ascii=False)}")
    return "\n".join(lines)


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tools-json", required=True)
    ap.add_argument("--out", default=os.path.normpath(os.path.join(
        here, "..", "mesh", "connectors", "gpos-spike-p01-tools.yaml")))
    a = ap.parse_args()
    tools = json.load(open(a.tools_json, encoding="utf-8"))
    text = open(a.out, encoding="utf-8").read()
    block = f"    manifest:\n{render(tools)}\n"
    if re.search(r"^    manifest:", text, re.M):
        text = re.sub(r"\n    manifest:.*\n(?:(?:      .*)?\n)*", "\n" + block, text, count=1)
    else:
        text = text.rstrip("\n") + "\n" + block
    open(a.out, "w", encoding="utf-8").write(text)
    print(f"{a.out}: {len(tools)} tools "
          f"({', '.join(sorted(t['name'] for t in tools))}); outputSchema on "
          f"{sum(1 for t in tools if t.get('outputSchema'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
