"""G0-10 probe: publish to gpos/spike/p10/<rule>/... and log the SAM outputs.

  python p10_pub.py --plan q1:1,q0:1,q1:0 --count 1 --wait 20
  python p10_pub.py --plan q1:1,q0:1,own:1 --count 60 --gap 1 --wait 90
  python p10_pub.py --plan own:1 --expiry 5 --count 2 --wait 5

--plan is a list of <rule>:<mqtt qos>; MQTT QoS 1 = Solace persistent
(guaranteed), QoS 0 = Solace direct. --expiry sets the MQTT 5 message
expiry interval (= Solace message TTL). Every line is JSON with a
wall-clock timestamp; at the end a summary per rule says which seq
came back on gpos/spike/p10/out/ok/<rule> (age = arrival - ts).
Credentials: MQTT_USERNAME / MQTT_PASSWORD from the environment.
"""
import argparse
import json
import os
import sys
import time
import uuid

import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties


def log(kind, **kw):
    print(json.dumps({"t": round(time.time(), 3), "kind": kind, **kw},
                     ensure_ascii=False), flush=True)


def find_seq(o):
    if isinstance(o, dict):
        if isinstance(o.get("seq"), str):
            return o["seq"]
        o = list(o.values())
    if isinstance(o, list):
        for v in o:
            r = find_seq(v)
            if r:
                return r
    if isinstance(o, str) and '"seq"' in o:
        try:
            return find_seq(json.loads(o))
        except ValueError:
            return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default="q1:1")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--gap", type=float, default=0.0)
    ap.add_argument("--wait", type=float, default=20.0)
    ap.add_argument("--expiry", type=int, default=0)
    ap.add_argument("--tag", default="t")
    ap.add_argument("--listen-only", action="store_true")
    a = ap.parse_args()
    plan = [(p.split(":")[0], int(p.split(":")[1])) for p in a.plan.split(",")]

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5,
                    client_id=f"gpos-spike-p10-{a.tag}-{uuid.uuid4().hex[:6]}")
    c.username_pw_set(os.environ["MQTT_USERNAME"], os.environ["MQTT_PASSWORD"])
    sent, got = {}, {}

    def on_message(_c, _u, msg):
        now = time.time()
        body = msg.payload.decode("utf-8", "replace")
        try:
            body = json.loads(body)
        except ValueError:
            pass
        seq = find_seq(body)
        age = None
        if seq in sent:
            age = round(now - sent[seq]["ts"], 3)
            got.setdefault(seq, []).append(msg.topic)
        elif isinstance(body, dict) and isinstance(body.get("ts"), (int, float)):
            age = round(now - body["ts"], 3)
        log("recv", topic=msg.topic, seq=seq, age=age,
            body=body)

    c.on_message = on_message
    c.connect("localhost", 1883, keepalive=30, clean_start=True)
    c.subscribe("gpos/spike/p10/out/#", qos=1)
    c.loop_start()
    time.sleep(1.0)
    if not a.listen_only:
        for i in range(a.count):
            for rule, qos in plan:
                seq = f"{a.tag}-{rule}-qos{qos}-{i + 1}-{uuid.uuid4().hex[:4]}"
                ts = time.time()
                payload = {"seq": seq, "ts": ts, "mode": f"{rule}/qos{qos}",
                           "note": None}
                props = None
                if a.expiry:
                    props = Properties(PacketTypes.PUBLISH)
                    props.MessageExpiryInterval = a.expiry
                topic = f"gpos/spike/p10/{rule}/{a.tag}"
                info = c.publish(topic, json.dumps(payload), qos=qos,
                                 properties=props)
                if qos:
                    info.wait_for_publish(5)
                sent[seq] = {"ts": ts, "rule": rule, "qos": qos}
                log("sent", topic=topic, seq=seq, qos=qos, expiry=a.expiry or None)
            if a.gap:
                time.sleep(a.gap)
    end = time.time() + a.wait
    while time.time() < end:
        time.sleep(0.2)
    c.loop_stop()
    c.disconnect()
    summ = {}
    for seq, s in sent.items():
        k = f"{s['rule']}/qos{s['qos']}"
        e = summ.setdefault(k, {"sent": 0, "ok": 0, "dup": 0, "missing": []})
        e["sent"] += 1
        n = len([t for t in got.get(seq, []) if "/out/ok/" in t])
        if n:
            e["ok"] += 1
            e["dup"] += n - 1
        else:
            e["missing"].append(seq)
    log("summary", per_mode=summ)
    return 0


if __name__ == "__main__":
    sys.exit(main())
