"""G0-02 B1 series via the notify REST API (answering as an admin).

Sends events on gpos/spike/hil/b1/<tag>, waits for the approval items
in marktleitung's inbox (GET /api/v1/notify/inbox?userId=...), answers
them (approve/deny, optionally shuffled) and records the run results on
gpos/spike/out/#. Prints one JSON summary line per run plus totals.

  python hitl_api_test.py --tag t2 --count 5 --mode seq --answer approve
  python hitl_api_test.py --tag t10 --count 5 --mode parallel --shuffle
  python hitl_api_test.py --tag t3 --count 1 --answer deny

Needs: MQTT_USERNAME/MQTT_PASSWORD (VPN default), SAM_AUTH_TOKEN and
SAM_CLI (exported by agent-mesh-deployment/scripts/lib/common.sh).
"""
import argparse
import json
import os
import random
import subprocess
import sys
import time
import uuid

import paho.mqtt.client as mqtt

USER = "marktleitung@solace.lab"


def sam_api(method, path, body=None):
    cmd = [os.environ["SAM_CLI"], "api", "-X", method, path]
    if body is not None:
        cmd += ["--input", "-"]
    p = subprocess.run(cmd, input=json.dumps(body) if body is not None else None,
                       capture_output=True, text=True, timeout=30)
    raw = "".join(l for l in p.stdout.splitlines(True)
                  if l.lstrip().startswith(("{", "[")))
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {"_raw": p.stdout[-300:], "_err": p.stderr[-300:]}


def pending_items():
    d = sam_api("GET", f"/api/v1/notify/inbox?userId={USER}&category=hil")
    items = d.get("data") if isinstance(d, dict) else d
    if isinstance(items, dict):
        items = items.get("items")
    return [i for i in (items or []) if i.get("promptState") == "pending"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--mode", choices=["seq", "parallel"], default="seq")
    ap.add_argument("--answer", choices=["approve", "deny"], default="approve")
    ap.add_argument("--shuffle", action="store_true")
    ap.add_argument("--result-wait", type=float, default=40)
    a = ap.parse_args()

    results = {}
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"gpos-g0-hitl-{uuid.uuid4().hex[:8]}")
    c.username_pw_set(os.environ["MQTT_USERNAME"], os.environ["MQTT_PASSWORD"])

    def on_message(_c, _u, msg):
        try:
            body = json.loads(msg.payload.decode())
        except ValueError:
            body = {"raw": msg.payload.decode("utf-8", "replace")}
        results.setdefault("_all", []).append(
            {"t": time.time(), "topic": msg.topic, "body": body})

    c.on_message = on_message
    c.connect("localhost", 1883, keepalive=30)
    c.subscribe("gpos/spike/out/#", qos=1)
    c.loop_start()
    time.sleep(1.0)
    known = {i["id"] for i in pending_items()}
    runs = []

    def send(i):
        seq = f"{a.tag}-{i + 1}-{uuid.uuid4().hex[:6]}"
        c.publish(f"gpos/spike/hil/b1/{a.tag}", json.dumps({"seq": seq}),
                  qos=1).wait_for_publish(5)
        return {"seq": seq, "sent": time.time()}

    def got(run):
        return [r for r in results.get("_all", []) if run["seq"] in json.dumps(r["body"])]

    approvals = []

    def drain(deadline, want_done):
        # answer every new pending approval until the runs we wait for are done
        while time.time() < deadline:
            pend = [i for i in pending_items() if i["id"] not in known]
            if a.shuffle:
                random.shuffle(pend)
            for it in pend:
                known.add(it["id"])
                t = time.time()
                r = sam_api("POST", f"/api/v1/notify/inbox/{it['id']}/respond?userId={USER}",
                            {"status": "answered", "data": {"approved": a.answer == "approve"}})
                approvals.append({"id": it["id"], "createdAt": it.get("createdAt"),
                                  "answered": t, "respond_ok": not (r or {}).get("errorType")})
            if all(got(r) for r in want_done):
                return
            time.sleep(0.3)

    if a.mode == "seq":
        for i in range(a.count):
            run = send(i)
            runs.append(run)
            drain(time.time() + a.result_wait, [run])
    else:
        for i in range(a.count):
            runs.append(send(i))
        drain(time.time() + a.result_wait + 20, runs)

    time.sleep(2)
    c.loop_stop()
    c.disconnect()
    allres = results.get("_all", [])
    for run in runs:
        res = got(run)
        print(json.dumps({"seq": run["seq"],
                          "event_to_result_s": round(res[0]["t"] - run["sent"], 2) if res else None,
                          "result_topic": res[0]["topic"] if res else None,
                          "result": res[0]["body"] if res else None,
                          "results": len(res)}, ensure_ascii=False), flush=True)
    print(json.dumps({"summary": True, "runs": len(runs), "approvals_answered": len(approvals),
                      "duplicate_requests": max(0, len(approvals) - len(runs)),
                      "ok": sum(1 for r in allres if r["topic"].endswith("/ok")),
                      "err": sum(1 for r in allres if r["topic"].endswith("/err"))}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
