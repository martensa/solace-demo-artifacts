"""G0-01: publish the generated events and time each run.

  set -a; . bsg-trading-desk-demo/.env; set +a
  python send_events.py --events <scratchpad>/g0-01/events.jsonl \
      --log <out.jsonl> [--mode serial|burst] [--gap 0.5]

Publishes every payload byte-exact (QoS 1) on its topic and listens on
gpos/spike/p01/out/#. A reply is matched by event_key
(purchaseTransactionId:offset). Per event it logs the send time, the
reply time, the duration, and whether the stub's sha256 of the
canonical JSON it received equals the sha256 of what was sent
(= JSON-equal including '@type').
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
import uuid

import paho.mqtt.client as mqtt


def canon_sha(payload: str) -> str:
    obj = json.loads(payload)
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--mode", default="serial", choices=["serial", "burst"])
    ap.add_argument("--gap", type=float, default=0.5)
    ap.add_argument("--timeout", type=float, default=40.0)
    ap.add_argument("--only", default="", help="comma list of seq to send")
    a = ap.parse_args()
    events = [json.loads(line) for line in open(a.events, encoding="utf-8")]
    if a.only:
        keep = set(a.only.split(","))
        events = [e for e in events if e["seq"] in keep]
    for e in events:
        ev = json.loads(e["payload"])
        e["event_key"] = f"{ev['purchaseTransactionId']}:{ev['metadata']['offset']}"
        e["sha"] = canon_sha(e["payload"])
    by_key = {e["event_key"]: e for e in events}
    replies: dict[str, dict] = {}
    cond = threading.Condition()
    out = open(a.log, "a", encoding="utf-8")

    def log(kind: str, **kw) -> None:
        out.write(json.dumps({"t": round(time.time(), 3), "kind": kind, **kw},
                             ensure_ascii=False) + "\n")
        out.flush()

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"gpos-spike-p01-send-{uuid.uuid4().hex[:6]}")
    c.username_pw_set(os.environ["MQTT_USERNAME"], os.environ["MQTT_PASSWORD"])

    def on_message(_c, _u, msg):
        t = time.time()
        body = msg.payload.decode("utf-8", "replace")
        try:
            data = json.loads(body)
        except ValueError:
            data = {"_raw": body}
        key = data.get("event_key", "") if isinstance(data, dict) else ""
        log("recv", topic=msg.topic, key=key, body=data)
        with cond:
            replies.setdefault(key or f"_unmatched_{len(replies)}",
                               {"t": t, "topic": msg.topic, "body": data})
            cond.notify_all()

    c.on_message = on_message
    c.connect(a.host, a.port, keepalive=30)
    c.subscribe("gpos/spike/p01/out/#", qos=1)
    c.loop_start()
    time.sleep(1.0)
    sent: dict[str, float] = {}
    for e in events:
        t0 = time.time()
        c.publish(e["topic"], e["payload"].encode("utf-8"), qos=1).wait_for_publish(5)
        sent[e["event_key"]] = t0
        log("sent", seq=e["seq"], topic=e["topic"], key=e["event_key"], bytes=e["bytes"],
            sha=e["sha"])
        if a.mode == "serial":
            with cond:
                cond.wait_for(lambda: e["event_key"] in replies, timeout=a.timeout)
            time.sleep(a.gap)
    deadline = time.time() + a.timeout
    with cond:
        cond.wait_for(lambda: all(k in replies for k in sent),
                      timeout=max(0.0, deadline - time.time()))
    c.loop_stop()
    c.disconnect()
    ok = 0
    print(f"{'seq':7} {'event':26} {'B':>5} {'verdict':14} {'dur_s':>6} sha_eq topic")
    for e in events:
        r = replies.get(e["event_key"])
        if not r:
            print(f"{e['seq']:7} {e['event']:26} {e['bytes']:5d} {'NO REPLY':14}")
            log("summary", seq=e["seq"], key=e["event_key"], reply=False)
            continue
        b = r["body"] if isinstance(r["body"], dict) else {}
        dur = r["t"] - sent[e["event_key"]]
        eq = b.get("raw_sha256") == e["sha"]
        ok += eq
        print(f"{e['seq']:7} {e['event']:26} {e['bytes']:5d} {str(b.get('verdict')):14} "
              f"{dur:6.2f} {eq!s:6} {r['topic']}")
        log("summary", seq=e["seq"], key=e["event_key"], reply=True, topic=r["topic"],
            duration_s=round(dur, 3), sha_equal=eq, verdict=b.get("verdict"),
            run_id=b.get("run_id"), raw_bytes=b.get("raw_bytes"))
    print(f"JSON-equal {ok}/{len(events)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
