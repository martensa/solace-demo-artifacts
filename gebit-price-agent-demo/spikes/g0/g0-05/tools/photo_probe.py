"""G0-05 probe: publish photo events over MQTT, time the replies.

Usage (scratch venv with paho-mqtt 2.x, MQTT_USERNAME/MQTT_PASSWORD
from bsg-trading-desk-demo/.env in the environment):
  python photo_probe.py --rule s1/a --img ../img/competitor_tag.jpg
  python photo_probe.py --rule s5 --scan s5-1-competitor_tag --no-photo

Event shape (Plan 3.2 R2):
  {"meta": {"scan_id", "photo_name", "device", "store"},
   "photo": {"name", "mime", "data": <base64>}}
--no-photo sends {"scan_id": ...} only (S5, fallback A2b).
Every line printed is JSON with a wall-clock timestamp; the reply line
carries dt = seconds from publish to reply.
"""
import argparse
import base64
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
    ap.add_argument("--rule", required=True, help="topic part after gpos/spike/p05/")
    ap.add_argument("--img", default="")
    ap.add_argument("--scan", default="")
    ap.add_argument("--no-photo", action="store_true")
    ap.add_argument("--prefix", default="", help='filename prefix, e.g. "user:"')
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--wait", type=float, default=60.0)
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    a = ap.parse_args()

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"gpos-p05-probe-{uuid.uuid4().hex[:8]}")
    c.username_pw_set(os.environ["MQTT_USERNAME"], os.environ["MQTT_PASSWORD"])
    sent = {}
    got = []

    def on_message(_c, _u, msg):
        body = msg.payload.decode("utf-8", "replace")
        try:
            body = json.loads(body)
        except ValueError:
            pass
        now = time.time()
        txt = json.dumps(body, ensure_ascii=False)
        sid = next((s for s in sent if s in txt), None)
        if sid is None and sent:  # sequential sends: the reply belongs to the last one
            sid = list(sent)[-1]
        dt = round(now - sent[sid], 2) if sid else None
        got.append(sid)
        log("recv", topic=msg.topic, scan_id=sid, dt=dt, body=body)

    c.on_message = on_message
    c.connect(a.host, a.port, keepalive=30)
    rn = a.rule.replace("/", "")  # rule name = topic part without slashes
    c.subscribe(f"gpos/spike/p05/out/ok/{rn}", qos=1)
    c.subscribe(f"gpos/spike/p05/out/err/{rn}", qos=1)
    c.loop_start()
    time.sleep(1.0)
    raw = open(a.img, "rb").read() if a.img else b""
    for i in range(a.count):
        sid = a.scan or f"{a.rule.replace('/', '')}-{i + 1}-{uuid.uuid4().hex[:6]}"
        if a.count > 1 and a.scan:
            sid = f"{a.scan}-{i + 1}-{uuid.uuid4().hex[:4]}"
        if a.no_photo:
            payload = {"scan_id": sid}
        else:
            name = (f"{a.prefix}cp-{sid}.jpg" if a.img.endswith(".jpg")
                    else f"{a.prefix}cp-{sid}.png")
            mime = "image/jpeg" if name.endswith(".jpg") else "image/png"
            payload = {"meta": {"scan_id": sid, "photo_name": name, "device": "tablet-01",
                                "store": "101"},
                       "photo": {"name": name, "mime": mime,
                                 "data": base64.b64encode(raw).decode()}}
        body = json.dumps(payload)
        topic = f"gpos/spike/p05/{a.rule}/{sid}"
        sent[sid] = time.time()
        c.publish(topic, body, qos=1).wait_for_publish(10)
        log("sent", topic=topic, scan_id=sid, img=os.path.basename(a.img),
            img_bytes=len(raw), payload_bytes=len(body))
        # wait for this reply before the next send (sequential latency)
        end = time.time() + a.wait
        while time.time() < end and sid not in got:
            time.sleep(0.1)
    end = time.time() + 2
    while time.time() < end:
        time.sleep(0.1)
    c.loop_stop()
    c.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
