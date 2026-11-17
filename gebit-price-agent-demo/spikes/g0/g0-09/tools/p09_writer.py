"""G0-09 Part A: writer agent latency and umlauts.

Publishes N events (sequentially) on gpos/spike/p09/write/<tag> with a
writer_input from data/writer_inputs.json (alternating), waits for the
workflow result on gpos/spike/p09/out/# and checks every output field:
strict UTF-8 decode of the raw MQTT bytes, mojibake markers, umlauts and
euro sign, transliterations, schema (keys, slot enum, string types) and
the plan's length limits. One JSON line per run plus a summary line.

  python p09_writer.py --tag a --count 20 --out ../logs/g0-09-a.jsonl
  python p09_writer.py --rule writen --tag n --count 5 --out ../logs/g0-09-a2.jsonl

Needs MQTT_USERNAME / MQTT_PASSWORD (VPN default, MQTT localhost:1883).
"""
import argparse
import json
import os
import statistics
import sys
import time
import uuid

import paho.mqtt.client as mqtt

HERE = os.path.dirname(os.path.abspath(__file__))
MOJIBAKE = ("Ã", "Â", "â‚¬", "�", "\\u00")
UMLAUTS = set("äöüßÄÖÜ€")
TRANSLIT = ("Suess", "Roesti", "Muench", "Weissw", "Kuehl", "frueh", "Fruehst",
            "Stueck", "fuer ", "ueber", "guenstig", "EUR")
FIELDS = ("slot", "headline", "rationale", "why_line")
LIMITS = {"headline": 70, "rationale": 220, "why_line": 60}


def pct(vals, p):
    s = sorted(vals)
    k = (len(s) - 1) * p
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[f] + (s[c] - s[f]) * (k - f), 2)


def check(raw, wi):
    out = {"utf8_strict": True}
    try:
        txt = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        out["utf8_strict"] = False
        out["decode_error"] = str(e)
        txt = raw.decode("utf-8", "replace")
    try:
        body = json.loads(txt)
    except ValueError:
        return out | {"json": False, "raw": txt[:300]}
    out["json"] = True
    res = body.get("result", body) if isinstance(body, dict) else {}
    if isinstance(res, dict) and "slot" not in res:
        for v in res.values():
            if isinstance(v, dict) and "slot" in v:
                res = v
                break
    out["fields"] = {f: res.get(f) for f in FIELDS}
    out["seq"] = res.get("seq")
    ok = all(isinstance(res.get(f), str) and res.get(f) for f in FIELDS)
    ok = ok and res.get("slot") in ("A", "B", "none")
    out["schema_valid"] = bool(ok)
    out["limits_ok"] = {f: len(res.get(f) or "") <= n for f, n in LIMITS.items()}
    out["mojibake"] = {f: [m for m in MOJIBAKE if m in (res.get(f) or "")]
                       for f in FIELDS[1:]}
    out["umlauts"] = {f: "".join(sorted(UMLAUTS & set(res.get(f) or "")))
                      for f in FIELDS[1:]}
    out["translit"] = {f: [t for t in TRANSLIT if t in (res.get(f) or "")]
                       for f in FIELDS[1:]}
    name = wi["article"]
    alltext = " ".join(res.get(f) or "" for f in FIELDS[1:])
    out["article_exact"] = name in alltext or name.split(" ")[0] in alltext
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="a")
    ap.add_argument("--rule", default="write")
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--wait", type=float, default=60)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    inputs = json.load(open(os.path.join(HERE, "..", "data", "writer_inputs.json"),
                            encoding="utf-8"))
    box = []
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"gpos-p09-a-{uuid.uuid4().hex[:8]}")
    c.username_pw_set(os.environ["MQTT_USERNAME"], os.environ["MQTT_PASSWORD"])
    c.on_message = lambda _c, _u, m: box.append((time.time(), m.topic, bytes(m.payload)))
    c.connect("localhost", 1883, keepalive=30)
    c.subscribe("gpos/spike/p09/out/#", qos=1)
    c.loop_start()
    time.sleep(1.0)
    rows = []
    with open(a.out, "a", encoding="utf-8") as fo:
        for i in range(a.count):
            wi = inputs[i % len(inputs)]
            seq = f"p09-{a.tag}-{i + 1}-{uuid.uuid4().hex[:6]}"
            payload = json.dumps({"seq": seq, "writer_input": wi},
                                 ensure_ascii=False).encode("utf-8")
            t0 = time.time()
            c.publish(f"gpos/spike/p09/{a.rule}/{a.tag}", payload, qos=1).wait_for_publish(5)
            hit = None
            while time.time() - t0 < a.wait and hit is None:
                for t, topic, raw in list(box):
                    if seq.encode() in raw:
                        hit = (t, topic, raw)
                        break
                time.sleep(0.05)
            row = {"seq": seq, "input": i % len(inputs), "payload_bytes": len(payload),
                   "event_to_result_s": round(hit[0] - t0, 3) if hit else None,
                   "topic": hit[1] if hit else None}
            if hit:
                row |= check(hit[2], wi)
            rows.append(row)
            fo.write(json.dumps(row, ensure_ascii=False) + "\n")
            fo.flush()
            print(json.dumps(row, ensure_ascii=False), flush=True)
    c.loop_stop()
    c.disconnect()
    lat = [r["event_to_result_s"] for r in rows
           if r["event_to_result_s"] is not None and (r.get("topic") or "").endswith("/ok")]
    summ = {"summary": True, "runs": len(rows), "ok": len(lat),
            "p50_s": round(statistics.median(lat), 2) if lat else None,
            "p90_s": pct(lat, 0.9) if lat else None,
            "min_s": min(lat) if lat else None, "max_s": max(lat) if lat else None,
            "schema_valid": sum(1 for r in rows if r.get("schema_valid")),
            "utf8_strict": sum(1 for r in rows if r.get("utf8_strict")),
            "mojibake_runs": sum(1 for r in rows
                                 if any((r.get("mojibake") or {}).values())),
            "runs_with_umlaut_or_euro": sum(1 for r in rows
                                            if any((r.get("umlauts") or {}).values())),
            "translit_runs": sum(1 for r in rows
                                 if any((r.get("translit") or {}).values())),
            "limits_ok_all": sum(1 for r in rows
                                 if r.get("limits_ok") and all(r["limits_ok"].values())),
            "article_named": sum(1 for r in rows if r.get("article_exact"))}
    print(json.dumps(summ), flush=True)
    with open(a.out, "a", encoding="utf-8") as fo:
        fo.write(json.dumps(summ) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
