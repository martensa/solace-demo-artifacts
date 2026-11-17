"""G0-09 Part A2: compare the writer text that came back over MQTT with
the notify_user item SAM stored for marktleitung (notify REST API).

  python p09_notify_check.py ../logs/g0-09-a2.jsonl

Needs SAM_CLI / SAM_AUTH_TOKEN (agent-mesh-deployment/scripts/lib/common.sh).
"""
import json
import os
import subprocess
import sys

USER = "marktleitung@solace.lab"


def main():
    rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
    rows = [r for r in rows if not r.get("summary") and r.get("fields")]
    p = subprocess.run([os.environ["SAM_CLI"], "api", "-X", "GET",
                        f"/api/v1/notify/inbox?userId={USER}&pageSize=100"],
                       capture_output=True, text=True, timeout=30)
    raw = "".join(l for l in p.stdout.splitlines(True) if l.lstrip().startswith("{"))
    items = json.loads(raw).get("data") or []
    ok = 0
    for r in rows:
        f = r["fields"]
        want_t = f"G0-09 {r['seq']}: {f['headline']}"
        want_b = f"{f['rationale']} | {f['why_line']}"
        hit = [i for i in items if r["seq"] in (i.get("title") or "")]
        same = bool(hit) and hit[0].get("title") == want_t and hit[0].get("body") == want_b
        ok += same
        print(json.dumps({"seq": r["seq"], "found": bool(hit),
                          "category": hit[0].get("category") if hit else None,
                          "title_equal": bool(hit) and hit[0].get("title") == want_t,
                          "body_equal": bool(hit) and hit[0].get("body") == want_b,
                          "title": hit[0].get("title") if hit else None},
                         ensure_ascii=False))
    print(json.dumps({"summary": True, "runs": len(rows), "byte_equal": ok}))


if __name__ == "__main__":
    sys.exit(main())
