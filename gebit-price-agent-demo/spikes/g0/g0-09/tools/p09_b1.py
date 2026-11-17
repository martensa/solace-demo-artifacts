"""G0-09 Part B: duplicate gated calls of variant B1 (sequential runs).

Sends events on gpos/spike/p09/<rule>/<tag> one after the other. For each
run it polls marktleitung's HIL inbox and approves every NEW pending item
whose A2UI 'info' text names exactly OUR agent (Agent "<agent>" wants to
run tool ...); items of other spikes are never touched. Records per run:
number of approval requests, their createdAt (server clock), detection
and answer times, event -> first request, last approval -> result and
event -> result. One JSON line per run plus a summary line.

  python p09_b1.py --rule b1  --agent gpos-spike-p09-approver   --count 50 --out x.jsonl
  python p09_b1.py --rule b1h --agent gpos-spike-p09-approver-h --count 30 --out y.jsonl

Needs MQTT_USERNAME / MQTT_PASSWORD (VPN default) and SAM_CLI /
SAM_AUTH_TOKEN (agent-mesh-deployment/scripts/lib/common.sh).
"""
import argparse
import datetime as dt
import json
import os
import statistics
import subprocess
import sys
import time
import uuid

import paho.mqtt.client as mqtt

USER = "marktleitung@solace.lab"


class AuthError(RuntimeError):
    pass


def sam_api(method, path, body=None):
    cmd = [os.environ["SAM_CLI"], "api", "-X", method, path]
    if body is not None:
        cmd += ["--input", "-"]
    p = subprocess.run(cmd, input=json.dumps(body) if body is not None else None,
                       capture_output=True, text=True, timeout=30)
    blob = p.stdout + p.stderr
    if "401" in blob and ("Unauthorized" in blob or "Not authenticated" in blob):
        raise AuthError(blob[-300:])
    if "Not authenticated" in blob:
        raise AuthError(blob[-300:])
    raw = "".join(l for l in p.stdout.splitlines(True)
                  if l.lstrip().startswith(("{", "[")))
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {"_raw": p.stdout[-300:], "_err": p.stderr[-300:]}


def info_text(item):
    for comp in (item.get("surface") or {}).get("components", []):
        if comp.get("id") == "info":
            return ((comp.get("text") or {}).get("literalString")) or ""
    return ""


def iso(s):
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def pct(vals, p):
    s = sorted(vals)
    k = (len(s) - 1) * p
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[f] + (s[c] - s[f]) * (k - f), 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", required=True)
    ap.add_argument("--agent", required=True)
    ap.add_argument("--tag", default="r")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--result-wait", type=float, default=90)
    ap.add_argument("--late-wait", type=float, default=2.0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    marker = f'Agent "{a.agent}" wants to run tool'

    box = []
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"gpos-p09-b-{uuid.uuid4().hex[:8]}")
    c.username_pw_set(os.environ["MQTT_USERNAME"], os.environ["MQTT_PASSWORD"])
    c.on_message = lambda _c, _u, m: box.append((time.time(), m.topic, bytes(m.payload)))
    c.connect("localhost", 1883, keepalive=30)
    c.subscribe("gpos/spike/p09/out/#", qos=1)
    c.loop_start()
    time.sleep(1.0)

    def inbox():
        d = sam_api("GET", f"/api/v1/notify/inbox?userId={USER}&category=hil&pageSize=50")
        items = d.get("data") if isinstance(d, dict) else d
        return items or []

    seen = {i["id"] for i in inbox()}          # everything that existed before
    foreign_seen = set()
    rows = []

    def poll_and_answer(reqs):
        for it in inbox():
            if it["id"] in seen:
                continue
            if marker not in info_text(it):
                if it["id"] not in foreign_seen:
                    foreign_seen.add(it["id"])   # other spike: leave it alone
                continue
            if it.get("promptState") != "pending":
                continue
            seen.add(it["id"])
            t_det = time.time()
            r = sam_api("POST", f"/api/v1/notify/inbox/{it['id']}/respond?userId={USER}",
                        {"status": "answered", "data": {"approved": True}})
            reqs.append({"id": it["id"], "createdAt": it.get("createdAt"),
                         "detected": t_det, "answered": time.time(),
                         "respond_ok": not (r or {}).get("errorType"),
                         "respond_err": (r or {}).get("errorType")})

    def result_for(seq):
        for t, topic, raw in list(box):
            if seq.encode() in raw:
                return t, topic, raw
        return None

    with open(a.out, "a", encoding="utf-8") as fo:
        for i in range(a.count):
            seq = f"p09-{a.rule}-{a.tag}-{i + 1}-{uuid.uuid4().hex[:6]}"
            reqs = []
            t0 = time.time()
            c.publish(f"gpos/spike/p09/{a.rule}/{a.tag}", json.dumps({"seq": seq}),
                      qos=1).wait_for_publish(5)
            hit = None
            try:
                while time.time() - t0 < a.result_wait:
                    poll_and_answer(reqs)
                    hit = result_for(seq)
                    if hit:
                        break
                    time.sleep(0.2)
                late_until = time.time() + a.late_wait
                n_before = len(reqs)
                while time.time() < late_until:
                    poll_and_answer(reqs)
                    time.sleep(0.3)
            except AuthError as e:
                print(json.dumps({"auth_error": str(e)}), flush=True)
                fo.write(json.dumps({"seq": seq, "auth_error": True}) + "\n")
                break
            body = None
            if hit:
                try:
                    body = json.loads(hit[2].decode("utf-8"))
                except ValueError:
                    body = {"raw": hit[2][:200].decode("utf-8", "replace")}
            created = [iso(r["createdAt"]) for r in reqs]
            kind = None
            if len(reqs) > 1 and created[0] and created[1]:
                gap = created[1] - created[0]
                # sequential = second request created after the first was answered
                kind = "sequential" if gap > (reqs[0]["answered"] - reqs[0]["detected"]) + 0.3 \
                    and created[1] > created[0] + 0.8 else "parallel"
            row = {"seq": seq, "rule": a.rule, "requests": len(reqs),
                   "late_requests": len(reqs) - n_before,
                   "dup_kind": kind,
                   "created_gap_s": round(created[1] - created[0], 3)
                   if len(reqs) > 1 and created[0] and created[1] else None,
                   "event_to_first_request_s": round(reqs[0]["detected"] - t0, 3) if reqs else None,
                   "approve_to_result_s": round(hit[0] - max(
                       r["answered"] for r in reqs if r["answered"] < hit[0]), 3)
                   if hit and any(r["answered"] < hit[0] for r in reqs) else None,
                   "event_to_result_s": round(hit[0] - t0, 3) if hit else None,
                   "result_topic": hit[1] if hit else None,
                   "status": ((body or {}).get("result") or body or {}).get("status")
                   if isinstance(body, dict) else None,
                   "respond_ok": all(r["respond_ok"] for r in reqs),
                   "req": [{"createdAt": r["createdAt"],
                            "det_s": round(r["detected"] - t0, 3),
                            "ans_s": round(r["answered"] - t0, 3)} for r in reqs]}
            if body and not row["status"] and isinstance(body, dict):
                row["body"] = body
            rows.append(row)
            fo.write(json.dumps(row, ensure_ascii=False) + "\n")
            fo.flush()
            print(json.dumps(row, ensure_ascii=False), flush=True)
    c.loop_stop()
    c.disconnect()
    done = [r for r in rows if r["event_to_result_s"] is not None]
    e2r = [r["event_to_result_s"] for r in done]
    e2i = [r["event_to_first_request_s"] for r in rows if r["event_to_first_request_s"]]
    a2r = [r["approve_to_result_s"] for r in rows if r["approve_to_result_s"] is not None]
    summ = {"summary": True, "rule": a.rule, "agent": a.agent, "runs": len(rows),
            "results": len(done),
            "ok": sum(1 for r in done if (r["result_topic"] or "").endswith("/ok")),
            "applied": sum(1 for r in rows if r["status"] == "applied"),
            "requests_total": sum(r["requests"] for r in rows),
            "runs_with_duplicate": sum(1 for r in rows if r["requests"] > 1),
            "runs_without_request": sum(1 for r in rows if r["requests"] == 0),
            "dup_kinds": [r["dup_kind"] for r in rows if r["dup_kind"]],
            "requests_per_run": round(sum(r["requests"] for r in rows) / len(rows), 3)
            if rows else None,
            "foreign_items_ignored": len(foreign_seen),
            "event_to_request_p50": round(statistics.median(e2i), 2) if e2i else None,
            "event_to_request_p90": pct(e2i, 0.9) if e2i else None,
            "approve_to_result_p50": round(statistics.median(a2r), 2) if a2r else None,
            "approve_to_result_p90": pct(a2r, 0.9) if a2r else None,
            "event_to_result_p50": round(statistics.median(e2r), 2) if e2r else None,
            "event_to_result_p90": pct(e2r, 0.9) if e2r else None,
            "event_to_result_max": max(e2r) if e2r else None}
    print(json.dumps(summ), flush=True)
    with open(a.out, "a", encoding="utf-8") as fo:
        fo.write(json.dumps(summ) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
