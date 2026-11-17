"""G0-09 Part B cross-check from the awe log (kubectl logs, JSON lines).

For every execution of the given workflow (agentName workflow_...) it
counts, inside the execution window, the gated tool executions
(get_current_time, approvalReason human) and HIL NotifyRequests (mode
input) of the given approver agent, plus structured-output retries of
the node 'apply'. Sequential runs only (attribution by time window).

  kubectl -n sam-solace-lab logs deploy/agent-mesh-solace-agent-mesh-awe \
      --since=30m > awe.log
  python p09_awe_count.py awe.log <workflow_agentName> <approver_agentName>
"""
import collections
import json
import sys


def main():
    path, wf, ag = sys.argv[1:4]
    L = []
    for line in open(path, encoding="utf-8"):
        try:
            L.append(json.loads(line))
        except ValueError:
            pass
    ex = {}
    for d in L:
        if d.get("agentName") != wf:
            continue
        t = d.get("traceID")
        if d.get("message") == "starting workflow execution":
            ex[t] = {"start": d["timestamp"], "end": None, "ok": None}
        elif t in ex and d.get("message", "").startswith("workflow completed"):
            ex[t]["end"], ex[t]["ok"] = d["timestamp"], True
        elif t in ex and "fail" in d.get("message", "").lower() and ex[t]["end"] is None:
            ex[t]["end"], ex[t]["ok"] = d["timestamp"], False
    dist = collections.Counter()
    rows = []
    for t, e in sorted(ex.items(), key=lambda kv: kv[1]["start"]):
        if not e["end"]:
            continue
        win = [d for d in L if e["start"] <= d["timestamp"] <= e["end"]]
        tools = sum(1 for d in win if d.get("agentName") == ag
                    and d.get("message") == "tool execution succeeded"
                    and d.get("tool") == "get_current_time")
        reqs = sum(1 for d in win if d.get("agentName") == ag
                   and d.get("message") == "notify: published NotifyRequest"
                   and d.get("mode") == "input")
        retries = sum(1 for d in win if d.get("traceID") == t
                      and "structured invocation retry" in d.get("message", ""))
        dist[(tools, reqs, retries)] += 1
        rows.append({"start": e["start"][11:23], "tool_exec": tools,
                     "hil_requests": reqs, "retries": retries, "ok": e["ok"]})
    for r in rows:
        if r["tool_exec"] != 1 or r["hil_requests"] != 1 or r["retries"]:
            print(json.dumps(r))
    print(json.dumps({"summary": True, "executions": len(rows),
                      "dist_tool_req_retry": {str(k): v for k, v in dist.items()},
                      "tool_exec_total": sum(r["tool_exec"] for r in rows),
                      "hil_requests_total": sum(r["hil_requests"] for r in rows)}))


if __name__ == "__main__":
    sys.exit(main())
