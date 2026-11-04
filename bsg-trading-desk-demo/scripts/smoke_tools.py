#!/usr/bin/env python3
"""Smoke test of the deterministic path WITHOUT SAM.

Drives bsg-tools over MCP exactly like an agent would and checks the
watcher's behaviour on the broker:

  1. watch_feed(alpha, dax-turbo, spread_pct > 0.5, hold 10 s)
  2. scenario wide_spread alpha 30 s -> exactly ONE alert within ~15 s
  3. enrich_alert(alert)  -> summary + attached data sets
  4. publish_desk_note    -> note on bsg/desk/notes/{watch_id}
  5. action plausibility_check -> issuer status in_review
  6. reset (scenario, watches, issuer status)

Usage (local or through kubectl port-forward):
  python scripts/smoke_tools.py --mcp http://127.0.0.1:8765/mcp \
      --mqtt-host 127.0.0.1 --mqtt-port 1883 --watcher http://127.0.0.1:8080
Exit code 0 = all checks passed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import time

import httpx
import paho.mqtt.client as mqtt
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def parse() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mcp", default="http://127.0.0.1:8765/mcp")
    ap.add_argument("--watcher", default="http://127.0.0.1:8080")
    ap.add_argument("--mqtt-host", default="127.0.0.1")
    ap.add_argument("--mqtt-port", type=int, default=1883)
    ap.add_argument("--mqtt-user", default="default")
    ap.add_argument("--mqtt-pass", default="")
    ap.add_argument("--observe-s", type=float, default=25,
                    help="seconds after the first alert to verify no second one")
    return ap.parse_args()


class Sniffer:
    def __init__(self, a: argparse.Namespace) -> None:
        self.msgs: list[tuple[float, str, dict]] = []
        self.lock = threading.Lock()
        self.c = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                             client_id="bsg-smoke")
        self.c.username_pw_set(a.mqtt_user, a.mqtt_pass)
        self.c.on_message = self._msg
        self.c.connect(a.mqtt_host, a.mqtt_port)
        for t in ("bsg/alerts/#", "bsg/desk/#", "bsg/watches/#"):
            self.c.subscribe(t)
        self.c.loop_start()

    def _msg(self, c, u, m):
        try:
            p = json.loads(m.payload)
        except ValueError:
            p = {}
        with self.lock:
            self.msgs.append((time.time(), m.topic, p))

    def find(self, prefix: str) -> list[tuple[float, str, dict]]:
        with self.lock:
            return [x for x in self.msgs if x[1].startswith(prefix)]

    def wait(self, prefix: str, timeout: float) -> tuple[float, str, dict] | None:
        end = time.time() + timeout
        while time.time() < end:
            hits = self.find(prefix)
            if hits:
                return hits[0]
            time.sleep(0.1)
        return None

    def publish(self, topic: str, payload: dict) -> None:
        self.c.publish(topic, json.dumps(payload), qos=1)


def text_of(res) -> str:
    return "".join(getattr(c, "text", "") for c in res.content if getattr(c, "type", "") == "text")


async def run(a: argparse.Namespace) -> int:
    fails: list[str] = []

    def check(ok: bool, msg: str) -> None:
        print(("PASS " if ok else "FAIL ") + msg)
        if not ok:
            fails.append(msg)

    sn = Sniffer(a)
    sn.publish("bsg/control/watch", {"cmd": "clear"})
    sn.publish("bsg/control/scenario", {"scenario": "reset"})
    time.sleep(1)
    async with streamable_http_client(a.mcp) as (read, write, *_):
        async with ClientSession(read, write) as s:
            await s.initialize()
            tools = sorted(t.name for t in (await s.list_tools()).tools)
            check({"watch_feed", "list_watches", "stop_watch", "enrich_alert",
                   "publish_desk_note"} <= set(tools), f"tools listed: {tools}")

            res = json.loads(text_of(await s.call_tool("watch_feed", {
                "issuer": "alpha", "product_class": "dax-turbo", "metric": "spread_pct",
                "op": ">", "threshold": 0.5, "hold_seconds": 10, "ttl_minutes": 30})))
            check(res.get("status") == "created", f"watch_feed -> {res.get('status')}")
            watch = res["watch"]
            wid = watch["watch_id"]
            check(watch["topic_filter"] == "bsg/quotes/alpha/dax-turbo/>",
                  f"topic filter {watch['topic_filter']}")

            t0 = time.time()
            sn.publish("bsg/control/scenario", {"scenario": "wide_spread", "issuer": "alpha",
                                                "duration_s": 30})
            hit = sn.wait(f"bsg/alerts/{wid}", 20)
            check(hit is not None, "alert received")
            if hit is None:
                return 1
            latency = hit[0] - t0
            check(latency <= 15, f"alert {latency:.1f} s after scenario start (<= 15 s)")
            alert = hit[2]
            t1 = time.time()
            res = await s.call_tool("enrich_alert", {"alert": json.dumps(alert)})
            summary = json.loads(text_of(res))
            res_blocks = [c for c in res.content if getattr(c, "type", "") == "resource"]
            check("datasets" in summary and summary["statistics"]["spread"]["alpha"]
                  ["mean_spread_pct_last_60s"] > 0.5,
                  f"enrich summary: alpha last-60s spread "
                  f"{summary['statistics']['spread']['alpha']['mean_spread_pct_last_60s']}")
            check(len(res_blocks) == 3, f"enrich attached {len(res_blocks)} data sets")
            check(len(text_of(res)) < 8000, f"summary stays small ({len(text_of(res))} chars)")
            check(sn.wait(f"bsg/desk/progress/{wid}", 3) is not None, "progress event published")
            print(f"     enrich took {time.time() - t1:.2f} s; "
                  f"quotes rows {summary['datasets'][f'bsg_quotes_{wid}.csv']['rows']}")

            note = "Alpha quotiert DAX-Turbos seit 10 s mit 0,8 % Spread.\nTest-Note."
            res = json.loads(text_of(await s.call_tool("publish_desk_note", {
                "watch_id": wid, "note": note, "branch": "issuer_specific", "issuer": "alpha",
                "alert_id": alert["alert_id"], "chart_ref": "smoke.png",
                "workflow_run_id": "smoke"})))
            check(res.get("status") == "published", "publish_desk_note")
            got = sn.wait(f"bsg/desk/notes/{wid}", 3)
            check(got is not None and got[2].get("branch") == "issuer_specific",
                  "note received on bsg/desk/notes/{watch_id}")

            remaining = a.observe_s - (time.time() - hit[0])
            print(f"     waiting {max(remaining, 0):.0f} s more to verify exactly one alert ...")
            time.sleep(max(remaining, 0))
            n = len(sn.find(f"bsg/alerts/{wid}"))
            check(n == 1, f"exactly one alert for the watch (got {n})")

    sn.publish("bsg/desk/actions", {"action": "plausibility_check", "issuer": "alpha",
                                    "by": "smoke"})
    time.sleep(1)
    st = {x["issuer"]: x["status"] for x in httpx.get(f"{a.watcher}/issuer-status").json()}
    check(st.get("alpha") == "in_review", f"issuer status alpha = {st.get('alpha')}")

    sn.publish("bsg/control/scenario", {"scenario": "reset"})
    sn.publish("bsg/control/watch", {"cmd": "clear"})
    sn.publish("bsg/desk/actions", {"action": "reset", "by": "smoke"})
    time.sleep(1)
    check(httpx.get(f"{a.watcher}/watches").json() == [], "reset cleared watches")
    print("RESULT:", "OK" if not fails else f"{len(fails)} failure(s)")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run(parse())))
