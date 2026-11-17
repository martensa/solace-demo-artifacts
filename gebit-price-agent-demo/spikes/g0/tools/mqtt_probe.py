"""Gate 0 probe: publish spike events over MQTT and log replies.

Usage (scratch venv with paho-mqtt 2.x):
  python mqtt_probe.py --topic gpos/spike/hil/a/t2 --count 1 --wait 60
  python mqtt_probe.py --listen-only --sub 'gpos/spike/out/#' --wait 300

Credentials: MQTT_USERNAME / MQTT_PASSWORD from the environment
(bsg-trading-desk-demo/.env, VPN default). Every line printed is
JSON with a wall-clock timestamp, so runs can be timed afterwards.
"""
import argparse
import json
import os
import sys
import time
import uuid

import paho.mqtt.client as mqtt


def log(kind, **kw):
    print(json.dumps({"t": round(time.time(), 3), "kind": kind, **kw},
                     ensure_ascii=False), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--topic", default="gpos/spike/hil/a/probe")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--gap", type=float, default=0.0)
    ap.add_argument("--sub", action="append", default=[])
    ap.add_argument("--wait", type=float, default=30.0)
    ap.add_argument("--listen-only", action="store_true")
    ap.add_argument("--note", default="")
    a = ap.parse_args()
    subs = a.sub or ["gpos/spike/out/#"]

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"gpos-g0-probe-{uuid.uuid4().hex[:8]}")
    c.username_pw_set(os.environ["MQTT_USERNAME"], os.environ["MQTT_PASSWORD"])

    def on_message(_c, _u, msg):
        body = msg.payload.decode("utf-8", "replace")
        try:
            body = json.loads(body)
        except ValueError:
            pass
        log("recv", topic=msg.topic, body=body)

    c.on_message = on_message
    c.connect(a.host, a.port, keepalive=30)
    for s in subs:
        c.subscribe(s, qos=1)
    c.loop_start()
    time.sleep(1.0)
    if not a.listen_only:
        for i in range(a.count):
            seq = f"{a.topic.rsplit('/', 1)[-1]}-{i + 1}-{uuid.uuid4().hex[:6]}"
            payload = {"seq": seq, "note": a.note or None}
            c.publish(a.topic, json.dumps(payload), qos=1).wait_for_publish(5)
            log("sent", topic=a.topic, seq=seq)
            if a.gap:
                time.sleep(a.gap)
    end = time.time() + a.wait
    while time.time() < end:
        time.sleep(0.2)
    c.loop_stop()
    c.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
