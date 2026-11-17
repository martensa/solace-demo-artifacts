"""G0-08a load generator: tool runs at a fixed rate in bursts.

  set -a; . bsg-trading-desk-demo/.env; set +a
  python load_gen.py --events <scratchpad>/g0-01/events.jsonl \
      --log logs/run.jsonl --rate 450 --burst 7 --duration 1800

Publishes over MQTT (localhost:1883, VPN default, QoS 1) to the topic of
each event (G0-01 stub workflow: gpos/spike/p01/pos/<Event>/<txId>) and
subscribes to the success and error output topics. Every N seconds
(N = burst * 3600 / rate, 56 s for 450/h with bursts of 7) it publishes
one burst of `burst` events back to back, so they run in parallel.

Sequence id: metadata.offset of every event is replaced by a unique
number (seq_base + i), the rest of the payload stays byte-identical.
The stub's reply carries event_key = purchaseTransactionId:offset, so
a reply is matched to its send by that number (error replies by a
search for it in the body). Run time = reply time - send time.

The log holds no payloads (GEBIT format stays out of the repo), only
send/receive times, sizes, the sequence id and selected reply fields.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import sys
import threading
import time
import uuid

import paho.mqtt.client as mqtt

OFFSET_RE = re.compile(r'"offset": "\d+"')


def canon_sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(p / 100.0 * len(s) + 0.5)) - 1))
    return s[k]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True, help="jsonl from g0-01 gen_events.py")
    ap.add_argument("--log", required=True)
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--rate", type=float, default=450.0, help="runs per hour")
    ap.add_argument("--burst", type=int, default=7, help="events per burst")
    ap.add_argument("--duration", type=float, default=1800.0, help="seconds")
    ap.add_argument("--bursts", type=int, default=0, help="fixed burst count (0 = from duration)")
    ap.add_argument("--timeout", type=float, default=60.0, help="reply timeout per event")
    ap.add_argument("--ok-topic", default="gpos/spike/p01/out/ok")
    ap.add_argument("--err-topic", default="gpos/spike/p01/out/err")
    ap.add_argument("--seq-base", type=int, default=0)
    ap.add_argument("--tag", default="g0-08a")
    a = ap.parse_args()

    events = [json.loads(line) for line in open(a.events, encoding="utf-8")]
    interval = a.burst * 3600.0 / a.rate
    n_bursts = a.bursts or int(a.duration // interval)
    seq_base = a.seq_base or (int(time.time()) % 100000) * 10000
    total = n_bursts * a.burst

    out = open(a.log, "a", encoding="utf-8")
    out_lock = threading.Lock()

    def log(kind: str, **kw) -> None:
        with out_lock:
            out.write(json.dumps({"t": round(time.time(), 4), "kind": kind, **kw},
                                 ensure_ascii=False) + "\n")
            out.flush()

    sent: dict[int, dict] = {}
    replies: dict[int, dict] = {}
    unmatched: list[dict] = []
    cond = threading.Condition()

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"gpos-spike-p08-load-{uuid.uuid4().hex[:6]}")
    c.username_pw_set(os.environ["MQTT_USERNAME"], os.environ["MQTT_PASSWORD"])

    def seq_of(body_text: str, data) -> int | None:
        key = data.get("event_key", "") if isinstance(data, dict) else ""
        if key and ":" in key:
            try:
                return int(key.rsplit(":", 1)[1]) - seq_base
            except ValueError:
                pass
        for m in re.finditer(r"\d{6,}", body_text):
            n = int(m.group(0)) - seq_base
            if n in sent:
                return n
        return None

    def on_message(_c, _u, msg):
        t = time.time()
        body = msg.payload.decode("utf-8", "replace")
        try:
            data = json.loads(body)
        except ValueError:
            data = {"_raw": body[:500]}
        seq = seq_of(body, data)
        is_err = msg.topic == a.err_topic
        rec = {"t": t, "topic": msg.topic, "err": is_err}
        if isinstance(data, dict):
            rec.update(run_id=data.get("run_id"), verdict=data.get("verdict"),
                       raw_sha256=data.get("raw_sha256"),
                       literal="{{" in body, bytes=len(msg.payload))
        if is_err:
            rec["error_body"] = body[:800]
        with cond:
            if seq is None or seq not in sent:
                unmatched.append({"t": t, "topic": msg.topic, "body": body[:800]})
                log("recv_unmatched", topic=msg.topic, body=body[:800])
            elif seq in replies:
                log("recv_dup", seq=seq, topic=msg.topic)
            else:
                replies[seq] = rec
                dur = t - sent[seq]["t"]
                log("recv", seq=seq, topic=msg.topic, dur_s=round(dur, 4),
                    **{k: v for k, v in rec.items() if k not in ("t", "topic")})
            cond.notify_all()

    def on_connect(_c, _u, _f, rc, _p=None):
        log("connect", rc=str(rc))

    def on_disconnect(_c, _u, _f, rc, _p=None):
        log("disconnect", rc=str(rc))

    c.on_message = on_message
    c.on_connect = on_connect
    c.on_disconnect = on_disconnect
    c.max_inflight_messages_set(50)
    c.connect(a.host, a.port, keepalive=30)
    c.subscribe([(a.ok_topic, 1), (a.err_topic, 1)])
    c.loop_start()
    time.sleep(1.5)

    log("start", tag=a.tag, rate=a.rate, burst=a.burst, interval_s=interval,
        bursts=n_bursts, total=total, seq_base=seq_base, events_file_rows=len(events))
    print(f"start {time.strftime('%H:%M:%S')} rate {a.rate}/h burst {a.burst} "
          f"interval {interval:.1f}s bursts {n_bursts} total {total} seq_base {seq_base}",
          flush=True)
    t_start = time.time()
    i = 0
    for b in range(n_bursts):
        target = t_start + b * interval
        while (now := time.time()) < target:
            time.sleep(min(0.5, target - now))
        infos = []
        for j in range(a.burst):
            e = events[i % len(events)]
            seq = i
            off = str(seq_base + seq)
            payload, n = OFFSET_RE.subn(f'"offset": "{off}"', e["payload"], count=1)
            obj = json.loads(payload)
            assert n == 1 and obj["metadata"]["offset"] == off, e["seq"]
            body = payload.encode("utf-8")
            sha = canon_sha(obj)
            with cond:
                t0 = time.time()
                sent[seq] = {"t": t0, "src": e["seq"], "event": e["event"],
                             "sha": sha, "burst": b}
            info = c.publish(e["topic"], body, qos=1)
            infos.append((seq, info))
            log("sent", seq=seq, burst=b, idx=j, src=e["seq"], event=e["event"],
                offset=off, bytes=len(body), rc=info.rc)
            i += 1
        for seq, info in infos:
            try:
                info.wait_for_publish(10)
                ok = info.is_published()
            except (RuntimeError, ValueError) as exc:
                ok = False
                log("puback_error", seq=seq, error=str(exc))
            if not ok:
                log("puback_missing", seq=seq)
        with cond:
            done = sum(1 for s in sent if s in replies)
        print(f"{time.strftime('%H:%M:%S')} burst {b + 1}/{n_bursts} sent {len(sent)} "
              f"replies {done} err {sum(1 for r in replies.values() if r['err'])}",
              flush=True)

    deadline = time.time() + a.timeout
    with cond:
        cond.wait_for(lambda: all(s in replies for s in sent),
                      timeout=max(0.0, deadline - time.time()))
    time.sleep(2.0)
    c.loop_stop()
    c.disconnect()

    durs, errs, missing, sha_bad, literal = [], [], [], [], []
    burst_durs: dict[int, list[float]] = {}
    for seq, s in sorted(sent.items()):
        r = replies.get(seq)
        if not r:
            missing.append(seq)
            log("summary", seq=seq, reply=False)
            continue
        dur = r["t"] - s["t"]
        if r["err"]:
            errs.append(seq)
        else:
            durs.append(dur)
            burst_durs.setdefault(s["burst"], []).append(dur)
        if not r["err"] and r.get("raw_sha256") != s["sha"]:
            sha_bad.append(seq)
        if r.get("literal"):
            literal.append(seq)
        log("summary", seq=seq, reply=True, err=r["err"], dur_s=round(dur, 4),
            src=s["src"], event=s["event"], verdict=r.get("verdict"),
            sha_equal=r.get("raw_sha256") == s["sha"], run_id=r.get("run_id"))
    res = {
        "sent": len(sent), "ok": len(durs), "err": len(errs), "missing": len(missing),
        "unmatched": len(unmatched), "sha_mismatch": len(sha_bad), "literal": len(literal),
        "p50": pct(durs, 50), "p95": pct(durs, 95), "p99": pct(durs, 99),
        "max": max(durs) if durs else float("nan"), "min": min(durs) if durs else float("nan"),
        "mean": statistics.fmean(durs) if durs else float("nan"),
        "wall_s": time.time() - t_start, "err_seqs": errs, "missing_seqs": missing,
        "burst_max_p50": statistics.median([max(v) for v in burst_durs.values()])
        if burst_durs else float("nan"),
    }
    log("result", **res)
    print(json.dumps(res, indent=1), flush=True)
    return 0 if not (errs or missing) else 1


if __name__ == "__main__":
    sys.exit(main())
